"""Tests for stimmung refinements: adaptive model selection + confidence threshold."""

from __future__ import annotations

import importlib
import json
from unittest.mock import patch

import pytest

from shared import config as shared_config


class TestAdaptiveModelSelection:
    """WS2: stimmung-aware model routing."""

    @pytest.fixture(autouse=True)
    def reset_local_capacity_backpressure(self):
        shared_config._LOCAL_CAPACITY_BACKPRESSURE_ACTIVE = False
        yield
        shared_config._LOCAL_CAPACITY_BACKPRESSURE_ACTIVE = False

    def test_nominal_returns_requested(self):
        stimmung = {"overall_stance": "nominal", "llm_cost_pressure": {"value": 0.1}}
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = shared_config.get_model_adaptive("balanced")
        # Should return balanced (claude-sonnet), not downgraded
        assert model.model_name == shared_config.get_model("balanced").model_name

    def test_high_cost_downgrades_balanced(self):
        stimmung = {
            "overall_stance": "cautious",
            "llm_cost_pressure": {"value": 0.8},
            "resource_pressure": {"value": 0.2},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = shared_config.get_model_adaptive("balanced")
        assert model.model_name == shared_config.get_model("fast").model_name

    def test_high_cost_keeps_fast(self):
        stimmung = {
            "overall_stance": "cautious",
            "llm_cost_pressure": {"value": 0.8},
            "resource_pressure": {"value": 0.2},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = shared_config.get_model_adaptive("fast")
        # fast doesn't downgrade on cost pressure
        assert model.model_name == shared_config.get_model("fast").model_name

    def test_high_resource_downgrades_to_local(self):
        stimmung = {
            "overall_stance": "degraded",
            "llm_cost_pressure": {"value": 0.1},
            "resource_pressure": {"value": 0.85},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = shared_config.get_model_adaptive("fast")
        assert model.model_name == shared_config.get_model("local-fast").model_name

    def test_local_capacity_signal_is_required_to_invert_resource_downgrade(self, monkeypatch):
        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", False)
        base_stimmung = {
            "overall_stance": "degraded",
            "llm_cost_pressure": {"value": 0.1},
            "resource_pressure": {"value": 0.85},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(base_stimmung)):
            assert (
                shared_config.get_model_adaptive("fast").model_name
                == shared_config.get_model("local-fast").model_name
            )

        hot_local_stimmung = {
            **base_stimmung,
            "local_capacity_pressure": {"value": 0.82, "freshness_s": 3.0},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(hot_local_stimmung)):
            assert (
                shared_config.get_model_adaptive("fast").model_name
                == shared_config.get_model("fast").model_name
            )

    def test_high_local_capacity_inverts_local_downgrade(self, monkeypatch):
        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", False)
        stimmung = {
            "overall_stance": "degraded",
            "llm_cost_pressure": {"value": 0.1},
            "resource_pressure": {"value": 0.85},
            "local_capacity_pressure": {"value": 0.82, "freshness_s": 3.0},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = shared_config.get_model_adaptive("fast")
        assert model.model_name == shared_config.get_model("fast").model_name

    def test_high_local_capacity_inverts_reasoning_local_downgrade(self, monkeypatch):
        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", False)
        stimmung = {
            "overall_stance": "degraded",
            "llm_cost_pressure": {"value": 0.1},
            "resource_pressure": {"value": 0.85},
            "local_capacity_pressure": {"value": 0.82, "freshness_s": 3.0},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = shared_config.get_model_adaptive("reasoning")
        assert model.model_name == shared_config.get_model("fast").model_name

    def test_local_capacity_backpressure_is_hysteresis_guarded(self, monkeypatch):
        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", False)
        stimmung_high = {
            "overall_stance": "degraded",
            "llm_cost_pressure": {"value": 0.1},
            "resource_pressure": {"value": 0.85},
            "local_capacity_pressure": {"value": 0.82, "freshness_s": 3.0},
        }
        stimmung_mid = {
            **stimmung_high,
            "local_capacity_pressure": {"value": 0.62, "freshness_s": 3.0},
        }
        stimmung_above_recovery = {
            **stimmung_high,
            "local_capacity_pressure": {"value": 0.58, "freshness_s": 3.0},
        }
        stimmung_low = {
            **stimmung_high,
            "local_capacity_pressure": {"value": 0.4, "freshness_s": 3.0},
        }

        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung_high)):
            assert (
                shared_config.get_model_adaptive("fast").model_name
                == shared_config.get_model("fast").model_name
            )
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung_mid)):
            assert (
                shared_config.get_model_adaptive("fast").model_name
                == shared_config.get_model("fast").model_name
            )
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung_above_recovery)):
            assert (
                shared_config.get_model_adaptive("fast").model_name
                == shared_config.get_model("fast").model_name
            )
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung_low)):
            assert (
                shared_config.get_model_adaptive("fast").model_name
                == shared_config.get_model("local-fast").model_name
            )

    def test_stale_local_capacity_fails_open_to_current_behavior(self, monkeypatch):
        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", False)
        stimmung = {
            "overall_stance": "degraded",
            "llm_cost_pressure": {"value": 0.1},
            "resource_pressure": {"value": 0.85},
            "local_capacity_pressure": {"value": 0.95, "freshness_s": 300.0},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = shared_config.get_model_adaptive("fast")
        assert model.model_name == shared_config.get_model("local-fast").model_name

    def test_nonfinite_local_capacity_fails_open_to_current_behavior(self, monkeypatch):
        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", True)
        stimmung = {
            "overall_stance": "degraded",
            "llm_cost_pressure": {"value": 0.1},
            "resource_pressure": {"value": 0.85},
            "local_capacity_pressure": {"value": "NaN", "freshness_s": "Infinity"},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = shared_config.get_model_adaptive("fast")
        assert model.model_name == shared_config.get_model("local-fast").model_name
        assert shared_config._LOCAL_CAPACITY_BACKPRESSURE_ACTIVE is False

    def test_critical_uses_cloud_fast_when_local_capacity_is_hot(self, monkeypatch):
        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", False)
        stimmung = {
            "overall_stance": "critical",
            "local_capacity_pressure": {"value": 0.9, "freshness_s": 2.0},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = shared_config.get_model_adaptive("balanced")
        assert model.model_name == shared_config.get_model("fast").model_name

    def test_critical_uses_local_without_local_capacity_pressure(self):
        stimmung = {"overall_stance": "critical"}
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = shared_config.get_model_adaptive("balanced")
        assert model.model_name == shared_config.get_model("local-fast").model_name

    def test_missing_stimmung_returns_requested(self):
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            model = shared_config.get_model_adaptive("balanced")
        assert model.model_name == shared_config.get_model("balanced").model_name


class TestAgentsConfigAdaptiveModelSelection:
    """The active agents._config helper must share local-capacity backpressure."""

    @pytest.fixture(autouse=True)
    def reset_local_capacity_backpressure(self):
        shared_config._LOCAL_CAPACITY_BACKPRESSURE_ACTIVE = False
        yield
        shared_config._LOCAL_CAPACITY_BACKPRESSURE_ACTIVE = False

    def test_high_local_capacity_inverts_active_fast_local_downgrade(self, monkeypatch):
        import agents._config as agents_config

        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", False)
        stimmung = {
            "overall_stance": "degraded",
            "llm_cost_pressure": {"value": 0.1},
            "resource_pressure": {"value": 0.85},
            "local_capacity_pressure": {"value": 0.82, "freshness_s": 3.0},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = agents_config.get_model_adaptive("fast")
        assert model.model_name == agents_config.get_model("fast").model_name

    def test_active_critical_uses_cloud_fast_when_local_capacity_is_hot(self, monkeypatch):
        import agents._config as agents_config

        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", False)
        stimmung = {
            "overall_stance": "critical",
            "local_capacity_pressure": {"value": 0.9, "freshness_s": 2.0},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            model = agents_config.get_model_adaptive("balanced")
        assert model.model_name == agents_config.get_model("fast").model_name


class TestActiveAdaptiveRouterCopies:
    """Active adaptive-router entrypoints must share local-capacity backpressure."""

    @pytest.fixture(autouse=True)
    def reset_local_capacity_backpressure(self):
        shared_config._LOCAL_CAPACITY_BACKPRESSURE_ACTIVE = False
        yield
        shared_config._LOCAL_CAPACITY_BACKPRESSURE_ACTIVE = False

    @pytest.mark.parametrize(
        "module_name",
        [
            "agents.briefing",
            "agents.profiler",
            "agents.activity_analyzer",
            "agents.drift_detector.config",
        ],
    )
    def test_resource_downgrade_respects_hot_local_capacity(self, module_name, monkeypatch):
        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", False)
        module = importlib.import_module(module_name)
        base_stimmung = {
            "overall_stance": "degraded",
            "llm_cost_pressure": {"value": 0.1},
            "resource_pressure": {"value": 0.85},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(base_stimmung)):
            assert (
                module.get_model_adaptive("fast").model_name
                == shared_config.get_model("local-fast").model_name
            )

        hot_local_stimmung = {
            **base_stimmung,
            "local_capacity_pressure": {"value": 0.82, "freshness_s": 3.0},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(hot_local_stimmung)):
            assert (
                module.get_model_adaptive("fast").model_name
                == shared_config.get_model("fast").model_name
            )

    @pytest.mark.parametrize(
        "module_name",
        [
            "agents.briefing",
            "agents.profiler",
            "agents.activity_analyzer",
            "agents.drift_detector.config",
        ],
    )
    def test_critical_stance_respects_hot_local_capacity(self, module_name, monkeypatch):
        monkeypatch.setattr(shared_config, "_LOCAL_CAPACITY_BACKPRESSURE_ACTIVE", False)
        module = importlib.import_module(module_name)
        stimmung = {
            "overall_stance": "critical",
            "local_capacity_pressure": {"value": 0.9, "freshness_s": 2.0},
        }
        with patch("pathlib.Path.read_text", return_value=json.dumps(stimmung)):
            assert (
                module.get_model_adaptive("balanced").model_name
                == shared_config.get_model("fast").model_name
            )


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
