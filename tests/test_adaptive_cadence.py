"""Tests for adaptive tick cadence (Phase 5)."""

from __future__ import annotations

from agents.visual_layer_aggregator import STATE_TICK_BASE_S, VisualLayerAggregator
from agents.visual_layer_state import (
    TemporalContext,
    VisualLayerState,
    VoiceSessionState,
)


def _make_state(**overrides) -> VisualLayerState:
    defaults = {
        "display_state": "ambient",
        "display_density": "ambient",
        "temporal_context": TemporalContext(),
    }
    defaults.update(overrides)
    return VisualLayerState(**defaults)


class TestAdaptiveCadence:
    def test_base_interval(self):
        assert STATE_TICK_BASE_S == 3.0

    def test_state_transition_speeds_up(self):
        agg = VisualLayerAggregator()
        agg._prev_display_state = "ambient"
        state = _make_state(display_state="peripheral")
        interval = agg._adaptive_tick_interval(state)
        assert interval == 0.5

    def test_voice_active_responsive(self):
        agg = VisualLayerAggregator()
        agg._voice_session = VoiceSessionState(active=True, state="listening")
        state = _make_state()
        interval = agg._adaptive_tick_interval(state)
        assert interval == 1.0

    def test_trend_changing_tracks_closely(self):
        agg = VisualLayerAggregator()
        state = _make_state(temporal_context=TemporalContext(trend_flow=0.02))
        interval = agg._adaptive_tick_interval(state)
        assert interval == 1.5

    def test_sustained_ambient_slows_down(self):
        agg = VisualLayerAggregator()
        agg._prev_display_state = "ambient"
        agg._production_active = False
        state = _make_state(display_state="ambient")
        interval = agg._adaptive_tick_interval(state)
        assert interval == 5.0

    def test_presenting_mode_slow(self):
        agg = VisualLayerAggregator()
        agg._prev_display_state = "ambient"
        state = _make_state(display_state="ambient", display_density="presenting")
        interval = agg._adaptive_tick_interval(state)
        assert interval == 4.0

    def test_stale_perception_slows_down(self):
        agg = VisualLayerAggregator()
        agg._prev_display_state = "ambient"
        state = _make_state(
            display_state="ambient",
            temporal_context=TemporalContext(perception_age_s=15.0),
        )
        interval = agg._adaptive_tick_interval(state)
        assert interval == 5.0

    def test_always_bounded(self):
        agg = VisualLayerAggregator()
        # Test various states
        for ds in ["ambient", "peripheral", "informational", "alert"]:
            agg._prev_display_state = ds
            state = _make_state(display_state=ds)
            interval = agg._adaptive_tick_interval(state)
            assert 0.5 <= interval <= 5.0
