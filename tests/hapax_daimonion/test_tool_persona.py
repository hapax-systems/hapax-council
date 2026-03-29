"""Tests for tool-aware system prompt."""

from agents.hapax_daimonion.persona import system_prompt


def test_operator_prompt_mentions_tools():
    prompt = system_prompt(guest_mode=False)
    assert "search" in prompt.lower() or "documents" in prompt.lower()
    assert "calendar" in prompt.lower()
    assert "sms" in prompt.lower() or "message" in prompt.lower()
    assert "camera" in prompt.lower() or "see" in prompt.lower()


def test_guest_prompt_does_not_mention_tools():
    prompt = system_prompt(guest_mode=True)
    assert "sms" not in prompt.lower()
