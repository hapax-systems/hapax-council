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


def _bcast(bid: str, lifecycle: str) -> dict:
    return {"id": bid, "snippet": {}, "status": {"lifeCycleStatus": lifecycle}}


def _mk_youtube_client(items=None, raise_with=None):
    """Build a MagicMock discovery client.

    ``items`` is the full list returned by ``liveBroadcasts.list(mine=true)``;
    resolver filters client-side on ``status.lifeCycleStatus``. ``raise_with``
    is an ``HttpError`` to raise on execute.
    """
    client = MagicMock()
    req = MagicMock()
    if raise_with is not None:
        req.execute.side_effect = raise_with
    else:
        req.execute.return_value = {"items": items or []}
    client.liveBroadcasts.return_value.list.return_value = req
    return client


def test_resolve_returns_live_when_present():
    creds = object()
    yt = _mk_youtube_client(items=[_bcast("BCAST_LIVE", "live")])
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, expiry = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid == "BCAST_LIVE"
    assert expiry > time.time() + 14 * 60  # hit TTL ~15 min


def test_resolve_prefers_live_over_ready():
    # Operator Q1=C: active family (live/liveStarting/testing) wins over
    # upcoming family (ready) even when both present in the same list.
    creds = object()
    yt = _mk_youtube_client(items=[_bcast("READY_BCAST", "ready"), _bcast("LIVE_BCAST", "live")])
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, _ = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid == "LIVE_BCAST"


def test_resolve_falls_through_to_ready():
    creds = object()
    yt = _mk_youtube_client(items=[_bcast("READY_BCAST", "ready")])
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, _ = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid == "READY_BCAST"


def test_resolve_ignores_complete_and_revoked():
    creds = object()
    yt = _mk_youtube_client(items=[_bcast("DONE", "complete"), _bcast("GONE", "revoked")])
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, _ = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid is None


def test_resolve_returns_none_when_no_broadcasts():
    creds = object()
    yt = _mk_youtube_client()
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, expiry = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid is None
    assert expiry < time.time() + 90  # miss TTL ~60 s, not 15 min


def test_resolve_caches_hit_until_expiry():
    creds = object()
    yt = _mk_youtube_client(items=[_bcast("BCAST1", "live")])
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
        # Second call should be cache-hit; the mock client should not be
        # re-invoked.
        yt.liveBroadcasts.reset_mock()
        youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert yt.liveBroadcasts.call_count == 0


def test_resolve_returns_none_on_http_500():
    creds = object()
    http_err = HttpError(resp=MagicMock(status=500, reason="err"), content=b"boom")
    yt = _mk_youtube_client(raise_with=http_err)
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, _ = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid is None


def test_resolve_returns_none_on_quota_exceeded():
    creds = object()
    http_err = HttpError(resp=MagicMock(status=403, reason="quotaExceeded"), content=b"quota")
    yt = _mk_youtube_client(raise_with=http_err)
    with patch.object(youtube_broadcast_resolver, "discovery_build", return_value=yt):
        bid, expiry = youtube_broadcast_resolver.resolve_active_broadcast_id(creds)
    assert bid is None
    assert expiry < time.time() + 90


def test_invalidate_cache_forces_next_call_to_re_resolve():
    creds = object()
    yt = _mk_youtube_client(items=[_bcast("BCAST1", "live")])
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
