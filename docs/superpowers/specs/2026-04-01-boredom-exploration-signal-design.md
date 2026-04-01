# Boredom and Exploration Signal — Design Specification

**Date:** 2026-04-01
**Status:** Approved — ready for implementation planning
**Approach:** C (per-component ExplorationSignal + stimmung integration)
**Depends on:** [SCM Spec](../../research/stigmergic-cognitive-mesh.md), [Control Law Specifications](../../research/2026-03-31-scm-control-law-specifications.md), [ControlSignal](../../../shared/control_signal.py)
**Research:** [Boredom-Curiosity PCT Formalization](../../research/2026-04-01-boredom-curiosity-pct-formalization.md)

---

## 1. Problem

The SCM has convergence without divergence. Fourteen control laws drive error toward zero. Stimmung detects failure states. Impingements detect surprise. Nothing detects the absence of surprise persisting too long. The system can settle into a fixed point — imagination elaborating the same themes, salience weights ossified around established concerns, the stigmergic mesh converged without ever diverging again.

Boredom is the missing homeostatic signal that prevents exploitation lock-in by driving exploration when engagement depletes.

## 2. Theoretical Grounding

Three complementary formalisms at three timescales:

**Divisive normalization (fast — per-tick).** Carandini-Heeger (2012). Per-edge gain decreases with predictability. Novel traces amplified, familiar traces suppressed. Each component independently habituates to its inputs.

**Compression progress / learning progress (medium — seconds).** Schmidhuber (2008), Oudeyer-Kaplan (2007). Curiosity = first derivative of model improvement. Boredom = zero learning progress. Maps to the rate of change of ControlSignal error.

**Stigmergic trace evaporation (slow — minutes).** Dorigo-Stutzle ACO (2004). Trace interest decays when unchanged. Adaptive evaporation accelerates when stagnation exceeds a patience threshold.

Additional theoretical support from Kelso's HKB metastability model (boredom as coupling decay in synchronized systems), Gomez-Ramirez & Costa's boredom decay term in predictive processing, and Heidegger's three forms of Langeweile mapping to the three escalation levels. Full citations in the research document.

## 3. Data Model

### 3.1 ExplorationSignal

Published by each of the 14 S1 components alongside their existing ControlSignal.

```python
@dataclass(frozen=True)
class ExplorationSignal:
    component: str
    timestamp: float

    # Layer 1: Divisive normalization (per-tick, per-input-edge)
    mean_habituation: float          # 0 = all novel, 1 = all habituated
    max_novelty_edge: str | None     # which input trace is freshest
    max_novelty_score: float         # how novel that edge is

    # Layer 2: Learning progress (seconds-scale)
    error_improvement_rate: float    # d(chronic_error)/dt — negative = learning
    chronic_error: float             # EMA of ControlSignal.error

    # Layer 3: Trace interest / evaporation (minutes-scale)
    mean_trace_interest: float       # aggregate interest across input traces
    stagnation_duration: float       # seconds since any input trace changed meaningfully

    # Layer 4: Phase coherence (mesh-level)
    local_coherence: float           # Kuramoto r with reading neighbors
    dwell_time_in_coherence: float   # seconds at current coherence level

    # Composite indices
    boredom_index: float             # 0-1, weighted composite
    curiosity_index: float           # 0-1, opportunity for learning
```

### 3.2 Boredom Index

Weighted composite across all four layers:

```
boredom = 0.30 * mean_habituation
        + 0.30 * (1.0 - mean_trace_interest)
        + 0.20 * clamp(stagnation_duration / T_patience, 0, 1)
        + 0.20 * clamp(dwell_time_in_coherence / T_patience, 0, 1)
```

`T_patience` is per-component (see §8). Default 300s.

### 3.3 Curiosity Index

Not the inverse of boredom. Bored + curious = healthy directed exploration. Bored + not curious = diffuse emptiness requiring reorganization.

```
curiosity = max(
    reorganization_drive,      # chronic error + no improvement
    max_novelty_score,         # novel edge found
    1.0 - local_coherence      # desynchronized — something changed
)
```

Where `reorganization_drive = clamp(chronic_error, 0, 1) * (1.0 if error_improvement_rate <= 0 else 0.5)`.

## 4. Habituation and Evaporation Mechanics

### 4.1 Per-Edge Habituation (Fast)

