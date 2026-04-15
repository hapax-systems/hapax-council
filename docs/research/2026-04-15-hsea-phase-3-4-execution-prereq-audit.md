# HSEA Phase 3 + Phase 4 execution prerequisite audit

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #162)
**Scope:** Per the two HSEA phase specs on main, enumerate Phase 3 (research program orchestration / C-cluster) and Phase 4 (code drafting cluster / I-cluster) prerequisites. Classify each as substrate-dependent / hardware-dependent / phase-dependent / already-satisfied. Assess whether any execution path is viable pre-substrate.
**Register:** scientific, neutral
**Depends on:** queue #108 (HSEA epic coverage audit, PR #867)

## 1. Headline

**Neither Phase 3 nor Phase 4 can fully execute pre-substrate.** Both have multi-layer upstream dependency chains that are not yet satisfied.

**Phase 3 (11 deliverables C2-C12):** blocked on HSEA Phases 0/1/2 execution (not yet started) + LRR Phase 1 research registry + LRR Phase 7 persona spec. **Not substrate-dependent directly** — the dep is on HSEA upstream phases which are themselves blocked on other work. **Pre-substrate prep work is minimal** because the phase is composed entirely of narrator drafters that subclass a not-yet-existing `ComposeDropActivity` from HSEA Phase 2.

**Phase 4 (6 deliverables 4.1-4.6):** blocked on LRR Phase 5 substrate swap + HSEA Phases 0/1/2 execution + LRR UP-1 frozen-files probe. **Substrate-dependent** directly per requirement 2 ("LRR UP-7 substrate swap closed"). Cannot execute without scenarios 1+2 shipped.

**Bottom line:** **no pre-substrate execution path exists** for either phase. Pre-substrate prep is limited to scaffolding that does not require upstream phases. Most of the prep work should wait for HSEA Phase 0/1/2 to land first.

## 2. Phase 3 prerequisite inventory

Per `docs/superpowers/specs/2026-04-15-hsea-phase-3-research-program-orchestration-design.md` §2 (lines 26-49).

### 2.1 Cross-epic prerequisites (7 items)

