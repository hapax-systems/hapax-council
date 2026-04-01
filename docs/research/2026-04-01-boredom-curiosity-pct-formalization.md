# Boredom and Curiosity in Control-Theoretic Frameworks

**Date:** 2026-04-01
**Status:** Deep research — ready for design specification
**Depends on:** [SCM Spec](stigmergic-cognitive-mesh.md), [Control Law Specifications](2026-03-31-scm-control-law-specifications.md), [ControlSignal](../../shared/control_signal.py)

---

## Abstract

This document formalizes boredom and curiosity within Perceptual Control Theory (PCT) and related control-theoretic frameworks, targeting a system of coupled feedback loops where each component publishes `ControlSignal(reference, perception, error)` and communicates through shared traces (stigmergy), not direct signaling. Seven research threads are developed: PCT reorganization, control-theoretic curiosity, metastability and exploration, adaptive gain control, hierarchical predictive control, stigmergic trace dynamics, and coupled oscillator models. Each thread concludes with a concrete mapping to the SCM architecture.

---

## 1. PCT and Intrinsic Motivation: Reorganization as the Boredom Mechanism

### 1.1 Background

Powers (1973, 2005) defines a hierarchy of control systems where each level controls perceptions of a particular type (intensity → sensation → configuration → transition → sequence → program → principle → system concept). Above the entire hierarchy sits the **reorganization system** — a meta-controller that restructures the hierarchy itself when intrinsic variables deviate from genetically specified reference values.

### 1.2 Reorganization Mechanics

Reorganization is modeled after E. coli chemotaxis (Koshland, 1980). The bacterium swims in a straight line when nutrient concentration is increasing; when concentration drops, it tumbles randomly and tries a new direction. Powers adopted this into PCT:

```
R(t) = R₀ + ∫₀ᵗ η(s) · g(E_intrinsic(s)) ds
```

Where:
- `R(t)` is the parameter vector of the control hierarchy at time t
- `R₀` is the initial configuration
- `η(s)` is a random direction vector (unit norm, uniformly distributed on the hypersphere)
- `g(E_intrinsic(s))` is the reorganization rate, monotonically increasing with intrinsic error
- `E_intrinsic` is the aggregate error across all intrinsic (essential) variables

The reorganization rate is proportional to persistent error:

```
g(E) = k · E    (linear case)
```

When error is low, reorganization proceeds slowly or ceases. When error is high, parameters change rapidly in random directions. This is a **biased random walk** — biased because configurations that reduce intrinsic error persist (the random walk direction changes less frequently when error decreases).

### 1.3 Where Boredom Fits

Boredom maps to the reorganization level in two distinct ways:

**Boredom-as-chronic-low-error.** When the control hierarchy is perfectly controlling all its perceptions (error ≈ 0 across all levels), the reorganization system has no drive. But this is not stable in complex environments — without new disturbances, higher-level reference signals may shift (what Powers calls "going up a level"), creating error at the system concept level. The organism begins to control for something new.

**Boredom-as-stalled-reorganization.** When reorganization has been ongoing (high intrinsic error) but the random walk has not found a better configuration after many steps, the system is in a state of frustrated exploration. This maps to a plateau in the error landscape where random perturbations do not reduce error.

### 1.4 PCT vs. Free Energy Principle

Baltieri et al. (2025) formally compared PCT and FEP using category theory, arguing that PCT can be understood as a subset of the FEP framework. The key difference for boredom: FEP handles exploration through **expected free energy** (epistemic + pragmatic value), while PCT handles it through **reorganization** (random variation). PCT's mechanism is simpler but less directed — it does not compute information gain, it just perturbs randomly when things are bad.

### 1.5 Mapping to ControlSignal Architecture

The current `ControlSignal(component, reference, perception)` with `error = |reference - perception|` is a direct implementation of PCT's lower-level error computation. What is missing is a **meta-signal** at the reorganization level:

```python
@dataclass(frozen=True)
class ReorganizationSignal:
    """Meta-signal: should the system restructure?"""
    component: str
    chronic_error: float      # EMA of error over reorganization_window
    error_improvement: float  # d(chronic_error)/dt — are we making progress?
    reorganization_rate: float  # k * chronic_error
    stagnation: float         # time since last improvement > threshold
```

Boredom emerges when `chronic_error > 0` but `error_improvement ≈ 0` (stalled reorganization) OR when `chronic_error ≈ 0` for all components (nothing to control for).

---

## 2. Control Theory of Curiosity: Information Intake as a Controlled Variable

### 2.1 Schmidhuber's Compression Progress

