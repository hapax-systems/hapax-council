"""Coordinator integration conformance for candidate carriage with zero effects."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.coordinator import core
from agents.coordinator.core import (
    Coordinator,
    DispatchDisposition,
    LaneState,
    MethodologyDispatchResult,
    Task,
    _ntfy_escalate,
)
from shared.dispatch_service_time import QueueLane, QueueTask, plan_dispatches
from shared.sdlc_pressure_gate import AdmissionDecision

TASK_A = Task(
    task_id="task-a",
    title="Task A",
    status="offered",
    assigned_to="unassigned",
    wsjf=10.0,
    effort_class="standard",
    platform_suitability=("claude",),
    quality_floor="deterministic_ok",
    path=Path("/nonexistent/task-a.md"),
)
TASK_B = Task(
    task_id="task-b",
    title="Task B",
    status="offered",
    assigned_to="unassigned",
    wsjf=1.0,
    effort_class="standard",
    platform_suitability=("claude",),
    quality_floor="deterministic_ok",
    path=Path("/nonexistent/task-b.md"),
)
LANE = LaneState(
    role="alpha",
    session="hapax-claude-alpha",
    platform="claude",
    alive=True,
    idle=True,
    dispatch_ready=True,
)


def _result(
    disposition: DispatchDisposition,
    reason: str,
) -> MethodologyDispatchResult:
    return MethodologyDispatchResult(disposition=disposition, reason=reason)


def _tick(
    coordinator: Coordinator,
    *,
    tasks: list[Task],
    result: MethodologyDispatchResult,
) -> tuple[object, MagicMock]:
    with (
        patch.object(coordinator, "_scan_tasks", return_value=tasks),
        patch.object(coordinator, "_check_lanes", return_value={"alpha": LANE}),
        patch.object(coordinator, "_dispatch", return_value=result) as dispatch,
        patch.object(coordinator, "_write_state") as write_state,
        patch(
            "agents.coordinator.core.observe_admission_state",
            return_value=AdmissionDecision(state="open"),
        ),
    ):
        coordinator.tick()
    return write_state.call_args.args[0], dispatch


def test_notification_compatibility_function_only_logs_hold(caplog) -> None:
    assert not hasattr(core, "send_notification")
    with caplog.at_level(logging.WARNING):
        _ntfy_escalate("title", "body")
    assert "notification HOLD" in caplog.text


def test_repeated_typed_refusals_remain_observable_without_suppression() -> None:
    coordinator = Coordinator()
    callback = MagicMock()
    coordinator._refusal_ledger._escalate_fn = callback
    attempts = 0

    for _ in range(8):
        state, dispatch = _tick(
            coordinator,
            tasks=[TASK_A],
            result=_result(
                DispatchDisposition.REFUSED,
                "BLOCKED: support-only route observation",
            ),
        )
        attempts += dispatch.call_count
        assert state.dispatches_this_tick == 0

    stats = coordinator._refusal_ledger.stats()
    assert attempts == 8
    assert stats["observations"] == 8
    assert stats["visible_holds"] == 1
    assert stats["cooled_down"] == 0
    assert stats["escalated"] == 0
    assert callback.call_count == 0


def test_held_candidate_never_records_refusal_or_materialization() -> None:
    coordinator = Coordinator()
    state, dispatch = _tick(
        coordinator,
        tasks=[TASK_A],
        result=_result(
            DispatchDisposition.HELD_CANDIDATE,
            "methodology_candidate_held_not_admitted",
        ),
    )

    assert dispatch.call_count == 1
    assert state.dispatches_this_tick == 0
    assert coordinator._refusal_ledger.stats()["observations"] == 0


def test_indeterminate_process_result_has_no_refusal_effect() -> None:
    coordinator = Coordinator()
    state, dispatch = _tick(
        coordinator,
        tasks=[TASK_A],
        result=_result(
            DispatchDisposition.INDETERMINATE,
            "dispatch_carrier_hash_mismatch",
        ),
    )

    assert dispatch.call_count == 1
    assert state.dispatches_this_tick == 0
    assert coordinator._refusal_ledger.stats()["refusal_triples"] == 0


def test_gate0a_result_has_no_materialized_outcome_authority_shape() -> None:
    assert "materialized_outcome" not in {disposition.value for disposition in DispatchDisposition}
    result = _result(
        DispatchDisposition.HELD_CANDIDATE,
        "methodology_candidate_held_not_admitted",
    )
    assert not hasattr(result, "materialized")


def test_candidate_plan_is_stable_and_ignores_support_modulators() -> None:
    tasks = [
        QueueTask(
            task_id="task-b",
            wsjf=10.0,
            platform_suitability=("claude",),
            age_s=999999.0,
            requirement_vector={"context_depth": 5},
        ),
        QueueTask(
            task_id="task-a",
            wsjf=10.0,
            platform_suitability=("claude",),
            age_s=0.0,
            requirement_vector={"context_depth": 0},
        ),
    ]
    lanes = [
        QueueLane(
            role="beta",
            platform="claude",
            cooldown_remaining_s=999999.0,
        ),
        QueueLane(role="alpha", platform="claude"),
    ]

    baseline = plan_dispatches(
        tasks,
        lanes,
        max_dispatches=2,
        age_norm_s=1.0,
        legacy=False,
        fit_blend=0.0,
    )
    hostile_modulators = plan_dispatches(
        list(reversed(tasks)),
        list(reversed(lanes)),
        max_dispatches=2,
        age_norm_s=10**12,
        legacy=True,
        fit_blend=-(10**9),
    )

    assert baseline == [("task-a", "alpha"), ("task-b", "beta")]
    assert hostile_modulators == baseline


def test_reoffer_private_boundaries_hold_without_io() -> None:
    coordinator = Coordinator()
    lane = LaneState(role="alpha", claimed_task="task-a", stalled=True)
    task = TASK_A

    assert coordinator._reoffer_stalled(lane) is False
    assert coordinator._reoffer_orphaned_claim(task, {"alpha": lane}) is False
    assert (
        coordinator._reoffer_orphaned_claims(
            [task],
            {"alpha": lane},
            now_wall=999999.0,
        )
        == 0
    )
