"""Tests for ``shared.youtube_broadcast_resolver``.

FINDING-V Phase 3: selection policy = active > upcoming (operator Q1=C),
TTL = 15 min on hit / 60 s on miss, publish_broadcast_id atomic
tmp+rename.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from shared import youtube_broadcast_resolver


@pytest.fixture(autouse=True)
def _clear_cache():
    youtube_broadcast_resolver._cache.clear()
    yield
    youtube_broadcast_resolver._cache.clear()


def _mk_youtube_client(active_items=None, upcoming_items=None, raise_on=None):
    """Build a MagicMock discovery client.

    ``raise_on`` is a dict ``{status: HttpError}``. Either ``_items`` arg
    controls what the matching status returns; missing items = [].
    """
    client = MagicMock()

    def _list(*, part: str, broadcastStatus: str, mine: bool):
        if raise_on and broadcastStatus in raise_on:
            req = MagicMock()
            req.execute.side_effect = raise_on[broadcastStatus]
            return req
        req = MagicMock()
        if broadcastStatus == "active":
            req.execute.return_value = {"items": active_items or []}
        elif broadcastStatus == "upcoming":
            req.execute.return_value = {"items": upcoming_items or []}
        else:
            req.execute.return_value = {"items": []}
        return req

    client.liveBroadcasts.return_value.list.side_effect = _list
    return client


def test_resolve_returns_active_when_present():
    creds = object()
    yt = _mk_youtube_client(active_items=[{"id": "BCAST_ACTIVE"}])
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, expiry = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid == "BCAST_ACTIVE"
    assert expiry > time.time() + 14 * 60  # hit TTL ~15 min


def test_resolve_falls_through_to_upcoming():
    creds = object()
    yt = _mk_youtube_client(active_items=[], upcoming_items=[{"id": "BCAST_UPCOMING"}])
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, _ = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid == "BCAST_UPCOMING"


def test_resolve_returns_none_when_no_broadcasts():
    creds = object()
    yt = _mk_youtube_client()
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, expiry = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid is None
    assert expiry < time.time() + 90  # miss TTL ~60 s, not 15 min


def test_resolve_caches_hit_until_expiry():
    creds = object()
    yt = _mk_youtube_client(active_items=[{"id": "BCAST1"}])
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
        # Second call should be cache-hit; the mock client should not be
        # re-invoked.
        yt.liveBroadcasts.reset_mock()
        youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert yt.liveBroadcasts.call_count == 0


def test_resolve_tolerates_http_error_on_active_then_upcoming_succeeds():
    creds = object()
    http_err = HttpError(resp=MagicMock(status=500, reason="err"), content=b"boom")
    yt = _mk_youtube_client(
        upcoming_items=[{"id": "BCAST_UP"}],
        raise_on={"active": http_err},
    )
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, _ = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid == "BCAST_UP"


def test_resolve_returns_none_on_quota_exceeded():
    creds = object()
    http_err = HttpError(resp=MagicMock(status=403, reason="quotaExceeded"), content=b"quota")
    yt = _mk_youtube_client(raise_on={"active": http_err})
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, expiry = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    # 403 short-circuits — no fall-through to upcoming, returns miss-ttl.
    assert bid is None
    assert expiry < time.time() + 90


def test_invalidate_cache_forces_next_call_to_re_resolve():
    creds = object()
    yt = _mk_youtube_client(active_items=[{"id": "BCAST1"}])
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
        youtube_broadcast_resolver.invalidate_cache(creds)
        yt.liveBroadcasts.reset_mock()
        youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert yt.liveBroadcasts.call_count >= 1


def test_publish_broadcast_id_writes_atomically(tmp_path: Path):
    target = tmp_path / "youtube-video-id.txt"
    youtube_broadcast_resolver.publish_broadcast_id(target, "BCAST_XYZ")
    assert target.read_text(encoding="utf-8") == "BCAST_XYZ"


def test_publish_broadcast_id_writes_empty_file_for_none(tmp_path: Path):
    target = tmp_path / "youtube-video-id.txt"
    youtube_broadcast_resolver.publish_broadcast_id(target, None)
    assert target.exists()
    assert target.read_text(encoding="utf-8") == ""


def test_publish_broadcast_id_creates_parent_dirs(tmp_path: Path):
    target = tmp_path / "nested" / "sub" / "youtube-video-id.txt"
    youtube_broadcast_resolver.publish_broadcast_id(target, "X")
    assert target.read_text(encoding="utf-8") == "X"


def test_publish_broadcast_id_no_partial_write_on_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "youtube-video-id.txt"
    target.write_text("PREVIOUS", encoding="utf-8")

    def _boom(*a, **k):
        raise OSError("rename failed")

    monkeypatch.setattr(youtube_broadcast_resolver.os, "replace", _boom)
    with pytest.raises(OSError):
        youtube_broadcast_resolver.publish_broadcast_id(target, "NEW")
    # Previous contents preserved — no partial write leaked through.
    assert target.read_text(encoding="utf-8") == "PREVIOUS"