Schmidhuber (2008) provides the most mathematically precise formalization of curiosity as a control signal. The core quantity is **compression progress** — the first derivative of the agent's ability to compress its observations:

```
curiosity_reward(t) = C(obs, t-1) - C(obs, t)
```

Where `C(obs, t)` is the description length (in bits) of the observation history using the agent's model at time t. When the model improves (learns a new regularity), `C` decreases and the reward is positive. When no further compression is possible (the data is already optimally compressed or is truly random), curiosity reward drops to zero.

**Boredom** = `curiosity_reward(t) ≈ 0` for extended periods (no compression progress).
**Anxiety** = the observation sequence has regularities that the agent cannot yet extract — high prediction error but no model improvement pathway visible.

### 2.2 Oudeyer-Kaplan Learning Progress

Oudeyer & Kaplan (2007) formalize curiosity as **learning progress** — the rate of decrease in prediction error within a particular sensorimotor region:

```
LP(region_i, t) = |ε(region_i, t - τ)| - |ε(region_i, t)|
```

Where `ε` is prediction error and `τ` is the evaluation window. The agent selects the region with highest `LP` — the one where it is learning fastest. This automatically avoids:
- Already-mastered regions (LP ≈ 0, nothing left to learn)
- Incomprehensible regions (LP ≈ 0, prediction error is high but not decreasing)

### 2.3 Information Intake Rate as a Controlled Variable

Synthesizing these, curiosity can be modeled as a **controlled variable** in PCT terms:

```
reference = target_learning_progress  (desired compression progress rate)
perception = actual_learning_progress (measured compression progress rate)
error = |reference - perception|
```

When `perception < reference`: boredom. The system is not learning fast enough.
When `perception > capacity`: anxiety/overwhelm. Information arrives faster than it can be compressed.

The reference signal for "desired learning progress" is itself set by a higher level in the hierarchy — it is not fixed. This creates a cascade: when the environment is rich, the reference rises (the system expects to keep learning). When the environment is impoverished, the reference decays (but slowly — creating a period of boredom before adaptation).

### 2.4 Mapping to ControlSignal Architecture

Each component already computes error. The missing quantity is the **rate of change of error** — is error decreasing (learning/adaptation), stable (equilibrium or stagnation), or increasing (degradation)?

```python
@dataclass(frozen=True)
class CuriositySignal:
    """Learning progress per component."""
    component: str
    error_derivative: float    # d(error)/dt — negative = learning, positive = degrading
    compression_progress: float  # bits saved per tick (if model is improving)
    novelty: float             # divergence of current perception from recent history
```

For the stigmergic mesh: each component reads traces from other components. The "learning" analog is how well a component can predict the traces it reads. If stimmung can predict DMN observations perfectly, stimmung has nothing to gain from reading DMN — boredom on that channel. If a new pattern appears in DMN observations that stimmung cannot predict, that channel becomes interesting.

---

## 3. Metastability and Exploration: Kelso's Coordination Dynamics

### 3.1 The Haken-Kelso-Bunz (HKB) Equation

The canonical equation for coordination dynamics:

```
φ̇ = Δω - a·sin(φ) - 2b·sin(2φ) + √Q·ξ(t)
```

Where:
- `φ` is relative phase between two coupled components
- `Δω` is intrinsic frequency difference (symmetry breaking parameter)
- `a, b` are coupling strengths
- `Q` is noise intensity
- `ξ(t)` is Gaussian white noise

**Metastability** occurs when `Δω` is large enough that no fixed points exist, but the remnants (ghosts) of the former attractors still influence the trajectory. The system dwells near these ghost attractors before escaping.

### 3.2 Dwelling Time and Escape Time

Kelso et al. (1990) showed that in the metastable regime:

**Dwelling time** `T_dwell` (time spent near a remnant attractor):
- Increases with coupling strength (stronger coupling = longer dwelling)
- Increases with symmetry (smaller Δω = longer dwelling)
- In the limit of zero noise, dwelling time → ∞ (the system gets trapped)

**Escape time** `T_escape` (time to transition between remnants):
- Decreases with intrinsic frequency difference (larger Δω = faster escape)
- Influenced by noise intensity Q (more noise = shorter escape times)

