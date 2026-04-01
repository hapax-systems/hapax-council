"""Tests for CPAL conversation control law."""

from agents.hapax_daimonion.cpal.control_law import ConversationControlLaw
from agents.hapax_daimonion.cpal.types import (
    CorrectionTier,
    ErrorDimension,
)


class TestControlLawEvaluation:
    def test_zero_error_ambient_no_action(self):
        """At ambient gain with no error, no correction needed."""
        law = ConversationControlLaw()
        result = law.evaluate(
            gain=0.05,
            ungrounded_du_count=0,
            repair_rate=0.0,
            gqi=0.8,
            silence_s=0.0,
        )
        assert result.error.magnitude < 0.1
        assert result.action_tier == CorrectionTier.T0_VISUAL

    def test_ungrounded_dus_raise_comprehension_error(self):
        law = ConversationControlLaw()
        result = law.evaluate(
            gain=0.6,
            ungrounded_du_count=3,
            repair_rate=0.0,
            gqi=0.5,
            silence_s=0.0,
        )
        assert result.error.comprehension > 0.3
        assert result.error.dominant == ErrorDimension.COMPREHENSION

    def test_declining_gqi_raises_affective_error(self):
        law = ConversationControlLaw()
        result = law.evaluate(
            gain=0.6,
            ungrounded_du_count=0,
            repair_rate=0.3,
            gqi=0.2,
            silence_s=0.0,
        )
        assert result.error.affective > 0.3
        assert result.error.dominant == ErrorDimension.AFFECTIVE

    def test_long_silence_raises_temporal_error(self):
        law = ConversationControlLaw()
        result = law.evaluate(
            gain=0.6,
            ungrounded_du_count=0,
            repair_rate=0.0,
            gqi=0.8,
            silence_s=20.0,
        )
        assert result.error.temporal > 0.3
        assert result.error.dominant == ErrorDimension.TEMPORAL

    def test_action_tier_scales_with_error(self):
        law = ConversationControlLaw()
        low = law.evaluate(gain=0.6, ungrounded_du_count=0, repair_rate=0.0, gqi=0.9, silence_s=0.0)
        high = law.evaluate(
            gain=0.6, ungrounded_du_count=5, repair_rate=0.5, gqi=0.2, silence_s=15.0
        )
        assert low.action_tier.value < high.action_tier.value

    def test_gain_modulates_action_tier(self):
        """Same error at low gain should produce lower-tier action."""
        law = ConversationControlLaw()
        low_gain = law.evaluate(
            gain=0.1, ungrounded_du_count=2, repair_rate=0.1, gqi=0.5, silence_s=5.0
        )
        high_gain = law.evaluate(
            gain=0.8, ungrounded_du_count=2, repair_rate=0.1, gqi=0.5, silence_s=5.0
        )
        assert low_gain.action_tier.value <= high_gain.action_tier.value


class TestControlSignalEmission:
    def test_emits_control_signal(self):
        law = ConversationControlLaw()
        result = law.evaluate(
            gain=0.5, ungrounded_du_count=1, repair_rate=0.1, gqi=0.6, silence_s=2.0
        )
        cs = result.control_signal
        assert cs.component == "conversation"
        assert 0.0 <= cs.reference <= 1.0
        assert 0.0 <= cs.perception <= 1.0
        assert cs.error >= 0.0

    def test_high_gqi_means_low_error(self):
        law = ConversationControlLaw()
        result = law.evaluate(
            gain=0.6, ungrounded_du_count=0, repair_rate=0.0, gqi=0.95, silence_s=0.0
        )
        assert result.control_signal.error < 0.15

    def test_low_gqi_means_high_error(self):
        law = ConversationControlLaw()
        result = law.evaluate(
            gain=0.6, ungrounded_du_count=3, repair_rate=0.3, gqi=0.1, silence_s=10.0
        )
        assert result.control_signal.error > 0.3


class TestRegionGating:
    def test_ambient_never_produces_vocal(self):
        law = ConversationControlLaw()
        result = law.evaluate(
            gain=0.05, ungrounded_du_count=5, repair_rate=0.5, gqi=0.1, silence_s=30.0
        )
        assert result.action_tier == CorrectionTier.T0_VISUAL

    def test_peripheral_max_t1(self):
        law = ConversationControlLaw()
        result = law.evaluate(
            gain=0.2, ungrounded_du_count=5, repair_rate=0.5, gqi=0.1, silence_s=30.0
        )
        assert result.action_tier in (CorrectionTier.T0_VISUAL, CorrectionTier.T1_PRESYNTHESIZED)

    def test_conversational_allows_t3(self):
        law = ConversationControlLaw()
        result = law.evaluate(
            gain=0.6, ungrounded_du_count=5, repair_rate=0.5, gqi=0.1, silence_s=30.0
        )
        assert result.action_tier == CorrectionTier.T3_FULL_FORMULATION
