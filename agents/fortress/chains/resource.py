"""Resource Manager governance chain.

Decides production priorities: food, drink, equipment.
Works with both FastFortressState (food_count/drink_count) and
FullFortressState (stockpiles + workshops).
"""

from __future__ import annotations

from agents._governance import (
    Candidate,
    FallbackChain,
    Selected,
    VetoChain,
    VetoResult,
)
from agents.fortress.schema import FastFortressState, FullFortressState

_STILL_TYPES = {"Still", "still", 13}
_KITCHEN_TYPES = {"Kitchen", "kitchen", 6}


def _has_still(state: FastFortressState) -> bool:
    """Check if a still exists for drink production."""
    if isinstance(state, FullFortressState) and len(state.workshops) > 0:
        return any(w.type in _STILL_TYPES for w in state.workshops)
    return True  # Assume available when we can't check or no workshop data


def _has_kitchen(state: FastFortressState) -> bool:
    """Check if a kitchen exists for food production."""
    if isinstance(state, FullFortressState) and len(state.workshops) > 0:
        return any(w.type in _KITCHEN_TYPES for w in state.workshops)
    return True


def _workshop_available(state: FastFortressState) -> bool:
    """Allow orders only if workshops exist (skip check for fast state)."""
    if isinstance(state, FullFortressState):
        return len(state.workshops) > 0
    return True  # Assume workshops exist when we can't check


def _needs_food(state: FastFortressState) -> bool:
    return state.food_count < state.population * 10


def _needs_drink(state: FastFortressState) -> bool:
    return state.drink_count < state.population * 5


def _needs_equipment(state: FastFortressState) -> bool:
    if isinstance(state, FullFortressState):
        return state.stockpiles.weapons < state.population // 5
    return False  # Can't check without full state


def _needs_workshop_for_drinks(state: FastFortressState) -> bool:
    """Need drinks AND lack the workshop to produce them."""
    return _needs_drink(state) and not _has_still(state)


def _needs_workshop_for_food(state: FastFortressState) -> bool:
    """Need food AND lack the workshop to produce it."""
    return _needs_food(state) and not _has_kitchen(state)


class ResourceManagerChain:
    """Governance chain for resource production decisions.

    When production is needed but the required workshop doesn't exist,
    escalates to infrastructure construction (build_workshops) instead
    of ordering production that can't execute.
    """

    CHAIN_NAME = "resource_manager"

    def __init__(self) -> None:
        self._veto_chain: VetoChain[FastFortressState] = VetoChain(
            []  # No global vetoes — workshop checks are per-candidate now
        )
        self._fallback: FallbackChain[FastFortressState, str] = FallbackChain(
            candidates=[
                # Infrastructure gaps take priority over production orders
                Candidate(
                    "build_workshops_drinks",
                    _needs_workshop_for_drinks,
                    "build_workshops",
                ),
                Candidate(
                    "build_workshops_food",
                    _needs_workshop_for_food,
                    "build_workshops",
                ),
                # Production orders (only reachable if workshops exist)
                Candidate("food_production", _needs_food, "food_production"),
                Candidate("drink_production", _needs_drink, "drink_production"),
                Candidate("equipment_production", _needs_equipment, "equipment_production"),
            ],
            default="no_action",
        )

    def evaluate(self, state: FastFortressState) -> tuple[VetoResult, Selected[str]]:
        """Evaluate vetoes and select production priority."""
        veto_result = self._veto_chain.evaluate(state)
        if not veto_result.allowed:
            return veto_result, Selected(action="no_action", selected_by="vetoed")
        selection = self._fallback.select(state)
        return veto_result, selection
