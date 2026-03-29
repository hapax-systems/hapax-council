"""Tests for salience correlation analysis in eval_grounding."""

from __future__ import annotations

import unittest

import pytest

pytestmark = pytest.mark.research

from agents.hapax_daimonion.eval_grounding import (
    SessionEval,
    TurnEval,
    analyze_salience_correlation,
    format_report,
)


def _make_trace(turn: int, activation: float, anchor: float) -> dict:
    """Build a fake Langfuse trace dict (REST API format)."""
    return {
        "metadata": {"turn": turn},
        "scores": [
            {"name": "activation_score", "value": activation},
            {"name": "context_anchor_success", "value": anchor},
        ],
    }


def _make_session(sid: str, n_turns: int) -> SessionEval:
    """Build a SessionEval with dummy turns."""
    se = SessionEval(session_id=sid, turn_count=n_turns)
    for i in range(n_turns):
        se.turns.append(TurnEval(turn_index=i, assistant_text="word " * (10 + i)))
    return se


class TestInsufficientData(unittest.TestCase):
    def test_insufficient_data_returns_none(self) -> None:
        """< 50 turns → None."""
        se = _make_session("s1", 10)
        traces = [_make_trace(i, 0.5, 0.8) for i in range(10)]
        result = analyze_salience_correlation([se], {"s1": traces})
        self.assertIsNone(result)


class TestCorrelationWithMockData(unittest.TestCase):
    def test_correlation_with_mock_data(self) -> None:
        """60 mock turns with known positive correlation."""
        n = 60
        se = _make_session("s1", n)
        # Activation increases with turn index → token count also increases
        traces = [_make_trace(i, float(i) / n, 0.5 + 0.3 * (i / n)) for i in range(n)]
        result = analyze_salience_correlation([se], {"s1": traces})
        self.assertIsNotNone(result)
        self.assertEqual(result["n_turns"], n)
        self.assertGreater(result["r_tokens"], 0)
        self.assertGreater(result["r_anchor"], 0)


class TestReportIncludesCorrelation(unittest.TestCase):
    def test_report_includes_correlation_section(self) -> None:
        """format_report output includes Claim 5 section when correlation present."""
        se = _make_session("s1", 5)
        se.acceptance_rate = 0.8
        se.reference_accuracy = 0.9
        se.grounding_depth = 2
        se.judge_summary = "Good"

        correlation = {
            "r_tokens": 0.45,
            "r_anchor": 0.32,
            "bf_tokens": 12.5,
            "bf_anchor": 4.2,
            "n_turns": 60,
            "ci_tokens": (0.2, 0.65),
            "ci_anchor": (0.05, 0.55),
        }
        report = format_report([se], correlation=correlation)
        self.assertIn("Claim 5: Salience Correlation", report)
        self.assertIn("r(activation, tokens): 0.450", report)
        self.assertIn("Turns analyzed: 60", report)

    def test_report_no_correlation(self) -> None:
        """format_report without correlation omits Claim 5 section."""
        se = _make_session("s1", 5)
        report = format_report([se])
        self.assertNotIn("Claim 5", report)


if __name__ == "__main__":
    unittest.main()
