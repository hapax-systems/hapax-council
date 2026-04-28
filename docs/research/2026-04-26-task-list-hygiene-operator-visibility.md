# Task-list hygiene & operator workstream visibility — research drop

**Date**: 2026-04-26
**Author**: research agent (alpha-research lane)
**Scope**: how to impose task-list hygiene for operator workstream visibility across coordinated sessions (alpha/beta/delta/epsilon). Implementation is downstream.
**Reading budget**: 15 minutes.
**Constitutional binders**: `feedback_no_operator_approval_waits`, `feedback_never_stall_revert_acceptable`, `feedback_features_on_by_default`, `feedback_full_automation_or_no_engagement`, `feedback_no_stale_branches`, `feedback_claim_before_parallel_work`.

---

## 1. Operator pain surface (diagnostic, with vault citations)

Vault state at 2026-04-26 09:00Z (`~/Documents/Personal/20-projects/hapax-cc-tasks/active/`):

| Status        | Count | Note |
|---------------|-------|------|
| `offered`     | 173   | Vast majority created 2026-04-25 in burst; 6 still alive from 2026-03-13 (40-day-old). |
| `claimed`     | 10    | **9 of 10 are `assigned_to: unassigned`, `claimed_at: null`** — i.e., status drift from `migrated-from-native` import on 2026-04-15. They are *NOT* actually claimed. |
| `in_progress` | 0     | The dashboard's headline column is empty, despite real work shipping. |
| `pr_open`     | 0     | No tasks in `pr_open` state — meaning either no PRs, or transition to `pr_open` is unwired. |
| `superseded`  | 1     | Lone real-state transition. |
| `refused`     | 0     | Confirms operator's "0 refused" cited in directive — refusal pipeline is dormant. |

**Synthesis**: the vault's status field is a **lossy projection** of session reality. Sessions ship work via PRs and `cc-close`, but interstitial states (`claimed → in_progress → pr_open`) are silently bypassed. The operator literally cannot see which session is doing what RIGHT NOW because the only authoritative signal — `status: in_progress` — is empty.

**Eight specific blind spots** (ranked by operator-cost):

1. **What is alpha/beta/delta/epsilon doing right now?** No live "current claim per session" surface that's faster than reading 4 yaml files.
2. **Status drift on import**: 9 ghost-`claimed` tasks from 2026-04-15 hide real claims in dashboard noise.
3. **Bypass the cc-task pipeline**: many shipped commits have no cc-task at all (relay yamls and alpha/beta-to-* notes show heavy session activity, but `pr_open` count = 0).
4. **Stale relay yamls**: `~/.cache/hapax/relay/{alpha,beta,delta,epsilon}.yaml` `session_status.timestamp` can be stale; no automated check exists.
5. **Orphan PRs**: a session may have an open PR not linked to any cc-task (PR ↔ cc-task linkage is `cc-close --pr N`, *post-hoc*).
6. **WIP bloat invisible**: even if `in_progress` worked, no per-session WIP-limit enforcement.
7. **Offered-burst staleness**: 173 offered, 153 of which created in last 24h — operator can't tell which are dead-on-arrival.
8. **Refusal silence**: `feedback_full_automation_or_no_engagement` says refusal is constitutional, but `status: refused` count = 0. Either no surface ever gets refused (unlikely) or refusal state is unwired.

---

## 2. Diagnostic patterns — concrete check definitions

Each check is a **read-only sweeper** producing a hygiene event. Thresholds are starting points; tunable.

### 2.1 Stale-in-progress (heartbeat)

**Trigger**: vault note has `status: in_progress` AND (`updated_at` > 24h old OR no commit in last 24h on `branch` AND no PR activity on `pr` in last 24h).

**Threshold**: 24h hard, 6h soft (warning). Aligns with `watch_cadence: 270s` session pulse — stale if 24h is ~316 missed pulses.

**Check**: `git log --since=24h --oneline ${branch}` empty AND `gh pr view ${pr} --json updatedAt` > 24h ago.

