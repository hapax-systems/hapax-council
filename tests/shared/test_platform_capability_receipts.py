"""Tests for coding-platform capability receipts."""

from __future__ import annotations

import json
import os
import runpy
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from shared.dispatcher_policy import (
    DispatchAction,
    RouteAuthorityReceipt,
    build_dispatch_request,
    evaluate_dispatch_policy,
    load_dispatch_policy_sources,
    route_authority_receipt_payload_hash,
    route_decision_receipt_payload,
)
from shared.platform_capability_receipts import (
    PLATFORM_CAPABILITY_RECEIPT_DIR_ENV,
    load_platform_capability_receipt,
    receipt_is_fresh,
)
from shared.platform_capability_registry import load_platform_capability_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-platform-capability-receipts"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"
QUOTA_LEDGER = REPO_ROOT / "config" / "quota-spend-ledger-fixtures.json"
NOW = "2026-05-17T19:55:00Z"
NOW_DT = datetime.fromisoformat(NOW.replace("Z", "+00:00"))
API_NOW = "2026-06-04T16:00:00Z"
API_NOW_DT = datetime.fromisoformat(API_NOW.replace("Z", "+00:00"))
SECRET = "sk-live-secret-value"


def _run_receipts(
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    now: str = NOW,
    platform: str = "codex",
    registry: Path = REGISTRY,
) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--registry",
            str(registry),
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


def _fresh_quota_ledger(tmp_path: Path, *, captured_at: str) -> Path:
    payload = json.loads(QUOTA_LEDGER.read_text(encoding="utf-8"))
    payload["ledger_id"] = "quota-spend-ledger-test-fresh"
    payload["captured_at"] = captured_at
    target_dir = tmp_path / "quota-ledger"
    target_dir.mkdir()
    target = target_dir / "quota-spend-ledger.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def _current_iso_z() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_route_authority_receipt(
    receipt_dir: Path,
    *,
    receipt_id: str,
    route_id: str,
    receipt_type: str,
    quality_floors: list[str] | None = None,
    task_ids: list[str] | None = None,
    mutation_surfaces: list[str] | None = None,
    issued_at: str | None = None,
    stale_after: str = "24h",
    payload_hash: str | None = None,
) -> Path:
    payload: dict[str, object] = {
        "route_authority_receipt_schema": 1,
        "receipt_id": receipt_id,
        "receipt_type": receipt_type,
        "route_id": route_id,
        "issued_at": issued_at or _current_iso_z(),
        "stale_after": stale_after,
        "signed_by": "operator",
        "evidence_refs": [f"test:{receipt_id}"],
        "quality_floors": quality_floors or [],
        "task_ids": task_ids or [],
        "mutation_surfaces": mutation_surfaces or [],
    }
    payload["signed_payload_sha256"] = payload_hash or route_authority_receipt_payload_hash(payload)
    target_dir = receipt_dir / "route-authority"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{receipt_id}.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return target


def _mark_platform_receipt_account_live_quota_observed(
    receipt_dir: Path,
    *,
    platform: str = "codex",
) -> None:
    receipt_path = receipt_dir / f"{platform}.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    quota = payload["quota"]
    quota["status"] = "observed"
    quota["reason_codes"] = []
    quota["evidence_refs"] = list(
        dict.fromkeys(
            [
                *quota.get("evidence_refs", []),
                f"test:{platform}:account-live-quota:observed",
            ]
        )
    )
    payload["known_unknowns"] = [
        item
        for item in payload.get("known_unknowns", [])
        if "Account-live subscription quota" not in item
    ]
    receipt_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


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


def test_future_platform_receipt_is_not_fresh(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir)},
        now="2026-07-05T15:00:00Z",
    )
    assert result.returncode == 0, result.stderr
    receipt = load_platform_capability_receipt(tmp_path / "codex.json")

    assert receipt_is_fresh(receipt, now=NOW_DT) is False


