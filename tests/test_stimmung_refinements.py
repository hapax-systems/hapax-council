"""Tests for stimmung refinements: adaptive model selection + confidence threshold."""

from __future__ import annotations

import json
from unittest.mock import patch


class TestAdaptiveModelSelection:
    """WS2: stimmung-aware model routing."""

    def test_nominal_returns_requested(self):
        from shared.config import get_model, get_model_adaptive

        stimmung = {"overall_stance": "nominal", "llm_cost_pressure": {"value": 0.1}}
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = get_model_adaptive("balanced")
        # Should return balanced (claude-sonnet), not downgraded
        assert model.model_name == get_model("balanced").model_name

    def test_high_cost_downgrades_balanced(self):
        from shared.config import get_model, get_model_adaptive

        stimmung = {
            "overall_stance": "cautious",
            "llm_cost_pressure": {"value": 0.8},
            "resource_pressure": {"value": 0.2},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = get_model_adaptive("balanced")
        assert model.model_name == get_model("fast").model_name

    def test_high_cost_keeps_fast(self):
        from shared.config import get_model, get_model_adaptive

        stimmung = {
            "overall_stance": "cautious",
            "llm_cost_pressure": {"value": 0.8},
            "resource_pressure": {"value": 0.2},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = get_model_adaptive("fast")
        # fast doesn't downgrade on cost pressure
        assert model.model_name == get_model("fast").model_name

    def test_high_resource_downgrades_to_local(self):
        from shared.config import get_model, get_model_adaptive

        stimmung = {
            "overall_stance": "degraded",
            "llm_cost_pressure": {"value": 0.1},
            "resource_pressure": {"value": 0.85},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = get_model_adaptive("fast")
        assert model.model_name == get_model("local-fast").model_name

    def test_critical_always_local(self):
        from shared.config import get_model, get_model_adaptive

        stimmung = {"overall_stance": "critical"}
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = get_model_adaptive("balanced")
        assert model.model_name == get_model("local-fast").model_name

    def test_missing_stimmung_returns_requested(self):
        from shared.config import get_model, get_model_adaptive

        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            model = get_model_adaptive("balanced")
        assert model.model_name == get_model("balanced").model_name


class TestAdaptiveConfidenceThreshold:
    """WS5: self-tuning confidence threshold."""

    def _make_monitor(self):
        from agents.hapax_daimonion.workspace_monitor import WorkspaceMonitor

        return WorkspaceMonitor(enabled=False)

    def test_initial_threshold(self):
        monitor = self._make_monitor()
        assert monitor._local_confidence_threshold == 0.7

    def test_high_agreement_lowers_threshold(self):
        monitor = self._make_monitor()
        monitor._agreement_count = 9
        monitor._disagreement_count = 1
        monitor._threshold_adjust_interval = 10
        monitor._maybe_adjust_threshold()
        assert monitor._local_confidence_threshold < 0.7

    def test_high_disagreement_raises_threshold(self):
        monitor = self._make_monitor()
        monitor._agreement_count = 5
        monitor._disagreement_count = 5
        monitor._threshold_adjust_interval = 10
        monitor._maybe_adjust_threshold()
        assert monitor._local_confidence_threshold > 0.7

    def test_threshold_bounded_low(self):
        monitor = self._make_monitor()
        monitor._local_confidence_threshold = 0.52
        monitor._agreement_count = 10
        monitor._disagreement_count = 0
        monitor._threshold_adjust_interval = 10
        monitor._maybe_adjust_threshold()
        assert monitor._local_confidence_threshold >= 0.5

    def test_threshold_bounded_high(self):
        monitor = self._make_monitor()
        monitor._local_confidence_threshold = 0.88
        monitor._agreement_count = 2
        monitor._disagreement_count = 8
        monitor._threshold_adjust_interval = 10
        monitor._maybe_adjust_threshold()
        assert monitor._local_confidence_threshold <= 0.9

    def test_counters_reset_after_adjust(self):
        monitor = self._make_monitor()
        monitor._agreement_count = 8
        monitor._disagreement_count = 2
        monitor._threshold_adjust_interval = 10
        monitor._maybe_adjust_threshold()
        assert monitor._agreement_count == 0
        assert monitor._disagreement_count == 0

    def test_no_adjust_below_interval(self):
        monitor = self._make_monitor()
        monitor._agreement_count = 3
        monitor._disagreement_count = 0
        monitor._threshold_adjust_interval = 10
        monitor._maybe_adjust_threshold()
        # Not enough data — threshold unchanged
        assert monitor._local_confidence_threshold == 0.7
        # Counters NOT reset
        assert monitor._agreement_count == 3
