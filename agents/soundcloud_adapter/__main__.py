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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.music.provenance import (
    build_music_provenance_token,
    classify_music_provenance,
    is_broadcast_safe,
)

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


def _resolve_client_id_with_source() -> tuple[str | None, str]:
    """Resolve a client_id and report where it came from.

    Returns ``(client_id, source)`` where ``source`` is ``"env"`` (operator
    pinned ``SOUNDCLOUD_CLIENT_ID``), ``"scraped"`` (freshly scraped because
    env was empty), or ``"none"`` (env empty and scrape failed). The source
    drives 401 auto-heal: only an ``"env"`` id is treated as a stale *hint*
    worth re-scraping past (a scraped id is already fresh — re-scraping the
    same bundle yields the same value).
    """
    env_cid = os.environ.get("SOUNDCLOUD_CLIENT_ID", "").strip()
    if env_cid:
        return env_cid, "env"
    scraped = _scrape_client_id()
    if scraped:
        log.info("Scraped fresh SoundCloud client_id (env was empty)")
        return scraped, "scraped"
    return None, "none"


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


@dataclass
class _FetchOutcome:
    """Result of a single source fetch.

    ``failed`` distinguishes a fetch that *errored* (auth/network — the source
    is configured and a client library is present, but the call raised) from a
    genuinely empty success or a stable "no source to fetch" state (no library
    installed, no id configured). Only ``failed`` outcomes protect a non-empty
    last-good playlist from being clobbered with 0 tracks; a genuine empty is
    allowed to empty the file. See ``main``.
    """

    tracks: list[dict[str, Any]] = field(default_factory=list)
    failed: bool = False


def _sclib_resolve_with_retry(client_mod: Any, target: str) -> Any:
    """Resolve a SoundCloud URL via sclib, auto-healing a stale env client_id.

    A pinned/expired ``SOUNDCLOUD_CLIENT_ID`` makes ``api.resolve()`` 401;
    sclib then indexes the bool error body (``obj['kind']``) and raises
    ``TypeError: 'bool' object is not subscriptable``. Either failure — when
    the id came from the *environment* — triggers a single fresh scrape and
    retry: the env id is a hint, not gospel. A non-env (already scraped) id is
    not retried, since re-scraping the same bundle yields the same value. The
    final exception propagates so callers can flag the source failed.
    """
    client_id, source = _resolve_client_id_with_source()
    api = client_mod.SoundcloudAPI(client_id=client_id)
    try:
        return api.resolve(target)
    except Exception:
        if source != "env":
            raise  # already fresh-scraped (or none) — a retry can't help
        fresh = _scrape_client_id()
        if not fresh or fresh == client_id:
            raise
        log.warning(
            "SoundCloud resolve failed with env client_id (likely stale/401); "
            "retrying with a freshly scraped client_id"
        )
        api = client_mod.SoundcloudAPI(client_id=fresh)
        return api.resolve(target)


def _fetch_likes(
    user_id: str,
    *,
    client_spec: tuple[Any, str] | None = None,
    limit: int = 200,
) -> _FetchOutcome:
    """Fetch likes, reporting whether the attempt errored (see _FetchOutcome)."""
    spec = client_spec if client_spec is not None else _try_import_client()
    if spec is None:
        log.warning(
            "No SoundCloud client library available (sclib or soundcloud) — "
            "skipping fetch. Install one locally if you want Phase 1 candidates."
        )
        return _FetchOutcome(tracks=[], failed=False)

    client_mod, flavor = spec
    try:
        if flavor == "sclib":
            user = _sclib_resolve_with_retry(client_mod, f"https://soundcloud.com/{user_id}")
            tracks_attr = getattr(user, "tracks", None) or getattr(user, "likes", None) or []
            return _FetchOutcome(tracks=[_normalize_sclib_track(t) for t in tracks_attr[:limit]])
        if flavor == "soundcloud":
            client = client_mod.Client()  # type: ignore[attr-defined]
            raw = client.get(f"/users/{user_id}/favorites", limit=limit)
            return _FetchOutcome(tracks=[_normalize_soundcloud_track(t) for t in raw])
    except Exception:
        log.warning("SoundCloud fetch failed", exc_info=True)
        return _FetchOutcome(tracks=[], failed=True)
    return _FetchOutcome(tracks=[], failed=False)


