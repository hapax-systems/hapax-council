"""Review regressions for the complete interactive admission boundary.

Every observation is synthetic; subprocess writers use temporary bindings only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.dispatcher_policy import (
    DispatchAction,
    build_dispatch_request,
    evaluate_dispatch_policy,
)
from shared.platform_capability_registry import load_platform_capability_registry
from shared.quota_spend_ledger import (
    QuotaSpendLedger,
    SubscriptionQuotaState,
    subscription_quota_state_for_route,
)
from tests.scripts.test_claude_account_live_observe_per_route import _served, obs
from tests.scripts.test_hapax_claude_interactive_admission import NOW, ROUTE, _availability
from tests.scripts.test_hapax_quota_telemetry_writer import (
    CLAUDE_ADMISSION_SCRIPT,
    _claude_admission,
    _run_writer,
)
from tests.shared.test_dispatcher_policy import _capability, _quota, _request, _task_fields

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("model", ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-8"])
def test_interactive_observer_selects_and_mints_only_opus(tmp_path: Path, model: str) -> None:
    evidence = obs.Observation("served", NOW, "synthetic", model=model)
    selected = obs.evidence_by_route([evidence], (ROUTE,))[ROUTE]
    planned = obs.mint(
        evidence,
        now=NOW,
        route_ids=(ROUTE,),
        stale_after_seconds=900,
        receipt_dir=tmp_path,
        dry_run=True,
    )[0]
    if model.startswith("claude-opus"):
        assert selected is evidence
        assert "would_run" in planned
    else:
        assert selected is None
        assert planned.get("skipped") == "model-family-mismatch"


def test_interactive_cheap_serve_does_not_suppress_opus_probe(tmp_path, monkeypatch, capsys):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(_served(NOW - timedelta(minutes=1), "claude-haiku-4-5") + "\n")
    calls = []

    def probe(now):
        calls.append(now)
        return obs.Observation("served", now, "synthetic-probe", model="claude-opus-4-8")

    monkeypatch.setattr(obs, "probe", probe)
    assert (
        obs.main(
            [
                "--transcript-glob",
                str(transcript),
                "--headless-glob",
                str(tmp_path / "absent"),
                "--now",
                NOW.isoformat(),
                "--route-id",
                ROUTE,
                "--receipt-dir",
                str(tmp_path / "receipts"),
                "--probe",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert calls == [NOW]
    assert result["probe"]["witnessed_routes"] == [ROUTE]
    assert result["observed_model_by_route"][ROUTE] == "claude-opus-4-8"
    assert result["receipts"][0]["returncode"] == 0


def test_default_observer_produces_interactive_receipt(tmp_path, capsys):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(_served(NOW - timedelta(minutes=1), "claude-opus-4-8") + "\n")
    receipts = tmp_path / "receipts"
    assert (
        obs.main(
            [
                "--transcript-glob",
                str(transcript),
                "--headless-glob",
                str(tmp_path / "absent"),
                "--now",
                NOW.isoformat(),
                "--receipt-dir",
                str(receipts),
                "--no-probe",
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    interactive = next(item for item in result["receipts"] if item["route_id"] == ROUTE)
    assert interactive["returncode"] == 0
    assert any(f"route_id: {ROUTE}" in path.read_text() for path in receipts.glob("*.yaml"))


@pytest.mark.parametrize("quota_state", [None, "unknown", "stale", "exhausted", "fresh"])
def test_interactive_dispatch_checks_quota_even_with_fresh_capability(quota_state):
    # Capability projection can precede a missing/newer dispatch quota read.
    request = _request(
        platform="claude",
        mode="interactive",
        route_id=ROUTE,
        capability=_capability(route_id=ROUTE, telemetry_quota_source="ledger"),
        quota=None
        if quota_state is None
        else _quota(
            subscription_quota_state="fresh",
            route_subscription_quota_state=quota_state,
        ),
    )
    decision = evaluate_dispatch_policy(request, now=NOW)
    if quota_state == "fresh":
        assert decision.action is DispatchAction.LAUNCH, decision.reason_codes
        assert decision.quota_freshness_green is True
    else:
        assert decision.action is DispatchAction.HOLD, decision.reason_codes
        assert decision.quota_freshness_green is False
        assert "policy_launch" not in decision.reason_codes
        assert (
            "subscription_route_quota_unavailable"
            if quota_state is None
            else "subscription_route_quota_not_fresh"
        ) in decision.reason_codes


@pytest.mark.parametrize("source_route", ["claude.headless.full", "claude.review.opus", ROUTE])
def test_ledger_binds_produced_evidence_to_its_route(tmp_path, source_route):
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, route_id=source_route, observed_at="2026-06-09T23:55:00Z")
    result, path = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(path.read_text())
    snapshot = next(s for s in payload["quota_snapshots"] if s["route_id"] == source_route)
    snapshot["route_id"] = ROUTE
    payload["quota_snapshots"] = [snapshot]
    state, _ = subscription_quota_state_for_route(
        QuotaSpendLedger.model_validate(payload),
        ROUTE,
        now=NOW,
    )
    assert state is (
        SubscriptionQuotaState.FRESH if source_route == ROUTE else SubscriptionQuotaState.UNKNOWN
    )


@pytest.mark.parametrize("condition", ["missing", "exhausted", "fresh"])
def test_produced_registry_cannot_override_dispatch_quota(tmp_path, monkeypatch, condition):
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, route_id=ROUTE, observed_at="2026-06-09T23:55:00Z")
    result, path = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr
    _, availability = _availability(tmp_path, monkeypatch, path)
    assert availability.available is True
    registry = load_platform_capability_registry(receipt_dir=tmp_path / "claude-platform", now=NOW)
    payload = json.loads(path.read_text())
    if condition == "exhausted":
        for snapshot in payload["quota_snapshots"]:
            if snapshot["route_id"] == ROUTE:
                snapshot["subscription_quota_state"] = "exhausted"
    ledger = None if condition == "missing" else QuotaSpendLedger.model_validate(payload)
    request = build_dispatch_request(
        task_id="policy-test",
        lane="cx-green",
        platform="claude",
        mode="interactive",
        profile="full",
        task_fields=_task_fields(),
        registry=registry,
        quota_ledger=ledger,
        now=NOW,
    )
    decision = evaluate_dispatch_policy(request, now=NOW)
    if condition == "fresh":
        assert decision.action is DispatchAction.LAUNCH, decision.reason_codes
    else:
        assert decision.action is DispatchAction.HOLD, decision.reason_codes
        assert (
            "subscription_route_quota_unavailable"
            if condition == "missing"
            else "subscription_route_quota_not_fresh"
        ) in decision.reason_codes


@pytest.mark.parametrize("route_id", ["claude.headless.full", "claude.review.opus", ROUTE])
def test_legacy_composite_holds_until_telemetry_regenerates_route_binding(tmp_path, route_id):
    produced = subprocess.run(
        [
            sys.executable,
            str(CLAUDE_ADMISSION_SCRIPT),
            "--receipt-dir",
            str(tmp_path / "relay-receipts"),
            "--route-id",
            route_id,
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
    receipt_bytes = receipt.read_bytes()
    result, path = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(path.read_text())
    snapshot = next(s for s in payload["quota_snapshots"] if s["route_id"] == route_id)
    fresh_until = snapshot["fresh_until"]
    assert any(f":route_id:{route_id}:" in ref for ref in snapshot["evidence_refs"])
    state, _ = subscription_quota_state_for_route(
        QuotaSpendLedger.model_validate(payload), route_id, now=NOW
    )
    assert state is SubscriptionQuotaState.FRESH

    # Simulate the on-disk ledger from before route binding was introduced.
    snapshot["evidence_refs"] = [
        ref.replace(f"route_id:{route_id}:", "") for ref in snapshot["evidence_refs"]
    ]
    path.write_text(json.dumps(payload))
    state, _ = subscription_quota_state_for_route(
        QuotaSpendLedger.model_validate_json(path.read_text()), route_id, now=NOW
    )
    assert state is SubscriptionQuotaState.UNKNOWN

    # Regeneration uses the same receipt, without renewing the observation.
    regenerated_at = NOW + timedelta(minutes=1)
    result, path = _run_writer(tmp_path, now=regenerated_at.isoformat())
    assert result.returncode == 0, result.stderr
    assert receipt.read_bytes() == receipt_bytes
    ledger = QuotaSpendLedger.model_validate_json(path.read_text())
    snapshot = next(s for s in ledger.quota_snapshots if s.route_id == route_id)
    assert snapshot.fresh_until == datetime.fromisoformat(fresh_until.replace("Z", "+00:00"))
    state, refs = subscription_quota_state_for_route(ledger, route_id, now=regenerated_at)
    assert state is SubscriptionQuotaState.FRESH
    assert any(f":route_id:{route_id}:" in ref for ref in refs)
    state, _ = subscription_quota_state_for_route(ledger, route_id, now=snapshot.fresh_until)
    assert state is SubscriptionQuotaState.STALE


@pytest.mark.parametrize("condition", ["missing", "fresh", "expired"])
def test_runbook_exact_readback_is_executable(tmp_path, monkeypatch, condition):
    now = datetime.now(UTC).replace(microsecond=0)
    ledger = tmp_path / "missing-ledger.json"
    if condition != "missing":
        relay = tmp_path / "relay-receipts"
        relay.mkdir()
        observed = now - timedelta(minutes=20 if condition == "expired" else 5)
        _claude_admission(relay, route_id=ROUTE, observed_at=observed.isoformat())
        captured = observed + timedelta(minutes=1) if condition == "expired" else now
        result, ledger = _run_writer(tmp_path, now=captured.isoformat())
        assert result.returncode == 0, result.stderr
    _availability(tmp_path, monkeypatch, ledger, now=now)
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", str(tmp_path / "claude-platform"))
    document = (ROOT / "docs/runbooks/claude-interactive-quota-admission.md").read_text()
    code = re.search(r"python - <<'PY'\n(.*?)\nPY\n", document, re.S).group(1)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    readback = json.loads(result.stdout)
    assert readback["ledger_source"] == ("fixtures" if condition == "missing" else "live")
    assert (
        readback["quota_state"]
        == {"missing": "unknown", "fresh": "fresh", "expired": "stale"}[condition]
    )
    availability = readback["availability"]["receipts"][0]
    assert availability["predicate"]["account_live_quota_attested"] is (condition == "fresh")
    if condition == "fresh":
        assert availability["status"] == "available"
    else:
        assert availability["status"] != "available"
    if condition != "missing":
        snapshot = readback["quota_snapshots"][0]
        assert snapshot["route_id"] == ROUTE
        assert snapshot["provider"] == "anthropic-claude-subscription"
        assert snapshot["fresh_until"]
        assert snapshot["evidence_refs"]
