# Boredom & Exploration Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-component boredom/curiosity signals to the SCM, with a 4-layer computation (habituation, learning progress, trace evaporation, phase coherence), 3-level DMN escalation, a new stimmung dimension (`exploration_deficit`), and a SEEKING stance.

**Architecture:** Each of the 14 S1 components computes its own `ExplorationSignal` from its input traces. Boredom propagates through the existing impingement cascade. DMN responds with 3 escalation levels. Stimmung aggregates per-component signals into a system-wide `exploration_deficit` dimension that triggers a new SEEKING stance. Implementation follows the spec's 7-step sequence: data model → trace publication → 3 pilot components → impingement types + DMN → stimmung → full rollout → observability.

**Tech Stack:** Python 3.12, Pydantic, dataclasses, `/dev/shm` JSON traces, pytest with asyncio_mode=auto.

**Spec:** `docs/superpowers/specs/2026-04-01-boredom-exploration-signal-design.md`
**Research:** `docs/research/2026-04-01-boredom-curiosity-pct-formalization.md`

---

## File Structure

**New files:**
| File | Responsibility |
|------|---------------|
| `shared/exploration.py` | ExplorationSignal dataclass, 4 tracker classes, `compute_exploration_signal()` |
| `shared/exploration_writer.py` | Atomic `/dev/shm` publication + ExplorationReader |
| `tests/test_exploration.py` | Unit tests for all 4 trackers + composite signal |
| `tests/test_exploration_writer.py` | Publication round-trip tests |
| `tests/test_exploration_stimmung.py` | Stimmung integration + SEEKING stance tests |
| `tests/test_exploration_dmn.py` | DMN escalation response tests |

**Modified files:**
| File | Change |
|------|--------|
| `shared/impingement.py:24-30` | Add BOREDOM, CURIOSITY, EXPLORATION_OPPORTUNITY types |
| `shared/stimmung.py:31-37,57-71,112-131,462-494` | SEEKING stance, exploration_deficit dimension, threshold integration |
| `agents/dmn/pulse.py:41-58,154-296` | Exploration state tracking, L1/L2/L3 escalation responses |
| `agents/imagination.py:114-157` | CadenceController responds to SEEKING stance |
| `agents/hapax_daimonion/salience_router.py:104-274` | Novelty weight modulation in SEEKING |

---

## Task 1: ExplorationSignal Data Model + Trackers

**Files:**
- Create: `shared/exploration.py`
- Create: `tests/test_exploration.py`

### Step 1.1: Write HabituationTracker tests

- [ ] **Write test file**

```python
# tests/test_exploration.py
"""Tests for shared.exploration — ExplorationSignal computation."""

from __future__ import annotations

import math

from shared.exploration import (
    ExplorationSignal,
    HabituationTracker,
    InterestTracker,
    LearningProgressTracker,
    CoherenceTracker,
    compute_exploration_signal,
)


class TestHabituationTracker:
    def test_novel_edge_has_full_gain(self) -> None:
        ht = HabituationTracker(edges=["dmn_pulse", "salience_router"])
        assert ht.gain("dmn_pulse") == 1.0

    def test_predictable_input_reduces_gain(self) -> None:
        ht = HabituationTracker(edges=["a"], kappa=1.0, alpha=0.5, beta=0.0)
        # Feed predictable values (same each tick)
        for _ in range(10):
            ht.update("a", current=1.0, previous=1.0, std_dev=0.1)
        assert ht.gain("a") < 0.5

    def test_surprising_input_preserves_gain(self) -> None:
        ht = HabituationTracker(edges=["a"], kappa=1.0, alpha=0.5, beta=0.0)
        # Feed surprising values (large change relative to std)
        for i in range(10):
            ht.update("a", current=float(i), previous=float(i - 1), std_dev=0.1)
        assert ht.gain("a") > 0.8

    def test_natural_decay_recovers_sensitivity(self) -> None:
        ht = HabituationTracker(edges=["a"], kappa=1.0, alpha=0.5, beta=0.1)
        # Habituate
        for _ in range(20):
            ht.update("a", current=1.0, previous=1.0, std_dev=0.1)
        habituated_gain = ht.gain("a")
        # Let decay run without new input
        for _ in range(50):
            ht.decay_all()
        assert ht.gain("a") > habituated_gain

    def test_mean_habituation(self) -> None:
        ht = HabituationTracker(edges=["a", "b"], kappa=1.0, alpha=0.5, beta=0.0)
        # Habituate only edge "a"
        for _ in range(20):
            ht.update("a", current=1.0, previous=1.0, std_dev=0.1)
        mh = ht.mean_habituation()
        assert 0.0 < mh < 1.0  # one habituated, one novel

    def test_max_novelty_edge(self) -> None:
        ht = HabituationTracker(edges=["a", "b"], kappa=1.0, alpha=0.5, beta=0.0)
        for _ in range(20):
            ht.update("a", current=1.0, previous=1.0, std_dev=0.1)
        edge, score = ht.max_novelty()
        assert edge == "b"
        assert score > 0.8
```

- [ ] **Run test to verify it fails**

