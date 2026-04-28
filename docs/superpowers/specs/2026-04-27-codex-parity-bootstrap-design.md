# Codex Parity Bootstrap — Design

**Status:** implemented
**Date:** 2026-04-27
**Owner:** bootstrap session

## Summary

Codex joins Claude Code as a first-class Hapax coding interface. The design goal is parity with the Claude Code operating contract: no ask-permission gates, same hook guardrails, same MCP surface, same Obsidian work-state source of truth, same relay coordination, and no credential copying.

Claude Code remains a peer interface, not the privileged source of policy. Shared policy now lives in agent-neutral helpers and is consumed by Claude-era hooks and the Codex hook adapter.

Correction from the bootstrap session: child-session spawning means **Codex spawning Codex**, not Claude Code spawning. No new Claude launcher is part of the target state.

## Principles

- **No permission crutch.** Codex launches in `approval_policy=never` and `sandbox_mode=danger-full-access` via `hapax-codex`. The safety layer is post-hoc repair plus deterministic guardrails, not interactive permission gates.
- **Obsidian is load-bearing.** `~/Documents/Personal/20-projects/hapax-cc-tasks/` remains the work-state source of truth for both Claude and Codex. Codex claim identity is `cx-<color>`.
- **One hook system.** Codex does not get a parallel policy stack. `hooks/scripts/codex-hook-adapter.sh` translates Codex events into the Claude hook JSON shape and reuses existing guards.
- **Separate thread identity from coordination slot.** Codex visible names use `cx-<color>`; `alpha`, `beta`, `delta`, and `epsilon` are coordination lanes, not Codex worktree names. Non-primary Codex worktrees use `hapax-council--cx-<color>` unless `--cd` is explicit.
- **Secrets stay in pass/hapax-secrets.** Config references MCP/env surfaces but does not embed secret values.
- **Codex-to-Codex spawning.** Parallel coding lanes should use the same `hapax-codex` wrapper with explicit thread, slot, terminal, task, and bootstrap material. Claude Code sessions are not spawned as a Codex parity mechanism.
- **Benchmark against Hapax, not industry median.** The public velocity report at `https://hapax.weblog.lol/velocity-report-2026-04-25` is the internal baseline Codex adoption should attempt to match and then exceed.

## Configuration Surfaces Found

- Global Claude settings at `~/.claude/settings.json`: full Bash/read/write permissions, `opus[1m]`, `effortLevel=xhigh`, `skipDangerousModePermissionPrompt=true`, global hooks, and plugins.
- Global Claude instructions at `~/.claude/CLAUDE.md`: autonomy, subagent git safety, plugin use, Gemini delegation, all permissions granted.
- Workspace Claude instructions at `~/projects/CLAUDE.md` -> `~/dotfiles/workspace-CLAUDE.md`: repo map, Obsidian vault, uv-only Python, pass/direnv secrets, worktree discipline.
- Council Claude instructions at `hapax-council/CLAUDE.md`: architecture, Obsidian integration, CC-task SSOT, hook discipline, axioms.
- Claude MCP config at `~/.claude.json`: context7, playwright, github, hapax-mcp, gemini-cli. Epidemic Sound MCP is deliberately decommissioned until a stronger use case exists.
- Codex config at `~/.codex/config.toml`: already on `gpt-5.5` / `xhigh`, trusted `~/projects`, but no MCP or hooks.

## Codex Contract

Canonical Codex launch:

```bash
scripts/hapax-codex --session cx-red --slot alpha
```

Canonical child Codex terminal launch:

```bash
scripts/hapax-codex --session cx-green --slot beta --task <task-id> --terminal tmux
```

Without an explicit `--cd`, that child uses `~/projects/hapax-council--cx-green`. The slot label remains available to relay and workload coordination, but Codex does not silently inherit Claude-era `hapax-council--delta`, `hapax-council--epsilon`, or `hapax-council--main-red` worktrees.

The launcher preflights Codex, the selected worktree, relay retirement state, and the requested terminal before creating a child terminal. For terminal launches, the Obsidian task claim happens inside the child `hapax-codex` process after the terminal starts, so a terminal startup failure cannot leave a task claimed without a running session.

