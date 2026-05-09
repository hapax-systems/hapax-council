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
import math
import os
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
    """A single dimension measurement.

    Phase A posterior promotion (audit-3-fix-3): ``sigma`` and ``n`` are
    additive fields with backward-compatible defaults.  ``sigma=0.0``
    means "treat as point estimate" (legacy behavior); downstream
    consumers that don't inspect sigma/n are unchanged.

    Phase C will introduce a posterior-aware stance aggregator gated on
    ``HAPAX_STIMMUNG_POSTERIOR_STANCE=1``; until then, sigma and n are
    informational only (surfaced in format_for_prompt and chronicle).
    """

    value: float = 0.0  # 0.0 = good, 1.0 = bad
    trend: str = "stable"  # rising | falling | stable
    freshness_s: float = 0.0  # seconds since last update
    sigma: float = 0.0  # posterior std-dev (0.0 = point estimate)
    n: int = 1  # sample count in the rolling window

    def exceeds_with_confidence(self, threshold: float, *, confidence: float = 0.7) -> bool:
        """Return True if P(value > threshold) >= confidence.

        Uses the Gaussian CDF approximation when sigma > 0. Falls back
        to simple comparison (value >= threshold) when sigma == 0 (point
        estimate / legacy behavior).

        This is the Phase C threshold gate: callers can replace
        ``dim.value >= threshold`` with
        ``dim.exceeds_with_confidence(threshold, confidence=0.7)``
        to get sigma-aware probabilistic gating.
        """
        if self.sigma <= 0:
            return self.value >= threshold
        # P(value > threshold) = 1 - Φ((threshold - value) / sigma)
        z = (threshold - self.value) / self.sigma
        # Approximate Gaussian CDF via math.erfc
        p_exceeds = 0.5 * math.erfc(z / math.sqrt(2.0))
        return p_exceeds >= confidence


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
    # Continuous-Loop Research Cadence §3.1 — 12th dimension.
    # Audience engagement (0-1, higher = more engaged chat) derived from
    # the structural-analyzer SHM at /dev/shm/hapax-chat-signals.json.
    # Weight: cognitive (0.3×) — epistemic state about the audience, not
    # a direct physiological or infrastructure signal.
    audience_engagement: DimensionReading = Field(default_factory=DimensionReading)

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
            elif dim.sigma > 0:
                lines.append(f"  {name}: {dim.value:.2f}±{dim.sigma:.2f} ({dim.trend}, n={dim.n})")
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
    "audience_engagement",
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

# Chronicle salience floor for stance transitions, by destination stance.
# All values >= 0.7 (the chronicle-ticker ward's _SALIENCE_THRESHOLD) so
# every stance change surfaces; severity lifts the value so downstream
# consumers that rank by salience can prefer transitions toward critical
# over routine recoveries.
_STANCE_TRANSITION_SALIENCE: dict[str, float] = {
    "critical": 1.0,
    "degraded": 0.9,
    "cautious": 0.8,
    "nominal": 0.75,
}


def dimension_spike_salience(value: float) -> float:
    """Salience for a ``dimension.spike`` chronicle event.

    Spikes only fire when ``value`` is in [0, 0.3] ∪ [0.7, 1.0], so
    ``0.5 + |value − 0.5|`` always lands in [0.7, 1.0] — at or above
    the 0.7 floor the chronicle-ticker ward's ``_is_lore_worthy``
    helper requires. Values further from the 0.5 baseline rank higher.
    """
    return round(min(1.0, 0.5 + abs(value - 0.5)), 3)