Run: `uv run pytest tests/test_exploration.py::TestHabituationTracker -v`
Expected: FAIL with ImportError

### Step 1.2: Implement HabituationTracker

- [ ] **Write shared/exploration.py with HabituationTracker**

```python
# shared/exploration.py
"""ExplorationSignal — per-component boredom/curiosity computation.

4-layer model:
  L1: Divisive normalization (per-tick habituation per input edge)
  L2: Learning progress (EMA of ControlSignal error derivative)
  L3: Trace interest evaporation (decay when unchanged)
  L4: Phase coherence (local Kuramoto order parameter)

Pure computation, no I/O. Publish via exploration_writer.py.
"""

from __future__ import annotations

import cmath
import math
import time
from dataclasses import dataclass, field


def _sigmoid(x: float, k: float = 10.0) -> float:
    return 1.0 / (1.0 + math.exp(-k * x))


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

    def update(
        self, edge: str, current: float, previous: float, std_dev: float
    ) -> None:
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
            self._weights[e] *= (1.0 - self._beta)

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
```

- [ ] **Run test**

Run: `uv run pytest tests/test_exploration.py::TestHabituationTracker -v`
Expected: PASS

- [ ] **Commit**

```bash
git add shared/exploration.py tests/test_exploration.py
git commit -m "feat(exploration): HabituationTracker — per-edge divisive normalization"
```

### Step 1.3: Write InterestTracker tests

- [ ] **Add to tests/test_exploration.py**

```python
class TestInterestTracker:
    def test_fresh_trace_has_full_interest(self) -> None:
        it = InterestTracker(traces=["a"], rho_base=0.005, rho_adapt=0.020, t_patience=300.0)
        assert it.interest("a") == 1.0

    def test_unchanged_trace_decays(self) -> None:
        it = InterestTracker(traces=["a"], rho_base=0.1, rho_adapt=0.0, t_patience=300.0)
        it.tick("a", current=1.0, std_dev=0.1, elapsed_s=10.0)
        assert it.interest("a") < 1.0

    def test_meaningful_change_resets_interest(self) -> None:
        it = InterestTracker(traces=["a"], rho_base=0.1, rho_adapt=0.0, t_patience=300.0)
        # Decay
        it.tick("a", current=1.0, std_dev=0.1, elapsed_s=10.0)
        decayed = it.interest("a")
        # Meaningful change
        it.tick("a", current=2.0, std_dev=0.1, elapsed_s=1.0)
        assert it.interest("a") > decayed

    def test_adaptive_evaporation_accelerates_after_patience(self) -> None:
        it = InterestTracker(traces=["a"], rho_base=0.005, rho_adapt=0.020, t_patience=10.0)
        # Before patience threshold
        it.tick("a", current=1.0, std_dev=0.1, elapsed_s=5.0)
        early = it.interest("a")
        # After patience threshold
        it2 = InterestTracker(traces=["a"], rho_base=0.005, rho_adapt=0.020, t_patience=10.0)
        it2.tick("a", current=1.0, std_dev=0.1, elapsed_s=15.0)
        late = it2.interest("a")
        assert late < early  # faster decay after patience exceeded

    def test_mean_trace_interest(self) -> None:
        it = InterestTracker(traces=["a", "b"], rho_base=0.1, rho_adapt=0.0, t_patience=300.0)
        it.tick("a", current=1.0, std_dev=0.1, elapsed_s=10.0)
        # "a" decayed, "b" fresh
        mean = it.mean_interest()
        assert 0.0 < mean < 1.0

    def test_stagnation_duration(self) -> None:
        it = InterestTracker(traces=["a", "b"], rho_base=0.005, rho_adapt=0.0, t_patience=300.0)
        it.tick("a", current=1.0, std_dev=0.1, elapsed_s=60.0)
        it.tick("b", current=1.0, std_dev=0.1, elapsed_s=30.0)
        assert it.stagnation_duration() == 30.0  # min of unchanged durations
```

- [ ] **Run to verify fails**

Run: `uv run pytest tests/test_exploration.py::TestInterestTracker -v`
Expected: FAIL

### Step 1.4: Implement InterestTracker

- [ ] **Add to shared/exploration.py**

```python
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

    def tick(
        self, trace: str, current: float, std_dev: float, elapsed_s: float
    ) -> None:
        if trace not in self._time_unchanged:
            return
        last = self._last_value[trace]
        threshold = max(std_dev, 1e-9)
        if last is not None and abs(current - last) > threshold:
            # Meaningful change — reset
            self._time_unchanged[trace] = 0.0
            self._last_value[trace] = current
        else:
            self._time_unchanged[trace] += elapsed_s
            if last is None:
                self._last_value[trace] = current

    def interest(self, trace: str) -> float:
        t_unchanged = self._time_unchanged.get(trace, 0.0)
        rho = self._rho_base + self._rho_adapt * _sigmoid(
            t_unchanged - self._t_patience
        )
        return math.exp(-rho * t_unchanged)

    def mean_interest(self) -> float:
        if not self._time_unchanged:
            return 1.0
        return sum(self.interest(t) for t in self._time_unchanged) / len(
            self._time_unchanged
        )

    def stagnation_duration(self) -> float:
        if not self._time_unchanged:
            return 0.0
        return min(self._time_unchanged.values())
```

