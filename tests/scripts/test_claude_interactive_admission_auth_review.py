"""Four signed-review regressions; all account observations are isolated fixtures."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from shared.capability_availability_guarantor import evaluate_registry_availability
from shared.dispatcher_policy import DispatchAction, evaluate_dispatch_policy
from shared.platform_capability_registry import load_platform_capability_registry
from tests.scripts.test_claude_account_live_observe_per_route import _served, obs
from tests.scripts.test_hapax_claude_interactive_admission import NOW, ROUTE
from tests.scripts.test_hapax_methodology_dispatch import (
    _availability_degraded_registry,
    _default_route_metadata,
    _spec,
    _task,
    _worktree,
)
from tests.scripts.test_hapax_methodology_dispatch import (
    _run as _run_dispatch,
)
from tests.scripts.test_hapax_quota_telemetry_writer import _claude_admission, _run_writer
from tests.shared.test_dispatcher_policy import _capability, _quota, _request
from tests.shared.test_platform_capability_registry import _make_receipt


@pytest.mark.parametrize("surface", ["transcript", "headless"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_passive_opus_without_subscription_auth_cannot_mint(
    tmp_path, monkeypatch, capsys, surface, dry_run
):
    record = json.loads(_served(NOW - timedelta(minutes=1), "claude-opus-5"))
    if surface == "headless":
        record = {"type": "result", "timestamp": record["timestamp"], **record["message"]}
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(record) + "\n")
    receipts = tmp_path / "receipts"
    monkeypatch.setattr(obs, "probe", lambda *a, **kw: pytest.fail("passive mode probed"))
    rc = obs.main(
        [
            "--transcript-glob",
            str(source if surface == "transcript" else tmp_path / "absent"),
            "--headless-glob",
            str(source if surface == "headless" else tmp_path / "absent"),
            "--now",
            NOW.isoformat(),
            "--receipt-dir",
            str(receipts),
            "--no-probe",
            "--json",
            *(["--dry-run"] if dry_run else []),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert rc == 4
    assert result["verdict"] == "no_evidence"
    assert not result.get("receipts")
    assert not list(receipts.glob("*.yaml"))


@pytest.mark.parametrize("dimensional", [False, True])
@pytest.mark.parametrize("capability_missing", [False, True])
def test_interactive_hold_recovers_the_actual_missing_boundary(dimensional, capability_missing):
    request = _request(
        platform="claude",
        mode="interactive",
        route_id=ROUTE,
        capability=None if capability_missing else _capability(route_id=ROUTE),
        quota=_quota(route_subscription_quota_state="fresh") if capability_missing else None,
    )
    decision = evaluate_dispatch_policy(
        request, candidate_requests=(request,) if dimensional else None, now=NOW
    )
    assert decision.action is DispatchAction.HOLD
    assert "Next action:" in decision.message
    if capability_missing:
        assert "config/platform-capability-registry.json" in decision.message
        assert ROUTE in decision.message
        assert "hapax-claude-subscription-quota-admission" not in decision.message
    else:
        assert f"hapax-claude-subscription-quota-admission --route-id {ROUTE}" in decision.message
        assert "hapax-quota-telemetry-writer --json" in decision.message


@pytest.mark.parametrize("route_id", [ROUTE, "claude.headless.full", "claude.review.opus"])
@pytest.mark.parametrize("minutes_later", [0, 10, 20])
def test_registry_account_attestation_tracks_receipt_expiry(
    tmp_path, monkeypatch, route_id, minutes_later
):
    relay = tmp_path / "relay-receipts"
    relay.mkdir()
    _claude_admission(relay, route_id=route_id, observed_at="2026-06-09T23:55:00Z")
    result, ledger = _run_writer(tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(ledger.read_text())
    snapshot = next(s for s in payload["quota_snapshots"] if s["route_id"] == route_id)
    snapshot["fresh_until"] = "2026-06-10T00:30:00Z"
    ledger.write_text(json.dumps(payload))
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(ledger))
    now = NOW + timedelta(minutes=minutes_later)
    expired = minutes_later >= 10
    platform = tmp_path / "platform"
    platform.mkdir()
    (platform / "claude.json").write_text(
        _make_receipt(observed_at=now, routes=[route_id]).model_dump_json()
    )
    registry = load_platform_capability_registry(receipt_dir=platform, now=now)
    availability = evaluate_registry_availability(registry, route_ids=[route_id], now=now)
    [receipt] = availability.receipts
    assert receipt.predicate.account_live_quota_attested is not expired
    if expired:
        assert receipt.available is False


def test_unrelated_dimensional_hold_does_not_prescribe_quota_repair():
    request = _request(
        platform="claude",
        mode="interactive",
        route_id=ROUTE,
        capability=_capability(route_id=ROUTE),
        quota=_quota(route_subscription_quota_state="fresh"),
        route_metadata_status="missing",
    )
    decision = evaluate_dispatch_policy(request, candidate_requests=(request,), now=NOW)
    assert decision.action is DispatchAction.HOLD
    assert "hapax-claude-subscription-quota-admission" not in decision.message


def test_dispatch_cli_degraded_registry_names_quota_recovery(tmp_path):
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "spec.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        _default_route_metadata(
            f"kind: build\nauthority_case: CASE-TEST-001\nparent_spec: {spec}\n"
        )
        .replace("allowed_platforms: []", "allowed_platforms: [claude]")
        .replace("required_mode: null", "required_mode: interactive")
        .replace("required_profile: null", "required_profile: full"),
    )
    registry = _availability_degraded_registry(tmp_path, ROUTE)
    result = _run_dispatch(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "beta",
        "--platform",
        "claude",
        "--mode",
        "interactive",
        extra_env={"HAPAX_PLATFORM_CAPABILITY_REGISTRY": str(registry)},
    )
    assert result.returncode == 10, result.stderr
    assert "no_eligible_dimensional_candidates" in result.stderr
    assert f"hapax-claude-subscription-quota-admission --route-id {ROUTE}" in result.stderr
    assert "hapax-quota-telemetry-writer --json" in result.stderr
    assert "retry" in result.stderr
