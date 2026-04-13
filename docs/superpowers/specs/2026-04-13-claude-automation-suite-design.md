# Claude Code Automation Suite — Design

**Date:** 2026-04-13
**Author:** beta session 5
**Status:** Approved — implementation in progress
**Related plan:** `docs/superpowers/plans/2026-04-13-claude-automation-suite-plan.md`

---

## 1. Problem

The hapax-council Claude Code setup is mature (25 hooks, 15+ plugins, ~10 integrated MCP servers) but five specific frictions surfaced repeatedly during the 2026-04-12 / 2026-04-13 reverie+daimonion work:

1. **Docs-only PRs hit the CI paths-ignore filter and stall in branch protection.** PR #706, #708, #720 each needed a non-md carrier bundle. The workaround is documented in `CLAUDE.md § Council-Specific Conventions` but every author rediscovers it the hard way.

2. **Rust edits silently miss `cargo check` until CI catches them.** PR #715 (F8) and PR #718 (F7 + bind-group expects) both required manual `cd hapax-logos && cargo check -p hapax-visual` after each edit. Forgetting cost a 7-minute CI cycle on a typo.

3. **Cross-worktree edits to peer territory require manual relay coordination.** Items 3-5 of beta session 4 touched delta's Rust files. The pattern that worked was: read peer relay yaml → grep convergence.log → append outbound note → then edit. Mechanical enough to automate; skipping it was the failure mode delta and the predecessor explicitly warned against.

4. **Multi-language data flows develop dead wires that take ~10 minutes to audit by hand.** The PR #555 → PR #710 silent regression (six dispatch effects dead for 10 days) and the F8 content.* bridge break (multi-day) were both "obvious in retrospect, invisible in code review" because each touched 4-hop chains: Python → uniforms.json → Rust override branch → WGSL shader read site, OR Python recruitment → affordance pipeline → daemon attribute → handler. A manual audit walks every hop; a specialized subagent could do it in seconds.

5. **GPU-bound features cannot be tested in pytest** (no wgpu device in CI), so deploy verification is "remember to jq the right keys after a rebuild". F8 verification is still pending as of session 5 start because nobody has run the canonical check.

The common pattern across all five: **the operator has to remember to invoke the right safeguard at the right moment**. The constitutional fix is to make the safeguards auto-fire — hooks that run on tool events without invocation, and subagents that the main Claude auto-invokes via description routing (no `/skill-name` needed).

## 2. Goals

- **Auto-firing only.** Every automation in this suite must run without an explicit user command. Hooks fire on tool events; subagents fire from main Claude's description-based routing. No `disable-model-invocation: false` skills that wait for `/slash-command`.
- **Advisories over blocks where possible.** Three of the five problems are "operator forgot, not operator wrong". The hooks should warn loudly via stderr and exit 0, not block via exit 2, except where a block is the only way to prevent a confirmed-bad action.
- **Single-user scope.** Subagents and global Claude settings updates are machine-local. The repo ships the canonical hook scripts and design docs; per-machine wiring is documented in the plan but not enforced.
- **Cargo-check is the only synchronous-blocking work.** The other automations are either pure-text checks (pattern matching against staged diff or yaml prose) or subagent dispatches (Claude reasons about whether to spawn). Cargo check is ~1s incremental, acceptable for a PostToolUse advisory.
- **Fail-open on every error.** Every hook follows the existing convention: JSON parse failure → exit 0, no git context → exit 0, missing tool → exit 0. The hooks must never block work because of their own bugs.

## 3. Non-goals

- **Not adding new MCP servers.** The existing surface (hapax, context7, playwright, claude.ai integrations) covers active needs. Adding more dilutes focus.
- **Not adding new plugins.** The user already has 15+ plugins installed.
- **Not adding user-invocable skills.** The user explicitly stated they almost never invoke skills explicitly. This requirement maps to hooks + auto-invoked subagents only.
- **Not formalizing a structured `file_scope` field in the relay yaml.** The relay protocol is prose-based and works fine for human readers. The relay-coordination-check hook will fuzzy-match against the existing prose fields rather than mutate the schema.
- **Not preventing the PR #555 class of regression at write-time.** The dispatch tracer subagent is invoked when editing the relevant files, but it cannot run inside CI for every PR. It is an aid, not a gate.
- **Not implementing pool metrics IPC exposure.** That is the deferred follow-up from delta PR-3 and lives in the hapax-visual crate, not in this automation suite.