- [ ] **Run test**

Run: `uv run pytest tests/test_exploration.py::TestInterestTracker -v`
Expected: PASS

- [ ] **Commit**

```bash
git add shared/exploration.py tests/test_exploration.py
git commit -m "feat(exploration): InterestTracker — trace evaporation with adaptive rho"
```

### Step 1.5: Write LearningProgressTracker tests

- [ ] **Add to tests/test_exploration.py**

```python
class TestLearningProgressTracker:
    def test_initial_state(self) -> None:
        lp = LearningProgressTracker(alpha_ema=0.05)
        assert lp.chronic_error == 0.0
        assert lp.error_improvement_rate == 0.0

    def test_decreasing_error_shows_learning(self) -> None:
        lp = LearningProgressTracker(alpha_ema=0.5)  # fast EMA for test
        for e in [1.0, 0.8, 0.6, 0.4, 0.2]:
            lp.update(e)
        assert lp.error_improvement_rate > 0.0  # positive = learning

    def test_stable_error_shows_stagnation(self) -> None:
        lp = LearningProgressTracker(alpha_ema=0.5)
        for _ in range(20):
            lp.update(0.5)
        assert abs(lp.error_improvement_rate) < 0.01

    def test_increasing_error_shows_degradation(self) -> None:
        lp = LearningProgressTracker(alpha_ema=0.5)
        for e in [0.2, 0.4, 0.6, 0.8, 1.0]:
            lp.update(e)
        assert lp.error_improvement_rate < 0.0  # negative = degrading
```

- [ ] **Run to verify fails**

Run: `uv run pytest tests/test_exploration.py::TestLearningProgressTracker -v`

### Step 1.6: Implement LearningProgressTracker

- [ ] **Add to shared/exploration.py**

```python
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
```

- [ ] **Run test**

Run: `uv run pytest tests/test_exploration.py::TestLearningProgressTracker -v`
Expected: PASS

- [ ] **Commit**

```bash
git add shared/exploration.py tests/test_exploration.py
git commit -m "feat(exploration): LearningProgressTracker — EMA error derivative"
```

### Step 1.7: Write CoherenceTracker tests

- [ ] **Add to tests/test_exploration.py**

```python
class TestCoherenceTracker:
    def test_synchronized_components_high_coherence(self) -> None:
        ct = CoherenceTracker(neighbors=["a", "b", "c"])
        # All at same phase
        ct.update_phases({"a": 0.0, "b": 0.0, "c": 0.0})
        assert ct.local_coherence() > 0.9

    def test_desynchronized_components_low_coherence(self) -> None:
        ct = CoherenceTracker(neighbors=["a", "b", "c"])
        # Evenly spread phases
        ct.update_phases({"a": 0.0, "b": 2.094, "c": 4.189})  # 0, 2pi/3, 4pi/3
        assert ct.local_coherence() < 0.2

    def test_dwell_time_accumulates_during_coherence(self) -> None:
        ct = CoherenceTracker(neighbors=["a", "b"], coherence_threshold=0.8)
        ct.update_phases({"a": 0.0, "b": 0.1})
        ct.tick(elapsed_s=5.0)
        ct.tick(elapsed_s=5.0)
        assert ct.dwell_time_in_coherence() == 10.0

    def test_dwell_time_resets_on_desync(self) -> None:
        ct = CoherenceTracker(neighbors=["a", "b"], coherence_threshold=0.8)
        ct.update_phases({"a": 0.0, "b": 0.1})
        ct.tick(elapsed_s=5.0)
        ct.update_phases({"a": 0.0, "b": 3.14})  # desync
        ct.tick(elapsed_s=5.0)
        assert ct.dwell_time_in_coherence() == 0.0
```

- [ ] **Run to verify fails**

Run: `uv run pytest tests/test_exploration.py::TestCoherenceTracker -v`

### Step 1.8: Implement CoherenceTracker

- [ ] **Add to shared/exploration.py**

```python
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
```

- [ ] **Run test**

Run: `uv run pytest tests/test_exploration.py::TestCoherenceTracker -v`
Expected: PASS

- [ ] **Commit**

```bash
git add shared/exploration.py tests/test_exploration.py
git commit -m "feat(exploration): CoherenceTracker — local Kuramoto order parameter"
```

### Step 1.9: Write ExplorationSignal + compute_exploration_signal tests

- [ ] **Add to tests/test_exploration.py**

