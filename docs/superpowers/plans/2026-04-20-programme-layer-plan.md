---
date: 2026-04-20
author: alpha (Claude Opus 4.7, 1M context, cascade worktree, planning subagent)
audience: delta (execution dispatcher) + operator
register: scientific, neutral
status: dispatchable plan — multi-phase, post-live iteration for task #164
related:
  - docs/research/2026-04-19-content-programming-layer-design.md
  - docs/superpowers/plans/2026-04-19-homage-completion-plan.md
  - docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md
  - agents/studio_compositor/director_loop.py
  - agents/studio_compositor/structural_director.py
  - shared/director_intent.py
  - shared/compositional_affordances.py
  - memory: feedback_hapax_authors_programmes.md
  - memory: project_programmes_enable_grounding.md
  - memory: feedback_no_expert_system_rules.md
  - memory: feedback_grounding_exhaustive.md
branch: hotfix/fallback-layout-assignment
operator-directive-load-bearing: |
  "director loop is not enough; hapax needs to program content in
  coherent batches in the way livestream content would actually be
  planned and then executed; director loop should be used for
  sub-programme moves."

  + "content programming arcs should GIVE and ENCOURAGE opportunities
  for grounding moves NOT REMOVE THE NEED FOR THEM"

  + "absolutely not Hapax is on the hook for everything" (rejecting
  hybrid/operator-curated authorship).
---

# Content Programming Layer — Implementation Plan

## §0. Scope, intent, and what this plan IS (and ISN'T)

This plan converts `docs/research/2026-04-19-content-programming-layer-
design.md` into a phase-by-phase execution plan for the **meso** layer
identified in that doc (Programme — bounded 5-30 min sections with role,
content directives, constraint envelope, success criteria, entry / exit
rituals). It is the post-go-live iteration on task #164, and is intended
to land across twelve discrete phases on
`hotfix/fallback-layout-assignment` after the tonight's HOMAGE
completion plan has merged and the 30-minute livestream acceptance
capture has been signed off.

The plan takes three load-bearing constraints as axiomatic — not as
design suggestions:

1. **Hapax authors every programme.** The operator never writes
   programme outlines, skeletons, cue sheets, templates, vault
   frontmatter for programmes, or any pre-stream authorship artifact.
   The vault at `~/Documents/Personal/` is a READ-SOURCE (perception
   input for the programme planner LLM), never a WRITE-TARGET. The
   operator's only pre-stream influence is biographical — goal notes,
   daily notes, sprint measures are read as perception, not consumed as
   programme skeletons. Runtime influence is via impingements
   (side-chat, Stream Deck, voice, presence shifts), which the pipeline
   already recruits capabilities against. Reference:
   `feedback_hapax_authors_programmes.md`.
