# `beta-phase-4-bootstrap` cherry-pick gap check (post PR #869)

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #165)
**Scope:** Classify all 63 branch-only commits on `beta-phase-4-bootstrap` by cherry-pick-worthiness + ship-readiness. Propose a targeted-not-batch cherry-pick strategy.
**Register:** scientific, neutral

## 1. Headline

**63 branch-only commits** on `beta-phase-4-bootstrap`. **~28 are beta's AWB research drops** (#203-#230 queue items). ~6 are already content-level-present on main via earlier targeted cherry-picks (PR #855/#886/#887/#901). The rest are Hermes-era pre-staging specs (superseded), code features (risky to cherry-pick while in-use), and coordination docs.

**Recommendation:** **do NOT ship a batch cherry-pick PR.** Per queue #163 disposition, PR #819 is the rolling workspace for beta's AWB output — batch cherry-picking would duplicate content between branch + main. Instead, propose **3 targeted cherry-pick queue items** for the highest-value branch-only research drops.

## 2. Method

```bash
cd ~/projects/hapax-council--beta
git log --format='%h %s' origin/main..HEAD > /tmp/beta-only-commits.txt
# 63 commits

# For key SHAs, verify content-level presence on main:
ls docs/research/2026-04-15-substrate-reeval-post-hermes.md  # → present (PR #901)
ls docs/research/2026-04-15-lrr-phase-6-0.5-block-patch.md   # → present (PR #886)
ls docs/superpowers/specs/*hsea-phase-6*                      # → present (PR #855)
```

## 3. Classification of 63 branch-only commits

### 3.1 Already content-level-present on main (6 commits)

These are on-branch by SHA but the content landed on main via other PRs:

| SHA | Subject | Landed via |
|---|---|---|
| `bb2fb27ca` | substrate research v1 post-Hermes | PR #901 queue #144 cherry-pick |
| `d33b5860c` | substrate research v2 errata | PR #901 queue #144 cherry-pick |
| `cda23c206` | LRR Phase 6 cohabitation drift reconciliation | extracted as standalone §0.5 patch via PR #886 queue #127 |
| `41dcebe94` | HSEA Phase 6 + 7 pre-staging extraction | PR #855 |
| `89283a9d1` | LRR Phase 10 pre-staging extraction | content on main via #128 runbook PR #887 (different form) |
| `793aa5818` | alpha LRR Phase 2 cadence analysis | PR #869 cumulative cherry-pick |

**Action:** none. These are already visible on main in one form or another.

### 3.2 Hermes-era pre-staging specs (SUPERSEDED, 10 commits)

Beta + others authored Phase 4/5/6 pre-staging specs on the branch with the Hermes-3 70B substrate framing. These are **structurally obsolete** per drop #62 §14 + §16 + §17 and have been superseded by main-branch counterparts:

| SHA | Subject | Superseded by |
|---|---|---|
| `35db6081c` | Phase 4 re-spec — livestream-only rule | Main has Phase 4 spec on main via different path |
| `3d9be7da9` | hoist research marker reader from director_loop | main director_loop already uses shared research_marker (confirmed by queue #164 audit) |
| `cd7add804` | DEVIATION-038 frozen-file coverage list | Branch-local DEVIATION-038 draft |
| `b0e6fbb1a` | DEVIATION-038 livestream-only rule | same |
| `faad34e16` | Phase 4 condition_id through voice grounding DVs | Live in director_loop on main via PR #839 equivalent |
| `327aced57` | CYCLE-2-PREREGISTRATION DEVIATION-038 | Branch-local |
| `4429a476e` | Phase 4 per-phase spec | Superseded by `docs/superpowers/specs/2026-04-15-lrr-phase-4-phase-a-completion-osf-design.md` on main |
| `b6b489efd` | lock-phase-a-condition.py | Branch-local script, would need separate cherry-pick if wanted |
| `ff18723e5` | check-phase-a-integrity.py | Branch-local script |
| `c82241e58` + `7aadac814` + `40daccc5b` + `83ec4f42e` + `18039c296` | Hermes-framed Phase 5 spec + DEVIATION-037 + scripts | **OBSOLETE per §14 + §16 + §17** — main has the substrate-scenario-1+2 spec via PR #896/#900 |
| `738fde330` + `156beef92` + `524127d93` | Phase 5 Option C reconciliation + RATIFIED flip + PR #826 xref | Historical — superseded by the re-spec on main |
| `c945b78f2` + `11a7eb81b` | Phase 6 spec + plan + design-language §12 stream-mode | Phase 6 belongs in cohabitation branch per queue #127 disposition |
| `391fe84d1` | apply drop #62 §10 Q2 + Q9 resolutions | Applied via queue #166 (PR #911) governance amendments |

**Action:** defer / do NOT cherry-pick. Content is either superseded by main-branch versions OR belongs in the cohabitation branch per protocol (Phase 6 spec).

### 3.3 Pi fleet + tabbyapi pre-staging (4 commits)

| SHA | Subject | Cherry-pick? |
|---|---|---|
| `bafd6b34f` | tabbyapi.service JIT warmup | **CANDIDATE** — warmup logic is useful + substrate-agnostic |
| `e24a2386c` | Pi fleet Thursday Pi 5 + Friday ReSpeaker deployment plan | **CANDIDATE** — actionable plan for near-term hardware arrival |
| `26016e094` | CLAUDE.md Pi fleet section + hapax-ai | **CANDIDATE** — CLAUDE.md update helps session context injection |
| `910e68448` | Pi fleet pre-staged scaffolding for hapax-ai + ReSpeaker | **CANDIDATE** — scaffolding is needed for Thursday/Friday hardware install |

**Action:** 4 candidates for a dedicated Pi fleet cherry-pick PR.

### 3.4 Beta's AWB research drops (~28 commits, queue #203-#230 range)

Ship-worthy but currently branch-only. Per queue #163 disposition, these should NOT be batch-cherry-picked.

**Highest-value candidates for targeted cherry-pick (alpha's selection):**

1. `7b77e5ad3` (beta #215 hapax-whoami edge case verification) — **already indirectly used** via queue #150 PR #904 (alpha's hardening)
2. `a52dafc87` (RIFTS harness schema fix) — **critical fix** for #159 review; should ship with the harness
3. `3a7672bd1` (RIFTS benchmark harness Phase 1) — **active scenario 1 execution vehicle** per queue #210; should ship so it's auditable on main
4. `954494ea5` (Prometheus observability for PresenceEngine feat) — **code feat** that extends the metrics registry; substrate-agnostic
5. `cb7573407` (CPAL loop latency profile) — valuable performance research

**Also worth considering:**
- `e82c32840` voice FX chain PipeWire verification
- `8a7d0e139` Kokoro 82M TTS memory footprint
- `5c9d6ad1e` Hermes weights disk cleanup inventory (tells operator what to clean up after §14 abandonment)
- `a5349edd8` PresenceEngine LR tuning (blocked-on-stale-watch-data finding)
- `02d9e9022` ReSpeaker Friday arrival prep

**Lower priority:**
- Beta queue #203-#208 (5 drops: pace audit, backends drift, identity retro, calibration audit, cherry-pick verification, beta index)
- Beta queue #217-#220 (session-internal audits)

### 3.5 Delta coordination docs on the branch (5 commits)

| SHA | Subject |
|---|---|
| `783964277` | consolidated delta pre-staging audit summary (Item #44) |
| `6d75f6255` | coordination protocol v1/v1.5 evaluation (Item #31) |
| `9515617ee` | CLAUDE.md drift scan (Item #63) |
| `cda23c206` | (see §3.1, already covered) |
| `833240188` | Prometheus condition_id cardinality pre-analysis (Item #77) |

**Action:** these are delta-authored research drops on beta's branch. They could ship via a delta cherry-pick PR, but the scope is less urgent. Defer unless delta specifically requests.

### 3.6 Other branch-only misc (~10 commits)

Remaining commits are substrate re-evaluation synthesis, LRR Phase 2 cadence work, HSEA integration docs, and epsilon/delta cross-session comparisons. Most are research-grade + ship-worthy but not urgent.

## 4. Summary table

| Class | Count | Cherry-pick action |
|---|---|---|
| Already content-on-main | 6 | none |
| Hermes-era obsolete specs | 10 | none |
| Pi fleet pre-staging | 4 | **propose dedicated cherry-pick PR** |
| Beta AWB research drops high-value | 5 | **propose targeted cherry-picks** |
| Beta AWB research drops medium-value | ~10 | defer; case-by-case |
| Delta coordination docs | 5 | defer |
| Other misc | ~10 | defer |
| Pre-reboot drafts | ~13 | defer |
| **Total** | **63** | |

## 5. Recommendations

### 5.1 Propose 3 targeted cherry-pick queue items

```yaml
id: "172"
title: "Cherry-pick Pi fleet pre-staging suite to main (4 commits)"
description: |
  Per queue #165 branch cherry-pick gap check. 4 commits on beta-
  phase-4-bootstrap provide Pi fleet deployment plan + hapax-ai
  scaffolding for the Thursday (Pi 5) + Friday (ReSpeaker) hardware
  arrival. Cherry-pick:
  - bafd6b34f tabbyapi JIT warmup
  - e24a2386c pi-fleet deployment plan
  - 26016e094 CLAUDE.md pi-fleet section
  - 910e68448 pi-fleet scaffolding for hapax-ai + ReSpeaker
  Conflicts possible on CLAUDE.md; resolve by keeping both main and
  beta content where applicable.
priority: normal
size_estimate: "~15 min cherry-pick + conflict resolution + PR"

id: "173"
title: "Cherry-pick RIFTS harness + schema fix to main (2 commits)"
description: |
  Per queue #165 + #159 review. Beta's RIFTS harness is actively
  running via queue #210 but lives only on beta-phase-4-bootstrap.
  Cherry-pick 3a7672bd1 (harness Phase 1) + a52dafc87 (schema fix)
  to main so the scenario 1 execution vehicle is auditable on main.
  This unblocks alpha's #159 review follow-ups (the code referenced
  in the review inflection lives only on branch).
priority: normal
size_estimate: "~15 min cherry-pick + smoke test + PR"

id: "174"
title: "Cherry-pick PresenceEngine Prometheus feat + CPAL latency research"
description: |
  Per queue #165. 2 high-value beta AWB outputs to cherry-pick:
  - 954494ea5 (feat(presence): Prometheus observability — code feat
    that extends #132 metrics registry inventory)
  - cb7573407 (docs(research): CPAL loop latency profile)
  Both are substrate-agnostic + ship-ready.
priority: low
size_estimate: "~15 min cherry-pick + PR"
```

### 5.2 Do NOT propose

- **Batch cherry-pick PR** of all 28 beta research drops — bypasses the rolling-workspace framing per queue #163
- **Cherry-pick of Hermes-era Phase 5 specs** — superseded by main-branch versions per §14 + §16 + §17
- **Cherry-pick of DEVIATION-038 drafts** — in-progress, may need beta re-authorship post-§16

### 5.3 Leave on branch

The remaining ~40 commits stay on `beta-phase-4-bootstrap` as beta's workspace content. PR #819's "rolling workspace" framing remains intact.

## 6. What this audit does NOT do

- **Does not execute any cherry-picks.** Proposes 3 targeted items.
- **Does not diff file content** between branch + main for each of the 63 commits — only classifies by commit message + SHA presence.
- **Does not verify my queue #144 cherry-pick** produced semantically-identical content to `bb2fb27ca` + `d33b5860c` — only confirms files exist on main.
- **Does not identify conflicts** ahead of cherry-pick — execution session will discover them.

## 7. Closing

63 branch-only commits classified. ~6 already content-level-present on main. ~10 Hermes-era obsolete. ~4 Pi fleet candidates. ~5 beta AWB high-value candidates. The rest are medium/low priority and should stay on the rolling workspace. Proposed 3 targeted cherry-pick queue items (#172, #173, #174) rather than a batch cherry-pick PR.

Branch-only commit per queue #165 acceptance criteria.

## 8. Cross-references

- PR #869 (commit `4e42b46e5`): previous cumulative beta cherry-pick
- PR #901 (queue #144): substrate research v1 + errata cherry-pick
- PR #886 (queue #127): LRR Phase 6 §0.5 reconciliation extract
- PR #855: HSEA Phase 6 + 7 spec extraction (beta-authored)
- PR #896 (queue #138): LRR Phase 5 re-spec supersedes Hermes-framed spec on branch
- PR #900 (queue #143): LRR Phase 5 plan supersedes Hermes-framed plan on branch
- PR #819 disposition: queue #140 (keep open as rolling workspace) + queue #163 (refined framing)
- Queue #159 RIFTS harness review — depends on cherry-picking the harness to main
- Queue #163 PR #819 disposition — sets the "rolling workspace, not deliverable PR" framing
- `beta-phase-4-bootstrap` — the 63-commit workspace branch

— alpha, 2026-04-15T22:13Z
