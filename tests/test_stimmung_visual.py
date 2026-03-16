"""Tests for stimmung visual layer integration — ambient modulation + zone."""

from __future__ import annotations

from agents.visual_layer_state import (
    _OPACITY_TARGETS,
    ZONE_LAYOUT,
    DisplayState,
    DisplayStateMachine,
    SignalCategory,
    SignalEntry,
    VisualLayerState,
)


def _signal(
    cat: SignalCategory = SignalCategory.SYSTEM_STATE,
    severity: float = 0.5,
    title: str = "test",
) -> SignalEntry:
    return SignalEntry(category=cat, severity=severity, title=title, source_id=f"test-{title}")


class TestSystemStateZone:
    def test_zone_layout_includes_system_state(self):
        assert SignalCategory.SYSTEM_STATE in ZONE_LAYOUT or "system_state" in ZONE_LAYOUT

    def test_zone_position(self):
        zone = ZONE_LAYOUT[SignalCategory.SYSTEM_STATE]
        assert zone.x == 0.01
        assert zone.y == 0.78
        assert zone.w == 0.21
        assert zone.h == 0.12

    def test_signal_category_has_system_state(self):
        assert SignalCategory.SYSTEM_STATE == "system_state"

    def test_opacity_targets_include_system_state(self):
        for state in (DisplayState.PERIPHERAL, DisplayState.INFORMATIONAL, DisplayState.ALERT):
            targets = _OPACITY_TARGETS[state]
            assert SignalCategory.SYSTEM_STATE in targets


class TestStimmungAmbientModulation:
    def test_nominal_no_modulation(self):
        sm = DisplayStateMachine()
        state = sm.tick([], stimmung_stance="nominal")
        # Nominal → no warmth added beyond baseline
        assert state.ambient_params.color_warmth == 0.0
        assert state.ambient_params.speed == 0.08

    def test_cautious_adds_warmth_and_speed(self):
        sm = DisplayStateMachine()
        state = sm.tick([], stimmung_stance="cautious")
        assert state.ambient_params.color_warmth == 0.15
        assert state.ambient_params.speed == 0.13  # 0.08 + 0.05

    def test_degraded_adds_more_warmth(self):
        sm = DisplayStateMachine()
        state = sm.tick([], stimmung_stance="degraded")
        assert state.ambient_params.color_warmth == 0.35
        assert state.ambient_params.speed == 0.18  # 0.08 + 0.1
        assert state.ambient_params.turbulence == 0.2  # 0.1 + 0.1

    def test_critical_adds_maximum_modulation(self):
        sm = DisplayStateMachine()
        state = sm.tick([], stimmung_stance="critical")
        assert state.ambient_params.color_warmth == 0.6
        assert state.ambient_params.speed == 0.28  # 0.08 + 0.2
        assert state.ambient_params.turbulence == 0.3  # 0.1 + 0.2

    def test_stimmung_stacks_with_severity(self):
        """Stimmung modulation adds on top of severity-based warmth."""
        sm = DisplayStateMachine()
        sig = _signal(cat=SignalCategory.HEALTH_INFRA, severity=0.3)
        state = sm.tick([sig], stimmung_stance="cautious")
        # severity warmth (0.3) + stimmung warmth (0.15) = 0.45
        assert state.ambient_params.color_warmth == 0.45

    def test_warmth_capped_at_one(self):
        """Even with high severity + critical stance, warmth doesn't exceed 1.0."""
        sm = DisplayStateMachine()
        sig = _signal(cat=SignalCategory.HEALTH_INFRA, severity=0.9)
        state = sm.tick([sig], stimmung_stance="critical")
        assert state.ambient_params.color_warmth <= 1.0

    def test_visual_layer_state_has_stimmung_stance(self):
        state = VisualLayerState()
        assert state.stimmung_stance == "nominal"

    def test_system_state_signals_categorized(self):
        sm = DisplayStateMachine()
        sig = _signal(cat=SignalCategory.SYSTEM_STATE, severity=0.5)
        state = sm.tick([sig])
        assert SignalCategory.SYSTEM_STATE in state.signals or "system_state" in state.signals
