"""CLI tests for scripts/hapax-platform-capability-freshness."""

from __future__ import annotations

import json
import math
import runpy
import subprocess
from collections.abc import Callable
from configparser import ConfigParser
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.capability_availability_guarantor import (
    RefreshStrategyRegistry,
    evaluate_route_availability,
)
from shared.platform_capability_receipts import (
    CliEvidence,
    EvidenceStatus,
    PlatformCapabilityReceipt,
    ProviderDocsEvidence,
    SurfaceEvidence,
    WrapperEvidence,
    load_platform_capability_receipt,
    parse_duration_spec,
)
from shared.platform_capability_registry import (
    _route_specific_quota_admission_fresh,
    check_registry_freshness,
    check_route_freshness,
    load_platform_capability_registry,
)
from shared.quota_spend_ledger import (
    QuotaSpendLedger,
    SubscriptionQuotaState,
    subscription_quota_state_for_route,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-platform-capability-freshness"
FRESH_NOW = "2026-05-09T21:00:00Z"
INERT_RECEIPT_DIR = REPO_ROOT / ".pytest-nonexistent-platform-receipts"

# Operational slack beyond the configured attempt budget; successful renewal is not
# guaranteed by a timer (failed/coalesced attempts can leave unbounded gaps).
MARGIN_S = 60
REVIEW_ROUTES = ("agy.review.direct", "glmcp.review.direct")


@dataclass(frozen=True)
class ProducerMeasurement:
    route_id: str
    declared_window_s: int
    producer: str | None
    terms: dict[str, int]

    @property
    def producer_envelope_s(self) -> float:
        # Absence has no finite renewal bound; it is never a zero-second producer.
        return sum(self.terms.values()) if self.producer else math.inf

    @property
    def margin_s(self) -> float:
        return self.declared_window_s - self.producer_envelope_s


def _unit_section(name: str, section: str) -> dict[str, str]:
    unit = ConfigParser(interpolation=None, strict=False)
    unit.optionxform = str
    unit.read_string((REPO_ROOT / "systemd/units" / name).read_text())
    return dict(unit[section])


def _unit_seconds(section: dict[str, str], key: str, default: str | None = None) -> int:
    value = section[key] if default is None else section.get(key, default)
    # Unknown duration syntax fails in fixture setup, outside the expected failure.
    if value.isdecimal():
        return int(value)
    return int(parse_duration_spec(value.replace("min", "m")).total_seconds())


def _timer_envelope(timer: dict[str, str], service: dict[str, str]) -> dict[str, int]:
    interval = "OnUnitActiveSec" if "OnUnitActiveSec" in timer else "OnUnitInactiveSec"
    return {
        "poll": _unit_seconds(timer, interval),
        "random_delay": _unit_seconds(timer, "RandomizedDelaySec", "0"),
        "accuracy": _unit_seconds(timer, "AccuracySec", "1min"),
        "service_timeout": _unit_seconds(service, "TimeoutStartSec"),
    }


@pytest.fixture
def admission_producer_measurements() -> dict[str, ProducerMeasurement]:
    routes = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())[
        "routes"
    ]
    producers = json.loads((REPO_ROOT / "config/determination-producers.json").read_text())[
        "producers"
    ]
    scheduled = []
    for path in sorted((REPO_ROOT / "systemd/units").glob("*.timer")):
        timer = _unit_section(path.name, "Timer")
        target = timer.get("Unit", path.with_suffix(".service").name)
        if (path.parent / target).is_file():
            scheduled.append((path.name, timer, _unit_section(target, "Service")))

    measurements = {}
    for route_id in REVIEW_ROUTES:
        route = next(route for route in routes if route["route_id"] == route_id)
        window = int(parse_duration_spec(route["freshness"]["quota_stale_after"]).total_seconds())
        candidates = []
        platform = route["platform"]
        for name, timer, service in scheduled:
            commands = " ".join(
                value for key, value in service.items() if key.startswith("ExecStart")
            )
            if "scripts/hapax-determine --json" in commands:
                for producer in producers:
                    if route_id in producer["subjects"]:
                        if f"scripts/hapax-{platform}-quota-admission" not in producer["command"]:
                            raise ValueError(f"unrecognized admission producer: {producer}")
                        terms = _timer_envelope(timer, service)
                        # is_due charges cadence since ran_at, including failed runs; a
                        # threshold crossing can miss a poll. Charge the whole serial service.
                        terms["cadence"] = producer["cadence_seconds"]
                        candidates.append(ProducerMeasurement(route_id, window, name, terms))
            elif any(
                command in commands
                for command in (
                    f"hapax-{platform}-quota-admission",
                    f"hapax-{platform}-seat-refresh",
                )
            ):
                candidates.append(
                    ProducerMeasurement(route_id, window, name, _timer_envelope(timer, service))
                )
        measurements[route_id] = (
            min(candidates, key=lambda item: item.producer_envelope_s)
            if candidates
            else ProducerMeasurement(route_id, window, None, {})
        )
    return measurements


