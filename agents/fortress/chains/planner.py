"""Fortress Planner governance chain.

Decides WHAT to build based on fortress state. Blueprint templates handle HOW.
Suppression reads (crisis_suppression, military_alert) wired in Batch 4.
"""

from __future__ import annotations

from agents._governance import (
    Candidate,
    FallbackChain,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
)
from agents.fortress.schema import FullFortressState


def _picks_available(state: FullFortressState) -> bool:
    """Allow only if fortress has mining picks."""
    return state.stockpiles.weapons > 0 or state.population > 0  # simplified


def _population_floor(state: FullFortressState) -> bool:
    """Allow only if population >= 3 (need workers to build)."""
    return state.population >= 3


def _needs_workshops_urgent(state: FullFortressState) -> bool:
    """Workshops needed urgently when drink is critically low and no still exists."""
    return len(state.workshops) == 0 and state.drink_count < state.population * 3


def _needs_bedrooms(state: FullFortressState) -> bool:
    return state.buildings.beds < state.population


def _needs_workshops(state: FullFortressState) -> bool:
    return len(state.workshops) < max(3, state.population // 10)


def _needs_stockpiles(state: FullFortressState) -> bool:
    return state.stockpiles.furniture < state.population  # simplified


def _needs_defense(state: FullFortressState) -> bool:
    return state.wealth.created > 50000 and state.buildings.trade_depot == 0  # simplified


class FortressPlannerChain:
    """Governance chain for spatial planning and construction."""

    CHAIN_NAME = "fortress_planner"

    def __init__(self) -> None:
        self._veto_chain: VetoChain[FullFortressState] = VetoChain(
            [
                Veto("picks_available", _picks_available, description="Mining picks required"),
                Veto("population_floor", _population_floor, description="Need >= 3 workers"),
            ]
        )
        self._fallback: FallbackChain[FullFortressState, str] = FallbackChain(
            candidates=[
                Candidate(
                    "expand_workshops_urgent",
                    _needs_workshops_urgent,
                    "expand_workshops",
                ),
                Candidate("expand_bedrooms", _needs_bedrooms, "expand_bedrooms"),
                Candidate("expand_workshops", _needs_workshops, "expand_workshops"),
                Candidate("expand_stockpiles", _needs_stockpiles, "expand_stockpiles"),
                Candidate("expand_defense", _needs_defense, "expand_defense"),
            ],
            default="no_action",
        )

    def evaluate(self, state: FullFortressState) -> tuple[VetoResult, Selected[str]]:
        """Evaluate vetoes and select action."""
        veto_result = self._veto_chain.evaluate(state)
        if not veto_result.allowed:
            return veto_result, Selected(action="no_action", selected_by="vetoed")
        selection = self._fallback.select(state)
        return veto_result, selection
