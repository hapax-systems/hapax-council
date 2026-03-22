# LLM-Assisted CI/CD for Reactive Automation

**Research Date:** 2026-03-12
**Scope:** On CI failure, LLM auto-fixes and pushes. On PR open, LLM reviews. On all checks green, auto-merge.

---

## 1. GitHub Actions + Claude Code Integration

### anthropics/claude-code-action

The official `anthropics/claude-code-action` GitHub Action (v1.0, GA since Aug 2025, 6.2k stars, 81 contributors) is the primary integration point. It runs Claude Code on GitHub-hosted runners within your own infrastructure.

**Supported triggers:**
- `issue_comment` / `pull_request_review_comment` -- responds to `@claude` mentions
- `pull_request` (opened, synchronize, reopened) -- automatic PR review
- `schedule` / `workflow_dispatch` -- cron jobs, manual triggers
- Any GitHub event via custom workflow configuration

**Auth requirements:**
- `ANTHROPIC_API_KEY` as a repository secret (direct API), OR
- AWS Bedrock via OIDC federation (no static keys), OR
- Google Vertex AI via Workload Identity Federation
- GitHub App token (either the official `claude` app via `/install-github-app`, or a custom GitHub App with Contents, Issues, Pull Requests read/write)

**Minimum GitHub permissions:**
```yaml
permissions:
  contents: read      # read repo
  issues: write       # comment on issues
  pull-requests: write # comment on PRs, create reviews
  # Add contents: write for commits/PRs
  # Add id-token: write for OIDC (Bedrock/Vertex)
```

**Key inputs:**
- `prompt` -- instructions for Claude (optional; omit for @claude interactive mode)
- `claude_args` -- CLI passthrough (`--max-turns`, `--model`, `--allowed-tools`, `--mcp-config`)
- `anthropic_api_key`, `github_token`, `trigger_phrase`, `use_bedrock`, `use_vertex`

**Capabilities:**
- Read/write files, run bash commands, analyze diffs, post review comments
- Create commits, push branches, open PRs
- Respects `CLAUDE.md` project guidelines
- Structured JSON output via action outputs
- MCP server integration for extended tooling
- Skills system for reusable workflows

**Limitations:**
- Cannot approve PRs (by design -- human review required)
- Limited to GitHub context by default (no arbitrary external API calls without MCP)
- Context window constraints (performance degrades as context fills)
- Cannot permanently change repo settings
- No access to private packages without explicit configuration
- Runs on GitHub-hosted runners (ubuntu-latest typical), subject to runner time limits

**IMPORTANT: The action runs with `--dangerously-skip-permissions` in CI.** This means Claude can modify files without per-action approval. The official docs explicitly warn: "Only use in a sandbox without internet access." In CI, the runner is ephemeral, which partially mitigates this, but it means the LLM has full filesystem access on the runner.

### Claude Code Non-Interactive Mode

For custom CI workflows beyond the action, `claude -p "prompt"` runs Claude non-interactively:
```bash
claude -p "Fix the lint errors in this repo" --output-format json --max-turns 5
```
This enables integration into any CI system, not just GitHub Actions.

---

## 2. Existing Tools in This Space

### Tier 1: Production-Grade LLM PR Reviewers

| Tool | What it does | Strengths | Weaknesses |
|------|-------------|-----------|------------|
| **CodeRabbit** | AI PR review on GitHub/GitLab/Azure/Bitbucket. 2M+ repos. | Line-by-line suggestions, 1-click commit for easy fixes, "Fix with AI" for harder ones, 40+ linter integrations, YAML config, learns from feedback. | Primarily review, not autonomous fix-and-push. Paid for full features. |
| **Greptile** | AI code review with full codebase graph. | Custom rules in plain English, mermaid diagrams, confidence scores, learns from emoji reactions. $30/dev/month. | Less mature auto-fix. Self-hosted option (AWS only). |
| **Qodo** (formerly CodiumAI) | Enterprise code review, 15+ agentic workflows. | 73.8% acceptance rate at monday.com, 800+ issues prevented/month. Multi-repo context. Living rules system. | Enterprise-focused pricing. |

### Tier 2: Autonomous Coding Agents

