"""Tests for shared/flow_state.py — flow state machine."""

from __future__ import annotations

import time

from shared.flow_state import (
    WARMING_THRESHOLD,
    FlowSignals,
    FlowState,
    FlowStateMachine,
)


class TestFlowStateMachine:
    def test_initial_state_is_idle(self):
        fsm = FlowStateMachine()
        assert fsm.state == FlowState.IDLE

    def test_idle_to_warming(self):
        fsm = FlowStateMachine(hysteresis_s=0)
        signals = FlowSignals(production_activity="production", flow_state_score=0.0)
        score = fsm.compute_composite_score(signals)
        assert score >= WARMING_THRESHOLD

        fsm.update(signals)
        assert fsm.state in (FlowState.WARMING_UP, FlowState.ACTIVE)

    def test_idle_to_active(self):
        fsm = FlowStateMachine(hysteresis_s=0)
        signals = FlowSignals(
            production_activity="production",
            flow_state_score=0.5,
            audio_energy_rms=0.05,
        )
        fsm.update(signals)
        assert fsm.state == FlowState.ACTIVE

    def test_active_to_flow(self):
        fsm = FlowStateMachine(hysteresis_s=0)
        # First get to active
        signals = FlowSignals(
            production_activity="production",
            flow_state_score=0.5,
            audio_energy_rms=0.05,
        )
        fsm.update(signals)
        assert fsm.state == FlowState.ACTIVE

        # Now push to flow
        signals = FlowSignals(
            production_activity="production",
            flow_state_score=0.9,
            audio_energy_rms=0.1,
            heart_rate_bpm=85,
            physiological_load=0.5,
            emotion_valence=0.5,
            emotion_arousal=0.5,
            session_duration_minutes=60,
        )
        fsm.update(signals)
        assert fsm.state == FlowState.FLOW

    def test_flow_to_winding_down(self):
        fsm = FlowStateMachine(hysteresis_s=0)
        fsm._state = FlowState.FLOW
        signals = FlowSignals(
            production_activity="idle",
            flow_state_score=0.1,
        )
        fsm.update(signals)
        assert fsm.state == FlowState.WINDING_DOWN

    def test_hysteresis_prevents_rapid_change(self):
        fsm = FlowStateMachine(hysteresis_s=300)
        fsm._last_transition = time.monotonic()  # Just transitioned

        signals = FlowSignals(
            production_activity="production",
            flow_state_score=0.9,
        )
        fsm.update(signals)
        assert fsm.state == FlowState.IDLE  # Hysteresis blocks

    def test_history_recorded(self):
        fsm = FlowStateMachine(hysteresis_s=0)
        signals = FlowSignals(
            production_activity="production",
            flow_state_score=0.5,
            audio_energy_rms=0.05,
        )
        fsm.update(signals)

        assert len(fsm.history) == 1
        assert fsm.history[0].from_state == FlowState.IDLE

    def test_reset(self):
        fsm = FlowStateMachine(hysteresis_s=0)
        fsm._state = FlowState.FLOW
        fsm._history.append(None)  # type: ignore
        fsm.reset()
        assert fsm.state == FlowState.IDLE
        assert fsm.history == []


class TestCompositeScore:
    def test_idle_scores_zero(self):
        fsm = FlowStateMachine()
        signals = FlowSignals()
        assert fsm.compute_composite_score(signals) == 0.0

    def test_production_activity_dominates(self):
        fsm = FlowStateMachine()
        signals = FlowSignals(production_activity="production")
        score = fsm.compute_composite_score(signals)
        assert score >= 0.35

    def test_max_score_clamped(self):
        fsm = FlowStateMachine()
        signals = FlowSignals(
            production_activity="production",
            flow_state_score=1.0,
            audio_energy_rms=1.0,
            heart_rate_bpm=100,
            physiological_load=0.8,
            emotion_valence=0.8,
            emotion_arousal=0.8,
            session_duration_minutes=120,
        )
        score = fsm.compute_composite_score(signals)
        assert score == 1.0

    def test_conversation_scores_lower_than_production(self):
        fsm = FlowStateMachine()
        prod = FlowSignals(production_activity="production")
        conv = FlowSignals(production_activity="conversation")
        assert fsm.compute_composite_score(prod) > fsm.compute_composite_score(conv)


class TestFlowSignals:
    def test_defaults(self):
        signals = FlowSignals()
        assert signals.production_activity == "idle"
        assert signals.heart_rate_bpm == 0
        assert signals.session_duration_minutes == 0.0
