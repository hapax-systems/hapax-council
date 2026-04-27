# Endogenous Drive Model & Role-Semantic Surfacing

**Date:** 2026-04-27
**Status:** Design (pre-approval)
**Constitutional references:**
- `feedback_no_expert_system_rules` — no hardcoded if-then-else gates
- `project_programmes_enable_grounding` — programmes expand, never replace
- `feedback_grounding_exhaustive` — all perceptual sources participate

## 1. Problem Statement

### 1.1 The Narration Silence Bug

The autonomous narrative system was migrated from a standalone polling loop
(`loop.py` + `gates.py`, 5 expert-system rules) to the `AffordancePipeline`
recruitment model. The migration correctly decommissioned the expert-system
rules but incorrectly assumed narration could be recruited via cosine
similarity to external impingements. It cannot: narration is not a
response to an external event — it is an internally-driven process.

Result: narration never fires because no exploration/sensory impingement
is semantically similar to "compose neutral first-system narration
grounding observed perceptual events into TTS-ready prose."

### 1.2 The Deeper Architectural Gap

The fix is not "make narration's description more similar to impingements."
The fix requires addressing two missing architectural primitives:

1. **Endogenous drives** — internally generated pressures (narration drive,
   self-reflection drive, system-awareness drive) that build over time
   and emit their own impingements when accumulated pressure is sufficient.
   Analogous to the human urge to narrate experience, which arises from
   internal state accumulation, not from external stimuli.

2. **Role-semantic surfacing** — the active programme's role should
   shape which capabilities surface and which are suppressed, not through
   explicit bias dicts but through semantic similarity between the role's
   natural-language description and capability descriptions. Roles are
   attractors in capability space: they pull role-relevant capabilities
   toward surfacing and push role-irrelevant ones down — probabilistically,
   never absolutely.

## 2. Design Principles

### 2.1 No Hard Gates (Constitutional)

Every mechanism must operate as a soft prior — a multiplier, a Bayesian
likelihood term, or a learned weight. Zero-valued multipliers are
architecturally forbidden. Under sufficient pressure (extreme
accumulation, interrupt-grade impingement), any suppressed capability
can still surface. This is analogous to healthy human cognition: home
troubles are appropriately suppressed at work, but abuse breaks through
suppression because the extremity overrides the contextual prior.

### 2.2 Probabilistic Surfacing

Surfacing decisions are computed as posterior probabilities, not boolean
evaluations. The posterior combines:

```
P(surface | context) ∝ P(context | surface) × P(surface)
                         ↑ likelihood terms     ↑ base prior
```

Where:
- **P(surface)** = base drive level (time-accumulated, decaying after emission)
- **P(context | surface)** = product of contextual likelihood terms
  (role similarity, stimmung state, chronicle richness, operator presence,
  recent outcome history)

### 2.3 Semantic, Not Symbolic

Role → capability mapping is computed via embedding similarity, not via
explicit dictionaries. A `LISTENING` role description embeds close to
narration and vocal-chain capabilities in vector space; a `REPAIR` role
embeds close to system-awareness and notification capabilities. The
mapping emerges from the semantic content of the descriptions, not from
manual enumeration.

## 3. Architecture

### 3.1 Endogenous Drive Evaluator

A new module: `shared/endogenous_drive.py`.

**Concept:** An endogenous drive is a latent variable that accumulates
pressure over time and, when it crosses a probabilistic threshold, emits
an impingement onto the bus. The drive is NOT a timer — it is a Bayesian
estimator that computes `P(emit_now)` at each evaluation tick.

```
┌─────────────────────────────────────┐
│         EndogenousDrive             │
│                                     │
│  base_pressure: float (0→1)        │  ← accumulates with time since last emission
│  contextual_modifiers: dict         │  ← role, stimmung, chronicle, operator presence
│  outcome_prior: BetaDist            │  ← learned from Thompson sampling (success/failure)
│  refractory_decay: float            │  ← post-emission cooldown (exponential decay)
│                                     │
│  evaluate(context) → float          │  → posterior probability of surfacing
│  emit() → Impingement | None        │  → if P > threshold, emit endogenous impingement
│  record_outcome(success: bool)      │  → update Thompson prior
└─────────────────────────────────────┘
```

**Accumulation function:**

```python
base_pressure = 1.0 - exp(-elapsed_since_last_emission / tau)
```

Where `tau` is the drive's characteristic time constant (e.g. 120s for
narration → pressure reaches ~0.63 at 120s, ~0.86 at 240s, ~0.95 at
360s). This is NOT a hardcoded cadence — it is a pressure curve that
the contextual modifiers can accelerate or decelerate.

**Contextual modifiers (likelihood terms):**

Each modifier is a float in `(0, ∞)` that multiplies the base pressure:

