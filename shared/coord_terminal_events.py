"""Terminal-event emitters for the coord event spine (HOS rung 3).

The spine itself (``CoordEventLog``) is daemon-owned; non-daemon callers (``cc-close``,
``cc-pr-merge-watcher``, session-end teardown) emit terminal lifecycle events via the
shim spool-fail-open path — the coord daemon ingests the spool into the canonical log.
These helpers construct the typed ``CoordEvent`` + spool it, so consumers don't re-derive
the event schema.

Event types:
  ``coord.task.closed``   — a cc-task reached a terminal status (done/withdrawn/superseded)
  ``coord.pr.merged``     — a council PR merged
  ``coord.session.ended`` — a session/lane ended

``actor`` = the ``hapax_agent_claim_key`` (``<role>-<session_id>``); ``subject`` = the
task/pr/session id; ``payload`` carries the binding (branch/pr/worktree) so projections can
act without re-deriving it (the closed-loop reclaim projection + the continuity fold both
consume these).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from shared.coord_event_log import (
    AppendReceipt,
    CoordEvent,
    CoordEventLog,
    CoordWriter,
    ReplayResult,
)

TASK_CLOSED = "coord.task.closed"
PR_MERGED = "coord.pr.merged"
SESSION_ENDED = "coord.session.ended"

TERMINAL_EVENT_TYPES = frozenset({TASK_CLOSED, PR_MERGED, SESSION_ENDED})


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit_coord_event(
    event_type: str,
    *,
    actor: str,
    subject: str,
    payload: Mapping[str, Any] | None = None,
    authority_case: str | None = None,
    parent_spec: str | None = None,
    writer_name: str = "cc-task-gate",
    log: CoordEventLog | None = None,
    reason: str = "terminal_event",
) -> AppendReceipt:
    """Spool a typed terminal coord event for daemon ingestion (non-daemon emit path).

    Non-daemon callers cannot append the canonical log directly; they spool via a shim
    writer and the coord daemon ingests. Returns the (spooled) AppendReceipt.
    """
    log = log or CoordEventLog()
    writer = CoordWriter.shim(writer_name)
    event = CoordEvent(
        event_id=str(uuid.uuid4()),
        timestamp=_now_iso(),
        event_type=event_type,
        actor=actor,
        subject=subject,
        authority_case=authority_case,
        parent_spec=parent_spec,
        payload=dict(payload or {}),
    )
    return log.spool_fail_open(event, writer=writer, reason=reason)


def emit_task_closed(
    task_id: str,
    claim_key: str,
    *,
    terminal_status: str,
    branch: str | None = None,
    pr: int | None = None,
    worktree_path: str | None = None,
    **kwargs: Any,
) -> AppendReceipt:
    """Emit ``coord.task.closed`` — a cc-task reached a terminal status."""
    payload: dict[str, Any] = {"terminal_status": terminal_status, "closed_at": _now_iso()}
    if branch is not None:
        payload["branch"] = branch
    if pr is not None:
        payload["pr"] = pr
    if worktree_path is not None:
        payload["worktree_path"] = worktree_path
    return emit_coord_event(
        TASK_CLOSED, actor=claim_key, subject=task_id, payload=payload, **kwargs
    )


def emit_pr_merged(
    pr: int,
    claim_key: str,
    *,
    branch: str,
    merged_sha: str,
    base: str = "main",
    **kwargs: Any,
) -> AppendReceipt:
    """Emit ``coord.pr.merged`` — a council PR merged."""
    payload = {"branch": branch, "merged_sha": merged_sha, "base": base, "merged_at": _now_iso()}
    return emit_coord_event(PR_MERGED, actor=claim_key, subject=str(pr), payload=payload, **kwargs)


def emit_session_ended(
    session_id: str,
    claim_key: str,
    *,
    exit_reason: str = "unknown",
    task_id: str | None = None,
    worktree_path: str | None = None,
    branch: str | None = None,
    **kwargs: Any,
) -> AppendReceipt:
    """Emit ``coord.session.ended`` — a session/lane ended."""
    payload: dict[str, Any] = {"exit_reason": exit_reason, "ended_at": _now_iso()}
    if task_id is not None:
        payload["task_id"] = task_id
    if worktree_path is not None:
        payload["worktree_path"] = worktree_path
    if branch is not None:
        payload["branch"] = branch
    return emit_coord_event(
        SESSION_ENDED, actor=claim_key, subject=session_id, payload=payload, **kwargs
    )


class TerminalTaskProjection:
    """Reference ``Foldable`` projection: per-task terminal status from ``coord.task.closed``.

    Folds the coord event stream into ``{task_id: terminal_status}``. Demonstrates the
    projection-consumer pattern the closed-loop reclaim + continuity fold build on; a
    real projection would also act on the terminal state (here it only records it).
    """

    def __init__(self, terminals: Mapping[str, str] | None = None) -> None:
        self.terminals: dict[str, str] = dict(terminals or {})

    @classmethod
    def from_replay(cls, replay: ReplayResult) -> TerminalTaskProjection:
        projection = cls()
        for event in replay.events:
            projection.fold_event(event)
        return projection

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> TerminalTaskProjection:
        return cls(record.get("terminals", {}))

    def to_record(self) -> dict[str, Any]:
        return {"terminals": dict(self.terminals)}

    def fold_event(self, event: CoordEvent) -> None:
        if event.event_type == TASK_CLOSED:
            self.terminals[event.subject] = str(event.payload.get("terminal_status", "done"))
