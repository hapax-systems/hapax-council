"""Tests for hapax_voice intent router."""
from __future__ import annotations

from agents.hapax_voice.intent_router import IntentResult, classify_intent


def test_briefing_routes_local() -> None:
    result = classify_intent("give me my briefing")
    assert result.backend == "local"
    assert result.matched_pattern != ""


def test_calendar_routes_local() -> None:
    result = classify_intent("what's on my calendar today")
    assert result.backend == "local"


def test_system_status_routes_local() -> None:
    result = classify_intent("what's the system status")
    assert result.backend == "local"


def test_conversational_routes_gemini() -> None:
    result = classify_intent("tell me a joke about programming")
    assert result.backend == "gemini"
    assert result.matched_pattern == ""


def test_generic_routes_gemini() -> None:
    result = classify_intent("what is the capital of France")
    assert result.backend == "gemini"


def test_meeting_prep_routes_local() -> None:
    result = classify_intent("prepare for my meeting prep")
    assert result.backend == "local"


def test_hapax_prefix_routes_local() -> None:
    result = classify_intent("hey hapax, how are things looking")
    assert result.backend == "local"


def test_guest_mode_routes_gemini() -> None:
    result = classify_intent("what's the system status", guest_mode=True)
    assert result.backend == "gemini"