| Modifier | Source | Effect |
|---|---|---|
| `role_affinity` | Cosine similarity between role description embedding and drive description embedding | High for LISTENING→narration, low for RITUAL→narration |
| `chronicle_richness` | Count + recency of unnarrated chronicle events (RAG retrieval) | More unnarrated events → higher pressure |
| `stimmung_trajectory` | Current stimmung stance + gradient | Rising/falling transitions boost; stable flatline suppresses |
| `operator_presence` | Bayesian presence engine posterior | Absent operator → narration is freer; present → suppressed by conversation |
| `outcome_prior` | Thompson sample from Beta(α, β) conditioned on role | Past success in this context → higher; past failure → lower |

**Posterior computation:**

```python
posterior = base_pressure × role_affinity × chronicle_mod × stimmung_mod × presence_mod × outcome_sample
```

When `posterior > threshold` (drawn from a stochastic threshold to prevent
lock-step periodicity), the drive emits an impingement:

```python
Impingement(
    source="endogenous.narrative_drive",
    type=ImpingementType.CURIOSITY,  # or new ENDOGENOUS type
    strength=posterior,
    content={
        "narrative": f"Internal pressure to narrate has built to {posterior:.2f}. "
                     f"Chronicle has {n_unnarrated} unnarrated events since last emission. "
                     f"Role affinity for narration: {role_affinity:.2f}.",
        "drive": "narration",
        "unnarrated_events": n_unnarrated,
        "role_affinity": role_affinity,
    },
    intent_family=None,  # global recruitment — let the pipeline select
)
```