The critical insight: **boredom is the destabilization of a stable attractor**. When coupling strength decays (the components stop reinforcing each other's phase), a formerly stable synchronized state becomes metastable, and eventually the system escapes to explore new phase relationships.

### 3.3 Boredom as Coupling Decay

Formally, introduce time-dependent coupling:

```
a(t) = a₀ · exp(-λ · T_sync(t))
```

Where `T_sync(t)` is the cumulative time the system has spent in synchrony (phase-locked within some threshold). The longer the system stays synchronized, the weaker the coupling becomes, until the synchronized state destabilizes and the system transitions.

This is structurally identical to habituation: the response to a sustained stimulus decays over time.

### 3.4 Mapping to ControlSignal Architecture

In the SCM, "phase" corresponds to the alignment between a component's output and the patterns in the traces it reads. Two components are "synchronized" when their traces are mutually predictable. The coupling decays when predictability persists — this is the boredom mechanism at the mesh level.

```python
@dataclass
class MetastabilityState:
    """Per-edge metastability in the reading-dependency graph."""
    reader: str
    writer: str
    phase_coherence: float      # 0-1, how predictable writer's trace is to reader
    dwell_time: float           # seconds in current coherence regime
    coupling_strength: float    # decays with dwell_time when coherent
    escape_probability: float   # P(transition) per tick
```

When `phase_coherence` is high and `dwell_time` is large, `coupling_strength` has decayed and `escape_probability` is elevated — the system is primed to break out of its current pattern. The "escape" in the mesh is a component changing its reference signal or reading a different set of traces.

---

## 4. Adaptive Gain Control: Divisive Normalization and Boredom

### 4.1 The Carandini-Heeger Normalization Model

Divisive normalization (Carandini & Heeger, 2012) is now considered a canonical neural computation. The response of a neuron is:

```
R_i = D_i^n / (σ^n + Σ_j w_j · D_j^n)
```

Where:
- `D_i` is the driving input to neuron i
- `σ` is the semi-saturation constant
- `w_j` are normalization weights (from the normalization pool)
- `n` is an exponent (typically 2)

The denominator (the normalization pool) implements gain control: when the pool is active, individual responses are suppressed. When a novel stimulus activates a channel not in the current normalization pool, it gets a high-gain response.

### 4.2 Habituation as Gain Reduction

Sustained stimulation on channel i causes the normalization weight `w_i` to increase over time:

```
dw_i/dt = α · R_i - β · w_i
```

Where α is the accumulation rate and β is the decay rate. As `w_i` increases, the denominator grows, and `R_i` decreases — the channel habituates. When stimulation stops, `w_i` decays back to baseline, and sensitivity recovers.

### 4.3 Novelty as Gain Asymmetry

A novel stimulus activates a channel j where `w_j ≈ 0` (no accumulated normalization weight). This channel gets a disproportionately strong response relative to habituated channels:

```
gain_novel / gain_habituated = (σ^n + Σ w_j D_j^n) / σ^n ≫ 1
```

This is boredom and curiosity in gain terms:
- **Boredom** = all channels have high normalization weights (everything is habituated, nothing gets a strong response)
- **Curiosity** = a channel has low normalization weight (novel input gets amplified)

### 4.4 Formal Model: Time-Dependent Gain per Trace Channel

For the SCM, each reading edge (reader → writer) has a gain that decreases with exposure:

```
gain(edge_ij, t) = G_max / (1 + κ · ∫₀ᵗ I(edge_ij, s) ds)
```

Where:
- `G_max` is maximum gain (novelty response)
- `κ` is the habituation rate
- `I(edge_ij, s)` is a binary indicator: 1 if the reader successfully predicted the writer's trace at time s, 0 otherwise

**Boredom index** for a component:

```
B_i(t) = 1 - (1/|E_i|) Σ_{j ∈ E_i} gain(edge_ij, t) / G_max
```

Where `E_i` is the set of edges (traces) that component i reads. When `B_i → 1`, all channels are habituated. When `B_i → 0`, all channels are novel.

### 4.5 Mapping to ControlSignal Architecture

```python
@dataclass(frozen=True)
class GainState:
    """Per-edge gain in the reading-dependency graph."""
    reader: str
    writer: str
    gain: float                 # current gain (0 to G_max)
    normalization_weight: float  # accumulated exposure
    novelty_score: float        # inverse of normalization_weight, normalized
    habituation_fraction: float  # 1 - gain/G_max
```

The component's overall boredom is the mean habituation across all its input edges. The action when boredom exceeds a threshold: the component should either (a) change what it reads (explore new traces), (b) change how it reads (modify its restriction map), or (c) signal to the reorganization level that it needs restructuring.

---

## 5. Hierarchical Predictive Control and the Zero-Error Problem

### 5.1 The Boredom Trap in Predictive Processing

Gomez-Ramirez & Costa (2017) identify a fundamental problem in hierarchical predictive systems: if the system's sole objective is minimizing prediction error, it should seek maximally predictable environments and never explore. They call this the "dark room problem" (Friston's term) or more precisely, the **exploitation trap**.

