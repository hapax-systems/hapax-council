"""Tests for the visual layer signal aggregator.

Covers: signal mapping functions, aggregator compute/write, atomic file write,
graceful degradation on API errors.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agents.visual_layer_aggregator import (
    SignalAggregator,
    _map_briefing,
    _map_drift,
    _map_goals,
    _map_gpu,
    _map_health,
    _map_nudges,
)
from agents.visual_layer_state import SignalCategory

# ── Health Mapping ──────────────────────────────────────────────────────────


class TestMapHealth:
    def test_healthy_returns_empty(self):
        assert _map_health({"overall_status": "healthy"}) == []

    def test_degraded_returns_signal(self):
        signals = _map_health({
            "overall_status": "degraded",
            "failed_checks": ["docker", "gpu"],
        })
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.HEALTH_INFRA
        assert signals[0].severity >= 0.5
        assert "degraded" in signals[0].title.lower()

    def test_failed_with_many_checks(self):
        signals = _map_health({
            "overall_status": "failed",
            "failed_checks": ["a", "b", "c", "d", "e"],
        })
        assert signals[0].severity == 1.0  # capped at 1.0


# ── GPU Mapping ─────────────────────────────────────────────────────────────


class TestMapGpu:
    def test_low_vram_returns_empty(self):
        assert _map_gpu({"vram_used_mib": 5000, "vram_total_mib": 24000}) == []

    def test_high_vram_returns_signal(self):
        signals = _map_gpu({"vram_used_mib": 22000, "vram_total_mib": 24000})
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.HEALTH_INFRA
        assert "VRAM" in signals[0].title

    def test_empty_data_returns_empty(self):
        assert _map_gpu({}) == []
        assert _map_gpu(None) == []


# ── Nudge Mapping ───────────────────────────────────────────────────────────


class TestMapNudges:
    def test_maps_top_3(self):
        nudges = [
            {"title": f"Nudge {i}", "priority": "medium", "id": str(i), "reason": "test"}
            for i in range(5)
        ]
        signals = _map_nudges(nudges)
        assert len(signals) == 3

    def test_priority_maps_to_severity(self):
        signals = _map_nudges([{"title": "Critical", "priority": "critical", "id": "1"}])
        assert signals[0].severity == 0.85

    def test_empty_returns_empty(self):
        assert _map_nudges([]) == []


# ── Briefing Mapping ────────────────────────────────────────────────────────


class TestMapBriefing:
    def test_maps_headline(self):
        signals = _map_briefing({"headline": "System healthy, 3 goals on track"})
        assert len(signals) == 1
        assert signals[0].category == SignalCategory.CONTEXT_TIME

    def test_empty_returns_empty(self):
        assert _map_briefing({}) == []
        assert _map_briefing(None) == []

    def test_no_headline_returns_empty(self):
        assert _map_briefing({"headline": ""}) == []


# ── Drift Mapping ───────────────────────────────────────────────────────────


class TestMapDrift:
    def test_maps_high_severity(self):
        signals = _map_drift({
            "items": [
                {"severity": "high", "title": "Drift item", "id": "1"},
                {"severity": "low", "title": "Minor drift", "id": "2"},
            ]
        })
        assert len(signals) == 1
        assert signals[0].severity == 0.7

    def test_critical_severity(self):
        signals = _map_drift({
            "items": [{"severity": "critical", "title": "Critical", "id": "1"}]
        })
        assert signals[0].severity == 0.85

    def test_empty_returns_empty(self):
        assert _map_drift({}) == []
        assert _map_drift(None) == []


# ── Goal Mapping ────────────────────────────────────────────────────────────


class TestMapGoals:
    def test_maps_stale_goals(self):
        signals = _map_goals({
            "goals": [
                {"title": "Goal A", "stale": True, "id": "1"},
                {"title": "Goal B", "stale": False, "id": "2"},
            ]
        })
        assert len(signals) == 1
        assert "Stale" in signals[0].title

    def test_empty_returns_empty(self):
        assert _map_goals({}) == []
        assert _map_goals(None) == []


# ── Aggregator ──────────────────────────────────────────────────────────────


class TestAggregator:
    def test_compute_writes_file(self, tmp_path: Path):
        """Verify atomic write to output path."""
        output_file = tmp_path / "visual-layer-state.json"
        agg = SignalAggregator()

        with patch("agents.visual_layer_aggregator.OUTPUT_DIR", tmp_path), \
             patch("agents.visual_layer_aggregator.OUTPUT_FILE", output_file), \
             patch("agents.visual_layer_aggregator._read_perception", return_value={}):
            agg.compute_and_write()

        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert "display_state" in data
        assert data["display_state"] == "ambient"

    def test_compute_with_signals(self, tmp_path: Path):
        """Verify state escalation with signals."""
        output_file = tmp_path / "visual-layer-state.json"
        agg = SignalAggregator()
        agg._fast_signals = _map_health({
            "overall_status": "failed",
            "failed_checks": ["docker", "gpu", "voice", "qdrant", "litellm"],
        })

        with patch("agents.visual_layer_aggregator.OUTPUT_DIR", tmp_path), \
             patch("agents.visual_layer_aggregator.OUTPUT_FILE", output_file), \
             patch("agents.visual_layer_aggregator._read_perception", return_value={}):
            state = agg.compute_and_write()

        assert state.display_state.value != "ambient"

    @pytest.mark.asyncio
    async def test_poll_fast_tolerates_errors(self):
        """Verify graceful degradation on API errors."""
        agg = SignalAggregator()
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        agg._client = mock_client

        await agg.poll_fast()
        assert agg._fast_signals == []

    @pytest.mark.asyncio
    async def test_poll_slow_tolerates_errors(self):
        """Verify graceful degradation on slow API errors."""
        agg = SignalAggregator()
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        agg._client = mock_client

        await agg.poll_slow()
        assert agg._slow_signals == []
