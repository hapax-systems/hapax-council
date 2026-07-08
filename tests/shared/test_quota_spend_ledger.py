"""Tests for inert quota/spend ledger models."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from shared.quota_spend_ledger import (
    DEFAULT_QUOTA_SPEND_LEDGER_LIVE,
    QUOTA_SPEND_LEDGER_FIXTURES,
    QUOTA_SPEND_LEDGER_LIVE_ENV,
    RECEIPT_BOUNDED_SUBSCRIPTION_PROVIDERS,
    RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES,
    ArtifactProvenanceRecord,
    BootstrapDependencyState,
    BudgetLifecycleState,
    DependencyState,
    Effort,
    ModelId,
    PaidApiBudgetState,
    PaidRouteRequest,
    Quantization,
    QuotaSpendLedger,
    SpendGateDecisionState,
    SpendReceipt,
    SpendReconciliationState,
    SubscriptionQuotaState,
    SupportArtifactAuthority,
    SupportArtifactDisposition,
    build_dashboard,
    evaluate_paid_route_eligibility,
    has_successful_task_scoped_glmcp_payg_review_spend,
    load_quota_spend_ledger,
    load_quota_spend_ledger_resolved,
    subscription_quota_state_for_route,
    successful_task_scoped_glmcp_payg_review_spend_receipts,
)

NOW = datetime(2026, 5, 17, 8, 0, 0, tzinfo=UTC)
CURRENT_REFRESH_NOW = datetime(2026, 6, 4, 17, 10, 0, tzinfo=UTC)
GLMCP_ADMISSION_EVIDENCE_REF = (
    "relay-receipt:glmcp-quota-admission.yaml:"
    "witness:supported-tool-usage-witness:"
    "supported_tool:hapax-glmcp-reviewer:"
    "endpoint:https://api.z.ai/api/coding/paas/v4:"
    "model:glm-5.2:"
    "observed_at:2026-05-17T07:59:00Z:"
    "fresh_until:2026-05-17T08:05:00Z"
)
GLMCP_PAYG_ADMISSION_EVIDENCE_REF = (
    GLMCP_ADMISSION_EVIDENCE_REF.replace(
        "glmcp-quota-admission.yaml",
        "glmcp-quota-admission-payg.yaml",
    )
    .replace(
        "endpoint:https://api.z.ai/api/coding/paas/v4:",
        "endpoint:https://api.z.ai/api/paas/v4:",
    )
    .replace(
        "witness:supported-tool-usage-witness:",
        "witness:glmcp-payg-spend-20260517t075900z-test.yaml:",
    )
    .replace(
        "model:glm-5.2:",
        "model:glm-5.2:primary_error_class:quota_exhausted:"
        "quota_wall_evidence_ref:cx-glmcp-quota-wall.yaml:",
    )
)
GLMCP_PAYG_ADMISSION_WITHOUT_WALL_EVIDENCE_REF = GLMCP_PAYG_ADMISSION_EVIDENCE_REF.replace(
    "primary_error_class:quota_exhausted:quota_wall_evidence_ref:cx-glmcp-quota-wall.yaml:",
    "",
)
GLMCP_REVIEWER_TOOL_CLAUDE_ENDPOINT_EVIDENCE_REF = GLMCP_ADMISSION_EVIDENCE_REF.replace(
    "endpoint:https://api.z.ai/api/coding/paas/v4:",
    "endpoint:https://api.z.ai/api/anthropic:",
)
GLMCP_CLAUDE_TOOL_CODING_ENDPOINT_EVIDENCE_REF = GLMCP_ADMISSION_EVIDENCE_REF.replace(
    "supported_tool:hapax-glmcp-reviewer:",
    "supported_tool:claude_code:",
)
GLMCP_HASHED_ADMISSION_EVIDENCE_REF = GLMCP_ADMISSION_EVIDENCE_REF.replace(
    "glmcp-quota-admission.yaml",
    "unsafe-receipt-name-sha256:0123456789abcdef",
)
GLMCP_SECRETISH_WITNESS_EVIDENCE_REF = GLMCP_ADMISSION_EVIDENCE_REF.replace(
    "witness:supported-tool-usage-witness:",
    "witness:sk-live-secret-token-000000000000000000000000:",
)
AGY_ADMISSION_EVIDENCE_REF = (
    "relay-receipt:agy-quota-admission.yaml:"
    "witness:agy-gemini31pro-smoke-witness:"
    "supported_tool:hapax-agy-reviewer:"
    "model:gemini-3.1-pro-preview:"
    "observed_at:2026-05-17T07:59:00Z:"
    "fresh_until:2026-05-17T08:05:00Z"
)
AGY_SECRETISH_WITNESS_EVIDENCE_REF = AGY_ADMISSION_EVIDENCE_REF.replace(
    "witness:agy-gemini31pro-smoke-witness:",
    "witness:sk-live-secret-token-000000000000000000000000:",
)


def _payload() -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8")),
    )


def _active_budget_payload() -> dict[str, Any]:
    payload = deepcopy(_payload())
    payload["captured_at"] = "2026-05-17T07:59:30Z"
    payload["paid_api_budget_freshness_ttl_s"] = 120
    budget = payload["transition_budgets"][0]
    budget["created_at"] = "2026-05-17T07:00:00Z"
    budget["expires_at"] = "2026-05-17T09:00:00Z"
    budget["total_cap_usd"] = "10.00"
    budget["per_task_cap_usd"] = "5.00"
    budget["daily_cap_usd"] = "10.00"
    budget["subscription_path_checked_at"] = "2026-05-17T07:00:00Z"
    budget["lifecycle_state"] = "active"
    payload["spend_receipts"] = []
    payload["spend_gate_decisions"] = []
    payload["artifact_provenance"] = []
    payload["provider_dependencies"][0]["dependency_state"] = "active"
    payload["provider_dependencies"][0]["critical_path"] = True
    payload["provider_dependencies"][0]["review_by"] = "2026-05-17T09:00:00Z"
    payload["provider_dependencies"][0]["replacement_route_id"] = "opaque.route.subscription"
    payload["renewal_records"][0]["hard_expiry_review_at"] = "2026-05-17T09:00:00Z"
    return payload


def _add_glmcp_payg_budget(
    payload: dict[str, Any],
    *,
    expires_at: str = "2026-05-17T09:00:00Z",
) -> str:
    budget_id = "tb-20260517-zai-glmcp-payg-review"
    payload["transition_budgets"].append(
        {
            "budget_schema": 1,
            "budget_id": budget_id,
            "authority_case": "CASE-CAPACITY-ROUTING-GLMCP-PAYG-TEST",
            "approved_by": "operator",
            "created_at": "2026-05-17T07:00:00Z",
            "expires_at": expires_at,
            "capacity_pool": "api_paid_spend",
            "providers_allowed": ["z_ai"],
            "profiles_allowed": ["glmcp-review-direct"],
            "task_classes_allowed": ["independent-review"],
            "quality_floors_allowed": ["frontier_review_required"],
            "total_cap_usd": "100.00",
            "per_task_cap_usd": "2.00",
            "daily_cap_usd": "20.00",
            "auto_top_up_allowed": False,
            "subscription_path_checked_at": "2026-05-17T07:00:00Z",
            "reason_subscription_path_not_used": (
                "fixture Coding Plan quota exhausted; PAYG spend gate under test"
            ),
            "steady_state_replacement": {
                "target_route_id": None,
                "blocker_to_remove": None,
                "exit_criterion": None,
            },
            "ledger_owner": "test",
            "dashboard_visibility": "required",
            "lifecycle_state": "active",
        }
    )
    return budget_id


def _add_glmcp_payg_spend_receipt(
    payload: dict[str, Any],
    budget_id: str,
    *,
    spend_id: str = "spend-20260517T075900Z-glmcp-payg-review-test",
    task_id: str = "cc-task-glmcp-review-seat-glm52-model-contract-20260706",
    estimated_cost_usd: str = "0.05",
) -> None:
    payload["spend_receipts"].append(
        {
            "spend_receipt_schema": 1,
            "spend_id": spend_id,
            "task_id": task_id,
            "authority_case": "CASE-CAPACITY-ROUTING-GLMCP-PAYG-TEST",
            "route_id": "glmcp.review.direct",
            "capacity_pool": "api_paid_spend",
            "budget_id": budget_id,
            "provider": "z_ai",
            "model_or_engine": "glm-5.2",
            "model_id": "z_ai-glm-5.2",
            "effort": "none",
            "quantization": "not_applicable",
            "auth_surface": "api_key",
            "quality_floor": "frontier_review_required",
            "quality_preservation_reason": (
                "receipt-bounded GLMCP review fallback after Coding Plan quota wall"
            ),
            "spend_reason": "quota_exhaustion",
            "estimated_cost_usd": estimated_cost_usd,
            "created_at": "2026-05-17T07:59:00Z",
            "reconcile_by": "2026-05-18T07:59:00Z",
            "reconciliation_state": "pending",
            "support_artifact_authority": "none",
        }
    )


def _request(**overrides: object) -> PaidRouteRequest:
    payload: dict[str, object] = {
        "route_id": "opaque.route.bootstrap",
        "task_id": "capacity-routing-quota-spend-ledger",
        "provider": "opaque-provider-a",
        "profile": "opaque-profile-full",
        "task_class": "authority-case-implementation",
        "quality_floor": "frontier_required",
        "estimated_cost_usd": "1.00",
        "capacity_pool": "bootstrap_budget",
    }
    payload.update(overrides)
    return PaidRouteRequest.model_validate(payload)


def test_default_fixture_reconciles_expired_bootstrap_without_reopening_spend() -> None:
    ledger = load_quota_spend_ledger()
    bootstrap_budget = ledger.budget_by_id("tb-20260509-bootstrap-expired")
    bootstrap_receipt = ledger.spend_receipts[0]
    bootstrap_dependency = ledger.provider_dependencies[0]
    provenance = ledger.artifact_provenance[0]

    assert bootstrap_budget.lifecycle_state is BudgetLifecycleState.RETIRED
    assert bootstrap_receipt.reconciliation_state is SpendReconciliationState.FROZEN_REFUSED
    assert bootstrap_receipt.is_unreconciled_overdue(NOW) is False
    assert bootstrap_dependency.dependency_state is DependencyState.REPLACED
    assert bootstrap_dependency.last_reviewed_at == datetime(2026, 5, 17, 7, 42, tzinfo=UTC)
    assert provenance.support_artifact_authority is (
        SupportArtifactAuthority.SUPPORT_NON_AUTHORITATIVE
    )
    assert provenance.artifact_disposition is SupportArtifactDisposition.RETIRED
    assert provenance.waiting_for_review() is False
    assert ledger.transition_budgets
    assert ledger.spend_gate_decisions[0].decision_state is (
        SpendGateDecisionState.REFUSED_UNRECONCILED_SPEND
    )
    assert any(
        decision.decision_id == "sgd-20260604-provider-gateway-google-frontier-fast"
        and decision.decision_state is SpendGateDecisionState.ELIGIBLE_ACTIVE_BUDGET
        for decision in ledger.spend_gate_decisions
    )
    assert all(not budget.auto_top_up_allowed for budget in ledger.transition_budgets)


def test_paid_route_refuses_without_any_transition_budget() -> None:
    payload = _active_budget_payload()
    payload["transition_budgets"] = []
    payload["provider_dependencies"] = []
    payload["renewal_records"] = []
    ledger = QuotaSpendLedger.model_validate(payload)

    decision = evaluate_paid_route_eligibility(ledger, _request(), now=NOW)

    assert decision.eligible is False
    assert decision.state == "refused_no_matching_budget"
    assert "no matching TransitionBudget" in decision.blocking_reasons


def test_retired_bootstrap_budget_refuses_paid_route() -> None:
    ledger = load_quota_spend_ledger()

    decision = evaluate_paid_route_eligibility(ledger, _request(), now=NOW)

    assert decision.eligible is False
    assert decision.state == "refused_expired_budget"
    assert any("frozen/refused spend receipts" in reason for reason in decision.blocking_reasons)
    assert "tb-20260509-bootstrap-expired" in decision.evidence_refs


def test_stale_budget_ledger_refuses_otherwise_valid_budget() -> None:
    payload = _active_budget_payload()
    payload["captured_at"] = "2026-05-17T07:00:00Z"
    payload["paid_api_budget_freshness_ttl_s"] = 60
    ledger = QuotaSpendLedger.model_validate(payload)

    decision = evaluate_paid_route_eligibility(ledger, _request(), now=NOW)

    assert decision.eligible is False
    assert decision.state == "refused_budget_gate"
    assert "budget ledger stale" in decision.blocking_reasons


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "other-provider"),
        ("profile", "other-profile"),
        ("task_class", "other-task-class"),
        ("quality_floor", "other-quality-floor"),
    ],
)
def test_provider_profile_task_class_and_quality_floor_mismatches_fail_closed(
    field: str,
    value: str,
) -> None:
    ledger = QuotaSpendLedger.model_validate(_active_budget_payload())

    decision = evaluate_paid_route_eligibility(ledger, _request(**{field: value}), now=NOW)

    assert decision.eligible is False
    assert decision.state == "refused_no_matching_budget"


def test_cap_exhaustion_refuses_paid_route() -> None:
    payload = _active_budget_payload()
    payload["spend_receipts"] = [
        {
            "spend_receipt_schema": 1,
            "spend_id": "spend-20260509T203000Z-cap-used",
            "task_id": "capacity-routing-quota-spend-ledger",
            "authority_case": "CASE-CAPACITY-ROUTING-001",
            "route_id": "opaque.route.bootstrap",
            "capacity_pool": "bootstrap_budget",
            "budget_id": "tb-20260509-bootstrap-expired",
            "provider": "opaque-provider-a",
            "model_or_engine": "opaque-engine-a",
            "auth_surface": "api_key",
            "quality_floor": "frontier_required",
            "quality_preservation_reason": "fixture cap use",
            "spend_reason": "bootstrap_equilibrium",
            "estimated_cost_usd": None,
            "actual_cost_usd": "10.00",
            "cap_remaining_usd": "0.00",
            "created_at": "2026-05-17T07:30:00Z",
            "reconcile_by": None,
            "reconciliation_state": "reconciled",
            "reconciled_at": "2026-05-17T07:45:00Z",
            "reconciliation_reason": "fixture cap use reconciled",
            "artifact_refs": [],
            "support_artifact_authority": "none",
        }
    ]
    ledger = QuotaSpendLedger.model_validate(payload)

    decision = evaluate_paid_route_eligibility(ledger, _request(), now=NOW)

    assert decision.eligible is False
    assert decision.state == "refused_exhausted_budget"


def test_per_task_cap_sums_existing_spend_for_same_task_only() -> None:
    payload = _active_budget_payload()
    budget = payload["transition_budgets"][0]
    budget["per_task_cap_usd"] = "2.00"
    payload["spend_receipts"] = [
        {
            "spend_receipt_schema": 1,
            "spend_id": "spend-20260517T073000Z-task-a-used",
            "task_id": "capacity-routing-quota-spend-ledger",
            "authority_case": "CASE-CAPACITY-ROUTING-001",
            "route_id": "opaque.route.bootstrap",
            "capacity_pool": "bootstrap_budget",
            "budget_id": "tb-20260509-bootstrap-expired",
            "provider": "opaque-provider-a",
            "model_or_engine": "opaque-engine-a",
            "auth_surface": "api_key",
            "quality_floor": "frontier_required",
            "quality_preservation_reason": "fixture task cap use",
            "spend_reason": "bootstrap_equilibrium",
            "estimated_cost_usd": None,
            "actual_cost_usd": "1.75",
            "cap_remaining_usd": "8.25",
            "created_at": "2026-05-17T07:30:00Z",
            "reconcile_by": None,
            "reconciliation_state": "reconciled",
            "reconciled_at": "2026-05-17T07:45:00Z",
            "reconciliation_reason": "fixture task cap use reconciled",
            "artifact_refs": [],
            "support_artifact_authority": "none",
        },
        {
            "spend_receipt_schema": 1,
            "spend_id": "spend-20260517T073500Z-task-b-used",
            "task_id": "other-task",
            "authority_case": "CASE-CAPACITY-ROUTING-001",
            "route_id": "opaque.route.bootstrap",
            "capacity_pool": "bootstrap_budget",
            "budget_id": "tb-20260509-bootstrap-expired",
            "provider": "opaque-provider-a",
            "model_or_engine": "opaque-engine-a",
            "auth_surface": "api_key",
            "quality_floor": "frontier_required",
            "quality_preservation_reason": "fixture other task cap use",
            "spend_reason": "bootstrap_equilibrium",
            "estimated_cost_usd": None,
            "actual_cost_usd": "1.75",
            "cap_remaining_usd": "6.50",
            "created_at": "2026-05-17T07:35:00Z",
            "reconcile_by": None,
            "reconciliation_state": "reconciled",
            "reconciled_at": "2026-05-17T07:45:00Z",
            "reconciliation_reason": "fixture other task cap use reconciled",
            "artifact_refs": [],
            "support_artifact_authority": "none",
        },
    ]
    ledger = QuotaSpendLedger.model_validate(payload)

    exhausted = evaluate_paid_route_eligibility(
        ledger,
        _request(estimated_cost_usd="0.30"),
        now=NOW,
    )
    different_task = evaluate_paid_route_eligibility(
        ledger,
        _request(task_id="fresh-task", estimated_cost_usd="0.30"),
        now=NOW,
    )

    assert exhausted.eligible is False
    assert exhausted.state == "refused_exhausted_budget"
    assert different_task.eligible is True
    assert str(different_task.cap_remaining_usd) == "1.70"


def test_reconciled_zero_actual_spend_counts_zero_against_caps() -> None:
    payload = _active_budget_payload()
    budget = payload["transition_budgets"][0]
    budget["per_task_cap_usd"] = "0.05"
    payload["spend_receipts"] = [
        {
            "spend_receipt_schema": 1,
            "spend_id": "spend-20260517T073000Z-zero-actual",
            "task_id": "capacity-routing-quota-spend-ledger",
            "authority_case": "CASE-CAPACITY-ROUTING-001",
            "route_id": "opaque.route.bootstrap",
            "capacity_pool": "bootstrap_budget",
            "budget_id": "tb-20260509-bootstrap-expired",
            "provider": "opaque-provider-a",
            "model_or_engine": "opaque-engine-a",
            "auth_surface": "api_key",
            "quality_floor": "frontier_required",
            "quality_preservation_reason": "fixture failed request reconciled to zero cost",
            "spend_reason": "bootstrap_equilibrium",
            "estimated_cost_usd": "0.05",
            "actual_cost_usd": "0.00",
            "cap_remaining_usd": "0.05",
            "created_at": "2026-05-17T07:30:00Z",
            "reconcile_by": "2026-05-18T07:30:00Z",
            "reconciliation_state": "reconciled",
            "reconciled_at": "2026-05-17T07:45:00Z",
            "reconciliation_reason": "fixture failed before billable completion",
            "artifact_refs": [],
            "support_artifact_authority": "none",
        }
    ]
    ledger = QuotaSpendLedger.model_validate(payload)

    decision = evaluate_paid_route_eligibility(
        ledger,
        _request(estimated_cost_usd="0.05"),
        now=NOW,
    )

    assert decision.eligible is True
    assert str(decision.cap_remaining_usd) == "0.00"


def test_route_subscription_snapshot_fresh_until_expires_independently() -> None:
    payload = _active_budget_payload()
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-fresh",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [GLMCP_ADMISSION_EVIDENCE_REF],
            "operator_visible_reason": "fixture GLMCP admission",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    fresh_state, fresh_refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )
    stale_state, stale_refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 6, tzinfo=UTC),
    )

    assert fresh_state is SubscriptionQuotaState.FRESH
    assert fresh_refs == (GLMCP_ADMISSION_EVIDENCE_REF,)
    assert stale_state is SubscriptionQuotaState.STALE
    assert (
        "quota-snapshot:quota-glmcp-review-direct-fresh:fresh_until_expired:2026-05-17T08:05:00Z"
        in stale_refs
    )


def test_receipt_bounded_route_fresh_snapshot_requires_fresh_until() -> None:
    payload = _active_budget_payload()
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-fresh",
            "captured_at": "2026-05-17T07:59:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [GLMCP_ADMISSION_EVIDENCE_REF],
            "operator_visible_reason": "fixture GLMCP admission missing expiry",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert "quota-snapshot:quota-glmcp-review-direct-fresh:fresh_until_missing" in refs


def test_receipt_bounded_route_fresh_snapshot_requires_glmcp_admission_evidence() -> None:
    payload = _active_budget_payload()
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-forged-fresh",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "some-other-provider",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": ["relay-receipt:forged-quota-green"],
            "operator_visible_reason": "fixture forged glmcp fresh snapshot",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert "relay-receipt:forged-quota-green" in refs
    assert (
        "quota-snapshot:quota-glmcp-review-direct-forged-fresh:untrusted_glmcp_admission_evidence"
    ) in refs


@pytest.mark.parametrize(
    "evidence_ref",
    [
        GLMCP_REVIEWER_TOOL_CLAUDE_ENDPOINT_EVIDENCE_REF,
        GLMCP_CLAUDE_TOOL_CODING_ENDPOINT_EVIDENCE_REF,
    ],
)
def test_receipt_bounded_route_rejects_mismatched_tool_endpoint_evidence(
    evidence_ref: str,
) -> None:
    payload = _active_budget_payload()
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-mismatch",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [evidence_ref],
            "operator_visible_reason": "fixture mismatched glmcp admission evidence",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert evidence_ref in refs
    assert (
        "quota-snapshot:quota-glmcp-review-direct-mismatch:untrusted_glmcp_admission_evidence"
    ) in refs


def test_receipt_bounded_route_accepts_writer_hashed_admission_label() -> None:
    payload = _active_budget_payload()
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-hashed-label",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [GLMCP_HASHED_ADMISSION_EVIDENCE_REF],
            "operator_visible_reason": "fixture hashed glmcp admission receipt label",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.FRESH
    assert refs == (GLMCP_HASHED_ADMISSION_EVIDENCE_REF,)


def test_receipt_bounded_route_accepts_payg_endpoint_admission_evidence() -> None:
    payload = _active_budget_payload()
    budget_id = _add_glmcp_payg_budget(payload)
    _add_glmcp_payg_spend_receipt(payload, budget_id)
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-payg-fresh",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [
                GLMCP_PAYG_ADMISSION_EVIDENCE_REF,
                "spend-gate:glmcp.review.direct:eligible_active_budget",
                f"spend-gate-budget:{budget_id}",
            ],
            "operator_visible_reason": "fixture GLMCP PAYG admission receipt",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.FRESH
    assert GLMCP_PAYG_ADMISSION_EVIDENCE_REF in refs
    assert "spend-gate:glmcp.review.direct:eligible_active_budget" in refs
    assert f"spend-gate-budget:{budget_id}" in refs


def test_successful_task_scoped_glmcp_payg_review_spend_witness_is_discovered() -> None:
    payload = _active_budget_payload()
    budget_id = _add_glmcp_payg_budget(payload)
    task_id = "cc-task-glmcp-review-seat-glm52-model-contract-20260706"
    _add_glmcp_payg_spend_receipt(payload, budget_id, task_id=task_id)
    receipt = payload["spend_receipts"][-1]
    receipt["actual_cost_usd"] = "0.05"
    receipt["cap_remaining_usd"] = "1.95"
    receipt["reconciliation_state"] = "reconciled"
    receipt["reconciled_at"] = "2026-05-17T08:00:00Z"
    receipt["reconciliation_reason"] = (
        "PAYG API call returned model output; provider invoice unavailable"
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    receipts = successful_task_scoped_glmcp_payg_review_spend_receipts(ledger, task_id)

    assert [receipt.spend_id for receipt in receipts] == [
        "spend-20260517T075900Z-glmcp-payg-review-test"
    ]
    assert has_successful_task_scoped_glmcp_payg_review_spend(ledger, task_id) is True


def test_pending_task_scoped_glmcp_payg_review_spend_is_not_successful_witness() -> None:
    payload = _active_budget_payload()
    budget_id = _add_glmcp_payg_budget(payload)
    task_id = "cc-task-glmcp-review-seat-glm52-model-contract-20260706"
    _add_glmcp_payg_spend_receipt(payload, budget_id, task_id=task_id)
    ledger = QuotaSpendLedger.model_validate(payload)

    assert successful_task_scoped_glmcp_payg_review_spend_receipts(ledger, task_id) == ()
    assert has_successful_task_scoped_glmcp_payg_review_spend(ledger, task_id) is False


def test_receipt_bounded_route_rejects_payg_when_witness_task_cap_exhausted() -> None:
    payload = _active_budget_payload()
    budget_id = _add_glmcp_payg_budget(payload)
    _add_glmcp_payg_spend_receipt(payload, budget_id, estimated_cost_usd="2.00")
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-payg-task-cap-exhausted",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [
                GLMCP_PAYG_ADMISSION_EVIDENCE_REF,
                "spend-gate:glmcp.review.direct:eligible_active_budget",
                f"spend-gate-budget:{budget_id}",
            ],
            "operator_visible_reason": "fixture GLMCP PAYG admission receipt",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert (
        "quota-snapshot:quota-glmcp-review-direct-payg-task-cap-exhausted:"
        "payg_spend_gate_missing_or_ineligible"
    ) in refs


def test_receipt_bounded_route_rejects_payg_without_spend_receipt_witness() -> None:
    payload = _active_budget_payload()
    budget_id = _add_glmcp_payg_budget(payload)
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-payg-no-spend-receipt",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [
                GLMCP_PAYG_ADMISSION_EVIDENCE_REF,
                "spend-gate:glmcp.review.direct:eligible_active_budget",
                f"spend-gate-budget:{budget_id}",
            ],
            "operator_visible_reason": "fixture GLMCP PAYG admission receipt",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert (
        "quota-snapshot:quota-glmcp-review-direct-payg-no-spend-receipt:"
        "payg_spend_gate_missing_or_ineligible"
    ) in refs


def test_receipt_bounded_route_rejects_payg_spend_receipt_from_wrong_budget() -> None:
    payload = _active_budget_payload()
    budget_id = _add_glmcp_payg_budget(payload)
    wrong_budget_id = payload["transition_budgets"][0]["budget_id"]
    _add_glmcp_payg_spend_receipt(payload, wrong_budget_id)
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-payg-wrong-budget-receipt",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [
                GLMCP_PAYG_ADMISSION_EVIDENCE_REF,
                "spend-gate:glmcp.review.direct:eligible_active_budget",
                f"spend-gate-budget:{budget_id}",
            ],
            "operator_visible_reason": "fixture GLMCP PAYG admission receipt",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert (
        "quota-snapshot:quota-glmcp-review-direct-payg-wrong-budget-receipt:"
        "payg_spend_gate_missing_or_ineligible"
    ) in refs


def test_receipt_bounded_route_rejects_payg_without_quota_wall_witness() -> None:
    payload = _active_budget_payload()
    budget_id = _add_glmcp_payg_budget(payload)
    _add_glmcp_payg_spend_receipt(payload, budget_id)
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-payg-no-wall-witness",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [
                GLMCP_PAYG_ADMISSION_WITHOUT_WALL_EVIDENCE_REF,
                "spend-gate:glmcp.review.direct:eligible_active_budget",
                f"spend-gate-budget:{budget_id}",
            ],
            "operator_visible_reason": "fixture GLMCP PAYG admission receipt without wall witness",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert (
        "quota-snapshot:quota-glmcp-review-direct-payg-no-wall-witness:"
        "untrusted_glmcp_admission_evidence"
    ) in refs


def test_receipt_bounded_route_rejects_payg_without_spend_gate_evidence() -> None:
    payload = _active_budget_payload()
    _add_glmcp_payg_budget(payload)
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-payg-no-spend-gate",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [GLMCP_PAYG_ADMISSION_EVIDENCE_REF],
            "operator_visible_reason": "fixture GLMCP PAYG admission receipt",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert (
        "quota-snapshot:quota-glmcp-review-direct-payg-no-spend-gate:"
        "payg_spend_gate_missing_or_ineligible"
    ) in refs


def test_receipt_bounded_route_rechecks_payg_budget_at_read_time() -> None:
    payload = _active_budget_payload()
    budget_id = _add_glmcp_payg_budget(payload, expires_at="2026-05-17T08:01:00Z")
    _add_glmcp_payg_spend_receipt(payload, budget_id)
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-payg-expired-budget",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [
                GLMCP_PAYG_ADMISSION_EVIDENCE_REF,
                "spend-gate:glmcp.review.direct:eligible_active_budget",
                f"spend-gate-budget:{budget_id}",
            ],
            "operator_visible_reason": "fixture GLMCP PAYG admission receipt",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 2, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert (
        "quota-snapshot:quota-glmcp-review-direct-payg-expired-budget:"
        "payg_spend_gate_missing_or_ineligible"
    ) in refs


def test_receipt_bounded_route_rejects_and_redacts_secretish_witness() -> None:
    payload = _active_budget_payload()
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-glmcp-review-direct-secretish-witness",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "glmcp.review.direct",
            "provider": "z_ai-glm-coding-plan",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [GLMCP_SECRETISH_WITNESS_EVIDENCE_REF],
            "operator_visible_reason": "fixture secretish glmcp admission witness",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "glmcp.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert GLMCP_SECRETISH_WITNESS_EVIDENCE_REF not in refs
    assert any(ref.startswith("quota-evidence-ref:redacted-secretish-sha256:") for ref in refs)
    assert (
        "quota-snapshot:quota-glmcp-review-direct-secretish-witness:untrusted_glmcp_admission_evidence"
    ) in refs


def test_overdue_reconciliation_freezes_otherwise_valid_budget() -> None:
    payload = _active_budget_payload()
    payload["spend_receipts"] = [
        {
            "spend_receipt_schema": 1,
            "spend_id": "spend-20260509T203000Z-unreconciled",
            "task_id": "capacity-routing-quota-spend-ledger",
            "authority_case": "CASE-CAPACITY-ROUTING-001",
            "route_id": "opaque.route.bootstrap",
            "capacity_pool": "bootstrap_budget",
            "budget_id": "tb-20260509-bootstrap-expired",
            "provider": "opaque-provider-a",
            "model_or_engine": "opaque-engine-a",
            "auth_surface": "api_key",
            "quality_floor": "frontier_required",
            "quality_preservation_reason": "fixture unreconciled estimate",
            "spend_reason": "bootstrap_equilibrium",
            "estimated_cost_usd": "1.00",
            "actual_cost_usd": None,
            "cap_remaining_usd": None,
            "created_at": "2026-05-17T07:30:00Z",
            "reconcile_by": "2026-05-17T07:45:00Z",
            "artifact_refs": [],
            "support_artifact_authority": "none",
        }
    ]
    ledger = QuotaSpendLedger.model_validate(payload)

    decision = evaluate_paid_route_eligibility(ledger, _request(), now=NOW)

    assert decision.eligible is False
    assert decision.state == "refused_budget_gate"
    assert any(
        "unreconciled spend receipts overdue" in reason for reason in decision.blocking_reasons
    )


def test_quality_floor_is_opaque_string_supplied_by_other_slices() -> None:
    payload = _active_budget_payload()
    payload["transition_budgets"][0]["quality_floors_allowed"] = ["later-slice-quality-floor"]
    ledger = QuotaSpendLedger.model_validate(payload)

    decision = evaluate_paid_route_eligibility(
        ledger,
        _request(quality_floor="later-slice-quality-floor"),
        now=NOW,
    )

    assert decision.eligible is True
    assert decision.budget_id == "tb-20260509-bootstrap-expired"


def test_support_artifact_provenance_stays_non_authoritative_until_accepted() -> None:
    ledger = load_quota_spend_ledger()
    provenance = ledger.artifact_provenance[0]

    assert provenance.support_artifact_authority is (
        SupportArtifactAuthority.SUPPORT_NON_AUTHORITATIVE
    )
    assert provenance.artifact_disposition is SupportArtifactDisposition.RETIRED
    assert provenance.waiting_for_review() is False

    payload = provenance.model_dump(mode="json")
    payload["artifact_disposition"] = "pending_review"
    payload["disposition_reviewed_at"] = None
    payload["disposition_reason"] = None
    pending = ArtifactProvenanceRecord.model_validate(payload)
    assert pending.waiting_for_review() is True

    payload["support_artifact_authority"] = "accepted_authoritative"
    with pytest.raises(ValidationError, match="accepted artifacts require acceptor"):
        ArtifactProvenanceRecord.model_validate(payload)


def test_dashboard_exposes_reconciled_bootstrap_state() -> None:
    dashboard = build_dashboard(load_quota_spend_ledger(), now=CURRENT_REFRESH_NOW)

    assert dashboard.paid_api_budget_state is PaidApiBudgetState.ACTIVE
    assert dashboard.budget_ledger_stale is False
    assert dashboard.bootstrap_dependency_state is BootstrapDependencyState.NONE
    assert dashboard.provider_dependency_count == 0
    assert dashboard.support_artifacts_waiting_for_review == 0
    assert "bootstrap_dependency_state:expired" not in dashboard.non_green_states
    assert "spend_reconciliation_overdue" not in dashboard.non_green_states
    assert dashboard.frozen_spend_refs == ("spend-20260509T193000Z-opaque-route",)
    assert dashboard.closed_provider_dependency_refs == ("dep-opaque-provider-bootstrap",)
    assert dashboard.closed_support_artifact_refs == ("artifacts/support/bootstrap-draft.md",)
    assert dashboard.paid_api_route_eligible is True


def test_provider_gateway_google_frontier_fast_budget_is_current_and_eligible() -> None:
    ledger = load_quota_spend_ledger()

    decision = evaluate_paid_route_eligibility(
        ledger,
        _request(
            route_id="api.headless.provider_gateway",
            provider="google",
            profile="frontier-fast",
            task_class="authority-case-implementation",
            quality_floor="frontier_required",
            capacity_pool="api_paid_spend",
        ),
        now=CURRENT_REFRESH_NOW,
    )

    assert decision.eligible is True
    assert decision.state == "eligible_active_budget"
    assert decision.budget_id == "tb-20260510-anthropic-api-steady-state"


def test_claude_code_subscription_exhaustion_does_not_block_api_budget() -> None:
    ledger = load_quota_spend_ledger()
    dashboard = build_dashboard(ledger, now=CURRENT_REFRESH_NOW)

    assert dashboard.subscription_quota_state is SubscriptionQuotaState.EXHAUSTED
    assert dashboard.paid_api_budget_state is PaidApiBudgetState.ACTIVE
    assert dashboard.paid_api_route_eligible is True
    assert dashboard.paid_api_blocking_reasons == ()
    assert "subscription_quota_state:exhausted" in dashboard.non_green_states

    decision = evaluate_paid_route_eligibility(
        ledger,
        _request(
            route_id="litellm.anthropic.claude-opus-4",
            provider="anthropic",
            profile="frontier-full",
            task_class="agent-dispatch",
            quality_floor="frontier_required",
            estimated_cost_usd="1.00",
            capacity_pool="api_paid_spend",
        ),
        now=CURRENT_REFRESH_NOW,
    )

    assert decision.eligible is True
    assert decision.state == "eligible_active_budget"
    assert decision.budget_id == "tb-20260510-anthropic-api-steady-state"


def test_subscription_quota_state_for_route_uses_exact_route_snapshot() -> None:
    payload = _payload()
    payload["quota_snapshots"].extend(
        [
            {
                "quota_snapshot_schema": 1,
                "snapshot_id": "quota-glmcp-review-direct-unknown",
                "captured_at": "2026-06-10T00:00:00Z",
                "route_id": "glmcp.review.direct",
                "provider": "z_ai-glm-coding-plan",
                "capacity_pool": "subscription_quota",
                "subscription_quota_state": "unknown",
                "evidence_refs": ["relay-receipt:glmcp:quota-admission:absent"],
                "operator_visible_reason": "fixture glmcp unknown",
            },
            {
                "quota_snapshot_schema": 1,
                "snapshot_id": "quota-codex-headless-full-fresh",
                "captured_at": "2026-06-10T00:00:00Z",
                "route_id": "codex.headless.full",
                "provider": "codex-subscription",
                "capacity_pool": "subscription_quota",
                "subscription_quota_state": "fresh",
                "evidence_refs": ["relay-receipt:codex:quota-wall:absent"],
                "operator_visible_reason": "fixture codex fresh",
            },
        ]
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(ledger, "glmcp/review/direct")

    assert state is SubscriptionQuotaState.UNKNOWN
    assert refs == ("relay-receipt:glmcp:quota-admission:absent",)


def test_module_has_no_provider_or_runtime_imports() -> None:
    source = Path("shared/quota_spend_ledger.py").read_text(encoding="utf-8")

    forbidden_tokens = [
        "import openai",
        "from openai",
        "import anthropic",
        "from anthropic",
        "google.generativeai",
        "google.cloud",
        "mistralai",
        "requests",
        "httpx",
        "urllib.request",
        "os.environ",
        "pass show",
        "hapax_secrets",
        "subprocess",
        "logos",
        "grafana",
        "health-monitor",
        "hapax-rte-state",
        "dispatch_task",
    ]
    for token in forbidden_tokens:
        assert token not in source


def test_fixture_file_contains_no_private_payload_or_credential_material() -> None:
    text = QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8")

    forbidden_tokens = [
        "/private/operator-home",
        "raw_body",
        "receipt_email",
        "customer_email",
        "billing_details",
        "card_number",
        "government_id",
        "passport",
        "pass show",
        "STRIPE_PAYMENT_LINK_WEBHOOK_SECRET",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
    ]
    for token in forbidden_tokens:
        assert token not in text


def _valid_live_payload(captured_at: str = "2026-06-10T00:00:00Z") -> dict[str, Any]:
    payload = deepcopy(_payload())
    payload["ledger_id"] = "quota-spend-ledger-live-test"
    payload["captured_at"] = captured_at
    return payload


def test_resolved_loader_prefers_live_ledger_when_present(tmp_path: Path) -> None:
    live = tmp_path / "quota-spend-ledger-live.json"
    live.write_text(json.dumps(_valid_live_payload()), encoding="utf-8")

    resolved = load_quota_spend_ledger_resolved(live_path=live)

    assert resolved.source == "live"
    assert resolved.path == live
    assert resolved.live_error is None
    assert resolved.ledger.ledger_id == "quota-spend-ledger-live-test"


def test_resolved_loader_falls_back_to_fixtures_when_live_missing(tmp_path: Path) -> None:
    resolved = load_quota_spend_ledger_resolved(live_path=tmp_path / "absent.json")

    assert resolved.source == "fixtures"
    assert resolved.path == QUOTA_SPEND_LEDGER_FIXTURES
    assert resolved.live_error is None


def test_resolved_loader_reports_invalid_live_ledger_on_fallback(tmp_path: Path) -> None:
    live = tmp_path / "quota-spend-ledger-live.json"
    live.write_text("{not json", encoding="utf-8")

    resolved = load_quota_spend_ledger_resolved(live_path=live)

    assert resolved.source == "fixtures"
    assert resolved.live_error is not None
    assert "invalid quota/spend ledger" in resolved.live_error


def test_live_env_override_resolution_lives_outside_the_inert_module() -> None:
    # The inert ledger module exports the env var name + default path but must
    # not read the environment itself (pinned by
    # test_module_has_no_provider_or_runtime_imports). The env-aware resolution
    # lives in shared.dispatcher_policy.
    from shared.dispatcher_policy import quota_spend_ledger_live_path_from_env

    assert QUOTA_SPEND_LEDGER_LIVE_ENV == "HAPAX_QUOTA_SPEND_LEDGER_LIVE"
    assert DEFAULT_QUOTA_SPEND_LEDGER_LIVE.name == "quota-spend-ledger-live.json"
    assert callable(quota_spend_ledger_live_path_from_env)


# --------------------------------------------------------------------------------------
# Quantization metering (capability-haiku-localtool-routes slice)
# --------------------------------------------------------------------------------------
def test_quantization_enum_parity_with_registry() -> None:
    """The ledger defines its OWN Quantization enum (it must not import the registry — the ledger
    is the deliberately low-dependency inert module). This drift-pin keeps the two value sets
    byte-identical so a receipt's quantization matches a route descriptor's quantization exactly."""
    from shared.platform_capability_registry import Quantization as RegistryQuantization

    assert {q.value for q in Quantization} == {q.value for q in RegistryQuantization}


def test_spend_receipt_quantization_defaults_and_separates() -> None:
    """quantization defaults to NOT_APPLICABLE (hosted/cloud receipts have no bpw notion, and the
    defaulted field keeps every existing fixture valid), and a local receipt can record a specific
    EXL3 bpw so exl3_4_0bpw vs 5_0bpw are distinguishable on the receipt."""
    ledger = QuotaSpendLedger.model_validate(
        json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8"))
    )
    base = ledger.spend_receipts[0]
    assert base.quantization is Quantization.NOT_APPLICABLE  # absent in the fixture -> default

    payload = base.model_dump(mode="json")
    payload["quantization"] = "exl3_4_0bpw"
    four_bpw = SpendReceipt.model_validate(payload)
    payload["quantization"] = "exl3_5_0bpw"
    five_bpw = SpendReceipt.model_validate(payload)
    assert four_bpw.quantization is Quantization.EXL3_4_0BPW
    assert five_bpw.quantization is Quantization.EXL3_5_0BPW
    assert four_bpw.quantization is not five_bpw.quantization


def test_effort_and_model_id_enum_parity_with_registry() -> None:
    """The ledger mirrors the registry Effort/ModelId enums (it must not import the registry — the
    inert ledger is low-dependency). These drift-pins keep the value sets byte-identical so a
    receipt's metered effort/model_id matches a route descriptor's exactly."""
    from shared.platform_capability_registry import Effort as RegistryEffort
    from shared.platform_capability_registry import ModelId as RegistryModelId

    assert {e.value for e in Effort} == {e.value for e in RegistryEffort}
    assert {m.value for m in ModelId} == {m.value for m in RegistryModelId}


def test_agy_receipt_bounded_route_has_guarded_provider_mapping() -> None:
    assert "agy.review.direct" in RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES
    assert (
        RECEIPT_BOUNDED_SUBSCRIPTION_PROVIDERS["agy.review.direct"] == "google-antigravity-cli-agy"
    )
    assert RECEIPT_BOUNDED_SUBSCRIPTION_PROVIDERS["glmcp.review.direct"] == "z_ai-glm-coding-plan"


def test_receipt_bounded_route_accepts_agy_admission_evidence() -> None:
    payload = _active_budget_payload()
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-agy-review-direct-fresh",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "agy.review.direct",
            "provider": "google-antigravity-cli-agy",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [AGY_ADMISSION_EVIDENCE_REF],
            "operator_visible_reason": "fixture agy admission",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "agy.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.FRESH
    assert refs == (AGY_ADMISSION_EVIDENCE_REF,)


def test_receipt_bounded_route_rejects_secretish_agy_witness() -> None:
    payload = _active_budget_payload()
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-agy-review-direct-secretish-witness",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "agy.review.direct",
            "provider": "google-antigravity-cli-agy",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [AGY_SECRETISH_WITNESS_EVIDENCE_REF],
            "operator_visible_reason": "fixture agy secretish witness",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "agy.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert AGY_SECRETISH_WITNESS_EVIDENCE_REF not in refs
    assert any(ref.startswith("quota-evidence-ref:redacted-secretish-sha256:") for ref in refs)
    assert (
        "quota-snapshot:quota-agy-review-direct-secretish-witness:untrusted_agy_admission_evidence"
    ) in refs


def test_agy_receipt_bounded_route_rejects_generic_fresh_quota_snapshot() -> None:
    payload = _active_budget_payload()
    payload["generated_from"].append("scripts/hapax-quota-telemetry-writer")
    payload["quota_snapshots"].append(
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-agy-review-direct-generic-fresh",
            "captured_at": "2026-05-17T07:59:00Z",
            "fresh_until": "2026-05-17T08:05:00Z",
            "route_id": "agy.review.direct",
            "provider": "agy-subscription",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": ["relay-receipt:generic-agy-quota-green"],
            "operator_visible_reason": "fixture generic agy quota snapshot",
        }
    )
    ledger = QuotaSpendLedger.model_validate(payload)

    state, refs = subscription_quota_state_for_route(
        ledger,
        "agy.review.direct",
        now=datetime(2026, 5, 17, 8, 0, tzinfo=UTC),
    )

    assert state is SubscriptionQuotaState.UNKNOWN
    assert "relay-receipt:generic-agy-quota-green" in refs
    assert (
        "quota-snapshot:quota-agy-review-direct-generic-fresh:untrusted_agy_admission_evidence"
        in refs
    )


def test_spend_receipt_meters_effort_and_structured_model_id() -> None:
    """effort defaults to NONE and model_id to None (free-text model_or_engine is retained), and a
    receipt can record a structured dated model_id + the effort the spend was incurred at — so the
    spend plane keys on the same execution axes the route descriptor does."""
    ledger = QuotaSpendLedger.model_validate(
        json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8"))
    )
    base = ledger.spend_receipts[0]
    assert base.effort is Effort.NONE
    assert base.model_id is None  # legacy receipts carry only free-text model_or_engine

    payload = base.model_dump(mode="json")
    payload["model_id"] = "claude-opus-4-8"
    payload["effort"] = "xhigh"
    metered = SpendReceipt.model_validate(payload)
    assert metered.model_id is ModelId.CLAUDE_OPUS_4_8
    assert metered.effort is Effort.XHIGH
    assert metered.model_or_engine == base.model_or_engine  # free-text identity retained alongside
