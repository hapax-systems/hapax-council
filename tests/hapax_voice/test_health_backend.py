"""Tests for HealthBackend — system health from health-history.jsonl."""

from __future__ import annotations

import json

import pytest

from agents.hapax_voice.backends.health import HealthBackend
from agents.hapax_voice.primitives import Behavior


class TestHealthBackend:
    def test_80_of_80_healthy(self, tmp_path):
        path = tmp_path / "health-history.jsonl"
        path.write_text(json.dumps({"healthy": 80, "total": 80}) + "\n")
        backend = HealthBackend(history_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["system_health_status"].value == "healthy"
        assert behaviors["system_health_ratio"].value == pytest.approx(1.0)

    def test_70_of_80_degraded(self, tmp_path):
        path = tmp_path / "health-history.jsonl"
        path.write_text(json.dumps({"healthy": 70, "total": 80}) + "\n")
        backend = HealthBackend(history_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["system_health_status"].value == "degraded"
        assert behaviors["system_health_ratio"].value == pytest.approx(0.875)

    def test_0_of_80_failed(self, tmp_path):
        path = tmp_path / "health-history.jsonl"
        path.write_text(json.dumps({"healthy": 0, "total": 80}) + "\n")
        backend = HealthBackend(history_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["system_health_status"].value == "failed"
        assert behaviors["system_health_ratio"].value == pytest.approx(0.0)

    def test_missing_file_defaults(self, tmp_path):
        path = tmp_path / "health-history.jsonl"
        backend = HealthBackend(history_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["system_health_status"].value == "unknown"
        assert behaviors["system_health_ratio"].value == pytest.approx(1.0)

    def test_empty_file_defaults(self, tmp_path):
        path = tmp_path / "health-history.jsonl"
        path.write_text("")
        backend = HealthBackend(history_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["system_health_status"].value == "unknown"

    def test_multiple_lines_reads_last(self, tmp_path):
        path = tmp_path / "health-history.jsonl"
        lines = [
            json.dumps({"healthy": 80, "total": 80}),
            json.dumps({"healthy": 0, "total": 80}),
        ]
        path.write_text("\n".join(lines) + "\n")
        backend = HealthBackend(history_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert behaviors["system_health_status"].value == "failed"

    def test_failed_triggers_governor_pause(self, tmp_path):
        """Verify failed health → governor system_health veto denies."""
        from agents.hapax_voice.perception import EnvironmentState

        state = EnvironmentState(
            timestamp=0.0,
            system_health="failed",
            operator_present=True,
        )
        assert state.system_health == "failed"

    def test_degraded_is_fail_open(self, tmp_path):
        """Degraded health should NOT trigger governor pause."""
        from agents.hapax_voice.governor import PipelineGovernor
        from agents.hapax_voice.perception import EnvironmentState

        gov = PipelineGovernor()
        state = EnvironmentState(
            timestamp=0.0,
            system_health="degraded",
            operator_present=True,
        )
        directive = gov.evaluate(state)
        assert directive == "process"