Their resolution uses a model inspired by Black-Scholes-Merton option pricing:

```
dV/dt = μV dt + σV dW
```

Where:
- `V` is the subjective value of the current behavioral policy
- `μ` is the drift (expected prediction pleasure from exploitation)
- `σ` is volatility (uncertainty from exploration)
- `dW` is a Wiener process (random exploration)

**Boredom** enters as a **time-decay on subjective value**:

```
dV/dt = (μ - λ_boredom) · V dt + σV dW
```

Where `λ_boredom > 0` is the boredom rate. Even when prediction pleasure `μ` is positive (the system is successfully predicting), `V` eventually declines if `λ_boredom > μ`. This forces the system to abandon successful-but-stale policies and explore.

### 5.2 Precision-Weighted Prediction Error

In the Free Energy framework (Friston, 2009), prediction errors are weighted by their **precision** (inverse variance). Boredom maps to **precision reduction on familiar channels**:

```
F = Σ_i π_i · ε_i²
```

Where:
- `F` is (variational) free energy
- `π_i` is precision of prediction error on channel i
- `ε_i` is prediction error on channel i

When a prediction is chronically accurate, precision `π_i` decreases (the system "stops paying attention" to that channel). This has two effects:
1. The contribution of channel i to overall free energy drops — the system cares less about maintaining accuracy on that channel.
2. Resources (attention) are freed for channels with higher precision (novel or important signals).

### 5.3 Expected Free Energy and Curiosity

Friston et al. (2015, 2019) decompose expected free energy into:

```
G(π) = -E_Q[ln P(o|C)] + E_Q[H[P(s|o)]]
     = -extrinsic_value   + epistemic_value
```

Where:
- Extrinsic value: expected utility relative to preferred outcomes
- Epistemic value: expected information gain (mutual information between hidden states and observations)

Curiosity corresponds to policies that maximize epistemic value. When all observations are fully predicted (epistemic value = 0), only extrinsic value drives behavior. When extrinsic value is also satisfied (all goals met), **expected free energy is minimized everywhere** — the system has nothing to do. This is the formal definition of chronic zero-error boredom.

### 5.4 Higher-Level Goal Vacancy

In a hierarchical system, higher levels set reference signals for lower levels. When a higher-level goal is achieved (error = 0), two things can happen:

1. **Goal replacement:** The higher level generates a new reference signal. This requires a source of new goals — either from an even higher level, or from reorganization.
2. **Goal vacancy:** No new reference signal is generated. Lower levels continue operating but are now controlling for nothing meaningful. Their error may be zero (successfully controlling for a vestigial reference) or rising (environment changes while no one is steering).

Goal vacancy is the hierarchical version of boredom. The detection criterion:

```
vacancy(level_k) = (error_k < ε_low) AND (Σ_{j < k} error_j < ε_low) AND (duration > T_vacancy)
```

All levels below k have low error, level k has low error, and this has persisted for longer than `T_vacancy`. The system is functioning but not accomplishing anything new.

### 5.5 Mapping to ControlSignal Architecture

The existing `ControlSignal` reports error but not precision or temporal dynamics. Extension:

```python
@dataclass(frozen=True)
class HierarchicalControlSignal(ControlSignal):
    """Extended signal with precision and goal vacancy detection."""
    precision: float          # inverse variance of error over recent window
    error_derivative: float   # d(error)/dt
    vacancy_duration: float   # seconds since error last exceeded threshold
    goal_active: bool         # whether a meaningful reference is set
```

A component signals boredom when `error ≈ 0`, `error_derivative ≈ 0`, and `vacancy_duration > T_vacancy`. The reorganization response: either the component requests a new reference from a higher level (DMN generates new concerns), or it begins random exploration (perturbing its own parameters to see if interesting error patterns emerge).

---

## 6. Stigmergic Trace Dynamics: Pheromone Evaporation as Boredom

### 6.1 ACO Pheromone Update Rule

In Ant Colony Optimization (Dorigo & Stutzle, 2004), the pheromone on edge (i,j) evolves as:

```
τ_ij(t+1) = (1 - ρ) · τ_ij(t) + Σ_k Δτ_ij^k
```

Where:
- `ρ ∈ (0,1)` is the evaporation rate
- `Δτ_ij^k` is the pheromone deposited by ant k on edge (i,j)

