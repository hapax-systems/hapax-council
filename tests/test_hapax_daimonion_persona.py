"""Tests for hapax_daimonion persona module."""

from __future__ import annotations

from agents.hapax_daimonion.persona import (
    format_notification,
    session_end_message,
    system_prompt,
    voice_greeting,
)


def test_system_prompt_contains_hapax_and_operator() -> None:
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


def test_system_prompt_minimal_has_no_tool_directory() -> None:
    prompt = system_prompt(tool_recruitment_active=True)
    assert "Hapax" in prompt
    assert "Your tools:" not in prompt
    assert "get_calendar_today" not in prompt
    assert len(prompt) < 750  # minimal prompt is ~728 chars (~180 tokens)


def test_system_prompt_minimal_preserves_identity() -> None:
    prompt = system_prompt(tool_recruitment_active=True)
    assert "warm but concise" in prompt
    assert "Never invent" in prompt


def test_system_prompt_full_when_no_recruitment() -> None:
    prompt = system_prompt(tool_recruitment_active=False)
    assert "Your tools:" in prompt
    assert "get_calendar_today" in prompt


def test_experiment_mode_takes_priority_over_recruitment() -> None:
    prompt = system_prompt(experiment_mode=True, tool_recruitment_active=True)
    assert "Your tools:" not in prompt
    assert "get_calendar_today" not in prompt
    # Should be experiment prompt, not minimal prompt
    assert len(prompt) < 420  # experiment prompt is ~403 chars