def test_fresh_subscription_receipt_allows_local_dispatch_without_account_live_quota_api(
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
    assert "policy_launch" in decision.reason_codes
    assert "account_live_quota_evidence_absent" not in decision.reason_codes
    assert "capability_availability_degraded" not in decision.reason_codes


def test_antigrav_receipt_cannot_reintroduce_excised_route(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "agy", "1.0.0")
    wrapper = tmp_path / "home" / ".local" / "bin" / "hapax-antigrav"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)

    for platform in ("antigrav", "Antigrav", "antigravity", "gemini-cli"):
        result = _run_receipts(
            tmp_path,
            env={"PATH": str(bin_dir), "HOME": str(tmp_path / "home")},
            platform=platform,
        )

        assert result.returncode == 2
        assert f"platform '{platform.lower()}' is retired/excised" in result.stderr
        assert "agy.review.direct" in result.stderr
        assert not (tmp_path / f"{platform}.json").exists()


def test_agy_receipt_records_live_review_route_without_unblocking_quota(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    home_dir = tmp_path / "home"
    bin_dir.mkdir()
    bundled_cli_ref = (
        home_dir
        / ".gemini"
        / "antigravity-cli"
        / "builtin"
        / "skills"
        / "antigravity_guide"
        / "references"
        / "cli.md"
    )
    bundled_cli_ref.parent.mkdir(parents=True)
    bundled_cli_ref.write_text("# agy CLI reference\n", encoding="utf-8")
    _fake_binary(bin_dir, "agy", "1.0.10")

    result = _run_receipts(
        tmp_path,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(home_dir)},
        platform="agy",
        now="2026-07-05T14:51:11Z",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["receipts"][0]["platform"] == "agy"
    assert payload["receipts"][0]["cli_available"] is True
    assert payload["receipts"][0]["wrapper_exists"] is True
    assert payload["receipts"][0]["quota_status"] == "unobservable"
    receipt = json.loads((tmp_path / "agy.json").read_text(encoding="utf-8"))
    assert receipt["platform"] == "agy"
    assert receipt["routes"] == ["agy.review.direct"]
    assert receipt["cli"]["version"] == "1.0.10"
    assert receipt["quota"]["reason_codes"] == ["account_live_quota_receipt_absent"]
    config_refs = {item["path"]: item for item in receipt["config_refs"]}
    assert (
        config_refs["~/.gemini/antigravity-cli/builtin/skills/antigravity_guide/references/cli.md"][
            "exists"
        ]
        is True
    )
    assert all(item["redacted"] is True for item in receipt["config_refs"])

    registry = load_platform_capability_registry(
        REGISTRY,
        receipt_dir=tmp_path,
        now=datetime(2026, 7, 5, 14, 52, tzinfo=UTC),
    )
    route = registry.require("agy.review.direct")
    assert route.route_state.value == "blocked"
    assert "agy_review_seat_receipt_admission_required" not in route.blocked_reasons
    assert "route_specific_quota_receipt_absent" in route.blocked_reasons


def test_agy_receipt_requires_executable_review_wrapper(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "agy", "1.0.10")
    wrapper = tmp_path / "non-executable-hapax-agy-reviewer"
    wrapper.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    wrapper.chmod(stat.S_IRUSR | stat.S_IWUSR)
    registry_payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for route in registry_payload["routes"]:
        if route["route_id"] == "agy.review.direct":
            route["sanctioned_wrapper"] = str(wrapper)
            break
    else:  # pragma: no cover - fixture invariant
        raise AssertionError("agy.review.direct route missing from registry fixture")
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    registry = registry_dir / "platform-capability-registry.json"
    registry.write_text(json.dumps(registry_payload), encoding="utf-8")

    result = _run_receipts(
        tmp_path,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path / "home")},
        platform="agy",
        registry=registry,
        now="2026-07-05T14:51:11Z",
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "agy.json").read_text(encoding="utf-8"))
    assert receipt["wrapper"]["exists"] is True
    assert receipt["wrapper"]["executable"] is False
    assert receipt["capability"]["status"] == "blocked"
    assert "sanctioned_wrapper_not_executable" in receipt["capability"]["reason_codes"]
    assert receipt["resource"]["status"] == "blocked"
    assert receipt["resource"]["reason_codes"] == ["wrapper_not_executable"]

    registry_with_receipt = load_platform_capability_registry(
        registry,
        receipt_dir=tmp_path,
        now=datetime(2026, 7, 5, 14, 52, tzinfo=UTC),
    )
    route = registry_with_receipt.require("agy.review.direct")
    assert route.route_state.value == "blocked"
    assert "agy_review_seat_receipt_admission_required" in route.blocked_reasons
    assert "sanctioned_wrapper_not_executable" in route.blocked_reasons
    assert "wrapper_not_executable" in route.blocked_reasons


