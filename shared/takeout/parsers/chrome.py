"""chrome.py — Parser for Chrome browser data (history, bookmarks).

Chrome Takeout includes:
- BrowserHistory.json: [{page_transition, title, url, time_usec, client_id}]
- Bookmarks.html: Netscape bookmark format
"""
from __future__ import annotations

import json
import logging
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime, timezone

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.chrome")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse Chrome data from a Takeout ZIP."""
    prefix_options = [
        "Takeout/Chrome/",
        "Chrome/",
    ]

    for prefix in prefix_options:
        history_path = f"{prefix}BrowserHistory.json"
        if history_path in zf.namelist():
            yield from _parse_history(zf, history_path, config)
            break

    for prefix in prefix_options:
        bookmarks_path = f"{prefix}Bookmarks.html"
        if bookmarks_path in zf.namelist():
            yield from _parse_bookmarks(zf, bookmarks_path, config)
            break


def _parse_history(
    zf: zipfile.ZipFile,
    path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse BrowserHistory.json.

    Format: {"Browser History": [{page_transition, title, url, time_usec, client_id}]}

    Deduplicates by URL, keeping visit count as structured field.
    """
    try:
        raw = zf.read(path)
        data = json.loads(raw)
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("Failed to parse %s: %s", path, e)
        return

    entries = data.get("Browser History", [])
    if not isinstance(entries, list):
        log.warning("Expected list in Browser History, got %s", type(entries).__name__)
        return

    # Aggregate by URL: count visits, keep latest timestamp and title
    url_data: dict[str, dict] = {}
    for entry in entries:
        url = entry.get("url", "")
        if not url:
            continue

        title = entry.get("title", "")
        time_usec = entry.get("time_usec", 0)

        # Chrome stores time as microseconds since 1601-01-01 (Windows epoch)
        timestamp = _chrome_time_to_datetime(time_usec)

        if url not in url_data:
            url_data[url] = {
                "title": title,
                "url": url,
                "visit_count": 0,
                "latest_timestamp": timestamp,
                "transition": entry.get("page_transition", ""),
            }

        url_data[url]["visit_count"] += 1
        if timestamp and (
            url_data[url]["latest_timestamp"] is None
            or timestamp > url_data[url]["latest_timestamp"]
        ):
            url_data[url]["latest_timestamp"] = timestamp
            if title:  # Update title to latest non-empty
                url_data[url]["title"] = title

    # Yield deduplicated records
    for url, info in url_data.items():
        title = info["title"] or url
        record_id = make_record_id("google", "chrome", url)

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="chrome",
            title=title,
            text=f"{title}\n{url}",
            content_type="browser_history",
            timestamp=info["latest_timestamp"],
            modality_tags=list(config.modality_defaults),
            structured_fields={
                "url": url,
                "visit_count": info["visit_count"],
                "transition": info["transition"],
            },
            data_path=config.data_path,
            source_path=path,
        )


def _parse_bookmarks(
    zf: zipfile.ZipFile,
    path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse Bookmarks.html (Netscape bookmark format)."""
    import re

    try:
        raw = zf.read(path).decode("utf-8", errors="replace")
    except KeyError:
        return

    # Extract <A HREF="url" ADD_DATE="timestamp">title</A>
    pattern = re.compile(
        r'<A HREF="([^"]+)"[^>]*?(?:ADD_DATE="(\d+)")?[^>]*>([^<]+)</A>',
        re.IGNORECASE,
    )

    for match in pattern.finditer(raw):
        url = match.group(1)
        add_date = match.group(2)
        title = match.group(3).strip()

        timestamp = None
        if add_date:
            try:
                timestamp = datetime.fromtimestamp(int(add_date), tz=timezone.utc)
            except (ValueError, OSError):
                pass

        record_id = make_record_id("google", "chrome_bookmark", url)

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="chrome",
            title=title,
            text=f"{title}\n{url}",
            content_type="bookmark",
            timestamp=timestamp,
            modality_tags=["text", "knowledge"],
            structured_fields={"url": url},
            data_path="structured",
            source_path=path,
        )


def _chrome_time_to_datetime(time_usec: int) -> datetime | None:
    """Convert Chrome's time_usec (microseconds since 1601-01-01) to datetime."""
    if not time_usec:
        return None
    # Chrome epoch: 1601-01-01 00:00:00 UTC
    # Unix epoch: 1970-01-01 00:00:00 UTC
    # Difference: 11644473600 seconds
    try:
        unix_seconds = (time_usec / 1_000_000) - 11644473600
        return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None
