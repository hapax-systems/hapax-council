"""Staleness-checked /dev/shm trace reader.

Every component reading from /dev/shm should use read_trace() instead
of raw json.loads(path.read_text()). This enforces P3 (staleness safety)
from the SCM specification — no component acts on data older than its
configured staleness threshold.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class TraceProvenance:
    """Metadata about a trace read for causal chain logging."""

    source_path: str
    reader_id: str
    timestamp: float
    age_s: float | None
    stale_threshold_s: float
    was_fresh: bool
    data_keys: frozenset[str] | None


def read_trace_with_provenance(
    path: Path, stale_s: float, *, reader_id: str
) -> tuple[dict[str, Any] | None, TraceProvenance]:
    """Read a JSON trace with staleness check, returning provenance metadata.

    Always returns the provenance record regardless of whether the data
    was fresh. Callers use provenance to build causal chain logs.
    """
    age = trace_age(path)
    data = read_trace(path, stale_s)
    return data, TraceProvenance(
        source_path=str(path),
        reader_id=reader_id,
        timestamp=time.time(),
        age_s=age,
        stale_threshold_s=stale_s,
        was_fresh=data is not None,
        data_keys=frozenset(data.keys()) if data else None,
    )


def read_and_log_trace(
    path: Path,
    stale_s: float,
    *,
    reader_node: str,
    fields_extracted: list[str],
    prior_state: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """read_trace() wrapper returning transformation context for Chronicle emission.

    Returns (data, context) where context contains the metadata needed
    to call emit_transformation() after the caller computes posterior_state.
    Returns (None, None) if the trace is stale or missing.
    source_node is derived from path.parent.name (path must follow /dev/shm/{component}/ convention).
    """
    data = read_trace(path, stale_s)
    if data is None:
        return None, None
    return data, {
        "source_node": path.parent.name,
        "reader_node": reader_node,
        "fields_extracted": fields_extracted,
        "prior_state": prior_state,
    }