## 4. Solution

Six automations across two layers.

### 4.1 Hooks (3 — all auto-firing on tool events)

| Hook | Event | Tool match | Trigger condition | Result |
|------|-------|------------|---------------------|--------|
| `docs-only-pr-warn.sh` | PreToolUse | `Bash` | command matches `git commit` AND `git diff --cached --name-only` is entirely under `docs/**` / `*.md` / `lab-journal/**` / `research/**` / `axioms/**/*.md` AND current branch ≠ `main` | stderr advisory pointing at the canonical CLAUDE.md note + the `__all__` carrier pattern; exit 0 |
| `cargo-check-rust.sh` | PostToolUse | `Edit\|Write\|MultiEdit\|NotebookEdit` | edited file path matches `hapax-logos/crates/<crate>/src/**/*.rs` | runs `cd hapax-logos && cargo check -p <crate>` (silent on success), prints first 20 error lines on failure; exit 0 always |
| `relay-coordination-check.sh` | PreToolUse | `Edit\|Write\|MultiEdit\|NotebookEdit` | edited file path is under one of the cross-worktree-territory prefixes (see §4.3) | reads peer relay yaml files under `~/.cache/hapax/relay/`, fuzzy-matches edited path against peer `focus`/`current_item`/`decisions`/`context_artifacts` fields; if any peer matches AND that peer's `session_status` is `ACTIVE`, prints stderr advisory naming the peer and the matched field; exit 0 always |

**Why each hook is auto-firing not user-invoked:**

- `docs-only-pr-warn`: the operator is about to invoke `git commit` — they're already at the friction point. A hook is the only place in the workflow that can intercept the commit attempt.
- `cargo-check-rust`: edits arrive via Edit/Write tool calls during normal Claude work. A PostToolUse hook is the only place that runs immediately after an edit without user action.
- `relay-coordination-check`: edits arrive via the same Edit/Write tools. PreToolUse fires before the write so the operator sees the warning while there's still time to coordinate.

**Why exit 0 (advisory) for all three:**

- `docs-only-pr-warn` — the operator may legitimately want a docs-only commit (e.g., resetting beta-standby, partial work in progress). Blocking would interrupt valid work.
- `cargo-check-rust` — Rust edit may be intermediate (operator is iterating); CI is the actual gate. Hook is a fast feedback loop, not a checkpoint.
- `relay-coordination-check` — fuzzy-matching peer prose is high-recall low-precision. Blocking on every fuzzy match would be obnoxious. Advisory lets the operator decide.

### 4.2 Subagents (3 — auto-invoked by main Claude via description routing)

Each subagent definition lives in the operator's global `~/.claude/agents/<name>.md` (machine-local; shipped via the `tooling/claude-agents/` template directory documented in §6 and copied during install).