def stance_transition_salience(to_stance: str) -> float:
    """Salience for a ``stance.changed`` chronicle event.

    Lookup by destination stance, defaulting to 0.85 for any stance
    name not in :data:`_STANCE_TRANSITION_SALIENCE`. The default
    keeps every transition surface-worthy under the 0.7 floor.
    """
    return _STANCE_TRANSITION_SALIENCE.get(to_stance, 0.85)


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
        # Welford online variance state per-dimension: (count, mean, M2)
        # Used for Phase B posterior sigma. Tracks the rolling window
        # (same maxlen=5 as _windows) via reset-on-overflow.
        self._welford: dict[str, tuple[int, float, float]] = {
            name: (0, 0.0, 0.0) for name in _DIMENSION_NAMES
        }
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

    def update_audio_self_perception(
        self,
        *,
        rms_dbfs: float = -60.0,
        silence_ratio: float = 1.0,
        witness_age_s: float = 0.0,
        witness_error: str | None = None,
        classification: str = "",
    ) -> None:
        """Update from broadcast egress audio self-perception.

        Closes the audio self-perception loop: Hapax hears its own
        broadcast output and feeds the measurement back into stimmung.

        Routes through existing dimensions:
        - health: audio chain liveness (witness fresh + non-silent)
        - error_rate: audio faults (clipping, noise, witness errors)

        Args:
            rms_dbfs: RMS level in dBFS from egress loopback witness.
            silence_ratio: Fraction of samples below silence floor (0-1).
            witness_age_s: Seconds since last egress witness write.
            witness_error: Error string from witness producer (None = OK).
            classification: Signal classification at OBS-bound stage
                (MUSIC_VOICE, TONE, NOISE, SILENT, CLIPPING, or empty).
        """
        # Audio health: 0.0 = healthy chain, 1.0 = dead/broken.
        # Witness staleness (> 30s = stale, > 120s = dead)
        if witness_error:
            audio_health = 0.8
        elif witness_age_s > 120:
            audio_health = 1.0
        elif witness_age_s > 30:
            audio_health = 0.5
        elif silence_ratio > 0.95:
            audio_health = 0.6
        elif silence_ratio > 0.8:
            audio_health = 0.3
        else:
            audio_health = 0.0

        self._record("health", audio_health)

        # Audio error contribution: clipping/noise at OBS stage is a fault.
        classification_upper = classification.upper()
        if classification_upper == "CLIPPING":
            audio_error = 0.9
        elif classification_upper == "NOISE":
            audio_error = 0.5
        elif classification_upper == "SILENT" and silence_ratio > 0.95:
            audio_error = 0.4
        elif witness_error:
            audio_error = 0.6
        else:
            audio_error = 0.0

        if audio_error > 0:
            self._record("error_rate", audio_error)

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

    def update_audience_engagement(self, engagement: float) -> None:
        """Update audience-engagement reading from the chat structural analyzer.

        Args:
            engagement: 0-1 score where 1.0 = highly engaged audience. Inverted
                for stimmung convention (where 0.0 = good, 1.0 = bad): a quiet
                audience reads as high stimmung ``audience_engagement``
                because from the system's perspective, the cognitive state
                of "no audience attention" warrants a stance response
                (e.g., shift toward ``study`` / ``silence``).

        Continuous-Loop Research Cadence §3.1. Source: engagement reducer
        over ``/dev/shm/hapax-chat-signals.json`` (producer: Phase 9 §3.1
        structural analyzer sink).
        """
        value = 1.0 - max(0.0, min(1.0, engagement))
        self._record("audience_engagement", value)

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

            # Derive sigma from Welford state
            w_count, _w_mean, w_m2 = self._welford[name]
            if w_count >= 2:
                variance = w_m2 / (w_count - 1)  # sample variance
                sigma = variance**0.5
            else:
                sigma = 0.0

            dimensions[name] = DimensionReading(
                value=round(value, 3),
                trend=trend,
                freshness_s=round(freshness, 1),
                sigma=round(sigma, 4),
                n=max(1, w_count),
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
                        # ``salience`` is read by the chronicle-ticker
                        # ward (``_is_lore_worthy``) and any downstream
                        # consumer that filters / ranks events.
                        spike_salience = dimension_spike_salience(reading.value)
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
                                    "sigma": round(reading.sigma, 4),
                                    "n": reading.n,
                                    "previous_value": round(prev, 3) if prev is not None else None,
                                    "salience": spike_salience,
                                },
                            )
                        )
            self._prev_chronicle_dims = {
                name: reading.value for name, reading in dimensions.items()
            }
        except Exception:
            pass  # Chronicle unavailable — non-fatal

        _prev_stance = self._last_stance
        # Posterior-aware stance aggregation is the default (cc-task
        # dimension-reading-posterior-promotion, 2026-05-04). Setting
        # ``HAPAX_STIMMUNG_POSTERIOR_STANCE=0`` falls back to the legacy
        # point-estimate ``_compute_stance`` for emergency rollback;
        # any other value (including unset) uses the posterior path.
        _use_posterior = os.environ.get("HAPAX_STIMMUNG_POSTERIOR_STANCE", "1") != "0"
        if _use_posterior:
            raw_stance = self._compute_stance_posterior(dimensions)
        else:
            raw_stance = self._compute_stance(dimensions)
        stance = self._apply_hysteresis(raw_stance)

        # Chronicle: record stance transitions
        if _prev_stance != stance:
            try:
                _tid, _sid = current_otel_ids()
                # Salience by destination severity — every stance
                # transition is lore-worthy (>= 0.7), but transitions
                # toward critical / degraded carry more weight than
                # routine recoveries.
                stance_salience = stance_transition_salience(stance)
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
                            "salience": stance_salience,
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
        """Record a reading for a dimension.

        Also updates the Welford online variance tracker for the
        dimension. The Welford state is reset when the rolling window
        overflows (maxlen=5) to keep sigma tracking only the recent
        window, not the entire history.
        """
        now = time.monotonic()
        clamped = max(0.0, min(1.0, value))
        window = self._windows[dimension]
        was_full = len(window) == window.maxlen
        window.append((now, clamped))
        self._last_update[dimension] = now

        # Welford update — reset when window wraps to keep sigma fresh
        count, mean, m2 = self._welford[dimension]
        if was_full:
            # Window just dropped the oldest sample; recompute from scratch
            vals = [v for _, v in window]
            n = len(vals)
            if n > 0:
                new_mean = sum(vals) / n
                new_m2 = sum((v - new_mean) ** 2 for v in vals)
                self._welford[dimension] = (n, new_mean, new_m2)
            else:
                self._welford[dimension] = (0, 0.0, 0.0)
        else:
            # Normal Welford incremental update
            count += 1
            delta = clamped - mean
            mean += delta / count
            delta2 = clamped - mean
            m2 += delta * delta2
            self._welford[dimension] = (count, mean, m2)

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

        # SEEKING: fires from NOMINAL or CAUTIOUS when exploration_deficit is high.
        # Audit R6 (cc-task seeking-stance-gate-relax, 2026-05-02): the prior
        # `worst == NOMINAL` gate was too strict — common operational noise
        # (LLM cost pressure, transient resource pressure, slight perception
        # confidence dips) leaves worst at CAUTIOUS for sustained periods,
        # suppressing SEEKING entirely even when exploration_deficit is well
        # above 0.35 with rising trend. CAUTIOUS represents tolerable
        # degradation that does NOT signal infrastructure breakage; pursuing
        # exploration during CAUTIOUS is safe (and the surface needs the
        # variance modulation). DEGRADED+ continues to block SEEKING — those
        # signal real infrastructure problems where exploration would compete
        # with recovery.
        if worst in (Stance.NOMINAL, Stance.CAUTIOUS):
            exploration = dimensions.get("exploration_deficit", DimensionReading())
            if exploration.freshness_s <= _STALE_THRESHOLD_S and exploration.value > 0.35:
                return Stance.SEEKING

        return worst

    @staticmethod
    def _compute_stance_posterior(
        dimensions: dict[str, DimensionReading],
    ) -> Stance:
        """Posterior-aware stance aggregator (Phase C).

        Instead of gating on ``effective >= threshold``, gates on
        ``P(value > threshold) >= confidence_cutoff`` under a
        Normal(value, sigma) model. When sigma=0, this is bit-identical
        to the legacy ``_compute_stance``.

        Confidence cutoffs per stance level:
        - CAUTIOUS: P >= 0.7 (moderate confidence)
        - DEGRADED: P >= 0.85 (high confidence)
        - CRITICAL: P >= 0.95 (very high confidence)

        A noisy single-sample spike (high mean, high sigma) will NOT
        immediately escalate — Bayesian humility under measurement noise.

        Activated only when ``HAPAX_STIMMUNG_POSTERIOR_STANCE=1``.
        """
        # Per-stance confidence cutoffs
        _CONFIDENCE_CAUTIOUS = 0.7
        _CONFIDENCE_DEGRADED = 0.85
        _CONFIDENCE_CRITICAL = 0.95

        worst = Stance.NOMINAL
        for name, dim in dimensions.items():
            if dim.freshness_s > _STALE_THRESHOLD_S:
                continue
            if name == "exploration_deficit":
                continue

            effective_value = dim.value
            effective_sigma = dim.sigma
            if name in _BIOMETRIC_DIMENSION_NAMES:
                effective_value *= _BIOMETRIC_STANCE_WEIGHT
                effective_sigma *= _BIOMETRIC_STANCE_WEIGHT
                thresholds = _BIOMETRIC_THRESHOLDS
            elif name in _COGNITIVE_DIMENSION_NAMES:
                effective_value *= _COGNITIVE_STANCE_WEIGHT
                effective_sigma *= _COGNITIVE_STANCE_WEIGHT
                thresholds = _COGNITIVE_THRESHOLDS
            else:
                thresholds = _INFRA_THRESHOLDS

            # Build a synthetic DimensionReading for the effective values
            eff_dim = DimensionReading(value=effective_value, sigma=effective_sigma, n=dim.n)

            if eff_dim.exceeds_with_confidence(thresholds[2], confidence=_CONFIDENCE_CRITICAL):
                dim_stance = Stance.CRITICAL
            elif eff_dim.exceeds_with_confidence(thresholds[1], confidence=_CONFIDENCE_DEGRADED):
                dim_stance = Stance.DEGRADED
            elif eff_dim.exceeds_with_confidence(thresholds[0], confidence=_CONFIDENCE_CAUTIOUS):
                dim_stance = Stance.CAUTIOUS
            else:
                dim_stance = Stance.NOMINAL

            if _STANCE_ORDER[dim_stance] > _STANCE_ORDER[worst]:
                worst = dim_stance

        # SEEKING: same logic as legacy (exploration_deficit gate)
        if worst in (Stance.NOMINAL, Stance.CAUTIOUS):
            exploration = dimensions.get("exploration_deficit", DimensionReading())
            if exploration.freshness_s <= _STALE_THRESHOLD_S and exploration.value > 0.35:
                return Stance.SEEKING

        return worst
