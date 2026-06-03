"""Tests for shared/coord_projection.py — taxonomy, emitters, projection fold."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from shared import coord_projection as cp
from shared.coord_event_log import (
    CoordEvent,
    CoordEventLog,
    CoordWriter,
    DuplicateEventError,
    ReplayResult,
)


def _log(tmp_path: Path) -> CoordEventLog:
    return CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )


# --- deterministic event_id builders -----------------------------------------


def test_event_ids_are_deterministic_and_distinct() -> None:
    a = cp.stage_transition_event_id(
        task_id="t1", authority_case="CASE-X", from_stage="S6", to_stage="S7", timestamp="ts"
    )
    b = cp.stage_transition_event_id(
        task_id="t1", authority_case="CASE-X", from_stage="S6", to_stage="S7", timestamp="ts"
    )
    c = cp.stage_transition_event_id(
        task_id="t1", authority_case="CASE-X", from_stage="S6", to_stage="S8", timestamp="ts"
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


def test_emit_migration_annotated_noop_by_default_writes_when_injected(tmp_path: Path) -> None:
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
        _event("coord_dispatch.launch_succeeded", "task-1", {"outcome": "succeeded"}, eid="d1"),
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
