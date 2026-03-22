# M1: SDLC Workflow Visibility

**Date:** 2026-03-12
**Scope:** hapax-constitution (extend to council/officium once validated)
**Goal:** Make sdlc-implement and auto-fix workflows observable — know when they run, what they change, whether they succeed, and at what cost.

## Current Workflow Analysis

### sdlc-implement.yml

**Trigger:** `repository_dispatch` (type: `sdlc-plan`) or `pull_request_review` (changes_requested on agent/ branches).

**What it does:**
1. Resolves issue number from dispatch payload or branch name
2. Fetches issue title/body/labels via `gh`
3. Creates or checks out `agent/issue-N` branch
4. Runs Claude Code action (Sonnet, 10 max-turns, Bash/Read/Edit/Write/Glob/Grep)
5. Commits changes with `[bot]` identity
6. Creates or locates existing PR

**What is already captured:**
- Issue context (title, labels, body) — used as prompt input, not persisted as metadata
- No-change case: comments on issue + adds `needs-human` label
- PR body has a verification checklist (YAML lint, tests, scoped changes)

**What is NOT captured:**
- No job summary (GitHub Actions `$GITHUB_STEP_SUMMARY`)
- No timing data (wall-clock duration of Claude Code step)
- No token/cost tracking from the Claude Code action
- No artifact upload (no trace export, no logs)
- No notification on completion (success or failure)
- No structured record of what files were changed or diff size
- No link back to the triggering triage/dispatch event

### auto-fix.yml

**Trigger:** `workflow_run` on CI workflow completion (failure only, non-main branches, no `[auto-fix]` in commit message).

**What it does:**
1. Guard: counts prior `[auto-fix]` commits, caps at 3 attempts
2. Downloads failed CI logs
3. Scope check: only proceeds if yamllint/ruff errors detected
4. Runs Claude Code action (Sonnet, 3 max-turns, Bash/Read/Edit/Write)
5. Commits fix with `[auto-fix]` prefix
6. Labels PR `needs-human` on: max attempts reached, unfixable scope, or no changes produced

**What is already captured:**
- Attempt count (git log grep) — crude but functional
- Scope classification (fixable vs unfixable)
- Failure escalation via `needs-human` label

**What is NOT captured:**
- No job summary
- No timing data
- No artifact upload of the failed CI log or the fix attempt
- No structured audit record
- No notification

### sdlc-triage.yml (reference — better instrumented)

Triage is the best-instrumented workflow. It already has:
- `LANGFUSE_EXPORT_FILE` for trace capture
- `actions/upload-artifact@v4` for trace JSONL
- Structured step outputs (type, complexity, reject reason)
- Error handler that links to workflow run
- Issue comments with structured results

**The implement and auto-fix workflows should be brought to parity with triage.**

## Module Assessments

### audit.py — Usable as-is

**Verdict: Use directly, no rework needed.**

The `log_audit()` function already accepts all relevant fields:
- `action` — "implement" or "auto-fix"
- `actor` — "claude-code[bot]"
- `check_name` — issue number or CI check name
- `fix_applied` — summary of changes
- `classification` — issue type from triage
- `circuit_breaker` — state dict from CircuitBreaker
- `outcome` — "success", "no-changes", "error"
- `git_head` — commit SHA after push
- `duration_ms` — wall-clock time
- `pr_number` — created/updated PR number
- `metadata` — freeform dict for token counts, model, etc.

The JSONL format at `profiles/audit.jsonl` is append-only with rotation support. It writes to the repo working directory, which means in CI it goes into the checked-out tree. For CI, we should write to `/tmp/` and upload as artifact, same pattern as triage traces.

### circuit_breaker.py — Good interface, integrate into auto-fix

**Verdict: Interface fits, but auto-fix doesn't use it yet.**

The auto-fix workflow currently has a hand-rolled attempt counter (grep git log for `[auto-fix]`). The `CircuitBreaker` class offers:
- `can_attempt(check_name)` — replaces the git log grep
- `record_attempt(check_name, success=bool)` — tracks outcome
- `is_tripped(check_name)` — clean check for "should we stop"
- `status()` — monitoring-friendly dict of all states
- Window-based reset (24h default) — better than the current "ever on this branch" approach

**Integration challenge:** CircuitBreaker persists to `profiles/circuit-breaker.json` in the repo. In CI, this file doesn't persist between runs. Options:
1. **Keep the git-log approach** for auto-fix (it naturally persists across runs)
2. **Use CircuitBreaker in-memory only** — instantiate, feed it the git-log count, use as a decision wrapper
3. **Persist state as a workflow artifact** — download previous run's state file

Recommendation: Option 2. Use CircuitBreaker as a structured decision layer on top of the existing git-log count. Add a thin shell wrapper or Python script that reads the count, feeds it to CircuitBreaker, and emits the decision + state dict for audit logging.

### trace_export.py — Already designed for CI

The `TraceContext` and `TraceSpan` are built exactly for this use case. Set `LANGFUSE_EXPORT_FILE=/tmp/langfuse-traces.jsonl`, wrap operations, upload as artifact. Triage already does this. Implement and auto-fix should follow the same pattern.

