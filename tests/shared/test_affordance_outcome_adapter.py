"""Tests for adapting CapabilityOutcomeEnvelope into AffordancePipeline learning."""

from __future__ import annotations

import pytest

from shared.affordance_outcome_adapter import (
    AffordanceOutcomeUpdateKind,
    build_commanded_no_witness_outcome,
    decide_affordance_outcome_update,
)
from shared.affordance_pipeline import AffordancePipeline
from shared.capability_outcome import (
    CapabilityOutcomeEnvelope,
    FixtureCase,
    LearningPolicy,
    LearningTarget,
    OutcomeStatus,
    WitnessPolicy,
    load_capability_outcome_fixtures,
)


def _outcome(outcome_id: str) -> CapabilityOutcomeEnvelope:
    return load_capability_outcome_fixtures().require_outcome(outcome_id)


def test_witnessed_success_updates_affordance_learning() -> None:
    outcome = _outcome("coe:audio.public-tts:witnessed-success")
    decision = decide_affordance_outcome_update(outcome)

    assert decision.kind is AffordanceOutcomeUpdateKind.SUCCESS
    assert decision.should_update is True
    assert decision.success is True
    assert decision.capability_name == "Public TTS route"
    assert decision.claim_posterior_update_allowed is False


def test_witnessed_failure_updates_negative_affordance_learning() -> None:
    outcome = _outcome("coe:visual.frame:witnessed-failure")
    decision = decide_affordance_outcome_update(outcome)

    assert decision.kind is AffordanceOutcomeUpdateKind.FAILURE
    assert decision.should_update is True
    assert decision.success is False
    assert "frame witness failed" in decision.reason


@pytest.mark.parametrize(
    ("fixture_case", "outcome_id"),
    [
        (FixtureCase.SELECTED_ONLY, "coe:content.candidate:selected-only"),
        (FixtureCase.COMMANDED_ONLY, "coe:midi.transport:commanded-only"),
        (FixtureCase.INFERRED, "coe:perception.context:inferred"),
        (FixtureCase.STALE, "coe:archive.replay:stale"),
        (FixtureCase.MISSING, "coe:tool.sources:missing"),
        (FixtureCase.LEGACY_PUBLIC_EVENT, "coe:public-event.legacy:missing-gate"),
    ],
)
def test_no_update_fixtures_do_not_update_verified_success(
    fixture_case: FixtureCase,
    outcome_id: str,
) -> None:
    outcome = _outcome(outcome_id)
    decision = decide_affordance_outcome_update(outcome)

    assert outcome.fixture_case is fixture_case
    assert decision.kind is AffordanceOutcomeUpdateKind.NO_UPDATE
    assert decision.should_update is False
    assert decision.success is None


def test_only_witness_policy_outcomes_feed_positive_learning() -> None:
    fixtures = load_capability_outcome_fixtures()
    positive_decisions = []

    for outcome in fixtures.outcomes:
        decision = decide_affordance_outcome_update(outcome)
        if decision.kind is AffordanceOutcomeUpdateKind.SUCCESS:
            positive_decisions.append((outcome.outcome_id, outcome.witness_policy))
        if outcome.witness_policy not in {
            WitnessPolicy.WITNESSED,
            WitnessPolicy.PUBLIC_EVENT_ADAPTER,
        }:
            assert decision.kind is not AffordanceOutcomeUpdateKind.SUCCESS
            assert decision.should_update is False

    assert positive_decisions == [
        ("coe:audio.public-tts:witnessed-success", WitnessPolicy.WITNESSED),
        ("coe:governance.no-expert:refused", WitnessPolicy.WITNESSED),
        ("coe:public-event.rvpe:accepted", WitnessPolicy.PUBLIC_EVENT_ADAPTER),
    ]


def test_blocked_outcome_does_not_update_verified_success() -> None:
    outcome = _outcome("coe:provider.search:blocked")
    decision = decide_affordance_outcome_update(outcome)

    assert outcome.outcome_status is OutcomeStatus.BLOCKED
    assert decision.should_update is False
    assert decision.kind is AffordanceOutcomeUpdateKind.NO_UPDATE