def test_review_admission_producer_characterization(
    admission_producer_measurements: dict[str, ProducerMeasurement],
) -> None:
    assert set(admission_producer_measurements) == set(REVIEW_ROUTES)
    for route_id, measured in admission_producer_measurements.items():
        dominant = max(measured.terms, key=measured.terms.get) if measured.terms else "none"
        print(
            f"{route_id}: window={measured.declared_window_s}s; producer={measured.producer}; "
            f"terms={measured.terms}; envelope={measured.producer_envelope_s}s; "
            f"margin={measured.margin_s}s; required_margin>{MARGIN_S}s; dominant={dominant}"
        )
        # Relations survive a repair; no assertion requires a negative margin or absence.
        assert all(term >= 0 for term in measured.terms.values())
        assert all(measured.producer_envelope_s >= term for term in measured.terms.values())
        assert (measured.margin_s > 0) == (
            measured.declared_window_s > measured.producer_envelope_s
        )
    dispatcher = _timer_envelope(
        _unit_section("hapax-pr-review-dispatch.timer", "Timer"),
        _unit_section("hapax-pr-review-dispatch.service", "Service"),
    )
    print(
        f"review dispatcher: terms={dispatcher}; envelope={sum(dispatcher.values())}s (not an admission producer)"
    )


@pytest.mark.parametrize(
    "route_id",
    [
        pytest.param(
            "agy.review.direct",
            marks=pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="agy window 900s - envelope 2130s = -1230s; owner: agy cadence follow-on to quota-observation-cadence-margin-20260905",
            ),
        ),
        pytest.param(
            "glmcp.review.direct",
            marks=pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="glmcp window 900s; scheduled admission producer absent at 58ab8558d; owner: #4624 glm producer repair",
            ),
        ),
    ],
)
def test_review_admission_declared_window_exceeds_producer_envelope_with_margin(
    route_id: str, admission_producer_measurements: dict[str, ProducerMeasurement]
) -> None:
    measured = admission_producer_measurements[route_id]
    declared_window_s = measured.declared_window_s
    producer_envelope_s = measured.producer_envelope_s
    # Only the positive-margin invariant is expected to fail. A repair is strict XPASS.
    assert declared_window_s > producer_envelope_s + MARGIN_S, measured


