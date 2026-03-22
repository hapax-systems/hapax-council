"""Tests for trajectory scores and turn-pair coherence in eval_grounding."""

from __future__ import annotations

import unittest

import pytest

pytestmark = pytest.mark.research

from agents.hapax_voice.eval_grounding import (
    SessionEval,
    collect_per_turn_scores,
    compute_trajectories,
    format_report,
)


def _make_per_turn(
    anchors: list[float],
    frustrations: list[float] | None = None,
    acceptances: list[float] | None = None,
) -> list[dict[str, float]]:
    """Build per-turn score dicts from value lists."""
    n = len(anchors)
    if frustrations is None:
        frustrations = [0.0] * n
    if acceptances is None:
        acceptances = [0.3] * n  # IGNORE default
    return [
        {
            "context_anchor_success": a,
            "frustration_score": f,
            "acceptance_type": acc,
        }
        for a, f, acc in zip(anchors, frustrations, acceptances, strict=True)
    ]


class TestTrajectorySlope(unittest.TestCase):
    def test_improving_anchor(self) -> None:
        """Linearly increasing anchors → positive trajectory."""
        se = SessionEval(turn_count=6)
        scores = _make_per_turn([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])
        compute_trajectories(se, scores)
        self.assertGreater(se.anchor_trajectory, 0.05)

    def test_flat_anchor(self) -> None:
        """Constant anchors → near-zero trajectory."""
        se = SessionEval(turn_count=6)
        scores = _make_per_turn([0.5, 0.5, 0.5, 0.5, 0.5, 0.5])
        compute_trajectories(se, scores)
        self.assertAlmostEqual(se.anchor_trajectory, 0.0, places=3)

    def test_declining_frustration(self) -> None:
        """Decreasing frustration → negative trajectory (good)."""
        se = SessionEval(turn_count=5)
        scores = _make_per_turn(
            [0.5] * 5,
            frustrations=[4.0, 3.0, 2.0, 1.0, 0.0],
        )
        compute_trajectories(se, scores)
        self.assertLess(se.frustration_trajectory, -0.5)

    def test_too_few_turns(self) -> None:
        """< 3 turns → no trajectory computed."""
        se = SessionEval(turn_count=2)
        scores = _make_per_turn([0.1, 0.9])
        compute_trajectories(se, scores)
        self.assertEqual(se.anchor_trajectory, 0.0)


class TestTurnPairCoherence(unittest.TestCase):
    def test_accept_after_high_anchor(self) -> None:
        """High anchor turns followed by ACCEPT → high coherence."""
        se = SessionEval(turn_count=6)
        scores = _make_per_turn(
            anchors=[0.8, 0.8, 0.8, 0.8, 0.8, 0.8],
            acceptances=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0],  # all ACCEPT
        )
        compute_trajectories(se, scores)
        self.assertIsNotNone(se.acceptance_after_anchor)
        self.assertGreater(se.acceptance_after_anchor, 0.8)

    def test_frustration_after_low_anchor(self) -> None:
        """Low anchor turns followed by frustration → high coherence."""
        se = SessionEval(turn_count=6)
        scores = _make_per_turn(
            anchors=[0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
            frustrations=[2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
        )
        compute_trajectories(se, scores)
        self.assertIsNotNone(se.frustration_after_miss)
        self.assertGreater(se.frustration_after_miss, 0.8)

    def test_insufficient_pairs(self) -> None:
        """Too few high-anchor turns → None."""
        se = SessionEval(turn_count=5)
        scores = _make_per_turn(
            anchors=[0.1, 0.1, 0.1, 0.8, 0.1],  # only 1 high anchor
            acceptances=[1.0, 1.0, 1.0, 1.0, 1.0],
        )
        compute_trajectories(se, scores)
        self.assertIsNone(se.acceptance_after_anchor)


class TestCollectPerTurnScores(unittest.TestCase):
    def test_extracts_and_orders(self) -> None:
        """Extracts scores from trace dicts and orders by turn."""
        traces = [
            {
                "metadata": {"turn": 2},
                "scores": [{"name": "context_anchor_success", "value": 0.8}],
            },
            {
                "metadata": {"turn": 0},
                "scores": [{"name": "context_anchor_success", "value": 0.2}],
            },
            {
                "metadata": {"turn": 1},
                "scores": [
                    {"name": "context_anchor_success", "value": 0.5},
                    {"name": "frustration_score", "value": 1},
                ],
            },
        ]
        result = collect_per_turn_scores(traces)
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[0]["context_anchor_success"], 0.2)
        self.assertAlmostEqual(result[1]["context_anchor_success"], 0.5)
        self.assertAlmostEqual(result[2]["context_anchor_success"], 0.8)

    def test_handles_intValue_format(self) -> None:
        """Handles Langfuse intValue wrapper for turn index."""
        traces = [
            {
                "metadata": {"turn": {"intValue": 0}},
                "scores": [{"name": "context_anchor_success", "value": 0.5}],
            },
        ]
        result = collect_per_turn_scores(traces)
        self.assertEqual(len(result), 1)


class TestFormatReportTrajectories(unittest.TestCase):
    def test_includes_trajectory(self) -> None:
        """Report includes trajectory data when present."""
        se = SessionEval(
            session_id="test",
            turn_count=6,
            acceptance_rate=0.8,
            reference_accuracy=0.9,
            grounding_depth=2,
            anchor_trajectory=0.05,
            frustration_trajectory=-0.3,
            acceptance_after_anchor=0.85,
        )
        report = format_report([se])
        self.assertIn("Anchor trajectory: +0.0500 (improving)", report)
        self.assertIn("Frustration trajectory: -0.3000", report)
        self.assertIn("P(accept|high anchor): 85.0%", report)

    def test_omits_trajectory_when_zero(self) -> None:
        """Report omits trajectory when all zeros (too few turns)."""
        se = SessionEval(session_id="test", turn_count=2)
        report = format_report([se])
        self.assertNotIn("trajectory", report)


if __name__ == "__main__":
    unittest.main()