### 2.2 Ghost-claimed (status-drift)

**Trigger**: `status: claimed` AND (`assigned_to: unassigned` OR `claimed_at: null`).

**Threshold**: any. This is a definitional violation; `cc-claim` cannot produce this state.

**Action**: auto-revert to `status: offered` + log to `_dashboard/cc-hygiene-events.md`.

### 2.3 Duplicate-claim (cross-session)

**Trigger**: two sessions' relay yamls list the **same `task_id`** in `current_claim` field within a 5-minute window.

**Threshold**: zero tolerance. Constitutional violation (`feedback_claim_before_parallel_work`).

**Action**: youngest claim wins, older session gets `dispatched-while-claimed` notification in its relay yaml.

### 2.4 Orphan-PR

**Trigger**: open `gh pr list` PR with branch in main repo AND no vault cc-task whose `pr` field equals that PR number.

**Threshold**: any open PR > 1h old without cc-task linkage.

**Action**: surface to operator; downstream agent decides retroactive `cc-link <pr> <task_id>`.

### 2.5 Relay-yaml staleness

**Trigger**: `~/.cache/hapax/relay/{role}.yaml` `last_updated` timestamp > 30 minutes ago.

**Threshold**: 30 min hard, 15 min soft. (Sessions running `watch_cadence: 270s` should refresh every 4.5 min; 30 min = 6+ missed pulses → session likely silent.)

### 2.6 WIP-limit violation

**Trigger**: a single session has > K tasks in `status: in_progress`.

**Threshold**: K=3 per Anthropic Claude Code parallel-session guidance and Vibe Kanban / Agent Kanban defaults (3-5 sweet spot).

**Action**: hygiene-event log; soft warning rather than hard block. Operator may temporarily lift via env var.

### 2.7 Offered-staleness (auto-archive)

**Trigger**: `status: offered` AND `created_at` > 14 days ago AND no `claimed_at` AND no `updated_at` newer than `created_at`.

**Threshold**: 14 days. Six tasks in vault already qualify (2026-03-13 cohort).

**Action**: auto-transition to `status: superseded` with annex `auto-archived-via-staleness`. Reversible (move from `closed/` back to `active/` re-classifies).

### 2.8 Refusal-pipeline-dormancy

**Trigger**: zero `status: refused` events in last 7 days AND `feedback_full_automation_or_no_engagement` in force.

**Threshold**: weekly. This isn't a violation per se — surfaces the *absence* of an expected signal.

---

## 3. Visibility surfaces — comparison & recommendation

| Surface | Single-glance? | Mobile? | Latency | Already in stack? | Best-fit |
|---|---|---|---|---|---|
| Vault Dataview dashboards | yes (in Obsidian) | poor (Obsidian mobile is read-only-feeling) | seconds (manual refresh) | yes | **deep-dive** when something looks wrong |
| Waybar widget | yes (status-bar real-estate) | n/a | seconds | yes | **ambient pulse** — colored dot per session + WIP count |
| Logos panel (Tauri) | yes | n/a | live (WS) | yes (existing panels) | **operator command surface** — link from dot to acting on it |
| ntfy push | one-shot text | yes (phone) | seconds | yes | **violation alerts only** (not steady state) |
| omg.lol weblog | public | yes | minutes | yes | **public-facing daily summary**; ABSOLUTE constraint: must be auto-only per `feedback_full_automation_or_no_engagement` |
| Terminal CLI (`hapax workstream`) | yes (when terminal is open) | n/a | seconds | partial | **diagnostic** for power-use; not steady-state |

**Recommendation**: layered surface, all on by default per `feedback_features_on_by_default`:

1. **Waybar widget** = primary ambient signal. Four dots (alpha/beta/delta/epsilon), color-coded green/amber/red by hygiene events, with WIP count next to each. Click → opens Logos panel.
2. **Logos panel** = synthesis surface. Lists current claim per session, hygiene-event log, action buttons (acknowledge / clear ghost / revert claim).
3. **Vault dashboard (`cc-hygiene.md`)** = source-of-truth deep-dive. Updated by sweeper.
4. **ntfy** = violation-grade alerts only (duplicate-claim, orphan-PR > 6h, session silent > 30 min).

