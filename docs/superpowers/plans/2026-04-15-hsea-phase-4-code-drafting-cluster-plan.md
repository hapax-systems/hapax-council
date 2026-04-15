# HSEA Phase 4 — Code Drafting Cluster (Cluster I, Rescoped) — Plan

**Date:** 2026-04-15
**Spec reference:** `docs/superpowers/specs/2026-04-15-hsea-phase-4-code-drafting-cluster-design.md`
**Branch target:** `feat/hsea-phase-4-code-drafting-cluster`
**Unified phase mapping:** UP-12 parallelizable cluster basket (~1,100 LOC post-rescoping)

---

## 0. Preconditions

- [ ] LRR UP-0 + UP-1 closed (research registry + `check-frozen-files.py --probe` live)
- [ ] LRR UP-7 (substrate swap) closed — **NOTE per drop #62 §14**: operator has ratified a substrate replacement for Hermes; Phase 4 cannot open until the substrate is chosen + LRR Phase 5 (or equivalent) has shipped the swap
- [ ] HSEA UP-2 (Phase 0) closed — governance queue, spawn budget, promote-patch.sh stub, axiom precedent draft
- [ ] HSEA UP-4 (Phase 1) closed — SourceRegistry + Sierpinski slot infrastructure for diff streaming
- [ ] HSEA UP-10 (Phase 2) closed — `ComposeDropActivity` public API for narrator drafters + `patch` activity stub to replace
- [ ] LRR UP-11 closed (LRR Phase 9 closed-loop wiring) for I2/I3 narrator targets
- [ ] Operator decision made on I4/I5 reframing (§14 option A/B/C per spec §7 Q1)
- [ ] Session claims phase: `hsea-state.yaml::phase_statuses[4].status: open`

---

## 1. Deliverable 4.1 — Base code drafter

### 1.1 Pydantic-ai agent base

- [ ] Create `tests/code_drafter/test_base.py`:
  - [ ] `test_code_patch_schema_valid` — construct `CodePatch(files=[FileDiff(...)], test_plan="...", rationale="...", risk_assessment="...", risk_factors=[], rollback_plan="...", blocked_by=[], unblocks=[])`
  - [ ] `test_drafter_deps_required_fields`
  - [ ] `test_build_agent_balanced_tier` — factory returns agent with `balanced` model
  - [ ] `test_build_agent_capable_tier` — factory returns agent with `capable` (Opus) model
  - [ ] `test_system_prompt_contains_destructive_regex_constraint` — prompt includes the NEVER-write list
  - [ ] `test_system_prompt_contains_frozen_files_awareness`
- [ ] Create `agents/code_drafter/__init__.py`:
  - [ ] Pydantic-ai agent with `output_type=CodePatch`
  - [ ] `build_agent(tier: Literal["balanced", "capable"]) -> Agent[DrafterDeps, CodePatch]`
  - [ ] System prompt assembled from CLAUDE.md + pyproject.toml + the NEVER-write list
- [ ] Create `agents/code_drafter/_schema.py`:
  - [ ] `class FileDiff(BaseModel)`: path, diff, operation (add/modify/delete)
  - [ ] `class CodePatch(BaseModel)`: files, test_plan, rationale, risk_assessment, risk_factors, rollback_plan, blocked_by, unblocks
  - [ ] `class DrafterDeps(BaseModel)`: target_task, source_files, conventions, frozen_file_list, line_cap

### 1.2 Capable tier alias

- [ ] Edit `shared/config.py`: add `capable → claude-opus-4-6` to the model alias dict
- [ ] Edit `agents/_config.py`: same
- [ ] Regression test: `get_model("capable")` returns the Opus model

### 1.3 Commit 4.1

- [ ] Lint + format + pyright
- [ ] `git add agents/code_drafter/__init__.py agents/code_drafter/_schema.py shared/config.py agents/_config.py tests/code_drafter/test_base.py`
- [ ] `git commit -m "feat(hsea-phase-4): 4.1 base code drafter + capable tier alias"`

