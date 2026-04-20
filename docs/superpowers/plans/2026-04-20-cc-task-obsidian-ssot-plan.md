# CC-Task Obsidian Source-of-Truth — Implementation Plan

**Status:** ready-to-execute
**Date:** 2026-04-20
**Author:** alpha (refining delta's spec)
**Owner:** alpha (zone)
**Spec:** `docs/superpowers/specs/2026-04-20-cc-task-obsidian-ssot-design.md`
**WSJF:** 4.3 (D-30 in WSJF master table — P0 structural fix)
**Branch:** trio-delivery direct-to-main (per existing burst pattern), or `feat/cc-task-obsidian-ssot` if scope grows
**Total effort:** ~9h focused work

## 0. Why this plan exists

The 2026-04-20 total-workstream gap audit identified **3 systemic patterns**
producing the recurring near-miss failure mode operator flagged:

1. Plans live, queue does not refer back
2. Research-doc-without-plan treated as planning
3. Operator queues fragment across surfaces (WSJF D-NN + alpha.yaml OQ-NN +
   scattered task #NN with no canonical join)

This plan is the **structural fix** for misses #1 + #3 — it makes the
operator's existing Obsidian vault the canonical work-state surface, with
strict CC enforcement so no session can mutate files without declaring a
task that the operator can see.

## 1. Pre-flight

Before Phase 1 starts:

- [ ] Verify `~/Documents/Personal/` vault exists + is writable
- [ ] Verify Obsidian Tasks + Dataview plugins are installed (per spec §Why
      Obsidian — already operator-deployed)
- [ ] Verify `agents/vault_context_writer.py` Obsidian REST API plumbing
      still works (`uv run python -m agents.vault_context_writer --dry-run`)
- [ ] Verify `~/.cache/hapax/relay/` is the canonical relay store
- [ ] Confirm SSOT plan docs/superpowers/plans path is the right home for
      this plan (it is — established convention)

Operator-decision items from spec §Open questions to lock before Phase 2:

- [ ] Q1 — migration imports all 219 tasks (closed too) or only pending?
      **Spec recommendation: all 219.** Default to that absent override.
- [ ] Q2 — `cc-claim` helper as fish function or bash script?
      **Spec recommendation: bash.** Default.
- [ ] Q3 — gate on read-only tools too, or only destructive (Edit/Write/Bash)?
      **Spec recommendation: only destructive.** Default.
- [ ] Q4 — Dataview as acceptable community-plugin dependency? **Spec
      recommendation: acceptable.** Default.
- [ ] Q5 — SessionStart preamble shows top-5 offered tasks by WSJF?
      **Spec recommendation: yes.** Default.

Operator-author override on any answer flips the corresponding default at
Phase entry.

## 2. Phase 1 — Vault scaffold (1h)

### 2.1 Tasks

**T1.1** Create folder structure:

```
~/Documents/Personal/20-projects/hapax-cc-tasks/
  _dashboard/
  active/
  closed/
```

**T1.2** Write frontmatter template at
`~/Documents/Personal/50-templates/tpl-cc-task.md` with the canonical
schema from spec §Frontmatter schema (lines 88-108). Include the
`type: cc-task` discriminator so Dataview queries can scope by type.

**T1.3** Write five dashboard notes to `_dashboard/`:
- `cc-active.md` — in_progress by assigned_to (spec §Dashboards)
- `cc-offered.md` — offered + priority sorted by wsjf desc
- `cc-blocked.md` — blocked + reason
- `cc-by-role.md` — grouped by assigned_to
- `cc-recent-closed.md` — closed in last 7d (Dataview `WHERE
  date(completed_at) > date(today) - dur(7 days)`)

**T1.4** Write `_dashboard/cc-readme.md` documenting the schema, the state
machine, and how the operator interprets each dashboard.

### 2.2 Exit criterion

`ls ~/Documents/Personal/20-projects/hapax-cc-tasks/_dashboard/` returns
all 5 dashboard notes + readme. Opening Obsidian → switching to one of the
dashboard notes shows an empty Dataview table (because no task notes exist
yet) without errors.

### 2.3 Commit

```
chore(vault): hapax-cc-tasks scaffold (Phase 1 of CC-task Obsidian SSOT)
```

Vault changes are NOT in the council git repo (the vault is the
operator's personal vault). Commit happens at the next vault-sync
checkpoint per operator's existing Obsidian Sync workflow.

## 3. Phase 2 — Migration script (2h)

### 3.1 Tasks

**T2.1** Identify the native-CC-TaskTool snapshot path. Most likely
either:
- `~/.claude/projects/<sanitized-cwd>/tasks/*.json`
- A snapshot in `~/.claude/projects/<sanitized-cwd>/conversations/<uuid>.jsonl`
  with embedded task records

Run `find ~/.claude/projects -type f -newer /tmp -mtime -1 | head -10` and
inspect to confirm the on-disk format. Document the path in
`scripts/migrate_native_tasks_to_vault.py:DOCSTRING`.

**T2.2** Write `scripts/migrate_native_tasks_to_vault.py`:

- Read native task records from the path identified in T2.1.
- For each task, generate one `.md` per the canonical frontmatter schema.
- Status mapping: `pending` → `offered`; `in_progress` → `claimed`;
  `completed` → `done`; `cancelled` → `withdrawn`.
- Place active records in `active/`, terminal records in `closed/`.
- Preserve task IDs (use existing native ID, padded to 6 digits).
- `--dry-run` flag prints what would be written; `--apply` performs the
  write.
- Idempotent: re-running on top of existing vault notes is a no-op (skip
  files that already exist; document this so the operator can't
  accidentally overwrite hand-edits).

**T2.3** Tests at `tests/scripts/test_migrate_native_tasks.py`:

- Fixture: 5 synthetic native task records spanning all status values.
- Run migration with `--apply` against `tmp_path`.
- Assert: 5 `.md` files generated, frontmatter parses, status mapping
  correct, IDs preserved.
- Assert: re-running is a no-op (no overwrite).
- Assert: `--dry-run` writes nothing.

### 3.2 Exit criterion

`uv run python scripts/migrate_native_tasks_to_vault.py --apply` produces
one `.md` per native task in `~/Documents/Personal/20-projects/hapax-cc-tasks/{active,closed}/`.
Operator opens Obsidian, sees populated dashboards.

### 3.3 Commit

```
feat(scripts): migrate native CC tasks to Obsidian vault (Phase 2)
```

## 4. Phase 3 — Enforcement hook (1.5h)

### 4.1 Tasks

**T3.1** Write `hooks/scripts/cc-task-gate.sh`:

- PreToolUse hook for `Edit`, `Write`, and `Bash` (when Bash command
  matches `git commit`, `git push`, or any `>` redirect).
- Read session role from `$CLAUDE_ROLE` env, fallback to inferring from
  `~/.cache/hapax/relay/{role}.yaml` (single relay file present →
  unambiguous role).
- Read claimed task ID from `~/.cache/hapax/cc-active-task-{role}` — one
  line, integer.
- Locate task note: `~/Documents/Personal/20-projects/hapax-cc-tasks/active/{padded-id}-*.md`
  via glob.
- Parse frontmatter (use `python3 -c "import yaml,sys; ..."` for
  robustness; the bash-yaml dance is fragile).
- Reject unless `status == in_progress` AND `assigned_to == {role}`.
- Reject with operator-clear message including the task ID, current
  status, and a hint at `cc-claim {id}` if no claim file exists.
- Special case: `blocked` status → reject with `blocked_reason` from
  frontmatter if present.

**T3.2** Write `~/.local/bin/cc-claim` and `~/.local/bin/cc-close`
helpers per spec §Session-facing helpers. Both atomic-edit the
frontmatter via tmp+rename.

**T3.3** Tests at `tests/hooks/test_cc_task_gate.sh` (shellcheck +
fixture vault):

- Fixture: 4 tasks (1 in_progress assigned to alpha, 1 offered, 1
  blocked, 1 done).
- Cases: rejects when no claim file; rejects when claimed task is offered;
  rejects when claimed-but-wrong-role; rejects with reason on blocked;
  passes when status+role match; fails-closed on vault-unreadable.

**T3.4** Register the hook in council settings.json:

```jsonc
{
  "permissions": {
    "hooks": [
      {
        "match": "PreToolUse",
        "tools": ["Edit", "Write", "Bash"],
        "command": "hooks/scripts/cc-task-gate.sh"
      }
    ]
  }
}
```

Note: hook is OFF by default (commented out) until Phase 7 validation.

### 4.2 Exit criterion

`bash hooks/scripts/cc-task-gate.sh` against fixture vault returns
correct exit code for each of the 6 test cases. shellcheck passes
clean.

### 4.3 Commit

```
feat(hooks): cc-task-gate enforcement hook + cc-claim/cc-close helpers (Phase 3)
```

## 5. Phase 4 — Session-start wiring (1h)

### 5.1 Tasks

**T4.1** Update `hooks/scripts/session-context.sh` to display:
- Currently-claimed task (from `~/.cache/hapax/cc-active-task-{role}`)
- Top 5 offered tasks by WSJF (from vault `active/` notes with
  `status: offered`, sorted by `wsjf` descending)
- Dashboard reminder: "Operator dashboard: open Obsidian → 20-projects/
  hapax-cc-tasks/_dashboard/cc-active"

**T4.2** Tests against synthetic fixture vault:
- Assert claimed task surfaces with correct title.
- Assert top-5-offered list is wsjf-sorted.
- Assert no-claim case shows the dashboard hint, not an error.

### 5.2 Exit criterion

Restart a session — the SessionStart preamble shows the operator's
dashboard pointer + claimed task (or empty + offered list if no claim).

### 5.3 Commit

```
feat(hooks): session-context displays vault-canonical task state (Phase 4)
```

## 6. Phase 5 — Relay bridge (1.5h)

### 6.1 Tasks

**T5.1** Write `agents/relay_to_cc_tasks.py`:
- 5-min systemd-timer-driven mirror.
- Reads `~/.cache/hapax/relay/{alpha,beta,delta,epsilon}.yaml`.
- For each `active_queue_items[]` entry, generate or update a vault task
  note. Mapping: queue-item title → task title; `assigned_to` from the
  yaml file's session name; `status: offered`.
- Idempotent (existing notes update mtime + status only; don't
  overwrite operator hand-edits to body).

**T5.2** Systemd unit `systemd/units/hapax-relay-to-cc-tasks.{service,timer}`:
- Timer 5min cadence
- Service runs `uv run python -m agents.relay_to_cc_tasks`
- ntfy on failure

**T5.3** Tests at `tests/agents/test_relay_to_cc_tasks.py`:
- Fixture relay yaml + tmp_path vault.
- Assert mirror creates task notes for queue items.
- Assert re-run is idempotent on hand-edited body.

### 6.2 Exit criterion

`systemctl --user start hapax-relay-to-cc-tasks` produces vault notes
for every relay queue item; 5-min timer shows up in `systemctl --user
list-timers`.

### 6.3 Commit

```
feat(agents): relay-yaml → cc-tasks vault bridge + systemd timer (Phase 5)
```

## 7. Phase 6 — Deprecation + docs (1h)

### 7.1 Tasks

**T6.1** Update `~/.cache/hapax/relay/PROTOCOL.md`:
- Document that Obsidian vault is the canonical work-state surface.
- Relay yaml is now the operator's ergonomic inbox (still valid for
  hand-editing offers).
- Per-task state lives in vault notes, not in `active_queue_items[]`.

**T6.2** Update `CLAUDE.md` (workspace) + `hapax-council/CLAUDE.md`:
- Add § "CC Task Tracking" pointing at the vault folder + dashboards.
- Note: native `TaskCreate` is deprecated for cross-session work; use
  `cc-claim {id}` + vault notes instead. Native TaskCreate remains
  permitted for single-session ephemeral todos.

**T6.3** Add memory entry in `~/.claude/projects/-home-hapax-projects/memory/`:
- `reference_cc_task_vault.md` — points at the vault path + dashboards
  + spec/plan refs.

### 7.2 Exit criterion

`grep -r "TaskCreate" docs/superpowers/plans/ docs/superpowers/specs/`
returns no recommendations to use it for new work. CLAUDE.md sections
exist + render cleanly. MEMORY.md has the new reference link.

### 7.3 Commit

```
docs(ssot): deprecate native TaskTool for workstream items (Phase 6)
```

## 8. Phase 7 — Validation (1h)

### 8.1 Tasks

**T7.1** Manual end-to-end smoke:
- Operator opens Obsidian, browses `_dashboard/cc-active.md`. Verifies
  current claimed task surfaces.
- Operator hand-edits one active task to `status: blocked` with
  `blocked_reason: "operator paused for review"`.
- Within next CC tool call in that session, expect the hook to reject
  with the operator-readable blocked message.
- Operator reverts the edit. Verify next tool call succeeds.

**T7.2** Hook activation: flip the cc-task-gate hook from commented-out
to live in council `settings.json`. Restart sessions.

**T7.3** Verify all 4 sessions (alpha/beta/delta/epsilon) onboard
correctly post-activation: each session reads its claim file or sees
the offered-list hint.

### 8.2 Exit criterion

The smoke test passes end-to-end. Hook is live in production. Operator
confirms they can see all CC work in Obsidian without opening Claude
Code.

### 8.3 Commit

```
feat(hooks): activate cc-task-gate enforcement (Phase 7 — SSOT live)
```

## 9. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Native task path schema changes between CC versions | M | Migration breaks | Phase 2 dry-run + inspection step catches before write |
| Vault on different filesystem than ~/.cache | L | Hook race / partial writes | Hook reads tmpfs cache file, then atomic vault read; both are POSIX-fsync-safe |
| Operator forgets dashboard exists | M | Defeats the structural fix | SessionStart preamble surfaces it on every cold-start |
| Dataview plugin removal | L | Dashboards stop rendering | Markdown body still readable; Dataview is community plugin so Obsidian itself isn't load-bearing |
| Hook adds latency to every Edit/Write | L | Annoying | Pure-filesystem hook: <10ms per call; bounded by single yaml parse |
| Vault sync conflict | M | Hand-edit lost mid-session | Obsidian Sync handles conflicts; helper scripts use atomic tmp+rename |

## 10. Acceptance criteria (single-PR)

All checkboxes from spec §Success criteria + this plan's per-phase exit
criteria must pass:

- [ ] Operator opens Obsidian once and knows the complete state of all CC work
- [ ] No CC session can mutate files without declaring a task ID matching
      a vault note in `in_progress` state (verified by Phase 7 smoke)
- [ ] Native CC TaskTool usage is deprecated for workstream items
      (CLAUDE.md note + grep audit)
- [ ] Operator can freeze any session by editing one frontmatter line
      (Phase 7 smoke)
- [ ] No new Obsidian plugin dependency beyond Tasks + Dataview
- [ ] All 7 phase commits land in chronological order on a single
      feature branch (or main per trio-delivery convention)
- [ ] WSJF doc updated to mark D-30 SHIPPED with the merge SHA

## 11. Sequencing relative to other in-flight work

- **Does NOT block** OQ-02 Phase 2 (test harness) — orthogonal axis.
- **Does NOT block** HSEA Phase 0 — different epic.
- **DOES block** D-29 (HOMAGE Ward umbrella plan) and D-31 (8-spec triage)
  if those try to track work without using the SSOT — they should land
  AFTER this so they get vault task notes from day one.
- **Does NOT block** the producer-side D-01 voice-tier wire (delta).

Recommend alpha ships this BEFORE picking up D-28 (programme-layer plan
audit) so the audit's findings get filed as vault tasks rather than
WSJF-D-NN drift.

## 12. References

- Spec: `docs/superpowers/specs/2026-04-20-cc-task-obsidian-ssot-design.md`
- Gap audit: `docs/research/2026-04-20-total-workstream-gap-audit.md` §6
- WSJF doc: `docs/superpowers/handoff/2026-04-20-delta-wsjf-reorganization.md`
  D-30 row
- Existing vault plumbing: `agents/vault_context_writer.py`,
  `agents/sprint_tracker.py`, `agents/obsidian_sync.py`
- Hook structure to mirror: `hooks/scripts/work-resolution-gate.sh`
