"""Tests for shared/coord_projection.py — taxonomy, emitters, projection fold."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import stat
import subprocess
import sys
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
