#!/usr/bin/env python3
"""YouTube viewer-count producer — Phase 4 of orphan-ward-producers plan.

Polls the active livestream's `concurrentViewers` count on a 90 s
cadence and publishes the integer to
`/dev/shm/hapax-compositor/youtube-viewer-count.txt`. The compositor's
`WhosHereCairoSource` reads the file with `int(text)` — no JSON, no
trailing newline, write `"0"` when the broadcast is offline.

Quota cost: 1 unit per `videos.list` call (90 s cadence ≈ 960
units/day). Resolver lookup is cached so resolving the broadcast id
adds ~144 units/day (1 unit / `liveBroadcasts.list` * cache misses).

Plan: docs/superpowers/plans/2026-04-20-orphan-ward-producers-plan.md
Phase 4. Spec: same plan §lines 248-295.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from googleapiclient.errors import HttpError

from shared.google_auth import build_service, get_google_credentials
from shared.youtube_broadcast_resolver import (
    invalidate_cache,
    resolve_active_broadcast_id,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("youtube-viewer-count")


VIEWER_COUNT_FILE = Path("/dev/shm/hapax-compositor/youtube-viewer-count.txt")
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# Cadence per plan §lines 263-264. 90 s = 960 units/day quota.
POLL_INTERVAL_S = 90.0
# Cadence when no broadcast is live; matches Phase 4 plan
# (don't burn quota spinning).
OFFLINE_RETRY_S = 30.0


def write_viewer_count(path: Path, count: int) -> None:
    """Atomic write of the viewer count as plain integer text.

    No newline, no JSON wrapper, no `None` literal — the
    WhosHereCairoSource reader does `int(text.strip())`. Atomic via
    tmp + rename so a partial write never reaches the consumer.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(str(int(count)))
    tmp.replace(path)


def fetch_viewer_count(youtube, broadcast_id: str) -> int:
    """Fetch concurrentViewers for a broadcast. Returns 0 on any
    extraction failure or when the field is absent (broadcast offline /
    in pre-roll / post-roll).
    """
    response = youtube.videos().list(part="liveStreamingDetails", id=broadcast_id).execute()
    items = response.get("items", [])
    if not items:
        return 0
    details = items[0].get("liveStreamingDetails", {})
    raw = details.get("concurrentViewers")
    if raw is None:
        return 0
    # The API returns concurrentViewers as a STRING (per plan §line 266);
    # cast carefully.
    try:
        return int(raw)
    except (TypeError, ValueError):
        log.warning("invalid concurrentViewers value %r → treating as 0", raw)
        return 0


def emit_freshness(seconds: float) -> None:
    """Best-effort Prometheus emit. Producer-freshness gauge per plan
    §lines 274-275. Counter creation is lazy so this script can run
    even if prometheus_client isn't installed in the venv.
    """
    try:
        from shared.ward_observability import emit_ward_producer_freshness

        emit_ward_producer_freshness("youtube_viewer_count", seconds)
    except Exception:
        log.debug("ward producer freshness emit failed", exc_info=True)


def run_loop(*, _now=time.time, _sleep=time.sleep, _max_iters: int | None = None) -> None:
    """Main poll loop. ``_now``/``_sleep``/``_max_iters`` exist for
    deterministic testing — production calls run_loop() with defaults."""
    # build_service signature: (api, version, scopes, *, pass_key) — it
    # calls get_google_credentials internally. The Credentials object is
    # still needed for resolve_active_broadcast_id / invalidate_cache.
    creds = get_google_credentials(SCOPES)
    youtube = build_service("youtube", "v3", SCOPES)
    iters = 0
    while _max_iters is None or iters < _max_iters:
        broadcast_id, _ = resolve_active_broadcast_id(creds)
        started = _now()
        if broadcast_id is None:
            write_viewer_count(VIEWER_COUNT_FILE, 0)
            emit_freshness(0.0)
            log.info("no active broadcast; viewer count → 0")
            iters += 1
            if _max_iters is None or iters < _max_iters:
                _sleep(OFFLINE_RETRY_S)
            continue
        try:
            count = fetch_viewer_count(youtube, broadcast_id)
            write_viewer_count(VIEWER_COUNT_FILE, count)
            emit_freshness(_now() - started)
            log.info("viewer count → %d (broadcast %s)", count, broadcast_id)
        except HttpError as e:
            if getattr(e, "resp", None) is not None and getattr(e.resp, "status", 0) == 404:
                log.info("broadcast %s 404; invalidating cache", broadcast_id)
                invalidate_cache(creds)
                write_viewer_count(VIEWER_COUNT_FILE, 0)
            else:
                log.warning("videos.list failed: %s", e)
        except Exception:
            log.warning("viewer count fetch raised; keeping last value", exc_info=True)
        iters += 1
        if _max_iters is None or iters < _max_iters:
            _sleep(POLL_INTERVAL_S)


def main() -> None:
    log.info("youtube-viewer-count-producer starting")
    try:
        run_loop()
    except KeyboardInterrupt:
        log.info("interrupted; exiting")


if __name__ == "__main__":
    main()
