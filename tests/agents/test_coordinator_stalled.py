"""Gate-0A tests for stalled/refusal support with no recovery effects."""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.coordinator.core import (
    STALL_OUTPUT_GRACE_S,
    Coordinator,
    CoordinatorState,
    DispatchDisposition,
    LaneState,
    MethodologyDispatchResult,
    Task,
    _lane_to_dict,
    project_stalled,
)
from agents.coordinator.refusal_ledger import (
    SUPPORT_EFFECT_STATE,
    SUPPORT_HOLD_REASON,
    DispatchRefusalLedger,
)
from shared.sdlc_pressure_gate import AdmissionDecision


@contextlib.contextmanager
def _isolated(tmp: Path) -> Iterator[None]:
    for sub in ("tasks", "cache", "pid"):
        (tmp / sub).mkdir(exist_ok=True)
    with (
        patch("agents.coordinator.core.TASKS_DIR", tmp / "tasks"),
        patch("agents.coordinator.core.CACHE_DIR", tmp / "cache"),
        patch("agents.coordinator.core.PID_DIR", tmp / "pid"),
        patch("agents.coordinator.core.REOFFER_LEDGER", tmp / "ledger.jsonl"),
    ):
        yield


def _lane(
    *, role: str = "ut_lane", claim: str | None = "ut-task-20260602", output_age_s: float = 0.0
) -> LaneState:
    return LaneState(
        role=role,
        session="",
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
        f"---\ntask_id: {task_id}\nstatus: {status}\nassigned_to: {assigned}\nwsjf: 5\n---\nbody\n",
        encoding="utf-8",
    )
    return path


def _set_launcher_alive(pid_dir: Path, role: str) -> None:
    (pid_dir / f"{role}.launcher.pid").write_text(str(os.getpid()), encoding="utf-8")


def _task(task_id: str, status: str = "claimed") -> Task:
    return Task(
        task_id=task_id,
        title="x",
        status=status,
        assigned_to="ut_lane",
        wsjf=5.0,
        effort_class="standard",
        platform_suitability=("claude",),
        quality_floor="deterministic_ok",
        path=Path(f"/tmp/{task_id}.md"),
    )


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


# -- stalled is an observation only ------------------------------------------------


def test_project_stalled_dead_launcher_is_support_signal(tmp_path: Path) -> None:
    with _isolated(tmp_path):
        lane = _lane(output_age_s=0.0)
        assert project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task})) is True


def test_project_stalled_stale_output_is_support_signal(tmp_path: Path) -> None:
    with _isolated(tmp_path):
        _set_launcher_alive(tmp_path / "pid", "ut_lane")
        lane = _lane(output_age_s=STALL_OUTPUT_GRACE_S + 1.0)
        assert project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task})) is True


def test_project_stalled_fresh_working_is_false(tmp_path: Path) -> None:
    with _isolated(tmp_path):
        _set_launcher_alive(tmp_path / "pid", "ut_lane")
        lane = _lane(output_age_s=STALL_OUTPUT_GRACE_S - 1.0)
        assert project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task})) is False


def test_project_stalled_live_headless_launcher_is_false(tmp_path: Path) -> None:
    with (
        _isolated(tmp_path),
        patch(
            "agents.coordinator.core._live_headless_launcher",
            return_value=(os.getpid(), "ut-task-20260602"),
        ),
    ):
        lane = _lane(output_age_s=float("inf"))
        lane.pid = os.getpid()
        lane.pid_source = "proc"
        assert project_stalled(lane, non_terminal_task_ids=frozenset({lane.claimed_task})) is False


def test_project_stalled_no_claim_or_terminal_claim_is_false(tmp_path: Path) -> None:
    with _isolated(tmp_path):
        assert project_stalled(_lane(claim=None), non_terminal_task_ids=frozenset()) is False
        lane = _lane(claim="finished-task")
        assert project_stalled(lane, non_terminal_task_ids=frozenset({"other"})) is False


# -- every pre-admission recovery path is held before IO ---------------------------


