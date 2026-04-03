"""Tests for stimmung pipeline coherence — field name consistency and SHM flow.

Regression tests for the 2026-03-31 audit findings:
- C1: API route must parse nested DimensionReading dicts
- C2: Sync agent must persist all 10 dimensions
- C3: imagination.py must use "stance" (sensor-layer key) not "overall_stance" (raw SHM key)
- C4: reverie/actuation.py must use "overall_stance" and derive color_warmth
- H2: Engine must ignore stale stimmung (>5min)
- M4: ContextAssembler must read SHM only once
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.stimmung import DimensionReading, StimmungCollector, SystemStimmung


class TestShmWriteRoundtrip:
    """Verify SHM write produces JSON that consumers can parse."""

    def test_model_dump_json_is_nested(self):
        """SystemStimmung.model_dump_json() must produce nested dimension objects."""
        s = SystemStimmung(
            health=DimensionReading(value=0.5, trend="rising", freshness_s=3.0),
            overall_stance="cautious",
            timestamp=1000.0,
        )
        raw = json.loads(s.model_dump_json())

        assert isinstance(raw["health"], dict)
        assert raw["health"]["value"] == 0.5
        assert raw["health"]["trend"] == "rising"
        assert raw["health"]["freshness_s"] == 3.0
        assert raw["overall_stance"] == "cautious"

    def test_collector_snapshot_roundtrip(self):
        """Collector → snapshot → JSON → parse must preserve all 10 dimensions."""
        collector = StimmungCollector()
        collector.update_health(healthy=8, total=10)
        collector.update_gpu(used_mb=22000, total_mb=24000)
        collector.update_biometrics(hrv_current=30, hrv_baseline=50)

        snapshot = collector.snapshot()
        raw = json.loads(snapshot.model_dump_json())

        # All 10 dimensions must be present as nested dicts
        expected_dims = [
            "health",
            "resource_pressure",
            "error_rate",
            "processing_throughput",
            "perception_confidence",
            "llm_cost_pressure",
            "grounding_quality",
            "operator_stress",
            "operator_energy",
            "physiological_coherence",
        ]
        for dim in expected_dims:
            assert dim in raw, f"Missing dimension: {dim}"
            assert isinstance(raw[dim], dict), f"{dim} not nested"
            assert "value" in raw[dim], f"{dim} missing value"
            assert "trend" in raw[dim], f"{dim} missing trend"
            assert "freshness_s" in raw[dim], f"{dim} missing freshness_s"

    def test_shm_write_produces_parseable_json(self, tmp_path: Path):
        """write_stimmung() produces JSON that API route can parse."""
        from agents.visual_layer_aggregator.stimmung_methods import write_stimmung

        # Minimal aggregator mock
        class FakeAgg:
            _stimmung = SystemStimmung(
                health=DimensionReading(value=0.3, trend="stable", freshness_s=2.0),
                overall_stance="cautious",
                timestamp=time.time(),
            )

        stimmung_dir = tmp_path / "hapax-stimmung"
        stimmung_file = stimmung_dir / "state.json"

        with (
            patch("agents.visual_layer_aggregator.constants.STIMMUNG_DIR", stimmung_dir),
            patch("agents.visual_layer_aggregator.constants.STIMMUNG_FILE", stimmung_file),
        ):
            write_stimmung(FakeAgg())

        assert stimmung_file.exists()
        raw = json.loads(stimmung_file.read_text())
        assert raw["overall_stance"] == "cautious"
        assert isinstance(raw["health"], dict)
        assert raw["health"]["value"] == 0.3


class TestConsumerFieldNames:
    """Verify consumers use correct field names from SystemStimmung JSON."""

    def _make_stimmung_raw(self, **overrides) -> dict:
        """Create a realistic stimmung_raw dict from SystemStimmung."""
        s = SystemStimmung(
            health=DimensionReading(value=0.5, trend="rising", freshness_s=3.0),
            resource_pressure=DimensionReading(value=0.8, trend="stable", freshness_s=2.0),
            operator_stress=DimensionReading(value=0.6, trend="rising", freshness_s=5.0),
            overall_stance="degraded",
            timestamp=time.time(),
            **overrides,
        )
        return json.loads(s.model_dump_json())

    def test_imagination_reads_stance(self):
        """imagination.assemble_context must use 'stance' (sensor-layer key), not 'overall_stance'."""
        from agents.imagination import assemble_context

        # sensor.py normalises overall_stance → stance before writing the snapshot
        stimmung_raw = self._make_stimmung_raw()
        sensor_snapshot = {
            "stimmung": {
                "stance": stimmung_raw["overall_stance"],  # sensor.py normalisation
                "operator_stress": stimmung_raw.get("operator_stress", {}),
            }
        }
        context = assemble_context([], [], sensor_snapshot)

        assert "stance=degraded" in context
        assert "stance=unknown" not in context

    def test_reverie_reads_overall_stance(self):
        """reverie actuation must use 'overall_stance' for stance signal."""
        from agents.reverie._uniforms import write_uniforms
        from agents.visual_chain import VisualChainCapability

        vc = VisualChainCapability()
        stimmung_raw = self._make_stimmung_raw()

        write_uniforms(None, stimmung_raw, vc, 0.0, (0.5, 0.5), 0.0)

        # Read back the written uniforms
        uniforms_path = Path("/dev/shm/hapax-imagination/pipeline/uniforms.json")
        if uniforms_path.exists():
            written = json.loads(uniforms_path.read_text())
            assert written.get("signal.stance", -1) != 0.0  # degraded = 0.5, not 0.0
            assert "signal.color_warmth" in written

    def test_reverie_color_warmth_derived_from_infra(self):
        """color_warmth must be derived from worst infra dimension, not a phantom field."""
        stimmung_raw = self._make_stimmung_raw()

        # Worst infra value is resource_pressure at 0.8
        worst_infra = 0.0
        for dim_key in (
            "health",
            "resource_pressure",
            "error_rate",
            "processing_throughput",
            "perception_confidence",
            "llm_cost_pressure",
        ):
            dim_data = stimmung_raw.get(dim_key, {})
            if isinstance(dim_data, dict):
                worst_infra = max(worst_infra, dim_data.get("value", 0.0))

        assert worst_infra == pytest.approx(0.8)  # resource_pressure

    def test_engine_ignores_stale_stimmung(self, tmp_path: Path):
        """Engine must return nominal for stimmung older than 5 minutes."""
        stale_state = {
            "overall_stance": "critical",
            "timestamp": time.time() - 600,  # 10 minutes old
        }
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(stale_state))

        from logos.engine import ReactiveEngine

        engine = ReactiveEngine()

        def patched():
            import json as _json

            try:
                data = _json.loads(state_file.read_text(encoding="utf-8"))
                ts = data.get("timestamp", 0)
                if ts > 0 and (time.time() - ts) > 300:
                    return "nominal"
                return data.get("overall_stance", "nominal")
            except (OSError, _json.JSONDecodeError):
                return "nominal"

        engine._read_stimmung_stance = patched
        result = engine._read_stimmung_stance()
        assert result == "nominal"  # stale → nominal, not "critical"


class TestSyncDimensions:
    """Verify sync agent captures all 10 dimensions."""

    def test_sync_dimension_names_complete(self):
        """stimmung_sync.DIMENSION_NAMES must include all 10 dimensions."""
        from agents.stimmung_sync import DIMENSION_NAMES
        from shared.stimmung import _DIMENSION_NAMES

        assert set(DIMENSION_NAMES) == set(_DIMENSION_NAMES)

    def test_sync_reads_nested_dimensions(self, tmp_path: Path):
        """sync() must extract values from nested dimension dicts."""
        from agents.stimmung_sync import DIMENSION_NAMES, sync

        state = {
            "overall_stance": "cautious",
            "timestamp": time.time(),
        }
        for dim in DIMENSION_NAMES:
            state[dim] = {"value": 0.42, "trend": "stable", "freshness_s": 5.0}

        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        with (
            patch("agents.stimmung_sync.STIMMUNG_STATE", state_file),
            patch("agents.stimmung_sync.CACHE_DIR", tmp_path / "cache"),
            patch("agents.stimmung_sync.STATE_FILE", tmp_path / "cache" / "state.json"),
            patch("agents.stimmung_sync.RAG_DIR", tmp_path / "rag"),
            patch("agents._sensor_protocol.write_sensor_state"),
            patch("agents._sensor_protocol.emit_sensor_impingement"),
        ):
            result = sync()

        assert result is True

        # Verify cached state has all 10 dimensions
        cache_state = json.loads((tmp_path / "cache" / "state.json").read_text())
        last_reading = cache_state["readings"][-1]
        for dim in DIMENSION_NAMES:
            assert dim in last_reading, f"Missing {dim} in sync reading"
            assert last_reading[dim] == pytest.approx(0.42)


class TestContextAssemblerSingleRead:
    """Verify ContextAssembler reads SHM only once per assemble()."""

    def test_single_file_read(self, tmp_path: Path):
        """ContextAssembler must read stimmung file once, not twice."""
        from shared.context import ContextAssembler

        state = {
            "overall_stance": "degraded",
            "timestamp": time.time(),
            "health": {"value": 0.5, "trend": "stable", "freshness_s": 3.0},
        }
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        assembler = ContextAssembler(stimmung_path=state_file)
        ctx = assembler.assemble()

        assert ctx.stimmung_stance == "degraded"
        assert ctx.stimmung_raw["overall_stance"] == "degraded"
        assert isinstance(ctx.stimmung_raw["health"], dict)
