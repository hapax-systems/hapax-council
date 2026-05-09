"""Shared YouTube active-broadcast resolver.

Used by ``scripts/hapax-youtube-video-id-publisher`` (publishes the id into
``/dev/shm/hapax-compositor/youtube-video-id.txt`` so ``chat-monitor``
unblocks) and by ``scripts/hapax-youtube-viewer-count-producer`` (feeds
``videos.list(liveStreamingDetails)``).

Selection policy (operator decision 2026-04-20, FINDING-V Q1 = option C):
prefer ``broadcastStatus=active`` when any is present, else fall through
to newest ``upcoming``. The resolver does NOT filter by channel id —
``mine=true`` on the authenticated creds is sufficient for the single
operator invariant. Adding ``HAPAX_YOUTUBE_CHANNEL_ID`` is a trivial
upgrade when a second authenticated channel ever appears.

Cache policy: 15 min on hit (broadcasts rarely migrate ids mid-run),
60 s on miss (operator goes live mid-session; a long cache would keep
chat-monitor blocked until the window expires).
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from googleapiclient.discovery import build as discovery_build
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)

_HIT_TTL_SECONDS = 15 * 60
_MISS_TTL_SECONDS = 60


@dataclass
class _CacheEntry:
    broadcast_id: str | None
    expires_at: float


_cache: dict[int, _CacheEntry] = {}


def resolve_active_broadcast_id(creds: object) -> tuple[str | None, float]:
    """Return ``(broadcast_id, cache_ttl_expiry_epoch)``.

    ``broadcast_id`` is ``None`` when no active/upcoming broadcast
    exists on the authenticated account. The returned expiry is an
    absolute ``time.time()``-compatible epoch seconds value; callers
    may honour it to avoid burning quota, or discard and retry sooner
    if they need stricter freshness.

    Caching is keyed on ``id(creds)`` so test fixtures can reset state
    by passing a fresh object. Production callers should keep a single
    ``Credentials`` instance for the service lifetime.
    """
    now = time.time()
    cache_key = id(creds)
    entry = _cache.get(cache_key)
    if entry is not None and entry.expires_at > now:
        return entry.broadcast_id, entry.expires_at

    broadcast_id = _resolve_uncached(creds)
    ttl = _HIT_TTL_SECONDS if broadcast_id is not None else _MISS_TTL_SECONDS
    expiry = now + ttl
    _cache[cache_key] = _CacheEntry(broadcast_id, expiry)
    return broadcast_id, expiry


def invalidate_cache(creds: object) -> None:
    """Drop the cache entry for ``creds``.

    Call when a ``videos.list`` or similar downstream call reports the
    broadcast ended (HTTP 404 on the broadcast id) — the cached
    broadcast_id is stale and the resolver should re-hit the API on
    next call.
    """
    _cache.pop(id(creds), None)


def _resolve_uncached(creds: object) -> str | None:
    """Hit the YouTube Data API directly, no caching.

    Returns ``None`` on any failure: HTTP error, no broadcasts, malformed
    response. A single warning is logged per distinct failure mode; the
    caller decides whether to retry (they should, with backoff).

    API shape: ``liveBroadcasts.list`` rejects ``mine=true`` combined with
    ``broadcastStatus`` as of v3 ("incompatibleParameters" 400). Pull
    ``mine=true`` with ``status`` in ``part=`` and filter client-side on
    ``status.lifeCycleStatus``. Selection policy (operator Q1=C): prefer
    ``live``/``liveStarting`` / ``testing`` (active family); fall through
    to ``ready`` (upcoming family); nothing else qualifies.
    """
    try:
        youtube = discovery_build("youtube", "v3", credentials=creds, cache_discovery=False)
    except Exception:
        log.exception("failed to build youtube discovery client")
        return None

    try:
        response = (
            youtube.liveBroadcasts()
            .list(part="id,snippet,status", mine=True, maxResults=50)
            .execute()
        )
    except HttpError as exc:
        if exc.resp.status == 403:
            log.warning("liveBroadcasts.list quotaExceeded or auth failure: %s", exc)
            return None
        log.warning("liveBroadcasts.list HTTP %s: %s", exc.resp.status, exc)
        return None
    except Exception:
        log.exception("liveBroadcasts.list failed")
        return None

    items = response.get("items") or []
    active_family = ("live", "liveStarting", "testing")
    upcoming_family = ("ready",)

    for family in (active_family, upcoming_family):
        for item in items:
            lifecycle = (item.get("status") or {}).get("lifeCycleStatus")
            if lifecycle in family:
                return item.get("id")
    return None


def publish_broadcast_id(path: Path, broadcast_id: str | None) -> None:
    """Write ``broadcast_id`` (or empty file when ``None``) to ``path``
    via tmp+rename.

    The file contents are plain text — a single broadcast id with no
    trailing newline, or an empty file when the broadcast is offline.
    This matches the contract ``scripts/chat-monitor.py::_wait_for_video_id``
    already reads. ``WhosHereCairoSource`` and other readers tolerate
    empty files (decode to empty string, treat as offline).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = broadcast_id if broadcast_id is not None else ""
    tmp_fd, tmp_path_s = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path_s, path)
    except Exception:
        try:
            os.unlink(tmp_path_s)
        except OSError:
            pass
        raise
