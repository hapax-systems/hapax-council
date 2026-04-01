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
        "presence_state": "PRESENT",
        "stimmung_stance": "nominal",
        "session_active": False,
    }


class TestProactiveGate:
    def test_passes_when_all_conditions_met(self) -> None:
        gate = ProactiveGate()
        # salience=0.95 → near-certain passage through sigmoid gate
        frag = _make_fragment(salience=0.95)
        # Retry a few times to handle rare sigmoid miss
        passed = any(gate.should_speak(frag, _passing_state()) for _ in range(10))
        assert passed is True

    def test_low_salience_usually_fails(self) -> None:
        gate = ProactiveGate()
        frag = _make_fragment(salience=0.5)
        failures = sum(1 for _ in range(100) if not gate.should_speak(frag, _passing_state()))
        assert failures > 80

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
        frag = _make_fragment(salience=0.99)
        passed = any(gate.should_speak(frag, _passing_state()) for _ in range(10))
        assert passed is True

    def test_cooldown_resets_on_operator_speech(self) -> None:
        gate = ProactiveGate()
        gate.record_utterance()
        # Cooldown active — should fail
        assert gate.should_speak(_make_fragment(), _passing_state()) is False
        # Operator speaks — clears cooldown
        gate.on_operator_speech()
        frag = _make_fragment(salience=0.99)
        passed = any(gate.should_speak(frag, _passing_state()) for _ in range(10))
        assert passed is True

    def test_fails_unknown_activity(self) -> None:
        gate = ProactiveGate()
        state = _passing_state()
        state["perception_activity"] = "unknown"
        assert gate.should_speak(_make_fragment(), state) is False
