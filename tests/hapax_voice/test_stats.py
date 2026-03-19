"""Tests for Bayesian analysis functions in agents.hapax_voice.stats."""

from __future__ import annotations

import unittest

from agents.hapax_voice.stats import (
    bayes_correlation,
    bayes_factor,
    rope_check,
    sequential_check,
)


class TestBayesFactor(unittest.TestCase):
    def test_bf_strong_evidence(self) -> None:
        """18/20 successes with Beta(2,2) prior and wide ROPE → BF > 10."""
        bf = bayes_factor(18, 20, prior_a=2, prior_b=2, rope_low=0.3, rope_high=0.7)
        self.assertGreater(bf, 10)

    def test_bf_near_null(self) -> None:
        """10/20 successes with symmetric prior → BF near 1."""
        bf = bayes_factor(10, 20, prior_a=2, prior_b=2, rope_low=0.4, rope_high=0.6)
        self.assertLess(bf, 5)
        self.assertGreater(bf, 0.2)


class TestSequentialCheck(unittest.TestCase):
    def test_stop_h1(self) -> None:
        self.assertEqual(sequential_check(bf=15.0, n=10, max_n=30), "stop_h1")

    def test_continue(self) -> None:
        self.assertEqual(sequential_check(bf=3.0, n=10, max_n=30), "continue")

    def test_stop_max(self) -> None:
        self.assertEqual(sequential_check(bf=3.0, n=30, max_n=30), "stop_max")

    def test_stop_h0(self) -> None:
        self.assertEqual(sequential_check(bf=0.05, n=10, max_n=30), "stop_h0")


class TestRopeCheck(unittest.TestCase):
    def test_rope_inside(self) -> None:
        """10/20 with tight ROPE → mass mostly inside."""
        result = rope_check(10, 20, prior_a=2, prior_b=2, rope_low=0.3, rope_high=0.7)
        self.assertGreater(result["inside"], 0.5)
        self.assertAlmostEqual(result["inside"] + result["outside"], 1.0, places=10)


class TestBayesCorrelation(unittest.TestCase):
    def test_correlation_positive(self) -> None:
        """Correlated arrays → r > 0, BF > 1."""
        x = list(range(50))
        y = [v * 2.0 + 1.0 for v in x]
        result = bayes_correlation(x, y, prior_mu=0.0, prior_sigma=1.0)
        self.assertGreater(result["r"], 0.9)
        self.assertGreater(result["bf"], 1.0)
        self.assertIsInstance(result["ci_95"], tuple)
        self.assertEqual(len(result["ci_95"]), 2)

    def test_correlation_null(self) -> None:
        """Uncorrelated → r ≈ 0."""
        import random

        rng = random.Random(42)
        x = [rng.gauss(0, 1) for _ in range(100)]
        y = [rng.gauss(0, 1) for _ in range(100)]
        result = bayes_correlation(x, y, prior_mu=0.0, prior_sigma=1.0)
        self.assertLess(abs(result["r"]), 0.3)


if __name__ == "__main__":
    unittest.main()
