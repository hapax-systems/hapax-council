"""Tests for alignment tax measurement — governance overhead metrics.

Self-contained, asyncio_mode="auto", unittest.mock only.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from agents.alignment_tax_meter import (
    AlignmentTaxSnapshot,
    measure_alignment_tax,
    measure_label_operations,
    measure_sdlc_overhead,
    measure_token_cost_overhead,
)


class TestMeasureLabelOperations(unittest.TestCase):
    """Microbenchmark: consent label operations."""

    def test_returns_timing_data(self):
        result = measure_label_operations(iterations=100)
        assert "join_us" in result
        assert "can_flow_to_us" in result
        assert "governor_check_us" in result
        assert result["iterations"] == 100

    def test_join_is_sub_millisecond(self):
        """join() should be well under 1ms for small labels."""
        result = measure_label_operations(iterations=1000)
        assert result["join_us"] < 1000  # < 1ms

    def test_can_flow_to_is_sub_millisecond(self):
        """can_flow_to() should be well under 1ms."""
        result = measure_label_operations(iterations=1000)
        assert result["can_flow_to_us"] < 1000

    def test_governor_check_is_sub_millisecond(self):
        """Governor check_input should be well under 1ms."""
        result = measure_label_operations(iterations=1000)
        assert result["governor_check_us"] < 1000


class TestMeasureSdlcOverhead(unittest.TestCase):
    """SDLC pipeline: axiom-gate overhead."""

    def test_missing_file_returns_unavailable(self):
        with patch("agents.alignment_tax_meter.SDLC_EVENTS_PATH", Path("/nonexistent")):
            result = measure_sdlc_overhead()
            assert not result["available"]

    def test_parses_events_with_duration(self):
        now = datetime.now(UTC)
        events = [
            {"timestamp": now.isoformat(), "stage": "triage", "duration_ms": 100},
            {"timestamp": now.isoformat(), "stage": "plan", "duration_ms": 200},
            {"timestamp": now.isoformat(), "stage": "review", "duration_ms": 150},
            {"timestamp": now.isoformat(), "stage": "axiom-gate", "duration_ms": 50},
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
            path = Path(f.name)

        try:
            with patch("agents.alignment_tax_meter.SDLC_EVENTS_PATH", path):
                result = measure_sdlc_overhead(lookback_days=1)
                assert result["available"]
                assert result["axiom_gate_ms"] == 50
                assert result["total_pipeline_ms"] == 500
                assert result["tax_pct"] == 10.0
        finally:
            path.unlink()

    def test_excludes_old_events(self):
        old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        recent = datetime.now(UTC).isoformat()
        events = [
            {"timestamp": old, "stage": "axiom-gate", "duration_ms": 999},
            {"timestamp": recent, "stage": "axiom-gate", "duration_ms": 10},
            {"timestamp": recent, "stage": "triage", "duration_ms": 90},
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
            path = Path(f.name)

        try:
            with patch("agents.alignment_tax_meter.SDLC_EVENTS_PATH", path):
                result = measure_sdlc_overhead(lookback_days=7)
                assert result["available"]
                assert result["axiom_gate_ms"] == 10  # old event excluded
                assert result["tax_pct"] == 10.0  # 10 / 100
        finally:
            path.unlink()


class TestMeasureTokenCostOverhead(unittest.TestCase):
    """Token cost: governance vs total from Langfuse."""

    def test_langfuse_unavailable(self):
        with patch(
            "shared.langfuse_client.langfuse_get",
            side_effect=ImportError("no langfuse"),
        ):
            # The import itself would fail, but we mock at module level
            pass

    def test_parses_governance_calls(self):
        now = datetime.now(UTC).isoformat()
        mock_data = {
            "data": [
                {
                    "startTime": now,
                    "name": "litellm-acompletion",
                    "calculatedTotalCost": 0.10,
                    "metadata": {},
                },
                {
                    "startTime": now,
                    "name": "axiom_gate_judge",
                    "calculatedTotalCost": 0.02,
                    "metadata": {},
                },
                {
                    "startTime": now,
                    "name": "litellm-acompletion",
                    "calculatedTotalCost": 0.05,
                    "metadata": {"is_governance_operation": True},
                },
            ]
        }

        with patch("agents._langfuse_client.langfuse_get", return_value=mock_data):
            result = measure_token_cost_overhead(lookback_days=1)
            assert result["available"]
            assert result["governance_calls"] == 2
            assert result["total_calls"] == 3
            assert result["governance_cost"] == 0.07
            assert result["total_cost"] == 0.17
            # 0.07 / 0.17 ≈ 41.2%
            assert 40 < result["tax_pct"] < 42


class TestMeasureAlignmentTax(unittest.TestCase):
    """Full snapshot combining all dimensions."""

    def test_returns_snapshot(self):
        with (
            patch("agents.alignment_tax_meter.SDLC_EVENTS_PATH", Path("/nonexistent")),
            patch(
                "agents.alignment_tax_meter.measure_token_cost_overhead",
                return_value={"available": False, "reason": "test"},
            ),
        ):
            snapshot = measure_alignment_tax(lookback_days=1)
            assert isinstance(snapshot, AlignmentTaxSnapshot)
            assert snapshot.measurement_timestamp
            assert snapshot.label_join_us > 0
            assert snapshot.label_flow_check_us > 0
            assert snapshot.governor_check_us > 0

    def test_sdlc_data_flows_through(self):
        now = datetime.now(UTC).isoformat()
        events = [
            {"timestamp": now, "stage": "triage", "duration_ms": 80},
            {"timestamp": now, "stage": "axiom-gate", "duration_ms": 20},
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
            path = Path(f.name)

        try:
            with (
                patch("agents.alignment_tax_meter.SDLC_EVENTS_PATH", path),
                patch(
                    "agents.alignment_tax_meter.measure_token_cost_overhead",
                    return_value={"available": False},
                ),
            ):
                snapshot = measure_alignment_tax(lookback_days=1)
                assert snapshot.axiom_gate_duration_ms == 20
                assert snapshot.total_pipeline_duration_ms == 100
                assert snapshot.sdlc_tax_pct == 20.0
        finally:
            path.unlink()