Each component maintains a normalization weight per input edge:

```
w_ij(t+1) = w_ij(t) + α · predictable(t) - β · w_ij(t)
```

`predictable(t) = 1` if `|trace_j(t) - trace_j(t-1)| < δ_j`, else `0`. Threshold `δ_j` = trace's historical standard deviation (scale-invariant change detection).

Gain from normalization weight:

```
gain_ij(t) = G_max / (1 + κ · w_ij(t))
```

Parameters: `α = 0.1`, `β = 0.01`, `κ = 1.0`, `G_max = 1.0`.

`mean_habituation` = mean of `(1 - gain_ij / G_max)` across all input edges.

### 4.2 Trace Interest Evaporation (Slow)

```
interest_j(t) = exp(-ρ(t) · T_unchanged_j(t))
```

Resets to 1.0 on meaningful change (exceeds `δ_j`).

Adaptive evaporation rate:

```
ρ(t) = ρ_base + ρ_adapt · sigmoid(stagnation(t) - T_patience)
```

`ρ_base = 0.005/s` (halves in ~140s). `ρ_adapt = 0.020/s`. `T_patience = 300s`. After 5 minutes of stagnation, interest halves in ~28s.

### 4.3 Learning Progress (Medium)

```
chronic_error(t) = α_ema · error(t) + (1 - α_ema) · chronic_error(t-1)
error_improvement_rate(t) = chronic_error(t-1) - chronic_error(t)
```

`α_ema = 0.05` (~20-tick memory at 1Hz).

### 4.4 Phase Coherence (Mesh-Level)

Per-component effective phase: `θ_i = 2π · (t_i mod T_i) / T_i`

Local order parameter: `r_i = |Σ_{j ∈ neighbors(i)} e^(iθ_j)| / |neighbors(i)|`

Dwell time accumulates while `r_i > 0.8`.

### 4.5 State Persistence

Habituation weights and interest values live in-process memory. Reset on component restart — intentional. A restarted component sees everything as novel.

## 5. Control Law: Boredom-Driven Exploration (15th Control Law)

### 5.1 Response Modes

```
IF boredom_index > 0.7 AND curiosity_index > 0.4:
    → DIRECTED EXPLORATION
    Increase gain on max_novelty_edge (×1.5)
    Decrease gain on most-habituated edges (×0.5)
    Accelerate tick rate by 1.3×
    Emit Impingement(type=EXPLORATION_OPPORTUNITY, strength=curiosity_index)

IF boredom_index > 0.7 AND curiosity_index < 0.4:
    → UNDIRECTED EXPLORATION
    With probability sigmoid(boredom_index - 0.7):
        Read one trace not in current input set (temporary, N=30 ticks)
        Perturb reference signal by ε ~ N(0, σ_explore)
    Emit Impingement(type=BOREDOM, strength=boredom_index)

IF boredom_index < 0.7 AND curiosity_index > 0.6:
    → FOCUSED ENGAGEMENT
    Increase gain on max_novelty_edge (×2.0)
    Emit Impingement(type=CURIOSITY, strength=curiosity_index)
```

### 5.2 Temporary Edge Expansion

During undirected exploration, a component temporarily subscribes to an adjacent trace (one hop in the reading-dependency graph from an existing neighbor) for 30 ticks. If the temporary edge produces low habituation (novel signal), it is promoted to a persistent reading dependency. Otherwise it expires.

### 5.3 Reference Signal Perturbation

Each component defines `σ_explore` — the magnitude of random perturbation it tolerates. Applied as additive Gaussian noise to the reference value during undirected exploration.

### 5.4 New Impingement Types

```python
BOREDOM = "boredom"                          # nothing interesting
CURIOSITY = "curiosity"                      # something novel found
EXPLORATION_OPPORTUNITY = "exploration_opp"   # bored but see a target
```

Propagate through existing impingement cascade. Cascade depth limit (max 3) prevents echo.

## 6. DMN as Reorganization Authority

Three escalating responses:

### 6.1 Level 1 — Redirect Attention (Pulse Daemon)

**Trigger:** Single component emits BOREDOM impingement.

Pulse daemon's next evaluative tick targets the bored component's domain. Asks "what hasn't been noticed?" rather than "what's happening?" If the tick finds novelty, it emits STATISTICAL_DEVIATION back — breaking stagnation from outside.

