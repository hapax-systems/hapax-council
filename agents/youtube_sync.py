"""YouTube RAG sync — subscriptions, likes, and playlists.

Captures YouTube engagement signals for profiler and scout integration.
Watch history is limited via API; syncs liked videos and subscriptions reliably.

Usage:
    uv run python -m agents.youtube_sync --auth        # OAuth consent
    uv run python -m agents.youtube_sync --full-sync    # Full sync
    uv run python -m agents.youtube_sync --auto         # Incremental sync
    uv run python -m agents.youtube_sync --stats        # Show sync state
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".cache" / "youtube-sync"
STATE_FILE = CACHE_DIR / "state.json"
PROFILE_FACTS_FILE = CACHE_DIR / "youtube-profile-facts.jsonl"
CHANGES_LOG = CACHE_DIR / "changes.jsonl"
RAG_SOURCES = Path.home() / "documents" / "rag-sources"
YOUTUBE_DIR = RAG_SOURCES / "youtube"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
]

MAX_LIKED_VIDEOS = 200
RAG_RECENT_COUNT = 50


# ── Schemas ──────────────────────────────────────────────────────────────────


class LikedVideo(BaseModel):
    """A liked YouTube video."""

    video_id: str
    title: str
    channel: str
    published_at: str = ""
    liked_at: str = ""
    category: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    duration: str = ""
    view_count: int = 0


class Subscription(BaseModel):
    """A YouTube channel subscription."""

    channel_id: str
    channel_name: str
    description: str = ""
    subscribed_at: str = ""
    video_count: int = 0


class PlaylistInfo(BaseModel):
    """A YouTube playlist."""

    playlist_id: str
    title: str
    video_count: int = 0
    description: str = ""


class YouTubeSyncState(BaseModel):
    """Persistent sync state."""

    liked_videos: dict[str, LikedVideo] = Field(default_factory=dict)
    subscriptions: dict[str, Subscription] = Field(default_factory=dict)
    playlists: dict[str, PlaylistInfo] = Field(default_factory=dict)
    last_full_sync: float = 0.0
    last_sync: float = 0.0
    stats: dict[str, int] = Field(default_factory=dict)


# ── Auth ────────────────────────────────────────────────────────────────────


def _get_youtube_service():
    """Build authenticated YouTube Data API service."""
    from shared.google_auth import build_service

    return build_service("youtube", "v3", SCOPES)


# ── State Management ─────────────────────────────────────────────────────────


def _load_state(path: Path = STATE_FILE) -> YouTubeSyncState:
    """Load sync state from disk."""
    if path.exists():
        try:
            return YouTubeSyncState.model_validate_json(path.read_text())
        except Exception as exc:
            log.warning("Corrupt state file, starting fresh: %s", exc)
    return YouTubeSyncState()


def _save_state(state: YouTubeSyncState, path: Path = STATE_FILE) -> None:
    """Persist sync state to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    tmp.rename(path)


# ── Behavioral Logging ──────────────────────────────────────────────────────


def _log_change(change_type: str, name: str, extra: dict | None = None) -> None:
    """Append behavioral change event to JSONL log."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry: dict = {
        "change_type": change_type,
        "name": name,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if extra:
        entry.update(extra)
    with open(CHANGES_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    log.debug("Logged change: %s — %s", change_type, name)


# ── Formatting ──────────────────────────────────────────────────────────────


def _format_liked_video_markdown(v: LikedVideo) -> str:
    """Format a liked video as a markdown document for RAG ingestion."""
    try:
        dt = datetime.fromisoformat(v.published_at.replace("Z", "+00:00"))
        ts_frontmatter = dt.strftime("%Y-%m-%dT%H:%M:%S")
        date_display = dt.strftime("%a %b %d, %Y")
    except (ValueError, TypeError, AttributeError):
        ts_frontmatter = v.published_at
        date_display = v.published_at

    tags_str = "[" + ", ".join(v.tags) + "]" if v.tags else "[]"
    desc_block = f"\n\n{v.description}" if v.description else ""

    return f"""---
