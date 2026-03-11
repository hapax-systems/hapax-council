"""Integration tests for demo quality pipeline."""
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from agents.demo import parse_duration, build_planning_prompt
from agents.demo_models import load_personas


class TestBuildPlanningPromptEnriched:
    def test_includes_research_context(self):
        personas = load_personas()
        prompt = build_planning_prompt(
            "health monitoring", "leadership", personas["leadership"],
            "## Current Health\nScore: 74/75", "## Style Guide\nVoice: first-person",
        )
        assert "74/75" in prompt
        assert "first-person" in prompt

    def test_includes_visual_type_guidance(self):
        personas = load_personas()
        prompt = build_planning_prompt(
            "the system", "family", personas["family"],
            "research", "planning context",
        )
        assert "screenshot" in prompt
        assert "diagram" in prompt
        assert "chart" in prompt

    def test_includes_audience_persona(self):
        personas = load_personas()
        prompt = build_planning_prompt(
            "agents", "technical-peer", personas["technical-peer"],
            "research", "planning context",
        )
        assert "technical-peer" in prompt


class TestDurationIntegration:
    def test_parse_duration_in_pipeline(self):
        """Duration parsing returns correct seconds."""
        assert parse_duration("10m", "leadership") == 600

    def test_audience_default_applied(self):
        assert parse_duration(None, "family") == 180
