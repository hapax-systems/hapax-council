"""SoundCloud → local music repo bridge (task #131, Phase 1).

Reads the operator's public SoundCloud profile (likes / reposts /
playlists), converts each track into a :class:`LocalMusicTrack` shape,
and writes them to ``~/hapax-state/music-repo/soundcloud.jsonl``. The
candidate surfacer downstream treats local and SoundCloud tracks
uniformly — the ``"soundcloud"`` tag differentiates sources.

**Phase 1 caveats:**

* **No OAuth.** We pull public endpoints only. Operator sets
  ``HAPAX_SOUNDCLOUD_USER_ID`` (numeric id) or
  ``HAPAX_SOUNDCLOUD_USERNAME`` (vanity slug) in the environment.
* **No auto-play.** Candidate surfacer emits approval prompts;
  the operator must explicitly accept before any playback happens.
* **Optional library.** We try ``sclib`` first, fall back to
  ``soundcloud-api`` (``soundcloud_python``), and if neither is
  installed the adapter logs a warning and exits cleanly — no runtime
  dep added to ``pyproject.toml``.

Usage::

    uv run python -m agents.soundcloud_adapter --auto
    uv run python -m agents.soundcloud_adapter --stats
    uv run python -m agents.soundcloud_adapter --user-id 12345678
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

__all__ = [
    "SOUNDCLOUD_REPO_PATH",
    "fetch_likes",
    "main",
]

log = logging.getLogger(__name__)

SOUNDCLOUD_REPO_PATH: Path = Path.home() / "hapax-state" / "music-repo" / "soundcloud.jsonl"


def _try_import_client() -> tuple[Any, str] | None:
    """Return (client_module, flavor) or ``None`` when no SC lib is installed."""
    try:
        import sclib  # type: ignore[import-untyped]

        return sclib, "sclib"
    except ImportError:
        pass
    try:
        import soundcloud  # type: ignore[import-untyped]

        return soundcloud, "soundcloud"
    except ImportError:
        pass
    return None


def _resolve_user_id(args: argparse.Namespace) -> str | None:
    """Pick the operator's SoundCloud identifier from args → env."""
    if args.user_id:
        return str(args.user_id)
    env_id = os.environ.get("HAPAX_SOUNDCLOUD_USER_ID")
    if env_id:
        return env_id.strip()
    # Username (vanity slug) fallback — resolve lazily in fetch_likes
    env_name = os.environ.get("HAPAX_SOUNDCLOUD_USERNAME")
    if env_name:
        return env_name.strip()
    return None


def fetch_likes(
    user_id: str,
    *,
    client_spec: tuple[Any, str] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Fetch the operator's SoundCloud likes as raw dicts.

    Returns an empty list — with a warning logged — when no SoundCloud
    library is installed, so callers degrade gracefully. The candidate
    surfacer treats a missing SoundCloud pool as "local-only".

    Public endpoints only. No OAuth tokens read or written.
    """
    spec = client_spec if client_spec is not None else _try_import_client()
    if spec is None:
        log.warning(
            "No SoundCloud client library available (sclib or soundcloud) — "
            "skipping fetch. Install one locally if you want Phase 1 candidates."
        )
        return []

    client_mod, flavor = spec
    try:
        if flavor == "sclib":
            api = client_mod.SoundcloudAPI()
            user = api.resolve(f"https://soundcloud.com/{user_id}")
            tracks_attr = getattr(user, "tracks", None) or getattr(user, "likes", None) or []
            out: list[dict[str, Any]] = []
            for t in tracks_attr[:limit]:
                out.append(_normalize_sclib_track(t))
            return out
        if flavor == "soundcloud":
            client = client_mod.Client()  # type: ignore[attr-defined]
            raw = client.get(f"/users/{user_id}/favorites", limit=limit)
            return [_normalize_soundcloud_track(t) for t in raw]
    except Exception:
        log.warning("SoundCloud fetch failed", exc_info=True)
        return []
    return []


def _normalize_sclib_track(t: Any) -> dict[str, Any]:
    """Convert an ``sclib`` Track-ish into a LocalMusicTrack-shaped dict."""
    duration_ms = getattr(t, "duration", 0) or 0
    return {
        "path": str(getattr(t, "permalink_url", "") or getattr(t, "uri", "")),
        "title": str(getattr(t, "title", "") or "unknown"),
        "artist": str(getattr(t, "artist", "") or "unknown"),
        "album": "",
        "duration_s": max(float(duration_ms) / 1000.0, 1.0),
        "tags": ["soundcloud"] + _split_tags(getattr(t, "genre", "") or ""),
        "energy": 0.5,
        "bpm": None,
        "last_played_ts": None,
        "play_count": 0,
    }


def _normalize_soundcloud_track(t: Any) -> dict[str, Any]:
    """Convert a ``soundcloud`` python-client dict into our shape."""
    d = t.fields() if hasattr(t, "fields") else dict(t)
    duration_ms = d.get("duration", 0) or 0
    return {
        "path": str(d.get("permalink_url") or d.get("uri") or ""),
        "title": str(d.get("title") or "unknown"),
        "artist": str((d.get("user") or {}).get("username") or "unknown"),
        "album": "",
        "duration_s": max(float(duration_ms) / 1000.0, 1.0),
        "tags": ["soundcloud"] + _split_tags(str(d.get("genre") or "")),
        "energy": 0.5,
        "bpm": None,
        "last_played_ts": None,
        "play_count": 0,
    }


def _split_tags(raw: str) -> list[str]:
    if not raw:
        return []
    return [s.strip().lower() for s in raw.replace(";", ",").split(",") if s.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    """Persist rows atomically (tmp + rename). Returns count written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    lines = [json.dumps(r, sort_keys=True) for r in rows]
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    tmp.replace(path)
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SoundCloud adapter — Phase 1 metadata sync for task #131."
    )
    parser.add_argument("--auto", action="store_true", help="Run one sync pass and exit.")
    parser.add_argument("--stats", action="store_true", help="Print existing repo stats.")
    parser.add_argument(
        "--user-id",
        type=str,
        default=None,
        help=(
            "SoundCloud user id / vanity slug override. "
            "Falls back to $HAPAX_SOUNDCLOUD_USER_ID or $HAPAX_SOUNDCLOUD_USERNAME."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max number of tracks to pull from the public profile.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.stats:
        if SOUNDCLOUD_REPO_PATH.exists():
            count = sum(1 for _ in SOUNDCLOUD_REPO_PATH.read_text().splitlines() if _.strip())
            print(f"soundcloud.jsonl: {count} tracks at {SOUNDCLOUD_REPO_PATH}")
        else:
            print(f"soundcloud.jsonl: missing ({SOUNDCLOUD_REPO_PATH})")
        return 0

    user_id = _resolve_user_id(args)
    if not user_id:
        log.error(
            "No SoundCloud user id. Set $HAPAX_SOUNDCLOUD_USER_ID "
            "or $HAPAX_SOUNDCLOUD_USERNAME (or pass --user-id)."
        )
        return 2

    started = time.time()
    rows = fetch_likes(user_id, limit=args.limit)
    written = _write_jsonl(SOUNDCLOUD_REPO_PATH, rows)
    dur = time.time() - started
    log.info(
        "soundcloud sync: wrote %d tracks to %s in %.1fs",
        written,
        SOUNDCLOUD_REPO_PATH,
        dur,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