---

## 2. Deliverable 4.2 — Staging infrastructure

### 2.1 Staging + gates + escalation + diff + conventions

- [ ] Create `tests/code_drafter/test_staging.py` + `test_gates.py` + `test_escalation.py`:
  - [ ] `test_stage_patch_atomic_write` — `stage_patch()` writes to `<ulid>` subdir with metadata
  - [ ] `test_run_gates_destructive_regex` — reject `git reset --hard` in any file diff
  - [ ] `test_run_gates_line_cap_exceeded`
  - [ ] `test_run_gates_frozen_files_probe_calls_subprocess` — verify `check-frozen-files.py --probe` is invoked
  - [ ] `test_escalation_to_capable_on_gate_failure`
  - [ ] `test_opus_rate_limit_enforced` — 4th Opus call in a day returns `rate_limited` error
  - [ ] `test_diff_parse` — parse unified diff format
  - [ ] `test_conventions_enforced` — snake_case, type hints, pydantic-ai output_type usage
- [ ] Create `agents/code_drafter/_staging.py`, `_gates.py`, `_escalation.py`, `_diff.py`, `_conventions.py` per spec §3.2

### 2.2 Config files

- [ ] Create `config/code_drafter.yaml`:
  - [ ] `line_caps`: per-task line caps (I6=200, I7=500, I1-I5=150-300)
  - [ ] `gate_thresholds`: ruff/pytest/frozen-files failure tolerance
  - [ ] `opus_rate_limit: 3` (daily cap)

### 2.3 Commit 4.2

- [ ] `git add agents/code_drafter/_*.py config/code_drafter.yaml tests/code_drafter/test_*.py`
- [ ] `git commit -m "feat(hsea-phase-4): 4.2 staging infrastructure + gates + escalation + Opus rate limiter"`

---

## 3. Deliverable 4.4 — promote-patch.sh + reject-patch.sh

### 3.1 promote-patch.sh (extend HSEA Phase 0 0.4 stub)

- [ ] Replace the Phase 0 stub with the full implementation:
  - [ ] Re-run gates (ruff + pytest + frozen-files + destructive regex)
  - [ ] `git apply` + commit with Claude-attributed message
  - [ ] Optional `--pr` flag: `gh pr create --draft`
- [ ] Extend `tests/scripts/test_promote_patch.bats` with real-patch fixtures

### 3.2 reject-patch.sh (new)

- [ ] Archive to `~/hapax-state/staged-patches/archive/<ulid>/`
- [ ] Write rejection reason file
- [ ] Update governance queue entry via `GovernanceQueue.update_status(id, "rejected", ...)`
- [ ] Tests: `tests/scripts/test_reject_patch.bats`

### 3.3 Commit 4.4

- [ ] `git add scripts/promote-patch.sh scripts/reject-patch.sh tests/scripts/test_promote_patch.bats tests/scripts/test_reject_patch.bats`
- [ ] `git commit -m "feat(hsea-phase-4): 4.4 promote-patch full impl + reject-patch.sh"`

---

## 4. Deliverable 4.6 — code_review.py integration

### 4.1 code_reviewer agent

- [ ] Create `tests/code_reviewer/test_review.py`:
  - [ ] `test_review_agent_runs` — invoke with a fixture CodePatch; returns review notes
  - [ ] `test_review_surfaces_known_pitfalls` — fixture patch with a common antipattern; review notes mention it
  - [ ] `test_review_writes_notes_file` — review_notes.md created in staging dir
- [ ] Create `agents/code_reviewer/__init__.py`:
  - [ ] Pydantic-ai agent separate from `code_drafter`
  - [ ] `output_type=ReviewNotes(findings, severity, recommendations)`
  - [ ] System prompt from `_prompts.py`
- [ ] Create `agents/code_reviewer/_prompts.py` with review prompt templates

### 4.2 Integration into staging flow

