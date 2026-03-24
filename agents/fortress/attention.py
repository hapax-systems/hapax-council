"""Attention budget — constrained observation allocation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from agents.fortress.config import PerceptionConfig


class AttentionTier(StrEnum):
    CRISIS = "crisis"  # Tier 1: 40% (65% during crisis)
    ROUTINE = "routine"  # Tier 2: 35%
    STRATEGIC = "strategic"  # Tier 3: 25% (0% during crisis)


FREE_TOOLS = frozenset({"scan_threats", "check_announcements"})


@dataclass(frozen=True)
class TierAllocation:
    crisis: int
    routine: int
    strategic: int


def compute_budget(population: int, config: PerceptionConfig | None = None) -> int:
    cfg = config or PerceptionConfig()
    return min(
        cfg.budget_cap,
        int(cfg.budget_base + cfg.budget_scale * math.sqrt(max(1, population))),
    )


def allocate_tiers(budget: int, crisis_active: bool = False) -> TierAllocation:
    if crisis_active:
        crisis = int(budget * 0.65)
        routine = budget - crisis
        return TierAllocation(crisis=crisis, routine=routine, strategic=0)
    crisis = int(budget * 0.40)
    routine = int(budget * 0.35)
    strategic = budget - crisis - routine
    return TierAllocation(crisis=crisis, routine=routine, strategic=strategic)


class AttentionBudget:
    def __init__(self, population: int = 0, config: PerceptionConfig | None = None) -> None:
        self._config = config or PerceptionConfig()
        self._budget = compute_budget(population, self._config)
        self._allocation = allocate_tiers(self._budget)
        self._spent: dict[AttentionTier, int] = {t: 0 for t in AttentionTier}
        self._game_day: int = 0

    @property
    def budget(self) -> int:
        return self._budget

    @property
    def allocation(self) -> TierAllocation:
        return self._allocation

    def reset(self, population: int, game_day: int) -> None:
        self._budget = compute_budget(population, self._config)
        self._allocation = allocate_tiers(self._budget)
        self._spent = {t: 0 for t in AttentionTier}
        self._game_day = game_day

    def can_spend(self, tier: AttentionTier) -> bool:
        limit = getattr(self._allocation, tier.value)
        return self._spent[tier] < limit

    def spend(self, tier: AttentionTier, cost: int = 1) -> bool:
        if not self.can_spend(tier):
            return False
        self._spent[tier] += cost
        return True

    def remaining(self, tier: AttentionTier) -> int:
        limit = getattr(self._allocation, tier.value)
        return max(0, limit - self._spent[tier])

    @property
    def total_remaining(self) -> int:
        return sum(self.remaining(t) for t in AttentionTier)

    def reallocate_for_crisis(self) -> None:
        self._allocation = allocate_tiers(self._budget, crisis_active=True)

    def is_free(self, tool_name: str) -> bool:
        return tool_name in FREE_TOOLS
