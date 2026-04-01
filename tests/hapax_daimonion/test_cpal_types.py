"""Tests for CPAL core types."""

from agents.hapax_daimonion.cpal.types import (
    ConversationalRegion,
    CorrectionTier,
    ErrorDimension,
    ErrorSignal,
    GainUpdate,
)


class TestConversationalRegion:
    def test_all_regions_defined(self):
        assert len(ConversationalRegion) == 5

    def test_region_ordering(self):
        """Regions have increasing gain thresholds."""
        assert ConversationalRegion.AMBIENT.threshold < ConversationalRegion.PERIPHERAL.threshold
        assert ConversationalRegion.PERIPHERAL.threshold < ConversationalRegion.ATTENTIVE.threshold
        assert (
            ConversationalRegion.ATTENTIVE.threshold < ConversationalRegion.CONVERSATIONAL.threshold
        )
        assert (
            ConversationalRegion.CONVERSATIONAL.threshold < ConversationalRegion.INTENSIVE.threshold
        )

    def test_region_from_gain(self):
        assert ConversationalRegion.from_gain(0.0) == ConversationalRegion.AMBIENT
        assert ConversationalRegion.from_gain(0.05) == ConversationalRegion.AMBIENT
        assert ConversationalRegion.from_gain(0.15) == ConversationalRegion.PERIPHERAL
        assert ConversationalRegion.from_gain(0.35) == ConversationalRegion.ATTENTIVE
        assert ConversationalRegion.from_gain(0.55) == ConversationalRegion.CONVERSATIONAL
        assert ConversationalRegion.from_gain(0.85) == ConversationalRegion.INTENSIVE
        assert ConversationalRegion.from_gain(1.0) == ConversationalRegion.INTENSIVE


class TestCorrectionTier:
    def test_all_tiers_defined(self):
        assert len(CorrectionTier) == 4

    def test_tier_ordering(self):
        """Tiers have increasing cost."""
        tiers = list(CorrectionTier)
        assert tiers == [
            CorrectionTier.T0_VISUAL,
            CorrectionTier.T1_PRESYNTHESIZED,
            CorrectionTier.T2_LIGHTWEIGHT,
            CorrectionTier.T3_FULL_FORMULATION,
        ]


class TestErrorSignal:
    def test_construction(self):
        err = ErrorSignal(
            comprehension=0.3,
            affective=0.1,
            temporal=0.5,
        )
        assert err.comprehension == 0.3
        assert err.affective == 0.1
        assert err.temporal == 0.5

    def test_magnitude(self):
        """Magnitude is the max of all dimensions."""
        err = ErrorSignal(comprehension=0.3, affective=0.1, temporal=0.5)
        assert err.magnitude == 0.5

    def test_dominant_dimension(self):
        err = ErrorSignal(comprehension=0.3, affective=0.1, temporal=0.5)
        assert err.dominant == ErrorDimension.TEMPORAL

    def test_zero_error(self):
        err = ErrorSignal(comprehension=0.0, affective=0.0, temporal=0.0)
        assert err.magnitude == 0.0

    def test_suggested_tier(self):
        """Error magnitude maps to correction tier."""
        assert ErrorSignal(0.05, 0.0, 0.0).suggested_tier == CorrectionTier.T0_VISUAL
        assert ErrorSignal(0.2, 0.0, 0.0).suggested_tier == CorrectionTier.T1_PRESYNTHESIZED
        assert ErrorSignal(0.5, 0.0, 0.0).suggested_tier == CorrectionTier.T3_FULL_FORMULATION
        assert ErrorSignal(0.8, 0.0, 0.0).suggested_tier == CorrectionTier.T3_FULL_FORMULATION


class TestGainUpdate:
    def test_construction(self):
        gu = GainUpdate(delta=0.05, source="operator_speech")
        assert gu.delta == 0.05
        assert gu.source == "operator_speech"

    def test_driver_is_positive(self):
        gu = GainUpdate(delta=0.1, source="grounding_success")
        assert gu.is_driver

    def test_damper_is_negative(self):
        gu = GainUpdate(delta=-0.05, source="silence_decay")
        assert gu.is_damper
