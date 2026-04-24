"""State readers for the /now page — soft (fail-silent) I/O.

Each loader reads one canonical source path, parses gracefully, and
returns a default / None when the source is absent. Absence is normal
(dev laptop, service not running yet) — the daemon continues and
renders placeholders.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class NowState(BaseModel):
    """Assembled state passed to the Jinja template.

    Every field has a safe default so callers can build partial states
    without raising — the template handles missing sections with
    placeholders.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    working_mode: str = "unknown"
    stimmung: dict[str, Any] | None = None
    chronicle_recent: list[dict[str, Any]] = []
    timestamp_iso: str = ""


def load_working_mode(path: Path) -> str:
    """Read ``~/.cache/hapax/working-mode`` → `"research"` | `"rnd"` |
    `"fortress"` | `"unknown"`."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or "unknown"
    except (FileNotFoundError, OSError):
        return "unknown"


def load_stimmung(path: Path) -> dict[str, Any] | None:
    """Read `/dev/shm/hapax-dmn/stimmung.json` and return the parsed
    dict, or None if the file is missing / malformed."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO 8601 timestamp tolerantly — accept Z suffix."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_chronicle_recent(
    path: Path,
    *,
    now_iso: str,
    window_minutes: int = 30,
    min_salience: float = 0.6,
) -> list[dict[str, Any]]:
    """Read chronicle events from `events.jsonl` and return entries
    within the recent window AND above the salience threshold.

    Returns an empty list when the file is absent or unreadable.
    Malformed lines are silently skipped (defensive against JSONL tails
    written concurrently).
    """
    now = _parse_iso(now_iso)
    if now is None:
        return []
    cutoff = now - timedelta(minutes=window_minutes)

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []

    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        salience = event.get("salience", 0.0)
        if not isinstance(salience, (int, float)) or salience < min_salience:
            continue
        ts = _parse_iso(event.get("ts", ""))
        if ts is None or ts < cutoff:
            continue
        out.append(event)
    # Newest last (chronological); template renders in order as-is.
    out.sort(key=lambda e: _parse_iso(e.get("ts", "")) or datetime.min.replace(tzinfo=UTC))
    return out
