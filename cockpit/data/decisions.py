"""decisions.py — Decision capture for operator actions on nudges.

Records when the operator acts on, dismisses, or lets a nudge expire.
Persisted to ~/.cache/cockpit/decisions.jsonl for profiler consumption.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

log = logging.getLogger("cockpit.decisions")

from shared.config import COCKPIT_STATE_DIR

_DECISIONS_PATH = COCKPIT_STATE_DIR / "decisions.jsonl"


@dataclass
class Decision:
    """A recorded operator decision on a nudge."""

    timestamp: str
    nudge_title: str
    nudge_category: str
    action: str  # "executed" | "dismissed" | "expired"
    context: str = ""
    active_accommodations: list[str] = field(default_factory=list)


def _rotate_decisions(max_lines: int = 500) -> None:
    """Keep only the last max_lines decision entries."""
    if not _DECISIONS_PATH.exists():
        return
    try:
        lines = _DECISIONS_PATH.read_text().strip().splitlines()
        if len(lines) > max_lines:
            import tempfile

            keep = lines[-max_lines:]
            fd, tmp = tempfile.mkstemp(dir=_DECISIONS_PATH.parent, suffix=".jsonl")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write("\n".join(keep) + "\n")
                os.replace(tmp, _DECISIONS_PATH)
            except Exception:
                os.unlink(tmp)
                raise
            log.info("Rotated decisions.jsonl: %d → %d lines", len(lines), len(keep))
    except OSError as e:
        log.debug("Decision rotation skipped: %s", e)


def record_decision(decision: Decision) -> None:
    """Append a decision to the JSONL log with auto-populated accommodations."""
    _DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Auto-populate active accommodations if not already set
    if not decision.active_accommodations:
        try:
            from cockpit.accommodations import load_accommodations

            active = load_accommodations()
            decision.active_accommodations = [a.id for a in active if a.active]
        except Exception:
            pass

    try:
        with open(_DECISIONS_PATH, "a") as f:
            f.write(json.dumps(asdict(decision)) + "\n")
    except OSError as e:
        log.warning("Failed to record decision: %s", e)

    _rotate_decisions()


def collect_decisions(hours: int = 168) -> list[Decision]:
    """Read recent decisions within the given lookback window (default 7 days)."""
    if not _DECISIONS_PATH.exists():
        return []

    cutoff = datetime.now(UTC).timestamp() - (hours * 3600)
    decisions: list[Decision] = []

    try:
        for line in _DECISIONS_PATH.read_text().strip().splitlines():
            try:
                data = json.loads(line)
                ts_str = data.get("timestamp", "")
                # Parse ISO timestamp to check cutoff
                try:
                    ts = datetime.fromisoformat(ts_str).timestamp()
                except (ValueError, TypeError):
                    ts = 0
                if ts >= cutoff:
                    decisions.append(Decision(**data))
            except (json.JSONDecodeError, TypeError):
                continue
    except OSError:
        return []

    return decisions
