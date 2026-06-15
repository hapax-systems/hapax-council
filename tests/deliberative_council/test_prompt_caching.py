"""Tests for prompt caching optimisation (R1b).

Verifies that:
- phase1_system_prompt produces stable, cacheable content
- RESEARCH_SYSTEM_PROMPT is a static string
- build_member passes system_prompt through to Agent
- The stable/dynamic split is maintained correctly
"""

from __future__ import annotations

from unittest.mock import patch

from agents.deliberative_council.members import build_member
from agents.deliberative_council.prompts import (
    RESEARCH_SYSTEM_PROMPT,
    _format_axes_block,
    phase1_prompt_parts,
    phase1_system_prompt,
)
from agents.deliberative_council.rubrics import NarrativeQualityRubric


def test_phase1_system_prompt_contains_rubric_and_role() -> None:
    rubric = NarrativeQualityRubric()
    sys_prompt = phase1_system_prompt(rubric, seed=42)
    assert "deliberative council" in sys_prompt
    assert rubric.instructions[:50] in sys_prompt
    for axis in rubric.axes:
        assert axis.name in sys_prompt
        assert axis.description[:30] in sys_prompt


def test_phase1_system_prompt_is_deterministic_for_same_seed() -> None:
    rubric = NarrativeQualityRubric()
    a = phase1_system_prompt(rubric, seed=42)
    b = phase1_system_prompt(rubric, seed=42)
    assert a == b


def test_phase1_system_prompt_differs_by_seed() -> None:
    rubric = NarrativeQualityRubric()
    a = phase1_system_prompt(rubric, seed=1)
    b = phase1_system_prompt(rubric, seed=2)
    # Same content, different axis order.  The string should differ.
    assert a != b


def test_phase1_system_prompt_contains_scoring_instructions() -> None:
    rubric = NarrativeQualityRubric()
    sys_prompt = phase1_system_prompt(rubric, seed=42)
    assert "Score each axis" in sys_prompt
    assert '"scores"' in sys_prompt
    assert '"rationale"' in sys_prompt


def test_research_system_prompt_is_static_string() -> None:
    assert isinstance(RESEARCH_SYSTEM_PROMPT, str)
    assert "research" in RESEARCH_SYSTEM_PROMPT.lower()
    assert "investigate" in RESEARCH_SYSTEM_PROMPT.lower()
    assert "research_findings" in RESEARCH_SYSTEM_PROMPT


def test_format_axes_block_covers_all_axes() -> None:
    rubric = NarrativeQualityRubric()
    block = _format_axes_block(rubric)
    for axis in rubric.axes:
        assert axis.name in block


def test_build_member_passes_system_prompt() -> None:
    """build_member should pass system_prompt through to Agent()."""
    with patch(
        "agents.deliberative_council.members.Agent",
        autospec=True,
    ) as mock_agent:
        build_member("opus", system_prompt="test system prompt")
        assert mock_agent.called
        _, kwargs = mock_agent.call_args
        assert kwargs["system_prompt"] == "test system prompt"


def test_build_member_without_system_prompt_uses_empty() -> None:
    """When no system_prompt is given, Agent gets an empty string."""
    with patch(
        "agents.deliberative_council.members.Agent",
        autospec=True,
    ) as mock_agent:
        build_member("opus")
        assert mock_agent.called
        _, kwargs = mock_agent.call_args
        assert kwargs["system_prompt"] == ""


def test_phase1_prompt_parts_still_works_without_cache_ttl() -> None:
    """Legacy path: phase1_prompt_parts without cache_ttl returns a string."""
    rubric = NarrativeQualityRubric()
    result = phase1_prompt_parts(rubric, "test text", "ref/123")
    assert isinstance(result, str)
    assert "ref/123" in result
    assert "test text" in result
