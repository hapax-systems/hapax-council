"""Tests for shared/coord_projection.py — taxonomy, emitters, projection fold."""

from __future__ import annotations

import ast
import dataclasses
import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import pytest
from hapax.context_canon import CoordReplaySnapshot, build_coord_replay_snapshot

from shared import coord_projection as cp
from shared.coord_event_log import (
    CoordEvent,
    CoordEventLog,
    CoordWriter,
    DuplicateEventError,
    ReplayResult,
)


@pytest.fixture(autouse=True)
def _activate_candidate_lifecycle_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Effect tests exercise a candidate that remains default-deny in production."""

    monkeypatch.setattr(cp, "_LIFECYCLE_EFFECT_ACTIVATION", True)


def _filesystem_tree(root: Path) -> tuple[tuple[object, ...], ...]:
    paths = (root, *sorted(root.rglob("*")))
    rows: list[tuple[object, ...]] = []
    for path in paths:
        metadata = path.lstat()
        kind = (
            "symlink"
            if path.is_symlink()
            else "directory"
            if path.is_dir()
            else "file"
            if path.is_file()
            else "other"
        )
        if kind == "symlink":
            content = path.readlink().as_posix()
        elif kind == "file":
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOATIME)
            try:
                digest = hashlib.sha256()
                while chunk := os.read(fd, 1024 * 1024):
                    digest.update(chunk)
                content = digest.hexdigest()
            finally:
                os.close(fd)
        else:
            content = None
        rows.append(
            (
                str(path.relative_to(root.parent)),
                kind,
                stat.S_IMODE(metadata.st_mode),
                metadata.st_uid,
                metadata.st_gid,
                metadata.st_size,
                metadata.st_atime_ns,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
                content,
            )
        )
    return tuple(rows)


def _log(tmp_path: Path) -> CoordEventLog:
    return CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )


def _snapshot_from_replay(
    replay: ReplayResult,
    *,
    ledger_path: Path,
    since_sequence: int = 0,
) -> CoordReplaySnapshot:
    return build_coord_replay_snapshot(
        tuple(event.to_record() for event in replay.events),
        ledger_path=ledger_path,
        source=replay.source,
        degraded=replay.degraded,
        errors=replay.errors,
        since_sequence=since_sequence,
    )


def _event_plane_snapshot(log: CoordEventLog) -> CoordReplaySnapshot:
    return _snapshot_from_replay(log.replay(), ledger_path=log.db_path)


# --- deterministic event_id builders -----------------------------------------


def test_event_ids_are_deterministic_and_distinct() -> None:
    a = cp.stage_transition_event_id(
        task_id="t1",
        authority_case="CASE-X",
        from_stage="S6",
        to_stage="S7",
        timestamp="ts",
    )
    b = cp.stage_transition_event_id(
        task_id="t1",
        authority_case="CASE-X",
        from_stage="S6",
        to_stage="S7",
        timestamp="ts",
    )
    c = cp.stage_transition_event_id(
        task_id="t1",
        authority_case="CASE-X",
        from_stage="S6",
        to_stage="S8",
        timestamp="ts",
    )
    assert a == b  # stable across calls
    assert a != c  # different load-bearing fields → different id
    assert a.startswith("sdlc-stage-")

    flip = cp.authorization_flip_event_id(
        task_id="t1", field="release_authorized", old=False, new=True, timestamp="ts"
    )
    assert flip.startswith("authz-flip-")
    assert cp.evidence_appended_event_id(evidence_id="EVD-1").startswith("evidence-")
    assert cp.migration_annotated_event_id(
        task_id="t1", stage="S6", risk_tier="T2", decision="adopted"
    ).startswith("migration-")


# --- STRICT emitters ----------------------------------------------------------


def test_emit_stage_transition_appends_canonical_event(tmp_path: Path) -> None:
    log = _log(tmp_path)
    receipt = cp.emit_stage_transition(
        event_log=log,
        task_id="task-1",
        from_stage="S6_IMPLEMENTATION",
        to_stage="S7_RELEASE",
        authority_case="CASE-SDLC-REFORM-001",
        actor="zeta",
        no_go_snapshot={"release_authorized": False, "implementation_authorized": True},
        timestamp="2026-05-31T14:00:00Z",
    )
    assert receipt.appended is True

    events = log.replay().events
    assert len(events) == 1
    event = events[0]
    assert event.event_type == cp.CANON_STAGE_TRANSITION
    assert event.subject == "task-1"
    assert event.authority_case == "CASE-SDLC-REFORM-001"
    assert event.payload["to_stage"] == "S7_RELEASE"
    assert event.payload["no_go_snapshot"]["implementation_authorized"] is True
    assert event.payload["origin"] == "cli"


def test_emit_stage_transition_is_idempotent_on_duplicate(tmp_path: Path) -> None:
    log = _log(tmp_path)
    kwargs = dict(
        event_log=log,
        task_id="task-1",
        from_stage="S6",
        to_stage="S7",
        authority_case="CASE-X",
        actor="zeta",
        no_go_snapshot={},
        timestamp="2026-05-31T14:00:00Z",
    )
    first = cp.emit_stage_transition(**kwargs)
    second = cp.emit_stage_transition(**kwargs)  # same inputs → same event_id

    assert first.appended is True
    assert second.appended is True  # duplicate treated as idempotent success
    assert len(log.replay().events) == 1  # not double-appended


def test_emit_authorization_flip_records_keystone_event(tmp_path: Path) -> None:
    log = _log(tmp_path)
    receipt = cp.emit_authorization_flip(
        event_log=log,
        task_id="task-1",
        field="release_authorized",
        old=False,
        new=True,
        authority_case="CASE-X",
        actor="zeta",
        reason="CI green",
        timestamp="2026-05-31T14:00:00Z",
    )
    assert receipt.appended is True
    event = log.replay().events[0]
    assert event.event_type == cp.CANON_AUTHZ_FLIP
    assert event.payload == {
        "field": "release_authorized",
        "old": False,
        "new": True,
        "reason": "CI green",
        "actor": "zeta",
    }


def test_emit_authorization_flip_rejects_non_no_go_field(tmp_path: Path) -> None:
    log = _log(tmp_path)
    with pytest.raises(ValueError, match="not a no-go boolean"):
        cp.emit_authorization_flip(
            event_log=log,
            task_id="task-1",
            field="status",  # not a no-go boolean
            old="offered",
            new="claimed",
            authority_case="CASE-X",
            actor="zeta",
        )
    assert log.replay().events == ()


def test_strict_emit_propagates_non_duplicate_errors(tmp_path: Path) -> None:
    # The strict path swallows ONLY DuplicateEventError (idempotent success); any
    # other error must propagate so the caller ABORTS and never writes a
    # projection the ledger does not back.
    log = _log(tmp_path)
    with mock.patch.object(log, "append", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            cp.emit_stage_transition(
                event_log=log,
                task_id="task-1",
                from_stage="S6",
                to_stage="S7",
                authority_case="CASE-X",
                actor="zeta",
                no_go_snapshot={},
            )


def test_strict_emit_treats_duplicate_as_success(tmp_path: Path) -> None:
    # DuplicateEventError (event already durable) is idempotent success, not error.
    log = _log(tmp_path)
    with mock.patch.object(log, "append", side_effect=DuplicateEventError("dup")):
        receipt = cp.emit_authorization_flip(
            event_log=log,
            task_id="task-1",
            field="release_authorized",
            old=False,
            new=True,
            authority_case="CASE-X",
            actor="zeta",
        )
    assert receipt.appended is True
    assert receipt.spooled is False


def test_emit_stage_transition_intent_spools_for_shim(tmp_path: Path) -> None:
    log = _log(tmp_path)
    receipt = cp.emit_stage_transition_intent(
        event_log=log,
        task_id="task-1",
        from_stage="(none)",
        to_stage="S6_IMPLEMENTATION",
        authority_case="CASE-X",
        actor="cc-task-gate",
        no_go_snapshot={"implementation_authorized": True},
        timestamp="2026-05-31T14:00:00Z",
    )
    assert receipt.spooled is True
    assert receipt.appended is False
    # Nothing in the canonical log yet — only a spooled intent for boot reconcile.
    assert not log.db_path.exists()
    spool_files = sorted(log.spool_dir.glob("*.jsonl"))
    assert len(spool_files) == 1


# --- BEST-EFFORT emitters (no-op by default, never raise) ---------------------


def test_emit_evidence_appended_is_noop_without_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(cp.EVIDENCE_MIRROR_ENV, raising=False)

    class _Entry:
        evidence_id = "EVD-1"
        case_id = "CASE-X"
        kind = "test"
        valence = "positive"
        claim = "it works"
        risk_tier = "T0"
        producer = "pytest"
        timestamp_utc = 1_700_000_000.0

    assert cp.emit_evidence_appended(_Entry()) is None  # no event_log, env unset → no-op


def test_emit_evidence_appended_writes_when_injected(tmp_path: Path) -> None:
    log = _log(tmp_path)

    class _Entry:
        evidence_id = "EVD-1"
        case_id = "CASE-X"
        kind = "test"
        valence = "positive"
        claim = "it works"
        risk_tier = "T0"
        producer = "pytest"
        timestamp_utc = 1_700_000_000.0

    receipt = cp.emit_evidence_appended(_Entry(), event_log=log)
    assert receipt is not None and receipt.appended is True
    event = log.replay().events[0]
    assert event.event_type == cp.CANON_EVIDENCE_APPENDED
    assert event.subject == "CASE-X"
    assert event.payload["evidence_id"] == "EVD-1"


def test_emit_evidence_appended_never_raises_on_bad_entry(tmp_path: Path) -> None:
    log = _log(tmp_path)

    class _Broken:
        # Missing required attributes → AttributeError inside, must be swallowed.
        pass

    assert cp.emit_evidence_appended(_Broken(), event_log=log) is None


def test_emit_migration_annotated_noop_by_default_writes_when_injected(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    assert (
        cp.emit_migration_annotated(task_id="t1", stage="S6", risk_tier="T2", decision="adopted")
        is None
    )

    receipt = cp.emit_migration_annotated(
        task_id="t1",
        stage="S6",
        risk_tier="T2",
        decision="adopted",
        seeded_fields=["release_authorized"],
        event_log=log,
    )
    assert receipt is not None
    event = log.replay().events[0]
    assert event.event_type == cp.CANON_MIGRATION_ANNOTATED
    assert event.payload["seeded_fields"] == ["release_authorized"]


# --- The projection fold ------------------------------------------------------


def _event(
    event_type: str, subject: str, payload: dict, *, eid: str, ac: str = "CASE-X"
) -> CoordEvent:
    return CoordEvent(
        event_id=eid,
        timestamp="2026-05-31T14:00:00Z",
        event_type=event_type,
        actor="zeta",
        subject=subject,
        authority_case=ac,
        payload=payload,
    )


def test_projection_folds_stage_and_no_go_last_write_wins(tmp_path: Path) -> None:
    log = _log(tmp_path)
    # Append in order; the fold must reflect the latest per field.
    log.append(
        _event(
            cp.CANON_STAGE_TRANSITION,
            "task-1",
            {"to_stage": "S6", "no_go_snapshot": {"release_authorized": False}},
            eid="e1",
        ),
        writer=CoordWriter.daemon(),
    )
    log.append(
        _event(
            cp.CANON_STAGE_TRANSITION,
            "task-1",
            {"to_stage": "S7", "no_go_snapshot": {"release_authorized": False}},
            eid="e2",
        ),
        writer=CoordWriter.daemon(),
    )
    log.append(
        _event(
            cp.CANON_AUTHZ_FLIP,
            "task-1",
            {"field": "release_authorized", "old": False, "new": True},
            eid="e3",
        ),
        writer=CoordWriter.daemon(),
    )

    projection = cp.CoordProjection.from_replay(log.replay())
    state = projection.tasks["task-1"]
    assert state.stage == "S7"  # last stage wins
    assert state.authority_case == "CASE-X"
    assert state.no_go["release_authorized"] is True  # flip wins over snapshot


def test_projection_ignores_unrelated_event_types(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(
        _event(
            "coord_dispatch.launch_succeeded",
            "task-1",
            {"outcome": "succeeded"},
            eid="d1",
        ),
        writer=CoordWriter.daemon(),
    )
    projection = cp.CoordProjection.from_replay(log.replay())
    assert "task-1" not in projection.tasks  # dispatch events are not coordination state


# --- snapshot serialization (event-sourcing checkpoint round-trip) ------------
# The fold serialized to a record and restored, so the coord log can checkpoint
# its derived state (bb-event-sourced-substrate, snapshot-only slice). The
# round-trip must be lossless and the restored state must keep folding correctly,
# because the snapshot tail-fold seeds from exactly this record.


def _canon(record: object) -> str:
    import json

    return json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def test_task_state_record_round_trips() -> None:
    state = cp.TaskState(
        task_id="task-1",
        stage="S7",
        authority_case="CASE-X",
        no_go={"release_authorized": True, "implementation_authorized": False},
    )
    assert cp.TaskState.from_record(state.to_record()) == state


def test_projection_record_round_trips_losslessly(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(
        _event(
            cp.CANON_STAGE_TRANSITION,
            "task-1",
            {"to_stage": "S7", "no_go_snapshot": {"release_authorized": False}},
            eid="e1",
        ),
        writer=CoordWriter.daemon(),
    )
    log.append(
        _event(
            cp.CANON_AUTHZ_FLIP,
            "task-1",
            {"field": "release_authorized", "old": False, "new": True},
            eid="e2",
        ),
        writer=CoordWriter.daemon(),
    )
    projection = cp.CoordProjection.from_replay(log.replay())

    restored = cp.CoordProjection.from_record(projection.to_record())

    assert restored.tasks == projection.tasks
    assert restored.tasks["task-1"].no_go["release_authorized"] is True


def test_projection_record_is_canonically_order_independent() -> None:
    # Two projections with the same logical content but tasks inserted in different
    # orders must serialize to byte-identical canonical JSON — the property the
    # snapshot-vs-full-replay equality rests on.
    a = cp.CoordProjection()
    a.tasks["task-2"] = cp.TaskState(task_id="task-2", stage="S6")
    a.tasks["task-1"] = cp.TaskState(task_id="task-1", stage="S7")
    b = cp.CoordProjection()
    b.tasks["task-1"] = cp.TaskState(task_id="task-1", stage="S7")
    b.tasks["task-2"] = cp.TaskState(task_id="task-2", stage="S6")

    assert _canon(a.to_record()) == _canon(b.to_record())


def test_fold_event_is_the_public_incremental_fold(tmp_path: Path) -> None:
    # fold_event folds one event in place; folding the stream one-by-one must equal
    # from_replay — the snapshot tail-fold depends on this equivalence.
    log = _log(tmp_path)
    log.append(
        _event(cp.CANON_STAGE_TRANSITION, "task-1", {"to_stage": "S6"}, eid="e1"),
        writer=CoordWriter.daemon(),
    )
    log.append(
        _event(cp.CANON_STAGE_TRANSITION, "task-1", {"to_stage": "S7"}, eid="e2"),
        writer=CoordWriter.daemon(),
    )
    replay = log.replay()

    incremental = cp.CoordProjection()
    for event in replay.events:
        incremental.fold_event(event)

    assert incremental.tasks == cp.CoordProjection.from_replay(replay).tasks


def test_seeded_projection_plus_tail_equals_full_fold(tmp_path: Path) -> None:
    # The determinism guarantee the snapshot rests on: serialize a projection of the
    # head events, restore it, fold the tail into the restored state, and the result
    # equals folding the whole stream from sequence zero.
    log = _log(tmp_path)
    log.append(
        _event(
            cp.CANON_STAGE_TRANSITION,
            "task-1",
            {"to_stage": "S6", "no_go_snapshot": {"release_authorized": False}},
            eid="e1",
        ),
        writer=CoordWriter.daemon(),
    )
    log.append(
        _event(cp.CANON_STAGE_TRANSITION, "task-1", {"to_stage": "S7"}, eid="e2"),
        writer=CoordWriter.daemon(),
    )
    log.append(
        _event(
            cp.CANON_AUTHZ_FLIP,
            "task-1",
            {"field": "release_authorized", "old": False, "new": True},
            eid="e3",
        ),
        writer=CoordWriter.daemon(),
    )
    events = log.replay().events

    head_record = cp.CoordProjection.from_replay(
        ReplayResult(events=tuple(events[:2]), source="sqlite")
    ).to_record()
    seeded = cp.CoordProjection.from_record(head_record)
    for event in events[2:]:
        seeded.fold_event(event)

    full = cp.CoordProjection.from_replay(log.replay())
    assert seeded.tasks == full.tasks
    assert seeded.tasks["task-1"].no_go["release_authorized"] is True


# --- receipt-first lifecycle transaction ------------------------------------


def _intent(**overrides: object) -> cp.LifecycleTransitionIntent:
    values: dict[str, object] = {
        "task_id": "task-1",
        "from_stage": "S6_IMPLEMENTATION",
        "to_stage": "S7_RUNTIME_VERIFICATION",
        "edge_class": "next",
        "authority_case": "CASE-X",
        "actor": "cx-test",
        "no_go_snapshot": {key: key == "implementation_authorized" for key in cp.NO_GO_BOOLEANS},
        "parent_spec": "/tmp/spec.md",
    }
    values.update(overrides)
    if "guard_evidence" not in values:
        from shared.sdlc_lifecycle import SDLC_STAGE_METADATA, stage_token

        source = stage_token(str(values["from_stage"]))
        target = stage_token(str(values["to_stage"]))
        edge_class = str(values["edge_class"])
        edges = (
            SDLC_STAGE_METADATA.by_token[source].next_edges
            if edge_class == "next"
            else SDLC_STAGE_METADATA.by_token[source].fall_edges
        )
        edge = next((candidate for candidate in edges if candidate.to == target), None)
        values["guard_evidence"] = (
            {guard: (f"receipt:test:{guard}",) for guard in edge.guards} if edge else {}
        )
    return cp.LifecycleTransitionIntent.create(**values)  # type: ignore[arg-type]


def test_transition_intent_refuses_non_edge_and_ambiguous_edge_class() -> None:
    with pytest.raises(cp.LifecycleTransitionError, match="transition_edge_illegal"):
        _intent(from_stage="S0", to_stage="S11", edge_class="next")
    with pytest.raises(cp.LifecycleTransitionError, match="transition_edge_class_ambiguous"):
        _intent(from_stage="S6", to_stage="BLOCKED", edge_class="auto")
    assert _intent(from_stage="S3_5", to_stage="S0", edge_class="next").edge_class == "next"
    assert _intent(from_stage="S6", to_stage="BLOCKED", edge_class="fall").edge_class == "fall"


def test_lifecycle_effects_default_deny_before_journal_event_or_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    monkeypatch.setattr(cp, "_LIFECYCLE_EFFECT_ACTIVATION", False)

    with pytest.raises(
        cp.LifecycleTransitionError,
        match="transition_effect_activation_unavailable",
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=root,
            lock_root=tmp_path / "locks",
        )
    with pytest.raises(
        cp.LifecycleTransitionError,
        match="transition_effect_activation_unavailable",
    ):
        cp.recover_lifecycle_transactions(
            event_log=log,
            transaction_root=root,
            lock_root=tmp_path / "locks",
        )

    assert note.read_bytes() == b"stage: S6\n"
    assert not root.exists()
    assert log.replay().events == ()


def test_executor_rejects_bypassed_mutable_intent_before_any_effect(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    intent = _intent()
    with pytest.raises(TypeError):
        intent.no_go_snapshot["implementation_authorized"] = False
    with pytest.raises(TypeError):
        intent.guard_evidence[next(iter(intent.guard_evidence))] = ("forged",)
    object.__setattr__(
        intent,
        "no_go_snapshot",
        {**intent.no_go_snapshot, "implementation_authorized": "yes"},
    )

    with pytest.raises(
        cp.LifecycleTransitionError,
        match="transition_no_go_snapshot_malformed|transition_intent_shape_malformed",
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=intent,
            projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
            transaction_root=root,
            lock_root=tmp_path / "locks",
        )

    assert note.read_bytes() == b"stage: S6\n"
    assert not root.exists()
    assert log.replay().events == ()


def test_public_lifecycle_executor_refuses_terminal_edge(tmp_path: Path) -> None:
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S10\n")
    intent = _intent(
        from_stage="S10",
        to_stage="S11",
        predecessor_position_ref="canon-position@sha256:" + "a" * 64,
        echo_receipt_ref="mq:echo-close",
        evidence_type="terminal_close_admission",
        evidence_summary="terminal-close-admission@sha256:" + "b" * 64,
    )

    with pytest.raises(cp.LifecycleTransitionError, match="transition_terminal_executor_required"):
        cp.execute_lifecycle_transition(
            event_log=_log(tmp_path),
            intent=intent,
            projections=[cp.FileProjection.capture(note, after=b"stage: S11\n")],
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
        )

    assert note.read_bytes() == b"stage: S10\n"


def test_lifecycle_transaction_appends_before_projection_and_replays_exactly(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")

    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[projection],
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
        timestamp="2026-07-11T15:00:00Z",
    )

    assert note.read_bytes() == b"stage: S7\n"
    events = log.replay().events
    assert [event.event_type for event in events] == [
        cp.CANON_TRANSITION_PREPARED,
        cp.CANON_TRANSITION_APPLIED,
    ]
    assert events[0].sequence is not None and events[1].sequence is not None
    assert receipt.prepared_sequence == events[0].sequence
    assert receipt.applied_sequence == events[1].sequence

    replayed = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[projection],
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
        timestamp="2099-01-01T00:00:00Z",
    )
    assert replayed.replayed is True
    assert len(log.replay().events) == 2


def test_lifecycle_transaction_rolls_back_when_applied_append_fails(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_append = log.append

    def fail_applied(event: CoordEvent, **kwargs: object):
        if event.event_type == cp.CANON_TRANSITION_APPLIED:
            raise RuntimeError("applied append unavailable")
        return original_append(event, **kwargs)  # type: ignore[arg-type]

    with mock.patch.object(log, "append", side_effect=fail_applied):
        with pytest.raises(RuntimeError, match="applied append unavailable"):
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=_intent(),
                projections=[projection],
                transaction_root=tmp_path / "transactions",
                lock_root=tmp_path / "locks",
                timestamp="2026-07-11T15:00:00Z",
            )

    assert note.read_bytes() == b"stage: S6\n"
    assert [event.event_type for event in log.replay().events] == [
        cp.CANON_TRANSITION_PREPARED,
        cp.CANON_TRANSITION_ABORTED,
    ]


def test_terminal_append_projection_failure_durably_blocks_retry(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    lock_root = tmp_path / "locks"
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_append = log.append
    original_project = cp._project_phase_append_receipt

    def fail_applied(event: CoordEvent, **kwargs: object):
        if event.event_type == cp.CANON_TRANSITION_APPLIED:
            raise RuntimeError("applied append unavailable")
        return original_append(event, **kwargs)  # type: ignore[arg-type]

    def fail_aborted_projection(*args: object, **kwargs: object):
        event = args[1]
        if isinstance(event, CoordEvent) and event.payload.get("phase") == "aborted":
            raise OSError("phase projection unavailable")
        return original_project(*args, **kwargs)  # type: ignore[arg-type]

    with (
        mock.patch.object(log, "append", side_effect=fail_applied),
        mock.patch.object(
            cp,
            "_project_phase_append_receipt",
            side_effect=fail_aborted_projection,
        ),
        pytest.raises(
            cp.LifecycleTransitionError,
            match="transition_terminal_phase_projection_persistence_failed",
        ),
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=transaction_root,
            lock_root=lock_root,
        )

    manifest = next(transaction_root.glob("*/manifest.json"))
    record = json.loads(manifest.read_text(encoding="ascii"))
    assert record["state"] == "recovery_required"
    assert record["reason_code"] == ("transition_terminal_phase_projection_persistence_failed")
    with pytest.raises(
        cp.LifecycleTransitionError,
        match="transition_aborted_projection_unreconciled",
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=transaction_root,
            lock_root=lock_root,
        )
    assert len(tuple(transaction_root.glob("*/manifest.json"))) == 1


@pytest.mark.parametrize("failed_phase", ("aborted", "applied"))
def test_recovery_reconciles_terminal_append_projection_cut(
    tmp_path: Path,
    failed_phase: str,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    lock_root = tmp_path / "locks"
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_append = log.append
    original_project = cp._project_phase_append_receipt

    def maybe_fail_applied(event: CoordEvent, **kwargs: object):
        if failed_phase == "aborted" and event.event_type == cp.CANON_TRANSITION_APPLIED:
            raise RuntimeError("applied append unavailable")
        return original_append(event, **kwargs)  # type: ignore[arg-type]

    def fail_terminal_projection(*args: object, **kwargs: object):
        event = args[1]
        if isinstance(event, CoordEvent) and event.payload.get("phase") == failed_phase:
            raise OSError("terminal projection unavailable")
        return original_project(*args, **kwargs)  # type: ignore[arg-type]

    with (
        mock.patch.object(log, "append", side_effect=maybe_fail_applied),
        mock.patch.object(
            cp,
            "_project_phase_append_receipt",
            side_effect=fail_terminal_projection,
        ),
        pytest.raises(
            cp.LifecycleTransitionError,
            match="transition_terminal_phase_projection_persistence_failed",
        ),
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=transaction_root,
            lock_root=lock_root,
        )

    recovered = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=transaction_root,
        lock_root=lock_root,
    )
    assert recovered[0].state == failed_phase
    inspected = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=transaction_root,
        task_id="task-1",
    )
    assert inspected.scope_complete is True
    assert inspected.transactions[0].state == failed_phase


def test_lifecycle_transaction_never_rolls_back_over_third_party_bytes(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")

    def race(phase: str, index: int | None) -> None:
        if phase == "after_prepared":
            note.write_bytes(b"third-party\n")

    with pytest.raises(cp.LifecycleTransitionError, match="precondition_changed"):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
            timestamp="2026-07-11T15:00:00Z",
            failure_hook=race,
        )
    assert note.read_bytes() == b"third-party\n"


def test_recovery_commits_crash_left_complete_postimage(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")

    def crash(phase: str, index: int | None) -> None:
        if phase == "after_projection":
            raise SystemExit(91)

    with pytest.raises(SystemExit):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
            timestamp="2026-07-11T15:00:00Z",
            failure_hook=crash,
        )
    assert note.read_bytes() == b"stage: S7\n"
    assert [event.event_type for event in log.replay().events] == [cp.CANON_TRANSITION_PREPARED]

    result = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
    )
    assert result == (
        cp.LifecycleRecoveryResult(
            result[0].transaction_id,
            "applied",
            "transition_recovered_from_prepared",
        ),
    )
    assert [event.event_type for event in log.replay().events] == [
        cp.CANON_TRANSITION_PREPARED,
        cp.CANON_TRANSITION_APPLIED,
    ]


def test_update_cas_restores_racing_preimage_without_loss(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_rename = cp._renameat2
    raced = False

    def race_exchange(
        src_dir_fd: int,
        src_name: str,
        dst_dir_fd: int,
        dst_name: str,
        flags: int,
    ) -> None:
        nonlocal raced
        if flags == cp._RENAME_EXCHANGE and not raced:
            raced = True
            note.write_bytes(b"third-party\n")
        original_rename(src_dir_fd, src_name, dst_dir_fd, dst_name, flags)

    with mock.patch.object(cp, "_renameat2", side_effect=race_exchange):
        with pytest.raises(cp.LifecycleTransitionError, match="precondition_changed"):
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=_intent(),
                projections=[projection],
                transaction_root=tmp_path / "transactions",
                lock_root=tmp_path / "locks",
                timestamp="2026-07-11T15:00:00Z",
            )

    assert note.read_bytes() == b"third-party\n"
    assert [event.event_type for event in log.replay().events] == [
        cp.CANON_TRANSITION_PREPARED,
        cp.CANON_TRANSITION_ABORTED,
    ]


def test_create_cas_noreplace_refuses_racing_create(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    projection = cp.FileProjection.capture(note, after=b"created by transition\n")
    original_rename = cp._renameat2
    raced = False

    def race_create(
        src_dir_fd: int,
        src_name: str,
        dst_dir_fd: int,
        dst_name: str,
        flags: int,
    ) -> None:
        nonlocal raced
        if flags == cp._RENAME_NOREPLACE and dst_name == note.name and not raced:
            raced = True
            note.write_bytes(b"third-party\n")
        original_rename(src_dir_fd, src_name, dst_dir_fd, dst_name, flags)

    with mock.patch.object(cp, "_renameat2", side_effect=race_create):
        with pytest.raises(cp.LifecycleTransitionError, match="precondition_changed"):
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=_intent(),
                projections=[projection],
                transaction_root=tmp_path / "transactions",
                lock_root=tmp_path / "locks",
                timestamp="2026-07-11T15:00:00Z",
            )

    assert note.read_bytes() == b"third-party\n"


def test_aborted_operation_retries_as_next_attempt(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_append = log.append

    def fail_first_applied(event: CoordEvent, **kwargs: object):
        if event.event_type == cp.CANON_TRANSITION_APPLIED:
            raise RuntimeError("transient applied append failure")
        return original_append(event, **kwargs)  # type: ignore[arg-type]

    with mock.patch.object(log, "append", side_effect=fail_first_applied):
        with pytest.raises(RuntimeError, match="transient applied"):
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=_intent(),
                projections=[projection],
                transaction_root=tmp_path / "transactions",
                lock_root=tmp_path / "locks",
                timestamp="2026-07-11T15:00:00Z",
            )

    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[projection],
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
        timestamp="2026-07-11T15:01:00Z",
    )

    assert receipt.attempt_no == 1
    assert receipt.transaction_id.endswith(".attempt-0001")
    assert note.read_bytes() == b"stage: S7\n"


def test_crash_before_prepared_reuses_attempt_and_manifest_timestamp(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")

    def crash(phase: str, index: int | None) -> None:
        if phase == "before_prepared":
            raise SystemExit(90)

    with pytest.raises(SystemExit):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
            timestamp="2026-07-11T15:00:00Z",
            failure_hook=crash,
        )

    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[projection],
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
        timestamp="2099-01-01T00:00:00Z",
    )
    assert receipt.attempt_no == 0
    assert log.replay().events[0].timestamp == "2026-07-11T15:00:00Z"


def test_applied_commit_then_caller_error_never_rolls_back(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_append = log.append

    def commit_then_raise(event: CoordEvent, **kwargs: object):
        receipt = original_append(event, **kwargs)  # type: ignore[arg-type]
        if event.event_type == cp.CANON_TRANSITION_APPLIED:
            raise RuntimeError("caller lost applied return")
        return receipt

    with mock.patch.object(log, "append", side_effect=commit_then_raise):
        receipt = cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
            timestamp="2026-07-11T15:00:00Z",
        )

    assert receipt.applied_sequence is not None
    assert note.read_bytes() == b"stage: S7\n"
    assert [event.event_type for event in log.replay().events] == [
        cp.CANON_TRANSITION_PREPARED,
        cp.CANON_TRANSITION_APPLIED,
    ]


def test_applied_unknown_preserves_postimage_without_aborted_receipt(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_append = log.append
    original_replay = log.replay
    applied_attempted = False

    def fail_applied(event: CoordEvent, **kwargs: object):
        nonlocal applied_attempted
        if event.event_type == cp.CANON_TRANSITION_APPLIED:
            applied_attempted = True
            raise RuntimeError("applied outcome unknown")
        return original_append(event, **kwargs)  # type: ignore[arg-type]

    def unavailable_replay(*args: object, **kwargs: object):
        if applied_attempted:
            raise RuntimeError("ledger unavailable")
        return original_replay(*args, **kwargs)  # type: ignore[arg-type]

    with (
        mock.patch.object(log, "append", side_effect=fail_applied),
        mock.patch.object(log, "replay", side_effect=unavailable_replay),
        pytest.raises(cp.LifecycleTransitionError, match="applied_commit_unknown"),
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
            timestamp="2026-07-11T15:00:00Z",
        )

    assert note.read_bytes() == b"stage: S7\n"
    assert [event.event_type for event in original_replay().events] == [
        cp.CANON_TRANSITION_PREPARED
    ]


def test_successful_and_rolled_back_transactions_leave_no_scratch(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")

    cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[projection],
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
    )

    assert not list(note.parent.glob(".*.transition-scratch"))

    second = cp.FileProjection.capture(note, after=b"stage: S8\n")
    second_intent = _intent(from_stage="S7", to_stage="S8")
    original_append = log.append

    def fail_applied(event: CoordEvent, **kwargs: object):
        if event.event_type == cp.CANON_TRANSITION_APPLIED:
            raise RuntimeError("refuse applied")
        return original_append(event, **kwargs)  # type: ignore[arg-type]

    with mock.patch.object(log, "append", side_effect=fail_applied):
        with pytest.raises(RuntimeError, match="refuse applied"):
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=second_intent,
                projections=[second],
                transaction_root=tmp_path / "transactions",
                lock_root=tmp_path / "locks",
            )

    assert note.read_bytes() == b"stage: S7\n"
    assert not list(note.parent.glob(".*.transition-scratch"))


def test_projection_refuses_hardlink_and_boolean_mode(tmp_path: Path) -> None:
    note = tmp_path / "task.md"
    alias = tmp_path / "alias.md"
    note.write_bytes(b"stage: S6\n")
    os.link(note, alias)

    with pytest.raises(cp.LifecycleTransitionError, match="projection_path_unsafe"):
        cp.FileProjection.capture(note, after=b"stage: S7\n")
    with pytest.raises(cp.LifecycleTransitionError, match="projection_shape_malformed"):
        cp.FileProjection.from_snapshot(
            tmp_path / "new.md",
            before=None,
            before_mode=None,
            after=b"content\n",
            after_mode=True,
        )


def test_atomic_private_install_detects_temp_inode_swap(tmp_path: Path) -> None:
    target = tmp_path / "private" / "manifest.json"
    target.parent.mkdir(mode=0o700)
    original_rename = cp._renameat2
    raced = False

    def race_destination(
        src_dir_fd: int,
        src: str,
        dst_dir_fd: int,
        dst: str,
        flags: int,
    ) -> None:
        nonlocal raced
        if not raced and dst == target.name and flags == cp._RENAME_NOREPLACE:
            raced = True
            fd = os.open(
                dst,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dst_dir_fd,
            )
            try:
                os.write(fd, b"attacker\n")
                os.fsync(fd)
            finally:
                os.close(fd)
        original_rename(src_dir_fd, src, dst_dir_fd, dst, flags)

    with (
        mock.patch.object(cp, "_renameat2", side_effect=race_destination),
        pytest.raises(cp.LifecycleTransitionError, match="precondition_changed"),
    ):
        cp._atomic_install(target, b"expected\n", 0o600, None)

    assert target.read_bytes() == b"attacker\n"


def test_atomic_private_install_refuses_fifo_without_blocking(tmp_path: Path) -> None:
    target = tmp_path / "private" / "manifest.json"
    target.parent.mkdir(mode=0o700)
    os.mkfifo(target, 0o600)
    script = """
