# Reactive CI/CD — Design Document

**Date:** 2026-03-12
**Layer:** 1 of 3 (LLM-Driven SDLC)
**Status:** Design

---

## Problem

CI failures on hapax-council PRs currently require manual intervention — the operator must read logs, fix lint/typecheck/test errors, push, and wait for re-run. This is a mechanical loop that can be automated for well-scoped failure classes.

Additionally, PRs receive no automated code review. The operator is the sole reviewer, creating a single point of failure for code quality.

Auto-merge is disabled, requiring manual merge even when all checks pass and the PR is approved.

## Goals

1. **Auto-fix**: On CI failure, Claude Code diagnoses and fixes lint, typecheck, and format errors, commits with `[auto-fix]` tag, and CI re-runs.
2. **Auto-review**: On PR open/update, Claude Code reviews for bugs, security issues, and axiom compliance.
3. **Auto-merge**: When all checks pass and review is clean, trivial PRs auto-merge. Non-trivial PRs queue for human approval.

## Non-Goals

- Auto-fixing test logic failures (assertion mismatches, wrong behavior)
- Auto-fixing runtime/integration errors
- Replacing human judgment for architectural decisions
- Auto-merging changes to oversight systems (health monitor, axioms, alerts, backup scripts)

## Current State

- **CI workflow**: `.github/workflows/ci.yml` — 5 jobs (lint, typecheck, test, web-build, vscode-build)
- **Branch protection**: Strict — all 5 checks required on main
- **Auto-merge**: Disabled
- **CODEOWNERS**: Not configured
- **Linter**: Ruff (code + format)
- **Type checker**: Pyright (basic mode, permissive)
- **Test framework**: pytest + pytest-asyncio, `llm` tests excluded in CI

## Architecture

```
PR pushed / CI fails
  │
  ├── [Trigger: pull_request opened/synchronize]
  │   └── Claude PR Review (claude-code-action)
  │       ├── Bugs, security, axiom compliance
  │       ├── Posts inline review comments
  │       └── Does NOT approve (by design)
  │
  └── [Trigger: workflow_run CI completed + failed]
      └── Auto-Fix Job
          ├── Guard: not an [auto-fix] commit
          ├── Guard: < 3 auto-fix attempts on this branch
          ├── Guard: failure is lint/typecheck/format only
          ├── Claude Code fixes issues (--max-turns 5)
          ├── Commits with [auto-fix] prefix
          └── Push triggers CI re-run
                │
                └── [All checks pass + review clean]
                    └── Auto-merge (for trivial PRs only)
                        ├── Guard: diff < 50 lines
                        ├── Guard: no changes to protected paths
                        └── Merge via merge queue
```

## Infinite Loop Prevention

Five independent circuit breakers:

1. **Commit tag**: Skip if latest commit contains `[auto-fix]`
2. **Attempt counter**: Count `[auto-fix]` commits on branch. Stop at 3.
3. **Failure scope**: Only attempt fix for lint (`ruff`), typecheck (`pyright`), and format errors. Test failures, build failures → label `needs-human`.
4. **Turn budget**: `--max-turns 5` on Claude Code invocation.
5. **Job timeout**: `timeout-minutes: 10` on the GitHub Action job.

## Protected Paths (Never Auto-Merge)

Changes touching these paths always require human review, regardless of diff size or CI status:

```
agents/health_monitor.py
shared/alert_state.py
shared/axiom_enforcement.py
shared/config.py
axioms/
hooks/
systemd/
hapax-backup-*.sh
```

## Auto-Merge Criteria

A PR can auto-merge only when ALL of these hold:

- All 5 CI checks pass
- Claude review posted no HIGH-priority findings
- Diff < 50 lines total
- No files in protected paths list
- PR is not a draft
- PR was not created by an external contributor
- Auto-merge enabled on the PR (explicit opt-in)

## Security Constraints

- `ANTHROPIC_API_KEY` stored as GitHub repository secret
- Claude Code action pinned to specific commit SHA (not `@v1` tag)
- Minimal GitHub token permissions: `contents: write`, `pull-requests: write`
- Never `admin`, `security_events`, or `actions: write`
- Auto-fix only runs on branches owned by repo collaborators (not forks)
- Prompt injection mitigation: auto-fix prompt is hardcoded in workflow YAML, not derived from PR content
- All Claude output appears in GitHub Actions logs — no secrets in repo files Claude might read

## Cost Model

| Activity | Est. Cost/Run | Monthly Est. (20 PRs/wk) |
|----------|--------------|--------------------------|
| PR review (Sonnet) | $0.15-0.25 | $12-20 |
| Auto-fix (Sonnet) | $0.06-0.30 | $5-24 |
| GitHub Actions compute | $0.01-0.09 | $1-7 |
| **Total** | | **$18-51/month** |

Control: `--max-turns 5`, `timeout-minutes: 10`, concurrency groups, Sonnet (not Opus).

## Workflow Files

Two new workflow files:

### 1. `.github/workflows/claude-review.yml`
- Trigger: `pull_request` (opened, synchronize)
- Permissions: `contents: read`, `pull-requests: write`
- Concurrency: one per PR number
- Action: `anthropics/claude-code-action` with review prompt
- Model: `claude-sonnet-4-6`

### 2. `.github/workflows/auto-fix.yml`
- Trigger: `workflow_run` (CI workflow, completed)
- Condition: CI failed + not `[auto-fix]` commit + not main branch
- Permissions: `contents: write`, `pull-requests: write`
- Concurrency: one per branch
- Action: `anthropics/claude-code-action` with scoped fix prompt
- Model: `claude-sonnet-4-6`
- Budget: `--max-turns 5`, `timeout-minutes: 10`

## Repo Configuration Changes

1. Enable auto-merge in repo settings
2. Add CODEOWNERS file for protected paths
3. Enable merge queue (optional, recommended)
4. Add `ANTHROPIC_API_KEY` as repository secret

## Success Metrics

- **Auto-fix success rate**: % of lint/type failures resolved without human intervention
- **Review signal-to-noise**: % of Claude review comments that are actionable (not nitpicks)
- **Time-to-green**: Time from PR push to all checks passing (should decrease)
- **Human override rate**: % of auto-fix commits that humans subsequently modify
- **Cost per PR**: Track via Anthropic API dashboard

## Risks

| Risk | Mitigation |
|------|-----------|
| Infinite fix loop | 5 independent circuit breakers (see above) |
| Hallucinated fix introduces bug | Scoped to lint/type only; test suite catches regressions |
| Cost runaway | `--max-turns 5`, `timeout-minutes: 10`, Anthropic usage limits |
| Prompt injection via PR description | Fix prompt hardcoded in YAML, not derived from PR content |
| Review fatigue from noisy comments | Prompt tuned for signal; LOW-priority findings suppressed |
| Auto-merge merges bad code | Protected paths, diff size gate, review findings gate |

## Dependencies

- `anthropics/claude-code-action@v1` (pin to commit SHA)
- `ANTHROPIC_API_KEY` secret
- GitHub repo settings changes (auto-merge, optionally merge queue)
