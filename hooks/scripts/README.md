# hooks/scripts — Claude Code hook scripts

PreToolUse / PostToolUse hooks enforcing branch discipline, axiom
compliance, session-naming invariants, and other governance rules at
the tool-call level.

Wired in `.claude/settings.json` (root `hooks` key). Each hook reads
the tool call via stdin (JSON `{tool_name, tool_input, ...}`) and
exits non-zero to block or emit advisory stderr to warn. All hooks
are idempotent — re-running with the same input produces the same
verdict.

## Hook inventory

| Hook | Tool gate | Behaviour |
|------|-----------|-----------|
| `work-resolution-gate.sh` | Edit / Write | BLOCK when a feature branch has commits but no PR, or when on main with open PRs whose branches are local |
| `no-stale-branches.sh` | Bash | BLOCK branch creation if any unmerged branch exists; BLOCK destructive git on feature branches; enforce 4-worktree session cap (alpha + beta + delta + 1 spontaneous) |
| `push-gate.sh` | Bash | BLOCK `git push` without passing tests |
| `pii-guard.sh` | Edit / Write | BLOCK edits whose file content matches PII patterns |
| `axiom-commit-scan.sh` | Bash | BLOCK commits whose messages violate axiom patterns |
| `axiom-scan.sh` / `axiom-patterns.sh` / `axiom-audit.sh` | session | Axiom compliance scanning, retroactive audit |
| `conflict-marker-scan.sh` | Write / Edit | WARN on merge-conflict markers in content |
| `docs-only-pr-warn.sh` | Bash | ADVISORY: docs-only PRs don't trigger branch protection |
| `doc-update-advisory.sh` | Edit / Write | ADVISORY: suggest related doc updates |
| `llm-metadata-gate.sh` | Bash | BLOCK LLM calls missing required metadata |
| `pip-guard.sh` | Bash | BLOCK `pip install` invocations; project uses uv |
| `registry-guard.sh` | Edit / Write | BLOCK changes to sealed registry files |
| `relay-coordination-check.sh` | session | ADVISORY: relay protocol status |
| `safe-stash-guard.sh` | Bash | BLOCK `git stash` that would discard work |
| `session-context.sh` | session | ADVISORY: session context on start |
| `session-name-enforcement.sh` | Bash | BLOCK Bash commands referencing unknown session names (zeta, sigma, etc.) |
| `session-summary.sh` | session | ADVISORY: session summary on stop |
| `skill-trigger-advisory.sh` | session | ADVISORY: suggest skills matching context |
| `sprint-tracker.sh` | session | ADVISORY: sprint progress |
| `branch-switch-guard.sh` | Bash | BLOCK cross-session branch switches |
| `gemini-session-adapter.sh` / `gemini-tool-adapter.sh` | session | Adapter bridges for Gemini subagents |
| `conductor-*.sh` | session | Session-conductor protocol |
| `cargo-check-rust.sh` | Edit / Write | PostToolUse: run cargo check on .rs edits |

## Session-naming invariant

Approved session names are `alpha`, `beta`, `gamma`, `delta`, and
`epsilon`. These are operational slots — not rhetorical choices —
and the tooling assumes them:

- `hapax-whoami` (identity resolver) grep-matches this set.
- `scripts/hapax-whoami-audit.sh` fails non-zero on any other name.
- `session-name-enforcement.sh` PreToolUse hook BLOCKS Bash commands
  that reference a greek-letter-shaped name outside this set when
  used as a session identifier (`session=<name>`,
  `hapax-council--<name>/` worktree slot, `session-context.sh
  <name>` argument, etc.).
- The worktree cap (`no-stale-branches.sh`) is sized to this slot
  set: alpha + beta + delta + 1 spontaneous = 4 worktrees.

Adding a new session name requires amending both this file and the
approved list in `scripts/hapax-whoami-audit.sh`, then re-running
`scripts/worktree-cap-audit.sh` to confirm the new slot fits the
cap.

## Branch & worktree discipline

The workspace policy is three permanent session slots plus one
spontaneous slot:

- `hapax-council/` — alpha (primary)
- `hapax-council--beta/` — beta (permanent)
- `hapax-council--<slug>/` — spontaneous (one at a time; must be
  cleaned up before new spontaneous work)
- `hapax-council--delta/` or equivalent — delta session (permanent,
  first-class from 2026-04-12)

`no-stale-branches.sh` enforces the 4-worktree ceiling.
Infrastructure worktrees under `~/.cache/` (e.g. rebuild-scratch
managed by `rebuild-logos.sh`) are NOT counted. See
`docs/runbooks/worktree-cap-policy.md` for the full policy +
cleanup procedure.

## Running a hook manually

Each hook reads its input from stdin as JSON:

```fish
echo '{"tool_name": "Bash", "tool_input": {"command": "git branch feat/foo"}}' \
    | hooks/scripts/no-stale-branches.sh
```

Exit code 0 = allow, 2 = block (Claude Code surfaces the block to
the model), any stderr output is surfaced to the model's tool-
result feedback.

## Related

- `.claude/settings.json` — hook wiring
- `docs/runbooks/worktree-cap-policy.md` — worktree cap + cleanup
- `docs/governance/` — governance docs referenced by individual
  hooks (axiom-* scans, session-naming, etc.)
