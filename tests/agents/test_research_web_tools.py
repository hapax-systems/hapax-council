"""Tests for Perplexity web search tools in the research agent."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def _mock_litellm_env(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")


@pytest.mark.usefixtures("_mock_litellm_env")
class TestSearchWeb:
    def test_search_web_returns_grounded_response(self):
        mock_result = MagicMock()
        mock_result.output = "Stigmergic coordination is a mechanism..."

        with patch("agents.research.Agent") as mock_agent_cls:
            instance = mock_agent_cls.return_value
            instance.run = AsyncMock(return_value=mock_result)

            from agents.research import search_web

            ctx = MagicMock()
            result = asyncio.get_event_loop().run_until_complete(
                search_web(ctx, "stigmergic coordination")
            )
            assert "Stigmergic" in result
            assert "unavailable" not in result.lower()

    def test_search_web_handles_failure(self):
        with patch("agents.research.Agent") as mock_agent_cls:
            instance = mock_agent_cls.return_value
            instance.run = AsyncMock(side_effect=ConnectionError("timeout"))

            from agents.research import search_web

            ctx = MagicMock()
            result = asyncio.get_event_loop().run_until_complete(search_web(ctx, "test query"))
            assert "unavailable" in result.lower()

    def test_search_web_accepts_recency_filter(self):
        mock_result = MagicMock()
        mock_result.output = "Recent results..."

        with patch("agents.research.Agent") as mock_agent_cls:
            instance = mock_agent_cls.return_value
            instance.run = AsyncMock(return_value=mock_result)

            from agents.research import search_web

            ctx = MagicMock()
            result = asyncio.get_event_loop().run_until_complete(
                search_web(ctx, "test", recency="week")
            )
            assert "unavailable" not in result.lower()

    def test_search_web_accepts_domain_filter(self):
        mock_result = MagicMock()
        mock_result.output = "Filtered results..."

        with patch("agents.research.Agent") as mock_agent_cls:
            instance = mock_agent_cls.return_value
            instance.run = AsyncMock(return_value=mock_result)

            from agents.research import search_web

            ctx = MagicMock()
            result = asyncio.get_event_loop().run_until_complete(
                search_web(ctx, "test", domains=["arxiv.org"])
            )
            assert "unavailable" not in result.lower()


@pytest.mark.usefixtures("_mock_litellm_env")
class TestDeepResearch:
    def test_deep_research_returns_response(self):
        mock_result = MagicMock()
        mock_result.output = "Comprehensive analysis of..."

        with (
            patch("agents.research.Agent") as mock_agent_cls,
            patch("shared.working_mode.is_fortress", return_value=False),
        ):
            instance = mock_agent_cls.return_value
            instance.run = AsyncMock(return_value=mock_result)

            from agents.research import deep_research

            ctx = MagicMock()
            result = asyncio.get_event_loop().run_until_complete(
                deep_research(ctx, "state of human-AI collaboration")
            )
            assert "Comprehensive" in result

    def test_deep_research_skipped_in_fortress_mode(self):
        with patch("shared.working_mode.is_fortress", return_value=True):
            from agents.research import deep_research

            ctx = MagicMock()
            result = asyncio.get_event_loop().run_until_complete(
                deep_research(ctx, "test question")
            )
            assert "fortress" in result.lower()

    def test_deep_research_handles_failure(self):
        with (
            patch("agents.research.Agent") as mock_agent_cls,
            patch("shared.working_mode.is_fortress", return_value=False),
        ):
            instance = mock_agent_cls.return_value
            instance.run = AsyncMock(side_effect=ConnectionError("timeout"))

            from agents.research import deep_research

            ctx = MagicMock()
            result = asyncio.get_event_loop().run_until_complete(
                deep_research(ctx, "test question")
            )
            assert "unavailable" in result.lower()