def fetch_likes(
    user_id: str,
    *,
    client_spec: tuple[Any, str] | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Fetch the operator's SoundCloud likes as raw dicts.

    Returns an empty list — with a warning logged — when no SoundCloud
    library is installed, so callers degrade gracefully. The candidate
    surfacer treats a missing SoundCloud pool as "local-only". A stale env
    ``SOUNDCLOUD_CLIENT_ID`` that 401s self-heals via a fresh scrape + retry.

    Public endpoints only. No OAuth tokens read or written.
    """
    return _fetch_likes(user_id, client_spec=client_spec, limit=limit).tracks


def _tag_rows(
    raw_tracks: list[Any],
    normalizer: Any,
    extra_tags: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in raw_tracks[:limit]:
        row = normalizer(t)
        for tag in extra_tags:
            if tag not in row["tags"]:
                row["tags"].append(tag)
        out.append(row)
    return out


def _fetch_set(
    url: str,
    *,
    client_spec: tuple[Any, str] | None = None,
    limit: int = 500,
    extra_tags: list[str] | None = None,
) -> _FetchOutcome:
    """Fetch a set, reporting whether the attempt errored (see _FetchOutcome)."""
    if extra_tags is None:
        extra_tags = ["banked"]

    spec = client_spec if client_spec is not None else _try_import_client()
    if spec is None:
        log.warning(
            "No SoundCloud client library available — cannot fetch set from %s",
            url,
        )
        return _FetchOutcome(tracks=[], failed=False)

    client_mod, flavor = spec
    try:
        if flavor == "sclib":
            obj = _sclib_resolve_with_retry(client_mod, url)
            # sclib Playlist exposes .tracks; Track lists return empty
            tracks_attr = getattr(obj, "tracks", None) or []
            return _FetchOutcome(
                tracks=_tag_rows(tracks_attr, _normalize_sclib_track, extra_tags, limit)
            )
        if flavor == "soundcloud":
            client = client_mod.Client()  # type: ignore[attr-defined]
            resolved = client.get("/resolve", url=url)
            raw_tracks = getattr(resolved, "tracks", None) or []
            return _FetchOutcome(
                tracks=_tag_rows(raw_tracks, _normalize_soundcloud_track, extra_tags, limit)
            )
    except Exception:
        log.warning("SoundCloud set fetch failed for %s", url, exc_info=True)
        return _FetchOutcome(tracks=[], failed=True)
    return _FetchOutcome(tracks=[], failed=False)


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
    — callers degrade to likes-only or local-only. A stale env
    ``SOUNDCLOUD_CLIENT_ID`` that 401s self-heals via a fresh scrape + retry.
    """
    return _fetch_set(url, client_spec=client_spec, limit=limit, extra_tags=extra_tags).tracks


def _normalize_sclib_track(t: Any) -> dict[str, Any]:
    """Convert an ``sclib`` Track-ish into a LocalMusicTrack-shaped dict."""
    duration_ms = getattr(t, "duration", 0) or 0
    path = str(getattr(t, "permalink_url", "") or getattr(t, "uri", ""))
    provenance = _soundcloud_provenance_fields(path, getattr(t, "license", None))
    return {
        "path": path,
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
        "broadcast_safe": provenance["broadcast_safe"],
        "whitelist_source": None,
        **provenance,
    }


def _normalize_soundcloud_track(t: Any) -> dict[str, Any]:
    """Convert a ``soundcloud`` python-client dict into our shape."""
    d = t.fields() if hasattr(t, "fields") else dict(t)
    duration_ms = d.get("duration", 0) or 0
    path = str(d.get("permalink_url") or d.get("uri") or "")
    provenance = _soundcloud_provenance_fields(path, d.get("license"))
    return {
        "path": path,
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
        "broadcast_safe": provenance["broadcast_safe"],
        "whitelist_source": None,
        **provenance,
    }


def _soundcloud_provenance_fields(path: str, raw_license: Any) -> dict[str, Any]:
    license_text = str(raw_license).strip() if raw_license is not None else None
    music_provenance, music_license = classify_music_provenance(
        source="soundcloud-oudepode",
        track_id=path,
        license=license_text,
    )
    token = build_music_provenance_token(path, music_provenance)
    has_metadata_license = bool(license_text)
    return {
        "music_provenance": music_provenance,
        "music_license": music_license,
        "provenance_token": token,
        "provenance_source": (
            "soundcloud:license_metadata"
            if has_metadata_license
            else "soundcloud:operator_owned_adapter"
        ),
        "quarantine_reason": None if token and is_broadcast_safe(music_provenance) else "unknown",
        "broadcast_safe": token is not None and is_broadcast_safe(music_provenance),
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


def _existing_track_count(path: Path) -> int:
    """Count non-blank lines (≈ tracks) in an existing repo file; 0 if absent."""
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


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
    by_path: dict[str, dict[str, Any]] = {}
    any_source_failed = False

    if user_id:
        likes = _fetch_likes(user_id, limit=args.limit)
        any_source_failed = any_source_failed or likes.failed
        for row in likes.tracks:
            path = row.get("path") or ""
            if path and path not in by_path:
                by_path[path] = row
        log.info("soundcloud likes: %d tracks", len(by_path))

    if banked_url:
        banked = _fetch_set(banked_url, limit=args.limit)
        any_source_failed = any_source_failed or banked.failed
        for row in banked.tracks:
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
        log.info("soundcloud banked: %d tracks (post-dedup)", len(banked.tracks))

    rows = list(by_path.values())

    # Fail-safe: never clobber a non-empty last-good playlist with 0 tracks
    # because a configured source's fetch *errored* (auth/network). Only a
    # genuine, successful empty result may empty the file. A stale client_id
    # that 401s is auto-healed upstream (scrape + retry); reaching here with an
    # empty-and-failed result means even the fresh scrape failed — so preserve
    # last-good and surface a nonzero exit (systemd OnFailure notifies).
    if not rows and any_source_failed:
        existing = _existing_track_count(SOUNDCLOUD_REPO_PATH)
        if existing:
            log.warning(
                "All SoundCloud fetches failed; preserving last-good playlist "
                "(%d tracks) at %s. Check $SOUNDCLOUD_CLIENT_ID / network.",
                existing,
                SOUNDCLOUD_REPO_PATH,
            )
        else:
            log.warning(
                "All SoundCloud fetches failed and no prior playlist to preserve. "
                "Check $SOUNDCLOUD_CLIENT_ID / network."
            )
        return 1

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