import sys
from pathlib import Path
from shared import coord_projection as cp
try:
    cp._atomic_install(Path(sys.argv[1]), b"replacement\\n", 0o600, None)
except cp.LifecycleTransitionError as exc:
    print(exc.reason_code)
else:
    raise SystemExit("unexpected success")
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(target)],
        check=True,
        capture_output=True,
        text=True,
        timeout=3,
    )

    assert result.stdout.strip() == "transition_projection_path_unsafe"
    assert stat.S_ISFIFO(target.lstat().st_mode)


def test_atomic_private_install_preserves_fifo_exchange_race_for_recovery(
    tmp_path: Path,
) -> None:
    target = tmp_path / "private" / "manifest.json"
    target.parent.mkdir(mode=0o700)
    target.write_bytes(b"before\n")
    target.chmod(0o600)
    expected = cp._private_file_state(target, max_bytes=1024)
    assert expected is not None
    original_rename = cp._renameat2
    raced = False

    def substitute_fifo_after_exchange(
        src_dir_fd: int,
        src: str,
        dst_dir_fd: int,
        dst: str,
        flags: int,
    ) -> None:
        nonlocal raced
        original_rename(src_dir_fd, src, dst_dir_fd, dst, flags)
        if raced or flags != cp._RENAME_EXCHANGE:
            return
        raced = True
        os.unlink(src, dir_fd=src_dir_fd)
        os.mkfifo(src, 0o600, dir_fd=src_dir_fd)

    with (
        mock.patch.object(cp, "_renameat2", side_effect=substitute_fifo_after_exchange),
        pytest.raises(cp.LifecycleTransitionError) as raised,
    ):
        cp._atomic_install(target, b"after\n", 0o600, expected)

    assert raised.value.reason_code == "transition_private_install_recovery_required"
    assert stat.S_ISFIFO(target.lstat().st_mode)


def test_lock_inode_replacement_is_detected_after_flock(tmp_path: Path) -> None:
    """The post-flock identity check, exercised through the transition's own entry point.

    The lock primitive moved to shared/task_note_lock.py and takes ``LOCK_EX | LOCK_NB`` against
    a deadline rather than a blocking ``LOCK_EX``, so this probe matches the exclusive *bit*
    instead of the exact operation value — and the *first* such call is now the lock file's,
    because the root is taken ``LOCK_SH``.

    This check is the only thing standing between a swapped lock pathname and a critical
    section entered on an orphaned inode. It is not, however, a guard against a lock file
    unlinked while a section is already held: it protects the acquirer at acquisition, not the
    incumbent for the duration. That residual is named in the module docstring's reaper
    contract, and is why the root is still held (shared) across the section.
    """

    root = tmp_path / "locks"
    original_flock = cp.fcntl.flock
    exclusive_calls = 0

    def replace_lock(handle: int, operation: int) -> None:
        nonlocal exclusive_calls
        original_flock(handle, operation)
        if not operation & cp.fcntl.LOCK_EX:
            return
        exclusive_calls += 1
        if exclusive_calls != 1:
            return
        names = [name for name in os.listdir(root) if name.endswith(".lock")]
        assert len(names) == 1
        path = root / names[0]
        path.unlink()
        path.write_bytes(b"")
        path.chmod(0o600)

    with (
        mock.patch.object(cp.fcntl, "flock", side_effect=replace_lock),
        pytest.raises(cp.LifecycleTransitionError, match="lock_identity_changed"),
    ):
        with cp._transition_locks("task-1", (), root):
            pytest.fail("split lock entered critical section")


def test_noncanonical_applied_manifest_is_not_replayed(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[projection],
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
    )
    payload = json.loads(receipt.manifest_path.read_text(encoding="ascii"))
    receipt.manifest_path.write_text(json.dumps(payload, indent=2), encoding="ascii")

    with pytest.raises(cp.LifecycleTransitionError, match="manifest_noncanonical"):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
        )


def test_recovery_refuses_unsafe_empty_transaction_root(tmp_path: Path) -> None:
    real_root = tmp_path / "real-transactions"
    real_root.mkdir(mode=0o700)
    transaction_root = tmp_path / "transactions"
    transaction_root.symlink_to(real_root, target_is_directory=True)

    result = cp.recover_lifecycle_transactions(
        event_log=_log(tmp_path),
        transaction_root=transaction_root,
        lock_root=tmp_path / "locks",
    )

    assert result == (
        cp.LifecycleRecoveryResult(
            "transition-root",
            "recovery_required",
            "transition_private_directory_unsafe",
        ),
    )


def test_recovery_refuses_orphan_transaction_directory(tmp_path: Path) -> None:
    root = tmp_path / "transactions"
    root.mkdir(mode=0o700)
    orphan = root / f"sdlc-txn-{'a' * 64}.attempt-0000"
    orphan.mkdir(mode=0o700)

    result = cp.recover_lifecycle_transactions(
        event_log=_log(tmp_path),
        transaction_root=root,
        lock_root=tmp_path / "locks",
    )

    assert result[0].state == "recovery_required"
    assert result[0].reason_code == "transition_manifest_missing"


def test_recovery_reports_ledger_only_prepared_receipt(tmp_path: Path) -> None:
    log = _log(tmp_path)
    intent = _intent()
    projection = cp.FileProjection.from_snapshot(
        tmp_path / "vault" / "task-1.md",
        before=b"stage: S6\n",
        before_mode=0o644,
        after=b"stage: S7\n",
        after_mode=0o644,
    )
    operation_id = cp.lifecycle_transition_id(intent, [projection])
    transaction_id = cp._attempt_transaction_id(operation_id, 0)
    event = cp._transaction_event(
        event_type=cp.CANON_TRANSITION_PREPARED,
        phase="prepared",
        transaction_id=transaction_id,
        operation_id=operation_id,
        attempt_no=0,
        intent=intent,
        projections=[projection],
        timestamp="2026-07-11T15:00:00Z",
    )
    log.append(event, writer=CoordWriter.daemon())

    result = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
    )

    assert result == (
        cp.LifecycleRecoveryResult(
            transaction_id,
            "recovery_required",
            "transition_receipt_manifest_missing",
        ),
    )


def test_recovery_refuses_undeclared_transaction_entry(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
    )
    (receipt.manifest_path.parent / "stray.tmp").write_bytes(b"unexpected\n")

    result = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
    )

    assert result[0].state == "recovery_required"
    assert result[0].reason_code == "transition_manifest_directory_entry_unknown"


def test_recovery_refuses_manifest_phase_without_ledger_receipt(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")

    def crash(phase: str, index: int | None) -> None:
        if phase == "before_prepared":
            raise SystemExit(90)

    with pytest.raises(SystemExit):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
            failure_hook=crash,
        )
    manifest = next((tmp_path / "transactions").glob("*/manifest.json"))
    payload = json.loads(manifest.read_text(encoding="ascii"))
    payload["state"] = "prepared"
    manifest.write_text(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="ascii",
    )

    result = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=tmp_path / "transactions",
        lock_root=tmp_path / "locks",
    )

    assert result[0].state == "recovery_required"
    assert result[0].reason_code == "transition_manifest_phase_receipt_missing"


def test_lifecycle_inspection_preserves_applied_history_despite_projection_drift(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    lock_root = tmp_path / "locks"
    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=transaction_root,
        lock_root=lock_root,
    )
    note.write_bytes(b"later projection state\n")
    transaction_before = _filesystem_tree(transaction_root)
    locks_before = _filesystem_tree(lock_root)
    events_before = log.replay().events
    event_plane_snapshot = _event_plane_snapshot(log)

    def mutation_forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("lifecycle inspection attempted mutation")

    with (
        mock.patch.object(cp, "_transition_locks", side_effect=mutation_forbidden),
        mock.patch.object(cp, "_execute_lifecycle_transition", side_effect=mutation_forbidden),
        mock.patch.object(cp, "_write_manifest", side_effect=mutation_forbidden),
        mock.patch.object(cp, "_rollback_projections", side_effect=mutation_forbidden),
        mock.patch.object(cp, "_finalize_applied_scratches", side_effect=mutation_forbidden),
        mock.patch.object(cp, "_strict_append_exact", side_effect=mutation_forbidden),
        mock.patch.object(log, "append", side_effect=mutation_forbidden),
    ):
        result = cp.inspect_lifecycle_transactions(
            event_log=object(),
            event_plane_snapshot=event_plane_snapshot,
            transaction_root=transaction_root,
            task_id="task-1",
        )

    assert result.complete is True
    assert result.may_authorize is False
    assert result.event_plane_snapshot_ref == event_plane_snapshot.snapshot_ref
    assert result.scope_transaction_refs == (result.transactions[0].inspection_ref,)
    assert result.transactions[0].transaction_id == receipt.transaction_id
    assert result.transactions[0].state == "applied"
    assert result.transactions[0].recovery_required is False
    assert note.read_bytes() == b"later projection state\n"
    assert _filesystem_tree(transaction_root) == transaction_before
    assert _filesystem_tree(lock_root) == locks_before
    assert log.replay().events == events_before


def test_lifecycle_inspection_classifies_exact_aborted_history(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    original_append = log.append

    def fail_applied(event: CoordEvent, **kwargs: object):
        if event.event_type == cp.CANON_TRANSITION_APPLIED:
            raise RuntimeError("applied append unavailable")
        return original_append(event, **kwargs)  # type: ignore[arg-type]

    with mock.patch.object(log, "append", side_effect=fail_applied):
        with pytest.raises(RuntimeError, match="applied append unavailable"):
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=_intent(),
                projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
                transaction_root=transaction_root,
                lock_root=tmp_path / "locks",
            )

    transaction_id = next(transaction_root.glob("*/manifest.json")).parent.name
    result = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=transaction_root,
        task_id="task-1",
    )
    assert result.complete is True
    assert result.transactions[0].transaction_id == transaction_id
    assert result.transactions[0].state == "aborted"
    assert result.transactions[0].recovery_required is False


@pytest.mark.parametrize(
    "crash_phase",
    ["before_prepared", "after_prepared", "after_projection", "before_applied"],
)
def test_lifecycle_inspection_holds_crash_left_state_without_recovery(
    tmp_path: Path,
    crash_phase: str,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    lock_root = tmp_path / "locks"

    def crash(phase: str, index: int | None) -> None:
        if phase == crash_phase:
            raise SystemExit(91)

    with pytest.raises(SystemExit):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
            transaction_root=transaction_root,
            lock_root=lock_root,
            failure_hook=crash,
        )
    transaction_before = _filesystem_tree(transaction_root)
    locks_before = _filesystem_tree(lock_root)
    events_before = log.replay().events
    projection_before = note.read_bytes()

    result = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=transaction_root,
        task_id="task-1",
    )

    assert result.complete is False
    assert len(result.transactions) == 1
    assert result.transactions[0].recovery_required is True
    assert result.transactions[0].state in {"not_started", "prepared", "hold"}
    assert _filesystem_tree(transaction_root) == transaction_before
    assert _filesystem_tree(lock_root) == locks_before
    assert log.replay().events == events_before
    assert note.read_bytes() == projection_before


def test_lifecycle_inspection_holds_receipt_without_manifest(tmp_path: Path) -> None:
    log = _log(tmp_path)
    intent = _intent()
    projection = cp.FileProjection.from_snapshot(
        tmp_path / "vault" / "task-1.md",
        before=b"stage: S6\n",
        before_mode=0o644,
        after=b"stage: S7\n",
        after_mode=0o644,
    )
    operation_id = cp.lifecycle_transition_id(intent, [projection])
    transaction_id = cp._attempt_transaction_id(operation_id, 0)
    log.append(
        cp._transaction_event(
            event_type=cp.CANON_TRANSITION_PREPARED,
            phase="prepared",
            transaction_id=transaction_id,
            operation_id=operation_id,
            attempt_no=0,
            intent=intent,
            projections=[projection],
            timestamp="2026-07-11T15:00:00Z",
        ),
        writer=CoordWriter.daemon(),
    )

    result = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=tmp_path / "transactions",
        task_id="task-1",
    )
    assert result.complete is False
    assert "transition_receipt_manifest_or_projection_missing" in result.reason_codes
    assert result.transactions[0].transaction_id == transaction_id
    assert result.transactions[0].state == "hold"


def test_lifecycle_inspection_holds_unsafe_and_unknown_journals(tmp_path: Path) -> None:
    log = _log(tmp_path)
    real_root = tmp_path / "real-transactions"
    real_root.mkdir(mode=0o700)
    unsafe_root = tmp_path / "unsafe-transactions"
    unsafe_root.symlink_to(real_root, target_is_directory=True)

    unsafe = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=unsafe_root,
    )
    assert unsafe.complete is False
    assert unsafe.transactions[0].transaction_id == "transition-root"
    assert unsafe.transactions[0].state == "hold"

    root = tmp_path / "transactions"
    root.mkdir(mode=0o700)
    (root / "unknown-journal").write_bytes(b"untyped\n")
    unknown = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=root,
    )
    assert unknown.complete is False
    assert unknown.transactions[0].transaction_id == "unknown-journal"
    assert unknown.transactions[0].reason_codes == ("transition_manifest_root_entry_unknown",)

    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    journal_root = tmp_path / "journal-transactions"
    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=journal_root,
        lock_root=tmp_path / "locks",
    )
    (receipt.manifest_path.parent / "stray.tmp").write_bytes(b"unknown\n")
    unknown_child = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=journal_root,
        task_id="task-1",
    )
    assert unknown_child.complete is False
    assert unknown_child.transactions[0].transaction_id == receipt.transaction_id
    assert unknown_child.transactions[0].reason_codes == (
        "transition_manifest_directory_entry_unknown",
        "transition_receipt_manifest_or_projection_missing",
    )


def test_lifecycle_inspection_discards_classification_when_seal_races(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=transaction_root,
        lock_root=tmp_path / "locks",
    )
    original_seal = cp.ReadOnlyFsSnapshot.seal

    def race_before_seal(snapshot: cp.ReadOnlyFsSnapshot):
        late_entry = transaction_root / "seal-race"
        late_entry.write_bytes(b"concurrent\n")
        late_entry.chmod(0o600)
        return original_seal(snapshot)

    with mock.patch.object(
        cp.ReadOnlyFsSnapshot,
        "seal",
        autospec=True,
        side_effect=race_before_seal,
    ):
        result = cp.inspect_lifecycle_transactions(
            event_plane_snapshot=_event_plane_snapshot(log),
            transaction_root=transaction_root,
            task_id="task-1",
        )

    assert result.complete is False
    assert result.fs_seal_ref is None
    assert result.transactions[0].transaction_id == "transition-root"
    assert result.transactions[0].state == "hold"
    assert result.transactions[0].reason_codes[0] in {
        "fs_snapshot_concurrent_change",
        "fs_snapshot_directory_changed",
        "fs_snapshot_listing_changed",
    }


def test_coord_replay_snapshot_is_exact_non_authorizing_support(tmp_path: Path) -> None:
    log = _log(tmp_path)
    intent = _intent()
    projection = cp.FileProjection.from_snapshot(
        tmp_path / "vault" / "task-1.md",
        before=b"stage: S6\n",
        before_mode=0o644,
        after=b"stage: S7\n",
        after_mode=0o644,
    )
    operation_id = cp.lifecycle_transition_id(intent, [projection])
    transaction_id = cp._attempt_transaction_id(operation_id, 0)
    log.append(
        cp._transaction_event(
            event_type=cp.CANON_TRANSITION_PREPARED,
            phase="prepared",
            transaction_id=transaction_id,
            operation_id=operation_id,
            attempt_no=0,
            intent=intent,
            projections=[projection],
            timestamp="2026-07-11T15:00:00Z",
        ),
        writer=CoordWriter.daemon(),
    )

    snapshot = _event_plane_snapshot(log)

    assert snapshot.may_authorize is False
    assert snapshot.coverage_complete is True
    assert cp.CoordReplaySnapshot is CoordReplaySnapshot
    assert snapshot.since_sequence == 0
    assert snapshot.through_sequence == 1
    record = snapshot.model_dump(mode="json", by_alias=True)
    assert CoordReplaySnapshot.model_validate(record) == snapshot
    with pytest.raises(ValueError):
        CoordReplaySnapshot.model_validate({**record, "event_count": True})


def test_capture_coord_replay_snapshot_does_not_create_an_absent_ledger(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)

    snapshot = cp.capture_coord_replay_snapshot(log)

    assert snapshot.degraded is True
    assert snapshot.errors == ("coord_event_log_absent",)
    assert snapshot.event_count == 0
    assert snapshot.may_authorize is False
    assert not log.db_path.exists()


def test_lifecycle_inspection_seals_empty_estate_and_requires_event_coverage(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    root = tmp_path / "absent-transactions"

    covered = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=root,
        task_id="task-1",
        observed_at="2026-07-11T15:00:00Z",
    )
    uncovered = cp.inspect_lifecycle_transactions(
        transaction_root=root,
        task_id="task-1",
        observed_at="2026-07-11T15:00:00Z",
    )

    assert covered.scope_complete is True
    assert covered.transactions == ()
    assert covered.fs_seal_ref is not None
    assert dataclasses.replace(covered) == covered
    with pytest.raises(ValueError, match="identity mismatch"):
        dataclasses.replace(covered, envelope_hash="f" * 64)
    assert uncovered.scope_complete is False
    assert uncovered.event_plane_snapshot_ref is None
    assert "transition_event_plane_coverage_absent" in uncovered.reason_codes


def test_lifecycle_inspection_rejects_stale_event_plane_prefix(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    root = tmp_path / "transactions"
    cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=root,
        lock_root=tmp_path / "locks",
    )
    replay = log.replay()
    stale = _snapshot_from_replay(
        ReplayResult(events=replay.events[:1], source="sqlite"),
        ledger_path=log.db_path,
    )

    result = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=stale,
        transaction_root=root,
        task_id="task-1",
    )

    assert stale.coverage_complete is True
    assert result.scope_complete is False
    assert "transition_phase_projection_event_plane_missing" in result.reason_codes


def test_lifecycle_inspection_never_reads_sqlite_locks_or_mutators(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=transaction_root,
        lock_root=tmp_path / "locks",
    )
    event_snapshot = _event_plane_snapshot(log)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("read-only inspection crossed an effect boundary")

    with (
        mock.patch("sqlite3.connect", side_effect=forbidden),
        mock.patch.object(log, "replay", side_effect=forbidden),
        mock.patch.object(cp, "_transition_locks", side_effect=forbidden),
        mock.patch.object(cp, "_write_manifest", side_effect=forbidden),
        mock.patch.object(cp, "_strict_append_exact", side_effect=forbidden),
        mock.patch.object(cp, "_rollback_projections", side_effect=forbidden),
    ):
        result = cp.inspect_lifecycle_transactions(
            event_log=log,
            event_plane_snapshot=event_snapshot,
            transaction_root=transaction_root,
            task_id="task-1",
        )

    assert result.scope_complete is True


def test_lifecycle_definition_must_rebuild_from_exact_source() -> None:
    definition, source = cp._capture_current_lifecycle_definition()
    fabricated_record = definition.model_dump(mode="json", by_alias=True)
    fabricated_record["lifecycle_ref"] = "fabricated-lifecycle"
    identity_body = {
        key: value
        for key, value in fabricated_record.items()
        if key not in {"definition_ref", "definition_hash"}
    }
    digest = cp._domain_hash("hapax.lifecycle-definition.v1", identity_body)
    fabricated_record["definition_hash"] = digest
    fabricated_record["definition_ref"] = f"lifecycle-definition@sha256:{digest}"
    fabricated = cp.LifecycleDefinition.model_validate(fabricated_record)

    with pytest.raises(
        cp.LifecycleTransitionError,
        match="transition_lifecycle_source_mismatch",
    ):
        _intent(
            lifecycle_definition=fabricated,
            lifecycle_source=source,
        )


