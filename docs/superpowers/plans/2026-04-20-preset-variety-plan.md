---
date: 2026-04-20
author: alpha (Claude Opus 4.7, 1M context, cascade worktree)
audience: delta (execution dispatcher) + operator
register: scientific, neutral
status: dispatchable plan — multi-phase, mixed parallel/serial
related:
  - docs/research/2026-04-19-preset-variety-design.md (research source, task #166)
  - docs/research/2026-04-19-content-programming-layer-design.md (programme palette dependency)
  - docs/research/2026-04-19-expert-system-blinding-audit.md (A6/A7 retirement context)
  - docs/superpowers/plans/2026-04-19-homage-completion-plan.md §B6 (un-shipped HARDM → FX-bias coupling)
  - shared/affordance_pipeline.py (scoring formula)
  - shared/affordance.py (ActivationState, Thompson)
  - agents/studio_compositor/preset_family_selector.py (FAMILY_PRESETS)
  - agents/studio_compositor/random_mode.py (recent-recruitment read, A6 fallback)
branch: hotfix/fallback-layout-assignment
operator-directive-load-bearing: |
  "preset variety and preset chain variety still very repetitive and samey"
  (2026-04-19). Load-bearing: variety is a SCORING + PROGRAMME problem
  (research §4), not a rotation-rule problem. Retired gates (F1/F2) must
  NOT be resurrected. No anti-repeat filter. No hardcoded rotation rule.
---

# Preset + Chain Variety — Completion Plan (post-live iteration, task #166)

## §0. Scope, intent, and what this plan IS

Task #166 converts the research-doc findings in
`docs/research/2026-04-19-preset-variety-design.md` into dispatchable
phases on `hotfix/fallback-layout-assignment`. The research establishes
that the preset + chain "same-y" complaint is NOT a missing-rotation
problem — it is a **scoring problem** (the affordance pipeline does not
price in recency or perceptual distance) compounded by a **programme
problem** (the recruitable surface is narrower than the preset corpus
and dominated by a single family, `calm-textural`). The research
explicitly rejects reintroducing the variety gates retired tonight
(F1/F2); the fix is to enrich the signal landscape the pipeline scores
over, not to filter its outputs.

Two load-bearing memories constrain the plan shape:

1. `feedback_no_expert_system_rules` — NO hardcoded rotation rule, NO
   anti-repeat gate, NO expert-system filter at any tier of this work.
   Behavior emerges from impingement → recruitment → role → persona.
2. `project_programmes_enable_grounding` — programme palette ranges are
   **soft priors** that tilt the scoring field, not hard gates that
   remove capabilities from recruitment.

This plan is NOT code. Each phase below is a discrete execution-subagent
dispatch with bounded scope, a success criterion, and a rollback path.
Phases 1 and 9 bracket the work with pre- and post-deploy telemetry so
the operator can read the intervention effect quantitatively rather than
subjectively. Phase 2 is the highest-value quickest fix and should ship
before any scoring-layer change — the research §1 finding that the
director narrative is locked on `calm-textural` for 4+ hours is upstream
of the affordance pipeline, and no scoring tweak compounds while that
monoculture holds.

Operator directive `feedback_exhaust_research_before_solutioning` is
honored by the §1-telemetry-first bracket: no scoring change lands
without a baseline to compare against.

---

## §1. Success definition — what "done" measures like

The acceptance test is quantitative, derived from pre- and post-deploy
telemetry over 60-minute windows captured by Phase 1 / Phase 9.
Qualitative read is secondary (the operator's "same-y" complaint is
itself an entropy assessment).

### 1.1 Preset-family distribution Shannon entropy

- **Pre-deploy (Phase 1 baseline):** compute Shannon entropy `H = -Σ
  p_i × log2(p_i)` over preset.bias family applications in the last 60
  min. Research §1 implies this is near zero today (single family
  dominates 12+ consecutive samples).
- **Post-deploy acceptance:** `H ≥ 1.5` over a 60-min window spanning a
  normal livestream session. Maximum with 5 uniformly-applied families
  is `log2(5) ≈ 2.32`; a floor of 1.5 corresponds to an effective
  distribution covering ≥3 families with non-trivial weight (no single
  family above ~50% share).

### 1.2 Slot-level colorgrade:halftone ratio

- **Pre-deploy baseline:** research §1 reports 47:1 colorgrade over
  halftone activations over 12h. Phase 1 re-measures on a 60-min window
  to get a comparable unit.
- **Post-deploy acceptance:** ratio ≤10:1 over the same 60-min window.
  This measures whether the "personality" nodes (halftone, pixsort,
  ascii, glitch_block) lift out of the 1–4% floor.

### 1.3 Recent-10 perceptual-distance distribution

- **Pre-deploy baseline:** for each preset activation, compute cosine
  distance against the most-similar of the previous 10 activations'
  capability embeddings; take the mean over a 60-min window. Expected
  to be low (research §1 implies ~0.1–0.2 mean).
- **Post-deploy acceptance:** mean recent-10 min-distance `≥ 0.4`.
  Equivalent to "the typical new preset has at least one dimension of
  meaningful perceptual difference from the last 10 applied."

### 1.4 Visible narrative diversity

- **Post-deploy subjective:** operator 60-min read of `/dev/video42`
  reports at least 3 of the 5 families firing ("the chain visits
  audio-reactive, glitch-dense, and warm-minimal registers, not just
  calm-textural"). Operator mark on the Phase 9 checklist gates the
  "done" declaration.

### 1.5 No gate regressions

- `feedback_no_expert_system_rules` compliance verified by `rg` at
  Phase 9: no new `if <family> == X and cooldown` or anti-repeat filter
  patterns in the merged phase set. Recency signal must be a SCORING
  INPUT on `SelectionCandidate`, not a branch in a filter path.

If Phase 9 re-measurement shows entropy has at least doubled AND
colorgrade:halftone ≤10:1 AND recent-10 mean ≥0.4, declare win. If any
fail, the plan is NOT done — triage to the relevant phase and iterate.

---

## §2. Phase list

Phases are grouped 1 through 9. Phase 1 and Phase 9 bracket the
intervention; Phase 2 is prompt-level and is the cheapest biggest-signal
move; Phases 3–7 are architectural scoring-layer work; Phase 8 is the
terminal programme layer dependency on task #164.

Each phase has: scope (file paths bounded), blocking dependencies,
parallel-safe siblings, success criteria (measurable where possible),
test strategy, LOC range, commit-message template.

**All phases:** commit directly to `hotfix/fallback-layout-assignment`.
Do NOT switch branches. Do NOT use `isolation: "worktree"` (operator-
mandated subagent git safety per workspace CLAUDE.md). Each commit is
self-contained and ends with the standard
`Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
trailer.

---

### Phase 1: Telemetry baseline (pre-intervention measurement)

**Scope:**
- New file: `scripts/measure-preset-variety-baseline.py` — reads the
  last 60 min of `preset.bias` recruitment records from
  `~/hapax-state/stream-experiment/director-intent.jsonl` and
  `~/hapax-state/affordance/recruitment-log.jsonl`, computes:
  (a) Shannon entropy over family distribution, (b) per-family
  histogram, (c) per-preset activation count, (d) colorgrade:halftone
  ratio over `activate_plan` log lines, (e) recent-10 cosine-min-distance
  mean if embeddings are available (skip with NA if not).
- New file: `docs/research/preset-variety-baseline-2026-04-20.json` —
  baseline JSON artifact committed to the repo so Phase 9 can diff
  against it deterministically.
- New file: `agents/studio_compositor/director_observability.py`
  extension — a `preset_family_histogram` helper that can be queried
  from the metrics endpoint.

**Description:** This phase establishes the quantitative ground against
which every subsequent phase measures. Per `feedback_verify_before_claiming_done`
and `feedback_exhaust_research_before_solutioning`, no scoring change
lands without a baseline. The script runs over already-existing logs so
it can execute immediately without blocking on system changes.

**Blocking dependencies:** None. First phase; runs on current system
state.

**Parallel-safe siblings:** None (Phase 1 completes first, alone, so
every downstream phase can cite it).

**Success criteria:**
- Script runs in <30s against a 60-min log window.
- Baseline JSON checked in with entropy, histogram, ratio, mean-distance
  fields populated.
- Numbers triangulate against research §1: Shannon entropy near 0,
  colorgrade:halftone ≥30:1, recent-10 mean ≤0.25.

**Test strategy:** Unit test on a synthesized log fixture (small JSONL
with 50 deterministic records); assert entropy computed correctly to 4
decimal places. No integration test — the script's correctness is
verified by the fixture test and by its output matching research §1.

**Estimated LOC:** 200 script + 50 tests. Size: S.

**Commit message template:**

```
feat(preset-variety): Phase 1 — telemetry baseline script + JSON artifact

measure-preset-variety-baseline.py computes Shannon entropy, per-family
histogram, colorgrade:halftone ratio, recent-10 cosine-min-distance mean
from existing director-intent.jsonl + recruitment-log.jsonl. Baseline
JSON committed to docs/research/preset-variety-baseline-2026-04-20.json
so Phase 9 can diff deterministically.

Phase 1 of preset-variety-plan. Pre-intervention ground truth for
scoring-layer phases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Phase 2: Diagnose + unblock narrative monoculture on `calm-textural`

**Scope:**
- `agents/studio_compositor/director_loop.py` — audit the director
  prompt string(s) used at the `_call_activity_llm` site. Search for
  any literal mention of `calm-textural` as a default, preferred
  family, or example. Remove or neutralize any family-name bias in the
  prompt template.
- `agents/studio_compositor/preset_family_selector.py` — audit
  `FAMILY_PRESETS` membership counts and verify all 5 families are
  represented in the affordance catalog (cross-ref with Qdrant
  `affordances` collection keys). Fix any family with <3 presets
  registered as affordances.
- `shared/affordance_pipeline.py` — audit the grounding-signal whitelist
  for the `preset.bias` capability family (gate audit A6 per
  `docs/research/2026-04-19-expert-system-blinding-audit.md`). Surface
  any implicit default that routes to `neutral-ambient` or
  `calm-textural` when no signal fires.
- Instrumentation: add a one-line log at `_call_activity_llm` return:
  `family_selected=<name> prompt_hash=<sha256[:8]>` so further prompt
  drift can be diagnosed without grepping log archives.

**Description:** Per research §1, the director's NARRATIVE itself is
locked on `calm-textural` — 12+ consecutive samples over 4 hours, zero
alternatives. This is upstream of the affordance pipeline. Before any
scoring-layer change can compound, the narrative has to be freed.

Research §8 question 8 flags this as "possibly the director's prompt is
templating in the recently-recruited family name and creating a
self-reinforcing loop." The dominant hypothesis is that the prompt has
an example / default / preferred-family phrasing that biases the LLM
output — a "mild expert-system-rule smuggle" per the global directive.
If found, the prompt line is to be neutralized (family-name list
presented in randomized order, no "prefer" / "default" language, no
family-specific examples).

If the prompt is clean and the monoculture persists, the second
hypothesis is catalog-side: some families may be under-populated in
Qdrant relative to `FAMILY_PRESETS`, so cosine retrieval consistently
returns the same top-1.

This phase is PROMPT + CATALOG work, not scoring work. Per the research
§4 thesis, it is also the cheapest phase with the largest expected
signal. It MUST land before Phases 3–7.

**Blocking dependencies:** Phase 1 (need baseline to measure against).

**Parallel-safe siblings:** None. Phase 2 is the narrative-unblock
critical path; parallelism resumes at Phase 3.

**Success criteria:**
- If prompt bias is found: a diff that removes the biasing line, with a
  brief comment explaining the removal. Unit test pins the prompt has
  no per-family preference phrasing.
- If catalog sparsity is found: Qdrant `affordances` collection query
  returns ≥3 members for every `preset.bias.<family>` entry.
- Post-deploy verification: in a 20-min window after Phase 2 ships, the
  narrative log shows ≥2 distinct family tokens (up from the current 1).
- `rg 'calm-textural|neutral-ambient' agents/studio_compositor/director_loop.py`
  returns 0 hardcoded defaults; any remaining matches are in data, not
  control flow.

**Test strategy:** Static grep assertion in a CI test; narrative-family
diversity in a 20-min manual observation window. If a prompt template
is used, pin its SHA256 in the test so silent regressions are caught.

**Estimated LOC:** 100 diff + 50 tests. Size: S.

**Commit message template:**

```
fix(preset-variety): Phase 2 — unblock narrative monoculture on calm-textural

Research §1 documented the director narrative locked on calm-textural
for 4+ hours (12+ consecutive samples). Root cause: <prompt default |
catalog sparsity | whitelist smuggle — fill in from audit>. Fix:
<describe>. Pin regression test on prompt SHA256 / Qdrant catalog
membership count.

Phase 2 of preset-variety-plan. Cheapest-biggest-signal move;
prerequisite for scoring-layer Phases 3–7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Phase 3: `recency_distance` as scoring input

**Scope:**
- `shared/affordance.py` — add `_RecencyTracker` Pydantic model. Rolling
  window of N=10 most-recently-applied capability embeddings +
  capability names. Methods: `record_apply(name, embedding)`,
  `distance(embedding) -> float` returning `1 - max_cosine_sim` over the
  window.
- `shared/affordance_pipeline.py` — add `recency_distance: float = 0.0`
  to `SelectionCandidate`; compute per-candidate at scoring time; fold
  into the combined score:
  `combined = (W_SIMILARITY × sim + W_BASE_LEVEL × base +
              W_CONTEXT × ctx + W_THOMPSON × ts +
              W_RECENCY × recency_distance) × cost_weight`
  with renormalized weights `0.45 / 0.18 / 0.09 / 0.18 / 0.10`.
- Feature flag: `HAPAX_AFFORDANCE_RECENCY_WEIGHT` (default 0.10). 0.0
  disables the term; any positive value activates it. Allows operator
  runtime adjustment without redeploy.
- Tests: `tests/shared/test_affordance_recency.py` — unit tests on
  `_RecencyTracker` (window-size bound, distance monotonicity, empty
  window returns 1.0 max novelty), integration test that a
  recently-applied candidate gets a lower final score than an identical
  non-recent candidate.

**Description:** The core scoring-layer move from research §5.1.
Recency-distance is a SCORING INPUT, not a filter — highly-grounded
recruitment can still apply the same family twice in a row if the
signal strongly justifies it. The 0.10 weight is small enough that
strong narrative still wins, but large enough to break ties in favor of
perceptually-distant options.

Prior art: curiosity-driven exploration (Pathak et al. 2017), RND
(Burda et al. 2018), Spotify Discover / Netflix diversity rerankers.

**Blocking dependencies:** Phase 1 (baseline), Phase 2 (narrative
un-stuck, otherwise scoring change has no room to compound).

**Parallel-safe siblings:** Phase 4 (Thompson decay), Phase 5
(affordance catalog audit), Phase 6 (perceptual impingement) — all
touch different code paths.

**Success criteria:**
- Unit + integration tests pass.
- Post-deploy: Phase 9 re-measurement shows Shannon entropy ≥1.0 (2x
  baseline), even without Phases 4–8. Recency-distance term alone
  should move the needle meaningfully.
- `rg 'if.*recent.*return' shared/affordance_pipeline.py` returns 0 —
  no filter/gate pattern; recency is strictly a score contribution.

**Test strategy:** Unit tests on `_RecencyTracker`; integration test
mocking 10-capability recruitment stream and asserting the 11th's score
is lower when it matches the 10th's embedding. Property-based
Hypothesis test: ordering stable under permutation of non-recent
candidates.

**Estimated LOC:** 250 module changes + 200 tests. Size: M.

**Commit message template:**

```
feat(preset-variety): Phase 3 — recency_distance scoring input

Add _RecencyTracker rolling window (N=10) over capability embeddings +
recency_distance field on SelectionCandidate. Fold into the affordance
pipeline score formula at 0.10 weight (feature-flagged via
HAPAX_AFFORDANCE_RECENCY_WEIGHT). Renormalized weights:
0.45/0.18/0.09/0.18/0.10. Recency is a SCORING INPUT, not a filter —
strong grounding signals still win.

Phase 3 of preset-variety-plan. Architectural; no expert-system rule
smuggled.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Phase 4: Thompson posterior decay on non-recruitment

**Scope:**
- `shared/affordance.py::ActivationState` — add `decay_unused(gamma_unused=0.999)`
  method pulling `ts_alpha` / `ts_beta` toward Beta(2, 1) prior:
  ```
  target_alpha, target_beta = 2.0, 1.0
  ts_alpha = ts_alpha * gamma_unused + target_alpha * (1 - gamma_unused)
  ts_beta  = ts_beta  * gamma_unused + target_beta  * (1 - gamma_unused)
  ```
- `shared/affordance_pipeline.py` — on each `select()` call, iterate
  over non-recruited capabilities in the candidate set and invoke
  `decay_unused`.
- Feature flag: `HAPAX_AFFORDANCE_THOMPSON_DECAY` (default 0.999). 1.0
  disables (no decay); 0.99 aggressive; 0.95 restless.
- Regression test: `tests/shared/test_affordance_thompson_decay.py` —
  pin that after 700 non-recruitment ticks at gamma=0.999, posterior
  has drifted to within 10% of Beta(2,1); at 70 ticks under gamma=0.99,
  similar drift.

**Description:** Research §5.2 architectural move. Currently
`ActivationState` decays only on `record_success` / `record_failure` —
there is no time-based decay for non-recruited capabilities. After a
long monopoly by capability A, capability B's `thompson_sample()` stays
frozen; this phase makes B slowly recover toward the Beta(2,1) mean
(~0.67) so B can eventually win on Thompson variance even when
base-level is depressed.

Decay-rate tradeoff: 0.999 ≈ 700-tick half-life (gentle, hours),
0.99 ≈ 70-tick (~1 min at 1 Hz), 0.95 ≈ 14-tick (restless). Start at
0.999; Phase 9 re-measurement tells us whether to tighten.

**Blocking dependencies:** Phase 1 (baseline).

**Parallel-safe siblings:** Phase 3, Phase 5, Phase 6.

**Success criteria:**
- Regression test pins the math.
- Post-deploy: idle capabilities' `ts_alpha` / `ts_beta` telemetry
  (exposed at `/api/affordances/state/summary` per Phase 1) shows drift
  over 24h toward Beta(2,1). Capability variance in recruitment
  increases over 24h.
- `rg 'if.*not_recruited' shared/affordance.py` returns 0 — decay is
  a state update, not a branch.

**Test strategy:** Unit test with time-mocked tick loop; assert
posterior drift to within tolerance at fixed gamma. Property-based
Hypothesis test: decay is monotone toward the prior regardless of
starting state.

**Estimated LOC:** 80 module + 120 tests. Size: S.

**Commit message template:**

```
feat(preset-variety): Phase 4 — Thompson posterior decay on non-recruitment

ActivationState.decay_unused pulls ts_alpha / ts_beta toward Beta(2,1)
at gamma_unused=0.999 per non-recruitment tick. Pipeline applies it on
every select() call to non-recruited candidates. Feature-flagged via
HAPAX_AFFORDANCE_THOMPSON_DECAY. Regression test pins 700-tick
half-life.

Phase 4 of preset-variety-plan. Lets dormant capabilities recover
Thompson variance after long monopolies without adding a filter.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Phase 5: Affordance-catalog closure audit

**Scope:**
- New script: `scripts/audit-preset-affordances.py` — enumerates every
  `preset.bias.<family>` capability in Qdrant `affordances` collection,
  cross-checks against `FAMILY_PRESETS` in
  `preset_family_selector.py` and against `presets/*.json` on disk,
  flags (a) families with <3 registered affordances, (b) presets
  registered but failing to load (e.g., `thermal` fragment-compile
  failure per research §1), (c) affordances in Qdrant with no disk
  preset, (d) disk presets with no affordance.
- Audit report committed: `docs/research/preset-affordance-audit-2026-04-20.md`
  capturing the run output.
- If gaps surface: remediation commits (one per category) registering
  missing affordances in Qdrant using the Gibson-verb description
  pattern from `shared/compositional_affordances.py`.

**Description:** Research §5.3. Even if scoring prices in recency,
pricing operates over whatever candidate set retrieval produces. If
families are narrowly represented in Qdrant, recency buys you variation
within a narrow pool. Research §1 initially reported no orphans but
flagged the `ward.highlight` parallel as cautionary; Phase 5 makes the
check explicit and remediates any findings.

This phase also surfaces the `thermal` shader compile failure
(research §1 noted 30+ fails in 12h), which silently shrinks
`warm-minimal` by one preset — a real variety leak.

**Blocking dependencies:** Phase 1 (baseline context).

**Parallel-safe siblings:** Phase 3, Phase 4, Phase 6.

**Success criteria:**
- Audit script exits <30s.
- Audit report committed with findings enumerated.
- Every `preset.bias.<family>` entry has ≥3 registered members
  post-remediation.
- Load-failure presets are either fixed (shader recompiles clean) or
  deregistered from their family map with a comment explaining why.

**Test strategy:** Script fixture-tested on a toy Qdrant stand-in; live
output captured in the audit report.

**Estimated LOC:** 200 script + 100 tests + remediation (variable, 0–300
depending on gaps). Size: S–M.

**Commit message template:**

```
chore(preset-variety): Phase 5 — affordance catalog closure audit + fixes

audit-preset-affordances.py enumerates preset.bias.<family> entries in
Qdrant vs FAMILY_PRESETS vs presets/*.json. Findings: <fill in>. Fixes:
<fill in — registered N missing affordances, repaired thermal shader
recompile, etc.>. Audit report at
docs/research/preset-affordance-audit-2026-04-20.md.

Phase 5 of preset-variety-plan. Ensures scoring variety has a wide
pool to operate over.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Phase 6: Perceptual distance as impingement

**Scope:**
- `shared/affordance_pipeline.py` — when the recency tracker (Phase 3)
  observes last-N embeddings clustering (mean pairwise cosine similarity
  > 0.85), emit an impingement:
  ```python
  Impingement(
    source="affordance_pipeline.recency",
    intent_family="content.too-similar-recently",
    content={"metric": "preset_recency_cluster",
             "cluster_similarity": float,
             "cluster_size": int},
    narrative=("The visual chain has stayed in a similar register for "
               f"the last {cluster_size} applies (cluster similarity "
               f"{cluster_similarity:.2f}). Reach for something "
               "perceptually distant if the moment allows.")
  )
  ```
- `shared/compositional_affordances.py` — register a new
  `novelty.shift` capability with a Gibson-verb description
  ("widen the perceptual register; reach for a perceptually-distant
  preset family from what has recently fired"). This is the recruitment
  target for the impingement.
- `agents/studio_compositor/compositional_consumer.py` — consumer path
  for `content.too-similar-recently` routes through the normal
  impingement dispatch (no special-casing).
- Tests: `tests/shared/test_perceptual_distance_impingement.py` —
  impingement fires within 1 tick when last-10 cluster ≥0.85; does not
  fire when cluster <0.85; `novelty.shift` capability becomes a
  recruitment candidate with the right embedding.

**Description:** Research §5.4. Anti-repetition as an IMPINGEMENT, not
as a gate. The pipeline decides whether to act — if the operator is
mid-narration and the moment demands continuity, narrative similarity
still outweighs the novelty impingement. The impingement is a fact
about the perceptual surface ("the last N applies have clustered"),
not a rule about what to do next. This satisfies
`feedback_no_expert_system_rules` because no filter, no gate, no
hardcoded rotation.

**Blocking dependencies:** Phase 3 (need `_RecencyTracker` infrastructure).

**Parallel-safe siblings:** Phase 4, Phase 5.

**Success criteria:**
- Unit + integration tests pass.
- Live: in a 60-min window, `content.too-similar-recently` impingements
  appear in `director-intent.jsonl` with frequency correlated to
  subjective "same-y" stretches.
- `novelty.shift` capability recruitment visible in recruitment log.
- `rg 'if.*cluster.*return|if.*similar.*skip' shared/affordance_pipeline.py`
  returns 0 — no filter/gate pattern.

**Test strategy:** Unit test on impingement emission math; integration
test on consumer dispatch; regression test that the impingement
doesn't force a shift (the pipeline can still pick a recent family if
signal strong).

**Estimated LOC:** 200 module + 150 tests. Size: M.

**Commit message template:**

```
feat(preset-variety): Phase 6 — perceptual distance as impingement

AffordancePipeline emits content.too-similar-recently impingement when
last-10 cluster cosine similarity ≥0.85. Registered novelty.shift
capability becomes a recruitment target. Impingement is a perceptual
FACT, not a rule — pipeline decides whether to act on it.

Phase 6 of preset-variety-plan. Anti-repetition as signal, not gate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Phase 7: Chain-level transition variety

**Scope:**
- `shared/compositional_affordances.py` — register 5 transition
  affordances under a new `transition.*` family:
  - `transition.fade.smooth` — the existing 12-step brightness fade
  - `transition.cut.hard` — single-frame swap, no crossfade
  - `transition.netsplit.burst` — fast multi-ward clear + re-fill
  - `transition.ticker.scroll` — slide-in from edge
  - `transition.dither.noise` — dithered noise mask transition
- New primitives module: `agents/studio_compositor/transition_primitives.py`
  — 4 new primitive functions (the 5th is the existing fade).
- `agents/studio_compositor/random_mode.py` — update transition
  selection to go through the affordance pipeline: recruit BOTH a
  preset (or family) AND a transition per chain change.
- Tests: `tests/studio_compositor/test_transition_affordances.py` —
  unit test per primitive (renders deterministic output),
  integration test that transition entropy over 1h ≥0.6.

**Description:** Research §5.5. Currently every preset change uses
the same fade-to-black transition — even if preset variety is solved,
transitions still feel identical. Registering transitions as
affordances doubles the chain-level vocabulary. The existing fade
becomes the implementation behind `transition.fade.smooth`; the other
4 need new primitive functions.

**Blocking dependencies:** Phase 3, Phase 5 (catalog audit — transitions
are registered alongside).

**Parallel-safe siblings:** Phase 6.

**Success criteria:**
- 5 transitions each visually verifiable on `/dev/video42` via a short
  demo script (`scripts/demo-transitions.py` — invokes each in
  sequence).
- Transition Shannon entropy over 1h ≥0.6.
- `rg 'transition.*if.*rotate' agents/studio_compositor/random_mode.py`
  returns 0 — no hardcoded rotation of transitions.

**Test strategy:** Per-primitive golden image test (deterministic
seeds, tolerance ±4 per channel); integration test on entropy over a
simulated 1h recruitment stream.

**Estimated LOC:** 400 module + 200 tests. Size: M–L.

**Commit message template:**

```
feat(preset-variety): Phase 7 — chain-level transition affordances

Register 5 transition capabilities (fade.smooth, cut.hard,
netsplit.burst, ticker.scroll, dither.noise) as affordance entries.
random_mode recruits BOTH preset AND transition per chain change.
Doubles chain-level vocabulary.

Phase 7 of preset-variety-plan. Transition recruitment through the
same pipeline — no separate rotation rule.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Phase 8: Programme-owned palette ranges (gated on task #164)

**Scope:**
- `shared/programmes/` — add `ProgrammeAesthetics` Pydantic model per
  research §5.6:
  ```python
  class ProgrammeAesthetics(BaseModel):
    palette_bias: dict[str, float]    # family_name -> weight 0..1
    transition_bias: dict[str, float] # transition_name -> weight 0..1
    feedback_intensity_range: tuple[float, float]
    motion_register: Literal["still", "drift", "pulse", "burst"]
  ```
- `shared/affordance_pipeline.py::_compute_context_boost` — fold
  `palette_bias` into the context boost for preset candidates when a
  programme is active.
- Example programme definitions: `vinyl-listening` (calm-textural 0.4,
  warm-minimal 0.4, audio-reactive 0.2, glitch-dense 0.0, smooth
  transitions, low feedback); `beat-making` (audio-reactive 0.5,
  glitch-dense 0.4, burst transitions, high feedback).
- Tests: `tests/shared/test_programme_aesthetics.py` — unit test on
  context-boost math; integration test on a 4h multi-programme window
  showing entropy ≥0.8 when programme flips occur.

**Description:** Research §5.6. Programme palette ranges are SOFT
PRIORS per `project_programmes_enable_grounding` — they bias the
scoring, they do not remove capabilities from recruitment. If
impingement strongly demands a glitch-dense move during a
vinyl-listening programme, recruitment can still win — the bias just
tilts the field.

**Blocking dependencies:** Task #164 content-programming layer
(Phase 1–3 of that plan must land first so programmes exist to declare
aesthetics). Within this plan, also gated on Phase 3 (context_boost
infrastructure).

**Parallel-safe siblings:** None — terminal phase.

**Success criteria:**
- ≥2 programmes declare `ProgrammeAesthetics`.
- Cross-programme palette flips visible in a 4h capture.
- 4h multi-programme entropy ≥0.8 (above the 1.5 Phase 9 floor because
  cross-programme rotation compounds within-programme variety).
- `rg 'if.*programme.*and.*family' shared/affordance_pipeline.py`
  returns 0 — programme is a bias, not a filter.

**Test strategy:** Unit test on context-boost math; integration test
using a fake 4h programme-flip timeline.

**Estimated LOC:** 300 module + 200 tests. Size: M.

**Commit message template:**

```
feat(preset-variety): Phase 8 — programme-owned palette ranges

ProgrammeAesthetics schema declares palette_bias / transition_bias /
feedback_intensity_range / motion_register. Pipeline folds palette_bias
into _compute_context_boost — soft prior per
project_programmes_enable_grounding, never a hard gate. Example
programmes: vinyl-listening, beat-making.

Phase 8 of preset-variety-plan. Gated on task #164 content-programming
layer Phases 1–3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Phase 9: Post-deploy re-measurement + win declaration

**Scope:**
- Run `scripts/measure-preset-variety-baseline.py` on the post-deploy
  60-min window.
- New file: `docs/research/preset-variety-postdeploy-YYYY-MM-DD.json`
  captures results.
- Delta script: `scripts/compare-preset-variety.py` reads the baseline
  + post-deploy JSONs, prints a diff table:
  ```
  metric                  baseline   post-deploy   delta   threshold   pass/fail
  shannon_entropy         0.12       1.62          +1.50   >=1.5       PASS
  colorgrade:halftone     47.3       8.1           -39.2   <=10.0      PASS
  recent10_mean_dist      0.18       0.44          +0.26   >=0.4       PASS
  ```
- Operator visual-read declaration on the checklist items from §1.4.

**Description:** Phase 1's counterpart. Re-runs the same script on a
fresh window, diffs against the baseline, and declares win or triages.
If any metric fails the threshold, the responsible phase is identified
(e.g., entropy still <1.5 -> scoring changes under-weighted, tune
`HAPAX_AFFORDANCE_RECENCY_WEIGHT` up; halftone still underfired ->
affordance catalog gap, Phase 5 remediation incomplete).

**Blocking dependencies:** All of Phases 1-7 must have landed and
deployed. Phase 8 blocks only if the content-programming layer has
landed; otherwise Phase 9 runs against the Phases-1-7-only baseline
and declares win on that basis.

**Parallel-safe siblings:** None - terminal phase.

**Success criteria:**
- Delta script exits 0 with all three quantitative metrics passing.
- Operator subjective-read >=3 of 5 families firing in a 60-min window.
- `rg 'if.*family.*cooldown|if.*recent.*return' agents/ shared/`
  across all merged phases returns 0 - no expert-system rule
  resurrection.

**Test strategy:** Script fixture-tested on a toy baseline/post-deploy
pair. Live run is the acceptance gate.

**Estimated LOC:** 150 script + 50 tests. Size: S.

**Commit message template:**

```
chore(preset-variety): Phase 9 — post-deploy re-measurement + win declaration

Ran measure-preset-variety-baseline.py on post-deploy 60-min window.
Results: entropy <pre>-><post>, colorgrade:halftone <pre>-><post>,
recent-10 mean-distance <pre>-><post>. All thresholds met / <list
failures>. <Win declared | triage to Phase X>.

Phase 9 of preset-variety-plan. Terminal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## §3. DAG + critical path

```
Phase 1 (baseline)
    |
    v
Phase 2 (narrative unblock)          <-- highest-value quickest fix
    |
    v
 +--+---+------+------+
 v      v      v      v
Phase 3   Phase 4   Phase 5
(recency) (Thompson (catalog
 scoring) decay)    audit)
 |         |        |
 +---+-----+----+---+
     v          v
  Phase 6    Phase 7
  (impingement) (transitions)
     |          |
     +----+-----+
          v
     Phase 8 (programme - ALSO gated on task #164)
          |
          v
     Phase 9 (re-measurement)
```

**Critical path:** Phase 1 -> Phase 2 -> Phase 3 -> Phase 6 -> Phase 9
(narrative unblock + scoring input + impingement + measure). Phase 2
is serial-critical - the research explicitly flags that scoring
improvements do not compound while the narrative monoculture holds.

**Parallel opportunities:**
- Phases 3, 4, 5 can fan out after Phase 2 (three distinct
  modules: pipeline scoring, activation decay, Qdrant catalog).
- Phases 6 and 7 can fan out after Phase 3 lands (6 needs recency
  tracker; 7 needs pipeline awareness of transition family).
- Phase 8 is terminal and is gated externally on task #164.

**Estimated critical-path wall-clock:** Phase 1 ~= 2h. Phase 2 ~= 2h
(mostly audit, small fix). Phase 3 ~= 4h. Phase 6 ~= 3h. Phase 9 ~= 1h.
~= 12h serial; parallel dispatch on Phases 3/4/5 compresses the full
1-7 set into ~8h wall-clock assuming three execution subagents. Phase 8
is external to that estimate.

---

## §4. Per-phase risk

| Phase | Failure at 80% | Rollback | Detection |
|-------|---------------|----------|-----------|
| 1 | Script mis-parses log format; baseline is noise | One-commit revert; re-run with fix | Fixture test |
| 2 | Prompt-bias removal makes narrative incoherent | Revert prompt edit; neutralise differently | Narrative log shows degraded quality |
| 3 | Recency weight too high; continuity breaks | Feature flag `HAPAX_AFFORDANCE_RECENCY_WEIGHT=0.0`; revert | Operator visual flag + entropy spike past reasonable range |
| 4 | Decay too aggressive; Thompson posteriors thrash | Feature flag `HAPAX_AFFORDANCE_THOMPSON_DECAY=1.0` disables | Telemetry on idle-capability variance |
| 5 | Audit surfaces hundreds of gaps; remediation explodes | Ship audit report alone; defer remediation to separate PRs | Report size + gap count |
| 6 | Impingement fires constantly; pipeline thrashes | Tune cluster-similarity threshold up (0.85 -> 0.90); revert | `content.too-similar-recently` frequency in director-intent log |
| 7 | Transition primitive crashes compositor | Revert one commit; transitions default back to fade.smooth | systemd restart loop |
| 8 | `ProgrammeAesthetics` soft prior becomes de-facto hard gate | Assertion test at pipeline boundary: no candidate excluded from recruitment purely on palette_bias | Recruitment log shows non-biased family firing when signal demands |
| 9 | Thresholds set too aggressively; phase-work ships but "fails" | Re-run with adjusted thresholds; declare partial-win if >=2 of 3 pass | Delta script output |

---

## §5. Branch / PR strategy

- **Branch:** `hotfix/fallback-layout-assignment` (already current).
  All phases commit directly. Do NOT create new branches per phase.
- **Per phase:** one execution subagent -> one commit (or tight set:
  module + tests + fixture data) -> push -> delta opens one PR with
  squash-merge. The PR body is the phase's success criteria.
- **PR template (per phase):**

  ```
  ## Phase <N>: <name>

  Per docs/superpowers/plans/2026-04-20-preset-variety-plan.md §<N>.

  ## Changes
  - <bullet list of file changes>

  ## Measurement evidence
  - Pre: <metric>: <value>
  - Post: <metric>: <value> (threshold <value>)

  ## Test plan
  - [ ] `uv run pytest <paths> -q`
  - [ ] `uv run ruff check <paths>`
  - [ ] `rg 'if.*family.*rotate|if.*recent.*return' <paths>` returns 0
        (no expert-system rule smuggle)

  Closes task #166 phase N.
  ```

- **CI gate:** every phase's PR must pass CI (ruff, pytest). Delta
  does NOT merge until CI green.
- **Merge order:** Phase 1 first. Phase 2 second. Phases 3/4/5 in
  parallel. Phase 6 after 3. Phase 7 after 3+5. Phase 8 after task
  #164 lands. Phase 9 terminal.
- **Operator owns:** PR review (light-touch), merge button, deploy
  command, Phase 9 subjective-read declaration.
- **DO NOT:** force-push to main; rebase merged commits; skip CI;
  skip the Phase 9 re-measurement before declaring win; reintroduce
  any filter/gate pattern the research §4 thesis rejects.

---

## §6. Acceptance checklist

Walk after Phase 9 ships. Mark PASS / FLAG / BLOCK per item.

### Quantitative

1. [ ] `scripts/compare-preset-variety.py` exits 0 with all three
       metrics passing thresholds
2. [ ] Shannon entropy >=1.5 over 60-min window (vs baseline)
3. [ ] colorgrade:halftone ratio <=10:1 over 60-min window
4. [ ] Recent-10 mean cosine min-distance >=0.4
5. [ ] `hapax_preset_family_distribution` Prometheus metric shows >=3
       of 5 families firing in a 60-min window

### No-regression (expert-system-rule audit)

6. [ ] `rg 'if.*family.*cooldown|if.*recent.*return|if.*cluster.*skip'
       agents/ shared/` across all merged phases returns 0
7. [ ] Phase 2 narrative-prompt audit committed; no per-family
       preference phrasing remains
8. [ ] No phase introduced a new filter path - recency, Thompson decay,
       impingement, and programme palette bias are all SCORING INPUTS
       or STATE UPDATES, never filter-conditions

### Catalog

9. [ ] Every `preset.bias.<family>` Qdrant entry has >=3 registered
       members
10. [ ] No presets failing to load at compositor start (thermal
        shader recompiles clean or explicitly deregistered)

### Subjective read (operator, 60-min `/dev/video42` capture)

11. [ ] >=3 of 5 preset families visibly fire
12. [ ] >=2 distinct transitions observed in chain changes
13. [ ] "Same-y" complaint subjectively resolved

### Operator declaration

14. [ ] Operator: "variety reads like 30 presets, not 6" -> DONE

---

## §7. Notes for execution subagents

### Subagent dispatch hygiene (verbatim, non-negotiable)

Per workspace CLAUDE.md "Subagent Git Safety — MANDATORY": dispatch
WITHOUT `isolation: "worktree"`. Include verbatim in every dispatch
prompt:

> You are working in the cascade worktree
> (`/home/hapax/projects/hapax-council--cascade-2026-04-18`). Branch
> is `hotfix/fallback-layout-assignment`. Commit directly to this
> branch. Do NOT create branches. Do NOT run `git checkout` or
> `git switch`. Do NOT switch branches under any circumstances.

After EVERY subagent that writes code, immediately verify:
`ls <expected_files> && git log --oneline -3 origin/hotfix/fallback-layout-assignment..`.
If files are missing, rewrite directly - the code is in conversation
context. Do not re-dispatch.

### Expert-system-rule smuggle audit (PER PHASE)

Before declaring a phase complete, run:

```
rg 'if.*family.*cooldown|if.*recent.*return|if.*cluster.*skip|
    if.*programme.*and.*refuse|if.*same.*family.*reject'
   <files_touched>
```

Any match is a bug. The research §4 thesis is non-negotiable:
recency is a score contribution, Thompson decay is a state update,
impingement is a signal, programme palette is a soft prior. Filters
and gates are ALL forbidden.

The single expected exception is if an execution subagent discovers a
pre-existing gate pattern while editing an adjacent site - in that
case, flag it, reference the gate-audit docs
(`docs/research/2026-04-19-expert-system-blinding-audit.md`), and
propose retirement as a separate PR.

### Feature flags as rollback levers

Phases 3 and 4 ship behind feature flags
(`HAPAX_AFFORDANCE_RECENCY_WEIGHT`, `HAPAX_AFFORDANCE_THOMPSON_DECAY`).
If operator flags a variety-too-restless or continuity-broken regression
post-deploy, the flag is the fastest rollback (no commit revert). The
flag values for "neutralise" are 0.0 (recency) and 1.0 (Thompson -
gamma of 1.0 means no decay). Document the operator-runtime override
path in the release notes.

### Phase-2 root-cause uncertainty

Research §8 question 8 flags the director-prompt hypothesis as
"possibly" - the dominant expectation is prompt-level, but the Phase 2
subagent should investigate all three candidates (prompt bias, catalog
sparsity, whitelist smuggle) and report which actually dominates.
Commit message fills in the root-cause bracket based on findings.

### Phase ordering under task #164 slippage

If task #164 (content-programming layer) is delayed past the Phase 7
ship date, Phase 8 is deferred indefinitely and does NOT block win
declaration on Phases 1-7. The Phase 9 thresholds are set so the
scoring+catalog work alone should pass them. If it does not, diagnosis
triages to the scoring weight tuning, not to Phase 8 dependency.

### Phases that are "as ambiguous as the plan can make them" but still dispatchable

- **Phase 2 root cause:** the plan lists three candidate diagnoses
  without pre-committing. Execution subagent enumerates, tests, and
  fills in the commit-message bracket.
- **Phase 5 remediation scope:** the audit may surface a wide spread of
  gaps. Subagent's default is to commit the audit report first, then
  propose remediation as a separate subagent dispatch if the scope
  exceeds ~300 LOC.
- **Phase 6 cluster-similarity threshold:** 0.85 is the starting point
  from research §5.4. Subagent may tune within 0.80-0.90 based on live
  frequency observed on the telemetry rig; pin final value in a
  regression test.
- **Phase 7 transition primitive parameters:** step counts, durations,
  and easing curves are under-specified. Subagent picks values that
  render legibly at 24 fps; operator tunes post-deploy.
- **Phase 8 example palette bias weights:** research §5.6 sketches
  vinyl-listening and beat-making. Subagent may propose different
  programmes if task #164's landed set makes different pairings more
  natural; maintain the soft-prior contract regardless.

---

**Cross-references:**

- `docs/research/2026-04-19-preset-variety-design.md` (research source)
- `docs/research/2026-04-19-content-programming-layer-design.md`
  (programme palette dependency for Phase 8)
- `docs/research/2026-04-19-expert-system-blinding-audit.md` (A6/A7
  retirement context; Phase 2 catalog audit cross-refs)
- `docs/superpowers/plans/2026-04-19-homage-completion-plan.md` §B6
  (un-shipped HARDM -> FX-bias coupling; complements Phase 6 by adding a
  second impingement channel)
- Memory: `feedback_no_expert_system_rules` (every phase bound by this),
  `project_programmes_enable_grounding` (Phase 8 contract),
  `feedback_grounding_exhaustive` (every phase is grounding or
  outsourced-by-grounding),
  `feedback_exhaust_research_before_solutioning` (Phase 1 gates all
  subsequent work),
  `feedback_verify_before_claiming_done` (Phase 9 gates win declaration).
