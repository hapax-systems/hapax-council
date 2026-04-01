"""ExplorationSignal — per-component boredom/curiosity computation.

4-layer model:
  L1: Divisive normalization (per-tick habituation per input edge)
  L2: Trace interest evaporation (decay when unchanged)
  L3: Learning progress (EMA of ControlSignal error derivative)
  L4: Phase coherence (local Kuramoto order parameter)

Pure computation, no I/O. Publish via exploration_writer.py.
"""

from __future__ import annotations

import cmath
import math
import time
from dataclasses import dataclass


def _sigmoid(x: float, k: float = 10.0) -> float:
    z = -k * x
    if z > 500:
        return 0.0
    if z < -500:
        return 1.0
    return 1.0 / (1.0 + math.exp(z))


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ── Layer 1: Divisive Normalization ──────────────────────────────────────────


class HabituationTracker:
    """Per-edge gain control via Carandini-Heeger normalization."""

    def __init__(
        self,
        edges: list[str],
        kappa: float = 1.0,
        alpha: float = 0.1,
        beta: float = 0.01,
        g_max: float = 1.0,
    ) -> None:
        self._kappa = kappa
        self._alpha = alpha
        self._beta = beta
        self._g_max = g_max
        self._weights: dict[str, float] = {e: 0.0 for e in edges}

    def update(self, edge: str, current: float, previous: float, std_dev: float) -> None:
        """Feed one tick of trace data for an edge."""
        if edge not in self._weights:
            return
        delta = abs(current - previous)
        threshold = max(std_dev, 1e-9)
        predictable = 1.0 if delta < threshold else 0.0
        w = self._weights[edge]
        self._weights[edge] = w + self._alpha * predictable - self._beta * w

    def decay_all(self) -> None:
        """Apply natural decay without new input (sensitivity recovery)."""
        for e in self._weights:
            self._weights[e] *= 1.0 - self._beta

    def gain(self, edge: str) -> float:
        w = self._weights.get(edge, 0.0)
        return self._g_max / (1.0 + self._kappa * max(w, 0.0))

    def mean_habituation(self) -> float:
        if not self._weights:
            return 0.0
        gains = [self.gain(e) for e in self._weights]
        return 1.0 - sum(gains) / (len(gains) * self._g_max)

    def max_novelty(self) -> tuple[str | None, float]:
        if not self._weights:
            return None, 0.0
        best_edge = max(self._weights, key=lambda e: self.gain(e))
        return best_edge, self.gain(best_edge) / self._g_max


# ── Layer 2: Trace Interest Evaporation ──────────────────────────────────────


class InterestTracker:
    """Per-trace interest decay with adaptive evaporation."""

    def __init__(
        self,
        traces: list[str],
        rho_base: float = 0.005,
        rho_adapt: float = 0.020,
        t_patience: float = 300.0,
    ) -> None:
        self._rho_base = rho_base
        self._rho_adapt = rho_adapt
        self._t_patience = t_patience
        self._last_value: dict[str, float | None] = {t: None for t in traces}
        self._time_unchanged: dict[str, float] = {t: 0.0 for t in traces}

    def tick(self, trace: str, current: float, std_dev: float, elapsed_s: float) -> None:
        if trace not in self._time_unchanged:
            return
        last = self._last_value[trace]
        threshold = max(std_dev, 1e-9)
        if last is not None and abs(current - last) > threshold:
            self._time_unchanged[trace] = 0.0
            self._last_value[trace] = current
        else:
            self._time_unchanged[trace] += elapsed_s
            if last is None:
                self._last_value[trace] = current

    def interest(self, trace: str) -> float:
        t_unchanged = self._time_unchanged.get(trace, 0.0)
        rho = self._rho_base + self._rho_adapt * _sigmoid(t_unchanged - self._t_patience)
        return math.exp(-rho * t_unchanged)

    def mean_interest(self) -> float:
        if not self._time_unchanged:
            return 1.0
        return sum(self.interest(t) for t in self._time_unchanged) / len(self._time_unchanged)

    def stagnation_duration(self) -> float:
        if not self._time_unchanged:
            return 0.0
        return min(self._time_unchanged.values())


# ── Layer 3: Learning Progress ───────────────────────────────────────────────


class LearningProgressTracker:
    """EMA of ControlSignal error + first derivative."""

    def __init__(self, alpha_ema: float = 0.05) -> None:
        self._alpha = alpha_ema
        self._chronic_error: float = 0.0
        self._prev_chronic: float = 0.0
        self._initialized: bool = False

    def update(self, error: float) -> None:
        if not self._initialized:
            self._chronic_error = error
            self._initialized = True
            return
        self._prev_chronic = self._chronic_error
        self._chronic_error = self._alpha * error + (1.0 - self._alpha) * self._chronic_error

    @property
    def chronic_error(self) -> float:
        return self._chronic_error

    @property
    def error_improvement_rate(self) -> float:
        """Positive = learning (error decreasing). Negative = degrading."""
        return self._prev_chronic - self._chronic_error


