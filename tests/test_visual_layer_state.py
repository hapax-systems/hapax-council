"""Tests for visual layer data models and display state machine.

Covers: state transitions, escalation/de-escalation hysteresis, signal
categorization, attention budget, opacity computation, ambient parameters,
and edge cases.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.visual_layer_state import (
    MAX_SIGNALS_PER_ZONE,
    MAX_TOTAL_VISIBLE_SIGNALS,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    ZONE_LAYOUT,
    AmbientParams,
    DisplayState,
    DisplayStateMachine,
    SignalCategory,
    SignalEntry,
    VisualLayerState,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _signal(
    cat: SignalCategory = SignalCategory.HEALTH_INFRA,
    severity: float = 0.5,
    title: str = "test",
) -> SignalEntry:
    return SignalEntry(category=cat, severity=severity, title=title, source_id=f"test-{title}")


def _signals(n: int, severity: float = 0.5) -> list[SignalEntry]:
    """Generate n signals spread across categories."""
    cats = list(SignalCategory)
    return [
        _signal(cat=cats[i % len(cats)], severity=severity, title=f"sig-{i}") for i in range(n)
    ]


# ── Model Tests ──────────────────────────────────────────────────────────────


class TestModels:
    def test_display_state_values(self):
        assert len(DisplayState) == 5
        assert DisplayState.AMBIENT == "ambient"
        assert DisplayState.PERFORMATIVE == "performative"

    def test_signal_category_values(self):
        assert len(SignalCategory) == 6

    def test_zone_layout_covers_all_categories(self):
        for cat in SignalCategory:
            assert cat.value in ZONE_LAYOUT or cat in ZONE_LAYOUT

    def test_zone_specs_in_bounds(self):
        for zone in ZONE_LAYOUT.values():
            assert 0 <= zone.x <= 1
            assert 0 <= zone.y <= 1
            assert 0 < zone.w <= 1
            assert 0 < zone.h <= 1
            assert zone.x + zone.w <= 1.01  # Allow tiny rounding
            assert zone.y + zone.h <= 1.01

    def test_visual_layer_state_defaults(self):
        s = VisualLayerState()
        assert s.display_state == DisplayState.AMBIENT
        assert s.zone_opacities == {}
        assert s.signals == {}

    def test_signal_entry_frozen(self):
        s = _signal()
        assert s.category == SignalCategory.HEALTH_INFRA
        assert s.severity == 0.5

    def test_ambient_params_defaults(self):
        p = AmbientParams()
        assert 0 < p.speed < 1
        assert 0 < p.turbulence < 1
        assert p.color_warmth == 0.0


# ── State Transitions ────────────────────────────────────────────────────────


class TestStateTransitions:
    def test_starts_ambient(self):
        sm = DisplayStateMachine()
        assert sm.state == DisplayState.AMBIENT

    def test_no_signals_stays_ambient(self):
        sm = DisplayStateMachine()
        result = sm.tick(signals=[], now=0)
        assert result.display_state == DisplayState.AMBIENT

    def test_one_signal_goes_peripheral(self):
        sm = DisplayStateMachine()
        result = sm.tick(signals=[_signal(severity=0.3)], now=0)
        assert result.display_state == DisplayState.PERIPHERAL

    def test_three_signals_goes_informational(self):
        sm = DisplayStateMachine()
        result = sm.tick(signals=_signals(3, severity=0.3), now=0)
        assert result.display_state == DisplayState.INFORMATIONAL

    def test_medium_severity_goes_informational(self):
        sm = DisplayStateMachine()
        result = sm.tick(signals=[_signal(severity=SEVERITY_MEDIUM)], now=0)
        assert result.display_state == DisplayState.INFORMATIONAL

    def test_high_severity_goes_alert(self):
        sm = DisplayStateMachine()
        result = sm.tick(signals=[_signal(severity=SEVERITY_HIGH)], now=0)
        assert result.display_state == DisplayState.ALERT

    def test_critical_severity_goes_alert(self):
        sm = DisplayStateMachine()
        result = sm.tick(signals=[_signal(severity=SEVERITY_CRITICAL)], now=0)
        assert result.display_state == DisplayState.ALERT

    def test_performative_requires_production_and_flow_and_audio(self):
        sm = DisplayStateMachine()
        # All three needed
        result = sm.tick(
            signals=[],
            production_active=True,
            audio_energy=0.1,
            flow_score=0.7,
            now=0,
        )
        assert result.display_state == DisplayState.PERFORMATIVE

    def test_performative_missing_flow(self):
        sm = DisplayStateMachine()
        result = sm.tick(
            signals=[], production_active=True, audio_energy=0.1, flow_score=0.2, now=0
        )
        assert result.display_state != DisplayState.PERFORMATIVE

    def test_performative_missing_audio(self):
        sm = DisplayStateMachine()
        result = sm.tick(
            signals=[], production_active=True, audio_energy=0.0, flow_score=0.7, now=0
        )
        assert result.display_state != DisplayState.PERFORMATIVE

    def test_performative_missing_production(self):
        sm = DisplayStateMachine()
        result = sm.tick(
            signals=[], production_active=False, audio_energy=0.1, flow_score=0.7, now=0
        )
        assert result.display_state != DisplayState.PERFORMATIVE


# ── Deep Flow Suppression ────────────────────────────────────────────────────


class TestFlowSuppression:
    def test_deep_flow_suppresses_to_ambient(self):
        """Non-critical signals during deep flow → AMBIENT (protect the flow)."""
        sm = DisplayStateMachine()
        result = sm.tick(signals=_signals(5, severity=0.5), flow_score=0.7, now=0)
        assert result.display_state == DisplayState.AMBIENT

    def test_critical_survives_deep_flow(self):
        """Critical signal breaks through even during deep flow."""
        sm = DisplayStateMachine()
        result = sm.tick(
            signals=[_signal(severity=SEVERITY_CRITICAL)], flow_score=0.7, now=0
        )
        assert result.display_state == DisplayState.ALERT

    def test_high_severity_suppressed_during_flow(self):
        """High (but not critical) severity is suppressed during flow."""
        sm = DisplayStateMachine()
        result = sm.tick(
            signals=[_signal(severity=SEVERITY_HIGH - 0.01)], flow_score=0.7, now=0
        )
        assert result.display_state == DisplayState.AMBIENT


# ── Hysteresis ───────────────────────────────────────────────────────────────


class TestHysteresis:
    def test_escalation_is_immediate(self):
        sm = DisplayStateMachine()
        sm.tick(signals=[], now=0)  # AMBIENT
        result = sm.tick(signals=[_signal(severity=SEVERITY_CRITICAL)], now=0.1)
        assert result.display_state == DisplayState.ALERT

    def test_deescalation_requires_cooldown(self):
        sm = DisplayStateMachine()
        # Escalate to ALERT
        sm.tick(signals=[_signal(severity=SEVERITY_CRITICAL)], now=0)
        assert sm.state == DisplayState.ALERT
        # Immediately remove signals — should NOT deescalate yet
        result = sm.tick(signals=[], now=1.0)
        assert result.display_state == DisplayState.ALERT  # Still alert (cooldown ~5s)

    def test_deescalation_after_cooldown(self):
        sm = DisplayStateMachine()
        # Escalate to ALERT
        sm.tick(signals=[_signal(severity=SEVERITY_CRITICAL)], now=0)
        # Wait longer than any cooldown
        result = sm.tick(signals=[], now=20.0)
        assert result.display_state == DisplayState.AMBIENT

    def test_no_oscillation_on_brief_spike(self):
        """Brief spike followed by calm should escalate then slowly return."""
        sm = DisplayStateMachine()
        sm.tick(signals=[], now=0)  # AMBIENT
        sm.tick(signals=[_signal(severity=SEVERITY_CRITICAL)], now=1)  # → ALERT
        assert sm.state == DisplayState.ALERT
        # Signal disappears — but cooldown keeps us in ALERT
        sm.tick(signals=[], now=2)
        assert sm.state == DisplayState.ALERT
        sm.tick(signals=[], now=4)
        assert sm.state == DisplayState.ALERT
        # After cooldown, deescalate
        sm.tick(signals=[], now=20)
        assert sm.state == DisplayState.AMBIENT


# ── Signal Categorization ────────────────────────────────────────────────────


class TestSignalCategorization:
    def test_signals_grouped_by_category(self):
        sm = DisplayStateMachine()
        signals = [
            _signal(cat=SignalCategory.HEALTH_INFRA, severity=0.8, title="health"),
            _signal(cat=SignalCategory.WORK_TASKS, severity=0.5, title="nudge"),
            _signal(cat=SignalCategory.GOVERNANCE, severity=0.3, title="consent"),
        ]
        result = sm.tick(signals=signals, now=0)
        assert SignalCategory.HEALTH_INFRA in result.signals
        assert SignalCategory.WORK_TASKS in result.signals

    def test_max_signals_per_zone(self):
        sm = DisplayStateMachine()
        signals = [
            _signal(cat=SignalCategory.WORK_TASKS, severity=0.5, title=f"n-{i}")
            for i in range(10)
        ]
        result = sm.tick(signals=signals, now=0)
        work = result.signals.get(SignalCategory.WORK_TASKS, [])
        assert len(work) <= MAX_SIGNALS_PER_ZONE

    def test_total_signal_budget(self):
        sm = DisplayStateMachine()
        # Many signals across all categories
        signals = _signals(20, severity=0.3)
        result = sm.tick(signals=signals, now=0)
        total = sum(len(entries) for entries in result.signals.values())
        assert total <= MAX_TOTAL_VISIBLE_SIGNALS

    def test_highest_severity_signals_kept(self):
        sm = DisplayStateMachine()
        signals = [
            _signal(cat=SignalCategory.HEALTH_INFRA, severity=0.9, title="critical"),
            _signal(cat=SignalCategory.HEALTH_INFRA, severity=0.1, title="minor"),
        ]
        result = sm.tick(signals=signals, now=0)
        health = result.signals.get(SignalCategory.HEALTH_INFRA, [])
        if health:
            assert health[0].title == "critical"


# ── Opacity Computation ──────────────────────────────────────────────────────


class TestOpacity:
    def test_ambient_all_zero(self):
        sm = DisplayStateMachine()
        result = sm.tick(signals=[], now=0)
        for opacity in result.zone_opacities.values():
            assert opacity == 0.0

    def test_alert_has_high_opacity_zone(self):
        sm = DisplayStateMachine()
        result = sm.tick(signals=[_signal(severity=SEVERITY_CRITICAL)], now=0)
        assert max(result.zone_opacities.values()) >= 0.9

    def test_empty_zones_zeroed(self):
        """Zones with no signals get opacity 0 even in INFORMATIONAL state."""
        sm = DisplayStateMachine()
        signals = [_signal(cat=SignalCategory.HEALTH_INFRA, severity=0.5)]
        result = sm.tick(signals=signals, now=0)
        # HEALTH_INFRA should have opacity, but GOVERNANCE (no signals) should be 0
        assert result.zone_opacities.get(SignalCategory.GOVERNANCE, 0.0) == 0.0

    def test_performative_all_zero(self):
        sm = DisplayStateMachine()
        result = sm.tick(
            signals=[],
            production_active=True,
            audio_energy=0.1,
            flow_score=0.7,
            now=0,
        )
        for opacity in result.zone_opacities.values():
            assert opacity == 0.0


# ── Ambient Parameters ───────────────────────────────────────────────────────


class TestAmbientParams:
    def test_healthy_system_cool_slow(self):
        sm = DisplayStateMachine()
        result = sm.tick(signals=[], now=0)
        assert result.ambient_params.color_warmth == 0.0
        assert result.ambient_params.speed < 0.15

    def test_severity_increases_warmth(self):
        sm = DisplayStateMachine()
        result = sm.tick(signals=[_signal(severity=0.8)], now=0)
        assert result.ambient_params.color_warmth > 0.5

    def test_flow_reduces_speed(self):
        sm = DisplayStateMachine()
        no_flow = sm.tick(signals=[], flow_score=0.0, now=0)
        sm2 = DisplayStateMachine()
        with_flow = sm2.tick(signals=[], flow_score=0.8, now=0)
        assert with_flow.ambient_params.speed <= no_flow.ambient_params.speed


# ── Invariants (Hypothesis) ──────────────────────────────────────────────────


class TestInvariants:
    @given(
        severity=st.floats(min_value=0.0, max_value=1.0),
        flow=st.floats(min_value=0.0, max_value=1.0),
        n_signals=st.integers(min_value=0, max_value=20),
        production=st.booleans(),
        audio=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=200)
    def test_state_always_valid(
        self, severity: float, flow: float, n_signals: int, production: bool, audio: float
    ):
        sm = DisplayStateMachine()
        signals = [_signal(severity=severity, title=f"s{i}") for i in range(n_signals)]
        result = sm.tick(
            signals=signals,
            flow_score=flow,
            production_active=production,
            audio_energy=audio,
            now=0,
        )
        assert result.display_state in DisplayState
        assert all(0.0 <= v <= 1.0 for v in result.zone_opacities.values())
        total = sum(len(e) for e in result.signals.values())
        assert total <= MAX_TOTAL_VISIBLE_SIGNALS

    @given(
        severity=st.floats(min_value=0.0, max_value=1.0),
        flow=st.floats(min_value=0.0, max_value=1.0),
        audio=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=100)
    def test_ambient_params_bounded(self, severity: float, flow: float, audio: float):
        sm = DisplayStateMachine()
        result = sm.tick(
            signals=[_signal(severity=severity)] if severity > 0 else [],
            flow_score=flow,
            audio_energy=audio,
            now=0,
        )
        p = result.ambient_params
        assert 0 <= p.speed <= 1
        assert 0 <= p.turbulence <= 1
        assert 0 <= p.color_warmth <= 1
        assert 0 <= p.brightness <= 1

    @given(flow=st.floats(min_value=0.6, max_value=1.0))
    @settings(max_examples=50)
    def test_deep_flow_only_critical_breaks_through(self, flow: float):
        """During deep flow, only CRITICAL severity reaches ALERT."""
        sm = DisplayStateMachine()
        # Sub-critical during flow
        result = sm.tick(
            signals=[_signal(severity=SEVERITY_HIGH - 0.01)],
            flow_score=flow,
            now=0,
        )
        assert result.display_state == DisplayState.AMBIENT
