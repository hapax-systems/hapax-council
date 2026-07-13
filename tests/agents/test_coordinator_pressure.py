"""Ambient pressure is support evidence, not Gate-0A candidate authority."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.coordinator.core import (
    MAX_HELD_CANDIDATES_PER_TICK,
    Coordinator,
    DispatchDisposition,
    LaneState,
    MethodologyDispatchResult,
    Task,
)
from shared.sdlc_pressure_gate import AdmissionDecision


def _task() -> Task:
    return Task(
        task_id="t1",
        title="x",
        status="offered",
        assigned_to="unassigned",
        wsjf=10.0,
        effort_class="standard",
        platform_suitability=("claude",),
        quality_floor="deterministic_ok",
        path=Path("/tmp/t1.md"),
    )


def _idle_lane() -> LaneState:
    return LaneState(role="beta", platform="claude", alive=True, idle=True)


def _run_tick(state: str) -> tuple[list[tuple[str, str]], object]:
    coordinator = Coordinator()
    candidates: list[tuple[str, str]] = []

    def held_candidate(task: Task, lane: LaneState) -> MethodologyDispatchResult:
        candidates.append((task.task_id, lane.role))
        return MethodologyDispatchResult(
            DispatchDisposition.HELD_CANDIDATE,
            "methodology_candidate_held_not_admitted",
        )

    with (
        patch.object(Coordinator, "_scan_tasks", return_value=[_task()]),
        patch.object(Coordinator, "_check_lanes", return_value={"beta": _idle_lane()}),
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
def test_pressure_neither_suppresses_nor_authorizes_held_candidate(
    pressure_state: str,
) -> None:
    candidates, state = _run_tick(pressure_state)

    assert candidates == [("t1", "beta")]
    assert state.dispatches_this_tick == 0
    assert state.pressure_observation == {
        "admission_state": pressure_state,
        "reasons": [],
        "candidate_influence": "none",
        "may_authorize": False,
    }


def test_gate0a_candidate_budget_is_static_and_bounded() -> None:
    assert MAX_HELD_CANDIDATES_PER_TICK == 1