@pytest.mark.parametrize("platform", ["agy", "glmcp"])
@pytest.mark.parametrize(
    ("observation", "offset_seconds", "expected_state", "reason"),
    [
        ("present", -1, SubscriptionQuotaState.FRESH, None),
        ("present", 0, SubscriptionQuotaState.STALE, "fresh_until_expired"),
        ("present", 1, SubscriptionQuotaState.STALE, "fresh_until_expired"),
        ("missing_expiry", 1, SubscriptionQuotaState.UNKNOWN, "fresh_until_missing"),
        ("missing_snapshot", 1, SubscriptionQuotaState.UNKNOWN, "missing"),
    ],
)
def test_review_admission_consumer_expiry_boundaries(
    platform: str,
    observation: str,
    offset_seconds: int,
    expected_state: SubscriptionQuotaState,
    reason: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed = datetime(2026, 9, 5, 18, 0, 25, tzinfo=UTC)
    expires = observed + timedelta(minutes=15)
    checked_at = expires + timedelta(seconds=offset_seconds)
    route_id = f"{platform}.review.direct"
    provider = "google-antigravity-cli-agy" if platform == "agy" else "z_ai-glm-coding-plan"
    model = "gemini-3.1-pro-high" if platform == "agy" else "glm-5.2"
    endpoint = "endpoint:https://api.z.ai/api/coding/paas/v4:" if platform == "glmcp" else ""
    evidence_ref = (
        f"relay-receipt:{platform}-quota-admission.yaml:witness:reviewer-smoke-witness:"
        f"supported_tool:hapax-{platform}-reviewer:{endpoint}model:{model}:"
        "observed_at:2026-09-05T18:00:25Z:fresh_until:2026-09-05T18:15:25Z"
    )
    payload = json.loads((REPO_ROOT / "config/quota-spend-ledger-fixtures.json").read_text())
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    snapshot = {
        "quota_snapshot_schema": 1,
        "snapshot_id": f"quota-{platform}-cadence",
        "captured_at": expires - timedelta(seconds=1),
        "fresh_until": None if observation == "missing_expiry" else expires,
        "route_id": route_id,
        "provider": provider,
        "capacity_pool": "subscription_quota",
        "subscription_quota_state": "fresh",
        "evidence_refs": [evidence_ref],
        "operator_visible_reason": "Synthetic sanctioned admission; original expiry retained",
    }
    payload["quota_snapshots"] = [] if observation == "missing_snapshot" else [snapshot]
    # Consumer-only boundary cases; publication is exercised separately below.
    payload["captured_at"] = checked_at
    ledger = QuotaSpendLedger.model_validate(payload)
    state, refs = subscription_quota_state_for_route(ledger, route_id, now=checked_at)
    assert state is expected_state
    if reason == "missing":
        assert refs == (f"quota-snapshot:{route_id}:missing",)
    elif reason is not None:
        suffix = ":2026-09-05T18:15:25Z" if reason == "fresh_until_expired" else ""
        assert f"quota-snapshot:quota-{platform}-cadence:{reason}{suffix}" in refs
    else:
        assert refs == (evidence_ref,)

    live_path = tmp_path / "quota-ledger.json"
    live_path.write_text(ledger.model_dump_json())
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(live_path))
    admitted, admission_refs = _route_specific_quota_admission_fresh(
        {"route_id": route_id}, now=checked_at
    )
    assert admitted is (expected_state is SubscriptionQuotaState.FRESH)
    assert admission_refs == refs
    if observation == "present":
        assert ledger.quota_snapshots[0].fresh_until == expires


def _write_review_admission(
    relay: Path, platform: str, *, observed_at: datetime, failed: bool = False
) -> None:
    # Raw observation only: the fixture never supplies a derived fresh_until.
    fields = {
        "schema": f"hapax.{platform}_quota_admission.v1",
        "status": "failed" if failed else "quota_available",
        "provider": "google-antigravity-cli-agy" if platform == "agy" else "z_ai-glm-coding-plan",
        "capacity_pool": "subscription_quota",
        "route_id": f"{platform}.review.direct",
        "supported_tool": f"hapax-{platform}-reviewer",
        "model": "gemini-3.1-pro-high" if platform == "agy" else "glm-5.2",
        "observed_at": observed_at.isoformat(),
        "stale_after_seconds": 900,
        "evidence_ref": "reviewer-smoke-witness",
        "secret_value_persisted": "false",  # pragma: allowlist secret (field name, no value)
        "prompt_or_output_persisted": "false",
    }
    if platform == "agy":
        fields.update(
            secret_source="agy:operator-session",  # pragma: allowlist secret (locator, no value)
            billing_mode="operator_session_subscription",
            smoke_command="scripts/hapax-agy-reviewer",
            smoke_returncode=1 if failed else 0,
            smoke_stdout_validated="false" if failed else "true",
            positive_admission="false" if failed else "true",
        )
    else:
        fields.update(
            secret_source="pass:glmcp/api-key",  # pragma: allowlist secret (locator, no value)
            billing_mode="coding_plan_subscription",
            endpoint="https://api.z.ai/api/coding/paas/v4",
            payg_fallback="false",
        )
    (relay / f"{platform}-quota-admission.yaml").write_text(
        "\n".join(f"{key}: {value}" for key, value in fields.items()) + "\n"
    )


