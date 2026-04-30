"""Tests for the grant opportunity scout and attestation queue."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from shared.application_obligation_refusal import ApplicationObligation
from shared.grant_opportunity_scout import (
    DEFAULT_GRANT_FIXTURE_PATH,
    GrantOpportunityRecord,
    OperatorAttestationRequirement,
    PrivateEvidencePacket,
    evaluate_grant_opportunity,
    load_grant_opportunity_fixtures,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas" / "grant-opportunity-scout.schema.json"


def test_fixture_packet_validates_against_json_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(DEFAULT_GRANT_FIXTURE_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_fixture_packet_loads_and_declares_non_manual_scout_sources() -> None:
    fixtures = load_grant_opportunity_fixtures()

    assert fixtures.fixture_set_id == "grant_opportunity_scout_attestation_queue"
    assert {source.requires_manual_opportunity_chasing for source in fixtures.scout_sources} == {
        False
    }
    assert {source.automation_mode for source in fixtures.scout_sources} <= {
        "api",
        "rss",
        "site_watch",
        "mailbox_parser",
        "operator_seeded_once",
    }


def test_fixture_decisions_match_expected_contract() -> None:
    fixtures = load_grant_opportunity_fixtures()

    for fixture in fixtures.fixtures:
        decision = evaluate_grant_opportunity(fixture.opportunity)

        assert decision.queue_state == fixture.expected_queue_state, fixture.fixture_id
        assert set(fixture.expected_refusal_reasons) <= set(decision.refusal_reasons)
        assert set(fixture.expected_operator_actions) <= set(decision.operator_actions)
        assert decision.handled_by_fast_path_task is fixture.expected_fast_path
        assert decision.public_release_allowed is False
        assert decision.monetization_allowed is False
        assert decision.institutional_public_claim_allowed is False


def test_openai_fast_path_is_referenced_not_overwritten() -> None:
    fixture = next(
        fixture
        for fixture in load_grant_opportunity_fixtures().fixtures
        if fixture.fixture_id == "openai_fast_path_referenced_not_overwritten"
    )

    decision = evaluate_grant_opportunity(fixture.opportunity)

    assert fixture.opportunity.urgent_fast_path_task_id == "openai-safety-fellowship-fast-packet"
    assert decision.handled_by_fast_path_task is True
    assert decision.queue_state == "operator_attestation_required"
    assert decision.evidence_packet_refs == ("grant-evidence:openai-safety-fellowship-fast-packet",)


def test_private_evidence_packet_cannot_grant_public_or_money_authority() -> None:
    fixtures = load_grant_opportunity_fixtures()

    for fixture in fixtures.fixtures:
        opportunity = fixture.opportunity
        decision = evaluate_grant_opportunity(opportunity)

        assert opportunity.target_family == "grants_fellowships"
        assert opportunity.readiness_state_ceiling == "private-evidence"
        assert opportunity.public_release_allowed is False
        assert opportunity.monetization_allowed is False
        assert opportunity.institutional_public_claim_allowed is False
        assert opportunity.evidence_packet.public_release_allowed is False
        assert opportunity.evidence_packet.monetization_allowed is False
        assert decision.private_evidence_allowed is True


def test_refused_obligation_classes_fail_closed() -> None:
    fixtures = load_grant_opportunity_fixtures()
    by_id = {fixture.fixture_id: fixture for fixture in fixtures.fixtures}

    expected = {
        "fake_affiliation_refused": "fake_affiliation",
        "recurring_reporting_refused": "recurring_reports",
        "private_data_exposure_refused": "private_data_exposure",
        "custom_performance_refused": "custom_performance",
        "community_service_refused": "customer_service_obligation",
        "manual_opportunity_chasing_refused": "manual_opportunity_chasing",
    }
    for fixture_id, reason in expected.items():
        decision = evaluate_grant_opportunity(by_id[fixture_id].opportunity)

        assert decision.queue_state == "refused"
        assert reason in decision.refusal_reasons


def test_required_attestation_must_be_explicit_operator_act() -> None:
    with pytest.raises(ValidationError, match="required attestation"):
        OperatorAttestationRequirement(
            required=True,
            explicit_operator_act_only=True,
            operator_action="one_time_bootstrap",
            operator_visible_reason="invalid attestation shape",
        )


def test_urgent_fast_path_id_must_match_opportunity_id() -> None:
    base = load_grant_opportunity_fixtures().fixtures[1].opportunity

    with pytest.raises(ValidationError, match="urgent fast path task id"):
        GrantOpportunityRecord.model_validate(
            base.model_dump(mode="json")
            | {"urgent_fast_path_task_id": "openai-safety-fellowship-fast-packet"}
        )


def test_attestation_required_needs_legal_attestation_obligation() -> None:
    base = load_grant_opportunity_fixtures().fixtures[1].opportunity
    payload = base.model_dump(mode="json")
    payload["attestation"] = {
        "required": True,
        "explicit_operator_act_only": True,
        "operator_action": "explicit_legal_attestation",
        "attestation_ref": None,
        "operator_visible_reason": "attestation requested",
    }

    with pytest.raises(ValidationError, match="legal_attestation obligation"):
        GrantOpportunityRecord.model_validate(payload)


def test_lifecycle_states_are_preserved_for_outcome_tracking() -> None:
    base = load_grant_opportunity_fixtures().fixtures[1].opportunity

    for lifecycle_state in ("submitted", "won", "lost", "disbursed", "follow_up_due"):
        opportunity = GrantOpportunityRecord.model_validate(
            base.model_dump(mode="json") | {"lifecycle_state": lifecycle_state}
        )
        decision = evaluate_grant_opportunity(opportunity)

        assert decision.queue_state == lifecycle_state


def test_evidence_packet_requires_privacy_and_provenance_labels() -> None:
    with pytest.raises(ValidationError):
        PrivateEvidencePacket(
            packet_id="grant-evidence:bad",
            evidence_refs=("cc-task:n1-methodology-dossier",),
            privacy_labeled=False,
            provenance_labeled=True,
            public_release_allowed=False,
            monetization_allowed=False,
        )


def test_model_accepts_application_obligation_instances() -> None:
    obligation = ApplicationObligation(
        class_id="bootstrap_setup",
        recurrence="one_time",
        automation_fit="automated",
        summary="One-time account setup.",
    )

    assert obligation.class_id == "bootstrap_setup"
