"""Tests for private resource-capability schema/projection models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.resource_capability import (
    FORBIDDEN_PROVIDER_WRITE_SCOPES,
    AutonomyDebtEvent,
    AvoidabilityClass,
    CalendarWriteEnvelope,
    DecisionState,
    ExpectedMailCandidate,
    GrowthNoGoMatrix,
    MonetaryCapability,
    NoGoDecision,
    PublicResourceClaimEnvelope,
    ResourceCapability,
    ResourceOpportunity,
    ResourceValuation,
    SemanticTransactionTrace,
    TransactionPressureLedger,
    load_resource_capability_fixtures,
)


def test_models_are_strict_and_forbid_extra_fields() -> None:
    fixtures = load_resource_capability_fixtures()
    payload = fixtures.opportunities[0].model_dump(mode="json")
    payload["unexpected_runtime_field"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResourceOpportunity.model_validate(payload)


def test_monetary_capability_is_resource_capability_subtype() -> None:
    fixtures = load_resource_capability_fixtures()
    monetary = fixtures.monetary_capabilities[0]

    assert isinstance(monetary, ResourceCapability)
    assert issubclass(MonetaryCapability, ResourceCapability)
    assert monetary.monetary_capability_kind == "resource_capability_subtype"


def test_nominal_cash_equivalent_and_operational_values_remain_separate() -> None:
    fixtures = load_resource_capability_fixtures()
    capability = fixtures.capabilities[0]
    valuation = capability.valuation

    assert valuation.nominal_value == 5000
    assert valuation.cash_equivalent_value == 0
    assert valuation.operational_capability_value == 8200
    assert valuation.operational_capability_value != valuation.revenue_value

    missing_cash = valuation.model_dump(mode="json")
    missing_cash.pop("cash_equivalent_value")
    with pytest.raises(ValidationError, match="cash_equivalent_value"):
        ResourceValuation.model_validate(missing_cash)


def test_unknown_cash_equivalent_cannot_fall_back_to_nominal_value() -> None:
    valuation = ResourceValuation(
        nominal_value=100,
        nominal_unit="USD_RECEIVABLE",
        cash_equivalent_value=None,
        cash_equivalent_currency="USD",
        operational_capability_value=0,
        revenue_value=0,
        trust_cost=1,
        conversion_confidence=0,
        value_basis_refs=["evidence:unknown"],
    )

    assert valuation.cash_equivalent_value is None
    assert valuation.nominal_value == 100


def test_public_claim_envelope_defaults_to_blocked() -> None:
    fixtures = load_resource_capability_fixtures()
    envelope = fixtures.public_claim_envelopes[0]

    assert envelope.claim_allowed is False
    assert envelope.evidence_refs == []
    assert envelope.counterparty_terms_refs == []

    payload = envelope.model_dump(mode="json")
    payload["claim_allowed"] = True
    with pytest.raises(ValidationError, match="public resource claim requires evidence"):
        PublicResourceClaimEnvelope.model_validate(payload)


def test_hard_boundary_operator_actions_are_autonomy_debt() -> None:
    fixtures = load_resource_capability_fixtures()
    debt = fixtures.autonomy_debt_events[0]

    assert debt.hard_boundary is True
    assert debt.avoidability is AvoidabilityClass.EXTERNAL_HARD_BOUNDARY
    assert debt.recurrence_key == "provider_terms_review"

    payload = debt.model_dump(mode="json")
    payload["avoidability"] = "reducible"
    with pytest.raises(ValidationError, match="hard boundary autonomy debt"):
        AutonomyDebtEvent.model_validate(payload)


def test_growth_no_go_matrix_blocks_forbidden_and_unknown_scopes() -> None:
    fixtures = load_resource_capability_fixtures()
    matrix = fixtures.growth_no_go_matrix

    assert {scope.value for scope in matrix.forbidden_provider_write_scopes} == (
        FORBIDDEN_PROVIDER_WRITE_SCOPES
    )
    for scope in FORBIDDEN_PROVIDER_WRITE_SCOPES:
        assert matrix.decision_for(scope) is NoGoDecision.BLOCKED
    assert matrix.decision_for("new_provider_write_scope") is NoGoDecision.BLOCKED

    payload = matrix.model_dump(mode="json")
    payload["rules"][0]["decision"] = "requires_later_authority"
    with pytest.raises(ValidationError, match="must fail closed"):
        GrowthNoGoMatrix.model_validate(payload)


def test_expected_mail_candidate_allows_only_sanitized_fields() -> None:
    fixtures = load_resource_capability_fixtures()
    candidate = fixtures.expected_mail_candidates[0]

    assert candidate.message_id_hash.startswith("sha256:")
    assert candidate.sender_identity_token == "sender-domain-hash:provider"

    payload = candidate.model_dump(mode="json")
    payload["raw_body_text"] = "secret body"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExpectedMailCandidate.model_validate(payload)

    payload = candidate.model_dump(mode="json")
    payload["sender_identity_token"] = "person@example.com"
    with pytest.raises(ValidationError, match="full sender address"):
        ExpectedMailCandidate.model_validate(payload)


def test_calendar_write_envelope_blocks_external_effects_by_default() -> None:
    fixtures = load_resource_capability_fixtures()
    envelope = fixtures.calendar_write_envelopes[0]

    assert envelope.attendee_policy == "blocked_none"
    assert envelope.notification_policy == "blocked_none"
    assert envelope.conference_data_policy == "blocked_none"
    assert envelope.availability_promise is False

    payload = envelope.model_dump(mode="json")
    payload["attendee_policy"] = "allow_external_attendees"
    with pytest.raises(ValidationError, match="blocked_none"):
        CalendarWriteEnvelope.model_validate(payload)


def test_stale_surface_conflicts_remain_blocked_stale_conflict() -> None:
    fixtures = load_resource_capability_fixtures()
    stale = fixtures.opportunities[1]

    assert stale.decision_state is DecisionState.BLOCKED_STALE_CONFLICT
    assert stale.stale_conflict_refs

    payload = stale.model_dump(mode="json")
    payload["decision_state"] = "observe_only"
    with pytest.raises(ValidationError, match="stale conflicts"):
        ResourceOpportunity.model_validate(payload)


def test_semantic_transaction_trace_is_private_observability_only() -> None:
    fixtures = load_resource_capability_fixtures()
    trace = fixtures.semantic_transaction_traces[0]
    ledger = fixtures.transaction_pressure_ledgers[0]

    assert trace.privacy_scope == "private"
    assert trace.public_projection_allowed is False
    assert trace.observability_surface == "machine_operator_only"
    assert trace.runtime_tracing_authorized is False
    assert trace.provider_api_execution_authorized is False
    assert trace.autonomy_debt_event_refs == ["autonomy-debt:operator-terms-review"]
    assert ledger.public_projection_allowed is False
    assert ledger.provider_poll_authorized is False
    assert ledger.external_effect_authorized is False

    payload = trace.model_dump(mode="json")
    payload["public_projection_allowed"] = True
    with pytest.raises(ValidationError, match="False"):
        SemanticTransactionTrace.model_validate(payload)

    ledger_payload = ledger.model_dump(mode="json")
    for key in (
        "transaction_pressure_refs",
        "transaction_refs",
        "communication_refs",
        "action_refs",
        "waiting_state_refs",
        "event_refs",
        "refusal_refs",
        "escalation_refs",
        "provider_state_refs",
        "calendar_obligation_refs",
    ):
        ledger_payload[key] = []
    with pytest.raises(ValidationError, match="semantic surface refs"):
        TransactionPressureLedger.model_validate(ledger_payload)


def test_resource_capability_module_has_no_provider_or_runtime_imports() -> None:
    source = Path("shared/resource_capability.py").read_text(encoding="utf-8")

    forbidden_tokens = [
        "googleapiclient",
        "smtplib",
        "stripe",
        "agents.mail_monitor",
        "agents.gmail_sync",
        "agents.gcalendar_sync",
        "payment_rails",
        "events.insert",
        "events.patch",
    ]
    for token in forbidden_tokens:
        assert token not in source
