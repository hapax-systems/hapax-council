"""Tests for agents.knowledge.query — knowledge & context query agent."""

from __future__ import annotations

from agents.knowledge.query import (
    KnowledgeDeps,
    build_system_prompt,
    create_agent,
)


class TestBuildSystemPrompt:
    def test_includes_collection_descriptions(self):
        prompt = build_system_prompt()
        assert "documents" in prompt
        assert "profile-facts" in prompt
        assert "briefing" in prompt

    def test_includes_source_service_guide(self):
        prompt = build_system_prompt()
        assert "gdrive" in prompt
        assert "gmail" in prompt
        assert "obsidian" in prompt

    def test_includes_mermaid_instructions(self):
        prompt = build_system_prompt()
        assert "mermaid" in prompt.lower()
        assert "```mermaid" in prompt

    def test_prompt_includes_empty_state_guidance(self):
        prompt = build_system_prompt()
        assert "When Data is Unavailable" in prompt
        assert "sync agents" in prompt.lower()
        assert "briefing" in prompt.lower()
        assert "07:00" in prompt or "daily" in prompt.lower()


class TestCreateAgent:
    def test_creates_agent_with_deps_type(self):
        agent = create_agent()
        assert agent.deps_type is KnowledgeDeps

    def test_agent_has_expected_tools(self):
        agent = create_agent()
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        assert "search_docs" in tool_names
        assert "search_profile_facts" in tool_names
        assert "briefing" in tool_names
        assert "digest" in tool_names
        assert "scout_report" in tool_names
        assert "operator_goals" in tool_names
        assert "collection_stats" in tool_names
