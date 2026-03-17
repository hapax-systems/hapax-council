"""Tests for decoupled fast/slow loop architecture (Phase 2) and staleness (Phase 3)."""

from __future__ import annotations

from agents.visual_layer_aggregator import (
    HEALTH_POLL_S,
    SLOW_POLL_S,
    STATE_TICK_BASE_S,
    VisualLayerAggregator,
)
from agents.visual_layer_state import (
    DisplayState,
    SignalStaleness,
    TemporalContext,
)


class TestDecoupledArchitecture:
    def test_state_tick_base_faster_than_old(self):
        """State tick is now 3s, not 15s."""
        assert STATE_TICK_BASE_S <= 3.0

    def test_health_poll_interval(self):
        assert HEALTH_POLL_S == 15.0

    def test_slow_poll_interval(self):
        assert SLOW_POLL_S == 60.0


class TestStaleness:
    def test_initial_staleness_zero(self):
        agg = VisualLayerAggregator()
        s = agg._compute_staleness()
        assert isinstance(s, SignalStaleness)
        # All zero before any polls
        assert s.perception_s == 0.0
        assert s.health_s == 0.0

    def test_staleness_after_perception(self):
        agg = VisualLayerAggregator()
        import time

        agg._ts_perception = time.monotonic() - 5.0
        s = agg._compute_staleness()
        assert 4.5 <= s.perception_s <= 6.0

    def test_staleness_in_state_output(self):
        agg = VisualLayerAggregator()
        state = agg.compute_and_write()
        assert hasattr(state, "signal_staleness")
        assert isinstance(state.signal_staleness, SignalStaleness)


class TestTemporalContextOutput:
    def test_temporal_context_in_state(self):
        agg = VisualLayerAggregator()
        state = agg.compute_and_write()
        assert hasattr(state, "temporal_context")
        assert isinstance(state.temporal_context, TemporalContext)

    def test_temporal_context_defaults(self):
        tc = TemporalContext()
        assert tc.trend_flow == 0.0
        assert tc.trend_audio == 0.0
        assert tc.trend_hr == 0.0
        assert tc.ring_depth == 0


class TestComputeAndWriteBackwardCompat:
    """Ensure existing compute_and_write behavior is preserved."""

    def test_produces_valid_state(self):
        agg = VisualLayerAggregator()
        state = agg.compute_and_write()
        assert state.display_state in DisplayState
        assert isinstance(state.zone_opacities, dict)

    def test_ambient_text_still_works(self):
        agg = VisualLayerAggregator()
        agg._ambient_text = "test fact"
        state = agg.compute_and_write()
        assert state.ambient_text == "test fact"

    def test_activity_label_still_inferred(self):
        agg = VisualLayerAggregator()
        state = agg.compute_and_write()
        assert isinstance(state.activity_label, str)