### log.py (sdlc event log) — Should be called from workflows

`log_sdlc_event()` records stage, issue/PR number, result, duration, model. Neither implement nor auto-fix currently call it. Adding calls would make the `profiles/sdlc-events.jsonl` complete across all pipeline stages.

## Planned Workflow Annotations

### sdlc-implement.yml changes

#### 1. Job summary (`$GITHUB_STEP_SUMMARY`)

Add after the "Commit and push" step:

```yaml
- name: Write job summary
  if: always()
  run: |
    ISSUE=${{ steps.issue.outputs.number }}
    BRANCH="agent/issue-${ISSUE}"
    FILES_CHANGED=$(git diff --name-only origin/main..HEAD | wc -l)
    INSERTIONS=$(git diff --stat origin/main..HEAD | tail -1 | grep -oP '\d+ insertion' | grep -oP '\d+' || echo 0)
    DELETIONS=$(git diff --stat origin/main..HEAD | tail -1 | grep -oP '\d+ deletion' | grep -oP '\d+' || echo 0)

    cat >> "$GITHUB_STEP_SUMMARY" <<EOF
    ## Implementation Summary

    | Field | Value |
    |-------|-------|
    | Issue | #${ISSUE} |
    | Branch | \`${BRANCH}\` |
    | Files changed | ${FILES_CHANGED} |
    | Insertions | +${INSERTIONS} |
    | Deletions | -${DELETIONS} |
    | Outcome | ${{ job.status }} |
    | Duration | $(( $(date +%s) - ${{ steps.start.outputs.time }} ))s |
    EOF
```

#### 2. Timing capture

Add a start-time step immediately after checkout:

```yaml
- name: Record start time
  id: start
  run: echo "time=$(date +%s)" >> "$GITHUB_OUTPUT"
```

#### 3. Trace export

Add `LANGFUSE_EXPORT_FILE` to the Claude Code step env (if the action supports env passthrough — otherwise capture via a wrapper step). Upload as artifact:

```yaml
- name: Upload traces
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: langfuse-traces-implement-${{ steps.issue.outputs.number }}
    path: /tmp/langfuse-traces.jsonl
    if-no-files-found: ignore
```

#### 4. Audit log entry

Add a step that calls `log_audit()` via Python, writing to `/tmp/audit.jsonl`, then upload as artifact. Alternatively, inline it as a JSON append in shell.

#### 5. Diff summary as artifact

```yaml
- name: Save diff summary
  if: always()
  run: |
    git diff --stat origin/main..HEAD > /tmp/diff-summary.txt 2>/dev/null || true
    git diff origin/main..HEAD > /tmp/full-diff.patch 2>/dev/null || true

- name: Upload diff artifacts
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: implement-diff-${{ steps.issue.outputs.number }}
    path: |
      /tmp/diff-summary.txt
      /tmp/full-diff.patch
    if-no-files-found: ignore
```

### auto-fix.yml changes

#### 1. Job summary

```yaml
- name: Write job summary
  if: always()
  run: |
    cat >> "$GITHUB_STEP_SUMMARY" <<EOF
    ## Auto-Fix Summary

    | Field | Value |
    |-------|-------|
    | Branch | ${{ github.event.workflow_run.head_branch }} |
    | Triggering run | ${{ github.event.workflow_run.id }} |
    | Attempt | ${{ steps.guard.outputs.auto_fix_count }} / 3 |
    | Fixable | ${{ steps.scope.outputs.fixable }} |
    | Outcome | ${{ job.status }} |
    EOF
```

#### 2. Upload CI failure log as artifact

The log is already downloaded to `/tmp/ci-failure.log`. Just upload it:

```yaml
- name: Upload CI failure log
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: ci-failure-log-${{ github.event.workflow_run.head_branch }}
    path: /tmp/ci-failure.log
    if-no-files-found: ignore
```

#### 3. Structured guard output

Enhance the guard step to emit a JSON status for downstream consumption:

```yaml
- name: Emit guard status
  if: always()
  run: |
    echo '{"attempts": ${{ steps.guard.outputs.auto_fix_count }}, "max": 3, "should_fix": ${{ steps.guard.outputs.should_fix }}, "fixable": "${{ steps.scope.outputs.fixable || 'skipped' }}"}' | jq . > /tmp/autofix-status.json
```

## Notification Design

### Primary: ntfy push notification

ntfy is lightweight, self-hostable, and already a good fit for the local workstation. Send a push on workflow completion.

**Add to both workflows as a final step:**

```yaml
- name: Notify completion
  if: always()
  env:
    NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
  run: |
    STATUS="${{ job.status }}"
    if [ "$STATUS" = "success" ]; then
      ICON="white_check_mark"
      PRIORITY="default"
    else
      ICON="x"
      PRIORITY="high"
    fi

    curl -s \
      -H "Title: SDLC ${{ github.workflow }} ${STATUS}" \
      -H "Priority: ${PRIORITY}" \
      -H "Tags: ${ICON},robot" \
      -H "Click: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}" \
      -d "Issue #${{ steps.issue.outputs.number || 'N/A' }} — ${STATUS}" \
      "https://ntfy.sh/${NTFY_TOPIC}" || true
```

