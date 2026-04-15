# HSEA epic coverage audit

**Date:** 2026-04-15
**Author:** alpha (queue/ item #108; mirror of LRR coverage audit #103)
**Scope:** per-phase audit of HSEA (Hapax Self-Executing Agent) epic spec/plan/implementation coverage on `origin/main`.
**Authoritative surface:** `origin/main` as of commit `63b115eae`. Branch-only artifacts (`beta-phase-4-bootstrap` etc.) are NOT counted as "on main".
**Status:** research drop; ground-truth snapshot for HSEA continuation planning.

---

## 1. Coverage matrix (13 HSEA phases)

| Phase | Spec on main | Plan on main | Implementation PRs | Execution status | Notes |
|---|---|---|---|---|---|
| **0** Foundation primitives + axiom precedent | ✓ `2026-04-15-hsea-phase-0-foundation-primitives-design.md` | ✓ `2026-04-15-hsea-phase-0-foundation-primitives-plan.md` | — | **PRE-STAGED, NOT STARTED** | §4 decision 3: ships joint `hapax-constitution` PR bundling HSEA Phase 0 0.5 `sp-hsea-mg-001` precedent with LRR Phase 6 constitutional amendments (drop #62 §10 Q5 ratification) |
| **1** Visibility surfaces (HUD + placards) | ✓ `2026-04-15-hsea-phase-1-visibility-surfaces-design.md` | ✓ `2026-04-15-hsea-phase-1-visibility-surfaces-plan.md` | — | **PRE-STAGED, NOT STARTED** | 5 placeholder zones already declared in `config/compositor-zones.yaml` (hud_top_left, objective_strip, frozen_files_placard, governance_queue_placard, condition_transition_banner) from LRR Phase 2 item 10b PR #850 |
| **2** Core director activities | ✓ `2026-04-15-hsea-phase-2-core-director-activities-design.md` | ✓ `2026-04-15-hsea-phase-2-core-director-activities-plan.md` | — | **PRE-STAGED, NOT STARTED** | — |
| **3** Research program orchestration (Cluster C) | ✓ `2026-04-15-hsea-phase-3-research-program-orchestration-design.md` | ✓ `2026-04-15-hsea-phase-3-research-program-orchestration-plan.md` | — | **PRE-STAGED, NOT STARTED** | — |
| **4** Code drafting cluster (Cluster I, rescoped) | ✓ `2026-04-15-hsea-phase-4-code-drafting-cluster-design.md` | ✓ `2026-04-15-hsea-phase-4-code-drafting-cluster-plan.md` | — | **PRE-STAGED, NOT STARTED** | Drop #62 §10 Q3 ratification: narration-only per operator (not full code drafting); rescoping documented in spec §1 |
| **5** M-series triad (biometric strip + mood + model-arbiter) | ✓ `2026-04-15-hsea-phase-5-m-series-triad-design.md` | ✓ `2026-04-15-hsea-phase-5-m-series-triad-plan.md` | — | **PRE-STAGED, NOT STARTED** | — |
| **6** Content quality + clip mining (Cluster B) | ✓ `2026-04-15-hsea-phase-6-content-quality-clip-mining-design.md` (PR #855, cherry-pick from beta) | **MISSING** | — | **SPEC ONLY, NO PLAN** | PR #855 shipped the spec only; companion plan deferred per alpha's 16:55Z note "can be written as follow-up" |
| **7** Self-monitoring + catastrophic tail (Cluster D) | ✓ `2026-04-15-hsea-phase-7-self-monitoring-catastrophic-tail-design.md` (PR #855) | **MISSING** | — | **SPEC ONLY, NO PLAN** | Same as Phase 6 — plan deferred in PR #855 |
| **8** Platform value curation | ✓ `2026-04-15-hsea-phase-8-platform-value-curation-design.md` | ✓ `2026-04-15-hsea-phase-8-platform-value-curation-plan.md` | — | **PRE-STAGED, NOT STARTED** | — |
| **9** Revenue preparation (Cluster H) | ✓ `2026-04-15-hsea-phase-9-revenue-preparation-design.md` | ✓ `2026-04-15-hsea-phase-9-revenue-preparation-plan.md` | — | **PRE-STAGED, NOT STARTED** | Drop #62 §10 Q6 ratification: revenue deliverable timing (substrate-independent) |
| **10** Reflexive stack | ✓ `2026-04-15-hsea-phase-10-reflexive-stack-design.md` | ✓ `2026-04-15-hsea-phase-10-reflexive-stack-plan.md` | — | **PRE-STAGED, NOT STARTED** | — |
| **11** Multi-agent spawner | ✓ `2026-04-15-hsea-phase-11-multi-agent-spawner-design.md` | ✓ `2026-04-15-hsea-phase-11-multi-agent-spawner-plan.md` | — | **PRE-STAGED, NOT STARTED** | — |
| **12** Long-tail + handoff (HSEA epic terminal) | ✓ `2026-04-15-hsea-phase-12-long-tail-handoff-design.md` | ✓ `2026-04-15-hsea-phase-12-long-tail-handoff-plan.md` | — | **PRE-STAGED, NOT STARTED** | Epic terminal phase per drop #62 §5 |

## 2. Summary statistics

- **13 of 13 HSEA phase specs on main** ✓ (complete coverage)
- **11 of 13 HSEA phase plans on main** (Phase 6 + Phase 7 plans MISSING)
- **0 of 13 HSEA phases have execution PRs on main** — HSEA epic is in 100% pre-staging state
- **1 docs-only PR shipped this overnight session** — PR #855 (cherry-picked Phase 6 + Phase 7 specs from beta's `beta-phase-4-bootstrap` branch)

## 3. Critical gaps

### 3.1 Phase 6 + Phase 7 plans missing

**Gap:** PR #855 cherry-picked the Phase 6 + Phase 7 specs but explicitly deferred the companion plan docs: *"Not in this commit: Phase 6 or Phase 7 plan docs (same compact pattern as HSEA Phase 5 plan; can be written as follow-up by beta or delta)"*.

**Severity:** MINOR. Pattern is copyable from HSEA Phase 5 plan. Opening sessions for Phase 6 + 7 can derive from the spec §3 deliverables + spec §8 execution order. Shipping the plan docs makes the pattern easier for the opener.

**Proposed follow-up:** queue items to author Phase 6 + Phase 7 plan docs (~150 LOC each, ~20 min each). Can be bundled into one PR or two. Recommended: one PR for both to match the cherry-pick pattern from PR #855.

### 3.2 Zero execution progress across all 13 phases

**Gap:** HSEA is 100% pre-staged, 0% executed. No PRs advance HSEA implementation. This is by design — HSEA Phase 0 depends on the joint `hapax-constitution` PR (per drop #62 §10 Q5) which in turn depends on LRR Phase 6 readiness which in turn depends on LRR Phase 5 substrate decision.

**Severity:** NOT A DRIFT. Expected state. HSEA execution unblocks when LRR Phase 5 lands and the joint constitutional PR ships.

### 3.3 Joint constitutional PR dependency chain

HSEA Phase 0 0.5 `sp-hsea-mg-001` precedent + `mg-drafting-visibility-001` implication are drafted into the HSEA Phase 0 spec deliverable 0.5, but the actual constitutional PR is opened by **LRR Phase 6** per the Q5 ratification. This creates a cross-epic dependency:

```
operator substrate decision (Phase 5)
     ↓
LRR Phase 5 spec + plan + execution
     ↓
LRR Phase 6 constitutional PR (joint vehicle)
     ↓ bundles:
     1. LRR Phase 6 4 constitutional amendments
     2. HSEA Phase 0 0.5 sp-hsea-mg-001 precedent YAML
     3. LRR Phase 6 70B reactivation guard rule (post-§14)
     ↓
HSEA Phase 0 0.2/0.3/0.4 can open (non-0.5 deliverables)
     ↓
HSEA Phase 1 opens (reads Phase 0 primitives + LRR Phase 1 research registry)
     ↓
HSEA Phases 2-12 open in parallel or per drop #62 §5 UP-12 cluster framework
```

This chain is documented in drop #62 §5 unified sequence UP-0 → UP-2 → UP-10 → UP-12.

## 4. Cross-epic dependencies (HSEA side)

### 4.1 HSEA Phase 1 depends on LRR Phase 2 item 10a (CairoSourceRegistry)

HSEA Phase 1 will register 5 CairoSource subclasses (HUD, objective strip, frozen-files placard, governance queue placard, condition transition banner) via `CairoSourceRegistry.register()` from LRR Phase 2 PR #849. The placeholder zones are already declared in `config/compositor-zones.yaml` (PR #850) so HSEA Phase 1 opener can register without editing the YAML.

**Status:** LRR Phase 2 item 10a is DONE on main. HSEA Phase 1 is unblocked on this axis. Remaining HSEA Phase 1 blocker: Phase 0 + research registry completion.

### 4.2 HSEA Phase 5 M1 depends on LRR Phase 10 §3.1 per-condition Prometheus slicing

HSEA Phase 5 M1 (biometric strip) reads per-condition Prometheus metrics to slice HR/HRV/presence by research condition. This requires LRR Phase 10 §3.1 (per-condition Prometheus slicing) to be implemented first.

**Status:** Phase 10 §3.1 is PARTIAL (cardinality pre-analysis exists on branch, dashboards not yet authored). Per LRR Phase 10 continuation audit (commit `f60cf4c49`), §3.1 is blocked on Phase 5 substrate decision.

### 4.3 HSEA Phase 7 D2 depends on LRR Phase 10 §3.1

Same dependency as HSEA Phase 5 M1. Anomaly narration reads per-condition Prometheus series.

### 4.4 HSEA Phase 1 research-state broadcaster → LRR Phase 1 research marker

HSEA Phase 1 1.1 (HUD strip) reads the active `condition_id` from `/dev/shm/hapax-compositor/research-marker.json` via the `shared/research_marker.py::read_marker()` helper. LRR Phase 1 PR #841 shipped this helper.

**Status:** LRR Phase 1 shipping is complete. HSEA Phase 1 is unblocked on this axis.

## 5. What HSEA inherits from LRR (current state)

HSEA phases can begin opening once their dependencies close. Currently available from LRR:

- **LRR Phase 1 research registry** (shipping complete) — provides `shared/research_marker.py` + `scripts/research-registry.py` CLI + `~/hapax-state/research-registry/` state directory
- **LRR Phase 2 archive pipeline** (substantively complete per `docs/superpowers/handoff/2026-04-15-lrr-phase-2-closure-handoff.md` commit `63b115eae`) — provides `CairoSourceRegistry`, `compositor-zones.yaml` placeholder zones, archive-search CLI, purge CLI with consent tie-in, research marker frame injection
- **Drop #62 §10 ratifications** — HSEA has clear policy guidance on Q1 (Option C substrate), Q3 (Cluster I narration-only), Q5 (joint constitutional PR), Q6 (Cluster H timing), Q7-Q10 (various operational decisions)

Not yet available from LRR:

- **LRR Phase 3** (hardware validation) — in progress; partial PRs shipped
- **LRR Phase 4** (Phase A completion + OSF pre-reg) — in progress
- **LRR Phase 5** (substrate swap) — BLOCKED on operator decision
- **LRR Phase 6** (governance finalization + joint constitutional PR) — BLOCKED on Phase 5
- **LRR Phase 7** (persona spec) — BLOCKED on Phase 5
- **LRR Phases 8-11** (content programming, closed-loop, observability, unknown) — BLOCKED on upstream

## 6. HSEA execution critical path

```
LRR Phase 5 (substrate)           ← operator blocker
     ↓
LRR Phase 6 (joint constitutional PR)
     ↓ bundles HSEA Phase 0 0.5 precedent
HSEA Phase 0 (non-0.5 deliverables + axiom precedent landed)
     ↓
HSEA Phase 1 (visibility surfaces)   ← can begin after Phase 0
     ↓
HSEA Phases 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 (parallel per UP-12 cluster basket)
     ↓
HSEA Phase 12 (long-tail + handoff, epic terminal)
```

**Gate lift:** operator substrate decision → LRR Phase 5 → LRR Phase 6 constitutional PR → HSEA Phase 0 → HSEA Phase 1 → parallel Phases 2-11 → HSEA Phase 12.

## 7. Comparison to LRR epic coverage

| Epic | Spec coverage | Plan coverage | Execution progress | Critical blocker |
|---|---|---|---|---|
| **LRR** | 9 of 11 phases (Phase 5, 6, 11 missing or undefined) | 9 of 11 phases | 5 of 11 phases in-progress or shipped | Operator substrate decision |
| **HSEA** | 13 of 13 phases ✓ | 11 of 13 phases (Phase 6 + 7 plans missing) | 0 of 13 phases shipped | LRR Phase 6 constitutional PR (which depends on LRR Phase 5) |

**Observation:** HSEA has BETTER spec coverage than LRR on main. This is because:

1. Beta pre-shipped HSEA specs into PR #855 cherry-pick (Phase 6 + 7)
2. Delta's overnight pre-staging covered all 13 HSEA phases completely
3. LRR Phase 5/6/10/11 have unresolved policy/hardware issues that make their spec authoring conditional

**HSEA execution will go faster than LRR once it starts** because all 13 specs are on main and ready to read. LRR execution required additional research + drop #62 ratifications + substrate decision as gate conditions.

## 8. Recommendations

### 8.1 Immediate (pre-Phase-5 decision)

1. **Author HSEA Phase 6 + Phase 7 plan docs** (matches existing HSEA Phase 5 plan pattern) — small PR, ~30 min total, no dependencies. Closes the only spec/plan gap on main.
2. **Verify HSEA Phase 0 0.5 draft YAML** is at the expected location per HSEA Phase 0 spec §3.5 — this is the content that lands in the joint constitutional PR. A future session opening Phase 0 can skip re-authoring if the draft already exists.

### 8.2 Pre-PR-#819-merge

1. **No additional cherry-picks needed** — HSEA spec/plan coverage on main is already complete (except Phase 6/7 plans from §8.1).

### 8.3 Post-LRR-Phase-5

1. **Author LRR Phase 6 constitutional PR** (joint vehicle bundling HSEA Phase 0 0.5 + LRR Phase 6 amendments)
2. **Open HSEA Phase 0 non-0.5 deliverables** (0.1-0.4) in parallel with LRR Phase 6 ratification
3. **HSEA Phase 1 opens** once Phase 0 is complete + LRR Phase 1 research registry is marked terminal

## 9. Non-drift observations

### 9.1 PR #855 cherry-pick authorship preserved

PR #855 preserved beta's authorship on the Phase 6 + Phase 7 specs (Author: beta in header). This is the correct pattern per alpha's refill 7 cadence analysis §5.5 ("partial cherry-picks preserve authorship"). No drift.

### 9.2 13 of 13 HSEA specs on main is unusual

Most epics never have 100% spec pre-staging before execution begins. HSEA's complete pre-staging is a side effect of delta's overnight extraction cycle at ~3 phases/hour with parallel-run context. Future epics may or may not follow this pattern depending on coordinator bandwidth.

### 9.3 No on-main HSEA research drops

Beta has authored several HSEA-related research drops on `beta-phase-4-bootstrap` (coordinator protocol evaluation, pattern meta-analysis, second-perspective synthesis) that reference HSEA as the execution context but are not HSEA-epic-authoritative. These are meta/process drops, not HSEA content, so their absence from main is not a coverage gap.

## 10. References

- LRR epic coverage audit (sibling): `docs/research/2026-04-15-lrr-epic-coverage-audit.md` (commit `030aa79af`)
- LRR Phase 10 continuation audit: `docs/research/2026-04-15-lrr-phase-10-continuation-audit.md` (commit `f60cf4c49`)
- LRR Phase 2 closure handoff: `docs/superpowers/handoff/2026-04-15-lrr-phase-2-closure-handoff.md` (commit `63b115eae`)
- Drop #62 §5 unified sequence: `docs/research/2026-04-14-cross-epic-fold-in-lrr-hsea.md` §5
- Drop #62 §10 Q5 joint PR ratification: same file §12.2 Q5 addendum
- HSEA epic spec: `docs/superpowers/specs/2026-04-14-hsea-epic-design.md` (parent authority)
- PR #855 HSEA Phase 6 + 7 cherry-pick: commit `aa4576e79`

— alpha, 2026-04-15T17:40Z
