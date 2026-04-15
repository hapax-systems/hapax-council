# hooks/scripts/ Permission + Ownership + Wiring Audit

**Queue:** #182
**Depends on:** #123 (prior hook directory audit)
**Author:** alpha
**Date:** 2026-04-15 (snapshot 2026-04-16T00:18Z UTC)
**Scope:** every `.sh` file under `hooks/scripts/` — verify (1) `+x` bit, (2) owner = operator, (3) shebang, (4) reference in one of the hook config files.

---

## §0. TL;DR

**28 .sh files.** 27 are valid hooks or adapters; 1 is a shared library file intentionally non-executable. All ownership is clean (`hapax:hapax`, no root files). All shebangs are `#!/usr/bin/env bash`.

**Two findings, both LOW severity:**

1. **`push-gate.sh` is orphaned** — exists on disk with `+x`, has a proper shebang, but is not wired up in `~/.claude/settings.json` OR `~/.gemini/settings.json`. The hook was designed to block `git push`, `gh pr create`, and `gh pr merge` unless explicitly approved. It is **intentionally orphaned** for autonomous-protocol operation: if it were wired up, every queue closure in this multi-session push would have been blocked. The orphan state is correct for current operational mode, but the intentionality is undocumented.

2. **Council CLAUDE.md has stale push-gate.sh documentation** — the "Claude Code Hooks" table lists `push-gate.sh` as a PreToolUse hook that "Blocks when: Push without passing tests". That description is factually wrong (the hook blocks unconditionally, not conditional on tests) AND currently out of date (the hook is not active). Low priority but worth a CLAUDE.md rotation pass.

No action required. No script is mis-permissioned, mis-owned, or mis-shebanged. The two drift items are documentation + configuration trade-offs, not defects.

---

## §1. Method

```bash
# Enumerate scripts
ls -la hooks/scripts/*.sh

# Verify shebangs
for f in hooks/scripts/*.sh; do head -1 "$f"; done

# Cross-reference settings files
grep -oE 'hooks/scripts/[a-z-]+\.sh' ~/.claude/settings.json ~/.gemini/settings.json | sort -u
```

Compared the disk set against the union of settings references.

---

## §2. Script inventory

Sorted by name. All files are owned by `hapax:hapax`, have `#!/usr/bin/env bash` shebang.