```python
class TestExplorationSignal:
    def test_boredom_index_fully_novel(self) -> None:
        sig = ExplorationSignal(
            component="test",
            timestamp=0.0,
            mean_habituation=0.0,
            max_novelty_edge=None,
            max_novelty_score=0.0,
            error_improvement_rate=0.0,
            chronic_error=0.0,
            mean_trace_interest=1.0,
            stagnation_duration=0.0,
            local_coherence=0.0,
            dwell_time_in_coherence=0.0,
            boredom_index=0.0,
            curiosity_index=0.0,
        )
        assert sig.boredom_index == 0.0

    def test_boredom_index_fully_habituated(self) -> None:
        sig = ExplorationSignal(
            component="test",
            timestamp=0.0,
            mean_habituation=1.0,
            max_novelty_edge=None,
            max_novelty_score=0.0,
            error_improvement_rate=0.0,
            chronic_error=0.0,
            mean_trace_interest=0.0,
            stagnation_duration=600.0,
            local_coherence=0.95,
            dwell_time_in_coherence=600.0,
            boredom_index=0.0,
            curiosity_index=0.0,
        )
        # Recompute to test the formula
        bi = compute_boredom_index(
            mean_habituation=1.0,
            mean_trace_interest=0.0,
            stagnation_duration=600.0,
            dwell_time_in_coherence=600.0,
            t_patience=300.0,
        )
        assert bi > 0.9


class TestComputeBoredomIndex:
    def test_weights_sum_to_one(self) -> None:
        # All maxed → should approach 1.0
        bi = compute_boredom_index(
            mean_habituation=1.0,
            mean_trace_interest=0.0,
            stagnation_duration=1000.0,
            dwell_time_in_coherence=1000.0,
            t_patience=300.0,
        )
        assert 0.95 < bi <= 1.0

    def test_all_novel_zero_boredom(self) -> None:
        bi = compute_boredom_index(
            mean_habituation=0.0,
            mean_trace_interest=1.0,
            stagnation_duration=0.0,
            dwell_time_in_coherence=0.0,
            t_patience=300.0,
        )
        assert bi == 0.0


class TestComputeCuriosityIndex:
    def test_novel_edge_drives_curiosity(self) -> None:
        ci = compute_curiosity_index(
            chronic_error=0.0,
            error_improvement_rate=0.0,
            max_novelty_score=0.9,
            local_coherence=0.95,
        )
        assert ci >= 0.9

    def test_stalled_reorganization_drives_curiosity(self) -> None:
        ci = compute_curiosity_index(
            chronic_error=0.8,
            error_improvement_rate=-0.01,  # no improvement
            max_novelty_score=0.0,
            local_coherence=0.95,
        )
        assert ci > 0.5

    def test_desynchronization_drives_curiosity(self) -> None:
        ci = compute_curiosity_index(
            chronic_error=0.0,
            error_improvement_rate=0.0,
            max_novelty_score=0.0,
            local_coherence=0.2,
        )
        assert ci >= 0.8
```

- [ ] **Run to verify fails**

### Step 1.10: Implement ExplorationSignal dataclass + compute functions

- [ ] **Add to shared/exploration.py**

```python
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
```

- [ ] **Run all exploration tests**

Run: `uv run pytest tests/test_exploration.py -v`
Expected: ALL PASS

- [ ] **Commit**

```bash
git add shared/exploration.py tests/test_exploration.py
git commit -m "feat(exploration): ExplorationSignal dataclass + composite compute functions"
```

---

## Task 2: Trace Publication (ExplorationWriter + Reader)

**Files:**
- Create: `shared/exploration_writer.py`
- Create: `tests/test_exploration_writer.py`

### Step 2.1: Write publication tests

- [ ] **Write test file**

```python
# tests/test_exploration_writer.py
"""Tests for shared.exploration_writer — /dev/shm publication."""

from __future__ import annotations

import json
from pathlib import Path

from shared.exploration import ExplorationSignal
from shared.exploration_writer import (
    ExplorationReader,
    publish_exploration_signal,
)


def _make_signal(component: str = "test") -> ExplorationSignal:
    return ExplorationSignal(
        component=component,
        timestamp=1000.0,
        mean_habituation=0.5,
        max_novelty_edge="dmn_pulse",
        max_novelty_score=0.8,
        error_improvement_rate=-0.003,
        chronic_error=0.12,
        mean_trace_interest=0.6,
        stagnation_duration=45.0,
        local_coherence=0.7,
        dwell_time_in_coherence=20.0,
        boredom_index=0.42,
        curiosity_index=0.8,
    )


class TestPublishExplorationSignal:
    def test_writes_json(self, tmp_path: Path) -> None:
        sig = _make_signal()
        publish_exploration_signal(sig, shm_root=tmp_path)
        path = tmp_path / "hapax-exploration" / "test.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["component"] == "test"
        assert data["boredom_index"] == 0.42

    def test_atomic_overwrite(self, tmp_path: Path) -> None:
        sig1 = _make_signal()
        publish_exploration_signal(sig1, shm_root=tmp_path)
        sig2 = ExplorationSignal(**{**sig1.to_dict(), "boredom_index": 0.99, "timestamp": 2000.0})
        publish_exploration_signal(sig2, shm_root=tmp_path)
        path = tmp_path / "hapax-exploration" / "test.json"
        data = json.loads(path.read_text())
        assert data["boredom_index"] == 0.99


class TestExplorationReader:
    def test_reads_published_signal(self, tmp_path: Path) -> None:
        publish_exploration_signal(_make_signal("dmn_pulse"), shm_root=tmp_path)
        reader = ExplorationReader(shm_root=tmp_path)
        sig = reader.read("dmn_pulse")
        assert sig is not None
        assert sig["component"] == "dmn_pulse"

    def test_returns_none_for_missing(self, tmp_path: Path) -> None:
        reader = ExplorationReader(shm_root=tmp_path)
        assert reader.read("nonexistent") is None

    def test_read_all(self, tmp_path: Path) -> None:
        publish_exploration_signal(_make_signal("a"), shm_root=tmp_path)
        publish_exploration_signal(_make_signal("b"), shm_root=tmp_path)
        reader = ExplorationReader(shm_root=tmp_path)
        signals = reader.read_all()
        assert len(signals) == 2
        assert {s["component"] for s in signals.values()} == {"a", "b"}
```

