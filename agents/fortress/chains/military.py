"""Military Commander governance chain.

Decides military posture: assault, defend, burrow, or stand down.
Suppression wiring (military_alert field) added in Batch 4.
"""

from __future__ import annotations

from agents.fortress.schema import FullFortressState
from agents.hapax_daimonion.governance import (
    Candidate,
    FallbackChain,
    Selected,
    Veto,
    VetoChain,
    VetoResult,
)


def _minimum_population(state: FullFortressState) -> bool:
    """Allow military actions only with >= 10 dwarves."""
    return state.population >= 10


def _equipment_available(state: FullFortressState) -> bool:
    """Allow only if weapons exist in stockpiles."""
    return state.stockpiles.weapons > 0


def _food_critical_no_draft(state: FullFortressState) -> bool:
    """Block military drafting when food is critically low (< 2 per capita)."""
    return state.food_count >= state.population * 2


def _threat_full_assault(state: FullFortressState) -> bool:
    return state.active_threats > 20


def _threat_defensive(state: FullFortressState) -> bool:
    return state.active_threats > 0


def _threat_burrow(state: FullFortressState) -> bool:
    return state.active_threats > 0 and state.population < 20


class MilitaryCommanderChain:
    """Governance chain for military decisions."""

    CHAIN_NAME = "military_commander"

    def __init__(self) -> None:
        self._veto_chain: VetoChain[FullFortressState] = VetoChain(
            [
                Veto(
                    "minimum_population",
                    _minimum_population,
                    description="Need >= 10 dwarves for military",
                ),
                Veto(
                    "equipment_available",
                    _equipment_available,
                    description="Weapons required in stockpile",
                ),
                Veto(
                    "food_critical_no_draft",
                    _food_critical_no_draft,
                    description="Food too low for military draft",
                ),
            ]
        )
        self._fallback: FallbackChain[FullFortressState, str] = FallbackChain(
            candidates=[
                Candidate("full_assault", _threat_full_assault, "full_assault"),
                Candidate("civilian_burrow", _threat_burrow, "civilian_burrow"),
                Candidate("defensive_position", _threat_defensive, "defensive_position"),
            ],
            default="no_action",
        )

    def evaluate(self, state: FullFortressState) -> tuple[VetoResult, Selected[str]]:
        """Evaluate vetoes and select military posture."""
        veto_result = self._veto_chain.evaluate(state)
        if not veto_result.allowed:
            return veto_result, Selected(action="no_action", selected_by="vetoed")
        selection = self._fallback.select(state)
        return veto_result, selection