**Setup required:**
- Create a private ntfy topic (or use self-hosted ntfy)
- Add `NTFY_TOPIC` as a repository secret
- Install ntfy client on workstation or use phone app

### Secondary: GitHub issue comment (already partially done)

The implement workflow already comments on no-change. Extend to always comment with a structured summary on completion:

```yaml
- name: Comment on issue
  if: always() && steps.issue.outputs.number != ''
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    STATUS="${{ job.status }}"
    DURATION=$(( $(date +%s) - ${{ steps.start.outputs.time }} ))
    gh issue comment ${{ steps.issue.outputs.number }} --body "## Implementation ${STATUS}

    - **Duration:** ${DURATION}s
    - **Workflow run:** [${{ github.run_id }}](${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }})
    - **Branch:** \`agent/issue-${{ steps.issue.outputs.number }}\`"
```

### Not recommended: Slack/Discord webhooks

Unnecessary complexity for a single-operator system. ntfy + issue comments covers both push (phone/desktop) and pull (GitHub timeline) channels.

## Token and Cost Tracking

### Challenge

The `anthropics/claude-code-action@beta` does not currently expose token usage or cost as step outputs. The action runs Claude Code as a subprocess and the usage data stays internal.

### Approach: Extract from Claude Code action outputs

1. **Check action outputs:** The claude-code-action may expose outputs in future versions. Monitor the action's README/changelog.

2. **Parse from logs (fragile):** Claude Code prints token usage in its output. Could grep the step log, but this couples to output format.

3. **LANGFUSE_EXPORT_FILE (preferred):** If the action respects this env var, trace spans will include model/cost data in the exported JSONL. This is the cleanest path — same mechanism triage uses.

4. **Estimate from turns:** As a fallback, estimate cost from model + max-turns:
   - Sonnet input: ~$3/MTok, output: ~$15/MTok
   - 10 turns at ~2K tokens each = ~20K tokens = ~$0.06-0.30 per run
   - Track actual values once LANGFUSE_EXPORT_FILE works

### Implementation

Add to both workflows:

```yaml
env:
  LANGFUSE_EXPORT_FILE: /tmp/langfuse-traces.jsonl
```

Then extract cost from the trace file in the summary step:

```yaml
- name: Extract cost from traces
  if: always()
  run: |
    COST=0
    if [ -f /tmp/langfuse-traces.jsonl ]; then
      COST=$(jq -s '[.[].cost_usd // 0] | add' /tmp/langfuse-traces.jsonl 2>/dev/null || echo 0)
    fi
    echo "cost_usd=$COST" >> "$GITHUB_OUTPUT"
```

## Implementation Order

1. **Add start-time capture** to both workflows (trivial, no risk)
2. **Add job summaries** to both workflows (write-only, no risk)
3. **Add artifact uploads** (traces, logs, diffs) to both workflows
4. **Add ntfy notification** step + `NTFY_TOPIC` secret
5. **Add issue completion comment** to implement workflow
6. **Add LANGFUSE_EXPORT_FILE** env var and cost extraction
7. **Integrate circuit_breaker.py** into auto-fix as structured decision wrapper

## Verification Checklist

- [ ] `sdlc-implement.yml` produces a job summary visible in Actions UI
- [ ] `sdlc-implement.yml` uploads trace artifact (`langfuse-traces-implement-N`)
- [ ] `sdlc-implement.yml` uploads diff artifact (`implement-diff-N`)
- [ ] `sdlc-implement.yml` comments on issue with duration and run link
- [ ] `sdlc-implement.yml` sends ntfy notification on completion
- [ ] `auto-fix.yml` produces a job summary with attempt count and fixability
- [ ] `auto-fix.yml` uploads CI failure log as artifact
- [ ] `auto-fix.yml` sends ntfy notification on completion
- [ ] Cost data appears in traces when `LANGFUSE_EXPORT_FILE` is respected by the action
- [ ] Both workflows still pass concurrency guards (no regressions)
- [ ] `needs-human` label escalation still works in all failure paths
- [ ] Dry-run test: trigger implement on a test issue, verify all artifacts/summaries appear

## Files to Modify

| File | Changes |
|------|---------|
| `.github/workflows/sdlc-implement.yml` | Start time, summary, artifacts, notification, issue comment |
| `.github/workflows/auto-fix.yml` | Summary, artifact upload, notification |
| Repository secrets | Add `NTFY_TOPIC` |

## Files Referenced (read-only, no changes needed)

| File | Role |
|------|------|
| `sdlc/audit.py` | Audit logging — usable as-is for recording outcomes |
| `sdlc/circuit_breaker.py` | Circuit breaker — good interface, use as decision wrapper in auto-fix |
| `sdlc/log.py` | SDLC event log — call from workflows for pipeline-wide event stream |
| `sdlc/trace_export.py` | Trace export — already designed for CI, proven in triage |
| `sdlc/github.py` | GitHub CLI wrapper — no changes needed |
| `.github/workflows/sdlc-triage.yml` | Reference implementation for good CI instrumentation |
