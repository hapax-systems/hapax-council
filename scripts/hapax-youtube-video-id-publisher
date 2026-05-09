#!/usr/bin/env python3
"""Publish the current YouTube broadcast id to SHM for chat-monitor.

FINDING-V Phase 5. Unblocks ``scripts/chat-monitor.py::_wait_for_video_id()``
by writing the active broadcast id into
``/dev/shm/hapax-compositor/youtube-video-id.txt`` every 60 s (or
sooner on cache miss). Same atomic tmp+rename pattern as other
compositor SHM producers.

Runs as the ``hapax-youtube-video-id.service`` systemd user unit,
``Before=chat-monitor.service``.

Quota footprint: ``liveBroadcasts.list`` = 1 unit per call, so one tick
per 60 s = 1,440 units/day worst case. The 15 min on-hit cache drops
that by ~15x to ~100 units/day in steady state.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from pathlib import Path

from shared.freshness_gauge import FreshnessGauge
from shared.google_auth import (
    YOUTUBE_STREAMING_TOKEN_PASS_KEY,
    get_google_credentials,
)
from shared.youtube_broadcast_resolver import (
    publish_broadcast_id,
    resolve_active_broadcast_id,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("youtube-video-id-publisher")

_POLL_INTERVAL_SECONDS = 60.0
_VIDEO_ID_PATH = Path("/dev/shm/hapax-compositor/youtube-video-id.txt")
_YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

_shutdown = False


def _handle_signal(signum, frame):  # noqa: ARG001
    global _shutdown
    _shutdown = True
    log.info("signal %d received, draining", signum)


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Prefer the scoped sub-channel token; fall back to the main-account
    # token if the operator hasn't minted the sub-channel token yet.
    # Falling back makes the failure mode observable (liveStreamingNotEnabled
    # 403 on main channel) rather than crashing silently.
    creds = get_google_credentials(
        _YOUTUBE_SCOPES,
        pass_key=YOUTUBE_STREAMING_TOKEN_PASS_KEY,
        interactive=False,
    )
    if creds is None:
        log.warning(
            "no token at %s — falling back to default google/token. "
            "Run `uv run python scripts/mint-google-token.py` to mint the "
            "sub-channel token.",
            YOUTUBE_STREAMING_TOKEN_PASS_KEY,
        )
        creds = get_google_credentials(_YOUTUBE_SCOPES, interactive=False)
    if creds is None:
        log.error("no Google credentials available — cannot resolve broadcast id")
        return 1

    freshness = FreshnessGauge(
        "hapax_ward_producer_youtube_video_id", expected_cadence_s=_POLL_INTERVAL_SECONDS
    )

    last_published: str | None | object = object()  # sentinel → force first write
    while not _shutdown:
        try:
            broadcast_id, _ = resolve_active_broadcast_id(creds)
            if broadcast_id != last_published:
                publish_broadcast_id(_VIDEO_ID_PATH, broadcast_id)
                if broadcast_id is None:
                    log.info("broadcast offline — published empty file")
                else:
                    log.info("broadcast id published: %s", broadcast_id)
                last_published = broadcast_id
            freshness.mark_published()
        except Exception:
            log.exception("tick failed")
            freshness.mark_failed()

        # Sleep in 1 s increments so signal handling is responsive.
        slept = 0.0
        while slept < _POLL_INTERVAL_SECONDS and not _shutdown:
            time.sleep(1.0)
            slept += 1.0

    log.info("shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
