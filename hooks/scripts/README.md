# hooks/scripts — Claude Code hook scripts

PreToolUse / PostToolUse hooks enforcing branch discipline, axiom
compliance, session-naming invariants, and other governance rules at
the tool-call level.

Wired through Claude Code settings (root `hooks` key; on this workstation,
`~/.claude/settings.json`). Each hook reads the tool call via stdin (JSON
`{tool_name, tool_input, ...}`) and exits non-zero to block or emit advisory
stderr to warn. All hooks are idempotent — re-running with the same input
produces the same verdict.

As of 2026-05-29, normal Claude Code sessions point their hook commands at the
clean merged source path `$HOME/.cache/hapax/rebuild/worktree/hooks/scripts/`
rather than the dirty canonical checkout. See
`docs/runbooks/claude-code-config-conformance.md` for verification commands.

## Hook inventory

| Hook | Tool gate | Behaviour |
|------|-----------|-----------|
| `work-resolution-gate.sh` | Edit / Write | BLOCK when a feature branch has commits but no PR, or when on main with open PRs whose branches are local |
| `no-stale-branches.sh` | Bash | BLOCK branch creation if any unmerged branch exists; BLOCK destructive git on feature branches; enforce visible worktree cap during Claude+Codex transition |
| `push-gate.sh` | Bash — **unwired** | Unconditional `git push`/PR approval block, but NOT registered in settings.json (inactive). Use the conditional in-session release-evidence gate below. |
| `pr-release-gate.sh` | Bash / GitHub MCP PR create+merge | BLOCKS PR create/merge when a task's AVSDLC/test-before-push release evidence is missing; degrades advisory-only on infrastructure failures. |
| `pii-guard.sh` | Edit / Write | BLOCK edits whose file content matches PII patterns |
| `axiom-commit-scan.sh` | Bash | BLOCK commits whose messages violate axiom patterns |
| `axiom-scan.sh` / `axiom-patterns.sh` / `axiom-audit.sh` | session | Axiom compliance scanning, retroactive audit |
| `conflict-marker-scan.sh` | Write / Edit | WARN on merge-conflict markers in content |
| `docs-only-pr-warn.sh` | Bash | ADVISORY: docs-only PRs use required-check sentinels; no carrier file needed |
| `doc-update-advisory.sh` | Edit / Write | ADVISORY: suggest related doc updates |
| `llm-metadata-gate.sh` | Write (PostToolUse) | ADVISORY: warn when a new `agents/<name>/__init__.py` lacks a sibling `METADATA.yaml` |
| `visual-audio-evidence-reflex.sh` | Edit / Write / MultiEdit (PostToolUse) | ADVISORY: when visual/audio/audiovisual surfaces change, remind the session to collect AVSDLC witness evidence before release. |
| `hook-presence-verify.sh` | SessionStart | ADVISORY: verify every absolute hook command in Claude settings exists and is executable. |
| `pip-guard.sh` | Bash | BLOCK `pip install` invocations; project uses uv |
| `registry-guard.sh` | Edit / Write | BLOCK changes to sealed registry files |
| `relay-coordination-check.sh` | session | ADVISORY: relay protocol status |
| `safe-stash-guard.sh` | Bash | BLOCK `git stash` that would discard work |
| `session-context.sh` | session | ADVISORY: session context on start |
| `session-name-enforcement.sh` | Bash | BLOCK Bash commands referencing unknown session names (zeta, sigma, etc.) |
| `session-summary.sh` | session | ADVISORY: session summary on stop |
| `subagent-git-safety.sh` | SubagentStop | ADVISORY: remind parent sessions to preserve subagent-produced git state before worktree cleanup. |
| `skill-trigger-advisory.sh` | session | ADVISORY: suggest skills matching context |
| `sprint-tracker.sh` | session | ADVISORY: sprint progress |
| `branch-switch-guard.sh` | Bash | BLOCK cross-session branch switches |
| `canonical-worktree-protect.sh` | Bash | BLOCK `git checkout/switch/reset --hard` to non-main refs in canonical worktree (`~/projects/hapax-council`); allows main-targeting commands, file restores, fetches, pulls, worktree-add. Operator escape: `HAPAX_CANONICAL_PROTECT_BYPASS=1` |
| `gemini-session-adapter.sh` / `gemini-tool-adapter.sh` | session | Legacy adapter bridges retained for historical fixtures; not active launch paths |
| `conductor-*.sh` | session | Session-conductor protocol |
| `cargo-check-rust.sh` | Edit / Write | PostToolUse: run cargo check on .rs edits |