**Evaporation** (`ρ`) is the boredom mechanism:
- Without evaporation (`ρ = 0`), pheromone accumulates monotonically. The colony converges to a single path and never explores alternatives. This is the exploitation trap.
- With high evaporation (`ρ → 1`), traces vanish before they can reinforce. The colony never converges. This is pure exploration without learning.
- The optimal `ρ` balances convergence speed against solution quality.

### 6.2 Optimal Evaporation Rate

Stützle & Hoos (2000) proved convergence of the MAX-MIN Ant System (MMAS), which bounds pheromone to `[τ_min, τ_max]`:

```
τ_max = (1/ρ) · (1/f*)
τ_min = τ_max · (1 - p_best^(1/n)) / ((n/2 - 1) · p_best^(1/n))
```

Where `f*` is the best solution cost, `n` is the problem dimension, and `p_best` is the desired probability that the best solution is constructed.

The **effective exploration rate** depends on the ratio `τ_max/τ_min`:
- When `ρ` is small, `τ_max` is large, the ratio grows, and the system exploits heavily.
- When `ρ` is large, `τ_max` is small, the ratio shrinks, and exploration dominates.

Adaptive approaches (Stützle et al., 2010) vary `ρ` over time: high initially (explore), decreasing as the search progresses (exploit found solutions), then increasing again if stagnation is detected. **Stagnation detection is the formal analog of boredom detection.**

### 6.3 Evaporation in the SCM Trace Architecture

The SCM traces on `/dev/shm` are JSON files overwritten on each tick. They do not accumulate like pheromone — they are replaced. However, derived quantities (pattern confidence, temporal band entries, apperception dimensions) do accumulate. The evaporation analog for the SCM is the **decay of these accumulated quantities**.

Current decay mechanisms in the codebase:
- `_pattern_consolidation.py`: pattern confidence decays with `days_since_confirmed`
- `visual_chain.py`: visual chain state decays at `decay_rate = 0.02` per second
- `ghost.py` (studio effect): temporal persistence with exponential decay

What is missing: a **trace freshness mechanism** that reduces the weight of any trace that has not changed recently. A trace that reports the same value tick after tick should gradually lose influence — not because the information is wrong, but because it is not informative. This is evaporation applied to information value rather than information content.

### 6.4 Formal Model: Trace Interest Decay

```
interest(trace_j, t) = interest_0 · exp(-ρ · T_unchanged(t))
```

Where:
- `interest_0` is the initial interest when the trace last changed
- `ρ` is the evaporation rate (boredom rate)
- `T_unchanged(t)` is the time since the trace's value last changed meaningfully

"Changed meaningfully" requires a threshold: `|trace_j(t) - trace_j(t_last_change)| > δ_j`. This prevents noise from resetting the interest clock.

The **exploration-exploitation balance** for a reader depends on the aggregate interest across its input traces:

```
aggregate_interest_i(t) = (1/|E_i|) Σ_{j ∈ E_i} interest(trace_j, t)
```

When `aggregate_interest_i < θ_bored`, the component should:
1. Increase its sensitivity to small changes in existing traces (gain increase)
2. Seek out traces it does not currently read (exploration)
3. Signal to the DMN that it has excess capacity (available for reassignment)

### 6.5 Adaptive Evaporation

The evaporation rate itself should be adaptive:

```
ρ_i(t) = ρ_base + ρ_adapt · sigmoid(stagnation_i(t) - T_stagnation)
```

Where `stagnation_i(t)` measures how long component i has been in a low-interest state. When stagnation exceeds `T_stagnation`, the evaporation rate increases sharply — "patience runs out" and the system actively discards accumulated trace weights to force re-evaluation.

---

## 7. Coupled Oscillator Models: Phase-Locking as Boredom

### 7.1 Standard Kuramoto Model

The Kuramoto model for N oscillators:

```
θ̇_i = ω_i + (K/N) Σ_j sin(θ_j - θ_i)
```

Where:
- `θ_i` is the phase of oscillator i
- `ω_i` is the natural frequency
- `K` is the coupling strength

At critical coupling `K_c`, the system transitions from incoherence to partial synchronization. The order parameter:

```
r · e^(iψ) = (1/N) Σ_j e^(iθ_j)
```

Where `r ∈ [0,1]` measures global coherence (1 = full sync, 0 = incoherence).

### 7.2 Boredom as Chronic Synchronization

Full synchronization (`r → 1`) in a cognitive system means all components are phase-locked — producing and consuming traces in a rigid, predictable pattern. This is functionally boring: no new information flows, no surprises, no learning.

Introduce **time-in-synchrony dependent coupling decay**:

```
K(t) = K_0 · exp(-λ · ∫₀ᵗ H(r(s) - r_sync) ds)
```

Where:
- `K_0` is the base coupling strength
- `λ` is the boredom decay rate
- `H` is the Heaviside function
- `r_sync` is the synchronization threshold

The integral accumulates time spent in synchrony. The longer the system stays synchronized, the weaker the coupling, until eventually `K < K_c` and the system desynchronizes — entering an exploratory phase.

### 7.3 Environment-Mediated Coupling (Stigmergic Kuramoto)

Schwab et al. (2012) generalized the Kuramoto model to **indirect coupling through an external medium**:

```
θ̇_i = ω_i + κ · Im(H · e^(-iθ_i))
H = Σ_j (e^(iθ_j) / N) / (1 + αH)
```

Where `H` is the state of the shared medium and `α` controls the medium's response. This is directly analogous to stigmergy: oscillators do not sense each other directly, they sense the shared medium (the traces on `/dev/shm`), and their contributions to the medium mix.

Key result: environment-mediated coupling produces **bistability** between synchronization and incoherence that does not exist in the standard Kuramoto model. The system can be "trapped" in either regime, requiring a perturbation to transition. This is exactly the boredom-escape dynamic: the system can be trapped in synchrony (boring) and needs a perturbation (internal or external) to break free.

### 7.4 Lambert's Stigmergic Oscillator Model

Lambert (2012) proposed a specifically stigmergic alternative to Kuramoto for music systems:

- Each oscillator deposits a "pulse" on a shared trace (local field)
- Coupling is mediated entirely through the trace — no global state
- The trace has spatial extent (oscillators are affected more by nearby traces)
- The trace **decays over time** — the evaporation mechanism

This model exhibits synchronization through purely local, indirect interactions. Crucially, the decay rate of the trace controls the exploration-exploitation balance exactly as pheromone evaporation does in ACO.

### 7.5 Mapping to ControlSignal Architecture

The SCM's 14 components do not have explicit "phases" but they do have **cadences** (tick rates) and **publication timestamps**. The analog of phase coherence is:

```python
@dataclass
class OscillatorState:
    """Per-component oscillator characterization."""
    component: str
    effective_frequency: float  # 1 / mean_inter_tick_interval
    phase: float               # normalized position in tick cycle
    coherence_with: dict[str, float]  # per-reader coherence

def mesh_order_parameter(states: list[OscillatorState]) -> float:
    """Global synchronization measure (Kuramoto r)."""
    phases = [s.phase for s in states]
    r = abs(sum(cmath.exp(1j * p) for p in phases) / len(phases))
    return r
```

When the mesh order parameter is high for extended periods, the system is over-synchronized (boring). The corrective action: reduce coupling by having components skip trace reads (effectively reducing K), or introduce deliberate phase perturbations (stochastic delays in tick timing).

---

## 8. Unified Formalization: Boredom and Curiosity in the SCM

### 8.1 Synthesis

All seven frameworks converge on the same structure:

| Framework | Boredom Signal | Curiosity Signal | Escape Mechanism |
|-----------|---------------|-----------------|------------------|
| PCT Reorganization | Chronic low error + no improvement | High reorganization rate | Random parameter variation |
| Compression Progress | Zero learning progress | High compression progress | Seek compressible novelty |
| HKB Metastability | Long dwelling time in attractor | Phase transition approaching | Coupling decay + noise |
| Divisive Normalization | High habituation across channels | Novel channel with low norm weight | Gain asymmetry |
| Predictive Processing | Low precision on all channels | High epistemic value | Expected free energy minimization |
| ACO Evaporation | Stale pheromone (all trails equal) | Fresh deposit on unexplored trail | Trace decay |
| Kuramoto Synchrony | High order parameter sustained | Low order parameter (desynchrony) | Coupling strength decay |

### 8.2 Proposed ControlSignal Extension

A unified boredom/curiosity layer for the SCM, compatible with the existing `ControlSignal`:

```python
@dataclass(frozen=True)
class ExplorationSignal:
    """Boredom/curiosity state for a mesh component."""
    component: str

    # PCT reorganization
    chronic_error: float            # EMA of ControlSignal.error
    error_improvement_rate: float   # d(chronic_error)/dt

    # Gain control (per-input-edge average)
    mean_habituation: float         # 0 = all novel, 1 = all habituated
    max_novelty_edge: str           # which input trace is most novel

    # Trace interest (evaporation)
    mean_trace_interest: float      # aggregate interest across input traces
    stagnation_duration: float      # seconds since any input trace changed meaningfully

    # Phase coherence
    mesh_coherence: float           # local order parameter (coherence with neighbors)
    dwell_time_in_coherence: float  # seconds at current coherence level

    @property
    def boredom_index(self) -> float:
        """Composite boredom score: 0 = fully engaged, 1 = maximally bored."""
        return (
            0.3 * self.mean_habituation
            + 0.3 * (1.0 - self.mean_trace_interest)
            + 0.2 * min(1.0, self.stagnation_duration / 300.0)
            + 0.2 * min(1.0, self.dwell_time_in_coherence / 300.0)
        )

    @property
    def curiosity_index(self) -> float:
        """Composite curiosity score: 0 = no drive to explore, 1 = maximum."""
        reorganization_drive = min(1.0, self.chronic_error) * (1.0 if self.error_improvement_rate <= 0 else 0.5)
        novelty_opportunity = 1.0 - self.mean_habituation
        return max(reorganization_drive, novelty_opportunity, 1.0 - self.mesh_coherence)

    @property
    def exploration_probability(self) -> float:
        """Probability of taking an exploratory action this tick."""
        return sigmoid(self.boredom_index - 0.5) * self.curiosity_index
```

### 8.3 Control Law: Boredom-Driven Exploration

```
IF boredom_index > θ_bored (0.7):
    1. Increase gain on least-habituated input edges (gain × 1.5)
    2. Decrease gain on most-habituated input edges (gain × 0.5)
    3. With probability exploration_probability:
       a. Read a trace not currently in the component's input set
       b. Perturb reference signal by ε ~ N(0, σ_explore)
    4. Publish impingement(type=BOREDOM, strength=boredom_index)
       → DMN can restructure reference signals

IF curiosity_index > θ_curious (0.6) AND boredom_index < θ_bored:
    1. The system is not bored but has found something interesting
    2. Increase gain on the max_novelty_edge
    3. Increase tick rate (sample more frequently from interesting trace)
    4. Publish impingement(type=CURIOSITY, strength=curiosity_index)
       → DMN can allocate attention resources
```

### 8.4 Parameter Regimes

| Parameter | Value | Source | Rationale |
|-----------|-------|--------|-----------|
| Habituation rate κ | 0.01/s | Carandini & Heeger analogy | Full habituation in ~100s of unchanged input |
| Evaporation rate ρ_base | 0.005/s | ACO literature | Trace interest halves in ~140s |
| Adaptive ρ increment | 0.02/s | ACO adaptive schemes | 4x faster decay when stagnated |
| Coupling decay λ | 0.003/s | HKB parameter regime | Coupling halves after ~230s in sync |
| Boredom threshold | 0.7 | - | Trigger exploration when 70% habituated |
| Curiosity threshold | 0.6 | - | Focus attention when novelty found |
| Vacancy timeout T_vacancy | 300s | 5 minutes | Flag goal vacancy after 5 min zero-error |
| Stagnation timeout T_stagnation | 300s | 5 minutes | Accelerate evaporation after 5 min |

### 8.5 Interaction with Existing SCM Components

**Stimmung:** Boredom signals from multiple components aggregate into a system-wide "engagement" dimension in stimmung. Low aggregate engagement shifts stance toward a more exploratory mode (potentially a new stance level between nominal and cautious: "seeking").

**DMN (Pulse Daemon):** Receives boredom impingements. When multiple components report boredom simultaneously, DMN's evaluative tick should prioritize generating novel observations — looking for patterns it hasn't noticed before, asking different questions of the visual surface.

**Imagination Daemon:** Boredom signals should increase imagination's `salience` threshold and broaden its `material` selection. When the system is bored, imagination should range more widely rather than refining existing themes.

**Reverie (Visual Surface):** Boredom maps to the visual vocabulary: increased `diffusion` parameter, more temporal feedback (the `@accum_fb` node), and longer crossfade times between content slots — the visual surface becomes more contemplative, less reactive.

**Temporal Bands:** A bored system's temporal signature changes — the retention ring should show longer protention (looking further ahead for novelty) and shorter retention (letting go of recent-but-uninteresting patterns faster).

---

## 9. Mathematical Appendix

### 9.1 Sigmoid Function

```
sigmoid(x) = 1 / (1 + exp(-k·x))
```

With `k = 10` for sharp transitions in the exploration probability.

### 9.2 Exponential Moving Average for Chronic Error

```
EMA(t) = α · error(t) + (1 - α) · EMA(t-1)
```

With `α = 0.05` (20-tick memory at 1Hz tick rate).

### 9.3 Trace Change Detection

