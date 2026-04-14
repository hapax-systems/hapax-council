"""Tests for shared/inference_budget.py — LRR Phase 9 item 5."""

from __future__ import annotations

import pytest  # noqa: TC002 — runtime dep for fixtures

from shared.inference_budget import (
    DEFAULT_REFRESH_SECONDS,
    DEFAULT_TIER_BUDGETS,
    BudgetExhausted,
    InferenceBudgetAllocator,
    InferenceTier,
    TierBudgetConfig,
)


class TestTierTaxonomy:
    def test_five_tiers(self) -> None:
        assert len(InferenceTier) == 5

    def test_tier_labels(self) -> None:
        assert InferenceTier.T1_CLAIM_AGENDA.label == "claim_agenda"
        assert InferenceTier.T2_ARC_PLANNER.label == "arc_planner"
        assert InferenceTier.T3_BLOCK_SCHEDULER.label == "block_scheduler"
        assert InferenceTier.T4_ACTIVITY_SELECTOR.label == "activity_selector"
        assert InferenceTier.T5_TICK_EXECUTION.label == "tick_execution"

    def test_default_budgets_cover_all_tiers(self) -> None:
        covered = {c.tier for c in DEFAULT_TIER_BUDGETS}
        assert covered == set(InferenceTier)


class TestReserve:
    def test_reserve_within_budget_ok(self) -> None:
        alloc = InferenceBudgetAllocator(now_fn=lambda: 1000.0)
        alloc.reserve(InferenceTier.T1_CLAIM_AGENDA, 100)
        remaining = alloc.remaining(InferenceTier.T1_CLAIM_AGENDA)
        assert remaining == 20_000 - 100

    def test_reserve_exhausts(self) -> None:
        configs = (TierBudgetConfig(InferenceTier.T4_ACTIVITY_SELECTOR, tokens_per_refresh=1000),)
        alloc = InferenceBudgetAllocator(
            configs=configs,
            now_fn=lambda: 1000.0,
        )
        alloc.reserve(InferenceTier.T4_ACTIVITY_SELECTOR, 1000)
        with pytest.raises(BudgetExhausted) as exc_info:
            alloc.reserve(InferenceTier.T4_ACTIVITY_SELECTOR, 1)
        assert exc_info.value.tier == InferenceTier.T4_ACTIVITY_SELECTOR
        assert exc_info.value.requested == 1
        assert exc_info.value.remaining == 0

    def test_negative_tokens_rejected(self) -> None:
        alloc = InferenceBudgetAllocator(now_fn=lambda: 1000.0)
        with pytest.raises(ValueError, match="non-negative"):
            alloc.reserve(InferenceTier.T1_CLAIM_AGENDA, -1)


class TestRefresh:
    def test_refresh_resets_consumption(self) -> None:
        clock = {"t": 1000.0}
        configs = (TierBudgetConfig(InferenceTier.T4_ACTIVITY_SELECTOR, tokens_per_refresh=500),)
        alloc = InferenceBudgetAllocator(
            configs=configs,
            now_fn=lambda: clock["t"],
            refresh_seconds=60.0,
        )
        alloc.reserve(InferenceTier.T4_ACTIVITY_SELECTOR, 400)
        assert alloc.remaining(InferenceTier.T4_ACTIVITY_SELECTOR) == 100

        clock["t"] = 1100.0  # 100s later, past the 60s refresh
        assert alloc.remaining(InferenceTier.T4_ACTIVITY_SELECTOR) == 500

    def test_refresh_below_interval_does_not_reset(self) -> None:
        clock = {"t": 1000.0}
        configs = (TierBudgetConfig(InferenceTier.T4_ACTIVITY_SELECTOR, tokens_per_refresh=500),)
        alloc = InferenceBudgetAllocator(
            configs=configs,
            now_fn=lambda: clock["t"],
            refresh_seconds=60.0,
        )
        alloc.reserve(InferenceTier.T4_ACTIVITY_SELECTOR, 400)
        clock["t"] = 1030.0  # only 30s later
        assert alloc.remaining(InferenceTier.T4_ACTIVITY_SELECTOR) == 100

    def test_reserve_after_refresh_succeeds(self) -> None:
        clock = {"t": 1000.0}
        configs = (TierBudgetConfig(InferenceTier.T4_ACTIVITY_SELECTOR, tokens_per_refresh=500),)
        alloc = InferenceBudgetAllocator(
            configs=configs,
            now_fn=lambda: clock["t"],
            refresh_seconds=60.0,
        )
        alloc.reserve(InferenceTier.T4_ACTIVITY_SELECTOR, 500)  # exhaust
        clock["t"] = 1100.0
        alloc.reserve(InferenceTier.T4_ACTIVITY_SELECTOR, 300)  # allowed after refresh
        assert alloc.remaining(InferenceTier.T4_ACTIVITY_SELECTOR) == 200


