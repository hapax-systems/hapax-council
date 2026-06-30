from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agents.deliberative_council.capability_admission import (
    CapabilityAdmissionReceipt,
    admit_model_alias,
    admit_tool,
    capability_admission_event_scope,
    record_capability_admission,
    route_resource_admission_state,
)
from shared.quota_spend_ledger import QUOTA_SPEND_LEDGER_FIXTURES

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
    target = tmp_path / "platform-capability-registry.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_paid_model_alias_gets_admitted_receipt(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
    monkeypatch.setenv("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW", "2026-06-01T00:10:00Z")

    admission = admit_model_alias("opus")

    assert admission.admitted is True
    assert admission.capability_id == "cctv.model.opus"
    assert admission.admission_action == "admitted"
    assert admission.receipt_ref.startswith("cctv-capability-admission:")
    assert "tb-20260510-anthropic-api-steady-state" in admission.receipt_refs


def test_unbudgeted_provider_refuses_before_invocation(tmp_path: Path, monkeypatch) -> None:
    ledger = _write_test_ledger(tmp_path)
    monkeypatch.setenv("HAPAX_CCTV_QUOTA_SPEND_LEDGER", str(ledger))
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
