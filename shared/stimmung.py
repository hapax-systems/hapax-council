"""SystemStimmung — unified self-state vector for system self-awareness.

Pure-logic module: no I/O, no threading, no network. Aggregates readings
from existing data sources (health, GPU, Langfuse, engine, perception)
into a single Stimmung snapshot that colors system behavior.

6 dimensions, each a DimensionReading with value/trend/freshness.
Overall stance derived from worst non-stale dimension.
"""

from __future__ import annotations

import time
from collections import deque
from enum import StrEnum

from pydantic import BaseModel, Field

# ── Stance ───────────────────────────────────────────────────────────────────


class Stance(StrEnum):
    """System-wide self-assessment."""

    NOMINAL = "nominal"
    CAUTIOUS = "cautious"
    DEGRADED = "degraded"
    CRITICAL = "critical"


# ── Dimension Reading ────────────────────────────────────────────────────────


class DimensionReading(BaseModel, frozen=True):
    """A single dimension measurement."""

    value: float = 0.0  # 0.0 = good, 1.0 = bad
    trend: str = "stable"  # rising | falling | stable
    freshness_s: float = 0.0  # seconds since last update


# ── SystemStimmung ───────────────────────────────────────────────────────────


class SystemStimmung(BaseModel):
    """Unified self-state vector — 6 dimensions + derived stance."""

    health: DimensionReading = Field(default_factory=DimensionReading)
    resource_pressure: DimensionReading = Field(default_factory=DimensionReading)
    error_rate: DimensionReading = Field(default_factory=DimensionReading)
    processing_throughput: DimensionReading = Field(default_factory=DimensionReading)
    perception_confidence: DimensionReading = Field(default_factory=DimensionReading)
    llm_cost_pressure: DimensionReading = Field(default_factory=DimensionReading)
    overall_stance: Stance = Stance.NOMINAL
    timestamp: float = 0.0

    def format_for_prompt(self) -> str:
        """Compact text block for system prompt injection."""
        lines = [f"System stance: {self.overall_stance.value}"]
        for name in _DIMENSION_NAMES:
            dim: DimensionReading = getattr(self, name)
            if dim.freshness_s > _STALE_THRESHOLD_S:
                lines.append(f"  {name}: stale ({dim.freshness_s:.0f}s)")
            else:
                lines.append(f"  {name}: {dim.value:.2f} ({dim.trend})")
        return "\n".join(lines)

    def modulation_factor(self, dimension: str) -> float:
        """Return a modulation factor for a dimension: 1.0 (nominal) → 0.3 (critical).

        Used by downstream consumers to scale behavior intensity.
        """
        dim: DimensionReading = getattr(self, dimension, DimensionReading())
        if dim.value < 0.3:
            return 1.0
        if dim.value < 0.6:
            return 0.7
        if dim.value < 0.85:
            return 0.5
        return 0.3

    @property
    def non_nominal_dimensions(self) -> dict[str, DimensionReading]:
        """Return dimensions with value >= 0.3 and not stale."""
        result = {}
        for name in _DIMENSION_NAMES:
            dim: DimensionReading = getattr(self, name)
            if dim.value >= 0.3 and dim.freshness_s <= _STALE_THRESHOLD_S:
                result[name] = dim
        return result


_DIMENSION_NAMES = [
    "health",
    "resource_pressure",
    "error_rate",
    "processing_throughput",
    "perception_confidence",
    "llm_cost_pressure",
]

_STALE_THRESHOLD_S = 120.0  # dimensions older than this are excluded from stance

# ── Baseline Constants ───────────────────────────────────────────────────────

_ENGINE_EVENTS_PER_MIN_BASELINE = 10.0  # expected events/min at nominal load


# ── StimmungCollector ────────────────────────────────────────────────────────


