"""activity.py — Parser for Google My Activity services.

Handles Search, YouTube, Gemini, and other My Activity exports.
These share a common JSON format: array of {title, time, subtitles, ...}.
Some exports use HTML format instead — we handle both.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.activity")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse My Activity records from a Takeout ZIP.

    Tries JSON format first (MyActivity.json), falls back to HTML.
    """
    # Find matching files
    prefix_options = [
        f"Takeout/{config.takeout_path}/",
        f"{config.takeout_path}/",
    ]

    json_files = []
    html_files = []

    for name in zf.namelist():
        for prefix in prefix_options:
            if name.startswith(prefix):
                if name.endswith(".json"):
                    json_files.append(name)
                elif name.endswith(".html"):
                    html_files.append(name)
                break

    if json_files:
        for jf in json_files:
            yield from _parse_json(zf, jf, config)
    elif html_files:
        for hf in html_files:
            yield from _parse_html(zf, hf, config)


def _parse_json(
    zf: zipfile.ZipFile,
    path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse JSON-format My Activity file.

    Format: [{header, title, time, subtitles: [{name}], titleUrl, ...}]
    """
    try:
        raw = zf.read(path)
        data = json.loads(raw)
    except (json.JSONDecodeError, KeyError) as e:
        log.warning("Failed to parse %s: %s", path, e)
        return

    if not isinstance(data, list):
        log.warning("Expected list in %s, got %s", path, type(data).__name__)
        return

    for entry in data:
        title = entry.get("title", "")
        if not title:
            continue

        # Parse timestamp
        timestamp = _parse_time(entry.get("time", ""))

        # Build text from title + subtitles
        text_parts = [title]
        for sub in entry.get("subtitles", []):
            name = sub.get("name", "")
            if name:
                text_parts.append(name)

        # URL if present
        url = entry.get("titleUrl", "")
        if url:
            text_parts.append(url)

        text = "\n".join(text_parts)

        # Source key for dedup
        source_key = entry.get("time", "") + title
        record_id = make_record_id("google", config.takeout_path, source_key)

        # Extract service-specific structured fields
        structured: dict = {}
        if url:
            structured["url"] = url
        header = entry.get("header", "")
        if header:
            structured["header"] = header

        # Products (e.g., "Google Search", "YouTube")
        products = entry.get("products", [])
        if products:
            structured["products"] = products

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service=_service_from_path(config.takeout_path),
            title=title,
            text=text,
            content_type=config.content_type,
            timestamp=timestamp,
            modality_tags=list(config.modality_defaults),
            categories=products,
            structured_fields=structured,
            data_path=config.data_path,
            source_path=path,
        )


def _parse_html(
    zf: zipfile.ZipFile,
    path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse HTML-format My Activity file.

    Basic extraction — pull text content from activity entries.
    HTML format is less structured, so we extract what we can.
    """
    try:
        raw = zf.read(path).decode("utf-8", errors="replace")
    except KeyError:
        return

    # My Activity HTML has divs with class "content-cell"
    # Simple regex extraction — avoids heavy HTML parser dependency
    # Pattern: entries separated by <div class="content-cell ...">
    entries = re.split(r'<div class="content-cell[^"]*">', raw)

    for i, entry in enumerate(entries[1:], 1):  # Skip header
        # Extract text, strip tags
        text = re.sub(r"<[^>]+>", " ", entry)
        text = re.sub(r"\s+", " ", text).strip()

        if not text or len(text) < 5:
            continue

        # Try to extract timestamp
        time_match = re.search(
            r"(\w+ \d{1,2}, \d{4}, \d{1,2}:\d{2}:\d{2}\s*(?:AM|PM)?)",
            entry,
        )
        timestamp = None
        if time_match:
            try:
                timestamp = datetime.strptime(
                    time_match.group(1).strip(),
                    "%b %d, %Y, %I:%M:%S %p",
                )
            except ValueError:
                pass

        title = text[:100] + "..." if len(text) > 100 else text
        source_key = f"html:{i}:{text[:50]}"
        record_id = make_record_id("google", config.takeout_path, source_key)

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service=_service_from_path(config.takeout_path),
            title=title,
            text=text,
            content_type=config.content_type,
            timestamp=timestamp,
            modality_tags=list(config.modality_defaults),
            data_path=config.data_path,
            source_path=path,
        )


def _parse_time(time_str: str) -> datetime | None:
    """Parse Google's timestamp format."""
    if not time_str:
        return None
    # Format: "2025-06-15T10:30:00.000Z" or "2025-06-15T10:30:00Z"
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    # Try fromisoformat as fallback
    try:
        return datetime.fromisoformat(time_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _service_from_path(takeout_path: str) -> str:
    """Extract service name from takeout path.

    "My Activity/Search" → "search"
    "My Activity/YouTube" → "youtube"
    """
    parts = takeout_path.split("/")
    return parts[-1].lower().replace(" ", "_")
