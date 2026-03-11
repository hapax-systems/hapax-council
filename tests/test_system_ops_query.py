"""Tests for agents.system_ops.query — system operations query agent."""

from __future__ import annotations

from agents.system_ops.query import (
    SystemOpsDeps,
    build_system_prompt,
    create_agent,
)


class TestBuildSystemPrompt:
    def test_includes_table_schemas(self):
        prompt = build_system_prompt()
        assert "health_runs" in prompt
        assert "drift_items" in prompt
        assert "drift_runs" in prompt
        assert "digest_runs" in prompt
        assert "knowledge_maint" in prompt

    def test_includes_paradigm_guidance(self):
        prompt = build_system_prompt()
        assert "sql" in prompt.lower() or "SQL" in prompt
        assert "live" in prompt.lower()

    def test_includes_mermaid_instructions(self):
        prompt = build_system_prompt()
        assert "mermaid" in prompt.lower()
        assert "```mermaid" in prompt

    def test_prompt_includes_empty_state_guidance(self):
        prompt = build_system_prompt()
        assert "When Data is Unavailable" in prompt
        assert "health monitor" in prompt.lower() or "health_runs" in prompt
        assert "every 15 minutes" in prompt
        assert "drift detector" in prompt.lower() or "drift_runs" in prompt


class TestCreateAgent:
    def test_creates_agent_with_deps_type(self):
        agent = create_agent()
        assert agent.deps_type is SystemOpsDeps

    def test_agent_has_expected_tools(self):
        agent = create_agent()
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        assert "sql_query" in tool_names
        assert "table_schemas" in tool_names
        assert "infra_snapshot" in tool_names
        assert "manifest_section" in tool_names
        assert "langfuse_cost" in tool_names
        assert "qdrant_stats" in tool_names
