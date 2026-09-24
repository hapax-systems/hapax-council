"""Exercise the existing receipt → ledger → registry → availability boundary.

All observations are synthetic fixtures in tmp_path; no live quota is attested.
The producer and telemetry CLI execute normally, with local hardware stubbed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.capability_availability_guarantor import (
    RefreshStatus,
    default_refresh_strategy_registry,
    evaluate_route_availability,
)
from shared.platform_capability_registry import (
    check_registry_freshness,
    load_platform_capability_registry,
)
from shared.quota_spend_ledger import (
    QuotaSpendLedger,
    SubscriptionQuotaState,
    subscription_quota_state_for_route,
)
from tests.scripts.test_hapax_quota_telemetry_writer import (
    CLAUDE_ADMISSION_SCRIPT,
    _claude_admission,
    _run_writer,
    _wall_receipt,
)
from tests.shared.test_platform_capability_registry import _make_receipt

ROUTE = "claude.interactive.full"
NOW = datetime(2026, 6, 10, tzinfo=UTC)


def _availability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ledger: Path, *, now: datetime = NOW
):
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(ledger))
    receipts = tmp_path / "claude-platform"
    receipts.mkdir(exist_ok=True)
    # A local CLI/wrapper observation is necessary but cannot attest account quota.
    receipt = _make_receipt(observed_at=now, routes=[ROUTE])
    (receipts / "claude.json").write_text(receipt.model_dump_json())
    registry = load_platform_capability_registry(receipt_dir=receipts, now=now)
    route = registry.require(ROUTE)
    freshness = check_registry_freshness(registry, route_ids=[ROUTE], now=now).routes[0]
    return route, evaluate_route_availability(
        route, freshness, refresh_strategies=default_refresh_strategy_registry(), now=now
    )


@pytest.mark.parametrize(
    "observation",
    ["missing", "stale", "future", "headless", "review", "lane_presence", "wrong_provider"],
)
def test_interactive_unsafe_observation_keeps_admission_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, observation: str
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    if observation != "missing":
        fields = {"route_id": ROUTE, "observed_at": "2026-06-09T23:55:00Z"}
        if observation == "stale":
            fields["observed_at"] = "2026-06-09T23:45:00Z"  # exactly expires at NOW
        elif observation == "future":
            fields["observed_at"] = "2026-06-10T00:01:00Z"
        elif observation in {"headless", "review"}:
            fields["route_id"] = (
                "claude.headless.full" if observation == "headless" else "claude.review.opus"
            )
        elif observation == "lane_presence":
            fields["evidence_ref"] = "hapax-claude-alpha-session-present"
        _claude_admission(relay, **fields)
        if observation == "wrong_provider":
            path = relay / "claude-subscription-quota-admission.yaml"
            path.write_text(
                path.read_text().replace(
                    "provider: anthropic-claude-subscription", "provider: anthropic-api"
                )
            )

    result, ledger = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr
    route, availability = _availability(tmp_path, monkeypatch, ledger)
    assert availability.available is False
    assert "account_live_quota_receipt_absent" in route.blocked_reasons
    assert availability.predicate.account_live_quota_attested is False


def test_interactive_missing_observation_names_executable_route_remediation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, availability = _availability(tmp_path, monkeypatch, tmp_path / "missing-ledger.json")
    assert availability.available is False
    assert availability.refresh_status is RefreshStatus.DEFERRED
    assert (
        "subscription_admission_writer_route_unsupported" not in availability.refresh_reason_codes
    )
    assert any(
        f"hapax-claude-subscription-quota-admission --route-id {ROUTE} " in command
        for command in availability.refresh_remediation_commands
    )


def test_interactive_real_producer_reaches_availability_without_admitting_siblings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    produced = subprocess.run(
        [
            sys.executable,
            str(CLAUDE_ADMISSION_SCRIPT),
            "--receipt-dir",
            str(tmp_path / "relay-receipts"),
            "--route-id",
            ROUTE,
            "--now",
            "2026-06-09T23:55:00Z",
            "--evidence-ref",
            "claude-subscription-headroom-observed-20260609t2355z",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert produced.returncode == 0, produced.stderr
    receipt = Path(json.loads(produced.stdout)["path"])
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert "secret_value_persisted: false" in receipt.read_text()
    assert "prompt_or_output_persisted: false" in receipt.read_text()

    result, ledger_path = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr
    ledger = QuotaSpendLedger.model_validate_json(ledger_path.read_text())
    state, refs = subscription_quota_state_for_route(ledger, ROUTE, now=NOW)
    assert state is SubscriptionQuotaState.FRESH
    assert any(ref.endswith(":account-live-quota:observed") for ref in refs)
    for sibling in ("claude.headless.full", "claude.review.opus"):
        sibling_state, _ = subscription_quota_state_for_route(ledger, sibling, now=NOW)
        assert sibling_state is SubscriptionQuotaState.UNKNOWN
    # Expiry must also hold at the ledger reader without a telemetry rewrite.
    expired, _ = subscription_quota_state_for_route(
        ledger, ROUTE, now=datetime(2026, 6, 10, 0, 10, tzinfo=UTC)
    )
    assert expired is SubscriptionQuotaState.STALE
    route, availability = _availability(tmp_path, monkeypatch, ledger_path)
    assert route.blocked_reasons == []
    assert route.telemetry.quota_source.value == "ledger"
    assert availability.available is True
    assert availability.predicate.account_live_quota_attested is True
    expired_route, expired_availability = _availability(
        tmp_path, monkeypatch, ledger_path, now=datetime(2026, 6, 10, 0, 10, tzinfo=UTC)
    )
    assert "account_live_quota_receipt_absent" in expired_route.blocked_reasons
    assert expired_availability.available is False
    assert expired_availability.predicate.account_live_quota_attested is False


@pytest.mark.parametrize("wall_route", [ROUTE, "claude.headless.full", "claude.review.opus"])
def test_interactive_admission_respects_shared_pool_wall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wall_route: str
) -> None:
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, route_id=ROUTE, observed_at="2026-06-09T23:55:00Z")
    _wall_receipt(
        relay,
        "dev1",
        "2026-06-10T06:00:00Z",
        route_id=wall_route,
        detected_at="2026-06-09T23:57:00Z",
    )
    result, ledger_path = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr
    ledger = QuotaSpendLedger.model_validate_json(ledger_path.read_text())
    state, refs = subscription_quota_state_for_route(ledger, ROUTE, now=NOW)
    assert state is SubscriptionQuotaState.EXHAUSTED
    assert any(f":route_id:{wall_route}:" in ref for ref in refs)
    _, availability = _availability(tmp_path, monkeypatch, ledger_path)
    assert availability.available is False


@pytest.mark.parametrize("defect", ["provider", "writer", "evidence", "expiry"])
def test_interactive_ledger_requires_bounded_producer_evidence(defect: str) -> None:
    # A declared FRESH snapshot alone must not authorize this newly covered route.
    from tests.shared.test_quota_spend_ledger import (
        CLAUDE_ADMISSION_EVIDENCE_REF,
        CLAUDE_NOW,
        _claude_ledger,
    )

    payload = _claude_ledger(
        CLAUDE_ADMISSION_EVIDENCE_REF.replace("claude.headless.full", ROUTE), route_id=ROUTE
    ).model_dump(mode="json")
    snapshot = next(s for s in payload["quota_snapshots"] if s["route_id"] == ROUTE)
    if defect == "provider":
        snapshot["provider"] = "anthropic-api"
    elif defect == "writer":
        payload["generated_from"].remove("scripts/hapax-quota-telemetry-writer")
    elif defect == "evidence":
        snapshot["evidence_refs"] = ["local:claude-session-present"]
    else:
        snapshot.pop("fresh_until")
    state, _ = subscription_quota_state_for_route(
        QuotaSpendLedger.model_validate(payload), ROUTE, now=CLAUDE_NOW
    )
    assert state is SubscriptionQuotaState.UNKNOWN