def test_lifecycle_inspection_uses_stored_definition_not_current_metadata_path(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=transaction_root,
        lock_root=tmp_path / "locks",
    )

    with mock.patch(
        "shared.sdlc_lifecycle.SDLC_STAGE_METADATA_PATH",
        tmp_path / "missing-current-metadata.yaml",
    ):
        result = cp.inspect_lifecycle_transactions(
            event_plane_snapshot=_event_plane_snapshot(log),
            transaction_root=transaction_root,
            task_id="task-1",
        )

    assert result.scope_complete is True
    assert result.transactions[0].state == "applied"


def test_historical_derivation_does_not_reexecute_current_compiler(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=transaction_root,
        lock_root=tmp_path / "locks",
    )
    event_snapshot = _event_plane_snapshot(log)

    with mock.patch.object(
        cp,
        "_rebuild_lifecycle_definition",
        side_effect=AssertionError("historical inspection invoked the live compiler"),
    ):
        result = cp.inspect_lifecycle_transactions(
            event_plane_snapshot=event_snapshot,
            transaction_root=transaction_root,
            task_id="task-1",
        )

    assert result.scope_complete is True
    assert result.transactions[0].state == "applied"


def test_unknown_historical_compiler_ref_is_typed_hold(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=transaction_root,
        lock_root=tmp_path / "locks",
    )
    manifest = json.loads(receipt.manifest_path.read_text(encoding="ascii"))
    manifest["lifecycle_definition"]["compiler_ref"] = "hapax.lifecycle-definition-compiler@unknown"
    receipt.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="ascii",
    )

    result = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=transaction_root,
        task_id="task-1",
    )

    assert result.scope_complete is False
    assert "transition_lifecycle_compiler_unsupported" in result.reason_codes


def test_lifecycle_inspection_rejects_mutated_replay_snapshot(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    transaction_root = tmp_path / "transactions"
    cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=transaction_root,
        lock_root=tmp_path / "locks",
    )
    snapshot = _event_plane_snapshot(log)
    with pytest.raises(TypeError):
        snapshot.events[0].payload["operation_id"] = "sdlc-txn-" + "f" * 64
    changed_event = snapshot.events[0].model_copy(
        update={
            "payload": {
                **snapshot.events[0].model_dump(mode="json")["payload"],
                "operation_id": "sdlc-txn-" + "f" * 64,
            }
        }
    )
    snapshot = snapshot.model_copy(update={"events": (changed_event, *snapshot.events[1:])})

    result = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=snapshot,
        transaction_root=transaction_root,
        task_id="task-1",
    )

    assert result.scope_complete is False
    assert result.event_plane_snapshot_ref is None
    assert "transition_event_plane_snapshot_malformed" in result.reason_codes


@pytest.mark.parametrize("artifact", ("source", "definition", "phase"))
def test_lifecycle_inspection_holds_tampered_self_contained_artifact(
    tmp_path: Path,
    artifact: str,
) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    root = tmp_path / "transactions"
    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[cp.FileProjection.capture(note, after=b"stage: S7\n")],
        transaction_root=root,
        lock_root=tmp_path / "locks",
    )
    journal = receipt.manifest_path.parent
    if artifact == "source":
        target = journal / cp._LIFECYCLE_SOURCE_BLOB
        target.write_bytes(target.read_bytes() + b"# semantic drift\n")
    elif artifact == "definition":
        target = journal / cp._LIFECYCLE_DEFINITION_BLOB
        record = json.loads(target.read_text(encoding="ascii"))
        record["lifecycle_ref"] = "tampered-lifecycle"
        target.write_text(
            json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="ascii",
        )
    else:
        target = journal / cp._phase_projection_name("prepared")
        record = json.loads(target.read_text(encoding="ascii"))
        record["projection_hash"] = "f" * 64
        target.write_text(
            json.dumps(record, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="ascii",
        )

    result = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=root,
        task_id="task-1",
    )

    assert result.scope_complete is False
    assert result.transactions[0].state == "hold"
    assert any("malformed" in reason or "mismatch" in reason for reason in result.reason_codes)


def test_preserved_v1_history_is_visible_but_does_not_block_unrelated_scope(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    lock_root = tmp_path / "locks"
    note_a = tmp_path / "vault" / "task-a.md"
    note_b = tmp_path / "vault" / "task-b.md"
    note_a.parent.mkdir()
    note_a.write_bytes(b"stage: S6\n")
    note_b.write_bytes(b"stage: S6\n")
    cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(task_id="task-a"),
        projections=[cp.FileProjection.capture(note_a, after=b"stage: S7\n")],
        transaction_root=root,
        lock_root=lock_root,
    )
    legacy = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(task_id="task-b"),
        projections=[cp.FileProjection.capture(note_b, after=b"stage: S7\n")],
        transaction_root=root,
        lock_root=lock_root,
    )
    legacy_manifest = json.loads(legacy.manifest_path.read_text(encoding="ascii"))
    legacy_manifest["schema"] = cp.TRANSITION_TRANSACTION_SCHEMA_V1
    legacy.manifest_path.write_text(
        json.dumps(
            legacy_manifest,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
    )
    events = tuple(
        dataclasses.replace(
            event,
            payload={
                **event.payload,
                "schema": cp.TRANSITION_TRANSACTION_SCHEMA_V1,
            },
        )
        if event.subject == "task-b"
        else event
        for event in log.replay().events
    )
    event_snapshot = _snapshot_from_replay(
        ReplayResult(events=events, source="sqlite"),
        ledger_path=log.db_path,
    )

    result = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=event_snapshot,
        transaction_root=root,
        task_id="task-a",
    )

    assert result.estate_complete is False
    assert result.scope_complete is True
    legacy_result = next(item for item in result.transactions if item.task_id == "task-b")
    assert legacy_result.state == "hold"
    assert "transition_v1_self_containment_absent" in legacy_result.reason_codes


def test_lifecycle_scope_ignores_proven_unrelated_task_hold(tmp_path: Path) -> None:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    lock_root = tmp_path / "locks"
    note_a = tmp_path / "vault" / "task-a.md"
    note_b = tmp_path / "vault" / "task-b.md"
    note_a.parent.mkdir()
    note_a.write_bytes(b"stage: S6\n")
    note_b.write_bytes(b"stage: S6\n")
    cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(task_id="task-a"),
        projections=[cp.FileProjection.capture(note_a, after=b"stage: S7\n")],
        transaction_root=root,
        lock_root=lock_root,
    )

    def crash(phase: str, index: int | None) -> None:
        if phase == "before_prepared":
            raise SystemExit(92)

    with pytest.raises(SystemExit):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(task_id="task-b"),
            projections=[cp.FileProjection.capture(note_b, after=b"stage: S7\n")],
            transaction_root=root,
            lock_root=lock_root,
            failure_hook=crash,
        )

    result = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=root,
        task_id="task-a",
    )

    assert result.estate_complete is False
    assert result.scope_complete is True
    assert len(result.transactions) == 2
    assert len(result.scope_transaction_refs) == 1


def test_lifecycle_inspection_rejects_two_applied_attempts(tmp_path: Path) -> None:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    intent = _intent()
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    cp.execute_lifecycle_transition(
        event_log=log,
        intent=intent,
        projections=[projection],
        transaction_root=root,
        lock_root=tmp_path / "locks",
        timestamp="2026-07-11T15:00:00Z",
    )
    operation_id = cp.lifecycle_transition_id(intent, [projection])
    transaction_id = cp._attempt_transaction_id(operation_id, 1)
    scratches = (cp._scratch_for(projection, transaction_id, 0),)
    cp._write_manifest(
        root,
        operation_id,
        1,
        transaction_id,
        intent,
        [projection],
        scratches,
        timestamp="2026-07-11T16:00:00Z",
        state="created",
    )
    prepared_event = cp._transaction_event(
        event_type=cp.CANON_TRANSITION_PREPARED,
        phase="prepared",
        transaction_id=transaction_id,
        operation_id=operation_id,
        attempt_no=1,
        intent=intent,
        projections=[projection],
        timestamp="2026-07-11T16:00:00Z",
    )
    applied_event = cp._transaction_event(
        event_type=cp.CANON_TRANSITION_APPLIED,
        phase="applied",
        transaction_id=transaction_id,
        operation_id=operation_id,
        attempt_no=1,
        intent=intent,
        projections=[projection],
        timestamp="2026-07-11T16:00:00Z",
    )
    prepared_receipt = log.append(prepared_event, writer=CoordWriter.daemon())
    prepared_projection = cp._project_phase_append_receipt(
        root / transaction_id,
        prepared_event,
        prepared_receipt,
        prior=None,
    )
    cp._write_manifest(
        root,
        operation_id,
        1,
        transaction_id,
        intent,
        [projection],
        scratches,
        timestamp="2026-07-11T16:00:00Z",
        state="prepared",
    )
    applied_receipt = log.append(applied_event, writer=CoordWriter.daemon())
    cp._project_phase_append_receipt(
        root / transaction_id,
        applied_event,
        applied_receipt,
        prior=prepared_projection,
    )
    cp._write_manifest(
        root,
        operation_id,
        1,
        transaction_id,
        intent,
        [projection],
        scratches,
        timestamp="2026-07-11T16:00:00Z",
        state="applied",
    )

    result = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=root,
        task_id="task-1",
    )

    assert result.scope_complete is False
    assert "transition_operation_applied_multiple" in result.reason_codes
    assert {item.state for item in result.transactions} == {"hold"}


def test_lifecycle_writer_refuses_uninspectable_blob_before_journal_write(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    projection = cp.FileProjection.from_snapshot(
        note,
        before=None,
        before_mode=None,
        after=b"x" * (cp._MAX_LIFECYCLE_BLOB_BYTES + 1),
        after_mode=0o600,
    )

    with pytest.raises(
        cp.LifecycleTransitionError,
        match="transition_manifest_inspection_bound_exceeded",
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=root,
            lock_root=tmp_path / "locks",
        )

    assert not root.exists()
    assert log.replay().events == ()


def _interrupt_initial_materialization(
    tmp_path: Path,
    *,
    cut_after_install: int,
) -> tuple[CoordEventLog, Path, Path, Path, cp.FileProjection]:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    lock_root = tmp_path / "locks"
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_install = cp._atomic_install
    installs = 0

    def crash_after_install(
        path: Path,
        payload: bytes | None,
        mode: int | None,
        expected: cp._EntryState | None,
    ) -> None:
        nonlocal installs
        original_install(path, payload, mode, expected)
        installs += 1
        if installs == cut_after_install:
            raise SystemExit(92)

    with (
        mock.patch.object(cp, "_atomic_install", side_effect=crash_after_install),
        pytest.raises(SystemExit),
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=root,
            lock_root=lock_root,
            timestamp="2026-07-11T15:00:00Z",
        )
    return log, root, lock_root, note, projection


@pytest.mark.parametrize("cut_after_install", (1, 2, 3, 4, 5, 6))
def test_initial_journal_materialization_is_resumable_at_every_artifact_cut(
    tmp_path: Path,
    cut_after_install: int,
) -> None:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_install = cp._atomic_install
    installs = 0

    def crash_after_install(
        path: Path,
        payload: bytes | None,
        mode: int | None,
        expected: cp._EntryState | None,
    ) -> None:
        nonlocal installs
        original_install(path, payload, mode, expected)
        installs += 1
        if installs == cut_after_install:
            raise SystemExit(93)

    with (
        mock.patch.object(cp, "_now_iso", return_value="2026-07-11T15:00:00Z"),
        mock.patch.object(cp, "_atomic_install", side_effect=crash_after_install),
        pytest.raises(SystemExit),
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=root,
            lock_root=tmp_path / "locks",
        )

    assert tuple(root.glob("sdlc-txn-*.attempt-*")) == ()
    assert log.replay().events == ()
    interrupted = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=root,
        task_id="task-1",
    )
    assert interrupted.scope_complete is False
    assert interrupted.transactions[0].state == "hold"

    recovered = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=root,
        lock_root=tmp_path / "locks",
    )
    assert recovered[0].state == "not_started"
    assert recovered[0].reason_code == "transition_materialization_promoted"
    with mock.patch.object(cp, "_now_iso", return_value="2026-07-11T16:00:00Z"):
        receipt = cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=root,
            lock_root=tmp_path / "locks",
        )
    assert receipt.manifest_path.is_file()
    manifest = json.loads(receipt.manifest_path.read_text(encoding="ascii"))
    assert manifest["created_at"] == "2026-07-11T15:00:00Z"
    assert tuple(cp._materialization_root(root).iterdir()) == ()
    completed = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=root,
        task_id="task-1",
    )
    assert completed.scope_complete is True


def test_boot_recovery_promotes_complete_staged_materialization(tmp_path: Path) -> None:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    lock_root = tmp_path / "locks"
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_install = cp._atomic_install
    installs = 0

    def crash_after_manifest(
        path: Path,
        payload: bytes | None,
        mode: int | None,
        expected: cp._EntryState | None,
    ) -> None:
        nonlocal installs
        original_install(path, payload, mode, expected)
        installs += 1
        if installs == 6:
            raise SystemExit(94)

    with (
        mock.patch.object(cp, "_atomic_install", side_effect=crash_after_manifest),
        pytest.raises(SystemExit),
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=root,
            lock_root=lock_root,
            timestamp="2026-07-11T15:00:00Z",
        )

    recovered = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=root,
        lock_root=lock_root,
    )
    assert recovered[0].state == "not_started"
    assert recovered[0].reason_code == "transition_materialization_promoted"
    assert tuple(cp._materialization_root(root).iterdir()) == ()

    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[projection],
        transaction_root=root,
        lock_root=lock_root,
        timestamp="2026-07-11T16:00:00Z",
    )
    assert receipt.manifest_path.is_file()


def test_plan_and_stage_count_as_one_materialization_identity(tmp_path: Path) -> None:
    log, root, _lock_root, _note, _projection = _interrupt_initial_materialization(
        tmp_path,
        cut_after_install=6,
    )

    with mock.patch.object(cp, "_MAX_LIFECYCLE_TRANSACTIONS", 1):
        inspected = cp.inspect_lifecycle_transactions(
            event_plane_snapshot=_event_plane_snapshot(log),
            transaction_root=root,
            task_id="task-1",
        )

    assert len(inspected.transactions) == 1
    assert inspected.transactions[0].state == "hold"
    assert "transition_manifest_count_limit" not in inspected.reason_codes


def test_semantically_invalid_self_hashed_plan_is_unattributed_global_hold(
    tmp_path: Path,
) -> None:
    log, root, lock_root, _note, _projection = _interrupt_initial_materialization(
        tmp_path,
        cut_after_install=1,
    )
    materialization_root = cp._materialization_root(root)
    plan_path = next(materialization_root.glob("*.plan.json"))
    plan = cp._load_materialization_plan(plan_path)
    artifacts = dict(plan.artifacts)
    artifacts[cp._LIFECYCLE_SOURCE_BLOB] += b"# forged source\n"
    forged = cp.LifecycleMaterializationPlan.create(plan.transaction_id, artifacts)
    plan_path.write_bytes(forged.payload())

    inspected = cp.inspect_lifecycle_transactions(
        event_plane_snapshot=_event_plane_snapshot(log),
        transaction_root=root,
        task_id="unrelated-task",
    )
    recovered = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=root,
        lock_root=lock_root,
    )

    assert inspected.scope_complete is False
    assert inspected.transactions[0].task_id is None
    assert recovered == (
        cp.LifecycleRecoveryResult(
            plan.transaction_id,
            "recovery_required",
            "transition_lifecycle_source_mismatch",
        ),
    )
    assert tuple(path for path in materialization_root.iterdir() if path.is_dir()) == ()


def test_materialization_plan_refuses_existing_phase_receipt_before_write(
    tmp_path: Path,
) -> None:
    log, root, lock_root, _note, projection = _interrupt_initial_materialization(
        tmp_path,
        cut_after_install=1,
    )
    intent = _intent()
    operation_id = cp.lifecycle_transition_id(intent, [projection])
    transaction_id = cp._attempt_transaction_id(operation_id, 0)
    log.append(
        cp._transaction_event(
            event_type=cp.CANON_TRANSITION_PREPARED,
            phase="prepared",
            transaction_id=transaction_id,
            operation_id=operation_id,
            attempt_no=0,
            intent=intent,
            projections=[projection],
            timestamp="2026-07-11T15:00:00Z",
        ),
        writer=CoordWriter.daemon(),
    )

    recovered = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=root,
        lock_root=lock_root,
    )

    assert recovered == (
        cp.LifecycleRecoveryResult(
            transaction_id,
            "recovery_required",
            "transition_materialization_receipt_present",
        ),
    )
    assert not (root / transaction_id).exists()
    assert not (cp._materialization_root(root) / transaction_id).exists()


def test_failed_plan_blocks_complete_stage_from_second_pass(tmp_path: Path) -> None:
    log, root, lock_root, _note, _projection = _interrupt_initial_materialization(
        tmp_path,
        cut_after_install=6,
    )
    materialization_root = cp._materialization_root(root)
    plan_path = next(materialization_root.glob("*.plan.json"))
    transaction_id = plan_path.name.removesuffix(".plan.json")
    plan_path.write_bytes(b"{}\n")

    recovered = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=root,
        lock_root=lock_root,
    )

    assert len(recovered) == 1
    assert recovered[0].transaction_id == transaction_id
    assert recovered[0].state == "recovery_required"
    assert not (root / transaction_id).exists()
    assert (materialization_root / transaction_id / "manifest.json").is_file()
    assert plan_path.read_bytes() == b"{}\n"


def test_residual_plan_requires_exact_promoted_static_identity(tmp_path: Path) -> None:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    lock_root = tmp_path / "locks"
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_rename = cp._renameat2

    def crash_after_promotion(
        src_dir_fd: int,
        src_name: str,
        dst_dir_fd: int,
        dst_name: str,
        flags: int,
    ) -> None:
        original_rename(src_dir_fd, src_name, dst_dir_fd, dst_name, flags)
        if src_name == dst_name and cp._TRANSACTION_DIRECTORY_RE.fullmatch(src_name) is not None:
            raise SystemExit(97)

    with (
        mock.patch.object(cp, "_renameat2", side_effect=crash_after_promotion),
        pytest.raises(SystemExit),
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=root,
            lock_root=lock_root,
            timestamp="2026-07-11T15:00:00Z",
        )

    materialization_root = cp._materialization_root(root)
    plan_path = next(materialization_root.glob("*.plan.json"))
    plan = cp._load_materialization_plan(plan_path)
    artifacts = dict(plan.artifacts)
    manifest = json.loads(artifacts["manifest.json"])
    manifest["created_at"] = "2026-07-11T15:00:01Z"
    artifacts["manifest.json"] = (
        json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("ascii")
    forged = cp.LifecycleMaterializationPlan.create(plan.transaction_id, artifacts)
    plan_path.write_bytes(forged.payload())

    recovered = cp.recover_lifecycle_transactions(
        event_log=log,
        transaction_root=root,
        lock_root=lock_root,
    )

    assert len(recovered) == 1
    assert recovered[0].reason_code == "transition_materialization_plan_collision"
    assert plan_path.read_bytes() == forged.payload()
    assert (root / plan.transaction_id / "manifest.json").is_file()


@pytest.mark.parametrize("cut", ("rename", "source_fsync", "destination_fsync"))
def test_materialization_promotion_is_resumable_after_rename_cuts(
    tmp_path: Path,
    cut: str,
) -> None:
    log = _log(tmp_path)
    root = tmp_path / "transactions"
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    original_rename = cp._renameat2
    original_fsync = os.fsync
    promoted = False
    promotion_fsyncs = 0

    def cut_after_rename(
        src_dir_fd: int,
        src_name: str,
        dst_dir_fd: int,
        dst_name: str,
        flags: int,
    ) -> None:
        nonlocal promoted
        original_rename(src_dir_fd, src_name, dst_dir_fd, dst_name, flags)
        if src_name != dst_name or cp._TRANSACTION_DIRECTORY_RE.fullmatch(src_name) is None:
            return
        promoted = True
        if cut == "rename":
            raise SystemExit(95)

    def cut_after_fsync(fd: int) -> None:
        nonlocal promotion_fsyncs
        original_fsync(fd)
        if not promoted:
            return
        promotion_fsyncs += 1
        if (
            cut == "source_fsync"
            and promotion_fsyncs == 1
            or cut == "destination_fsync"
            and promotion_fsyncs == 2
        ):
            raise SystemExit(96)

    with (
        mock.patch.object(cp, "_renameat2", side_effect=cut_after_rename),
        mock.patch.object(os, "fsync", side_effect=cut_after_fsync),
        pytest.raises(SystemExit),
    ):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=root,
            lock_root=tmp_path / "locks",
            timestamp="2026-07-11T15:00:00Z",
        )

    assert len(tuple(root.glob("sdlc-txn-*.attempt-*"))) == 1
    receipt = cp.execute_lifecycle_transition(
        event_log=log,
        intent=_intent(),
        projections=[projection],
        transaction_root=root,
        lock_root=tmp_path / "locks",
        timestamp="2026-07-11T16:00:00Z",
    )
    assert receipt.manifest_path.is_file()
    assert (
        json.loads(receipt.manifest_path.read_text(encoding="ascii"))["created_at"]
        == "2026-07-11T15:00:00Z"
    )


# --- universal zero-write filesystem snapshot -------------------------------


def test_read_only_fs_snapshot_seals_exact_private_tree_without_effect(
    tmp_path: Path,
) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    payload = root / "manifest.json"
    payload.write_bytes(b"exact bytes\n")
    payload.chmod(0o600)
    before = _filesystem_tree(root)

    with cp.ReadOnlyFsSnapshot(max_total_bytes=1024) as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        assert snapshot.list_names(directory) == ("manifest.json",)
        observed = snapshot.observe_file_at(
            directory,
            "manifest.json",
            private=True,
            max_bytes=1024,
        )
        assert observed.present is True
        assert observed.captured is not None
        assert observed.captured.content == b"exact bytes\n"
        seal = snapshot.seal()

    assert _filesystem_tree(root) == before
    assert seal.may_authorize is False
    assert seal.seal_ref == f"read-only-fs-snapshot@sha256:{seal.seal_hash}"
    assert seal.directory_observations == (directory.observation_sha256,)
    assert seal.file_observations == (observed.observation_sha256,)


@pytest.mark.parametrize(
    ("change_scope", "should_seal"),
    (("estate", False), ("observed_paths", True)),
)
def test_read_only_fs_snapshot_scopes_unrelated_sibling_churn(
    tmp_path: Path,
    change_scope: str,
    should_seal: bool,
) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    observed_path = root / "observed.json"
    observed_path.write_bytes(b"exact\n")
    observed_path.chmod(0o600)

    with cp.ReadOnlyFsSnapshot(
        max_total_bytes=1024,
        change_scope=change_scope,  # type: ignore[arg-type]
    ) as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        snapshot.observe_file_at(
            directory,
            observed_path.name,
            private=True,
            max_bytes=1024,
        )
        sibling = root / "unrelated.json"
        sibling.write_bytes(b"unrelated\n")
        sibling.chmod(0o600)
        sibling.unlink()
        if should_seal:
            seal = snapshot.seal()
        else:
            with pytest.raises(cp.ReadOnlySnapshotError) as raised:
                snapshot.seal()

    if should_seal:
        assert seal.schema == "hapax.read-only-fs-snapshot.v2"
        assert seal.change_scope == "observed_paths"
    else:
        assert raised.value.reason_code in {
            "fs_snapshot_concurrent_change",
            "fs_snapshot_directory_changed",
        }


def test_observed_paths_snapshot_detects_absent_name_aba(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)

    with cp.ReadOnlyFsSnapshot(change_scope="observed_paths") as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        observed = snapshot.observe_file_at(
            directory,
            "absent.json",
            private=True,
            max_bytes=1024,
        )
        assert observed.present is False
        raced = root / "absent.json"
        raced.write_bytes(b"raced\n")
        raced.chmod(0o600)
        raced.unlink()
        with pytest.raises(cp.ReadOnlySnapshotError) as raised:
            snapshot.seal()

    assert raised.value.reason_code == "fs_snapshot_concurrent_change"


def test_observed_paths_listing_makes_unrelated_names_relevant(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)

    with cp.ReadOnlyFsSnapshot(change_scope="observed_paths") as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        assert snapshot.list_names(directory) == ()
        sibling = root / "unrelated.json"
        sibling.write_bytes(b"unrelated\n")
        sibling.chmod(0o600)
        sibling.unlink()
        with pytest.raises(cp.ReadOnlySnapshotError) as raised:
            snapshot.seal()

    assert raised.value.reason_code in {
        "fs_snapshot_concurrent_change",
        "fs_snapshot_listing_changed",
    }


def test_observed_paths_snapshot_detects_exact_directory_rename_aba(
    tmp_path: Path,
) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    child = root / "objects"
    child.mkdir(mode=0o700)
    parked = root / "parked"

    with cp.ReadOnlyFsSnapshot(change_scope="observed_paths") as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        snapshot.pin_dir_at(directory, "objects", private=True)
        child.rename(parked)
        parked.rename(child)
        with pytest.raises(cp.ReadOnlySnapshotError) as raised:
            snapshot.seal()

    assert raised.value.reason_code in {
        "fs_snapshot_concurrent_change",
        "fs_snapshot_directory_changed",
    }


def test_read_only_fs_snapshot_rejects_scope_schema_aliasing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="change_scope"):
        cp.ReadOnlyFsSnapshot(change_scope="partial")  # type: ignore[arg-type]

    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    with cp.ReadOnlyFsSnapshot(change_scope="observed_paths") as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        seal = snapshot.seal()

    with pytest.raises(ValueError, match="scope/schema mismatch"):
        dataclasses.replace(seal, schema="hapax.read-only-fs-snapshot.v1")


