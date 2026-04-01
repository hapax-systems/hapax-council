"""Conversation control law -- the 15th S1 component.

Evaluates conversational state against the grounding reference and
selects a corrective action tier. Emits a ControlSignal for SCM
mesh-wide observability.

Reference: mutual understanding (GQI = 1.0 ideal).
Perception: current grounding state (GQI, ungrounded DUs, repair rate).
Error: gap between reference and perception.
Action: tiered correction proportional to error x gain.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.hapax_daimonion.cpal.types import (
    ConversationalRegion,
    CorrectionTier,
    ErrorSignal,
)
from shared.control_signal import ControlSignal

_REGION_MAX_TIER: dict[ConversationalRegion, CorrectionTier] = {
    ConversationalRegion.AMBIENT: CorrectionTier.T0_VISUAL,
    ConversationalRegion.PERIPHERAL: CorrectionTier.T1_PRESYNTHESIZED,
    ConversationalRegion.ATTENTIVE: CorrectionTier.T2_LIGHTWEIGHT,
    ConversationalRegion.CONVERSATIONAL: CorrectionTier.T3_FULL_FORMULATION,
    ConversationalRegion.INTENSIVE: CorrectionTier.T3_FULL_FORMULATION,
}

_TIER_ORDER = [
    CorrectionTier.T0_VISUAL,
    CorrectionTier.T1_PRESYNTHESIZED,
    CorrectionTier.T2_LIGHTWEIGHT,
    CorrectionTier.T3_FULL_FORMULATION,
]


@dataclass(frozen=True)
class ControlLawResult:
    """Result of a single control law evaluation."""

    error: ErrorSignal
    action_tier: CorrectionTier
    control_signal: ControlSignal
    region: ConversationalRegion


class ConversationControlLaw:
    """Evaluates conversational state and selects corrective action."""

    def evaluate(
        self,
        *,
        gain: float,
        ungrounded_du_count: int,
        repair_rate: float,
        gqi: float,
        silence_s: float,
    ) -> ControlLawResult:
        comprehension = min(1.0, ungrounded_du_count * 0.20 + repair_rate)
        affective = max(0.0, 1.0 - gqi - 0.15)
        temporal = min(1.0, silence_s / 30.0)

        error = ErrorSignal(
            comprehension=comprehension,
            affective=affective,
            temporal=temporal,
        )

        region = ConversationalRegion.from_gain(gain)

        suggested = error.suggested_tier
        max_allowed = _REGION_MAX_TIER[region]
        suggested_idx = _TIER_ORDER.index(suggested)
        max_idx = _TIER_ORDER.index(max_allowed)
        action_tier = _TIER_ORDER[min(suggested_idx, max_idx)]

        cs = ControlSignal(
            component="conversation",
            reference=1.0,
            perception=gqi,
        )

        return ControlLawResult(
            error=error,
            action_tier=action_tier,
            control_signal=cs,
            region=region,
        )
