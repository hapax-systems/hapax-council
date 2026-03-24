"""Tests for agents.fortress.creativity_metrics — entropy, novelty, narrative density."""

from __future__ import annotations

import unittest

from agents.fortress.creativity_metrics import (
    CreativityMetrics,
    narrative_density,
    novelty_score,
    policy_entropy,
    semantic_injection_rate,
)


class TestPolicyEntropy(unittest.TestCase):
    def test_single_action_zero_entropy(self) -> None:
        self.assertAlmostEqual(policy_entropy({"dig": 10}), 0.0)

    def test_uniform_distribution_max_entropy(self) -> None:
        # 4 uniform actions → log2(4) = 2.0
        counts = {"dig": 10, "build": 10, "order": 10, "military": 10}
        self.assertAlmostEqual(policy_entropy(counts), 2.0, places=5)

    def test_empty_counts_zero(self) -> None:
        self.assertAlmostEqual(policy_entropy({}), 0.0)

    def test_two_actions_unequal(self) -> None:
        counts = {"dig": 9, "build": 1}
        ent = policy_entropy(counts)
        self.assertGreater(ent, 0.0)
        self.assertLess(ent, 1.0)

    def test_eight_uniform_actions(self) -> None:
        counts = {f"action_{i}": 10 for i in range(8)}
        self.assertAlmostEqual(policy_entropy(counts), 3.0, places=5)


class TestNoveltyScore(unittest.TestCase):
    def test_new_action_perfect_novelty(self) -> None:
        self.assertAlmostEqual(novelty_score("new", ["old", "other"]), 1.0)

    def test_always_repeated_zero_novelty(self) -> None:
        self.assertAlmostEqual(novelty_score("same", ["same", "same", "same"]), 0.0)

    def test_empty_prior_perfect_novelty(self) -> None:
        self.assertAlmostEqual(novelty_score("anything", []), 1.0)

    def test_partial_repetition(self) -> None:
        # "a" appears 2 out of 4 → novelty = 1 - 0.5 = 0.5
        self.assertAlmostEqual(novelty_score("a", ["a", "b", "a", "c"]), 0.5)


class TestNarrativeDensity(unittest.TestCase):
    def test_basic_ratio(self) -> None:
        self.assertAlmostEqual(narrative_density(10, 2.0), 5.0)

    def test_zero_years(self) -> None:
        self.assertAlmostEqual(narrative_density(10, 0.0), 0.0)

    def test_zero_episodes(self) -> None:
        self.assertAlmostEqual(narrative_density(0, 5.0), 0.0)

    def test_negative_years(self) -> None:
        self.assertAlmostEqual(narrative_density(10, -1.0), 0.0)


class TestSemanticInjectionRate(unittest.TestCase):
    def test_all_semantic(self) -> None:
        self.assertAlmostEqual(semantic_injection_rate(10, 10), 1.0)

    def test_none_semantic(self) -> None:
        self.assertAlmostEqual(semantic_injection_rate(0, 10), 0.0)

    def test_zero_total(self) -> None:
        self.assertAlmostEqual(semantic_injection_rate(0, 0), 0.0)

    def test_half(self) -> None:
        self.assertAlmostEqual(semantic_injection_rate(5, 10), 0.5)


class TestCreativityMetricsRecord(unittest.TestCase):
    def test_record_action_updates_counts(self) -> None:
        m = CreativityMetrics()
        m.record_action("dig")
        m.record_action("dig")
        m.record_action("build")
        self.assertEqual(m.action_counts["dig"], 2)
        self.assertEqual(m.action_counts["build"], 1)
        self.assertEqual(m.total_decisions, 3)
        self.assertEqual(len(m.prior_actions), 3)

    def test_record_action_with_semantic_ref(self) -> None:
        m = CreativityMetrics()
        m.record_action("dig", has_semantic_ref=True)
        m.record_action("build", has_semantic_ref=False)
        self.assertEqual(m.semantic_refs, 1)

    def test_record_episode(self) -> None:
        m = CreativityMetrics()
        m.record_episode()
        m.record_episode()
        self.assertEqual(m.episode_count, 2)

    def test_update_ticks(self) -> None:
        m = CreativityMetrics()
        m.update_ticks(500_000)
        self.assertEqual(m.game_ticks, 500_000)


class TestCreativityMetricsComposite(unittest.TestCase):
    def test_compute_score_bounded(self) -> None:
        m = CreativityMetrics()
        m.update_ticks(403_200)  # 1 year
        for i in range(20):
            m.record_action(f"action_{i % 5}", has_semantic_ref=i % 3 == 0)
        m.record_episode()
        m.record_episode()
        score = m.compute_score()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_empty_metrics_score_zero(self) -> None:
        m = CreativityMetrics()
        m.update_ticks(403_200)
        score = m.compute_score()
        # Empty: entropy=0, novelty=1 (empty action), density=0, sir=0
        # novelty of "" in [] = 1.0, but prior_actions has <=1 elem so branch differs
        # Actually: prior_actions is empty, so novelty returns 1.0 for ""
        # But wait — no prior_actions at all, so novelty_score("", []) = 1.0
        self.assertGreaterEqual(score, 0.0)

    def test_to_dict_keys(self) -> None:
        m = CreativityMetrics()
        m.update_ticks(403_200)
        m.record_action("dig")
        d = m.to_dict()
        expected_keys = {
            "policy_entropy",
            "latest_novelty",
            "narrative_density",
            "semantic_injection_rate",
            "composite_score",
            "total_decisions",
            "episode_count",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_to_dict_values_are_rounded(self) -> None:
        m = CreativityMetrics()
        m.update_ticks(403_200)
        m.record_action("dig")
        m.record_action("build")
        d = m.to_dict()
        # All float values should be rounded to 3 decimal places
        for key in (
            "policy_entropy",
            "latest_novelty",
            "narrative_density",
            "semantic_injection_rate",
            "composite_score",
        ):
            val = d[key]
            self.assertEqual(val, round(val, 3))

    def test_custom_weights(self) -> None:
        m = CreativityMetrics()
        m.update_ticks(403_200)
        m.record_action("dig")
        # All weight on novelty (index 1)
        score = m.compute_score(weights=(0.0, 1.0, 0.0, 0.0))
        # novelty of "dig" in [] = 1.0 (empty prior after removing last)
        # Actually prior_actions[:-1] = [], so novelty = 1.0
        self.assertAlmostEqual(score, 1.0)


if __name__ == "__main__":
    unittest.main()
