"""LRR Phase 1 item 3 — research marker read/write helper.

Importable library for the research-marker SHM file at
``/dev/shm/hapax-compositor/research-marker.json``. The marker holds
the currently active research condition ID so every reaction on the
livestream can be tagged with it at write time. Matches the on-disk
format produced by ``scripts/research-registry.py``'s
``_write_marker`` / ``_append_marker_change`` helpers (inlined in the
CLI since PR #792) — this module extracts the read/write logic into
a reusable library surface so the compositor director loop + HSEA
Phase 1 research-state broadcaster + any future consumer can import
it without shelling out to the CLI.

Schema per LRR Phase 1 spec §3.3:

    {
        "condition_id": "cond-phase-a-baseline-qwen-001",
        "set_at": "2026-04-14T05:35:00Z",
        "set_by": "research-registry-cli",
        "epoch": 42
    }

**Atomic write pattern:** ``write_marker`` uses ``tempfile.mkstemp`` +
``flush + fsync + os.replace`` so a concurrent reader never sees a
partially-written marker file. The pattern is vendored inline rather
than imported from ``agents.studio_compositor.atomic_io`` to avoid a
shared→agents layering violation.

**Stale detection:** ``read_marker(max_age_s=...)`` inspects the file
mtime and returns ``None`` if the file is older than the threshold.
Useful for consumers that want to render "condition unknown" rather
than tag with a stale value when the CLI hasn't updated the marker
recently.

**Audit log append:** ``write_marker`` atomically appends one JSONL
entry to ``~/hapax-state/research-registry/research_marker_changes.
jsonl`` describing the transition (from_condition + to_condition +
epoch + changed_by + reason). This is the append-only audit trail
required by LRR epic §I-1.

Reference: drop #62 §3 row 3 (ownership), LRR Phase 1 design spec
``docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md``
§3.3 (spec), LRR Phase 1 plan §2.1 (TDD task list).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MARKER_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")
AUDIT_LOG_PATH = Path.home() / "hapax-state" / "research-registry" / "research_marker_changes.jsonl"


@dataclass(frozen=True)
class MarkerState:
    """Snapshot of the research marker at read time.

    `condition_id` is the active research condition; `set_at` is the
    ISO 8601 timestamp of the last write; `set_by` is a free-form
    string naming the actor that wrote the marker (CLI, session id,
    etc.); `epoch` is a monotonically-increasing counter that bumps on
    every condition change.
    """

    condition_id: str
    set_at: datetime
    set_by: str
    epoch: int


def _atomic_write_json(payload: object, path: Path) -> None:
    """Write ``payload`` to ``path`` atomically.

    Uses ``tempfile.mkstemp`` to create a sibling temp file in the
    same directory, writes + flushes + fsyncs, then ``os.replace``s
    the temp onto the target. Concurrent readers either see the
    old file (before the rename) or the new file (after the rename)
    but never a partially-written blob.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_s = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path_s, path)
    except Exception:
        tmp_path = Path(tmp_path_s)
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _append_audit_log(entry: dict[str, object]) -> None:
    """Append one JSONL entry to the marker-changes audit log.

    Uses plain ``open(..., "a")`` with ``flush + fsync`` — no atomic
    write semantics. Append-mode writes are atomic at the kernel level
    for writes smaller than ``PIPE_BUF`` (4096 bytes on Linux), which
    a single JSON audit entry comfortably fits within.
    """
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry) + "\n"
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_marker(max_age_s: float | None = None) -> MarkerState | None:
    """Read the current research marker, or ``None`` if unavailable.

    Returns ``None`` when:
    - The marker file does not exist
    - The file is older than ``max_age_s`` seconds (stale detection)
    - The file content is malformed JSON
    - The file is missing one of the required fields

    This is a non-raising interface: consumers that want to tag
    reactions with the current condition can call this on every
    reaction tick and fall back to "condition unknown" when the
    return is ``None``. The LRR Phase 1 spec §3.3 requires that
    consumers render "condition unknown — check registry" rather
    than crash on a missing marker.
    """
    if not MARKER_PATH.exists():
        return None
    if max_age_s is not None:
        try:
            mtime = MARKER_PATH.stat().st_mtime
            age_s = datetime.now(UTC).timestamp() - mtime
            if age_s > max_age_s:
                return None
        except OSError:
            return None
    try:
        data = json.loads(MARKER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    condition_id = data.get("condition_id")
    set_at_raw = data.get("set_at")
    set_by = data.get("set_by")
    epoch = data.get("epoch")
    if not isinstance(condition_id, str) or not condition_id:
        return None
    if not isinstance(set_at_raw, str) or not set_at_raw:
        return None
    if not isinstance(set_by, str):
        return None
    if not isinstance(epoch, int):
        return None
    try:
        set_at = datetime.fromisoformat(set_at_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return MarkerState(
        condition_id=condition_id,
        set_at=set_at,
        set_by=set_by,
        epoch=epoch,
    )


def write_marker(
    condition_id: str,
    *,
    set_by: str = "research-marker-lib",
    reason: str = "",
) -> MarkerState:
    """Write a new marker state + append an audit log entry.

    Reads the existing marker (if any), bumps the epoch, writes the
    new marker atomically, then appends one audit log entry describing
    the transition. Returns the new :class:`MarkerState`.

    If the current marker is missing or malformed, epoch starts at 1
    and the ``from_condition`` field of the audit log entry is
    ``None``.

    Does NOT enforce append-only semantics on the condition_id itself
    — callers can re-use the same condition_id across multiple writes
    (for re-affirming the active condition, testing, or recovery).
    The audit log will record every call regardless.
    """
    now = datetime.now(UTC)
    previous = read_marker()
    new_epoch = (previous.epoch + 1) if previous is not None else 1

    new_state = MarkerState(
        condition_id=condition_id,
        set_at=now,
        set_by=set_by,
        epoch=new_epoch,
    )

    payload = {
        "condition_id": new_state.condition_id,
        "set_at": new_state.set_at.isoformat().replace("+00:00", "Z"),
        "set_by": new_state.set_by,
        "epoch": new_state.epoch,
    }
    _atomic_write_json(payload, MARKER_PATH)

    audit_entry = {
        "at": now.isoformat().replace("+00:00", "Z"),
        "from_condition": previous.condition_id if previous else None,
        "to_condition": condition_id,
        "epoch": new_epoch,
        "changed_by": set_by,
        "reason": reason,
    }
    _append_audit_log(audit_entry)

    return new_state