@pytest.fixture
def review_publication(
    platform: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    Path, Path, Path, Callable[[datetime], tuple[QuotaSpendLedger, list[PlatformCapabilityReceipt]]]
]:
    relay = tmp_path / "relay"
    relay.mkdir()
    receipts = tmp_path / "capability-receipts"
    live = tmp_path / "ledger.json"
    monkeypatch.setenv("HAPAX_RELAY_RECEIPT_DIR", str(relay))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", str(receipts))
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(live))
    # No account, resource, credential, provider, or SSH probes. The publication and
    # observation-loading functions themselves execute unchanged against tmp_path.
    writer = runpy.run_path(str(REPO_ROOT / "scripts/hapax-quota-telemetry-writer"))[
        "main"
    ].__globals__
    publisher = runpy.run_path(str(REPO_ROOT / "scripts/hapax-platform-capability-receipts"))[
        "main"
    ].__globals__
    monkeypatch.setitem(publisher, "QUOTA_RECEIPT_DIR", relay)
    monkeypatch.setitem(publisher, "QUOTA_LEDGER_LIVE", live)
    monkeypatch.setitem(publisher, "CONFIG_REFS_BY_PLATFORM", {platform: []})
    monkeypatch.setitem(
        publisher,
        "observe_cli",
        lambda platform, **kwargs: CliEvidence(binary=platform, available=True, version="test"),
    )
    monkeypatch.setitem(
        writer, "probe_local_resource_state", lambda **kwargs: ("green", ["test:resource"])
    )
    publications = []
    clock = {}

    def publish(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        # Replace only process transport: the writer's refresh function and both
        # real CLI main functions still run. Reject any unexpected external call.
        assert Path(argv[1]) == REPO_ROOT / "scripts/hapax-platform-capability-receipts"
        args = [arg for arg in argv[2:] if arg not in {"--all", "--codex-exec-auth-probe"}]
        result = publisher["main"]([*args, "--platform", platform, "--now", clock["now"], "--json"])
        publications.append(load_platform_capability_receipt(receipts / f"{platform}.json"))
        return subprocess.CompletedProcess(argv, result, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", publish)

    def tick(now: datetime) -> tuple[QuotaSpendLedger, list[PlatformCapabilityReceipt]]:
        clock["now"] = now.isoformat()
        publications.clear()
        assert (
            writer["main"](
                [
                    "--now",
                    clock["now"],
                    "--out",
                    str(live),
                    "--relay-receipt-dir",
                    str(relay),
                    "--platform-capability-receipt-dir",
                    str(receipts),
                    "--json",
                ]
            )
            == 0
        )
        # On this head the writer refreshes receipts BEFORE rebuilding its ledger.
        # Publish once more to consume that new ledger, including on the first tick.
        publish(
            [
                "python",
                str(REPO_ROOT / "scripts/hapax-platform-capability-receipts"),
                "--receipt-dir",
                str(receipts),
            ]
        )
        ledger = QuotaSpendLedger.model_validate_json(live.read_text())
        return ledger, list(publications)

    return relay, receipts, live, tick


@pytest.mark.parametrize("platform", ["agy", "glmcp"])
def test_review_admission_expiry_survives_real_publication(
    platform: str, review_publication: tuple, capsys: pytest.CaptureFixture[str]
) -> None:
    relay, _receipts, _live, tick = review_publication
    observed = datetime.fromisoformat(FRESH_NOW)
    original_expiry = observed + timedelta(seconds=900)
    _write_review_admission(relay, platform, observed_at=observed)
    measurements = []
    for offset in (0, 450, 899):
        now = observed + timedelta(seconds=offset)
        ledger, publications = tick(now)
        snapshot = next(
            s for s in ledger.quota_snapshots if s.route_id == f"{platform}.review.direct"
        )
        assert snapshot.captured_at == now
        assert snapshot.fresh_until == original_expiry
        assert (
            subscription_quota_state_for_route(ledger, snapshot.route_id, now=now)[0]
            is SubscriptionQuotaState.FRESH
        )
        assert publications[-1].quota.status is EvidenceStatus.OBSERVED
        for receipt in publications:
            # The very first refresh sees no ledger yet; subsequent publications
            # must all be observed and bounded by the same original admission.
            if offset == 0 and receipt.quota.status is EvidenceStatus.UNOBSERVABLE:
                assert receipt.quota.reason_codes == ["quota_telemetry_unknown"]
                continue
            assert receipt.quota.status is EvidenceStatus.OBSERVED
            assert receipt.observed_at == now
            remaining = parse_duration_spec(receipt.quota.stale_after)
            assert receipt.observed_at + remaining == original_expiry
            assert remaining.total_seconds() == 900 - offset
        capsys.readouterr()
        measurements.append(
            f"{platform}: t=+{offset}s; fresh_until={snapshot.fresh_until.isoformat()}; published_remaining={publications[-1].quota.stale_after}"
        )

    print("\n".join(measurements))


@pytest.mark.parametrize("platform", ["agy", "glmcp"])
@pytest.mark.parametrize("observation", ["absent", "failed"])
def test_registry_quota_observation_absent_or_failed_is_not_fresh(
    platform: str, observation: str, review_publication: tuple, tmp_path: Path
) -> None:
    relay, receipts, _live, tick = review_publication
    now = datetime.fromisoformat(FRESH_NOW)
    route_id = f"{platform}.review.direct"
    payload = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())
    route = next(route for route in payload["routes"] if route["route_id"] == route_id)
    _mark_fresh(route)
    route["telemetry"]["quota_source"] = "ledger"
    registry_path = _write_registry(tmp_path, payload)
    if observation == "failed":
        _write_review_admission(relay, platform, observed_at=now, failed=True)
    ledger, publications = tick(now)
    assert (
        subscription_quota_state_for_route(ledger, route_id, now=now)[0]
        is SubscriptionQuotaState.UNKNOWN
    )
    assert all(receipt.quota.status is EvidenceStatus.UNOBSERVABLE for receipt in publications)

    registry = load_platform_capability_registry(registry_path, receipt_dir=receipts, now=now)
    result = check_registry_freshness(registry, route_ids=[route_id], now=now)
    assert result.ok is False
    missing_reason = (
        "route_specific_quota_receipt_absent"
        if platform == "agy"
        else "glmcp_review_seat_receipt_admission_required"
    )
    assert f"{route_id}: quota blocked: {missing_reason}" in result.routes[0].errors


@pytest.mark.parametrize("route_id", REVIEW_ROUTES)
def test_checker_detects_quota_timestamp_loss_after_registry_loading(
    route_id: str, tmp_path: Path
) -> None:
    payload = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())
    route = next(route for route in payload["routes"] if route["route_id"] == route_id)
    _mark_fresh(route)
    route["telemetry"]["quota_source"] = "ledger"
    now = datetime.fromisoformat(FRESH_NOW)
    registry = load_platform_capability_registry(
        _write_registry(tmp_path, payload), receipt_dir=tmp_path / "no-receipts", now=now
    )
    assert check_registry_freshness(registry, route_ids=[route_id], now=now).ok is True
    loaded_route = next(route for route in registry.routes if route.route_id == route_id)
    # The schema disallows a null timestamp without reasons. Exercise the checker's
    # defensive branch by losing ONLY the timestamp after a successful real load;
    # do not insert a verdict or blocker that would independently keep it red.
    loaded_route.freshness.quota_checked_at = None
    result = check_route_freshness(loaded_route, now=now)
    assert result.ok is False
    assert result.errors == (f"{route_id}: quota freshness is unknown",)


