"""youtube.py — Parser for YouTube and YouTube Music full export.

Handles the "YouTube and YouTube Music/" Takeout folder which contains:
- history/watch-history.html — watch history (outer-cell format)
- history/search-history.html — search history (outer-cell format)
- subscriptions/subscriptions.csv — channel subscriptions
- playlists/*.csv — playlist contents (Video ID, timestamp)
"""

from __future__ import annotations

import csv
import io
import logging
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.youtube")

# Timestamp format in watch/search history HTML
_TS_PATTERN = re.compile(r"(\w{3} \d{1,2}, \d{4}, \d{1,2}:\d{2}:\d{2}\s*(?:AM|PM)?\s*\w*)")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse YouTube and YouTube Music full export."""
    prefix_options = [
        f"Takeout/{config.takeout_path}/",
        f"{config.takeout_path}/",
    ]

    files_by_type: dict[str, list[str]] = {
        "watch": [],
        "search": [],
        "subscription": [],
        "playlist": [],
    }

    for name in zf.namelist():
        for prefix in prefix_options:
            if not name.startswith(prefix):
                continue
            rel = name[len(prefix) :]
            if rel == "history/watch-history.html":
                files_by_type["watch"].append(name)
            elif rel == "history/search-history.html":
                files_by_type["search"].append(name)
            elif rel == "subscriptions/subscriptions.csv":
                files_by_type["subscription"].append(name)
            elif rel.startswith("playlists/") and rel.endswith("-videos.csv"):
                files_by_type["playlist"].append(name)
            break

    for f in files_by_type["watch"]:
        yield from _parse_watch_history(zf, f, config)

    for f in files_by_type["search"]:
        yield from _parse_search_history(zf, f, config)

    for f in files_by_type["subscription"]:
        yield from _parse_subscriptions(zf, f, config)

    for f in files_by_type["playlist"]:
        yield from _parse_playlist(zf, f, config)


def _parse_watch_history(
    zf: zipfile.ZipFile,
    path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse watch-history.html — structured entries with video URLs and channels."""
    try:
        raw = zf.read(path).decode("utf-8", errors="replace")
    except KeyError:
        return

    entries = re.split(r'<div class="outer-cell', raw)
    log.info("  watch-history: %d entries", len(entries) - 1)

    for entry in entries[1:]:
        # Extract video URL and title
        video_match = re.search(
            r'Watched\s+<a href="(https://www\.youtube\.com/watch\?v=[^"]+)">([^<]+)</a>',
            entry,
        )
        if not video_match:
            continue

        url = video_match.group(1)
        title = _decode_html(video_match.group(2))

        # Extract channel
        channel_match = re.search(
            r'<a href="https://www\.youtube\.com/channel/[^"]+">([^<]+)</a>',
            entry,
        )
        channel = _decode_html(channel_match.group(1)) if channel_match else ""

        timestamp = _extract_timestamp(entry)

        text_parts = [f"Watched: {title}"]
        if channel:
            text_parts.append(f"Channel: {channel}")
        text_parts.append(url)

        source_key = url + (timestamp.isoformat() if timestamp else "")
        record_id = make_record_id("google", "youtube", source_key)

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="youtube_full",
            title=f"Watched: {title}",
            text="\n".join(text_parts),
            content_type="video_watch",
            timestamp=timestamp,
            modality_tags=list(config.modality_defaults),
            structured_fields={"url": url, "channel": channel, "type": "watch"},
            data_path="structured",
            source_path=path,
        )


