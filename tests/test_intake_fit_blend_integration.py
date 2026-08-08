"""Integration: the composite fit-blend rank-key at BOTH dispatch sites.

Guards the two load-bearing invariants of the shadow slice:
  * ``plan_dispatches`` with ``fit_blend=0.0`` is byte-identical to pure-WSJF (the golden
    guarantee) and a non-zero blend measurably reorders;
  * ``_repair_cooled_plan`` honors the SAME ``fit_blend`` (the no-spin repair pass must
    never reorder relative to the plan — both sites use ``composite_rank_key``).
"""

from __future__ import annotations

from agents.coordinator.core import Coordinator
from shared.dispatch_service_time import QueueLane, QueueTask, plan_dispatches

_L1 = QueueLane(role="L1", platform="codex")


def _task(tid: str, wsjf: float, rv: dict[str, int] | None = None) -> QueueTask:
    return QueueTask(
        task_id=tid,
        wsjf=wsjf,
        platform_suitability=("codex",),
        age_s=0.0,
        requirement_vector=rv,
    )


# ----------------------------------------------------------- plan_dispatches golden


def test_plan_blend_zero_keeps_pure_wsjf_tie_order() -> None:
    # Equal wsjf; A has a high fit, B is DARK. blend=0 => pure wsjf => ``max`` breaks the
    # tie by position (A first), NOT by fit — proving the composite short-circuited.
    a = _task("A", 5.0, {"context_length": 5})  # fit 5.0
    b = _task("B", 5.0, None)  # fit 0.0 (DARK)
    assert plan_dispatches([a, b], [_L1], max_dispatches=1, fit_blend=0.0) == [("A", "L1")]
    # A negative blend sinks A below B -> B wins (the blend flowed through as arithmetic).
    assert plan_dispatches([a, b], [_L1], max_dispatches=1, fit_blend=-1.0) == [("B", "L1")]


def test_plan_blend_positive_lets_high_fit_overtake_lower_wsjf() -> None:
    # B has the higher wsjf but zero fit; A has lower wsjf but high fit. A large enough
    # blend lets A overtake B — the demand-shape signal influencing selection.
    a = _task("A", 4.0, {"context_length": 5, "mutation_risk": 5})  # fit 5.0
    b = _task("B", 5.0, None)  # fit 0.0
    assert plan_dispatches([a, b], [_L1], max_dispatches=1, fit_blend=0.0) == [("B", "L1")]
    assert plan_dispatches([a, b], [_L1], max_dispatches=1, fit_blend=1.0) == [("A", "L1")]


def test_plan_blend_zero_identical_across_rv_shapes() -> None:
    # Golden guarantee: blend=0 yields the same plan whether RVs are full, partial, or
    # absent — the composite short-circuits to pure wsjf for every task. plan_dispatches
    # is lane-outer (one task per idle lane), so 3 lanes pull the 3 wsjf-equal tasks in
    # position order — fit does NOT reorder them.
    l1 = QueueLane(role="L1", platform="codex")
    l2 = QueueLane(role="L2", platform="codex")
    l3 = QueueLane(role="L3", platform="codex")
    full = _task(
        "full",
        3.0,
        {
            d: 5
            for d in (
                "quality_floor",
                "information_scope",
                "context_length",
                "mutation_risk",
                "verification_demand",
                "ambiguity_novelty",
                "composition_coupling",
                "governance_sensitivity",
            )
        },
    )
    partial = _task("partial", 3.0, {"context_length": 4})
    dark = _task("dark", 3.0, None)
    assert plan_dispatches(
        [full, partial, dark], [l1, l2, l3], max_dispatches=3, fit_blend=0.0
    ) == [
        ("full", "L1"),
        ("partial", "L2"),
        ("dark", "L3"),
    ]


# ----------------------------------------------- _repair_cooled_plan honors fit_blend


class _StubRefusalLedger:
    """Minimal refusal ledger: ``any_cooldown_for_pair`` over a fixed pair set."""

    def __init__(self, cooled: set[tuple[str, str]]) -> None:
        self._cooled = set(cooled)

    def any_cooldown_for_pair(self, task_id: str, role: str, now: float | None = None) -> bool:
        return (task_id, role) in self._cooled


def test_repair_cooled_plan_honors_fit_blend() -> None:
    # A is cooled on L1; the backfill chooses between B (higher wsjf, low fit) and C
    # (lower wsjf, high fit). blend=0 -> B (wsjf order); blend=1.0 -> C (fit lifts it).
    # Proves the repair site uses composite_rank_key with the same fit_blend as the plan.
    coord = Coordinator()
    coord._refusal_ledger = _StubRefusalLedger({("A", "L1")})
    tasks = [
        _task("A", 10.0, None),
        _task("B", 8.0, {"context_length": 1}),  # fit 1.0
        _task("C", 6.0, {"context_length": 5}),  # fit 5.0
    ]
    plan0, skipped0 = coord._repair_cooled_plan(
        [("A", "L1")], tasks, [_L1], age_norm_s=3600.0, now_mono=0.0, fit_blend=0.0
    )
    assert plan0 == [("B", "L1")]  # pure-wsjf backfill
    assert skipped0 == 0
    plan1, _ = coord._repair_cooled_plan(
        [("A", "L1")], tasks, [_L1], age_norm_s=3600.0, now_mono=0.0, fit_blend=1.0
    )
    assert plan1 == [("C", "L1")]  # C: 6+5=11 > B: 8+1=9


def test_repair_cooled_plan_skips_when_no_backfill() -> None:
    # A cooled, no eligible backfill -> the pair is dropped, skipped=1 (the no-spin law's
    # honest "freed a lane with nothing to fill it" count). fit_blend is irrelevant.
    coord = Coordinator()
    coord._refusal_ledger = _StubRefusalLedger({("A", "L1")})
    tasks = [_task("A", 10.0, {"context_length": 5})]
    plan, skipped = coord._repair_cooled_plan(
        [("A", "L1")], tasks, [_L1], age_norm_s=3600.0, now_mono=0.0, fit_blend=1.0
    )
    assert plan == []
    assert skipped == 1
