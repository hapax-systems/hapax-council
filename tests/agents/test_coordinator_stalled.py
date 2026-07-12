"""Stall observation and fail-closed claim-detachment tests.

The coordinator may observe that a lane is stale or absent. It has no standing
authority to change task status, owner, or claim artifacts from that observation.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agents.coordinator.core import (
    STALL_OUTPUT_GRACE_S,
    Coordinator,
    CoordinatorState,
    LaneState,
    Task,
    _lane_to_dict,
    _reserve_lanes_from_task_ssot,
    project_stalled,
)
from shared.coord_dispatch import (
    DispatchLaunchRequest,
    _accept_dispatch_message,
    _append_dispatch_event,
)
from shared.coord_event_log import CoordEventLog
from shared.sdlc_pressure_gate import AdmissionDecision


@contextlib.contextmanager
def _isolated(tmp: Path) -> Iterator[None]:
    for sub in ("tasks", "cache", "pid", "shm"):
        (tmp / sub).mkdir(exist_ok=True)
    with (
        patch("agents.coordinator.core.TASKS_DIR", tmp / "tasks"),
        patch("agents.coordinator.core.CACHE_DIR", tmp / "cache"),
        patch("agents.coordinator.core.PID_DIR", tmp / "pid"),
        patch("agents.coordinator.core.SHM_DIR", tmp / "shm"),
        patch("agents.coordinator.core.SHM_FILE", tmp / "shm" / "state.json"),
    ):
        yield


def _lane(
    *, role: str = "ut_lane", claim: str | None = "ut-task-20260602", output_age_s: float = 0.0
) -> LaneState:
    return LaneState(
        role=role,
        platform="claude",
        alive=True,
        claimed_task=claim,
        idle=False,
        output_age_s=output_age_s,
    )


def _write_note(
    tasks_dir: Path, task_id: str, *, status: str = "in_progress", assigned: str = "ut_lane"
) -> Path:
    path = tasks_dir / f"{task_id}.md"
    path.write_text(
        f"---\ntask_id: {task_id}\nstatus: {status}\nassigned_to: {assigned}\n---\nbody\n",
        encoding="utf-8",
    )
    return path


def _task(path: Path, *, status: str = "claimed", assigned_to: str = "ut_lane") -> Task:
    return Task(
        task_id=path.stem,
        title="test",
        status=status,
        assigned_to=assigned_to,
        wsjf=5.0,
        effort_class="standard",
        platform_suitability=("claude",),
        quality_floor="deterministic_ok",
        path=path,
        claimed_at=0.0,
        priority="p0",
        source_sha256="a" * 64,
    )


def _set_launcher_alive(pid_dir: Path, role: str) -> None:
    (pid_dir / f"{role}.launcher.pid").write_text(str(os.getpid()), encoding="utf-8")


def test_project_stalled_dead_launcher_is_observation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            lane = _lane()
            assert project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task}))


def test_project_stalled_stale_output_is_observation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            _set_launcher_alive(tmp / "pid", "ut_lane")
            lane = _lane(output_age_s=STALL_OUTPUT_GRACE_S + 1.0)
            assert project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task}))


def test_project_stalled_fresh_working_is_false() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            _set_launcher_alive(tmp / "pid", "ut_lane")
            lane = _lane(output_age_s=STALL_OUTPUT_GRACE_S - 1.0)
            assert not project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task}))


def test_pidfile_free_live_launcher_stays_busy() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with (
            _isolated(tmp),
            patch(
                "agents.coordinator.core._live_headless_launcher",
                return_value=(os.getpid(), "ut-task-20260602"),
            ),
        ):
            lane = _lane(output_age_s=float("inf"))
            lane.pid = os.getpid()
            lane.pid_source = "proc"
            assert not project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task}))


def test_no_claim_or_terminal_claim_is_not_stalled() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            assert not project_stalled(_lane(claim=None), non_terminal_task_ids=frozenset())
            lane = _lane(claim="finished-task")
            assert not project_stalled(lane, non_terminal_task_ids=frozenset({"other"}))


def test_direct_stalled_reoffer_refuses_and_preserves_all_bytes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            note = _write_note(tmp / "tasks", "ut-task-20260602")
            claim = tmp / "cache" / "cc-active-task-ut_lane"
            claim.write_text("ut-task-20260602\n", encoding="utf-8")
            note_before = note.read_bytes()
            claim_before = claim.read_bytes()

            assert not Coordinator()._reoffer_stalled(_lane(output_age_s=86_400.0))

            assert note.read_bytes() == note_before
            assert claim.read_bytes() == claim_before


def test_direct_orphan_reoffer_refuses_and_preserves_all_bytes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            note = _write_note(tmp / "tasks", "ut-task-20260602", status="claimed")
            task = _task(note)
            before = note.read_bytes()

            assert Coordinator()._reoffer_orphaned_claims([task], {}, now_wall=10_000.0) == 0
            assert not Coordinator()._reoffer_orphaned_claim(task, {})
            assert note.read_bytes() == before


def test_direct_escalation_refuses_and_does_not_notify() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            note = _write_note(tmp / "tasks", "ut-task-20260602", status="claimed")
            before = note.read_bytes()
            with patch("agents.coordinator.core.send_notification") as notify:
                assert not Coordinator()._escalate_stalled(
                    _lane(), note.stem, note, note.read_text(encoding="utf-8")
                )
            assert note.read_bytes() == before
            notify.assert_not_called()


def _run_tick(lanes: dict[str, LaneState], tasks: list[Task], admission: str) -> CoordinatorState:
    captured: list[CoordinatorState] = []
    with (
        patch.object(Coordinator, "_scan_tasks", return_value=tasks),
        patch.object(Coordinator, "_check_lanes", return_value=lanes),
        patch.object(Coordinator, "_dispatch", return_value=(True, "")),
        patch.object(
            Coordinator, "_write_state", side_effect=lambda state, **_: captured.append(state)
        ),
        patch(
            "agents.coordinator.core.admission_state",
            return_value=AdmissionDecision(state=admission),
        ),
    ):
        Coordinator().tick()
    return captured[0]


def test_tick_never_invokes_detach_for_stalled_lane() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            lane = _lane(output_age_s=86_400.0)
            task = _task(_write_note(tmp / "tasks", lane.claimed_task or "missing"))
            with (
                patch.object(Coordinator, "_reoffer_stalled") as stalled,
                patch.object(Coordinator, "_reoffer_orphaned_claims") as orphaned,
            ):
                state = _run_tick({lane.role: lane}, [task], "open")

            stalled.assert_not_called()
            orphaned.assert_not_called()
            assert state.lanes_stalled == 1
            assert state.reoffers_this_tick == 0


def test_task_ssot_reserves_lane_when_claim_and_relay_telemetry_are_absent() -> None:
    lane = LaneState(
        role="ut_lane",
        platform="claude",
        alive=True,
        idle=True,
        claimed_task=None,
    )
    task = _task(Path("/tmp/authoritative-task.md"), assigned_to="ut_lane")

    _reserve_lanes_from_task_ssot({lane.role: lane}, [task])

    assert lane.claimed_task == task.task_id
    assert lane.task_ssot_claims == (task.task_id,)
    assert lane.idle is False
    assert lane.dispatch_ready is False
    assert lane.dispatch_blocked_reason == f"lane_reserved_by_task_ssot:{task.task_id}"


def test_platform_qualified_task_owner_reserves_bare_lane() -> None:
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)
    task = _task(Path("/tmp/qualified.md"), assigned_to="claude/ut_lane")

    _reserve_lanes_from_task_ssot({lane.role: lane}, [task])

    assert lane.claimed_task == task.task_id
    assert lane.dispatch_ready is False
    assert lane.dispatch_blocked_reason == f"lane_reserved_by_task_ssot:{task.task_id}"


def test_unmappable_qualified_owner_holds_all_lanes() -> None:
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)
    task = _task(Path("/tmp/unmappable.md"), assigned_to="unknown/ut_lane")

    _reserve_lanes_from_task_ssot({lane.role: lane}, [task])

    assert lane.dispatch_ready is False
    assert lane.dispatch_blocked_reason == f"task_ssot_owner_unmappable:{task.task_id}"


def test_tick_does_not_dispatch_over_task_ssot_reservation() -> None:
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)
    owned = _task(Path("/tmp/owned.md"), assigned_to="ut_lane")
    offered = _task(Path("/tmp/offered.md"), status="offered", assigned_to="unassigned")
    captured: list[CoordinatorState] = []

    with (
        patch.object(Coordinator, "_scan_tasks", return_value=[owned, offered]),
        patch.object(Coordinator, "_check_lanes", return_value={lane.role: lane}),
        patch.object(Coordinator, "_dispatch") as dispatch,
        patch.object(
            Coordinator, "_write_state", side_effect=lambda state, **_: captured.append(state)
        ),
        patch(
            "agents.coordinator.core.admission_state",
            return_value=AdmissionDecision(state="open"),
        ),
    ):
        Coordinator().tick()

    dispatch.assert_not_called()
    assert captured[0].lanes_idle == 0
    assert captured[0].lanes[lane.role]["task_ssot_claims"] == [owned.task_id]


def test_malformed_task_ssot_holds_coordinator_admission_fleet_wide() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            (tmp / "tasks" / "malformed-owned.md").write_text(
                "---\nstatus: [\nassigned_to: ut_lane\n---\n",
                encoding="utf-8",
            )
            _write_note(tmp / "tasks", "offered", status="offered", assigned="unassigned")
            lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)
            captured: list[CoordinatorState] = []
            coordinator = Coordinator()

            with (
                patch.object(Coordinator, "_check_lanes", return_value={lane.role: lane}),
                patch.object(Coordinator, "_dispatch") as dispatch,
                patch.object(
                    Coordinator,
                    "_write_state",
                    side_effect=lambda state, **_: captured.append(state),
                ),
                patch(
                    "agents.coordinator.core.admission_state",
                    return_value=AdmissionDecision(state="open"),
                ),
            ):
                coordinator.tick()

            dispatch.assert_not_called()
            assert captured[0].task_ssot_complete is False
            assert captured[0].lanes_idle == 0
            assert captured[0].lanes[lane.role]["dispatch_blocked_reason"] == (
                "task_ssot_incomplete"
            )


def test_non_scalar_ownership_fields_make_task_ssot_incomplete() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            (tmp / "tasks" / "malformed-shape.md").write_text(
                "---\ntask_id: malformed-shape\nstatus: [claimed]\nassigned_to: [ut_lane]\n---\n",
                encoding="utf-8",
            )
            coordinator = Coordinator()

            assert coordinator._scan_tasks() == []
            assert coordinator._task_ssot_complete is False


def test_duplicate_ownership_fields_make_task_ssot_incomplete() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            (tmp / "tasks" / "duplicate-owner.md").write_text(
                "---\ntask_id: duplicate-owner\nstatus: claimed\n"
                "assigned_to: ut_lane\nassigned_to: unassigned\n---\n",
                encoding="utf-8",
            )
            coordinator = Coordinator()

            assert coordinator._scan_tasks() == []
            assert coordinator._task_ssot_complete is False


def test_missing_assigned_to_field_makes_task_ssot_incomplete() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            (tmp / "tasks" / "missing-owner.md").write_text(
                "---\ntask_id: missing-owner\nstatus: offered\n---\n",
                encoding="utf-8",
            )
            coordinator = Coordinator()

            assert coordinator._scan_tasks() == []
            assert coordinator._task_ssot_complete is False


def test_explicit_null_assigned_to_is_canonical_unassigned() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            (tmp / "tasks" / "null-owner.md").write_text(
                "---\ntask_id: null-owner\nstatus: offered\nassigned_to: null\n---\n",
                encoding="utf-8",
            )
            coordinator = Coordinator()

            tasks = coordinator._scan_tasks()
            assert [task.assigned_to for task in tasks] == ["unassigned"]
            assert coordinator._task_ssot_complete is True


def test_missing_canonical_identity_fields_make_task_ssot_incomplete() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            (tmp / "tasks" / "missing-task-id.md").write_text(
                "---\nstatus: offered\nassigned_to: unassigned\n---\n",
                encoding="utf-8",
            )
            coordinator = Coordinator()

            assert coordinator._scan_tasks() == []
            assert coordinator._task_ssot_complete is False


def test_dispatch_revalidates_task_ssot_immediately_before_first_effect(
    tmp_path: Path,
) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    coordinator = Coordinator()
    offered = _task(Path("/tmp/offered.md"), status="offered", assigned_to="unassigned")
    newly_owned = _task(Path("/tmp/newly-owned.md"), assigned_to="ut_lane")
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch.object(
            coordinator,
            "_read_task_snapshot",
            return_value=([offered, newly_owned], True),
        ),
        patch("agents.coordinator.core._prepare_dispatch_message") as prepare,
        patch("agents.coordinator.core.subprocess.run") as run,
    ):
        accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is False
    assert reason == f"lane_reserved_by_task_ssot:{newly_owned.task_id}"
    prepare.assert_not_called()
    run.assert_not_called()


def test_dispatch_holds_when_mutation_moment_task_snapshot_is_incomplete(
    tmp_path: Path,
) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    coordinator = Coordinator()
    offered = _task(Path("/tmp/offered.md"), status="offered", assigned_to="unassigned")
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch.object(coordinator, "_read_task_snapshot", return_value=([], False)),
        patch("agents.coordinator.core._prepare_dispatch_message") as prepare,
        patch("agents.coordinator.core.subprocess.run") as run,
    ):
        accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is False
    assert reason == "task_ssot_incomplete"
    prepare.assert_not_called()
    run.assert_not_called()


def test_dispatch_refuses_target_claimed_by_a_different_lane_after_initial_scan(
    tmp_path: Path,
) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    coordinator = Coordinator()
    offered = _task(Path("/tmp/target.md"), status="offered", assigned_to="unassigned")
    claimed_elsewhere = _task(Path("/tmp/target.md"), status="claimed", assigned_to="beta")
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch.object(
            coordinator,
            "_read_task_snapshot",
            return_value=([claimed_elsewhere], True),
        ),
        patch("agents.coordinator.core._prepare_dispatch_message") as prepare,
        patch("agents.coordinator.core.subprocess.run") as run,
    ):
        accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is False
    assert reason == "task_not_dispatchable_from_fresh_ssot:status=claimed:assigned_to=beta"
    prepare.assert_not_called()
    run.assert_not_called()


def test_dispatch_revalidates_destination_after_mq_preparation(tmp_path: Path) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    coordinator = Coordinator()
    offered = _task(Path("/tmp/target.md"), status="offered", assigned_to="unassigned")
    destination_claim = _task(Path("/tmp/new-claim.md"), assigned_to="ut_lane")
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch.object(
            coordinator,
            "_read_task_snapshot",
            side_effect=[([offered], True), ([offered, destination_claim], True)],
        ),
        patch(
            "agents.coordinator.core._prepare_dispatch_message", return_value="mq-test"
        ) as prepare,
        patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
        patch(
            "agents.coordinator.core._abort_prepared_dispatch_message",
            side_effect=lambda _, __, reason: reason,
        ) as abort,
        patch("agents.coordinator.core.subprocess.run") as run,
    ):
        accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is False
    assert reason == f"lane_reserved_by_task_ssot:{destination_claim.task_id}"
    prepare.assert_called_once()
    abort.assert_called_once()
    run.assert_not_called()


def test_dispatch_keeps_prepared_mq_invisible_when_post_prepare_validation_holds(
    tmp_path: Path,
) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    db_path = tmp_path / "relay" / "messages.db"
    coordinator = Coordinator()
    offered = replace(
        _task(Path("/tmp/target.md"), status="offered", assigned_to="unassigned"),
        authority_case="CASE-P0-TEST",
        authority_item="target",
    )
    destination_claim = _task(Path("/tmp/new-claim.md"), assigned_to="ut_lane")
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch.object(
            coordinator,
            "_read_task_snapshot",
            side_effect=[([offered], True), ([offered, destination_claim], True)],
        ),
        patch.dict(os.environ, {"HAPAX_RELAY_MQ_DB": str(db_path)}),
        patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
        patch("agents.coordinator.core.subprocess.run") as run,
    ):
        accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is False
    assert reason == f"lane_reserved_by_task_ssot:{destination_claim.task_id}"
    run.assert_not_called()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT state, reason FROM recipients").fetchone() == (
            "deferred",
            f"coordinator_prepare_aborted:lane_reserved_by_task_ssot:{destination_claim.task_id}",
        )


def test_dispatch_revokes_prepared_mq_when_methodology_spawn_fails(tmp_path: Path) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    db_path = tmp_path / "relay" / "messages.db"
    coordinator = Coordinator()
    offered = replace(
        _task(Path("/tmp/target.md"), status="offered", assigned_to="unassigned"),
        authority_case="CASE-P0-TEST",
        authority_item="target",
    )
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch.object(coordinator, "_read_task_snapshot", return_value=([offered], True)),
        patch.dict(os.environ, {"HAPAX_RELAY_MQ_DB": str(db_path)}),
        patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
        patch("agents.coordinator.core.subprocess.run", side_effect=OSError("spawn failed")),
    ):
        accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is False
    assert reason == "OSError: spawn failed"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT state, reason FROM recipients").fetchone() == (
            "deferred",
            "coordinator_prepare_aborted:OSError: spawn failed",
        )


def test_dispatch_timeout_with_pickup_finalizes_mq_and_terminal_event(tmp_path: Path) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    db_path = tmp_path / "relay" / "messages.db"
    coord_dir = tmp_path / "coord"
    coordinator = Coordinator()
    offered = replace(
        _task(Path("/tmp/target.md"), status="offered", assigned_to="unassigned"),
        authority_case="CASE-P0-TEST",
        authority_item="target",
        parent_spec="/tmp/spec.md",
    )
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)

    def accept_then_timeout(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        message_id = cmd[cmd.index("--mq-message-id") + 1]
        with sqlite3.connect(db_path) as conn:
            payload = json.loads(
                conn.execute(
                    "SELECT payload FROM messages WHERE message_id = ?",
                    (message_id,),
                ).fetchone()[0]
            )
        request = DispatchLaunchRequest(
            task_id=offered.task_id,
            lane=lane.role,
            platform=lane.platform,
            mode="headless",
            profile="full",
            authority_case=offered.authority_case or "",
            authority_item=offered.authority_item,
            parent_spec=offered.parent_spec,
            message_id=message_id,
            mq_db_path=db_path,
            event_log=CoordEventLog(
                db_path=coord_dir / "ledger.db",
                jsonl_path=coord_dir / "ledger.jsonl",
                spool_dir=coord_dir / "spool",
            ),
            binding_hash=payload["dispatch_binding"]["binding_hash"],
        )
        key = request.effective_idempotency_key
        _accept_dispatch_message(request, idempotency_key=key)
        _append_dispatch_event(
            request,
            idempotency_key=key,
            outcome="started",
            returncode=None,
        )
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch.object(coordinator, "_read_task_snapshot", return_value=([offered], True)),
        patch.dict(
            os.environ,
            {
                "HAPAX_RELAY_MQ_DB": str(db_path),
                "HAPAX_COORD_LEDGER_DB": str(coord_dir / "ledger.db"),
                "HAPAX_COORD_JSONL_MIRROR": str(coord_dir / "ledger.jsonl"),
                "HAPAX_COORD_SPOOL_DIR": str(coord_dir / "spool"),
            },
        ),
        patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
        patch("agents.coordinator.core.subprocess.run", side_effect=accept_then_timeout),
        patch("agents.coordinator.core._dispatch_landed", return_value=True),
        patch("agents.coordinator.core.DISPATCH_TIMEOUT_LANDING_GRACE_S", 0.0),
    ):
        accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is True
    assert reason == ""
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT state FROM recipients").fetchone() == ("processed",)
    event_types = [
        event.event_type
        for event in CoordEventLog(
            db_path=coord_dir / "ledger.db",
            jsonl_path=coord_dir / "ledger.jsonl",
            spool_dir=coord_dir / "spool",
        )
        .replay()
        .events
    ]
    assert event_types == [
        "coord_dispatch.launch_started",
        "coord_dispatch.launch_succeeded",
    ]


def test_timeout_without_pickup_holds_one_accepted_dispatch_without_retry(
    tmp_path: Path,
) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    db_path = tmp_path / "relay" / "messages.db"
    coord_dir = tmp_path / "coord"
    cache_dir = tmp_path / "cache"
    relay_dir = tmp_path / "relay-state"
    cache_dir.mkdir()
    relay_dir.mkdir()
    coordinator = Coordinator()
    offered = replace(
        _task(Path("/tmp/target.md"), status="offered", assigned_to="unassigned"),
        authority_case="CASE-P0-TEST",
        authority_item="target",
        parent_spec="/tmp/spec.md",
    )
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)
    calls = 0

    def accept_then_timeout(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        message_id = cmd[cmd.index("--mq-message-id") + 1]
        with sqlite3.connect(db_path) as conn:
            payload = json.loads(
                conn.execute(
                    "SELECT payload FROM messages WHERE message_id = ?",
                    (message_id,),
                ).fetchone()[0]
            )
        request = DispatchLaunchRequest(
            task_id=offered.task_id,
            lane=lane.role,
            platform=lane.platform,
            mode="headless",
            profile="full",
            authority_case=offered.authority_case or "",
            authority_item=offered.authority_item,
            parent_spec=offered.parent_spec,
            message_id=message_id,
            mq_db_path=db_path,
            event_log=CoordEventLog(
                db_path=coord_dir / "ledger.db",
                jsonl_path=coord_dir / "ledger.jsonl",
                spool_dir=coord_dir / "spool",
            ),
            binding_hash=payload["dispatch_binding"]["binding_hash"],
        )
        key = request.effective_idempotency_key
        _accept_dispatch_message(request, idempotency_key=key)
        _append_dispatch_event(
            request,
            idempotency_key=key,
            outcome="started",
            returncode=None,
        )
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch.object(coordinator, "_read_task_snapshot", return_value=([offered], True)),
        patch.dict(
            os.environ,
            {
                "HAPAX_RELAY_MQ_DB": str(db_path),
                "HAPAX_COORD_LEDGER_DB": str(coord_dir / "ledger.db"),
                "HAPAX_COORD_JSONL_MIRROR": str(coord_dir / "ledger.jsonl"),
                "HAPAX_COORD_SPOOL_DIR": str(coord_dir / "spool"),
            },
        ),
        patch("agents.coordinator.core.CACHE_DIR", cache_dir),
        patch("agents.coordinator.core.RELAY_DIR", relay_dir),
        patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
        patch("agents.coordinator.core.subprocess.run", side_effect=accept_then_timeout),
        patch("agents.coordinator.core._dispatch_landed", return_value=False),
        patch("agents.coordinator.core.DISPATCH_TIMEOUT_LANDING_GRACE_S", 0.0),
    ):
        first = coordinator._dispatch(offered, lane)
        second = coordinator._dispatch(offered, lane)

    assert first[0] is False
    assert first[1].startswith("dispatch_in_flight:")
    assert second[0] is False
    assert second[1].startswith("dispatch_in_flight:")
    assert calls == 1
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert conn.execute("SELECT state FROM recipients").fetchone()[0] == "accepted"


def test_dispatch_rechecks_lane_projection_after_mq_preparation(tmp_path: Path) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    coordinator = Coordinator()
    offered = _task(Path("/tmp/target.md"), status="offered", assigned_to="unassigned")
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch.object(coordinator, "_read_task_snapshot", return_value=([offered], True)),
        patch("agents.coordinator.core._prepare_dispatch_message", return_value="mq-test"),
        patch(
            "agents.coordinator.core._refresh_dispatch_lane",
            return_value=LaneState(
                role="ut_lane",
                platform="claude",
                alive=False,
                idle=True,
                dispatch_ready=False,
            ),
        ),
        patch(
            "agents.coordinator.core._abort_prepared_dispatch_message",
            side_effect=lambda _, __, reason: reason,
        ) as abort,
        patch("agents.coordinator.core.subprocess.run") as run,
    ):
        accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is False
    assert reason == "lane_projection_changed:alive=false"
    abort.assert_called_once()
    run.assert_not_called()


def test_dispatch_rechecks_claim_cache_after_mq_preparation(tmp_path: Path) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    offered = _task(Path("/tmp/target.md"), status="offered", assigned_to="unassigned")
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)

    with _isolated(tmp_path):
        coordinator = Coordinator()

        def prepare_message(_task: Task, _lane: LaneState) -> str:
            (tmp_path / "cache" / "cc-active-task-ut_lane").write_text(
                "arrived-during-mq\n",
                encoding="utf-8",
            )
            return "mq-test"

        with (
            patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
            patch.object(
                coordinator,
                "_read_task_snapshot",
                return_value=([offered], True),
            ) as read_snapshot,
            patch("agents.coordinator.core._prepare_dispatch_message", side_effect=prepare_message),
            patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
            patch(
                "agents.coordinator.core._abort_prepared_dispatch_message",
                side_effect=lambda _, __, reason: reason,
            ) as abort,
            patch("agents.coordinator.core.subprocess.run") as run,
        ):
            accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is False
    assert reason == "lane_claim_cache_present:arrived-during-mq"
    assert read_snapshot.call_count == 1
    abort.assert_called_once()
    run.assert_not_called()


def test_dispatch_rechecks_relay_ownership_after_mq_preparation(tmp_path: Path) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    relay_dir = tmp_path / "relay"
    relay_dir.mkdir()
    offered = _task(Path("/tmp/target.md"), status="offered", assigned_to="unassigned")
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)
    coordinator = Coordinator()

    def prepare_message(_task: Task, _lane: LaneState) -> str:
        (relay_dir / "ut_lane-status.yaml").write_text(
            "status: active\ncurrent_claim: arrived-during-mq\n",
            encoding="utf-8",
        )
        return "mq-test"

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch("agents.coordinator.core.RELAY_DIR", relay_dir),
        patch.object(
            coordinator,
            "_read_task_snapshot",
            return_value=([offered], True),
        ) as read_snapshot,
        patch("agents.coordinator.core._prepare_dispatch_message", side_effect=prepare_message),
        patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
        patch(
            "agents.coordinator.core._abort_prepared_dispatch_message",
            side_effect=lambda _, __, reason: reason,
        ) as abort,
        patch("agents.coordinator.core.subprocess.run") as run,
    ):
        accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is False
    assert reason == "lane_relay_claim_present:arrived-during-mq"
    assert read_snapshot.call_count == 1
    abort.assert_called_once()
    run.assert_not_called()


def test_dispatch_rejects_selected_note_body_drift_after_mq_preparation(
    tmp_path: Path,
) -> None:
    dispatcher = tmp_path / "hapax-methodology-dispatch"
    dispatcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)
    coordinator = Coordinator()
    offered = replace(
        _task(Path("/tmp/target.md"), status="offered", assigned_to="unassigned"),
        source_sha256="before",
    )
    changed = replace(offered, source_sha256="after")
    lane = LaneState(role="ut_lane", platform="claude", alive=True, idle=True)

    with (
        patch("agents.coordinator.core.METHODOLOGY_DISPATCHER", dispatcher),
        patch.object(
            coordinator,
            "_read_task_snapshot",
            side_effect=[([offered], True), ([changed], True)],
        ),
        patch("agents.coordinator.core._prepare_dispatch_message", return_value="mq-test"),
        patch("agents.coordinator.core._refresh_dispatch_lane", return_value=lane),
        patch(
            "agents.coordinator.core._abort_prepared_dispatch_message",
            side_effect=lambda _, __, reason: reason,
        ) as abort,
        patch("agents.coordinator.core.subprocess.run") as run,
    ):
        accepted, reason = coordinator._dispatch(offered, lane)

    assert accepted is False
    assert reason == "task_ssot_changed_during_mq_prepare"
    abort.assert_called_once()
    run.assert_not_called()


def test_state_declares_claim_detach_hold_policy() -> None:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        with _isolated(tmp):
            Coordinator()._write_state(CoordinatorState())
            payload = json.loads((tmp / "shm" / "state.json").read_text(encoding="utf-8"))
            assert payload["claim_detach_policy"] == "hold_requires_governed_effect_authority"
            assert payload["task_ssot_complete"] is True


def test_lane_to_dict_exposes_stalled_and_output_age() -> None:
    out = _lane_to_dict(LaneState(role="ut_lane", stalled=True, output_age_s=42.0))
    assert out["stalled"] is True
    assert out["output_age_s"] == 42.0
    assert _lane_to_dict(LaneState(role="x"))["output_age_s"] is None


def test_coordinator_never_uses_process_group_kill() -> None:
    import agents.coordinator.core as core

    assert "killpg(" not in Path(core.__file__).read_text(encoding="utf-8")
