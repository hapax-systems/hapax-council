# CC-Task Obsidian Source-of-Truth — Design

**Status:** draft
**Date:** 2026-04-20
**Author:** delta session (operator directive — enforcement + transparency research)
**Owner:** alpha (shipping surface)
**Motivating operator quote:**

> "We have an onboard task management and project planning system integrated with Obsidian (i think). Implemented awhile back. Research how to strictly enforce the usage of this system by Claude Code (ENFORCED STRICTLY) to drive and delegate work and make the state perfectly transparent to me by referencing obsidian (if it is in obsidian, honestly, might be wrong)."

## Summary

Consolidate all Claude-Code-driven work state into a single Obsidian vault folder. Current reality is fragmented across five stores (native CC TaskTool, relay YAML, Obsidian sprint/goal notes, handoff docs, memory files); the native TaskTool holds 219 items **invisible to the operator**. This spec moves canonical work state into `~/Documents/Personal/20-projects/hapax-cc-tasks/` as per-task markdown notes with structured frontmatter, uses the existing Obsidian Tasks + Dataview community plugins for operator-facing views, and enforces via a single PreToolUse hook that reads the vault directly. Relay YAML retires to an operator-ergonomic inbox; native CC TaskTool is deprecated.

Net new code: ~80 LOC hook + ~150 LOC migration script + vault template + dashboard notes. No new Logos API routes. No new long-running agents.

## Motivation

### Problems with the status quo

1. **Native CC TaskTool invisibility.** 219 tasks exist; operator cannot see them without opening Claude Code and running `/tasks`. Biggest transparency gap in the stack.
2. **Multiple write surfaces disagree.** Relay YAML, native tasks, handoff docs, and Obsidian goal notes each hold partial work state. When they drift, nobody knows which is canonical.
3. **No enforcement of task-claim-before-action.** Any session can edit/write code without first declaring what task it's working on. Audit trails depend on commit discipline alone.
4. **Obsidian sprint system is narrow.** Only covers R&D sprint measures/gates/goals — not the general CC workstream (governance, livestream, audio-topology, etc.).
5. **Near-miss discovery loop.** On 2026-04-20 operator asked whether content programming had been spec'd; alpha and operator both initially thought no, then discovered `2026-04-15-lrr-phase-8-content-programming-via-objectives-plan.md`. Without a unified index the same near-miss will recur.

### Why Obsidian

- Operator's single life-planning surface (goals, sprint measures, dailies, people notes already there).
- Plain-text markdown + YAML — git-backed, no lock-in, readable without Obsidian.
- Two mature plugins already widely deployed (Tasks, Dataview) solve the query/view layer at zero cost.
- Obsidian Local REST API already wired in this repo (`vault_context_writer.py`) — plumbing exists.
- Filesystem-as-bus is the house style (cf. council CLAUDE.md § Architecture).

### Why not build a custom Logos API route

An earlier research pass recommended a custom `/api/obsidian-tasks` endpoint (~400 LOC). Rejected because:

- Obsidian Tasks + Dataview plugins already render filterable dashboards from plain frontmatter — zero custom view code.
- Filesystem reads in the enforcement hook have no service dependency (no Logos-down failure mode).
- Fewer moving parts → fewer places for state to drift.

## Scope

### In scope

- New vault folder `20-projects/hapax-cc-tasks/` with one `.md` per work item.
- Frontmatter schema + vault template + migration script for the 219 native tasks.
- PreToolUse enforcement hook.
- Dataview dashboard notes (`cc-active.md`, `cc-offered.md`, `cc-blocked.md`, `cc-by-role.md`).
- SessionStart preamble update — sessions claim a task ID before any mutation tool use.
- Relay-YAML retirement plan (keeps YAML as ergonomic operator inbox, vault becomes canonical).
- Native-CC-TaskTool deprecation doc.
- Sync point: alpha's WSJF tracking migrates into task-note frontmatter `wsjf: <float>`.