## Session-naming invariant

The canonical lane vocabulary (SSOT: `hooks/scripts/agent-role.sh`
`assert-identity`) is: greek slots `alpha` `beta` `gamma` `delta`
`epsilon` `zeta` `eta` `theta`; Codex
`cx-<color>` (e.g. `cx-red`); Claude relay lanes `cc-<name>` (e.g.
`cc-zai`); and Vibe `vbe-<n>`. These are operational identities — not
rhetorical choices — and the tooling assumes them:

- `hapax-whoami` (identity resolver) resolves the role env var FIRST
  (`HAPAX_AGENT_NAME`, then the `CODEX_THREAD_NAME`/`CODEX_SESSION_NAME`/
  `CODEX_SESSION`/`CODEX_ROLE` vars, then `HAPAX_AGENT_ROLE`, then
  `CLAUDE_ROLE`), then the session-role marker, then the compositor walk —
  WM-independent, so identity survives a missing hyprctl (KWin/niri). Exact
  same precedence as `hapax_agent_identity` in `agent-role.sh`.
- `scripts/hapax-whoami-audit.sh` fails non-zero on any name outside
  the vocabulary above.
- `session-name-enforcement.sh` PreToolUse hook BLOCKS Bash commands
  that reference a greek-letter-shaped token OUTSIDE the approved greek
  slots (i.e. `kappa` and beyond) when used as a session identifier.
- The worktree cap (`no-stale-branches.sh`) is sized for the full
  multi-interface team (greek + `cx-*` + `cc-*` + `vbe-*`).
- Legacy `iota` was the retired Gemini CLI lane and is intentionally no longer
  accepted as a session identity.

Recheck commands (verify these claims after any change):
- `agent-role.sh whoami` — the resolved role for this session (the SSOT path).
- `scripts/hapax-whoami-audit.sh` — exits non-zero on a name outside the vocabulary.
- `rg -n 'gemini-(session|tool)-adapter' hooks tests config scripts` — confirms
  the Gemini hook adapters are retained only as dormant adapter fixtures, not
  launch or dispatch paths.
- `uv run pytest tests/scripts/test_role_identity_resolution.py tests/hooks/test_session_name_enforcement.py`
  — exercises env-first resolution, the audit approved-set, the assert-identity vocab,
  and the enforcement deny-list against the canonical vocabulary above.

Adding a new session name requires amending this file AND the canonical
vocabulary in `hooks/scripts/agent-role.sh` (assert-identity), the
approved list in `scripts/hapax-whoami-audit.sh`, and the greek
deny-list in `session-name-enforcement.sh`, then re-running
`scripts/worktree-cap-audit.sh` to confirm the new slot fits the
cap.

## Branch & worktree discipline

The workspace policy is now interface-qualified:

- `hapax-council/` — primary/integrator
- `hapax-council--beta/` — legacy Claude beta lane
- `hapax-council--<slug>/` — spontaneous (one at a time; must be
  cleaned up before new spontaneous work)
- `hapax-council--delta/` or equivalent — legacy Claude delta lane
- `hapax-council--epsilon/` or equivalent — legacy Claude epsilon lane
- `hapax-council--cx-<color>/` — first-class Codex lane

`no-stale-branches.sh` enforces the transition ceiling.
Infrastructure worktrees under `~/.cache/` (e.g. rebuild-scratch
managed by `rebuild-logos.sh`), `.claude/worktrees/`, and
`.codex/worktrees/` are NOT counted. See
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

- `~/.claude/settings.json` and project `.claude/settings.json` — hook wiring
- `docs/runbooks/claude-code-config-conformance.md` — current activation and verification state
- `docs/runbooks/worktree-cap-policy.md` — worktree cap + cleanup
- `docs/governance/` — governance docs referenced by individual
  hooks (axiom-* scans, session-naming, etc.)
