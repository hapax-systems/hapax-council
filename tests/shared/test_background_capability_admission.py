"""Tests for background capability admission through the real dispatch policy."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from shared.fix_capabilities.background_admission import admit_background_capability

NOW = datetime(2026, 6, 4, 16, 30, tzinfo=UTC)
QUOTA_FIXTURE = Path("config/quota-spend-ledger-fixtures.json")


def _provider_task_fields() -> dict[str, object]:
    return {
        "task_id": "task-background-model",
        "status": "claimed",
        "assigned_to": "background",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "parent_spec": "spec.md",
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "provider_spend",
        "mutation_scope_refs": ["background:model"],
        "risk_flags": {},
        "kind": "hardening",
    }


def _write_provider_gateway_receipt(receipt_dir: Path) -> None:
    observed = NOW.isoformat().replace("+00:00", "Z")
    receipt = {
        "receipt_schema": 1,
        "receipt_id": "test-api-provider-gateway",
        "platform": "api",
        "routes": ["api.headless.provider_gateway"],
        "observed_at": observed,
        "stale_after": "1h",
        "cli": {"binary": "litellm", "available": True, "version": "test"},
        "wrapper": {
            "path": "scripts/hapax-methodology-dispatch",
            "exists": True,
            "executable": True,
        },
        "config_refs": [],
        "tool_state": [],
        "mcp_status": [],
        "capability": {
            "status": "observed",
            "source": "test",
            "observed_at": observed,
            "stale_after": "1h",
            "evidence_refs": ["test:capability"],
            "reason_codes": [],
        },
        "resource": {
            "status": "observed",
            "source": "test",
            "observed_at": observed,
            "stale_after": "1h",
            "evidence_refs": ["test:resource"],
            "reason_codes": [],
        },
        "quota": {
            "status": "unobservable",
            "source": "test",
            "observed_at": observed,
            "stale_after": "1h",
            "evidence_refs": [],
            "reason_codes": ["quota_telemetry_unknown"],
        },
        "provider_docs": {
            "refs": ["test:provider-docs"],
            "fetched_at": observed,
            "stale_after": "30d",
            "fetch_status": "observed",
        },
        "known_unknowns": [],
    }
    (receipt_dir / "api.json").write_text(json.dumps(receipt), encoding="utf-8")


def test_background_model_call_refuses_without_platform_receipt(tmp_path: Path) -> None:
    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        task_fields=_provider_task_fields(),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is False
    assert admission.policy_outcome == "hold"
    assert "unsupported_route" not in admission.reason_codes
    assert "provider_gateway_evidence_absent" in admission.denial_summary()


def test_background_model_call_admits_with_platform_and_budget_receipts(tmp_path: Path) -> None:
    _write_provider_gateway_receipt(tmp_path)

    admission = admit_background_capability(
        capability_name="studio.scene_classifier.llm",
        route_id="api.headless.provider_gateway",
        model_alias="gemini-flash",
        task_fields=_provider_task_fields(),
        mutation_surface="provider_spend",
        quality_floor="frontier_required",
        authority_level="authoritative",
        receipt_dir=tmp_path,
        quota_ledger_path=QUOTA_FIXTURE,
        now=NOW,
        write_receipt=False,
    )

    assert admission.admitted is True
    assert admission.policy_outcome == "launch"
    assert admission.reason_codes == ("policy_launch",)
    assert admission.quota_evidence_refs == ("tb-20260510-anthropic-api-steady-state",)
    assert admission.model_descriptor["execution_descriptor"]["model_id"] == (
        "gemini-3.1-pro-preview"
    )
