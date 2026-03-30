"""insight_queries.py — Persistent insight query execution and storage.

Runs queries as background asyncio tasks, persists results to JSONL.
Queries survive frontend disconnects and page navigation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from uuid import uuid4

from logos._config import LOGOS_STATE_DIR

log = logging.getLogger("logos.insight_queries")

_QUERIES_PATH = LOGOS_STATE_DIR / "insight-queries.jsonl"
_MAX_ENTRIES = 200
_MAX_CONCURRENT = 3

# In-memory registry of running tasks
_active: dict[str, asyncio.Task[None]] = {}


@dataclass
class InsightRecord:
    """A persisted insight query and its result."""

    id: str
    query: str
    status: str  # "running" | "done" | "error"
    agent_type: str = ""
    markdown: str = ""
    created_at: str = ""
    completed_at: str | None = None
    elapsed_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None
    parent_id: str | None = None


def _new_id() -> str:
    return f"iq-{uuid4().hex[:8]}"


def load_all() -> list[dict]:
    """Read all records from JSONL, newest last."""
    if not _QUERIES_PATH.exists():
        return []
    records: list[dict] = []
    try:
        for line in _QUERIES_PATH.read_text().strip().splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return records


def get(query_id: str) -> dict | None:
    """Get a single record by ID."""
    for r in load_all():
        if r.get("id") == query_id:
            return r
    return None


def _append(record: dict) -> None:
    """Append one record to the JSONL file."""
    _QUERIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_QUERIES_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as e:
        log.warning("Failed to append insight query: %s", e)
    _rotate()


def _rewrite(records: list[dict]) -> None:
    """Atomically rewrite the JSONL file."""
    _QUERIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_QUERIES_PATH.parent, suffix=".jsonl")
    try:
        with os.fdopen(fd, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        os.replace(tmp, _QUERIES_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _rotate() -> None:
    """Keep only the newest MAX_ENTRIES records."""
    if not _QUERIES_PATH.exists():
        return
    try:
        lines = _QUERIES_PATH.read_text().strip().splitlines()
        if len(lines) > _MAX_ENTRIES:
            keep = lines[-_MAX_ENTRIES:]
            _rewrite([json.loads(line) for line in keep])
            log.info("Rotated insight-queries.jsonl: %d → %d", len(lines), _MAX_ENTRIES)
    except OSError as e:
        log.debug("Rotation skipped: %s", e)


def update(query_id: str, updates: dict) -> None:
    """Update a record in-place by ID."""
    records = load_all()
    found = False
    for r in records:
        if r.get("id") == query_id:
            r.update(updates)
            found = True
            break
    if found:
        _rewrite(records)


def delete(query_id: str) -> bool:
    """Delete a record by ID. Cancel its task if still running."""
    task = _active.pop(query_id, None)
    if task and not task.done():
        task.cancel()

    records = load_all()
    filtered = [r for r in records if r.get("id") != query_id]
    if len(filtered) == len(records):
        return False
    _rewrite(filtered)
    return True


def recover_stale() -> None:
    """Mark any 'running' records as error (called on startup)."""
    records = load_all()
    patched = False
    for r in records:
        if r.get("status") == "running":
            r["status"] = "error"
            r["error"] = "Server restarted during query execution"
            r["completed_at"] = datetime.now(UTC).isoformat()
            patched = True
    if patched:
        _rewrite(records)
        log.info("Recovered stale running queries on startup")


def active_count() -> int:
    """Number of currently running query tasks."""
    # Clean up finished tasks
    done = [k for k, t in _active.items() if t.done()]
    for k in done:
        del _active[k]
    return len(_active)


def start(
    query: str,
    parent_id: str | None = None,
    prior_context: str | None = None,
    agent_type_override: str | None = None,
) -> dict:
    """Create a record, spawn a background task, return the record dict."""
    record = InsightRecord(
        id=_new_id(),
        query=query,
        status="running",
        created_at=datetime.now(UTC).isoformat(),
        parent_id=parent_id,
    )
    rec_dict = asdict(record)
    _append(rec_dict)

    task = asyncio.create_task(
        _run_task(
            record.id,
            query,
            prior_context=prior_context,
            agent_type_override=agent_type_override,
        )
    )
    _active[record.id] = task
    return rec_dict


async def _run_task(
    record_id: str,
    query: str,
    prior_context: str | None = None,
    agent_type_override: str | None = None,
) -> None:
    """Execute the query agent and persist the result."""
    try:
        from logos.query_dispatch import classify_query, run_query

        agent_type = agent_type_override or classify_query(query)
        update(record_id, {"agent_type": agent_type})

        result = await run_query(agent_type, query, prior_context=prior_context)

        update(
            record_id,
            {
                "status": "done",
                "agent_type": result.agent_type,
                "markdown": result.markdown,
                "completed_at": datetime.now(UTC).isoformat(),
                "elapsed_ms": result.elapsed_ms,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
            },
        )
    except asyncio.CancelledError:
        update(
            record_id,
            {
                "status": "error",
                "error": "Query cancelled",
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as e:
        log.exception("Insight query %s failed", record_id)
        update(
            record_id,
            {
                "status": "error",
                "error": str(e),
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
    finally:
        _active.pop(record_id, None)