def _parse_search_history(
    zf: zipfile.ZipFile,
    path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse search-history.html — YouTube search queries."""
    try:
        raw = zf.read(path).decode("utf-8", errors="replace")
    except KeyError:
        return

    entries = re.split(r'<div class="outer-cell', raw)
    log.info("  search-history: %d entries", len(entries) - 1)

    for entry in entries[1:]:
        # Extract search query
        search_match = re.search(r"Searched for\s+(.+?)(?:<br|$)", entry)
        if not search_match:
            continue

        query = _decode_html(re.sub(r"<[^>]+>", "", search_match.group(1)).strip())
        if not query:
            continue

        timestamp = _extract_timestamp(entry)

        source_key = f"search:{query}:{timestamp.isoformat() if timestamp else ''}"
        record_id = make_record_id("google", "youtube", source_key)

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="youtube_full",
            title=f"YouTube search: {query}",
            text=query,
            content_type="search_query",
            timestamp=timestamp,
            modality_tags=["text", "behavioral", "temporal"],
            structured_fields={"query": query, "type": "search"},
            data_path="structured",
            source_path=path,
        )


def _parse_subscriptions(
    zf: zipfile.ZipFile,
    path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse subscriptions.csv — channel subscriptions."""
    try:
        raw = zf.read(path).decode("utf-8", errors="replace")
    except KeyError:
        return

    reader = csv.DictReader(io.StringIO(raw))
    count = 0
    for row in reader:
        channel_id = row.get("Channel Id", "")
        channel_title = row.get("Channel Title", "")
        channel_url = row.get("Channel Url", "")

        if not channel_title:
            continue

        source_key = f"sub:{channel_id}"
        record_id = make_record_id("google", "youtube", source_key)

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="youtube_full",
            title=f"Subscribed: {channel_title}",
            text=f"YouTube subscription: {channel_title}",
            content_type="subscription",
            modality_tags=["media", "behavioral"],
            structured_fields={
                "channel_id": channel_id,
                "channel_title": channel_title,
                "channel_url": channel_url,
                "type": "subscription",
            },
            data_path="structured",
            source_path=path,
        )
        count += 1

    log.info("  subscriptions: %d channels", count)


def _parse_playlist(
    zf: zipfile.ZipFile,
    path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse playlist CSV — video IDs with timestamps."""
    try:
        raw = zf.read(path).decode("utf-8", errors="replace")
    except KeyError:
        return

    # Extract playlist name from filename: "Music-videos.csv" → "Music"
    import os

    basename = os.path.basename(path)
    playlist_name = basename.replace("-videos.csv", "").replace("-videos(1).csv", "")

    reader = csv.DictReader(io.StringIO(raw))
    count = 0
    for row in reader:
        video_id = row.get("Video ID", "")
        ts_str = row.get("Playlist Video Creation Timestamp", "")

        if not video_id:
            continue

        timestamp = None
        if ts_str:
            try:
                timestamp = datetime.fromisoformat(ts_str).replace(tzinfo=None)
            except ValueError:
                pass

        url = f"https://www.youtube.com/watch?v={video_id}"
        source_key = f"playlist:{playlist_name}:{video_id}"
        record_id = make_record_id("google", "youtube", source_key)

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="youtube_full",
            title=f"Playlist [{playlist_name}]: {video_id}",
            text=f"Video in playlist '{playlist_name}': {url}",
            content_type="playlist_item",
            timestamp=timestamp,
            modality_tags=["media", "behavioral"],
            structured_fields={
                "video_id": video_id,
                "playlist": playlist_name,
                "url": url,
                "type": "playlist",
            },
            data_path="structured",
            source_path=path,
        )
        count += 1

    log.info("  playlist '%s': %d videos", playlist_name, count)


def _extract_timestamp(html_entry: str) -> datetime | None:
    """Extract timestamp from a YouTube history HTML entry."""
    match = _TS_PATTERN.search(html_entry)
    if not match:
        return None

    ts_str = match.group(1).strip()

    # Try multiple formats — Google uses locale-dependent formatting
    for fmt in (
        "%b %d, %Y, %I:%M:%S %p %Z",
        "%b %d, %Y, %I:%M:%S %p",
        "%b %d, %Y, %H:%M:%S %Z",
        "%b %d, %Y, %H:%M:%S",
    ):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue

    # Strip timezone suffix and retry
    ts_clean = re.sub(r"\s+[A-Z]{2,5}$", "", ts_str)
    for fmt in ("%b %d, %Y, %I:%M:%S %p", "%b %d, %Y, %H:%M:%S"):
        try:
            return datetime.strptime(ts_clean, fmt)
        except ValueError:
            continue

    return None


def _decode_html(text: str) -> str:
    """Decode common HTML entities."""
    import html

    return html.unescape(text)
