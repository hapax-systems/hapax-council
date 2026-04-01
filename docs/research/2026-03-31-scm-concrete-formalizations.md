# SCM Concrete Formalizations: Applied Mathematical Frameworks

**Date:** 2026-03-31
**Status:** Active research — ready for design spec production
**Depends on:** [SCM Spec](stigmergic-cognitive-mesh.md), [Remaining Gaps Research](2026-03-31-scm-remaining-gaps-research.md)

---

## Abstract

This document instantiates four mathematical frameworks on the 14-node stigmergic cognitive mesh, producing concrete structures with specific numbers, types, and computability assessments. Each framework is grounded in actual /dev/shm file paths, JSON schemas, and codebase-derived restriction maps — not abstract algebra dressed in our vocabulary.

---

## 1. Cellular Sheaf on the Reading-Dependency Graph

### 1.1 Base Space

Directed graph G = (V, E) with |V| = 14 processes and |E| = 31 reading edges. Edge A → B means "A reads B's trace."

The graph has one tetrahedron (3-simplex): **{DMN, Imagination, Stimmung, Reverie}** — the cognitive core where background cognition, imaginative production, affective state, and visual expression are all pairwise coupled.

### 1.2 Stalks

Each stalk F(v) is the typed product space of that node's JSON state. Representative dimensions:

| Node | Stalk dimension (linearized) | Key types |
|------|------------------------------|-----------|
| Stimmung (v5) | 32 | 10 × DimensionReading(value, trend, freshness) + Stance + timestamp |
| DMN (v3) | 15 | observations[5], tick, published_at, status fields |
| Imagination (v4) | 10 | content_refs[], dimensions{3}, salience, continuation, material |
| IR Perception (v0) | 14 | 14 sensor signals (bool, float, enum) |
| Reverie (v10) | 20 | 15 shader params + 4 slot opacities + stance uniform |
| Apperception (v7) | 14 | 7 self-dimensions × (confidence, counts) |

Total linearized dimension across all stalks: **~168**.

### 1.3 Restriction Maps

Every restriction map is a lossy projection. No restriction map is an embedding — information is always lost from writer to reader.

Example: DMN reads stimmung (e0):
```
ρ(e0): F(v5) → partial(F(v3))
  42 keys → 7 keys: stance, operator_stress, error_rate, grounding_quality, age_s, stale, source
  DimensionReading triple (value, trend, freshness_s) collapses to just value
  Reader ADDS computed fields (age_s, stale) not in writer's trace
```

Example: Reverie reads stimmung (e11):
```
ρ(e11): F(v5) → partial(F(v10))
  42 keys → 2 floats: signal.stance (ordinal), signal.color_warmth (derived)
  Extreme projection: entire system mood → 2 GPU uniform values
```

### 1.4 Cohomology

**H^0 (global sections):** A consistent assignment of values to all 14 nodes where restriction maps agree. H^0 ≈ 0 in practice because heterogeneous cadences guarantee that readings are sampled at different times. Global sections only exist during system stasis (deep idle, steady production).

**H^1 (obstructions):** Measures where and how local observations fail to cohere. Concrete generators:

1. **Stimmung-perception split:** stance=nominal but ir_person_detected=false with age < 10s. System is "healthy" but perceiving nobody.
2. **Imagination-observation divergence:** DMN observations are bland ("stable×5") but imagination produces material=fire, salience=0.9. Internal LLM state not captured in any trace.
3. **Temporal-perception desynchronization:** Temporal bands report activity=idle but contact mic shows energy=0.8. The retention ring hasn't incorporated the acoustic event yet.

**Key insight:** H^1 is never zero in practice. System health is measured by whether all H^1 generators are **transient** (lifetime bounded by slowest reader cadence), not by H^1 = 0.

### 1.5 Computational Feasibility

Coboundary map δ^0 is a **120 × 168 sparse matrix**. SVD computation: <5ms via numpy. Easily within a 1-second DMN tick. Libraries: pysheaf, numpy, networkx. For a 14-node system, this is matrix algebra, not topology.

---

## 2. Scott Domain for Trace Configurations

### 2.1 Tokens

~705 leaf keys across ~40 JSON files. Discretized to ~100 bins per continuous dimension: **~70,700 tokens**. Each token is a triple (path, key, value).

### 2.2 Consistency

