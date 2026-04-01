"""CPAL control law evaluator -- the cognitive tick.

Replaces CognitiveLoop. Ticks at ~150ms, reads all three streams,
runs the control law, and dispatches actions. This is the single
point of coordination for the CPAL architecture.
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

    def tick(self, dt: float) -> EvaluatorResult:
        """Run one evaluator tick."""
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

        # 3. Control law evaluation
        result = self._control_law.evaluate(
            gain=self._gain_controller.gain,
            ungrounded_du_count=0,  # Phase 4 wires grounding ledger
            repair_rate=0.0,
            gqi=0.8,  # Phase 4 wires GQI
            silence_s=0.0 if signals.speech_active else dt,
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