- [ ] **Run to verify fails**

Run: `uv run pytest tests/test_exploration_writer.py -v`

### Step 2.2: Implement ExplorationWriter + Reader

- [ ] **Write shared/exploration_writer.py**

```python
# shared/exploration_writer.py
"""Atomic publication of ExplorationSignal to /dev/shm."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from shared.exploration import ExplorationSignal

log = logging.getLogger("exploration")

_DEFAULT_SHM = Path("/dev/shm")


def publish_exploration_signal(
    signal: ExplorationSignal,
    shm_root: Path = _DEFAULT_SHM,
) -> None:
    """Write ExplorationSignal atomically to /dev/shm/hapax-exploration/{component}.json."""
    directory = shm_root / "hapax-exploration"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{signal.component}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(signal.to_dict()), encoding="utf-8")
    tmp.rename(target)


class ExplorationReader:
    """Read ExplorationSignal JSON from /dev/shm."""

    def __init__(self, shm_root: Path = _DEFAULT_SHM) -> None:
        self._dir = shm_root / "hapax-exploration"

    def read(self, component: str) -> dict | None:
        path = self._dir / f"{component}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def read_all(self) -> dict[str, dict]:
        signals = {}
        if not self._dir.exists():
            return signals
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                signals[path.stem] = data
            except (OSError, json.JSONDecodeError):
                continue
        return signals
```

- [ ] **Run tests**

Run: `uv run pytest tests/test_exploration_writer.py -v`
Expected: PASS

- [ ] **Commit**

```bash
git add shared/exploration_writer.py tests/test_exploration_writer.py
git commit -m "feat(exploration): ExplorationWriter + Reader for /dev/shm publication"
```

---

## Task 3: New Impingement Types

**Files:**
- Modify: `shared/impingement.py:24-30`
- Test: `tests/test_exploration.py` (add to existing)

### Step 3.1: Add impingement types

- [ ] **Add to tests/test_exploration.py**

```python
from shared.impingement import ImpingementType


class TestExplorationImpingementTypes:
    def test_boredom_type_exists(self) -> None:
        assert ImpingementType.BOREDOM == "boredom"

    def test_curiosity_type_exists(self) -> None:
        assert ImpingementType.CURIOSITY == "curiosity"

    def test_exploration_opportunity_type_exists(self) -> None:
        assert ImpingementType.EXPLORATION_OPPORTUNITY == "exploration_opp"
```

- [ ] **Run to verify fails**

Run: `uv run pytest tests/test_exploration.py::TestExplorationImpingementTypes -v`

- [ ] **Modify shared/impingement.py — add 3 types after line 30**

Add after existing types in the `ImpingementType` enum:

```python
    BOREDOM = "boredom"
    CURIOSITY = "curiosity"
    EXPLORATION_OPPORTUNITY = "exploration_opp"
```

- [ ] **Run test**

Run: `uv run pytest tests/test_exploration.py::TestExplorationImpingementTypes -v`
Expected: PASS

- [ ] **Commit**

```bash
git add shared/impingement.py tests/test_exploration.py
git commit -m "feat(exploration): add BOREDOM, CURIOSITY, EXPLORATION_OPPORTUNITY impingement types"
```

---

## Task 4: Stimmung Integration — SEEKING Stance + exploration_deficit

**Files:**
- Modify: `shared/stimmung.py`
- Create: `tests/test_exploration_stimmung.py`

### Step 4.1: Write SEEKING stance tests

- [ ] **Write test file**

```python
# tests/test_exploration_stimmung.py
"""Tests for stimmung exploration_deficit + SEEKING stance."""

from __future__ import annotations

from shared.stimmung import Stance


class TestSeekingStance:
    def test_seeking_exists(self) -> None:
        assert Stance.SEEKING == "seeking"

    def test_stance_ordering(self) -> None:
        ordered = [Stance.NOMINAL, Stance.SEEKING, Stance.CAUTIOUS, Stance.DEGRADED, Stance.CRITICAL]
        assert len(ordered) == 5
```

- [ ] **Run to verify fails**

Run: `uv run pytest tests/test_exploration_stimmung.py -v`

### Step 4.2: Add SEEKING to Stance enum

- [ ] **Modify shared/stimmung.py Stance enum (line ~31-37)**

Insert SEEKING between NOMINAL and CAUTIOUS:

```python
class Stance(StrEnum):
    """System-wide self-assessment."""
    NOMINAL = "nominal"
    SEEKING = "seeking"
    CAUTIOUS = "cautious"
    DEGRADED = "degraded"
    CRITICAL = "critical"
```

- [ ] **Run test**

Run: `uv run pytest tests/test_exploration_stimmung.py::TestSeekingStance -v`
Expected: PASS

- [ ] **Commit**

```bash
git add shared/stimmung.py tests/test_exploration_stimmung.py
git commit -m "feat(exploration): add SEEKING stance between NOMINAL and CAUTIOUS"
```

### Step 4.3: Write exploration_deficit dimension tests

- [ ] **Add to tests/test_exploration_stimmung.py**

```python
from unittest.mock import patch
from pathlib import Path

from shared.stimmung import StimmungCollector, Stance


class TestExplorationDeficit:
    def test_update_exploration_sets_dimension(self) -> None:
        sc = StimmungCollector()
        sc.update_exploration(0.5)
        snap = sc.snapshot()
        assert hasattr(snap, "exploration_deficit")
        assert snap.exploration_deficit.value == 0.5

    def test_high_exploration_deficit_enters_seeking(self) -> None:
        sc = StimmungCollector()
        # All infrastructure healthy
        sc.update_health(99, 99, [])
        sc.update_gpu(0.3)
        sc.update_engine(10.0, 0.0)
        sc.update_perception(1.0, 0.9)
        sc.update_langfuse(0.0)
        # High exploration deficit for 3+ ticks (hysteresis)
        for _ in range(5):
            sc.update_exploration(0.5)
            snap = sc.snapshot()
        assert snap.overall_stance == Stance.SEEKING

    def test_seeking_suppressed_when_degraded(self) -> None:
        sc = StimmungCollector()
        # Infrastructure degraded
        sc.update_health(50, 99, [])
        sc.update_gpu(0.95)  # high pressure
        sc.update_exploration(0.5)
        snap = sc.snapshot()
        # Should NOT be SEEKING — infrastructure problems override
        assert snap.overall_stance != Stance.SEEKING
```

- [ ] **Run to verify fails**

Run: `uv run pytest tests/test_exploration_stimmung.py::TestExplorationDeficit -v`

### Step 4.4: Implement exploration_deficit dimension

- [ ] **Modify shared/stimmung.py**

1. Add `exploration_deficit` to `SystemStimmung` model (after grounding_quality field, ~line 71):
```python
    exploration_deficit: DimensionReading = Field(default_factory=DimensionReading)
```

2. Add to `_COGNITIVE_DIMENSION_NAMES` list (~line 119):
```python
_COGNITIVE_DIMENSION_NAMES = ["grounding_quality", "exploration_deficit"]
```

3. Add `_exploration_window` to `StimmungCollector.__init__` (~line 179):
```python
        self._exploration_window: deque[float] = deque(maxlen=5)
```

4. Add `update_exploration()` method (after update_grounding_quality):
```python
    def update_exploration(self, deficit: float) -> None:
        """Update exploration deficit (0.0 = engaged, 1.0 = system-wide boredom)."""
        self._exploration_window.append(_clamp(deficit))
```

5. In `snapshot()` method (~line 361), add exploration dimension computation alongside grounding_quality:
```python
        if self._exploration_window:
            exploration_val = sum(self._exploration_window) / len(self._exploration_window)
            dimensions["exploration_deficit"] = DimensionReading(
                value=exploration_val,
                trend=0.0,
                freshness=1.0,
            )
```

6. In `_compute_stance()` (~line 462), add SEEKING logic before the infrastructure stance computation:
```python
        # SEEKING: only from exploration_deficit, only when infra is nominal/cautious
        if infra_stance in (Stance.NOMINAL, Stance.CAUTIOUS):
            exploration_val = dimensions.get("exploration_deficit", DimensionReading()).value
            if exploration_val > 0.35:
                return Stance.SEEKING
```

7. In `_apply_hysteresis()`, add SEEKING hysteresis (degrade to SEEKING with 3 consecutive, recover with 5):
```python
        # SEEKING hysteresis: enter after 3, exit after 5
        if raw_stance == Stance.SEEKING:
            self._seeking_count = getattr(self, "_seeking_count", 0) + 1
            if self._seeking_count >= 3:
                return Stance.SEEKING
            return self._last_stance if self._last_stance != Stance.SEEKING else Stance.NOMINAL
        else:
            self._seeking_count = 0
```

- [ ] **Run tests**

Run: `uv run pytest tests/test_exploration_stimmung.py -v`
Expected: PASS

- [ ] **Run existing stimmung tests to verify no regression**

Run: `uv run pytest tests/test_stimmung.py tests/test_stimmung_hysteresis.py -v`
Expected: PASS

- [ ] **Commit**

```bash
git add shared/stimmung.py tests/test_exploration_stimmung.py
git commit -m "feat(exploration): exploration_deficit dimension + SEEKING stance in stimmung"
```

---

## Task 5: DMN Escalation Responses

**Files:**
- Modify: `agents/dmn/pulse.py`
- Create: `tests/test_exploration_dmn.py`

