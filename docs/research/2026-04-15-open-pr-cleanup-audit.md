# Open PR cleanup audit

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #119)
**Scope:** Review all open PRs on `ryanklee/hapax-council` and recommend action (merge, close, defer, fix-first) per PR. Captures the PR backlog state as of 2026-04-15T17:45Z for delta's coordinator tracking.
**Register:** scientific, neutral

## 1. Headline

**13 open PRs** as of 2026-04-15T17:45Z:

- **3 session-authored** (alpha/beta work-in-flight)
- **10 dependabot** (9 stale ≥5 days, 1 from last week)

Recommendations:

- **1 urgent merge** — PR #869 beta research drops cherry-pick (carries 9 items; unblocks downstream LRR Phase 10 + research drop availability)
- **1 trivial merge** — PR #864 operator activation runbook (MERGEABLE per last check; shipped by parallel session)
- **1 beta-owned rebase** — PR #819 `beta-phase-4-bootstrap` DRAFT + CONFLICTING; beta's session owns the resolve
- **10 dependabot triage** — merge cleanly (claude-code-action bumps), defer via operator judgment (framework bumps), or close as superseded

## 2. Session-authored PRs (3)

### PR #869 — beta cumulative research drops cherry-pick

- **Branch:** `feat/beta-research-drops-cumulative-cherry-pick`
- **Created:** 2026-04-15T17:42Z
- **State:** OPEN, MERGEABLE, `BLOCKED` (required checks pending)
- **Scope:** Cherry-picks 9 of beta's research drops from `beta-phase-4-bootstrap` to main: items #71 (substrate research v2), #74 (pattern-extraction meta-research), #75 (epsilon vs delta pre-staging comparison), #76 (second-perspective morning synthesis), #77 (cross-epic Prometheus cardinality pre-analysis), #79 (cross-epic integration smoke test design), #89 (self-consistency meta-audit), #90 (CLAUDE.md re-sync check), #91 (cadence analysis).