@pytest.mark.parametrize("unsafe_kind", ("symlink", "mode", "hardlink", "fifo"))
def test_read_only_fs_snapshot_refuses_unsafe_objects_without_blocking(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    target = root / "target"
    target.write_bytes(b"payload\n")
    target.chmod(0o600)

    if unsafe_kind == "symlink":
        candidate = root / "candidate"
        candidate.symlink_to(target)
    elif unsafe_kind == "mode":
        candidate = target
        candidate.chmod(0o640)
    elif unsafe_kind == "hardlink":
        candidate = root / "candidate"
        os.link(target, candidate)
    else:
        candidate = root / "candidate"
        os.mkfifo(candidate, 0o600)

    with cp.ReadOnlyFsSnapshot(max_total_bytes=1024) as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        with pytest.raises(cp.ReadOnlySnapshotError) as raised:
            snapshot.observe_file_at(
                directory,
                candidate.name,
                private=True,
                max_bytes=1024,
            )

    assert raised.value.reason_code == "fs_snapshot_file_unsafe"


def test_read_only_fs_snapshot_refuses_nonprivate_directory(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o755)

    with cp.ReadOnlyFsSnapshot() as snapshot:
        with pytest.raises(cp.ReadOnlySnapshotError) as raised:
            snapshot.pin_absolute_dir(root, private_final=True)

    assert raised.value.reason_code == "fs_snapshot_private_directory_unsafe"


def test_read_only_fs_snapshot_detects_file_aba_before_seal(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    payload = root / "manifest.json"
    payload.write_bytes(b"A\n")
    payload.chmod(0o600)

    with cp.ReadOnlyFsSnapshot(max_total_bytes=1024) as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        snapshot.list_names(directory)
        snapshot.observe_file_at(
            directory,
            payload.name,
            private=True,
            max_bytes=1024,
        )
        payload.write_bytes(b"B\n")
        payload.write_bytes(b"A\n")
        with pytest.raises(cp.ReadOnlySnapshotError) as raised:
            snapshot.seal()
        with pytest.raises(cp.ReadOnlySnapshotError) as retry:
            snapshot.seal()

    assert raised.value.reason_code in {
        "fs_snapshot_concurrent_change",
        "fs_snapshot_file_changed",
    }
    assert retry.value.reason_code == "fs_snapshot_lifecycle_invalid"


def test_read_only_fs_snapshot_detects_directory_rename_aba(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    parked = tmp_path / "parked"

    with cp.ReadOnlyFsSnapshot() as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        snapshot.list_names(directory)
        root.rename(parked)
        parked.rename(root)
        with pytest.raises(cp.ReadOnlySnapshotError) as raised:
            snapshot.seal()

    assert raised.value.reason_code in {
        "fs_snapshot_concurrent_change",
        "fs_snapshot_directory_changed",
    }


def test_read_only_fs_snapshot_enforces_file_and_aggregate_bounds(
    tmp_path: Path,
) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    payload = root / "manifest.json"
    payload.write_bytes(b"0123456789")
    payload.chmod(0o600)

    with cp.ReadOnlyFsSnapshot(max_total_bytes=8) as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        with pytest.raises(cp.ReadOnlySnapshotError) as raised:
            snapshot.observe_file_at(
                directory,
                payload.name,
                private=True,
                max_bytes=8,
            )

    assert raised.value.reason_code == "fs_snapshot_size_limit"


def test_read_only_fs_snapshot_seals_absent_directory_and_detects_creation(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700)
    missing = parent / "missing"

    with cp.ReadOnlyFsSnapshot() as snapshot:
        assert (
            snapshot.pin_absolute_dir(
                missing,
                private_final=True,
                allow_missing=True,
            )
            is None
        )
        seal = snapshot.seal()

    assert seal.absence_observations
    assert seal.listing_observations

    with cp.ReadOnlyFsSnapshot() as snapshot:
        assert (
            snapshot.pin_absolute_dir(
                missing,
                private_final=True,
                allow_missing=True,
            )
            is None
        )
        missing.mkdir(mode=0o700)
        with pytest.raises(cp.ReadOnlySnapshotError) as raised:
            snapshot.seal()

    assert raised.value.reason_code in {
        "fs_snapshot_concurrent_change",
        "fs_snapshot_directory_changed",
        "fs_snapshot_listing_changed",
    }


def test_read_only_fs_snapshot_seal_is_self_validating(tmp_path: Path) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    with cp.ReadOnlyFsSnapshot() as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        snapshot.list_names(directory)
        seal = snapshot.seal()

    with pytest.raises(ValueError, match="identity mismatch"):
        dataclasses.replace(seal, seal_hash="f" * 64)


def test_read_only_fs_snapshot_rejects_foreign_and_expired_handles(
    tmp_path: Path,
) -> None:
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    first = cp.ReadOnlyFsSnapshot()
    second = cp.ReadOnlyFsSnapshot()
    try:
        directory = first.pin_absolute_dir(root, private_final=True)
        assert directory is not None
        with pytest.raises(cp.ReadOnlySnapshotError) as foreign:
            second.list_names(directory)
        assert foreign.value.reason_code == "fs_snapshot_handle_foreign"
        first.list_names(directory)
        first.seal()
        with pytest.raises(cp.ReadOnlySnapshotError) as sealed:
            first.list_names(directory)
        assert sealed.value.reason_code == "fs_snapshot_lifecycle_invalid"
        first.close()
        with pytest.raises(cp.ReadOnlySnapshotError) as closed:
            first.observe_file_at(
                directory,
                "missing",
                private=True,
                max_bytes=1024,
            )
        assert closed.value.reason_code == "fs_snapshot_lifecycle_invalid"
    finally:
        first.close()
        second.close()


def test_read_only_fs_snapshot_nonprivate_listing_preserves_atime(
    tmp_path: Path,
) -> None:
    root = tmp_path / "shared"
    root.mkdir(mode=0o755)
    before = root.stat().st_atime_ns

    with cp.ReadOnlyFsSnapshot() as snapshot:
        directory = snapshot.pin_absolute_dir(root, private_final=False)
        assert directory is not None
        assert snapshot.list_names(directory) == ()
        snapshot.seal()

    assert root.stat().st_atime_ns == before


def test_read_only_fs_snapshot_refuses_unbounded_root_observation() -> None:
    with cp.ReadOnlyFsSnapshot() as snapshot:
        with pytest.raises(cp.ReadOnlySnapshotError) as raised:
            snapshot.pin_absolute_dir(Path("/"), private_final=False)

    assert raised.value.reason_code == "fs_snapshot_root_observation_forbidden"


# --- renameat2 flag fallback: mounts that refuse every non-zero flag ----------
#
# The vault SSOT moved onto NFS4.2, where `vfs_rename` rejects any non-zero
# renameat2 flag before the filesystem is reached, so RENAME_EXCHANGE and
# RENAME_NOREPLACE both return EINVAL while flags=0 succeeds (measured:
# NFS-RENAMEAT2-PROBE-MEASUREMENT-20260913.md). These tests state that mount
# rather than needing one: they substitute `_renameat2_primitive`, so the
# injected errno travels the real dispatch inside `_renameat2`.


class _Crash(Exception):
    """Stands in for the process dying between two steps of a rebuilt sequence."""


def _exists_at(dir_fd: int, name: str) -> bool:
    try:
        os.lstat(name, dir_fd=dir_fd)
    except FileNotFoundError:
        return False
    return True


def _unsupported_flag_mount(
    *,
    unsupported_errno: int = errno.EINVAL,
    flags_that_fail: frozenset[int] = frozenset({cp._RENAME_EXCHANGE, cp._RENAME_NOREPLACE}),
) -> Callable[[int, str, int, str, int], int]:
    """Return a `_renameat2_primitive` substitute for a mount lacking those flags.

    NOREPLACE keeps its EEXIST answer when the destination exists: the VFS runs
    that existence check before it ever consults the filesystem, so a mount that
    cannot honour the flag still refuses a racing create correctly, and only the
    dst-absent case reaches `vfs_rename` and EINVALs. Reproducing that asymmetry
    is what makes this a mount simulation rather than a blanket error injector.
    """

    real = cp._renameat2_primitive

    def primitive(
        src_dir_fd: int,
        src_name: str,
        dst_dir_fd: int,
        dst_name: str,
        flags: int,
    ) -> int:
        if flags in flags_that_fail:
            if flags == cp._RENAME_NOREPLACE and _exists_at(dst_dir_fd, dst_name):
                return errno.EEXIST
            return unsupported_errno
        return real(src_dir_fd, src_name, dst_dir_fd, dst_name, flags)

    return primitive


def test_update_projects_on_a_mount_that_refuses_rename_exchange(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")

    with mock.patch.object(cp, "_renameat2_primitive", side_effect=_unsupported_flag_mount()):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
        )

    assert note.read_bytes() == b"stage: S7\n"
    assert stat.S_IMODE(note.stat().st_mode) == projection.after_mode
    assert not list(note.parent.glob(".*.transition-scratch"))
    assert not _fallback_remnants(note.parent)
    assert [event.event_type for event in log.replay().events] == [
        cp.CANON_TRANSITION_PREPARED,
        cp.CANON_TRANSITION_APPLIED,
    ]


def test_create_projects_on_a_mount_that_refuses_rename_noreplace(tmp_path: Path) -> None:
    """The create leg is the one such a mount breaks on every single call.

    NOREPLACE's existence check passes when the destination is absent, so the
    unsupported flag reaches `vfs_rename` and EINVALs — which is exactly the
    shape of a fresh claim publication, where neither note nor marker exists yet.
    """

    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    projection = cp.FileProjection.capture(note, after=b"created by transition\n")

    with mock.patch.object(cp, "_renameat2_primitive", side_effect=_unsupported_flag_mount()):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=[projection],
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
        )

    assert note.read_bytes() == b"created by transition\n"
    assert not list(note.parent.glob(".*.transition-scratch"))
    assert not _fallback_remnants(note.parent)
    assert [event.event_type for event in log.replay().events] == [
        cp.CANON_TRANSITION_PREPARED,
        cp.CANON_TRANSITION_APPLIED,
    ]


def test_claim_shaped_projection_lands_note_and_marker_on_such_a_mount(
    tmp_path: Path,
) -> None:
    """The production shape that failed: an updated note plus a created marker.

    A claim publication projects both in one transaction — the note flips
    offered->claimed (update, EXCHANGE) and the role marker appears (create,
    NOREPLACE) — so the two legs exercise different fallbacks. The measured
    failure left the note reverted to `offered` and no marker on disk, so both
    halves of the post-state are asserted here.
    """

    log = _log(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "task-1.md"
    note.write_bytes(b"status: offered\nassigned_to: unassigned\n")
    marker = vault / "task-1.claimed-by-beta"

    projections = [
        cp.FileProjection.capture(note, after=b"status: claimed\nassigned_to: beta\n"),
        cp.FileProjection.capture(marker, after=b"beta\n"),
    ]

    with mock.patch.object(cp, "_renameat2_primitive", side_effect=_unsupported_flag_mount()):
        cp.execute_lifecycle_transition(
            event_log=log,
            intent=_intent(),
            projections=projections,
            transaction_root=tmp_path / "transactions",
            lock_root=tmp_path / "locks",
        )

    assert note.read_bytes() == b"status: claimed\nassigned_to: beta\n"
    assert marker.read_bytes() == b"beta\n"
    assert not list(vault.glob(".*.transition-scratch"))
    assert not _fallback_remnants(vault)
    assert [event.event_type for event in log.replay().events] == [
        cp.CANON_TRANSITION_PREPARED,
        cp.CANON_TRANSITION_APPLIED,
    ]


def test_rebuilt_noreplace_still_refuses_a_racing_create(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    projection = cp.FileProjection.capture(note, after=b"created by transition\n")
    mount = _unsupported_flag_mount()
    raced = False

    def race_then_refuse(
        src_dir_fd: int,
        src_name: str,
        dst_dir_fd: int,
        dst_name: str,
        flags: int,
    ) -> int:
        nonlocal raced
        if flags == cp._RENAME_NOREPLACE and dst_name == note.name and not raced:
            raced = True
            note.write_bytes(b"third-party\n")
        return mount(src_dir_fd, src_name, dst_dir_fd, dst_name, flags)

    with mock.patch.object(cp, "_renameat2_primitive", side_effect=race_then_refuse):
        with pytest.raises(cp.LifecycleTransitionError, match="precondition_changed"):
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=_intent(),
                projections=[projection],
                transaction_root=tmp_path / "transactions",
                lock_root=tmp_path / "locks",
            )

    assert raced
    assert note.read_bytes() == b"third-party\n"
    assert not _fallback_remnants(note.parent)


def test_rebuilt_exchange_restores_a_racing_preimage_without_loss(tmp_path: Path) -> None:
    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    mount = _unsupported_flag_mount()
    raced = False

    def race_exchange(
        src_dir_fd: int,
        src_name: str,
        dst_dir_fd: int,
        dst_name: str,
        flags: int,
    ) -> int:
        nonlocal raced
        if flags == cp._RENAME_EXCHANGE and not raced:
            raced = True
            note.write_bytes(b"third-party\n")
        return mount(src_dir_fd, src_name, dst_dir_fd, dst_name, flags)

    with mock.patch.object(cp, "_renameat2_primitive", side_effect=race_exchange):
        with pytest.raises(cp.LifecycleTransitionError, match="precondition_changed"):
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=_intent(),
                projections=[projection],
                transaction_root=tmp_path / "transactions",
                lock_root=tmp_path / "locks",
            )

    assert raced
    assert note.read_bytes() == b"third-party\n"
    assert not _fallback_remnants(note.parent)
    assert [event.event_type for event in log.replay().events] == [
        cp.CANON_TRANSITION_PREPARED,
        cp.CANON_TRANSITION_ABORTED,
    ]


def test_exchange_fallback_reproduces_the_syscall_post_state(tmp_path: Path) -> None:
    """Post-state equivalence, which the rollback legs rely on — but it is NOT the whole
    contract, and this docstring used to say it was.

    Both names must survive — `dst` holding what `src` held and `src` holding the
    displaced bytes — so a rollback exchange can put them back. The inodes must
    swap too: callers detect races by comparing entry state, so a copy where the
    syscall moved an inode would read as a third-party write.

    What equivalence does **not** carry is the syscall's atomicity, and the callers
    depended on that to *surface* a concurrent writer rather than only to order the
    writes. A rebuild can satisfy every assertion here and still lose a racer's bytes
    while the readback passes. See the residual list on `_relocate_to_scratch`, the
    race tests below, and NFS-EXCHANGE-FALLBACK-DESIGN-20260911.md §8, which corrects
    the ratified design on exactly this point.
    """

    directory = tmp_path / "dir"
    directory.mkdir()
    (directory / "src").write_bytes(b"replacement\n")
    (directory / "dst").write_bytes(b"displaced\n")
    src_inode = (directory / "src").stat().st_ino
    dst_inode = (directory / "dst").stat().st_ino

    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        cp._fallback_exchange(dir_fd, "src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert (directory / "dst").read_bytes() == b"replacement\n"
    assert (directory / "src").read_bytes() == b"displaced\n"
    assert (directory / "dst").stat().st_ino == src_inode
    assert (directory / "src").stat().st_ino == dst_inode
    assert sorted(path.name for path in directory.iterdir()) == ["dst", "src"]


def test_exchange_fallback_keeps_both_entries_recoverable_at_every_cut(
    tmp_path: Path,
) -> None:
    """Crash injection between each step of the rebuilt sequence.

    The syscall is atomic and the rebuild is not, so what the rebuild owes is not
    atomicity but that no cut can lose bytes. At every cut both the replacement
    and the displaced entry must still be reachable under some name, and any
    surviving pin must carry the dotted prefix the scratch sweeps look for.
    """

    for cut in range(1, 12):
        directory = tmp_path / f"cut-{cut}"
        directory.mkdir()
        (directory / ".src").write_bytes(b"replacement\n")
        (directory / "dst").write_bytes(b"displaced\n")

        calls = 0
        real_link, real_rename = os.link, os.rename

        def counted_link(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if calls == cut:
                raise _Crash()
            return real_link(*args, **kwargs)  # type: ignore[arg-type]

        def counted_rename(*args: object, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if calls == cut:
                raise _Crash()
            return real_rename(*args, **kwargs)  # type: ignore[arg-type]

        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            with (
                mock.patch.object(os, "link", counted_link),
                mock.patch.object(os, "rename", counted_rename),
            ):
                try:
                    cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
                except _Crash:
                    pass
        finally:
            os.close(dir_fd)

        surviving = {path.read_bytes() for path in directory.iterdir() if path.is_file()}
        assert b"replacement\n" in surviving, f"cut {cut} lost the replacement"
        assert b"displaced\n" in surviving, f"cut {cut} lost the displaced entry"
        # Every remnant must be dotted AND computable from the operands. The check used to
        # test `".transition-pin." in name`, which the switch to deterministic names made
        # unmatchable — the names end at `.transition-pin` with no suffix — so it silently
        # stopped examining anything. A reviewer caught that; this is the repaired form.
        # The round-32 conversions extended the computable set beyond bare role names:
        # reserves for adornment targets, the dance's stacked `.transition-safety`, and
        # the release's `.transition-withdrawn` are all reachable crash states now, so the
        # closure is generated rather than listed.
        computable = _computable_fallback_names(".src", "dst")
        remnants = [p.name for p in directory.iterdir() if ".transition-" in p.name]
        for name in remnants:
            assert name.startswith("."), (
                f"cut {cut} left {name} where the scratch sweeps cannot see it"
            )
            assert name in computable, (
                f"cut {cut} left {name}, which is not computable from the operands"
            )
            assert name.count(".transition-") <= 3, (
                f"cut {cut} left {name} stacked deeper than any leg adorns — a name "
                "nothing can recompute, which is the unfindable-remnant defect again"
            )


def test_fallback_never_answers_an_errno_that_is_not_unsupported(tmp_path: Path) -> None:
    """A real refusal must not be retried by another route.

    ENOSPC means the operation was attempted and failed; rebuilding it from
    link+rename would attempt MORE than the primary did. The safety precondition
    is the kernel's own "this flag does not exist here", nothing weaker.
    """

    directory = tmp_path / "dir"
    directory.mkdir()
    (directory / "src").write_bytes(b"replacement\n")
    (directory / "dst").write_bytes(b"displaced\n")
    rebuilt = False

    def refusing(*_args: object) -> int:
        return errno.ENOSPC

    def record(*_args: object) -> None:
        nonlocal rebuilt
        rebuilt = True

    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with (
            mock.patch.object(cp, "_renameat2_primitive", side_effect=refusing),
            mock.patch.dict(
                cp._RENAME_FLAG_FALLBACKS,
                {cp._RENAME_EXCHANGE: record, cp._RENAME_NOREPLACE: record},
            ),
        ):
            with pytest.raises(OSError) as raised:
                cp._renameat2(dir_fd, "src", dir_fd, "dst", cp._RENAME_EXCHANGE)
    finally:
        os.close(dir_fd)

    assert raised.value.errno == errno.ENOSPC
    assert not rebuilt
    assert (directory / "dst").read_bytes() == b"displaced\n"


def test_rebuilt_exchange_refuses_a_cross_directory_rename(tmp_path: Path) -> None:
    """The exchange rebuild pins the displaced inode beside the entries it swaps,
    so it cannot span two directories: across a filesystem boundary the restock
    leg would have to be a copy, and a copy is not an exchange. It refuses rather
    than approximating — and every EXCHANGE call site is same-directory anyway."""

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "src").write_bytes(b"replacement\n")
    (second / "dst").write_bytes(b"displaced\n")

    src_fd = os.open(first, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    dst_fd = os.open(second, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with mock.patch.object(
            cp,
            "_renameat2_primitive",
            side_effect=_unsupported_flag_mount(),
        ):
            with pytest.raises(OSError) as raised:
                cp._renameat2(src_fd, "src", dst_fd, "dst", cp._RENAME_EXCHANGE)
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert raised.value.errno == errno.EXDEV
    assert (first / "src").read_bytes() == b"replacement\n"
    assert (second / "dst").read_bytes() == b"displaced\n"
    assert not _fallback_remnants(first)


def test_rebuilt_noreplace_promotes_a_directory_across_directories(
    tmp_path: Path,
) -> None:
    """Journal materialization renames a whole staged transaction directory into
    the canonical root under NOREPLACE. `link(2)` refuses directories, so this leg
    cannot use the file rebuild; it lstats the destination and then renames, refusing
    **any** existing entry with EEXIST — not only an empty directory. This docstring
    said "leaving only an empty destination directory to be refused explicitly",
    describing a narrow guard that was never implemented; the empty-directory case is
    merely the one where the guard is indispensable, since `rename` refuses the other
    shapes on its own. A mkdir-reservation design was drafted for this and
    **rejected**; see `_fallback_noreplace_directory`, which says why. Cross-directory
    by construction — the shape the ratified design's projection-leg inventory did not
    cover."""

    staging = tmp_path / "staging"
    final = tmp_path / "final"
    staging.mkdir()
    final.mkdir()
    journal = staging / "txn-1"
    journal.mkdir()
    (journal / "manifest.json").write_bytes(b"{}\n")

    src_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    dst_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with mock.patch.object(
            cp,
            "_renameat2_primitive",
            side_effect=_unsupported_flag_mount(),
        ):
            cp._renameat2(src_fd, "txn-1", dst_fd, "txn-1", cp._RENAME_NOREPLACE)
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert (final / "txn-1" / "manifest.json").read_bytes() == b"{}\n"
    assert not journal.exists()


@pytest.mark.parametrize(
    ("occupant", "label"),
    [
        ({"manifest.json": b'{"final": true}\n'}, "a populated journal"),
        ({}, "an empty directory"),
    ],
    ids=["populated-journal", "empty-directory"],
)
def test_rebuilt_directory_noreplace_refuses_an_occupied_destination(
    tmp_path: Path,
    occupant: dict[str, bytes],
    label: str,
) -> None:
    """Both occupied shapes get NOREPLACE's answer, and nothing is touched.

    Called directly rather than through `_renameat2`, because the wrapper cannot
    reach this branch on the mount being modelled: the VFS runs NOREPLACE's
    existence check before consulting the filesystem, so an occupied destination
    already returns EEXIST from the syscall and the rebuild never runs. Driving
    this through the wrapper would assert the simulator's own answer and stay
    green with the branch deleted — it did, until the mutation check caught it.

    The branch is still load-bearing: with the destination absent the syscall
    EINVALs, the rebuild does run, and `rename(2)` on directories would let an
    empty one through. Note the shipped guard refuses EVERY existing destination,
    not only an empty directory — the empty-directory case is merely the one where
    it is indispensable, since `rename` refuses the others on its own.

    `reached_rename` is what makes this a test of the GUARD rather than of the
    host's `rename`. Without it the populated case is host-dependent theatre: xfs
    answers EEXIST for a rename onto a non-empty directory, so an errno-only
    assertion stays green with the guard narrowed to empty directories — measured,
    that mutation passed here and failed on the sibling window test. tmpfs and
    nfs4 answer ENOTEMPTY for the same call, so the same mutation would have been
    caught on those. Pin the mechanism and the host stops mattering.
    """

    staging = tmp_path / "staging"
    final = tmp_path / "final"
    staging.mkdir()
    final.mkdir()
    (staging / "txn-1").mkdir()
    (staging / "txn-1" / "manifest.json").write_bytes(b'{"staged": true}\n')
    (final / "txn-1").mkdir()
    for name, payload in occupant.items():
        (final / "txn-1" / name).write_bytes(payload)

    reached_rename = False
    real_rename = os.rename

    def note_rename(*args: object, **kwargs: object) -> None:
        nonlocal reached_rename
        reached_rename = True
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    src_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    dst_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with mock.patch.object(os, "rename", note_rename):
            with pytest.raises(OSError) as raised:
                cp._fallback_noreplace(src_fd, "txn-1", dst_fd, "txn-1")
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert raised.value.errno == errno.EEXIST, label
    assert not reached_rename, f"{label}: refused by rename, not by the leg's own guard"
    assert (staging / "txn-1" / "manifest.json").read_bytes() == b'{"staged": true}\n'
    assert sorted(path.name for path in (final / "txn-1").iterdir()) == sorted(occupant)


def test_rebuilt_directory_noreplace_leaves_the_staged_journal_promotable(
    tmp_path: Path,
) -> None:
    """A failed rename must leave nothing at the destination and the staged journal
    exactly where a retry will find it."""

    staging = tmp_path / "staging"
    final = tmp_path / "final"
    staging.mkdir()
    final.mkdir()
    (staging / "txn-1").mkdir()
    (staging / "txn-1" / "manifest.json").write_bytes(b"{}\n")

    def refuse_rename(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    src_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    dst_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with (
            mock.patch.object(cp, "_renameat2_primitive", side_effect=_unsupported_flag_mount()),
            mock.patch.object(os, "rename", refuse_rename),
        ):
            with pytest.raises(OSError) as raised:
                cp._renameat2(src_fd, "txn-1", dst_fd, "txn-1", cp._RENAME_NOREPLACE)
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert raised.value.errno == errno.EIO
    assert list(final.iterdir()) == []
    assert (staging / "txn-1" / "manifest.json").read_bytes() == b"{}\n"


def _errno_plain_rename_gives(root: Path, occupy: Callable[[Path], object]) -> int:
    """What a plain `rename(2)` of a directory onto this occupant answers, HERE.

    rename(2) documents "EEXIST or ENOTEMPTY" for a non-empty destination directory and
    leaves the choice to the filesystem — measured 2026-09-14: ENOTEMPTY on tmpfs and on
    the nfs4 export the fallback exists for, EEXIST on the xfs that backs this worktree's
    tmp_path. Hardcoding either would pin the host, not the behaviour, so the expectation
    is taken from the same filesystem the test then exercises.
    """

    bench = root / f"errno-probe-{uuid.uuid4().hex[:8]}"
    bench.mkdir()
    source = bench / "src"
    source.mkdir()
    destination = bench / "dst"
    occupy(destination)
    try:
        os.rename(source, destination)
    except OSError as refusal:
        return int(refusal.errno or 0)
    raise AssertionError(f"rename onto {destination} succeeded; this occupant does not refuse")


@pytest.mark.parametrize(
    ("occupy", "label"),
    [
        (
            lambda path: [path.mkdir(), (path / "manifest.json").write_bytes(b'{"final": true}\n')],
            "a populated journal",
        ),
        (lambda path: path.write_bytes(b'{"final": true}\n'), "a regular file"),
    ],
    ids=["populated-journal", "regular-file"],
)
def test_rebuilt_directory_noreplace_cannot_lose_a_journal_it_did_not_see(
    tmp_path: Path,
    occupy: Callable[[Path], object],
    label: str,
) -> None:
    """The residual window between the check and the rename, stated as a property.

    This is the ONLY interleaving in which `rename`'s own refusals are load-bearing: when
    the destination is occupied before the call, the leg's lstat guard answers EEXIST and
    the rename never runs. Here the destination is empty at check time and the occupant
    lands afterwards, so the refusal can only come from `rename(2)` — and the errno is
    asserted against what a plain rename answers on this same filesystem, not against a set.

    An earlier version accepted any OSError. That is the pattern that let a sibling test
    claim to have measured ENOTEMPTY and ENOTDIR while only ever reaching the guard, so the
    mechanism is pinned here explicitly: `reached_rename` fails if the guard answers instead.
    """

    staging = tmp_path / "staging"
    final = tmp_path / "final"
    staging.mkdir()
    final.mkdir()
    (staging / "txn-1").mkdir()
    (staging / "txn-1" / "manifest.json").write_bytes(b'{"staged": true}\n')
    expected_errno = _errno_plain_rename_gives(tmp_path, occupy)
    real_rename = os.rename
    reached_rename = False

    def race_then_rename(*args: object, **kwargs: object) -> None:
        nonlocal reached_rename
        reached_rename = True
        occupy(final / "txn-1")
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    src_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    dst_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with (
            mock.patch.object(cp, "_renameat2_primitive", side_effect=_unsupported_flag_mount()),
            mock.patch.object(os, "rename", race_then_rename),
        ):
            with pytest.raises(OSError) as raised:
                cp._renameat2(src_fd, "txn-1", dst_fd, "txn-1", cp._RENAME_NOREPLACE)
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert reached_rename, f"{label}: the guard answered, so this never reached the window"
    assert raised.value.errno == expected_errno, (label, raised.value.errno, expected_errno)
    assert (staging / "txn-1" / "manifest.json").read_bytes() == b'{"staged": true}\n'
    arrived = final / "txn-1"
    if arrived.is_dir():
        assert (arrived / "manifest.json").read_bytes() == b'{"final": true}\n'
    else:
        assert arrived.read_bytes() == b'{"final": true}\n'


def test_supported_mount_never_reaches_the_fallback(tmp_path: Path) -> None:
    """Zero behaviour change where the flags work, which is every local filesystem
    the estate runs on."""

    directory = tmp_path / "dir"
    directory.mkdir()
    (directory / "src").write_bytes(b"replacement\n")
    (directory / "dst").write_bytes(b"displaced\n")
    rebuilt = False

    def record(*_args: object) -> None:
        nonlocal rebuilt
        rebuilt = True

    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with mock.patch.dict(
            cp._RENAME_FLAG_FALLBACKS,
            {cp._RENAME_EXCHANGE: record, cp._RENAME_NOREPLACE: record},
        ):
            cp._renameat2(dir_fd, "src", dir_fd, "dst", cp._RENAME_EXCHANGE)
    finally:
        os.close(dir_fd)

    assert not rebuilt
    assert (directory / "dst").read_bytes() == b"replacement\n"
    assert (directory / "src").read_bytes() == b"displaced\n"


def test_create_leg_types_its_install_failure_instead_of_leaking_an_oserror(
    tmp_path: Path,
) -> None:
    """The create leg had no typed predicate for anything but EEXIST.

    On the unsupporting mount that hole swallowed the defect itself, surfacing as
    `transaction_entry_unknown` rather than as a projection refusal. The fallback
    answers EINVAL now, so the hole is pinned with an errno it does not claim.
    """

    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    projection = cp.FileProjection.capture(note, after=b"created by transition\n")
    real_primitive = cp._renameat2_primitive

    def out_of_space(
        src_dir_fd: int,
        src_name: str,
        dst_dir_fd: int,
        dst_name: str,
        flags: int,
    ) -> int:
        if flags == cp._RENAME_NOREPLACE and dst_name == note.name:
            return errno.ENOSPC
        return real_primitive(src_dir_fd, src_name, dst_dir_fd, dst_name, flags)

    with mock.patch.object(cp, "_renameat2_primitive", side_effect=out_of_space):
        with pytest.raises(cp.LifecycleTransitionError) as raised:
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=_intent(),
                projections=[projection],
                transaction_root=tmp_path / "transactions",
                lock_root=tmp_path / "locks",
            )

    assert raised.value.reason_code == "transition_projection_install_failed"
    assert not note.exists()


def test_displace_leg_predicate_names_the_flag_it_actually_uses(tmp_path: Path) -> None:
    """`exchange_failed` on a NOREPLACE leg cost a real diagnosis: one predicate
    covered two flags, so a journal could not say which syscall had failed."""

    log = _log(tmp_path)
    note = tmp_path / "vault" / "task-1.md"
    note.parent.mkdir()
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=None)
    real_primitive = cp._renameat2_primitive

    def refuse_displace(
        src_dir_fd: int,
        src_name: str,
        dst_dir_fd: int,
        dst_name: str,
        flags: int,
    ) -> int:
        if flags == cp._RENAME_NOREPLACE and src_name == note.name:
            return errno.ENOSPC
        return real_primitive(src_dir_fd, src_name, dst_dir_fd, dst_name, flags)

    with mock.patch.object(cp, "_renameat2_primitive", side_effect=refuse_displace):
        with pytest.raises(cp.LifecycleTransitionError) as raised:
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=_intent(),
                projections=[projection],
                transaction_root=tmp_path / "transactions",
                lock_root=tmp_path / "locks",
            )

    assert raised.value.reason_code == "transition_projection_displace_failed"
    assert note.read_bytes() == b"stage: S6\n"


def test_rebuilt_file_noreplace_refuses_an_occupied_destination(tmp_path: Path) -> None:
    """The NOREPLACE property, asserted on the rebuilt leg itself.

    ``test_rebuilt_noreplace_still_refuses_a_racing_create`` drives the whole
    transition and **passes even when this leg is replaced by a plain rename**
    (measured; a coverage probe confirms it does reach this leg, so it is exercised
    and still does not discriminate — it is satisfied by something downstream, not
    by the refusal it is named for). A property that survives its own destruction is
    not pinned, so this asserts it where it lives, at the leg, where nothing else
    can satisfy it.

    A plain rename here would silently destroy the occupant, which is the precise
    fail-open ``RENAME_NOREPLACE`` exists to prevent.
    """

    (tmp_path / "src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"occupant\n")
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(OSError) as caught:
            cp._fallback_noreplace(dir_fd, "src", dir_fd, "dst")
        assert caught.value.errno == errno.EEXIST

        # Neither side moved: the occupant is intact and the source is still there
        # for the caller's retry. Nothing was decided quietly.
        assert (tmp_path / "dst").read_bytes() == b"occupant\n"
        assert (tmp_path / "src").read_bytes() == b"replacement\n"

        # And the refusal is not an accident of the destination existing: onto a
        # free name the same leg installs and consumes the source.
        cp._fallback_noreplace(dir_fd, "src", dir_fd, "free")
        assert (tmp_path / "free").read_bytes() == b"replacement\n"
        assert not (tmp_path / "src").exists()
    finally:
        os.close(dir_fd)


def test_renameat2_never_rebuilds_a_real_fault(tmp_path: Path) -> None:
    """The errno boundary is the fallback's safety precondition — pin it directly.

    ``_RENAME_FLAG_UNSUPPORTED_ERRNOS`` is what separates "this mount does not
    implement the flag" from "the write failed". Widening it by one entry — adding
    ``EIO`` — left the whole suite green (measured), so the boundary was asserted
    nowhere. That is the fallback-discipline hazard in its exact form: on a genuine
    I/O fault the code would stop failing and start **attempting the write again by
    another route**, which is the one thing a failure path must never do.

    Driven at the wrapper with the fallbacks replaced by recorders, so the assertion
    is about the dispatch decision and cannot be satisfied by a fallback that
    happens to work on the filesystem the tests run on.
    """

    (tmp_path / "src").write_bytes(b"src\n")
    (tmp_path / "dst").write_bytes(b"dst\n")
    entered: list[tuple[object, ...]] = []

    def recorder(*args: object) -> None:
        entered.append(args)

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            mock.patch.object(cp, "_renameat2_primitive", return_value=errno.EIO),
            mock.patch.dict(
                cp._RENAME_FLAG_FALLBACKS,
                {cp._RENAME_EXCHANGE: recorder, cp._RENAME_NOREPLACE: recorder},
            ),
        ):
            for flags in (cp._RENAME_EXCHANGE, cp._RENAME_NOREPLACE):
                with pytest.raises(OSError) as caught:
                    cp._renameat2(dir_fd, "src", dir_fd, "dst", flags)
                assert caught.value.errno == errno.EIO
    finally:
        os.close(dir_fd)

    assert entered == []
    assert (tmp_path / "src").read_bytes() == b"src\n"
    assert (tmp_path / "dst").read_bytes() == b"dst\n"


#: Enumerated HERE, independently of the production set, because a test parameterized from
#: `_RENAME_FLAG_UNSUPPORTED_ERRNOS` loses a case exactly when someone deletes the behaviour
#: the case protects — the mutation and its own oracle vanish together. A reviewer caught
#: that in the first version of this test. These are the errnos a mount uses to say "this
#: flag does not exist here", and the fallback must run for every one of them.
_MUST_DISPATCH_THE_REBUILD = (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP)


def test_the_declared_unsupported_set_matches_the_errnos_this_suite_requires() -> None:
    """The independent enumeration and the production set must agree, in both directions.

    Missing member: a mount answering that errno would get a real failure instead of the
    fallback, and the SSOT stays broken. Extra member: an errno that means something else
    would start being retried by another route, which is the fallback-discipline hazard.
    """

    assert set(_MUST_DISPATCH_THE_REBUILD) == set(cp._RENAME_FLAG_UNSUPPORTED_ERRNOS), (
        sorted(errno.errorcode.get(e, e) for e in _MUST_DISPATCH_THE_REBUILD),
        sorted(errno.errorcode.get(e, e) for e in cp._RENAME_FLAG_UNSUPPORTED_ERRNOS),
    )


@pytest.mark.parametrize("unsupported", _MUST_DISPATCH_THE_REBUILD, ids=errno.errorcode.get)
def test_every_unsupported_errno_dispatches_a_rebuild_that_really_runs(
    tmp_path: Path, unsupported: int
) -> None:
    """Each errno, through the wrapper, asserted on the FILESYSTEM post-state.

    The mount simulations all inject EINVAL, which is what this export answers; ENOSYS,
    ENOTSUP and EOPNOTSUPP were declared for mounts that answer differently and nothing
    exercised them. An earlier version of this test replaced both rebuilds with callbacks and
    asserted only that a callback ran — which cannot tell a rebuild that works from one that
    corrupts. The real legs run here and the entries are checked afterwards.
    """

    directory = tmp_path / errno.errorcode.get(unsupported, str(unsupported))
    directory.mkdir()
    (directory / "src").write_bytes(b"replacement\n")
    (directory / "dst").write_bytes(b"displaced\n")

    dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(
            cp,
            "_renameat2_primitive",
            side_effect=_unsupported_flag_mount(unsupported_errno=unsupported),
        ):
            cp._renameat2(dir_fd, "src", dir_fd, "dst", cp._RENAME_EXCHANGE)
            # EXCHANGE swapped them, so the NOREPLACE below promotes onto a free name.
            assert (directory / "dst").read_bytes() == b"replacement\n"
            assert (directory / "src").read_bytes() == b"displaced\n"
            cp._renameat2(dir_fd, "src", dir_fd, "free", cp._RENAME_NOREPLACE)
    finally:
        os.close(dir_fd)

    assert (directory / "free").read_bytes() == b"displaced\n"
    assert not (directory / "src").exists()
    assert not _fallback_remnants(directory), sorted(p.name for p in directory.iterdir())


@pytest.mark.parametrize("flags", [0, cp._RENAME_EXCHANGE | cp._RENAME_NOREPLACE, 1 << 20])
def test_flags_without_a_rebuild_are_never_retried_by_another_route(
    tmp_path: Path, flags: int
) -> None:
    """`flags == 0` and any flag this module does not use must reach no fallback.

    A plain rename that failed has failed and there is nothing to rebuild; an unknown flag
    must not silently acquire a rebuild designed for a different one. Both are decided by
    `_RENAME_FLAG_FALLBACKS.get(flags) is None`, and neither had a direct test — so the
    dispatch could start covering them without anything going red.
    """

    (tmp_path / "src").write_bytes(b"src\n")
    (tmp_path / "dst").write_bytes(b"dst\n")
    entered: list[object] = []

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            # EINVAL: a declared-unsupported errno, so ONLY the missing rebuild can be
            # what stops the dispatch here.
            mock.patch.object(cp, "_renameat2_primitive", return_value=errno.EINVAL),
            mock.patch.dict(
                cp._RENAME_FLAG_FALLBACKS,
                {
                    cp._RENAME_EXCHANGE: lambda *a: entered.append(a),
                    cp._RENAME_NOREPLACE: lambda *a: entered.append(a),
                },
            ),
        ):
            with pytest.raises(OSError) as caught:
                cp._renameat2(dir_fd, "src", dir_fd, "dst", flags)
        assert caught.value.errno == errno.EINVAL
    finally:
        os.close(dir_fd)

    assert entered == [], f"flags={flags:#x} reached a rebuild that was not written for it"
    assert (tmp_path / "src").read_bytes() == b"src\n"
    assert (tmp_path / "dst").read_bytes() == b"dst\n"


# --- race detection in the rebuilt legs (review criticals C1 and C2) -----------
#
# `link`-then-mutate is not atomic, so a writer that atomically replaces the entry a
# leg is about to destroy would lose its bytes — and because the rebuild reproduces the
# syscall's post-state exactly, the displaced name holds the pinned preimage, the
# caller's readback passes, and the transaction records `applied` over the loss. The
# native flags never had that hole: they acted against whatever occupied the name at the
# instant of the call. Atomicity was supplying race DETECTION, and the callers were
# built on it.
#
# These pin the detection, and the last one pins the residual window that detection
# cannot close. See NFS-EXCHANGE-FALLBACK-DESIGN-20260911.md §8.


def _fallback_remnants(directory: Path) -> list[str]:
    """Scratches and adornments left by a rebuilt rename leg, and only those.

    Deliberately narrower than `*.transition-*`, which also matches the transaction's own
    `.transition-scratch` that several tests legitimately leave behind. The assertions this
    replaces globbed `*.transition-pin.*` — a trailing-dot pattern that the switch to
    deterministic names made unmatchable, so six "no residue" assertions silently became
    no-ops. A reviewer caught that.

    Round 32 widened the residue class: the retirement dance and the rename-based release
    hang `_RETIREMENT_ADORNMENTS` suffixes off names the legs already computed
    (`.transition-safety`, `.transition-withdrawn`, …), so matching the role suffixes alone
    would repeat the silent no-op this helper's own history warns about — a test leaving a
    `.transition-safety` remnant would pass a "no residue" assertion. Both suffix sets are
    matched now; stacked adornments (`…staged.transition-safety`) still end in one, so a
    single `endswith` covers them.
    """

    suffixes = tuple(f".transition-{role}" for role in cp._FALLBACK_SCRATCH_ROLES)
    suffixes += cp._RETIREMENT_ADORNMENTS
    return sorted(path.name for path in directory.iterdir() if path.name.endswith(suffixes))


def _computable_fallback_names(*bases: str) -> set[str]:
    """Every fallback name computable from the operands — roles AND stacked adornments.

    The residue contract is not "dotted" but *computable*: an operator — or the discovery
    sweep the projection-lock task owes — must be able to enumerate every remnant from the
    operands alone. That set is not just `_fallback_scratch_name(base, role)`: the
    round-32 conversions reserve bare adorned names off the operand stem
    (`.src.transition-consumed`), stack a second adornment during the dance
    (`.src.transition-staged.transition-safety`), and the refill stacks TWO off a role
    name (`.src.transition-holding.transition-staged.transition-safety`). Depth is bounded
    by two adornments by construction — no leg adorns an adorned name twice — so a remnant
    deeper than that is a bug this closure exists to surface.
    """

    names = {base if base.startswith(".") else f".{base}" for base in bases}
    for base in list(names):
        for role in cp._FALLBACK_SCRATCH_ROLES:
            names.add(f"{base}.transition-{role}")
    for _ in range(2):
        names |= {f"{name}{suffix}" for name in names for suffix in cp._RETIREMENT_ADORNMENTS}
    return names


def _replace_atomically(directory: Path, name: str, payload: bytes) -> None:
    """What a racing writer does: a new inode at the name, atomically."""
    scratch = directory / f".racer-{os.urandom(4).hex()}"
    scratch.write_bytes(payload)
    os.rename(scratch, directory / name)


# --- unlink-site census (claude-1 round-32: residual completeness, recheckable) ---

_UNLINK_SITE_CENSUS: dict[str, int] = {
    # Every os.unlink call site in shared/coord_projection.py, by enclosing function.
    # This is the module's destroy surface: adding an entry is a review event, not a
    # mechanical update — each one must justify why its removal cannot take a foreign
    # writer's only copy, and the disclosed conditional (_retire_scratch) carries its
    # residual assignment to the projection-lock row.
    "_relocate_to_scratch": 1,
    "_move_aside_atomically": 1,
    "_retire_scratch": 1,
    "_unlink_exact_entry": 1,
}


def test_every_unlink_site_is_census_pinned() -> None:
    """The residual list's completeness must be recheckable, not re-asserted.

    claude-1 round-32: the review could not verify that the disclosed unlink-site
    list was complete — completeness lived in prose. This enumerates the module's
    os.unlink call sites with `ast` against the documented census above, so an added
    removal site fails here until it is consciously entered with its justification,
    and a removed site fails until the census shrinks. Drift goes red.
    """

    counts: dict[str, int] = {}
    stack: list[str] = []

    class _Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr == "unlink"
                and isinstance(function.value, ast.Name)
                and function.value.id == "os"
            ):
                owner = stack[-1] if stack else "<module>"
                counts[owner] = counts.get(owner, 0) + 1
            self.generic_visit(node)

    _Visitor().visit(ast.parse(Path(cp.__file__).read_text(encoding="utf-8")))
    assert counts == _UNLINK_SITE_CENSUS


def _race_after_link(
    directory: Path,
    name: str,
    payload: bytes,
    *,
    only_linking: str | None = None,
) -> mock._patch[object]:
    """Land a racing replacement in the window a leg's identity check covers.

    The replacement is injected immediately after the pin/link is taken, which is inside
    the span between taking the reference and destroying the original — the part the
    check can see.

    `only_linking` restricts the injection to the link whose *source* is that name. A
    transaction links several times (journal blobs before the projection), and firing on
    the first of them lands the racer before `_cas_project`'s own precondition check,
    which then refuses with `transition_precondition_changed` — a correct refusal, but by
    the pre-existing check rather than by the new one. Measured, and it is why this
    parameter exists: without it a transaction-level test passes for the wrong reason.
    """

    real_link = os.link
    state = {"fired": False}

    def racing_link(*args: object, **kwargs: object) -> None:
        result = real_link(*args, **kwargs)  # type: ignore[arg-type]
        targeted = only_linking is None or (args and str(args[0]) == only_linking)
        if targeted and not state["fired"]:
            state["fired"] = True
            _replace_atomically(directory, name, payload)
        return result

    return mock.patch.object(os, "link", racing_link)


def test_exchange_fallback_refuses_a_replacement_racing_after_the_pin(
    tmp_path: Path,
) -> None:
    """C1: the racer's bytes must survive and the leg must refuse, not silently install."""

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with _race_after_link(tmp_path, "dst", b"racing-writer\n"):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
        assert caught.value.reason_code == "transition_precondition_changed"
    finally:
        os.close(dir_fd)

    # Nothing of the racer's was destroyed, and nothing of ours was installed.
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"racing-writer\n" in surviving
    assert b"replacement\n" in surviving
    assert b"displaced\n" in surviving
    assert (tmp_path / ".src").read_bytes() == b"replacement\n"
    # The scratches are deliberately LEFT: after the leg has moved dst aside, a scratch can
    # be the sole name of a live entry, so the failure path unlinks nothing at all. This
    # assertion used to require no residue, which was the wrong contract — tidying up here
    # is what would have destroyed the raced preimage.
    assert _fallback_remnants(tmp_path)
    # The refusal names the scratch the other writer's bytes are now at — the one an operator
    # must not delete. Requiring it to enumerate EVERY remnant was a test about message
    # formatting rather than about preservation, and it broke on a message that is more
    # precise, not less.
    assert cp._fallback_scratch_name(".src", "holding") in str(caught.value)
    assert "recover-claim-publications" in caught.value.repair_action


def test_noreplace_publishes_then_refuses_a_replacement_racing_the_source(
    tmp_path: Path,
) -> None:
    """The ACCEPTED publish-then-refuse window, REFUSE-ONLY since round-30 closed C1.

    On the delete leg `src` is the live projection, so a writer that replaces it after
    the caller's check is carried to `dst` by the publish rename — a rename relocates
    whatever occupies the source, and no reservation on `src` can prevent that. So the
    leg publishes, verifies WHAT landed, and refuses. The refusal no longer restores
    the carried entry to `src`: the restoration it replaces was two conditional acts —
    link the racer back, then an identity-checked unlink of our publication — with a
    destroy window between them, which is what the round-30 review closed as C1. The
    racer's bytes stay preserved AT `dst` and `src` stays vacant: a crash-consistent
    intermediate for recovery, the same shape move-or-fail produces elsewhere. Nothing
    the leg does destroys anything: the preimage this transition intended to move was
    replaced by the racer before the leg's first mutation (the ACCEPTED entry of the
    residual list; coordinator ruling 2026-09-15T02:36Z, refined refuse-only the same
    day).
    """

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    real_rename = os.rename
    fired = False

    def racing_rename(*args: object, **kwargs: object) -> None:
        # Strictly before the publish rename, so the rename itself carries the racer
        # across. `_replace_atomically` renames too, so the flag keeps this from
        # recursing into the racer's own move.
        nonlocal fired
        if not fired and args and str(args[0]) == "task.md" and str(args[1]) == ".task.md.scratch":
            fired = True
            _replace_atomically(tmp_path, "task.md", b"racing-writer\n")
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", racing_rename):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_noreplace(dir_fd, "task.md", dir_fd, ".task.md.scratch")
        assert caught.value.reason_code == "transition_precondition_changed"
    finally:
        os.close(dir_fd)

    assert fired
    # The racer's bytes stay exactly where the publish rename carried them — AT the
    # destination, their only name — and the live source name stays vacant: the
    # crash-consistent intermediate the refusal hands to recovery. No dotted remnant
    # exists, because this leg never minted one.
    assert (tmp_path / ".task.md.scratch").read_bytes() == b"racing-writer\n"
    assert os.stat(tmp_path / ".task.md.scratch").st_nlink == 1
    assert not (tmp_path / "task.md").exists()
    assert _fallback_remnants(tmp_path) == []
    # The refusal names both states — preserved AT the destination, source vacant —
    # and the next command.
    assert "preserved there" in str(caught.value)
    assert "recover-claim-publications" in caught.value.repair_action


def test_race_detection_refuses_the_whole_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The detection has to reach the caller, which is where the fail-open lived.

    A leg that refuses is only useful if the transaction then declines to record
    `applied`. The bug was never the rename by itself — it was that the post-state
    satisfied `_cas_project`'s readback, so the transaction accepted a loss.
    """

    log = _log(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "task-1.md"
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=b"stage: S7\n")
    monkeypatch.setattr(cp, "_renameat2_primitive", _unsupported_flag_mount())

    with _race_after_link(vault, note.name, b"racing-writer\n", only_linking=note.name):
        with pytest.raises(cp.LifecycleTransitionError) as raised:
            cp.execute_lifecycle_transition(
                event_log=log,
                intent=_intent(),
                projections=[projection],
                transaction_root=tmp_path / "transactions",
                lock_root=tmp_path / "locks",
                timestamp="2026-07-11T15:00:00Z",
            )

    # Two refusals are correct here and the code picks the stricter one. The leg raises
    # EBUSY, which the update site maps to `transition_projection_exchange_failed`; the
    # transaction then cannot cleanly roll back over a file a third party is holding and
    # escalates to `transition_projection_recovery_required` — preserve both, reconcile by
    # hand. Asserted as a set rather than as one string, because the property under test is
    # "refused and nothing lost", and pinning my first guess would have made this test a
    # statement about my prediction instead. (Measured: it is the recovery escalation.)
    assert raised.value.reason_code in {
        "transition_projection_exchange_failed",
        "transition_projection_recovery_required",
    }
    # What actually matters: nothing recorded applied, and no bytes were destroyed.
    event_types = [event.event_type for event in log.replay().events]
    assert cp.CANON_TRANSITION_APPLIED not in event_types
    assert event_types[0] == cp.CANON_TRANSITION_PREPARED

    # A consequence of move-or-fail worth asserting rather than glossing: when the race is
    # caught at step 3, `dst` has already been MOVED aside and the publish never happened,
    # so the live name is left VACANT with both generations under computable scratch names.
    # That is a crash-consistent intermediate for recovery to reconcile — no loss — but it
    # is a real behaviour change from the previous shape, where the live name always held
    # something. Stated here so it cannot be discovered later as a surprise.
    assert not note.exists()
    surviving = {path.read_bytes() for path in vault.iterdir() if path.is_file()}
    assert b"racing-writer\n" in surviving, "the racing writer's bytes must survive"
    assert b"stage: S6\n" in surviving, "the displaced preimage must survive"
    # The remnant holding those bytes is a fallback scratch, and it is derived from the
    # TRANSACTION's scratch operand rather than from the note name — which is the whole point
    # of the round-6 fix, since deriving it from the live name let successive transactions
    # collide on it. The test cannot recompute the name without the transaction id, so it
    # asserts the class instead.
    remnants = _fallback_remnants(vault)
    assert remnants, "the preserved bytes must be under a computable fallback scratch"
    assert all(name.startswith(".") for name in remnants), remnants


def test_scratch_names_are_dotted_and_deterministic(tmp_path: Path) -> None:
    """Two properties, and the second is the one that matters for recovery.

    **Dotted** for any operand: the name used to inherit its dot from `src_name`, and
    `_atomic_install`'s rollback passes ordinary journal filenames, so real pins landed as
    `manifest.json.transition-pin.<hex>`. Every crash test supplied `.src`, which is why
    nothing saw it.

    **Deterministic**: the name used to carry `os.urandom(8).hex()`, which made every
    remnant unfindable — recovery addresses the exact computed `scratch.path.name`, and a
    random name is neither recorded nor recomputable. Derived from the operand, a remnant
    is computable by anything that can recompute the operand. That is not the same as
    recovery *discovering* it — nothing in this module sweeps a directory — and the
    difference is stated in `_fallback_scratch_name` rather than implied away.
    """

    for operand in ("manifest.json", ".src", "0001.after", "task-1.md"):
        for role in cp._FALLBACK_SCRATCH_ROLES:
            name = cp._fallback_scratch_name(operand, role)
            assert name.startswith("."), (operand, role, name)
            assert name.endswith(f".transition-{role}"), name
            # Same input, same name — every call, not just within one process.
            assert name == cp._fallback_scratch_name(operand, role)
        # The roles never collide with each other — asserted against the declared set, so
        # adding a role cannot silently start colliding with an existing one.
        assert len(
            {cp._fallback_scratch_name(operand, r) for r in cp._FALLBACK_SCRATCH_ROLES}
        ) == len(cp._FALLBACK_SCRATCH_ROLES)

    # And the names the leg actually creates are the computable ones, for a non-dotted
    # operand — which is the case that used to produce a visible, unfindable pin.
    (tmp_path / "manifest.json").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    created: list[str] = []
    real_link, real_rename = os.link, os.rename

    def recording_link(src: object, dst: object, **kwargs: object) -> None:
        created.append(str(dst))
        return real_link(src, dst, **kwargs)  # type: ignore[arg-type]

    def recording_rename(src: object, dst: object, **kwargs: object) -> None:
        created.append(str(dst))
        return real_rename(src, dst, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            mock.patch.object(os, "link", recording_link),
            mock.patch.object(os, "rename", recording_rename),
        ):
            cp._fallback_exchange(dir_fd, "manifest.json", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    scratch_names = {name for name in created if ".transition-" in name}
    assert scratch_names, created
    assert all(name.startswith(".") for name in scratch_names), scratch_names
    # Every scratch the leg touched is one an operator can recompute from the operands —
    # roles AND the round-32 adornments (staged/safety/…), because the leg now creates
    # both classes and both are crash-reachable remnants.
    computable = _computable_fallback_names("manifest.json", "dst")
    assert scratch_names <= computable, scratch_names - computable


def test_a_prior_attempts_remnant_refuses_instead_of_being_renamed_around(
    tmp_path: Path,
) -> None:
    """Deterministic names turn a collision into information, so it is a refusal.

    The old random-name scheme retried under a fresh name on EEXIST, which had to be a
    guess about the cause. With the name derived from the operand, a collision can only
    mean a previous attempt's remnant is still on disk — the same condition
    `_write_scratch` already reads as `transition_projection_scratch_exists`, and the same
    remedy: recover or quarantine it. Renaming around it would abandon the remnant and
    lose whatever it was holding.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    remnant = tmp_path / cp._fallback_scratch_name(".src", "pin")
    remnant.write_bytes(b"a previous attempt left this\n")

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(cp.LifecycleTransitionError) as raised:
            cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert raised.value.reason_code == "transition_projection_scratch_exists"
    # Refused before touching either live entry, and the remnant is untouched.
    assert (tmp_path / "dst").read_bytes() == b"displaced\n"
    assert (tmp_path / ".src").read_bytes() == b"replacement\n"
    assert remnant.read_bytes() == b"a previous attempt left this\n"


def test_exchange_preserves_a_replacement_arriving_at_the_install_itself(
    tmp_path: Path,
) -> None:
    """The window that used to be the documented limit, now closed.

    This replaces `test_the_residual_race_window_is_open_and_this_is_the_documented_limit`,
    which asserted the loss and said in its own docstring that a failure there was good
    news and it should be deleted with the design caveat. Three reviewer families made that
    due. The racer is injected at the same cut — the destructive step itself, past every
    check — and the leg now relocates rather than replaces, so there is nothing left to
    lose at any interleaving.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    real_rename = os.rename
    fired = False

    def racing_rename(*args: object, **kwargs: object) -> None:
        # The old residual gap: strictly after the identity check.
        nonlocal fired
        if not fired:
            fired = True
            _replace_atomically(tmp_path, "dst", b"racing-writer\n")
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", racing_rename):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
        assert caught.value.reason_code == "transition_precondition_changed"
    finally:
        os.close(dir_fd)

    assert fired
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    # All three generations survive: the racer's, ours, and the entry being displaced.
    assert b"racing-writer\n" in surviving
    assert b"replacement\n" in surviving
    assert b"displaced\n" in surviving


def test_a_foreign_rename_onto_our_reserved_placeholder_is_refused_and_preserved_r4(
    tmp_path: Path,
) -> None:
    """Residual R4 — CLOSED by the round-32 consume-then-refuse publish.

    The exchange's publish reserves the LIVE destination, and a foreign `rename` onto
    that reservation is not excluded by `O_CREAT|O_EXCL`. Under the reserve-then-rename
    shape the consuming rename destroyed that arrival while the post-rename identity
    check passed — the one silent loss, pinned here for two rounds as a boundary. The
    link publish closes it by construction: the reservation is consumed EARLY, withdrawn
    by rename to a dotted `{src}.transition-consumed` name — a rename carries whatever
    occupies the name, so the arrival is preserved THERE — and the identity check at the
    withdrawn name then refuses with both entries intact and the live destination freed.
    The window that remains elsewhere is the NOREPLACE inline leg, whose reserved
    destination is dotted by caller census (R2-class); this leg has no live-name window
    left, and the projection-lock row
    (`projection-lock-coverage-projected-path-writers-20260913`) remains the closure for
    the rogue-on-dotted class, not for this one.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    pin = cp._fallback_scratch_name(".src", "pin")
    holding = cp._fallback_scratch_name(".src", "holding")
    consumed = ".src.transition-consumed"
    real_rename = os.rename
    fired = False

    def foreign_arrival_under_the_withdraw(*args: object, **kwargs: object) -> None:
        # The R4 window under the closed shape: our placeholder holds `dst`, the consuming
        # withdraw rename has not run. A protocol-ignoring writer atomically replaces the
        # name — over the placeholder — and the real rename then carries THAT arrival
        # across to the consumed name instead of destroying it. The selector pins the
        # destination operand too: the displaced-entry relocation one step earlier also
        # renames FROM `dst`, and firing there is the arrival-at-holding refusal pinned
        # separately above — not this one.
        nonlocal fired
        if not fired and args and str(args[0]) == "dst" and str(args[1]) == consumed:
            fired = True
            _replace_atomically(tmp_path, "dst", b"late-arrival\n")
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", foreign_arrival_under_the_withdraw):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
        assert caught.value.reason_code == "transition_precondition_changed"
    finally:
        os.close(dir_fd)

    assert fired
    # The arrival is PRESERVED at the consumed name — refused, not destroyed — and the
    # live destination is freed with both operands untouched by the refusal.
    assert (tmp_path / consumed).read_bytes() == b"late-arrival\n"
    assert os.stat(tmp_path / consumed).st_nlink == 1
    assert not (tmp_path / "dst").exists()
    assert (tmp_path / ".src").read_bytes() == b"replacement\n"
    # The displaced entry is preserved at both of its scratch names by the failing path,
    # which unlinks nothing — and the refusal names all three preserved locations.
    assert (tmp_path / pin).read_bytes() == b"displaced\n"
    assert (tmp_path / holding).read_bytes() == b"displaced\n"
    assert "preserved" in str(caught.value)
    assert "recover-claim-publications" in caught.value.repair_action
    assert set(_fallback_remnants(tmp_path)) == {pin, holding, consumed}


def test_delete_leg_preserves_a_replacement_arriving_after_the_check(
    tmp_path: Path,
) -> None:
    """The arrival at the PUBLISHED name, which the refusal must not destroy.

    This is the sibling of the exchange test above at the window that remains open here:
    nothing retires the source by checking it into a scratch any more, so the uncovered
    gap is a writer landing on `dst` between the publish and the verification. The
    mismatch branch refuses WITHOUT undoing anything: since round-30 closed C1 there is
    no link-back restoration and no identity-checked unlink of our publication — the
    racer's entry stays exactly where it landed, at `dst`, its only name, and `src`
    stays vacant. What the leg already did (the publish rename carrying our preimage
    across, then the racer's own atomic replace over it) destroyed nothing the racer
    did not destroy itself.
    """

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    real_fsync = os.fsync
    fired = False

    def replacing_fsync(fd: int) -> None:
        # After the publish barrier, before the verification read: the racer replaces
        # the entry that just landed at the destination.
        nonlocal fired
        real_fsync(fd)
        if not fired:
            fired = True
            _replace_atomically(tmp_path, ".task.md.scratch", b"racing-writer\n")

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "fsync", replacing_fsync):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_noreplace(dir_fd, "task.md", dir_fd, ".task.md.scratch")
        assert caught.value.reason_code == "transition_precondition_changed"
    finally:
        os.close(dir_fd)

    assert fired
    # The other writer's bytes live, at the destination their own atomic replace put
    # them, as their only name; the live source name stays vacant for recovery to
    # reconcile against it. The leg's second act — the one the restoration used to
    # perform — no longer exists, so there is nothing left to get wrong.
    assert (tmp_path / ".task.md.scratch").read_bytes() == b"racing-writer\n"
    assert os.stat(tmp_path / ".task.md.scratch").st_nlink == 1
    assert not (tmp_path / "task.md").exists()
    assert _fallback_remnants(tmp_path) == []
    # The refusal names what was carried where, and the next command.
    assert "preserved there" in str(caught.value)
    assert "recover-claim-publications" in caught.value.repair_action


def test_a_scratch_install_refuses_a_foreign_arrival_on_the_live_name(
    tmp_path: Path,
) -> None:
    """C2: a scratch → live install must refuse an occupied live name, not eat it.

    Staged transaction material is installed at live names from `.transition-scratch`
    / `.transition-tmp` sources. Under the reserve-then-rename shape this leg once
    shared with live sources, a foreign writer that renamed onto the reserved
    placeholder was destroyed by the consuming rename while the post-rename identity
    check passed — the exact regression the round-30 review flagged (C2). The closure
    is the source's SHAPE: a scratch source does not need its name consumed, so the
    install is published by `link(2)` — create-or-EEXIST for EVERY occupant, whoever
    they are and however they got there. The EEXIST escapes bare, exactly as the raw
    EEXIST of the `link` publish this module once used did, and callers already
    discriminate on it (`_renameat2` re-raises the fallback's OSError unaltered).
    """

    staged = ".staged.transition-scratch"
    (tmp_path / staged).write_bytes(b"staged-bytes\n")
    real_link = os.link
    real_rename = os.rename
    fired = {"link": False, "rename": False}

    def landing_link(*args: object, **kwargs: object) -> None:
        if not fired["link"] and args and str(args[0]) == staged and str(args[1]) == "task.md":
            fired["link"] = True
            _replace_atomically(tmp_path, "task.md", b"foreigner\n")
        return real_link(*args, **kwargs)  # type: ignore[arg-type]

    def landing_rename(*args: object, **kwargs: object) -> None:
        if not fired["rename"] and args and str(args[0]) == staged and str(args[1]) == "task.md":
            fired["rename"] = True
            _replace_atomically(tmp_path, "task.md", b"foreigner\n")
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "link", landing_link):
            with mock.patch.object(os, "rename", landing_rename):
                with pytest.raises(FileExistsError):
                    cp._fallback_noreplace(dir_fd, staged, dir_fd, "task.md")
    finally:
        os.close(dir_fd)

    # The primitive that ran is the one this design chose: the link, not a rename.
    assert fired["link"]
    assert not fired["rename"]
    # The foreign entry stands at the live name, whole, as its only name — refused,
    # not consumed.
    assert (tmp_path / "task.md").read_bytes() == b"foreigner\n"
    assert os.stat(tmp_path / "task.md").st_nlink == 1
    # Our staged bytes survive at the scratch, untouched: the link never landed, so
    # nothing of ours moved at all.
    assert (tmp_path / staged).read_bytes() == b"staged-bytes\n"
    assert os.stat(tmp_path / staged).st_nlink == 1
    assert _fallback_remnants(tmp_path) == []


