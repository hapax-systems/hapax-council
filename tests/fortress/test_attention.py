"""Tests for attention budget allocation."""

from __future__ import annotations

import unittest

from agents.fortress.attention import (
    AttentionBudget,
    AttentionTier,
    TierAllocation,
    allocate_tiers,
    compute_budget,
)
from agents.fortress.config import PerceptionConfig


class TestComputeBudget(unittest.TestCase):
    def test_zero_population(self) -> None:
        # sqrt(1) * 1.8 + 5 = 6.8 -> 6
        budget = compute_budget(0)
        assert budget == 6

    def test_small_population(self) -> None:
        # sqrt(10) * 1.8 + 5 ≈ 10.7 -> 10
        budget = compute_budget(10)
        assert budget == 10

    def test_large_population_capped(self) -> None:
        # sqrt(1000) * 1.8 + 5 ≈ 61.9 -> capped at 30
        budget = compute_budget(1000)
        assert budget == 30

    def test_custom_config(self) -> None:
        cfg = PerceptionConfig(budget_base=10, budget_scale=2.0, budget_cap=50)
        budget = compute_budget(100, cfg)
        # sqrt(100) * 2.0 + 10 = 30
        assert budget == 30


class TestAllocateTiers(unittest.TestCase):
    def test_normal_allocation(self) -> None:
        alloc = allocate_tiers(20)
        assert alloc.crisis == 8  # 40%
        assert alloc.routine == 7  # 35%
        assert alloc.strategic == 5  # remainder
        assert alloc.crisis + alloc.routine + alloc.strategic == 20

    def test_crisis_allocation(self) -> None:
        alloc = allocate_tiers(20, crisis_active=True)
        assert alloc.crisis == 13  # 65%
        assert alloc.routine == 7  # remainder
        assert alloc.strategic == 0
        assert alloc.crisis + alloc.routine == 20

    def test_small_budget(self) -> None:
        alloc = allocate_tiers(5)
        assert alloc.crisis + alloc.routine + alloc.strategic == 5


class TestAttentionBudget(unittest.TestCase):
    def test_initial_budget(self) -> None:
        ab = AttentionBudget(population=50)
        assert ab.budget > 0

    def test_spend_and_remaining(self) -> None:
        ab = AttentionBudget(population=50)
        initial = ab.remaining(AttentionTier.ROUTINE)
        assert initial > 0
        assert ab.spend(AttentionTier.ROUTINE)
        assert ab.remaining(AttentionTier.ROUTINE) == initial - 1

    def test_cannot_overspend(self) -> None:
        ab = AttentionBudget(population=0)
        # Exhaust routine budget
        while ab.can_spend(AttentionTier.ROUTINE):
            ab.spend(AttentionTier.ROUTINE)
        assert not ab.can_spend(AttentionTier.ROUTINE)
        assert not ab.spend(AttentionTier.ROUTINE)

    def test_total_remaining(self) -> None:
        ab = AttentionBudget(population=50)
        assert ab.total_remaining == ab.budget

    def test_reset(self) -> None:
        ab = AttentionBudget(population=50)
        ab.spend(AttentionTier.ROUTINE)
        ab.reset(population=100, game_day=2)
        # After reset, budget recalculated and all spent reset
        assert ab.total_remaining == ab.budget

    def test_reallocate_for_crisis(self) -> None:
        ab = AttentionBudget(population=50)
        ab.reallocate_for_crisis()
        assert ab.remaining(AttentionTier.STRATEGIC) == 0
        assert ab.allocation.strategic == 0

    def test_is_free(self) -> None:
        ab = AttentionBudget()
        assert ab.is_free("scan_threats")
        assert ab.is_free("check_announcements")
        assert not ab.is_free("observe_region")

    def test_allocation_property(self) -> None:
        ab = AttentionBudget(population=50)
        alloc = ab.allocation
        assert isinstance(alloc, TierAllocation)


if __name__ == "__main__":
    unittest.main()
