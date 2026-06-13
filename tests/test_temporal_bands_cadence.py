"""Temporal-band producer path + cadence pins (round-2 adequacy audit).

The temporal-band write was moved off the 15s health-poll onto the perception/
state tick (adaptive, bounded [0.5, 5.0]s — see test_adaptive_cadence.py for the
bound). These exercise the real producer method (`_emit_temporal_bands`) that the
fast loop calls: its success path, its short-ring no-op, and the failure path
(a producer error must be swallowed so the loop never dies).
"""

from __future__ import annotations

from unittest import mock

import pytest

from agents.visual_layer_aggregator import aggregator as agg_mod
from agents.visual_layer_aggregator import constants as _c
from agents.visual_layer_aggregator.aggregator import VisualLayerAggregator


class _StopLoop(Exception):
    """Sentinel raised from a patched asyncio.sleep to exit the while-True loop."""


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


class TestStateTickLoopIntegration:
    """Integration: prove the bands actually RIDE the perception/state tick — the
    real _state_tick_loop must call _emit_temporal_bands each pass (a refactor
    dropping the call, or relocating it back to the slow poll, is caught here)."""

    async def test_state_tick_loop_emits_temporal_bands(self, monkeypatch):
        agg = VisualLayerAggregator()

        fake_state = mock.MagicMock()
        fake_state.display_state = "ambient"
        fake_state.signals = {}
        fake_state.voice_session = mock.MagicMock(active=False, state="off")

        monkeypatch.setattr(agg, "poll_perception", mock.MagicMock())
        monkeypatch.setattr(agg, "compute_and_write", mock.MagicMock(return_value=fake_state))
        monkeypatch.setattr(agg, "_tick_apperception", mock.MagicMock())
        monkeypatch.setattr(agg, "_adaptive_tick_interval", mock.MagicMock(return_value=3.0))
        monkeypatch.setattr(
            "agents.visual_layer_aggregator.apperception_bridges.write_cross_resonance",
            mock.MagicMock(),
        )
        emit_spy = mock.MagicMock(return_value=True)
        monkeypatch.setattr(agg, "_emit_temporal_bands", emit_spy)

        async def _stop(_seconds):
            raise _StopLoop  # exit after exactly one iteration

        monkeypatch.setattr(agg_mod.asyncio, "sleep", _stop)

        with pytest.raises(_StopLoop):
            await agg._state_tick_loop()
        emit_spy.assert_called_once()
