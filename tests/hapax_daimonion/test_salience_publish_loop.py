"""Tests for salience-router periodic-publish loop."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_daimonion.salience_publish_loop import (
    SALIENCE_PUBLISH_INTERVAL_S,
    salience_publish_loop,
)


class _FakeDaemon:
    def __init__(self, router=None) -> None:
        self._running = True
        if router is not None:
            self._salience_router = router


def test_constants_exist() -> None:
    assert SALIENCE_PUBLISH_INTERVAL_S == 30.0


@pytest.mark.asyncio
async def test_loop_publishes_when_router_present() -> None:
    """When the router has an _exploration tracker, every loop pass calls
    compute_and_publish() so the writer-fresh signal stays alive even
    when no operator utterances are routed."""
    tracker = MagicMock()
    router = MagicMock()
    router._exploration = tracker
    daemon = _FakeDaemon(router=router)

    # Replace the loop sleep with one that exits after the first publish
    # so the test doesn't actually wait 30s.
    async def fast_sleep(_: float) -> None:
        daemon._running = False

    with patch("agents.hapax_daimonion.salience_publish_loop.asyncio.sleep", new=fast_sleep):
        await asyncio.wait_for(salience_publish_loop(daemon), timeout=2.0)

    tracker.compute_and_publish.assert_called()


@pytest.mark.asyncio
async def test_loop_skips_when_router_missing() -> None:
    """When SalienceRouter isn't initialized (heuristic-routing fallback
    in init_audio.py), the loop must stay alive without raising."""
    daemon = _FakeDaemon(router=None)
    # No _salience_router attribute at all.

    async def fast_sleep(_: float) -> None:
        daemon._running = False

    with patch("agents.hapax_daimonion.salience_publish_loop.asyncio.sleep", new=fast_sleep):
        await asyncio.wait_for(salience_publish_loop(daemon), timeout=2.0)

    # No exception is success — the loop tolerated the missing router.


@pytest.mark.asyncio
async def test_loop_swallows_publish_exceptions() -> None:
    """A publisher crash must not take the daemon down — log + continue."""
    tracker = MagicMock()
    tracker.compute_and_publish.side_effect = RuntimeError("publisher down")
    router = MagicMock()
    router._exploration = tracker
    daemon = _FakeDaemon(router=router)

    sleep_count = {"n": 0}

    async def fast_sleep(_: float) -> None:
        sleep_count["n"] += 1
        if sleep_count["n"] >= 2:
            daemon._running = False

    with patch("agents.hapax_daimonion.salience_publish_loop.asyncio.sleep", new=fast_sleep):
        await asyncio.wait_for(salience_publish_loop(daemon), timeout=2.0)

    # At least 2 publish attempts — the loop kept ticking despite raises.
    assert tracker.compute_and_publish.call_count >= 2


@pytest.mark.asyncio
async def test_loop_exits_when_daemon_running_false_at_start() -> None:
    """Daemon already shutting down → loop exits without publishing."""
    tracker = MagicMock()
    router = MagicMock()
    router._exploration = tracker
    daemon = _FakeDaemon(router=router)
    daemon._running = False

    await asyncio.wait_for(salience_publish_loop(daemon), timeout=2.0)
    tracker.compute_and_publish.assert_not_called()