A trace has "changed meaningfully" when:

```
|trace(t) - trace(t_last_change)| > δ
```

Where `δ` is per-trace and set to the trace's historical standard deviation: `δ_j = σ_j(history)`. This makes the change detector scale-invariant — a 0.01 change in a trace that varies by 0.001 is meaningful; a 0.01 change in a trace that varies by 1.0 is not.

### 9.4 Local Order Parameter

For component i with neighbors N(i) in the reading-dependency graph:

```
r_i = |Σ_{j ∈ N(i)} e^(i·θ_j)| / |N(i)|
```

Where `θ_j = 2π · (t_j mod T_j) / T_j` and `T_j` is component j's tick period.

---

## Sources

- [Perceptual Control Theory — Wikipedia](https://en.wikipedia.org/wiki/Perceptual_control_theory)
- [PCT vs. FEP: Reorganization Theory and Bayesian Inference (2025)](https://www.mdpi.com/2673-9321/5/4/35)
- [Schmidhuber — Driven by Compression Progress (2008)](https://arxiv.org/abs/0812.4360)
- [Schmidhuber — Formal Theory of Creativity, Fun, and Intrinsic Motivation](https://people.idsia.ch/~juergen/ieeecreative.pdf)
- [Oudeyer & Kaplan — Intrinsic Motivation Systems for Autonomous Mental Development](http://www.pyoudeyer.com/ims.pdf)
- [Oudeyer & Kaplan — What is Intrinsic Motivation? A Typology](https://pubmed.ncbi.nlm.nih.gov/18958277/)
- [Kelso et al. — Multistability and Metastability in the Brain](https://royalsocietypublishing.org/doi/10.1098/rstb.2011.0351)
- [Hancock & Kelso — Metastability Demystified (2024)](https://ccs.fau.edu/hbblab/pdfs/2024_Hancock_Kelso_NRN.pdf)
- [Haken-Kelso-Bunz Model — Scholarpedia](http://www.scholarpedia.org/article/Haken-Kelso-Bunz_model)
- [HKB Model: From Matter to Movement to Mind](https://link.springer.com/article/10.1007/s00422-021-00890-w)
- [Carandini & Heeger — Normalization as a Canonical Neural Computation (2012)](https://www.nature.com/articles/nrn3136)
- [Adaptive Gain Control During Human Perceptual Choice](https://pmc.ncbi.nlm.nih.gov/articles/PMC4411568/)
- [Optimal Information Gain at the Onset of Habituation](https://elifesciences.org/reviewed-preprints/99767v2)
- [Gomez-Ramirez & Costa — Boredom Begets Creativity (2017)](https://pubmed.ncbi.nlm.nih.gov/28479110/)
- [Synthesising Boredom: A Predictive Processing Approach (2023)](https://link.springer.com/article/10.1007/s11229-023-04380-3)
- [Friston — Active Inference and Epistemic Value (2015)](https://pubmed.ncbi.nlm.nih.gov/25689102/)
- [Friston — Generalised Free Energy and Active Inference (2019)](https://link.springer.com/article/10.1007/s00422-019-00805-w)
- [Friston — Predictive Coding Under the Free-Energy Principle](https://pmc.ncbi.nlm.nih.gov/articles/PMC2666703/)
- [Dorigo & Stützle — Ant Colony Optimization (2004)](https://web2.qatar.cmu.edu/~gdicaro/15382/additional/aco-book.pdf)
- [Stützle et al. — Parameter Adaptation in ACO (2010)](https://lopez-ibanez.eu/doc/StuLopPelMau2010adaptiveACO.pdf)
- [ACO with Self-Adaptive Evaporation Rate in Dynamic Environments](https://ieeexplore.ieee.org/document/7007866/)
- [Kuramoto Model — Wikipedia](https://en.wikipedia.org/wiki/Kuramoto_model)
- [Kuramoto Model with Coupling Through an External Medium](https://pmc.ncbi.nlm.nih.gov/articles/PMC3532102/)
- [Lambert — A Stigmergic Model for Oscillator Synchronisation (ICMC 2012)](https://quod.lib.umich.edu/i/icmc/bbp2372.2012.044/1)
- [Stigmergy: From Mathematical Modelling to Control (2024)](https://royalsocietypublishing.org/rsos/article/11/9/240845/92941)
- [Computational Theories of Curiosity-Driven Learning](https://arxiv.org/pdf/1802.10546)
- [A Nice Surprise? Predictive Processing and the Active Pursuit of Novelty](https://link.springer.com/article/10.1007/s11097-017-9525-z)