### Step 5.1: Write DMN Level 1 response tests

- [ ] **Write test file**

```python
# tests/test_exploration_dmn.py
"""Tests for DMN boredom/curiosity escalation responses."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from agents._impingement import Impingement, ImpingementType
from agents.dmn.buffer import DMNBuffer
from agents.dmn.pulse import DMNPulse


def _boredom_impingement(source: str = "test", strength: float = 0.7) -> Impingement:
    return Impingement(
        source=source,
        type=ImpingementType.BOREDOM,
        strength=strength,
        content={"boredom_index": strength},
    )


class TestDMNLevel1:
    """Single component boredom → pulse redirects evaluative tick."""

    async def test_boredom_impingement_triggers_exploration_evaluative(self) -> None:
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        pulse.receive_exploration_impingement(_boredom_impingement("dmn_imagination"))
        assert pulse._exploration_targets == ["dmn_imagination"]
```

- [ ] **Run to verify fails**

Run: `uv run pytest tests/test_exploration_dmn.py::TestDMNLevel1 -v`

### Step 5.2: Implement DMN Level 1

- [ ] **Modify agents/dmn/pulse.py**

Add to `DMNPulse.__init__` (~line 41):
```python
        self._exploration_targets: list[str] = []
        self._boredom_window: list[tuple[float, str]] = []  # (timestamp, source)
```

Add method:
```python
    def receive_exploration_impingement(self, imp: Impingement) -> None:
        """Receive boredom/curiosity impingement for escalation processing."""
        if imp.type == ImpingementType.BOREDOM:
            self._exploration_targets.append(imp.source)
            self._boredom_window.append((time.time(), imp.source))
            # Prune window to 60s
            cutoff = time.time() - 60.0
            self._boredom_window = [(t, s) for t, s in self._boredom_window if t > cutoff]
```

- [ ] **Run test**

Run: `uv run pytest tests/test_exploration_dmn.py::TestDMNLevel1 -v`
Expected: PASS

### Step 5.3: Write DMN Level 2 tests + implement

- [ ] **Add to tests/test_exploration_dmn.py**

```python
class TestDMNLevel2:
    """3+ components bored within 60s → imagination divergence mode."""

    def test_multi_component_boredom_triggers_level2(self) -> None:
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        for src in ["comp_a", "comp_b", "comp_c"]:
            pulse.receive_exploration_impingement(_boredom_impingement(src))
        assert pulse.exploration_level() >= 2

    def test_single_component_stays_level1(self) -> None:
        buf = DMNBuffer()
        pulse = DMNPulse(buf)
        pulse.receive_exploration_impingement(_boredom_impingement("comp_a"))
        assert pulse.exploration_level() == 1
```

- [ ] **Add to agents/dmn/pulse.py**

```python
    def exploration_level(self) -> int:
        """Current escalation level: 0=none, 1=single-component, 2=multi-component, 3=sustained."""
        if not self._boredom_window:
            return 0
        unique_sources = {s for _, s in self._boredom_window}
        if len(unique_sources) >= 3:
            return 2
        if len(unique_sources) >= 1:
            return 1
        return 0
```

- [ ] **Run tests**

Run: `uv run pytest tests/test_exploration_dmn.py -v`
Expected: PASS

- [ ] **Commit**

```bash
git add agents/dmn/pulse.py tests/test_exploration_dmn.py
git commit -m "feat(exploration): DMN Level 1+2 escalation responses"
```

---

## Task 6: Imagination CadenceController SEEKING Response

**Files:**
- Modify: `agents/imagination.py:114-157`
- Add test to: `tests/test_exploration.py`

### Step 6.1: Write cadence SEEKING test

- [ ] **Add to tests/test_exploration.py**

```python
from agents.imagination import CadenceController


class TestCadenceSeeking:
    def test_seeking_reduces_cadence_floor(self) -> None:
        cc = CadenceController(base_s=12.0, accelerated_s=4.0)
        normal_interval = cc.current_interval()
        cc.set_seeking(True)
        seeking_interval = cc.current_interval()
        assert seeking_interval < normal_interval

    def test_seeking_false_restores_normal(self) -> None:
        cc = CadenceController(base_s=12.0, accelerated_s=4.0)
        cc.set_seeking(True)
        cc.set_seeking(False)
        assert cc.current_interval() == 12.0
```

- [ ] **Run to verify fails**

### Step 6.2: Implement set_seeking on CadenceController

- [ ] **Modify agents/imagination.py CadenceController**

Add to `__init__` (~line 120):
```python
        self._seeking: bool = False
```

Add method:
```python
    def set_seeking(self, seeking: bool) -> None:
        """When system is in SEEKING stance, use 2s floor instead of 4s."""
        self._seeking = seeking
```

Modify `current_interval()` (~line 144):
```python
    def current_interval(self) -> float:
        if self._seeking:
            base = 2.0  # SEEKING floor
        elif self._accelerated:
            base = self._accelerated_s
        else:
            base = self._base_s
        return base * (2.0 if self._tpn_active else 1.0)
```

- [ ] **Run test**

