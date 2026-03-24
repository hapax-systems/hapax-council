"""Fortress goal library — CompoundGoal definitions.

Each goal has a context_selector (which subgoals to activate given state)
and check functions (is this subgoal satisfied?).
"""

from __future__ import annotations

from agents.fortress.goals import CompoundGoal, SubGoal
from agents.fortress.schema import FastFortressState, FullFortressState

# --- Satisfaction predicates ---


def _has_enough_food(state: FastFortressState) -> bool:
    return state.food_count >= state.population * 10


def _has_enough_drink(state: FastFortressState) -> bool:
    return state.drink_count >= state.population * 5


def _has_beds(state: FastFortressState) -> bool:
    if isinstance(state, FullFortressState):
        return state.buildings.beds >= state.population
    return False


def _has_military(state: FastFortressState) -> bool:
    return state.population >= 10  # simplified: assumes squads created at 10


def _no_threats(state: FastFortressState) -> bool:
    return state.active_threats == 0


def _has_workshops(state: FastFortressState) -> bool:
    if isinstance(state, FullFortressState):
        return len(state.workshops) >= 3
    return False


def _has_entrance(state: FastFortressState) -> bool:
    if isinstance(state, FullFortressState):
        return state.buildings.doors > 0
    return False


# --- Context selectors ---


def _survive_winter_selector(state: FastFortressState) -> tuple[str, ...]:
    active: list[str] = []
    if not _has_enough_food(state):
        active.append("emergency_food")
    if not _has_enough_drink(state):
        active.append("emergency_drink")
    active.append("secure_shelter")  # always relevant in winter
    return tuple(active)


def _prepare_for_siege_selector(state: FastFortressState) -> tuple[str, ...]:
    active: list[str] = []
    if not _has_military(state):
        active.append("establish_military")
    active.append("stockpile_weapons")
    active.append("build_defenses")
    return tuple(active)


def _found_fortress_selector(state: FastFortressState) -> tuple[str, ...]:
    """Initial embark: everything needed."""
    return ("dig_entrance", "build_workshops", "start_farming", "create_bedrooms")


def _process_migrants_selector(state: FastFortressState) -> tuple[str, ...]:
    active: list[str] = []
    active.append("assign_beds")
    active.append("assign_labors")
    if state.population > 20:
        active.append("expand_food")
    return tuple(active)


def _respond_to_siege_selector(state: FastFortressState) -> tuple[str, ...]:
    active: list[str] = ["deploy_military"]
    if state.population > 30:
        active.append("burrow_civilians")
    active.append("activate_traps")
    return tuple(active)


# --- Goal definitions ---

SURVIVE_WINTER = CompoundGoal(
    id="survive_winter",
    description="Ensure fortress survives through winter with adequate food, drink, and shelter",
    priority=80,
    context_selector=_survive_winter_selector,
    subgoals=(
        SubGoal(
            id="emergency_food",
            description="Produce food urgently",
            chain="resource_manager",
            check=_has_enough_food,
        ),
        SubGoal(
            id="emergency_drink",
            description="Brew drinks urgently",
            chain="resource_manager",
            check=_has_enough_drink,
        ),
        SubGoal(
            id="secure_shelter",
            description="Ensure all dwarves have beds",
            chain="fortress_planner",
            check=_has_beds,
        ),
    ),
)

PREPARE_FOR_SIEGE = CompoundGoal(
    id="prepare_for_siege",
    description="Prepare military and defenses for an anticipated siege",
    priority=70,
    context_selector=_prepare_for_siege_selector,
    subgoals=(
        SubGoal(
            id="establish_military",
            description="Create and equip military squads",
            chain="military_commander",
            check=_has_military,
        ),
        SubGoal(
            id="stockpile_weapons",
            description="Forge weapons and armor",
            chain="resource_manager",
            preconditions=("establish_military",),
            check=lambda s: False,  # requires weapon count check via FullFortressState
        ),
        SubGoal(
            id="build_defenses",
            description="Construct entrance defenses",
            chain="fortress_planner",
            check=lambda s: False,  # requires entrance defense check
        ),
    ),
)

