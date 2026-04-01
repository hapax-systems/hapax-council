"""CPAL control law evaluator -- the cognitive tick.

Replaces CognitiveLoop. Reads perception, formulation, and production
streams, runs the control law, and produces action decisions. The
runner calls this with real grounding state from the grounding bridge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agents.hapax_daimonion.cpal.control_law import ConversationControlLaw
from agents.hapax_daimonion.cpal.loop_gain import LoopGainController
from agents.hapax_daimonion.cpal.types import CorrectionTier, GainUpdate

log = logging.getLogger(__name__)

_SPEECH_GAIN_DELTA = 0.05
_BARGE_IN_VAD_THRESHOLD = 0.9


@dataclass(frozen=True)
class EvaluatorResult:
    """Result of a single evaluator tick."""

    action_tier: CorrectionTier
    region: object  # ConversationalRegion
    error_magnitude: float
    gain: float


class CpalEvaluator:
    """Control law evaluator -- the cognitive tick."""

    def __init__(
        self,
        perception: object,
        formulation: object,
        production: object,
        control_law: ConversationControlLaw | None = None,
    ) -> None:
        self.perception = perception
        self.formulation = formulation
        self.production = production
        self._control_law = control_law or ConversationControlLaw()
        self._gain_controller = LoopGainController()

    @property
    def gain_controller(self) -> LoopGainController:
        return self._gain_controller

    def tick(
        self,
        dt: float,
        *,
        ungrounded_du_count: int = 0,
        repair_rate: float = 0.0,
        gqi: float = 0.8,
        silence_s: float | None = None,
    ) -> EvaluatorResult:
        """Run one evaluator tick.

        Args:
            dt: Time since last tick.
            ungrounded_du_count: From grounding bridge.
            repair_rate: From grounding bridge.
            gqi: From grounding bridge (0.0-1.0).
            silence_s: Accumulated silence. If None, uses dt when not speaking.
        """
        signals = self.perception.signals

        # 1. Gain updates
        if signals.speech_active and signals.vad_confidence > 0.3:
            self._gain_controller.apply(
                GainUpdate(delta=_SPEECH_GAIN_DELTA, source="operator_speech")
            )
        else:
            self._gain_controller.decay(dt)

        # 2. Barge-in detection
        if (
            self.production.is_producing
            and signals.speech_active
            and signals.vad_confidence > _BARGE_IN_VAD_THRESHOLD
        ):
            self.production.interrupt()
            log.info("Barge-in: operator speech interrupted production")

        # 3. Control law evaluation with real grounding state
        _silence = silence_s if silence_s is not None else (0.0 if signals.speech_active else dt)
        result = self._control_law.evaluate(
            gain=self._gain_controller.gain,
            ungrounded_du_count=ungrounded_du_count,
            repair_rate=repair_rate,
            gqi=gqi,
            silence_s=_silence,
        )

        # 4. Backchannel check
        bc = self.formulation.select_backchannel(
            region=result.region,
            speech_active=signals.speech_active,
            speech_duration_s=signals.speech_duration_s,
            trp_probability=signals.trp_probability,
        )
        if bc is not None:
            log.debug("Backchannel selected: %s (%s)", bc.signal_type, bc.tier)

        return EvaluatorResult(
            action_tier=result.action_tier,
            region=result.region,
            error_magnitude=result.error.magnitude,
            gain=self._gain_controller.gain,
        )