### 6.2 Level 2 — Generate Novel Material (Imagination Daemon)

**Trigger:** 3+ components emit BOREDOM within a 60s window.

Imagination switches from continuation mode to divergence mode. Samples from least-recently-active concern graph regions. Cadence drops to floor (2s). Floods the system with novel associations.

### 6.3 Level 3 — Restructure References (Resolver Daemon)

**Trigger:** `exploration_deficit` in SEEKING stance for > 600s.

Resolver reads each bored component's ExplorationSignal, identifies maximally habituated input edges, and generates new reference signals targeting the least habituated edges. Directed restructuring based on the curiosity landscape.

### 6.4 DMN Self-Regulation

DMN daemons compute their own ExplorationSignals. If imagination habituates to its own output patterns, it applies its own perturbation — shifts embedding space sampling region, changes generation temperature, or varies the LLM model used for fragment generation.

## 7. Stimmung Integration

### 7.1 New Dimension: `exploration_deficit`

Added to cognitive dimension group (weight 0.3):

```
exploration_deficit = clamp(aggregate_boredom - aggregate_curiosity, 0.0, 1.0)
```

Where `aggregate_boredom = mean(boredom_index)` and `aggregate_curiosity = mean(curiosity_index)` across all 14 components.

### 7.2 New Stance: SEEKING

Inserted between NOMINAL and CAUTIOUS:

```
NOMINAL  (0.00 - 0.30)  → normal operation
SEEKING  (0.30 - 0.45)  → exploration mode, only entered via exploration_deficit
CAUTIOUS (0.45 - 0.60)  → resource/error pressure
DEGRADED (0.60 - 0.85)
CRITICAL (0.85+)
```

SEEKING is suppressed if any failure-based dimension would place the system in CAUTIOUS or higher.

**Entry/exit hysteresis:**
- Enter: `exploration_deficit > 0.35` for 3 consecutive ticks
- Exit: `exploration_deficit < 0.25` for 5 consecutive ticks

### 7.3 SEEKING Stance Modulation

| Component | SEEKING modulation |
|---|---|
| Imagination | Cadence floor 4s → 2s, material selection cone widened |
| Salience router | Novelty weight 0.15 → 0.30 |
| Reverie | `diffusion` ↑, `temporal_distortion` ↑, longer crossfade |
| DMN pulse | Evaluative questions shift to "what haven't I noticed?" |
| Affordance pipeline | Retrieval similarity threshold 0.7 → 0.5 |
| Temporal bands | Protention window extends, retention decay accelerates |

## 8. Per-Component Parameters

| Component | `κ` (habituation) | `T_patience` (s) | `σ_explore` | Tier |
|---|---|---|---|---|
| stimmung | 0.005 | 600 | 0.02 | Integration |
| dmn_pulse | 0.02 | 180 | 0.15 | Cognitive |
| dmn_imagination | 0.015 | 240 | 0.20 | Cognitive |
| dmn_resolver | 0.008 | 300 | 0.05 | Integration |
| salience_router | 0.012 | 300 | 0.10 | Cognitive |
| temporal_bands | 0.010 | 360 | 0.08 | Cognitive |
| fast_perception | 0.025 | 120 | 0.03 | Perceptual |
| visual_chain | 0.015 | 240 | 0.12 | Cognitive |
| affordance_pipeline | 0.012 | 300 | 0.10 | Cognitive |
| content_resolver | 0.010 | 300 | 0.08 | Cognitive |
| ir_presence | 0.020 | 180 | 0.02 | Perceptual |
| input_activity | 0.020 | 180 | 0.02 | Perceptual |
| contact_mic | 0.020 | 180 | 0.02 | Perceptual |
| voice_state | 0.008 | 360 | 0.05 | Integration |

