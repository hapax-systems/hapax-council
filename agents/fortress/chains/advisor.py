"""Advisor governance chain.

Routes operator queries to recommendation categories.
No vetoes: advisory output is never blocked.
"""

from __future__ import annotations

from agents.fortress.schema import FullFortressState
from agents.hapax_daimonion.governance import (
    Candidate,
    FallbackChain,
    Selected,
    VetoChain,
    VetoResult,
)


def _has_threats(state: FullFortressState) -> bool:
    return state.active_threats > 0


def _has_low_food(state: FullFortressState) -> bool:
    return state.stockpiles.food < state.population * 10


class AdvisorChain:
    """Governance chain for operator query routing."""

    CHAIN_NAME = "advisor"

    def __init__(self) -> None:
        self._veto_chain: VetoChain[FullFortressState] = VetoChain([])
        self._fallback: FallbackChain[FullFortressState, str] = FallbackChain(
            candidates=[
                Candidate("threat_assessment", _has_threats, "threat_assessment"),
                Candidate("resource_assessment", _has_low_food, "resource_assessment"),
            ],
            default="general_assessment",
        )

    def evaluate(self, state: FullFortressState) -> tuple[VetoResult, Selected[str]]:
        """Route query to recommendation category."""
        veto_result = self._veto_chain.evaluate(state)
        selection = self._fallback.select(state)
        return veto_result, selection
