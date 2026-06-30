from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from agents.deliberative_council.capability_admission import (
    CapabilityAdmissionReceipt,
    CapabilityDescriptor,
    admit_capability,
    admit_model_alias,
    admit_tool,
    capability_admission_event_scope,
    record_capability_admission,
    route_resource_admission_state,
)
from shared.quota_spend_ledger import QUOTA_SPEND_LEDGER_FIXTURES, CapacityPool

REPO_ROOT = Path(__file__).resolve().parents[3]
PLATFORM_CAPABILITY_REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"


def _write_test_ledger(tmp_path: Path) -> Path:
    payload = json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8"))
    payload["ledger_id"] = "quota-spend-ledger-cctv-test"
    payload["captured_at"] = "2026-06-01T00:00:00Z"
    payload["paid_api_budget_freshness_ttl_s"] = 86400
    for budget in payload["transition_budgets"]:
        if budget["budget_id"] == "tb-20260510-anthropic-api-steady-state":
            budget["expires_at"] = "2026-07-10T00:00:00Z"
            budget["providers_allowed"] = ["anthropic", "google"]
            budget["profiles_allowed"] = ["frontier-full", "frontier-fast", "coding"]
            budget["task_classes_allowed"] = ["research"]
            budget["quality_floors_allowed"] = ["frontier_required"]
    target = tmp_path / "quota-spend-ledger.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _write_platform_registry(
    tmp_path: Path,
    *,
    local_worker_blocked: bool,
    provider_gateway_blocked: bool | None = None,
) -> Path:
    payload = json.loads(PLATFORM_CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    local_worker = next(
        route for route in payload["routes"] if route["route_id"] == "local_tool.local.worker"
    )
    if local_worker_blocked:
        local_worker["route_state"] = "blocked"
        local_worker["blocked_reasons"] = [
            "local_inference_worker_receipt_admission_required",
            "fresh_capability_evidence_absent",
            "quota_telemetry_unknown",
        ]
        local_worker["freshness"]["capability_checked_at"] = None
        local_worker["freshness"]["quota_checked_at"] = None
        local_worker["freshness"]["evidence"]["capability"] = {
            "evidence_refs": [],
            "blocked_reasons": ["fresh_capability_evidence_absent"],
        }
        local_worker["freshness"]["evidence"]["quota"] = {
            "evidence_refs": [],
            "blocked_reasons": ["quota_telemetry_unknown"],
        }
    else:
        local_worker["route_state"] = "active"
        local_worker["blocked_reasons"] = []
        local_worker["freshness"]["capability_checked_at"] = "2026-06-01T00:00:00Z"
        local_worker["freshness"]["quota_checked_at"] = "2026-06-01T00:00:00Z"
        local_worker["freshness"]["evidence"]["capability"] = {
            "evidence_refs": ["test:local-worker-capability"],
            "blocked_reasons": [],
        }
        local_worker["freshness"]["evidence"]["quota"] = {
            "evidence_refs": ["test:local-worker-quota"],
            "blocked_reasons": [],
        }
    if provider_gateway_blocked is not None:
        gateway = next(
            route
            for route in payload["routes"]
            if route["route_id"] == "api.headless.provider_gateway"
        )
        if provider_gateway_blocked:
            gateway["route_state"] = "blocked"
            gateway["blocked_reasons"] = [
                "provider_gateway_evidence_absent",
                "provider_budget_receipt_absent",
            ]
            gateway["freshness"]["capability_checked_at"] = None
            gateway["freshness"]["quota_checked_at"] = None
            gateway["freshness"]["resource_checked_at"] = None
            gateway["freshness"]["evidence"]["capability"] = {
                "evidence_refs": [],
                "blocked_reasons": ["provider_gateway_evidence_absent"],
            }
            gateway["freshness"]["evidence"]["quota"] = {
                "evidence_refs": [],
                "blocked_reasons": ["provider_budget_receipt_absent"],
            }
            gateway["freshness"]["evidence"]["resource"] = {
                "evidence_refs": [],
                "blocked_reasons": ["gateway_resource_receipt_absent"],
            }
        else:
            gateway["route_state"] = "active"
            gateway["blocked_reasons"] = []
            gateway["freshness"]["capability_checked_at"] = "2026-06-01T00:00:00Z"
            gateway["freshness"]["quota_checked_at"] = "2026-06-01T00:00:00Z"
            gateway["freshness"]["resource_checked_at"] = "2026-06-01T00:00:00Z"
            gateway["freshness"]["evidence"]["capability"] = {
                "evidence_refs": ["test:provider-gateway-capability"],
                "blocked_reasons": [],
            }
            gateway["freshness"]["evidence"]["quota"] = {
                "evidence_refs": ["test:provider-gateway-quota"],
                "blocked_reasons": [],
            }
            gateway["freshness"]["evidence"]["resource"] = {
                "evidence_refs": ["test:provider-gateway-resource"],
                "blocked_reasons": [],
            }
    target = tmp_path / "platform-capability-registry.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_paid_model_alias_gets_admitted_receipt(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    registry = _write_platform_registry(
        tmp_path, local_worker_blocked=False, provider_gateway_blocked=False
    )
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(registry))
    monkeypatch.setenv("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW", "2026-06-01T00:10:00Z")

    admission = admit_model_alias("opus")

    assert admission.admitted is True
    assert admission.capability_id == "cctv.model.opus"
    assert admission.admission_action == "admitted"
    assert admission.receipt_ref.startswith("cctv-capability-admission:")
    assert "tb-20260510-anthropic-api-steady-state" in admission.receipt_refs
    assert "platform-capability-registry:api.headless.provider_gateway" in admission.receipt_refs