**Design principle:** Perceptual backends habituate fast, perturb little (notice novelty, don't distort input). Cognitive components habituate moderately, perturb more (where creative exploration happens). Integration components habituate slowly, perturb minimally (stable substrate).

## 9. Trace Publication

### 9.1 /dev/shm Layout

```
/dev/shm/
├── hapax-control/              # existing ControlSignal
├── hapax-exploration/          # NEW — ExplorationSignal per component
│   ├── stimmung.json
│   ├── dmn_pulse.json
│   └── ...
├── hapax-exploration-edges/    # NEW — per-edge habituation (observability)
│   ├── dmn_imagination--contact_mic.json
│   └── ...
└── hapax-imagination/          # existing
```

### 9.2 ExplorationSignal JSON

```json
{
  "component": "dmn_imagination",
  "timestamp": 1743487200.0,
  "mean_habituation": 0.62,
  "max_novelty_edge": "contact_mic",
  "max_novelty_score": 0.81,
  "error_improvement_rate": -0.003,
  "chronic_error": 0.12,
  "mean_trace_interest": 0.34,
  "stagnation_duration": 187.0,
  "local_coherence": 0.45,
  "dwell_time_in_coherence": 22.0,
  "boredom_index": 0.58,
  "curiosity_index": 0.81
}
```

### 9.3 Edge State JSON (Observability)

```json
{
  "reader": "dmn_imagination",
  "writer": "contact_mic",
  "gain": 0.83,
  "normalization_weight": 0.21,
  "interest": 0.71,
  "time_unchanged": 42.0,
  "habituation_fraction": 0.17
}
```

### 9.4 Stimmung Trace Extension

Existing stimmung trace gains `exploration_deficit` field and SEEKING as a valid stance value.

## 10. Integration Sequence

Seven steps, each independently testable, each producing a PR.

**Step 1: `shared/exploration.py` — Data model + computation.** ExplorationSignal dataclass, HabituationTracker, InterestTracker, LearningProgressTracker, CoherenceTracker, `compute_exploration_signal()`. Pure computation, no I/O, fully unit-testable.

**Step 2: `shared/exploration_writer.py` — Trace publication.** Writer for `/dev/shm/hapax-exploration/`, optional edge state writer, ExplorationReader for consumers.

**Step 3: Wire into 3 pilot components.** `dmn_imagination`, `salience_router`, `fast_perception`. Covers cognitive, routing, and perceptual tiers. Each component's daemon loop: initialize trackers from reading_deps, compute ExplorationSignal each tick, publish, apply control law.

**Step 4: New impingement types + DMN response.** BOREDOM, CURIOSITY, EXPLORATION_OPPORTUNITY types. DMN Level 1 (pulse redirect), Level 2 (imagination divergence), Level 3 (resolver restructuring).

**Step 5: Stimmung integration.** `exploration_deficit` as 11th dimension. SEEKING stance with hysteresis. Per-consumer modulation rules.

**Step 6: Roll out to remaining 11 components.** Per-component parameter tuning. Validate smooth boredom→exploration→novelty→engagement→habituation→boredom cycle.

**Step 7: Observability + Bayesian validation hooks.** Langfuse traces, health monitor checks, Grafana panel, Sprint 0 measure hooks.

## 11. Out of Scope

- Operator-facing boredom detection (system-internal only)
- Permanent reading-graph rewiring (temporary edge expansion only)
- LLM calls in exploration computation (deterministic/numerical hot path)
- Reactive engine rule modifications (exploration flows through existing impingement/trace mechanisms)

## 12. Key Sources

- Carandini & Heeger (2012). Normalization as a canonical neural computation. *Nature Reviews Neuroscience*.
- Schmidhuber (2008). Driven by compression progress. *arXiv:0812.4360*.
- Oudeyer & Kaplan (2007). Intrinsic motivation systems for autonomous mental development. *IEEE Trans. Evolutionary Computation*.
- Dorigo & Stutzle (2004). *Ant Colony Optimization*. MIT Press.
- Gomez-Ramirez & Costa (2017). Boredom begets creativity. *Biosystems*.
- Danckert et al. (2025). Boredom signals deviation from a cognitive homeostatic set point. *Communications Psychology*.
- Heidegger (1929-30/1995). *The Fundamental Concepts of Metaphysics*. Indiana UP.
- Eastwood et al. (2012). The unengaged mind. *Perspectives on Psychological Science*.
- Bench & Lench (2013). On the function of boredom. *Behavioral Sciences*.
- Kelso et al. (1990). HKB metastability. See full citations in research document.
- Friston et al. (2015). Active inference and epistemic value. *Cognitive Neuroscience*.
- Yu, Chang & Kanai (2018). Boredom-driven curious learning by homeo-heterostatic value gradients. *Frontiers in Neurorobotics*.