- [ ] Edit `agents/code_drafter/_staging.py`: after `stage_patch()` succeeds + `run_gates()` passes, invoke `code_reviewer.agent.run(patch)` + write to `review_notes.md` in the staging dir
- [ ] Review happens BEFORE governance queue entry write — operator sees the review when they first look at the queue entry

### 4.3 Commit 4.6

- [ ] `git add agents/code_reviewer/ tests/code_reviewer/ agents/code_drafter/_staging.py`
- [ ] `git commit -m "feat(hsea-phase-4): 4.6 code_reviewer agent + mandatory review in staging flow"`

---

## 5. Deliverable 4.5 — Director `patch` activity full implementation

### 5.1 Full patch activity

- [ ] Create `tests/hapax_daimonion/test_activity_patch_full.py`:
  - [ ] `test_patch_selects_from_priorities_yaml` — fixture priorities file; assert task selection
  - [ ] `test_patch_invokes_drafter_subprocess` — mock subprocess; verify drafter is called
  - [ ] `test_patch_streams_diff_to_sierpinski` — verify Sierpinski slot writes
  - [ ] `test_patch_narrates_milestones` — verify daimonion narration at salience 0.45
  - [ ] `test_patch_approval_inotify` — mock governance queue status flip → `approved`; assert re-narration with SHA
- [ ] Replace `agents/hapax_daimonion/activities/patch.py` stub from HSEA Phase 2 3.5 with the full implementation:
  - [ ] Read `config/patch_priorities.yaml`
  - [ ] Invoke `agents.code_drafter.build_agent(tier).run(...)` via subprocess
  - [ ] Stream diff text to `/dev/shm/hapax-compositor/patch-diff-stream.partial.md` (new Sierpinski slot)
  - [ ] Narrate milestones
  - [ ] Watch governance queue for approval
  - [ ] Re-narrate with commit SHA on approval

### 5.2 Config file

- [ ] Create `config/patch_priorities.yaml` — operator-editable priority list

### 5.3 Commit 4.5

- [ ] `git add agents/hapax_daimonion/activities/patch.py config/patch_priorities.yaml tests/hapax_daimonion/test_activity_patch_full.py`
- [ ] `git commit -m "feat(hsea-phase-4): 4.5 director patch activity full implementation (replaces Phase 2 3.5 stub)"`

---

## 6. Deliverable 4.3 — Sub-drafters (2 code-gen + 5 narrators)

Ship in order: I7 → I6 → I1/I2/I3 → I4/I5 (last; requires §14 reframing decision).

### 6.1 I7 — ritualized director states

- [ ] Test: fixture time-of-day; verify state transitions fire at Midnight/Wake/Crate/Last Call windows
- [ ] Create `agents/code_drafter/drafters/i7_ritualized_states.py` (extends base drafter)
- [ ] Create `agents/director_loop/_ritual_states.py` (NEW file — the target of the drafter)
- [ ] Commit: `feat(hsea-phase-4): 4.3 I7 ritualized director states drafter`

### 6.2 I6 — YouTube tee (conditional)

- [ ] Check frozen-files probe on `rtmp_output.py`; if frozen, demote I6 to narration-only per spec §3.3
- [ ] If not frozen: create `agents/code_drafter/drafters/i6_youtube_tee.py`
- [ ] If frozen: create narrator variant `agents/code_drafter/drafters/i6_youtube_tee_narrator.py` composing `ComposeDropActivity`
- [ ] Commit: `feat(hsea-phase-4): 4.3 I6 YouTube tee drafter (conditional code-gen or narration)`

### 6.3 I1 — PyMC 5 BEST narrator

- [ ] Test: fixture git log with PyMC BEST port commit; assert research drop cites the commit SHA
- [ ] Create `agents/code_drafter/drafters/i1_pymc5_best_narrator.py` composing `ComposeDropActivity`
- [ ] Findings_reader closure: watches LRR UP-1 commit log for `stats.py` BEST port commits
- [ ] Commit: `feat(hsea-phase-4): 4.3 I1 PyMC 5 BEST narrator drafter`

