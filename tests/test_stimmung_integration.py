"""Tests for stimmung integration with the visual layer aggregator."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents._stimmung import DimensionReading, StimmungCollector, SystemStimmung
from agents.visual_layer_aggregator import (
    VisualLayerAggregator,
    map_stimmung,
)
from agents.visual_layer_state import SignalCategory


class TestMapStimmung:
    def test_nominal_produces_no_signals(self):
        s = SystemStimmung()
        assert map_stimmung(s) == []

    def test_non_nominal_produces_signals(self):
        s = SystemStimmung(
            health=DimensionReading(value=0.5, trend="rising", freshness_s=5.0),
            resource_pressure=DimensionReading(value=0.8, trend="stable", freshness_s=3.0),
        )
        signals = map_stimmung(s)
        assert len(signals) == 2
        assert all(sig.category == SignalCategory.SYSTEM_STATE for sig in signals)
        assert any("health" in sig.title for sig in signals)
        assert any("resource pressure" in sig.title for sig in signals)

    def test_stale_dimensions_excluded(self):
        s = SystemStimmung(
            error_rate=DimensionReading(value=0.9, freshness_s=200.0),
        )
        assert map_stimmung(s) == []

    def test_signal_severity_matches_dimension_value(self):
        s = SystemStimmung(
            health=DimensionReading(value=0.7, trend="stable", freshness_s=5.0),
        )
        signals = map_stimmung(s)
        assert len(signals) == 1
        assert signals[0].severity == 0.7

    def test_trend_in_title(self):
        s = SystemStimmung(
            health=DimensionReading(value=0.5, trend="rising", freshness_s=5.0),
        )
        signals = map_stimmung(s)
        assert "(rising)" in signals[0].title


class TestAggregatorStimmung:
    def test_aggregator_has_stimmung_collector(self):
        agg = VisualLayerAggregator()
        assert isinstance(agg._stimmung_collector, StimmungCollector)
        assert agg._stimmung is None

    def test_compute_and_write_with_nominal_stimmung(self):
        agg = VisualLayerAggregator()
        state = agg.compute_and_write()
        assert state.stimmung_stance == "nominal"

    def test_compute_and_write_with_degraded_stimmung(self):
        agg = VisualLayerAggregator()
        # Feed degraded health into collector
        agg._stimmung_collector.update_health(healthy=3, total=10)
        agg._stimmung = agg._stimmung_collector.snapshot()
        state = agg.compute_and_write()
        assert state.stimmung_stance in ("degraded", "critical")

    def test_stimmung_signals_in_output(self):
        agg = VisualLayerAggregator()
        agg._stimmung_collector.update_gpu(used_mb=22000, total_mb=24000)
        agg._stimmung = agg._stimmung_collector.snapshot()
        state = agg.compute_and_write()
        system_signals = state.signals.get(SignalCategory.SYSTEM_STATE, [])
        assert len(system_signals) >= 1

    @pytest.mark.asyncio
    async def test_update_stimmung_reads_files(self, tmp_path: Path, monkeypatch):
        """Verify _update_stimmung reads data sources without error."""
        # Create minimal data files
        health_path = tmp_path / "health-history.jsonl"
        health_path.write_text(json.dumps({"healthy": 8, "total": 10}))

        infra_path = tmp_path / "infra-snapshot.json"
        infra_path.write_text(json.dumps({"gpu": {"used_mb": 5000, "total_mb": 24000}}))

        monkeypatch.setattr(
            "agents.visual_layer_aggregator.constants.HEALTH_HISTORY_PATH", health_path
        )
        monkeypatch.setattr(
            "agents.visual_layer_aggregator.constants.INFRA_SNAPSHOT_PATH", infra_path
        )
        monkeypatch.setattr(
            "agents.visual_layer_aggregator.constants.LANGFUSE_STATE_PATH",
            tmp_path / "nonexistent.json",
        )

        agg = VisualLayerAggregator()
        agg._ts_perception = time.monotonic() - 5.0  # 5s ago
        agg._update_stimmung()

        assert agg._stimmung is not None
        assert agg._stimmung.health.value == 0.2  # 8/10 healthy → 0.2 bad
        assert agg._stimmung.resource_pressure.value < 0.3

    @pytest.mark.asyncio
    async def test_update_stimmung_tolerates_missing_files(self, monkeypatch):
        """All sources missing → still produces a nominal snapshot."""
        monkeypatch.setattr(
            "agents.visual_layer_aggregator.constants.HEALTH_HISTORY_PATH",
            Path("/nonexistent/health.jsonl"),
        )
        monkeypatch.setattr(
            "agents.visual_layer_aggregator.constants.INFRA_SNAPSHOT_PATH",
            Path("/nonexistent/infra.json"),
        )
        monkeypatch.setattr(
            "agents.visual_layer_aggregator.constants.LANGFUSE_STATE_PATH",
            Path("/nonexistent/langfuse.json"),
        )

        agg = VisualLayerAggregator()
        agg._update_stimmung()
        # Should not crash, and perception update at least runs
        assert agg._stimmung is not None
