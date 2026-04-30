"""Tests for nested content-programme outcome contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.content_programme_feedback_ledger import (
    build_feedback_event_from_run_envelope,
    event_allows_public_truth_claim,
)
from shared.content_programme_run_store import (
    REQUIRED_NESTED_PROGRAMME_OUTCOME_KINDS,
    NestedProgrammeOutcome,
    build_fixture_envelope,
    nested_outcome_refs_for_feedback,
    validate_nested_programme_outcomes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_STORE_SCHEMA = REPO_ROOT / "schemas" / "content-programme-run-store-event-surface.schema.json"
FEEDBACK_SCHEMA = REPO_ROOT / "schemas" / "content-programme-feedback-ledger.schema.json"


def _outcome(run_case: str, kind: str) -> NestedProgrammeOutcome:
    run = build_fixture_envelope(run_case)
    return next(outcome for outcome in run.nested_outcomes if outcome.kind == kind)


def test_run_envelope_carries_all_nested_outcome_kinds_and_feedback_consumes_refs() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    feedback = build_feedback_event_from_run_envelope(run)

    assert {outcome.kind for outcome in run.nested_outcomes} == set(
        REQUIRED_NESTED_PROGRAMME_OUTCOME_KINDS
    )
    assert nested_outcome_refs_for_feedback(run) == feedback.nested_programme_outcome_refs
    assert len(feedback.nested_programme_outcome_refs) == 7
    validate_nested_programme_outcomes(run.nested_outcomes)
    assert any(
        outcome.kind == "conversion" and outcome.public_conversion_success
        for outcome in run.nested_outcomes
    )


def test_public_conversion_success_requires_matching_accepted_public_event() -> None:
    run = build_fixture_envelope("public_live_blocked_run")
    conversion = _outcome("public_live_blocked_run", "conversion").model_copy(
        update={
            "state": "linked",
            "public_event_refs": ("ResearchVehiclePublicEvent:missing",),
            "blocked_reasons": (),
            "public_conversion_success": True,
            "learning_update_allowed": True,
        }
    )
    mutated = tuple(
        conversion if outcome.kind == "conversion" else outcome for outcome in run.nested_outcomes
    )

    with pytest.raises(ValueError, match="matching accepted public-event outcome"):
        validate_nested_programme_outcomes(mutated)


def test_conversion_held_run_has_no_public_conversion_success_without_rvpe() -> None:
    run = build_fixture_envelope("conversion_held_run")
    feedback = build_feedback_event_from_run_envelope(run)
    conversion = _outcome("conversion_held_run", "conversion")

    assert conversion.state == "held"
    assert conversion.public_conversion_success is False
    assert "research_vehicle_public_event_missing" in conversion.blocked_reasons
    validate_nested_programme_outcomes(run.nested_outcomes)
    assert not any(
        outcome.kind == "conversion" and outcome.public_conversion_success
        for outcome in run.nested_outcomes
    )
    assert feedback.programme_state == "conversion_held"
    assert event_allows_public_truth_claim(feedback) is False


@pytest.mark.parametrize(
    ("run_case", "kind", "state"),
    [
        ("refusal_run", "refusal", "refused"),
        ("correction_run", "correction", "corrected"),
    ],
)
def test_refusal_and_correction_learning_do_not_validate_refused_claim(
    run_case: str,
    kind: str,
    state: str,
) -> None:
    run = build_fixture_envelope(run_case)
    feedback = build_feedback_event_from_run_envelope(run)
    outcome = _outcome(run_case, kind)

    assert outcome.state == state
    assert outcome.learning_update_allowed is True
    assert outcome.claim_posterior_update_allowed is False
    assert outcome.public_conversion_success is False
    assert outcome.validates_refused_claim is False
    assert event_allows_public_truth_claim(feedback) is False


def test_nested_outcome_graph_fails_closed_when_required_stage_is_missing() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    missing_correction = tuple(
        outcome for outcome in run.nested_outcomes if outcome.kind != "correction"
    )

    with pytest.raises(ValueError, match="missing kinds: correction"):
        validate_nested_programme_outcomes(missing_correction)


def test_schema_surfaces_nested_outcomes_to_run_store_and_feedback_ledger() -> None:
    run_schema = json.loads(RUN_STORE_SCHEMA.read_text(encoding="utf-8"))
    feedback_schema = json.loads(FEEDBACK_SCHEMA.read_text(encoding="utf-8"))
    feedback_event = feedback_schema["$defs"]["content_programme_feedback_event"]

    assert "nested_outcomes" in run_schema["required"]
    assert "nested_outcomes" in run_schema["properties"]
    assert set(run_schema["x-required_nested_programme_outcome_kinds"]) == set(
        REQUIRED_NESTED_PROGRAMME_OUTCOME_KINDS
    )
    assert "nested_programme_outcome_refs" in feedback_event["required"]
    assert "nested_programme_outcome_refs" in feedback_event["properties"]
