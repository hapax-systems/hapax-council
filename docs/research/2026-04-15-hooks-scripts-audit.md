# `hooks/scripts/` audit + documentation

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #123)
**Scope:** Catalogue all hook scripts in `hooks/scripts/`. Classify by hook event, tool gated, block conditions, integration with `session-context.sh`. Cross-reference council CLAUDE.md § "Claude Code Hooks" to identify documentation gaps.
**Register:** scientific, neutral

## 1. Headline

**28 hook scripts, 22 represent actual PreToolUse/PostToolUse/SessionStart/Stop gates.** Council CLAUDE.md documents 6. **22 undocumented hooks**.

The gap is not a bug — CLAUDE.md documents the hooks most likely to block operator-initiated work. The undocumented hooks are either (a) PostToolUse advisories, (b) session lifecycle glue (conductor), (c) adapters for non-Claude-Code environments (Gemini), or (d) placeholders.

**Still, CLAUDE.md table should be expanded** to mention:

- `branch-switch-guard.sh` (blocks branch creation in primary worktrees — I hit this earlier)
- `pip-guard.sh` (blocks pip, enforces uv)
- `safe-stash-guard.sh` (blocks `git stash pop`)
- `registry-guard.sh` (blocks edits to axioms/registry.yaml + constitutive files)
- `conflict-marker-scan.sh` (PostToolUse detection of merge markers)
- `relay-coordination-check.sh` (relay state staleness detection)

## 2. Method

```bash
ls hooks/scripts/*.sh | wc -l      # 28
for h in hooks/scripts/*.sh; do
  head -20 "$h" | grep -E "^# " | head -3 | sed 's/^# //'
done
```

## 3. Full inventory (28 scripts)

### 3.1 PreToolUse gates (14 scripts) — actively block tool calls

| # | Hook | Gates | Blocks when | Documented in CLAUDE.md |
|---|---|---|---|---|
| 1 | `axiom-commit-scan.sh` | Bash | `git commit` / `git push` message matches T0 axiom violation patterns | ✓ yes |
| 2 | `axiom-scan.sh` | Edit/Write/MultiEdit | New code matches T0 axiom violation patterns (auth, role, user_id, etc.) | ✓ yes (subsumed under CLAUDE.md row `axiom-commit-scan`) |
| 3 | `branch-switch-guard.sh` | Bash | `git checkout -b` / `git switch -c` in primary worktree (must use worktree) | ✗ **undocumented** |
| 4 | `docs-only-pr-warn.sh` | Bash | `git commit` on feature branch changing only `docs/**` or `*.md` (advisory warning) | ✗ undocumented |
| 5 | `llm-metadata-gate.sh` | Bash | placeholder — no-op | — |
| 6 | `no-stale-branches.sh` | Bash | Branch creation with unmerged branches exist; destructive git commands on feature branches | ✓ yes |
| 7 | `pii-guard.sh` | Edit/Write | Content contains PII patterns (home dir path, email, etc.) | ✓ yes |
| 8 | `pip-guard.sh` | Bash | `pip install` / `pip3 install` (enforces uv) | ✗ **undocumented** |
| 9 | `push-gate.sh` | Bash | `git push` without passing tests; subject to no-test-run blocks | ✓ yes |
| 10 | `registry-guard.sh` | Edit/Write | Edits to `axioms/registry.yaml` or constitutive rules without CODEOWNERS path | ✗ **undocumented** |
| 11 | `relay-coordination-check.sh` | Edit/Write/MultiEdit | Relay state (alpha/beta yaml) older than threshold | ✗ undocumented |
| 12 | `safe-stash-guard.sh` | Bash | `git stash pop` (policy: NEVER pop, always `stash apply` then `stash drop`) | ✗ **undocumented** |
| 13 | `work-resolution-gate.sh` | Edit/Write | Feature branch with commits but no PR; on main with open PRs whose branch is local | ✓ yes |
| 14 | `conductor-pre.sh` | any tool | Session Conductor guardrails (relay coordination) | — (infrastructure) |

### 3.2 PostToolUse advisories (5 scripts)