**Syntactic:** Single-key uniqueness (enforced by atomic rename). Cross-file independence (each file has one writer — 38/40 files are single-writer).

**Semantic:** Constraints that should hold but aren't mechanically enforced: presence coherence, stance-dimension coherence, flow-activity coherence, imagination-observation coherence, grounding-voice coherence.

### 2.3 CRDT Properties

The system IS a collection of **LWW-Registers**. Every trace file has exactly one writer. No merge function needed. The only "merge" is logical: readers combine multiple trace files into a local snapshot (read-side join, not write-side merge).

---

## 3. Persistent Homology

β₀ = 1 (connected), β₁ ≈ 7 (seven independent information loops). The tetrahedron {DMN, Imagination, Stimmung, Reverie} is the densest subcomplex.

**Phase transitions under failure:**
- DMN crash: β₁ drops 7 → ~2. Catastrophic to topological richness.
- Stimmung crash: β₁ drops 7 → ~3-4. System more resilient than DMN loss.
- IR Perception offline: β₀ and β₁ unchanged. Leaf nodes are topologically invisible.

**Topological stability** = min(β₁ after single-node removal / β₁ before) = ~0.29 (DMN-bound). This confirms DMN as the critical hub.

---

## 4. Traced Monoidal Category

### 4.1 Objects

16 typed objects derived from codebase JSON schemas: StimmungState (O1), PerceptionBehaviors (O2), IrDetectionReport (O3), WatchBiometrics (O4), SensorSnapshot (O5), DMNObservations (O6), Impingement (O7), ImaginationFragment (O8), VisualChainState (O9), VisualOutput (O10), VisualLayerState (O11), TemporalContext (O12), ApperceptionState (O13), ControlSignal (O14), OperatorBehavior (O15), VoiceOutput (O16). Unit I = empty/stale trace.

### 4.2 Morphisms

Each process is a morphism. Key morphisms:

| Morphism | Domain | Codomain |
|----------|--------|----------|
| stimmung_collector | O14 ⊗ O4 ⊗ O2 | O1 |
| dmn_sensory | O5 | O6 ⊗ O7 |
| imagination | O6 ⊗ O5 ⊗ O1 | O8 ⊗ O7 |
| reverie_pipeline | O9 ⊗ O8 ⊗ O1 | O10 |
| **operator** | O10 ⊗ O16 ⊗ O11 | **O15** |

### 4.3 The Trace

System composite S: O15 → O10 ⊗ O16 ⊗ O11. Operator Op: O10 ⊗ O16 ⊗ O11 → O15. The trace closes the loop:

```
Tr_B(F): X → Y
  X = initial conditions (working mode, time, config, calendar)
  Y = external effects (Langfuse traces, ntfy, Qdrant writes, journal)
  B = OperatorBehavior (traced out — invisible from outside)
```

The autonomous system is `Tr_B(F)`. The operator's behavior circulates internally. An external observer sees only boot conditions and side effects.

### 4.4 Int Construction

In Int(C), System = (SystemOutput⁺, OperatorBehavior⁻) and Operator = (OperatorBehavior⁺, SystemOutput⁻). They are **dual**: what the system produces is what the operator consumes, and vice versa. The trace in C becomes ordinary composition in Int(C).

---

## 5. Eigenform Analysis

### 5.1 State Vector

x ∈ ℝ^~25 with components: presence_probability, activity, flow_state, flow_score, audio_energy, heart_rate, stimmung_stance, operator_stress, imagination_salience, visual_brightness, display_density, surprise_max, apperception_coherence.

### 5.2 Convergence

T(x) = one complete perception → cognition → expression → operator response loop.

| Scenario | Convergence | Time | Mechanism |
|----------|-------------|------|-----------|
| Deep work arrival | x* = {flow=deep, visual=ambient, stimmung=nominal} | 10-15 min | Negative feedback, flow hysteresis (300s floor) |
| Music production | Stable orbit O* in ~5-dim subspace | N/A (quasiperiodic) | Contact mic ↔ visual chain ↔ operator lag structure |
| IR miscalibration | Divergence | Unbounded | Phantom operator, stale content production |

### 5.3 EigenBEHAVIOR (Music Production)

Not a fixed point but a stable orbit: operator creates → system responds visually → operator adjusts → system adapts. Period: ~10-20s (4-8 VLA ticks). Orbiting dimensions: audio_energy, imagination_salience, visual intensity/tension/spectral_color, desk_activity.