2. **Programmes expand grounding, they do not replace it.** A Programme
   is an affordance-expander. Its constraint envelope is a soft prior
   (a bias weighting in the affordance pipeline's scoring function),
   never a hard gate that cuts capabilities from recruitment. A
   Programme's content directives are perceptual grounding opportunities
   — material Hapax can reach for — not pre-written narrative text.
   Programmes must never contain scripted utterances, hardcoded cadence
   overrides that bypass recruitment, or pre-determined ward emphasis
   sequences. Reference: `project_programmes_enable_grounding.md`.
3. **Every move is a grounded recruitment.** Programme authorship
   itself is recruitment — the planner LLM recruits programme-shape
   capabilities (role, duration, constraint envelope shape) from an
   affordance catalog at show-start and at each boundary. Transition
   rituals are recruited through the choreographer, not hardcoded by
   programme definition. There is no expert-system rule, timer-driven
   gate, or hardcoded threshold in this plan's deliverables that the
   pipeline could have decided instead. References:
   `feedback_no_expert_system_rules.md`,
   `feedback_grounding_exhaustive.md`.

This plan IS a set of twelve discrete subagent dispatches under delta
orchestration. Each phase produces one squash-merged PR. Critical-path
estimate in §3. Per-phase risk in §4. Branch/PR strategy in §5.
Operator-walked acceptance checklist in §6. Execution-subagent
boilerplate in §7.

This plan is NOT code — it is a dispatchable plan. It is NOT a hotfix
— it builds the meso layer Hapax has never had. It is NOT a rewrite of
the existing director tiers — the narrative director and structural
director remain, demoted to the tactical and sub-programme scales
respectively. It is NOT a path that reintroduces any expert-system
rule at the programme scale; if any phase below appears to do so,
that's a bug and must be flagged.

The plan's critical assertion: every phase's success criteria include
a grounding-expansion check. No phase may REDUCE the candidate set
the affordance pipeline scores against. Programmes are additive —
they expand the recruitment surface, not shrink it. Phase-level proofs
are in §2.

---

## §1. Success definition — what "done" looks like at the stream surface

The acceptance test is a 30-minute livestream capture containing three
programmes of distinct role (concretely: `opening-listening`,
`studio-work-block`, `wind-down`), with programme transitions at the
two internal boundaries. Success is measured against five concrete
observable criteria at the surface level, not at the code level.

**1.1 Observable programme identity at the surface.** A viewer
watching for 90 s within any single programme can name, from visual
and audible cues alone, what section they are in. The listening
programme reads as a listening programme (ward emphasis at most 2/min
biased, substrate saturation damped, speech-surface threshold high);
studio-work-block reads as a studio-work-block (ward emphasis 3-5/min
biased, substrate saturation lifted, desk-work camera foregrounded);
wind-down reads as wind-down (ward emphasis <=1/min biased, substrate
saturation minimum, captions dimmed). The surface does not read as an
unbroken stream of tactical reactions.

**1.2 Observable transitions at programme boundaries.** At each
programme boundary, the surface visibly marks the transition through
four beats recruited (not hardcoded): exit ritual of outgoing programme
(signature artefact rotation + ward choreography via the
choreographer), director-loop freeze (recruited cadence bias, 3-5 s),
substrate palette crossfade (Reverie mixer recruited palette shift),
entry ritual of incoming programme (signature artefact + ward
choreography). Viewers see "we moved into a new section" without
needing explicit chrome. The rituals themselves are *recruited through
the pipeline* — no programme defines literal emphasis sequences;
programmes emit ritual-scope impingements and the pipeline recruits
from the active capability catalog.

**1.3 Cadence envelope honored softly, not rigidly.** Concrete targets
(soft-prior biases, not hard gates):

- Listening programme: ward emphasis rate soft-biased toward <=2/min,
  actual can exceed if impingement pressure demands.
- Hothouse programme: ward emphasis rate soft-biased toward >=5/min,
  actual can fall below if impingement pressure is low.
- Studio-work-block: ward emphasis rate soft-biased toward 3-5/min.
- Wind-down: ward emphasis rate soft-biased toward <=1/min.

The scoring function applies the soft prior; the pipeline can still
surface capabilities outside the soft envelope when their recruitment
score exceeds the in-envelope alternatives. The Prometheus counter
`hapax_programme_soft_prior_overridden_total{programme_id, reason}`
increments on each such override (and must be non-zero in a healthy
system — if it's always zero, the soft prior has become a hard gate,
which is the anti-pattern).

**1.4 Programme condition id stamping in all artifacts.** Every
director-intent JSONL record, every ward-properties write, every
CPAL utterance event, and every Prometheus metric carries both the
outer research condition id (as today) AND the active programme id.
The Bayesian validation pipeline can slice by programme within a
condition: a 1-condition stream with 3 programmes produces 3 samples,
not 1.

**1.5 JSONL programme-outcomes log contains no scripted text.** Post-
stream audit of `~/hapax-state/programmes/<show_id>/<programme-id>.
jsonl` confirms: narrative utterances are generated by the narrative
director LLM (grounded), not by programme definition. No line in the
outcomes log was a template substitution from the programme plan. If
any utterance traces to a hardcoded string in the programme catalog,
that's a bug.

**Grounding-expansion assertion (global).** Across the 30-min capture,
the affordance pipeline's candidate-set size AFTER programme filter is
greater-than-or-equal-to the candidate-set size BEFORE programme
filter would have been at every single tick. Programmes only ADD
capabilities to the recruitment space via role-scoped extensions
(e.g., `ward.emphasis.<id>` family opens during `hothouse_pressure`
role); they do not REMOVE capabilities. The Prometheus counter
`hapax_programme_candidate_set_reduction_total{programme_id}` must
stay at 0 for the entire stream. A non-zero value is a blocking bug
that must be fixed before the programme layer is considered live.

---

## §2. Phase list

Twelve phases, organised into four families: **P** (primitive),
**G** (generation), **C** (consumer integrations), **T** (transitions
+ observability + acceptance). Each phase has: scope (exact file
paths), blocking deps, parallel-safe siblings, success criteria
(including grounding-expansion assertion), test strategy, LOC estimate
(S/M/L), commit-message template.

Sizes are calibrated the same way as the homage plan: S <=200 LOC,
M 200-500 LOC, L 500-1500 LOC.

### Family P — Primitive + state

#### Phase 1: `Programme` Pydantic primitive + affordance-expander properties

**Scope:**
- New file: `shared/programme.py`
- Tests: `tests/shared/test_programme.py`

**Description:** Implement the Pydantic-style sketch from research §3:
`ProgrammeRole` (12-member StrEnum: LISTENING, SHOWCASE, RITUAL,
INTERLUDE, WORK_BLOCK, TUTORIAL, WIND_DOWN, HOTHOUSE_PRESSURE, AMBIENT,
EXPERIMENT, REPAIR, INVITATION), `ProgrammeStatus` (4-member:
PENDING, ACTIVE, COMPLETED, ABORTED), `ProgrammeConstraintEnvelope`,
`ProgrammeContent`, `ProgrammeRitual`, `ProgrammeSuccessCriteria`,
`Programme`.

CRITICAL — the envelope fields are **soft-prior biases**, not hard
gates. Rename fields accordingly so the code reads the intent:

- `forbidden_capabilities` → `capability_bias_negative` (a dict of
  capability-name -> score-multiplier in (0.0, 1.0); 0.25 is
  "bias against but allow if impingement insists"; zero is rejected
  at validator time)
- `required_capabilities` → `capability_bias_positive` (a dict of
  capability-name -> score-multiplier in (1.0, infinity); 4.0 is
  "strongly prefer")
- `ward_emphasis_cap` → `ward_emphasis_target_rate_per_min` (target
  rate, not a hard cap; the narrative director receives it as a soft
  prior)
- `narrative_cadence_s` → `narrative_cadence_prior_s` (a prior the
  pipeline can override under impingement pressure)
- `surface_threshold` → `surface_threshold_prior` (a prior, not a
  ceiling)
- `reverie_saturation_target` kept as-is (this is a genuine palette
  target, not a gate)

This renaming is load-bearing: it encodes the grounding-expansion
architectural axiom at the type system layer so no downstream consumer
can accidentally treat the envelope as a hard gate.

Also provide properties:

- `Programme.expands_candidate_set(capability_name) -> bool` — asserts
  `capability_bias_negative.get(name, 1.0) > 0.0` (strictly positive;
  zero would be a hard exclusion and is architecturally forbidden)
- `Programme.bias_multiplier(capability_name) -> float` — returns the
  composed bias (positive-or-negative) for the consumer's scoring
  function
- `Programme.elapsed_s` (already in sketch)
- `Programme.validate_soft_priors_only()` — type-check validator that
  runs at model instantiation; raises `ValueError` if any bias is
  <=0 or any "hard gate" sentinel leaks in

**Blocking dependencies:** None (leaf module).

**Parallel-safe siblings:** Phase 2, 3, 4, 8, 9 can all run alongside.

**Success criteria:**
- `uv run pytest tests/shared/test_programme.py -q` passes (>=20 tests)
- `uv run ruff check shared/programme.py` clean
- `uv run pyright shared/programme.py` clean
- **Grounding-expansion:** the type system REJECTS any envelope with
  `capability_bias_negative[name] == 0.0`. Attempting to instantiate
  such an envelope raises `ValueError`. Phase 1 thus cannot produce a
  hard-gate envelope; the architectural invariant is enforced at the
  Pydantic validator level.

**Test strategy:** Unit tests per sub-model (field-level validation,
validator rejects zero-bias, `expands_candidate_set` property),
round-trip JSON serialisation, at-instantiation soft-prior validation.

**Estimated LOC:** 400-600 module + 300-400 tests. Size: M.

**Commit message template:**

```
feat(programme): Pydantic primitive — soft-prior envelope, no hard gates

Implements the Programme primitive from
docs/research/2026-04-19-content-programming-layer-design.md §3.
Phase 1 of the programme-layer plan.

Key architectural encoding: constraint envelope fields are renamed to
soft-prior terms (capability_bias_positive/negative, *_prior) and a
Pydantic validator rejects zero-bias at model instantiation, so hard
gates cannot be constructed. Per project_programmes_enable_grounding —
programmes EXPAND grounding, they do not replace it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

#### Phase 2: ProgrammePlanStore — persist + rotate plans

**Scope:**
- New file: `agents/programme_manager/plan_store.py`
- New file: `agents/programme_manager/__init__.py` (module scaffold)
- Tests: `tests/programme_manager/test_plan_store.py`

**Description:** Persistence + rotation layer for programme plans at
`~/hapax-state/programmes/<show_id>/plan.json`. The store provides:

- `ProgrammePlanStore.load(show_id) -> ProgrammePlan | None`
- `ProgrammePlanStore.save(show_id, plan: ProgrammePlan) -> None` —
  atomic tmp+rename
- `ProgrammePlanStore.rotate(show_id) -> None` — moves
  `plan.json` to `plan.<iso8601>.json` and removes files older than
  7 days (so re-plans at programme boundaries don't accumulate cruft)
- `ProgrammePlanStore.active_plan(show_id) -> ProgrammePlan | None` —
  the plan currently in effect; lock-free read
- `ProgrammePlanStore.history(show_id) -> list[ProgrammePlanRotation]`
  — all rotations in chronological order, for post-stream analysis

`ProgrammePlan` is a new Pydantic wrapper: `programmes: list[Programme]`,
`plan_author: str` (always `"hapax-director-planner"` per the
hapax-authored constraint), `plan_generated_at: float`,
`show_id: str`, `condition_id: str | None`,
`perceptual_snapshot_ref: str | None` (relative path to a perception
snapshot file captured alongside for auditability).

**Blocking dependencies:** Phase 1.

**Parallel-safe siblings:** Phase 3, 4, 8, 9.

**Success criteria:**
- Plans round-trip to disk and back without data loss
- Rotation is atomic (tmp+rename); interrupted writes never produce a
  partial `plan.json`
- `uv run pytest tests/programme_manager/test_plan_store.py -q`
  passes (>=15 tests, including crash-consistency via
  `unittest.mock`)
- **Hapax-authored invariant:** `ProgrammePlan.plan_author` is
  immutable post-instantiation and must equal
  `"hapax-director-planner"`. A validator rejects any other value.
  This prevents downstream code from writing a plan attributed to
  the operator or a vault-loader.
- **Grounding-expansion:** the store never mutates a saved
  `Programme`'s envelope to reduce bias; rotation preserves the
  plan verbatim. A test asserts that `rotate` followed by
  `active_plan` returns envelope-bias-equivalent Programmes.

**Test strategy:** Filesystem mock + atomic-rename tests, rotation
ordering, crash-consistency (simulate interrupted write).

**Estimated LOC:** 350-500 module + 250 tests. Size: M.

**Commit message template:**

```
feat(programme): ProgrammePlanStore — persist + rotate plans

Persistence layer at ~/hapax-state/programmes/<show_id>/plan.json
with atomic tmp+rename, rotation on re-plan (keep 7d), and an
invariant-enforced Hapax-authored author field. Phase 2 of the
programme-layer plan.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Family G — Plan generation (Hapax-authored)

#### Phase 3: Hapax-authored programme planner LLM

**Scope:**
- New file: `agents/programme_manager/planner.py`
- New file: `agents/programme_manager/prompts/programme_plan.md`
- Tests: `tests/programme_manager/test_planner.py`

**Description:** The programme planner LLM call — runs at show-start
and at each programme boundary, emits a 2-5 programme plan as a
`ProgrammePlan`. Inputs (read-only):

1. **Perceptual snapshot** — current `PerceptualField` state: operator
   presence, stance, biometrics (from watch receiver), recent utterance,
   camera / IR signals, room ambient, contact-mic activity.
2. **Vault state** (read-source only, per
   `feedback_hapax_authors_programmes`): goal notes (`type: goal`
   frontmatter), sprint measures, today's daily note, active project
   frontmatter, person notes for any consented-interaction context.
   Vault is read via the existing `logos/data/vault_goals.py` +
   `vault_scan` helpers; NO new vault writes are added, no
   `type: programme` frontmatter is defined, no programme template is
   scaffolded into `50-templates/`.
3. **Operator profile** — recent activity, fatigue proxy, working mode
   (`research`/`rnd`/`fortress` via `shared/working_mode.py`).
4. **Research condition history** — Thompson-sampling posteriors over
   (`programme_role` × `condition_id`) pairs from prior streams,
   loaded from `~/hapax-state/programmes/_history/posteriors.json`
   (the planner updates this post-show in Phase 9).
5. **Available content state** — vinyl platter current track (if any),
   SoundCloud queue depth, whiteboard content classification from the
   overhead camera, YouTube reaction queue state.

The LLM is routed through LiteLLM at the `balanced` tier (Claude
Sonnet) for grounding quality — this is a grounding-critical planning
call per `feedback_director_grounding` and
`feedback_grounding_exhaustive`. Never route to an ungrounded tier.

The prompt is a Markdown file at
`agents/programme_manager/prompts/programme_plan.md` (NOT an inline
Python string), loaded by the planner. It enumerates the 12 roles
with brief gloss each, describes the soft-prior envelope fields, and
instructs the LLM to emit JSON matching `ProgrammePlan`. The prompt
explicitly states that `capability_bias_*` values must be strictly
positive (no hard gates).

Output: JSON validated against `ProgrammePlan`; on validation failure,
the planner retries once with the validation error message fed back.
On second failure, the planner logs a WARN and the system falls
through to "no active programme" — the stack works fine without a
programme (see Phase 4 consumer fallback).

The planner LLM call is an affordance pipeline recruitment at the
planning scale. The planner LLM "recruits" programme-shape
capabilities; its output is a grounded recruitment product, not a
pre-written script. This is the meta-move that aligns programme
authorship with the unified recruitment architecture.

**Blocking dependencies:** Phase 1, Phase 2.

**Parallel-safe siblings:** Phase 4, 8, 9.

**Success criteria:**
- Planner produces a validated `ProgrammePlan` on happy-path inputs
  in <30 s (research doc §10 Q9 — operator accepts ~15-30 s show-start
  latency)
- Planner retries on validation failure and succeeds on benign
  malformations (unknown role name -> retry with enum reminder)
- **Hapax-authored invariant:** `plan.plan_author ==
  "hapax-director-planner"`; the planner never reads a
  user-supplied outline file. A test asserts that even if a
  well-formed programme JSON is left in the vault at
  `~/Documents/Personal/20-projects/hapax-research/programmes/*.md`,
  the planner ignores it.
- **Grounding-expansion:** the planner's output envelopes must have
  strictly positive `capability_bias_*` values (already enforced at
  Phase 1's type layer; this phase tests it end-to-end through
  `planner.plan(inputs)`). A test asserts candidate-set size at the
  downstream affordance pipeline is non-decreasing after plan
  application vs. empty plan.
- `uv run pytest tests/programme_manager/test_planner.py -q` passes
  (>=18 tests with `unittest.mock` for LLM call, VCR-style fixtures
  for end-to-end)

**Test strategy:** `unittest.mock` for the LiteLLM call with fixture
response payloads covering: happy path, validation failure +
retry success, hard-gate attempt rejected, vault-outline-ignored.
No real LLM calls in CI.

**Estimated LOC:** 500-750 module + 400 tests + 150-line prompt.
Size: L.

**Commit message template:**

```
feat(programme): Hapax-authored programme planner LLM

Runs at show-start and programme boundaries; reads perception + vault
+ profile + condition history + content state; emits validated
ProgrammePlan. Routes through `balanced` tier (Claude Sonnet) for
grounding quality.

Hapax-authored enforced at two layers: plan.plan_author validator
(Phase 2) and test that vault programme files are ignored.

Phase 3 of the programme-layer plan. Per research §4.1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Family C — Consumer integrations (soft-prior biases)

#### Phase 4: Affordance pipeline — programme as soft prior scoring input

**Scope:**
- `shared/compositional_affordances.py` — extend
  `AffordancePipeline.select` to accept an optional programme context
- New helper: `_apply_programme_bias(candidates, programme) ->
  list[Candidate]` — ADDS bias terms to each candidate's score based
  on `programme.bias_multiplier(candidate.name)`
- Tests: `tests/shared/test_affordance_pipeline_programme.py`

**Description:** This is the load-bearing consumer integration. The
affordance pipeline is the central choke point where programme soft
priors become scoring biases. Per research §5.1 and
`project_programmes_enable_grounding`:

- The programme filter runs BEFORE scoring, but it is a **bias
  application**, not a candidate-set reduction.
- The programme's `capability_bias_positive` dict maps to score
  multipliers > 1.0; `capability_bias_negative` maps to multipliers
  in (0.0, 1.0).
- **Zero is never a valid multiplier** — the Phase 1 validator
  guarantees this.
- Candidates whose composed score falls below the pipeline's existing
  recruitment threshold are NOT recruited; they are still in the
  candidate set being scored. They could still win if impingement
  pressure is high and their base similarity is above threshold.

Concrete change to `AffordancePipeline.select`:

```python
def select(self, impingement, *, programme=None, ...):
    candidates = self._retrieve_top_k(impingement.embedding)
    # candidates is ALWAYS the full retrieved set; programme never
    # shrinks it
    if programme is not None:
        candidates = _apply_programme_bias(candidates, programme)
        # _apply_programme_bias returns a list of the SAME length,
        # with each Candidate's score multiplied by the bias
    candidates = self._apply_governance_veto(candidates)
    candidates = self._score(candidates)
    return self._threshold_filter(candidates)
```

Also update the Prometheus emission to add a
`hapax_programme_candidate_set_reduction_total{programme_id}` counter
that must stay at 0 (increments only on implementation bug).

**Blocking dependencies:** Phase 1.

**Parallel-safe siblings:** Phase 5, 6, 8, 9 (different files).

**Success criteria:**
- Pipeline applies programme bias without shrinking the candidate set
- **Grounding-expansion assertion (test):** `len(candidates_after_programme)
  == len(candidates_before_programme)` for ALL programme inputs,
  including pathological ones (every capability strongly biased
  negative).
- `hapax_programme_candidate_set_reduction_total` metric starts at 0
  and stays at 0 through the CI integration test suite
- Test: impingement with bias-negative capability still recruits that
  capability when its cosine score is high enough to overcome the
  bias (e.g., 0.9 cosine × 0.25 bias = 0.225 composed score, below
  threshold 0.30 — does NOT recruit; BUT raise impingement score to
  0.95 cosine × 0.5 bias = 0.475, DOES recruit — impingement pressure
  overrides soft prior)
- `uv run pytest tests/shared/test_affordance_pipeline_programme.py
  -q` passes (>=16 tests)
- `uv run ruff check shared/compositional_affordances.py` clean

**Test strategy:** Mock-based unit tests over the scoring function.
Integration test that walks a recruitment against a strongly-biased-
negative capability and asserts recruitment is possible under high
impingement pressure.

**Estimated LOC:** 150-300 module + 300 tests. Size: M.

**Commit message template:**

```
feat(programme): affordance pipeline — programme bias as soft prior

Extends AffordancePipeline.select to accept an optional programme
context. Programme envelope is applied as a score MULTIPLIER, never
as a candidate-set reduction. Candidate-set size is strictly preserved.

Phase 4 of the programme-layer plan. Per research §5.1 and the
grounding-expansion axiom (project_programmes_enable_grounding).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

#### Phase 5: Structural director — programme-aware emission

**Scope:**
- `agents/studio_compositor/structural_director.py` — extend
  `StructuralDirector.tick_once` to read the active programme and:
  - Include programme `role` + `narrative_beat` in the LLM prompt
    context
  - Pass `preset_family_priors` + `homage_rotation_mode_priors` as
    SOFT PRIOR fields in the prompt (framed as "prefers X" not
    "must X")
  - Override `structural_cadence_s` for this tick iff
    `programme.constraints.structural_cadence_prior_s` is set
- `shared/director_intent.py` — extend `StructuralIntent` with an
  optional `programme_id: str | None` field so the emitted intent
  carries the programme stamp (consumed by Phase 9 observability)
- Tests: `tests/studio_compositor/test_structural_director_programme.py`

**Description:** The structural director keeps its 90 s LLM cadence
(overrideable as above). The programme feeds the prompt as a context
frame — the LLM is told "you are 12 min into a listening programme; the
programme's soft prior is `preset_family_priors=['calm-textural']`
and `homage_rotation_mode_priors=['paused','deliberate']`; emit a
StructuralIntent that serves the programme". The LLM may choose
outside the priors if the perceptual field demands it; the priors bias
the LLM, not gate it.

Concrete: the prompt MD file
`agents/studio_compositor/prompts/structural_director.md` (new; lifted
from inline where applicable) gets a new section `## Programme
context` that renders the programme's role + beat + soft-priors in
the prompt only when a programme is active.

The grounding-expansion assertion at the structural-director layer:
the prompt is written so the LLM knows it CAN emit outside the soft
priors when impingement pressure justifies it. Test: feed the LLM
a high-impingement-pressure fixture where the programme's prior is
"paused" and the correct response is "burst"; assert the LLM picks
burst ~30% of the time across a 100-call replay (validates the bias
isn't over-constraining).

**Blocking dependencies:** Phase 1. Phase 3 recommended (so
real programmes exist to consume; with mocks we can test without
Phase 3).

**Parallel-safe siblings:** Phase 4, 6, 7, 8, 9.

**Success criteria:**
- Structural director's `tick_once` output honours programme priors
  on typical inputs (in-envelope choice ~70-80% of ticks)
- Structural director emits out-of-envelope choices under high
  impingement pressure (~20-30% of ticks when pressure forces it)
- `StructuralIntent.programme_id` populated in every emission when
  a programme is active
- **Grounding-expansion:** prompt text explicitly frames priors as
  soft (a pinned regression test inspects the rendered prompt
  string and asserts it contains phrases like "prefers" / "bias" /
  "soft prior" and NOT phrases like "must" / "required" / "only")
- `uv run pytest tests/studio_compositor/test_structural_director_programme.py
  -q` passes (>=15 tests)

**Test strategy:** Mock LLM with fixture responses; verify prompt
content contains programme context; verify emission carries
`programme_id`; replay-based soft-prior / hard-gate distinction test.

**Estimated LOC:** 300-500 module + 300 tests. Size: M.

**Commit message template:**

```
feat(programme): structural director — programme-aware emission

Structural director reads active programme and feeds its role, beat,
and soft priors into the LLM prompt as biases (NOT gates). Programme
id is stamped on every emitted StructuralIntent. Regression pin on
prompt wording to prevent hard-gate drift.

Phase 5 of the programme-layer plan. Per research §5.2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

#### Phase 6: CPAL speech-production — programme-owned should_surface bias (retires F5)

**Scope:**
- `agents/hapax_daimonion/cpal/impingement_adapter.py` (lines ~101-105
  per the F5 deferred scope in the homage plan) — the existing
  `should_surface` hardcoded threshold becomes a programme-driven
  soft prior
- `agents/hapax_daimonion/cpal/runner.py::CpalRunner.process_impingement`
  — read the active programme via a programme-context lookup helper
- `agents/run_loops_aux.py:445-449` — remove the "CPAL owns it"
  short-circuit so pipeline-scored speech reaches CPAL
- Tests: `tests/hapax_daimonion/test_cpal_programme_threshold.py`

**Description:** This phase RETIRES the deferred F5 homage item ("restore
speech_production recruitment path + retire should_surface hardcoded
thresholds"). CPAL's should_surface threshold currently reads a
hardcoded `DEFAULT_SURFACE_THRESHOLD`. The new behaviour:

- `threshold = programme.constraints.surface_threshold_prior or
  DEFAULT_SURFACE_THRESHOLD`
- The threshold is a SOFT PRIOR, not a gate — CPAL's scoring function
  already accepts modulation; we add a bias term that moves the
  threshold by a multiplier in [0.5, 2.0] based on the programme.
- A listening programme biases threshold up (×1.5, Hapax stays quieter);
  a tutorial programme biases threshold down (×0.7, Hapax narrates more
  liberally).
- **The threshold can still be overridden** when impingement pressure
  is extreme. Concretely: the CPAL scorer already computes
  `salience + gain - error_penalty`; the threshold comparison now
  becomes `score >= base_threshold * programme_bias`. A salience-1.0
  impingement still surfaces under any programme.

This retires the F5 speech short-circuit path — the
`run_loops_aux.py:445-449` "CPAL owns it" discard is removed
simultaneously, and CPAL's `should_surface` takes pipeline-scored
speech as a first-class input.

**Blocking dependencies:** Phase 1, Phase 4.

**Parallel-safe siblings:** Phase 5, 7, 8, 9.

**Success criteria:**
- CPAL threshold is programme-biased when a programme is active;
  falls back to DEFAULT_SURFACE_THRESHOLD when none is active
- Salience-1.0 impingements always surface regardless of programme
  (demonstrating the soft-prior not-a-gate property)
- F5 short-circuit in `run_loops_aux.py:445-449` is removed;
  pipeline-scored speech reaches CPAL
- **Grounding-expansion:** test feeds a listening programme + high-
  salience speech-worthy impingement and asserts the utterance DOES
  surface (bias is soft, not ceiling)
- `uv run pytest tests/hapax_daimonion/test_cpal_programme_threshold.py
  -q` passes (>=12 tests)

**Test strategy:** Mock the impingement-pipeline integration; verify
threshold composition; verify salience-1.0 override; verify F5
retirement via regression pin ("the discarded-score path is gone").

**Estimated LOC:** 200-400 module + 250 tests. Size: M.

**Commit message template:**

```
feat(programme): CPAL should_surface — programme-owned soft-prior bias

CPAL's should_surface threshold becomes a programme-biased soft prior
(multiplier in [0.5, 2.0]), not a hard gate. High-salience impingements
still surface regardless of programme. Retires the F5-deferred
speech-production short-circuit (run_loops_aux.py:445-449) — pipeline-
scored speech now reaches CPAL directly.

Phase 6 of the programme-layer plan. Per research §5.4 and closes the
F5 item from the homage plan.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

### Family T — Transitions + observability + integration + acceptance

#### Phase 7: Programme transition choreographer

**Scope:**
- New file: `agents/programme_manager/transition.py`
- `agents/programme_manager/manager.py` — the overall ProgrammeManager
  loop (reads plan, tracks active programme elapsed, evaluates
  boundary triggers, invokes transition choreography)
- Tests: `tests/programme_manager/test_transition.py`
- Tests: `tests/programme_manager/test_manager.py`

**Description:** The transition choreographer orchestrates programme
boundaries. Three boundary-trigger types (research §6):

1. **Planned**: `elapsed_s >= planned_duration_s` AND
   `completion_predicates` all true
2. **Operator-triggered**: impingement arrives with
   `intent_family="programme.transition.<next_programme_id>"`
   — injected by Stream Deck, side-chat, or voice
3. **Emergent**: `abort_predicates` evaluate true (Phase 10 adds the
   abort predicate evaluator)

When a boundary fires, the transition is NOT a hardcoded 4-beat
sequence in code. Instead, the ProgrammeManager EMITS a series of
impingements:

- `programme.exit_ritual.<current_programme_role>` — high-salience,
  soft-prior-biased toward recruiting signature artefact + ward
  choreography capabilities
- `programme.boundary.freeze` — biases the cadence priors down for
  `ritual.boundary_freeze_prior_s` (default 4 s) — the director loop
  can still emit if an impingement demands, but soft-prior-biased
  toward settling
- `programme.palette.shift.<to_role>` — biases Reverie mixer toward
  the incoming palette
- `programme.entry_ritual.<next_programme_role>` — mirrors exit

The pipeline recruits against these impingements as normal. The ward
that lights up for the exit ritual, the signature artefact that
rotates, the ward choreography emitted — ALL chosen by the
affordance pipeline based on which capabilities best match the
ritual-scope impingement narrative. NO choreographer-internal list
of "the exit moves are X, Y, Z". Rituals are recruited, not scripted.

This is the concrete encoding of `project_programmes_enable_grounding`:
programme rituals create grounding opportunities (new high-salience
ritual-scope impingements) that the pipeline reaches for, not a
template engine that plays canned moves.

**Blocking dependencies:** Phase 1, 2, 4 (pipeline needs to see
ritual-scope impingements biased by programme), Phase 5 (structural
director needs to see programme_id on emitted intents so transitions
are observable in director logs).

**Parallel-safe siblings:** Phase 8, 9, 10.

**Success criteria:**
- ProgrammeManager advances PENDING → ACTIVE → COMPLETED through
  the planned lifecycle
- Boundary triggers emit ritual-scope impingements that the pipeline
  recruits against (observable via director-intent.jsonl after
  an integration run)
- `elapsed_s` and `actual_started_at` / `actual_ended_at` stamped
  correctly in state file
- **Grounding-expansion:** ritual-scope impingements are scored
  through the normal pipeline; no transition step uses a hardcoded
  capability invocation. Test: mock a boundary, observe the
  impingements emitted, assert each is a normal Impingement (not a
  direct `dispatch_*` call)
- `uv run pytest tests/programme_manager/test_transition.py -q`
  passes (>=14 tests)
- `uv run pytest tests/programme_manager/test_manager.py -q`
  passes (>=18 tests)

**Test strategy:** State-machine tests for manager; impingement-
emission tests for choreographer; integration test that stages a
boundary and inspects the emission sequence.

**Estimated LOC:** 500-800 module + 500 tests. Size: L.

**Commit message template:**

```
feat(programme): transition choreographer — rituals recruited, not scripted

ProgrammeManager + transition module: boundaries emit ritual-scope
impingements (programme.exit_ritual.<role>, programme.boundary.freeze,
programme.palette.shift.<to_role>, programme.entry_ritual.<role>) that
the affordance pipeline recruits against. Choreographer never contains
a hardcoded list of "the exit moves are X" — rituals are recruited
through the pipeline like every other expression.

Phase 7 of the programme-layer plan. Per research §6 and the
project_programmes_enable_grounding architectural axiom.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

#### Phase 8: Reverie palette range per programme

**Scope:**
- `agents/visual_layer_aggregator/substrate_writer.py` (or wherever the
  Reverie `colorgrade.saturation` / `colorgrade.hue_rotate` flow lands
  — see homage plan A6 for the audit trail) — extend to read
  `active_programme.constraints.reverie_saturation_target` as a
  soft-prior target
- The programme's target is the *range centre*; the actual written
  saturation remains modulated by stimmung / choreographer
  transition-energy signals (homage A6 wiring)
- Tests: `tests/visual_layer_aggregator/test_substrate_programme_palette.py`

**Description:** The homage plan's A6 phase damped saturation to 0.40
under BitchX. This phase makes the target programme-owned. Concrete:

- `ReverieSubstrateWriter.compute_target(package, programme, stimmung,
  transition_energy) -> float` — returns the composed saturation target
- The programme's `reverie_saturation_target` is a RANGE CENTRE: the
  writer computes `target = clamp(programme.reverie_saturation_target
  + stimmung_delta + 0.1 * transition_energy, 0.0, 1.0)`
- When no programme is active, falls back to package default (A6
  behaviour)

Per-role defaults (defined in the planner prompt — these are
suggestions to the LLM, not hardcoded tuples):

- `LISTENING`: target 0.30 (substrate dims so music foregrounds)
- `HOTHOUSE_PRESSURE`: target 0.70 (substrate visibly responds)
- `WIND_DOWN`: target 0.25 (minimum)
- `WORK_BLOCK`: target 0.50 (moderate)

The planner may choose otherwise based on perceptual context — e.g.
if operator biometrics indicate high stress, the planner may pick a
lower target for `WORK_BLOCK` than the nominal 0.50.

**Blocking dependencies:** Phase 1. Homage plan's A6 phase (for
the substrate-writer plumbing). Phase 2 (so the active programme is
readable).

**Parallel-safe siblings:** Phase 4, 5, 6, 7, 9.

**Success criteria:**
- Saturation target respects programme value when programme active
- Stimmung and transition-energy still modulate around the programme
  centre (soft prior, not fixed)
- **Grounding-expansion:** test with a listening programme + high
  transition-energy signal asserts saturation briefly lifts above
  0.30 (shows the programme target isn't a ceiling)
- Live `jq '."colorgrade.saturation"'
  /dev/shm/hapax-imagination/uniforms.json` during a listening
  programme yields values in roughly [0.25, 0.45] (centered on
  programme target, with modulation)
- `uv run pytest
  tests/visual_layer_aggregator/test_substrate_programme_palette.py
  -q` passes (>=10 tests)

**Test strategy:** Unit tests for `compute_target` with programme +
stimmung + transition-energy fixtures; integration pin for uniforms
file contents.

**Estimated LOC:** 150-300 module + 200 tests. Size: M.

**Commit message template:**

```
feat(programme): Reverie saturation target — programme-owned centre

Reverie substrate writer reads active programme's
reverie_saturation_target as the centre of a range that stimmung +
transition_energy modulate around. Soft prior, not a fixed value.

Phase 8 of the programme-layer plan. Per research §5.5 and builds on
homage A6 substrate damping.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

#### Phase 9: Observability — programme metrics + per-programme JSONL

**Scope:**
- `shared/programme_observability.py` — new module mirroring
  `shared/director_observability.py`
- Prometheus metrics:
  - `hapax_programme_start_total{role, show_id}`
  - `hapax_programme_end_total{role, show_id, reason}` (reason ∈
    {planned, operator, emergent, aborted})
  - `hapax_programme_active{programme_id, role}` gauge
  - `hapax_programme_duration_planned_seconds{programme_id}` gauge
  - `hapax_programme_duration_actual_seconds{programme_id}` gauge
  - `hapax_programme_soft_prior_overridden_total{programme_id, reason}`
    — MUST be non-zero in healthy streams (zero = soft prior is acting
    as hard gate)
  - `hapax_programme_candidate_set_reduction_total{programme_id}` —
    MUST stay at zero (non-zero = bug)
- JSONL outcome log at
  `~/hapax-state/programmes/<show_id>/<programme-id>.jsonl` with
  events: `start` (full Programme), `tactical_summary` every 60 s
  (wards emphasised + impingements recruited + speech surfaced during
  window), `abort` (with predicate), `end` (with actual duration +
  reason). Append-only, rotates at 5 MiB / keep 3.
- Grafana dashboard JSON at
  `grafana/dashboards/programme-layer.json`
- Tests: `tests/shared/test_programme_observability.py`

**Description:** Mirror of homage C1 Prometheus work at the programme
scale. Wire emit calls into:

- ProgrammeManager lifecycle (start / end / abort)
- AffordancePipeline (candidate-set reduction counter — must stay 0)
- Pipeline scoring (soft-prior override counter — must be >0 per
  stream to confirm soft priors aren't hardening)

Grafana panels:

- Programme timeline (Gantt-style): which programme is active when
- Soft-prior override rate (sanity check per programme)
- Candidate-set reduction count (should always be zero; alert if not)
- Planned vs actual duration per programme

**Blocking dependencies:** Phase 1, 2, 4, 7.

**Parallel-safe siblings:** Phase 10, 11.

**Success criteria:**
- `curl -s http://localhost:9482/metrics | grep hapax_programme_`
  returns >=7 metric families
- JSONL outcome log contains `start`, `tactical_summary`, `end`
  events for every programme in the acceptance stream
- Grafana dashboard loads and all 4 panels render
- **Grounding-expansion (architectural check):**
  `hapax_programme_candidate_set_reduction_total` is strictly zero
  across the 30-min acceptance stream
- **Soft-prior-not-hardening check:**
  `hapax_programme_soft_prior_overridden_total` is >0 across the
  acceptance stream (at least one override per programme)
- `uv run pytest tests/shared/test_programme_observability.py -q`
  passes (>=14 tests)

**Test strategy:** prometheus_client test fixtures + JSONL round-
trip tests. Grafana dashboard loaded in a local instance as manual
smoketest.

**Estimated LOC:** 400-600 module + 300 tests + 200 LOC dashboard.
Size: M.

**Commit message template:**

```
feat(programme): observability — Prometheus metrics + JSONL outcome log

hapax_programme_* metrics family; per-programme JSONL outcome log at
~/hapax-state/programmes/<show_id>/<programme-id>.jsonl; Grafana
dashboard. Includes two invariant metrics:
- candidate_set_reduction_total: must stay at 0 (bug detector)
- soft_prior_overridden_total: must be >0 per stream (soft-prior-not-
  hardening detector)

Phase 9 of the programme-layer plan. Per research §8.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

#### Phase 10: Abort predicate evaluator + re-plan

**Scope:**
- `agents/programme_manager/abort_evaluator.py` — new module:
  `AbortEvaluator.evaluate(programme, perceptual_snapshot) ->
  AbortDecision | None`
- Extend `ProgrammeManager.tick` to call the evaluator each tick
- On abort: invoke the planner (Phase 3) again with a "re-plan
  forward" flag; save the new plan via ProgrammePlanStore.rotate
  (Phase 2); transition to the new plan's first programme
- Tests: `tests/programme_manager/test_abort_evaluator.py`

**Description:** Per research §4.4 + §6 emergent-transition type. The
abort predicates are named strings in `ProgrammeSuccessCriteria.
abort_predicates` (from Phase 1). The evaluator implements a
registered set of predicate name → evaluator callable mappings:

- `operator_left_room_for_10min` — checks IR presence gauge
- `impingement_pressure_above_0.8_for_3min` — checks VLA pressure
  gauge
- `consent_contract_expired` — checks `axioms/contracts/`
- `vinyl_side_a_finished` — checks vinyl-platter tail-in state
- `operator_voice_contradicts_programme_intent` — checks recent STT
  against programme narrative_beat (LLM-graded via `coding` tier
  — this is a grounding move, must use a grounded model)

When an abort fires, the planner re-runs (Phase 3) with the abort
decision as additional context. The re-plan may keep subsequent
programmes or rewrite the remainder of the show. The operator has a
5 s veto grace window — if an impingement arrives with
`intent_family="programme.abort.veto"` within 5 s of an abort
decision, the abort is cancelled and the programme continues.

**Blocking dependencies:** Phase 2, 3, 7.

**Parallel-safe siblings:** Phase 9, 11.

**Success criteria:**
- Abort fires on predicate true; transitions to re-planned first
  programme
- Veto window respected (impingement arrives within 5 s; abort
  cancelled)
- Re-plan preserves programme-authorship invariant (plan.plan_author
  still `hapax-director-planner`)
- **Grounding-expansion:** abort predicates are EVALUATED by
  registered callables; no hardcoded "at t+Xs, abort" exists. A test
  pinned the predicate registry as the only source of abort decisions.
- `uv run pytest tests/programme_manager/test_abort_evaluator.py -q`
  passes (>=15 tests)

**Test strategy:** Mocked perceptual snapshots for each registered
predicate; veto window timing test; re-plan integration test.

**Estimated LOC:** 350-550 module + 300 tests. Size: M.

**Commit message template:**

```
feat(programme): abort evaluator + re-plan

Registered abort predicates (operator_left_room_for_10min,
impingement_pressure_above_0.8_for_3min, consent_contract_expired,
vinyl_side_a_finished, operator_voice_contradicts_programme_intent)
fire an abort; the planner re-runs to rewrite remaining programmes;
5-second operator veto window respected.

Phase 10 of the programme-layer plan. Per research §4.4 + §6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

#### Phase 11: Integration with homage B3 — choreographer rotation_mode unlocked

**Scope:**
- Audit the homage-plan B3 phase's landed state — specifically, the
  choreographer startup-entry dispatch path
- `agents/studio_compositor/homage/choreographer.py` — confirm the
  rotation_mode selector now safely consumes programme-provided
  rotation_mode priors. The homage plan's B3 phase kept the
  rotation-mode selection cautious to avoid the HOLD-hotfix corner;
  with a programme layer in place, rotations are more legible (every
  rotation has a programme-context reason) so the choreographer can
  rotate more aggressively
- Extend the choreographer's rotation-mode selection to read from
  `active_programme.constraints.homage_rotation_mode_priors` as a
  SOFT PRIOR weight — the structural director still picks the
  specific mode per tick; the programme biases which modes are
  likely
- Tests: `tests/studio_compositor/test_choreographer_programme_rotation.py`

**Description:** The homage plan's B3 un-bypassed the choreographer
FSM. B4 added `steady|deliberate|rapid|burst` rotation modes. This
phase integrates both with the programme layer: a programme can
express "I prefer `paused|deliberate` during this listening section"
as a soft prior, and the structural director's mode-selection LLM
reads that as a bias.

This phase is explicitly a grounding-expansion move: it OPENS the
space of safe rotation-mode choices (previously constrained by the
HOLD-hotfix corner) because the programme layer gives every rotation
a legible reason. The choreographer isn't choosing rotations in a
vacuum; it's choosing rotations in service of a named, active
programme.

**Blocking dependencies:** Phase 1, 5 (structural director), 7
(transition choreographer). Also needs the homage plan's B3 + B4 to
be merged.

**Parallel-safe siblings:** Phase 9, 10.

**Success criteria:**
- Structural director emits rotation modes biased toward programme's
  priors (e.g., `paused` or `deliberate` chosen ~75% during a
  `LISTENING` programme)
- Out-of-prior rotation modes still possible under high impingement
  pressure (~20% for listening)
- No regression on the HOLD-hotfix corner — wards still advance
  through the FSM; startup dispatch still fires
- **Grounding-expansion:** the rotation-mode catalog is
  ADDITIVE under programme — programmes don't forbid modes; they
  bias. Test: pathological listening programme (every non-listening
  mode strongly biased negative) can still emit a `burst` mode
  under very high impingement pressure.
- `uv run pytest
  tests/studio_compositor/test_choreographer_programme_rotation.py
  -q` passes (>=12 tests)

**Test strategy:** Replay-based test with mocked structural director
LLM — feed fixture impingement contexts under various programmes,
assert mode distribution matches expected biases.

**Estimated LOC:** 200-350 module + 250 tests. Size: M.

**Commit message template:**

```
feat(programme): choreographer rotation_mode — programme-biased priors

Extends the homage-plan B4 rotation-mode selection with programme-
provided priors. Choreographer remains un-bypassed (B3); rotation-mode
catalog remains ADDITIVE under programme (no forbidden modes).

Phase 11 of the programme-layer plan. Per research §5.6 and integrates
with homage plan B3 + B4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

#### Phase 12: End-to-end acceptance — 30-min 3-programme stream

**Scope:**
- `scripts/run-programme-layer-acceptance.sh` — operator-runnable
  acceptance harness
- `docs/runbooks/programme-layer-acceptance.md` — operator walkthrough
  checklist (mirror of the homage Phase 10 rehearsal runbook, scoped
  to programmes)
- Integration test:
  `tests/integration/test_programme_layer_e2e.py` — a synthetic
  30-min replay that exercises three programmes, boundary transitions,
  metric emission, JSONL outcome log correctness, and the two
  invariant metrics

**Description:** Acceptance criteria operator walks (live with
`mpv v4l2:///dev/video42`, plus the synthetic test for CI):

1. Programme plan generated at show-start; visible in
   `~/hapax-state/programmes/<show_id>/plan.json`
2. First programme's surface reads as its role (listening →
   quiet, damped substrate; work-block → active, moderate substrate;
   wind-down → minimal activity, dim substrate)
3. Boundary transitions visible (exit ritual → boundary freeze →
   palette shift → entry ritual), each recruited via the pipeline
4. Per-programme soft-prior override counter is >0 (bias isn't
   hardening)
5. Candidate-set reduction counter is 0 (grounding-expansion holds)
6. JSONL outcome log contains full lifecycle events per programme
7. No line in any outcome log traces to a template string in a
   programme catalog (no scripted text leak)
8. Programme id stamped on every director-intent record during the
   stream (matches active programme via timestamp)

**Blocking dependencies:** ALL preceding phases (1-11).

**Parallel-safe siblings:** None (terminal acceptance).

**Success criteria:**
- Auto-checkable items: 100% pass (scripts/harness green)
- Operator VERIFY items: >=95% pass (operator may flag 1-2 cosmetic
  without blocking)
- Synthetic integration test runs to completion without invariant
  violations
- **Grounding-expansion (global):**
  `hapax_programme_candidate_set_reduction_total{*}` is strictly 0
  for the acceptance window
- **Soft-prior-not-hardening (global):**
  `hapax_programme_soft_prior_overridden_total{*}` is >0 per
  programme
- Operator signs off in the runbook: "programme layer live"

**Estimated LOC:** 200 script + 300 test + 100 runbook. Size: M.

**Commit message template:**

```
test(programme): end-to-end acceptance — 30min 3-programme stream

Harness + synthetic integration test exercising three programmes and
two boundaries. Invariant checks: candidate-set reduction strictly 0;
soft-prior override count strictly >0 per programme.

Phase 12 (terminal) of the programme-layer plan. Acceptance gate
before the programme layer is considered live.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## §3. DAG + critical path

### Dependency DAG

```
              BATCH 1 (no deps)
              Phase 1: Programme primitive

                      |
                      v
              BATCH 2 (need Phase 1)
              Phase 2: ProgrammePlanStore
              Phase 4: Affordance pipeline soft prior
              Phase 5: Structural director programme-aware
              Phase 8: Reverie palette per programme
              (Phase 5 also benefits from Phase 3 but mock-testable)

                      |
                      v
              BATCH 3 (need Phase 2)
              Phase 3: Hapax-authored planner
              Phase 6: CPAL threshold (needs Phase 4)
              Phase 9: Observability (needs Phases 2, 4, 7)

                      |
                      v
              BATCH 4 (need Phases 1, 2, 4, 5)
              Phase 7: Transition choreographer

                      |
                      v
              BATCH 5 (need Phases 3, 7)
              Phase 10: Abort evaluator + re-plan
              Phase 11: Choreographer rotation_mode integration
                        (also needs homage B3+B4 merged)

                      |
                      v
              TERMINAL
              Phase 12: E2E acceptance
```

### Critical path

Longest serial chain:

`Phase 1 → Phase 2 → Phase 3 → Phase 7 → Phase 10 → Phase 12`

With size estimates:

- Phase 1: M ~ 2 h
- Phase 2: M ~ 2 h
- Phase 3: L ~ 4 h (LLM prompt engineering is the long pole)
- Phase 7: L ~ 4 h (state machine complexity)
- Phase 10: M ~ 2.5 h
- Phase 12: M ~ 2 h

**Critical path floor: ~16-18 h serial.** With 3-4 concurrent
subagents in Batch 2 (Phase 4/5/8 alongside 2), and 2-3 in Batches 3+4
the floor compresses to **~10-12 h wall-clock** for plan-complete
state, plus operator-walked Phase 12 (~1 h).

Two-sentence critical path summary: The longest serial chain runs
Phase 1 → Phase 2 → Phase 3 → Phase 7 → Phase 10 → Phase 12, gated on
programme primitive → store → Hapax-authored planner → transition
choreographer → abort + re-plan → end-to-end acceptance. Parallel
execution of Phase 4/5/8 alongside Phase 2, and Phase 6/9 alongside
Phase 3/7, compresses the wall-clock from ~16 h serial to ~10-12 h
with 3-4 concurrent subagents.

---

## §4. Per-phase risk table

| Phase | Failure at 80% | Rollback | Detection |
|-------|---------------|----------|-----------|
| 1 | Envelope rename lands but downstream code still reads old names | Backward-compat aliases retained until Phase 4-11 migrate | Unit tests + pyright |
| 2 | Atomic rename races on tmpfs → partial plan.json | Retain backup on load failure; re-run planner | Tests + post-failure backup-load path |
| 3 | Planner LLM produces plans that always over-constrain (every capability biased negative near zero) | Validator rejects; planner retries with explicit soft-prior reminder | Integration test asserts candidate-set-reduction counter stays 0 |
| 4 | Bias composition breaks existing pipeline behaviour (scores drift across unrelated tests) | Phase 4 commit is revertible independently; pipeline falls back to programme-absent path | Existing pipeline tests fail loudly in CI |
| 5 | Structural director's prompt drifts toward hard-gate language | Regression pin on rendered prompt content catches it | Prompt-inspection test |
| 6 | CPAL F5 retirement accidentally drops speech surfacing | Integration test on speech-surface path; revert one file | Regression test; operator notices silence |
| 7 | Transition impingements too low-salience; rituals don't recruit | Bump salience floor; regression test on observed recruitment | Integration test + operator visual |
| 8 | Saturation target misses programme centre (always at default) | Revert substrate-writer change; fall back to A6 behaviour | `jq` check + visual |
| 9 | Metrics collide with homage C1 metric family | Namespace is `hapax_programme_*` (distinct from `hapax_homage_*`); no collision by construction | `curl /metrics` verification |
| 10 | Abort fires too aggressively; programmes churn | Per-predicate rate limits; 5s veto grace window | Operator can veto; metrics show abort rate |
| 11 | Rotation-mode bias contradicts B4 direct-selection; choreographer thrashes | Soft-prior weight capped; pathological bias caught by the additivity test | Operator visual + rotation-mode metric |
| 12 | Synthetic integration test passes but operator finds surface doesn't read as 3 sections | Diagnosis focuses on Phase 7 ritual recruitment; iterate Phase 7 impingement shapes | Operator walkthrough |

---

## §5. Branch / PR strategy

- **Branch:** `hotfix/fallback-layout-assignment` (continuing the
  tonight's branch). All phases commit directly. Do NOT create new
  branches per phase. Per-phase worktree isolation is forbidden (the
  subagent git safety rule in the workspace CLAUDE.md).
- **Per phase = one PR.** Hard requirement. Tonight's 30-commit PR
  was painful to review; each programme-layer phase gets its own
  squash-merge PR. Delta opens the PR, operator reviews light-touch,
  delta merges when CI green.
- **PR template (per phase):**

  ```
  ## Phase <N>: <name>

  Per docs/superpowers/plans/2026-04-20-programme-layer-plan.md §2 Phase <N>.

  ## Changes
  - <bullet list of file changes>

  ## Grounding-expansion assertion
  - <the per-phase assertion from the success criteria>

  ## Hapax-authored assertion (if applicable)
  - <the programme-authorship constraint invariant from success criteria>

  ## Test plan
  - [ ] `uv run pytest <paths> -q`
  - [ ] `uv run ruff check <paths>`
  - [ ] `uv run pyright <paths>` (for type-load-bearing phases)
  - [ ] Integration: <if any>
  ```

- **Merge order:** Phase 1 first (all downstream depends on it).
  Phase 2-4-5-8 parallel after 1. Phase 3 after 2. Phase 6 after 4.
  Phase 7 after 1-2-4-5. Phase 9-10-11 after 7. Phase 12 terminal.
- **CI gate:** every phase's PR must pass CI (ruff, pytest, pyright
  for phases that touch types). Delta does NOT merge on red.
- **Rebase hygiene:** after each merge to `hotfix/fallback-layout-
  assignment`, running subagents should `git pull --rebase origin
  hotfix/fallback-layout-assignment` before their commit. The scope
  of each phase is narrow enough that conflicts are rare (12 phases
  touching largely non-overlapping files); when conflicts appear
  they are usually in shared modules (`shared/programme.py`,
  `shared/compositional_affordances.py`) and the later-landing
  subagent resolves.
- **DO NOT:** force-push to main; rebase merged commits; skip CI;
  merge Phase 12 without the operator walkthrough; reintroduce hard
  gates under the soft-prior API surface.

---

## §6. Go-live acceptance checklist

Operator walks this in <15 min after Phase 12 lands + merges. Checklist
is designed so each item is PASS / FLAG / BLOCK.

### Surface observability (via `mpv v4l2:///dev/video42`)

1. [ ] During the listening programme, the surface reads as a listening
       section — substrate dim, ward emphasis sparse
2. [ ] During the work-block programme, the surface reads as a work
       section — camera on desk-work, substrate moderate
3. [ ] During the wind-down programme, the surface reads as a wind-down
       section — substrate minimal, captions visibly dimmer
4. [ ] Programme boundary 1 (listening → work-block) produces a visible
       transition: exit ritual → pause → palette shift → entry ritual
5. [ ] Programme boundary 2 (work-block → wind-down) produces a visible
       transition with distinct exit / entry rituals from boundary 1

### Artifact inspection (via `jq`, `ls`, `curl`)

6. [ ] `~/hapax-state/programmes/<show_id>/plan.json` exists and
       contains 3 programmes with Hapax author stamp
7. [ ] Each programme has its own JSONL outcome log in
       `~/hapax-state/programmes/<show_id>/<programme-id>.jsonl`
8. [ ] Director-intent records during each programme carry the
       programme_id (sample 5 per programme, inspect via `jq`)
9. [ ] `curl -s http://localhost:9482/metrics | grep
       hapax_programme_candidate_set_reduction_total` shows value 0
10. [ ] `curl -s http://localhost:9482/metrics | grep
        hapax_programme_soft_prior_overridden_total` shows value >0
        for each programme

### Architectural invariants

11. [ ] Plan author is `hapax-director-planner` in `plan.json`
12. [ ] Vault has no `type: programme` notes (grep confirms)
13. [ ] No file under
        `~/Documents/Personal/20-projects/hapax-research/programmes/`
        (directory does not exist)
14. [ ] JSONL outcome log utterances are unique strings (no line
        matches a programme definition template)
15. [ ] Programme transitions traced to ritual-scope impingements in
        director-intent.jsonl (not direct dispatch calls)

### Operational health

16. [ ] Grafana dashboard `programme-layer` loads; all 4 panels render
17. [ ] Abort predicate evaluator fired at most once during the stream
        (healthy stream; no churn)
18. [ ] If abort fired: re-plan completed within 30 s; operator had
        the 5s veto grace
19. [ ] `hapax_programme_active` gauge matches the programme visible
        at surface at any sampled timestamp

Sign-off: operator declares "programme layer live".

---

## §7. Notes for execution subagents

### Git safety (verbatim — non-negotiable)

Every dispatched execution subagent receives, in its prompt, the
following exact text:

> You are working in a shared directory
> (`/home/hapax/projects/hapax-council--cascade-2026-04-18`) on branch
> `hotfix/fallback-layout-assignment`. Do NOT create branches. Do NOT
> run `git checkout` or `git switch`. Commit directly to the current
> branch. Do NOT switch branches under any circumstances. Do NOT use
> `isolation: "worktree"` when dispatching further subagents.

After each dispatched subagent, delta verifies immediately:
`ls <expected_files> && git log --oneline -3`. If files are missing,
rewrite directly in the main session — the implementation is in the
conversation context.

### Rebase hygiene

Before beginning any phase, run:

```
cd /home/hapax/projects/hapax-council--cascade-2026-04-18
git pull --rebase origin hotfix/fallback-layout-assignment
```

If another phase has landed in the interim, your phase's conflicts
will most likely be in `shared/programme.py` (Phase 1 side effect)
or `shared/compositional_affordances.py` (Phase 4 side effect). In
both cases, accept the landed phase's version for non-overlapping
code and apply your phase's changes on top.

### Conflict guidance per module

- `shared/programme.py` — append-only after Phase 1 merges. Later
  phases don't modify the existing Pydantic classes; they add new
  fields if needed (and such additions should route through a Phase
  1 amendment PR, not a cross-phase edit).
- `shared/compositional_affordances.py` — only Phase 4 touches
  `AffordancePipeline.select`. If a later phase conflicts here, it's
  a scope violation — escalate to delta.
- `agents/programme_manager/` — Phase 2 creates the module;
  Phase 3, 7, 10 add sibling files. Avoid cross-file edits within
  `programme_manager/` in a single phase PR.
- `config/programme-layer/` — if a phase proposes a new config
  file, clear the path with delta first.

### Soft-prior-not-hardening discipline

Any phase that accepts or applies programme-envelope bias MUST:

1. Validate bias values are strictly positive (reject zero explicitly)
2. Emit `hapax_programme_candidate_set_reduction_total` observability
   (and verify it stays 0 in the phase's own tests)
3. Include at least one test that applies a strong negative bias AND
   a high-salience impingement, and asserts the capability recruits
   (soft prior, not gate)

If the subagent finds a case where a hard gate seems unavoidable (e.g.
a capability MUST be forbidden for legal / consent reasons during a
programme), that's NOT a programme responsibility — it's the
consent-gate or governance-veto responsibility, and the phase should
route through those existing mechanisms, not introduce a programme-
level hard gate.

### Hapax-authored discipline

Any phase touching programme authorship, planner inputs, or vault
integration MUST:

1. Read the vault via existing read-only helpers
   (`logos/data/vault_goals.py`, `vault_scan`, etc.)
2. Not create new vault write paths
3. Not define `type: programme` frontmatter anywhere
4. Not create `50-templates/tpl-programme.md` or equivalent
5. Validate `plan_author == "hapax-director-planner"` on any persisted
   plan

If the subagent finds itself writing a file under
`~/Documents/Personal/`, that's a scope violation — escalate to delta.

### LLM routing discipline

The programme planner (Phase 3), the abort-predicate LLM grader
(Phase 10's `operator_voice_contradicts_programme_intent`), and the
structural director prompt updates (Phase 5) ALL route through the
grounded tier (`balanced` / `coding`). Never route these to a "fast
but ungrounded" tier. Per
`feedback_grounding_exhaustive` — every move is grounded or
outsourced-by-grounding; programme planning is a grounding move at
the show scale.

If speed becomes an issue:

- Phase 3 (show-start latency): prompt compression via the existing
  `scripts/benchmark_prompt_compression_b6.py` harness; cache the
  perceptual snapshot; consider pre-generating the plan during
  previous day's wind-down (research doc §10 Q9). Never downgrade
  to ungrounded model.
- Phase 5 (per-tick cadence): add the programme context as a diff
  against the prior tick's prompt; leverage LiteLLM Redis response
  cache for perception snapshots that haven't changed. Never
  downgrade.
- Phase 10 (abort grade): pre-compute candidate abort-predicate
  summaries in the background at programme-start so the evaluation
  itself is a cheap comparison.

### Test discipline

Every phase's test suite MUST include:

1. At least one unit test per public function / method added
2. At least one integration test that exercises the phase's surface
   from the nearest consumer's perspective
3. The grounding-expansion assertion (phase-appropriate form)
4. The Hapax-authored assertion (if the phase touches planner/
   plan-store/plan-loader paths)

Phases 4, 6, 9 have the strongest grounding-expansion invariants;
their test suites must be especially thorough here.

### Escalation

If a subagent encounters scope ambiguity, architectural conflict,
or apparent bug in a previously-landed phase: DO NOT push through.
Report to delta with:

- The phase being worked on
- The observed issue
- The file paths involved
- Whether a workaround exists or rework is needed

Delta coordinates cross-phase fixes; no subagent should silently
patch a different phase's work.

---

**End of plan.**