The launcher exports:

- `HAPAX_AGENT_INTERFACE=codex`
- `HAPAX_AGENT_NAME=cx-red`
- `CODEX_THREAD_NAME=cx-red`
- `CODEX_ROLE=cx-red` for backward compatibility
- `HAPAX_AGENT_SLOT=alpha`
- `HAPAX_WORKTREE_ROLE=alpha`
- `HAPAX_CODEX_WORKTREE_STRATEGY=primary|codex-native|explicit`

The same thread identity owns:

- `assigned_to: cx-red` in vault cc-task notes
- `~/.cache/hapax/cc-active-task-cx-red`
- `~/.cache/hapax/relay/cx-red.yaml` when relay participation is active

When a task or child terminal is provided, `hapax-codex` writes a bootstrap file under `${XDG_CACHE_HOME:-$HOME/.cache}/hapax/codex-spawns/` and passes `Bootstrap file: <path>` as the opening prompt unless the caller is invoking a non-interactive Codex subcommand such as `mcp list` or `resume`.

## Multi-Session Pattern

Prefer multiple Codex threads for WSJF trains when there are independent work items and clear path claims. A practical pattern is 3-5 active interfaces total across Claude/Codex:

- one alpha/primary integrator
- one or two implementation lanes
- one research/audit lane
- one verification or docs lane when useful

Single-session Codex is better only for tightly coupled refactors, unclear ownership, or work where immediate local feedback dominates parallelism.

## Velocity Baseline

The future Codex adoption comparison should use the same measurement frame as the published Hapax Velocity Report:

- Public artifact: `https://hapax.weblog.lol/velocity-report-2026-04-25`
- Local canonical note: `~/Documents/Personal/30-areas/hapax/velocity-report-2026-04-25.md`
- Source research drop: `docs/research/2026-04-25-velocity-comparison.md`
- Publication task: `~/Documents/Personal/20-projects/hapax-cc-tasks/closed/leverage-mktg-velocity-report-publish.md`
- Baseline window: 2026-04-25, 18-hour observation window
- Baseline throughput: 30 PRs/day, 137 commits/day, approximately 33,500 LOC churn/day
- Baseline operating shape: four concurrent Claude Code sessions on max-effort routing, coordinated by filesystem-as-bus, relay YAML, and Obsidian cc-task claims

Codex parity means preserving the operating shape while changing the first-class interface. Codex improvement means beating the baseline on useful throughput or quality-adjusted throughput without weakening refusal tracking, Obsidian transparency, hook enforcement, or the no-operator-labor publication constraints.

## Obsidian

Codex must treat Obsidian as a system surface, not background context:

- CC-task notes remain the canonical queue and assignment state.
- SessionStart surfaces claimed task plus offered tasks.
- Hygiene dashboards now support dynamic Codex `cx-*` identities.
- Vault writes still use existing Obsidian agents and Local REST plumbing; Codex should not invent a second task database.

## Credentials

Credentials are available under expected `pass` paths and via `hapax-secrets`. Codex configuration and docs must name sources, not values. The launcher sources `/run/user/$UID/hapax-secrets.env` or `~/.cache/hapax/secrets.env` when present, and sets `PASSWORD_STORE_DIR` for scripts that read `pass` directly.

MCP credential handling is deliberately wrapper-based where Codex cannot express the Claude header shape:

- Context7 uses `CONTEXT7_API_KEY` from `pass context7/api-key` as Codex's bearer token env var.
- Epidemic Sound MCP is not part of Codex startup; existing local music assets remain independent of MCP startup.
- GitHub uses the official local Docker MCP server through `scripts/hapax-github-mcp`, because the remote `https://api.githubcopilot.com/mcp/` path rejected the local `gho_` token with a Copilot feature entitlement error. The wrapper loads a token from expected pass paths, `gh auth token`, or Claude MCP config, then execs `ghcr.io/github/github-mcp-server` without writing the token to config.
