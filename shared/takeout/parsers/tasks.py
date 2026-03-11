"""tasks.py — Parser for Google Tasks exports.

Tasks Takeout includes JSON files with task lists and their items.
Format: {kind, items: [{id, title, updated, notes, status, due, ...}]}
"""

from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Iterator
from datetime import datetime

from shared.takeout.models import NormalizedRecord, ServiceConfig, make_record_id

log = logging.getLogger("takeout.tasks")


def parse(zf: zipfile.ZipFile, config: ServiceConfig) -> Iterator[NormalizedRecord]:
    """Parse Tasks from a Takeout ZIP."""
    prefix_options = [
        "Takeout/Tasks/",
        "Tasks/",
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

        yield from _parse_tasks_json(data, name, config)


def _parse_tasks_json(
    data: dict | list,
    source_path: str,
    config: ServiceConfig,
) -> Iterator[NormalizedRecord]:
    """Parse task data from a JSON structure.

    Handles both the top-level format {items: [...]} and
    raw lists of task objects.
    """
    items: list[dict] = []

    if isinstance(data, dict):
        items = data.get("items", [])
        if not items and "title" in data:
            # Single task object
            items = [data]
    elif isinstance(data, list):
        items = data

    for item in items:
        if not isinstance(item, dict):
            continue

        title = item.get("title", "")
        if not title:
            continue

        # Notes/description
        notes = item.get("notes", "")

        # Status
        status = item.get("status", "")

        # Timestamp
        timestamp = None
        updated = item.get("updated", "")
        if updated:
            try:
                timestamp = datetime.fromisoformat(updated.replace("Z", "+00:00")).replace(
                    tzinfo=None
                )
            except ValueError:
                pass

        # Due date
        due = item.get("due", "")

        # Build text
        text_parts = [title]
        if status:
            text_parts.append(f"Status: {status}")
        if due:
            text_parts.append(f"Due: {due}")
        if notes:
            text_parts.append(f"\n{notes}")

        text = "\n".join(text_parts)

        # Task ID
        task_id = item.get("id", f"{source_path}:{title}")
        record_id = make_record_id("google", "tasks", task_id)

        # Structured fields
        structured: dict = {}
        if status:
            structured["status"] = status
        if due:
            structured["due"] = due
        if item.get("completed"):
            structured["completed"] = item["completed"]
        if item.get("parent"):
            structured["parent_id"] = item["parent"]

        yield NormalizedRecord(
            record_id=record_id,
            platform="google",
            service="tasks",
            title=title,
            text=text,
            content_type="task",
            timestamp=timestamp,
            modality_tags=list(config.modality_defaults),
            structured_fields=structured,
            data_path=config.data_path,
            source_path=source_path,
        )