def test_reoffer_holds_without_rewriting_task_or_emitting_ledger(tmp_path: Path) -> None:
    with _isolated(tmp_path):
        note = _write_note(tmp_path / "tasks", "ut-task-20260602")
        before = note.read_bytes()

        assert Coordinator()._reoffer_stalled(_lane(output_age_s=99999.0)) is False

        assert note.read_bytes() == before
        assert _records(tmp_path / "ledger.jsonl") == []


def test_reoffer_holds_without_clearing_claim_signal(tmp_path: Path) -> None:
    with _isolated(tmp_path):
        _write_note(tmp_path / "tasks", "ut-task-20260602")
        signal = tmp_path / "cache" / "cc-active-task-ut_lane"
        signal.write_text("ut-task-20260602", encoding="utf-8")

        assert Coordinator()._reoffer_stalled(_lane()) is False

        assert signal.read_text(encoding="utf-8") == "ut-task-20260602"


def test_reoffer_holds_on_ambiguous_match_without_ledger_write(tmp_path: Path) -> None:
    with _isolated(tmp_path):
        tasks = tmp_path / "tasks"
        first = _write_note(tasks, "reform-clog-g-20260602")
        second = _write_note(tasks, "reform-clog-d-20260602")
        first_before, second_before = first.read_bytes(), second.read_bytes()

        assert Coordinator()._reoffer_stalled(_lane(claim="reform-clog")) is False

        assert first.read_bytes() == first_before
        assert second.read_bytes() == second_before
        assert _records(tmp_path / "ledger.jsonl") == []


def test_reoffer_cap_cannot_block_task_or_notify(tmp_path: Path) -> None:
    import agents.coordinator.core as core

    with _isolated(tmp_path):
        note = _write_note(tmp_path / "tasks", "ut-task-20260602")
        before = note.read_bytes()
        coordinator = Coordinator()
        coordinator._reoffer_counts["ut-task-20260602"] = 10**9

        assert coordinator._reoffer_stalled(_lane()) is False

        assert note.read_bytes() == before
        assert not hasattr(core, "send_notification")
        assert _records(tmp_path / "ledger.jsonl") == []


def _run_tick(lanes: dict[str, LaneState], tasks: list[Task], admission: str) -> CoordinatorState:
    coordinator = Coordinator()
    captured: list[CoordinatorState] = []
    with (
        patch.object(Coordinator, "_scan_tasks", return_value=tasks),
        patch.object(Coordinator, "_check_lanes", return_value=lanes),
        patch.object(
            Coordinator,
            "_write_state",
            side_effect=lambda state, **_: captured.append(state),
        ),
        patch(
            "agents.coordinator.core.observe_admission_state",
            return_value=AdmissionDecision(state=admission),
        ),
    ):
        coordinator.tick()
    return captured[0]


@pytest.mark.parametrize("admission", ["open", "paced", "closed"])
def test_tick_projects_stalled_but_never_reoffers_or_dispatches(
    tmp_path: Path, admission: str
) -> None:
    with _isolated(tmp_path):
        note = _write_note(tmp_path / "tasks", "ut-task-20260602")
        before = note.read_bytes()
        state = _run_tick(
            {"ut_lane": _lane(output_age_s=99999.0)},
            [_task("ut-task-20260602")],
            admission,
        )

        assert state.lanes_stalled == 1
        assert state.reoffers_this_tick == 0
        assert state.dispatches_this_tick == 0
        assert note.read_bytes() == before
        assert _records(tmp_path / "ledger.jsonl") == []


def test_blocked_and_pr_open_claims_are_not_stalled_recovery_candidates(tmp_path: Path) -> None:
    with _isolated(tmp_path):
        lanes = {
            "ut_blocked": _lane(role="ut_blocked", claim="blocked", output_age_s=99999.0),
            "ut_pr": _lane(role="ut_pr", claim="pr", output_age_s=99999.0),
        }
        state = _run_tick(lanes, [_task("blocked", "blocked"), _task("pr", "pr_open")], "open")
        assert state.lanes_stalled == 0
        assert state.reoffers_this_tick == 0


