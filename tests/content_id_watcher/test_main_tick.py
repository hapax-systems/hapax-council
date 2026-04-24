"""Integration tests for agents.content_id_watcher.__main__.tick."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.content_id_watcher.__main__ import tick
from agents.content_id_watcher.salience import (
    KIND_CONTENT_ID_MATCH,
    KIND_LIFECYCLE_COMPLETE,
)
from agents.content_id_watcher.state import WatcherState


def _live_response(broadcast_id: str, **status_overrides) -> dict[str, dict]:
    base = {
        "id": broadcast_id,
        "snippet": {"title": "Live", "description": "desc"},
        "status": {
            "lifeCycleStatus": "live",
            "liveBroadcastPriority": "normal",
            "rejectionReason": None,
            "publicStatsViewable": True,
            "madeForKids": False,
        },
        "contentDetails": {"boundStreamId": "stream-1"},
        "monetizationDetails": {"cuepointSchedule": {"strategy": "off"}},
    }
    base["status"].update(status_overrides)
    return {broadcast_id: base}


def _client_for_live(snapshots: list[dict[str, dict]]) -> MagicMock:
    """Returns a client whose successive ticks see ``snapshots`` in order."""
    client = MagicMock()
    client.enabled = True
    return client


def test_tick_cold_start_emits_no_events(tmp_path: Path) -> None:
    state = WatcherState()
    impingements = tmp_path / "impingements.jsonl"
    snapshots = [_live_response("bx")]
    client = MagicMock(enabled=True)

    with (
        patch(
            "agents.content_id_watcher.__main__.poll_live_broadcasts",
            side_effect=snapshots,
        ),
        patch("agents.content_id_watcher.__main__.poll_archived_video", return_value=None),
        patch("agents.content_id_watcher.emitter._IMPINGEMENT_PATH", impingements),
    ):
        tick(client, state, now=1000.0)

    assert not impingements.exists() or impingements.read_text() == ""
    assert "bx" in state.live_snapshots


def test_tick_detects_lifecycle_complete_and_enrols_vod(tmp_path: Path) -> None:
    state = WatcherState()
    impingements = tmp_path / "impingements.jsonl"

    cold = _live_response("bx")
    completed = _live_response("bx", lifeCycleStatus="complete")
    client = MagicMock(enabled=True)

    with (
        patch(
            "agents.content_id_watcher.__main__.poll_live_broadcasts",
            side_effect=[cold, completed],
        ),
        patch("agents.content_id_watcher.__main__.poll_archived_video", return_value=None),
        patch("agents.content_id_watcher.emitter._IMPINGEMENT_PATH", impingements),
    ):
        tick(client, state, now=1000.0)
        tick(client, state, now=1060.0)

    records = [json.loads(line) for line in impingements.read_text().splitlines()]
    kinds = [r["kind"] for r in records]
    assert KIND_LIFECYCLE_COMPLETE in kinds
    assert "bx" in state.vod_first_polled_at


def test_tick_emits_content_id_match_on_post_archive_vod(tmp_path: Path) -> None:
    state = WatcherState()
    impingements = tmp_path / "impingements.jsonl"
    state.enroll_vod("vid-1", now=1000.0)

    vod_snapshots = [
        {
            "id": "vid-1",
            "snippet": {"title": "VOD"},
            "status": {"rejectionReason": None, "madeForKids": False, "publicStatsViewable": True},
            "contentDetails": {},
            "monetizationDetails": {},
        },
        {
            "id": "vid-1",
            "snippet": {"title": "VOD"},
            "status": {
                "rejectionReason": "copyrightStrike",
                "madeForKids": False,
                "publicStatsViewable": True,
            },
            "contentDetails": {},
            "monetizationDetails": {},
        },
    ]
    client = MagicMock(enabled=True)

    with (
        patch("agents.content_id_watcher.__main__.poll_live_broadcasts", return_value={}),
        patch(
            "agents.content_id_watcher.__main__.poll_archived_video",
            side_effect=vod_snapshots,
        ),
        patch("agents.content_id_watcher.emitter._IMPINGEMENT_PATH", impingements),
    ):
        tick(client, state, now=1100.0)
        tick(client, state, now=1400.0)

    records = [json.loads(line) for line in impingements.read_text().splitlines()]
    kinds = [r["kind"] for r in records]
    assert KIND_CONTENT_ID_MATCH in kinds


def test_tick_quota_exhaustion_does_not_crash(tmp_path: Path) -> None:
    """When poll_live returns empty (silent-skip on quota), tick continues."""
    state = WatcherState()
    impingements = tmp_path / "impingements.jsonl"
    client = MagicMock(enabled=True)

    with (
        patch("agents.content_id_watcher.__main__.poll_live_broadcasts", return_value={}),
        patch("agents.content_id_watcher.__main__.poll_archived_video", return_value=None),
        patch("agents.content_id_watcher.emitter._IMPINGEMENT_PATH", impingements),
    ):
        tick(client, state, now=1000.0)

    assert not impingements.exists() or impingements.read_text() == ""


def test_tick_expires_old_vods(tmp_path: Path) -> None:
    state = WatcherState()
    state.enroll_vod("vid-old", now=0.0)
    client = MagicMock(enabled=True)

    with (
        patch("agents.content_id_watcher.__main__.poll_live_broadcasts", return_value={}),
        patch("agents.content_id_watcher.__main__.poll_archived_video", return_value=None),
    ):
        tick(client, state, now=10000.0)  # well past TTL

    assert "vid-old" not in state.vod_first_polled_at