---

## 6. Coupled PCT Model

### 6.1 Two Control Loops

**S-loop** (system controls perceptions of operator): controlled variables = presence, engagement, stress, energy, audio. Reference = stimmung thresholds. Output = visual brightness, imagination cadence, display density.

**O-loop** (operator controls perceptions of system): controlled variables = visual intensity, voice intrusiveness, notification load, ambient presence, responsiveness. Reference = activity-dependent (deep work wants dim/silent, music wants responsive/expressive).

### 6.2 Stability

| Mode | G_s | G_o | Product | Stable? |
|------|-----|-----|---------|---------|
| Deep work | 0.3 | 0.1 | 0.03 | Strongly |
| Music production | 0.7 | 0.5 | 0.35 | Yes |
| Active conversation | 0.8 | 0.7 | 0.56 | Yes, slower convergence |
| Correction cycle | 1.0 | 1.0 | 1.0 | Marginal, oscillation risk |

The correction cycle case is real and observed. Controlled by frustration_detector (dampens system responsiveness after consecutive corrections) and stimmung hysteresis (3-reading recovery threshold).

### 6.3 TCV Protocols

Five candidate controlled variables with concrete disturbance tests: visual surface intensity, notification load, voice proactivity, display density, system responsiveness. The operator controls different variables in different activity modes — PCT reorganization triggered by flow_state transitions and working_mode switching.

---

## 7. Channel Theory

### 7.1 Classifications

Core classification C_shm: tokens = file byte contents, types = file paths. Time-varying. Peripheral classifications: one per process with domain-specific token/type spaces.

### 7.2 Constraints (8 verified)

C1: stance=critical ⇒ voice_proactivity ≤ 0.3 (modulation_factor)
C2: ir_person_detected=true ⇒ within 8s, presence_probability ≥ 0.7 (Bayesian + enter_ticks)
C3: No flow_state transition within 300s of previous (hysteresis)
C4: Stance recovery requires 3 consecutive nominal readings
C5: Apperception dimension gated 600s after 5 consecutive negatives (rumination breaker)
C6: Imagination cadence: nominal→1x, cautious→1.5x, degraded→2x, critical→4x
C7: Cascade depth ≤ 3, strength × 0.7 per hop
C8: Apperception coherence ≥ 0.15 (shame spiral prevention)

---

## 8. IFC Label Enforcement Design

### 8.1 JSON Schema

```json
{"_consent": {"label": [{"owner": "alice", "readers": ["operator"]}], "provenance": ["contract-alice-2026-01"], "labeled_at": 1711865000.0}}
```

Absent = legacy unlabeled (treat as bottom). Null = explicitly public. Empty label = formal bottom with audit trail. Overhead: 16-350 bytes per file (1.5-7% of typical trace size).

### 8.2 File Classification

| Category | Count | Examples |
|----------|-------|---------|
| Needs direct label | 6 | perception-state, consent-state, self-band, snapshot, ir_presence, watch |
| Inherits label | 6 | buffer.txt, observations, impingements, current.json, stream.jsonl, slots |
| Always public | 9 | stimmung, health, status, uniforms, governance, compositor status |

### 8.3 Five Boundary Gates

1. API responses (`logos/api/routes/`) — gate on SSE flow events
2. LLM prompts (`env_context.py`) — gate on perception injection into system prompt
3. Qdrant upserts (`ingest.py`) — extend existing consent_label extraction
4. Notifications (`shared/notify.py`) — suppress when label is non-bottom
5. Visual surface (`reverie/governance.py`) — extend VetoChain + frame-consent.json sidecar

### 8.4 Migration

Gradual (Option B): readers treat absent `_consent` as bottom. Writers upgraded one service at a time, person-adjacent first. Each step is an independent PR. Verification: `jq '._consent' /dev/shm/hapax-*/state.json`.

---

## 9. Cross-Formalism Summary

