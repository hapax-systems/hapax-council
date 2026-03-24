"""Trend engine — rate-of-change, anomaly, and projection analysis.

Tracks ~20 game state variables with EMA velocity, rolling Z-score
(Welford's online algorithm), and CUSUM shift detection.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from agents.fortress.schema import FastFortressState


@dataclass
class VariableTracker:
    """Per-variable statistics tracker."""

    values: deque[float] = field(default_factory=lambda: deque(maxlen=30))
    timestamps: deque[int] = field(default_factory=lambda: deque(maxlen=30))
    ema_rate: float = 0.0
    ewma_mean: float = 0.0
    ewma_var: float = 0.0
    n: int = 0
    cusum_pos: float = 0.0
    cusum_neg: float = 0.0

    def push(self, value: float, tick: int, alpha: float = 0.2) -> None:
        if self.values:
            prev = self.values[-1]
            prev_tick = self.timestamps[-1]
            dt = max(1, tick - prev_tick)
            raw_rate = (value - prev) / dt
            if self.n == 0:
                self.ema_rate = raw_rate
            else:
                self.ema_rate = alpha * raw_rate + (1 - alpha) * self.ema_rate
        self.values.append(value)
        self.timestamps.append(tick)
        self.n += 1
        # EWMA for Z-score
        if self.n == 1:
            self.ewma_mean = value
            self.ewma_var = 0.0
        else:
            self.ewma_mean = alpha * value + (1 - alpha) * self.ewma_mean
            self.ewma_var = alpha * (value - self.ewma_mean) ** 2 + (1 - alpha) * self.ewma_var

    def z_score(self, value: float) -> float:
        std = self.ewma_var**0.5 if self.ewma_var > 0 else 0.0
        return (value - self.ewma_mean) / std if std > 0 else 0.0

    def cusum_check(
        self,
        value: float,
        target: float,
        threshold: float = 5.0,
        drift: float = 0.5,
    ) -> str | None:
        self.cusum_pos = max(0, self.cusum_pos + value - target - drift)
        self.cusum_neg = max(0, self.cusum_neg + target - value - drift)
        if self.cusum_pos > threshold:
            self.cusum_pos = 0.0
            return "shift_up"
        if self.cusum_neg > threshold:
            self.cusum_neg = 0.0
            return "shift_down"
        return None


# Trend thresholds per variable: (rising_min, declining_max, crashing_max)
TREND_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "food_count": (0.05, -0.05, -0.15),
    "drink_count": (0.05, -0.05, -0.15),
    "population": (0.01, -0.01, -0.05),
    "most_stressed_value": (0.03, -0.02, -0.10),
    "idle_dwarf_count": (0.05, -0.05, -0.15),
}

# Variables to extract from state
TRACKED_VARIABLES: tuple[str, ...] = (
    "food_count",
    "drink_count",
    "population",
    "idle_dwarf_count",
    "most_stressed_value",
    "active_threats",
    "job_queue_length",
)


class TrendEngine:
    """Tracks trends, anomalies, and projections for fortress state variables."""

    def __init__(self) -> None:
        self._trackers: dict[str, VariableTracker] = {
            name: VariableTracker() for name in TRACKED_VARIABLES
        }

    def push(self, state: FastFortressState) -> None:
        tick = state.game_tick
        for name in TRACKED_VARIABLES:
            value = float(getattr(state, name, 0))
            self._trackers[name].push(value, tick)

    def trend(self, variable: str) -> str:
        tracker = self._trackers.get(variable)
        if not tracker or tracker.n < 3:
            return "unknown"
        current = tracker.values[-1] if tracker.values else 0
        if current == 0:
            return "stable"
        pct_rate = tracker.ema_rate * 120 / max(abs(current), 1.0)  # per 120-tick interval
        thresholds = TREND_THRESHOLDS.get(variable, (0.05, -0.05, -0.15))
        if pct_rate > thresholds[0]:
            return "rising"
        if pct_rate > thresholds[1]:
            return "stable"
        if pct_rate > thresholds[2]:
            return "declining"
        return "crashing"

    def anomalies(self) -> list[str]:
        results = []
        for name, tracker in self._trackers.items():
            if tracker.n < 5:
                continue
            current = tracker.values[-1]
            z = tracker.z_score(current)
            if abs(z) > 3.5:
                results.append(f"CRITICAL: {name} anomaly (z={z:.1f})")
            elif abs(z) > 2.5:
                results.append(f"WARNING: {name} anomaly (z={z:.1f})")
        return results

    def projections(self) -> list[str]:
        results = []
        for name in ("food_count", "drink_count"):
            tracker = self._trackers.get(name)
            if not tracker or tracker.n < 3:
                continue
            current = tracker.values[-1]
            rate = tracker.ema_rate
            if rate < 0 and current > 0:
                ticks_to_zero = int(current / abs(rate))
                days = ticks_to_zero // 1200
                results.append(f"{name} exhausted in ~{days} days at current rate")
        return results

    def trends_summary(self) -> dict[str, str]:
        return {name: self.trend(name) for name in TRACKED_VARIABLES}
