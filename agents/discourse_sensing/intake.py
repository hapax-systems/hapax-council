"""Intake writes: one JSONL record per new item, create-once run reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.discourse_sensing.parsers import SensedItem


def item_record_path(intake_dir: str | Path, first_seen_iso: str) -> Path:
    """The dated JSONL file a record lands in, chosen by first-seen day."""
    day = first_seen_iso[:10] or "undated"
    return Path(intake_dir) / "sensed" / f"{day}.jsonl"


def item_record(item: SensedItem, first_seen_iso: str) -> dict:
    """The recon record form: one flat mapping per sensed item."""
    record = {
        "source_id": item.source_id,
        "venue": item.venue,
        "source": item.source_name,
        "canonical_url": item.canonical_url,
        "handle": item.handle,
        "title": item.title,
        "published_at": item.published_at,
        "first_seen_at": first_seen_iso,
        "content_hash": item.content_hash,
    }
    if item.external_url is not None:
        record["external_url"] = item.external_url
    return record


def append_items(intake_dir: str | Path, items: list[SensedItem], first_seen_iso: str) -> None:
    if not items:
        return
    path = item_record_path(intake_dir, first_seen_iso)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item_record(item, first_seen_iso), sort_keys=True) + "\n")


def write_run_report(intake_dir: str | Path, report: dict, stamp: str) -> Path:
    """Write the per-run report once; an existing report is left in place."""
    path = Path(intake_dir) / "runs" / f"{stamp}.json"
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path
