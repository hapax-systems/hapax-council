"""Tests for agents.fortress.creativity — bell curve, gates, rigidity."""

from __future__ import annotations

import math
import time
import unittest

from agents.fortress.creativity import (
    creativity_activation,
    creativity_available,
    creativity_epsilon,
    maslow_gate,
    n_candidates_under_rigidity,
    neuroception_safe,
    rigidity_factor,
)
from agents.fortress.schema import FastFortressState


def _state(**overrides: object) -> FastFortressState:
    defaults: dict = {
        "timestamp": time.time(),
        "game_tick": 100_000,
        "year": 1,
        "season": 0,
        "month": 0,
        "day": 0,
        "fortress_name": "TestFort",
        "paused": False,
        "population": 50,
        "food_count": 500,
        "drink_count": 300,
        "active_threats": 0,
        "job_queue_length": 10,
        "idle_dwarf_count": 5,
        "most_stressed_value": 50_000,
    }
    defaults.update(overrides)
    return FastFortressState(**defaults)


class TestCreativityActivation(unittest.TestCase):
    """Bell curve peaks at center, falls off at extremes."""

    def test_peak_at_center(self) -> None:
        val = creativity_activation(0.4)
        self.assertAlmostEqual(val, 1.0, places=5)

    def test_low_at_zero_stress(self) -> None:
        val = creativity_activation(0.0)
        # exp(-(0.4^2)/(2*0.04)) = exp(-2) ~ 0.135
        self.assertAlmostEqual(val, math.exp(-2), places=5)
        self.assertLess(val, 0.15)

    def test_low_at_high_stress(self) -> None:
        val = creativity_activation(0.8)
        # exp(-((0.4)^2)/(2*0.04)) = exp(-2) ~ 0.135
        self.assertAlmostEqual(val, math.exp(-2), places=5)
        self.assertLess(val, 0.15)

    def test_symmetric_around_center(self) -> None:
        lo = creativity_activation(0.2)
        hi = creativity_activation(0.6)
        self.assertAlmostEqual(lo, hi, places=5)

    def test_custom_center_and_width(self) -> None:
        val = creativity_activation(0.5, center=0.5, width=0.1)
        self.assertAlmostEqual(val, 1.0, places=5)


class TestNeuroceptionSafe(unittest.TestCase):
    def test_safe_below_threshold(self) -> None:
        self.assertTrue(neuroception_safe(0.69))

    def test_unsafe_above_threshold(self) -> None:
        self.assertFalse(neuroception_safe(0.71))

    def test_boundary_is_unsafe(self) -> None:
        # Exactly at threshold: not strictly less than
        self.assertFalse(neuroception_safe(0.7))

    def test_custom_threshold(self) -> None:
        self.assertTrue(neuroception_safe(0.5, threshold=0.6))
        self.assertFalse(neuroception_safe(0.7, threshold=0.6))


class TestMaslowGate(unittest.TestCase):
    def test_all_needs_met(self) -> None:
        state = _state(
            population=50,
            food_count=500,
            drink_count=300,
            active_threats=0,
            most_stressed_value=50_000,
            idle_dwarf_count=5,
        )
        self.assertTrue(maslow_gate(state))

    def test_food_insufficient(self) -> None:
        state = _state(population=50, food_count=100)  # need 250
        self.assertFalse(maslow_gate(state))

    def test_drink_insufficient(self) -> None:
        state = _state(population=50, drink_count=50)  # need 150
        self.assertFalse(maslow_gate(state))

    def test_active_threats(self) -> None:
        state = _state(active_threats=1)
        self.assertFalse(maslow_gate(state))

    def test_extreme_stress(self) -> None:
        state = _state(most_stressed_value=150_000)
        self.assertFalse(maslow_gate(state))

    def test_too_many_idle(self) -> None:
        state = _state(population=50, idle_dwarf_count=20)  # 40% > 30%
        self.assertFalse(maslow_gate(state))

    def test_zero_population_safe(self) -> None:
        # max(1, 0) = 1, so needs are trivially met
        state = _state(population=0, food_count=10, drink_count=10, idle_dwarf_count=0)
        self.assertTrue(maslow_gate(state))


class TestCreativityAvailable(unittest.TestCase):
    def test_no_suppression_at_peak(self) -> None:
        val = creativity_available(0.4, 0.0)
        self.assertAlmostEqual(val, 1.0, places=5)

    def test_full_suppression_returns_floor(self) -> None:
        val = creativity_available(0.4, 1.0, floor=0.05)
        self.assertAlmostEqual(val, 0.05, places=5)

    def test_half_suppression_halves_signal(self) -> None:
        val = creativity_available(0.4, 0.5)
        self.assertAlmostEqual(val, 0.5, places=5)

    def test_clamped_to_one(self) -> None:
        # Even with negative suppression (shouldn't happen but guard)
        val = creativity_available(0.4, -0.5)
        self.assertLessEqual(val, 1.0)


class TestCreativityEpsilon(unittest.TestCase):
    def test_peak_creativity(self) -> None:
        eps = creativity_epsilon(0.4, 0.0, base_epsilon=0.30)
        self.assertAlmostEqual(eps, 0.30, places=5)

    def test_suppressed(self) -> None:
        eps = creativity_epsilon(0.4, 1.0, base_epsilon=0.30, floor=0.05)
        self.assertAlmostEqual(eps, 0.30 * 0.05, places=5)

    def test_scales_with_available(self) -> None:
        eps_lo = creativity_epsilon(0.0, 0.0)
        eps_hi = creativity_epsilon(0.4, 0.0)
        self.assertLess(eps_lo, eps_hi)


class TestRigidityFactor(unittest.TestCase):
    def test_no_threat(self) -> None:
        self.assertAlmostEqual(rigidity_factor(0.0, 0.0), 0.0)

    def test_full_crisis(self) -> None:
        self.assertAlmostEqual(rigidity_factor(1.0, 0.0), 0.8)

    def test_full_military(self) -> None:
        self.assertAlmostEqual(rigidity_factor(0.0, 1.0), 0.8)

    def test_uses_max(self) -> None:
        self.assertAlmostEqual(rigidity_factor(0.5, 0.8), 0.8 * 0.8)


class TestNCandidatesUnderRigidity(unittest.TestCase):
    def test_no_rigidity_all_candidates(self) -> None:
        self.assertEqual(n_candidates_under_rigidity(10, 0.0, 0.0), 10)

    def test_full_suppression_minimum_one(self) -> None:
        self.assertEqual(n_candidates_under_rigidity(10, 1.0, 1.0), 2)
        # rigidity = 0.8, so 10 * 0.2 = 2

    def test_single_candidate_always_one(self) -> None:
        self.assertEqual(n_candidates_under_rigidity(1, 1.0, 1.0), 1)

    def test_partial_suppression(self) -> None:
        # crisis=0.5, mil=0.0 -> rigidity=0.4 -> 10 * 0.6 = 6
        self.assertEqual(n_candidates_under_rigidity(10, 0.5, 0.0), 6)


if __name__ == "__main__":
    unittest.main()
