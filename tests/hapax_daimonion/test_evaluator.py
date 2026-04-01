"""Tests for CPAL control law evaluator."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.cpal.evaluator import CpalEvaluator
from agents.hapax_daimonion.cpal.types import ConversationalRegion, CorrectionTier, GainUpdate


class TestEvaluatorGainUpdates:
    def _make_evaluator(self):
        perception = MagicMock()
        perception.signals = MagicMock(
            vad_confidence=0.0,
            speech_active=False,
            speech_duration_s=0.0,
            is_speaking=False,
            energy_rms=0.0,
            trp_probability=0.0,
        )
        formulation = MagicMock()
        formulation.state = MagicMock(value="idle")
        formulation.select_backchannel.return_value = None
        production = MagicMock()
        production.is_producing = False
        return CpalEvaluator(
            perception=perception,
            formulation=formulation,
            production=production,
        )

    def test_initial_gain_ambient(self):
        ev = self._make_evaluator()
        assert ev.gain_controller.region == ConversationalRegion.AMBIENT

    def test_operator_speech_drives_gain(self):
        ev = self._make_evaluator()
        ev.perception.signals.speech_active = True
        ev.perception.signals.vad_confidence = 0.8
        ev.tick(dt=0.15)
        assert ev.gain_controller.gain > 0.0

    def test_silence_decays_gain(self):
        ev = self._make_evaluator()
        ev.gain_controller.apply(GainUpdate(delta=0.5, source="test"))
        ev.perception.signals.speech_active = False
        ev.tick(dt=5.0)
        assert ev.gain_controller.gain < 0.5

    def test_tick_returns_action(self):
        ev = self._make_evaluator()
        ev.gain_controller.apply(GainUpdate(delta=0.6, source="test"))
        ev.perception.signals.speech_active = False
        ev.perception.signals.trp_probability = 0.7
        result = ev.tick(dt=0.15)
        assert result is not None
        assert result.action_tier is not None
        assert result.region is not None


class TestEvaluatorActionDispatch:
    def _make_evaluator(self):
        perception = MagicMock()
        perception.signals = MagicMock(
            vad_confidence=0.0,
            speech_active=False,
            speech_duration_s=0.0,
            is_speaking=False,
            energy_rms=0.0,
            trp_probability=0.0,
        )
        formulation = MagicMock()
        formulation.state = MagicMock(value="idle")
        formulation.select_backchannel.return_value = None
        production = MagicMock()
        production.is_producing = False
        return CpalEvaluator(
            perception=perception,
            formulation=formulation,
            production=production,
        )

    def test_ambient_produces_no_vocal(self):
        ev = self._make_evaluator()
        result = ev.tick(dt=0.15)
        assert result.action_tier == CorrectionTier.T0_VISUAL

    def test_barge_in_interrupts_production(self):
        ev = self._make_evaluator()
        ev.production.is_producing = True
        ev.perception.signals.speech_active = True
        ev.perception.signals.vad_confidence = 0.95
        ev.tick(dt=0.15)
        ev.production.interrupt.assert_called()