platform: google
service: youtube
content_type: liked_video
source_service: youtube
source_platform: google
record_id: {v.video_id}
timestamp: {ts_frontmatter}
modality_tags: [video, entertainment]
category: {v.category}
tags: {tags_str}
---

# {v.title}

**Channel:** {v.channel}
**Published:** {date_display}
**Category:** {v.category or "unknown"}
**Duration:** {v.duration or "unknown"}
**Views:** {v.view_count:,}
**Link:** https://www.youtube.com/watch?v={v.video_id}{desc_block}
"""


def _format_subscriptions_markdown(subs: list[Subscription]) -> str:
    """Format all subscriptions as a single markdown document."""
    lines = [
        "---",
        "platform: google",
        "service: youtube",
        "content_type: subscriptions_list",
        "source_service: youtube",
        "source_platform: google",
        "modality_tags: [social, entertainment]",
        f"subscription_count: {len(subs)}",
        "---",
        "",
        "# YouTube Subscriptions",
        "",
        f"Total: {len(subs)} channels",
        "",
    ]
    for s in sorted(subs, key=lambda x: x.channel_name.lower()):
        desc = f" — {s.description}" if s.description else ""
        count = f" ({s.video_count} videos)" if s.video_count else ""
        lines.append(f"- **{s.channel_name}**{count}{desc}")

    lines.append("")
    return "\n".join(lines)


# ── API Sync Operations ─────────────────────────────────────────────────────


def _sync_liked_videos(service, state: YouTubeSyncState) -> int:
    """Sync liked videos from YouTube API. Returns count of new likes."""
    log.info("Syncing liked videos...")
    new_count = 0
    page_token = None
    total_fetched = 0

    while total_fetched < MAX_LIKED_VIDEOS:
        resp = (
            service.videos()
            .list(
                part="snippet,contentDetails,statistics",
                myRating="like",
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )

        for item in resp.get("items", []):
            vid = item["id"]
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})
            stats = item.get("statistics", {})

            if vid not in state.liked_videos:
                new_count += 1
                _log_change("liked", snippet.get("title", vid), {"video_id": vid})

            state.liked_videos[vid] = LikedVideo(
                video_id=vid,
                title=snippet.get("title", ""),
                channel=snippet.get("channelTitle", ""),
                published_at=snippet.get("publishedAt", ""),
                category=snippet.get("categoryId", ""),
                description=snippet.get("description", ""),
                tags=snippet.get("tags", []),
                duration=content.get("duration", ""),
                view_count=int(stats.get("viewCount", 0)),
            )
            total_fetched += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    log.info("Liked videos: %d total, %d new", len(state.liked_videos), new_count)
    return new_count


def _sync_subscriptions(service, state: YouTubeSyncState) -> int:
    """Sync subscriptions from YouTube API. Returns count of changes."""
    log.info("Syncing subscriptions...")
    old_ids = set(state.subscriptions.keys())
    new_subs: dict[str, Subscription] = {}
    page_token = None

    while True:
        resp = (
            service.subscriptions()
            .list(
                part="snippet",
                mine=True,
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )

        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            res = snippet.get("resourceId", {})
            channel_id = res.get("channelId", "")
            if not channel_id:
                continue

            new_subs[channel_id] = Subscription(
                channel_id=channel_id,
                channel_name=snippet.get("title", ""),
                description=snippet.get("description", ""),
                subscribed_at=snippet.get("publishedAt", ""),
            )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    new_ids = set(new_subs.keys())
    added = new_ids - old_ids
    removed = old_ids - new_ids

    for ch_id in added:
        _log_change("subscribed", new_subs[ch_id].channel_name, {"channel_id": ch_id})
    for ch_id in removed:
        name = state.subscriptions[ch_id].channel_name
        _log_change("unsubscribed", name, {"channel_id": ch_id})

    state.subscriptions = new_subs
    changes = len(added) + len(removed)
    log.info(
        "Subscriptions: %d total, %d added, %d removed", len(new_subs), len(added), len(removed)
    )
    return changes


def _sync_playlists(service, state: YouTubeSyncState) -> int:
    """Sync playlists from YouTube API. Returns count of playlists."""
    log.info("Syncing playlists...")
    new_playlists: dict[str, PlaylistInfo] = {}
    page_token = None

    while True:
        resp = (
            service.playlists()
            .list(
                part="snippet,contentDetails",
                mine=True,
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )

        for item in resp.get("items", []):
            pid = item["id"]
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})

            new_playlists[pid] = PlaylistInfo(
                playlist_id=pid,
                title=snippet.get("title", ""),
                description=snippet.get("description", ""),
                video_count=content.get("itemCount", 0),
            )

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    state.playlists = new_playlists
    log.info("Playlists: %d total", len(new_playlists))
    return len(new_playlists)


def _full_sync(service, state: YouTubeSyncState) -> dict[str, int]:
    """Run full sync of all YouTube data. Returns summary counts."""
    new_likes = _sync_liked_videos(service, state)
    sub_changes = _sync_subscriptions(service, state)
    playlist_count = _sync_playlists(service, state)

    state.last_full_sync = time.time()
    state.last_sync = time.time()
    state.stats = {
        "liked_videos": len(state.liked_videos),
        "subscriptions": len(state.subscriptions),
        "playlists": len(state.playlists),
    }

    return {
        "new_likes": new_likes,
        "sub_changes": sub_changes,
        "playlists": playlist_count,
    }


# ── File Writing ─────────────────────────────────────────────────────────────


def _write_youtube_files(state: YouTubeSyncState) -> None:
    """Write liked videos and subscriptions as markdown for RAG ingestion."""
    likes_dir = YOUTUBE_DIR / "liked"
    likes_dir.mkdir(parents=True, exist_ok=True)

    # Write recent liked videos (most recent first by published_at)
    sorted_likes = sorted(
        state.liked_videos.values(),
        key=lambda v: v.published_at or "",
        reverse=True,
    )[:RAG_RECENT_COUNT]

    written = 0
    for v in sorted_likes:
        safe_title = v.title.replace("/", "_").replace("\\", "_")[:80]
        path = likes_dir / f"{v.video_id}_{safe_title}.md"
        content = _format_liked_video_markdown(v)
        path.write_text(content, encoding="utf-8")
        written += 1

    log.info("Wrote %d liked video files to %s", written, likes_dir)

    # Write subscriptions as a single file
    if state.subscriptions:
        YOUTUBE_DIR.mkdir(parents=True, exist_ok=True)
        subs_path = YOUTUBE_DIR / "subscriptions.md"
        content = _format_subscriptions_markdown(list(state.subscriptions.values()))
        subs_path.write_text(content, encoding="utf-8")
        log.info("Wrote subscriptions to %s", subs_path)


# ── Profiler Integration ─────────────────────────────────────────────────────


def _generate_profile_facts(state: YouTubeSyncState) -> list[dict]:
    """Generate deterministic profile facts from YouTube state."""
    from collections import Counter

    facts: list[dict] = []
    source = "youtube-sync:youtube-profile-facts"

    # Topic interests from tags across liked videos
    tag_counts: Counter[str] = Counter()
    channel_counts: Counter[str] = Counter()

    for v in state.liked_videos.values():
        for tag in v.tags:
            tag_counts[tag.lower()] += 1
        channel_counts[v.channel] += 1

    if tag_counts:
        top_tags = ", ".join(t for t, _ in tag_counts.most_common(15))
        facts.append(
            {
                "dimension": "information_seeking",
                "key": "topic_interests",
                "value": top_tags,
                "confidence": 0.85,
                "source": source,
                "evidence": f"Top tags across {len(state.liked_videos)} liked videos",
            }
        )

    if channel_counts:
        top_channels = ", ".join(ch for ch, _ in channel_counts.most_common(10))
        facts.append(
            {
                "dimension": "information_seeking",
                "key": "favorite_channels",
                "value": top_channels,
                "confidence": 0.85,
                "source": source,
                "evidence": f"Most-liked channels across {len(state.liked_videos)} videos",
            }
        )

    # Subscription-based interests
    if state.subscriptions:
        sub_names = ", ".join(
            s.channel_name
            for s in sorted(
                state.subscriptions.values(),
                key=lambda s: s.channel_name.lower(),
            )[:20]
        )
        facts.append(
            {
                "dimension": "information_seeking",
                "key": "subscriptions",
                "value": sub_names,
                "confidence": 0.90,
                "source": source,
                "evidence": f"Active subscriptions ({len(state.subscriptions)} channels)",
            }
        )

    return facts


def _write_profile_facts(state: YouTubeSyncState) -> None:
    """Write profile facts JSONL for profiler bridge consumption."""
    facts = _generate_profile_facts(state)
    if not facts:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_FACTS_FILE, "w", encoding="utf-8") as fh:
        for fact in facts:
            fh.write(json.dumps(fact) + "\n")
    log.info("Wrote %d profile facts to %s", len(facts), PROFILE_FACTS_FILE)


# ── Stats ────────────────────────────────────────────────────────────────────


def _print_stats(state: YouTubeSyncState) -> None:
    """Print sync statistics."""
    from collections import Counter

    print("YouTube Sync State")
    print("=" * 40)
    print(f"Liked videos:    {len(state.liked_videos):,}")
    print(f"Subscriptions:   {len(state.subscriptions):,}")
    print(f"Playlists:       {len(state.playlists):,}")
    print(
        f"Last full sync:  {datetime.fromtimestamp(state.last_full_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_full_sync else 'never'}"
    )
    print(
        f"Last sync:       {datetime.fromtimestamp(state.last_sync, tz=UTC).strftime('%Y-%m-%d %H:%M UTC') if state.last_sync else 'never'}"
    )

    if state.liked_videos:
        tag_counts: Counter[str] = Counter()
        for v in state.liked_videos.values():
            for tag in v.tags:
                tag_counts[tag.lower()] += 1
        if tag_counts:
            print("\nTop tags:")
            for tag, count in tag_counts.most_common(10):
                print(f"  {tag}: {count}")

    if state.playlists:
        print("\nPlaylists:")
        for p in state.playlists.values():
            print(f"  {p.title} ({p.video_count} videos)")


# ── Orchestration ────────────────────────────────────────────────────────────


def run_auth() -> None:
    """Interactive OAuth consent flow."""
    print("Authenticating with YouTube...")
    service = _get_youtube_service()
    resp = service.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items", [])
    if items:
        title = items[0]["snippet"]["title"]
        print(f"Authenticated as: {title}")
    else:
        print("Authenticated (no channel found)")
    print("Token saved to pass store.")


def run_full_sync() -> None:
    """Full sync of all YouTube data."""
    from shared.notify import send_notification

    service = _get_youtube_service()
    state = _load_state()

    summary = _full_sync(service, state)
    _save_state(state)
    _write_youtube_files(state)
    _write_profile_facts(state)

    msg = (
        f"YouTube sync: {len(state.liked_videos)} likes "
        f"({summary['new_likes']} new), "
        f"{len(state.subscriptions)} subs "
        f"({summary['sub_changes']} changes), "
        f"{summary['playlists']} playlists"
    )
    log.info(msg)
    send_notification("YouTube Sync", msg, tags=["cloud"])


def run_auto() -> None:
    """Auto sync — YouTube has no delta API, so this runs a full sync."""
    run_full_sync()


def run_stats() -> None:
    """Display sync statistics."""
    state = _load_state()
    if not state.liked_videos and not state.subscriptions:
        print("No sync state found. Run --full-sync first.")
        return
    _print_stats(state)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube RAG sync")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--auth", action="store_true", help="Run OAuth consent flow")
    group.add_argument("--full-sync", action="store_true", help="Full YouTube sync")
    group.add_argument("--auto", action="store_true", help="Auto sync (full, no delta API)")
    group.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="youtube-sync", level="DEBUG" if args.verbose else None)

    if args.auth:
        run_auth()
    elif args.full_sync:
        run_full_sync()
    elif args.auto:
        run_auto()
    elif args.stats:
        run_stats()


if __name__ == "__main__":
    main()