class StimmungCollector:
    """Collects raw readings and produces SystemStimmung snapshots.

    Pure logic — no I/O. Callers feed in data via update_*() methods,
    then call snapshot() to get the current state.

    Keeps a rolling window of last 5 readings per dimension for trend detection.
    """

    def __init__(self) -> None:
        self._windows: dict[str, deque[tuple[float, float]]] = {
            name: deque(maxlen=5) for name in _DIMENSION_NAMES
        }
        self._last_update: dict[str, float] = {}

    def update_health(
        self, healthy: int, total: int, failed_checks: list[str] | None = None
    ) -> None:
        """Update from health check data."""
        if total <= 0:
            return
        value = 1.0 - (healthy / total)
        self._record("health", value)

    def update_gpu(self, used_mb: float, total_mb: float) -> None:
        """Update from GPU/VRAM data."""
        if total_mb <= 0:
            return
        value = used_mb / total_mb
        self._record("resource_pressure", value)

    def update_engine(
        self,
        events_processed: int,
        actions_executed: int,
        errors: int,
        uptime_s: float,
    ) -> None:
        """Update from reactive engine status."""
        # Error rate
        total_actions = max(1, actions_executed)
        error_value = min(1.0, errors / total_actions)
        self._record("error_rate", error_value)

        # Processing throughput — events/min vs baseline
        # Low throughput is NOT stress when the engine is simply idle
        # (no filesystem changes = no events = normal). Throughput
        # pressure only matters when there ARE events to process.
        if uptime_s > 60 and actions_executed > 0:
            events_per_min = (events_processed / uptime_s) * 60.0
            throughput_ratio = min(1.0, events_per_min / _ENGINE_EVENTS_PER_MIN_BASELINE)
            throughput_value = 1.0 - throughput_ratio
        else:
            throughput_value = 0.0  # idle engine = no pressure
        self._record("processing_throughput", throughput_value)

    def update_perception(self, freshness_s: float, confidence: float = 1.0) -> None:
        """Update from perception state freshness and optional confidence.

        freshness_s: seconds since last perception update.
        confidence: aggregate backend confidence (0.0-1.0), 1.0 = all fresh.
        """
        # Staleness: 0s = 0.0, 30s+ = 1.0
        stale_value = min(1.0, freshness_s / 30.0)
        # Combine staleness and confidence deficit
        value = max(stale_value, 1.0 - confidence)
        self._record("perception_confidence", value)

    def update_langfuse(
        self,
        daily_cost: float = 0.0,
        error_count: int = 0,
        total_traces: int = 0,
    ) -> None:
        """Update from Langfuse sync state."""
        # Cost pressure: $0 = 0.0, $50+ = 1.0
        # Max plan is effectively unlimited for Claude; $50 threshold
        # only triggers on heavy API fallback usage.
        cost_value = min(1.0, daily_cost / 50.0)
        # Error ratio
        error_ratio = min(1.0, error_count / max(1, total_traces)) if total_traces > 0 else 0.0
        # Combined: max of cost and error pressure
        value = max(cost_value, error_ratio)
        self._record("llm_cost_pressure", value)

    def snapshot(self, now: float | None = None) -> SystemStimmung:
        """Produce a SystemStimmung from current readings."""
        if now is None:
            now = time.monotonic()

        dimensions = {}
        for name in _DIMENSION_NAMES:
            window = self._windows[name]
            last_update = self._last_update.get(name, 0.0)
            freshness = now - last_update if last_update > 0 else _STALE_THRESHOLD_S + 1

            if window:
                value = window[-1][1]  # most recent value
                trend = self._compute_trend(window)
            else:
                value = 0.0
                trend = "stable"

            dimensions[name] = DimensionReading(
                value=round(value, 3),
                trend=trend,
                freshness_s=round(freshness, 1),
            )

        stance = self._compute_stance(dimensions)

        return SystemStimmung(
            **dimensions,
            overall_stance=stance,
            timestamp=now,
        )

    def _record(self, dimension: str, value: float) -> None:
        """Record a reading for a dimension."""
        now = time.monotonic()
        self._windows[dimension].append((now, max(0.0, min(1.0, value))))
        self._last_update[dimension] = now

    @staticmethod
    def _compute_trend(window: deque[tuple[float, float]]) -> str:
        """Detect trend from last 3 readings."""
        if len(window) < 3:
            return "stable"
        recent = [v for _, v in list(window)[-3:]]
        if all(recent[i] < recent[i + 1] for i in range(len(recent) - 1)):
            return "rising"
        if all(recent[i] > recent[i + 1] for i in range(len(recent) - 1)):
            return "falling"
        return "stable"

    @staticmethod
    def _compute_stance(dimensions: dict[str, DimensionReading]) -> Stance:
        """Derive stance from worst non-stale dimension."""
        worst = 0.0
        for dim in dimensions.values():
            if dim.freshness_s > _STALE_THRESHOLD_S:
                continue
            worst = max(worst, dim.value)

        if worst >= 0.85:
            return Stance.CRITICAL
        if worst >= 0.6:
            return Stance.DEGRADED
        if worst >= 0.3:
            return Stance.CAUTIOUS
        return Stance.NOMINAL
