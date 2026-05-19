"""agents/audience_perception.py — Audience state perception daemon.

Polls audience metrics and writes to /dev/shm/hapax-perception/audience.json.
Currently a stub: reads from a manual override file or falls back to zeros.
When YouTube Data API auth is configured, _poll_youtube_api() will provide
live viewer count, chat rate, and watch time.

Zero external dependencies — stdlib only.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

OUTPUT_DIR = Path("/dev/shm/hapax-perception")
OUTPUT_FILE = OUTPUT_DIR / "audience.json"
OVERRIDE_FILE = OUTPUT_DIR / "audience-override.json"

POLL_INTERVAL_S = 2.0


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _poll_youtube_api() -> dict[str, Any] | None:
    """Poll YouTube Data API for live audience metrics.

    Returns None until YouTube API auth is configured. When implemented,
    returns dict with viewer_count, chat_rate_per_min, avg_watch_time_s,
    and subscriber_delta.
    """
    return None


def _poll_audience() -> dict[str, Any]:
    """Read audience state from override file, YouTube API, or fall back to zeros."""
    # Manual override path — operator can drop a file to simulate audience
    override = _read_json(OVERRIDE_FILE)
    if override is not None:
        return {
            "viewer_count": override.get("viewer_count", 0),
            "chat_rate_per_min": override.get("chat_rate_per_min", 0.0),
            "avg_watch_time_s": override.get("avg_watch_time_s", 0.0),
            "subscriber_delta": override.get("subscriber_delta", 0),
            "source": "override",
        }

    # YouTube API path — stub for now
    yt = _poll_youtube_api()
    if yt is not None:
        yt["source"] = "youtube_api"
        return yt

    # Fallback — no audience data available
    return {
        "viewer_count": 0,
        "chat_rate_per_min": 0.0,
        "avg_watch_time_s": 0.0,
        "subscriber_delta": 0,
        "source": "fallback",
    }


def _write_state(state: dict[str, Any]) -> None:
    """Write audience state to SHM."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(UTC).isoformat()
    tmp = OUTPUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(OUTPUT_FILE)


def run() -> None:
    """Main daemon loop — poll and write every POLL_INTERVAL_S."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log.info("audience_perception daemon starting (poll=%ss)", POLL_INTERVAL_S)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            state = _poll_audience()
            _write_state(state)
        except Exception:
            log.exception("audience poll tick failed")
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    run()
