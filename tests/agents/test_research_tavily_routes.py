"""Retired Sonar callers use Tavily and name a next action when search fails."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.research import deep_research, search_web
from shared.tavily_client import TavilyRequestError


@pytest.mark.asyncio
async def test_search_web_uses_scout_lane_and_maps_hour_to_day() -> None:
    with patch("shared.tavily_client.search_snippets", return_value="a hit") as search:
        result = await search_web(None, "stigmergy", recency="hour", domains=["arxiv.org"])
    assert result == "a hit"
    assert search.call_args.args[0] == "stigmergy"
    assert search.call_args.kwargs["lane"] == "scout_horizon"
    assert search.call_args.kwargs["time_range"] == "day"
    assert search.call_args.kwargs["include_domains"] == ["arxiv.org"]


@pytest.mark.asyncio
async def test_deep_research_uses_research_lane() -> None:
    with patch("shared.tavily_client.search_snippets", return_value="a report") as search:
        result = await deep_research(None, "how does midi routing work")
    assert result == "a report"
    assert search.call_args.kwargs["lane"] == "research_reports"
    assert search.call_args.kwargs["search_depth"] == "advanced"


@pytest.mark.asyncio
async def test_search_web_error_names_next_action() -> None:
    with patch(
        "shared.tavily_client.search_snippets",
        side_effect=TavilyRequestError("upstream refused"),
    ):
        result = await search_web(None, "stigmergy")
    assert "Web search unavailable" in result
    assert "next_action=" in result


@pytest.mark.asyncio
async def test_deep_research_error_names_next_action() -> None:
    with patch(
        "shared.tavily_client.search_snippets",
        side_effect=TavilyRequestError("upstream refused"),
    ):
        result = await deep_research(None, "how does midi routing work")
    assert "Deep research unavailable" in result
    assert "next_action=" in result
