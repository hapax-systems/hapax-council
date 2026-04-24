"""Hapax Content-ID watcher daemon.

Polls ``liveBroadcasts.list`` every 60 s for the operator's active
sub-channel broadcasts; tracks each broadcast that transitions to
``complete`` for an additional hour at 5-min cadence to catch the
post-archive Content-ID rejection window. Detected field changes flow
to the daimonion impingement bus, with a high-salience subset also
firing ntfy.

Run as a systemd user unit (``hapax-content-id-watcher.service``).
Default ``HAPAX_CONTENT_ID_WATCHER_ENABLED=0`` so the daemon ships
disabled until the operator flips the env flag.
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from agents.content_id_watcher.change_detector import detect_changes
from agents.content_id_watcher.emitter import emit_change
from agents.content_id_watcher.poller import poll_archived_video, poll_live_broadcasts
from agents.content_id_watcher.salience import KIND_LIFECYCLE_COMPLETE
from agents.content_id_watcher.state import (
    LIVE_POLL_INTERVAL_S,
    VOD_POLL_INTERVAL_S,
    WatcherState,
)
from shared.youtube_api_client import READONLY_SCOPES, YouTubeApiClient
from shared.youtube_rate_limiter import QuotaBucket

log = logging.getLogger(__name__)

_shutdown = False


def _install_signal_handlers() -> None:
    def _handler(signum, _frame):
        global _shutdown
        log.info("received signal %s — shutting down", signum)
        _shutdown = True

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def _build_client() -> YouTubeApiClient:
    return YouTubeApiClient(scopes=READONLY_SCOPES, rate_limiter=QuotaBucket.default())


def tick(client: YouTubeApiClient, state: WatcherState, *, now: float) -> None:
    """One pass: poll live, diff, emit, then poll any enrolled VODs."""
    new_live = poll_live_broadcasts(client)
    for broadcast_id, snapshot in new_live.items():
        old = state.live_snapshots.get(broadcast_id)
        for event in detect_changes(old, snapshot, broadcast_id=broadcast_id):
            emit_change(event)
            if event.kind == KIND_LIFECYCLE_COMPLETE and event.new_value == "complete":
                state.enroll_vod(broadcast_id, now=now)
        state.live_snapshots[broadcast_id] = snapshot

    for video_id in state.vods_in_queue():
        snapshot = poll_archived_video(client, video_id)
        if snapshot is None:
            continue
        old = state.vod_snapshots.get(video_id)
        for event in detect_changes(old, snapshot, broadcast_id=video_id):
            emit_change(event)
        state.vod_snapshots[video_id] = snapshot

    state.expire_vods(now=now)


def _seconds_until_next_live_tick(last_tick: float) -> float:
    delta = LIVE_POLL_INTERVAL_S - (time.time() - last_tick)
    return max(0.0, delta)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s %(message)s"
    )
    _install_signal_handlers()

    client = _build_client()
    if not client.enabled:
        log.error("YouTube API client could not be enabled — exiting")
        return 1

    state = WatcherState()
    log.info("content_id_watcher started")
    last_live_tick = 0.0
    last_vod_tick = 0.0

    while not _shutdown:
        now = time.time()
        if (now - last_vod_tick) >= VOD_POLL_INTERVAL_S or last_vod_tick == 0.0:
            last_vod_tick = now
        if (now - last_live_tick) >= LIVE_POLL_INTERVAL_S or last_live_tick == 0.0:
            try:
                tick(client, state, now=now)
            except Exception as exc:
                log.exception("tick failed: %s", exc)
            last_live_tick = now
        # Sleep in short slices so SIGTERM is responsive within ~1 s.
        slept = 0.0
        while slept < _seconds_until_next_live_tick(last_live_tick) and not _shutdown:
            time.sleep(min(1.0, _seconds_until_next_live_tick(last_live_tick)))
            slept += 1.0

    log.info("content_id_watcher exiting cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
