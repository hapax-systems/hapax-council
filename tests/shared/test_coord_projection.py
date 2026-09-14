"""Tests for shared/coord_projection.py — taxonomy, emitters, projection fold."""

from __future__ import annotations

import dataclasses
import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
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
    root = tmp_path / "locks"
    original_flock = cp.fcntl.flock
    exclusive_calls = 0

    def replace_lock(handle: int, operation: int) -> None:
        nonlocal exclusive_calls
        original_flock(handle, operation)
        if operation != cp.fcntl.LOCK_EX:
            return
        exclusive_calls += 1
        if exclusive_calls != 2:
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
    while the readback passes. See `_refuse_if_displaced_entry_moved`, the race tests
    below, and NFS-EXCHANGE-FALLBACK-DESIGN-20260911.md §8, which corrects the ratified
    design on exactly this point.
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

    for cut in range(1, 5):
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
        computable = {
            cp._fallback_scratch_name(base, role)
            for base in (".src", "dst")
            for role in cp._FALLBACK_SCRATCH_ROLES
        }
        remnants = [p.name for p in directory.iterdir() if ".transition-" in p.name]
        for name in remnants:
            assert name.startswith("."), (
                f"cut {cut} left {name} where the scratch sweeps cannot see it"
            )
            assert name in computable, (
                f"cut {cut} left {name}, which is not computable from the operands"
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
    cannot use the file rebuild; it checks the destination with `lstat` and then
    renames, because plain `rename(2)` already carries the NOREPLACE property for
    directories unconditionally — ENOTEMPTY onto a populated directory, ENOTDIR onto
    a file — leaving only an empty destination directory to be refused explicitly.
    A mkdir-reservation design was drafted for this and **rejected**; see
    `_fallback_noreplace_directory`, which says why. Cross-directory by
    construction — the shape the ratified design's projection-leg inventory did not
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
    empty one through where every other shape is refused unconditionally.
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

    src_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    dst_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with pytest.raises(OSError) as raised:
            cp._fallback_noreplace(src_fd, "txn-1", dst_fd, "txn-1")
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert raised.value.errno == errno.EEXIST, label
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


def test_rebuilt_directory_noreplace_cannot_lose_a_journal_it_did_not_see(
    tmp_path: Path,
) -> None:
    """The residual window between the check and the rename, stated as a property.

    A populated journal appearing at the destination after the check is refused by
    the rename itself, with the staged copy intact — so no interleaving of this
    sequence can lose bytes, which is what NOREPLACE guards here.
    """

    staging = tmp_path / "staging"
    final = tmp_path / "final"
    staging.mkdir()
    final.mkdir()
    (staging / "txn-1").mkdir()
    (staging / "txn-1" / "manifest.json").write_bytes(b'{"staged": true}\n')
    real_rename = os.rename

    def race_then_rename(*args: object, **kwargs: object) -> None:
        (final / "txn-1").mkdir()
        (final / "txn-1" / "manifest.json").write_bytes(b'{"final": true}\n')
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    src_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    dst_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with (
            mock.patch.object(cp, "_renameat2_primitive", side_effect=_unsupported_flag_mount()),
            mock.patch.object(os, "rename", race_then_rename),
        ):
            with pytest.raises(OSError):
                cp._renameat2(src_fd, "txn-1", dst_fd, "txn-1", cp._RENAME_NOREPLACE)
    finally:
        os.close(src_fd)
        os.close(dst_fd)

    assert (final / "txn-1" / "manifest.json").read_bytes() == b'{"final": true}\n'
    assert (staging / "txn-1" / "manifest.json").read_bytes() == b'{"staged": true}\n'


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
    """Scratches left by a rebuilt rename leg, and only those.

    Deliberately narrower than `*.transition-*`, which also matches the transaction's own
    `.transition-scratch` that several tests legitimately leave behind. The assertions this
    replaces globbed `*.transition-pin.*` — a trailing-dot pattern that the switch to
    deterministic names made unmatchable, so six "no residue" assertions silently became
    no-ops. A reviewer caught that.
    """

    suffixes = tuple(f".transition-{role}" for role in cp._FALLBACK_SCRATCH_ROLES)
    return sorted(path.name for path in directory.iterdir() if path.name.endswith(suffixes))


def _replace_atomically(directory: Path, name: str, payload: bytes) -> None:
    """What a racing writer does: a new inode at the name, atomically."""
    scratch = directory / f".racer-{os.urandom(4).hex()}"
    scratch.write_bytes(payload)
    os.rename(scratch, directory / name)


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


def test_noreplace_fallback_refuses_a_replacement_racing_after_the_link(
    tmp_path: Path,
) -> None:
    """C2: on the delete leg `src` is the live projection, so the unlink is destructive."""

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with _race_after_link(tmp_path, "task.md", b"racing-writer\n"):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_noreplace(dir_fd, "task.md", dir_fd, ".task.md.scratch")
        assert caught.value.reason_code == "transition_precondition_changed"
    finally:
        os.close(dir_fd)

    assert (tmp_path / "task.md").read_bytes() == b"racing-writer\n"
    # Our half-made link is withdrawn, so the caller sees no phantom displaced entry.
    assert not (tmp_path / ".task.md.scratch").exists()
    assert os.stat(tmp_path / "task.md").st_nlink == 1


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
        # The three roles never collide with each other.
        assert len({cp._fallback_scratch_name(operand, r) for r in cp._FALLBACK_SCRATCH_ROLES}) == 3

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
    # Every scratch the leg touched is one an operator can recompute from the operands.
    computable = {
        cp._fallback_scratch_name(base, role)
        for base in ("manifest.json", "dst")
        for role in cp._FALLBACK_SCRATCH_ROLES
    }
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


def test_delete_leg_preserves_a_replacement_arriving_after_the_check(
    tmp_path: Path,
) -> None:
    """The delete leg retires `src` by MOVING it, so nothing is destroyed even in the gap
    the identity check cannot cover.

    This is the window that remains open on the exchange leg (see the test above) and is
    closed here, because retiring an entry does not require replacing an occupied name:
    `rename` relocates whatever it finds, so a replacement that landed after the check
    survives at the holding name and shows up as an identity mismatch. `unlink` would have
    destroyed it while the caller's displaced-entry comparison still matched.
    """

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    real_rename = os.rename
    fired = False

    def racing_rename(*args: object, **kwargs: object) -> None:
        # Strictly after the check: at the very syscall that retires `src`.
        nonlocal fired
        if not fired:
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
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    # Both sets of bytes live: the other writer's, and the preimage this leg displaced.
    assert b"racing-writer\n" in surviving
    assert b"live-preimage\n" in surviving
    # The preimage's ONLY name is now the scratch, because the racer's own rename removed
    # the original. Withdrawing it on this path would destroy it — the trap this test
    # exists to pin.
    assert (tmp_path / ".task.md.scratch").read_bytes() == b"live-preimage\n"
    # The refusal names the scratch now holding the other writer's bytes, and the next
    # command. It no longer enumerates the caller's own scratch, because the refusal is
    # raised by the relocation helper, which knows the names it made and not the caller's.
    assert cp._fallback_scratch_name("task.md", "holding") in str(caught.value)
    assert "recover-claim-publications" in caught.value.repair_action


def test_missing_entry_at_the_check_is_a_refusal_not_a_crash(tmp_path: Path) -> None:
    """T1: the `FileNotFoundError` branch of the identity check had no test.

    A writer that *removes* the entry rather than replacing it must produce the same
    typed refusal as a replacement, not an unhandled `FileNotFoundError` escaping the leg
    as an untyped fault the callers do not discriminate.
    """

    (tmp_path / "gone").write_bytes(b"x\n")
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        expected = os.stat("gone", dir_fd=dir_fd, follow_symlinks=False)
        os.unlink("gone", dir_fd=dir_fd)
        with pytest.raises(cp.LifecycleTransitionError) as caught:
            cp._refuse_if_displaced_entry_moved(dir_fd, "gone", expected, "subject")
        assert caught.value.reason_code == "transition_precondition_changed"
        assert "removed" in str(caught.value)
        # executive_function: the hold names the next command.
        assert "recover-claim-publications" in caught.value.repair_action
    finally:
        os.close(dir_fd)


def test_noreplace_interrupted_after_linking_loses_nothing(tmp_path: Path) -> None:
    """T1: interruption between the link and the retire, which nothing covered.

    Process termination does not run cleanup handlers, so the state a crash leaves is the
    state on disk at that instant — both names addressing one inode. Nothing may be lost,
    and the leftover must be a dotted name the scratch sweeps can see.
    """

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    real_rename = os.rename

    def crash_on_retire(*args: object, **kwargs: object) -> None:
        raise _Crash()

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", crash_on_retire):
            with pytest.raises(_Crash):
                cp._fallback_noreplace(dir_fd, "task.md", dir_fd, ".task.md.scratch")
    finally:
        os.close(dir_fd)
        os.rename = real_rename  # type: ignore[assignment]

    # The inode is reachable under both names; no bytes are gone.
    assert (tmp_path / "task.md").read_bytes() == b"live-preimage\n"
    assert (tmp_path / ".task.md.scratch").read_bytes() == b"live-preimage\n"
    assert os.stat(tmp_path / "task.md").st_ino == os.stat(tmp_path / ".task.md.scratch").st_ino


@pytest.mark.parametrize("leg", ["exchange", "noreplace"])
@pytest.mark.parametrize("cut", [1, 2, 3, 4, 5])
def test_fsync_failure_at_every_cut_loses_nothing_and_leaves_reachable_remnants(
    tmp_path: Path, leg: str, cut: int
) -> None:
    """T1, done properly: a failure at EVERY step, not only the first.

    The previous version raised on *every* `fsync`, so it always fired at the earliest one
    — before installation or retirement — and the later cuts went untested. A reviewer was
    right that this made the test weaker than its name. Now the failure is injected at the
    Nth `fsync`, which walks it through pin, move-aside, publish, retire and finalise.

    Two properties at each cut, and the second is what recovery needs:

    * **No bytes are lost.** Every generation that existed is still readable under some
      name, because each step is a move or a create-or-fail.
    * **Every remnant is reachable.** The leftover names are exactly the ones computable
      from the operands, so an operator — or the discovery work owed by the projection-lock
      task — can enumerate them without a directory sweep, which this module does not have.

    Cuts beyond a leg's fsync count simply complete; that is asserted rather than skipped,
    so a leg that silently loses an fsync shows up here.
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
        with mock.patch.object(os, "fsync", failing_fsync):
            try:
                call(dir_fd)
                completed = True
            except OSError as exc:
                assert exc.errno == errno.EIO, (leg, cut, exc)
                completed = False
    finally:
        os.close(dir_fd)

    # The cut either fired inside the leg, or the leg had fewer fsyncs than `cut`.
    assert completed == (seen < cut), (leg, cut, seen, completed)

    present = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert expected <= set(present.values()), (leg, cut, present)

    computable = {
        cp._fallback_scratch_name(base, role)
        for base in operands
        for role in cp._FALLBACK_SCRATCH_ROLES
    } | set(operands)
    unreachable = set(present) - computable
    assert not unreachable, (leg, cut, unreachable)


@pytest.mark.parametrize(
    ("leg", "required_barriers"),
    [("exchange", 5), ("noreplace", 3)],
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
    removal of durability barriers" requires. Ordering is pinned too: the last thing a leg
    does is a barrier, so a crash after the final rename cannot leave the directory entry
    unflushed.
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
    assert order[-1] == "fsync", (leg, order)

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


@pytest.mark.parametrize("role", ["pin", "holding", "spent"])
def test_exchange_refuses_when_any_scratch_destination_is_occupied(
    tmp_path: Path, role: str
) -> None:
    """A remnant may be another writer's only copy, so it is never renamed over.

    Attempt 1 detects a race and deliberately preserves a concurrent writer's ONLY copy at
    a predictable scratch name. Attempt 2 used to rename straight over it and report
    success. Every role is covered, because round 5 guarded only `pin`.
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


def test_noreplace_refuses_when_its_holding_scratch_is_occupied(tmp_path: Path) -> None:
    """The same guard on the delete leg, which had none at all."""

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    remnant = tmp_path / cp._fallback_scratch_name("task.md", "holding")
    remnant.write_bytes(b"another writer's only copy\n")

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(cp.LifecycleTransitionError) as raised:
            cp._fallback_noreplace(dir_fd, "task.md", dir_fd, ".task.md.scratch")
    finally:
        os.close(dir_fd)

    assert raised.value.reason_code == "transition_projection_scratch_exists"
    assert remnant.read_bytes() == b"another writer's only copy\n"
    assert (tmp_path / "task.md").read_bytes() == b"live-preimage\n"


def test_refill_refuses_a_source_recreated_after_retirement(tmp_path: Path) -> None:
    """The refill is create-or-fail, because both identity checks precede it.

    A writer can recreate `src` between its retirement and the refill, after every check has
    already passed. The refill used to be an unconditional `rename(pin → src)`, which
    destroyed that entry silently. Reachable with a live filename: `_atomic_install`'s
    rollback passes a journal filename as `src`.
    """

    (tmp_path / "manifest.json").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    spent = cp._fallback_scratch_name("manifest.json", "spent")
    real_rename = os.rename
    fired = False

    def recreate_src_before_refill(*args: object, **kwargs: object) -> None:
        nonlocal fired
        result = real_rename(*args, **kwargs)  # type: ignore[arg-type]
        if not fired and (tmp_path / spent).exists():
            fired = True
            (tmp_path / "manifest.json").write_bytes(b"recreated-by-another-writer\n")
        return result

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", recreate_src_before_refill):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_exchange(dir_fd, "manifest.json", dir_fd, "dst")
        assert caught.value.reason_code == "transition_precondition_changed"
    finally:
        os.close(dir_fd)

    assert fired
    # The other writer's entry stands, and the displaced entry is still reachable.
    assert (tmp_path / "manifest.json").read_bytes() == b"recreated-by-another-writer\n"
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"displaced\n" in surviving
    assert b"replacement\n" in surviving
    # executive_function: name the next command, and say what not to delete.
    assert "recover-claim-publications" in str(caught.value)
    assert "do not delete" in str(caught.value)


def test_cleanup_leaves_a_scratch_another_writer_replaced(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Cleanup is the last place this repair can lose data, and it did.

    An unconditional `unlink` of a scratch destroys whatever occupies that name, including
    an entry another writer put there while the leg ran. Identity is re-read immediately
    before each removal; a mismatch is left for the recovery sweep and logged under a
    stable, greppable code rather than raised — by cleanup time the projection has already
    succeeded, so raising would discard a verified post-state over an untidy remnant.
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    spent = cp._fallback_scratch_name(".src", "spent")
    real_link = os.link
    swapped = False

    def swap_spent_after_the_refill(*args: object, **kwargs: object) -> None:
        # The window that exercises cleanup's guard: after step 6 has verified `spent`, and
        # before cleanup re-reads its identity. Injecting earlier is a different test — step
        # 6 would catch it and refuse — and injecting at `os.unlink` is too late, because the
        # guard's `lstat` has already run by then. That is worth stating: I got it wrong the
        # first time and the test passed for the wrong reason.
        nonlocal swapped
        result = real_link(*args, **kwargs)  # type: ignore[arg-type]
        if not swapped and len(args) > 1 and str(args[1]) == ".src":
            swapped = True
            _replace_atomically(tmp_path, spent, b"someone-elses-entry\n")
        return result

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with caplog.at_level("WARNING"):
            with mock.patch.object(os, "link", swap_spent_after_the_refill):
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
    abandoned = tmp_path / f"{spent}.transition-abandoned"
    assert abandoned.read_bytes() == b"someone-elses-entry\n"
    assert not (tmp_path / spent).exists(), "the scratch name must be free for a retry"
    assert cp._SCRATCH_ABANDONED in caplog.text
    assert spent in caplog.text
    assert "recover-claim-publications" in caplog.text


def test_directory_noreplace_refuses_an_empty_destination_appearing_after_the_check(
    tmp_path: Path,
) -> None:
    """The leg every transaction runs through, at the interleaving its argument rests on.

    `_fallback_noreplace_directory` lstats the destination and then renames, arguing that
    every post-check arrival except an *empty* directory is refused by `rename` itself. Only
    the straight-line refusal was pinned. This injects the one case the argument excuses —
    an empty directory appearing after the check — and the two pass-throughs the argument
    depends on.
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

        # Pass-throughs the argument depends on: a POPULATED destination and a FILE
        # destination are refused by rename itself, so neither can be silently clobbered.
        second = staging / "txn-2"
        second.mkdir()
        (second / "manifest.json").write_bytes(b"{}\n")
        populated = final / "txn-2"
        populated.mkdir()
        (populated / "keep-me").write_bytes(b"occupied\n")
        with pytest.raises(OSError) as caught:
            cp._fallback_noreplace(src_fd, "txn-2", dst_fd, "txn-2")
        assert caught.value.errno in {errno.ENOTEMPTY, errno.EEXIST, errno.EBUSY}
        assert (populated / "keep-me").read_bytes() == b"occupied\n"

        third = staging / "txn-3"
        third.mkdir()
        (final / "txn-3").write_bytes(b"a file, not a directory\n")
        with pytest.raises(OSError) as caught:
            cp._fallback_noreplace(src_fd, "txn-3", dst_fd, "txn-3")
        assert caught.value.errno in {errno.ENOTDIR, errno.EEXIST, errno.EBUSY}
        assert (final / "txn-3").read_bytes() == b"a file, not a directory\n"
    finally:
        os.close(src_fd)
        os.close(dst_fd)


# --- the two open windows, pinned as documented limits --------------------------------
#
# Reviewers are right that these boundaries were untested: the collision tests populate a
# scratch BEFORE invocation (so they exercise only the vacancy refusal) and the cleanup test
# injects before the `lstat` (so it exercises only the identity branch). Neither touched the
# boundary where the loss actually lives.
#
# They ask for tests asserting byte PRESERVATION there. That is the closure, and it is not
# available at this layer — refusing an occupied destination needs `link`, which breaks the
# single-link invariant `_entry_state_at` enforces, and removing a directory entry has no
# compare-and-unlink form. See `_relocate_to_scratch`.
#
# So these assert what the code ACTUALLY does at those exact interleavings, labelled as the
# documented windows. Worth having for two reasons: the boundaries stop being unexamined,
# and when the concurrency is removed and the behaviour becomes preservation, these fail and
# force the update rather than rotting into false documentation. A failure here is good
# news — delete them in the change that closes the window.


def test_open_window_arrival_at_a_scratch_between_the_vacancy_check_and_the_rename(
    tmp_path: Path,
) -> None:
    """DOCUMENTED LIMIT — not a preservation guarantee. See the block comment above."""

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    holding = cp._fallback_scratch_name(".src", "holding")
    real_rename = os.rename
    fired = False

    def arrive_just_before_the_relocation(*args: object, **kwargs: object) -> None:
        # The vacancy check has passed; this is the rename it guards.
        nonlocal fired
        if not fired and len(args) > 1 and str(args[1]) == holding:
            fired = True
            (tmp_path / holding).write_bytes(b"arrived-after-the-check\n")
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", arrive_just_before_the_relocation):
            cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert fired, "the arrival must land in the guarded window for this to mean anything"
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"arrived-after-the-check\n" not in surviving, (
        "the window CLOSED — good news. Delete this test, and the caveat in "
        "NFS-EXCHANGE-FALLBACK-DESIGN-20260911.md, in the same change."
    )
    # The projection itself still completes correctly; that is what makes the loss silent.
    assert (tmp_path / "dst").read_bytes() == b"replacement\n"
    assert (tmp_path / ".src").read_bytes() == b"displaced\n"


def test_open_window_replacement_between_cleanups_identity_check_and_its_unlink(
    tmp_path: Path,
) -> None:
    """DOCUMENTED LIMIT — not a preservation guarantee. See the block comment above."""

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    spent = cp._fallback_scratch_name(".src", "spent")
    real_unlink = os.unlink
    fired = False

    def replace_just_before_the_unlink(*args: object, **kwargs: object) -> None:
        # `_retire_scratch` has already re-read identity and decided this name is ours.
        nonlocal fired
        if not fired and args and str(args[0]) == spent:
            fired = True
            _replace_atomically(tmp_path, spent, b"replaced-after-the-check\n")
        return real_unlink(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "unlink", replace_just_before_the_unlink):
            cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert fired
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"replaced-after-the-check\n" not in surviving, (
        "the window CLOSED — good news. Delete this test, and the caveat in "
        "NFS-EXCHANGE-FALLBACK-DESIGN-20260911.md, in the same change."
    )
    assert (tmp_path / "dst").read_bytes() == b"replacement\n"


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

        def refuse_to_link(*args: object, **kwargs: object) -> None:
            raise OSError(errno.EIO, os.strerror(errno.EIO), "link")

        with caplog.at_level("WARNING"):
            with mock.patch.object(os, "link", refuse_to_link):
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
    """

    target = tmp_path / "scratch"
    target.write_bytes(b"ours\n")
    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        expected = os.lstat("scratch", dir_fd=dir_fd)

        def boom(*args: object, **kwargs: object) -> None:
            raise OSError(errno.EIO, os.strerror(errno.EIO), failing)

        with caplog.at_level("WARNING"):
            with mock.patch.object(os, failing, boom):
                # Must not raise. Before the fix, both parametrisations did.
                freed = cp._retire_scratch(dir_fd, "scratch", expected, subject="probe")
    finally:
        os.close(dir_fd)

    assert freed is False
    assert target.read_bytes() == b"ours\n", "an unreadable or unremovable scratch is left"
    assert cp._SCRATCH_ABANDONED in caplog.text


def test_noreplace_holding_relocation_refuses_a_replaced_source(tmp_path: Path) -> None:
    """The delete leg's relocation boundary, which had no regression of its own.

    Coverage lived on the exchange leg only. This is the same property on the leg where
    `src` is the LIVE projection path, so a replacement there is the case that matters.
    """

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    real_rename = os.rename
    fired = False

    def replace_src_before_the_relocation(*args: object, **kwargs: object) -> None:
        nonlocal fired
        if not fired:
            fired = True
            _replace_atomically(tmp_path, "task.md", b"racing-writer\n")
        return real_rename(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "rename", replace_src_before_the_relocation):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_noreplace(dir_fd, "task.md", dir_fd, ".task.md.scratch")
        assert caught.value.reason_code == "transition_precondition_changed"
    finally:
        os.close(dir_fd)

    assert fired
    surviving = {path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert b"racing-writer\n" in surviving
    assert b"live-preimage\n" in surviving


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
    """

    (tmp_path / ".src").write_bytes(b"replacement\n")
    (tmp_path / "dst").write_bytes(b"displaced\n")
    real_unlink = os.unlink

    def refuse_to_unlink_scratches(*args: object, **kwargs: object) -> None:
        if args and ".transition-" in str(args[0]):
            raise OSError(errno.EIO, os.strerror(errno.EIO), "unlink")
        return real_unlink(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "unlink", refuse_to_unlink_scratches):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_exchange(dir_fd, ".src", dir_fd, "dst")
    finally:
        os.close(dir_fd)

    assert caught.value.reason_code == "transition_projection_recovery_required"
    # It names the scratch, says why continuing would fail, and gives the next command.
    assert "path-unsafe" in str(caught.value)
    assert "recover-claim-publications" in caught.value.repair_action
    assert any(name in str(caught.value) for name in _fallback_remnants(tmp_path))
    # The projection's own post-state still landed; this is about the leftover, not a loss.
    assert (tmp_path / "dst").read_bytes() == b"replacement\n"


def test_the_delete_leg_reports_an_unremovable_scratch_too(tmp_path: Path) -> None:
    """The same escalation on the NOREPLACE leg, which was left behind.

    The exchange leg got this in the previous round and this one did not, so an EIO here left
    `holding` as a second link to the live inode and the next readback refused it as
    path-unsafe — the same defect and the same misdirected diagnosis, one leg over. Fixing
    one instance of a shape without sweeping for the rest is the error this file keeps
    repeating, so both legs are now pinned rather than just the one that was reported.
    """

    (tmp_path / "task.md").write_bytes(b"live-preimage\n")
    real_unlink = os.unlink

    def refuse_to_unlink_scratches(*args: object, **kwargs: object) -> None:
        if args and ".transition-" in str(args[0]):
            raise OSError(errno.EIO, os.strerror(errno.EIO), "unlink")
        return real_unlink(*args, **kwargs)  # type: ignore[arg-type]

    dir_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with mock.patch.object(os, "unlink", refuse_to_unlink_scratches):
            with pytest.raises(cp.LifecycleTransitionError) as caught:
                cp._fallback_noreplace(dir_fd, "task.md", dir_fd, ".task.md.scratch")
    finally:
        os.close(dir_fd)

    assert caught.value.reason_code == "transition_projection_recovery_required"
    assert "path-unsafe" in str(caught.value)
    assert "recover-claim-publications" in caught.value.repair_action
    # Nothing lost: the displaced preimage is still reachable under the caller's scratch.
    assert (tmp_path / ".task.md.scratch").read_bytes() == b"live-preimage\n"
