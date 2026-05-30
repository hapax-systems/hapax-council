#!/usr/bin/env python3
"""screwm-oarb-playlist-rotator — RNG-rotate the canonical YouTube playlist (re-homes the director).

The youtube-player (HTTP API on :8055) streams YouTube A/V: video -> /dev/video50, audio ->
hapax-yt-loudnorm -> MPC USB IN 7/8 (AUX6/7). On video-end its slot goes idle; the retired
studio-compositor director used to notice that and dispatch the next random playlist entry.
That rotation stopped when the director was retired. This re-homes it screwm-native:

  poll the player; when a slot is idle, POST /play a fresh random entry (by id) from Oudepode's
  hand-curated canonical playlist  ->  the playlist streams on RNG rotation, audio on USB 7/8.

It also mirrors the current id to youtube-video-id.txt so the OARB sphere (slot 1, aoa_sphere)
shows the same video.

- Playlist resolved via `yt-dlp --flat-playlist`, cached in /dev/shm, refreshed every 6h.
- DEFERS while livestreaming (working-mode == fortress): the operator + the live-broadcast-id
  publisher own the player + the OARB then.
- Never interrupts a playing slot (dispatches only when idle) -> respects a manual
  `youtube-player play <url>` until it finishes.
- Fail-safe throughout: yt-dlp / HTTP errors fall back to the cache or simply retry next poll;
  never crashes.
"""

from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

PLAYLIST_ID = os.environ.get("SCREWM_OARB_PLAYLIST_ID", "PL-4nvD1KwuH--sViEAFY2cHVmS6_B4CQ5")
PLAYLIST_URL = f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"
PLAYER_BASE = os.environ.get("SCREWM_YT_PLAYER_BASE", "http://127.0.0.1:8055")
VIDEO_ID_PATH = Path(
    os.environ.get("SCREWM_OARB_VIDEO_ID_PATH", "/dev/shm/hapax-compositor/youtube-video-id.txt")
)
CACHE_PATH = Path(
    os.environ.get("SCREWM_OARB_CACHE_PATH", "/dev/shm/hapax-compositor/oarb-playlist-ids.json")
)
WORKING_MODE_PATH = Path.home() / ".cache" / "hapax" / "working-mode"
POLL_S = float(os.environ.get("SCREWM_OARB_POLL_S", "12"))
PLAYLIST_REFRESH_S = float(os.environ.get("SCREWM_OARB_PLAYLIST_REFRESH_S", "21600"))  # 6h
_FETCH_TIMEOUT_S = 120
_HTTP_TIMEOUT_S = 5

_STOP = False


def _on_signal(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def _is_livestreaming() -> bool:
    """Defer while livestreaming (fortress): the operator + broadcast-id publisher own YT then."""
    try:
        return WORKING_MODE_PATH.read_text(encoding="utf-8").strip().lower() == "fortress"
    except OSError:
        return False


def _looks_like_video_id(value: str) -> bool:
    return len(value) == 11 and all(c.isalnum() or c in "-_" for c in value)


def _fetch_playlist_ids() -> list[str]:
    try:
        proc = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--no-warnings", "--print", "%(id)s", PLAYLIST_URL],
            capture_output=True,
            text=True,
            timeout=_FETCH_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if _looks_like_video_id(ln.strip())]


def _load_ids(now: float) -> list[str]:
    cached: list[str] = []
    try:
        if CACHE_PATH.exists():
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                cached = [v for v in data if isinstance(v, str) and _looks_like_video_id(v)]
            if cached and (now - CACHE_PATH.stat().st_mtime) < PLAYLIST_REFRESH_S:
                return cached
    except (OSError, ValueError):
        pass
    fresh = _fetch_playlist_ids()
    if fresh:
        try:
            tmp = CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(fresh), encoding="utf-8")
            os.replace(tmp, CACHE_PATH)
        except OSError:
            pass
        return fresh
    return cached  # fetch failed -> ride the cache rather than going dark


def _player_idle() -> bool:
    """True when no player slot is playing. Fail-safe: on HTTP error return False so we do
    NOT dispatch into an unknown/unreachable player state."""
    try:
        with urllib.request.urlopen(PLAYER_BASE + "/status", timeout=_HTTP_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return False
    slots = data if isinstance(data, list) else data.get("slots", [data])
    return not any(isinstance(s, dict) and s.get("playing") for s in slots)


def _player_play(url: str) -> bool:
    try:
        body = json.dumps({"url": url}).encode("utf-8")
        req = urllib.request.Request(
            PLAYER_BASE + "/play",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            resp.read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def _write_video_id(video_id: str) -> None:
    VIDEO_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = VIDEO_ID_PATH.with_suffix(".tmp")
    tmp.write_text(video_id + "\n", encoding="utf-8")
    os.replace(tmp, VIDEO_ID_PATH)


def main() -> int:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    last: str | None = None
    while not _STOP:
        now = time.time()
        if _is_livestreaming():
            time.sleep(min(POLL_S, 30.0))
            continue
        if _player_idle():
            ids = _load_ids(now)
            if ids:
                pool = [v for v in ids if v != last] or ids
                video_id = random.choice(pool)  # noqa: S311 — content shuffle, not crypto
                if _player_play(f"https://www.youtube.com/watch?v={video_id}"):
                    _write_video_id(video_id)
                    last = video_id
        slept = 0.0
        while not _STOP and slept < POLL_S:
            time.sleep(min(2.0, POLL_S - slept))
            slept += 2.0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
