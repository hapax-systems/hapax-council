"""Gate-0A candidate planning ignores non-authorizing fit and cooldown signals."""

from __future__ import annotations

from agents.coordinator.core import Coordinator
from shared.dispatch_service_time import QueueLane, QueueTask, plan_dispatches


def _task(
    task_id: str,
    wsjf: float,
    *,
    platform: str = "codex",
    age_s: float = 0.0,
    requirement_vector: dict[str, int] | None = None,
) -> QueueTask:
    return QueueTask(
        task_id=task_id,
        wsjf=wsjf,
        platform_suitability=(platform,),
        age_s=age_s,
        requirement_vector=requirement_vector,
    )


def test_fit_blend_cannot_reorder_equal_wsjf_candidates() -> None:
    high_fit = _task(
        "task-b",
        5.0,
        requirement_vector={"context_length": 5, "mutation_risk": 5},
    )
    dark = _task("task-a", 5.0)
    lanes = [QueueLane(role="cx-alpha", platform="codex")]

    for blend in (-10**9, 0.0, 10**9):
        assert plan_dispatches(
            [high_fit, dark],
            lanes,
            max_dispatches=1,
            fit_blend=blend,
        ) == [("task-a", "cx-alpha")]


def test_age_cooldown_legacy_and_input_order_cannot_reorder() -> None:
    tasks = [
        _task("task-b", 5.0, age_s=10**12),
        _task("task-a", 5.0, age_s=0.0),
    ]
    lanes = [
        QueueLane(
            role="cx-beta",
            platform="codex",
            cooldown_remaining_s=10**12,
        ),
        QueueLane(role="cx-alpha", platform="codex"),
    ]

    baseline = plan_dispatches(
        tasks,
        lanes,
        max_dispatches=2,
        age_norm_s=1.0,
        legacy=False,
        fit_blend=0.0,
    )
    modulated = plan_dispatches(
        list(reversed(tasks)),
        list(reversed(lanes)),
        max_dispatches=2,
        age_norm_s=10**12,
        legacy=True,
        fit_blend=10**9,
    )

    assert baseline == [("task-a", "cx-alpha"), ("task-b", "cx-beta")]
    assert modulated == baseline


def test_raw_wsjf_and_route_compatibility_remain_candidate_inputs() -> None:
    tasks = [
        _task("codex-low", 1.0),
        _task("codex-high", 10.0),
        _task("claude-high", 20.0, platform="claude"),
    ]
    lanes = [
        QueueLane(role="alpha", platform="claude"),
        QueueLane(role="cx-alpha", platform="codex"),
    ]

    assert plan_dispatches(tasks, lanes, max_dispatches=2) == [
        ("claude-high", "alpha"),
        ("codex-high", "cx-alpha"),
    ]


def test_operator_pool_and_non_dispatchable_lanes_are_excluded() -> None:
    tasks = [_task("task-a", 5.0, platform="claude")]
    lanes = [
        QueueLane(role="dev", platform="claude"),
        QueueLane(role="beta", platform="claude", dispatchable=False),
        QueueLane(role="alpha", platform="claude"),
    ]

    assert plan_dispatches(tasks, lanes, max_dispatches=3) == [("task-a", "alpha")]


def test_refusal_repair_is_identity_and_cannot_consume_cooldown_state() -> None:
    coordinator = Coordinator()
    plan = [("task-a", "cx-alpha")]
    repaired, skipped = coordinator._repair_cooled_plan(
        plan,
        [_task("task-a", 5.0)],
        [QueueLane(role="cx-alpha", platform="codex")],
        age_norm_s=1.0,
        now_mono=1.0,
        fit_blend=10**9,
    )

    assert repaired == plan
    assert skipped == 0
