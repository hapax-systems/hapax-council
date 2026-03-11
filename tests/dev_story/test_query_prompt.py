"""Tests for dev-story query agent prompt content."""

from __future__ import annotations

from agents.dev_story.query import build_system_prompt


def test_prompt_includes_mermaid_instructions():
    prompt = build_system_prompt()
    assert "mermaid" in prompt.lower()
    assert "```mermaid" in prompt


def test_prompt_includes_diagram_guidance():
    prompt = build_system_prompt()
    assert "graph" in prompt.lower() or "flowchart" in prompt.lower()
    assert "gantt" in prompt.lower() or "timeline" in prompt.lower()


def test_prompt_includes_empty_state_guidance():
    prompt = build_system_prompt()
    assert "When Data is Unavailable" in prompt
    assert "git-extractor" in prompt.lower() or "dev_story" in prompt
    assert "uv run python -m agents.dev_story" in prompt
