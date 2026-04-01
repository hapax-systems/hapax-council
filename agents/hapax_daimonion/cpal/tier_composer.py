"""Tier composer -- sequences tiered signals into conversational responses.

When the evaluator selects an action tier, the composer produces the
full sequence: T0 (visual) -> T1 (backchannel/ack) -> T2 (floor claim)
-> T3 (substantive). Each tier fills the time the next needs to prepare.

This is the "no dead air" principle from the spec: the 3-5s LLM latency
is inhabited by lower-tier signals.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agents.hapax_daimonion.cpal.types import ConversationalRegion, CorrectionTier

log = logging.getLogger(__name__)

# Tier ordering for comparison (avoids fragile string comparison on enum values)
_TIER_ORDER = [
    CorrectionTier.T0_VISUAL,
    CorrectionTier.T1_PRESYNTHESIZED,
    CorrectionTier.T2_LIGHTWEIGHT,
    CorrectionTier.T3_FULL_FORMULATION,
]
_TIER_RANK = {t: i for i, t in enumerate(_TIER_ORDER)}

_VOCAL_REGIONS = frozenset(
    {
        ConversationalRegion.ATTENTIVE,
        ConversationalRegion.CONVERSATIONAL,
        ConversationalRegion.INTENSIVE,
    }
)

_T3_REGIONS = frozenset(
    {
        ConversationalRegion.CONVERSATIONAL,
        ConversationalRegion.INTENSIVE,
    }
)


@dataclass(frozen=True)
class ComposedAction:
    """A sequence of tiered actions to execute."""

    tiers: tuple[CorrectionTier, ...]
    signal_types: tuple[str, ...]  # parallel to tiers
    trigger: str  # what caused this composition


class TierComposer:
    """Composes tiered signal sequences from evaluator decisions.

    Given an action tier and conversational region, produces the
    full sequence of signals that should fire. Lower tiers fire
    first to fill latency.
    """

    def compose(
        self,
        *,
        action_tier: CorrectionTier,
        region: ConversationalRegion,
        trigger: str = "control_law",
    ) -> ComposedAction:
        """Compose a signal sequence for the given action tier."""
        tiers: list[CorrectionTier] = []
        signals: list[str] = []
        requested_rank = _TIER_RANK[action_tier]

        # T0 always fires (visual acknowledgment)
        tiers.append(CorrectionTier.T0_VISUAL)
        signals.append("attentional_shift")

        if requested_rank < _TIER_RANK[CorrectionTier.T1_PRESYNTHESIZED]:
            return ComposedAction(tiers=tuple(tiers), signal_types=tuple(signals), trigger=trigger)

        # T1: vocal acknowledgment if region permits
        if region in _VOCAL_REGIONS:
            tiers.append(CorrectionTier.T1_PRESYNTHESIZED)
            signals.append("acknowledgment")

        if requested_rank < _TIER_RANK[CorrectionTier.T2_LIGHTWEIGHT]:
            return ComposedAction(tiers=tuple(tiers), signal_types=tuple(signals), trigger=trigger)

        # T2: discourse marker / floor claim if region permits
        if region in _VOCAL_REGIONS:
            tiers.append(CorrectionTier.T2_LIGHTWEIGHT)
            signals.append("discourse_marker")

        if requested_rank < _TIER_RANK[CorrectionTier.T3_FULL_FORMULATION]:
            return ComposedAction(tiers=tuple(tiers), signal_types=tuple(signals), trigger=trigger)

        # T3: substantive response if region permits
        if region in _T3_REGIONS:
            tiers.append(CorrectionTier.T3_FULL_FORMULATION)
            signals.append("substantive_response")

        return ComposedAction(tiers=tuple(tiers), signal_types=tuple(signals), trigger=trigger)
