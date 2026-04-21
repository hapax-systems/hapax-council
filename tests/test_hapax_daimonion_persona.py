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
    # Guest prompt must explicitly distinguish the partner from the
    # operator so operator-private tools (briefing, goals, profile)
    # stay out of scope. The exact phrasing has shifted from
    # "primary operator" → "not the operator" — pin both formulations.
    assert "guest" in prompt
    assert "not the operator" in prompt or "primary operator" in prompt


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
    """When tool_recruitment_active=True, the prompt must NOT enumerate
    individual tools (the recruitment loop selects per-turn)."""
    prompt = system_prompt(tool_recruitment_active=True)
    assert "Hapax" in prompt
    # Tool-directory marker is the per-tool identifier list. The
    # recruitment-active path strips them so the LLM only sees the
    # tools the recruitment loop chose.
    assert "get_calendar_today" not in prompt


def test_system_prompt_minimal_preserves_identity() -> None:
    """Identity-anchoring text survives the recruitment-active prune."""
    prompt = system_prompt(tool_recruitment_active=True)
    # "Never invent" pins the no-confabulation contract; persona
    # rewrites have preserved this phrase across multiple iterations.
    assert "Never invent" in prompt
    # Hapax identity itself.
    assert "Hapax" in prompt


def test_system_prompt_full_when_no_recruitment() -> None:
    """When tool_recruitment_active=False, the full tool directory
    appears so the LLM has the full vocabulary available."""
    prompt = system_prompt(tool_recruitment_active=False)
    # Per-tool identifier appears in the full-directory variant.
    assert "get_calendar_today" in prompt


def test_experiment_mode_takes_priority_over_recruitment() -> None:
    """experiment_mode=True must strip the tool directory regardless
    of tool_recruitment_active. The two prompts (experiment vs
    recruitment-active) collapse to the same minimal shape — no
    per-tool identifier enumerated."""
    prompt_experiment = system_prompt(experiment_mode=True, tool_recruitment_active=True)
    prompt_recruitment = system_prompt(experiment_mode=False, tool_recruitment_active=True)
    assert "get_calendar_today" not in prompt_experiment
    # Experiment-priority means the prompt should be no LARGER than the
    # recruitment-only prompt (experiment can never re-enable the
    # tool directory).
    assert len(prompt_experiment) <= len(prompt_recruitment)