def test_a_foreign_replacement_of_the_published_live_name_keeps_our_staged_bytes(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The retire dance's accepted exposure: OUR bytes stranded, THEIRS intact.

    The retire that follows a link-publish is the round-32 dance — withdraw to a reserved
    `.transition-safety` name, remove only from there, only while another name still
    reaches the inode. The worst case on the live side: a foreign writer replaces the
    just-published live name after the withdrawal, so at the count the staged inode's
    remaining name is the SAFETY name alone. The old conditional unlink destroyed that
    last name (round-31 C1's replay); the dance instead PRESERVES the staged bytes at the
    safety name — recoverable under a name the journal can rebuild from — frees the
    scratch name so the operand does not wedge, and reports the strand. Accepted in the
    residual list (R2/R5): the staged bytes are ours and the journal rebuilds them,
    which is why this strand is acceptable where the displaced entry's loss was not.
    """

    staged = ".staged.transition-scratch"
    safety = f"{staged}.transition-safety"
    (tmp_path / staged).write_bytes(b"staged-bytes\n")

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with caplog.at_level("WARNING"):
            with _race_after_link(tmp_path, "task.md", b"foreigner\n", only_linking=staged):
                cp._fallback_noreplace(dir_fd, staged, dir_fd, "task.md")
    finally:
        os.close(dir_fd)

    # The foreign entry owns the live name, whole, as its only name.
    assert (tmp_path / "task.md").read_bytes() == b"foreigner\n"
    assert os.stat(tmp_path / "task.md").st_nlink == 1
    # Our staged bytes are PRESERVED at the safety name — the dance withdrew them there
    # before the count found them stranded — and the scratch name itself is FREE, so the
    # operand does not wedge behind a refusal.
    assert not (tmp_path / staged).exists()
    assert (tmp_path / safety).read_bytes() == b"staged-bytes\n"
    assert os.stat(tmp_path / safety).st_nlink == 1
    # The retire reported the strand rather than failing the leg or destroying
    # either entry.
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert "PRESERVED" in caplog.text
    assert "only remaining name" in caplog.text


def test_a_displaced_entry_stranded_by_a_live_sibling_replacement_survives_c1(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """C1, replayed end to end: writer B's displaced entry must survive writer C.

    The codex round-31 replay: A link-publishes; writer C replaces the LIVE sibling while
    the retire is in flight; the scratch then holds writer B's displaced entry as its
    inode's LAST name, and the pre-dance identity-checked unlink destroyed exactly that.
    The dance answers by construction — the entry is withdrawn to the safety name first,
    the count finds no second name, and the entry is PRESERVED there with the scratch
    name freed. This is the two-writer regression the review asked for, at the
    interleaving that produced the original loss.
    """

    staged = ".staged.transition-scratch"
    safety = f"{staged}.transition-safety"
    (tmp_path / staged).write_bytes(b"writer-B displaced\n")
    real_rename = os.rename
    replaced = False

    def writer_c_replaces_the_live_sibling(*args: object, **kwargs: object) -> None:
        # After the dance's withdrawal, before its count: writer C replaces the live
        # name the link publish just installed.
        nonlocal replaced
        result = real_rename(*args, **kwargs)  # type: ignore[arg-type]
        if not replaced and args and str(args[0]) == staged:
            replaced = True
            _replace_atomically(tmp_path, "task.md", b"writer-C replacement\n")
        return result

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with caplog.at_level("WARNING"):
            with mock.patch.object(os, "rename", writer_c_replaces_the_live_sibling):
                cp._fallback_noreplace(dir_fd, staged, dir_fd, "task.md")
    finally:
        os.close(dir_fd)

    assert replaced
    # C owns the live name; B's entry is PRESERVED at the safety name as its inode's only
    # remaining name; the scratch name is free. Nothing destroyed, nothing raised.
    assert (tmp_path / "task.md").read_bytes() == b"writer-C replacement\n"
    assert os.stat(tmp_path / "task.md").st_nlink == 1
    assert (tmp_path / safety).read_bytes() == b"writer-B displaced\n"
    assert os.stat(tmp_path / safety).st_nlink == 1
    assert not (tmp_path / staged).exists()
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert "PRESERVED" in caplog.text


def test_c1_disclosed_residual_c_after_the_final_count_loses_b_at_caller_level(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """DISCLOSED RESIDUAL, pinned at the caller: writer C between the safety dance's
    final link count and its unlink loses writer B's restored entry.

    Round-32's C1 replay pins the writer that arrives BEFORE the count — the dance
    finds nlink 1 at the safety name and PRESERVES the entry there. The codex round-32
    review correctly observed the other half was unpinned: driven through the whole
    delete leg (displace → stale-displacement restore → link publish → retire), writer
    C can replace the live name AFTER the count has read nlink 2 {live, safety} and
    BEFORE the licensed unlink. The unlink then takes B's last name, and the nlink>1
    branch returns True having logged nothing — the exact window the dance's own code
    comment discloses and assigns to
    `projection-lock-coverage-projected-path-writers-20260913`.

    Asserted AS DISCLOSED — B's bytes are lost, C owns the live name — because a
    boundary pinned is a boundary that flips loudly the day the lock row closes it.
    REVERSE with that row: B must then survive under its own preserved name, and these
    loss assertions become survival assertions.
    """

    log = _log(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "task-1.md"
    note.write_bytes(b"stage: S6\n")
    projection = cp.FileProjection.capture(note, after=None)
    real_primitive = cp._renameat2_primitive
    real_unlink = os.unlink
    b_landed = False
    c_fired = False

    def writer_b_then_unsupported_mount(
        src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str, flags: int
    ) -> int:
        # The first NOREPLACE call with the live name as source is the delete leg's
        # displace. B replaces the live name after `_cas_project` snapshotted
        # `current` and before the displacement, so the displace carries B's entry
        # aside; the mount then refuses the flag and the leg rebuilds, exactly as
        # the NFS vault does.
        nonlocal b_landed
        if not b_landed and flags == cp._RENAME_NOREPLACE and src_name == note.name:
            b_landed = True
            _replace_atomically(vault, note.name, b"writer-B replacement\n")
        if flags in (cp._RENAME_EXCHANGE, cp._RENAME_NOREPLACE):
            if flags == cp._RENAME_NOREPLACE and _exists_at(dst_dir_fd, dst_name):
                return errno.EEXIST
            return errno.EINVAL
        return real_primitive(src_dir_fd, src_name, dst_dir_fd, dst_name, flags)

    def writer_c_at_the_guarded_unlink(*args: object, **kwargs: object) -> None:
        # The dance's unlink of the withdrawn safety name is the only removal that
        # runs while B still holds a second name. C replaces the live sibling first,
        # so B's entry drops to the safety name alone and the licensed unlink takes
        # its last copy.
        nonlocal c_fired
        # The delete leg's own scratch is `.{name}.{sha}.transition-scratch`, so its
        # dance-stacked safety name ends `.transition-scratch.transition-safety` —
        # narrowing past bare `.transition-safety` matters: the transaction's lock
        # staging also retires scratch adornments BEFORE the legs run, and a bare
        # suffix match fires writer C there, replacing the live preimage and refusing
        # the transition at the preimage check before the delete leg ever runs.
        if not c_fired and args and str(args[0]).endswith(".transition-scratch.transition-safety"):
            c_fired = True
            _replace_atomically(vault, note.name, b"writer-C replacement\n")
        real_unlink(*args, **kwargs)  # type: ignore[arg-type]

    with mock.patch.object(cp, "_renameat2_primitive", side_effect=writer_b_then_unsupported_mount):
        with mock.patch.object(os, "unlink", side_effect=writer_c_at_the_guarded_unlink):
            with caplog.at_level("WARNING"):
                with pytest.raises(cp.LifecycleTransitionError) as raised:
                    cp.execute_lifecycle_transition(
                        event_log=log,
                        intent=_intent(),
                        projections=[projection],
                        transaction_root=tmp_path / "transactions",
                        lock_root=tmp_path / "locks",
                    )

    assert b_landed and c_fired
    assert raised.value.reason_code == "transition_precondition_changed"
    # C owns the live name; nothing of B survives anywhere in the transaction's tree —
    # the disclosed loss, asserted so the row that closes it has a red test to flip.
    assert note.read_bytes() == b"writer-C replacement\n"
    assert os.stat(note).st_nlink == 1
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert path.read_bytes() != b"writer-B replacement\n", path
    assert _fallback_remnants(tmp_path) == []
    # The nlink>1 branch completes silently — the preservation branch was never taken.
    assert "PRESERVED" not in caplog.text


def test_an_entry_removed_after_publication_is_a_refusal_not_a_crash(tmp_path: Path) -> None:
    """T1: the `FileNotFoundError` branch after publication had no test.

    A writer that *removes* the published destination — rather than replacing it — must
    produce the same typed refusal as a replacement, not an unhandled
    `FileNotFoundError` escaping the leg as an untyped fault the callers do not
    discriminate. The source's only name was consumed by the move, so the refusal has
    to say that too: reload the current position rather than retry.
    """

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    real_fsync = os.fsync
    fired = False

    def removing_fsync(fd: int) -> None:
        nonlocal fired
        real_fsync(fd)
        if not fired:
            fired = True
            os.unlink(tmp_path / ".task.md.scratch")

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "fsync", removing_fsync):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_noreplace(dir_fd, "task.md", dir_fd, ".task.md.scratch")
        assert caught.value.reason_code == "transition_precondition_changed"
        assert "removed" in str(caught.value)
        # executive_function: the hold names the next command.
        assert "recover-claim-publications" in caught.value.repair_action
    finally:
        os.close(dir_fd)

    assert fired
    # The entry is gone because the racing writer removed it; the leg destroyed nothing.
    assert not (tmp_path / "task.md").exists()
    assert not (tmp_path / ".task.md.scratch").exists()
    assert _fallback_remnants(tmp_path) == []


def test_cleanup_keeps_a_spent_scratch_that_is_a_displaced_entrys_last_name(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """codex-1's C2: cleanup treated matching identity as proof of redundancy too.

    The replay needs no I/O failure anywhere. A writer replaces the live note, so the exchange
    preserves THAT inode while publishing; the caller detects the mismatch and exchanges back;
    a second writer then takes over the live name; and cleanup meets `.transition-spent`,
    which by then holds the displaced entry's only remaining copy.

    No writer touches a scratch name, so the `O_CREAT|O_EXCL` reservation that protects the
    scratch names is irrelevant here — this is about what cleanup is entitled to remove. The
    pre-dance guard was `st_nlink`: ours AND redundant is removable, and "ours and the only
    name" was merely KEPT — which left the operand wedged behind the leftover name. The
    round-32 dance removes nothing at the given name at all: the entry is withdrawn to a
    reserved `.transition-safety` name first, the count finds it stranded there, and the
    outcome is PRESERVED-at-safety with the scratch name FREED — recoverable, and not a
    wedge.

    Driven directly at `_retire_scratch`, because reaching the state through the full exchange
    requires the caller's rollback, and this pins the decision the cleanup actually makes.
    """

    displaced = tmp_path / "spent-scratch"
    displaced.write_bytes(b"DISPLACED WRITER ONLY COPY\n")
    displaced_inode = displaced.stat().st_ino
    expected = displaced.stat()  # ours by identity...
    assert expected.st_nlink == 1  # ...and the only name for it
    safety = "spent-scratch.transition-safety"

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with caplog.at_level("WARNING"):
            freed = cp._retire_scratch(dir_fd, "spent-scratch", expected, subject="probe")
    finally:
        os.close(dir_fd)

    # The displaced entry survives — at the safety name the dance withdrew it to, still
    # the inode's only name — and the scratch name it occupied is free, so retries on
    # the operand are not wedged behind it.
    assert not displaced.exists(), (
        "cleanup removed a scratch that was the only name for its inode — the displaced "
        "entry is unrecoverable, which is exactly the reproduced C2 loss"
    )
    preserved = tmp_path / safety
    assert preserved.stat().st_ino == displaced_inode
    assert preserved.read_bytes() == b"DISPLACED WRITER ONLY COPY\n"
    assert os.stat(preserved).st_nlink == 1
    assert freed is True
    # Preserved-and-stranded is a state an operator must reconcile, so it is reported as
    # that rather than passed over in silence.
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert "PRESERVED" in caplog.text
    assert "only remaining name" in caplog.text
    assert "clear it by hand" in caplog.text


def test_cleanup_still_removes_a_scratch_that_is_genuinely_redundant(tmp_path: Path) -> None:
    """The other side of C2's guard, which must keep working or every transaction wedges.

    `_retire_scratch` runs on the SUCCESS path, and the scratch it retires is normally a second
    name for a live projected inode. Leaving that behind gives the live entry `st_nlink == 2`,
    which `_entry_state_at` refuses as path_unsafe on the next readback — so "never remove"
    would break every following transaction on the operand. Redundant-and-ours must still go.
    """

    live = tmp_path / "live"
    live.write_bytes(b"published\n")
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # A genuine second name for the live inode, which is what `spent` actually is.
        os.link("live", "spent-scratch", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        expected = os.lstat("spent-scratch", dir_fd=dir_fd)
        assert expected.st_nlink == 2
        freed = cp._retire_scratch(dir_fd, "spent-scratch", expected, subject="probe")
    finally:
        os.close(dir_fd)

    assert freed is True
    assert not (tmp_path / "spent-scratch").exists(), "the redundant scratch was not removed"
    # The live entry survives and is back to a single link, so the next readback passes.
    assert live.read_bytes() == b"published\n"
    assert live.stat().st_nlink == 1


def test_abandonment_refuses_an_occupied_target_instead_of_overwriting_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The same property on the cleanup side, which also had no occupied-target test."""

    (tmp_path / "scratch").write_bytes(b"someone-elses\n")
    (tmp_path / "other").write_bytes(b"ours\n")
    abandoned = "scratch.transition-abandoned"
    (tmp_path / abandoned).write_bytes(b"AN EARLIER ABANDONMENT\n")

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        expected = os.lstat("other", dir_fd=dir_fd)  # deliberately NOT what `scratch` holds
        with caplog.at_level("WARNING"):
            freed = cp._retire_scratch(dir_fd, "scratch", expected, subject="probe")
    finally:
        os.close(dir_fd)

    assert (tmp_path / abandoned).read_bytes() == b"AN EARLIER ABANDONMENT\n", (
        "abandonment overwrote an earlier abandonment — the reservation no longer refuses"
    )
    # Neither entry destroyed; the name stays occupied, so it is reported as the stuck state.
    assert (tmp_path / "scratch").read_bytes() == b"someone-elses\n"
    assert freed is False
    assert cp._SCRATCH_ABANDONED in caplog.text


def test_noreplace_interrupted_before_publishing_loses_nothing(tmp_path: Path) -> None:
    """T1: interruption between the reserve and the publish, which nothing covered.

    Process termination does not run cleanup handlers, so the state a crash leaves is the
    state on disk at that instant. A Python-level interruption runs the reservation's
    release on the way out, which is what this pins: the source intact, the reserved
    name freed — and, since the round-32 rename-based release, the placeholder
    WITHDRAWN to a `.transition-withdrawn` name rather than unlinked, so an arrival
    that reached the name in the gap survives under a computable dotted name instead
    of being destroyed by the release (C3's class; the release itself is pinned in
    `test_a_release_withdraw_carries_a_racing_arrival_across_c3`). The hard-crash
    window — a kill that skips handlers between the reserve and the rename — strands
    the empty placeholder at the reserved name instead (residual R3); that one fails
    toward refusal and is cleared by hand.
    """

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    withdrawn = ".task.md.scratch.transition-withdrawn"
    real_rename = os.rename

    def crash_before_the_publish(*args: object, **kwargs: object) -> None:
        # Only the publish rename dies; the release's own withdraw must run, or the
        # remnant this test pins is never produced.
        if args and str(args[0]) == "task.md" and str(args[1]) == ".task.md.scratch":
            raise _Crash()
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", crash_before_the_publish):
            with pytest.raises(_Crash):
                cp._fallback_noreplace(dir_fd, "task.md", dir_fd, ".task.md.scratch")
    finally:
        os.close(dir_fd)

    # The source never moved, and the reservation was released even on the way out of a
    # hard failure: a placeholder left at this name would refuse every later attempt on
    # this operand, which is the wedge the release exists to prevent.
    assert (tmp_path / "task.md").read_bytes() == b"live-preimage\n"
    assert os.stat(tmp_path / "task.md").st_nlink == 1
    assert not (tmp_path / ".task.md.scratch").exists()
    # The release withdrew rather than unlinked, and the withdrawal is the remnant it
    # leaves: the empty placeholder, under a name a sweep can compute from the operand.
    assert (tmp_path / withdrawn).read_bytes() == b""
    assert _fallback_remnants(tmp_path) == [withdrawn]


@pytest.mark.parametrize("leg", ["exchange", "noreplace"])
@pytest.mark.parametrize("cut", list(range(1, 13)))
def test_fsync_failure_at_every_cut_loses_nothing_and_leaves_reachable_remnants(
    tmp_path: Path, leg: str, cut: int, caplog: pytest.LogCaptureFixture
) -> None:
    """T1, done properly: a failure at EVERY step, not only the first.

    The previous version raised on *every* `fsync`, so it always fired at the earliest one
    — before installation or retirement — and the later cuts went untested. A reviewer was
    right that this made the test weaker than its name. Now the failure is injected at the
    Nth `fsync`, which walks it through pin, move-aside, publish, retire and finalise —
    twelve barriers on the exchange, counted by the barrier test below.

    Two properties at each cut, and the second is what recovery needs:

    * **No bytes are lost.** Every generation that existed is still readable under some
      name, because each step is a move or a create-or-fail.
    * **Every remnant is reachable.** The leftover names are exactly the ones computable
      from the operands — roles and the round-32 adornments — so an operator, or the
      discovery work owed by the projection-lock task, can enumerate them without a
      directory sweep, which this module does not have.

    Completion is not uniform any more, and that is the point of the round-32 barrier
    split: the four PROPAGATING barriers (the consume and vacate withdrawals of the two
    link publishes) fail the leg, while the three dance withdrawals ABSORB the failure
    and report it — a completed leg with "could not be made durable" in the log is the
    absorbed outcome, not a swallowed one. Cuts beyond a leg's fsync count simply
    complete; that is asserted rather than skipped, so a leg that silently loses an
    fsync shows up here.
    """

    if leg == "exchange":
        (tmp_path / ".src").write_bytes(b"replacement\n")
        (tmp_path / "dst").write_bytes(b"displaced\n")
        operands = (".src", "dst")

        def call(fd: int) -> None:
            cp._fallback_exchange(fd, ".src", fd, "dst")

        expected = {b"replacement\n", b"displaced\n"}
    else:
        (tmp_path / "task.md").write_bytes(b"live-preimage\n")
        operands = ("task.md", ".task.md.scratch")

        def call(fd: int) -> None:
            cp._fallback_noreplace(fd, "task.md", fd, ".task.md.scratch")

        expected = {b"live-preimage\n"}

    seen = 0
    real_fsync = os.fsync

    def failing_fsync(fd: int) -> None:
        nonlocal seen
        seen += 1
        if seen == cut:
            raise OSError(errno.EIO, os.strerror(errno.EIO), f"fsync #{cut}")
        real_fsync(fd)

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            mock.patch.object(os, "fsync", failing_fsync),
            caplog.at_level("WARNING"),
        ):
            try:
                call(dir_fd)
                completed = True
            except OSError as exc:
                assert exc.errno == errno.EIO, (leg, cut, exc)
                completed = False
    finally:
        os.close(dir_fd)

    # The cut either fired inside the leg, or the leg had fewer fsyncs than `cut` — or
    # it fired inside a dance withdrawal, which absorbs the failure and completes with
    # the barrier's loss reported in the log instead.
    assert completed == (seen < cut) or "could not be made durable" in caplog.text, (
        leg,
        cut,
        seen,
        completed,
        caplog.text,
    )

    present = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert expected <= set(present.values()), (leg, cut, present)

    computable = _computable_fallback_names(*operands) | set(operands)
    unreachable = set(present) - computable
    assert not unreachable, (leg, cut, unreachable)


@pytest.mark.parametrize(
    ("leg", "required_barriers"),
    # The exchange is now link-publish plus withdraw-dances: eleven name-establishing
    # mutations, each followed by its own barrier, and the pin retire closes out with
    # an explicit barrier after its dance's unlink — twelve in all. The delete leg's
    # success path is ONE publish rename followed by ONE barrier — the reserve is an
    # `os.open`, which establishes an empty placeholder rather than resolving a name to
    # an inode, so no barrier is owed to it.
    [("exchange", 12), ("noreplace", 1)],
)
def test_each_leg_performs_its_durability_barriers(
    tmp_path: Path, leg: str, required_barriers: int
) -> None:
    """The barrier count, asserted independently of the implementation's own behaviour.

    The cut test above derives its expectation from how many `fsync` calls it observes, so a
    reviewer pointed out that **removing every barrier satisfies it**: `seen` becomes 0,
    every cut "completes", and its byte and name assertions still hold. Its docstring
    claimed a lost barrier would show up there. It would not.

    This is the missing half. The required count is written down here, so deleting any
    `fsync` from either leg fails this test — which is what "the witness must not accept
    removal of durability barriers" requires. Ordering is pinned too: every
    name-establishing mutation is followed by a barrier before the next, and the final
    one is barriered before the leg ends — the retire dance's unlink of a redundant
    name may legitimately trail the last barrier.
    """

    if leg == "exchange":
        (tmp_path / ".src").write_bytes(b"replacement\n")
        (tmp_path / "dst").write_bytes(b"displaced\n")

        def call(fd: int) -> None:
            cp._fallback_exchange(fd, ".src", fd, "dst")
    else:
        (tmp_path / "task.md").write_bytes(b"live-preimage\n")

        def call(fd: int) -> None:
            cp._fallback_noreplace(fd, "task.md", fd, ".task.md.scratch")

    order: list[str] = []
    real_fsync, real_link, real_rename, real_unlink = os.fsync, os.link, os.rename, os.unlink

    def note(kind: str, fn: object) -> object:
        def wrapper(*args: object, **kwargs: object) -> object:
            order.append(kind)
            return fn(*args, **kwargs)  # type: ignore[operator]

        return wrapper

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            mock.patch.object(os, "fsync", note("fsync", real_fsync)),
            mock.patch.object(os, "link", note("link", real_link)),
            mock.patch.object(os, "rename", note("rename", real_rename)),
            mock.patch.object(os, "unlink", note("unlink", real_unlink)),
        ):
            call(dir_fd)
    finally:
        os.close(dir_fd)

    assert order.count("fsync") >= required_barriers, (leg, order)
    # No trailing-barrier assert: the exchange now ends with the retire dance's unlink
    # of a redundant name, which may legitimately follow the last barrier. The
    # established-based loop below already requires a barrier after the FINAL
    # name-establishing mutation, which is the durability-relevant event.

    # Ordering, asserted so that MOVING a barrier fails rather than only DELETING one.
    #
    # The previous form was `"fsync" in order[first:second] or second == first + 1`, and a
    # reviewer showed it cannot fail: consecutive mutations are either adjacent, satisfying
    # the second clause, or separated by the only other recorded operation — an fsync —
    # satisfying the first. It accepted every ordering it recorded, including all barriers
    # moved to the end, which is exactly the trace it was written to reject.
    #
    # Every name-establishing mutation must be followed by a barrier BEFORE the next one,
    # and the last must be followed by one too. Stated as gaps rather than as a running
    # count, which is the third formulation and the first that is neither vacuous nor wrong:
    #
    #   * the original `"fsync" in order[first:second] or second == first + 1` could not
    #     fail — the `or` was an escape hatch that adjacency always satisfied;
    #   * a running prefix deficit caught barriers moved LATER but accepted every barrier
    #     moved EARLIER, since a barrier before its write only makes the deficit smaller. A
    #     barrier that precedes the write it is supposed to flush is useless, and a reviewer
    #     was right that the assertion shrugged at it.
    #
    # `unlink` is excluded, and the exclusion is the invariant rather than a convenience: an
    # earlier version counted it and the real trace failed with four outstanding, because
    # cleanup batches three unlinks of *redundant* names before one barrier. Those names'
    # inodes remain reachable elsewhere, so a crash there costs nothing. Barriers are owed
    # to operations that change which inode a name resolves to, not to the tidying after.
    established = [i for i, kind in enumerate(order) if kind in {"link", "rename"}]
    assert established, (leg, order)
    for first, second in zip(established, established[1:], strict=False):
        assert "fsync" in order[first + 1 : second], (
            f"{leg}: no barrier between the mutations at {first} and {second}",
            order,
        )
    assert "fsync" in order[established[-1] + 1 :], (
        f"{leg}: no barrier after the final name-establishing mutation",
        order,
    )


