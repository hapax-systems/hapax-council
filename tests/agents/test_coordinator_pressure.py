"""L3 consumer: the coordinator paces its dispatch loop under CPU pressure.

Under 'closed' it dispatches nothing this tick (tasks stay OFFERED on disk — not
dropped); under 'paced' it caps dispatches/tick and stretches the cooldown.
Slows the controller, never abandons work.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.coordinator.core import (
    DISPATCH_COOLDOWN_S,
    Coordinator,
    LaneState,
    Task,
    pressure_dispatch_budget,
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
    return LaneState(role="beta", platform="claude", alive=True, idle=True, claimed_task=None)


# ── pure budget ──────────────────────────────────────────────────────────────


def test_budget_open_allows_full_throughput() -> None:
    assert pressure_dispatch_budget("open", idle_count=4, base_cooldown=120.0) == (4, 120.0)


def test_budget_paced_caps_one_and_stretches_cooldown() -> None:
    max_dispatch, cooldown = pressure_dispatch_budget("paced", idle_count=4, base_cooldown=120.0)
    assert max_dispatch == 1
    assert cooldown > 120.0


def test_budget_closed_allows_no_dispatch() -> None:
    assert pressure_dispatch_budget("closed", idle_count=4, base_cooldown=120.0)[0] == 0


# ── tick() honours admission ─────────────────────────────────────────────────


def _run_tick(state: str) -> list[tuple[Task, LaneState]]:
    coord = Coordinator()
    dispatched: list[tuple[Task, LaneState]] = []
    with (
        patch.object(Coordinator, "_scan_tasks", return_value=[_task()]),
        patch.object(Coordinator, "_check_lanes", return_value={"beta": _idle_lane()}),
        patch.object(
            Coordinator,
            "_dispatch",
            side_effect=lambda t, lane: bool(dispatched.append((t, lane))) or True,
        ),
        patch.object(Coordinator, "_write_state"),
        patch(
            "agents.coordinator.core.admission_state",
            return_value=AdmissionDecision(state=state),
        ),
    ):
        coord.tick()
    return dispatched


def test_tick_dispatches_nothing_when_closed() -> None:
    assert _run_tick("closed") == []  # queued (stays offered), not dropped


def test_tick_dispatches_when_open() -> None:
    assert len(_run_tick("open")) == 1


def test_dispatch_cooldown_default_unchanged() -> None:
    # Guard the base constant the pressure scaler multiplies.
    assert DISPATCH_COOLDOWN_S == 120.0