**Author:** ryanklee (likely a parallel session executing beta's queue item #88 — the consolidated cherry-pick PR).

**Recommendation:** **merge as soon as CI passes.** This is the primary unblocker for several downstream items:

- LRR Phase 10 continuation depends on beta's Phase 10 extraction landing on main
- The HSEA Phase 6/7 plan docs that `docs/research-cross-repo-rebase-audit.md` (PR #868) flagged as the remaining gap will be partially covered
- `beta-phase-4-bootstrap` itself becomes less dangerous to rebase once its cherry-pick content is on main

**Action:** wait for CI, then admin-merge. Parallel session is probably already monitoring it.

### PR #864 — LRR Phase 2 operator activation runbook (item #97)

- **Branch:** `docs/lrr-phase-2-operator-activation-runbook`
- **Created:** 2026-04-15T17:04:52Z
- **State:** OPEN, mergeable UNKNOWN (CI re-running)
- **Scope:** Operator activation runbook for LRR Phase 2 items #54 + #58 — the `systemctl --user enable --now audio-recorder.service` + `contact-mic-recorder.service` sequence with pre-check + rollback.

**Author:** ryanklee (parallel session, shipped during refill 7 while alpha was working #96 + #98 + #99).

**Recommendation:** **merge.** The content is complete + correct (alpha's queue item #97 disposition confirmed via parallel-session detection at refill 7 closure). Waiting on CI.

**Action:** CI-watch, then admin-merge if green.

### PR #819 — beta-phase-4-bootstrap (DRAFT)

- **Branch:** `beta-phase-4-bootstrap`
- **Created:** 2026-04-15T01:28:21Z
- **State:** DRAFT, `CONFLICTING` (per GitHub API)
- **Ahead/behind:** 34 ahead / 89 behind (per PR #868 cross-repo audit)
- **Scope:** The original beta session's Phase 4 bootstrap + overnight substrate research + Phase 6/7/10 extractions + protocol evaluation drop + consolidated audit + CLAUDE.md drift scan.

**Recommendation:** **beta-owned rebase.** Per PR #868 §7.2, alpha should NOT attempt this rebase:

- Beta's session has the cognitive context for beta's commits
- 47+ adjacent PRs landed on main touching beta's surface area (scripts/, agents/studio_compositor/, shared/, config/, systemd/units/)
- PR #855 already cherry-picked Phase 6/7 specs; rebase will see duplicates as conflicting adds
- PR #869 is now actively cherry-picking 9 more research drops, narrowing the conflict surface

**Action:** delta adds "rebase beta-phase-4-bootstrap onto origin/main" as a beta queue item after PR #869 merges. Beta's session picks it up on next watch. If beta's session has stood down (16:30Z last update), delta may need to escalate via inflection to operator.

## 3. Dependabot PRs (10)

### Recent (2026-04-10, 5 days old)

| PR | Title | Age | Recommendation |
|---|---|---|---|
| #642 | Bump `@types/vscode` 1.109.0 → 1.115.0 in /vscode | 5d | MERGE if CI green; vscode extension type updates, low risk |
| #641 | Bump `marked` 15.0.12 → 18.0.0 in /vscode | 5d | REVIEW — major version bump; check release notes for breaking changes |
| #640 | Bump `pnpm/action-setup` 4 → 6 | 5d | REVIEW — GitHub Action major version; check workflow compatibility |
| #639 | Bump `dependabot/fetch-metadata` 2 → 3 | 5d | REVIEW — GitHub Action major version; dependabot's own metadata fetcher |

### Older (2026-04-03, 12 days old — hapax-logos subdirectory)

| PR | Title | Age | Recommendation |
|---|---|---|---|
| #590 | Bump `recharts` 3.8.0 → 3.8.1 in /hapax-logos | 12d | MERGE if CI green; patch version, low risk |
| #589 | Bump `mermaid` 11.13.0 → 11.14.0 in /hapax-logos | 12d | MERGE if CI green; minor version, low risk |
| #588 | Bump `@tanstack/react-query` 5.90.21 → 5.96.2 in /hapax-logos | 12d | MERGE if CI green; 6 minor versions in one bump, run test suite |
| #587 | Bump `@types/node` 24.12.0 → 25.5.2 in /hapax-logos | 12d | MERGE if CI green; type-only, low risk |
| #586 | Bump `typescript-eslint` 8.57.1 → 8.58.0 in /hapax-logos | 12d | MERGE if CI green; dev dependency, low risk |
| #583 | Bump `anthropics/claude-code-action` 1.0.82 → 1.0.87 | 12d | MERGE if CI green; action version bump |

### Dependabot backlog pattern

All 10 dependabot PRs are from the last 5–12 days. None require alpha action beyond triage recommendations. The 4 major-version bumps (#641 marked, #640 pnpm/action-setup, #639 dependabot/fetch-metadata) are the only ones needing operator judgment before merge.

**Note:** there is no "dependabot PR close on supersede" policy in place. When dependabot opens a newer version PR (e.g., claude-code-action 1.0.92 supersedes 1.0.87), the older PRs become stale but don't auto-close. Operator should close superseded dependabot PRs during the next branch-audit sweep.

## 4. Missing from the audit

No PRs from epsilon on `ryanklee/hapax-council`. Epsilon's Pi fleet work lives in separate PRs on `pi-edge/` or in the `beta-phase-4-bootstrap` branch (via beta's session).

No PRs from delta. Delta is coordinator-only and does not ship PRs directly — delta's work is inflection writing + queue/ population + research drop authoring (committed directly to main in some cases).

## 5. Aggregate recommendations

### 5.1 Immediate (alpha can watch these through CI)

| PR | Action | Rationale |
|---|---|---|
| #869 | Wait for CI + admin-merge | Unblocks beta's research drop landing + narrows #819 rebase surface |
| #864 | Wait for CI + admin-merge | Item #97 already accepted by parallel session; just CI-gated |

### 5.2 Delta/operator queue items (not alpha's direct action)

| PR | Action | Who |
|---|---|---|
| #819 | Rebase + review + convert from DRAFT to READY | Beta's session (or delta add to beta refill) |
| #642 | Review + merge | Alpha can merge if `types/vscode` compat is obvious |
| #641 | Review + merge (major version) | Operator decides; check marked 16/17/18 changelogs |
| #640 | Review + merge (major version) | Operator decides; test pnpm workflow compatibility |
| #639 | Review + merge (major version) | Operator decides; test dependabot metadata action |
| #590, #589, #588, #587, #586, #583 | Batch merge if all CI-green | Operator can sweep in one operation |

### 5.3 Not-urgent cleanup

- Close any dependabot PRs that are superseded by newer PRs in the same dependency line
- Review the hapax-logos subdirectory backlog as a group (#587-#590) rather than per-PR

## 6. Cross-references

- Queue item #110 cross-repo rebase audit (`docs/research/2026-04-15-cross-repo-rebase-audit.md`, PR #868) — covers the branch state; this audit covers the PR state. The two are complementary.
- Queue item #119 (this audit) — specifically scopes to open PR triage recommendations
- Memory feedback: `feedback_branch_discipline.md`, `feedback_no_stale_branches.md`, `feedback_rebase_alpha_after_merge.md` — the protocol rules informing these recommendations
- PR #869 is the parallel session's execution of beta queue item #88 (cumulative cherry-pick)

## 7. Closing

The open PR surface is healthy: 3 session PRs (2 mergeable-soon, 1 DRAFT conflicting), 10 dependabot PRs (all in standard triage states, no bot health issues). The notable backlog is the hapax-logos dependabot subdirectory (~6 PRs ≥12 days old) which operator should sweep in a single batch operation when convenient.

No urgent close-recommendations. No stuck PRs blocking session work. The beta rebase (#819) is the only meaningful coordination concern, and it's correctly scoped to beta's session rather than alpha's.

Branch-only commit per queue item #119 acceptance criteria.

— alpha, 2026-04-15T17:45Z