# --- round-6: the class of defect, not the two spots -------------------------------
#
# Round 5 shipped move-or-fail on the LIVE names and left plain renames into the SCRATCH
# destinations, so a second attempt on the same operand destroyed whatever the first had
# deliberately preserved — and reported success. Three families caught it. These pin the
# whole class: no rename onto an occupied name anywhere, no unconditional unlink of a
# scratch anywhere, for every role and both legs.


@pytest.mark.parametrize("role", ["pin", "holding"])
def test_exchange_refuses_when_any_scratch_destination_is_occupied(
    tmp_path: Path, role: str
) -> None:
    """A remnant may be another writer's only copy, so it is never renamed over.

    Attempt 1 detects a race and deliberately preserves a concurrent writer's ONLY copy at
    a predictable scratch name. Attempt 2 used to rename straight over it and report
    success. Both live roles are covered — `spent` no longer has a generator on this leg
    (the publish rename consumes `src` directly), so only `pin` and `holding` are ever
    consulted.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    remnant = tmp_path / cp._fallback_scratch_name(".src", role)
    remnant.write_bytes(b"another writer's only copy\n")

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(cp.LifecycleTransitionError) as raised:
            cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert raised.value.reason_code == "transition_projection_scratch_exists"
    assert remnant.read_bytes() == b"another writer's only copy\n"
    # Refused before anything moved, so both live entries are untouched.
    assert (tmp_path / "dst").read_bytes() == b"displaced\n"
    assert (tmp_path / ".src").read_bytes() == b"replacement\n"
    # executive_function: the refusal has to say what to do next.
    assert "recover-claim-publications" in raised.value.repair_action


@pytest.mark.parametrize(
    ("fire_point", "fire_dst"),
    [
        ("publish-vacate", ".manifest.json.transition-staged"),
        ("refill-consume-withdraw", ".manifest.json.transition-holding.transition-consumed"),
    ],
)
def test_refill_refuses_a_source_recreated_after_retirement(
    tmp_path: Path, fire_point: str, fire_dst: str
) -> None:
    """The refill is create-or-fail, because both identity checks precede it.

    A writer can recreate `src` between its consumption at the publish and the refill,
    after every check has already passed. The publish is a link dance now, so the
    window has two openings and both are pinned here: the recreation can land at the
    publish's own vacate — `src` has just been renamed to its staged name — or one
    beat later, inside the refill, between its placeholder's consume-withdraw and its
    `link(staged2 -> src)`.

    At the first opening the refill's reserve (`O_CREAT|O_EXCL`) at the live name
    meets the arrival and refuses. At the second the refill's publish link meets
    EEXIST and refuses, naming the arrival's preserved live name and the staged name
    where the displaced entry survives. At both points the retire at step 5 has
    already completed: the pin is gone, and the displaced entry lives on its
    remaining scratch name alone.
    """

    (tmp_path / "manifest.json").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    pin = cp._fallback_scratch_name("manifest.json", "pin")
    holding = cp._fallback_scratch_name("manifest.json", "holding")
    staged2 = f"{holding}.transition-staged"
    real_rename = os.rename
    fired = False

    def recreate_src_inside_the_window(*args: object, **kwargs: object) -> None:
        # Fires once, at whichever rename's destination is `fire_dst` — the publish's
        # vacate or the refill's consume-withdraw, each unique in the trace — and the
        # writer recreates the live name immediately after, inside the window.
        nonlocal fired
        result = real_rename(*args, **kwargs)  # type: ignore[arg-type]
        if not fired and args and str(args[1]) == fire_dst:
            fired = True
            (tmp_path / "manifest.json").write_bytes(b"recreated-by-another-writer\n")
        return result

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", recreate_src_inside_the_window):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_exchange(dir_fd, "manifest.json", dir_fd, "dst")
        assert caught.value.reason_code == "transition_precondition_changed"
    finally:
        os.close(dir_fd)

    assert fired
    # The other writer's entry stands, and the interrupted exchange is intact behind the
    # refusal: published at `dst`, displaced preserved, pin already retired at step 5.
    assert (tmp_path / "manifest.json").read_bytes() == b"recreated-by-another-writer\n"
    assert (tmp_path / "dst").read_bytes() == b"replacement\n"
    assert not (tmp_path / pin).exists()
    if fire_point == "publish-vacate":
        # The refusal fired at the refill's reserve, before the refill's own dance
        # touched `holding` — the displaced entry keeps its step-2 name.
        assert (tmp_path / holding).read_bytes() == b"displaced\n"
        assert os.stat(tmp_path / holding).st_nlink == 1
        assert not (tmp_path / staged2).exists()
    else:
        # The refusal fired at the refill's publish link: `holding` was already vacated
        # to `staged2`, so the displaced entry survives there, and the refusal names
        # both the arrival's live name and that staged name.
        assert (tmp_path / staged2).read_bytes() == b"displaced\n"
        assert os.stat(tmp_path / staged2).st_nlink == 1
        assert not (tmp_path / holding).exists()
        assert "manifest.json" in str(caught.value)
        assert staged2 in str(caught.value)
    # executive_function: name the next command, and say what not to delete.
    assert "recover-claim-publications" in str(caught.value)
    assert "do not delete" in str(caught.value)


def test_an_arrival_during_the_pin_retire_meets_a_create_or_fail_refill(
    tmp_path: Path,
) -> None:
    """R1's window, reopened at the reorder: benign now, and this pins it stays that way.

    The retire of the pin is still a check followed by an act — there is no
    compare-and-unlink — so an arrival can land inside it. The retire is a withdraw
    dance now: the pin is renamed to its `.transition-safety` name, barriered, and
    only then unlinked if its inode survives elsewhere. This injects the arrival at
    the closest observable point — the dance's guarded unlink of the safety name,
    between its count and its act — while the live `src` name is VACANT (vacated at
    step 3), so a writer taking `src` in the gap meets the refill's
    `O_CREAT|O_EXCL` reserve at step 6 and is refused with every generation intact.
    On the pre-reorder shape — the pin consumed into `src` by a rename, residual R1 —
    no such injection point existed and the leg raised nothing, which is the honest
    red this test was written against.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    pin = cp._fallback_scratch_name(".src", "pin")
    holding = cp._fallback_scratch_name(".src", "holding")
    real_unlink = os.unlink
    fired = False

    def take_src_during_the_pin_unlink(*args: object, **kwargs: object) -> None:
        # Inside the retire dance's count-then-unlink window: the pin has been
        # withdrawn to `{pin}.transition-safety`, the count has read nlink 2 (safety +
        # holding), the unlink has not run. The writer takes the VACANT live name —
        # `_replace_atomically` renames onto a name that does not exist, which is a
        # create — and the real unlink then frees the safety name as intended.
        nonlocal fired
        if not fired and args and str(args[0]) == f"{pin}.transition-safety":
            fired = True
            _replace_atomically(tmp_path, ".src", b"attacker\n")
        return real_unlink(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "unlink", take_src_during_the_pin_unlink):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
        assert caught.value.reason_code == "transition_precondition_changed"
    finally:
        os.close(dir_fd)

    assert fired
    # All three generations survive, each under exactly one name: the arrival at the
    # live `src`, our replacement published at `dst`, and the displaced entry at
    # `holding` — the retire completed, so the pin is gone and nothing was destroyed
    # to make the refusal.
    assert (tmp_path / ".src").read_bytes() == b"attacker\n"
    assert os.stat(tmp_path / ".src").st_nlink == 1
    assert (tmp_path / "dst").read_bytes() == b"replacement\n"
    assert os.stat(tmp_path / "dst").st_nlink == 1
    assert (tmp_path / holding).read_bytes() == b"displaced\n"
    assert os.stat(tmp_path / holding).st_nlink == 1
    assert not (tmp_path / pin).exists()
    # The dance unlinked the withdrawn safety name (nlink 2 → 1), so it leaves no
    # residue of its own either.
    assert not (tmp_path / f"{pin}.transition-safety").exists()
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"attacker\n" in surviving
    assert b"replacement\n" in surviving
    assert b"displaced\n" in surviving
    # executive_function: the refusal names the arrival, what not to delete, and the
    # next command.
    assert "do not delete" in str(caught.value)
    assert "recover-claim-publications" in str(caught.value)


