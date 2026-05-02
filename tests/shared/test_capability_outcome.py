"""Tests for CapabilityOutcomeEnvelope fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.capability_outcome import (
    OUTCOME_ENVELOPE_REQUIRED_FIELDS,
    REQUIRED_NO_UPDATE_CASES,
    REQUIRED_OUTCOME_STATUSES,
    CapabilityOutcomeEnvelope,
    CapabilityOutcomeError,
    FixtureCase,
    OutcomeStatus,
    WitnessPolicy,
    load_capability_outcome_fixtures,
)


def test_capability_outcome_loader_covers_statuses_fields_and_no_update_cases() -> None:
    fixtures = load_capability_outcome_fixtures()

    assert {status.value for status in fixtures.outcome_statuses} == REQUIRED_OUTCOME_STATUSES
    assert {case.value for case in fixtures.no_update_fixture_cases} == REQUIRED_NO_UPDATE_CASES
    assert set(fixtures.outcome_envelope_required_fields) == set(OUTCOME_ENVELOPE_REQUIRED_FIELDS)

    outcomes = fixtures.outcomes
    assert {outcome.outcome_status.value for outcome in outcomes} == REQUIRED_OUTCOME_STATUSES
    assert {outcome.fixture_case.value for outcome in outcomes} >= REQUIRED_NO_UPDATE_CASES


def test_witnessed_success_can_update_action_success_without_claim_posterior() -> None:
    fixtures = load_capability_outcome_fixtures()
    outcome = fixtures.require_outcome("coe:audio.public-tts:witnessed-success")

    assert outcome.outcome_status is OutcomeStatus.SUCCESS
    assert outcome.witness_policy is WitnessPolicy.WITNESSED
    assert outcome.validates_success() is True
    assert outcome.allows_verified_public_or_action_success_update() is True
    assert outcome.verified_success.action is True
    assert outcome.verified_success.public is False
    assert outcome.allows_claim_posterior_update() is False


def test_public_event_accepted_requires_evidence_and_gate_refs() -> None:
    fixtures = load_capability_outcome_fixtures()
    outcome = fixtures.require_outcome("coe:public-event.rvpe:accepted")

    assert outcome.outcome_status is OutcomeStatus.PUBLIC_EVENT_ACCEPTED
    assert outcome.validates_success() is True
    assert outcome.verified_success.public is True
    assert outcome.allows_verified_public_or_action_success_update() is True
    assert outcome.allows_claim_posterior_update() is True
    assert outcome.public_claim_evidence.evidence_envelope_refs
    assert outcome.public_claim_evidence.public_event_refs == [
        "ResearchVehiclePublicEvent:segment-9"
    ]
    assert outcome.public_claim_evidence.gate_refs


def test_refusal_success_does_not_validate_refused_claim() -> None:
    fixtures = load_capability_outcome_fixtures()
    outcome = fixtures.require_outcome("coe:governance.no-expert:refused")

    assert outcome.outcome_status is OutcomeStatus.REFUSED
    assert outcome.validates_success() is True
    assert outcome.learning_update.allowed is True
    assert outcome.verified_success.capability is True
    assert outcome.verified_success.public is False
    assert outcome.verified_success.claim_posterior is False
    assert outcome.allows_claim_posterior_update() is False


@pytest.mark.parametrize(
    ("fixture_case", "expected_outcome_id"),
    [
        (FixtureCase.SELECTED_ONLY, "coe:content.candidate:selected-only"),
        (FixtureCase.COMMANDED_ONLY, "coe:midi.transport:commanded-only"),
        (FixtureCase.INFERRED, "coe:perception.context:inferred"),
        (FixtureCase.STALE, "coe:archive.replay:stale"),
        (FixtureCase.MISSING, "coe:tool.sources:missing"),
        (FixtureCase.LEGACY_PUBLIC_EVENT, "coe:public-event.legacy:missing-gate"),
    ],
)
def test_no_update_cases_cannot_validate_success_or_public_action_updates(
    fixture_case: FixtureCase,
    expected_outcome_id: str,
) -> None:
    fixtures = load_capability_outcome_fixtures()
    rows = fixtures.rows_for_fixture_case(fixture_case)

    assert [row.outcome_id for row in rows] == [expected_outcome_id]
    row = rows[0]
    assert row.validates_success() is False
    assert row.allows_verified_public_or_action_success_update() is False
    assert row.allows_claim_posterior_update() is False
    assert row.learning_update.allowed is False
    assert row.verified_success.capability is False
    assert row.verified_success.action is False
    assert row.verified_success.public is False
    assert row.verified_success.claim_posterior is False
    assert f"fixture_case:{fixture_case.value}" in row.success_blockers()


@pytest.mark.parametrize(
    "outcome_id",
    [
        "coe:content.candidate:selected-only",
        "coe:midi.transport:commanded-only",
        "coe:perception.context:inferred",
        "coe:archive.replay:stale",
        "coe:tool.sources:missing",
        "coe:public-event.legacy:missing-gate",
    ],
)
def test_mutated_no_update_rows_raise_explicit_errors(outcome_id: str) -> None:
    fixtures = load_capability_outcome_fixtures()
    payload = fixtures.require_outcome(outcome_id).model_dump(mode="json")
    payload["learning_update"]["allowed"] = True
    payload["learning_update"]["policy"] = "success"
    payload["learning_update"]["target"] = "affordance_activation"
    payload["learning_update"]["required_witness_refs"] = ["witness:fake"]
    payload["verified_success"]["capability"] = True
    payload["verified_success"]["action"] = True

    with pytest.raises(ValueError, match="no-update fixture cannot allow learning"):
        CapabilityOutcomeEnvelope.model_validate(payload)


def test_legacy_public_event_without_rvpe_gate_cannot_update_public_learning() -> None:
    fixtures = load_capability_outcome_fixtures()
    outcome = fixtures.require_outcome("coe:public-event.legacy:missing-gate")

    assert outcome.fixture_case is FixtureCase.LEGACY_PUBLIC_EVENT
    assert outcome.witness_policy is WitnessPolicy.LEGACY_PUBLIC_EVENT
    assert outcome.validates_success() is False
    assert outcome.allows_verified_public_or_action_success_update() is False
    assert outcome.allows_claim_posterior_update() is False
    assert outcome.verified_success.public is False
    assert outcome.verified_success.claim_posterior is False
    assert "ResearchVehiclePublicEvent:segment-legacy" in (
        outcome.learning_update.missing_witness_refs
    )
    assert "fixture_case:legacy_public_event" in outcome.success_blockers()
    assert outcome.programme_refs == ["programme:runner-refusal-harness"]
    assert outcome.health_refs == ["world-surface-health:public-event.legacy.blocked"]


def test_claim_posterior_update_without_public_evidence_fails_closed() -> None:
    fixtures = load_capability_outcome_fixtures()
    payload = fixtures.require_outcome("coe:audio.public-tts:witnessed-success").model_dump(
        mode="json"
    )
    payload["claim_posterior_update"]["allowed"] = True
    payload["claim_posterior_update"]["claim_ids"] = ["claim:unsupported"]
    payload["claim_posterior_update"]["evidence_envelope_refs"] = ["evidence-envelope:fake"]
    payload["claim_posterior_update"]["gate_refs"] = ["gate:fake"]

    with pytest.raises(ValueError, match="claim posterior update requires public claim evidence"):
        CapabilityOutcomeEnvelope.model_validate(payload)


def test_fixture_summary_mismatch_fails_closed(tmp_path: Path) -> None:
    fixtures = load_capability_outcome_fixtures()
    payload = fixtures.model_dump(mode="json")
    payload["summary"]["success_validated_count"] = 99

    path = tmp_path / "bad-capability-outcome-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CapabilityOutcomeError, match="summary does not match outcomes"):
        load_capability_outcome_fixtures(path)