def test_tick_carries_pure_candidate_as_hold_without_materializing_dispatch(tmp_path: Path) -> None:
    coordinator = Coordinator()
    lane = _lane(claim=None)
    lane.idle = True
    task = _task("candidate", "offered")
    captured: list[CoordinatorState] = []
    held = MethodologyDispatchResult(
        DispatchDisposition.HELD_CANDIDATE,
        "methodology_dispatch_carrier_held_not_admitted",
    )
    with (
        _isolated(tmp_path),
        patch.object(Coordinator, "_scan_tasks", return_value=[task]),
        patch.object(Coordinator, "_check_lanes", return_value={"ut_lane": lane}),
        patch.object(coordinator, "_dispatch", return_value=held) as dispatch,
        patch.object(
            Coordinator,
            "_write_state",
            side_effect=lambda state, **_: captured.append(state),
        ),
        patch(
            "agents.coordinator.core.observe_admission_state",
            return_value=AdmissionDecision(state="open"),
        ),
    ):
        coordinator.tick()

    dispatch.assert_called_once()
    assert dispatch.call_args.args[0].task_id == "candidate"
    assert dispatch.call_args.args[1].role == "ut_lane"
    assert captured[0].dispatches_this_tick == 0
    assert coordinator._refusal_ledger.stats()["refusal_triples"] == 0


# -- refusal/starvation observations cannot suppress, notify, or escalate ---------


def test_refusal_ledger_counts_bounded_support_without_cooldown_or_notification() -> None:
    notifications: list[tuple[str, str]] = []
    ledger = DispatchRefusalLedger(k=1, _escalate_fn=lambda *args: notifications.append(args))

    entry = ledger.record_refusal("task", "lane", "route policy refuse: held", now=100.0)

    assert entry.effect_state == SUPPORT_EFFECT_STATE
    assert entry.hold_reason == SUPPORT_HOLD_REASON
    assert entry.may_authorize is False
    assert entry.hold_visible is True
    assert entry.cooldown_until == 0.0
    assert entry.escalated is False
    assert not ledger.is_cooled_down("task", "lane", now=101.0)
    assert not ledger.any_cooldown_for_pair("task", "lane", now=101.0)
    assert not ledger.any_cooldown_for_task("task", now=101.0)
    assert notifications == []


def test_starvation_signal_becomes_visible_hold_without_notification() -> None:
    notifications: list[tuple[str, str]] = []
    ledger = DispatchRefusalLedger(
        starvation_horizon_s=10.0,
        _escalate_fn=lambda *args: notifications.append(args),
    )

    assert ledger.tick_starvation(3, 0, now=100.0) is False
    assert ledger.tick_starvation(3, 0, now=111.0) is False

    stats = ledger.stats(now=111.0)
    assert stats["effect_state"] == SUPPORT_EFFECT_STATE
    assert stats["starvation_hold_visible"] is True
    assert stats["starvation_escalated"] is False
    assert stats["cooled_down"] == stats["escalated"] == 0
    assert notifications == []


@pytest.mark.parametrize(
    ("task", "lane", "reason", "now"),
    [
        ("", "lane", "reason", 1.0),
        ("task", " lane", "reason", 1.0),
        ("task", "lane", "", 1.0),
        ("task", "lane", "reason", math.nan),
    ],
)
def test_refusal_observation_is_strictly_bounded(
    task: str, lane: str, reason: str, now: float
) -> None:
    with pytest.raises(ValueError, match="dispatch_refusal_.*_invalid"):
        DispatchRefusalLedger().record_refusal(task, lane, reason, now=now)


# -- concrete safety and projection surface ---------------------------------------


def test_coordinator_module_has_no_process_group_kill() -> None:
    import agents.coordinator.core as core

    source = Path(core.__file__).read_text(encoding="utf-8")
    assert "killpg(" not in source
    for match in re.finditer(r"os\.kill\(([^)]*)\)", source):
        assert match.group(1).strip().endswith(", 0"), match.group(0)


def test_lane_projection_exposes_signal_without_nonfinite_json() -> None:
    projection = _lane_to_dict(LaneState(role="ut_lane", stalled=True, output_age_s=42.0))
    assert projection["stalled"] is True
    assert projection["output_age_s"] == 42.0
    assert _lane_to_dict(LaneState(role="x"))["output_age_s"] is None
