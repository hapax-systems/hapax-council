"""Temporal-band producer path + cadence pins (round-2 adequacy audit).

The temporal-band write was moved off the 15s health-poll onto the perception/
state tick (adaptive, bounded [0.5, 5.0]s — see test_adaptive_cadence.py for the
bound). These exercise the real producer method (`_emit_temporal_bands`) that the
fast loop calls: its success path, its short-ring no-op, and the failure path
(a producer error must be swallowed so the loop never dies).
"""

from __future__ import annotations

from unittest import mock

from agents.visual_layer_aggregator import constants as _c
from agents.visual_layer_aggregator.aggregator import VisualLayerAggregator


class TestEmitTemporalBands:
    """`_emit_temporal_bands` is the method the fast loop calls each tick."""

    def test_returns_true_and_calls_producer(self):
        agg = VisualLayerAggregator()
        with mock.patch(
            "agents.visual_layer_aggregator.stimmung_methods.write_temporal_bands"
        ) as w:
            assert agg._emit_temporal_bands() is True
        w.assert_called_once_with(agg)

    def test_swallows_producer_error(self):
        """A producer failure must NOT escape the fast state-tick loop."""
        agg = VisualLayerAggregator()
        with mock.patch(
            "agents.visual_layer_aggregator.stimmung_methods.write_temporal_bands",
            side_effect=RuntimeError("boom"),
        ):
            # must not raise; reports failure
            assert agg._emit_temporal_bands() is False

    def test_short_ring_writes_nothing(self, tmp_path, monkeypatch):
        """End-to-end through the real producer: <2 ring samples → no file."""
        monkeypatch.setattr(_c, "TEMPORAL_DIR", tmp_path)
        monkeypatch.setattr(_c, "TEMPORAL_FILE", tmp_path / "bands.json")
        agg = VisualLayerAggregator()  # fresh, empty ring
        assert agg._emit_temporal_bands() is True  # producer ran (early-returned)
        assert not (tmp_path / "bands.json").exists()