**Counter-recommendation against omg.lol**: presents authorship indeterminacy publicly *before* the operator sees it. Defer until co-publishing flow stabilizes (per the constitutional 2026-04-25 directive).

---

## 4. Hygiene auto-actions

| # | Trigger (from §2) | Action | Reversibility | Refusal-brief if any |
|---|---|---|---|---|
| H1 | Ghost-claimed (§2.2) | Auto-revert to `offered`, log event | Reversible (the `cc-claim` re-stamps) | None — definitional cleanup |
| H2 | Stale in-progress > 24h (§2.1) | Auto-revert to `offered`, log event, ntfy operator | Reversible | None — aligned with `feedback_never_stall_revert_acceptable` |
| H3 | Duplicate claim (§2.3) | Youngest wins; older session relay-notified | Soft (older session can re-claim if elder ships nothing in 1h) | None |
| H4 | Orphan PR > 6h (§2.4) | ntfy operator; do **NOT** auto-link (low confidence) | n/a | Avoid auto-link: false-positive cost > value |
| H5 | Relay yaml stale > 30 min (§2.5) | Mark session yellow on waybar; if > 60 min, mark red + ntfy | Reversible (next pulse clears) | None |
| H6 | WIP > 3 (§2.6) | Soft warning only — log event, color session amber | n/a | Hard-block here would stall and `feedback_never_stall_revert_acceptable` says don't stall |
| H7 | Offered > 14 days (§2.7) | Auto-`superseded` with annex | Reversible (file move back) | None |
| H8 | Auto-link PR on `gh pr create` | PostToolUse hook sniffs `gh pr create` output, looks up active claim file, writes `pr: N` to vault note | Reversible (manual edit) | None — strict subset of `cc-close --pr` |
| H9 | Auto-close cc-task on PR merge | systemd timer scans `gh pr list --state merged` since last run, calls `cc-close <task_id> --pr N` for each | Reversible (cc-task can be reopened) | None — trusted because PR merge is a stronger commitment than session intent |

**Wired vs. unwired today**: H8 and H9 are not wired. `cc-close --pr N` exists as a CLI but no automation calls it on merge — that's the missing link explaining "0 in pr_open, 285 closed" mismatch.

---

## 5. Multi-agent prior art (highest-value 6, with citations)