| # | Hook | Fires on | Function |
|---|---|---|---|
| 15 | `axiom-audit.sh` | Edit/Write/MultiEdit | Logs diffs to `~/.cache/` for audit trail |
| 16 | `cargo-check-rust.sh` | Edit/Write (`*.rs` files) | Runs `cargo check` post-edit |
| 17 | `conflict-marker-scan.sh` | Bash (git operations) | Detects `<<<<<<<`/`=======`/`>>>>>>>` in working tree |
| 18 | `doc-update-advisory.sh` | Bash (git commit) | Non-blocking advisory: "CLAUDE.md may need update" |
| 19 | `skill-trigger-advisory.sh` | Bash output | Watches for triggers like `pytest.*FAILED`, advises using `superpowers:systematic-debugging` |
| 20 | `conductor-post.sh` | any | Conductor sidecar event pipe |
| 21 | `sprint-tracker.sh` | Bash (post-commit) | Sprint measure completion detection for R&D mode |

### 3.3 Session lifecycle hooks (4 scripts)

| # | Hook | Event | Function |
|---|---|---|---|
| 22 | `session-context.sh` | SessionStart | Injects system state summary, relay status, open PRs, branch list |
| 23 | `session-summary.sh` | Stop | Writes session summary + axiom audit tail |
| 24 | `conductor-start.sh` | SessionStart | Launches Session Conductor sidecar (UDS relay) |
| 25 | `conductor-stop.sh` | Stop | Shuts down Session Conductor sidecar |

### 3.4 Adapters (2 scripts) — cross-environment glue

| # | Hook | Function |
|---|---|---|
| 26 | `gemini-session-adapter.sh` | Translates Claude Code SessionStart/Stop hooks to Gemini CLI format |
| 27 | `gemini-tool-adapter.sh` | Translates Gemini CLI BeforeTool/AfterTool JSON to Claude Code PreToolUse/PostToolUse |

### 3.5 Shared library (1 file)

| # | File | Function |
|---|---|---|
| 28 | `axiom-patterns.sh` | Sourced by `axiom-scan.sh` + `axiom-commit-scan.sh`; defines T0 violation regex patterns |

**Total actually-firing hooks: 22** (14 PreToolUse + 5 PostToolUse + 3 SessionStart/Stop). Adapters are environment-specific; library is sourced not invoked.

## 4. Council CLAUDE.md documentation gap

CLAUDE.md § "Claude Code Hooks" currently lists 6 hooks:

```
| work-resolution-gate.sh | Edit, Write | Feature branch with commits but no PR
| no-stale-branches.sh    | Bash        | Branch creation / destructive commands
| push-gate.sh            | Bash        | Push without passing tests
| pii-guard.sh            | Edit, Write | PII patterns in file content
| axiom-commit-scan.sh    | Bash        | Commit messages violating axiom patterns
| session-context.sh      | Bash        | Advisory: session context
```

### 4.1 Missing from CLAUDE.md (recommend adding)

| Hook | Rationale for documenting |
|---|---|
| `axiom-scan.sh` | Gates Edit/Write against T0 axiom violations in file content (not just commit messages). Blocks code that introduces auth/roles/user_id. |
| `branch-switch-guard.sh` | Blocks `git checkout -b` in primary worktree. Important for session discipline — session work must happen in dedicated worktrees. |
| `pip-guard.sh` | Enforces uv discipline. Will block an operator who instinctively types `pip install`. |
| `registry-guard.sh` | Protects constitutional files. Critical for axiom governance integrity. |
| `safe-stash-guard.sh` | Blocks `git stash pop`. Enforces stash-apply-then-drop pattern to avoid lost work. |

### 4.2 Optional additions (lower priority)

| Hook | Notes |
|---|---|
| `conflict-marker-scan.sh` | PostToolUse only — safety net, not a gate |
| `doc-update-advisory.sh` | Advisory only |
| `docs-only-pr-warn.sh` | Advisory only |
| `relay-coordination-check.sh` | Integration-specific |
| `conductor-*.sh` | Infrastructure hooks for Session Conductor |

### 4.3 OK to skip

