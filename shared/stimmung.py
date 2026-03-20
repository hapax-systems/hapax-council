"""SystemStimmung — unified self-state vector for system self-awareness.

Pure-logic module: no I/O, no threading, no network. Aggregates readings
from existing data sources (health, GPU, Langfuse, engine, perception)
and operator biometrics (HR, HRV, EDA, sleep, activity) into a single
Stimmung snapshot that colors system behavior.

9 dimensions (6 infrastructure + 3 biometric), each a DimensionReading
with value/trend/freshness. Overall stance derived from worst non-stale
dimension. Biometric dimensions use 0.5× weight so system stance remains
primarily infrastructure-driven.
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
    """Unified self-state vector — 9 dimensions + derived stance."""

    # Infrastructure dimensions (weight 1.0)
    health: DimensionReading = Field(default_factory=DimensionReading)
    resource_pressure: DimensionReading = Field(default_factory=DimensionReading)
    error_rate: DimensionReading = Field(default_factory=DimensionReading)
    processing_throughput: DimensionReading = Field(default_factory=DimensionReading)
    perception_confidence: DimensionReading = Field(default_factory=DimensionReading)
    llm_cost_pressure: DimensionReading = Field(default_factory=DimensionReading)

    # Biometric dimensions (weight 0.5 — softer thresholds, operator changes slowly)
    operator_stress: DimensionReading = Field(default_factory=DimensionReading)
    operator_energy: DimensionReading = Field(default_factory=DimensionReading)
    physiological_coherence: DimensionReading = Field(default_factory=DimensionReading)

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


_INFRA_DIMENSION_NAMES = [
    "health",
    "resource_pressure",
    "error_rate",
    "processing_throughput",
    "perception_confidence",
    "llm_cost_pressure",
]

_BIOMETRIC_DIMENSION_NAMES = [
    "operator_stress",
    "operator_energy",
    "physiological_coherence",
]

_DIMENSION_NAMES = _INFRA_DIMENSION_NAMES + _BIOMETRIC_DIMENSION_NAMES

# Biometric dimensions contribute at 0.5× weight to stance computation.
# Operator physiological state changes slowly — infrastructure should dominate.
_BIOMETRIC_STANCE_WEIGHT = 0.5

_STALE_THRESHOLD_S = 120.0  # dimensions older than this are excluded from stance

# ── Baseline Constants ───────────────────────────────────────────────────────

_ENGINE_EVENTS_PER_MIN_BASELINE = 500.0  # expected events/min at nominal load (inotify is chatty)


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
        """Update from GPU/VRAM data.

        VRAM usage below 80% is normal operation (Ollama models + YOLO +
        InsightFace). Pressure starts above 80% and scales to 1.0 at 95%.
        This prevents 65% VRAM utilization from driving degraded stance.
        """
        if total_mb <= 0:
            return
        raw_ratio = used_mb / total_mb
        # Remap: 0-80% → 0.0, 80-95% → 0.0-1.0, 95%+ → 1.0
        value = max(0.0, min(1.0, (raw_ratio - 0.80) / 0.15))
        self._record("resource_pressure", value)

    def update_engine(
        self,
        events_processed: int,
        actions_executed: int,
        errors: int,
        uptime_s: float,
    ) -> None:
        """Update from reactive engine status."""
        # Error rate — relative to total activity (events + actions).
        # A few errors with thousands of events is normal operation.
        # Zero activity = no error pressure.
        total_activity = events_processed + actions_executed
        if total_activity > 0:
            error_value = min(1.0, errors / total_activity)
        else:
            error_value = 0.0
        self._record("error_rate", error_value)

        # Processing throughput pressure — high event rate = system thrashing.
        # Low event rate = calm (nothing changing). The pressure is from
        # TOO MANY events, not too few. Previous logic was inverted.
        if uptime_s > 60 and events_processed > 0:
            events_per_min = (events_processed / uptime_s) * 60.0
            # Pressure rises when event rate exceeds baseline
            throughput_value = min(1.0, events_per_min / _ENGINE_EVENTS_PER_MIN_BASELINE)
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

    def update_biometrics(
        self,
        *,
        hrv_current: float | None = None,
        hrv_baseline: float | None = None,
        eda_active: bool = False,
        frustration_score: float = 0.0,
        sleep_quality: float | None = None,
        circadian_alignment: float = 0.5,
        activity_level: float = 0.0,
        hr_zone: float = 0.0,
        hrv_cv: float | None = None,
        skin_temp_cv: float | None = None,
    ) -> None:
        """Update biometric dimensions from watch/phone perception data.

        All inputs are optional — gracefully degrades when sensors are unavailable.
        """
        # ── operator_stress ──────────────────────────────────────────────
        # Weighted composite: 0.4×HRV_drop + 0.3×EDA_active + 0.3×frustration
        hrv_drop = 0.0
        if hrv_current is not None and hrv_baseline is not None and hrv_baseline > 0:
            # HRV drop: how far below baseline (0=at baseline, 1=50%+ below)
            ratio = hrv_current / hrv_baseline
            hrv_drop = max(0.0, min(1.0, (1.0 - ratio) * 2.0))

        eda_value = 1.0 if eda_active else 0.0
        stress = 0.4 * hrv_drop + 0.3 * eda_value + 0.3 * min(1.0, frustration_score)
        self._record("operator_stress", stress)

        # ── operator_energy ──────────────────────────────────────────────
        # Composite: 0.3×sleep + 0.3×circadian + 0.2×activity + 0.2×HR_zone
        # Inverted: 0.0 = high energy (good), 1.0 = depleted (bad)
        sleep_deficit = 1.0 - (sleep_quality if sleep_quality is not None else 0.5)
        circadian_pressure = circadian_alignment  # 0=peak, 1=worst
        activity_pressure = max(0.0, min(1.0, 1.0 - activity_level))
        hr_pressure = max(0.0, min(1.0, 1.0 - hr_zone))

        energy = (
            0.3 * sleep_deficit
            + 0.3 * circadian_pressure
            + 0.2 * activity_pressure
            + 0.2 * hr_pressure
        )
        self._record("operator_energy", energy)

        # ── physiological_coherence ──────────────────────────────────────
        # Rolling coefficient of variation — low CV = stable = good
        # 0.0 = perfectly coherent (good), 1.0 = highly variable (bad)
        coherence_values = []
        if hrv_cv is not None:
            # HRV CV: 0-10% = coherent, 30%+ = fragmented
            coherence_values.append(max(0.0, min(1.0, hrv_cv / 0.3)))
        if skin_temp_cv is not None:
            # Skin temp CV: 0-2% = stable, 10%+ = unstable
            coherence_values.append(max(0.0, min(1.0, skin_temp_cv / 0.1)))

        if coherence_values:
            coherence = sum(coherence_values) / len(coherence_values)
        else:
            coherence = 0.5  # unknown = neutral
        self._record("physiological_coherence", coherence)

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
        """Derive stance from worst non-stale dimension.

        Biometric dimensions contribute at 0.5× weight — operator state
        changes slowly and shouldn't dominate system stance.
        """
        worst = 0.0
        for name, dim in dimensions.items():
            if dim.freshness_s > _STALE_THRESHOLD_S:
                continue
            effective = dim.value
            if name in _BIOMETRIC_DIMENSION_NAMES:
                effective *= _BIOMETRIC_STANCE_WEIGHT
            worst = max(worst, effective)

        if worst >= 0.85:
            return Stance.CRITICAL
        if worst >= 0.6:
            return Stance.DEGRADED
        if worst >= 0.3:
            return Stance.CAUTIOUS
        return Stance.NOMINAL
