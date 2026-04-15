# HSEA Phase 4 — Code Drafting Cluster (Cluster I, Rescoped) — Design Spec

**Date:** 2026-04-15
**Author:** delta (pre-staging extraction; HSEA execution remains alpha/beta workstream)
**Status:** DRAFT pre-staging — awaiting operator sign-off + upstream substrate selection + LRR UP-1 closed before Phase 4 open
**Epic reference:** `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` §5 Phase 4 (as rewritten by alpha's PR #830 per drop #62 §10 Q3 ratification)
**Plan reference:** `docs/superpowers/plans/2026-04-15-hsea-phase-4-code-drafting-cluster-plan.md`
**Branch target:** `feat/hsea-phase-4-code-drafting-cluster`
**Cross-epic authority:** drop #62 §10 Q3 (Cluster I rescoping, ratified 2026-04-15T05:35Z) + drop #62 §14 (Hermes abandoned 2026-04-15T06:35Z)
**Unified phase mapping:** **UP-12 parallelizable cluster basket** (drop #62 §5 line 147): depends on UP-7 (substrate swap) + UP-10 (HSEA Phase 2) closed; HSEA Phase 4 shares UP-12 slot with HSEA Phases 5, 6, 7, 8, 9. ~1,100 LOC post-rescoping (down from ~3,500).

> **2026-04-15T07:20Z substrate reframing note:** this spec is structurally valid but I4 + I5 narrator targets reference the Hermes 3 8B pivot which was abandoned by the operator at 06:35Z per drop #62 §14. Phase 4 opener MUST read drop #62 §14 before starting I4/I5 work and retarget them to whichever substrate transition the operator ratifies. I1/I2/I3 are substrate-agnostic and unaffected; I6/I7 are substrate-agnostic and unaffected; 4.1/4.2/4.4/4.5/4.6 infrastructure is substrate-agnostic and unaffected.

---

## 1. Phase goal

Ship per-task drafters for every drop #57 critical-path code change — but per drop #62 §10 Q3 ratification (2026-04-15T05:35Z), 5 of the 7 sub-drafters (I1-I5) are **narration-only spectator drafters** that watch LRR phases land the canonical code and compose research drops summarizing the landing. Only I6 (YouTube tee, conditional) and I7 (ritualized director states) ship real code. The net effect: Phase 4 retains the Hapax-prepares-everything framing while moving the actual code ownership to LRR where it belongs per drop #62 §3 ownership table.

**What this phase is:** the `code_drafter` pydantic-ai agent base + staging infrastructure + `promote-patch.sh` / `reject-patch.sh` scripts + director `patch` activity full implementation + mandatory `code_review.py` integration (the "closes the loop" Hapax-self-review step) + 2 code-gen sub-drafters (I6, I7) + 5 narrator sub-drafters (I1-I5) each composing `ComposeDropActivity` from HSEA Phase 2 deliverable 3.6.

**What this phase is NOT:** does not ship the LRR code targets themselves (I1 PyMC BEST port is LRR Phase 1 item 7; I2/I3 activity priors are LRR Phase 9; I4/I5 substrate swap artifacts are LRR Phase 5a if it ever opens; the code ownership lives in LRR, not HSEA). Does not ship any new activity beyond `patch` (HSEA Phase 2 deliverable 3.5 is the `patch` stub; Phase 4 deliverable 4.5 is the full implementation).

**New alias:** `capable → claude-opus-4-6` added to `shared/config.py` + `agents/_config.py` (per epic spec Phase 4 header — this is a small infrastructure addition that Phase 4 ships so the code drafter has access to the highest-capability tier when needed).

---

## 2. Dependencies + preconditions

**Cross-epic (from drop #62):**

1. **LRR UP-0 + UP-1 closed.** UP-1 is hard: `check-frozen-files.py --probe` is LRR Phase 1 item 4 deliverable (drop #62 §3 row 1); Phase 4 deliverable 4.2 depends on the probe mode via the `run_gates()` helper.

2. **LRR UP-7 (substrate swap) closed** per drop #62 §5 row UP-12 dependency. Originally this meant UP-7a (Hermes 3 8B) closed. Per drop #62 §14 Hermes abandonment, UP-7 now means "whichever substrate replaces Hermes gets ratified and shipped". Phase 4 cannot open until:
   - The operator has ratified a replacement substrate per beta's research §9 recommendation (or chosen an alternative)
   - LRR Phase 5 (UP-7) has shipped the substrate swap code
   - At least one condition is open under the new substrate

3. **HSEA UP-2 (Phase 0) closed.** All 6 Phase 0 deliverables merged; `promote-patch.sh` + `promote-drop.sh` + governance queue + spawn budget + axiom precedent draft all shipped.

4. **HSEA UP-4 (Phase 1 visibility surfaces) closed.** Phase 4 deliverable 4.5 `patch` activity streams diff text to a Sierpinski slot — HSEA Phase 1's visibility infrastructure + LRR Phase 2's SourceRegistry mechanism are required for the streaming UX.

5. **HSEA UP-10 (Phase 2 core director activities) closed.** Phase 4 deliverable 4.5 `patch` activity is the full implementation of the stub shipped in HSEA Phase 2 deliverable 3.5. I1-I5 narrator drafters all compose `ComposeDropActivity` from HSEA Phase 2 deliverable 3.6 — without Phase 2, there is no narrator base.

6. **HSEA Phase 3 (UP-11) NOT required.** Phase 4 is a sibling of Phase 3 in the UP-12 cluster basket; both can ship in parallel. In practice, Phase 3's research orchestration narrators inform Phase 4's narrator drafters (same pattern, different scope), so shipping Phase 3 first would give Phase 4 a reference implementation.

**Intra-epic:** HSEA Phases 0, 1, 2 closed. HSEA Phase 3 closed strongly recommended but not strictly required.

**Infrastructure:**

1. `shared/config.py` (existing) — extended with `capable → claude-opus-4-6` alias
2. `agents/_config.py` (existing) — extended with `capable → claude-opus-4-6` alias
3. `scripts/check-frozen-files.py --probe` (LRR Phase 1 item 4)
4. `shared/governance_queue.py` + `shared/spawn_budget.py` + `scripts/promote-patch.sh` + `scripts/promote-drop.sh` (HSEA Phase 0 deliverables)
5. `ComposeDropActivity` public API (HSEA Phase 2 deliverable 3.6)
6. `config/patch_priorities.yaml` (new file, Phase 4 deliverable 4.5 creates)
7. `config/code_drafter.yaml` (new file, Phase 4 deliverable 4.2 creates)
8. `~/hapax-state/staged-patches/` (Phase 4 creates this subtree)
9. `~/hapax-state/opus-drafter-counter.jsonl` (Phase 4 deliverable 4.2 rate limiter ledger)

---

## 3. Deliverables (6 items: 4.1–4.6)

Extracted as-is from alpha's PR #830-updated HSEA epic spec §5 Phase 4.

### 3.1 Base code drafter (item 4.1)

**Scope:**
- `agents/code_drafter/__init__.py`: new module with pydantic-ai agent
- `output_type=CodePatch(files: list[FileDiff], test_plan, rationale, risk_assessment, risk_factors, rollback_plan, blocked_by, unblocks)`
- `DrafterDeps(target_task, source_files, conventions, frozen_file_list, line_cap)` — dependency injection for the drafter
- `build_agent(tier: "balanced" | "capable")` factory — constructs the pydantic-ai agent with the specified model tier (`capable` = Opus escalation)
- System prompt includes:
  - Project conventions (read from `CLAUDE.md` + `pyproject.toml` + project-local `.pre-commit-config.yaml`)
  - Explicit "NEVER write git/rm/sudo/curl|sh" constraint (destructive regex enforcement)
  - Frozen-files awareness (drafter must not propose patches touching frozen paths)
- **Target files:**
  - `agents/code_drafter/__init__.py` (~150 LOC)
  - `agents/code_drafter/_schema.py` (~130 LOC CodePatch + FileDiff models)
  - `tests/code_drafter/test_base.py` (~150 LOC)
- **Size:** ~280 LOC implementation + ~150 LOC tests

### 3.2 Staging infrastructure (item 4.2)

**Scope:**
- `agents/code_drafter/_staging.py`: `stage_patch()` atomically writes to `~/hapax-state/staged-patches/<ulid>/` with the patch + metadata + test plan
- `agents/code_drafter/_gates.py`: `run_gates()` runs:
  - Destructive-regex check (rejects patches containing `git reset --hard`, `rm -rf`, `sudo`, `curl | sh`, etc.)
  - Line cap check (per-task line caps stored in `config/code_drafter.yaml`)
  - Frozen-files probe via `check-frozen-files.py --probe` (LRR Phase 1 item 4)
  - Ruff + Pyright on the proposed patch (hypothetical application)
  - Pytest smoke test on touched files (runs the existing test suite against a stash of the patch)
- `agents/code_drafter/_escalation.py`: routes failing-gate patches to `capable` tier for re-attempt; tracks escalation count
- `agents/code_drafter/_diff.py`: diff parsing + application helpers
- `agents/code_drafter/_conventions.py`: project convention enforcement (snake_case, type hints, pydantic-ai output_type usage, etc.)
- `config/code_drafter.yaml`: per-task line caps, gate thresholds
- `~/hapax-state/opus-drafter-counter.jsonl`: rate limiter for Opus escalation (≤3/day), updated on each escalation call
- **Target files:**
  - `agents/code_drafter/_staging.py` (~120 LOC)
  - `agents/code_drafter/_gates.py` (~180 LOC)
  - `agents/code_drafter/_escalation.py` (~100 LOC)
  - `agents/code_drafter/_diff.py` (~80 LOC)
  - `agents/code_drafter/_conventions.py` (~80 LOC)
  - `config/code_drafter.yaml` (operator-editable)
  - `tests/code_drafter/test_staging.py` + `test_gates.py` + `test_escalation.py` (~240 LOC)
- **Size:** ~600 LOC total

### 3.3 Per-task drafter subclasses (item 4.3) — 2 code-gen + 5 narrators

Per alpha's PR #830 update (drop #62 §10 Q3 ratification 2026-04-15), the 7 sub-drafters split as:

**Code-generation drafters (2):**

- **I6 `t4_8_youtube_tee`** — tee branch for `rtmp_output.py` for backup ingest. Tier: `balanced`. Line cap: 200. **Conditional:** `rtmp_output.py` must NOT be in the active condition's frozen-files manifest at drafter open time. If frozen, I6 demotes to narration-only and the code work moves to a DEVIATION-gated LRR PR. Targets: `agents/studio_compositor/rtmp_output.py` extension (if not frozen).

- **I7 `t4_11_ritualized_states`** — four ritualized director states (Midnight/Wake/Crate/Last Call) with time-of-day gating. Tier: `balanced`. Line cap: 500. Targets: `agents/director_loop/_ritual_states.py` (NEW file; no frozen-file touch). This is the only I-drafter that writes genuinely new HSEA code per drop #62 §8.

**Narrator drafters (5) — all compose `ComposeDropActivity` from HSEA Phase 2 3.6:**

- **I1 `t1_3_pymc5_best_narrator`** — watches LRR UP-1 for PyMC 5 BEST port commits (LRR Phase 1 item 7). Drafts a research drop summarizing the port at landing time. Tier: `balanced`. Line cap: 150 (research drop text). Depends on: LRR UP-1 merged. **Substrate-agnostic.**

- **I2 `t1_7_stimmung_prior_narrator`** — watches LRR UP-11 (LRR Phase 9 closed-loop wiring) for stimmung-gated activity prior commits. Drafts a research drop with the wiring diagram + before/after stimmung traces. Tier: `balanced`. Line cap: 150. Depends on: LRR UP-11 merged. **Substrate-agnostic.**

- **I3 `t2_2_burst_cadence_narrator`** — watches LRR UP-11 (LRR Phase 9 + Phase 10 PERCEPTION_INTERVAL tuning) for burst/rest cadence state machine commits. Drafts a research drop with state-diagram + cadence histograms. Tier: `balanced`. Line cap: 150. Depends on: LRR UP-11 merged. **Substrate-agnostic.**

- **I4 `t2_6_hermes_8b_pivot_narrator`** — **Hermes target is SUPERSEDED per drop #62 §14.** Originally: watches LRR UP-7a for TabbyAPI + LiteLLM + conversation_pipeline landings and drafts a research drop covering the pivot arc (#54 → #62 → operator activation). Now: Phase 4 opener retargets to the actual substrate swap that replaces Hermes (whatever the operator ratifies from beta's research §9 recommendation). Line cap 300 still applies (substrate swap narration is the largest narrator drop). If the operator chooses "keep Qwen3.5-9B + 3 production fixes" (beta's primary recommendation), I4 becomes a narration of the production fixes + the Hermes-abandoned decision, NOT a substrate swap narration. If the operator chooses to parallel-deploy OLMo 3-7B, I4 narrates that deployment. Phase 4 opener decides the exact framing at phase open time based on the substrate state.

- **I5 `t2_8_guardrail_narrator`** — **Hermes DEVIATION target is SUPERSEDED per drop #62 §14.** Originally: watches LRR UP-7a DEVIATION-037 landing (T2.8 guardrail bundled into 8B pivot DEVIATION per Q2 ratification). Now: Phase 4 opener retargets to wherever the T2.8 guardrail ends up landing (whatever DEVIATION, if any, gates the new substrate's `conversation_pipeline.py` validator extension). If no substrate swap occurs (operator keeps Qwen3.5-9B), T2.8 still needs a DEVIATION of some kind (it touches a frozen file), and I5 narrates THAT DEVIATION's landing instead. Phase 4 opener decides.

**Size:** ~280 LOC total across the 7 sub-drafter implementations (mostly framework code; the narrator drafters are thin wrappers over `ComposeDropActivity`, and I6/I7 code-gen drafters reuse the base from 4.1)

### 3.4 `promote-patch.sh` + `reject-patch.sh` (item 4.4)

**Scope:**
- `scripts/promote-patch.sh` (HSEA Phase 0 0.4 initial implementation — Phase 4 extends with code-drafter-specific handling):
  - Re-runs final ruff + pytest + frozen-files check + destructive regex
  - Applies via `git apply`, stages, commits with Claude-attributed message
  - Optional `--pr` flag creates draft PR via `gh pr create --draft`
- `scripts/reject-patch.sh` (NEW):
  - Archives bundle to `~/hapax-state/staged-patches/archive/<ulid>/`
  - Writes rejection reason file
  - Updates governance queue entry with `status: rejected`
- Phase 0 0.4 shipped `promote-patch.sh` as a stub; Phase 4 4.4 is the real implementation with code-drafter integration
- **Target files:**
  - `scripts/promote-patch.sh` (~150 LOC final implementation)
  - `scripts/reject-patch.sh` (~100 LOC)
  - `tests/scripts/test_promote_patch.bats` (extension, ~80 LOC)
- **Size:** ~330 LOC total

### 3.5 Director `patch` activity full implementation (item 4.5)

**Scope:**
- Replaces the HSEA Phase 2 deliverable 3.5 stub with a full implementation
- Picks a task from `config/patch_priorities.yaml` (new operator-editable priority file)
- Invokes the drafter subprocess, streams diff text to a Sierpinski slot character-by-character
- Daimonion narrates milestones at salience 0.45 (low-key on-stream narration)
- On approval detection (inotify on the governance queue entry's status flip to `approved`), re-narrates with the committed SHA
- **Target files:**
  - `agents/hapax_daimonion/activities/patch.py` — REPLACES the stub from HSEA Phase 2 3.5
  - `config/patch_priorities.yaml` (operator-editable)
  - `tests/hapax_daimonion/test_activity_patch_full.py` (~200 LOC)
- **Size:** ~400 LOC implementation + tests

### 3.6 Mandatory `code_review.py` integration (item 4.6)

**Scope:**
- Every staged patch automatically goes through `code_review.agent.run()` BEFORE reaching the operator inbox
- `code_review.py` is a separate pydantic-ai agent that reviews the staged patch against project conventions + known pitfalls
- Review output written to `~/hapax-state/staged-patches/<ulid>/review_notes.md`
- Operator sees Hapax's self-review before Hapax's work — this "closes the loop" per drop #57 F-cluster framing (F4 peer review, F5 self-review)
- If the review surfaces blocking issues, the patch is NOT auto-rejected — the review notes are included in the governance queue entry so the operator can decide
- **Target files:**
  - `agents/code_reviewer/__init__.py` (~200 LOC review agent; separate module from `code_drafter` for concern separation)
  - `agents/code_reviewer/_prompts.py` (~80 LOC review prompt templates)
  - `tests/code_reviewer/test_review.py` (~150 LOC)
- **Size:** ~430 LOC

---

## 4. Phase-specific decisions since epic authored

1. **Drop #62 §10 Q3 rescoping applied by alpha's PR #830** (2026-04-15T05:35Z ratification + 06:07Z merge). I1-I5 are narration-only; I6/I7 are code-gen; net LOC ~-2,400. This extraction reflects the post-PR-#830 state of the HSEA epic spec.

2. **Drop #62 §14 Hermes abandonment supersedes I4 + I5 narration targets** (2026-04-15T06:35Z operator direction). I4 and I5 both originally targeted the Hermes 3 8B pivot; that pivot is no longer happening. Phase 4 opener reframes I4/I5 at execution time. Three options per beta's research §9 recommendation:
   - **Option A:** retarget I4 to "Hermes abandonment + production fixes" narration; I5 narrates whatever `conversation_pipeline.py` DEVIATION ships (if any)
   - **Option B:** retarget I4 to "OLMo 3-7B parallel deployment" narration (if operator ratifies beta's complementary recommendation); I5 narrates the OLMo-adjacent DEVIATION (if any)
   - **Option C:** retire I4 + I5 entirely and reduce Phase 4 to 5 sub-drafters (I1/I2/I3 narrators + I6/I7 code-gen); decision gate at phase open time based on what the operator has ratified
   - Delta's recommendation: **Option A** — most faithful to the drop #62 §14 framing that "the decision to abandon" is itself narrative content worth composing as a research drop

3. **HSEA Phase 2 deliverable 3.5 `patch` stub → Phase 4 deliverable 4.5 full implementation** — clean replacement, not additive. The stub signature is preserved so tests against the stub continue to pass after the full implementation lands.

4. **HSEA Phase 0 deliverable 0.4 `promote-patch.sh` stub → Phase 4 deliverable 4.4 full implementation** — same clean-replacement pattern. Phase 0 shipped the script shell for `promote-patch.sh`; Phase 4 ships the real code-drafter integration.

5. **`code_reviewer` is a NEW module, separate from `code_drafter`** — concern separation. The code drafter proposes; the code reviewer critiques; the operator decides. This three-role split matches F4 (peer review) + F5 (self-review) from drop #57 Cluster F framing.

6. **`check-frozen-files.py --probe` is a LRR Phase 1 dependency**, not a HSEA Phase 4 deliverable. Phase 4 deliverable 4.2 `run_gates()` invokes the LRR-shipped tool via subprocess.

7. **All drop #62 §10 open questions are closed** (Q1 ratified then practically reopened per §14, but Q2-Q10 remain valid). Phase 4 has no pending operator decisions from §10.

---

## 5. Exit criteria

Phase 4 closes when:

1. `shared/config.py` + `agents/_config.py` have `capable → claude-opus-4-6` alias registered
2. `agents/code_drafter/` module ships with all 5 sub-modules (`__init__.py`, `_staging.py`, `_gates.py`, `_escalation.py`, `_diff.py`, `_conventions.py`)
3. `config/code_drafter.yaml` + `config/patch_priorities.yaml` shipped and operator-editable
4. **Both code-generation drafters (I6 conditional on `rtmp_output.py` not frozen, I7) produce valid CodePatch outputs** against real source files
5. **All 5 narration-only spectator drafters (I1/I2/I3/I4/I5) produce valid research drop outputs** that cite the underlying LRR phase commits by SHA. **I4 + I5 targets have been reframed per §14 option A/B/C decision made at phase open time.**
6. At least 1 code patch (from I6 or I7) has gone through the full draft→review→approve→promote cycle successfully
7. At least 2 narrator drops have gone through the full draft→review→approve→promote-drop cycle successfully
8. `check-frozen-files.py --probe` mode merged (LRR Phase 1 item 4 dependency verified)
9. `code_review.py` agent integrated into the staging flow; every staged patch has a review_notes.md
10. `hsea-state.yaml::phase_statuses[4].status == closed`
11. Phase 4 handoff doc written
12. HSEA Phase 5/6/7/8/9 pre-open compatibility: the drafter base + staging infrastructure can be extended by future phases (test with a stub drafter from a Phase 5 deliverable)

---

## 6. Risks + mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| I4 + I5 reframing decision delayed | Phase 4 can't close with narrator drafters in place | Phase 4 opens only after operator has ratified a substrate direction per beta's research §9 |
| I6 conditional on `rtmp_output.py` frozen-status flips mid-phase | I6 demotes to narration mid-implementation | Check frozen state at each drafter invocation, not at phase open; demotion path documented |
| `code_review.py` produces noisy false-positive reviews | Operator fatigue | Review threshold tuning + operator override flag (`--skip-review`) for known-good patterns |
| Opus rate limit (≤3/day) hit during active drafter session | Escalation unavailable mid-session | Rate limiter surfaces the exhaustion clearly; drafter falls back to `balanced` tier + logs that it was capable-denied |
| Narrator drafter drops drown the governance queue | Queue fills with narration | Spawn budget per-drafter caps + governance queue TTL (14 days per HSEA Phase 0 0.2) |
| Drafter produces a patch that passes gates but has subtle bugs | Post-merge regression | Mandatory `code_review.py` integration (deliverable 4.6) is the mitigation; review notes surface to operator |
| Substrate-agnostic I1/I2/I3 narrators are blocked on LRR phases that haven't shipped | Phase 4 can't close narrators | Phase 4 opens only after LRR UP-1 (for I1), UP-11 (for I2/I3) — drop #62 §5 unified sequence enforces the ordering |
| Phase 4 collides with Phase 3 on governance queue + draft-buffer directory | Queue contention | Phase 3 + Phase 4 both compose `ComposeDropActivity` with distinct slugs per drafter; no collision |

---

## 7. Open questions

All drop #62 §10 resolved except the practical reopening of Q1 substrate per §14.

Phase-4-specific:

1. **I4 + I5 reframing option (A/B/C)**. Decision gate at phase open. Recommendation: Option A.
2. **`config/code_drafter.yaml` line cap defaults**. Tunable at phase open; initial defaults per 4.3 sub-drafter definitions (I6=200, I7=500, I1-I5=150-300 per narrator).
3. **Opus rate limit (≤3/day)**. Operator can tune; 3/day is the starting budget to prevent Opus-cost runaway.
4. **Review threshold for `code_reviewer`**. Default: operator sees all reviews; future tuning can suppress routine all-clear reviews.
5. **Narrator commit-SHA extraction**. I1-I5 narrators read git log to find the LRR commits they're narrating. Some narrators may need fuzzy matching (e.g., I1 watches for "PyMC BEST port" commit messages). Phase 4 opener defines the match heuristics.

---

## 8. Companion plan doc

`docs/superpowers/plans/2026-04-15-hsea-phase-4-code-drafting-cluster-plan.md`.

Execution order:

1. **4.1 Base code drafter** — foundational; all sub-drafters depend on the base agent
2. **4.2 Staging infrastructure** — depends on 4.1; provides the `stage_patch()` + `run_gates()` surfaces sub-drafters use
3. **4.4 `promote-patch.sh` + `reject-patch.sh`** — can ship in parallel with 4.1/4.2; touches scripts not Python
4. **4.6 `code_review.py` integration** — depends on 4.1/4.2; the review agent is a sibling of the drafter agent
5. **4.5 Director `patch` activity full implementation** — depends on 4.1/4.2/4.4/4.6 + HSEA Phase 2 stub
6. **4.3 Sub-drafters:**
   - I7 first (only fully-new-code drafter, smallest dependency surface)
   - I6 second (conditional on frozen-files check; simpler than narrators)
   - I1/I2/I3 next (narrators; substrate-agnostic; depend on LRR UP-1/UP-11)
   - I4/I5 last (require the substrate reframing decision per §14)

Each sub-drafter is a separate PR; the base + staging + promote scripts can bundle.

---

## 9. End

Pre-staging spec for HSEA Phase 4 Code Drafting Cluster (rescoped per drop #62 §10 Q3; I4/I5 targets superseded per §14). 6 deliverables + 7 sub-drafters (2 code-gen + 5 narrators). ~1,100 LOC post-rescoping.

Phase 4 opens only when:
- Operator has ratified a substrate direction per beta's research §9 recommendation (or chosen an alternative)
- LRR UP-1 + UP-11 (for I1/I2/I3 narrator targets) have shipped
- HSEA UP-2 + UP-4 + UP-10 closed
- A session claims the phase via `hsea-state.yaml::phase_statuses[4].status: open`

Ninth complete extraction in delta's pre-staging queue this session. Execution remains alpha/beta workstream.

— delta, 2026-04-15
