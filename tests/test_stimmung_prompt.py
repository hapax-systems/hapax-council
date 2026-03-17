"""Tests for stimmung system prompt injection."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from shared.operator import _read_stimmung_block


class TestStimmungPromptInjection:
    def test_missing_file_returns_empty(self):
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            assert _read_stimmung_block() == ""

    def test_nominal_returns_empty(self):
        """Nominal stance = no injection, zero token cost."""
        data = json.dumps(
            {
                "overall_stance": "nominal",
                "timestamp": time.monotonic(),
            }
        )
        with patch("pathlib.Path.read_text", return_value=data):
            result = _read_stimmung_block()
        assert result == ""

    def test_degraded_injects_block(self):
        """Non-nominal stance produces a prompt block."""
        from shared.stimmung import DimensionReading, Stance, SystemStimmung

        stimmung = SystemStimmung(
            health=DimensionReading(value=0.7, trend="rising", freshness_s=5.0),
            overall_stance=Stance.DEGRADED,
            timestamp=time.monotonic(),
        )
        raw = stimmung.model_dump_json()
        with patch("pathlib.Path.read_text", return_value=raw):
            result = _read_stimmung_block()
        assert "degraded" in result
        assert "System self-state" in result
        assert "health: 0.70 (rising)" in result
        assert "conserve resources" in result

    def test_critical_injects_block(self):
        from shared.stimmung import DimensionReading, Stance, SystemStimmung

        stimmung = SystemStimmung(
            resource_pressure=DimensionReading(value=0.95, trend="rising", freshness_s=2.0),
            overall_stance=Stance.CRITICAL,
            timestamp=time.monotonic(),
        )
        raw = stimmung.model_dump_json()
        with patch("pathlib.Path.read_text", return_value=raw):
            result = _read_stimmung_block()
        assert "critical" in result
        assert "resource_pressure" in result

    def test_stale_stimmung_returns_empty(self):
        """Stimmung older than 5 minutes is not injected."""
        from shared.stimmung import Stance, SystemStimmung

        # Use a positive timestamp that's clearly >300s in the past
        stale_ts = max(1.0, time.monotonic() - 400)
        stimmung = SystemStimmung(
            overall_stance=Stance.DEGRADED,
            timestamp=stale_ts,
        )
        raw = stimmung.model_dump_json()
        with patch("pathlib.Path.read_text", return_value=raw):
            result = _read_stimmung_block()
        assert result == ""

    def test_corrupt_json_returns_empty(self):
        with patch("pathlib.Path.read_text", return_value="not json{"):
            assert _read_stimmung_block() == ""
