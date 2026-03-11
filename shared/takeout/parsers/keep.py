"""keep.py — Parser for Google Keep notes.

Keep Takeout includes JSON files per note with structure:
{title, textContent, labels: [{name}], isArchived, isTrashed,
 isPinned, createdTimestampUsec, userEditedTimestampUsec,
 listContent: [{text, isChecked}]}
"""
from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Iterator
from datetime import datetime

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.keep")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse Keep notes from a Takeout ZIP."""
    prefix_options = [
        "Takeout/Keep/",
        "Keep/",
    ]

    for name in sorted(zf.namelist()):
        if not name.endswith(".json"):
            continue

        matched = False
        for prefix in prefix_options:
            if name.startswith(prefix):
                matched = True
                break

        if not matched:
            continue

        try:
            raw = zf.read(name)
            data = json.loads(raw)
        except (json.JSONDecodeError, KeyError) as e:
            log.debug("Skipping %s: %s", name, e)
            continue

        if not isinstance(data, dict):
            continue

        # Skip trashed notes
        if data.get("isTrashed", False):
            continue

        record = _note_to_record(data, name, config)
        if record:
            yield record


def _note_to_record(
    data: dict,
    source_path: str,
    config: ServiceConfig,
) -> NormalizedRecord | None:
    """Convert a single Keep note dict to a NormalizedRecord."""
    title = data.get("title", "")

    # Build text content
    text_parts: list[str] = []

    # Regular note text
    text_content = data.get("textContent", "")
    if text_content:
        text_parts.append(text_content)

    # Checklist items
    list_content = data.get("listContent", [])
    if list_content:
        for item in list_content:
            item_text = item.get("text", "")
            if item_text:
                checked = item.get("isChecked", False)
                prefix = "[x]" if checked else "[ ]"
                text_parts.append(f"{prefix} {item_text}")

    # Annotations (links, etc.)
    annotations = data.get("annotations", [])
    for ann in annotations:
        url = ann.get("url", "")
        ann_title = ann.get("title", "")
        if url:
            text_parts.append(f"Link: {ann_title} ({url})" if ann_title else f"Link: {url}")

    text = "\n".join(text_parts)

    if not title and not text:
        return None

    if not title:
        title = text[:80] + "..." if len(text) > 80 else text

    # Timestamp
    timestamp = None
    ts_usec = data.get("userEditedTimestampUsec") or data.get("createdTimestampUsec")
    if ts_usec:
        try:
            timestamp = datetime.fromtimestamp(int(ts_usec) / 1_000_000)
        except (ValueError, OSError):
            pass

    # Labels → categories
    labels = [label.get("name", "") for label in data.get("labels", []) if label.get("name")]

    # Build modality tags
    modality_tags = list(config.modality_defaults)

    # Additional structured fields
    structured: dict = {}
    if data.get("isPinned"):
        structured["pinned"] = True
    if data.get("isArchived"):
        structured["archived"] = True
    if data.get("color") and data["color"] != "DEFAULT":
        structured["color"] = data["color"]

    record_id = make_record_id("google", "keep", source_path)

    return NormalizedRecord(
        record_id=record_id,
        platform="google",
        service="keep",
        title=title,
        text=text,
        content_type="note",
        timestamp=timestamp,
        modality_tags=modality_tags,
        categories=labels,
        structured_fields=structured,
        data_path=config.data_path,
        source_path=source_path,
    )
