"""Tests for hapax_voice persona module."""

from __future__ import annotations

from agents.hapax_voice.persona import (
    format_notification,
    session_end_message,
    system_prompt,
    voice_greeting,
)


def test_system_prompt_contains_hapax_and_ryan() -> None:
    prompt = system_prompt()
    assert "Hapax" in prompt
    assert "Operator" in prompt


def test_guest_prompt_works() -> None:
    prompt = system_prompt(guest_mode=True)
    assert "Hapax" in prompt
    assert "primary operator" in prompt


def test_greeting_returns_string() -> None:
    result = voice_greeting()
    assert isinstance(result, str)
    assert len(result) > 0


def test_format_notification_contains_title() -> None:
    result = format_notification("Deploy Alert", "staging is down")
    assert "Deploy Alert" in result
    assert "staging is down" in result


def test_session_end_with_queued() -> None:
    msg = session_end_message(queued_count=3)
    assert "3" in msg
    assert "notifications" in msg


def test_session_end_without_queued() -> None:
    msg = session_end_message()
    assert msg == "Catch you later."
