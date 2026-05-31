"""Tests for coding-platform capability receipts."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from shared.dispatcher_policy import (
    DispatchAction,
    build_dispatch_request,
    evaluate_dispatch_policy,
    load_dispatch_policy_sources,
    route_authority_receipt_payload_hash,
    route_decision_receipt_payload,
)
from shared.platform_capability_registry import load_platform_capability_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-platform-capability-receipts"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"
NOW = "2026-05-17T19:55:00Z"
NOW_DT = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
SECRET = "sk-live-secret-value"


def _run_receipts(
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    now: str = NOW,
    platform: str = "codex",
) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--registry",
            str(REGISTRY),
            "--receipt-dir",
            str(tmp_path),
            "--platform",
            platform,
            "--now",
            now,
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=merged_env,
    )


def _fake_binary(bin_dir: Path, name: str, output: str) -> None:
    target = bin_dir / name
    target.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR)


def _fake_wrapper(home_dir: Path, relative_path: str) -> None:
    target = home_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR)


def _current_iso_z() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_route_authority_receipt(
    receipt_dir: Path,
    *,
    receipt_id: str,
    route_id: str,
    receipt_type: str,
    quality_floors: list[str] | None = None,
    payload_hash: str | None = None,
) -> Path:
    issued_at = _current_iso_z()
    payload: dict[str, object] = {
        "route_authority_receipt_schema": 1,
        "receipt_id": receipt_id,
        "receipt_type": receipt_type,
        "route_id": route_id,
        "issued_at": issued_at,
        "stale_after": "24h",
        "signed_by": "operator",
        "evidence_refs": [f"test:{receipt_id}"],
        "quality_floors": quality_floors or [],
    }
    payload["signed_payload_sha256"] = payload_hash or route_authority_receipt_payload_hash(payload)
    target_dir = receipt_dir / "route-authority"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{receipt_id}.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def test_receipt_refresh_redacts_secret_env_and_records_missing_cli(tmp_path: Path) -> None:
    result = _run_receipts(
        tmp_path,
        env={"PATH": "", "OPENAI_API_KEY": SECRET},
    )

    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stdout
    receipt_text = (tmp_path / "codex.json").read_text(encoding="utf-8")
    assert SECRET not in receipt_text
    receipt = json.loads(receipt_text)
    assert receipt["cli"]["available"] is False
    assert "cli_missing_or_unusable" in receipt["capability"]["reason_codes"]
    assert all(item["redacted"] is True for item in receipt["config_refs"])


def test_fresh_subscription_receipt_clears_account_live_quota_blocker(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", f"codex-cli 9.9.9 api_key={SECRET}")

    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir), "OPENAI_API_KEY": SECRET})

    assert result.returncode == 0, result.stderr
    assert SECRET not in (tmp_path / "codex.json").read_text(encoding="utf-8")
    registry = load_platform_capability_registry(REGISTRY, receipt_dir=tmp_path, now=NOW_DT)
    route = registry.require("codex.headless.full")

    assert route.freshness.quota_checked_at is not None
    assert "account_live_quota_receipt_absent" not in route.blocked_reasons
    assert "account_live_quota_receipt_absent" not in route.freshness.evidence.quota.blocked_reasons
    assert route.route_state.value == "active"
    assert any(
        ref.startswith("platform-capability-receipt:codex:")
        for ref in route.freshness.evidence.quota.evidence_refs
    )
    assert route.tool_state[0].evidence_ref.startswith("platform-capability-receipt:codex:")


def test_fresh_subscription_receipt_allows_dispatch_without_rollback(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")

    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)}, now=_current_iso_z())
    assert result.returncode == 0, result.stderr

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    task_fields = {
        "status": "claimed",
        "assigned_to": "cx-green",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "PLATFORM-RECEIPT-TEST",
        "priority": "p0",
        "wsjf": 12,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/platform_capability_registry.py"],
    }
    request = build_dispatch_request(
        task_id="platform-receipt-present",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
    )

    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert decision.registry_freshness_green is True


def test_antigrav_agy_receipt_clears_unobservable_quota_catch22(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "agy", "1.0.0")
    wrapper = tmp_path / "home" / ".local" / "bin" / "hapax-antigrav"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HOME": str(tmp_path / "home")},
        platform="antigrav",
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "antigrav.json").read_text(encoding="utf-8"))
    assert receipt["cli"]["binary"] == "agy"
    assert receipt["cli"]["available"] is True
    assert "quota_telemetry_unknown" in receipt["quota"]["reason_codes"]

    registry = load_platform_capability_registry(REGISTRY, receipt_dir=tmp_path, now=NOW_DT)
    route = registry.require("antigrav.interactive.full")

    assert route.route_state.value == "active"
    assert "quota_telemetry_unknown" not in route.blocked_reasons
    assert "quota_telemetry_unknown" not in route.freshness.evidence.quota.blocked_reasons


def test_stale_receipt_is_not_consumed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir)},
        now="2026-05-01T00:00:00Z",
    )
    assert result.returncode == 0, result.stderr

    registry = load_platform_capability_registry(REGISTRY, receipt_dir=tmp_path)
    route = registry.require("codex.headless.full")

    assert not any(
        ref.startswith("platform-capability-receipt:codex:")
        for ref in route.freshness.evidence.quota.evidence_refs
    )


def test_dispatch_policy_holds_when_receipts_are_absent(tmp_path: Path) -> None:
    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    task_fields = {
        "status": "claimed",
        "assigned_to": "cx-green",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "PLATFORM-RECEIPT-TEST",
        "priority": "p0",
        "wsjf": 12,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/platform_capability_registry.py"],
    }
    request = build_dispatch_request(
        task_id="platform-receipt-absent",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
    )

    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.HOLD
    assert "quota_telemetry_stale_or_unknown" in decision.reason_codes
    assert any("account_live_quota_receipt_absent" in reason for reason in decision.reason_codes)


def test_signed_opus_entitlement_receipt_allows_dispatch_without_policy_rollback(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    home_dir = tmp_path / "home"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "claude", "claude-cli 2.1.143")
    _fake_wrapper(home_dir, ".local/bin/hapax-claude-headless")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HOME": str(home_dir)},
        now=_current_iso_z(),
        platform="claude",
    )
    assert result.returncode == 0, result.stderr
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="opus-entitlement-test",
        route_id="claude.headless.opus",
        receipt_type="opus_model_entitlement",
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    task_fields = {
        "status": "claimed",
        "assigned_to": "cx-green",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "OPUS-ENTITLEMENT-TEST",
        "priority": "p1",
        "wsjf": 29,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/dispatcher_policy.py"],
    }
    request = build_dispatch_request(
        task_id="opus-entitlement-receipt-present",
        lane="cx-green",
        platform="claude",
        mode="headless",
        profile="opus",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
    )

    decision = evaluate_dispatch_policy(request)

    assert request.capability is not None
    assert any(
        record.startswith("route-authority-receipt:opus_model_entitlement:")
        for record in request.capability.explicit_equivalence_records
    )
    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert decision.compatibility_mode == "none"
    assert "policy_launch" in decision.reason_codes
    decision_payload = route_decision_receipt_payload(decision)
    assert any(
        ref.startswith("route-authority-receipt:opus_model_entitlement:")
        for ref in decision_payload["dimensional_evidence_refs"]
    )


def test_quality_equivalence_receipt_does_not_widen_authority_ceiling(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    home_dir = tmp_path / "home"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "claude", "claude-cli 2.1.143")
    _fake_wrapper(home_dir, ".local/bin/hapax-claude-headless")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "HOME": str(home_dir)},
        now=_current_iso_z(),
        platform="claude",
    )
    assert result.returncode == 0, result.stderr
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="sonnet-equivalence-test",
        route_id="claude.headless.sonnet",
        receipt_type="quality_equivalence",
        quality_floors=["frontier_required"],
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    task_fields = {
        "status": "claimed",
        "assigned_to": "cx-green",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "SONNET-EQUIVALENCE-TEST",
        "priority": "p1",
        "wsjf": 29,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/dispatcher_policy.py"],
        "review_requirement": {
            "support_artifact_allowed": True,
            "independent_review_required": True,
            "authoritative_acceptor_profile": "frontier_full",
        },
    }
    request = build_dispatch_request(
        task_id="sonnet-equivalence-receipt-present",
        lane="cx-green",
        platform="claude",
        mode="headless",
        profile="sonnet",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
    )

    decision = evaluate_dispatch_policy(request)

    assert request.capability is not None
    assert "frontier_required" in request.capability.eligible_quality_floors
    assert request.capability.authority_ceiling == "frontier_review_required"
    assert any(
        record.startswith("route-authority-receipt:quality_equivalence:")
        for record in request.capability.explicit_equivalence_records
    )
    assert decision.action is DispatchAction.SUPPORT_ONLY
    assert decision.launch_allowed is False
    assert decision.quality_floor_satisfied is True
    assert decision.authority_allowed is False
    assert "authority_ceiling_not_satisfied" in decision.reason_codes


def test_route_authority_receipt_signature_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="bad-signature-test",
        route_id="claude.headless.opus",
        receipt_type="opus_model_entitlement",
        payload_hash="sha256:not-the-payload",
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)

    assert sources.registry is None
    assert sources.registry_error is not None
    assert "signed payload hash mismatch" in sources.registry_error