This impingement then flows through the normal pipeline, where
`narration.autonomous_first_system` recruits naturally because its
description ("Compose neutral first-system narration grounding observed
perceptual events into TTS-ready prose") is semantically similar to the
impingement's narrative about wanting to narrate.

### 3.2 Role-Semantic Surfacing

Enhancement to `ProgrammeRole` and `AffordancePipeline`.

**Concept:** Each `ProgrammeRole` carries a natural-language description
that gets embedded once at pipeline initialization. When the pipeline
scores candidates, the active role's embedding contributes a
`role_affinity` term to the scoring function — capabilities whose
descriptions embed close to the role description get boosted;
capabilities that are distant get attenuated (but never zeroed).

#### 3.2.1 Role Descriptions

Added to `shared/programme.py` as a mapping:

```python
ROLE_DESCRIPTIONS: dict[ProgrammeRole, str] = {
    ProgrammeRole.LISTENING: (
        "Attending to the operator's music selections. Narrating "
        "observations about texture, rhythm, and emotional trajectory. "
        "Voice presence is primary. Background visual processes are "
        "active but subordinate to the listening experience."
    ),
    ProgrammeRole.SHOWCASE: (
        "Presenting and demonstrating research artifacts, code, or "
        "creative works. System awareness and compositional direction "
        "are heightened. Narration focuses on explaining what is being "
        "shown."
    ),
    ProgrammeRole.RITUAL: (
        "Structured boundary-marking ceremony. Visual choreography is "
        "primary. Voice is ceremonial and sparse. Autonomous narration "
        "is rare but not forbidden — a strong perceptual event can "
        "break through."
    ),
    ProgrammeRole.INTERLUDE: (
        "Brief transitional pause between programmes. Low energy. "
        "Visual is ambient and textural. Voice may offer a soft "
        "observation but does not seek attention."
    ),
    ProgrammeRole.WORK_BLOCK: (
        "Operator is engaged in focused work. System monitors for "
        "health and status. Voice is available for conversation but "
        "does not initiate proactively. Narration surfaces only when "
        "the perceptual landscape has shifted significantly."
    ),
    ProgrammeRole.WIND_DOWN: (
        "Preparing to end the stream. Energy decreasing. Visual "
        "simplifying. Voice may offer a closing reflection. New "
        "initiatives are not started."
    ),
    ProgrammeRole.AMBIENT: (
        "No operator present or specific task. The system observes "
        "and narrates freely. Autonomous narration is at its most "
        "natural cadence. Visual expression follows perceptual flow "
        "without compositional direction."
    ),
    # ... remaining roles
}
```

#### 3.2.2 Scoring Integration

In `AffordancePipeline.select()`, after computing `c.combined`:

```python
# Role-semantic boost: cosine similarity between active role
# description embedding and capability description embedding.
# Stored as a per-candidate term, applied as a soft multiplier.
# Range: [0.5, 2.0] — centered at 1.0 (neutral), can halve or
# double the score, but never zero it.
role_sim = cosine_similarity(role_embedding, capability_embedding)
role_multiplier = 0.5 + 1.5 * role_sim  # maps [0,1] → [0.5, 2.0]
c.combined *= role_multiplier
```

This replaces the current `_apply_programme_bias()` for capabilities
that don't have explicit `capability_bias_positive/negative` entries.
Explicit biases still override semantic ones (operator intent is
authoritative over computed similarity).

#### 3.2.3 Role-Conditioned Thompson Sampling

Currently, `ActivationState` tracks a single Beta(α, β) per capability.
This means "narration succeeded" updates the global prior regardless of
whether it succeeded during `LISTENING` (where it should have succeeded)
or during `RITUAL` (where it probably shouldn't have).

Enhancement: partition Thompson priors by role:

```python
class ActivationState(BaseModel):
    # Global prior (backward compatible)
    ts_alpha: float = 2.0
    ts_beta: float = 1.0

    # Role-conditioned priors
    role_priors: dict[str, tuple[float, float]] = {}  # role → (α, β)

    def thompson_sample(self, role: str | None = None) -> float:
        if role and role in self.role_priors:
            alpha, beta = self.role_priors[role]
            return random.betavariate(alpha, beta)
        return random.betavariate(self.ts_alpha, self.ts_beta)

    def record_success(self, role: str | None = None):
        self.ts_alpha += 1
        if role:
            a, b = self.role_priors.get(role, (2.0, 1.0))
            self.role_priors[role] = (a + 1, b)

    def record_failure(self, role: str | None = None):
        self.ts_beta += 1
        if role:
            a, b = self.role_priors.get(role, (2.0, 1.0))
            self.role_priors[role] = (a, b + 1)
```

Over time, the system LEARNS: "narration during LISTENING has a high
success rate (α=47, β=3)" vs "narration during RITUAL has a low success
rate (α=2, β=12)." This is the Bayesian analysis replacing the expert-
system gates — the same information that `gates.py` encoded as
`if programme.role in {RITUAL, WIND_DOWN, INTERLUDE}: deny` is now
learned from outcomes and applied probabilistically.

### 3.3 The Extremity Override

The architecture naturally handles extremity override through the
mathematics:

```python
posterior = base_pressure × role_affinity × ... × outcome_sample
```

A very high `base_pressure` (e.g. 45 minutes of unnarrated rich
chronicle during a ritual) can dominate:

```
base_pressure = 0.99 (45 min with τ=120s)
role_affinity = 0.3 (RITUAL is low for narration)
outcome_sample = 0.15 (ritual narration has poor history)
posterior = 0.99 × 0.3 × 0.15 × ... ≈ 0.045 (below threshold)
```

But with an exceptionally rich chronicle (20 unnarrated events):

```
chronicle_mod = 2.5 (strong upward modifier)
posterior = 0.99 × 0.3 × 0.15 × 2.5 × ... ≈ 0.111 (may cross threshold)
```

The "abuse at work" analog: when internal pressure is extreme enough,
it breaks through role suppression without any rule change. The math
does it.

### 3.4 How the Drive Emitter Runs

The drive evaluator needs a tick loop. Three options:

**Option A (preferred): Attach to the exploration tracker infrastructure.**
Add a `NarrativeDriveTracker` that runs alongside the existing 13
`ExplorationTrackerBundle` components. It feeds on chronicle state,
stimmung, and operator presence — all of which are already published
to SHM. When the posterior crosses threshold, it emits an impingement
via `_IMPINGEMENTS_FILE.open("a")`, identical to how exploration
impingements are emitted today.

This option requires no new loops, no new systemd services, and no new
SHM files. It rides the existing exploration infrastructure.

**Option B: Piggyback on the impingement consumer loop.**
Add a time-check inside `impingement_consumer_loop()` that evaluates
drives on a cadence (e.g. every 10s, similar to the old loop's tick).
Pro: co-located with the dispatch code. Con: conflates consumption with
production.

**Option C: Standalone loop in run_inner.py.**
A minimal async loop that evaluates drives and emits impingements.
Pro: clean separation. Con: another supervised task.

## 4. Module Map

```
shared/
  endogenous_drive.py           [NEW]  — EndogenousDrive class, evaluate(), emit()
  programme.py                  [MOD]  — Add ROLE_DESCRIPTIONS dict
  affordance_pipeline.py        [MOD]  — Role-semantic scoring in select()
                                       — Role-conditioned Thompson sampling
                                       — Role embedding cache

agents/hapax_daimonion/
  run_loops_aux.py              [MOD]  — Dispatch narration.autonomous_first_system
                                         from endogenous drive impingements
  autonomous_narrative/
    __init__.py                 [MOD]  — Document new architecture
    compose.py                  [KEEP] — Unchanged
    emit.py                     [KEEP] — Unchanged
    state_readers.py            [KEEP] — Unchanged (provides context for compose)

shared/affordance_registry.py   [KEEP] — narration.autonomous_first_system stays
                                         registered as an affordance
```

## 5. Data Flow

```
                                    ┌──────────────────────┐
                                    │   NarrativeDrive     │
                                    │   Evaluator          │
                                    │                      │
           chronicle ──────────────►│  base_pressure       │
           stimmung ───────────────►│  × role_affinity     │
           operator presence ──────►│  × chronicle_mod     │
           programme role ─────────►│  × stimmung_mod      │
           outcome history ────────►│  × thompson_sample   │
                                    │                      │
                                    │  posterior > thresh?  │
                                    │      │                │
                                    └──────┼────────────────┘
                                           │ yes
                                           ▼
                              ┌─────────────────────────┐
                              │ Impingement             │
                              │ source: endogenous.     │
                              │   narrative_drive       │
                              │ type: CURIOSITY         │
                              │ content.narrative:      │
                              │   "Internal pressure    │
                              │    to narrate..."       │
                              └─────────┬───────────────┘
                                        │
                                        ▼
                              ┌─────────────────────────┐
                              │ AffordancePipeline      │
                              │   .select(imp)          │
                              │                         │
                              │ Qdrant cosine sim:      │
                              │ narration.autonomous_   │
                              │ first_system scores     │
                              │ HIGH (0.7+) because     │
                              │ imp narrative ≈ cap     │
                              │ description             │
                              │                         │
                              │ + role_affinity boost   │
                              │ + Thompson sample       │
                              │ + programme bias        │
                              └─────────┬───────────────┘
                                        │
                                        ▼
                              ┌─────────────────────────┐
                              │ impingement_consumer    │
                              │   _dispatch_autonomous_ │
                              │   narration()           │
                              │                         │
                              │ compose → emit → TTS    │
                              │ → pipeline.record_      │
                              │   outcome(role=...)     │
                              │ → pipeline.add_         │
                              │   inhibition()          │
                              └─────────────────────────┘
```

## 6. Generalisation

The endogenous drive model is not narration-specific. Future drives:

| Drive | τ (time constant) | Key modifiers |
|---|---|---|
| `narration` | 120s | chronicle richness, role affinity, operator absence |
| `self_reflection` | 600s | apperception cascade density, stimmung volatility |
| `system_awareness` | 300s | health metric degradation, resource pressure |
| `exploration` | 180s | boredom index, habituation level, novelty deficit |

Each drive is an `EndogenousDrive` instance with its own `tau`,
contextual modifiers, and Thompson prior. All emit to the same
impingement bus and are recruited by the same pipeline.

## 7. Verification Plan

### 7.1 Unit Tests
- `test_endogenous_drive.py`: pressure accumulation, posterior computation,
  emission threshold, refractory cooldown, role conditioning
- `test_role_semantic_scoring.py`: role description embeddings, affinity
  computation, multiplier range [0.5, 2.0], no-zero invariant
- `test_role_conditioned_thompson.py`: success/failure recording per role,
  sample distribution conditioning

### 7.2 Integration Tests
- Start daimonion with AMBIENT role, verify narration fires within ~3min
- Switch to RITUAL role, verify narration frequency drops (not zero)
- Accumulate 20 chronicle events during RITUAL, verify narration breaks through
- Record 10 failures during RITUAL, verify Thompson prior shifts appropriately

### 7.3 Production Telemetry
- `recruitment-log.jsonl`: look for `endogenous.narrative_drive` source impingements
- `dispatch-trace.jsonl`: verify `narration.autonomous_first_system` appears as winner
- Prometheus: `hapax_endogenous_drive_posterior` gauge per drive per role

## 8. Open Questions

1. **Should `ImpingementType` gain an `ENDOGENOUS` variant?** Currently the
   closest fit is `CURIOSITY` ("system-internal: something novel found").
   A dedicated type improves traceability but expands the enum.

2. **Where does the tick loop live?** Option A (exploration tracker
   infrastructure) is cleanest but couples the drive evaluator to the
   exploration module. Option C (standalone) is most independent.

3. **How many role-conditioned Thompson buckets before memory explodes?**
   12 roles × N capabilities = 12N extra (α,β) pairs. With ~200
   capabilities, that's 2400 pairs — 19KB. Negligible.

4. **Should role descriptions be LLM-authored (by Hapax) or hand-written?**
   Hand-written ensures precision but violates `feedback_hapax_authors_programmes`.
   LLM-authored risks semantic drift. Suggestion: operator seeds initial
   descriptions, Hapax refines them over time via outcome-weighted editing.

5. **Interaction with existing `ProgrammeConstraintEnvelope.capability_bias_*`:**
   Should role-semantic scoring REPLACE explicit biases, or should explicit
   biases OVERRIDE semantic scores when present? Proposed: explicit overrides
   semantic (operator intent > computed similarity), semantic fills gaps
   where no explicit bias is set.
