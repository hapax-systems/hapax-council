"""Tests for adaptive tick cadence (Phase 5)."""

from __future__ import annotations

from agents.visual_layer_aggregator import STATE_TICK_BASE_S, VisualLayerAggregator
from agents.visual_layer_state import (
    TemporalContext,
    VisualLayerState,
    VoiceSessionState,
)
from shared.stimmung import DimensionReading, Stance, SystemStimmung


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
        agg._prev_display_state = "peripheral"
        agg._production_active = True  # avoid sustained-ambient path
        state = _make_state(display_state="peripheral", display_density="presenting")
        interval = agg._adaptive_tick_interval(state)
        assert interval >= 4.0

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


class TestStimmungTickModulation:
    """WS2: Stimmung-driven tick rate modulation."""

    def test_critical_stance_maxes_out(self):
        """Critical stance → 5.0s (maximum conservation)."""
        agg = VisualLayerAggregator()
        agg._prev_display_state = "ambient"
        agg._stimmung = SystemStimmung(overall_stance=Stance.CRITICAL)
        state = _make_state()
        interval = agg._adaptive_tick_interval(state)
        assert interval == 5.0

    def test_degraded_stance_slows_down(self):
        """Degraded stance → at least 4.0s."""
        agg = VisualLayerAggregator()
        agg._prev_display_state = "peripheral"
        agg._production_active = True
        agg._stimmung = SystemStimmung(overall_stance=Stance.DEGRADED)
        state = _make_state(display_state="peripheral")
        interval = agg._adaptive_tick_interval(state)
        assert interval >= 4.0

    def test_high_resource_pressure_slows(self):
        """High VRAM pressure → at least 4.0s even when nominal."""
        agg = VisualLayerAggregator()
        agg._prev_display_state = "ambient"
        agg._stimmung = SystemStimmung(
            overall_stance=Stance.NOMINAL,
            resource_pressure=DimensionReading(value=0.85, trend="stable"),
        )
        state = _make_state()
        interval = agg._adaptive_tick_interval(state)
        assert interval >= 4.0

    def test_error_spike_speeds_up(self):
        """Rising error rate → speed up to track recovery."""
        agg = VisualLayerAggregator()
        agg._prev_display_state = "peripheral"
        agg._production_active = True
        agg._stimmung = SystemStimmung(
            overall_stance=Stance.CAUTIOUS,
            error_rate=DimensionReading(value=0.6, trend="rising"),
        )
        state = _make_state(display_state="peripheral")
        interval = agg._adaptive_tick_interval(state)
        assert interval <= 1.5

    def test_llm_cost_pressure_slows(self):
        """High LLM cost → slow down to reduce downstream calls."""
        agg = VisualLayerAggregator()
        agg._prev_display_state = "peripheral"
        agg._production_active = True
        agg._stimmung = SystemStimmung(
            overall_stance=Stance.CAUTIOUS,
            llm_cost_pressure=DimensionReading(value=0.8, trend="rising"),
        )
        state = _make_state(display_state="peripheral")
        interval = agg._adaptive_tick_interval(state)
        assert interval >= 3.5

    def test_state_transition_overrides_stimmung(self):
        """State transition (0.5s) takes priority over degraded stance."""
        agg = VisualLayerAggregator()
        agg._prev_display_state = "ambient"
        agg._stimmung = SystemStimmung(overall_stance=Stance.DEGRADED)
        state = _make_state(display_state="peripheral")
        interval = agg._adaptive_tick_interval(state)
        assert interval == 0.5

    def test_voice_overrides_stimmung(self):
        """Voice active (1.0s) takes priority over degraded stance."""
        agg = VisualLayerAggregator()
        agg._prev_display_state = "ambient"
        agg._voice_session = VoiceSessionState(active=True, state="listening")
        agg._stimmung = SystemStimmung(overall_stance=Stance.DEGRADED)
        state = _make_state()
        interval = agg._adaptive_tick_interval(state)
        assert interval == 1.0

    def test_no_stimmung_uses_base(self):
        """Without stimmung data, falls through to existing logic."""
        agg = VisualLayerAggregator()
        agg._prev_display_state = "peripheral"
        agg._production_active = True
        agg._stimmung = None
        state = _make_state(display_state="peripheral")
        interval = agg._adaptive_tick_interval(state)
        assert interval == STATE_TICK_BASE_S
