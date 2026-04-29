"""Tests for content programme feedback-ledger helper models."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError

from shared.content_programme_feedback_ledger import (
    PROGRAMME_OUTCOME_STATES,
    AudienceMetric,
    AudienceOutcome,
    CapabilityOutcomeWitness,
    ContentProgrammeFeedbackEvent,
    PosteriorUpdate,
    ProgrammeOutcomeState,
    append_feedback_event,
    audience_outcome_is_aggregate_only,
    build_feedback_fixture,
    event_allows_public_truth_claim,
    posterior_update_is_evidence_bound,
    witnessed_outcome_allows_posterior_update,
)


def _event(state: ProgrammeOutcomeState = "completed") -> ContentProgrammeFeedbackEvent:
    return build_feedback_fixture(state, generated_at=datetime(2026, 4, 29, tzinfo=UTC))


def test_append_feedback_event_rejects_duplicate_ids_and_idempotency_keys() -> None:
    first = _event("completed")
    events = append_feedback_event((), first)

    try:
        append_feedback_event(events, first)
    except ValueError as exc:
        assert "duplicate ledger_event_id" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("duplicate ledger event should be rejected")

    duplicate_key = _event("public_run").model_copy(
        update={
            "ledger_event_id": "feedback:other",
            "idempotency_key": first.idempotency_key,
        }
    )

    try:
        append_feedback_event(events, duplicate_key)
    except ValueError as exc:
        assert "duplicate idempotency_key" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("duplicate feedback idempotency key should be rejected")


def test_audience_outcome_accepts_aggregate_only_metrics() -> None:
    outcome = AudienceOutcome(
        metrics=(
            AudienceMetric(
                metric_name="watch_time",
                value=0.58,
                sample_size=12,
                aggregate_ref="audience:aggregate:a",
                evidence_refs=("analytics:aggregate:a",),
            ),
        ),
        evidence_refs=("analytics:aggregate:a",),
    )

    assert audience_outcome_is_aggregate_only(outcome) is True

    try:
        AudienceMetric(
            metric_name="watch_time",
            value=0.58,
            sample_size=12,
            identity_scope="person",
            aggregate_ref="audience:person:a",
            evidence_refs=("analytics:person:a",),
        )
    except ValidationError as exc:
        assert "identity_scope" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("per-person audience metrics should be rejected")


def test_witnessed_outcomes_require_verified_witness_and_evidence_envelope() -> None:
    verified = CapabilityOutcomeWitness(
        capability_outcome_ref="coe:a",
        capability_outcome_envelope_ref="CapabilityOutcomeEnvelope:coe:a",
        witness_state="witness_verified",
        evidence_envelope_refs=("ee:a",),
        posterior_update_allowed=True,
    )
    missing = verified.model_copy(update={"evidence_envelope_refs": ()})
    inferred = verified.model_copy(update={"witness_state": "inferred_only"})

    assert witnessed_outcome_allows_posterior_update(verified) is True
    assert witnessed_outcome_allows_posterior_update(missing) is False
    assert witnessed_outcome_allows_posterior_update(inferred) is False


def test_posterior_update_proposals_must_be_evidence_bound_and_do_not_mutate_store() -> None:
    update = PosteriorUpdate(
        update_id="posterior:grounding:a",
        posterior_family="grounding_quality",
        target_ref="content-opportunity-model.posterior_state.grounding_yield_probability",
        source_signal="format_grounding_evaluation",
        value=0.82,
        confidence=0.74,
        prior_ref="posterior:grounding:a:prior",
        evidence_refs=("fge:a", "ee:a"),
        update_allowed=True,
    )

    assert posterior_update_is_evidence_bound(update) is True
    assert (
        posterior_update_is_evidence_bound(update.model_copy(update={"evidence_refs": ()})) is False
    )
    assert (
        posterior_update_is_evidence_bound(
            update.model_copy(update={"blocked_reason": "missing_evidence_ref"})
        )
        is False
    )


def test_blocked_refused_corrected_private_only_and_aborted_never_become_public_truth() -> None:
    for state in ("blocked", "refused", "corrected", "private_only", "aborted"):
        event = _event(state)
        assert event.learning_policy.blocked_refused_corrected_private_only_are_learning_events
        assert event_allows_public_truth_claim(event) is False
        assert event.learning_policy.posterior_store_mutation_allowed is False


def test_fixture_builder_covers_all_outcome_states_and_separates_learning_channels() -> None:
    for state in PROGRAMME_OUTCOME_STATES:
        event = _event(state)

        assert event.programme_state == state
        assert event.selected_state_refs
        assert event.commanded_state_refs
        assert event.separation_policy.selected_commanded_states_update_posteriors is False
        assert event.separation_policy.engagement_can_override_grounding is False
        assert event.separation_policy.revenue_can_override_grounding is False
        assert event.learning_policy.posterior_store_mutation_allowed is False

    completed = _event("completed")
    assert event_allows_public_truth_claim(completed) is True
    assert any(
        update.posterior_family == "grounding_quality" for update in completed.posterior_updates
    )
    assert audience_outcome_is_aggregate_only(completed.audience_outcome) is True