### Out of scope

- Migrating sprint measures / goals (they're already in Obsidian under `20-projects/hapax-research/sprint/` and `20-projects/hapax-research/`; this spec adds a sibling folder, doesn't touch them).
- Touching `docs/superpowers/plans/` or `docs/superpowers/specs/` — plans stay in git (they're artifacts, not work items; task notes *link* to them).
- Multi-operator / role-based access (axiom `single_user` — one operator, one vault).
- Changing the memory system — `~/.claude/projects/.../memory/` stays as-is; it's a separate concern (agent learning, not task tracking).

## Design

### Vault layout

```
~/Documents/Personal/20-projects/hapax-cc-tasks/
  _dashboard/
    cc-active.md          # Dataview: in_progress by assigned_to
    cc-offered.md         # Dataview: offered + priority
    cc-blocked.md         # Dataview: blocked + reason
    cc-by-role.md         # Dataview: grouped by assigned_to
    cc-recent-closed.md   # Dataview: closed in last 7d
  active/                  # status in {offered, claimed, in_progress, pr_open, blocked}
    000214-d-05-ring2-phase-1.md
    000231-homage-scrim-epic-plan.md
    ...
  closed/                  # status in {done, superseded, withdrawn}
    000027-lrr-phase-0.md
    ...
```

File naming: `{padded-id}-{slug}.md`. ID is monotonic; slug is for human readability. Sessions address tasks by `task_id` (not slug) to survive renames.

### Frontmatter schema (canonical)

```yaml
---
type: cc-task
task_id: 231
title: HOMAGE-SCRIM epic plan
status: offered      # offered | claimed | in_progress | pr_open | blocked | done | superseded | withdrawn
assigned_to: unassigned   # unassigned | alpha | beta | delta | epsilon
priority: high       # critical | high | normal | low
wsjf: 11.0           # optional; alpha's WSJF score for ranking
depends_on: [229, 230]
blocks: []
branch: null         # set when claimed
pr: null             # set when pr_open
created_at: 2026-04-20T18:00:00Z
claimed_at: null
completed_at: null
updated_at: 2026-04-20T18:00:00Z
parent_plan: docs/superpowers/plans/2026-04-20-homage-scrim-epic.md  # optional
parent_spec: null
tags: [homage, scrim, livestream]
---
```

Body:

```markdown
# {title}

## Intent
One-paragraph why-this-matters.

## Acceptance criteria
- [ ] concrete success signal 1
- [ ] concrete success signal 2

## Session log
<!-- Each session appends on claim/update/close -->
- 2026-04-20T18:05Z alpha claimed (branch: feat/homage-scrim-epic-plan)
- 2026-04-20T19:12Z alpha pushed plan — PR #1120 opened

## Links
- Parent plan: [[parent_plan]]
- Related: [[000230-nebulous-scrim-research]]
```

Operator can edit any field by hand. The only field CC *must* own is `session log` (append-only) and the status machine transitions.

### Status state machine

```
         offered ─► claimed ─► in_progress ─► pr_open ─► done
            │         │            │             │
            │         └─► blocked ─┘             └─► blocked
            ├─► withdrawn (operator only)
            └─► superseded (links via `superseded_by`)
```

Transitions that CC is allowed to make autonomously: `offered→claimed→in_progress→pr_open→done`, plus any→`blocked`.
Transitions reserved to operator (hook rejects CC attempts): `withdrawn`, `superseded`, manual `offered` reset.

### Enforcement — single PreToolUse hook

`hooks/scripts/cc-task-gate.sh`:

1. Fires on PreToolUse for `Edit | Write | Bash` when the invoked command is one of: git-commit, git-push, pytest with `--write`-equivalent flags, or any file mutation.
2. Reads session role from `$CLAUDE_ROLE` env or `~/.cache/hapax/relay/{role}.yaml`.
3. Reads claimed task ID from `~/.cache/hapax/cc-active-task-{role}` (one-line file, written by CC via an allowed `Bash` echo when claiming).
4. Reads the task note from `~/Documents/Personal/20-projects/hapax-cc-tasks/active/{padded-id}-*.md`.
5. Parses frontmatter. Rejects unless `status == in_progress` AND `assigned_to == {role}`.
6. If task is `blocked`, exit with a clear message including the `blocked_reason` field if present.
7. If the hook can't find a claimed-task file, exit with a suggestion: run `cc-claim {id}` or browse `cc-offered.md`.

No network calls. No daemon. Pure filesystem. If Obsidian is closed, the hook still works — the vault is just a directory of markdown files.

### Session-facing helpers (thin wrappers, optional)

`~/.local/bin/cc-claim {task-id}` — atomic claim:
1. Read note, verify `status == offered`, `assigned_to == unassigned`.
2. Rewrite frontmatter to `status: claimed`, `assigned_to: {role}`, `claimed_at: <now>`.
3. Append session-log line.
4. Write `~/.cache/hapax/cc-active-task-{role}` with the task ID.
5. Prompt sessions to transition to `in_progress` at first file mutation (done automatically by a second invocation from inside the hook).

`~/.local/bin/cc-close {task-id} --pr N` — close out:
1. Verify task is currently in `pr_open` state, session is assignee.
2. Move note from `active/` → `closed/`, set `status: done`, `completed_at: <now>`.
3. Clear the `~/.cache/hapax/cc-active-task-{role}` file.

Both helpers are optional ergonomics — CC can do the same with direct file edits. The hook enforces state invariants regardless of helper use.

### Dashboards

`_dashboard/cc-active.md`:
```markdown
# CC — Active Tasks

## By Role

\`\`\`dataview
TABLE WITHOUT ID
  file.link as "Task",
  assigned_to as "Role",
  priority as "P",
  branch as "Branch",
  pr as "PR"
FROM "20-projects/hapax-cc-tasks/active"
WHERE status = "in_progress"
SORT priority DESC, wsjf DESC
\`\`\`

## Blocked

\`\`\`dataview
TABLE WITHOUT ID file.link as "Task", blocked_reason
FROM "20-projects/hapax-cc-tasks/active"
WHERE status = "blocked"
\`\`\`
```

Similar for other dashboards. Dataview refreshes on every vault tab-focus — no lag.

### Relay-YAML retirement

Relay YAML stays because:
- Operator hand-edits queue offers quickly without opening Obsidian.
- SessionStart hook `session-context.sh` already surfaces it in the CC preamble.

Changes:
- `PROTOCOL.md` updated — relay queue becomes an "inbox" whose items are mirrored into Obsidian by a 5-minute timer (new agent `agents/relay_to_cc_tasks.py`). Obsidian is the canonical store; relay is ergonomic write-surface.
- Session status files (`alpha.yaml`, `delta.yaml`, etc.) keep their current role — session-level meta, not per-task state.

### Native-CC-TaskTool deprecation

- A migration script reads the native task store (via an internal CC interface or a snapshot export — alpha to identify the path during Phase 2) and generates one `.md` per task in `active/` or `closed/` folder depending on state.
- After migration, sessions stop using `TaskCreate`/`TaskUpdate` for work items. A brief CLAUDE.md note: "Native `TaskCreate` is deprecated — create an Obsidian task note instead."
- Native TaskTool remains allowed for conversation-scoped todos (single-session ephemeral work) but not for cross-session workstream items.

## Build sequence (high-level — alpha will refine into a plan doc)

**Phase 1 — Vault scaffold** (1h): folder structure, frontmatter template (`50-templates/tpl-cc-task.md`), five dashboard notes with Dataview queries.

**Phase 2 — Migration script** (2h): `scripts/migrate_native_tasks_to_vault.py`. Reads current native task list, generates one note per task preserving IDs + status + parent-plan references. Dry-run first, inspect output, then commit.

**Phase 3 — Enforcement hook** (1.5h): `hooks/scripts/cc-task-gate.sh`, plus `cc-claim` / `cc-close` helpers in `~/.local/bin/`. Tested against 10 sample tasks in vault.

**Phase 4 — Session-start wiring** (1h): update `session-context.sh` to display claimed task from vault (replacing/augmenting current relay display).

**Phase 5 — Relay bridge** (1.5h): `agents/relay_to_cc_tasks.py` 5-min timer mirroring relay-YAML queue into vault notes.

**Phase 6 — Deprecation + docs** (1h): update `PROTOCOL.md`, `CLAUDE.md`, add CLAUDE.md memory entry linking to this spec. Announce deprecation of native TaskTool for workstream items.

**Phase 7 — Validation** (1h): manual E2E — operator edits a task to `status: blocked` in Obsidian, verify the next tool call in the assigned session is rejected with a clear message. Operator reverts → session resumes.

**Total effort: ~9h of focused work, one feature branch, one PR.**

## Test plan

Unit tests for the hook (shellcheck + real-file fixtures):
- Rejects tool use when no active task file.
- Rejects when task `status != in_progress`.
- Rejects when `assigned_to != $CLAUDE_ROLE`.
- Passes when status + role match.
- Handles missing `blocked_reason` gracefully.
- Handles vault-unavailable (disk error) with fail-closed rejection + clear operator-facing message.

Integration tests: run `cc-claim` then perform a file edit; verify allowed. Mutate vault note to `blocked` mid-session; verify next edit rejected.

Smoke test: operator opens Obsidian, views `cc-active.md`, sees exactly what each session is doing. Edits one task — sees CC comply within one tool call.

## Success criteria

- Operator opens Obsidian once and knows the complete state of all CC work across sessions.
- No CC session can mutate files without declaring a task ID that matches a vault note in `in_progress` state.
- Native CC TaskTool usage drops to zero for workstream items (inspected via CC audit logs or post-hoc task-file count).
- Operator can freeze any session's work by editing one frontmatter line — effect is immediate.
- No Obsidian plugin outside the already-installed Tasks + Dataview set required.

## Open questions (for alpha / operator review)

1. Should the migration script also import completed tasks (all 219), or only currently-pending ones? Suggest: all 219 — closed tasks become searchable history in `closed/`.
2. Should the `cc-claim` helper be a fish function or a standalone bash script? (Likely bash for cross-session compatibility.)
3. How to handle Canva / Gmail / side-tool calls in CC — do they need task gating too, or only destructive local work? Suggest: only Edit/Write/Bash (destructive local); read-only tools stay ungated.
4. Dataview plugin is community-maintained — acceptable dependency, or does axiom `executive_function` argue for a core-only plugin stack? (Delta's read: acceptable — Dataview is as load-bearing as Obsidian itself in this workflow.)
5. SessionStart preamble currently displays relay queue; should it also display the top 5 offered tasks by WSJF from vault? Suggest: yes, immediately actionable for a session picking up work.

## Non-goals

- Not a Kanban board. Task notes are free-form markdown; dashboards are query-driven, not draggable.
- Not a replacement for git PRs. Task notes reference PR numbers; PR discussion happens on GitHub.
- Not a time-tracker. `claimed_at` / `completed_at` are audit breadcrumbs, not effort estimates.

## References

- `~/Documents/Personal/` — existing vault; CLAUDE.md workspace-level mention
- `agents/vault_context_writer.py` — Obsidian REST API plumbing already in repo
- `agents/sprint_tracker.py` — frontmatter-YAML vault-write pattern to reuse
- `hooks/scripts/work-resolution-gate.sh` — hook structure to follow for `cc-task-gate.sh`
- `~/.cache/hapax/relay/PROTOCOL.md` — current relay protocol; to be updated in Phase 6
- Obsidian Tasks: https://publish.obsidian.md/tasks/
- Obsidian Dataview: https://blacksmithgu.github.io/obsidian-dataview/