1. **Claude Kanban** (alessiocol/claude-kanban) — hook-based enforcement, session state preservation, deterministic task coordination with WIP limits. Closest analog to vault SSOT pattern. ([github.com/alessiocol/claude-kanban](https://github.com/alessiocol/claude-kanban))
2. **Vibe Kanban** / **Agent Kanban** — orchestration boards with leader/worker split; "leader plans and assigns, workers claim and ship." Suggests our coordinator-less peer model is a roads-less-traveled choice; defensible but worth noting. ([vibekanban.com](https://vibekanban.com/), [agent-kanban.dev](https://agent-kanban.dev/))
3. **Heartbeat pattern** (MindStudio, Paperclip) — 15–30 min scheduled lightweight check is the canonical staleness-preventer. Aligns with our 270s `watch_cadence` (more aggressive than industry default). ([mindstudio.ai/blog/what-is-heartbeat-pattern-paperclip](https://www.mindstudio.ai/blog/what-is-heartbeat-pattern-paperclip-ai-agents))
4. **Anthropic field-notes worktree pattern** (issue #1052, claudefa.st task management) — multi-session task list **shared across sessions**, where Session A completes → Session B sees update immediately. Endorses our vault-SSOT direction. ([github.com/anthropics/claude-code/issues/1052](https://github.com/anthropics/claude-code/issues/1052), [claudefa.st task management](https://claudefa.st/blog/guide/development/task-management))
5. **Addy Osmani — Code Agent Orchestra** — kill-criteria principle: "if an agent is stuck for 3+ iterations on the same error, stop and reassign." Maps directly to our stale-in-progress (§2.1) check. ([addyosmani.com/blog/code-agent-orchestra/](https://addyosmani.com/blog/code-agent-orchestra/))
6. **GitHub orphan-branch / abandoned-PR cleanup actions** (Remove Stale Branches, Cleanup Stale Branches Action, GitHub Branch Cleaner) — cross-validate the orphan-PR (§2.4) and offered-staleness (§2.7) auto-archive patterns. ([Remove Stale Branches](https://github.com/marketplace/actions/remove-stale-branches), [Cleanup Stale Branches Action](https://github.com/marketplace/actions/cleanup-stale-branches-action))

**Single sentence synthesis**: industry consensus 2026 = **shared task list + heartbeat + WIP cap + auto-archive on staleness**. Our gap is automation of the heartbeat-driven sweepers, not the data model.

---

## 6. Refused options

| Pattern | Constitutional reason for refusal |
|---|---|
| **Operator-approval prompt before auto-revert** | Violates `feedback_no_operator_approval_waits` (sessions never wait) AND `feedback_never_stall_revert_acceptable` (revert is *preferred* to stall). |
| **Hard WIP-block (refuse to start work when WIP > 3)** | Stalls the session — `feedback_never_stall_revert_acceptable`. Use soft warning instead. |
| **Auto-link any open PR to nearest cc-task by heuristic** | False-positive risk. Operator gets a wrong-state vault and must manually correct. Defer to ntfy + human-in-loop for orphan-PR. |
| **Public-facing omg.lol live workstream summary** | Authorship-indeterminacy may surface publicly before operator sees it. Constitutional thesis (`feedback_co_publishing_auto_only_unsettled_contribution`) requires fully-Hapax-authored or refused; gate on automation maturity. |
| **Coordinator-agent / "leader" agent** | Vibe Kanban / Agent Kanban use leader-worker; our model is peer-relay. Switching would violate the established session-equality of alpha/beta/delta/epsilon. Refused on architectural-stability grounds. |
| **Email digest** | `feedback_full_automation_or_no_engagement` — email surfaces have unbounded operator attention cost, no automation wraparound. ntfy+waybar+Logos covers the same with bounded latency. |
| **Per-task SLA / due dates** | Imposes false urgency on a non-deadline-driven workstream. Operator's correction model is `feedback_grounding_exhaustive` — work is grounded by impingement, not by deadline. Refused. |
| **Full audit log replay UI** | Event-sourcing pattern requires projection to be human-useful (per Azure / Kurrent guidance). Cost > value for single-operator vault — projection is the dashboard, not the raw log. Audit log stays append-only in `_dashboard/cc-hygiene-events.md` but no separate UI. |

---

## 7. Implementation phases (5 PRs, sequenced)

WSJF estimate uses operator-typical 1-10 scale: business-value × time-criticality × risk-reduction / job-size.

### PR1 — `cc-hygiene-sweeper` daemon (foundation)

- **Owner**: alpha (cognitive lane; touches scripts/ and systemd timer)
- **WSJF**: 8.5 (high value: unblocks all visibility; medium-low job size: ~300 LOC bash + python; low risk: read-only sweeper)
- **Scope**: `scripts/cc-hygiene-sweeper.py` runs all 8 §2 checks, writes events to `~/Documents/Personal/20-projects/hapax-cc-tasks/_dashboard/cc-hygiene-events.md` (append-only) and machine-readable `~/.cache/hapax/cc-hygiene-state.json`. systemd timer every 5 min. Ships off auto-actions (read-only).
- **Depends on**: nothing. Foundation.

### PR2 — Auto-action wiring (H1, H2, H7)

- **Owner**: alpha (continuation)
- **WSJF**: 7.0 (medium-high value: clears ghost-state cruft; medium job: ~150 LOC; medium risk: vault rewrites)
- **Scope**: in same sweeper, wire H1 (ghost-claim revert), H2 (stale-in-progress revert), H7 (offered-staleness archive). All reversible. **All on by default per `feedback_features_on_by_default`**, env-var killswitch `HAPAX_CC_HYGIENE_OFF=1` for incident-only.
- **Depends on**: PR1.

### PR3 — `gh pr create` PostToolUse hook + merge auto-close (H8, H9)

- **Owner**: beta (research-pipeline; touches hooks dir + systemd)
- **WSJF**: 8.0 (high value: explains the 0-pr_open mystery; medium job: ~200 LOC; medium risk: hook touches existing flow)
- **Scope**: `hooks/scripts/cc-task-pr-link.sh` (PostToolUse on Bash with `gh pr create`); `scripts/cc-pr-merge-watcher.py` (5-min timer scanning merged PRs).
- **Depends on**: PR1 for hygiene-state.json shape.

### PR4 — Waybar `cc-status` module + Logos panel

- **Owner**: delta (engine/awareness — Tauri panel is in their lane)
- **WSJF**: 6.5 (high value but lower-criticality: visibility upgrade, not correctness; medium-large job: ~400 LOC across waybar config + Tauri component; low risk)
- **Scope**: read `cc-hygiene-state.json`, render 4-dot waybar widget (color + WIP count); Logos panel `WorkstreamHygieneView.tsx` shows session table + event log with action buttons.
- **Depends on**: PR1 (state file) + PR3 (auto-close so pr_open is non-trivially populated).

### PR5 — ntfy violation alerts + dashboard rewrite

- **Owner**: epsilon (publish bus — owns ntfy outbound)
- **WSJF**: 5.5 (medium value: alerts only fire on actual violations; medium job: ~200 LOC; low risk)
- **Scope**: hygiene events of `severity: high` (duplicate-claim, orphan-PR > 6h, session silent > 60 min) push to ntfy with `Priority: 4`. Vault `_dashboard/cc-active.md` rewritten to surface hygiene-state alongside Dataview tables.
- **Depends on**: PR1 + PR4.

**Sequencing note**: PR1 must merge first; PR2 and PR3 can parallel after PR1; PR4 and PR5 can parallel after PR3. Aligns with one-branch-per-session discipline (`feedback_branch_discipline`).

---

## 8. Cross-references to existing operator memories

- `feedback_no_operator_approval_waits` — drives all auto-action design (no prompts)
- `feedback_never_stall_revert_acceptable` — drives stale-revert policy
- `feedback_features_on_by_default` — all hygiene defaults ON
- `feedback_full_automation_or_no_engagement` — refused omg.lol surface
- `feedback_no_stale_branches` — orphan-PR detection complements existing `no-stale-branches.sh`
- `feedback_claim_before_parallel_work` — duplicate-claim detection enforces it
- `project_session_conductor` — existing 6-rule deterministic sidecar; hygiene sweeper composes with it (parallel surface, not replacement)
- `feedback_workflow_autonomy_concision` — heartbeats already lighter; this adds automation, not noise
- `feedback_verify_before_claiming_done` — H9 (auto-close on merge) is the deploy-verified version of `cc-close`

---

## 9. Five-line ntfy summary

```
Vault hygiene research drop 2026-04-26: 173 offered, 10 claimed (9 ghost), 0 in_progress, 0 pr_open — pipeline is lossy.
Plan: cc-hygiene-sweeper daemon (8 checks: ghost/stale/duplicate/orphan/relay-stale/WIP/offered-archive/refusal-dormancy) + 4 visibility surfaces (waybar/Logos/vault/ntfy).
5 sequenced PRs: foundation sweeper -> auto-actions -> PR-linkage hooks -> waybar+Logos -> ntfy. WSJF leader: PR1 at 8.5.
All defaults ON per features-on-by-default; reverts > stalls; no operator-approval prompts.
Refused: omg.lol public surface, coordinator-agent, hard WIP-block, due-dates, email digest, auto-PR-link heuristic. Doc: docs/research/2026-04-26-task-list-hygiene-operator-visibility.md
```
