"""Bridgy Backfeed inbound-reply consumer — Phase 1.

Bridgy Backfeed (https://brid.gy/) translates Mastodon / Bluesky /
GitHub mentions of the operator's webposts into Webmention-shaped
inbound notifications. Those webmentions arrive at the operator's
omg.lol weblog; this consumer polls the weblog's webmentions surface
and aggregates events into the awareness state's cross_account block.

**Read-only contract.** This consumer NEVER POSTs to ``brid-dot-gy/replies (forbidden)``
or ``/publish-slash-reply (forbidden)``. Operator-mediated replies via daemon are
constitutionally precluded (full-automation-or-nothing: the daemon
cannot stand in for the operator on a conversational reply). A CI
guard regex test pins this contract.

Phase 1 (this PR):
- Pydantic ``BackfeedEvent`` model
- ``poll_omg_lol_webmentions(weblog_address)`` — GET-only fetcher
  (returns []  on missing endpoint / network failure)
- ``parse_webmention_payload(payload)`` — pure decoder
- 24h-rolling counters per platform

Phase 2 will wire the consumer into the awareness aggregator's
30s tick + extend ``CrossAccountBlock`` with the inbound counters.

Spec: drop 6 §3 cross_account category #8.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

log = logging.getLogger(__name__)


BackfeedPlatform = Literal["mastodon", "bluesky", "github"]


@dataclass(frozen=True)
class BackfeedEvent:
    """One inbound reply event from Bridgy Backfeed.

    Anti-anthropomorphization: events are structured (no narrative
    framing). ``excerpt`` caps at 80 chars per spec; longer content
    is truncated at the consumer rather than reshaped into prose.
    """

    timestamp: datetime
    platform: BackfeedPlatform
    author_handle: str
    in_reply_to: str  # weblog entry URL
    excerpt: str  # ≤80 chars


def _classify_platform(source_url: str) -> BackfeedPlatform | None:
    """Classify the originating platform from a webmention source URL."""
    s = source_url.lower()
    if "bsky.app" in s or "bsky.social" in s:
        return "bluesky"
    if "mastodon" in s or "/users/" in s or "/@" in s:
        return "mastodon"
    if "github.com" in s:
        return "github"
    return None


def parse_webmention_payload(payload: dict) -> BackfeedEvent | None:
    """Decode one webmention dict into a BackfeedEvent.

    Tolerates missing fields — webmention shapes vary by source. Returns
    None when the payload doesn't carry the load-bearing fields (timestamp,
    source URL, target URL).
    """
    source = payload.get("source")
    target = payload.get("target")
    ts_raw = payload.get("timestamp") or payload.get("verified_date")
    if not (source and target and ts_raw):
        return None

    platform = _classify_platform(source)
    if platform is None:
        return None

    try:
        timestamp = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        timestamp = datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    author = str(payload.get("author") or payload.get("author_handle") or "?")
    excerpt = str(payload.get("excerpt") or payload.get("content") or "")[:80]

    return BackfeedEvent(
        timestamp=timestamp,
        platform=platform,
        author_handle=author,
        in_reply_to=str(target),
        excerpt=excerpt,
    )


def aggregate_24h_counts(
    events: list[BackfeedEvent], *, now: datetime | None = None
) -> dict[BackfeedPlatform, int]:
    """Count events per platform within the trailing 24h window."""
    cutoff = now or datetime.now(UTC)
    counts: dict[BackfeedPlatform, int] = {"mastodon": 0, "bluesky": 0, "github": 0}
    for event in events:
        delta = cutoff - event.timestamp
        if delta.total_seconds() <= 86400:
            counts[event.platform] += 1
    return counts


def render_dot_grid_compact(counts: dict[BackfeedPlatform, int]) -> str:
    """Format the platform counts as a 1-line tag-string for waybar/sidebar.

    Output shape: ``"M:3 B:1 G:0"`` — Mastodon 3, Bluesky 1, GitHub 0.
    """
    return f"M:{counts.get('mastodon', 0)} B:{counts.get('bluesky', 0)} G:{counts.get('github', 0)}"


def poll_omg_lol_webmentions(weblog_address: str) -> list[BackfeedEvent]:
    """GET-only fetch of inbound webmentions from the operator's weblog.

    Phase 1: returns [] on any network / endpoint failure (the omg.lol
    webmentions surface may not yet be configured for the operator).
    Phase 2 will wire the actual polling once the omg.lol Mailhook /
    webmention endpoint shape is verified.

    NEVER posts to brid-dot-gy/replies (forbidden) or /publish-slash-reply (forbidden). The consumer is
    read-only by constitutional contract.
    """
    log.debug("bridgy_backfeed_consumer: polling weblog=%s (Phase 1 stub)", weblog_address)
    return []


__all__ = [
    "BackfeedEvent",
    "BackfeedPlatform",
    "aggregate_24h_counts",
    "parse_webmention_payload",
    "poll_omg_lol_webmentions",
    "render_dot_grid_compact",
]
