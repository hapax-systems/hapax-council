"""SoundCloud → local music repo bridge (task #131, Phase 1 + 2).

Reads the operator's public SoundCloud profile (likes / reposts /
playlists) AND a specific private "banked" set (via secret-token URL),
converts each track into a :class:`LocalMusicTrack` shape, and writes
them to ``~/hapax-state/music-repo/soundcloud.jsonl``. The candidate
surfacer downstream treats local and SoundCloud tracks uniformly —
the ``"soundcloud"`` tag differentiates sources; the ``"banked"`` tag
marks operator-curated tracks from the private banked set.

**Phase 1 caveats (unchanged):**

* **No OAuth.** We pull public endpoints only. Operator sets
  ``HAPAX_SOUNDCLOUD_USER_ID`` (numeric id) or
  ``HAPAX_SOUNDCLOUD_USERNAME`` (vanity slug) in the environment.
* **No auto-play.** Candidate surfacer emits approval prompts;
  the operator must explicitly accept before any playback happens.
* **Optional library.** We try ``sclib`` first, fall back to
  ``soundcloud-api`` (``soundcloud_python``), and if neither is
  installed the adapter logs a warning and exits cleanly — no runtime
  dep added to ``pyproject.toml``.

**Phase 2 additions:**

* ``HAPAX_SOUNDCLOUD_BANKED_URL`` env var — full URL to a SoundCloud set,
  including any ``s-...`` secret token for private sets. When set, the
  adapter fetches that set's tracks in addition to (or instead of, if
  no user id is configured) the user's likes, and tags them with
  ``"banked"`` so downstream candidate surfacers can prefer them.
* Dedup — likes ∪ banked union is deduped by ``path`` (permalink URL).

Usage::

    uv run python -m agents.soundcloud_adapter --auto
    uv run python -m agents.soundcloud_adapter --stats
    uv run python -m agents.soundcloud_adapter --user-id 12345678
    uv run python -m agents.soundcloud_adapter --banked-url 'https://...'
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
    "fetch_set",
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


def _scrape_client_id() -> str | None:
    """Scrape a fresh SoundCloud public-web client_id from sndcdn JS bundles.

    SoundCloud rotates the client_id embedded in its web-app JS bundles.
    sclib's hardcoded id goes stale (HTTP 401 on resolve); the fix is to
    fetch the homepage, follow any of the ``a-v2.sndcdn.com/assets/*.js``
    bundles, and regex-match the current value. Returns the first 32-char
    alphanumeric client_id found, or ``None`` on any scraping failure.
    """
    import re
    import urllib.request

    try:
        req = urllib.request.Request(
            "https://soundcloud.com/",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
        js_urls = re.findall(r"https://a-v2\.sndcdn\.com/assets/[^\"\s]+\.js", html)
        for url in reversed(js_urls):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                js = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
                m = re.search(r'client_id[=:]"([0-9a-zA-Z]{32})"', js)
                if m:
                    return m.group(1)
            except Exception:
                continue
    except Exception:
        log.warning("failed to scrape SoundCloud client_id", exc_info=True)
    return None


def _resolve_client_id() -> str | None:
    """Env → scrape fallback."""
    env_cid = os.environ.get("SOUNDCLOUD_CLIENT_ID", "").strip()
    if env_cid:
        return env_cid
    scraped = _scrape_client_id()
    if scraped:
        log.info("Scraped fresh SoundCloud client_id (env was empty)")
    return scraped


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
            api = client_mod.SoundcloudAPI(client_id=_resolve_client_id())
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


def fetch_set(
    url: str,
    *,
    client_spec: tuple[Any, str] | None = None,
    limit: int = 500,
    extra_tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch tracks from a specific SoundCloud set / playlist URL.

    ``url`` may include a secret token (``?s=...`` or the post-slug
    ``/s-xxxxx`` form) — both ``sclib`` and ``soundcloud-api`` honor
    the secret at resolve time.

    Returns normalized track dicts tagged with ``"soundcloud"`` plus any
    ``extra_tags`` (default: ``["banked"]``). Empty list on any failure
    — callers degrade to likes-only or local-only.
    """
    if extra_tags is None:
        extra_tags = ["banked"]

    spec = client_spec if client_spec is not None else _try_import_client()
    if spec is None:
        log.warning(
            "No SoundCloud client library available — cannot fetch set from %s",
            url,
        )
        return []

    client_mod, flavor = spec
    try:
        if flavor == "sclib":
            api = client_mod.SoundcloudAPI(client_id=_resolve_client_id())
            obj = api.resolve(url)
            # sclib Playlist exposes .tracks; Track lists return empty
            tracks_attr = getattr(obj, "tracks", None) or []
            out: list[dict[str, Any]] = []
            for t in tracks_attr[:limit]:
                row = _normalize_sclib_track(t)
                for tag in extra_tags:
                    if tag not in row["tags"]:
                        row["tags"].append(tag)
                out.append(row)
            return out
        if flavor == "soundcloud":
            client = client_mod.Client()  # type: ignore[attr-defined]
            resolved = client.get("/resolve", url=url)
            raw_tracks = getattr(resolved, "tracks", None) or []
            out = []
            for t in raw_tracks[:limit]:
                row = _normalize_soundcloud_track(t)
                for tag in extra_tags:
                    if tag not in row["tags"]:
                        row["tags"].append(tag)
                out.append(row)
            return out
    except Exception:
        log.warning("SoundCloud set fetch failed for %s", url, exc_info=True)
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
        # Adapter only syncs the operator's OWN SoundCloud catalogue
        # (Oudepode). Without these fields the music programmer's
        # weighted picker treats the records as anonymous "local" source
        # — drops the 1-in-8 oudepode cap and the broadcast-safe gate.
        "source": "soundcloud-oudepode",
        "content_risk": "tier_0_owned",
        "broadcast_safe": True,
        "whitelist_source": None,
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
        # See _normalize_sclib_track for rationale on these fields.
        "source": "soundcloud-oudepode",
        "content_risk": "tier_0_owned",
        "broadcast_safe": True,
        "whitelist_source": None,
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
    parser.add_argument(
        "--banked-url",
        type=str,
        default=None,
        help=(
            "Full SoundCloud set URL (including any s-... secret token). "
            "Falls back to $HAPAX_SOUNDCLOUD_BANKED_URL. Tracks tagged 'banked'."
        ),
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
    banked_url = (
        args.banked_url or os.environ.get("HAPAX_SOUNDCLOUD_BANKED_URL", "").strip() or None
    )

    if not user_id and not banked_url:
        log.error(
            "No SoundCloud source configured. Set $HAPAX_SOUNDCLOUD_USER_ID / "
            "$HAPAX_SOUNDCLOUD_USERNAME (likes) and/or $HAPAX_SOUNDCLOUD_BANKED_URL "
            "(private set). Pass --user-id / --banked-url to override."
        )
        return 2

    started = time.time()
    rows: list[dict[str, Any]] = []
    by_path: dict[str, dict[str, Any]] = {}

    if user_id:
        for row in fetch_likes(user_id, limit=args.limit):
            path = row.get("path") or ""
            if path and path not in by_path:
                by_path[path] = row
        log.info("soundcloud likes: %d tracks", len(by_path))

    if banked_url:
        banked_rows = fetch_set(banked_url, limit=args.limit)
        for row in banked_rows:
            path = row.get("path") or ""
            if not path:
                continue
            if path in by_path:
                # Already have it from likes — add 'banked' tag in place.
                existing_tags = by_path[path].setdefault("tags", [])
                if "banked" not in existing_tags:
                    existing_tags.append("banked")
            else:
                by_path[path] = row
        log.info("soundcloud banked: %d tracks (post-dedup)", len(banked_rows))

    rows = list(by_path.values())
    written = _write_jsonl(SOUNDCLOUD_REPO_PATH, rows)
    dur = time.time() - started
    log.info(
        "soundcloud sync: wrote %d tracks to %s in %.1fs (likes=%s, banked=%s)",
        written,
        SOUNDCLOUD_REPO_PATH,
        dur,
        "yes" if user_id else "no",
        "yes" if banked_url else "no",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
