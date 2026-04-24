"""Unit tests for agents.content_id_watcher.state."""

from __future__ import annotations

from agents.content_id_watcher.state import VOD_POLL_TTL_S, WatcherState


def test_enroll_vod_idempotent():
    state = WatcherState()
    state.enroll_vod("vid-1", now=1000.0)
    state.enroll_vod("vid-1", now=1500.0)
    # Earlier enrolment time is preserved
    assert state.vod_first_polled_at["vid-1"] == 1000.0


def test_expire_vods_drops_old_entries():
    state = WatcherState()
    state.enroll_vod("vid-old", now=0.0)
    state.enroll_vod("vid-new", now=1000.0)
    state.vod_snapshots["vid-old"] = {"k": "v"}
    expired = state.expire_vods(now=VOD_POLL_TTL_S + 500.0)
    assert "vid-old" in expired
    assert "vid-new" not in expired
    assert "vid-old" not in state.vod_first_polled_at
    assert "vid-old" not in state.vod_snapshots


def test_expire_vods_within_ttl_keeps_entries():
    state = WatcherState()
    state.enroll_vod("vid-1", now=0.0)
    expired = state.expire_vods(now=VOD_POLL_TTL_S - 1.0)
    assert expired == []
    assert "vid-1" in state.vod_first_polled_at


def test_vods_in_queue_returns_oldest_first():
    state = WatcherState()
    state.enroll_vod("vid-newer", now=200.0)
    state.enroll_vod("vid-older", now=100.0)
    queue = state.vods_in_queue()
    assert queue == ("vid-older", "vid-newer")
