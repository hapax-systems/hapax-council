"""Storyteller governance chain.

Decides narrative style based on fortress events.
Uses FastFortressState — narrative doesn't need unit-level details.
No vetoes: storytelling is pure output, never blocked.
"""

from __future__ import annotations

from agents.fortress.schema import FastFortressState
from agents.hapax_daimonion.governance import (
    Candidate,
    FallbackChain,
    Selected,
    VetoChain,
    VetoResult,
)


def _has_active_threats(state: FastFortressState) -> bool:
    return state.active_threats > 0


def _has_pending_events(state: FastFortressState) -> bool:
    return len(state.pending_events) > 0


class StorytellerChain:
    """Governance chain for narrative output selection."""

    CHAIN_NAME = "storyteller"

    def __init__(self) -> None:
        self._veto_chain: VetoChain[FastFortressState] = VetoChain([])
        self._fallback: FallbackChain[FastFortressState, str] = FallbackChain(
            candidates=[
                Candidate("dramatic_narrative", _has_active_threats, "dramatic_narrative"),
                Candidate("factual_summary", _has_pending_events, "factual_summary"),
            ],
            default="brief_update",
        )

    def evaluate(self, state: FastFortressState) -> tuple[VetoResult, Selected[str]]:
        """Select narrative style. Never vetoed."""
        veto_result = self._veto_chain.evaluate(state)
        selection = self._fallback.select(state)
        return veto_result, selection
