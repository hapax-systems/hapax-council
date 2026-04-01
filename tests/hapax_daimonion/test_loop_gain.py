"""Tests for CPAL loop gain controller."""

import math

from agents.hapax_daimonion.cpal.loop_gain import LoopGainController
from agents.hapax_daimonion.cpal.types import ConversationalRegion, GainUpdate


class TestLoopGainBasics:
    def test_initial_gain_is_zero(self):
        ctrl = LoopGainController()
        assert ctrl.gain == 0.0

    def test_initial_region_is_ambient(self):
        ctrl = LoopGainController()
        assert ctrl.region == ConversationalRegion.AMBIENT

    def test_gain_clamped_to_unit_interval(self):
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=5.0, source="test"))
        assert ctrl.gain == 1.0
        ctrl.apply(GainUpdate(delta=-10.0, source="test"))
        assert ctrl.gain == 0.0


class TestGainDrivers:
    def test_operator_speech_raises_gain(self):
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.15, source="operator_speech"))
        assert ctrl.gain == 0.15

    def test_multiple_drivers_accumulate(self):
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.15, source="operator_speech"))
        ctrl.apply(GainUpdate(delta=0.10, source="grounding_success"))
        assert ctrl.gain == 0.25

    def test_region_transitions_with_gain(self):
        ctrl = LoopGainController()
        assert ctrl.region == ConversationalRegion.AMBIENT
        ctrl.apply(GainUpdate(delta=0.15, source="operator_speech"))
        assert ctrl.region == ConversationalRegion.PERIPHERAL
        ctrl.apply(GainUpdate(delta=0.20, source="operator_speech"))
        assert ctrl.region == ConversationalRegion.ATTENTIVE
        ctrl.apply(GainUpdate(delta=0.20, source="grounding_success"))
        assert ctrl.region == ConversationalRegion.CONVERSATIONAL
        ctrl.apply(GainUpdate(delta=0.30, source="engagement"))
        assert ctrl.region == ConversationalRegion.INTENSIVE


class TestGainDampers:
    def test_damper_reduces_gain(self):
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.5, source="test"))
        ctrl.apply(GainUpdate(delta=-0.2, source="silence_decay"))
        assert ctrl.gain == 0.3

    def test_silence_decay(self):
        """Exponential decay with ~15s time constant."""
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.6, source="test"))
        ctrl.decay(dt=15.0)
        expected = 0.6 * math.exp(-15.0 / 15.0)
        assert abs(ctrl.gain - expected) < 0.01

    def test_decay_clamps_near_zero(self):
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.01, source="test"))
        ctrl.decay(dt=60.0)
        assert ctrl.gain == 0.0


class TestStimmungCeiling:
    def test_nominal_no_ceiling(self):
        ctrl = LoopGainController()
        ctrl.set_stimmung_ceiling("nominal")
        ctrl.apply(GainUpdate(delta=1.0, source="test"))
        assert ctrl.gain == 1.0

    def test_cautious_caps_at_0_7(self):
        ctrl = LoopGainController()
        ctrl.set_stimmung_ceiling("cautious")
        ctrl.apply(GainUpdate(delta=1.0, source="test"))
        assert ctrl.gain == 0.7

    def test_degraded_caps_at_0_5(self):
        ctrl = LoopGainController()
        ctrl.set_stimmung_ceiling("degraded")
        ctrl.apply(GainUpdate(delta=1.0, source="test"))
        assert ctrl.gain == 0.5

    def test_critical_caps_at_0_3(self):
        ctrl = LoopGainController()
        ctrl.set_stimmung_ceiling("critical")
        ctrl.apply(GainUpdate(delta=1.0, source="test"))
        assert ctrl.gain == 0.3

    def test_ceiling_enforced_retroactively(self):
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.8, source="test"))
        assert ctrl.gain == 0.8
        ctrl.set_stimmung_ceiling("degraded")
        assert ctrl.gain == 0.5


class TestHysteresis:
    def test_consecutive_failures_reduce_gain(self):
        """3 consecutive grounding failures -> reduce gain."""
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.6, source="test"))
        ctrl.record_grounding_outcome(success=False)
        ctrl.record_grounding_outcome(success=False)
        assert ctrl.gain == 0.6
        ctrl.record_grounding_outcome(success=False)
        assert ctrl.gain < 0.6

    def test_consecutive_successes_raise_gain(self):
        """5 consecutive successes -> raise gain."""
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.4, source="test"))
        for _ in range(4):
            ctrl.record_grounding_outcome(success=True)
        gain_before = ctrl.gain
        ctrl.record_grounding_outcome(success=True)
        assert ctrl.gain > gain_before

    def test_asymmetric_hysteresis(self):
        """Degrade is faster (3) than recover (5)."""
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.5, source="test"))

        for _ in range(3):
            ctrl.record_grounding_outcome(success=False)
        degraded_gain = ctrl.gain
        assert degraded_gain < 0.5

        for _ in range(3):
            ctrl.record_grounding_outcome(success=True)
        assert ctrl.gain == degraded_gain

        ctrl.record_grounding_outcome(success=True)
        ctrl.record_grounding_outcome(success=True)
        assert ctrl.gain > degraded_gain

    def test_success_resets_failure_counter(self):
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.5, source="test"))
        ctrl.record_grounding_outcome(success=False)
        ctrl.record_grounding_outcome(success=False)
        ctrl.record_grounding_outcome(success=True)
        ctrl.record_grounding_outcome(success=False)
        ctrl.record_grounding_outcome(success=False)
        assert ctrl.gain == 0.5


class TestGainHistory:
    def test_update_history_tracked(self):
        ctrl = LoopGainController()
        ctrl.apply(GainUpdate(delta=0.1, source="speech"))
        ctrl.apply(GainUpdate(delta=0.05, source="gaze"))
        assert len(ctrl.recent_updates) == 2
        assert ctrl.recent_updates[0].source == "speech"
        assert ctrl.recent_updates[1].source == "gaze"

    def test_history_bounded(self):
        ctrl = LoopGainController()
        for i in range(100):
            ctrl.apply(GainUpdate(delta=0.001, source=f"test_{i}"))
        assert len(ctrl.recent_updates) <= 50