class TestWarnCallback:
    def test_warn_fires_at_80_percent(self) -> None:
        warned: list[tuple[InferenceTier, float]] = []
        configs = (
            TierBudgetConfig(
                InferenceTier.T1_CLAIM_AGENDA,
                tokens_per_refresh=1000,
                warn_fraction=0.80,
            ),
        )
        alloc = InferenceBudgetAllocator(
            configs=configs,
            now_fn=lambda: 1000.0,
            warn_fn=lambda tier, frac: warned.append((tier, frac)),
        )
        alloc.reserve(InferenceTier.T1_CLAIM_AGENDA, 500)  # 50% — no warn
        assert warned == []
        alloc.reserve(InferenceTier.T1_CLAIM_AGENDA, 300)  # 80% — warn
        assert len(warned) == 1
        assert warned[0][0] == InferenceTier.T1_CLAIM_AGENDA
        assert warned[0][1] >= 0.80

    def test_warn_fires_at_most_once_per_interval(self) -> None:
        warned: list[tuple[InferenceTier, float]] = []
        configs = (
            TierBudgetConfig(
                InferenceTier.T1_CLAIM_AGENDA,
                tokens_per_refresh=1000,
                warn_fraction=0.80,
            ),
        )
        alloc = InferenceBudgetAllocator(
            configs=configs,
            now_fn=lambda: 1000.0,
            warn_fn=lambda tier, frac: warned.append((tier, frac)),
        )
        alloc.reserve(InferenceTier.T1_CLAIM_AGENDA, 800)
        alloc.reserve(InferenceTier.T1_CLAIM_AGENDA, 100)  # still over 80%
        assert len(warned) == 1

    def test_warn_resets_after_refresh(self) -> None:
        warned: list[tuple[InferenceTier, float]] = []
        clock = {"t": 1000.0}
        configs = (
            TierBudgetConfig(
                InferenceTier.T1_CLAIM_AGENDA,
                tokens_per_refresh=1000,
                warn_fraction=0.80,
            ),
        )
        alloc = InferenceBudgetAllocator(
            configs=configs,
            now_fn=lambda: clock["t"],
            warn_fn=lambda tier, frac: warned.append((tier, frac)),
            refresh_seconds=60.0,
        )
        alloc.reserve(InferenceTier.T1_CLAIM_AGENDA, 900)
        assert len(warned) == 1
        clock["t"] = 1100.0  # past refresh
        alloc.reserve(InferenceTier.T1_CLAIM_AGENDA, 900)
        assert len(warned) == 2


class TestSnapshot:
    def test_snapshot_contains_all_tiers(self) -> None:
        alloc = InferenceBudgetAllocator(now_fn=lambda: 1000.0)
        snap = alloc.snapshot()
        for tier in InferenceTier:
            assert tier.label in snap
            assert "tokens_per_refresh" in snap[tier.label]
            assert "tokens_consumed" in snap[tier.label]
            assert "remaining" in snap[tier.label]

    def test_snapshot_reflects_consumption(self) -> None:
        alloc = InferenceBudgetAllocator(now_fn=lambda: 1000.0)
        alloc.reserve(InferenceTier.T1_CLAIM_AGENDA, 100)
        snap = alloc.snapshot()
        assert snap["claim_agenda"]["tokens_consumed"] == 100
        assert snap["claim_agenda"]["remaining"] == 20_000 - 100


class TestDefaultRefreshInterval:
    def test_default_is_one_hour(self) -> None:
        assert DEFAULT_REFRESH_SECONDS == 3600.0
