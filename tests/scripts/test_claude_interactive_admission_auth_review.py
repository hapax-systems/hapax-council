"""Four signed-review regressions; all account observations are isolated fixtures."""

from __future__ import annotations

import json
import runpy
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from shared.capability_availability_guarantor import evaluate_registry_availability
from shared.dispatcher_policy import DispatchAction, evaluate_dispatch_policy
from shared.platform_capability_receipts import EvidenceStatus, receipt_is_fresh
from shared.platform_capability_registry import load_platform_capability_registry
from shared.quota_spend_ledger import _is_claude_admission_evidence_ref
from tests.scripts.test_claude_account_live_observe_per_route import _served, obs
from tests.scripts.test_claude_probe_subscription_boundary import (
    subscription_probe_home as subscription_probe_home,
)
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
from tests.shared.test_quota_spend_ledger import CLAUDE_ADMISSION_EVIDENCE_REF

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("route_id", [ROUTE, "claude.headless.full", "claude.review.opus"])
@pytest.mark.parametrize("minutes_later", [0, 10, 20])
@pytest.mark.parametrize("prior_projection", [False, True])
def test_retained_platform_receipt_drops_expired_account_attestation(
    tmp_path, monkeypatch, route_id, minutes_later, prior_projection
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

    # Exercise the actual quota-surface producer before expiry, then retain its
    # bytes while the enclosing platform receipt is still current after expiry.
    producer = runpy.run_path(str(ROOT / "scripts/hapax-platform-capability-receipts"))
    observe_quota = producer["observe_quota"]
    monkeypatch.setitem(observe_quota.__globals__, "QUOTA_RECEIPT_DIR", relay)
    monkeypatch.setitem(observe_quota.__globals__, "QUOTA_LEDGER_LIVE", ledger)
    seed = load_platform_capability_registry(receipt_dir=tmp_path / "absent", now=NOW)
    quota = observe_quota("claude", [seed.require(route_id)], now=NOW)
    assert quota.status is EvidenceStatus.OBSERVED
    assert any(ref.endswith(":account-live-quota:observed") for ref in quota.evidence_refs)
    retained = _make_receipt(observed_at=NOW, routes=[route_id])
    retained.quota = quota
    retained.quota.evidence_refs.append("test:unrelated-quota-provenance")
    platform = tmp_path / "platform"
    platform.mkdir()
    path = platform / "claude.json"
    before = retained.model_dump_json()
    path.write_text(before)
    registry_args = {}
    if prior_projection:
        projected_before = load_platform_capability_registry(receipt_dir=platform, now=NOW)
        registry_path = tmp_path / "registry.json"
        registry_path.write_text(projected_before.model_dump_json())
        registry_args["path"] = registry_path
    now = NOW + timedelta(minutes=minutes_later)
    assert receipt_is_fresh(retained, now=now)
    registry = load_platform_capability_registry(receipt_dir=platform, now=now, **registry_args)
    projected = registry.require(route_id)
    refs = projected.freshness.evidence.quota.evidence_refs
    [availability] = evaluate_registry_availability(
        registry, route_ids=[route_id], now=now
    ).receipts
    expired = minutes_later >= 10
    assert availability.predicate.account_live_quota_attested is not expired
    assert any(ref.endswith(":account-live-quota:observed") for ref in refs) is not expired
    assert set(quota.evidence_refs) - {
        ref for ref in quota.evidence_refs if ref.endswith(":account-live-quota:observed")
    } <= set(refs)
    assert "test:cap" in projected.freshness.evidence.capability.evidence_refs
    assert "test:res" in projected.freshness.evidence.resource.evidence_refs
    assert path.read_text() == before
    if expired:
        assert availability.available is False
        blocker = (
            "claude_review_route_specific_quota_receipt_absent"
            if route_id == "claude.review.opus"
            else "account_live_quota_receipt_absent"
        )
        assert blocker in projected.blocked_reasons


@pytest.mark.parametrize("model", ["claude-opus-5", "claude-sonnet-4-5", None, "wall"])
@pytest.mark.usefixtures("subscription_probe_home")
def test_real_probe_result_reaches_interactive_mint(tmp_path, monkeypatch, capsys, model):
    # Only the provider process is simulated. The real probe, selector, mint,
    # admission writer and receipt readback run without a live provider call.
    real_run = subprocess.run
    calls = []
    for name in list(obs.provider_redirect_env()):
        monkeypatch.delenv(name)
    for name in obs.PROBE_ENV_SCRUBBED:
        monkeypatch.setenv(name, "synthetic-redirect-value")

    def provider_run(argv, **kwargs):
        if argv == list(obs.PROBE_ARGV):
            calls.append(argv)
            assert kwargs["cwd"] == kwargs["env"]["HOME"]
            assert kwargs["cwd"] != str(Path.home())
            assert kwargs["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "synthetic-subscription-access-token"
            assert not any(name in kwargs["env"] for name in obs.PROBE_ENV_SCRUBBED)
            record = {
                "is_error": model == "wall",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
            if model == "wall":
                record["result"] = "You have hit your usage limit"
            elif model:
                record["model"] = model
            return subprocess.CompletedProcess(argv, 0, json.dumps(record), "")
        assert str(obs.ADMISSION_WRITER) in argv
        return real_run(argv, **kwargs)

    monkeypatch.setattr(obs.subprocess, "run", provider_run)
    receipts = tmp_path / "receipts"
    rc = obs.main(
        [
            "--transcript-glob",
            str(tmp_path / "absent-transcript"),
            "--headless-glob",
            str(tmp_path / "absent-headless"),
            "--now",
            NOW.isoformat(),
            "--route-id",
            ROUTE,
            "--receipt-dir",
            str(receipts),
            "--probe",
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert len(calls) == 1
    written = list(receipts.glob("*.yaml"))
    if model == "claude-opus-5":
        assert rc == 0
        assert result["probe"]["witnessed_routes"] == [ROUTE]
        assert result["observed_model_by_route"][ROUTE] == model
        assert len(written) == 1
        receipt = yaml.safe_load(written[0].read_text())
        assert receipt["route_id"] == ROUTE
        assert receipt["status"] == "quota_available"
        assert receipt["auth_surface"] == "subscription"
        assert receipt["probe_environment_scrubbed"].split(",") == list(obs.PROBE_ENV_SCRUBBED)
        assert receipt["observed_at"] == NOW
        assert "synthetic-redirect-value" not in written[0].read_text()
    else:
        assert rc == {"claude-sonnet-4-5": 5, "wall": 3, None: 4}[model]
        if model == "wall":
            assert len(written) == 1
            receipt = yaml.safe_load(written[0].read_text())
            assert receipt["status"] == "quota_blocked"
            assert receipt["auth_surface"] == "subscription"
            assert receipt["credential_binding"]
        else:
            assert not written


@pytest.mark.parametrize("route_id", [ROUTE, "claude.headless.full", "claude.review.opus"])
@pytest.mark.parametrize(
    ("observed_at", "fresh_until"),
    [
        ("2026-07-32T14:00:00Z", "2026-07-08T14:15:00Z"),
        ("2026-07-08T14:00:00Z", "2026-07-32T14:15:00Z"),
        ("2026-07-08T14:16:00Z", "2026-07-08T14:15:00Z"),
        ("2026-07-08T14:15:00Z", "2026-07-08T14:15:00Z"),
    ],
)
def test_admission_reference_rejects_invalid_windows(route_id, observed_at, fresh_until):
    valid = CLAUDE_ADMISSION_EVIDENCE_REF.replace("claude.headless.full", route_id)
    invalid = valid.replace("2026-07-08T14:00:00Z", observed_at).replace(
        "fresh_until:2026-07-08T14:15:00Z", f"fresh_until:{fresh_until}"
    )
    assert _is_claude_admission_evidence_ref(valid, route_id=route_id)
    assert not _is_claude_admission_evidence_ref(invalid, route_id=route_id)


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