@pytest.mark.parametrize("route_id", REVIEW_ROUTES)
def test_registry_quota_observation_expired_is_not_fresh(route_id: str, tmp_path: Path) -> None:
    payload = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())
    route = next(route for route in payload["routes"] if route["route_id"] == route_id)
    _mark_fresh(route)
    route["telemetry"]["quota_source"] = "ledger"
    route["freshness"]["quota_checked_at"] = "2026-05-09T20:44:59Z"
    now = datetime.fromisoformat(FRESH_NOW)
    registry = load_platform_capability_registry(
        _write_registry(tmp_path, payload), receipt_dir=tmp_path / "no-receipts", now=now
    )
    result = check_registry_freshness(registry, route_ids=[route_id], now=now)
    assert result.ok is False
    assert result.routes[0].errors == (
        f"{route_id}: quota stale; checked_at=2026-05-09T20:44:59+00:00 stale_after=15m",
    )


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    receipt_args = () if "--receipt-dir" in args else ("--receipt-dir", str(INERT_RECEIPT_DIR))
    return subprocess.run(
        [str(SCRIPT), *receipt_args, *args],
        text=True,
        capture_output=True,
        check=False,
    )


def _write_registry(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "platform-capability-registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_codex_receipt(receipt_dir: Path, *, observed_at: datetime) -> Path:
    receipt = PlatformCapabilityReceipt(
        receipt_id="test-codex-receipt",
        platform="codex",
        routes=["codex.headless.full", "codex.headless.spark"],
        observed_at=observed_at,
        stale_after="24h",
        cli=CliEvidence(binary="codex", available=True, version="codex-cli test"),
        wrapper=WrapperEvidence(
            path="scripts/hapax-codex",
            exists=True,
            executable=True,
            sha256="abc123",
        ),
        capability=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=[
                "test:codex:capability",
                "host:hapax-appendix:codex:exec:auth:saved-login:observed",
            ],
        ),
        resource=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=observed_at,
            stale_after="24h",
            evidence_refs=[
                "test:codex:resource",
                "local:current-codex-session:filesystem-shell-browser-usable:test",
            ],
        ),
        quota=SurfaceEvidence(
            status=EvidenceStatus.UNOBSERVABLE,
            source="test",
            observed_at=observed_at,
            stale_after="15m",
            evidence_refs=["local:codex:quota-probe:unobservable"],
            reason_codes=["account_live_quota_receipt_absent"],
        ),
        provider_docs=ProviderDocsEvidence(
            refs=["test:codex:provider-docs"],
            fetched_at=observed_at,
            stale_after="30d",
        ),
    )
    receipt_dir.mkdir(parents=True)
    path = receipt_dir / "codex.json"
    path.write_text(json.dumps(receipt.model_dump(mode="json")), encoding="utf-8")
    return path