def test_api_provider_gateway_receipt_allows_paid_gateway_dispatch(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "python3", f"Python 3.12.3 api_key={SECRET}")

    result = _run_receipts(
        tmp_path,
        env={"PATH": str(bin_dir), "OPENAI_API_KEY": SECRET},
        now=API_NOW,
        platform="api",
    )

    assert result.returncode == 0, result.stderr
    receipt_text = (tmp_path / "api.json").read_text(encoding="utf-8")
    assert SECRET not in receipt_text
    receipt = json.loads(receipt_text)
    assert "api.headless.provider_gateway" in receipt["routes"]
    assert "api.headless.openrouter" in receipt["routes"]
    assert receipt["quota"]["status"] == "unobservable"
    assert receipt["known_unknowns"][0].startswith("Provider spend is authorized")

    registry = load_platform_capability_registry(REGISTRY, receipt_dir=tmp_path, now=API_NOW_DT)
    gateway = registry.require("api.headless.provider_gateway")
    cloud = registry.require("api.headless.api_frontier")
    openrouter = registry.require("api.headless.openrouter")

    assert gateway.route_state.value == "active"
    assert "provider_budget_receipt_absent" not in gateway.blocked_reasons
    assert "provider_gateway_evidence_absent" not in gateway.blocked_reasons
    assert cloud.route_state.value == "blocked"
    assert "cloud_burst_release_gate_absent" in cloud.blocked_reasons
    assert openrouter.route_state.value == "blocked"
    assert "capabilityio_measurement_absent" in openrouter.blocked_reasons
    assert "openrouter_paid_budget_receipt_absent" in openrouter.blocked_reasons

    sources = load_dispatch_policy_sources(
        registry_path=REGISTRY,
        quota_ledger_path=_fresh_quota_ledger(tmp_path, captured_at=API_NOW),
        receipt_dir=tmp_path,
        now=API_NOW_DT,
    )
    task_fields = {
        "status": "claimed",
        "assigned_to": "cctv-gateway",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "PROVIDER-GATEWAY-RECEIPT-TEST",
        "priority": "p0",
        "wsjf": 12,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "provider_spend",
        "mutation_scope_refs": ["~/llm-stack/litellm-config.yaml"],
        "risk_flags": {"provider_billing_sensitive": True},
    }
    request = build_dispatch_request(
        task_id="provider-gateway-receipt-present",
        lane="cctv-gateway",
        platform="api",
        mode="headless",
        profile="provider_gateway",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
        now=API_NOW_DT,
    )

    decision = evaluate_dispatch_policy(request, now=API_NOW_DT)

    assert request.capability is not None
    assert request.capability.paid_provider == "google"
    assert request.capability.paid_profile == "frontier-fast"
    assert request.quota is not None
    assert "tb-20260510-anthropic-api-steady-state" in request.quota.evidence_refs
    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert "policy_launch" in decision.reason_codes


def test_glmcp_known_unknowns_disclose_secret_read_without_persistence() -> None:
    namespace = runpy.run_path(str(SCRIPT))

    unknowns = namespace["known_unknowns_for"]("glmcp")

    assert any("may read the pass-backed secret" in item for item in unknowns)
    assert any("never persists the secret value" in item for item in unknowns)
    assert not any("never reads secret values" in item for item in unknowns)


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
    _mark_platform_receipt_account_live_quota_observed(tmp_path, platform="claude")
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
    _mark_platform_receipt_account_live_quota_observed(tmp_path, platform="claude")
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


def _runtime_dispatch_request(sources, *, task_id: str):  # type: ignore[no-untyped-def]
    task_fields = {
        "status": "claimed",
        "assigned_to": "codex-main",
        "authority_case": "CASE-SDLC-REFORM-001",
        "authority_item": "MINIO-OLD-ROOT-CLEANUP",
        "priority": "p0",
        "wsjf": 35,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "runtime",
        "mutation_scope_refs": ["/var/lib/hapax/minio"],
    }
    return build_dispatch_request(
        task_id=task_id,
        lane="codex-main",
        platform="codex",
        mode="headless",
        profile="full",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
        route_authority_receipts=sources.route_authority_receipts,
    )


