"""Integration test: perception → governor → frame gate → session."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from agents.hapax_voice.perception import PerceptionEngine, EnvironmentState
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.frame_gate import FrameGate
from agents.hapax_voice.session import VoiceLifecycle


def _mock_presence(**overrides):
    defaults = dict(
        score="likely_present",
        face_detected=True,
        face_count=1,
        latest_vad_confidence=0.0,
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def test_full_chain_process():
    """Normal state: perception → governor → process → gate passes."""
    presence = _mock_presence()
    engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
    governor = PipelineGovernor()
    gate = FrameGate()
    session = VoiceLifecycle(silence_timeout_s=30)
    session.open(trigger="test")

    state = engine.tick()
    directive = governor.evaluate(state)
    gate.set_directive(directive)

    assert directive == "process"
    assert gate.directive == "process"
    assert not session.is_paused


def test_full_chain_conversation_pause():
    """Conversation detected → governor pauses → gate blocks."""
    presence = _mock_presence(face_count=2, latest_vad_confidence=0.9)
    engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
    governor = PipelineGovernor(conversation_debounce_s=0)  # instant for test
    gate = FrameGate()
    session = VoiceLifecycle(silence_timeout_s=30)
    session.open(trigger="test")

    state = engine.tick()
    assert state.conversation_detected is True

    directive = governor.evaluate(state)
    gate.set_directive(directive)

    assert directive == "pause"
    assert gate.directive == "pause"


def test_full_chain_wake_word_overrides():
    """Wake word overrides conversation pause."""
    presence = _mock_presence(face_count=2, latest_vad_confidence=0.9)
    engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
    governor = PipelineGovernor(conversation_debounce_s=0)
    gate = FrameGate()

    governor.wake_word_active = True
    state = engine.tick()
    directive = governor.evaluate(state)
    gate.set_directive(directive)

    assert directive == "process"


def test_full_chain_withdraw():
    """Operator absent > threshold → governor withdraws."""
    presence = _mock_presence(face_detected=False, face_count=0)
    engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
    governor = PipelineGovernor(operator_absent_withdraw_s=5.0)
    governor._last_operator_seen = time.monotonic() - 10.0

    state = engine.tick()
    directive = governor.evaluate(state)

    assert directive == "withdraw"


def test_slow_enrichment_updates_state():
    """Slow-tick activity mode update flows through to next fast tick."""
    presence = _mock_presence()
    engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
    governor = PipelineGovernor()

    engine.update_slow_fields(activity_mode="production")
    state = engine.tick()
    directive = governor.evaluate(state)

    assert state.activity_mode == "production"
    assert directive == "pause"
