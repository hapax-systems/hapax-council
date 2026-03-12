"""Structured audit logging for automated actions.

Records every automated fix, revert, hotfix, and refactor with full context.
Separate from incident logging — incidents are what went wrong, audit is what
the system did about it.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

_log = logging.getLogger(__name__)

AUDIT_LOG = Path("profiles/audit.jsonl")


def log_audit(
    action: str,
    actor: str,
    *,
    check_name: str = "",
    fix_applied: str = "",
    classification: str = "",
    circuit_breaker: dict | None = None,
    outcome: str = "",
    git_head: str | None = None,
    duration_ms: int = 0,
    pr_number: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Append a structured audit record to JSONL log."""
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "action": action,
        "actor": actor,
        "check_name": check_name,
        "fix_applied": fix_applied,
        "classification": classification,
        "circuit_breaker": circuit_breaker or {},
        "outcome": outcome,
        "git_head": git_head,
        "duration_ms": duration_ms,
        "pr_number": pr_number,
        "metadata": metadata or {},
    }
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as exc:
        _log.warning("Failed to write audit log: %s", exc)


def read_audit_log(
    since: float | None = None,
    action_filter: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Read audit log entries, optionally filtered."""
    if not AUDIT_LOG.exists():
        return []

    entries = []
    for line in AUDIT_LOG.read_text().strip().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if since and entry.get("timestamp", "") < datetime.fromtimestamp(since, tz=UTC).isoformat():
            continue
        if action_filter and entry.get("action") != action_filter:
            continue

        entries.append(entry)
        if len(entries) >= limit:
            break

    return entries


def rotate_audit_log(max_lines: int = 50_000, keep_lines: int = 25_000) -> None:
    """Rotate audit log if it exceeds max_lines."""
    if not AUDIT_LOG.exists():
        return

    lines = AUDIT_LOG.read_text().strip().splitlines()
    if len(lines) <= max_lines:
        return

    kept = lines[-keep_lines:]
    tmp = AUDIT_LOG.with_suffix(".tmp")
    tmp.write_text("\n".join(kept) + "\n")
    tmp.rename(AUDIT_LOG)
