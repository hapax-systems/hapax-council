"""CLI tests for scripts/hapax-platform-capability-freshness."""

from __future__ import annotations

import json
import subprocess
from configparser import ConfigParser
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
    parse_duration_spec,
)
from shared.platform_capability_registry import (
    PlatformCapabilityRegistry,
    _route_specific_quota_admission_fresh,
    check_registry_freshness,
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

# Measured at 9f4cd4518. These are deficits, not exemptions granting fresh supply.
# Replace each with a positive margin gate when its producer repair is admitted.
ADMISSION_PRODUCER_DEFICITS = {
    "agy": "scheduled hapax-determine; window 900s; attempt envelope 2130s; margin -1230s",
    "glmcp": "no scheduled admission producer; window 900s; dispatcher envelope 2505s",
}


def _unit_section(name: str, section: str) -> dict[str, str]:
    unit = ConfigParser(interpolation=None, strict=False)
    unit.optionxform = str
    unit.read_string((REPO_ROOT / "systemd/units" / name).read_text())
    return dict(unit[section])


def _unit_seconds(section: dict[str, str], key: str, default: str | None = None) -> int:
    value = section[key] if default is None else section.get(key, default)
    # These committed units use integer seconds, s, or min; unknown syntax fails closed.
    if value.isdecimal():
        return int(value)
    return int(parse_duration_spec(value.replace("min", "m")).total_seconds())


def _admission_producer_measurements() -> dict[str, str]:
    routes = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())[
        "routes"
    ]
    windows = {
        route["platform"]: int(
            parse_duration_spec(route["freshness"]["quota_stale_after"]).total_seconds()
        )
        for route in routes
        if route["route_id"] in {"agy.review.direct", "glmcp.review.direct"}
    }
    producers = json.loads((REPO_ROOT / "config/determination-producers.json").read_text())[
        "producers"
    ]
    agy_producers = [p for p in producers if "agy.review.direct" in p["subjects"]]
    assert len(agy_producers) == 1
    agy = agy_producers[0]
    assert agy["command"] == ["scripts/hapax-agy-quota-admission", "--json"]
    assert agy["evidence_ttl_seconds"] == windows["agy"]
    timer = _unit_section("hapax-determine.timer", "Timer")
    service = _unit_section("hapax-determine.service", "Service")
    assert "scripts/hapax-determine --json" in service["ExecStart"]
    # is_due uses ran_at, including failed runs. A threshold crossing can miss one poll.
    # Charge the whole serial service, not just agy's 240s smoke or its 300s runner timeout.
    poll = _unit_seconds(timer, "OnUnitActiveSec")
    runtime = _unit_seconds(service, "TimeoutStartSec")
    attempt_envelope = (
        agy["cadence_seconds"]
        + poll
        + _unit_seconds(timer, "RandomizedDelaySec", "0")
        + _unit_seconds(timer, "AccuracySec")
        + runtime
    )
    # This head can overrun an active-relative poll. The sum is a configured attempt budget,
    # not a guarantee of successful renewals: coalescing/failure can leave unbounded gaps.
    assert runtime > poll
    assert attempt_envelope + 60 >= windows["agy"], (
        "Replace the repaired deficit with a margin gate"
    )

    assert not any("glmcp.review.direct" in p["subjects"] for p in producers)
    assert not (REPO_ROOT / "scripts/hapax-glmcp-seat-refresh").exists()
    # Also catch a newly installed direct admission timer, regardless of the unit name.
    for path in (REPO_ROOT / "systemd/units").glob("*.timer"):
        scheduled = _unit_section(path.name, "Timer")
        target = scheduled.get("Unit", path.with_suffix(".service").name)
        if not (path.parent / target).is_file():
            continue
        command = _unit_section(target, "Service").get("ExecStart", "")
        assert "hapax-glmcp-quota-admission" not in command
        assert "hapax-glmcp-seat-refresh" not in command
    dispatch_timer = _unit_section("hapax-pr-review-dispatch.timer", "Timer")
    dispatch_service = _unit_section("hapax-pr-review-dispatch.service", "Service")
    dispatcher_envelope = (
        _unit_seconds(dispatch_timer, "OnUnitActiveSec")
        + _unit_seconds(dispatch_timer, "RandomizedDelaySec", "0")
        + _unit_seconds(dispatch_timer, "AccuracySec")
        + _unit_seconds(dispatch_service, "TimeoutStartSec")
    )
    return {
        "agy": (
            f"scheduled hapax-determine; window {windows['agy']}s; "
            f"attempt envelope {attempt_envelope}s; margin {windows['agy'] - attempt_envelope}s"
        ),
        "glmcp": (
            f"no scheduled admission producer; window {windows['glmcp']}s; "
            f"dispatcher envelope {dispatcher_envelope}s"
        ),
    }


def test_review_admission_producer_margin_deficits_are_explicit() -> None:
    assert _admission_producer_measurements() == ADMISSION_PRODUCER_DEFICITS
    # A missing row must fail, even when no scheduled producer can supply that family.
    assert set(ADMISSION_PRODUCER_DEFICITS) == {"agy", "glmcp"}


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
def test_review_admission_expiry_is_not_extended_by_republication(
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
    # A newly published ledger must not renew the admission's original validity.
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


@pytest.mark.parametrize("route_id", ["agy.review.direct", "glmcp.review.direct"])
@pytest.mark.parametrize("observed", [False, True], ids=["absent", "expired"])
def test_registry_quota_observation_absent_or_expired_is_not_fresh(
    route_id: str, observed: bool
) -> None:
    payload = json.loads((REPO_ROOT / "config/platform-capability-registry.json").read_text())
    route = next(route for route in payload["routes"] if route["route_id"] == route_id)
    _mark_fresh(route)
    route["telemetry"]["quota_source"] = "ledger"
    route["freshness"]["quota_checked_at"] = "2026-05-09T20:44:59Z" if observed else None
    blocker = (
        "route_specific_quota_receipt_absent"
        if route_id == "agy.review.direct"
        else "glmcp_review_seat_receipt_admission_required"
    )
    if not observed:
        route["route_state"] = "blocked"
        route["blocked_reasons"] = [blocker]
        route["freshness"]["evidence"]["quota"]["blocked_reasons"] = [blocker]
    registry = PlatformCapabilityRegistry.model_validate(payload)
    checked_at = datetime(2026, 5, 9, 21, 0, tzinfo=UTC)
    result = check_registry_freshness(registry, route_ids=[route_id], now=checked_at)

    assert result.ok is False
    assert result.checked_at == checked_at
    reason = (
        "quota stale; checked_at=2026-05-09T20:44:59+00:00 stale_after=15m"
        if observed
        else f"quota blocked: {blocker}"
    )
    expected = (f"{route_id}: {reason}",)
    if not observed:
        expected = (f"{route_id}: blocked: {blocker}", *expected)
    assert result.routes[0].errors == expected


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