def test_runtime_actuation_receipt_allows_task_bound_runtime_dispatch(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)}, now=_current_iso_z())
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="minio-cleanup-runtime-test",
        route_id="codex.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["runtime"],
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    )
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert any(
        reason.startswith("route-authority-receipt:runtime_actuation:codex.headless.full:")
        for reason in decision.reason_codes
    )


def test_runtime_actuation_receipt_wrong_task_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)}, now=_current_iso_z())
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="wrong-task-runtime-test",
        route_id="codex.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["some-other-task"],
        mutation_surfaces=["runtime"],
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    )
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_task_mismatch" in decision.reason_codes


def test_runtime_actuation_receipt_wrong_route_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)}, now=_current_iso_z())
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="wrong-route-runtime-test",
        route_id="claude.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["runtime"],
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    )
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_route_mismatch" in decision.reason_codes


def test_runtime_actuation_receipt_wrong_surface_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)}, now=_current_iso_z())
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="wrong-surface-runtime-test",
        route_id="codex.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["source"],
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    )
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_surface_mismatch" in decision.reason_codes


def test_runtime_actuation_receipt_stale_fails_closed_as_absent(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)}, now=_current_iso_z())
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="stale-runtime-test",
        route_id="codex.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["runtime"],
        issued_at="2026-01-01T00:00:00Z",
        stale_after="1h",
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    )
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_receipt_absent" in decision.reason_codes


def test_runtime_actuation_receipt_stale_on_request_fails_closed(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)}, now="2026-06-05T11:00:00Z")
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)

    payload: dict[str, object] = {
        "route_authority_receipt_schema": 1,
        "receipt_id": "manually-stale-runtime-test",
        "receipt_type": "runtime_actuation",
        "route_id": "codex.headless.full",
        "issued_at": "2026-06-05T10:00:00Z",
        "stale_after": "1h",
        "signed_by": "operator",
        "evidence_refs": ["test:manually-stale-runtime-test"],
        "quality_floors": [],
        "task_ids": ["appendix-podium-minio-old-root-cleanup-20260605"],
        "mutation_surfaces": ["runtime"],
    }
    payload["signed_payload_sha256"] = route_authority_receipt_payload_hash(payload)
    stale_receipt = RouteAuthorityReceipt.model_validate(payload)
    sources = load_dispatch_policy_sources(
        registry_path=REGISTRY,
        receipt_dir=tmp_path,
        now=datetime.fromisoformat("2026-06-05T11:00:00+00:00"),
    )
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    ).model_copy(update={"route_authority_receipts": (stale_receipt,)})

    decision = evaluate_dispatch_policy(
        request,
        now=datetime.fromisoformat("2026-06-05T11:01:00+00:00"),
    )

    assert decision.action is DispatchAction.REFUSE
    assert "runtime_actuation_receipt_stale" in decision.reason_codes


