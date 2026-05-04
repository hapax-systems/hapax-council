"""End-to-end-ish tests for the ChatReader state machine.

Mocks :class:`YouTubeApiClient` so the reader sees scripted API
responses. Checks the impingement-bus + chat-state-surface contracts
the operator's downstream consumers depend on.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from prometheus_client import CollectorRegistry

from agents.youtube_chat_reader.reader import (
    DEFAULT_RING_SIZE,
    ChatReader,
)


def _broadcast_response(*, broadcast_id: str = "BC1", live_chat_id: str = "LC1") -> dict:
    return {
        "items": [
            {
                "id": broadcast_id,
                "snippet": {"liveChatId": live_chat_id, "title": "test"},
                "status": {"lifeCycleStatus": "live"},
            }
        ]
    }


def _chat_response(
    *,
    items: list[dict],
    next_page_token: str = "tok-1",
    polling_ms: int = 2000,
) -> dict:
    return {
        "items": items,
        "nextPageToken": next_page_token,
        "pollingIntervalMillis": polling_ms,
    }


def _msg(text: str, *, item_id: str = "m1", author: str = "UC-test") -> dict:
    return {
        "id": item_id,
        "snippet": {"displayMessage": text, "publishedAt": "2026-05-04T02:31:14Z"},
        "authorDetails": {"channelId": author},
    }


@pytest.fixture
def fake_client() -> MagicMock:
    """A YouTubeApiClient stand-in with .enabled=True and scriptable execute()."""
    client = MagicMock()
    client.enabled = True
    # The reader builds requests via client.yt.<X>().<Y>().<...>; the request
    # value is just the argument to execute(), so any sentinel works.
    client.yt = MagicMock()
    return client


@pytest.fixture
def reader_factory(tmp_path: Path):
    def _factory(client: MagicMock) -> ChatReader:
        return ChatReader(
            client=client,
            impingement_path=tmp_path / "impingements.jsonl",
            chat_state_path=tmp_path / "recent.jsonl",
            registry=CollectorRegistry(),
        )

    return _factory


def test_idle_when_no_active_broadcast(fake_client: MagicMock, reader_factory) -> None:
    fake_client.execute.return_value = {"items": []}
    reader = reader_factory(fake_client)

    reader.tick_once(now=1000.0)

    assert reader._active_live_chat_id is None
    # Only liveBroadcasts.list was called, no liveChatMessages.list.
    endpoints = [call.kwargs["endpoint"] for call in fake_client.execute.call_args_list]
    assert "liveBroadcasts.list" in endpoints
    assert "liveChatMessages.list" not in endpoints


def test_enters_active_when_broadcast_live(
    fake_client: MagicMock, reader_factory, tmp_path: Path
) -> None:
    fake_client.execute.side_effect = [
        _broadcast_response(broadcast_id="BC1", live_chat_id="LC1"),
        _chat_response(items=[_msg("hello world")]),
    ]
    reader = reader_factory(fake_client)

    reader.tick_once(now=1000.0)
    reader.tick_once(now=1000.0)

    assert reader._active_broadcast_id == "BC1"
    assert reader._active_live_chat_id == "LC1"
    bus_path = tmp_path / "impingements.jsonl"
    assert bus_path.exists()
    lines = bus_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["source"] == "youtube_chat"
    assert record["content"]["text"] == "hello world"
    assert record["content"]["broadcast_id"] == "BC1"


def test_chat_state_surface_written_atomically(
    fake_client: MagicMock, reader_factory, tmp_path: Path
) -> None:
    fake_client.execute.side_effect = [
        _broadcast_response(),
        _chat_response(items=[_msg("first"), _msg("second", item_id="m2")]),
    ]
    reader = reader_factory(fake_client)

    reader.tick_once(now=1000.0)
    reader.tick_once(now=1000.0)

    state_path = tmp_path / "recent.jsonl"
    lines = state_path.read_text().strip().splitlines()
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    assert [p["text"] for p in payloads] == ["first", "second"]
    assert all("author_token" in p for p in payloads)


def test_ring_buffer_caps_at_default_size(
    fake_client: MagicMock, reader_factory, tmp_path: Path
) -> None:
    msgs = [_msg(f"m-{i}", item_id=f"m{i}") for i in range(DEFAULT_RING_SIZE + 5)]
    fake_client.execute.side_effect = [
        _broadcast_response(),
        _chat_response(items=msgs),
    ]
    reader = reader_factory(fake_client)

    reader.tick_once(now=1000.0)
    reader.tick_once(now=1000.0)

    state_path = tmp_path / "recent.jsonl"
    lines = state_path.read_text().strip().splitlines()
    assert len(lines) == DEFAULT_RING_SIZE
    payloads = [json.loads(line) for line in lines]
    # Most recent N — the first 5 messages should have rolled out.
    assert payloads[0]["text"] == "m-5"
    assert payloads[-1]["text"] == f"m-{DEFAULT_RING_SIZE + 4}"


def test_polling_interval_honoured(fake_client: MagicMock, reader_factory) -> None:
    fake_client.execute.side_effect = [
        _broadcast_response(),
        _chat_response(items=[_msg("hi")], polling_ms=4000),
    ]
    reader = reader_factory(fake_client)

    reader.tick_once(now=1000.0)
    reader.tick_once(now=1000.0)

    # Next poll should be no sooner than 1000 + 4 = 1004.
    assert reader._next_poll_at >= 1004.0


def test_drops_to_idle_on_api_raise(fake_client: MagicMock, reader_factory) -> None:
    """When liveChatMessages.list raises, we should drop to idle instead of looping."""
    fake_client.execute.side_effect = [
        _broadcast_response(),
        RuntimeError("liveChatId expired"),
    ]
    reader = reader_factory(fake_client)

    reader.tick_once(now=1000.0)
    reader.tick_once(now=1000.0)

    assert reader._active_live_chat_id is None


def test_skip_when_client_disabled(reader_factory, tmp_path: Path) -> None:
    """Without credentials, the reader stays silent — no API, no writes."""
    client = MagicMock()
    client.enabled = False
    reader = reader_factory(client)

    reader.tick_once(now=1000.0)

    assert not (tmp_path / "impingements.jsonl").exists()
    assert not (tmp_path / "recent.jsonl").exists()
    client.execute.assert_not_called()


def test_emit_filters_blank_messages(
    fake_client: MagicMock, reader_factory, tmp_path: Path
) -> None:
    """A whitespace-only message must not produce an impingement."""
    fake_client.execute.side_effect = [
        _broadcast_response(),
        _chat_response(
            items=[
                _msg("real message", item_id="m1"),
                _msg("   ", item_id="m2"),
            ]
        ),
    ]
    reader = reader_factory(fake_client)

    reader.tick_once(now=1000.0)
    reader.tick_once(now=1000.0)

    bus_path = tmp_path / "impingements.jsonl"
    lines = bus_path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["content"]["text"] == "real message"


def test_impingement_record_omits_raw_author(
    fake_client: MagicMock, reader_factory, tmp_path: Path
) -> None:
    """No bytes of the YouTube channelId may appear on disk."""
    raw_author = "UC-LEAK-TEST-ID-9999"
    fake_client.execute.side_effect = [
        _broadcast_response(),
        _chat_response(items=[_msg("hello", author=raw_author)]),
    ]
    reader = reader_factory(fake_client)

    reader.tick_once(now=1000.0)
    reader.tick_once(now=1000.0)

    bus_text = (tmp_path / "impingements.jsonl").read_text()
    state_text = (tmp_path / "recent.jsonl").read_text()
    assert raw_author not in bus_text
    assert raw_author not in state_text


def test_paginates_via_next_page_token(fake_client: MagicMock, reader_factory) -> None:
    """Subsequent polls should pass the previous nextPageToken."""
    fake_client.execute.side_effect = [
        _broadcast_response(),
        _chat_response(items=[_msg("a", item_id="a")], next_page_token="page-2"),
        _chat_response(items=[_msg("b", item_id="b")], next_page_token="page-3"),
    ]
    reader = reader_factory(fake_client)

    reader.tick_once(now=1000.0)
    reader.tick_once(now=1000.0)
    # Force the second poll: skip the polling-interval gate.
    reader._next_poll_at = 0.0
    reader.tick_once(now=2000.0)

    list_calls = [c for c in fake_client.yt.liveChatMessages().list.call_args_list]
    # Two list() invocations for chat — first with None, second with page-2.
    page_tokens = [c.kwargs.get("pageToken") for c in list_calls]
    assert None in page_tokens
    assert "page-2" in page_tokens