FOUND_FORTRESS = CompoundGoal(
    id="found_fortress",
    description="Initial embark sequence — establish basic infrastructure",
    priority=100,  # highest priority at start
    context_selector=_found_fortress_selector,
    subgoals=(
        SubGoal(
            id="dig_entrance",
            description="Dig entrance and stairwell",
            chain="fortress_planner",
            check=_has_entrance,
        ),
        SubGoal(
            id="build_workshops",
            description="Build essential workshops",
            chain="fortress_planner",
            preconditions=("dig_entrance",),
            check=_has_workshops,
        ),
        SubGoal(
            id="start_farming",
            description="Establish food production",
            chain="resource_manager",
            preconditions=("dig_entrance",),
            check=_has_enough_food,
        ),
        SubGoal(
            id="create_bedrooms",
            description="Dig and furnish bedrooms",
            chain="fortress_planner",
            preconditions=("dig_entrance",),
            check=_has_beds,
        ),
    ),
)

PROCESS_MIGRANTS = CompoundGoal(
    id="process_migrants",
    description="Integrate new migrant wave — beds, jobs, food scaling",
    priority=60,
    context_selector=_process_migrants_selector,
    subgoals=(
        SubGoal(
            id="assign_beds",
            description="Ensure beds for all",
            chain="fortress_planner",
            check=_has_beds,
        ),
        SubGoal(
            id="assign_labors",
            description="Assign appropriate labors",
            chain="resource_manager",
            check=lambda s: s.idle_dwarf_count < 3,
        ),
        SubGoal(
            id="expand_food",
            description="Scale food production for new population",
            chain="resource_manager",
            check=_has_enough_food,
        ),
    ),
)

RESPOND_TO_SIEGE = CompoundGoal(
    id="respond_to_siege",
    description="Active siege response — deploy military, protect civilians",
    priority=90,
    context_selector=_respond_to_siege_selector,
    subgoals=(
        SubGoal(
            id="deploy_military",
            description="Station squads at entrance",
            chain="military_commander",
            check=_no_threats,
        ),
        SubGoal(
            id="burrow_civilians",
            description="Restrict civilians to safe areas",
            chain="military_commander",
            check=_no_threats,
        ),
        SubGoal(
            id="activate_traps",
            description="Ensure traps are loaded",
            chain="fortress_planner",
            check=_no_threats,
        ),
    ),
)

HANDLE_STRANGE_MOOD = CompoundGoal(
    id="handle_strange_mood",
    description="Ensure moody dwarf gets materials and workshop access",
    priority=65,
    context_selector=lambda s: ("provide_materials",),
    subgoals=(
        SubGoal(
            id="provide_materials",
            description="Ensure required materials available",
            chain="resource_manager",
            check=lambda s: False,  # resolved when mood ends
        ),
    ),
)

MANAGE_TRADE = CompoundGoal(
    id="manage_trade",
    description="Trade with visiting caravan",
    priority=55,
    context_selector=lambda s: ("prepare_trade_goods",),
    subgoals=(
        SubGoal(
            id="prepare_trade_goods",
            description="Move goods to trade depot",
            chain="resource_manager",
            check=lambda s: False,
        ),
    ),
)

HANDLE_MANDATE = CompoundGoal(
    id="handle_mandate",
    description="Fulfill noble mandate to avoid punishment",
    priority=50,
    context_selector=lambda s: ("produce_mandated_item",),
    subgoals=(
        SubGoal(
            id="produce_mandated_item",
            description="Craft mandated items",
            chain="resource_manager",
            check=lambda s: False,
        ),
    ),
)

# Default goal set
DEFAULT_GOALS: list[CompoundGoal] = [
    FOUND_FORTRESS,
    SURVIVE_WINTER,
    PREPARE_FOR_SIEGE,
    PROCESS_MIGRANTS,
    RESPOND_TO_SIEGE,
    HANDLE_STRANGE_MOOD,
    MANAGE_TRADE,
    HANDLE_MANDATE,
]
