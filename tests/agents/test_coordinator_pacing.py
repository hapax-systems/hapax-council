"""Gate-0A computes a bounded held candidate independently of pressure."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.coordinator.core import (
    Coordinator,
    DispatchDisposition,
    LaneState,
    MethodologyDispatchResult,
    Task,
)
from shared.sdlc_pressure_gate import AdmissionDecision


def _tasks(count: int) -> list[Task]:
    return [
        Task(
            task_id=f"t{index}",
            title="x",
            status="offered",
            assigned_to="unassigned",
            wsjf=float(count - index),
            effort_class="standard",
            platform_suitability=("claude",),
            quality_floor="deterministic_ok",
            path=Path(f"/tmp/t{index}.md"),
        )
        for index in range(count)
    ]


def _lanes(count: int) -> dict[str, LaneState]:
    return {
        f"l{index}": LaneState(
            role=f"l{index}",
            platform="claude",
            alive=True,
            idle=True,
        )
        for index in range(count)
    }


def _candidate_plan(state: str) -> tuple[list[tuple[str, str]], object]:
    coordinator = Coordinator()
    candidates: list[tuple[str, str]] = []

    def held_candidate(task: Task, lane: LaneState) -> MethodologyDispatchResult:
        candidates.append((task.task_id, lane.role))
        return MethodologyDispatchResult(
            DispatchDisposition.HELD_CANDIDATE,
            "methodology_candidate_held_not_admitted",
        )

    with (
        patch.object(Coordinator, "_scan_tasks", return_value=_tasks(6)),
        patch.object(Coordinator, "_check_lanes", return_value=_lanes(6)),
        patch.object(Coordinator, "_dispatch", side_effect=held_candidate),
        patch.object(Coordinator, "_write_state") as write_state,
        patch(
            "agents.coordinator.core.observe_admission_state",
            return_value=AdmissionDecision(state=state),
        ),
    ):
        coordinator.tick()

    return candidates, write_state.call_args.args[0]


@pytest.mark.parametrize("pressure_state", ["open", "paced", "closed"])
def test_candidate_plan_is_identical_across_pressure_states(
    pressure_state: str,
) -> None:
    candidates, state = _candidate_plan(pressure_state)

    assert candidates == [("t0", "l0")]
    assert state.dispatches_this_tick == 0


def test_pressure_states_have_one_shared_candidate_plan() -> None:
    plans = [_candidate_plan(state)[0] for state in ("open", "paced", "closed")]
    assert plans[0] == plans[1] == plans[2]
