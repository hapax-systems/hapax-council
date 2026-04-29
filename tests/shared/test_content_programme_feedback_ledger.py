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
    RevenueProxy,
    append_feedback_event,
    audience_outcome_is_aggregate_only,
    build_feedback_event_from_run_envelope,
    build_feedback_fixture,
    build_scheduler_policy_feedback,
    event_allows_public_truth_claim,
    posterior_update_is_evidence_bound,
    witnessed_outcome_allows_posterior_update,
)
from shared.content_programme_run_store import build_fixture_envelope


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


def test_live_wire_records_refusal_as_successful_safety_learning_event() -> None:
    run = build_fixture_envelope("refusal_run")
    event = build_feedback_event_from_run_envelope(run)
    scheduler_view = build_scheduler_policy_feedback(event)

    assert event.programme_state == "refused"
    assert event.event_kind == "run_refused"
    assert event_allows_public_truth_claim(event) is False
    assert any(metric.metric_name == "refusal_count" for metric in event.safety_metrics)
    assert any(
        artifact.artifact_type == "refusal_artifact" and artifact.state == "emitted"
        for artifact in event.artifact_outputs
    )
    assert any(
        update.posterior_family == "safety_refusal_rate" and update.update_allowed
        for update in event.posterior_updates
    )
    assert not any(
        update.posterior_family == "grounding_quality" and update.update_allowed
        for update in event.posterior_updates
    )
    assert scheduler_view.operator_scoring_required is False
    assert "safety_refusal_rate" in scheduler_view.allowed_posterior_families


def test_live_wire_keeps_rights_blocked_high_value_runs_from_upgrading_grounding() -> None:
    run = build_fixture_envelope("rights_blocked_react_commentary")
    audience = AudienceOutcome(
        metrics=(
            AudienceMetric(
                metric_name="watch_time",
                value=0.99,
                sample_size=250,
                aggregate_ref="audience:aggregate:rights-blocked",
                evidence_refs=("audience:aggregate:rights-blocked",),
            ),
        ),
        evidence_refs=("audience:aggregate:rights-blocked",),
    )
    revenue = (
        RevenueProxy(
            proxy_name="support_intent",
            value=0.95,
            evidence_refs=("support:aggregate:rights-blocked",),
        ),
    )

    event = build_feedback_event_from_run_envelope(
        run,
        audience_outcome=audience,
        revenue_proxies=revenue,
    )
    scheduler_view = build_scheduler_policy_feedback(event)

    assert event.programme_state == "blocked"
    assert event.public_private_mode == "dry_run"
    assert event_allows_public_truth_claim(event) is False
    assert any(
        gate.gate_name == "rights_gate" and gate.state == "fail" and gate.blocks_public_claim
        for gate in event.gate_outcomes
    )
    assert any(metric.metric_name == "rights_block_count" for metric in event.safety_metrics)
    assert any(
        update.posterior_family == "audience_response"
        and update.source_signal == "audience_aggregate"
        for update in event.posterior_updates
    )
    assert any(
        update.posterior_family == "revenue_support_response"
        and update.source_signal == "revenue_aggregate"
        for update in event.posterior_updates
    )
    assert not any(
        update.posterior_family == "grounding_quality"
        and update.source_signal in {"audience_aggregate", "revenue_aggregate"}
        for update in event.posterior_updates
    )
    assert not any(
        update.posterior_family == "grounding_quality" and update.update_allowed
        for update in event.posterior_updates
    )
    assert scheduler_view.audience_revenue_can_upgrade_grounding is False
    assert scheduler_view.grounding_update_refs == ()
    assert set(scheduler_view.metric_response_update_refs) == {
        "posterior:audience:run_rights_blocked_react_commentary",
        "posterior:revenue:run_rights_blocked_react_commentary",
    }


def test_live_wire_records_correction_outcome_without_public_truth_upgrade() -> None:
    run = build_fixture_envelope("correction_run")
    event = build_feedback_event_from_run_envelope(run)
    scheduler_view = build_scheduler_policy_feedback(event)

    assert event.programme_state == "corrected"
    assert event.event_kind == "run_corrected"
    assert event.public_private_mode == "public_archive"
    assert event_allows_public_truth_claim(event) is False
    assert any(metric.metric_name == "correction_count" for metric in event.safety_metrics)
    assert any(
        artifact.artifact_type == "correction_artifact" and artifact.state == "emitted"
        for artifact in event.artifact_outputs
    )
    assert any(
        update.posterior_family == "safety_refusal_rate" and update.update_allowed
        for update in event.posterior_updates
    )
    assert "safety_refusal_rate" in scheduler_view.allowed_posterior_families
    assert scheduler_view.public_truth_claim_allowed is False


def test_live_wire_allows_evidence_bound_public_grounding_yield() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    event = build_feedback_event_from_run_envelope(run)

    assert event.programme_state == "public_run"
    assert event_allows_public_truth_claim(event) is True
    assert event.grounding_outputs
    assert any(
        update.posterior_family == "grounding_quality" and update.update_allowed
        for update in event.posterior_updates
    )