| Aspect | Sheaf | Category | Eigenform | PCT | Channel |
|--------|-------|----------|-----------|-----|---------|
| Emergent state | Presheaf on dependency graph | Product of all objects | State vector x | Perception signals | Core classification |
| Consistency | H^1 = 0 (ideal), transient H^1 (acceptable) | Well-defined trace | T(x*) = x* | Error = 0 | Constraints hold |
| Operator role | Reader of all stalks | Negative type in Int(C) | Part of x | O-loop controller | Peripheral classification |
| Stimmung | Restriction map modifier | Natural transformation | Modulates convergence rate | Gain scheduling | Constraints C1, C4, C6 |
| /dev/shm | Core classification stalks | Monoidal product | State vector | Perception signals | Core classification tokens |
| Failure | H^1 generator | Missing morphism | T divergence | Loop gain > 1 | Constraint violation |

**The key insight across all frameworks:** The operator is NOT external. The operator is part of the presheaf (sheaf), a morphism dual to the system (category), part of the state vector (eigenform), one of two coupled controllers (PCT), and a peripheral classification (channel). The formalisms converge on the same structural claim from different mathematical directions.

---

## 10. Computational Implementation Priorities

| Framework | Implementable? | Effort | Value |
|-----------|---------------|--------|-------|
| Sheaf cohomology (H^0, H^1) | Yes — 120×168 SVD, <5ms | 1 week | First computable mesh consistency metric |
| Persistent homology (β₀, β₁) | Yes — GUDHI on 14-node graph | 3 days | Structural health diagnostic |
| ControlSignal extension | Yes — extend existing pattern | 3 days | Complete mesh health coverage |
| IFC embedded labels | Yes — shared/labeled_trace.py | 5 days | Makes consent algebra operational |
| Eigenform convergence monitoring | Partially — need state vector logger | 1 week | Stability diagnostic |
| Coupled PCT analysis | Partially — need gain estimation | 2 weeks | Design criteria for new features |
| Channel theory constraints | Manually verified | 0 (already documented) | Architectural invariants |

---

## References

### Sheaf Theory
- Robinson, M. (2017). "Sheaves are the canonical data structure for sensor integration." Information Fusion, 36.
- Ledent, J. et al. (2025). "A Sheaf-Theoretic Characterization of Tasks in Distributed Systems." arXiv:2503.02556.
- arXiv:2510.00270 (2025). "Asynchronous Nonlinear Sheaf Diffusion for Multi-Agent Coordination."
- Schmid, U. (2025). "Applied Sheaf Theory for Multi-agent AI Systems." arXiv:2504.17700.

### Category Theory
- Joyal, A., Street, R. & Verity, D. (1996). "Traced monoidal categories." Math. Proc. Cambridge Phil. Soc., 119(3).
- Hasegawa, M. (2002). "Feedback, trace and fixed-point semantics." RAIRO, 36(2).
- Spivak, D.I. (2012). "Functorial Data Migration." Information and Computation.

### Eigenforms
- Kauffman, L.H. (2023). "Autopoiesis and Eigenform." Computation, 11(12), 247.
- Kauffman, L.H. (2005). "EigenForm." Kybernetes, 34(1/2).

### PCT
- Powers, W.T. (1973). Behavior: The Control of Perception. Aldine.
- Marken, R.S. & Mansell, W. (2013). "Perceptual Control as a Unifying Concept." Review of General Psychology.

### Channel Theory
- Barwise, J. & Seligman, J. (1997). Information Flow: The Logic of Distributed Systems. Cambridge.
- Aczel, P. (1988). Non-Well-Founded Sets. CSLI.

### IFC
- Rajani, V. et al. (2020). "From Fine- to Coarse-Grained Dynamic IFC and Back." POPL.
- Stefan, D. et al. (2011). "Flexible Dynamic IFC in Haskell." Haskell Symposium.

### Circularity
- Madduri, M.M. & Orsborn, A.L. (2026). "Co-adaptive neural interfaces." Nature Machine Intelligence, 8.
- Kirchhoff, M. & Kiverstein, J. (2019). Extended Consciousness and Predictive Processing. Routledge.
- Letelier, J.C. et al. (2023). "Autonomy as closure through category theory." arXiv:2305.15279.

### Domain Theory
- Abramsky, S. & Jung, A. (1994). "Domain Theory." Handbook of Logic in CS, Vol. 3.
- Shapiro, M. et al. (2011). "Conflict-free Replicated Data Types." SSS.

### Topology
- Edelsbrunner, H. & Harer, J. (2010). Computational Topology. AMS.
- Bailey (2026). "Topology as Language for Emergent Organization." arXiv:2603.25760.
