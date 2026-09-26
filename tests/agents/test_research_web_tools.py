"""Tests for Tavily web search tools in the research agent."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from shared.tavily_client import TavilyRequestError


class TestSearchWeb:
    def test_search_web_returns_grounded_response(self):
        with patch(
            "shared.tavily_client.search_snippets",
            return_value="Stigmergic coordination is a mechanism...",
        ):
            from agents.research import search_web

            result = asyncio.run(search_web(MagicMock(), "stigmergic coordination"))
            assert "Stigmergic" in result
            assert "unavailable" not in result.lower()

    def test_search_web_handles_failure(self):
        with patch(
            "shared.tavily_client.search_snippets",
            side_effect=TavilyRequestError("timeout"),
        ):
            from agents.research import search_web

            result = asyncio.run(search_web(MagicMock(), "test query"))
            assert "unavailable" in result.lower()

    def test_search_web_accepts_recency_filter(self):
        with patch(
            "shared.tavily_client.search_snippets",
            return_value="Recent results...",
        ) as search:
            from agents.research import search_web

            result = asyncio.run(search_web(MagicMock(), "test", recency="week"))
            assert "unavailable" not in result.lower()
            assert search.call_args.kwargs["time_range"] == "week"

    def test_search_web_accepts_domain_filter(self):
        with patch(
            "shared.tavily_client.search_snippets",
            return_value="Filtered results...",
        ) as search:
            from agents.research import search_web

            result = asyncio.run(search_web(MagicMock(), "test", domains=["arxiv.org"]))
            assert "unavailable" not in result.lower()
            assert search.call_args.kwargs["include_domains"] == ["arxiv.org"]


class TestDeepResearch:
    def test_deep_research_returns_response(self):
        with (
            patch(
                "shared.tavily_client.search_snippets",
                return_value="Comprehensive analysis of...",
            ),
            patch("shared.working_mode.is_fortress", return_value=False),
        ):
            from agents.research import deep_research

            result = asyncio.run(deep_research(MagicMock(), "state of human-AI collaboration"))
            assert "Comprehensive" in result

    def test_deep_research_skipped_in_fortress_mode(self):
        with patch("shared.working_mode.is_fortress", return_value=True):
            from agents.research import deep_research

            result = asyncio.run(deep_research(MagicMock(), "test question"))
            assert "fortress" in result.lower()

    def test_deep_research_handles_failure(self):
        with (
            patch(
                "shared.tavily_client.search_snippets",
                side_effect=TavilyRequestError("timeout"),
            ),
            patch("shared.working_mode.is_fortress", return_value=False),
        ):
            from agents.research import deep_research

            result = asyncio.run(deep_research(MagicMock(), "test question"))
            assert "unavailable" in result.lower()
