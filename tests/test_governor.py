"""Tests for PipelineGovernor."""

from __future__ import annotations

import time

from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState


def _state(**overrides) -> EnvironmentState:
    """Helper to build EnvironmentState with overrides."""
    defaults = dict(timestamp=time.monotonic())
    defaults.update(overrides)
    return EnvironmentState(**defaults)


def test_process_when_operator_present():
    gov = PipelineGovernor()
    state = _state(operator_present=True, face_count=1)
    assert gov.evaluate(state) == "process"


def test_pause_on_conversation():
    """face_count > 1 + speech → pause."""
    gov = PipelineGovernor(conversation_debounce_s=0)
    state = _state(face_count=2, speech_detected=True, operator_present=True)
    assert gov.evaluate(state) == "pause"


def test_pause_on_production_mode():
    gov = PipelineGovernor()
    state = _state(activity_mode="production", operator_present=True)
    assert gov.evaluate(state) == "pause"


def test_pause_on_meeting_mode():
    gov = PipelineGovernor()
    state = _state(activity_mode="meeting", operator_present=True)
    assert gov.evaluate(state) == "pause"


def test_withdraw_on_operator_absent():
    """No face for longer than threshold → withdraw."""
    gov = PipelineGovernor(operator_absent_withdraw_s=5.0)
    gov._last_operator_seen = time.monotonic() - 10.0
    state = _state(operator_present=False, face_count=0)
    assert gov.evaluate(state) == "withdraw"


def test_no_withdraw_if_recently_seen():
    """Operator absent but within threshold → process, not withdraw."""
    gov = PipelineGovernor(operator_absent_withdraw_s=60.0)
    gov._last_operator_seen = time.monotonic() - 5.0
    state = _state(operator_present=False, face_count=0)
    assert gov.evaluate(state) == "process"


def test_wake_word_override():
    """wake_word_active=True forces process regardless of other signals."""
    gov = PipelineGovernor()
    gov.wake_word_active = True
    state = _state(face_count=3, speech_detected=True, activity_mode="production")
    assert gov.evaluate(state) == "process"
    assert gov.wake_word_active is False


def test_conversation_debounce():
    """Conversation must persist for debounce_s before triggering pause."""
    gov = PipelineGovernor(conversation_debounce_s=3.0)
    state = _state(face_count=2, speech_detected=True, operator_present=True)
    assert gov.evaluate(state) == "process"  # within debounce
    gov._conversation_first_seen = time.monotonic() - 4.0
    assert gov.evaluate(state) == "pause"  # debounce expired


def test_no_conversation_resets_debounce():
    """When conversation signal disappears, debounce timer resets."""
    gov = PipelineGovernor(conversation_debounce_s=3.0)
    conv_state = _state(face_count=2, speech_detected=True, operator_present=True)
    gov.evaluate(conv_state)
    assert gov._conversation_first_seen is not None
    clear_state = _state(face_count=1, speech_detected=False, operator_present=True)
    gov.evaluate(clear_state)
    assert gov._conversation_first_seen is None


def test_environment_clear_auto_resume():
    """After conversation ends, auto-resume after environment_clear_resume_s."""
    gov = PipelineGovernor(conversation_debounce_s=0, environment_clear_resume_s=5.0)
    conv_state = _state(face_count=2, speech_detected=True, operator_present=True)
    assert gov.evaluate(conv_state) == "pause"
    assert gov._paused_by_conversation is True
    gov._conversation_cleared_at = time.monotonic() - 2.0
    clear_state = _state(face_count=1, speech_detected=False, operator_present=True)
    assert gov.evaluate(clear_state) == "pause"  # within delay
    gov._conversation_cleared_at = time.monotonic() - 6.0
    assert gov.evaluate(clear_state) == "process"  # auto-resumed


def test_environment_clear_resume_resets_on_new_conversation():
    """If conversation resumes during clear delay, timer resets."""
    gov = PipelineGovernor(conversation_debounce_s=0, environment_clear_resume_s=5.0)
    conv_state = _state(face_count=2, speech_detected=True, operator_present=True)
    gov.evaluate(conv_state)
    gov._conversation_cleared_at = time.monotonic() - 2.0
    clear_state = _state(face_count=1, speech_detected=False, operator_present=True)
    gov.evaluate(clear_state)
    gov.evaluate(conv_state)
    assert gov._conversation_cleared_at is None
