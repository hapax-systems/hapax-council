# Reactive CI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM-driven CI to hapax-council: automated PR review, auto-fix for lint/typecheck/format failures, and a gated path to auto-merge. Reduces manual CI loop time for the solo operator.

**Spec:** `docs/plans/2026-03-12-reactive-ci-design.md`

**Current CI:** `.github/workflows/ci.yml` — 5 jobs (lint, typecheck, test, web-build, vscode-build), all required on main.

---

## File Structure

```
.github/
  workflows/
    ci.yml                  # Existing — no changes
    claude-review.yml       # New — PR review on open/sync
    auto-fix.yml            # New — fix lint/type/format on CI failure
  CODEOWNERS                # New — protected path ownership
```

---

## Chunk 1: Repository Configuration

### Task 1: Add ANTHROPIC_API_KEY Secret

- [ ] **Step 1:** Navigate to the hapax-council repository Settings > Secrets and variables > Actions.
- [ ] **Step 2:** Add a new repository secret named `ANTHROPIC_API_KEY` with the Anthropic API key value.
- [ ] **Step 3:** Verify with:
  ```bash
  gh secret list --repo hapax/hapax-council
  ```
  Confirm `ANTHROPIC_API_KEY` appears in the list.

### Task 2: Enable Auto-Merge

- [ ] **Step 1:** Enable auto-merge on the repository:
  ```bash
  gh api repos/hapax/hapax-council \
    -X PATCH \
    -f allow_auto_merge=true
  ```
- [ ] **Step 2:** Verify:
  ```bash
  gh api repos/hapax/hapax-council --jq '.allow_auto_merge'
  # Expected: true
  ```

### Task 3: Verify Branch Protection

- [ ] **Step 1:** Check current branch protection rules:
  ```bash
  gh api repos/hapax/hapax-council/branches/main/protection
  ```
- [ ] **Step 2:** Confirm all 5 status checks are required: `lint`, `typecheck`, `test`, `web-build`, `vscode-build`.
- [ ] **Step 3:** If branch protection needs updating (e.g., to add merge queue support):
  ```bash
  gh api repos/hapax/hapax-council/branches/main/protection \
    -X PUT \
    -H "Accept: application/vnd.github+json" \
    --input - <<'JSON'
  {
    "required_status_checks": {
      "strict": true,
      "contexts": ["lint", "typecheck", "test", "web-build", "vscode-build"]
    },
    "enforce_admins": false,
    "required_pull_request_reviews": null,
    "restrictions": null
  }
  JSON
  ```

---

## Chunk 2: CODEOWNERS File

### Task 4: Create CODEOWNERS

**File:** Create `.github/CODEOWNERS`

- [ ] **Step 1:** Create the file with the following content:

```
# Protected paths — always require human review.
# These paths are excluded from auto-merge regardless of diff size or CI status.

# Oversight systems
agents/health_monitor.py     @hapax
shared/alert_state.py        @hapax
shared/axiom_enforcement.py  @hapax
shared/config.py             @hapax

# Governance
axioms/                      @hapax

# Hooks and systemd
hooks/                       @hapax
systemd/                     @hapax

# Backup scripts (in distro-work, but guard the pattern here)
hapax-backup-*.sh            @hapax

# CI/CD workflows themselves
.github/                     @hapax
```

- [ ] **Step 2:** Verify the CODEOWNERS syntax is valid by pushing to a branch and checking the repo Settings > Branches page shows CODEOWNERS as active.

---

## Chunk 3: Claude Review Workflow

### Task 5: Create `.github/workflows/claude-review.yml`

**File:** Create `.github/workflows/claude-review.yml`

- [ ] **Step 1:** Create the workflow file with the following content:

```yaml
name: Claude PR Review

on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: claude-review-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    # Skip auto-fix commits to avoid review-of-a-fix loops
    if: >-
      !contains(github.event.pull_request.head.ref, '[auto-fix]') &&
      !contains(github.event.head_commit.message || '', '[auto-fix]')
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      # Pin to a specific commit SHA — update this when upgrading the action.
      # Find latest SHA at: https://github.com/anthropics/claude-code-action/commits/main
      - uses: anthropics/claude-code-action@PIN_SHA_HERE
        with:
          model: claude-sonnet-4-6
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          direct_prompt: |
            Review this pull request for:

            1. **Bugs**: Logic errors, off-by-one, missing error handling, race conditions.
            2. **Security**: Hardcoded secrets, injection vectors, unsafe deserialization.
            3. **Axiom compliance**: Violations of the 4 constitutional axioms (single_user,
               executive_function, corporate_boundary, management_governance).
               See axioms/registry.yaml for definitions.
            4. **Type safety**: Mismatched types, missing annotations on public functions.

            Rules:
            - Only post comments for HIGH or MEDIUM priority findings.
            - Do NOT post nitpick, style, or formatting comments (Ruff handles those).
            - Do NOT approve the PR. Post review comments only.
            - Be concise. One sentence per finding, with a suggested fix if non-obvious.
            - If the PR looks clean, post a single summary comment saying so.
          max_turns: 5
```

- [ ] **Step 2:** Before merging, look up the latest commit SHA for `anthropics/claude-code-action` and replace `PIN_SHA_HERE`:
  ```bash
  gh api repos/anthropics/claude-code-action/commits/main --jq '.sha'
  ```

---

## Chunk 4: Auto-Fix Workflow

### Task 6: Create `.github/workflows/auto-fix.yml`

**File:** Create `.github/workflows/auto-fix.yml`

- [ ] **Step 1:** Create the workflow file with the following content:

```yaml
name: Auto-Fix CI Failures

on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]

permissions:
  contents: write
  pull-requests: write
  actions: read

concurrency:
  group: auto-fix-${{ github.event.workflow_run.head_branch }}
  cancel-in-progress: true

jobs:
  auto-fix:
    # Only run when:
    # 1. CI failed (not success or cancelled)
    # 2. Not on main branch
    # 3. The triggering commit was NOT already an auto-fix
    if: >-
      github.event.workflow_run.conclusion == 'failure' &&
      github.event.workflow_run.head_branch != 'main' &&
      !contains(github.event.workflow_run.head_commit.message, '[auto-fix]')
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.workflow_run.head_branch }}
          fetch-depth: 20
          token: ${{ secrets.GITHUB_TOKEN }}

      # Circuit breaker: count existing [auto-fix] commits on this branch.
      # If 3 or more, stop — something needs human attention.
      - name: Check auto-fix attempt count
        id: guard
        run: |
          COUNT=$(git log --oneline --grep='\[auto-fix\]' origin/main..HEAD | wc -l)
          echo "auto_fix_count=$COUNT" >> "$GITHUB_OUTPUT"
          if [ "$COUNT" -ge 3 ]; then
            echo "::warning::Auto-fix limit reached ($COUNT attempts). Labeling for human review."
            echo "should_fix=false" >> "$GITHUB_OUTPUT"
          else
            echo "should_fix=true" >> "$GITHUB_OUTPUT"
          fi

      # If too many attempts, label the PR and stop
      - name: Label PR for human review
        if: steps.guard.outputs.should_fix == 'false'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          PR_NUMBER=$(gh pr list --head "${{ github.event.workflow_run.head_branch }}" --json number --jq '.[0].number')
          if [ -n "$PR_NUMBER" ]; then
            gh pr edit "$PR_NUMBER" --add-label "needs-human"
          fi

      # Download the CI run logs to determine failure type
      - name: Download CI logs
        if: steps.guard.outputs.should_fix == 'true'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh run view ${{ github.event.workflow_run.id }} --log-failed > /tmp/ci-failure.log 2>&1 || true

      # Determine if the failure is in scope (lint/typecheck/format only)
      - name: Check failure scope
        if: steps.guard.outputs.should_fix == 'true'
        id: scope
        run: |
          LOG="/tmp/ci-failure.log"
          FIXABLE=false

          # Check for ruff (lint/format) or pyright (typecheck) failures
          if grep -qE '(ruff check|ruff format|pyright)' "$LOG" 2>/dev/null; then
            # But NOT test failures or build failures
            if ! grep -qE '(FAILED tests/|pytest|pnpm build|pnpm lint)' "$LOG" 2>/dev/null; then
              FIXABLE=true
            fi
          fi

          echo "fixable=$FIXABLE" >> "$GITHUB_OUTPUT"
          echo "Failure fixable by auto-fix: $FIXABLE"

      # Label and stop if failure is out of scope
      - name: Label unfixable PR
        if: steps.guard.outputs.should_fix == 'true' && steps.scope.outputs.fixable == 'false'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          PR_NUMBER=$(gh pr list --head "${{ github.event.workflow_run.head_branch }}" --json number --jq '.[0].number')
          if [ -n "$PR_NUMBER" ]; then
            gh pr edit "$PR_NUMBER" --add-label "needs-human"
          fi

      - uses: astral-sh/setup-uv@v5
        if: steps.guard.outputs.should_fix == 'true' && steps.scope.outputs.fixable == 'true'

      - name: Install dependencies
        if: steps.guard.outputs.should_fix == 'true' && steps.scope.outputs.fixable == 'true'
        run: uv sync --extra ci

      # Pin to a specific commit SHA — same as claude-review.yml.
      - name: Run Claude Code auto-fix
        if: steps.guard.outputs.should_fix == 'true' && steps.scope.outputs.fixable == 'true'
        uses: anthropics/claude-code-action@PIN_SHA_HERE
        with:
          model: claude-sonnet-4-6
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          direct_prompt: |
            The CI pipeline failed on this branch. Fix ONLY lint, typecheck, and format errors.

            Steps:
            1. Run `uv run ruff check .` and fix any lint errors with `uv run ruff check --fix .`
            2. Run `uv run ruff format .` to fix formatting
            3. Run `uv run pyright` and fix any type errors
            4. Do NOT change test files, test logic, or behavior
            5. Do NOT change any files in: axioms/, hooks/, systemd/, shared/config.py,
               shared/axiom_enforcement.py, shared/alert_state.py, agents/health_monitor.py
            6. Make minimal changes — fix only what is broken

            After fixing, verify all three pass:
            - `uv run ruff check .`
            - `uv run ruff format --check .`
            - `uv run pyright`
          max_turns: 5
          allowed_tools: "Bash,Read,Edit,Write"

      # Commit and push the fix
      - name: Commit auto-fix
        if: steps.guard.outputs.should_fix == 'true' && steps.scope.outputs.fixable == 'true'
        run: |
          git config user.name "claude-code[bot]"
          git config user.email "claude-code[bot]@users.noreply.github.com"
          if git diff --quiet && git diff --cached --quiet; then
            echo "No changes to commit — Claude could not fix the issue."
            PR_NUMBER=$(gh pr list --head "${{ github.event.workflow_run.head_branch }}" --json number --jq '.[0].number')
            if [ -n "$PR_NUMBER" ]; then
              gh pr edit "$PR_NUMBER" --add-label "needs-human"
            fi
          else
            git add -A
            git commit -m "[auto-fix] resolve lint/typecheck/format errors

            Automated fix by Claude Code. See CI logs for details.

            Co-Authored-By: Claude Sonnet <noreply@anthropic.com>"
            git push
          fi
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2:** Replace `PIN_SHA_HERE` with the same SHA used in `claude-review.yml`.

**Important notes on the auto-fix workflow:**
- The `workflow_run` trigger receives the _completed_ event from the CI workflow. It does NOT have access to the PR context directly — it uses the branch name to find the associated PR.
- The `GITHUB_TOKEN` used by `actions/checkout` must have write access to the branch. For PRs from forks, this will not work (by design — the security constraint requires the branch to be owned by a repo collaborator).
- The `git add -A` is acceptable here because the Claude Code action only modifies lint/type/format issues, and the `.gitignore` excludes build artifacts. The prompt explicitly forbids modifying protected paths.

---

## Chunk 5: Testing Strategy

### Task 7: Validate Claude Review Workflow

- [ ] **Step 1:** Create a test branch:
  ```bash
  git checkout -b test/reactive-ci-review
  ```

- [ ] **Step 2:** Add an intentional lint error to a non-protected file (e.g., add an unused import to `agents/scout.py`):
  ```python
  import os  # unused — should trigger ruff F401
  ```

- [ ] **Step 3:** Commit and push, open a PR:
  ```bash
  git add agents/scout.py
  git commit -m "test: intentional lint error for CI validation"
  git push -u origin test/reactive-ci-review
  gh pr create --title "test: validate reactive CI" --body "Testing claude-review and auto-fix workflows. Will close after validation."
  ```

- [ ] **Step 4:** Verify the `Claude PR Review` workflow triggers on the PR. Check:
  - It posts a review comment (should flag the unused import or note it is a lint issue)
  - It does NOT approve the PR
  - It completes within the 10-minute timeout
  - Cost is within expected range (~$0.15-0.25 visible in Anthropic dashboard)

- [ ] **Step 5:** Verify the `CI` workflow fails (ruff check should catch the unused import).

### Task 8: Validate Auto-Fix Workflow

- [ ] **Step 1:** After CI fails on the test PR (from Task 7), verify the `Auto-Fix CI Failures` workflow triggers.
- [ ] **Step 2:** Check that:
  - The guard steps pass (not an `[auto-fix]` commit, count < 3, failure is lint-scoped)
  - Claude Code runs and removes the unused import
  - A commit with `[auto-fix]` prefix is pushed to the branch
  - CI re-runs and passes
- [ ] **Step 3:** Verify the auto-fix commit message follows the expected format.
- [ ] **Step 4:** Verify that if you manually add another lint error and the auto-fix runs again, the attempt counter increments correctly.

### Task 9: Validate Circuit Breakers

- [ ] **Step 1:** To test the attempt counter circuit breaker, create a file that Claude cannot fix (e.g., a genuine type error that requires architectural understanding). Push 3 `[auto-fix]`-tagged commits manually:
  ```bash
  git commit --allow-empty -m "[auto-fix] simulated attempt 1"
  git commit --allow-empty -m "[auto-fix] simulated attempt 2"
  git commit --allow-empty -m "[auto-fix] simulated attempt 3"
  git push
  ```
- [ ] **Step 2:** Trigger a CI failure. Verify the auto-fix workflow runs but stops at the guard step and labels the PR `needs-human`.

### Task 10: Clean Up Test PR

- [ ] **Step 1:** Close the test PR without merging:
  ```bash
  gh pr close test/reactive-ci-review --delete-branch
  ```

---

## Chunk 6: Rollout Plan

### Week 1: Review-Only (Read-Only, No Commits)

- [ ] **Step 1:** Deploy only `claude-review.yml`. Do NOT deploy `auto-fix.yml` yet.
- [ ] **Step 2:** Monitor every PR for the first week:
  - Are review comments actionable or noisy?
  - Does the review complete within timeout?
  - What is the cost per review?
- [ ] **Step 3:** Tune the review prompt if needed. Common adjustments:
  - If too many LOW-priority comments leak through, add stricter filtering language
  - If reviews miss obvious issues, add specific patterns to watch for
  - If reviews are too slow, reduce `max_turns` to 3
- [ ] **Step 4:** Track metrics in a simple log (can be a markdown file or spreadsheet):
  | PR | Review posted? | Actionable comments | False positives | Cost | Duration |
  |----|---------------|--------------------|--------------------|------|----------|

### Week 2: Auto-Fix for Lint/Format Only

- [ ] **Step 1:** Deploy `auto-fix.yml` but modify the scope check to ONLY match ruff failures (not pyright):
  ```bash
  # In the scope check step, change the grep to:
  if grep -qE '(ruff check|ruff format)' "$LOG" 2>/dev/null; then
  ```
- [ ] **Step 2:** Also modify the Claude prompt to only run ruff commands (remove pyright steps).
- [ ] **Step 3:** Monitor for one week:
  - Does auto-fix resolve lint/format issues?
  - Are any fixes incorrect or harmful?
  - Does the circuit breaker work correctly?
  - Track: success rate, cost, human override rate
- [ ] **Step 4:** Track metrics:
  | PR | CI failed? | Auto-fix triggered? | Fixed? | Attempts | Human override? | Cost |
  |----|-----------|--------------------|---------|-----------|--------------------|------|

### Week 3: Auto-Fix for Typecheck

- [ ] **Step 1:** Expand the scope check to include pyright failures:
  ```bash
  if grep -qE '(ruff check|ruff format|pyright)' "$LOG" 2>/dev/null; then
  ```
- [ ] **Step 2:** Restore the full Claude prompt (including pyright steps).
- [ ] **Step 3:** Monitor closely — typecheck fixes are more complex than lint fixes. Watch for:
  - Fixes that change runtime behavior (adding `# type: ignore` is fine; changing logic is not)
  - Fixes to protected paths (should be blocked by prompt, but verify)
  - Cost increases (pyright fixes tend to use more turns)
