# Gemini ↔ Claude Hook Drift Check + Sync

**Queue:** #173
**Author:** alpha
**Date:** 2026-04-15
**Files touched:** `~/.claude/settings.json`, `~/.gemini/settings.json` (instance-local, not repo-tracked)
**Action:** drift documented + remediation applied in-place; this doc records the diff and rationale.

---

## §0. TL;DR

Two gemini-side gaps found and fixed:

1. **HIGH — relay-coordination-check missing from gemini BeforeTool.** Without it, a gemini session editing files in the council repo bypasses the relay protocol coordination gate that alpha + beta already run. Shipped: added to `~/.gemini/settings.json` with `replace|write_file` matcher.
2. **LOW — docs-only-pr-warn missing from gemini BeforeTool.** Cosmetic advisory about docs-only PRs. Shipped: added to `~/.gemini/settings.json` with `run_shell_command` matcher.

One claude-side gap found and fixed:

3. **CLEANUP — orphaned empty matcher in `~/.claude/settings.json`.** An entry with matcher `Bash|mcp__github__create_pull_request|mcp__github__merge_pull_request|mcp__github__push_files` had an empty `hooks: []` array — no-op residue from a prior removal that didn't clean up the matcher. Shipped: stripped via `jq '.hooks.PreToolUse |= map(select(.hooks | length > 0))'`. Entry count 13 → 12.

Post-sync parity: 12 PreToolUse entries in Claude, 12 BeforeTool entries in Gemini. Full coverage of the 10 real hook scripts (+ conductor-pre which spans both Bash and file-edit tool classes).

---

## §1. Method

1. Read `~/.claude/settings.json .hooks.PreToolUse` and `~/.gemini/settings.json .hooks.BeforeTool`.
2. Normalised each to a `(matcher, command-basename)` set.
3. Compared sets.
4. Noted the event-category name mismatch (PreToolUse vs BeforeTool; Stop vs SessionEnd).
5. Checked `gemini hooks migrate --help` — only flag is `--from-claude`, no dry-run mode. Did NOT run it (would be a write action and I wanted to stage the diff explicitly).
6. Backed up both files to `/tmp/{claude,gemini}-settings-backup.json`.
7. Applied the diff via jq in-place.
8. Verified post-count.

---

## §2. Pre-sync state

### §2.1. Claude `.hooks.PreToolUse` (13 entries, 12 with commands + 1 orphan)

| Matcher | Hook script |
|---------|-------------|
| Bash | axiom-commit-scan.sh |
| Edit\|Write\|MultiEdit\|NotebookEdit | axiom-scan.sh |
| Bash | branch-switch-guard.sh |
| Edit\|Write\|MultiEdit\|Bash\|NotebookEdit | conductor-pre.sh |
| Bash | docs-only-pr-warn.sh |
| Bash | no-stale-branches.sh |
| Edit\|Write\|MultiEdit\|NotebookEdit | pii-guard.sh |
| Bash | pip-guard.sh |
| Edit\|Write\|MultiEdit\|NotebookEdit | registry-guard.sh |
| Edit\|Write\|MultiEdit\|NotebookEdit | relay-coordination-check.sh |
| Bash | safe-stash-guard.sh |
| Edit\|Write\|MultiEdit\|NotebookEdit | work-resolution-gate.sh |
| **Bash\|mcp__github__create_pull_request\|mcp__github__merge_pull_request\|mcp__github__push_files** | **(empty hooks array — orphan)** |

### §2.2. Gemini `.hooks.BeforeTool` (10 entries, all with commands)

| Matcher | Hook name |
|---------|-----------|
| run_shell_command | axiom-commit-scan |
| replace\|write_file | axiom-scan |
| run_shell_command | branch-switch-guard |
| replace\|write_file\|run_shell_command | conductor-pre |
| run_shell_command | no-stale-branches |
| replace\|write_file | pii-guard |
| run_shell_command | pip-guard |
| replace\|write_file | registry-guard |
| run_shell_command | safe-stash-guard |
| replace\|write_file | work-resolution-gate |

---

## §3. Drift analysis

### §3.1. Event-category name mapping (INFORMATIONAL, not a drift)

| Concept | Claude field | Gemini field |
|---------|--------------|--------------|
| Before tool call | `PreToolUse` | `BeforeTool` |
| After tool call | `PostToolUse` | `AfterTool` |
| Session start | `SessionStart` | `SessionStart` |
| Session end | `Stop` | `SessionEnd` |

These are not drifts — they are the documented mapping between the two hook APIs. Gemini CLI 0.38.1's `gemini hooks migrate --from-claude` subcommand is built around this exact mapping.

### §3.2. Matcher name mapping

| Claude matcher | Gemini matcher |
|----------------|-----------------|
| `Bash` | `run_shell_command` |
| `Edit` / `Write` / `MultiEdit` / `NotebookEdit` | `replace` / `write_file` |

Both adapter-side invocations route through `hooks/scripts/gemini-tool-adapter.sh` which normalises gemini's tool input format into claude's (so the underlying hook script does not need to know which runtime is calling it).

### §3.3. Hook script drift

| Hook script | Claude | Gemini pre-sync | Gemini post-sync |
|-------------|--------|------------------|-------------------|
| axiom-commit-scan.sh | ✓ | ✓ | ✓ |
| axiom-scan.sh | ✓ | ✓ | ✓ |
| branch-switch-guard.sh | ✓ | ✓ | ✓ |
| conductor-pre.sh | ✓ | ✓ | ✓ |
| **docs-only-pr-warn.sh** | ✓ | **MISSING** | ✓ (added) |
| no-stale-branches.sh | ✓ | ✓ | ✓ |
| pii-guard.sh | ✓ | ✓ | ✓ |
| pip-guard.sh | ✓ | ✓ | ✓ |
| registry-guard.sh | ✓ | ✓ | ✓ |
| **relay-coordination-check.sh** | ✓ | **MISSING** | ✓ (added) |
| safe-stash-guard.sh | ✓ | ✓ | ✓ |
| work-resolution-gate.sh | ✓ | ✓ | ✓ |

