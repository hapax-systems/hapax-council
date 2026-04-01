"""Tests for hapax_daimonion context gate."""

from __future__ import annotations

from unittest.mock import patch

from agents.hapax_daimonion.context_gate import ContextGate
from agents.hapax_daimonion.primitives import Behavior
from agents.hapax_daimonion.session import SessionManager


def _make_behaviors(**kwargs) -> dict[str, Behavior]:
    """Helper to create Behavior dict from keyword args."""
    return {k: Behavior(v) for k, v in kwargs.items()}


def test_blocks_during_active_session() -> None:
    session = SessionManager()
    session.open("hotkey")
    gate = ContextGate(session=session)
    result = gate.check()
    assert not result.eligible
    assert "active" in result.reason.lower()


def test_allows_when_idle() -> None:
    session = SessionManager()
    gate = ContextGate(session=session)
    gate.set_behaviors(_make_behaviors(sink_volume=0.3, midi_active=False))
    result = gate.check()
    assert result.eligible


def test_blocks_high_volume() -> None:
    session = SessionManager()
    gate = ContextGate(session=session)
    gate.set_behaviors(_make_behaviors(sink_volume=0.9))
    result = gate.check()
    assert not result.eligible
    assert "volume" in result.reason.lower()


def test_blocks_studio_active() -> None:
    session = SessionManager()
    gate = ContextGate(session=session)
    gate.set_behaviors(_make_behaviors(sink_volume=0.3, midi_active=True))
    result = gate.check()
    assert not result.eligible
    assert "midi" in result.reason.lower()


def test_blocks_ambient_music() -> None:
    """Ambient classification blocks when music is detected."""
    session = SessionManager()
    gate = ContextGate(session=session)
    gate.set_behaviors(_make_behaviors(sink_volume=0.3, midi_active=False))
    with patch.object(
        gate,
        "_check_ambient",
        return_value=(False, "Ambient audio blocked: Music (0.85), total block prob=0.90"),
    ):
        result = gate.check()
    assert not result.eligible
    assert "ambient" in result.reason.lower()
    assert "music" in result.reason.lower()


def test_blocks_ambient_speech() -> None:
    """Ambient classification blocks when speech is detected on monitor."""
    session = SessionManager()
    gate = ContextGate(session=session)
    gate.set_behaviors(_make_behaviors(sink_volume=0.3, midi_active=False))
    with patch.object(
        gate,
        "_check_ambient",
        return_value=(False, "Ambient audio blocked: Speech (0.72), total block prob=0.75"),
    ):
        result = gate.check()
    assert not result.eligible
    assert "speech" in result.reason.lower()


def test_ambient_disabled_allows() -> None:
    """When ambient classification is disabled, gate skips that check."""
    session = SessionManager()
    gate = ContextGate(session=session, ambient_classification=False)
    gate.set_behaviors(_make_behaviors(sink_volume=0.3, midi_active=False))
    result = gate.check()
    assert result.eligible


def test_ambient_fail_closed() -> None:
    """If _check_ambient raises, the gate blocks (fail-closed)."""
    session = SessionManager()
    gate = ContextGate(session=session)
    gate.set_behaviors(_make_behaviors(sink_volume=0.3, midi_active=False))
    with patch.object(
        gate,
        "_check_ambient",
        return_value=(False, "Ambient classification unavailable (fail-closed)"),
    ):
        result = gate.check()
    assert not result.eligible
    assert "fail-closed" in result.reason.lower()


def test_gate_respects_environment_state_conversation():
    """Gate blocks when EnvironmentState shows conversation."""
    session = SessionManager(silence_timeout_s=30)
    gate = ContextGate(session=session)
    gate.set_activity_mode("conversation")
    result = gate.check()
    assert not result.eligible
    assert "conversation" in result.reason.lower()
