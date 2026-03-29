"""Tests for hapax_daimonion ntfy listener."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from agents.hapax_daimonion.ntfy_listener import (
    _ntfy_priority_to_str,
    parse_ntfy_event,
    subscribe_ntfy,
)


def test_parse_message_event() -> None:
    raw = json.dumps(
        {
            "event": "message",
            "topic": "hapax",
            "title": "Deploy",
            "message": "staging is up",
            "priority": 3,
        }
    )
    result = parse_ntfy_event(raw)
    assert result is not None
    assert result.title == "Deploy"
    assert result.message == "staging is up"
    assert result.priority == "normal"
    assert result.source == "ntfy"


def test_parse_keepalive_returns_none() -> None:
    raw = json.dumps({"event": "keepalive"})
    assert parse_ntfy_event(raw) is None


def test_parse_open_returns_none() -> None:
    raw = json.dumps({"event": "open", "topic": "hapax"})
    assert parse_ntfy_event(raw) is None


def test_priority_mapping() -> None:
    assert _ntfy_priority_to_str(5) == "urgent"
    assert _ntfy_priority_to_str(4) == "urgent"
    assert _ntfy_priority_to_str(3) == "normal"
    assert _ntfy_priority_to_str(2) == "low"
    assert _ntfy_priority_to_str(1) == "low"


@pytest.mark.asyncio
async def test_subscribe_ntfy_dispatches_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that subscribe_ntfy parses JSON lines and calls the callback."""
    lines = [
        json.dumps({"event": "open", "topic": "alerts"}),
        json.dumps(
            {
                "event": "message",
                "topic": "alerts",
                "title": "Build",
                "message": "build passed",
                "priority": 4,
            }
        ),
        json.dumps({"event": "keepalive"}),
        json.dumps(
            {
                "event": "message",
                "topic": "alerts",
                "title": "Deploy",
                "message": "deployed v2",
                "priority": 2,
            }
        ),
    ]

    call_count = 0
    received: list = []
    callback = AsyncMock(side_effect=lambda n: received.append(n))

    async def _fake_aiter_lines():
        nonlocal call_count
        for line in lines:
            yield line
        # After delivering all lines, raise to break the loop
        raise httpx.ReadError("stream ended")

    fake_response = AsyncMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.aiter_lines = _fake_aiter_lines
    # Make it usable as async context manager
    fake_response.__aenter__ = AsyncMock(return_value=fake_response)
    fake_response.__aexit__ = AsyncMock(return_value=False)

    fake_client = AsyncMock()
    fake_client.stream = MagicMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    # Make AsyncClient() return our fake client
    monkeypatch.setattr(httpx, "AsyncClient", lambda: fake_client)

    # Patch asyncio.sleep to raise after first reconnect attempt
    # (so the test doesn't loop forever)
    sleep_called = asyncio.Event()

    async def _fake_sleep(delay: float) -> None:
        sleep_called.set()
        raise asyncio.CancelledError("stop test loop")

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await subscribe_ntfy("http://localhost:8090", ["alerts"], callback)

    # Should have received exactly 2 message events
    assert len(received) == 2
    assert received[0].title == "Build"
    assert received[0].message == "build passed"
    assert received[0].priority == "urgent"
    assert received[1].title == "Deploy"
    assert received[1].message == "deployed v2"
    assert received[1].priority == "low"

    # Verify the URL used comma-separated topics + /json
    fake_client.stream.assert_called_with(
        "GET",
        "http://localhost:8090/alerts/json",
        timeout=None,
    )


@pytest.mark.asyncio
async def test_subscribe_ntfy_reconnects_on_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that subscribe_ntfy reconnects with backoff on connection failure."""
    sleep_delays: list[float] = []

    fake_client = AsyncMock()

    async def _raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    fake_response = AsyncMock()
    fake_response.__aenter__ = AsyncMock(side_effect=_raise_connect_error)
    fake_response.__aexit__ = AsyncMock(return_value=False)
    fake_client.stream = MagicMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr(httpx, "AsyncClient", lambda: fake_client)

    async def _fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)
        if len(sleep_delays) >= 4:
            raise asyncio.CancelledError("stop")

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    callback = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await subscribe_ntfy("http://localhost:8090", ["test"], callback)

    # Verify exponential backoff: 1, 2, 4, 8
    assert sleep_delays == [1.0, 2.0, 4.0, 8.0]
    callback.assert_not_called()