def test_paid_model_alias_refuses_blocked_platform_route(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    registry = _write_platform_registry(
        tmp_path, local_worker_blocked=False, provider_gateway_blocked=True
    )
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(registry))
    monkeypatch.setenv("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW", "2026-06-01T00:10:00Z")

    admission = admit_model_alias("opus")

    assert admission.admitted is False
    assert admission.capability_id == "cctv.model.opus"
    assert "provider_gateway_evidence_absent" in admission.reason_codes
    assert "provider_budget_receipt_absent" in admission.reason_codes
    assert "gateway_resource_receipt_absent" in admission.reason_codes
    assert "platform-capability-registry:api.headless.provider_gateway" in admission.receipt_refs


def test_paid_model_alias_refuses_missing_platform_route(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    registry = _write_platform_registry(
        tmp_path, local_worker_blocked=False, provider_gateway_blocked=False
    )
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(registry))
    monkeypatch.setenv("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW", "2026-06-01T00:10:00Z")
    descriptor = CapabilityDescriptor(
        capability_id="cctv.model.synthetic",
        route_id="synthetic-paid-route",
        provider="anthropic",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="frontier-full",
        task_class="research",
        quality_floor="frontier_required",
        estimated_cost_usd=Decimal("0.01"),
        platform_route_id="api.headless.missing-provider-gateway",
    )

    admission = admit_capability(descriptor)

    assert admission.admitted is False
    assert admission.capability_id == "cctv.model.synthetic"
    assert "platform_route_missing:api.headless.missing-provider-gateway" in admission.reason_codes


def test_receipt_identity_binds_decision_inputs(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    registry = _write_platform_registry(
        tmp_path, local_worker_blocked=False, provider_gateway_blocked=False
    )
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(registry))
    monkeypatch.delenv("HAPAX_METHODOLOGY_DISPATCH_TASK", raising=False)
    checked_at = datetime(2026, 6, 1, 0, 10, tzinfo=UTC)
    base = CapabilityDescriptor(
        capability_id="cctv.model.opus",
        route_id="claude-opus",
        provider="anthropic",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="frontier-full",
        task_class="research",
        quality_floor="frontier_required",
        estimated_cost_usd=Decimal("0.01"),
        platform_route_id="api.headless.provider_gateway",
    )
    faster_profile = CapabilityDescriptor(
        capability_id=base.capability_id,
        route_id=base.route_id,
        provider=base.provider,
        capacity_pool=base.capacity_pool,
        profile="frontier-fast",
        task_class=base.task_class,
        quality_floor=base.quality_floor,
        estimated_cost_usd=base.estimated_cost_usd,
        platform_route_id=base.platform_route_id,
    )

    first = admit_capability(base, now=checked_at)
    changed_profile = admit_capability(faster_profile, now=checked_at)
    changed_time = admit_capability(base, now=datetime(2026, 6, 1, 0, 11, tzinfo=UTC))

    assert first.admitted is True
    assert first.profile == "frontier-full"
    assert first.task_class == "research"
    assert first.quality_floor == "frontier_required"
    assert first.estimated_cost_usd == "0.01"
    assert first.evaluated_at == checked_at
    assert first.receipt_id != changed_profile.receipt_id
    assert first.receipt_id != changed_time.receipt_id


