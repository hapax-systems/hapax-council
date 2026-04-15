# HSEA Phase 2 — Core Director Activities — Plan

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction per alpha's 06:20Z delegation of operator directive "activities extraction, always be working")
**Status:** DRAFT pre-staging — awaiting operator sign-off + cross-epic dependency resolution before Phase 2 open
**Spec reference:** `docs/superpowers/specs/2026-04-15-hsea-phase-2-core-director-activities-design.md`
**Branch target:** `feat/hsea-phase-2-core-director-activities`
**Cross-epic authority:** drop #62 §3 + §5 UP-10 + §10 Q3 ratification
**Unified phase mapping:** UP-10 Core Director Activities (~2,500 LOC, ~3 sessions)

---

## 0. Preconditions (MUST verify before task 1.1)

- [ ] **LRR UP-0 closed.**
- [ ] **LRR UP-1 (research registry) closed.** Deliverables depend on `research-marker.json` + `condition_id` tagging from LRR Phase 1.
- [ ] **HSEA UP-2 (Phase 0) closed.** All 6 Phase 0 deliverables merged. Verify `shared/prom_query.py`, `shared/governance_queue.py`, `shared/spawn_budget.py`, `scripts/promote-*.sh`, `axioms/precedents/hsea/management-governance-drafting-as-content.yaml.draft`, `~/.cache/hapax/relay/hsea-state.yaml` all exist.
- [ ] **LRR UP-9 (persona spec) closed.** `axioms/persona/hapax-livestream.yaml` exists and the persona prompt is wired into `agents/hapax_daimonion/persona.py`. If UP-9 is not closed, Phase 2 cannot ship because activity prompt construction references the persona.
- [ ] **HSEA UP-4 (Phase 1 visibility surfaces) closed** (preferred, not strict). Phase 2 can ship without UP-4 but activity prompts are unverifiable on-stream without the glass-box prompt renderer.
- [ ] **FDL-1 deployed to a running compositor.** Activities that write to `/dev/shm/hapax-compositor/` expect the compositor tmpfs to exist.
- [ ] **Drop #62 §10 Q3 ratification in place.** Confirmed 2026-04-15T05:35Z; deliverable 3.6 (`compose_drop`) designed as the base for Phase 4 narrator drafters.
- [ ] **Session claims the phase.** Write `~/.cache/hapax/relay/hsea-state.yaml::phase_statuses[2].status: open` + `current_phase: 2` + `current_phase_owner: <session>` + `current_phase_branch: feat/hsea-phase-2-core-director-activities`. Update `research-stream-state.yaml::unified_sequence[UP-10].status: open` + `owner: <session>`.

---

## 1. Deliverable 3.1 — Activity taxonomy extension

Ships FIRST. All other deliverables depend on the extended `ACTIVITY_CAPABILITIES` list.

### 1.1 Tests first (TDD)

- [ ] Create `tests/hapax_daimonion/test_activity_taxonomy.py`:
  - [ ] `test_all_13_activities_registered` — import `ACTIVITY_CAPABILITIES`; assert exactly 13 entries; assert all 7 new names are present
  - [ ] `test_each_activity_has_description` — assert each of 13 has a non-empty description string
  - [ ] `test_response_schema_accepts_new_fields` — construct `DirectorActivityResponse(activity="reflect", noticed=3, intend="test")` without validation error
  - [ ] `test_response_schema_rejects_unknown_activity` — `activity="nonexistent"` fails validation
  - [ ] `test_reactor_log_writer_handles_new_fields` — mock writer; pass a reflect response; assert JSONL entry has `noticed` + `intend` fields
  - [ ] `test_content_scheduler_recognizes_draft` — scheduler with activity="draft" triggers `DraftStreamCairoSource` activation (stub)
- [ ] Run: all fail (module extensions missing)

### 1.2 Implementation