Run: `uv run pytest tests/test_exploration.py::TestCadenceSeeking -v`
Expected: PASS

- [ ] **Run existing imagination tests**

Run: `uv run pytest tests/ -k imagination -v`
Expected: PASS

- [ ] **Commit**

```bash
git add agents/imagination.py tests/test_exploration.py
git commit -m "feat(exploration): CadenceController.set_seeking() — 2s floor in SEEKING stance"
```

---

## Task 7: Salience Router SEEKING Modulation

**Files:**
- Modify: `agents/hapax_daimonion/salience_router.py`
- Add test to: `tests/test_exploration.py`

### Step 7.1: Write salience SEEKING test

- [ ] **Add to tests/test_exploration.py**

```python
class TestSalienceSeeking:
    def test_seeking_increases_novelty_weight(self) -> None:
        """In SEEKING, novelty weight should increase from 0.15 to 0.30."""
        from agents.hapax_daimonion.salience_router import SalienceRouter

        # This test verifies the router's weights property changes
        # We can't easily test the full routing without embeddings,
        # so test the weight accessor
        router = SalienceRouter.__new__(SalienceRouter)
        router._weights = {"concern_overlap": 0.55, "novelty": 0.15, "dialog_features": 0.30}
        router._seeking = False

        normal_novelty = router.effective_novelty_weight()
        router._seeking = True
        seeking_novelty = router.effective_novelty_weight()
        assert seeking_novelty > normal_novelty
        assert seeking_novelty == 0.30
```

- [ ] **Run to verify fails**

### Step 7.2: Implement SEEKING modulation on SalienceRouter

- [ ] **Modify agents/hapax_daimonion/salience_router.py**

Add to `__init__`:
```python
        self._seeking: bool = False
```

Add methods:
```python
    def set_seeking(self, seeking: bool) -> None:
        self._seeking = seeking

    def effective_novelty_weight(self) -> float:
        base = self._weights.get("novelty", 0.15)
        return 0.30 if self._seeking else base
```

In `route()`, where novelty weight is used (~line 192+), replace hardcoded weight with `self.effective_novelty_weight()`.

- [ ] **Run test**

Run: `uv run pytest tests/test_exploration.py::TestSalienceSeeking -v`
Expected: PASS

- [ ] **Commit**

```bash
git add agents/hapax_daimonion/salience_router.py tests/test_exploration.py
git commit -m "feat(exploration): SalienceRouter SEEKING modulation — novelty weight 0.15→0.30"
```

---

## Task 8: Integration Wiring — DMN Reads ExplorationSignals

**Files:**
- Modify: `agents/dmn/pulse.py`
- Modify: `agents/dmn/sensor.py` (if trace reading happens there)

### Step 8.1: Wire DMN to read exploration signals each tick

- [ ] **Modify agents/dmn/pulse.py `tick()` method**

After existing sensor reading, add:
```python
        # Read exploration signals from all components
        from shared.exploration_writer import ExplorationReader
        reader = ExplorationReader()
        exploration_signals = reader.read_all()

        # Compute system-wide exploration deficit for stimmung
        if exploration_signals:
            boredom_scores = [s.get("boredom_index", 0.0) for s in exploration_signals.values()]
            curiosity_scores = [s.get("curiosity_index", 0.0) for s in exploration_signals.values()]
            aggregate_boredom = sum(boredom_scores) / len(boredom_scores)
            aggregate_curiosity = sum(curiosity_scores) / len(curiosity_scores)
            exploration_deficit = max(0.0, min(1.0, aggregate_boredom - aggregate_curiosity))
            # Update stimmung (if collector is accessible)
            self._last_exploration_deficit = exploration_deficit
```

- [ ] **Run existing DMN tests**

Run: `uv run pytest tests/test_dmn.py tests/test_dmn_integration.py -v`
Expected: PASS (graceful when no signals exist)

- [ ] **Commit**

```bash
git add agents/dmn/pulse.py
git commit -m "feat(exploration): DMN reads ExplorationSignals + computes aggregate deficit"
```

---

## Remaining Tasks (6, 7 from spec — Full Rollout + Observability)

These are deferred to a follow-up PR after the pilot 3-component validation:

- **Task 9:** Wire ExplorationSignal computation into `dmn_imagination`, `salience_router`, `fast_perception` (the 3 pilot components)
- **Task 10:** Roll out to remaining 11 components with per-component parameters from spec §8
- **Task 11:** Langfuse tracing, Grafana dashboard, health monitor checks

Each of these tasks follows the same pattern: add tracker initialization to the component's daemon loop, call `compute_exploration_signal()` each tick, call `publish_exploration_signal()`, and apply the control law from spec §5.1.

---

## Verification

After all tasks complete:

1. `uv run pytest tests/test_exploration.py tests/test_exploration_writer.py tests/test_exploration_stimmung.py tests/test_exploration_dmn.py -v` — all pass
2. `uv run pytest tests/ -q` — no regressions
3. `uv run pyright shared/exploration.py shared/exploration_writer.py` — 0 errors
4. `uv run ruff check shared/exploration.py shared/exploration_writer.py` — clean