def test_cleanup_leaves_a_scratch_another_writer_replaced(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Cleanup is the last place this repair can lose data, and it did.

    An unconditional `unlink` of a scratch destroys whatever occupies that name, including
    an entry another writer put there while the leg ran. Removal is a withdraw dance
    now, and the dance re-reads identity before it removes anything; a mismatch is
    moved aside under a stable, greppable name rather than raised — by cleanup time the
    projection has already succeeded, so raising would discard a verified post-state
    over an untidy remnant. Since the retire-before-refill reorder the scratch the
    exchange retires is the `pin`, at step 5 — `holding` is consumed by the refill and
    no cleanup follows it at all.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    pin = cp._fallback_scratch_name(".src", "pin")
    real_unlink = os.unlink
    swapped = False

    def replace_the_pin_before_its_retire(*args: object, **kwargs: object) -> None:
        # The window that exercises the retire's guard: step 3's publish is complete —
        # its staged retire dance has just unlinked the staged safety name — and step
        # 5's retire of the pin has not yet re-read the pin's identity, so a writer
        # that replaces the pin's name with its own entry arrives between the two.
        nonlocal swapped
        result = real_unlink(*args, **kwargs)  # type: ignore[arg-type]
        if not swapped and args and str(args[0]) == ".src.transition-staged.transition-safety":
            swapped = True
            _replace_atomically(tmp_path, pin, b"someone-elses-entry\n")
        return result

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with caplog.at_level("WARNING"):
            with mock.patch.object(os, "unlink", replace_the_pin_before_its_retire):
                cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert swapped
    # The projection still succeeded — the post-state is the syscall's.
    assert (tmp_path / "dst").read_bytes() == b"replacement\n"
    assert (tmp_path / ".src").read_bytes() == b"displaced\n"
    # The other writer's entry was NOT removed. It is moved aside under an abandoned name
    # rather than simply left, because leaving it would block every later attempt on this
    # operand at the vacancy check — the system has to be able to unstick itself — while
    # still preserving the bytes under a name a sweep can find.
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"someone-elses-entry\n" in surviving
    abandoned = tmp_path / f"{pin}.transition-abandoned"
    assert abandoned.read_bytes() == b"someone-elses-entry\n"
    assert not (tmp_path / pin).exists(), "the scratch name must be free for a retry"
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert pin in caplog.text
    assert "inspect it before removing anything" in caplog.text


def test_directory_noreplace_refuses_an_empty_destination_appearing_after_the_check(
    tmp_path: Path,
) -> None:
    """The leg every transaction runs through, at the interleaving its argument rests on.

    `_fallback_noreplace_directory` lstats the destination and then renames, arguing that
    every post-check arrival except an *empty* directory is refused by `rename` itself. Only
    the straight-line refusal was pinned. This injects the one case the argument excuses —
    an empty directory appearing after the check — and then pins which mechanism answers a
    destination that was occupied all along: the guard, with EEXIST, never the rename.
    """

    staging = tmp_path / "staging"
    final = tmp_path / "final"
    staging.mkdir()
    final.mkdir()
    journal = staging / "txn-1"
    journal.mkdir()
    (journal / "manifest.json").write_bytes(b"{}\n")

    real_rename = os.rename
    fired = False

    def create_empty_destination(*args: object, **kwargs: object) -> None:
        nonlocal fired
        if not fired:
            fired = True
            (final / "txn-1").mkdir()
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    src_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
    dst_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", create_empty_destination):
            # An empty directory appearing here is the documented no-loss case: taking over
            # its name destroys nothing, because an empty directory holds nothing.
            cp._fallback_noreplace(src_fd, "txn-1", dst_fd, "txn-1")
        assert fired
        assert (final / "txn-1" / "manifest.json").read_bytes() == b"{}\n"
        assert not (staging / "txn-1").exists()

        # An occupied destination — populated directory OR file — is refused by the leg's
        # own lstat guard with EEXIST, before `os.rename` is reached at all.
        #
        # This asserted a SET of errnos including ENOTEMPTY and ENOTDIR, on the docstring's
        # claim that plain `rename` supplies those for directories. The set is what let it
        # pass: the guard's EEXIST satisfied it, `os.rename` never ran, and the behaviour the
        # comment named was never measured. Chasing that found the larger thing — the guard
        # refuses EVERY existing destination, so the rename is only ever reached with an
        # absent one and those errnos are unreachable through this function. The code is
        # stricter than the design it was documented against, and `reached_rename` below
        # fails if that ever stops being true.
        for name, make_occupant, survivor in (
            (
                "txn-2",
                lambda p: [p.mkdir(), (p / "keep-me").write_bytes(b"occupied\n")],
                "keep-me",
            ),
            ("txn-3", lambda p: p.write_bytes(b"a file, not a directory\n"), None),
        ):
            source = staging / name
            source.mkdir()
            (source / "manifest.json").write_bytes(b"{}\n")
            destination = final / name
            make_occupant(destination)

            reached_rename = False
            real_rename = os.rename

            def note_rename(*args: object, **kwargs: object) -> None:
                nonlocal reached_rename
                reached_rename = True
                return real_rename(*args, **kwargs)  # type: ignore[arg-type]

            with mock.patch.object(os, "rename", note_rename):
                with pytest.raises(OSError) as caught:
                    cp._fallback_noreplace(src_fd, name, dst_fd, name)
            assert caught.value.errno == errno.EEXIST, (name, caught.value.errno)
            assert not reached_rename, (
                f"{name}: the rename ran, so the guard no longer refuses every occupied "
                "destination — update this test and the leg's docstring together"
            )
            assert (source / "manifest.json").read_bytes() == b"{}\n"
            if survivor:
                assert (destination / survivor).read_bytes() == b"occupied\n"
            else:
                assert destination.read_bytes() == b"a file, not a directory\n"
    finally:
        os.close(src_fd)
        os.close(dst_fd)


# --- the scratch-arrival boundaries, and exactly who is excluded at them -----------------
#
# These three tests replace two that asserted the arriving bytes were DESTROYED. Both of
# those injected their arrival with a plain `write_bytes` — a writer that acquires nothing —
# so they measured the case no reservation and no lock can protect, and were read as evidence
# about the case that can be. The distinction is the whole content of this block:
#
#   participant      acquires the name the way `_relocate_to_scratch` does (O_CREAT|O_EXCL).
#                    EXCLUDED. Pinned by the first two tests; the first goes red if the
#                    reservation is reverted to a check.
#   non-participant  renames or create-truncates straight onto the name. NOT excluded, by
#                    this or by any lock in this module. Pinned by the third test, so the
#                    guarantee cannot quietly be read as wider than it is.
#
# Every writer of these names in this module is a participant, which is why this closes the
# reviewed window rather than merely narrowing it.
#
# One thing they do NOT show, and the old wording let it be misread: both inject their
# arrival with a plain `write_bytes`/`_replace_atomically`, i.e. a writer that acquires
# nothing. No reservation and no lock excludes that writer. These measure the unprotectable
# case; the protectable one is a second writer using this module's own acquisition path.


def test_a_placeholder_reservation_leaves_the_live_entrys_link_count_alone(
    tmp_path: Path,
) -> None:
    """The measurement the relocation's whole design rests on, as a runnable test.

    This lived only in a docstring table and a probe script in the operator's vault, which
    three reviewers correctly said is not a recheck a reader can run. It is the reason
    `_relocate_to_scratch` reserves with `O_CREAT|O_EXCL` rather than `link`: both are
    create-or-EEXIST, but `link` refuses by making a second name for the LIVE inode, and
    `_entry_state_at` rejects any projected entry at `st_nlink != 1`.

    If this ever fails, the reservation is no longer a legal way to take the name here and
    the design needs revisiting — which is exactly why it belongs in the suite and not in a
    file nobody but its author can open.
    """

    live = tmp_path / "note.md"
    live.write_bytes(b"live projection\n")
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)

    def invariant_verdict() -> str:
        try:
            cp._entry_state_at(dir_fd, "note.md", max_bytes=1 << 20)
        except cp.LifecycleTransitionError as refusal:
            return refusal.reason_code
        return "accepted"

    try:
        assert live.stat().st_nlink == 1
        assert invariant_verdict() == "accepted"

        # (a) `link` — the rejected primitive. The LIVE entry gains a name.
        os.link("note.md", "probe-link", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        assert live.stat().st_nlink == 2
        assert invariant_verdict() == "transition_projection_path_unsafe"
        os.unlink("probe-link", dir_fd=dir_fd)
        assert live.stat().st_nlink == 1

        # (b) an O_CREAT|O_EXCL placeholder — a SEPARATE inode. The live entry is untouched.
        holding = cp._fallback_scratch_name("note.md", "holding")
        os.close(os.open(holding, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=dir_fd))
        assert live.stat().st_nlink == 1, "the placeholder touched the live entry"
        assert (tmp_path / holding).stat().st_nlink == 1
        assert invariant_verdict() == "accepted"
    finally:
        os.close(dir_fd)


#: Every `pytest -k` selector a docstring in `shared/coord_projection.py` offers as a recheck
#: command, paired with a test name it must match.
_DOCSTRING_RECHECK_SELECTORS = (
    ("a_placeholder_reservation_leaves_the_live_entrys_link_count_alone", __name__),
    ("unsupported_errno", __name__),
    ("declared_unsupported_set", __name__),
    ("the_scratch_reservation_is_genuinely_exclusive", "nfs_integration"),
)


def test_every_docstring_recheck_selector_actually_selects_something() -> None:
    """A `-k` selector that matches nothing exits green-ish, which is an invisible skip.

    The module's docstrings hand readers `pytest -k <selector>` invocations as the way to
    recheck their claims. If a test is renamed, the selector silently selects zero tests and
    the recheck "passes" — the same invisible-skip defect the integration module was hardened
    against with `test_the_waiver_expiry_row_is_resolvable`. A reviewer noted the selectors
    could not be confirmed from the review packet; this confirms them from the suite instead.
    """

    import ast
    import inspect

    # Match against PARSED FUNCTION NAMES, not source text. The first version of this test
    # fell back to `selector in haystack`, and `haystack` was the whole module source — which
    # contains `_DOCSTRING_RECHECK_SELECTORS` itself, so every selector matched its own
    # declaration. A reviewer renamed every test function in memory and the assertion still
    # passed. A test that cannot fail is the defect this test exists to catch, committed inside
    # the test that catches it.
    def collected_test_names(path: Path) -> set[str]:
        tree = ast.parse(path.read_text())
        return {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        }

    here = Path(inspect.getsourcefile(sys.modules[__name__]) or __file__)
    names = {
        __name__: collected_test_names(here),
        "nfs_integration": collected_test_names(
            here.with_name("test_coord_projection_nfs_integration.py")
        ),
    }
    module_source = inspect.getsource(cp)

    for selector, where in _DOCSTRING_RECHECK_SELECTORS:
        assert any(selector in name for name in names[where]), (
            f"the docstring recheck selector {selector!r} matches no collected test in "
            f"{where} — `pytest -k {selector}` would select nothing and exit without "
            "checking anything, which is the invisible skip this pins"
        )
        assert selector in module_source, (
            f"{selector!r} is pinned here but no longer cited by any docstring; drop it from "
            "_DOCSTRING_RECHECK_SELECTORS or restore the citation"
        )


def _participant_takes(dir_fd: int, name: str, payload: bytes) -> str:
    """A second writer acquiring the scratch name the way `_relocate_to_scratch` does.

    This is the adversary the reviews describe — "a second attempt on the same operand", and
    on the delete leg "every transaction touching that note computes the same holding". It
    acquires through the same primitive the module uses, so whatever exclusion the real legs
    get, this gets. Returns what happened, so the test can assert on it rather than infer.
    """

    try:
        handle = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=dir_fd)
    except FileExistsError:
        return "excluded"
    os.write(handle, payload)
    os.close(handle)
    return "took the name"


