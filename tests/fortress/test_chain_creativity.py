"""Tests for agents.fortress.chains.creativity — CreativityChain governance."""

from __future__ import annotations

import time
import unittest

from agents.fortress.chains.creativity import CreativityChain
from agents.fortress.schema import FullFortressState, StockpileSummary, WealthSummary


def _full_state(**overrides: object) -> FullFortressState:
    defaults: dict = {
        "timestamp": time.time(),
        "game_tick": 500_000,
        "year": 2,
        "season": 1,
        "month": 3,
        "day": 10,
        "fortress_name": "TestFort",
        "paused": False,
        "population": 80,
        "food_count": 800,
        "drink_count": 500,
        "active_threats": 0,
        "job_queue_length": 20,
        "idle_dwarf_count": 5,
        "most_stressed_value": 30_000,
        "stockpiles": StockpileSummary(food=800, drink=500),
        "wealth": WealthSummary(created=50_000),
    }
    defaults.update(overrides)
    return FullFortressState(**defaults)


class TestCreativityChainPeaceful(unittest.TestCase):
    """Peaceful, prosperous fortress should produce creative actions."""

    def setUp(self) -> None:
        self.chain = CreativityChain()

    def test_peaceful_prosperous_allows_creativity(self) -> None:
        state = _full_state()
        veto_result, selection = self.chain.evaluate(state)
        self.assertTrue(veto_result.allowed)
        self.assertNotEqual(selection.action, "no_action")

    def test_semantic_naming_selected(self) -> None:
        # Low stress, no threats — semantic_naming is cheapest, selected first
        state = _full_state(most_stressed_value=30_000)
        veto_result, selection = self.chain.evaluate(state)
        self.assertTrue(veto_result.allowed)
        self.assertEqual(selection.action, "semantic_naming")


class TestCreativityChainVetoed(unittest.TestCase):
    """Various conditions that veto creativity."""

    def setUp(self) -> None:
        self.chain = CreativityChain()

    def test_siege_vetoes_creativity(self) -> None:
        state = _full_state(active_threats=5)
        veto_result, selection = self.chain.evaluate(state)
        self.assertFalse(veto_result.allowed)
        self.assertEqual(selection.action, "no_action")
        self.assertIn("maslow_gate", veto_result.denied_by)

    def test_famine_vetoes_creativity(self) -> None:
        state = _full_state(food_count=10)  # 80 pop * 5 = 400 needed
        veto_result, selection = self.chain.evaluate(state)
        self.assertFalse(veto_result.allowed)
        self.assertEqual(selection.action, "no_action")

    def test_drought_vetoes_creativity(self) -> None:
        state = _full_state(drink_count=10)  # 80 pop * 3 = 240 needed
        veto_result, selection = self.chain.evaluate(state)
        self.assertFalse(veto_result.allowed)

    def test_high_stress_vetoes_neuroception(self) -> None:
        # 200000 * 0.7 = 140000 threshold. 150000 > 140000 → neuroception fails
        state = _full_state(most_stressed_value=150_000)
        veto_result, selection = self.chain.evaluate(state)
        self.assertFalse(veto_result.allowed)
        self.assertIn("neuroception", veto_result.denied_by)

    def test_extreme_stress_vetoes_maslow(self) -> None:
        # most_stressed > 100_000 fails maslow stress threshold
        state = _full_state(most_stressed_value=120_000)
        veto_result, selection = self.chain.evaluate(state)
        self.assertFalse(veto_result.allowed)
        self.assertIn("maslow_gate", veto_result.denied_by)

    def test_too_many_idle_vetoes_maslow(self) -> None:
        # 80 pop * 0.3 = 24 idle threshold. 30 > 24 → fails
        state = _full_state(idle_dwarf_count=30)
        veto_result, selection = self.chain.evaluate(state)
        self.assertFalse(veto_result.allowed)


class TestCreativityChainFallback(unittest.TestCase):
    """Fallback selection based on state conditions."""

    def setUp(self) -> None:
        self.chain = CreativityChain()

    def test_low_population_no_architecture(self) -> None:
        # Pop 20 < 30 → no architectural_experiment
        state = _full_state(population=20, food_count=200, drink_count=120)
        veto_result, selection = self.chain.evaluate(state)
        self.assertTrue(veto_result.allowed)
        self.assertNotEqual(selection.action, "architectural_experiment")

    def test_low_wealth_no_enrichment(self) -> None:
        # wealth.created=1000 < 10000 → no aesthetic_enrichment
        state = _full_state(wealth=WealthSummary(created=1000))
        veto_result, selection = self.chain.evaluate(state)
        self.assertTrue(veto_result.allowed)
        # Should still get semantic_naming
        self.assertEqual(selection.action, "semantic_naming")

    def test_high_pop_high_wealth_gets_naming_first(self) -> None:
        # Even with high pop and wealth, semantic_naming has highest priority
        state = _full_state(population=100, wealth=WealthSummary(created=100_000))
        veto_result, selection = self.chain.evaluate(state)
        self.assertTrue(veto_result.allowed)
        self.assertEqual(selection.action, "semantic_naming")


if __name__ == "__main__":
    unittest.main()