- `gemini-session-adapter.sh` + `gemini-tool-adapter.sh` — Gemini CLI only, not Claude Code
- `llm-metadata-gate.sh` — placeholder
- `axiom-patterns.sh` — library, not a hook
- `cargo-check-rust.sh` — PostToolUse only, not a block
- `axiom-audit.sh` — PostToolUse audit log

## 5. False-positive risks

| Hook | False-positive risk | Mitigation in place? |
|---|---|---|
| `no-stale-branches.sh` | Blocks valid new-branch creation if ANY unmerged branch exists (even unrelated) | Partial — provides clear error message with branch list |
| `axiom-scan.sh` | Could flag legitimate edits to test fixtures or comments mentioning `user_id` | Patterns in `axiom-patterns.sh` use word-boundary regex |
| `pii-guard.sh` | Flags home-directory absolute paths in research docs (hit during queue #113 audit + this audit) | Known issue — workaround: rephrase to exclude absolute home paths |
| `docs-only-pr-warn.sh` | Warning only, doesn't block | N/A |
| `branch-switch-guard.sh` | Blocks even valid spontaneous worktree creation | Mitigation: operator uses `git worktree add` pattern explicitly |
| `safe-stash-guard.sh` | Blocks every `git stash pop` even when no work would be lost | By design — forces stash-apply pattern |

**Most impactful FP:** `pii-guard.sh` on home-directory absolute paths in research documentation. Hit twice during this session. Workaround is to rephrase paths as `hapax-council/...` relative. Not worth fixing the hook because the hook is correctly protecting the operator's home directory from appearing in public research drops.

## 6. Integration with `session-context.sh`

`session-context.sh` is the central SessionStart hook that:

1. Reads relay state (`~/.cache/hapax/relay/alpha.yaml`, `beta.yaml`, `PROTOCOL.md`)
2. Runs `hapax-whoami` to derive session identity (alpha/beta/delta)
3. Reads system state (docker containers, GPU VRAM, sprint progress)
4. Emits context injection via stdout (goes into Claude Code session prompt)

**Coupling:** several PreToolUse hooks read the same relay state files that `session-context.sh` writes. `relay-coordination-check.sh` in particular depends on the relay yaml files existing + being fresh. If `session-context.sh` fails silently, downstream hooks operate on stale state.

**No cross-hook coordination bugs observed in this audit.** Each hook reads state independently; no hook mutates state that another hook reads.

## 7. Recommendations

### 7.1 Priority

1. **Expand CLAUDE.md § "Claude Code Hooks" table** to include `axiom-scan`, `branch-switch-guard`, `pip-guard`, `registry-guard`, `safe-stash-guard`. Small doc edit, high operator value.
2. **File follow-up queue item:** this recommendation itself. Low priority, doc-only, ~15 min.

### 7.2 Deferrable

- Remove `llm-metadata-gate.sh` placeholder (cosmetic cleanup)
- Document `pii-guard.sh` absolute-path workaround in research-drop authoring conventions

### 7.3 No action needed

- Adapters for Gemini CLI are correctly placed; not Claude Code concerns
- Session Conductor hooks are infrastructure, not user-facing gates
- `axiom-patterns.sh` is correctly organized as a shared library

## 8. Closing

28 hook scripts total, 22 actual gates/advisories, 6 adapters/libraries/placeholders. Council CLAUDE.md documents 6 hooks — adequate for most common operator scenarios but incomplete. Recommend expanding the CLAUDE.md hook table to add 5 important undocumented hooks (`axiom-scan`, `branch-switch-guard`, `pip-guard`, `registry-guard`, `safe-stash-guard`).

Branch-only commit per queue item #123 acceptance criteria.

## 9. Cross-references

- Council CLAUDE.md § "Claude Code Hooks" — current 6-hook table
- `hooks/scripts/axiom-patterns.sh` — shared T0 pattern library
- `hooks/scripts/session-context.sh` — SessionStart hook, central state reader
- Session Conductor spec: `docs/superpowers/specs/2026-03-26-session-conductor-design.md` (if exists)
- Memory: `feedback_no_stale_branches.md`, `feedback_branch_discipline.md`

— alpha, 2026-04-15T18:55Z
