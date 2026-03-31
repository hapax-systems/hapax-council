"""SDLC decision log — structured JSONL persistence for pipeline telemetry.

Records triage, planning, review, and axiom-gate decisions so pipeline
throughput is observable.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

_log = logging.getLogger(__name__)

DEFAULT_LOG_PATH = Path("profiles/sdlc-events.jsonl")


def log_sdlc_event(
    stage: str,
    *,
    issue_number: int | None = None,
    pr_number: int | None = None,
    result: dict | None = None,
    duration_ms: int = 0,
    model_used: str = "",
    dry_run: bool = False,
    metadata: dict | None = None,
    log_path: Path | None = None,
) -> None:
    """Append a structured SDLC event to the JSONL log."""
    path = log_path or DEFAULT_LOG_PATH
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "stage": stage,
        "issue_number": issue_number,
        "pr_number": pr_number,
        "result": result or {},
        "duration_ms": duration_ms,
        "model_used": model_used,
        "dry_run": dry_run,
        "metadata": metadata or {},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as exc:
        _log.warning("Failed to write SDLC log: %s", exc)


def read_sdlc_events(
    since: float | None = None,
    stage_filter: str | None = None,
    limit: int = 1000,
    log_path: Path | None = None,
) -> list[dict]:
    """Read SDLC events, optionally filtered by time and stage."""
    path = log_path or DEFAULT_LOG_PATH
    if not path.exists():
        return []

    entries = []
    for line in path.read_text().strip().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if since and entry.get("timestamp", "") < datetime.fromtimestamp(since, tz=UTC).isoformat():
            continue
        if stage_filter and entry.get("stage") != stage_filter:
            continue

        entries.append(entry)
        if len(entries) >= limit:
            break

    return entries


def rotate_sdlc_log(
    max_lines: int = 50_000,
    keep_lines: int = 25_000,
    log_path: Path | None = None,
) -> None:
    """Rotate SDLC log if it exceeds max_lines."""
    path = log_path or DEFAULT_LOG_PATH
    if not path.exists():
        return

    lines = path.read_text().strip().splitlines()
    if len(lines) <= max_lines:
        return

    kept = lines[-keep_lines:]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(kept) + "\n")
    tmp.rename(path)
