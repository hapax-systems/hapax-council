"""CompoundGoal type system — declarative goal decomposition.

Promoted from imperative async methods to declarative DAG per
docs/superpowers/specs/2026-03-23-compound-goal-promotion.md.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from agents.fortress.schema import FastFortressState

log = logging.getLogger(__name__)


class GoalState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class SubGoal:
    """A single sub-task within a CompoundGoal."""

    id: str
    description: str
    chain: str  # which governance chain handles this
    preconditions: tuple[str, ...] = ()  # SubGoal IDs that must complete first
    check: Callable[[FastFortressState], bool] = lambda _: False  # is this satisfied?
    timeout_ticks: int = 12000  # ~10 in-game days default


@dataclass(frozen=True)
class CompoundGoal:
    """A decomposable strategic goal."""

    id: str
    description: str
    subgoals: tuple[SubGoal, ...]
    context_selector: Callable[[FastFortressState], tuple[str, ...]]
    priority: int = 50  # higher = more important

    def validate(self) -> None:
        """Check DAG acyclicity and referential integrity."""
        ids = {sg.id for sg in self.subgoals}
        for sg in self.subgoals:
            for pre in sg.preconditions:
                if pre not in ids:
                    raise ValueError(f"SubGoal {sg.id} has unknown precondition: {pre}")
        # Check for cycles via topological sort
        visited: set[str] = set()
        temp: set[str] = set()
        sg_map = {sg.id: sg for sg in self.subgoals}

        def visit(node_id: str) -> None:
            if node_id in temp:
                raise ValueError(f"Cycle detected involving SubGoal: {node_id}")
            if node_id in visited:
                return
            temp.add(node_id)
            for pre in sg_map[node_id].preconditions:
                visit(pre)
            temp.remove(node_id)
            visited.add(node_id)

        for sg_id in sorted(ids):
            visit(sg_id)


class GoalTracker:
    """Tracks state of active CompoundGoals and their SubGoals."""

    def __init__(self) -> None:
        self._goal_states: dict[str, GoalState] = {}
        self._subgoal_states: dict[str, dict[str, GoalState]] = {}
        self._activation_ticks: dict[str, int] = {}

    def activate(self, goal: CompoundGoal, tick: int) -> None:
        """Activate a goal (PENDING -> ACTIVE)."""
        self._goal_states[goal.id] = GoalState.ACTIVE
        self._subgoal_states[goal.id] = {sg.id: GoalState.PENDING for sg in goal.subgoals}
        self._activation_ticks[goal.id] = tick

    def goal_state(self, goal_id: str) -> GoalState:
        return self._goal_states.get(goal_id, GoalState.PENDING)

    def subgoal_state(self, goal_id: str, subgoal_id: str) -> GoalState:
        return self._subgoal_states.get(goal_id, {}).get(subgoal_id, GoalState.PENDING)

    def mark_subgoal(self, goal_id: str, subgoal_id: str, state: GoalState) -> None:
        if goal_id in self._subgoal_states:
            self._subgoal_states[goal_id][subgoal_id] = state

    def check_completion(self, goal: CompoundGoal, state: FastFortressState) -> bool:
        """Check if all context-selected subgoals are satisfied."""
        selected = goal.context_selector(state)
        for sg in goal.subgoals:
            if sg.id in selected and not sg.check(state):
                return False
        # All selected subgoals satisfied
        self._goal_states[goal.id] = GoalState.COMPLETED
        return True

    def check_timeouts(self, goal: CompoundGoal, current_tick: int) -> list[str]:
        """Return list of timed-out subgoal IDs."""
        activation = self._activation_ticks.get(goal.id, 0)
        elapsed = current_tick - activation
        timed_out: list[str] = []
        for sg in goal.subgoals:
            sg_state = self.subgoal_state(goal.id, sg.id)
            if sg_state == GoalState.ACTIVE and elapsed > sg.timeout_ticks:
                timed_out.append(sg.id)
                self.mark_subgoal(goal.id, sg.id, GoalState.BLOCKED)
        return timed_out


class GoalPlanner:
    """Selects and dispatches subgoals based on fortress state."""

    def __init__(self, goals: list[CompoundGoal] | None = None) -> None:
        self._goals = sorted(goals or [], key=lambda g: (-g.priority, g.id))
        self._tracker = GoalTracker()
        for goal in self._goals:
            goal.validate()

    @property
    def tracker(self) -> GoalTracker:
        return self._tracker

    def activate_goal(self, goal_id: str, tick: int) -> None:
        for goal in self._goals:
            if goal.id == goal_id:
                if self._tracker.goal_state(goal.id) == GoalState.ACTIVE:
                    return  # already active, don't reset progress
                self._tracker.activate(goal, tick)
                return

    def evaluate(self, state: FastFortressState) -> list[SubGoal]:
        """Return subgoals that should be dispatched this tick.

        For each active goal (processed in deterministic priority order):
        1. Run context_selector to get relevant subgoal IDs
        2. Filter to subgoals whose preconditions are met
        3. Filter to subgoals not already satisfied
        4. Return sorted by goal priority, then subgoal ID for determinism
        """
        dispatchable: list[SubGoal] = []

        for goal in self._goals:
            if self._tracker.goal_state(goal.id) != GoalState.ACTIVE:
                continue

            # Check if goal is now complete
            if self._tracker.check_completion(goal, state):
                log.info("Goal %s completed", goal.id)
                continue

            sg_map = {sg.id: sg for sg in goal.subgoals}

            # Re-check all ACTIVE subgoals for satisfaction (even if no longer selected)
            for sg in goal.subgoals:
                if self._tracker.subgoal_state(goal.id, sg.id) == GoalState.ACTIVE and sg.check(
                    state
                ):
                    self._tracker.mark_subgoal(goal.id, sg.id, GoalState.COMPLETED)

            selected_ids = set(goal.context_selector(state))

            for sg_id in sorted(selected_ids):
                sg = sg_map.get(sg_id)
                if sg is None:
                    continue

                sg_state = self._tracker.subgoal_state(goal.id, sg.id)
                if sg_state in (
                    GoalState.COMPLETED,
                    GoalState.BLOCKED,
                    GoalState.FAILED,
                ):
                    continue

                # Check preconditions
                preconds_met = all(
                    self._tracker.subgoal_state(goal.id, pre) == GoalState.COMPLETED
                    for pre in sg.preconditions
                )
                if not preconds_met:
                    continue

                # Check if already satisfied
                if sg.check(state):
                    self._tracker.mark_subgoal(goal.id, sg.id, GoalState.COMPLETED)
                    continue

                # Mark as active and dispatch
                self._tracker.mark_subgoal(goal.id, sg.id, GoalState.ACTIVE)
                dispatchable.append(sg)

        return dispatchable
