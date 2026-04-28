# Codex Parity Bootstrap — Implementation Plan

**Status:** implemented
**Date:** 2026-04-27
**Spec:** `docs/superpowers/specs/2026-04-27-codex-parity-bootstrap-design.md`

## Phase 1 — Research

- [x] Read global Claude settings, hooks, plugin list, MCP servers, and global instructions.
- [x] Read workspace and council Claude instructions, including Obsidian and CC-task SSOT.
- [x] Inspect Codex config, feature flags, hook schema, MCP syntax, and no-ask mode.
- [x] Identify Obsidian vault, vault sync/write agents, and credential source conventions.

## Phase 2 — Shared Identity

- [x] Add `hooks/scripts/agent-role.sh`.
- [x] Split agent identity (`cx-red`) from worktree slot (`alpha`).
- [x] Update Claude-era hooks and helpers to accept `HAPAX_AGENT_NAME`, `CODEX_THREAD_NAME`, `CODEX_ROLE`, and legacy `CLAUDE_ROLE`.
- [x] Teach `hapax-whoami` / audit to recognize Codex `cx-*` names.

## Phase 3 — Codex Runtime Wiring

- [x] Add `hooks/scripts/codex-hook-adapter.sh`.
- [x] Add `hooks/scripts/codex_patch_events.py` for `apply_patch` normalization.
- [x] Add `scripts/hapax-codex` no-ask launcher.
- [x] Add `scripts/hapax-codex --terminal tmux|foot` for Codex-to-Codex child sessions with explicit session, slot, task, and bootstrap material.
- [x] Correct the rejected Claude-spawn premise: no `hapax-claude` launcher is part of the Codex parity target state.
- [x] Correct the Claude-centric worktree premise: Codex child sessions default to `hapax-council--cx-<color>` worktrees; Greek slot names are coordination lanes only unless `--cd` is explicit.
- [x] Add `config/codex/config.toml` template and installer script.
- [x] Add workspace and repo `AGENTS.md`.

## Phase 4 — Obsidian / Relay Parity

- [x] Keep vault cc-task notes as canonical state.
- [x] Make claim files work for `cx-*` sessions.
- [x] Make SessionStart show Codex identity and task context.
- [x] Make relay coordination self-detection work for Codex threads.
- [x] Extend CC hygiene surfaces to dynamic `cx-*` identities.

## Phase 5 — Parallel-Work Readiness

- [x] Align worktree cap docs and audit script with the live 5-slot hook policy.
- [x] Preserve path-claim blocking for Codex via the shared relay hook.
- [x] Keep `--task-gate` opt-in for strict mutation gating until the existing D-30 validation completes.
- [x] Ensure terminal-spawn task claiming happens inside the child Codex process after terminal preflight, avoiding orphaned task claims when terminal startup fails.
- [x] Generate Codex bootstrap files under `${XDG_CACHE_HOME:-$HOME/.cache}/hapax/codex-spawns/` and pass them as the opening prompt.

## Phase 5.5 — Codex Adoption Benchmark Anchor

- [x] Locate the public Hapax Velocity Report artifact: `https://hapax.weblog.lol/velocity-report-2026-04-25`.
- [x] Locate the local canonical note: `~/Documents/Personal/30-areas/hapax/velocity-report-2026-04-25.md`.
- [x] Locate the source research drop: `docs/research/2026-04-25-velocity-comparison.md`.
- [x] Locate the publication task: `~/Documents/Personal/20-projects/hapax-cc-tasks/closed/leverage-mktg-velocity-report-publish.md`.
- [x] Record the internal benchmark to hit: 30 PRs/day, 137 commits/day, approximately 33,500 LOC churn/day, four concurrent Claude Code sessions, filesystem-as-bus coordination.
- [x] Define Codex success as matching or exceeding that baseline without weakening refusal-as-data, Obsidian transparency, deterministic hooks, or no-operator-labor publishing constraints.

## Phase 6 — Validation

- [x] Shell syntax check all changed scripts.
- [x] Run targeted hook and hygiene tests.
- [x] Smoke-test Codex hook config parsing with a temporary `CODEX_HOME`.
- [x] Smoke-test adapter blocks direct `pip` and axiom violations.
- [x] Smoke-test `hapax-codex` startup with Context7, local GitHub MCP, Tavily, hooks, and no approval gates active. Epidemic Sound MCP is decommissioned from startup until it has a stronger use case.