def test_adapter_rejects_mutated_commanded_only_success_even_if_policy_allows() -> None:
    outcome = _outcome("coe:midi.transport:commanded-only")
    mutated = outcome.model_copy(
        update={
            "learning_update": outcome.learning_update.model_copy(
                update={
                    "allowed": True,
                    "policy": LearningPolicy.SUCCESS,
                    "target": LearningTarget.AFFORDANCE_ACTIVATION,
                    "required_witness_refs": ["witness:midi.transport:fake"],
                    "missing_witness_refs": [],
                }
            ),
            "verified_success": outcome.verified_success.model_copy(
                update={"capability": True, "action": True}
            ),
        }
    )

    decision = decide_affordance_outcome_update(mutated)

    assert decision.should_update is False
    assert "fixture_case:commanded_only" in decision.reason


def test_pipeline_records_allowed_outcome_and_skips_no_update_outcome() -> None:
    pipe = AffordancePipeline()

    success_decision = pipe.record_capability_outcome(
        _outcome("coe:audio.public-tts:witnessed-success"),
        context={"mode": "public_route_smoke"},
    )
    no_update_decision = pipe.record_capability_outcome(
        _outcome("coe:midi.transport:commanded-only"),
        context={"mode": "public_route_smoke"},
    )
    legacy_public_event_decision = pipe.record_capability_outcome(
        _outcome("coe:public-event.legacy:missing-gate"),
        context={"mode": "public_route_smoke"},
    )

    success_state = pipe.get_activation_state("Public TTS route")
    skipped_state = pipe.get_activation_state("MIDI transport command")
    legacy_public_event_state = pipe.get_activation_state("Legacy public event adapter")
    assert success_decision.should_update is True
    assert success_state.use_count == 1
    assert success_state.ts_alpha > 2.0
    assert ("public_route_smoke", "Public TTS route") in pipe._context_associations
    assert no_update_decision.should_update is False
    assert skipped_state.use_count == 0
    assert ("public_route_smoke", "MIDI transport command") not in pipe._context_associations
    assert legacy_public_event_decision.should_update is False
    assert legacy_public_event_state.use_count == 0
    assert (
        "public_route_smoke",
        "Legacy public event adapter",
    ) not in pipe._context_associations


def test_governance_refusal_success_updates_gate_without_validating_refused_claim() -> None:
    pipe = AffordancePipeline()
    outcome = _outcome("coe:governance.no-expert:refused")

    decision = pipe.record_capability_outcome(
        outcome,
        context={"gate": "no_expert_system"},
    )

    state = pipe.get_activation_state("No-expert gate refusal")
    assert decision.kind is AffordanceOutcomeUpdateKind.SUCCESS
    assert decision.should_update is True
    assert decision.success is True
    assert decision.refused_claim_validated is False
    assert decision.claim_posterior_update_allowed is False
    assert outcome.verified_success.claim_posterior is False
    assert state.use_count == 1
    assert ("no_expert_system", "No-expert gate refusal") in pipe._context_associations


def test_commanded_no_witness_outcome_does_not_update_success_learning() -> None:
    pipe = AffordancePipeline()
    outcome = build_commanded_no_witness_outcome(
        "studio.toggle_livestream",
        command_ref="shm:hapax-compositor/livestream-control.json",
        route_ref="route:studio-livestream-control",
        public_claim_bearing=True,
    )

    decision = pipe.record_capability_outcome(outcome, context={"source": "test"})

    state = pipe.get_activation_state("studio.toggle_livestream")
    assert outcome.fixture_case is FixtureCase.COMMANDED_ONLY
    assert outcome.witness_policy is WitnessPolicy.COMMANDED_ONLY
    assert outcome.learning_update.allowed is False
    assert outcome.witness_refs == []
    assert decision.kind is AffordanceOutcomeUpdateKind.NO_UPDATE
    assert decision.should_update is False
    assert state.use_count == 0
    assert ("test", "studio.toggle_livestream") not in pipe._context_associations
