"""Retired Sonar callers use Tavily and name a next action when search fails."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
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


async def _loop_runs_during_search(
    call: Callable[..., Awaitable[str]],
) -> None:
    """A blocking search must not stall the event loop."""

    started = threading.Event()
    release = threading.Event()
    loop_ran = asyncio.Event()
    observed: dict[str, bool] = {}

    def _block(*_args: object, **_kwargs: object) -> str:
        started.set()
        release.wait(timeout=3)
        return "a hit"

    async def _mark() -> None:
        await asyncio.sleep(0)
        loop_ran.set()

    def _watch() -> None:
        assert started.wait(timeout=2)
        time.sleep(0.05)
        observed["while_blocked"] = loop_ran.is_set()
        release.set()

    watcher = threading.Thread(target=_watch)
    with patch("shared.tavily_client.search_snippets", _block):
        search_task = asyncio.create_task(call(None, "stigmergy"))
        mark_task = asyncio.create_task(_mark())
        watcher.start()
        await search_task
    watcher.join(timeout=3)
    await mark_task
    assert observed.get("while_blocked") is True


@pytest.mark.asyncio
async def test_search_web_does_not_block_the_event_loop() -> None:
    await _loop_runs_during_search(search_web)


@pytest.mark.asyncio
async def test_deep_research_does_not_block_the_event_loop() -> None:
    await _loop_runs_during_search(deep_research)


@pytest.mark.asyncio
async def test_deep_research_error_names_next_action() -> None:
    with patch(
        "shared.tavily_client.search_snippets",
        side_effect=TavilyRequestError("upstream refused"),
    ):
        result = await deep_research(None, "how does midi routing work")
    assert "Deep research unavailable" in result
    assert "next_action=" in result