| Tool | What it does | Status |
|------|-------------|--------|
| **GitHub Copilot Coding Agent** (Project Padawan) | Assign issues directly to Copilot, produces tested PRs in secure cloud sandbox. | GA as of late 2025. Dual-model architecture (GPT-4o/o1/Claude/Gemini). Human approval required for merge. |
| **GitHub Copilot Autofix** | CodeQL-powered security fix suggestions on code scanning alerts. Uses GPT-5.1. | Available on all public repos, GHAS license for private. Covers C#, C/C++, Go, Java, JS/TS, Python, Ruby, Rust. |
| **Claude Code Action** | Full agentic coding in CI. | GA v1.0. Most flexible for custom automation. |
| **Sweep.dev** | Was an AI coding assistant for automated PRs. | Pivoted to JetBrains IDE plugin (autocomplete). No longer a CI/CD tool. |

### Tier 3: Emerging / Niche

| Tool | Notes |
|------|-------|
| **OpenAI Codex CLI** | Similar concept to Claude Code but for OpenAI models. CI integration possible but less documented. |
| **Cursor / Windsurf** | IDE-focused, no native CI integration. |
| **Aider** | Open-source CLI coding assistant. Can be scripted in CI but no official action. |
| **SWE-agent** (Princeton) | Research-grade autonomous SWE agent. Not production CI tooling. |

### Failure Modes Observed Across Tools

1. **Hallucinated fixes** -- LLM "fixes" that compile but don't address the root cause
2. **Dependency confusion** -- suggesting packages that don't exist or are malicious
3. **Context overflow** -- large repos exhaust context, leading to partial/wrong fixes
4. **Infinite retry loops** -- fix introduces new failure, triggering another fix attempt
5. **Style drift** -- LLM-authored code diverges from project conventions over time
6. **Noisy reviews** -- low-signal comments on obvious code, "review fatigue"

---

## 3. Auto-Fix Patterns

### Standard "Fix on Failure" Loop

```yaml
name: Auto-Fix on CI Failure
on:
  # Trigger: a check suite or workflow fails
  workflow_run:
    workflows: ["CI"]
    types: [completed]

jobs:
  auto-fix:
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_branch }}

      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: |
            The CI workflow failed. Analyze the failure logs, identify the root cause,
            fix the issue, and commit the fix. Only fix lint, type, and test errors.
            Do NOT refactor unrelated code.
          claude_args: "--max-turns 10"
```

### Preventing Infinite Loops

This is the critical engineering challenge. Common strategies:

1. **Attempt counter via commit message or label:**
   ```yaml
   if: |
     github.event.workflow_run.conclusion == 'failure' &&
     !contains(github.event.workflow_run.head_commit.message, '[auto-fix]')
   ```
   Tag auto-fix commits with `[auto-fix]` and skip if already attempted.

2. **Max retry count via GitHub API:**
   Check how many `[auto-fix]` commits exist on the branch. If > N (typically 2-3), stop and open an issue or notify humans.

3. **Budget cap via `--max-turns`:**
   Limit Claude to 5-10 turns. If it can't fix in that budget, it fails gracefully.

4. **Scope restriction:**
   Only auto-fix specific failure types: lint, formatting, type errors. Never auto-fix logic failures or test assertion mismatches.

5. **Time-based circuit breaker:**
   Track timestamps. If auto-fix has been attempted within the last 30 minutes on the same branch, skip.

6. **Branch isolation:**
   Auto-fix pushes to a separate branch (`auto-fix/<original-branch>`) and opens a PR rather than pushing directly. This prevents the loop from ever touching the original branch's CI.

### Recommended Pattern

```
CI fails
  -> Check: is this an auto-fix commit? (STOP if yes)
  -> Check: have we attempted > 2 fixes on this branch? (STOP, notify human)
  -> Check: is the failure type in our allow-list? (STOP if not)
  -> Run Claude with --max-turns 5, scoped prompt
  -> Commit with [auto-fix] tag
  -> CI re-runs naturally on push
  -> If still failing after 2 auto-fix attempts, label PR "needs-human"
```

---

## 4. PR Auto-Review

### How LLM PR Reviewers Work in Practice

**Typical workflow:**
1. PR opened/updated triggers GitHub Action
2. Action checks out code, computes diff
3. LLM receives diff + context (CLAUDE.md, related files, PR description)
4. LLM posts review comments (inline on specific lines or as summary)

**Signal-to-noise ratio:**
- CodeRabbit reports ~74% acceptance rate at scale (monday.com case study)
- Greptile users report median merge time reduction from 20h to 1.8h
- Common complaint: too many "nitpick" comments on style that linters should catch
- Best results when LLM review is scoped: security-only, architecture-only, or bug-finding-only