- [ ] **Step 4:** If typecheck fixes are unreliable (>30% human override rate), roll back to lint-only and tune the prompt.

### Week 4: Evaluate and Decide on Auto-Merge

- [ ] **Step 1:** Compile metrics from weeks 1-3:
  - Auto-fix success rate (target: >80%)
  - Review signal-to-noise ratio (target: >70% actionable)
  - Average time-to-green improvement
  - Human override rate (target: <15%)
  - Total monthly cost (target: <$50)
- [ ] **Step 2:** If metrics meet targets, implement auto-merge:
  - Add a new job to `auto-fix.yml` (or a separate `auto-merge.yml`) that runs after all checks pass
  - Gate on: diff < 50 lines, no protected paths, no HIGH findings from review, not a draft, not from a fork
  - Use `gh pr merge --auto --squash` to enable merge queue
- [ ] **Step 3:** If metrics do NOT meet targets, document what needs improvement and plan a second iteration. Do not enable auto-merge until the foundation is solid.
- [ ] **Step 4:** Write a retrospective document at `docs/plans/2026-04-XX-reactive-ci-retrospective.md` covering what worked, what did not, and next steps for Layer 2 (Proactive SDLC).

---

## Security Checklist

- [ ] `ANTHROPIC_API_KEY` stored as repository secret (never in workflow YAML or repo files)
- [ ] `claude-code-action` pinned to commit SHA (not `@v1` or `@main`)
- [ ] Workflow permissions are minimal: `contents: read` for review, `contents: write` only for auto-fix
- [ ] Auto-fix prompt is hardcoded in YAML (not derived from PR title, description, or comments)
- [ ] Auto-fix only runs on branches owned by repo collaborators (workflow_run does not trigger on fork PRs)
- [ ] No `admin`, `security_events`, or `actions: write` permissions granted
- [ ] Protected paths are guarded in both CODEOWNERS and the auto-fix prompt
- [ ] All Claude output is visible in GitHub Actions logs

---

## Cost Controls

- [ ] `max_turns: 5` on both workflows
- [ ] `timeout-minutes: 10` on both jobs
- [ ] Concurrency groups prevent parallel runs on the same PR/branch
- [ ] Model is `claude-sonnet-4-6` (not Opus) for cost efficiency
- [ ] Circuit breaker stops auto-fix after 3 attempts per branch
- [ ] Set Anthropic API usage alerts at $50/month and hard limit at $100/month via the Anthropic dashboard