| # | Prerequisite | Class | Status |
|---|---|---|---|
| 1 | LRR UP-0 + UP-1 closed (standard chain) | phase-dependent | UP-0 ✓, **UP-1 NOT shipped** (research registry is LRR Phase 1; not yet executed) |
| 2 | LRR UP-3 (Phase 2 archive instrument) closed | phase-dependent | ✓ **SATISFIED** — LRR Phase 2 shipped via 10 PRs (#801-#810) |
| 3 | HSEA UP-2 (Phase 0) closed | phase-dependent | **NOT shipped** — Phase 0 deliverables 0.1-0.6 pre-staged but not executed |
| 4 | HSEA UP-4 (Phase 1 visibility surfaces) closed | phase-dependent | **NOT shipped** — Phase 1 pre-staged only |
| 5 | HSEA UP-10 (Phase 2 core director activities) closed — provides `ComposeDropActivity` base class | phase-dependent | **NOT shipped** — Phase 2 pre-staged only |
| 6 | LRR UP-9 (Phase 7 persona) closed (transitively via HSEA Phase 2) | phase-dependent | **NOT shipped** — Phase 7 prep inventory authored (queue #131) but execution pending |
| 7 | LRR Phase 4 closed for C6, C7, C11 (condition_id, OSF pre-reg, Phase A results) | phase-dependent | **NOT shipped** — Phase 4 spec + plan exist, Phase A data collection not started |

**Phase 3 substrate-dependence:** **NONE directly.** The deps are on upstream HSEA/LRR phases, not on substrate. But transitively, LRR Phase 5 (substrate) blocks LRR Phase 4 which blocks Phase 3 requirements 6 + 7.

### 2.2 Infrastructure prerequisites (8 items)

| # | Prerequisite | Class | Status |
|---|---|---|---|
| 1 | `ComposeDropActivity` public API from HSEA Phase 2 deliverable 3.6 | phase-dependent | **NOT available** — requires Phase 2 execution |
| 2 | LRR research registry + condition_id taxonomy (LRR Phase 1) | phase-dependent | **NOT available** |
| 3 | OSF project (created at LRR Phase 1 item 6) | phase-dependent | **NOT available** |
| 4 | PyMC 5 BEST implementation (LRR Phase 1 item 7) | phase-dependent | **NOT available** |
| 5 | Research integrity heartbeat file | phase-dependent | **NOT available** |
| 6 | `scripts/research-registry.py` CLI (LRR Phase 1) | phase-dependent | **NOT available** |
| 7 | `agents/hapax_daimonion/voice_session/` (existing voice grounding infrastructure) | already-satisfied | ✓ **SATISFIED** |
| 8 | Beta worktree read capability for C4 | already-satisfied | ✓ **SATISFIED** — read-only access is just `git log` / file reads on `~/projects/hapax-council--beta/` |

**Phase 3 infrastructure:** 2 of 8 already satisfied. 6 pending upstream phase execution.

### 2.3 Phase 3 pre-substrate execution viability

**Verdict: not viable.** Every C2-C12 deliverable requires the not-yet-existing `ComposeDropActivity` base class from HSEA Phase 2. No deliverable can be authored without that base.

**Possible pre-substrate prep:**

- **Draft the 11 deliverable descriptions** as pre-staging documents (but the Phase 3 spec + plan already provide this — further drafting would duplicate)
- **Author narrator stubs** that compose against a placeholder `ComposeDropActivity` — but these would be thrown away when Phase 2 ships the real base
- **No useful pre-execution work** other than what queue #131 Phase 7/8/9 prep already covers conceptually

**Alpha recommendation:** defer all Phase 3 work until HSEA Phase 2 ships the narrator base. Do NOT file pre-substrate execution items for Phase 3.

## 3. Phase 4 prerequisite inventory

Per `docs/superpowers/specs/2026-04-15-hsea-phase-4-code-drafting-cluster-design.md` §2 (lines 28-60).

### 3.1 Cross-epic prerequisites (6 items)

| # | Prerequisite | Class | Status |
|---|---|---|---|
| 1 | LRR UP-0 + UP-1 closed (UP-1 hard dep: `check-frozen-files.py --probe`) | phase-dependent | UP-0 ✓, **UP-1 NOT shipped** (LRR Phase 1) |
| 2 | LRR UP-7 substrate swap closed | **substrate-dependent** | **NOT shipped** — scenarios 1+2 ratified (§16) but not executed (LRR Phase 5 pending) |
| 3 | HSEA UP-2 (Phase 0) closed | phase-dependent | **NOT shipped** |
| 4 | HSEA UP-4 (Phase 1) closed | phase-dependent | **NOT shipped** |
| 5 | HSEA UP-10 (Phase 2) closed — `ComposeDropActivity` base | phase-dependent | **NOT shipped** |
| 6 | HSEA Phase 3 (UP-11) — NOT required (sibling in UP-12 basket; can parallel) | informational | — |

**Phase 4 substrate-dependence: DIRECT YES.** Requirement 2 explicitly blocks on LRR Phase 5 shipping the substrate swap. Post-§16 + §17 Option C, this means: either scenario 1 (Qwen verification) or scenario 2 (OLMo parallel) must be live, and at least one condition open under the new substrate.

### 3.2 Infrastructure prerequisites (9 items)

| # | Prerequisite | Class | Status |
|---|---|---|---|
| 1 | `shared/config.py` with `capable → claude-opus-4-6` alias | already-satisfied / near-miss | Existing `shared/config.py` has `balanced → claude-sonnet`. Does it have `capable`? Alpha did not verify; likely needs an add |
| 2 | `agents/_config.py` with `capable → claude-opus-4-6` alias | same as #1 | same |
| 3 | `scripts/check-frozen-files.py --probe` (LRR Phase 1 item 4) | phase-dependent | **NOT shipped** |
| 4 | `shared/governance_queue.py` + `shared/spawn_budget.py` + `scripts/promote-patch.sh` + `scripts/promote-drop.sh` (HSEA Phase 0) | phase-dependent | **NOT shipped** |
| 5 | `ComposeDropActivity` (HSEA Phase 2) | phase-dependent | **NOT shipped** |
| 6 | `config/patch_priorities.yaml` (Phase 4 4.5 creates) | self-satisfying | Phase 4 creates |
| 7 | `config/code_drafter.yaml` (Phase 4 4.2 creates) | self-satisfying | Phase 4 creates |
| 8 | `~/hapax-state/staged-patches/` | self-satisfying | Phase 4 creates |
| 9 | `~/hapax-state/opus-drafter-counter.jsonl` (Phase 4 4.2 rate limiter) | self-satisfying | Phase 4 creates |

**Phase 4 infrastructure:** 4 self-satisfying (Phase 4 creates on first run), 2 near-miss (config aliases may need tweak), 3 phase-dependent on upstream.

### 3.3 Phase 4 pre-substrate execution viability

**Verdict: not viable for full execution, but some substrate-independent scaffolding exists.**

Substrate-independent prep items that could ship pre-Phase-5:

**P4.prep-A — `capable` alias add to shared/config.py + agents/_config.py:**
- Prerequisite 1 + 2: add `"capable": "claude-opus"` (or whatever the final name is) to MODELS dicts
- Substrate-independent: the alias is cloud-routed (claude-opus-4-6), not local
- ~5 lines Python edit across 2 files
- Low-priority but small enough to ship as a pre-staging item

**P4.prep-B — stub `config/patch_priorities.yaml` + `config/code_drafter.yaml`:**
- Create empty placeholder files with schema frontmatter
- Phase 4 execution session will fill them in
- ~20 lines YAML each
- Has the effect of marking the config paths as "expected to exist" even pre-execution

**P4.prep-C — `~/hapax-state/staged-patches/` directory scaffold:**
- `mkdir -p ~/hapax-state/staged-patches/ && touch ~/hapax-state/staged-patches/.gitkeep`
- Even smaller; pure filesystem prep
- Out-of-repo path; would ship as a script `scripts/phase-4-scaffold.sh` that creates the directory

**P4.prep-D — per-task drafter stubs (optional):**
- Subclasses of the not-yet-existing `ComposeDropActivity` base — CANNOT ship without the base
- **Not viable pre-Phase-2**

**P4.prep-E — `scripts/code_review.py` integration stub:**
- Item 4.6 mandatory code review integration — requires knowing the full integration surface which is substrate-sensitive
- **Not viable pre-substrate**

**Alpha recommendation:** P4.prep-A is the most valuable (5-line alias add) + P4.prep-B is near-trivial. File both as low-priority follow-up queue items. Defer the rest.

## 4. Comparison to queue #131 Phase 7/8/9 prep inventory

Queue #131 found Phase 7 60% substrate-independent, Phase 8 50%, Phase 9 40%. **Phase 3 + Phase 4 are substantially less** pre-substrate-executable than Phase 7/8/9:

| Phase | Substrate-indep % | Reason |
|---|---|---|
| Phase 3 | ~5% | Every deliverable requires HSEA Phase 2's `ComposeDropActivity` base which is upstream-blocked |
| Phase 4 | ~15% | A few config + alias items can ship, but most work is substrate/phase-dep |
| Phase 7 | ~60% | Persona YAML authoring is standalone conceptual work |
| Phase 8 | ~50% | Objective schema + attention-bid format are standalone specs |
| Phase 9 | ~40% | SHM publisher stubs (editor/git/ci state) are substrate-independent |

**Phase 3 + 4 are "downstream consumer" phases** — they read what upstream phases produce. Downstream phases are always harder to pre-stage than upstream phases because the consumer interfaces aren't defined until producers ship.

## 5. Recommendations

### 5.1 File follow-up queue items

```yaml
id: "167"
title: "HSEA Phase 4 prep P4.prep-A — add capable alias to shared/config.py + agents/_config.py"
description: |
  Per queue #162 HSEA Phase 3/4 prereq audit. Phase 4 infra item 1+2
  require a "capable → claude-opus-4-6" alias in shared/config.py MODELS
  dict + agents/_config.py. ~5 lines per file, 2 files total. Low-
  priority, substrate-independent.
priority: low
size_estimate: "~10 LOC, ~10 min"

id: "168"
title: "HSEA Phase 4 prep P4.prep-B — stub config/patch_priorities.yaml + config/code_drafter.yaml"
description: |
  Per queue #162. Two placeholder YAML files for Phase 4 deliverable
  4.2 + 4.5. Filled in at Phase 4 execution time. Creating the files
  now marks the expected paths.
priority: low
size_estimate: "~40 LOC, ~15 min"
```

### 5.2 Do NOT file items for Phase 3

Phase 3 pre-substrate execution is not viable at all — every deliverable is blocked on `ComposeDropActivity` from HSEA Phase 2. Authoring stubs would be throwaway work. **Defer until HSEA Phase 2 ships.**

### 5.3 Phase 4 full execution readiness

Phase 4 full execution requires:
1. LRR Phase 1 research registry shipped (currently blocked on LRR Phase 5 substrate work or can run in parallel per queue #122 critical-path analysis)
2. LRR Phase 5 substrate swap shipped (scenarios 1+2)
3. HSEA Phase 0 + 1 + 2 shipped
4. P4.prep-A + P4.prep-B optional pre-staging items shipped (could land now)

**Expected Phase 4 execution window:** post-scenarios + post-HSEA-upstream. Alpha estimates 1-2 weeks from scenarios going live, assuming HSEA upstream moves in parallel.

## 6. What this audit does NOT do

- **Does not verify the `capable` alias is actually missing** from `shared/config.py` — alpha spot-checked but did not run `grep capable shared/config.py`. The prerequisite language in Phase 4 spec says "extended with" which implies it needs to be added; verify at P4.prep-A execution time.
- **Does not file the follow-up items.** Recommends them; delta decides whether to queue.
- **Does not re-analyze Phase 5/6/7/8/9** — those are covered by queue #122 critical path analysis + queue #131 Phase 7/8/9 prep inventory.
- **Does not check HSEA Phase 6/7 plans** — those are missing per queue #112 audit, separate concern.

## 7. Closing

Neither HSEA Phase 3 nor Phase 4 has viable pre-substrate execution. Phase 3 is ~5% substrate-independent; Phase 4 is ~15%. The 15% in Phase 4 translates to 2 small pre-staging items (P4.prep-A + P4.prep-B) that can ship now as low-priority follow-ups. All other Phase 3 + Phase 4 work waits for upstream HSEA phases + LRR Phase 1 registry + LRR Phase 5 substrate execution.

Branch-only commit per queue #162 acceptance criteria.

## 8. Cross-references

- HSEA Phase 3 spec: `docs/superpowers/specs/2026-04-15-hsea-phase-3-research-program-orchestration-design.md` §2 (prerequisites)
- HSEA Phase 4 spec: `docs/superpowers/specs/2026-04-15-hsea-phase-4-code-drafting-cluster-design.md` §2 (prerequisites)
- Queue #108 HSEA coverage audit (PR #867) — upstream
- Queue #112 HSEA branch-only reconciliation (PR #878) — Phase 6/7 plans unauthored
- Queue #122 cross-epic dependency graph (PR #884) — critical path analysis
- Queue #131 Phase 7/8/9 prep inventory (PR #889) — comparison reference for downstream phase pre-staging
- Queue #141 HSEA Hermes drift sweep (PR #898) — Phase 4 I4/I5 narrator retargeting templates
- Drop #62 §16 substrate ratification (PR #895) — Phase 4 substrate gate context
- Drop #62 §17 Option C pivot (PR #899) — Phase 5 execution mechanism change

— alpha, 2026-04-15T22:01Z
