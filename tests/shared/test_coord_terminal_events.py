"""Tests for the coord terminal-event emitters + reference projection (HOS rung 3).

Self-contained: tempfile-backed CoordEventLog, no shared fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.coord_event_log import (
    CoordEvent,
    CoordEventLog,
    CoordWriter,
    DirectLaneWriteError,
    ReplayResult,
)
from shared.coord_terminal_events import (
    PR_MERGED,
    SESSION_ENDED,
    TASK_CLOSED,
    TerminalTaskProjection,
    emit_pr_merged,
    emit_session_ended,
    emit_task_closed,
)


def _tmp_log(tmp_path: Path) -> CoordEventLog:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return CoordEventLog(
        db_path=tmp_path / "coord.db",
        jsonl_path=tmp_path / "coord.jsonl",
        spool_dir=tmp_path / "spool",
    )


def _read_spooled_event(spool_path: Path) -> CoordEvent:
    """Parse the first non-empty JSON record from a spool file (object or JSONL)."""
    for line in spool_path.read_text().splitlines():
        if line.strip():
            data = json.loads(line)
            # spool files wrap the event under an "event" key (with reason/spooled_at metadata)
            return CoordEvent.from_record(data.get("event", data))
    raise AssertionError(f"empty spool file: {spool_path}")


def test_emit_task_closed_spools_typed_event(tmp_path: Path) -> None:
    log = _tmp_log(tmp_path)
    receipt = emit_task_closed(
        "fleet-ghost-reclaim-20260623",
        "cc-omnigent-abc",
        terminal_status="done",
        branch="cc-omnigent/x",
        pr=4280,
        worktree_path="~/projects/hapax-council--eta",
        log=log,
    )
    assert receipt.spooled is True
    assert receipt.appended is False
    assert receipt.spool_path is not None and receipt.spool_path.exists()

    event = _read_spooled_event(receipt.spool_path)
    assert event.event_type == TASK_CLOSED
    assert event.actor == "cc-omnigent-abc"  # claim-key
    assert event.subject == "fleet-ghost-reclaim-20260623"  # task id
    assert event.payload["terminal_status"] == "done"
    assert event.payload["branch"] == "cc-omnigent/x"
    assert event.payload["pr"] == 4280


def test_emit_pr_merged_and_session_ended(tmp_path: Path) -> None:
    log = _tmp_log(tmp_path)
    r1 = emit_pr_merged(
        4280, "cc-omnigent-abc", branch="cc-omnigent/x", merged_sha="1a78acb56", log=log
    )
    e1 = _read_spooled_event(r1.spool_path)
    assert e1.event_type == PR_MERGED
    assert e1.subject == "4280"
    assert e1.payload["merged_sha"] == "1a78acb56"

    r2 = emit_session_ended(
        "sess-1", "cc-omnigent-abc", task_id="t-1", exit_reason="clean", log=log
    )
    e2 = _read_spooled_event(r2.spool_path)
    assert e2.event_type == SESSION_ENDED
    assert e2.payload["exit_reason"] == "clean"
    assert e2.payload["task_id"] == "t-1"


def test_lane_writer_cannot_spool(tmp_path: Path) -> None:
    """The daemon-owned invariant: a lane writer must not emit (only daemon + shim)."""
    log = _tmp_log(tmp_path)
    event = CoordEvent(
        event_id="x",
        timestamp="2026-06-23T00:00:00Z",
        event_type=TASK_CLOSED,
        actor="a",
        subject="s",
    )
    with pytest.raises(DirectLaneWriteError):
        log.spool_fail_open(event, writer=CoordWriter.lane("delta"), reason="x")


def test_terminal_task_projection_folds_closed_tasks(tmp_path: Path) -> None:
    log = _tmp_log(tmp_path)
    emit_task_closed("t-a", "cc-omnigent-1", terminal_status="done", log=log)
    emit_task_closed("t-b", "cc-omnigent-2", terminal_status="withdrawn", log=log)
    # a non-task event the projection must ignore
    emit_pr_merged(99, "cc-omnigent-1", branch="b", merged_sha="deadbeef", log=log)

    events = tuple(
        _read_spooled_event(p) for p in sorted((tmp_path / "spool").glob("*.jsonl")) if p.is_file()
    )
    replay = ReplayResult(events=events, source="jsonl_mirror")
    projection = TerminalTaskProjection.from_replay(replay)

    assert projection.terminals == {"t-a": "done", "t-b": "withdrawn"}
    # round-trips through to_record / from_record
    assert (
        TerminalTaskProjection.from_record(projection.to_record()).terminals == projection.terminals
    )