### §3.4. Orphaned empty matcher (claude side)

A single entry in `~/.claude/settings.json .hooks.PreToolUse` had:

```json
{
  "matcher": "Bash|mcp__github__create_pull_request|mcp__github__merge_pull_request|mcp__github__push_files",
  "hooks": []
}
```

Empty hooks array, so this matcher did nothing at runtime — pure cruft. Likely the residue of a removed push-gate or github-tool hook that left its matcher behind. Low priority but clean-up candidate.

---

## §4. Severity of the two missing gemini hooks

### §4.1. relay-coordination-check (HIGH)

`hooks/scripts/relay-coordination-check.sh` is the Edit/Write-time gate that enforces the relay protocol's coordination invariants: it checks that the session's `relay/<role>.yaml` status file is current, that `current_item` is set when pulling queue work, and that no foreign session has claimed the same work item. Alpha + beta sessions run it on every Edit/Write tool call. A gemini session editing files in the council repo **without** this hook would silently bypass the coordination gate and could:

- Clobber alpha/beta's in-flight work on the same file
- Leave a queue item `in_progress` after the session crashes without the heartbeat refresh
- Write to frozen files during an LRR research condition without the relay-aware frozen-file check

This is the most important hook to add on the gemini side.

### §4.2. docs-only-pr-warn (LOW)

`hooks/scripts/docs-only-pr-warn.sh` is an advisory that emits a message when a Bash tool call looks like a docs-only PR creation — it reminds the caller that CI's `paths-ignore` filter covers `docs/**` and that branch-protection checks will not fire. It's a cosmetic UX hint, not a safety gate. Gemini not having it means gemini sessions don't get the advisory, but nothing breaks.

### §4.3. Orphaned MCP matcher (CLEANUP)

Pure cruft. No runtime effect. Removed during this sync.

---

## §5. Sync action log

```
# 1. Backup
cp ~/.claude/settings.json /tmp/claude-settings-backup.json
cp ~/.gemini/settings.json /tmp/gemini-settings-backup.json

# 2. Strip orphan from Claude
jq '.hooks.PreToolUse |= map(select(.hooks | length > 0))' ~/.claude/settings.json > /tmp/claude-settings-fixed.json
mv /tmp/claude-settings-fixed.json ~/.claude/settings.json

# 3. Append relay-coordination-check + docs-only-pr-warn to Gemini
jq '.hooks.BeforeTool += [
  {"matcher": "replace|write_file", "hooks": [{"name": "relay-coordination-check", ...}]},
  {"matcher": "run_shell_command", "hooks": [{"name": "docs-only-pr-warn", ...}]}
]' ~/.gemini/settings.json > /tmp/gemini-settings-fixed.json
mv /tmp/gemini-settings-fixed.json ~/.gemini/settings.json

# 4. Verify counts
jq '.hooks.PreToolUse | length' ~/.claude/settings.json  # 12
jq '.hooks.BeforeTool | length' ~/.gemini/settings.json  # 12
```

Both post-sync files have 12 entries. Parity achieved.

---

## §6. Remaining divergence (by design)

- **Timeouts:** claude-side hooks don't have explicit per-hook timeouts (they use the default), while gemini-side entries have 5000–15000 ms timeouts. This is intentional — gemini's hook runtime requires an explicit timeout and claude's doesn't. No action.
- **gemini-tool-adapter.sh indirection:** every gemini-side hook wraps the claude hook script through `gemini-tool-adapter.sh` which translates gemini's tool input format. Claude hooks call the scripts directly because Claude already produces the expected format. No action.
- **AfterTool / PostToolUse hooks:** out of scope for this queue item. A separate audit could sweep these.

---

## §7. Follow-up candidates

| Priority | Item | Size |
|----------|------|------|
| MEDIUM | Add `gemini hooks migrate` as a scripted sync step — currently manual and prone to drift | ~30 LOC shell script wrapping the jq diff above |
| LOW | Extend this audit to `AfterTool` / `PostToolUse` hooks | ~20 min repeat of the same method |
| LOW | Document the event-category and matcher mappings in `hooks/README.md` (does that file exist? check) | ~50 lines |
| LOW | Sweep `hooks/scripts/gemini-tool-adapter.sh` for input-format-translation bugs (would be caught by runtime errors but worth a read) | ~15 min |

None of these are in queue #173's scope. Recommending queue items for the operator to prioritise.

---

## §8. Cross-references

- `~/.claude/settings.json` — instance-local; not repo-tracked
- `~/.gemini/settings.json` — instance-local; not repo-tracked
- `hooks/scripts/gemini-tool-adapter.sh` — translates gemini tool input → claude hook input format
- `hooks/scripts/relay-coordination-check.sh` — the HIGH-priority missing hook
- `hooks/scripts/docs-only-pr-warn.sh` — the LOW-priority missing hook
- Queue #173 — this item

---

## §9. Verdict

Drift was real and has been fixed. The gemini-side HIGH finding (`relay-coordination-check` missing) was a genuine gap in the relay protocol's enforcement layer — gemini sessions were editing files without the coordination gate that alpha + beta enforce. Post-sync, gemini has parity with Claude's 12-hook PreToolUse/BeforeTool surface.

No follow-up required for the queue item itself; the recommendations in §7 are cleanups and hardenings, not blockers.
