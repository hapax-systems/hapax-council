"""Tests for the grant attestation operating-system contract."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from shared.grant_attestation_operating_system import (
    LIFECYCLE_SEQUENCE,
    FundingEvidenceIntake,
    GrantOperatingFixture,
    GrantOperatingRecord,
    evaluate_grant_operating_record,
    load_grant_operating_fixtures,
    materialize_grant_operating_record,
)

TODAY = date(2026, 5, 1)


def _fixtures_by_id() -> dict[str, GrantOperatingFixture]:
    return {fixture.fixture_id: fixture for fixture in load_grant_operating_fixtures().fixtures}


def _record(fixture_id: str) -> GrantOperatingRecord:
    return materialize_grant_operating_record(_fixtures_by_id()[fixture_id])


def test_lifecycle_sequence_declares_full_operating_system() -> None:
    assert LIFECYCLE_SEQUENCE == (
        "discovered",
        "eligible",
        "refused",
        "drafted",
        "ready_for_attestation",
        "submitted",
        "won",
        "lost",
        "disbursed",
        "follow_up",
    )


def test_fixture_packet_materializes_and_matches_expected_decisions() -> None:
    fixture_set = load_grant_operating_fixtures()

    for fixture in fixture_set.fixtures:
        record = materialize_grant_operating_record(fixture)
        decision = evaluate_grant_operating_record(record, today=TODAY)

        assert decision.lifecycle_state == fixture.expected_lifecycle_state, fixture.fixture_id
        assert set(fixture.expected_refusal_reasons) <= set(decision.refusal_reasons)
        assert set(fixture.expected_operator_actions) <= set(decision.operator_actions)
        assert decision.operator_opportunity_chasing_required is False
        assert decision.public_release_allowed is False
        assert decision.monetization_allowed is False
        assert decision.institutional_public_claim_allowed is False
        assert record.requires_operator_opportunity_chasing is False
        assert record.source_row.id == fixture.source_row_id
        assert set(record.evidence_intake.reusable_evidence_packet_refs) <= set(
            decision.evidence_refs
        )
        assert set(record.evidence_intake.demo_kit_refs) <= set(decision.evidence_refs)
        assert set(record.evidence_intake.n1_methodology_refs) <= set(decision.evidence_refs)
        assert set(record.evidence_intake.public_event_proof_refs) <= set(decision.evidence_refs)


def test_ready_for_attestation_is_one_explicit_operator_act() -> None:
    record = _record("ready_residency_attestation")
    decision = evaluate_grant_operating_record(record, today=TODAY)

    assert decision.lifecycle_state == "ready_for_attestation"
    assert decision.attestation_state == "required_pending_operator"
    assert decision.submission_allowed is False
    assert "explicit_legal_attestation" in decision.operator_actions
    assert "operator attestation act" in decision.operator_visible_reason


def test_ready_for_attestation_cannot_already_have_attestation_ref() -> None:
    record = _record("ready_residency_attestation")
    payload = record.model_dump(mode="json") | {
        "operator_attestation_ref": "operator-attestation:already-done"
    }

    with pytest.raises(ValidationError, match="wait for the operator act"):
        GrantOperatingRecord.model_validate(payload)


def test_submitted_state_requires_operator_attestation_ref_when_required() -> None:
    record = _record("submitted_openai_after_attestation")
    payload = record.model_dump(mode="json") | {"operator_attestation_ref": None}

    with pytest.raises(ValidationError, match="operator_attestation_ref"):
        GrantOperatingRecord.model_validate(payload)


def test_refused_obligation_classes_fail_closed() -> None:
    base = _fixtures_by_id()["refused_fake_affiliation"]
    expected = {
        "fake_affiliation_refused": "fake_affiliation",
        "recurring_reporting_refused": "recurring_reports",
        "private_data_exposure_refused": "private_data_exposure",
        "custom_performance_refused": "custom_performance",
        "community_service_refused": "customer_service_obligation",
        "manual_opportunity_chasing_refused": "manual_opportunity_chasing",
    }

    for opportunity_fixture_id, reason in expected.items():
        fixture = GrantOperatingFixture.model_validate(
            base.model_dump(mode="json")
            | {
                "fixture_id": f"os_{opportunity_fixture_id}",
                "opportunity_fixture_id": opportunity_fixture_id,
            }
        )
        decision = evaluate_grant_operating_record(
            materialize_grant_operating_record(fixture),
            today=TODAY,
        )

        assert decision.lifecycle_state == "refused"
        assert reason in decision.refusal_reasons
        assert decision.submission_allowed is False


def test_evidence_intake_requires_all_consumed_packet_families() -> None:
    record = _record("drafted_compute_credit")
    decision = evaluate_grant_operating_record(record, today=TODAY)

    assert "funding-evidence:core-private-v0" in decision.evidence_refs
    assert "demo-kit:runtime-truth-private-v0" in decision.evidence_refs
    assert "cc-task:n1-methodology-dossier" in decision.evidence_refs
    assert "rvpe:private-proof-hold" in decision.evidence_refs

    with pytest.raises(ValidationError):
        FundingEvidenceIntake(
            reusable_evidence_packet_refs=("funding-evidence:core-private-v0",),
            demo_kit_refs=("demo-kit:runtime-truth-private-v0",),
            n1_methodology_refs=("cc-task:n1-methodology-dossier",),
            public_event_proof_refs=(),
            scout_evidence_packet_refs=("grant-evidence:compute-credit-bootstrap",),
        )


def test_deadlines_and_follow_up_are_machine_tracked_without_chasing() -> None:
    submitted = _record("submitted_openai_after_attestation")
    follow_up = _record("follow_up_compute_credit")

    submitted_decision = evaluate_grant_operating_record(submitted, today=TODAY)
    follow_up_decision = evaluate_grant_operating_record(follow_up, today=TODAY)

    assert submitted_decision.deadline_status == "due_soon"
    assert submitted_decision.follow_up_required is False
    assert submitted_decision.operator_opportunity_chasing_required is False
    assert follow_up_decision.deadline_status == "no_deadline"
    assert follow_up_decision.follow_up_required is True
    assert follow_up_decision.operator_opportunity_chasing_required is False


def test_outcome_states_store_evidence_for_posterior_and_stakeholder_reporting() -> None:
    decision = evaluate_grant_operating_record(_record("follow_up_compute_credit"), today=TODAY)

    assert decision.outcome_evidence_refs == ("grant-outcome:compute-credit-follow-up-due",)
    assert decision.posterior_update_refs == ("posterior:grant-follow-up-due",)
    assert decision.stakeholder_report_refs == ("stakeholder:grant-follow-up-state",)

    record = _record("follow_up_compute_credit")
    payload = record.model_dump(mode="json") | {"outcome_evidence_refs": []}
    with pytest.raises(ValidationError, match="outcome_evidence_refs"):
        GrantOperatingRecord.model_validate(payload)

    payload = record.model_dump(mode="json") | {"posterior_update_refs": []}
    with pytest.raises(ValidationError, match="posterior_update_refs"):
        GrantOperatingRecord.model_validate(payload)

    payload = record.model_dump(mode="json") | {"stakeholder_report_refs": []}
    with pytest.raises(ValidationError, match="stakeholder_report_refs"):
        GrantOperatingRecord.model_validate(payload)


def test_source_registry_refusal_triggers_fail_closed() -> None:
    record = _record("ready_residency_attestation")
    decision = evaluate_grant_operating_record(
        record,
        today=TODAY,
        active_refusal_triggers=("requires_in_person_event",),
    )

    assert decision.lifecycle_state == "refused"
    assert decision.submission_allowed is False
