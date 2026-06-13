"""Temporal-band cadence + state-tick path pins (round-2 adequacy audit).

write_temporal_bands was moved off the 15s health-poll onto the perception/
state tick (adaptive, bounded [0.5, 5.0]s — see test_adaptive_cadence.py for the
bound). These pin the producer's state-tick path and error path, and that the
call lives on the fast loop, not the slow poll.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

from agents.visual_layer_aggregator import constants as _c
from agents.visual_layer_aggregator.aggregator import VisualLayerAggregator
from agents.visual_layer_aggregator.stimmung_methods import write_temporal_bands


class TestWriteTemporalBands:
    def test_short_ring_is_noop(self, tmp_path, monkeypatch):
        """Fewer than 2 ring samples → nothing written (early return)."""
        monkeypatch.setattr(_c, "TEMPORAL_DIR", tmp_path)
        monkeypatch.setattr(_c, "TEMPORAL_FILE", tmp_path / "bands.json")
        agg = VisualLayerAggregator()  # fresh, empty ring
        write_temporal_bands(agg)
        assert not (tmp_path / "bands.json").exists()

    def test_swallows_formatter_error(self, tmp_path, monkeypatch):
        """A formatter failure must not propagate out of the fast loop."""
        monkeypatch.setattr(_c, "TEMPORAL_DIR", tmp_path)
        monkeypatch.setattr(_c, "TEMPORAL_FILE", tmp_path / "bands.json")
        agg = VisualLayerAggregator()
        agg._local_ring.push({"timestamp": 1.0})
        agg._local_ring.push({"timestamp": 2.0})
        with mock.patch.object(agg._temporal_formatter, "format", side_effect=RuntimeError("boom")):
            write_temporal_bands(agg)  # must not raise
        assert not (tmp_path / "bands.json").exists()


class TestTemporalBandsWiring:
    """Pin that the producer rides the fast state tick, not the slow health poll."""

    def test_call_is_inside_state_tick_loop_only(self):
        src = (Path("agents") / "visual_layer_aggregator" / "aggregator.py").read_text(
            encoding="utf-8"
        )
        # exactly one ACTIVE call (self.) — not counting comments
        active_calls = [
            ln
            for ln in src.splitlines()
            if "write_temporal_bands(self)" in ln and not ln.strip().startswith("#")
        ]
        assert len(active_calls) == 1, f"expected 1 active call, found {len(active_calls)}"

        state_tick = src.index("async def _state_tick_loop")
        api_poll = src.index("async def _api_poll_loop")
        call_pos = (
            src.index("write_temporal_bands(self)\n")
            if "write_temporal_bands(self)\n" in src
            else re.search(r"write_temporal_bands\(self\)", src).start()
        )
        # the active call sits between _state_tick_loop and _api_poll_loop
        assert state_tick < call_pos < api_poll