def test_a_participant_is_excluded_from_the_scratch_rather_than_overwritten(
    tmp_path: Path,
) -> None:
    """The relocation boundary: the second writer is refused BEFORE it can write.

    Previously this asserted the arrival's bytes were gone, under a comment saying closure
    was unavailable at this layer. The reservation in `_relocate_to_scratch` is what changed
    that: the name is taken atomically immediately before the rename that consumes it, so a
    writer acquiring it the same way loses the race cleanly instead of losing its bytes.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    holding = cp._fallback_scratch_name(".src", "holding")
    real_rename = os.rename
    outcome: str | None = None

    def race_inside_the_window(*args: object, **kwargs: object) -> None:
        # The reservation has been taken; this is the rename that consumes it — the exact
        # interleaving all three reviewer families named.
        nonlocal outcome
        if outcome is None and len(args) > 1 and str(args[1]) == holding:
            outcome = _participant_takes(dir_fd, holding, b"arrived-after-the-check\n")
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", race_inside_the_window):
            cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert outcome == "excluded", (
        f"the second writer was not excluded ({outcome}) — the destination is no longer "
        "reserved across the relocation, so an arrival here is destroyed silently again"
    )
    # Nothing was destroyed: it never wrote, and the projection completed.
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"arrived-after-the-check\n" not in surviving
    assert (tmp_path / "dst").read_bytes() == b"replacement\n"
    assert (tmp_path / ".src").read_bytes() == b"displaced\n"


@pytest.mark.parametrize(
    ("branch", "expected_at_the_name"),
    [("identity", b"ours\n"), ("abandonment", b"someone-elses\n")],
)
def test_cleanups_occupancy_argument_is_pinned_not_just_argued(
    tmp_path: Path, branch: str, expected_at_the_name: bytes
) -> None:
    """Both of cleanup's two-step branches, with occupancy mutated AWAY.

    `_retire_scratch` reads identity and then acts, and nothing can fuse those two steps.
    Safety rests on the name being OCCUPIED for the whole gap, so a writer acquiring names
    the way this module does is refused and never lands a replacement there. That was an
    argument in a docstring with one pin behind it, and the abandonment branch — which has
    the same two-step shape — had none at all.

    This drives both branches directly and, at the instant between the identity read and the
    action, has a participant try to take the name. The assertion is that it cannot.

    Mutation receipt, measured 2026-09-14 — add an `unlink` to the same injection so the name
    falls vacant, and the **identity** branch destroys the arrival. (The abandonment branch
    survives it, because a rename carries an arrival across where an unlink would not.) So
    occupancy is load-bearing, this test is not vacuous, and it is the only thing standing
    between the identity branch and the loss the reviewers described.
    """

    (tmp_path / "scratch").write_bytes(expected_at_the_name)
    (tmp_path / "other").write_bytes(b"ours\n")
    competitor: str | None = None
    real_lstat = os.lstat

    def race_inside_the_gap(*args: object, **kwargs: object) -> os.stat_result:
        """Between the identity read and the action, a participant tries for the name."""
        nonlocal competitor
        result = real_lstat(*args, **kwargs)
        if competitor is None and args and str(args[0]) == "scratch":
            competitor = _participant_takes(dir_fd, "scratch", b"COMPETITOR\n")
        return result

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # identity branch: `expected` IS what sits at the name. abandonment branch: it is not.
        expected = os.lstat("scratch" if branch == "identity" else "other", dir_fd=dir_fd)
        with mock.patch.object(os, "lstat", race_inside_the_gap):
            cp._retire_scratch(dir_fd, "scratch", expected, subject="probe")
    finally:
        os.close(dir_fd)

    assert competitor == "excluded", (
        f"a participant took the name inside the {branch} branch's gap ({competitor}) — "
        "cleanup no longer holds it across the gap, so the loss the occupancy argument "
        "rules out is reachable again"
    )
    survivors = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"COMPETITOR\n" not in survivors
    # And the entry that was there is handled by its own branch. The identity branch now
    # PRESERVES it: `expected` is the only name for that inode in this fixture, so the
    # withdraw dance finds nlink 1 at the safety name and keeps the entry there —
    # removing a last name is what codex-1's C2 replay destroyed. Redundant-and-ours is
    # the only removable case, and it is covered by the ordinary exchange tests where
    # `spent` is a genuine second link.
    if branch == "identity":
        assert not (tmp_path / "scratch").exists(), "the scratch name must be free"
        preserved = tmp_path / "scratch.transition-safety"
        assert preserved.read_bytes() == b"ours\n"
        assert os.stat(preserved).st_nlink == 1
    else:
        assert (tmp_path / "scratch.transition-abandoned").read_bytes() == b"someone-elses\n"


def test_losing_the_reservation_race_refuses_with_the_typed_hold(tmp_path: Path) -> None:
    """The branch that runs when THIS attempt is the one that loses.

    The exclusion test above wins the race and watches the competitor refuse, so it only ever
    runs the competitor's `FileExistsError` path — never this leg's own. A reviewer pointed
    out that the refusal here therefore had no coverage at all: it could raise the wrong
    reason code, or destroy the winner's entry on the way out, with nothing to catch it.

    Here the arrival lands after the vacancy check and BEFORE the reservation, so this
    attempt's `O_CREAT|O_EXCL` is the call that fails.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    holding = cp._fallback_scratch_name(".src", "holding")
    real_open = os.open
    arrived = False

    def arrive_just_before_the_reservation(*args: object, **kwargs: object) -> int:
        nonlocal arrived
        if not arrived and args and str(args[0]) == holding:
            arrived = True
            _replace_atomically(tmp_path, holding, b"WINNER OF THE RACE\n")
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "open", arrive_just_before_the_reservation):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert arrived, "the arrival must land before the reservation for this to mean anything"
    assert caught.value.reason_code == "transition_precondition_changed"
    # The winner's bytes are intact, both operands are intact, and the refusal says what to
    # do next rather than leaving the operator to guess.
    assert (tmp_path / holding).read_bytes() == b"WINNER OF THE RACE\n"
    assert (tmp_path / ".src").read_bytes() == b"replacement\n"
    assert (tmp_path / "dst").read_bytes() == b"displaced\n"
    assert "recover-claim-publications" in str(caught.value)
    assert holding in str(caught.value)


def test_a_writer_ignoring_the_protocol_is_not_excluded(tmp_path: Path) -> None:
    """The BOUND on the test above, pinned so the guarantee cannot be overclaimed.

    This writer renames straight onto the reserved name without acquiring it, and its bytes
    are destroyed exactly as they were before the reservation existed. A lock in this module
    would not exclude it either — both mechanisms bind the writers that consult them.

    So the claim this module may make is "every writer of these names in this module is
    excluded", never "the name cannot be taken". If a writer outside this module is ever
    found writing these dotted scratch names, this test is where that scope was recorded.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    holding = cp._fallback_scratch_name(".src", "holding")
    real_rename = os.rename
    fired = False

    def bypass_the_reservation(*args: object, **kwargs: object) -> None:
        nonlocal fired
        if not fired and len(args) > 1 and str(args[1]) == holding:
            fired = True
            _replace_atomically(tmp_path, holding, b"bypassed-the-protocol\n")
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", bypass_the_reservation):
            cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert fired
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"bypassed-the-protocol\n" not in surviving, (
        "a non-participating writer is now excluded too — that is stronger than a "
        "reservation can give, so find out what actually changed before believing it"
    )


def test_a_participant_cannot_replace_a_scratch_cleanup_is_about_to_unlink(
    tmp_path: Path,
) -> None:
    """The cleanup boundary, for the same two classes of writer.

    `_retire_scratch` counts and then unlinks, and those are still two operations —
    reviewers are right that no second identity check can close the gap between them.
    What closes it against a PARTICIPANT is that the name is occupied for the whole of
    it, so a writer acquiring names the way this module does is refused and never lands
    a replacement. The retire is a withdraw dance now, and the one conditional unlink
    the exchange's success path still performs is the dance's guarded removal of the
    PIN's `.transition-safety` name at step 5 — the pin itself is never unlinked and
    `holding` is consumed by the refill, so the boundary lives at the safety name.

    **This property does not come from the reservation and this test does not pin it.**
    Measured: with the reservation reverted to a check, the relocation test above goes red
    and this one stays green, because an occupied name refuses a *checking* writer just as
    well as a *reserving* one. It is recorded because it was previously asserted the other
    way round — that a replacement lands and is destroyed — which was true only of a writer
    that never checks, and that writer is the subject of the test above.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    pin = cp._fallback_scratch_name(".src", "pin")
    safety = f"{pin}.transition-safety"
    real_unlink = os.unlink
    outcome: str | None = None

    def race_inside_the_cleanup_gap(*args: object, **kwargs: object) -> None:
        # The dance has withdrawn the pin to its safety name, re-proven identity there,
        # and read nlink 2 — the guarded unlink has not run. The participant tries for
        # the SAFETY name, the occupied one.
        nonlocal outcome
        if outcome is None and args and str(args[0]) == safety:
            outcome = _participant_takes(dir_fd, safety, b"replaced-after-the-check\n")
        return real_unlink(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "unlink", race_inside_the_cleanup_gap):
            cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert outcome == "excluded", (
        f"the second writer was not excluded ({outcome}) — cleanup's unlink is reachable "
        "by a replacement again"
    )
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"replaced-after-the-check\n" not in surviving
    assert (tmp_path / "dst").read_bytes() == b"replacement\n"


def test_an_unconsumed_reservation_is_released_so_the_next_attempt_can_retry(
    tmp_path: Path,
) -> None:
    """The cost of reserving, and the release that pays it.

    A name taken at the reservation and never renamed onto would survive the process and
    refuse every later attempt on that operand — a wedge, which is what killed the earlier
    `mkdir`-reservation draft. The relocation releases its own placeholder when the rename it
    took it for fails, so a failed attempt leaves the operand exactly as it found it.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    holding = cp._fallback_scratch_name(".src", "holding")
    real_rename = os.rename

    def fail_the_relocation(*args: object, **kwargs: object) -> None:
        if len(args) > 1 and str(args[1]) == holding:
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", fail_the_relocation):
            with pytest.raises(OSError) as raised:
                cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
        assert raised.value.errno == errno.EIO

        # The placeholder is gone, so a retry is not wedged...
        assert not (tmp_path / holding).exists(), (
            "an unconsumed reservation survived the failure — every later attempt on this "
            "operand will now refuse at the vacancy check"
        )
        cp._refuse_if_scratch_occupied(dir_fd, (holding,), "retry")
    finally:
        os.close(dir_fd)

    # ... and the operand is untouched, so the retry has something to retry.
    assert (tmp_path / ".src").read_bytes() == b"replacement\n"


def test_a_reservation_whose_identity_cannot_be_established_is_refused_not_stranded(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`fstat` on our own new descriptor can fail, and it used to escape uncaught.

    The identification runs outside any handler, so an EIO there propagated straight out of
    the leg: the placeholder stayed, nothing was logged, and every later attempt on the
    operand refused at the vacancy check with no explanation anywhere. The name is held and
    unprovable, so it must NOT be removed — but it must be reported, and the refusal must
    say so rather than surfacing as a bare OSError from a syscall the caller never made.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    holding = cp._fallback_scratch_name(".src", "holding")
    real_fstat = os.fstat
    real_open = os.open
    ours: set[int] = set()

    def note_our_reservation(*args: object, **kwargs: object) -> int:
        handle = real_open(*args, **kwargs)  # type: ignore[arg-type]
        if args and str(args[0]) == holding:
            ours.add(handle)
        return handle

    def fail_identifying_our_reservation(handle: int) -> os.stat_result:
        if handle in ours:
            raise OSError(errno.EIO, os.strerror(errno.EIO), "fstat")
        return real_fstat(handle)

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with caplog.at_level("WARNING"):
            with (
                mock.patch.object(os, "open", note_our_reservation),
                mock.patch.object(os, "fstat", fail_identifying_our_reservation),
            ):
                with pytest.raises(cp.LifecycleTransitionError) as caught:
                    cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert caught.value.reason_code == "transition_projection_scratch_exists"
    # Preserve-on-uncertainty: the name is held and unprovable, so it stays.
    assert (tmp_path / holding).exists()
    # Both operands untouched — nothing moved before the identification.
    assert (tmp_path / ".src").read_bytes() == b"replacement\n"
    assert (tmp_path / "dst").read_bytes() == b"displaced\n"
    # And it is reported, with a remedy that acts on the thing it names.
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert holding in caplog.text
    assert "clear it by hand" in str(caught.value)
    assert "will not clear this name" in str(caught.value)


def test_a_refused_withdrawal_reports_the_reservation_it_leaves(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """codex round-32 major: `_release_scratch_reservation` ignored the withdrawal's
    False return, so a failed release left the placeholder holding the operand with
    nothing logged and no next action — a wedge invisible until every later attempt
    on that operand refused at the vacancy check. The caller now reports it through
    `_wedged`: the original reservation named, the refusal consequence spelled out,
    the manual remedy attached.
    """

    name = ".task.md.scratch-reservation"
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        handle = os.open(
            name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC, 0o600, dir_fd=dir_fd
        )
        placeholder = os.fstat(handle)
        os.close(handle)
        monkeypatch.setattr(cp, "_move_aside_atomically", lambda *args: False)
        with caplog.at_level("WARNING"):
            cp._release_scratch_reservation(dir_fd, name, placeholder)
    finally:
        os.close(dir_fd)

    assert cp._SCRATCH_ABANDONED in caplog.text
    assert name in caplog.text
    assert "transition_projection_scratch_exists" in caplog.text
    # The refusal it reports is real: the reservation is still holding the name.
    assert (tmp_path / name).exists()


def test_an_occupied_withdrawal_target_still_names_the_original_reservation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The same report on the real refusal path, not a stubbed one.

    A pre-occupied `.transition-withdrawn` target makes `_move_aside_atomically`
    return False at its reserve step — it wedges about the TARGET it could not take,
    and before round 33 that is where the reporting stopped, leaving the reservation
    at the operand unmentioned. Both names must reach the operator now.
    """

    name = ".task.md.scratch-reservation"
    (tmp_path / f"{name}.transition-withdrawn").write_bytes(b"prior remnant\n")
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        handle = os.open(
            name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC, 0o600, dir_fd=dir_fd
        )
        placeholder = os.fstat(handle)
        os.close(handle)
        with caplog.at_level("WARNING"):
            cp._release_scratch_reservation(dir_fd, name, placeholder)
    finally:
        os.close(dir_fd)

    # The helper's report about the target it could not reserve...
    assert f"{name}.transition-withdrawn" in caplog.text
    # ...and the caller's report that the reservation at the operand survives.
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert (tmp_path / name).exists()


def test_move_aside_reports_and_returns_false_when_identity_cannot_be_established(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The same failure on the never-raises path must stay never-raising.

    `_move_aside_atomically` is called from cleanup and from a rollback that is already
    propagating another exception. An `fstat` error escaping there would mask the failure
    actually being reported, so it returns False and says what it left behind.
    """

    (tmp_path / "scratch").write_bytes(b"someone-elses\n")
    (tmp_path / "other").write_bytes(b"ours\n")
    abandoned = "scratch.transition-abandoned"
    real_fstat = os.fstat
    real_open = os.open
    ours: set[int] = set()

    def note_our_reservation(*args: object, **kwargs: object) -> int:
        handle = real_open(*args, **kwargs)  # type: ignore[arg-type]
        if args and str(args[0]) == abandoned:
            ours.add(handle)
        return handle

    def fail_identifying_our_reservation(handle: int) -> os.stat_result:
        if handle in ours:
            raise OSError(errno.EIO, os.strerror(errno.EIO), "fstat")
        return real_fstat(handle)

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        expected = os.lstat("other", dir_fd=dir_fd)  # deliberately NOT what `scratch` holds
        with caplog.at_level("WARNING"):
            with (
                mock.patch.object(os, "open", note_our_reservation),
                mock.patch.object(os, "fstat", fail_identifying_our_reservation),
            ):
                freed = cp._retire_scratch(dir_fd, "scratch", expected, subject="probe")
    finally:
        os.close(dir_fd)

    assert freed is False
    # Nothing destroyed on either name.
    assert (tmp_path / "scratch").read_bytes() == b"someone-elses\n"
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert abandoned in caplog.text


def test_the_release_does_not_delete_an_EMPTY_entry_it_did_not_create(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Emptiness is not identity, and treating it as identity deleted a writer's only entry.

    The release used to accept "an empty regular file" as proof the placeholder was still
    ours. A writer can create an empty file too — a truncate-then-write in progress, a
    zero-byte marker — so a reviewer replayed the sequence that destroys it: replace the live
    source with an EMPTY file, fail the rename, and the release removes what the writer left.

    Every earlier test here injected a NON-empty replacement or failed before the rename, so
    all of them passed over the one case that mattered. The placeholder is identified by
    inode now, and this is the case that tells the two apart.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    holding = cp._fallback_scratch_name(".src", "holding")
    real_rename = os.rename

    def swap_in_an_empty_entry_then_fail(*args: object, **kwargs: object) -> None:
        if len(args) > 1 and str(args[1]) == holding:
            # Their entry, at our reserved name, indistinguishable from our placeholder by
            # size and type — and distinguishable by inode.
            _replace_atomically(tmp_path, holding, b"")
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with caplog.at_level("WARNING"):
            with mock.patch.object(os, "rename", swap_in_an_empty_entry_then_fail):
                with pytest.raises(OSError):
                    cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert (tmp_path / holding).exists(), (
        "the release deleted an empty entry it did not create — emptiness was taken for "
        "identity again"
    )
    # It is not ours, so the name stays taken; that blocks retries, so it must be reported.
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert "did not create" in caplog.text
    assert "recover-claim-publications" in caplog.text


def test_a_reservation_that_cannot_be_released_is_reported_as_a_wedge(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A wedge the operator cannot see is the defect this PR fixes elsewhere.

    The release swallowed every error and logged nothing, so its one bad outcome — a
    placeholder that refuses every later attempt on the operand, permanently — was silent.
    Every other remnant path here logs `_SCRATCH_ABANDONED` with a remedy; this one does
    too, and names the command that clears it.

    The release withdraws by rename now, so the wedge has a new shape: a stale remnant
    already sitting at the `.transition-withdrawn` name refuses the withdrawal's
    `O_CREAT|O_EXCL` reserve, and the placeholder this attempt took stays at the live
    scratch name. A remnant there is most likely a previous attempt's preserved bytes,
    so it is named — never touched.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    holding = cp._fallback_scratch_name(".src", "holding")
    withdrawn = f"{holding}.transition-withdrawn"
    (tmp_path / withdrawn).write_bytes(b"stale-from-a-previous-attempt\n")
    real_rename = os.rename

    def fail_the_relocation(*args: object, **kwargs: object) -> None:
        if len(args) > 1 and str(args[1]) == holding:
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with caplog.at_level("WARNING"):
            with mock.patch.object(os, "rename", fail_the_relocation):
                with pytest.raises(OSError):
                    cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert cp._SCRATCH_ABANDONED in caplog.text
    assert withdrawn in caplog.text
    assert "transition_projection_scratch_exists" in caplog.text
    assert "recover-claim-publications" in caplog.text
    # The wedge itself: the placeholder this attempt took is STILL THERE, empty, and
    # the stale remnant that refused the withdrawal is untouched.
    assert (tmp_path / holding).read_bytes() == b""
    assert (tmp_path / withdrawn).read_bytes() == b"stale-from-a-previous-attempt\n"


def test_a_release_withdraw_carries_a_racing_arrival_across_c3(tmp_path: Path) -> None:
    """Round-31 codex C3, replayed against the round-32 release.

    The NOREPLACE fallback's reservation destination is a name a racing writer can
    reach. The pre-round-32 release proved the placeholder's identity with `lstat`
    and then unlinked — two operations — so a rogue that replaced the reserved name
    between them had its entry destroyed by a call that had already decided the name
    was safe to remove. The release withdraws by rename now: one rename carries
    WHATEVER occupies the name at the instant of the call across to the reserved
    `.transition-withdrawn` name, ours or the rogue's. This injects the rogue between
    the release's identity check and the withdrawal — at the withdraw reserve's own
    `os.open`, the last syscall before the rename — and pins that it survives.
    """

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    withdrawn = ".task.md.scratch.transition-withdrawn"
    real_rename = os.rename
    real_open = os.open
    rogue_landed = False

    def fail_the_publish(*args: object, **kwargs: object) -> None:
        # Only the publish pair dies; the release's withdraw rename, and the rogue's
        # own move, must both go through. The pair filter keeps both safe.
        if args and str(args[0]) == "task.md" and str(args[1]) == ".task.md.scratch":
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    def rogue_lands_at_the_reserve(*args: object, **kwargs: object) -> int:
        # The withdraw reserve has just taken the `.transition-withdrawn` name, and
        # the release's identity check has ALREADY passed — the reserved name still
        # held this attempt's placeholder when it ran. A rogue replacing the reserved
        # name now sits exactly in the gap the old unlink could not see; the
        # withdrawal's rename then carries it across instead.
        nonlocal rogue_landed
        fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
        if not rogue_landed and args and str(args[0]) == withdrawn:
            rogue_landed = True
            _replace_atomically(tmp_path, ".task.md.scratch", b"rogue-arrival\n")
        return fd

    dir_fd = real_open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with (
            mock.patch.object(os, "rename", fail_the_publish),
            mock.patch.object(os, "open", rogue_lands_at_the_reserve),
        ):
            with pytest.raises(OSError):
                cp._fallback_noreplace(dir_fd, "task.md", dir_fd, ".task.md.scratch")
    finally:
        os.close(dir_fd)

    assert rogue_landed
    # The rogue survived the release: carried to the withdrawn name, not destroyed,
    # and the reserved name is free for the next attempt.
    assert not (tmp_path / ".task.md.scratch").exists()
    assert (tmp_path / withdrawn).read_bytes() == b"rogue-arrival\n"
    assert os.stat(tmp_path / withdrawn).st_nlink == 1
    # The source never moved.
    assert (tmp_path / "task.md").read_bytes() == b"live-preimage\n"
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"rogue-arrival\n" in surviving


def test_a_reservation_is_not_released_when_someone_else_filled_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The release must not become a second way to destroy bytes.

    It unlinks only an entry that is still the empty placeholder it created. A writer that
    ignored the protocol and dropped real bytes at the name is left for `_retire_scratch`,
    which preserves what it cannot identify — the release is a rollback of our own action,
    never a cleanup of somebody else's. Leaving it does block retries, so it is still
    reported rather than passed over in silence.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    holding = cp._fallback_scratch_name(".src", "holding")
    real_rename = os.rename

    def fill_the_reservation_then_fail(*args: object, **kwargs: object) -> None:
        if len(args) > 1 and str(args[1]) == holding:
            _replace_atomically(tmp_path, holding, b"not-a-placeholder-any-more\n")
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with caplog.at_level("WARNING"):
            with mock.patch.object(os, "rename", fill_the_reservation_then_fail):
                with pytest.raises(OSError):
                    cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert (tmp_path / holding).read_bytes() == b"not-a-placeholder-any-more\n", (
        "the release deleted an entry it did not create"
    )
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert "did not create" in caplog.text


def test_retire_scratch_leaves_the_entry_when_abandonment_itself_fails(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The I/O-error branch of cleanup, which had no direct coverage.

    When the entry is not ours AND it cannot be moved aside either, the only safe action
    left is to do nothing. That is a stuck state — retries refuse at the vacancy check until
    it is reconciled — so it must be reported as one rather than as routine tidying.
    """

    (tmp_path / "scratch").write_bytes(b"someone-elses\n")
    (tmp_path / "other").write_bytes(b"ours\n")
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        expected = os.lstat("other", dir_fd=dir_fd)  # deliberately NOT what `scratch` holds

        # Abandonment moves the entry with `rename` now, not `link`+`unlink`, so this
        # refuses the syscall abandonment actually uses.
        def refuse_to_rename(*args: object, **kwargs: object) -> None:
            raise OSError(errno.EIO, os.strerror(errno.EIO), "rename")

        with caplog.at_level("WARNING"):
            with mock.patch.object(os, "rename", refuse_to_rename):
                freed = cp._retire_scratch(dir_fd, "scratch", expected, subject="probe")
    finally:
        os.close(dir_fd)

    assert freed is False
    # Nothing destroyed, nothing moved.
    assert (tmp_path / "scratch").read_bytes() == b"someone-elses\n"
    # And it is reported as the stuck state it is.
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert "COULD NOT BE ABANDONED" in caplog.text
    assert "transition_projection_scratch_exists" in caplog.text


@pytest.mark.parametrize("failing", ["lstat", "unlink"])
def test_retire_scratch_absorbs_io_errors_on_every_branch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, failing: str
) -> None:
    """ "Never raises" has to hold on every branch, and it did not.

    The initial `lstat` and the identity-matched `unlink` caught only `FileNotFoundError`,
    so an `EIO` from either escaped the helper — failing a projection that had already
    succeeded, which is the single outcome this function's contract exists to prevent. A
    reviewer found it by replay; this pins both branches.

    The removal the `unlink` parametrization breaks is the dance's guarded removal of
    the withdrawn `.transition-safety` name — the only unlink left — and its outcome
    changed with it: the scratch name is already free, the entry is PRESERVED at the
    safety name (still reached by its sibling), and the call still never raises.
    """

    target = tmp_path / "scratch"
    target.write_bytes(b"ours\n")
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # A REDUNDANT scratch, deliberately. With a single link the nlink guard keeps the entry
        # before the patched `unlink` can raise, so the error handler is never reached and every
        # assertion below passes while covering nothing — a reviewer showed the body stays green
        # with that handler deleted. The second link is what makes the removal attempt happen.
        os.link("scratch", "live-elsewhere", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        expected = os.lstat("scratch", dir_fd=dir_fd)
        assert expected.st_nlink == 2, "the fixture must be redundant or the unlink is skipped"
        reached = False

        def boom(*args: object, **kwargs: object) -> None:
            nonlocal reached
            reached = True
            raise OSError(errno.EIO, os.strerror(errno.EIO), failing)

        with caplog.at_level("WARNING"):
            with mock.patch.object(os, failing, boom):
                # Must not raise. Before the fix, both parametrisations did.
                freed = cp._retire_scratch(dir_fd, "scratch", expected, subject="probe")
    finally:
        os.close(dir_fd)

    assert reached, (
        f"the patched {failing} was never called, so the error handler it exists to pin was "
        "not exercised — check the fixture still reaches the removal attempt"
    )
    if failing == "lstat":
        # Unreadable: left exactly in place, name still taken, reported.
        assert freed is False
        assert target.read_bytes() == b"ours\n", "an unreadable scratch is left"
        assert "could not be examined" in caplog.text
    else:
        # Unremovable: the dance withdrew `scratch` first, so the NAME is free — which
        # is what the caller owes the next attempt — and the redundant entry lives on
        # at the safety name, still reached by its sibling. `freed is True` is the
        # honest answer here, not a green wash: the leftover is a computable dotted
        # remnant a sweep finds, not an occupied live scratch name.
        assert freed is True
        assert not target.exists()
        preserved = tmp_path / "scratch.transition-safety"
        assert preserved.read_bytes() == b"ours\n"
        assert os.stat(preserved).st_nlink == 2
        assert "could not be removed" in caplog.text
    assert cp._SCRATCH_ABANDONED in caplog.text


def test_a_scratch_of_ours_that_cannot_be_removed_is_reported_where_it_happens(
    tmp_path: Path,
) -> None:
    """An unremovable scratch of OURS poisons the next readback, so it is named here.

    Absorbing the cleanup error was only half the contract. The callers ignored the return
    value, so a redundant link of ours survived, the live entry kept `st_nlink == 2`, and the
    very next `_entry_state_at` refused it as `transition_projection_path_unsafe` — the
    transition failing anyway, after its mutations, with a diagnosis pointing at the wrong
    thing. A reviewer confirmed that by replay across create, update and delete.

    Reported at the point where the cause is known instead. A foreign leftover still does not
    escalate: it harms nothing, and only a second link to a live inode does.

    Round-32 note on the injection: the unremovable scratch of ours is now the dance's
    own WITHDRAWAL failing — the pin stays at its name, the refill still completes, and
    the stranded check at the end of the leg is what turns the leftover into this
    refusal: `.src` reads back at nlink 2 with the pin, which is the `path-unsafe`
    shape the message names.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    pin = cp._fallback_scratch_name(".src", "pin")
    real_rename = os.rename

    def refuse_the_pin_withdraw(*args: object, **kwargs: object) -> None:
        # The step-5 dance's withdrawal of the pin is the only rename that dies; the
        # refill's own dance — and everything else — must run, or the post-state this
        # test pins is never produced.
        if len(args) > 1 and str(args[1]) == f"{pin}.transition-safety":
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", refuse_the_pin_withdraw):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert caught.value.reason_code == "transition_projection_recovery_required"
    # It names the scratch, says why continuing would fail, and gives the next command.
    assert "path-unsafe" in str(caught.value)
    assert "recover-claim-publications" in caught.value.repair_action
    assert any(name in str(caught.value) for name in _fallback_remnants(tmp_path))
    assert (tmp_path / pin).read_bytes() == b"displaced\n", "the stranded scratch is the pin"
    # The projection's own post-state still landed; this is about the leftover, not a loss.
    assert (tmp_path / "dst").read_bytes() == b"replacement\n"
    assert (tmp_path / ".src").read_bytes() == b"displaced\n"
