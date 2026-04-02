"""SystemStimmung — unified self-state vector for system self-awareness.

Pure-logic module: no I/O, no threading, no network. Aggregates readings
from existing data sources (health, GPU, Langfuse, engine, perception),
operator biometrics (HR, HRV, EDA, sleep, activity), and cognitive state
(grounding quality from voice sessions) into a single Stimmung snapshot
that colors system behavior.

10 dimensions (6 infrastructure + 1 cognitive + 3 biometric), each a
DimensionReading with value/trend/freshness. Overall stance derived from
worst non-stale dimension. Biometric dimensions use 0.5× weight, cognitive
dimensions use 0.3× weight, so system stance remains infrastructure-driven.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from enum import StrEnum

from pydantic import BaseModel, Field

from shared.control_signal import ControlSignal, publish_health

log = logging.getLogger("stimmung")

# ── Stance ───────────────────────────────────────────────────────────────────


class Stance(StrEnum):
    """System-wide self-assessment."""

    NOMINAL = "nominal"
    SEEKING = "seeking"
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
    """Unified self-state vector — 10 dimensions + derived stance."""

    # Infrastructure dimensions (weight 1.0)
    health: DimensionReading = Field(default_factory=DimensionReading)
    resource_pressure: DimensionReading = Field(default_factory=DimensionReading)
    error_rate: DimensionReading = Field(default_factory=DimensionReading)
    processing_throughput: DimensionReading = Field(default_factory=DimensionReading)
    perception_confidence: DimensionReading = Field(default_factory=DimensionReading)
    llm_cost_pressure: DimensionReading = Field(default_factory=DimensionReading)

    # Cognitive dimensions (weight 0.3 — epistemic state, lighter than infrastructure)
    grounding_quality: DimensionReading = Field(default_factory=DimensionReading)
    exploration_deficit: DimensionReading = Field(default_factory=DimensionReading)

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

_COGNITIVE_DIMENSION_NAMES = [
    "grounding_quality",
    "exploration_deficit",
]

_BIOMETRIC_DIMENSION_NAMES = [
    "operator_stress",
    "operator_energy",
    "physiological_coherence",
]

_DIMENSION_NAMES = _INFRA_DIMENSION_NAMES + _COGNITIVE_DIMENSION_NAMES + _BIOMETRIC_DIMENSION_NAMES

# Biometric dimensions contribute at 0.5× weight to stance computation.
# Operator physiological state changes slowly — infrastructure should dominate.
_BIOMETRIC_STANCE_WEIGHT = 0.5

# Cognitive dimensions contribute at 0.3× weight — epistemic state matters
# for conversation quality but doesn't override system health.
_COGNITIVE_STANCE_WEIGHT = 0.3

# Per-class stance thresholds applied to effective values (raw × weight).
# Infrastructure: standard thresholds.
# Biometric (0.5× weight): can reach DEGRADED at raw ≥ 0.8 (eff=0.4), never CRITICAL.
# Cognitive (0.3× weight): can reach CAUTIOUS at raw ≥ 0.5 (eff=0.15), never DEGRADED.
_INFRA_THRESHOLDS = (0.30, 0.60, 0.85)  # (CAUTIOUS, DEGRADED, CRITICAL)
_BIOMETRIC_THRESHOLDS = (0.15, 0.40, 1.01)  # CRITICAL unreachable (eff max = 0.5)
_COGNITIVE_THRESHOLDS = (0.15, 1.01, 1.01)  # DEGRADED+CRITICAL unreachable (eff max = 0.3)

# Stance ordering for comparison (StrEnum alphabetical order doesn't match severity).
# Keyed by Stance members; since Stance is StrEnum, Stance.NOMINAL == "nominal".
_STANCE_ORDER: dict[Stance, int] = {
    Stance.NOMINAL: 0,
    Stance.SEEKING: 0,  # parallel to NOMINAL, not a severity level
    Stance.CAUTIOUS: 1,
    Stance.DEGRADED: 2,
    Stance.CRITICAL: 3,
}

_STALE_THRESHOLD_S = 120.0  # dimensions older than this are excluded from stance

# ── Baseline Constants ───────────────────────────────────────────────────────

_ENGINE_EVENTS_PER_MIN_BASELINE = 500.0  # expected events/min at nominal load (inotify is chatty)


# ── StimmungCollector ────────────────────────────────────────────────────────


class StimmungCollector:
    """Collects raw readings and produces SystemStimmung snapshots.

    Pure logic — no I/O. Callers feed in data via update_*() methods,
    then call snapshot() to get the current state.

    Keeps a rolling window of last 5 readings per dimension for trend detection.

    Args:
        enable_exploration: If False, skip ExplorationTrackerBundle creation.
            Set to False when this collector is a secondary instance (e.g., in
            VLA) to prevent dual-writer interference on /dev/shm.
    """

    RECOVERY_THRESHOLD = 3  # consecutive nominal readings required to recover

    def __init__(self, *, enable_exploration: bool = True) -> None:
        self._windows: dict[str, deque[tuple[float, float]]] = {
            name: deque(maxlen=5) for name in _DIMENSION_NAMES
        }
        self._last_update: dict[str, float] = {}
        self._recovery_readings: int = 0
        self._last_stance: Stance = Stance.NOMINAL
        # Control law state
        self._cl_errors = 0
        self._cl_ok = 0
        self._cl_degraded = False
        # Exploration tracking (spec §8: kappa=0.005, T_patience=600s)
        self._exploration: ExplorationTrackerBundle | None = None
        if enable_exploration:
            from shared.exploration_tracker import ExplorationTrackerBundle

            self._exploration = ExplorationTrackerBundle(
                component="stimmung",
                edges=["stance_changes", "dimension_freshness"],
                traces=["overall_stance", "dimension_count"],
                neighbors=["dmn_pulse", "imagination"],
                kappa=0.005,
                t_patience=600.0,
                sigma_explore=0.02,
            )
        self._prev_stance_val: float = 0.0

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
        desk_activity: str = "",
        desk_energy: float = 0.0,
    ) -> None:
        """Update biometric dimensions from watch/phone/contact-mic perception data.

        All inputs are optional — gracefully degrades when sensors are unavailable.
        Desk activity and energy come from the contact mic backend.
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

        # Desk engagement from contact mic — active production reduces energy pressure
        _DESK_ENGAGEMENT = {
            "scratching": 0.8,
            "drumming": 0.7,
            "tapping": 0.5,
            "typing": 0.3,
            "active": 0.2,
        }
        desk_engagement = _DESK_ENGAGEMENT.get(desk_activity, 0.0)
        # Blend desk engagement into activity_pressure (physical engagement = less fatigue)
        if desk_engagement > 0:
            activity_pressure = min(activity_pressure, 1.0 - desk_engagement)

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

    def update_grounding_quality(self, gqi: float) -> None:
        """Update from voice grounding ledger.

        Args:
            gqi: Grounding Quality Index (0.0=poor, 1.0=excellent).
                 Inverted for stimmung (where 0.0=good, 1.0=bad).
        """
        value = 1.0 - max(0.0, min(1.0, gqi))
        self._record("grounding_quality", value)

    def update_exploration(self, deficit: float) -> None:
        """Update exploration deficit (0.0 = engaged, 1.0 = system-wide boredom)."""
        self._record("exploration_deficit", max(0.0, min(1.0, deficit)))

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

        # Chronicle: detect dimension spikes before stance computation
        try:
            from shared.chronicle import (
                ChronicleEvent,
                current_otel_ids,
            )
            from shared.chronicle import (
                record as chronicle_record,
            )

            _prev_dims = getattr(self, "_prev_chronicle_dims", {})
            for name, reading in dimensions.items():
                if reading.value > 0.7 or reading.value < 0.3:
                    prev = _prev_dims.get(name)
                    if prev is None or abs(reading.value - prev) > 0.15:
                        _tid, _sid = current_otel_ids()
                        chronicle_record(
                            ChronicleEvent(
                                ts=time.time(),
                                trace_id=_tid,
                                span_id=_sid,
                                parent_span_id=None,
                                source="stimmung",
                                event_type="dimension.spike",
                                payload={
                                    "dimension_name": name,
                                    "value": round(reading.value, 3),
                                    "trend": reading.trend,
                                    "previous_value": round(prev, 3) if prev is not None else None,
                                },
                            )
                        )
            self._prev_chronicle_dims = {
                name: reading.value for name, reading in dimensions.items()
            }
        except Exception:
            pass  # Chronicle unavailable — non-fatal

        _prev_stance = self._last_stance
        raw_stance = self._compute_stance(dimensions)
        stance = self._apply_hysteresis(raw_stance)

        # Chronicle: record stance transitions
        if _prev_stance != stance:
            try:
                _tid, _sid = current_otel_ids()
                chronicle_record(
                    ChronicleEvent(
                        ts=time.time(),
                        trace_id=_tid,
                        span_id=_sid,
                        parent_span_id=None,
                        source="stimmung",
                        event_type="stance.changed",
                        payload={
                            "from_stance": _prev_stance,
                            "to_stance": stance,
                            "dimension_values": {
                                name: round(reading.value, 3)
                                for name, reading in dimensions.items()
                            },
                        },
                    )
                )
            except Exception:
                pass  # Chronicle unavailable — non-fatal

        # Publish perceptual control signal for mesh-wide health aggregation
        _stance_error_map = {"nominal": 0.0, "cautious": 0.3, "degraded": 0.6, "critical": 1.0}
        sig = ControlSignal(
            component="stimmung",
            reference=0.0,  # target is nominal
            perception=_stance_error_map.get(stance, 0.5),
        )
        publish_health(sig)
        # Control law: error drives behavior (>50% stale dimensions)
        _stale_count = sum(1 for d in dimensions.values() if d.freshness_s > _STALE_THRESHOLD_S)
        _stale_error = _stale_count > len(dimensions) / 2
        if _stale_error:
            self._cl_errors += 1
            self._cl_ok = 0
        else:
            self._cl_errors = 0
            self._cl_ok += 1

        if self._cl_errors >= 3 and not self._cl_degraded:
            stance = "degraded"
            self._cl_degraded = True
            log.warning("Control law [stimmung]: degrading — forcing degraded stance")

        if self._cl_ok >= 5 and self._cl_degraded:
            self._cl_degraded = False
            log.info("Control law [stimmung]: recovered")

        # Exploration signal: track stance stability and dimension freshness
        stance_val = {
            "nominal": 0.0,
            "seeking": 0.1,
            "cautious": 0.3,
            "degraded": 0.6,
            "critical": 1.0,
        }.get(stance, 0.0)
        if self._exploration is not None:
            fresh_count = sum(1 for d in dimensions.values() if d.freshness_s < 120.0)
            self._exploration.feed_habituation(
                "stance_changes", stance_val, self._prev_stance_val, 0.1
            )
            self._exploration.feed_habituation(
                "dimension_freshness", float(fresh_count), float(len(dimensions)), 1.0
            )
            self._exploration.feed_interest("overall_stance", stance_val, 0.1)
            self._exploration.feed_interest("dimension_count", float(fresh_count), 1.0)
            self._exploration.feed_error(0.0 if stance in ("nominal", "seeking") else 0.5)
            self._exploration.compute_and_publish()
        self._prev_stance_val = stance_val

        return SystemStimmung(
            **dimensions,
            overall_stance=stance,
            timestamp=time.time(),
        )

    def _apply_hysteresis(self, raw_stance: Stance) -> Stance:
        """Apply hysteresis: degrade immediately, recover only after sustained improvement."""
        # SEEKING hysteresis: separate track (enter after 3, exit after 5)
        if raw_stance == Stance.SEEKING:
            self._seeking_count = getattr(self, "_seeking_count", 0) + 1
            if self._seeking_count >= 3:
                self._last_stance = Stance.SEEKING
                return Stance.SEEKING
            # Not yet sustained — return previous non-SEEKING stance
            return self._last_stance if self._last_stance != Stance.SEEKING else Stance.NOMINAL
        elif self._last_stance == Stance.SEEKING:
            self._seeking_exit_count = getattr(self, "_seeking_exit_count", 0) + 1
            if self._seeking_exit_count >= 5:
                self._seeking_count = 0
                self._seeking_exit_count = 0
                self._last_stance = raw_stance
                return raw_stance
            return Stance.SEEKING
        else:
            self._seeking_count = 0
            self._seeking_exit_count = 0

        if _STANCE_ORDER[raw_stance] >= _STANCE_ORDER[self._last_stance]:
            # Degradation (or same): apply immediately, reset recovery counter
            self._recovery_readings = 0
            self._last_stance = raw_stance
            return raw_stance

        # Raw stance is better than current — require sustained improvement
        if raw_stance == Stance.NOMINAL and self._last_stance != Stance.NOMINAL:
            self._recovery_readings += 1
            if self._recovery_readings >= self.RECOVERY_THRESHOLD:
                self._recovery_readings = 0
                self._last_stance = Stance.NOMINAL
                return Stance.NOMINAL
            return self._last_stance

        # Partial recovery (e.g. critical → cautious): apply immediately
        self._recovery_readings = 0
        self._last_stance = raw_stance
        return raw_stance

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

        Uses per-class thresholds so biometric/cognitive dimensions can
        nudge stance proportionally without dominating.
        """
        worst = Stance.NOMINAL
        for name, dim in dimensions.items():
            if dim.freshness_s > _STALE_THRESHOLD_S:
                continue
            # exploration_deficit only drives SEEKING, not severity escalation
            if name == "exploration_deficit":
                continue
            effective = dim.value
            if name in _BIOMETRIC_DIMENSION_NAMES:
                effective *= _BIOMETRIC_STANCE_WEIGHT
                thresholds = _BIOMETRIC_THRESHOLDS
            elif name in _COGNITIVE_DIMENSION_NAMES:
                effective *= _COGNITIVE_STANCE_WEIGHT
                thresholds = _COGNITIVE_THRESHOLDS
            else:
                thresholds = _INFRA_THRESHOLDS

            if effective >= thresholds[2]:
                dim_stance = Stance.CRITICAL
            elif effective >= thresholds[1]:
                dim_stance = Stance.DEGRADED
            elif effective >= thresholds[0]:
                dim_stance = Stance.CAUTIOUS
            else:
                dim_stance = Stance.NOMINAL

            if _STANCE_ORDER[dim_stance] > _STANCE_ORDER[worst]:
                worst = dim_stance

        # SEEKING: only when infrastructure is healthy AND exploration_deficit is high
        if worst == Stance.NOMINAL:
            exploration = dimensions.get("exploration_deficit", DimensionReading())
            if exploration.freshness_s <= _STALE_THRESHOLD_S and exploration.value > 0.35:
                return Stance.SEEKING

        return worst
