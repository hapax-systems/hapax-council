"""The coordinator caps converge (dispatch) actions/tick via the RecoveryGovernor.

#3850 wired the PSI *cooldown* scaling; bb-control-stability adds the per-tick
**converge-action ceiling** {open:6, paced:2, closed:0(+1 critical)} so the
controller cannot itself become a load-injecting storm — one dispatch per lane
at most under open, ≤2 under paced, none under closed (work stays queued).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.coordinator.core import Coordinator, LaneState, Task
from shared.recovery_governor import RecoveryParams, converge_action_cap
from shared.sdlc_pressure_gate import AdmissionDecision

# ── pure converge cap ─────────────────────────────────────────────────────────


def test_converge_cap_open_is_fleet_width() -> None:
    assert converge_action_cap("open") == RecoveryParams().tick_cap_open == 6


def test_converge_cap_paced_is_two() -> None:
    assert converge_action_cap("paced") == RecoveryParams().tick_cap_paced == 2


def test_converge_cap_closed_is_zero_without_critical() -> None:
    assert converge_action_cap("closed") == 0


def test_converge_cap_closed_grants_critical_reserve() -> None:
    assert (
        converge_action_cap("closed", critical_pending=True)
        == RecoveryParams().critical_reserve
        == 1
    )


# ── tick honours the converge ceiling ─────────────────────────────────────────


def _tasks(n: int) -> list[Task]:
    return [
        Task(
            task_id=f"t{i}",
            title="x",
            status="offered",
            assigned_to="unassigned",
            wsjf=float(n - i),
            effort_class="standard",
            platform_suitability=("claude",),
            quality_floor="deterministic_ok",
            path=Path(f"/tmp/t{i}.md"),
        )
        for i in range(n)
    ]


def _lanes(n: int) -> dict[str, LaneState]:
    return {
        f"l{i}": LaneState(
            role=f"l{i}", platform="claude", alive=True, idle=True, claimed_task=None
        )
        for i in range(n)
    }


def _run_tick(state: str, *, n_tasks: int, n_lanes: int) -> int:
    coord = Coordinator()
    dispatched: list = []
    with (
        patch.object(Coordinator, "_scan_tasks", return_value=_tasks(n_tasks)),
        patch.object(Coordinator, "_check_lanes", return_value=_lanes(n_lanes)),
        patch.object(
            Coordinator,
            "_dispatch",
            side_effect=lambda t, lane: bool(dispatched.append((t, lane))) or (True, ""),
        ),
        patch.object(Coordinator, "_write_state"),
        patch(
            "agents.coordinator.core.admission_state", return_value=AdmissionDecision(state=state)
        ),
    ):
        coord.tick()
    return len(dispatched)


def test_tick_caps_paced_dispatches_at_two() -> None:
    # 6 idle lanes + 6 offered tasks, but paced → at most 2 converge actions.
    assert _run_tick("paced", n_tasks=6, n_lanes=6) == 2


def test_tick_caps_open_dispatches_at_fleet_width() -> None:
    # 8 tasks but only 6 lanes; open cap is 6.
    assert _run_tick("open", n_tasks=8, n_lanes=6) == 6


def test_tick_dispatches_nothing_when_closed() -> None:
    assert _run_tick("closed", n_tasks=6, n_lanes=6) == 0