| Subagent | Auto-invocation trigger | What it does |
|----------|------------------------|--------------|
| `shader-bridge-auditor` | Edits to `agents/reverie/_uniforms.py`, any `agents/shaders/nodes/*.wgsl`, `hapax-logos/crates/hapax-visual/src/dynamic_pipeline.rs`, or `uniform_buffer.rs` | Walks the four-hop bridge: Python writer → uniforms.json key → Rust override branch → shader read site. Reports any dead wires (key written by Python with no Rust handler, or vice versa) and any shader uniforms with no writer at all. Read-only. |
| `affordance-pipeline-tracer` | Edits to `agents/hapax_daimonion/run_*.py`, `agents/hapax_daimonion/init_pipeline.py`, `agents/hapax_daimonion/cpal/*.py`, `agents/hapax_daimonion/capability.py`, or any file matching `agents/*_capability.py` | Walks every caller of `_affordance_pipeline.select`/`record_outcome` and every recruited capability registered in `init_pipeline`. Verifies each capability has a live dispatch handler reachable from a spawned background task. Reports dead branches (registered + recruited but no live consumer — the PR #555 class). Read-only. |
| `gpu-smoke-verifier` | After a PR merges that touches `hapax-logos/crates/hapax-visual/**`, `agents/reverie/_uniforms.py`, `agents/reverie/mixer.py`, or shader files. Also when the operator says anything like "verify the bridge is healthy" or "smoke test reverie". | Reads `/dev/shm/hapax-imagination/{uniforms.json,plan.json,current.json}`, `/dev/shm/hapax-reverie/predictions.json`, and frame mtimes. Reports HEALTHY/DEGRADED with exit-criteria matching the `reverie_uniforms_key_deficit > 5` tripwire from PR #713. Calls into `agents.reverie.debug_uniforms.snapshot()` for the canonical comparison. Read-only + Bash for jq. |

**Why each subagent is description-auto-invoked not user-invoked:**

- The main Claude already knows when it has just edited `_uniforms.py` or `dynamic_pipeline.rs`. A description that says "Use proactively after editing X" makes Claude spawn the subagent automatically as part of its post-edit reasoning.
- The user constraint ("almost never invoke explicitly") applies to user-facing slash commands. Subagents auto-invoked by Claude on its own initiative ARE invocation-free from the user's perspective — Claude does it.
- `<example>` blocks in each subagent description show the assistant proactively spawning the subagent in concrete scenarios. This is the canonical pattern in the existing `feature-dev:code-reviewer`, `pr-review-toolkit:silent-failure-hunter`, and `plugin-dev:plugin-validator` agents (see research findings in §7).

### 4.3 Cross-worktree territory definition

The `relay-coordination-check` hook needs to know which paths are "cross-worktree-shared". From the convergence.log audit (last 7 days):

```
hapax-logos/crates/**                  # delta/beta/alpha all touch
agents/studio_compositor/**            # alpha owns, delta + source-registry epic touches
agents/reverie/**                      # delta retired, beta touches
agents/hapax_daimonion/**              # beta owns, alpha audited
agents/dmn/**                          # cross-pollinates with daimonion
agents/visual_layer_aggregator/**      # alpha + beta both touch
shared/**                              # cross-cutting
agents/effect_graph/**                 # alpha owns, reverie satellites depend on
```

Files under `tests/`, `docs/`, `scripts/` are not flagged because conflicts there are mechanical merges, not semantic regressions.

## 5. Integration with existing infrastructure

### 5.1 Hooks plug into the existing global Claude settings

The hapax workspace already wires 25 hooks via the operator's global `settings.json`. The three new hooks are added as additional entries in the existing `PreToolUse`/`PostToolUse` arrays. The matcher patterns mirror the conventions already in use.

The wired bindings reference absolute paths to the tracked scripts (e.g., `<workspace>/hooks/scripts/docs-only-pr-warn.sh`).

### 5.2 Subagents use the canonical local-agents convention

Subagent `.md` files with `name`, `description`, `tools`, `model` frontmatter. The description includes the "Use proactively" trigger phrase + 2-3 `<example>` blocks per the existing `pr-review-toolkit:code-reviewer` and `feature-dev:code-reviewer` patterns.

### 5.3 Hooks share the existing skeleton

Every hook follows the canonical pattern from `axiom-commit-scan.sh` and `no-stale-branches.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
INPUT="$(cat)"
TOOL="$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
# ... matcher logic ...
# Advisory: echo to stderr, exit 0
# Block: echo to stderr, exit 2
exit 0
```

## 6. Distribution and install

Hooks are tracked in `hooks/scripts/`. Subagent definitions are tracked in `tooling/claude-agents/` as canonical sources, and the install step (manual, post-merge) copies them to the operator's global agents directory. The repo cannot ship the global Claude settings file directly because it is gitignored.

The plan doc walks through the manual install of subagents + the settings.json update. After this PR merges:

1. `cp tooling/claude-agents/*.md <operator-claude-config>/agents/`
2. Append the three new hook bindings to the operator's global `settings.json` (see plan §3.4 for the exact JSON snippet).
3. Restart any open Claude Code sessions so the new hooks are picked up.

This is the same install pattern the operator already uses for the 25 existing hooks (the scripts are tracked, the wiring is local).

## 7. Research findings backing this design

### 7.1 Hook infrastructure (Explore subagent, 2026-04-13)

- 25 hook scripts in `hooks/scripts/`, all tracked in git.
- The operator's global `settings.json` (untracked) wires them via absolute paths.
- PreToolUse (13 hooks) for blocks/checks before tool execution; PostToolUse (7) for advisories after; SessionStart/Stop (4) for session lifecycle.
- Canonical pattern: `set -euo pipefail`, `INPUT="$(cat)"`, jq-extract `.tool_input.*`, `echo to stderr + exit 0/2`. All hooks fail-open on JSON errors.
- Sibling-worktree filtering pattern (lines 168-176 in `no-stale-branches.sh`) walks `git worktree list` to skip branches owned by other sessions. The relay-coordination-check hook reuses this pattern when checking which session "owns" a given file path.
- The only existing hook that gates `git commit` content is `axiom-commit-scan.sh:18-36`. Its `git diff --cached` extraction pattern is the template for `docs-only-pr-warn.sh`.

### 7.2 Subagent infrastructure (Explore subagent, 2026-04-13)

- Subagents live in plugin `agents/<name>.md` files with frontmatter (`name`, `description`, `model`, `tools`, optional `color`).
- Auto-invocation contract is the `description:` field. Phrasing: "Use this agent when [trigger]" + "**Use proactively after** [action]" + 2-3 `<example>` blocks showing the assistant spawning the subagent.
- Strongest auto-invocation signal: `<example>` blocks where the user says something innocuous and the assistant explicitly says "I'll use the X agent to ...".
- **Hooks cannot directly invoke subagents.** Hooks run shell commands only; the subagent layer is invoked by Claude's reasoning. A hook can print stderr text that includes "consider running shader-bridge-auditor" and Claude will read it and act, but the hook does not spawn the agent itself.
- Canonical examples studied: `pr-review-toolkit:code-reviewer`, `feature-dev:code-reviewer`, `pr-review-toolkit:silent-failure-hunter`, `plugin-dev:plugin-validator`, `hookify:conversation-analyzer`. All use the "Use proactively after" + `<example>` pattern.

### 7.3 CI paths-ignore (Explore subagent, 2026-04-13)

- `.github/workflows/ci.yml` lines 6-19: `paths-ignore` covers `docs/**`, `*.md`, `lab-journal/**`, `research/**`, `axioms/**/*.md`. ALL jobs (lint, typecheck, test, web-build, vscode-build, secrets-scan, security) skip when only those paths change.
- Same patterns in `claude-review.yml:6-10` (minus `axioms/**/*.md`).
- Branch protection requires the `test` job to pass — so docs-only PRs hit eternal "checks not started" limbo.
- Verified: the workaround is to bundle one non-md file change per the existing `__all__` carrier pattern (PR #708 used `shared/impingement_consumer.py`, PR #720 used `agents/reverie/debug_uniforms.py`).

### 7.4 Cross-worktree friction audit (Explore subagent, 2026-04-13)

Five friction events in the past 7 days:

| File | Sessions | Manual coordination required |
|---|---|---|
| `agents/hapax_daimonion/run_inner.py` | beta vs alpha (camera epic boundary) | Convergence.log note before edit |
| `agents/studio_compositor/**` | alpha (camera epic) vs delta (source-registry) | Delta read alpha's relay yaml, stood down from competing implementation |
| `hapax-logos/crates/hapax-visual/{dynamic_pipeline,uniform_buffer}.rs` | beta cross-worktree edits during F8 | Verified delta closed via session_status, added alpha.yaml convergence note |
| Reverie state files in `/dev/shm` | delta + beta (parallel F6 fixes) | Both fixes orthogonal; no manual coordination but luck-based |
| `/dev/shm/hapax-imagination/uniforms.json` | three-way concurrent reads/writes | Versioning via `frame_id`/mtime; tolerant readers; no coordination |

Relay yaml schema is prose-based: `focus`, `current_item`, `decisions[].what`, `context_artifacts[]`. No structured `file_scope` field. The `relay-coordination-check` hook regex-mines these fields rather than mutating the schema. Recall is moderate (string-match against prose) but precision is high (peer paths typically appear verbatim). False negatives are acceptable because the hook is advisory only.

## 8. Risk + rollback

| Risk | Likelihood | Mitigation |
|---|---|---|
| Hook bug blocks legitimate work | Low | All three hooks exit 0 on failure (advisory mode). Even an internal bug fails open. |
| `cargo check` is slow on cold cache and slows iteration | Medium | Hook checks `cargo --offline check` first; falls back to network only if offline fails. ~1s incremental, ~30s cold. Operator can disable via env var. |
| Subagent description over-fires and Claude spawns too often | Medium | Descriptions include explicit `<example>` blocks for negative cases. If over-firing observed, narrow trigger conditions. |
| Relay yaml fuzzy-match has false positives | Medium | Hook is advisory only. Operator can ignore. Fix forward: tighten the match patterns. |
| Subagents are machine-local and a future operator forgets to install them | High | Canonical sources tracked in `tooling/claude-agents/`. Install step in plan doc + a `setup-claude-automation.sh` script that copies them and patches settings.json. |
| Hook scripts conflict with existing hooks via shared state | Low | Each hook is self-contained, reads only stdin and read-only filesystem. No cross-hook state. |
| `git diff --cached` is empty when the operator runs `git commit -a` | Low | The `docs-only-pr-warn` hook checks both staged and unstaged diff when `-a` is in the command. |

Rollback: revert the hook entries from the operator's global `settings.json`. The hook scripts can stay in `hooks/scripts/` indefinitely without being wired. Subagents in the global agents directory can be deleted with `rm`.

## 9. Acceptance criteria

- **AC1.** `hooks/scripts/docs-only-pr-warn.sh` exists, is executable, follows the canonical hook pattern, and exits 0 with a stderr advisory when run on a feature branch with only docs/md staged. Returns exit 0 silently when staged changes include any non-md file.
- **AC2.** `hooks/scripts/cargo-check-rust.sh` exists, is executable, and on a PostToolUse Edit event with `file_path` matching `hapax-logos/crates/<crate>/src/**/*.rs` runs `cargo check -p <crate>` and reports failures via stderr. Returns exit 0 silently on success and on non-Rust edits.
- **AC3.** `hooks/scripts/relay-coordination-check.sh` exists, is executable, and on a PreToolUse Edit/Write event with `file_path` under a cross-worktree-territory prefix reads peer relay yaml files and emits a stderr advisory if any peer's `session_status` is `ACTIVE` AND the file path appears in the peer's `focus`/`current_item`/`decisions`/`context_artifacts`. Returns exit 0 always.
- **AC4.** `tooling/claude-agents/shader-bridge-auditor.md` exists with frontmatter `name`, `description` (containing "Use proactively after editing"), `tools: [Glob, Grep, LS, Read, Bash]`, `model: opus`. Contains 2-3 `<example>` blocks.
- **AC5.** `tooling/claude-agents/affordance-pipeline-tracer.md` exists with the same structure, triggers on daimonion run loop / init_pipeline edits.
- **AC6.** `tooling/claude-agents/gpu-smoke-verifier.md` exists with the same structure, triggers on post-merge verification of hapax-visual changes.
- **AC7.** A `tooling/claude-agents/INSTALL.md` file documents the per-machine install: cp the agent files to the global agents directory plus the settings.json snippet to add the hook bindings.
- **AC8.** The design doc and plan doc are in `docs/superpowers/specs/` and `docs/superpowers/plans/` respectively. Both are referenced from each other.
- **AC9.** PR is bundled with a non-md carrier (the hook scripts and `tooling/` files satisfy this; the design+plan markdown alone would not).
- **AC10.** All three hooks pass a smoke test where the hook is invoked manually with a JSON payload simulating the trigger condition.

## 10. Out of scope (deferred)

- **Pool metrics IPC exposure** — separate cross-worktree Rust work, belongs in hapax-visual.
- **Sprint 0 G3 gate state mismatch** — outside vocal/visual workstream.
- **Apperception cascade direct-feed integration test** — separate testing concern.
- **B4 end-to-end smoke** — depends on a `hapax-imagination` rebuild, which depends on F8 deploy verification.
- **Subagent for the relay protocol itself** — could automate writing convergence notes, but the existing prose pattern works and adding structure would conflict with operator preferences observed in the relay log.
