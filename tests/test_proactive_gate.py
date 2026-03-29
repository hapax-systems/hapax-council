"""Tests for agents.proactive_gate — proactive speech gate conditions."""

from __future__ import annotations

import time

from agents.imagination import ImaginationFragment
from agents.proactive_gate import ProactiveGate


def _make_fragment(salience: float = 0.9) -> ImaginationFragment:
    return ImaginationFragment(
        content_references=[],
        dimensions={},
        salience=salience,
        continuation=False,
        narrative="test fragment",
    )


def _passing_state() -> dict:
    return {
        "perception_activity": "active",
        "vad_active": False,
        "last_utterance_time": time.monotonic() - 60.0,
        "tpn_active": False,
    }


class TestProactiveGate:
    def test_passes_when_all_conditions_met(self) -> None:
        gate = ProactiveGate()
        assert gate.should_speak(_make_fragment(), _passing_state()) is True

    def test_fails_low_salience(self) -> None:
        gate = ProactiveGate()
        assert gate.should_speak(_make_fragment(salience=0.7), _passing_state()) is False

    def test_fails_operator_idle(self) -> None:
        gate = ProactiveGate()
        state = _passing_state()
        state["perception_activity"] = "idle"
        assert gate.should_speak(_make_fragment(), state) is False

    def test_fails_operator_away(self) -> None:
        gate = ProactiveGate()
        state = _passing_state()
        state["perception_activity"] = "away"
        assert gate.should_speak(_make_fragment(), state) is False

    def test_fails_vad_active(self) -> None:
        gate = ProactiveGate()
        state = _passing_state()
        state["vad_active"] = True
        assert gate.should_speak(_make_fragment(), state) is False

    def test_fails_recent_utterance(self) -> None:
        gate = ProactiveGate()
        state = _passing_state()
        state["last_utterance_time"] = time.monotonic() - 10.0
        assert gate.should_speak(_make_fragment(), state) is False

    def test_fails_tpn_active(self) -> None:
        gate = ProactiveGate()
        state = _passing_state()
        state["tpn_active"] = True
        assert gate.should_speak(_make_fragment(), state) is False

    def test_fails_during_cooldown(self) -> None:
        gate = ProactiveGate()
        gate.record_utterance()
        assert gate.should_speak(_make_fragment(), _passing_state()) is False

    def test_cooldown_expires(self) -> None:
        gate = ProactiveGate(cooldown_s=0.0)
        gate.record_utterance()
        assert gate.should_speak(_make_fragment(), _passing_state()) is True

    def test_cooldown_resets_on_operator_speech(self) -> None:
        gate = ProactiveGate()
        gate.record_utterance()
        # Cooldown active — should fail
        assert gate.should_speak(_make_fragment(), _passing_state()) is False
        # Operator speaks — clears cooldown
        gate.on_operator_speech()
        assert gate.should_speak(_make_fragment(), _passing_state()) is True

    def test_fails_unknown_activity(self) -> None:
        gate = ProactiveGate()
        state = _passing_state()
        state["perception_activity"] = "unknown"
        assert gate.should_speak(_make_fragment(), state) is False
