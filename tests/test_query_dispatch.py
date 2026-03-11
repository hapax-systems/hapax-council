"""Tests for query dispatch — agent registry and classification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cockpit.query_dispatch import (
    classify_query,
    get_agent_list,
    run_query,
)


class TestClassifyQuery:
    def test_no_keyword_match_returns_default(self):
        """With no keyword matches, every query routes to the first agent (dev_story)."""
        result = classify_query("tell me about the weather")
        assert result == "dev_story"

    def test_dev_story_keywords_match(self):
        """Queries mentioning development terms route to dev_story."""
        result = classify_query("show me commit history for voice pipeline")
        assert result == "dev_story"

    def test_empty_query_returns_default(self):
        result = classify_query("")
        assert result == "dev_story"


class TestClassifyQueryMultiAgent:
    def test_health_query_routes_to_system_ops(self):
        result = classify_query("what is the system health status?")
        assert result == "system_ops"

    def test_docker_query_routes_to_system_ops(self):
        result = classify_query("which docker containers are running?")
        assert result == "system_ops"

    def test_cost_query_routes_to_system_ops(self):
        result = classify_query("how much did we spend on LLM costs?")
        assert result == "system_ops"

    def test_commit_query_still_routes_to_dev_story(self):
        result = classify_query("show me commit history and session patterns")
        assert result == "dev_story"

    def test_drift_routes_to_system_ops(self):
        result = classify_query("what infrastructure has drifted from docs?")
        assert result == "system_ops"


class TestClassifyQueryKnowledge:
    def test_document_search_routes_to_knowledge(self):
        result = classify_query("search for that document about API design")
        assert result == "knowledge"

    def test_briefing_routes_to_knowledge(self):
        result = classify_query("what did the briefing say today?")
        assert result == "knowledge"

    def test_email_routes_to_knowledge(self):
        result = classify_query("find emails from last week about the project")
        assert result == "knowledge"

    def test_obsidian_routes_to_knowledge(self):
        result = classify_query("search my obsidian notes for meeting prep")
        assert result == "knowledge"

    def test_goal_routes_to_knowledge(self):
        result = classify_query("what are my current goals?")
        assert result == "knowledge"


class TestGetAgentListAll:
    def test_includes_all_three_agents(self):
        agents = get_agent_list()
        types = {a.agent_type for a in agents}
        assert types == {"dev_story", "system_ops", "knowledge"}


class TestRunQuerySystemOps:
    @patch("cockpit.query_dispatch.extract_full_output", return_value="## Health\nAll good")
    @patch("cockpit.query_dispatch._call_factory")
    async def test_run_system_ops_query(self, mock_factory, mock_extract):
        mock_result = MagicMock()
        mock_result.usage.return_value = MagicMock(input_tokens=800, output_tokens=400)
        mock_agent = AsyncMock()
        mock_agent.run.return_value = mock_result
        mock_factory.return_value = (mock_agent, MagicMock())

        result = await run_query("system_ops", "what is the health status?")
        assert result.markdown == "## Health\nAll good"
        assert result.agent_type == "system_ops"


class TestGetAgentList:
    def test_returns_registered_agents(self):
        agents = get_agent_list()
        assert len(agents) >= 1
        assert agents[0].agent_type == "dev_story"
        assert agents[0].name == "Development Archaeology"
        assert agents[0].description != ""


class TestRunQuery:
    @patch("cockpit.query_dispatch.extract_full_output", return_value="## Test\nHello")
    @patch("cockpit.query_dispatch._call_factory")
    async def test_run_query_returns_markdown(self, mock_factory, mock_extract):
        mock_result = MagicMock()
        mock_result.usage.return_value = MagicMock(input_tokens=1000, output_tokens=500)
        mock_agent = AsyncMock()
        mock_agent.run.return_value = mock_result
        mock_factory.return_value = (mock_agent, MagicMock())

        result = await run_query("dev_story", "tell me about features")

        assert result.markdown == "## Test\nHello"
        assert result.agent_type == "dev_story"
        assert result.tokens_in == 1000
        assert result.tokens_out == 500

    async def test_run_query_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="Unknown query agent"):
            await run_query("nonexistent", "hello")


class TestClassifyEdgeCases:
    def test_infrastructure_keyword_routes_to_system_ops(self):
        result = classify_query("what changed in the infrastructure this week")
        assert result == "system_ops"

    def test_no_keyword_overlap_defaults_to_first_agent(self):
        result = classify_query("the quick brown fox jumps over the lazy dog")
        assert result == "dev_story"
