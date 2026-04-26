"""Local Langfuse trace reader — durable consumer-side store.

`agents.langfuse_sync` polls Langfuse every 6 hours and persists daily
trace records to ``~/documents/rag-sources/langfuse/traces-YYYY-MM-DD.jsonl``
alongside the human-readable markdown summaries.

This module reads from those JSONL files, giving consumers a durable trace
store that survives MinIO blob retention rotation (queue #242: dropped
from 14 days → 3 days). Consumers that previously polled the Langfuse API
with multi-day lookback windows should switch to this reader so they keep
working when the API stops returning >3-day-old data.

Caveat — granularity: this store is **trace-level**, not observation-level.
``langfuse_sync`` extracts ``TraceSummary`` records (one per Langfuse trace,
which can contain multiple LLM calls). For per-call analysis (token
distribution within a trace, fine-grained latency), continue to query the
Langfuse API directly with a ≤3-day window.

Example:

    from datetime import UTC, datetime, timedelta
    from agents import _langfuse_local

    since = datetime.now(UTC) - timedelta(days=14)
    for trace in _langfuse_local.query_traces(since):
        ...
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("agents._langfuse_local")

LANGFUSE_DIR: Path = Path.home() / "documents" / "rag-sources" / "langfuse"


def is_available() -> bool:
    """Return True if at least one daily trace JSONL file exists locally."""
    if not LANGFUSE_DIR.exists():
        return False
    return any(LANGFUSE_DIR.glob("traces-*.jsonl"))


def query_traces(since: datetime, until: datetime | None = None) -> Iterator[dict]:
    """Yield trace summary dicts within [since, until].

    Each dict matches ``agents.langfuse_sync.TraceSummary`` schema:
    ``trace_id``, ``name``, ``timestamp``, ``model``, ``input_preview``,
    ``output_preview``, ``total_cost``, ``latency_ms``, ``status``,
    ``tags``, ``metadata``.

    Iteration order: ascending by ``timestamp`` within each daily file,
    then by file date.
    """
    if until is None:
        until = datetime.now(UTC)
    if not LANGFUSE_DIR.exists():
        return

    since_str = since.isoformat()
    until_str = until.isoformat()
    since_day = since.strftime("%Y-%m-%d")
    until_day = until.strftime("%Y-%m-%d")

    for jsonl_path in sorted(LANGFUSE_DIR.glob("traces-*.jsonl")):
        date_part = jsonl_path.stem.replace("traces-", "")
        if date_part < since_day or date_part > until_day:
            continue
        try:
            with jsonl_path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError as exc:
                        log.warning("skipping malformed line in %s: %s", jsonl_path, exc)
                        continue
                    ts = rec.get("timestamp", "")
                    if since_str <= ts <= until_str:
                        yield rec
        except OSError as exc:
            log.warning("failed to read %s: %s", jsonl_path, exc)
            continue


# Audit 2026-04-26 B1 P0 #16-20: removed 5 unused query helpers
# (trace_count / cost_by_model / count_by_model / daily_cost_trend /
# filter_by_name). All five had zero call sites — apparent matches in
# `agents/langfuse_sync.py` + `agents/activity_analyzer.py` were string-
# literal coincidences, not function calls. The reader's load-bearing
# API is `is_available()` + `query_traces(since, until)`; both retained.
# Re-add helpers when an actual consumer materialises.