- [ ] Locate `ACTIVITY_CAPABILITIES` — likely in `agents/hapax_daimonion/persona.py` or `director_loop.py` (verify at open time)
- [ ] Extend from 6 → 13 entries by adding: `draft`, `reflect`, `critique`, `patch`, `compose_drop`, `synthesize`, `exemplar_review`
- [ ] Each new entry has: `name`, `description` (persona-compatible, operator-facing text), `schema_extensions` (list of required fields per activity)
- [ ] Extend pydantic-ai response schema (`DirectorActivityResponse` or equivalent `output_type`):
  - [ ] `activity: Literal[<13 names>]`
  - [ ] Optional fields: `noticed: int | None`, `intend: str | None`, `draft_slug: str | None`, `patch_target: str | None`, `synthesis_sources: list[str] | None`, `exemplar_id: str | None`, `content: str | None`
  - [ ] Field validators: when `activity == "reflect"`, both `noticed` and `intend` must be non-null; analogous for other activities
- [ ] Extend reactor log writer to comprehend new fields (graceful null-handling on missing fields)
- [ ] Extend content scheduler to route activity types to their corresponding Cairo sources (even if the sources don't exist yet; stub the lookups)

### 1.3 Commit 3.1

- [ ] `uv run ruff check agents/hapax_daimonion/ tests/hapax_daimonion/test_activity_taxonomy.py`
- [ ] `uv run ruff format` same files
- [ ] `uv run pyright agents/hapax_daimonion/director_schema.py`
- [ ] `git add agents/hapax_daimonion/persona.py agents/hapax_daimonion/director_schema.py agents/hapax_daimonion/reactor_log_writer.py agents/hapax_daimonion/content_scheduler.py tests/hapax_daimonion/test_activity_taxonomy.py`
- [ ] `git commit -m "feat(hsea-phase-2): 3.1 activity taxonomy extension 6→13 + response schema"`
- [ ] Update `hsea-state.yaml::phase_statuses[2].deliverables[1].status: completed`

---

## 2. Deliverable 3.2 — `draft` activity + `DraftStreamCairoSource`

### 2.1 `draft` activity handler

- [ ] Create `tests/hapax_daimonion/test_activity_draft.py`:
  - [ ] `test_draft_extends_partial_buffer` — mock LLM returning 400 chars; assert partial file grows by 400 chars
  - [ ] `test_draft_creates_buffer_if_missing` — no partial file exists; first draft call creates it at `/dev/shm/.../draft-buffer/<slug>.partial.md`
  - [ ] `test_spawn_budget_denied_abort` — mock `SpawnBudgetLedger.check_can_spawn()` returning `allowed=False`; assert activity aborts with `budget_denied` logged and no LLM call made
  - [ ] `test_completion_threshold_writes_governance_entry` — mock partial at 2100 chars; assert `GovernanceQueue.append(type="research-drop", ...)` called once
  - [ ] `test_idempotent_governance_entry` — re-invoke after completion threshold already hit; assert second governance entry NOT appended (idempotency via `status_history` check)
  - [ ] `test_balanced_tier_used` — assert LLM route is `balanced` (not `fast` or `local-fast`)
  - [ ] `test_prompt_includes_exemplar` — mock prompt assembly; assert one of the existing `docs/research/` files is read as exemplar
- [ ] Create `agents/hapax_daimonion/activities/draft.py`:
  - [ ] `def run_draft(slug: str, condition_id: str | None) -> DirectorActivityResponse`
  - [ ] Read partial file or init
  - [ ] Spawn budget check → LLM call → append to partial → completion check → governance queue append
  - [ ] Return `DirectorActivityResponse(activity="draft", draft_slug=slug, ...)`

### 2.2 `DraftStreamCairoSource`

- [ ] Create `tests/studio_compositor/test_draft_stream_source.py`:
  - [ ] `test_render_empty_placeholder` — partial file absent; assert Cairo renders "composing..."
  - [ ] `test_character_reveal_rate_200_cps` — partial file has 1000 chars; mock time delta 5s; assert rendered char count ≈ 1000 (fully revealed)
  - [ ] `test_character_reveal_rate_stimmung_modulation` — intensity=0.2 (low) → ~80 cps; intensity=0.9 (high) → ~240 cps
  - [ ] `test_zone_registration` — assert source registers with `SourceRegistry` under `draft_stream` zone name
- [ ] Create `agents/studio_compositor/draft_stream_source.py`:
  - [ ] `class DraftStreamCairoSource(CairoSource)` with constructor taking a slug
  - [ ] `_read_partial()` — atomic read of the partial file
  - [ ] `render()` — character-by-character reveal modulated by stimmung intensity

### 2.3 Spawn budget configuration

- [ ] Add `draft_activity` entry to `config/spawn-budget-caps.yaml.example`:
  - [ ] `daily_usd: 0.50` (allows ~10 drafts/day at $0.05/call)
  - [ ] `max_concurrent: 1`
  - [ ] `tier: balanced`

### 2.4 Commit 3.2

- [ ] Lint + format + pyright
- [ ] `git add agents/hapax_daimonion/activities/draft.py agents/studio_compositor/draft_stream_source.py tests/hapax_daimonion/test_activity_draft.py tests/studio_compositor/test_draft_stream_source.py config/spawn-budget-caps.yaml.example`
- [ ] `git commit -m "feat(hsea-phase-2): 3.2 draft activity + DraftStreamCairoSource + spawn budget cap"`
- [ ] Update `hsea-state.yaml::phase_statuses[2].deliverables[2].status: completed`

---

## 3. Deliverable 3.6 — `compose_drop` activity + `ComposeDropActivity` class

Ships THIRD (before 3.3/3.4/3.7/3.8/3.9) because it's load-bearing for Phase 4 narrator drafters per drop #62 Q3 ratification.

### 3.1 `ComposeDropActivity` class

- [ ] Create `tests/hapax_daimonion/test_activity_compose_drop.py`:
  - [ ] `test_instantiation_with_findings_reader` — pass a stub `findings_reader` returning 3 fake findings; assert `ComposeDropActivity` constructs
  - [ ] `test_run_composes_drop` — invoke `.run()`; assert LLM called with a prompt containing all 3 findings; assert response has `draft_slug` set
  - [ ] `test_run_writes_to_draft_buffer` — after `.run()`, partial file at `/dev/shm/.../draft-buffer/<slug>.partial.md` exists with the composed content
  - [ ] `test_run_writes_governance_entry` — assert `GovernanceQueue.append(type="research-drop", ...)` called
  - [ ] `test_run_spawn_budget_gated` — mock budget denied; assert no LLM call, no partial file created
  - [ ] `test_promote_moves_partial_to_final` — mock operator-approved state; call `.promote()`; assert partial moved to `docs/research/<date>-<slug>.md` (via `promote-drop.sh` subprocess)
  - [ ] `test_narrator_base_composition` — sub-class `ComposeDropActivity` with a custom findings_reader that watches a specific directory; assert the subclass works without re-implementing the core compose logic
- [ ] Create `agents/hapax_daimonion/activities/compose_drop.py`:
  - [ ] `class ComposeDropActivity`:
    - [ ] `__init__(self, findings_reader: Callable[[], list[dict]], drop_slug: str, exemplar_path: Path, tier: ModelTier = "balanced")`
    - [ ] `def run(self) -> DirectorActivityResponse` — spawn budget check → read findings → LLM synthesis → write partial → governance queue append
    - [ ] `def promote(self) -> None` — subprocess call to `scripts/promote-drop.sh <slug>`
  - [ ] Public-API: class is exported from the module top-level for Phase 4 narrator drafters to compose

### 3.2 Spawn budget configuration

- [ ] Add `compose_drop_activity` entry to caps YAML:
  - [ ] `daily_usd: 1.00` (allows ~10 composes/day at $0.10/call, higher than draft because synthesis prompts are larger)
  - [ ] `max_concurrent: 1`
  - [ ] `tier: balanced`

### 3.3 Commit 3.6

- [ ] Lint + format + pyright
- [ ] `git add agents/hapax_daimonion/activities/compose_drop.py tests/hapax_daimonion/test_activity_compose_drop.py config/spawn-budget-caps.yaml.example`
- [ ] `git commit -m "feat(hsea-phase-2): 3.6 compose_drop activity + ComposeDropActivity narrator base class"`
- [ ] Update `hsea-state.yaml::phase_statuses[2].deliverables[6].status: completed`
- [ ] **Export verification:** `python -c "from agents.hapax_daimonion.activities.compose_drop import ComposeDropActivity; print(ComposeDropActivity.__module__)"` succeeds — proves Phase 4 narrator drafters can import the base class

---

## 4. Deliverable 3.7 — `synthesize` activity + `SynthesisBannerSource`

### 4.1 `synthesize` activity handler

- [ ] Create `tests/hapax_daimonion/test_activity_synthesize.py`:
  - [ ] `test_synthesize_produces_30_word_output` — mock LLM returning 32 words; accept (tolerance ±20%)
  - [ ] `test_synthesize_rejects_long_output` — mock LLM returning 100 words; reject and re-roll (up to 2 retries then abort)
  - [ ] `test_synthesize_writes_banner_json` — after successful run, `/dev/shm/hapax-compositor/synthesis.json` exists with content + timestamp
  - [ ] `test_synthesize_includes_all_sources` — assert response.synthesis_sources lists all input agents
- [ ] Create `agents/hapax_daimonion/activities/synthesize.py`:
  - [ ] `def run_synthesize(sources: list[str], source_findings: list[dict]) -> DirectorActivityResponse`
  - [ ] `fast` tier LLM call (cheapest)
  - [ ] Output atomic-write to `/dev/shm/hapax-compositor/synthesis.json`

### 4.2 `SynthesisBannerSource`

- [ ] Create `tests/studio_compositor/test_synthesis_banner_source.py`:
  - [ ] `test_banner_shows_synthesis` — fixture synthesis.json; assert banner renders the content
  - [ ] `test_banner_fades_after_5s` — fixture synthesis.json with timestamp 6s ago; assert banner opacity is 0 (faded out)
  - [ ] `test_banner_absent_when_no_json` — no synthesis.json; assert no render
- [ ] Create `agents/studio_compositor/synthesis_banner_source.py`:
  - [ ] `class SynthesisBannerSource(CairoSource)`:
    - [ ] Reads `/dev/shm/hapax-compositor/synthesis.json` on each render
    - [ ] Displays content for 3-5 seconds then fades; fade is opacity-based
    - [ ] Zone: top-content banner

### 4.3 Commit 3.7

- [ ] Lint + format + pyright
- [ ] `git add agents/hapax_daimonion/activities/synthesize.py agents/studio_compositor/synthesis_banner_source.py tests/hapax_daimonion/test_activity_synthesize.py tests/studio_compositor/test_synthesis_banner_source.py config/spawn-budget-caps.yaml.example`
- [ ] `git commit -m "feat(hsea-phase-2): 3.7 synthesize activity + SynthesisBannerSource"`
- [ ] Update `hsea-state.yaml::phase_statuses[2].deliverables[7].status: completed`

---

## 5. Deliverable 3.8 — `ReflectiveMomentScorer` gate + calibration

Ships FIFTH because deliverables 3.3 (reflect) and 3.4 (critique) are GATED by this scorer; they cannot ship until the scorer exists.

### 5.1 Tests

- [ ] Create `tests/hapax_daimonion/test_reflective_moment_scorer.py`:
  - [ ] `test_score_formula` — fixture with known pattern_density, stance_specificity, etc.; assert score matches `0.3*pd + 0.25*ss + 0.2*tsr + 0.15*cq + 0.1*ccr`
  - [ ] `test_threshold_gate` — score > 0.65 returns `should_reflect=True`; score < 0.65 returns False
  - [ ] `test_cooldown_floor_12_ticks` — fire once; assert next 11 ticks return False regardless of score; tick 12 eligible
  - [ ] `test_enabled_flag_false_always_false` — when `enabled=False`, always returns False even with high score
  - [ ] `test_metrics_emitted_during_calibration` — scorer with `enabled=False`; assert Prometheus counter `hapax_reflective_moment_score` histogram increments per call
  - [ ] `test_component_gauges_emitted` — each component (pattern_density, stance_specificity, etc.) emitted as separate Prometheus gauge
- [ ] Create `agents/hapax_daimonion/reflective_moment_scorer.py`:
  - [ ] `class ReflectiveMomentScorer`:
    - [ ] `__init__(self, threshold: float = 0.65, cooldown_ticks: int = 12, enabled: bool = False)`
    - [ ] `def score(self, state: DirectorState) -> ScoreResult` — computes the 5-component score, emits metrics
    - [ ] `def should_reflect(self, state: DirectorState) -> bool` — applies threshold + cooldown + enabled flag
    - [ ] Prometheus metrics: `hapax_reflective_moment_score` histogram + 5 component gauges
  - [ ] `@dataclass class ScoreResult(value, components, should_reflect, disabled)`

### 5.2 Calibration protocol doc

- [ ] Create `research/protocols/reflective-moment-calibration.md`:
  - [ ] Purpose: 7-day wall-clock observation window to empirically tune the threshold
  - [ ] Protocol:
    - [ ] Day 0: ship scorer with `enabled=False`
    - [ ] Days 1-7: metrics collection via Prometheus
    - [ ] Day 7: analyze histogram; compute frequency of score > 0.65
    - [ ] Target: ~1 in 20 ticks (~5%) per drop #59 Finding
    - [ ] Tune threshold down if empirical frequency < 3%; tune up if > 8%
    - [ ] Enable gating via config flip
  - [ ] Analysis template: SQL/PromQL queries that compute the empirical distribution
  - [ ] Risk: the empirical target may not match 5% — document the tuning decision + rationale in this file

### 5.3 Commit 3.8

- [ ] Lint + format + pyright
- [ ] `git add agents/hapax_daimonion/reflective_moment_scorer.py tests/hapax_daimonion/test_reflective_moment_scorer.py research/protocols/reflective-moment-calibration.md`
- [ ] `git commit -m "feat(hsea-phase-2): 3.8 ReflectiveMomentScorer + 7-day calibration protocol"`
- [ ] Update `hsea-state.yaml::phase_statuses[2].deliverables[8].status: completed`
- [ ] **Calibration start:** document the current UTC time as Day 0; schedule the Day 7 analysis task in the operator's calendar OR file a task in the governance queue

---

## 6. Deliverable 3.3 — `reflect` activity

Ships SIXTH. Depends on 3.8 scorer existing.

### 6.1 Tests

- [ ] Create `tests/hapax_daimonion/test_activity_reflect.py`:
  - [ ] `test_reflect_enumerates_last_8_reactions` — fixture reactor log; assert prompt contains numbered reactions 1-8
  - [ ] `test_reflect_requires_noticed_index` — mock LLM returning response without `noticed`; assert re-roll (up to 3 retries)
  - [ ] `test_reflect_rejects_noticed_out_of_range` — mock response with `noticed=15`; assert re-roll
  - [ ] `test_reflect_writes_reactor_log_entry` — successful run; assert reactor log has new entry with `noticed` + `intend`
  - [ ] `test_reflect_blocked_by_scorer_disabled` — scorer with `enabled=False`; reflect activity refuses to run
  - [ ] `test_reflect_blocked_by_cooldown` — scorer on cooldown; reflect refuses
  - [ ] `test_reflect_spawn_budget_denied` — budget denied; activity aborts
- [ ] Create `agents/hapax_daimonion/activities/reflect.py`:
  - [ ] `def run_reflect(state: DirectorState, scorer: ReflectiveMomentScorer) -> DirectorActivityResponse | None`
  - [ ] Gating: check scorer.should_reflect() first; return None if gated
  - [ ] Spawn budget check
  - [ ] LLM call with enumerated reaction context
  - [ ] Re-roll loop (max 3) on anti-slop rejection
  - [ ] Return response or None on exhaustion

### 6.2 Commit 3.3

- [ ] Lint + format + pyright
- [ ] `git add agents/hapax_daimonion/activities/reflect.py tests/hapax_daimonion/test_activity_reflect.py config/spawn-budget-caps.yaml.example`
- [ ] `git commit -m "feat(hsea-phase-2): 3.3 reflect activity + anti-slop re-roll"`
- [ ] Update `hsea-state.yaml::phase_statuses[2].deliverables[3].status: completed`

---

## 7. Deliverable 3.4 — `critique` activity

Ships SEVENTH. Same dependency on 3.8 scorer.

### 7.1 Tests

- [ ] Create `tests/hapax_daimonion/test_activity_critique.py`:
  - [ ] `test_critique_reads_last_10_reactions`
  - [ ] `test_critique_requires_concrete_pattern_name` — mock LLM returning generic "I was repetitive"; assert re-roll
  - [ ] `test_critique_accepts_specific_pattern` — mock LLM returning "reliance on metaphor 'ocean' in 4 of 10 reactions"; assert accepted
  - [ ] `test_critique_writes_noticed_and_intend` — reactor log has both fields
  - [ ] `test_critique_gated_by_scorer`
- [ ] Create `agents/hapax_daimonion/activities/critique.py`:
  - [ ] Similar structure to reflect but reads 10 reactions and requires concrete pattern naming
  - [ ] Same gating + re-roll logic

### 7.2 Commit 3.4

- [ ] Lint + format + pyright
- [ ] `git add agents/hapax_daimonion/activities/critique.py tests/hapax_daimonion/test_activity_critique.py config/spawn-budget-caps.yaml.example`
- [ ] `git commit -m "feat(hsea-phase-2): 3.4 critique activity + concrete pattern naming constraint"`
- [ ] Update `hsea-state.yaml::phase_statuses[2].deliverables[4].status: completed`

---

## 8. Deliverable 3.9 — `exemplar_review` activity

Ships EIGHTH. Independent of other deliverables but lower priority.

### 8.1 Tests

- [ ] Create `tests/hapax_daimonion/test_activity_exemplar_review.py`:
  - [ ] `test_empty_exemplars_yaml_graceful` — `shared/exemplars.yaml` contains `exemplars: []`; activity returns no-op response; no error
  - [ ] `test_one_exemplar_compared` — fixture with 1 exemplar; activity reads own recent output + compares; response has `exemplar_id`
  - [ ] `test_missing_exemplars_file_graceful` — file doesn't exist; activity returns no-op
  - [ ] `test_spawn_budget_denied`
- [ ] Create `agents/hapax_daimonion/activities/exemplar_review.py`:
  - [ ] Read `shared/exemplars.yaml` via `yaml.safe_load`
  - [ ] If `exemplars` list is empty or file missing: return no-op response
  - [ ] Otherwise: pick a recent own output, pick an exemplar, LLM call to compare, return response

### 8.2 Commit 3.9

- [ ] Lint + format + pyright
- [ ] `git add agents/hapax_daimonion/activities/exemplar_review.py tests/hapax_daimonion/test_activity_exemplar_review.py config/spawn-budget-caps.yaml.example`
- [ ] `git commit -m "feat(hsea-phase-2): 3.9 exemplar_review activity + graceful empty-pool handling"`
- [ ] Update `hsea-state.yaml::phase_statuses[2].deliverables[9].status: completed`

---

## 9. Deliverable 3.5 — `patch` stub

Ships LAST. Trivial stub.

### 9.1 Stub + test

- [ ] Create `tests/hapax_daimonion/test_activity_patch_stub.py`:
  - [ ] `test_patch_stub_returns_no_op` — call `run_patch()`; assert response.activity == "patch" + response.patch_target is None + response.notes contains "no patches available"
  - [ ] `test_patch_stub_registered_in_taxonomy` — assert `ACTIVITY_CAPABILITIES` has `patch` entry (should already be present from 3.1)
- [ ] Create `agents/hapax_daimonion/activities/patch.py`:
  - [ ] `def run_patch() -> DirectorActivityResponse`:
    - [ ] Returns `DirectorActivityResponse(activity="patch", patch_target=None, notes="no patches available (stub; full impl lands in HSEA Phase 4)")`
  - [ ] No LLM call. No spawn budget check needed (no cost). No governance queue write.

### 9.2 Commit 3.5

- [ ] Lint + format
- [ ] `git add agents/hapax_daimonion/activities/patch.py tests/hapax_daimonion/test_activity_patch_stub.py`
- [ ] `git commit -m "feat(hsea-phase-2): 3.5 patch activity stub (full impl deferred to Phase 4)"`
- [ ] Update `hsea-state.yaml::phase_statuses[2].deliverables[5].status: completed`

---

## 10. Phase 2 close

All 9 deliverables complete. Final steps:

### 10.1 Smoke tests (matching spec §5 exit criteria)

- [ ] **Taxonomy extension verified:** `ACTIVITY_CAPABILITIES` has 13 entries; unit test passes
- [ ] **Each activity dispatches successfully** against a mocked LLM (fast acceptance test)
- [ ] **Director loop production run** for 5 minutes shows at least 3 distinct activity types in reactor log (including at least one Phase 2 activity)
- [ ] **Reactor log schema** — `jq '.activity' reactor-log-*.jsonl | sort -u` shows new types; entries have `noticed` + `intend` where applicable
- [ ] **ReflectiveMomentScorer metrics** — Prometheus shows `hapax_reflective_moment_score` histogram with non-zero counts; `enabled=False` still
- [ ] **Calibration protocol doc exists** at `research/protocols/reflective-moment-calibration.md`
- [ ] **Phase 4 dry-run:** construct a stub narrator drafter that composes `ComposeDropActivity` with a trivial findings_reader; verify it runs under Phase 2's infrastructure end-to-end
- [ ] **Spawn budget entries** in caps YAML for all 7 new touch points
- [ ] **DraftStreamCairoSource + SynthesisBannerSource** registered via SourceRegistry; visible in production compositor during smoke test
- [ ] **Governance queue integration:** successful draft or compose_drop run results in a new governance queue entry visible via `GovernanceQueue.pending()`

### 10.2 Handoff doc

- [ ] Write `docs/superpowers/handoff/2026-04-15-hsea-phase-2-complete.md`:
  - [ ] 9 deliverables shipped
  - [ ] PR/commit links
  - [ ] Phase 4 dry-run compatibility verification evidence
  - [ ] Calibration window start timestamp + tuning schedule
  - [ ] Known issues: any anti-slop rejection rates observed during testing
  - [ ] Next phase (HSEA Phase 3 Cluster C or HSEA Phase 4 Cluster I) preconditions

### 10.3 State file close-out

- [ ] `~/.cache/hapax/relay/hsea-state.yaml::phase_statuses[2].status: closed` + `closed_at` + `handoff_path`
- [ ] `deliverables[1..9].status: completed` (all 9)
- [ ] `last_completed_phase: 2`
- [ ] Request operator update to `unified_sequence[UP-10].status: closed` via governance-queue request

### 10.4 Final verification

- [ ] 9+ `feat(hsea-phase-2): …` commits in `git log --oneline`
- [ ] All 14 spec exit criteria pass
- [ ] Fresh shell shows `HSEA: Phase 2 · status=closed` in session-context
- [ ] Inflection to peers: Phase 2 closed; Phase 4 narrator base available; calibration window underway

---

## 11. Cross-epic coordination (canonical references)

- **LRR Phase 1 (research registry)** provides `research_marker.read_marker()` + condition_id → consumed by reactor log writer extension in 3.1 + every activity for Langfuse tagging.
- **LRR Phase 7 (persona)** provides `axioms/persona/hapax-livestream.yaml` → consumed by every activity's prompt construction via the persona module.
- **HSEA Phase 0 (foundation primitives)** provides `shared/governance_queue.py` (3.2 + 3.6 write drafts to it), `shared/spawn_budget.py` (every activity gates through it), `shared/prom_query.py` (not directly used by Phase 2 activities but used by HSEA Phase 1 surfaces that Phase 2 writes to).
- **HSEA Phase 1 (visibility surfaces)** provides `SourceRegistry` pattern for DraftStream + SynthesisBanner + glass-box prompt rendering for on-stream verification.
- **HSEA Phase 4 (Cluster I narrator drafters)** composes `ComposeDropActivity` from deliverable 3.6. Phase 2 exports the class as a public API; Phase 4 narrators construct instances.
- **Drop #62 §10 Q3 ratification** confirms I1-I5 are narration-only, making 3.6 load-bearing for Phase 4 execution.

---

## 12. End

This is the standalone per-phase plan for HSEA Phase 2. It is pre-staging — the plan is not executed until the phase opens per §0 preconditions. Companion spec at `docs/superpowers/specs/2026-04-15-hsea-phase-2-core-director-activities-design.md`.

Pre-staging authored by delta per alpha's 06:20Z delegation of the operator directive "activities extraction, always be working" (2026-04-15).

— delta, 2026-04-15
