"""Tests for AffordancePipeline learning authority narrowing.

Proves that world-facing positive learning is only permitted through
record_capability_outcome() with a valid CapabilityOutcomeEnvelope,
while internal/exploration learning and all failure paths remain open.
"""

from shared.affordance_outcome_adapter import (
    AffordanceOutcomeUpdateKind,
    build_commanded_no_witness_outcome,
    build_tool_recruitment_no_witness_outcome,
)
from shared.affordance_pipeline import AffordancePipeline, LearningAuthority
from shared.capability_outcome import (
    CapabilityOutcomeEnvelope,
    load_capability_outcome_fixtures,
)


def _witnessed_success() -> CapabilityOutcomeEnvelope:
    return load_capability_outcome_fixtures().require_outcome(
        "coe:audio.public-tts:witnessed-success"
    )


class TestCommandOnlyDoesNotPositiveLearn:
    """Selected-only and commanded-only outcomes must not positive-learn."""

    def test_tool_recruitment_no_witness_blocks_learning(self):
        pipe = AffordancePipeline()
        envelope = build_tool_recruitment_no_witness_outcome("search_web", legacy_success=True)
        decision = pipe.record_capability_outcome(envelope)

        assert decision.kind == AffordanceOutcomeUpdateKind.NO_UPDATE
        assert not decision.should_update
        state = pipe.get_activation_state("search_web")
        assert state.use_count == 0

    def test_commanded_no_witness_blocks_learning(self):
        pipe = AffordancePipeline()
        envelope = build_commanded_no_witness_outcome("livestream.start")
        decision = pipe.record_capability_outcome(envelope)

        assert decision.kind == AffordanceOutcomeUpdateKind.NO_UPDATE
        assert not decision.should_update
        state = pipe.get_activation_state("livestream.start")
        assert state.use_count == 0

    def test_direct_world_facing_positive_refused(self):
        pipe = AffordancePipeline()
        result = pipe.record_outcome(
            "narrate.voice",
            success=True,
            authority=LearningAuthority.WORLD_FACING,
        )

        assert result is False
        state = pipe.get_activation_state("narrate.voice")
        assert state.use_count == 0


class TestWitnessedOutcomeCanPositiveLearn:
    """Witnessed success through record_capability_outcome updates Thompson."""

    def test_witnessed_success_updates_efficacy(self):
        pipe = AffordancePipeline()
        envelope = _witnessed_success()
        decision = pipe.record_capability_outcome(envelope)

        assert decision.kind == AffordanceOutcomeUpdateKind.SUCCESS
        assert decision.should_update
        assert decision.success is True
        state = pipe.get_activation_state(envelope.capability_name)
        assert state.use_count == 1
        assert state.ts_alpha > 2.0

    def test_witnessed_success_strengthens_context(self):
        pipe = AffordancePipeline()
        envelope = _witnessed_success()
        pipe.record_capability_outcome(envelope, context={"stimmung": "contemplative"})

        assert pipe._context_associations[("contemplative", envelope.capability_name)] > 0


class TestLegacyBooleanPathRemainsNonWorldFacing:
    """Internal/reverie callers using record_outcome() directly still work."""

    def test_internal_positive_learning_permitted(self):
        pipe = AffordancePipeline()
        result = pipe.record_outcome(
            "node.shader_drift", success=True, context={"source": "reverie"}
        )

        assert result is True
        state = pipe.get_activation_state("node.shader_drift")
        assert state.use_count == 1

    def test_internal_authority_is_default(self):
        pipe = AffordancePipeline()
        result = pipe.record_outcome("content.yt.feature", success=True)

        assert result is True
        state = pipe.get_activation_state("content.yt.feature")
        assert state.use_count == 1

    def test_failure_always_permitted_regardless_of_authority(self):
        pipe = AffordancePipeline()
        result = pipe.record_outcome(
            "narrate.voice",
            success=False,
            authority=LearningAuthority.WORLD_FACING,
        )

        assert result is True
        state = pipe.get_activation_state("narrate.voice")
        assert state.ts_beta > 1.0

    def test_dismissal_still_works(self):
        pipe = AffordancePipeline()
        pipe.record_outcome("cap_a", success=True)
        pipe.record_dismissal("cap_a", impingement_id="imp-1")

        assert len(pipe._dismissal_log) == 1
        state = pipe.get_activation_state("cap_a")
        assert state.ts_beta > 1.0


class TestAuthorityEnumValues:
    """LearningAuthority enum is importable and has expected values."""

    def test_enum_values(self):
        assert LearningAuthority.INTERNAL == "internal"
        assert LearningAuthority.WORLD_FACING == "world_facing"

    def test_enum_is_string(self):
        assert isinstance(LearningAuthority.INTERNAL, str)
