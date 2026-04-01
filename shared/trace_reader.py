"""Staleness-checked /dev/shm trace reader.

Every component reading from /dev/shm should use read_trace() instead
of raw json.loads(path.read_text()). This enforces P3 (staleness safety)
from the SCM specification — no component acts on data older than its
configured staleness threshold.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def trace_age(path: Path) -> float | None:
    """Return the age of a trace file in seconds, or None if missing."""
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def read_trace(path: Path, stale_s: float) -> dict[str, Any] | None:
    """Read a JSON trace file with staleness check.

    Returns None if:
    - File is missing
    - File is older than stale_s seconds (by mtime)
    - File contains invalid JSON

    This is the standard read pattern for /dev/shm traces.
    Using raw json.loads() without staleness check violates P3.
    """
    try:
        age = time.time() - path.stat().st_mtime
        if age > stale_s:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
