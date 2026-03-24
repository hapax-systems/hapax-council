"""Tests for fortress goal library — context selectors and predicates."""

from __future__ import annotations

import unittest

from agents.fortress.goal_library import (
    DEFAULT_GOALS,
    FOUND_FORTRESS,
    PREPARE_FOR_SIEGE,
    PROCESS_MIGRANTS,
    RESPOND_TO_SIEGE,
    SURVIVE_WINTER,
)
from agents.fortress.schema import FastFortressState


def _base_fast(**overrides: object) -> FastFortressState:
    """Build a FastFortressState with sensible defaults."""
    defaults: dict = {
        "timestamp": 1.0,
        "game_tick": 10000,
        "year": 1,
        "season": 0,
        "month": 0,
        "day": 0,
        "fortress_name": "Boatmurdered",
        "paused": False,
        "population": 50,
        "food_count": 500,
        "drink_count": 250,
        "active_threats": 0,
        "job_queue_length": 10,
        "idle_dwarf_count": 5,
        "most_stressed_value": 0,
        "pending_events": (),
    }
    defaults.update(overrides)
    return FastFortressState(**defaults)


# ---------------------------------------------------------------------------
# All goals validate
# ---------------------------------------------------------------------------


class TestGoalLibraryValidation(unittest.TestCase):
    """Every goal in DEFAULT_GOALS must pass DAG validation."""

    def test_all_default_goals_validate(self) -> None:
        for goal in DEFAULT_GOALS:
            with self.subTest(goal=goal.id):
                goal.validate()

    def test_default_goals_count(self) -> None:
        self.assertEqual(len(DEFAULT_GOALS), 8)

    def test_unique_goal_ids(self) -> None:
        ids = [g.id for g in DEFAULT_GOALS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_unique_subgoal_ids_within_goals(self) -> None:
        for goal in DEFAULT_GOALS:
            sg_ids = [sg.id for sg in goal.subgoals]
            with self.subTest(goal=goal.id):
                self.assertEqual(len(sg_ids), len(set(sg_ids)))


# ---------------------------------------------------------------------------
# SURVIVE_WINTER
# ---------------------------------------------------------------------------


class TestSurviveWinter(unittest.TestCase):
    def test_low_food_selects_emergency_food(self) -> None:
        state = _base_fast(population=50, food_count=100)
        selected = SURVIVE_WINTER.context_selector(state)
        self.assertIn("emergency_food", selected)

    def test_low_drink_selects_emergency_drink(self) -> None:
        state = _base_fast(population=50, drink_count=100)
        selected = SURVIVE_WINTER.context_selector(state)
        self.assertIn("emergency_drink", selected)

    def test_shelter_always_selected(self) -> None:
        state = _base_fast(population=50, food_count=9999, drink_count=9999)
        selected = SURVIVE_WINTER.context_selector(state)
        self.assertIn("secure_shelter", selected)

    def test_adequate_food_not_selected(self) -> None:
        state = _base_fast(population=10, food_count=200)
        selected = SURVIVE_WINTER.context_selector(state)
        self.assertNotIn("emergency_food", selected)

    def test_adequate_drink_not_selected(self) -> None:
        state = _base_fast(population=10, drink_count=100)
        selected = SURVIVE_WINTER.context_selector(state)
        self.assertNotIn("emergency_drink", selected)


# ---------------------------------------------------------------------------
# PREPARE_FOR_SIEGE
# ---------------------------------------------------------------------------


class TestPrepareForSiege(unittest.TestCase):
    def test_small_pop_selects_establish_military(self) -> None:
        state = _base_fast(population=5)
        selected = PREPARE_FOR_SIEGE.context_selector(state)
        self.assertIn("establish_military", selected)

    def test_large_pop_no_establish_military(self) -> None:
        state = _base_fast(population=50)
        selected = PREPARE_FOR_SIEGE.context_selector(state)
        self.assertNotIn("establish_military", selected)

    def test_always_selects_weapons_and_defenses(self) -> None:
        state = _base_fast(population=50)
        selected = PREPARE_FOR_SIEGE.context_selector(state)
        self.assertIn("stockpile_weapons", selected)
        self.assertIn("build_defenses", selected)

    def test_stockpile_weapons_requires_military(self) -> None:
        sg_map = {sg.id: sg for sg in PREPARE_FOR_SIEGE.subgoals}
        self.assertIn("establish_military", sg_map["stockpile_weapons"].preconditions)


# ---------------------------------------------------------------------------
# FOUND_FORTRESS
# ---------------------------------------------------------------------------


class TestFoundFortress(unittest.TestCase):
    def test_selects_all_four(self) -> None:
        state = _base_fast(population=7)
        selected = FOUND_FORTRESS.context_selector(state)
        self.assertEqual(
            set(selected),
            {"dig_entrance", "build_workshops", "start_farming", "create_bedrooms"},
        )

    def test_highest_priority(self) -> None:
        self.assertEqual(FOUND_FORTRESS.priority, 100)

    def test_workshops_require_entrance(self) -> None:
        sg_map = {sg.id: sg for sg in FOUND_FORTRESS.subgoals}
        self.assertIn("dig_entrance", sg_map["build_workshops"].preconditions)

    def test_farming_requires_entrance(self) -> None:
        sg_map = {sg.id: sg for sg in FOUND_FORTRESS.subgoals}
        self.assertIn("dig_entrance", sg_map["start_farming"].preconditions)

    def test_bedrooms_require_entrance(self) -> None:
        sg_map = {sg.id: sg for sg in FOUND_FORTRESS.subgoals}
        self.assertIn("dig_entrance", sg_map["create_bedrooms"].preconditions)


# ---------------------------------------------------------------------------
# PROCESS_MIGRANTS
# ---------------------------------------------------------------------------


class TestProcessMigrants(unittest.TestCase):
    def test_always_selects_beds_and_labors(self) -> None:
        state = _base_fast(population=15)
        selected = PROCESS_MIGRANTS.context_selector(state)
        self.assertIn("assign_beds", selected)
        self.assertIn("assign_labors", selected)

    def test_small_pop_no_expand_food(self) -> None:
        state = _base_fast(population=15)
        selected = PROCESS_MIGRANTS.context_selector(state)
        self.assertNotIn("expand_food", selected)

    def test_large_pop_selects_expand_food(self) -> None:
        state = _base_fast(population=25)
        selected = PROCESS_MIGRANTS.context_selector(state)
        self.assertIn("expand_food", selected)


# ---------------------------------------------------------------------------
# RESPOND_TO_SIEGE
# ---------------------------------------------------------------------------


class TestRespondToSiege(unittest.TestCase):
    def test_always_selects_deploy_military(self) -> None:
        state = _base_fast(population=10)
        selected = RESPOND_TO_SIEGE.context_selector(state)
        self.assertIn("deploy_military", selected)

    def test_large_pop_selects_burrow(self) -> None:
        state = _base_fast(population=50)
        selected = RESPOND_TO_SIEGE.context_selector(state)
        self.assertIn("burrow_civilians", selected)

    def test_small_pop_no_burrow(self) -> None:
        state = _base_fast(population=20)
        selected = RESPOND_TO_SIEGE.context_selector(state)
        self.assertNotIn("burrow_civilians", selected)

    def test_always_selects_traps(self) -> None:
        state = _base_fast(population=10)
        selected = RESPOND_TO_SIEGE.context_selector(state)
        self.assertIn("activate_traps", selected)

    def test_siege_priority_is_high(self) -> None:
        self.assertEqual(RESPOND_TO_SIEGE.priority, 90)

    def test_all_checks_use_no_threats(self) -> None:
        """All siege subgoals complete when threats reach zero."""
        state = _base_fast(active_threats=0)
        for sg in RESPOND_TO_SIEGE.subgoals:
            with self.subTest(subgoal=sg.id):
                self.assertTrue(sg.check(state))

    def test_checks_fail_with_threats(self) -> None:
        state = _base_fast(active_threats=5)
        for sg in RESPOND_TO_SIEGE.subgoals:
            with self.subTest(subgoal=sg.id):
                self.assertFalse(sg.check(state))


if __name__ == "__main__":
    unittest.main()