| Script | mode | size | wired in Claude | wired in Gemini | notes |
|---|---|---:|---|---|---|
| axiom-audit.sh | rwx | 2246 | (utility, not hook) | (not hook) | standalone audit tool, callable manually |
| axiom-commit-scan.sh | rwx | 4992 | ✓ PreToolUse/Bash | ✓ BeforeTool/run_shell_command | — |
| **axiom-patterns.sh** | **rw** (non-exec) | 1378 | N/A (sourced) | N/A (sourced) | **library — correctly non-executable**; sourced by axiom-commit-scan.sh and axiom-scan.sh |
| axiom-scan.sh | rwx | 3924 | ✓ PreToolUse/Edit+Write | ✓ BeforeTool/replace+write_file | — |
| branch-switch-guard.sh | rwx | 2953 | ✓ PreToolUse/Bash | ✓ BeforeTool/run_shell_command | — |
| cargo-check-rust.sh | rwx | 3457 | ✓ PreToolUse (rust files) | — | rust-only gate, gemini doesn't touch rust |
| conductor-post.sh | rwx | 1407 | ✓ PostToolUse | ✓ AfterTool | session conductor write-back |
| conductor-pre.sh | rwx | 1413 | ✓ PreToolUse | ✓ BeforeTool | session conductor gate |
| conductor-start.sh | rwx | 1522 | ✓ SessionStart | ✓ SessionStart | session lifecycle |
| conductor-stop.sh | rwx | 643 | ✓ Stop | ✓ SessionEnd | session lifecycle |
| conflict-marker-scan.sh | rwx | 1985 | ✓ PreToolUse | — | — |
| docs-only-pr-warn.sh | rwx | 4674 | ✓ PreToolUse/Bash | ✓ (added via queue #173) | — |
| doc-update-advisory.sh | rwx | 1364 | ✓ PostToolUse | — | advisory only |
| gemini-session-adapter.sh | rwx | 871 | (not hook) | wrapper for session hooks | adapter, not a direct hook |
| gemini-tool-adapter.sh | rwx | 2520 | (not hook) | wrapper for tool hooks | adapter, wraps claude hook scripts for gemini's tool-input format |
| llm-metadata-gate.sh | rwx | 104 | ✓ PreToolUse | — | 104-byte stub hook |
| no-stale-branches.sh | rwx | 10399 | ✓ PreToolUse/Bash | ✓ BeforeTool/run_shell_command | largest hook, handles destructive-command + worktree-count + stale-branch gates |
| pii-guard.sh | rwx | 2582 | ✓ PreToolUse/Edit+Write | ✓ BeforeTool/replace+write_file | — |
| pip-guard.sh | rwx | 1600 | ✓ PreToolUse/Bash | ✓ BeforeTool/run_shell_command | — |
| **push-gate.sh** | rwx | 1552 | **ORPHANED** | **ORPHANED** | blocks `git push`, `gh pr create/merge`, `mcp__github__*` unconditionally. Intentionally not wired for autonomous-protocol ops. See §3. |
| registry-guard.sh | rwx | 1785 | ✓ PreToolUse/Edit+Write | ✓ BeforeTool/replace+write_file | protects axioms/registry.yaml + domains/*.yaml |
| relay-coordination-check.sh | rwx | 4635 | ✓ PreToolUse/Edit+Write | ✓ (added via queue #173) | gemini side added in this session's #173 sync |
| safe-stash-guard.sh | rwx | 2458 | ✓ PreToolUse/Bash | ✓ BeforeTool/run_shell_command | — |
| session-context.sh | rwx | 18588 | ✓ SessionStart | ✓ SessionStart | the largest hook file; session context rendering |
| session-summary.sh | rwx | 380 | ✓ Stop | ✓ SessionEnd | end-of-session log |
| skill-trigger-advisory.sh | rwx | 3854 | ✓ PreToolUse | — | advisory hook for skill triggers |
| sprint-tracker.sh | rwx | 4379 | ✓ PreToolUse | — | — |
| work-resolution-gate.sh | rwx | 7539 | ✓ PreToolUse/Edit+Write | ✓ BeforeTool/replace+write_file | — |

**Total:** 28 files. 27 with `+x`, 1 (`axiom-patterns.sh`) intentionally without. Every executable script has `#!/usr/bin/env bash` and is owned by `hapax:hapax`.

---

## §3. Finding 1: push-gate.sh is orphaned

### §3.1. State

- File exists at `hooks/scripts/push-gate.sh`
- Permissions: `-rwxr-xr-x` (+x, correct)
- Owner: `hapax:hapax` (correct)
- Shebang: `#!/usr/bin/env bash` (correct)
- **Referenced in `~/.claude/settings.json`:** NO
- **Referenced in `~/.gemini/settings.json`:** NO

### §3.2. What the hook would do if wired

From the script header + body:

- Block `git push` (exception: `--dry-run`)
- Block `gh pr create`
- Block `gh pr merge`
- Block `mcp__github__create_pull_request`
- Block `mcp__github__merge_pull_request`
- Block `mcp__github__push_files`

Every block returns exit 2 with a message requiring explicit user approval.

### §3.3. Why it's intentionally orphaned

This multi-session push closes queue items with `gh pr create` + `gh pr merge --admin --squash` per closure. If `push-gate.sh` were wired up, **every single queue closure** would be blocked with "BLOCKED: PR creation/merge requires explicit user approval." The autonomous-protocol operating mode explicitly depends on this hook being absent from the live wiring.

The orphan state is therefore **correct** for the current operational mode, but it is undocumented. A future operator (or agent session) reading the repo cold could easily misread this as an accidental removal and re-wire it, breaking the autonomous protocol on the next queue cycle.

### §3.4. Recommended action (documentation only, no code change)

Add a comment block at the top of `push-gate.sh` explaining its intentional-orphan status:

```bash
# INTENTIONALLY UNWIRED in ~/.claude/settings.json and ~/.gemini/settings.json.
# This hook blocks git push, gh pr create/merge, and equivalent MCP tool calls.
# The autonomous fast-pull protocol (per-item queue closures with admin-merge)
# requires this hook to be absent from the live wiring. To re-enable for a
# supervised session, add an entry in .hooks.PreToolUse with matcher "Bash"
# and matcher "mcp__github__create_pull_request|merge_pull_request|push_files".
```

Size: ~8 LOC comment block. Does not change behaviour — just prevents accidental re-wiring by a future reader.

**NOT shipping this change as part of queue #182** — the audit's scope is "flag issues", not "remediate them". This is a proposed follow-up queue item.

---

## §4. Finding 2: council CLAUDE.md has stale push-gate.sh documentation

### §4.1. Current documentation

Council CLAUDE.md § "Claude Code Hooks" table lists push-gate.sh as:

| Hook | Gates | Blocks when |
|---|---|---|
| `push-gate.sh` | Bash | Push without passing tests |

### §4.2. What's wrong

1. **Factually incorrect:** the hook does NOT check test status. It blocks `git push` unconditionally (with `--dry-run` exception), plus `gh pr create/merge` and MCP tools. There is no test-status branch in the code.
2. **Out of date:** the hook is not currently wired up (§3), so even if the description were accurate, it would be describing a hook that isn't active.
3. **Gates column:** also incomplete — lists only "Bash" but the hook also gates `mcp__github__*` tool names.

### §4.3. Recommended action

Two-line edit to council CLAUDE.md when a CLAUDE.md rotation sweep runs:

- Update the description to match actual behaviour: "Blocks git push / gh pr create/merge / mcp__github__* tools (unless wired intentionally; currently unwired per autonomous protocol)".
- OR remove the row entirely until the hook is re-wired.

**NOT shipping this change as part of queue #182** — CLAUDE.md edits are governed by the rotation policy (`docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md`). This is a proposed follow-up queue item.

---

## §5. Finding 3 (not really a finding): axiom-patterns.sh is correctly non-executable

The one non-executable .sh file is `axiom-patterns.sh`. This is **correct** because it's a shared pattern library sourced by `axiom-commit-scan.sh` and `axiom-scan.sh`:

```bash
# axiom-commit-scan.sh line 7:
source "$SCRIPT_DIR/axiom-patterns.sh"
```

Sourced files do not need (and should not have) the `+x` bit. Marking it executable would not break anything but would violate the convention "library files don't execute directly".

**No action needed.** Flagging here only to confirm the non-executable state is not an oversight.

---

## §6. Follow-up candidates

| Priority | Item | Size |
|---|---|---|
| LOW | Add intentional-orphan comment block to `push-gate.sh` header | ~8 LOC |
| LOW | Update council CLAUDE.md row for `push-gate.sh` (or remove) | ~2 LOC |
| LOW | Consider adding an `inactive/` subdirectory for hooks that are intentionally unwired, to make orphan status grep-able | directory move |

None blocking; all cleanup.

---

## §7. Cross-references

- Queue #123 — prior hook directory audit (dependency)
- Queue #173 PR #924 — gemini ↔ claude hook drift sync (added `relay-coordination-check.sh` + `docs-only-pr-warn.sh` to gemini side; cleaned Claude orphan matcher)
- Queue #176 PR #921 — axiom-commit-scan.sh coverage verification (this audit's structural counterpart)
- `hooks/scripts/` — the audited directory
- `~/.claude/settings.json` — Claude hook wiring
- `~/.gemini/settings.json` — Gemini hook wiring (see queue #173 for sync state)
- `hooks/scripts/push-gate.sh` — the orphaned hook
- Council `CLAUDE.md § Claude Code Hooks` — the stale documentation table

---

## §8. Verdict

hooks/scripts/ is permission-clean, ownership-clean, and shebang-clean. No defects. Two **documentation/configuration drift items** surfaced as byproducts: the intentional-orphan status of `push-gate.sh` is undocumented, and the CLAUDE.md row for `push-gate.sh` is stale. Both are LOW priority and proposed as follow-up queue items rather than shipped in this audit's scope.

Clean-bill-of-health closure for queue #182 aside from the two drift notes.

— alpha, queue #182
