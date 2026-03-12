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

    def test_failed_blocks_context_gate(self, tmp_path):
        """Verify failed health → ContextGate system_health veto denies."""
        import time
        from unittest.mock import MagicMock

        from agents.hapax_voice.context_gate import ContextGate

        path = tmp_path / "health-history.jsonl"
        path.write_text(json.dumps({"healthy": 0, "total": 80}) + "\n")
        backend = HealthBackend(history_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)

        session = MagicMock()
        session.is_active = False
        gate = ContextGate(session=session, ambient_classification=False)
        gate._activity_mode = "idle"
        now = time.monotonic()
        gate.set_behaviors({
            "sink_volume": Behavior(0.3, watermark=now),
            "midi_active": Behavior(False, watermark=now),
            "system_health_status": behaviors["system_health_status"],
        })
        result = gate.check()
        assert result.eligible is False
        assert "system health" in result.reason.lower()

    def test_degraded_blocks_context_gate(self, tmp_path):
        """Degraded health blocks ContextGate (not fail-open)."""
        import time
        from unittest.mock import MagicMock

        from agents.hapax_voice.context_gate import ContextGate

        path = tmp_path / "health-history.jsonl"
        path.write_text(json.dumps({"healthy": 70, "total": 80}) + "\n")
        backend = HealthBackend(history_path=path)
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)

        session = MagicMock()
        session.is_active = False
        gate = ContextGate(session=session, ambient_classification=False)
        gate._activity_mode = "idle"
        now = time.monotonic()
        gate.set_behaviors({
            "sink_volume": Behavior(0.3, watermark=now),
            "midi_active": Behavior(False, watermark=now),
            "system_health_status": behaviors["system_health_status"],
        })
        result = gate.check()
        assert result.eligible is False
        assert "degraded" in result.reason.lower()
