"""LRR Phase 9 item 5 — inference budget allocator.

Token bucket per tier of the 5-tier content hierarchy (Bundle 8 §2,
referenced by Bundle 9 §4). Each tier gets a configurable token quota
per hour; consumption is tracked live; graceful degradation fires
at 80% utilization.

Tier hierarchy (from Bundle 8):

    1  claim_agenda          — high-level research claim management
    2  arc_planner           — multi-week arc + block scheduling
    3  block_scheduler       — per-block activity selection
    4  activity_selector     — per-tick activity choice (director loop)
    5  tick_execution        — inline micro-decisions within an activity

Bundle 9 §4 policy:

- Each tier has a fixed token budget per refresh interval (default 1h)
- 80% consumption → warning ntfy (not blocking)
- 100% consumption → tier-specific graceful degradation
- Tier 2 fallback: non-LLM activities (vinyl, observe, silence, reverie)
- Tier 4 fallback: last-used activity sticks until refresh

This module ships the allocator + metrics. Wiring into the actual
tick dispatcher is a Phase 8 integration point documented in the
Phase 9 close handoff.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

__all__ = [
    "InferenceTier",
    "TierBudgetConfig",
    "InferenceBudgetAllocator",
    "BudgetExhausted",
    "DEFAULT_TIER_BUDGETS",
    "DEFAULT_REFRESH_SECONDS",
]

DEFAULT_REFRESH_SECONDS: Final = 3600.0
"""Bundle 9 §4 default refresh interval — budgets reset hourly."""


class InferenceTier(IntEnum):
    """Bundle 8 §2 5-tier content hierarchy."""

    T1_CLAIM_AGENDA = 1
    T2_ARC_PLANNER = 2
    T3_BLOCK_SCHEDULER = 3
    T4_ACTIVITY_SELECTOR = 4
    T5_TICK_EXECUTION = 5

    @property
    def label(self) -> str:
        return {
            InferenceTier.T1_CLAIM_AGENDA: "claim_agenda",
            InferenceTier.T2_ARC_PLANNER: "arc_planner",
            InferenceTier.T3_BLOCK_SCHEDULER: "block_scheduler",
            InferenceTier.T4_ACTIVITY_SELECTOR: "activity_selector",
            InferenceTier.T5_TICK_EXECUTION: "tick_execution",
        }[self]


@dataclass(frozen=True)
class TierBudgetConfig:
    """Per-tier budget configuration — tokens per refresh interval."""

    tier: InferenceTier
    tokens_per_refresh: int
    warn_fraction: float = 0.80


DEFAULT_TIER_BUDGETS: Final = (
    TierBudgetConfig(InferenceTier.T1_CLAIM_AGENDA, tokens_per_refresh=20_000),
    TierBudgetConfig(InferenceTier.T2_ARC_PLANNER, tokens_per_refresh=50_000),
    TierBudgetConfig(InferenceTier.T3_BLOCK_SCHEDULER, tokens_per_refresh=40_000),
    TierBudgetConfig(InferenceTier.T4_ACTIVITY_SELECTOR, tokens_per_refresh=80_000),
    TierBudgetConfig(InferenceTier.T5_TICK_EXECUTION, tokens_per_refresh=20_000),
)
"""Bundle 9 §4 default hourly budgets. Sums to 210k tokens/hour — tunable."""


class BudgetExhausted(RuntimeError):
    """Raised when a tier has no tokens remaining this interval."""

    def __init__(self, tier: InferenceTier, requested: int, remaining: int) -> None:
        super().__init__(
            f"tier {tier.label} budget exhausted: requested={requested} remaining={remaining}"
        )
        self.tier = tier
        self.requested = requested
        self.remaining = remaining


@dataclass
class _TierState:
    config: TierBudgetConfig
    tokens_consumed: int = 0
    last_refresh_ts: float = 0.0
    warned_this_interval: bool = False

    @property
    def remaining(self) -> int:
        return max(0, self.config.tokens_per_refresh - self.tokens_consumed)

    @property
    def consumed_fraction(self) -> float:
        if self.config.tokens_per_refresh == 0:
            return 1.0
        return self.tokens_consumed / self.config.tokens_per_refresh


class InferenceBudgetAllocator:
    """Thread-safe token bucket allocator per tier.

    Callers invoke :meth:`reserve` before dispatching an LLM call with
    the expected output-token count. If the tier's bucket has enough
    tokens, the call is allowed and the budget is debited; otherwise
    :class:`BudgetExhausted` is raised and the caller's degradation
    handler takes over.

    Buckets refresh every ``refresh_seconds`` (default 1h). The refresh
    is lazy — consumption is reset on the next ``reserve`` call after
    the interval boundary rather than on a background timer. This keeps
    the allocator dependency-free and trivially testable.
    """

    def __init__(
        self,
        *,
        configs: tuple[TierBudgetConfig, ...] = DEFAULT_TIER_BUDGETS,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        now_fn: Callable[[], float] | None = None,
        warn_fn: Callable[[InferenceTier, float], None] | None = None,
    ) -> None:
        self._refresh_seconds = refresh_seconds
        self._now_fn = now_fn or time.time
        self._warn_fn = warn_fn
        self._lock = threading.Lock()
        now = self._now_fn()
        self._tiers: dict[InferenceTier, _TierState] = {
            c.tier: _TierState(config=c, last_refresh_ts=now) for c in configs
        }

    def reserve(self, tier: InferenceTier, tokens: int) -> None:
        """Reserve ``tokens`` for a tier's upcoming call.

        Raises :class:`BudgetExhausted` if not enough budget remains.
        Fires the ``warn_fn`` callback once per interval when
        consumption crosses the tier's warn threshold.
        """
        if tokens < 0:
            raise ValueError(f"tokens must be non-negative, got {tokens}")
        with self._lock:
            state = self._tiers[tier]
            self._maybe_refresh(state)
            if tokens > state.remaining:
                raise BudgetExhausted(
                    tier=tier,
                    requested=tokens,
                    remaining=state.remaining,
                )
            state.tokens_consumed += tokens
            if (
                not state.warned_this_interval
                and state.consumed_fraction >= state.config.warn_fraction
                and self._warn_fn is not None
            ):
                state.warned_this_interval = True
                self._warn_fn(tier, state.consumed_fraction)

    def remaining(self, tier: InferenceTier) -> int:
        with self._lock:
            state = self._tiers[tier]
            self._maybe_refresh(state)
            return state.remaining

    def consumed_fraction(self, tier: InferenceTier) -> float:
        with self._lock:
            state = self._tiers[tier]
            self._maybe_refresh(state)
            return state.consumed_fraction

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        """Return a JSON-serializable snapshot of current tier state.

        Intended for the metrics exporter + ``/dev/shm`` publication.
        """
        with self._lock:
            return {
                tier.label: {
                    "tokens_per_refresh": state.config.tokens_per_refresh,
                    "tokens_consumed": state.tokens_consumed,
                    "remaining": state.remaining,
                    "consumed_fraction": round(state.consumed_fraction, 4),
                    "last_refresh_ts": state.last_refresh_ts,
                }
                for tier, state in self._tiers.items()
            }

    def _maybe_refresh(self, state: _TierState) -> None:
        now = self._now_fn()
        if now - state.last_refresh_ts >= self._refresh_seconds:
            state.tokens_consumed = 0
            state.last_refresh_ts = now
            state.warned_this_interval = False