def test_receipt_captures_dispatch_authority_context(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    registry = _write_platform_registry(
        tmp_path, local_worker_blocked=False, provider_gateway_blocked=False
    )
    task_root = tmp_path / "tasks"
    active = task_root / "active"
    active.mkdir(parents=True)
    task = active / "cc-task-cctv-test.md"
    task.write_text(
        "---\n"
        "type: cc-task\n"
        "task_id: cc-task-cctv-test\n"
        "authority_case: CASE-CAPACITY-ROUTING-001\n"
        "authority_item: cctv-admission-slice\n"
        "parent_spec: /tmp/parent-spec.md\n"
        "---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(registry))
    monkeypatch.setenv("HAPAX_CC_TASK_ROOT", str(task_root))
    monkeypatch.setenv("HAPAX_METHODOLOGY_DISPATCH_TASK", "cc-task-cctv-test")
    monkeypatch.setenv("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW", "2026-06-01T00:10:00Z")

    admission = admit_model_alias("opus")

    assert admission.authority_task_id == "cc-task-cctv-test"
    assert admission.authority_case == "CASE-CAPACITY-ROUTING-001"
    assert admission.authority_item == "cctv-admission-slice"
    assert admission.authority_parent_spec == "/tmp/parent-spec.md"
    assert admission.authority_source_ref == str(task)


def test_unbudgeted_provider_refuses_before_invocation(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    registry = _write_platform_registry(
        tmp_path, local_worker_blocked=False, provider_gateway_blocked=False
    )
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(registry))
    monkeypatch.setenv("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW", "2026-06-01T00:10:00Z")

    admission = admit_tool("web_verify")

    assert admission.admitted is False
    assert admission.capability_id == "cctv.tool.web_verify"
    assert "no_matching_transitionbudget" in admission.reason_codes


def test_local_tool_admission_uses_local_resource_snapshot(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    registry = _write_platform_registry(tmp_path, local_worker_blocked=False)
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(registry))
    monkeypatch.delenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", raising=False)
    monkeypatch.setenv("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW", "2026-06-01T00:10:00Z")

    admission = admit_tool("qdrant_lookup")

    assert admission.admitted is True
    assert admission.capability_id == "cctv.tool.qdrant_lookup"
    assert "quota.local_resource_state:green" in admission.receipt_refs


def test_local_tool_admission_refuses_registry_blocked_route(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    registry = _write_platform_registry(tmp_path, local_worker_blocked=True)
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(registry))
    monkeypatch.delenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", raising=False)
    monkeypatch.setenv("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW", "2026-06-01T00:10:00Z")

    admission = admit_tool("qdrant_lookup")

    assert admission.admitted is False
    assert admission.capability_id == "cctv.tool.qdrant_lookup"
    assert "local_inference_worker_receipt_admission_required" in admission.reason_codes
    assert "fresh_capability_evidence_absent" in admission.reason_codes
    assert "quota_telemetry_unknown" in admission.reason_codes
    assert "platform-capability-registry:local_tool.local.worker" in admission.receipt_refs


def test_local_model_admission_is_bound_to_route_snapshot(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW", "2026-06-01T00:10:00Z")

    local_fast = admit_model_alias("local-fast")
    appendix_fast = admit_model_alias("appendix-fast")

    assert local_fast.admitted is True
    assert local_fast.route_id == "local-fast"
    assert "litellm:gateway-4000-local-fast-route-healthy" in local_fast.receipt_refs
    assert appendix_fast.admitted is False
    assert appendix_fast.route_id == "appendix-fast"
    assert "local_resource_snapshot_missing" in appendix_fast.reason_codes
    assert appendix_fast.quota_evidence_refs == ()
    assert "litellm:gateway-4000-local-fast-route-healthy" not in appendix_fast.receipt_refs


def test_missing_ledger_refuses_fail_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(tmp_path / "missing.json"))

    admission = admit_model_alias("opus")

    assert admission.admitted is False
    assert admission.admission_action == "refused"
    assert admission.reason_codes[0].startswith("quota_spend_ledger_unavailable:")


def test_missing_live_ledger_does_not_admit_from_fixture_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", raising=False)
    monkeypatch.delenv("HAPAX_QUOTA_SPEND_LEDGER", raising=False)
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(tmp_path / "missing-live.json"))
    monkeypatch.setenv("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW", "2026-06-30T00:00:00Z")

    admission = admit_tool("qdrant_lookup")

    assert admission.admitted is False
    assert admission.capability_id == "cctv.tool.qdrant_lookup"
    assert admission.reason_codes[0].startswith("quota_spend_ledger_unavailable:")


def test_missing_descriptor_refuses_with_receipt(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", raising=False)

    admission = admit_tool("not_a_council_tool")

    assert admission.admitted is False
    assert admission.capability_id == "cctv.tool.not_a_council_tool"
    assert "capability_descriptor_missing" in admission.reason_codes
    assert admission.receipt_ref.startswith("cctv-capability-admission:")


def test_route_resource_admission_state_distinguishes_partial() -> None:
    admitted = CapabilityAdmissionReceipt(
        receipt_id="admitted",
        receipt_ref="cctv-capability-admission:admitted",
        capability_id="cctv.model.opus",
        route_id="claude-opus",
        provider="anthropic",
        capacity_pool="api_paid_spend",
        admission_action="admitted",
        admitted=True,
        receipt_refs=("cctv-capability-admission:admitted",),
    )
    refused = CapabilityAdmissionReceipt(
        receipt_id="refused",
        receipt_ref="cctv-capability-admission:refused",
        capability_id="cctv.model.web-research",
        route_id="web-research",
        provider="perplexity",
        capacity_pool="api_paid_spend",
        admission_action="refused",
        admitted=False,
        reason_codes=("no_matching_transitionbudget",),
        receipt_refs=("cctv-capability-admission:refused",),
    )

    assert route_resource_admission_state(()) == "missing"
    assert route_resource_admission_state((admitted, refused)) == "partial_admitted"
    assert route_resource_admission_state((refused,)) == "refused"


async def test_capability_admission_event_scope_is_task_local() -> None:
    first = CapabilityAdmissionReceipt(
        receipt_id="first",
        receipt_ref="cctv-capability-admission:first",
        capability_id="cctv.model.opus",
        route_id="claude-opus",
        provider="anthropic",
        capacity_pool="api_paid_spend",
        admission_action="admitted",
        admitted=True,
        receipt_refs=("cctv-capability-admission:first",),
    )
    second = CapabilityAdmissionReceipt(
        receipt_id="second",
        receipt_ref="cctv-capability-admission:second",
        capability_id="cctv.model.gemini-3-pro",
        route_id="gemini-pro",
        provider="google",
        capacity_pool="api_paid_spend",
        admission_action="admitted",
        admitted=True,
        receipt_refs=("cctv-capability-admission:second",),
    )

    async def _record(admission: CapabilityAdmissionReceipt) -> list[CapabilityAdmissionReceipt]:
        events: list[CapabilityAdmissionReceipt] = []
        with capability_admission_event_scope(events):
            await asyncio.sleep(0)
            record_capability_admission(admission)
            await asyncio.sleep(0)
        return events

    first_events, second_events = await asyncio.gather(_record(first), _record(second))

    assert first_events == [first]
    assert second_events == [second]