**Do teams trust LLM approvals?**
- **No team in production uses LLM-only approval for logic changes.** This is a universal finding.
- LLM approval is trusted for: formatting fixes, dependency bumps, doc-only changes, auto-generated code
- GitHub branch protection can require CODEOWNERS approval regardless of LLM review status

### Guardrails for LLM Review

| Guardrail | Implementation |
|-----------|---------------|
| **Diff size gate** | Only auto-approve if diff < N lines (e.g., 50 lines) |
| **File type gate** | Only auto-approve changes to `.md`, `.json`, config files |
| **Change type gate** | Only auto-approve if all changes are lint/format fixes (detect via commit message tag) |
| **Require human for logic** | If diff touches `.py`, `.ts`, `.go` implementation files, require CODEOWNERS |
| **Confidence threshold** | Some tools (Greptile) emit confidence scores; gate on score > threshold |
| **Two-LLM review** | Use a second LLM as adversarial reviewer (expensive but effective for security) |

### Recommended PR Review Workflow

```yaml
name: Claude PR Review
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: |
            Review this PR. Focus on:
            1. Bugs and logic errors (HIGH priority)
            2. Security vulnerabilities (HIGH priority)
            3. Performance issues (MEDIUM priority)
            4. Code style violations not caught by linters (LOW priority)

            Do NOT comment on: formatting, import order, or things
            the linter already catches. Be specific and actionable.
            If the PR looks good, say so briefly.
          claude_args: "--max-turns 5 --model claude-sonnet-4-6"
```

---

## 5. Auto-Merge with Branch Protection

### GitHub Auto-Merge Feature

- Enabled per-repo in Settings > General > Pull Requests
- PR author (with write access) clicks "Enable auto-merge"
- PR merges automatically when ALL required status checks pass AND required reviews are approved
- If someone without write access pushes to the PR, auto-merge disables automatically

### Branch Protection Rules Interaction

| Protection Rule | Impact on LLM Auto-Merge |
|----------------|--------------------------|
| **Required status checks** | LLM-authored commits trigger CI like any other. Auto-merge waits for all checks. |
| **Required reviews** | LLM cannot approve its own PRs. A human or a separate bot with review permission must approve. |
| **CODEOWNERS** | If CODEOWNERS file exists and matches changed files, those owners must approve. LLM cannot satisfy CODEOWNERS. |
| **Require signed commits** | LLM commits via GitHub API are signed by GitHub's GPG key. Commits pushed via `git push` from CI need a GPG key configured on the runner. |
| **Require linear history** | Forces squash or rebase. Compatible with auto-merge. |
| **Restrict pushes** | Can whitelist the GitHub App or bot account that Claude uses. |

### Merge Queues

GitHub merge queues (available on Team/Enterprise) provide additional safety:
- PRs enter a FIFO queue after approval
- Queue creates temporary branches (`gh-readonly-queue/...`) to validate against latest base + preceding PRs
- If validation fails, PR is removed from queue and remaining PRs revalidated
- Configurable: build concurrency (1-100), merge batch sizes, timeout thresholds
- Workflows must include `merge_group` event trigger

**For LLM-authored PRs, merge queues are strongly recommended** because they prevent the "semantic merge conflict" problem where two individually-correct PRs conflict when merged together.

### Recommended Auto-Merge Architecture

```
PR opened by human
  -> Claude reviews (GitHub Action, PR comment)
  -> CI runs (lint, test, build)
  -> Human approves (satisfies CODEOWNERS + required reviews)
  -> Auto-merge enabled (by human or automation)
  -> Merge queue validates against latest main
  -> Merge

PR opened by Claude (auto-fix branch)
  -> CI runs
  -> If diff is trivial (lint/format only):
       -> Auto-approve via separate bot account (NOT Claude's own token)
       -> Auto-merge via merge queue
  -> If diff is non-trivial:
       -> Request human review
       -> Human approves
       -> Auto-merge via merge queue
```

**Key constraint:** The token used to approve a PR must be different from the token that created the PR. GitHub prevents self-approval even for bots. Use a separate GitHub App or bot account for approval.

---

## 6. Security Considerations

### Can the LLM Introduce Vulnerabilities?

**Yes.** This is the primary risk. Documented failure modes:

1. **Hallucinated dependencies:** LLM suggests `npm install foo-utils` where `foo-utils` is a typo-squatting package or doesn't exist. GitHub Copilot Autofix docs explicitly warn about "fabricated dependencies" and "malicious packages masquerading under probable names."

2. **Partial fixes:** Fix resolves the immediate error but introduces a new vulnerability (e.g., disabling input validation to fix a type error).

3. **Prompt injection via PR content:** A malicious PR description or issue body could contain instructions that manipulate the LLM into introducing backdoors. This is especially dangerous with `--dangerously-skip-permissions`.

4. **Secrets in logs:** Claude's output appears in GitHub Actions logs. If Claude reads a file containing secrets and includes them in output, they're exposed in CI logs. Mitigation: use `::add-mask::` in workflow, or scope Claude's file access.

5. **Token permission escalation:** If the `GITHUB_TOKEN` has `contents: write`, Claude can push to any branch the token has access to. Scope tokens minimally.

### Supply Chain Risks

- LLM-authored code is not deterministic -- the same prompt can produce different code
- No provenance chain: you can't audit "why did the LLM write this specific line"
- Review burden shifts: humans must review LLM code with the same rigor as human code
- Dependency suggestions should be validated against a lockfile or allowlist

### Permission Scoping Recommendations

```yaml
# Minimal permissions for review-only
permissions:
  contents: read
  pull-requests: write

# For auto-fix (needs to push commits)
permissions:
  contents: write
  pull-requests: write

# NEVER grant unless absolutely needed:
#   admin, security_events, actions (write)
```

### Mitigation Checklist

- [ ] Use `--max-turns` to cap Claude's iteration budget
- [ ] Restrict `--allowed-tools` to only what's needed (e.g., `Edit,Bash(npm test)`)
- [ ] Use branch protection: require human approval for non-trivial changes
- [ ] Use CODEOWNERS for security-sensitive paths
- [ ] Pin `anthropics/claude-code-action@v1` to a specific commit SHA, not just `@v1`
- [ ] Monitor API usage for anomalies (unexpected spikes = possible prompt injection loop)
- [ ] Run LLM-authored code through the same SAST/DAST pipeline as human code
- [ ] Use merge queues to catch integration issues
- [ ] Audit Claude's commits with the same scrutiny as any contributor

---

## 7. Cost and Rate Limiting

### GitHub Actions Costs

| Plan | Free Minutes/Month | Linux Rate | Storage |
|------|-------------------|------------|---------|
| Free | 2,000 | $0.006/min (2-core) | 500 MB |
| Pro/Team | 3,000 | $0.006/min | 2-50 GB |
| Enterprise | 50,000 | $0.006/min | 50 GB |

A typical Claude Code CI run takes 2-15 minutes depending on task complexity. At $0.006/min (Linux 2-core), that's $0.012-$0.09 per run for GitHub compute.

### Claude API Costs (per 1M tokens, as of early 2026)

| Model | Input | Output | Cached Input | Batch Input | Batch Output |
|-------|-------|--------|-------------|-------------|--------------|
| Claude Sonnet 4 | $3 | $15 | $0.30 | $1.50 | $7.50 |
| Claude Opus 4 | $15 | $75 | $1.50 | $7.50 | $37.50 |
| Claude Haiku 3.5 | $0.80 | $4 | $0.08 | $0.40 | $2.00 |

**Estimated cost per CI run (Sonnet, typical):**
- Simple lint fix: ~10K input + 2K output = ~$0.06
- PR review (medium diff): ~50K input + 5K output = ~$0.23
- Complex auto-fix (10 turns): ~200K input + 20K output = ~$0.90
- Large PR review (big diff): ~500K input + 10K output = ~$1.65

**Monthly cost estimates (team of 5, active repo):**
- Review-only (20 PRs/week): ~$20-80/month API + ~$5-10 Actions
- Review + auto-fix (20 PRs + 10 fixes/week): ~$50-150/month API + ~$10-20 Actions
- Heavy usage (50 PRs + 30 fixes/week): ~$150-400/month API + ~$30-60 Actions

### Cost Control Strategies

1. **Model selection:** Use Sonnet (not Opus) for routine tasks. Reserve Opus for complex reviews.
2. **`--max-turns` cap:** Set to 5 for review, 10 for fix. Prevents runaway token consumption.
3. **Workflow-level timeout:** `timeout-minutes: 15` on the job.
4. **Concurrency controls:**
   ```yaml
   concurrency:
     group: claude-${{ github.ref }}
     cancel-in-progress: true
   ```
   This ensures only one Claude run per branch at a time.