def test_runtime_actuation_receipt_allows_dimensional_runtime_candidate(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    result = _run_receipts(tmp_path, env={"PATH": str(bin_dir)}, now=_current_iso_z())
    assert result.returncode == 0, result.stderr
    _mark_platform_receipt_account_live_quota_observed(tmp_path)
    _write_route_authority_receipt(
        tmp_path,
        receipt_id="minio-cleanup-runtime-dimensional-test",
        route_id="codex.headless.full",
        receipt_type="runtime_actuation",
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["runtime"],
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _runtime_dispatch_request(
        sources, task_id="appendix-podium-minio-old-root-cleanup-20260605"
    )
    decision = evaluate_dispatch_policy(request, candidate_requests=(request,))

    assert decision.action is DispatchAction.LAUNCH
    assert decision.dimensional_receipt is not None
    [candidate] = decision.dimensional_receipt.candidates
    assert not any(veto.code == "mutation_surface_mismatch" for veto in candidate.vetoes)


MINT_SCRIPT = REPO_ROOT / "scripts" / "hapax-mint-route-authority-receipt"


def _mint_route_authority_receipt(
    receipt_dir: Path,
    *,
    receipt_type: str,
    route_id: str,
    quality_floors: list[str] | None = None,
    now: str | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [
        sys.executable,
        str(MINT_SCRIPT),
        "--receipt-type",
        receipt_type,
        "--route-id",
        route_id,
        "--receipt-dir",
        str(receipt_dir),
        "--json",
    ]
    for floor in quality_floors or []:
        args += ["--quality-floor", floor]
    if now:
        args += ["--now", now]
    return subprocess.run(args, text=True, capture_output=True, check=False)


def _fresh_claude_platform_receipt(tmp_path: Path) -> None:
    """Write a fresh claude platform-capability receipt (clears quota/freshness)."""

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
    _mark_platform_receipt_account_live_quota_observed(tmp_path, platform="claude")


def _opus_dispatch_request(sources):  # type: ignore[no-untyped-def]
    task_fields = {
        "status": "claimed",
        "assigned_to": "eta",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "authority_item": "OPUS-REACHABILITY",
        "priority": "p0",
        "wsjf": 38,
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["shared/dispatcher_policy.py"],
    }
    return build_dispatch_request(
        task_id="opus-reachability-minted",
        lane="eta",
        platform="claude",
        mode="headless",
        profile="opus",
        task_fields=task_fields,
        registry=sources.registry,
        registry_error=sources.registry_error,
        quota_ledger=sources.quota_ledger,
        quota_error=sources.quota_error,
    )


def test_minted_opus_receipt_undegrades_route_to_launch_via_cli(tmp_path: Path) -> None:
    """The mint CLI produces a receipt that drives opus to LAUNCH end-to-end.

    Mirrors the live dispatch policy read-path (hapax-methodology-dispatch
    lines ~1229-1248): load_dispatch_policy_sources -> build_dispatch_request
    -> evaluate_dispatch_policy.
    """
    _fresh_claude_platform_receipt(tmp_path)

    mint = _mint_route_authority_receipt(
        tmp_path,
        receipt_type="opus_model_entitlement",
        route_id="claude.headless.opus",
        now=_current_iso_z(),
    )
    assert mint.returncode == 0, mint.stderr
    minted = json.loads(mint.stdout)
    assert Path(minted["receipt_path"]).exists()
    assert minted["receipt_path"].endswith(".json")
    assert minted["receipt_reference"].startswith(
        "route-authority-receipt:opus_model_entitlement:claude.headless.opus:"
    )

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _opus_dispatch_request(sources)
    decision = evaluate_dispatch_policy(request)

    assert request.capability is not None
    assert any(
        record.startswith("route-authority-receipt:opus_model_entitlement:")
        for record in request.capability.explicit_equivalence_records
    )
    assert decision.action is DispatchAction.LAUNCH
    assert decision.route_policy_green is True
    assert "policy_launch" in decision.reason_codes


def test_minted_opus_receipt_unreachable_without_receipt(tmp_path: Path) -> None:
    """Guard: without the minted receipt, the opus route stays HELD/REFUSED."""

    _fresh_claude_platform_receipt(tmp_path)

    sources = load_dispatch_policy_sources(registry_path=REGISTRY, receipt_dir=tmp_path)
    request = _opus_dispatch_request(sources)
    decision = evaluate_dispatch_policy(request)

    assert decision.action is not DispatchAction.LAUNCH


def test_live_read_path_defaults_receipt_dir_to_env_for_opus(tmp_path: Path) -> None:
    """The live read-path (no explicit receipt_dir) picks up receipts via env.

    Proves the dispatch CLI call site — which passes no receipt_dir — un-degrades
    opus once HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR points at the minted dir.
    """
    _fresh_claude_platform_receipt(tmp_path)
    mint = _mint_route_authority_receipt(
        tmp_path,
        receipt_type="opus_model_entitlement",
        route_id="claude.headless.opus",
        now=_current_iso_z(),
    )
    assert mint.returncode == 0, mint.stderr

    with patch.dict(os.environ, {PLATFORM_CAPABILITY_RECEIPT_DIR_ENV: str(tmp_path)}):
        sources = load_dispatch_policy_sources(registry_path=REGISTRY)
    request = _opus_dispatch_request(sources)
    decision = evaluate_dispatch_policy(request)

    assert decision.action is DispatchAction.LAUNCH
    assert "policy_launch" in decision.reason_codes