# ── Layer 4: Phase Coherence ─────────────────────────────────────────────────


class CoherenceTracker:
    """Local Kuramoto order parameter with reading neighbors."""

    def __init__(
        self,
        neighbors: list[str],
        coherence_threshold: float = 0.8,
    ) -> None:
        self._neighbors = neighbors
        self._coherence_threshold = coherence_threshold
        self._phases: dict[str, float] = {}
        self._dwell: float = 0.0

    def update_phases(self, phases: dict[str, float]) -> None:
        self._phases = {n: phases.get(n, 0.0) for n in self._neighbors}

    def local_coherence(self) -> float:
        if not self._phases:
            return 0.0
        n = len(self._phases)
        total = sum(cmath.exp(1j * p) for p in self._phases.values())
        return abs(total) / n

    def tick(self, elapsed_s: float) -> None:
        if self.local_coherence() > self._coherence_threshold:
            self._dwell += elapsed_s
        else:
            self._dwell = 0.0

    def dwell_time_in_coherence(self) -> float:
        return self._dwell


# ── Composite Signal ─────────────────────────────────────────────────────────


def compute_boredom_index(
    mean_habituation: float,
    mean_trace_interest: float,
    stagnation_duration: float,
    dwell_time_in_coherence: float,
    t_patience: float = 300.0,
) -> float:
    """Weighted composite boredom score: 0 = engaged, 1 = maximally bored."""
    return (
        0.30 * mean_habituation
        + 0.30 * (1.0 - mean_trace_interest)
        + 0.20 * _clamp(stagnation_duration / t_patience)
        + 0.20 * _clamp(dwell_time_in_coherence / t_patience)
    )


def compute_curiosity_index(
    chronic_error: float,
    error_improvement_rate: float,
    max_novelty_score: float,
    local_coherence: float,
) -> float:
    """Opportunity for learning: 0 = none, 1 = maximum."""
    reorg = _clamp(chronic_error) * (1.0 if error_improvement_rate <= 0 else 0.5)
    novelty = max_novelty_score
    desync = 1.0 - local_coherence
    return max(reorg, novelty, desync)


@dataclass(frozen=True)
class ExplorationSignal:
    """Per-component boredom/curiosity state."""

    component: str
    timestamp: float
    mean_habituation: float
    max_novelty_edge: str | None
    max_novelty_score: float
    error_improvement_rate: float
    chronic_error: float
    mean_trace_interest: float
    stagnation_duration: float
    local_coherence: float
    dwell_time_in_coherence: float
    boredom_index: float
    curiosity_index: float

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "timestamp": self.timestamp,
            "mean_habituation": round(self.mean_habituation, 4),
            "max_novelty_edge": self.max_novelty_edge,
            "max_novelty_score": round(self.max_novelty_score, 4),
            "error_improvement_rate": round(self.error_improvement_rate, 6),
            "chronic_error": round(self.chronic_error, 4),
            "mean_trace_interest": round(self.mean_trace_interest, 4),
            "stagnation_duration": round(self.stagnation_duration, 1),
            "local_coherence": round(self.local_coherence, 4),
            "dwell_time_in_coherence": round(self.dwell_time_in_coherence, 1),
            "boredom_index": round(self.boredom_index, 4),
            "curiosity_index": round(self.curiosity_index, 4),
        }


def compute_exploration_signal(
    component: str,
    habituation: HabituationTracker,
    interest: InterestTracker,
    learning: LearningProgressTracker,
    coherence: CoherenceTracker,
    t_patience: float = 300.0,
) -> ExplorationSignal:
    """Compose all 4 layers into a single ExplorationSignal."""
    max_edge, max_score = habituation.max_novelty()
    mh = habituation.mean_habituation()
    mi = interest.mean_interest()
    sd = interest.stagnation_duration()
    lc = coherence.local_coherence()
    dc = coherence.dwell_time_in_coherence()

    bi = compute_boredom_index(mh, mi, sd, dc, t_patience)
    ci = compute_curiosity_index(
        learning.chronic_error, learning.error_improvement_rate, max_score, lc
    )

    return ExplorationSignal(
        component=component,
        timestamp=time.time(),
        mean_habituation=mh,
        max_novelty_edge=max_edge,
        max_novelty_score=max_score,
        error_improvement_rate=learning.error_improvement_rate,
        chronic_error=learning.chronic_error,
        mean_trace_interest=mi,
        stagnation_duration=sd,
        local_coherence=lc,
        dwell_time_in_coherence=dc,
        boredom_index=bi,
        curiosity_index=ci,
    )