5. **Trigger filtering:** Don't run on draft PRs, bot-authored PRs, or docs-only changes.
6. **GitHub spending limits:** Set a hard cap in GitHub billing settings.
7. **Anthropic usage limits:** Set per-key usage limits in the Anthropic console.
8. **Prompt caching:** For repos where CLAUDE.md + system context is large, cached input tokens cost 90% less.

---

## 8. Concrete Recommendations

### For the hapax ecosystem (hapax-council, hapax-officium, etc.)

Given the architecture described in `CLAUDE.md` (multiple agent repos, shared infra, reactive filesystem engine), here is a phased adoption plan:

#### Phase 1: PR Review (Low Risk, High Value)

Add to each repo:
```yaml
name: Claude PR Review
on:
  pull_request:
    types: [opened, synchronize]
  issue_comment:
    types: [created]

jobs:
  review:
    if: |
      github.event_name == 'pull_request' ||
      contains(github.event.comment.body, '@claude')
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
      pull-requests: write
    concurrency:
      group: claude-review-${{ github.event.pull_request.number || github.event.issue.number }}
      cancel-in-progress: true
    steps:
      - uses: actions/checkout@v4
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: |
            Review this PR for bugs, security issues, and consistency
            with project conventions. Be concise and actionable.
          claude_args: "--max-turns 5 --model claude-sonnet-4-6"
```

**Cost:** ~$30-60/month across repos. **Risk:** Zero (read-only).

#### Phase 2: Auto-Fix for Lint/Type Errors (Medium Risk)

```yaml
name: Auto-Fix Lint
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]

jobs:
  auto-fix:
    if: |
      github.event.workflow_run.conclusion == 'failure' &&
      github.event.workflow_run.head_branch != 'main' &&
      !contains(github.event.workflow_run.head_commit.message, '[auto-fix]')
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_branch }}
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: |
            CI failed. Check the logs. ONLY fix lint, type, and formatting errors.
            Do NOT fix test logic or refactor code.
            Commit with message prefix "[auto-fix]".
            If you cannot fix the issue in 3 attempts, stop and comment
            "Auto-fix failed, needs human attention" on the PR.
          claude_args: "--max-turns 5 --model claude-sonnet-4-6"
```

**Cost:** ~$20-40/month additional. **Risk:** Low if scoped to lint/type only.

#### Phase 3: Auto-Merge for Trivial PRs (Higher Risk, Requires Branch Protection)

Prerequisites:
- Branch protection on `main`: require 1 review, require CI pass, require CODEOWNERS
- Merge queue enabled
- Separate bot account for approval (cannot be same as commit author)

Only auto-merge PRs where:
- All files changed are in an allowlist (docs, config, generated files)
- Diff < 50 lines
- All CI checks pass
- Claude review found no issues

**This phase requires significant trust calibration and should only be adopted after Phase 1 and 2 have run for 4-8 weeks with monitoring.**

### Architecture Decision: Which Tool to Use

| Scenario | Recommended Tool |
|----------|-----------------|
| PR review on your own repos | `anthropics/claude-code-action` (you already use Claude, consistent ecosystem) |
| PR review on client/enterprise repos | CodeRabbit or Qodo (mature, multi-platform, compliance features) |
| Auto-fix in CI | `anthropics/claude-code-action` (only tool with full agentic capability in CI) |
| Security scanning | GitHub Copilot Autofix (free on public repos, CodeQL-backed) in addition to Claude review |
| Issue-to-PR automation | GitHub Copilot Coding Agent OR Claude Code Action (both capable) |

### Key Risks to Monitor

1. **Infinite loop** -- the #1 operational risk. Implement all circuit breakers from Section 3.
2. **Cost runaway** -- set hard limits in both GitHub and Anthropic consoles.
3. **Prompt injection** -- malicious PR descriptions. Mitigate by restricting auto-fix to your own branches, not external contributor PRs.
4. **Review fatigue** -- if Claude posts too many low-value comments, developers ignore ALL comments. Tune prompts aggressively for signal-to-noise.
5. **False confidence** -- LLM approval is not human approval. Never let it substitute for human judgment on logic changes.