### 6.4 I2 — stimmung prior narrator

- [ ] Findings_reader: watches LRR UP-11 for stimmung-gated activity prior commits
- [ ] Commit: `feat(hsea-phase-4): 4.3 I2 stimmung prior narrator drafter`

### 6.5 I3 — burst cadence narrator

- [ ] Findings_reader: watches LRR UP-11 for burst/rest cadence + PERCEPTION_INTERVAL tuning commits
- [ ] Commit: `feat(hsea-phase-4): 4.3 I3 burst cadence narrator drafter`

### 6.6 I4 — substrate swap narrator (REFRAMED per drop #62 §14)

- [ ] **DECISION GATE:** read drop #62 §14 + check operator's current substrate decision
- [ ] If operator ratified "keep Qwen3.5-9B + production fixes" → I4 narrates "Hermes abandoned + production fixes landed"
- [ ] If operator ratified "parallel-deploy OLMo 3-7B" → I4 narrates "OLMo 3-7B deployment"
- [ ] If no decision yet: I4 is DEFERRED until decision lands
- [ ] Findings_reader closure tailored to the ratified direction
- [ ] Commit: `feat(hsea-phase-4): 4.3 I4 substrate transition narrator (post-§14 reframing)`

### 6.7 I5 — guardrail narrator (REFRAMED per drop #62 §14)

- [ ] **DECISION GATE:** same as I4
- [ ] I5 narrates whichever DEVIATION (if any) gates the new substrate's `conversation_pipeline.py` validator extension
- [ ] If no substrate swap + no new DEVIATION: I5 retires
- [ ] Commit: `feat(hsea-phase-4): 4.3 I5 guardrail narrator (post-§14 reframing)`

---

## 7. Phase 4 close

### 7.1 Smoke tests

- [ ] Both code-gen drafters (I6 conditional + I7) produce CodePatch outputs against real source files
- [ ] All 5 narrator drafters produce research drop outputs citing LRR commit SHAs
- [ ] At least 1 code patch through full draft→review→approve→promote cycle
- [ ] At least 2 narrator drops through full draft→review→approve→promote-drop cycle
- [ ] `check-frozen-files.py --probe` mode verified working
- [ ] `code_review.py` integrated + review_notes.md appearing in staging dirs
- [ ] Opus rate limiter enforced
- [ ] Governance queue does not drown under drafter + narrator output (spawn budget caps holding)

### 7.2 Handoff doc

- [ ] Write `docs/superpowers/handoff/2026-04-15-hsea-phase-4-complete.md` with I4/I5 reframing decision recorded

### 7.3 State close-out

- [ ] `hsea-state.yaml::phase_statuses[4].status: closed`
- [ ] Request operator update `unified_sequence[UP-12]` partial completion (Phase 4 is one of 6 HSEA phases in UP-12 cluster basket)

---

## 8. Cross-epic coordination

- **HSEA Phase 0 (UP-2)** ships the `promote-patch.sh` stub, governance queue, spawn budget that Phase 4 extends/consumes
- **HSEA Phase 1 (UP-4)** ships SourceRegistry + Sierpinski slot infrastructure that Phase 4 4.5 diff streaming uses
- **HSEA Phase 2 (UP-10)** ships `patch` stub (3.5) + `ComposeDropActivity` (3.6) base class that Phase 4 4.5 replaces and 4.3 narrators compose
- **HSEA Phase 3 (UP-11 portion)** is a sibling in UP-12; both compose `ComposeDropActivity`; no collision
- **LRR Phase 1 (UP-1)** ships `check-frozen-files.py --probe` mode that Phase 4 4.2 gates use
- **LRR UP-7 substrate swap** target is now substrate-TBD per drop #62 §14; I4/I5 retargeting decision gated on operator

---

## 9. End

Compact per-phase plan for HSEA Phase 4 Code Drafting Cluster (rescoped + §14-reframed). Ninth extraction in delta's pre-staging queue this session. Execution remains alpha/beta workstream.

— delta, 2026-04-15