def _mark_fresh(route: dict) -> None:
    route["route_state"] = "active"
    route["blocked_reasons"] = []
    route["freshness"]["capability_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["quota_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["resource_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["provider_docs_checked_at"] = "2026-05-09T20:55:00Z"
    route["freshness"]["evidence"] = {
        "capability": {
            "evidence_refs": ["test:fresh-capability"],
            "blocked_reasons": [],
        },
        "quota": {
            "evidence_refs": ["test:fresh-quota"],
            "blocked_reasons": [],
        },
        "resource": {
            "evidence_refs": ["test:fresh-resource"],
            "blocked_reasons": [],
        },
        "provider_docs": {
            "evidence_refs": ["test:fresh-provider-docs"],
            "blocked_reasons": [],
        },
    }
    for score in route["capability_scores"].values():
        score["observed_at"] = "2026-05-09T20:55:00Z"
    for tool in route["tool_state"]:
        tool["observed_at"] = "2026-05-09T20:55:00Z"


def test_json_reports_blocked_seed_registry_nonzero(tmp_path: Path) -> None:
    result = _run(
        "--json",
        "--now",
        "2026-05-17T08:14:00Z",
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["route_count"] == len(load_platform_capability_registry().routes)
    assert payload["routes"][0]["route_id"] == "codex.headless.full"
    errors = "\n".join(payload["routes"][0]["errors"])
    assert "quota blocked: account_live_quota_receipt_absent" in errors
    assert "freshness is unknown" not in errors
    assert "account_live_quota_receipt_absent" in payload["routes"][0]["blocked_reasons"]
    assert payload["routes"][0]["evidence_refs"]


def test_json_fails_nonzero_for_unsupported_route(tmp_path: Path) -> None:
    result = _run(
        "--json",
        "--now",
        FRESH_NOW,
        "--route",
        "codex/headless/nope",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["routes"][0]["supported"] is False
    assert payload["routes"][0]["errors"] == ["unsupported route: codex.headless.nope"]


def test_json_fails_structured_for_malformed_now(tmp_path: Path) -> None:
    result = _run(
        "--json",
        "--now",
        "definitely-not-a-date",
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 2
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "Invalid isoformat string" in payload["error"]
    assert "next action" in payload["error"]


def test_plain_text_fails_structured_for_malformed_now(tmp_path: Path) -> None:
    result = _run(
        "--now",
        "definitely-not-a-date",
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("ERROR: ")
    assert "Invalid isoformat string" in result.stderr
    assert "next action" in result.stderr


def test_json_succeeds_for_fresh_route_fixture(tmp_path: Path) -> None:
    payload = load_platform_capability_registry().model_dump(mode="json")
    route = next(route for route in payload["routes"] if route["route_id"] == "codex.headless.full")
    _mark_fresh(route)
    path = _write_registry(tmp_path, payload)

    result = _run(
        "--registry",
        str(path),
        "--json",
        "--now",
        FRESH_NOW,
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["routes"][0]["errors"] == []
    assert payload["non_supply_observation_errors"] == []


def test_route_freshness_fails_local_on_unrelated_observation_metadata(
    tmp_path: Path,
) -> None:
    payload = load_platform_capability_registry().model_dump(mode="json")
    route = next(route for route in payload["routes"] if route["route_id"] == "codex.headless.full")
    _mark_fresh(route)
    target = next(
        row
        for row in payload["omitted_capability_shapes"]
        if row["shape_id"] == "local_compute.agentic_trust_evaluator_surface"
    )
    target["summary"] = []
    path = _write_registry(tmp_path, payload)

    result = _run(
        "--registry",
        str(path),
        "--json",
        "--now",
        FRESH_NOW,
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 0, result.stdout
    observed = json.loads(result.stdout)
    assert observed["ok"] is True
    assert observed["routes"][0]["errors"] == []
    assert len(observed["non_supply_observation_errors"]) == 1
    assert "agentic_trust_evaluator_surface" in observed["non_supply_observation_errors"][0]


def test_json_applies_receipt_overlay_and_current_codex_session_availability(
    tmp_path: Path,
) -> None:
    receipt_dir = tmp_path / "receipts"
    _write_codex_receipt(
        receipt_dir,
        observed_at=datetime(2026, 5, 9, 20, 55, tzinfo=UTC),
    )

    result = _run(
        "--json",
        "--now",
        FRESH_NOW,
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(receipt_dir),
    )

    assert result.returncode == 0, result.stdout
    payload = json.loads(result.stdout)
    route = payload["routes"][0]
    assert payload["ok"] is True
    assert route["blocked_reasons"] == []
    assert "platform-capability-receipt:codex:test-codex-receipt" in route["evidence_refs"]

    checked_at = datetime(2026, 5, 9, 21, 0, tzinfo=UTC)
    registry = load_platform_capability_registry(receipt_dir=receipt_dir, now=checked_at)
    registry_route = registry.require("codex.headless.full")
    freshness_check = check_registry_freshness(
        registry,
        route_ids=["codex.headless.full"],
        now=checked_at,
    ).routes[0]
    availability = evaluate_route_availability(
        registry_route,
        freshness_check,
        refresh_strategies=RefreshStrategyRegistry(()),
        now=checked_at,
    )

    assert availability.available is True
    assert availability.reason_codes == ()


def test_json_fails_nonzero_for_stale_provider_docs(tmp_path: Path) -> None:
    payload = load_platform_capability_registry().model_dump(mode="json")
    route = next(route for route in payload["routes"] if route["route_id"] == "codex.headless.full")
    _mark_fresh(route)
    route["freshness"]["provider_docs_checked_at"] = "2026-03-01T00:00:00Z"
    path = _write_registry(tmp_path, payload)

    result = _run(
        "--registry",
        str(path),
        "--json",
        "--now",
        FRESH_NOW,
        "--route",
        "codex.headless.full",
        "--receipt-dir",
        str(tmp_path / "empty-receipts"),
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "provider_docs stale" in payload["routes"][0]["errors"][0]
