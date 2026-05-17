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
    QUOTA_SPEND_LEDGER_FIXTURES,
    ArtifactProvenanceRecord,
    BootstrapDependencyState,
    BudgetLifecycleState,
    DependencyState,
    PaidApiBudgetState,
    PaidRouteRequest,
    QuotaSpendLedger,
    SpendGateDecisionState,
    SpendReconciliationState,
    SupportArtifactAuthority,
    SupportArtifactDisposition,
    build_dashboard,
    evaluate_paid_route_eligibility,
    load_quota_spend_ledger,
)

NOW = datetime(2026, 5, 17, 8, 0, 0, tzinfo=UTC)


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


def _request(**overrides: object) -> PaidRouteRequest:
    payload: dict[str, object] = {
        "route_id": "opaque.route.bootstrap",
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
    dashboard = build_dashboard(load_quota_spend_ledger(), now=NOW)

    assert dashboard.paid_api_budget_state is PaidApiBudgetState.ACTIVE
    assert dashboard.bootstrap_dependency_state is BootstrapDependencyState.NONE
    assert dashboard.provider_dependency_count == 0
    assert dashboard.support_artifacts_waiting_for_review == 0
    assert "bootstrap_dependency_state:expired" not in dashboard.non_green_states
    assert "spend_reconciliation_overdue" not in dashboard.non_green_states
    assert dashboard.frozen_spend_refs == ("spend-20260509T193000Z-opaque-route",)
    assert dashboard.closed_provider_dependency_refs == ("dep-opaque-provider-bootstrap",)
    assert dashboard.closed_support_artifact_refs == ("artifacts/support/bootstrap-draft.md",)
    assert dashboard.paid_api_route_eligible is True


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
