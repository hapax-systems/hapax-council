"""Unit tests for agents.content_id_watcher.poller."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.content_id_watcher.poller import poll_archived_video, poll_live_broadcasts


def _client(*, enabled: bool = True, response=None) -> MagicMock:
    client = MagicMock()
    client.enabled = enabled
    client.execute.return_value = response
    client.yt = MagicMock()
    return client


def test_poll_live_disabled_returns_empty():
    client = _client(enabled=False)
    assert poll_live_broadcasts(client) == {}


def test_poll_live_returns_indexed_dict():
    client = _client(
        response={
            "items": [
                {"id": "bid-1", "snippet": {"title": "A"}},
                {"id": "bid-2", "snippet": {"title": "B"}},
            ]
        }
    )
    result = poll_live_broadcasts(client)
    assert set(result.keys()) == {"bid-1", "bid-2"}
    assert result["bid-1"]["snippet"]["title"] == "A"


def test_poll_live_quota_exhaustion_returns_empty():
    """client.execute returns None on quota silent-skip → empty dict."""
    client = _client(response=None)
    assert poll_live_broadcasts(client) == {}


def test_poll_live_skips_items_without_id():
    client = _client(
        response={
            "items": [
                {"id": "bid-1"},
                {"snippet": {"title": "no id"}},
                {"id": 123},  # non-string id
            ]
        }
    )
    result = poll_live_broadcasts(client)
    assert set(result.keys()) == {"bid-1"}


def test_poll_archived_returns_first_item():
    client = _client(response={"items": [{"id": "vid-1", "status": {"madeForKids": False}}]})
    snapshot = poll_archived_video(client, "vid-1")
    assert snapshot is not None
    assert snapshot["id"] == "vid-1"


def test_poll_archived_no_items_returns_none():
    client = _client(response={"items": []})
    assert poll_archived_video(client, "vid-x") is None


def test_poll_archived_disabled_returns_none():
    client = _client(enabled=False)
    assert poll_archived_video(client, "vid-x") is None


def test_poll_archived_quota_exhaustion_returns_none():
    client = _client(response=None)
    assert poll_archived_video(client, "vid-x") is None


def test_poll_live_passes_correct_endpoint_label():
    client = _client(response={"items": []})
    poll_live_broadcasts(client)
    _, kwargs = client.execute.call_args
    assert kwargs["endpoint"] == "liveBroadcasts.list"


def test_poll_archived_passes_correct_endpoint_label():
    client = _client(response={"items": [{"id": "vid-x"}]})
    poll_archived_video(client, "vid-x")
    _, kwargs = client.execute.call_args
    assert kwargs["endpoint"] == "videos.list"
