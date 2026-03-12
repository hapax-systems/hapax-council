# Proactive SDLC (Layer 2) — Implementation Plan

**Date:** 2026-03-12
**Layer:** 2 of 3 (LLM-Driven SDLC)
**Status:** Plan
**Design doc:** `docs/plans/2026-03-12-proactive-sdlc-design.md`
**Depends on:** Layer 1 (Reactive CI) stable for 4+ weeks

---

## 1. GitHub Actions Workflows

Four new workflow files under `.github/workflows/`. All use `anthropics/claude-code-action` pinned to commit SHA (not `@v1`) and share the `ANTHROPIC_API_KEY` repo secret.

### 1.1 Issue Triage — `.github/workflows/sdlc-triage.yml`

**Trigger:** `issues` event, `labeled` action, label `agent-eligible`.

**Permissions:** `issues: write`, `contents: read`.

**Concurrency:** `sdlc-triage-${{ github.event.issue.number }}` (cancel-in-progress: true).

**Steps:**

1. Checkout repo.
2. Set up uv, install deps (`uv sync --extra ci`).
3. Run triage script: `uv run python -m scripts.sdlc_triage --issue-number ${{ github.event.issue.number }}`.
4. Script outputs structured JSON: `{ "type": "bug|feature|chore", "complexity": "S|M|L", "axiom_relevance": [...], "reject_reason": null|"string" }`.
5. If complexity is `L` or `reject_reason` is non-null: add label `needs-human`, post comment explaining why, remove `agent-eligible`. Stop.
6. If S/M: add labels `triage:bug|feature|chore`, `complexity:S|M`, `sdlc:triaged`. Post triage summary as comment.
7. Dispatch `repository_dispatch` event type `sdlc-plan` with issue number payload. This triggers the implementation workflow.

**Timeout:** 5 minutes.

**Circuit breaker:** If the triage script errors, add label `needs-human` and post the error as a comment.

### 1.2 Implementation — `.github/workflows/sdlc-implement.yml`

**Trigger:** `repository_dispatch` event type `sdlc-plan`.

**Permissions:** `contents: write`, `pull-requests: write`, `issues: write`.

**Concurrency:** `sdlc-implement-${{ github.event.client_payload.issue_number }}` (cancel-in-progress: false — do not cancel mid-implementation).

**Steps:**

1. Checkout repo, set up uv.
2. **Planning phase:** Run `uv run python -m scripts.sdlc_plan --issue-number <N>`.
   - Reads the issue body + triage comment via `gh issue view`.
   - Queries Qdrant for relevant codebase context (files, functions, tests).
   - Produces a plan: files to modify, acceptance criteria, test strategy.
   - Posts plan as an issue comment.
   - Outputs plan JSON to `$GITHUB_OUTPUT`.
3. **Implementation phase:** Run `claude-code-action` with:
   - The plan as the prompt (not the raw issue — prevents prompt injection from issue body).
   - `--max-turns 15` (Opus, more complex work).
   - `--model claude-opus-4-6`.
   - System prompt includes CLAUDE.md + axiom summary.
4. Create branch `agent/issue-<N>-<slug>`, commit, push, open PR.
   - PR body includes: issue link, plan summary, Langfuse trace link, `agent-authored` label.
   - PR title: `[agent] <issue title>`.
5. Add label `sdlc:implementing` to issue, then `sdlc:in-review` when PR is opened.

**Timeout:** 15 minutes.

**Circuit breaker:** If implementation fails, post error as issue comment, add `needs-human`, remove `sdlc:implementing`.

### 1.3 Review — `.github/workflows/sdlc-review.yml`

**Trigger:** `pull_request` event, `opened` or `synchronize`, on branches matching `agent/*`.

**Permissions:** `contents: read`, `pull-requests: write`.

**Concurrency:** `sdlc-review-${{ github.event.pull_request.number }}` (cancel-in-progress: true — re-review on new pushes).

**Steps:**

1. Checkout repo, set up uv.
2. **Guard:** Only run on PRs with label `agent-authored`. Skip otherwise.
3. **Adversarial review:** Run `uv run python -m scripts.sdlc_review --pr-number <N>`.
   - Receives: diff (`gh pr diff`), fresh codebase context from Qdrant, axiom definitions.
   - Does NOT receive: author's chain-of-thought, planning rationale, or implementation reasoning.
   - Model: Claude Sonnet (different model than the Opus author — diversity by design).
   - Focus areas: correctness, security, axiom compliance, test coverage, regression risk.
   - Outputs structured review with per-file comments.
4. Post review comments on PR via GitHub API.
5. If no blocking issues: post `APPROVED` review status.
6. If blocking issues found: post `CHANGES_REQUESTED` with specific feedback.
   - Track review round count in PR labels: `review-round:1`, `review-round:2`.
   - If round >= 3: add `needs-human`, post escalation comment.

**Timeout:** 10 minutes.

**Fix cycle:** When `CHANGES_REQUESTED`, the `sdlc-implement.yml` workflow has a secondary trigger path:
- Trigger: `pull_request_review` event, `submitted` action, review state `changes_requested`.
- Guard: PR has `agent-authored` label and review round < 3.
- Runs a **Fixer Agent** (separate invocation from Author, per design doc isolation rules):
  - Receives: review comments + current code. Does NOT see original author reasoning.
  - Model: Claude Sonnet (not Opus — cost control on fix rounds).
  - `--max-turns 8`.
  - Pushes fix commit to the same branch, which re-triggers review.

### 1.4 Axiom Gate — `.github/workflows/sdlc-axiom-gate.yml`

**Trigger:** `pull_request_review` event, `submitted` action, review state `approved`, on branches matching `agent/*`.

**Permissions:** `contents: read`, `pull-requests: write`, `issues: write`.

**Concurrency:** `sdlc-axiom-gate-${{ github.event.pull_request.number }}`.

**Steps:**

1. Checkout repo, set up uv.
2. **Structural checks** (deterministic, no LLM):
   - All 5 CI jobs passed (check via `gh pr checks`).
   - No changes to protected paths (reuse protected paths list from Layer 1 design).
   - Commit message format compliance (conventional commits regex).
   - Diff size within bounds (< 500 lines for S, < 1500 for M).
3. **Semantic checks** (LLM judge):
   - Run `uv run python -m scripts.sdlc_axiom_judge --pr-number <N>`.
   - Model: Claude Haiku (fast, cheap, focused evaluation per design doc).
   - Input: full diff + 4 constitutional axiom definitions + derived implications.
   - Output: per-axiom compliance verdict with reasoning.
   - T0 violation: hard block. Post blocking review comment explaining the violation.
   - T1+ violation: post advisory comment, add label `axiom:precedent-review` for human.
4. If all gates pass: add label `sdlc:ready-for-human`, post summary comment with:
   - Triage classification.
   - Plan link.
   - Review summary (rounds, findings resolved).
   - Axiom compliance verdict.
   - Langfuse trace link.
   - Cost summary.

**Timeout:** 5 minutes.

---

## 2. New Code Components

All new code lives under `scripts/` (CLI entry points for CI) and `shared/` (reusable logic). Agents in `agents/` are not modified — the SDLC pipeline is a separate concern.

### 2.1 Triage Agent — `scripts/sdlc_triage.py`

**Entry point:** `python -m scripts.sdlc_triage --issue-number N`

**Logic:**

```
1. Fetch issue via `gh issue view N --json title,body,labels`.
2. Build prompt:
   - System: axiom summary + triage instructions.
   - User: issue title + body.
3. Call LiteLLM (Sonnet) with structured output:
   - type: Literal["bug", "feature", "chore"]
   - complexity: Literal["S", "M", "L"]
   - axiom_relevance: list[str]  # which axioms are relevant
   - reject_reason: str | None
   - file_hints: list[str]  # suspected relevant files
4. Output JSON to stdout for workflow consumption.
```

**Prompt design:** The triage prompt must include:
- The 4 axiom summaries (single-user, executive function, corporate boundary, management governance).
- Complexity heuristics: S = single file, M = 2-5 files, L = architectural or cross-cutting.
- Rejection criteria: ambiguous requirements, L complexity, axiom-sensitive changes, changes to protected paths.

**Depends on:** `shared.config.get_model()`, `shared.axiom_registry.load_axioms()`.

**New shared utility:** `shared/sdlc_github.py` — thin wrapper around `gh` CLI for issue/PR operations (fetch issue, post comment, add/remove labels, fetch diff). Used by all 4 scripts. Wraps `subprocess.run(["gh", ...])` with error handling and JSON parsing.

### 2.2 Planning Agent — `scripts/sdlc_plan.py`

**Entry point:** `python -m scripts.sdlc_plan --issue-number N`

**Logic:**

```
1. Fetch issue + triage comment via gh CLI.
2. Query Qdrant for relevant context:
   - Embed issue title + body via shared.config.embed().
   - Search "documents" collection for relevant files.
   - Search "axiom-precedents" for related decisions.
3. Build prompt:
   - System: CLAUDE.md content + axiom constraints + operator constraints.
   - User: issue + triage + retrieved context.
4. Call LiteLLM (Sonnet) with structured output:
   - files_to_modify: list[{path, reason, change_type}]
   - acceptance_criteria: list[str]
   - test_strategy: str
   - implementation_notes: str
   - estimated_diff_lines: int
5. Post plan as issue comment.
6. Output plan JSON for downstream consumption.
```

**Depends on:** `shared.config.get_model()`, `shared.config.get_qdrant()`, `shared.config.embed()`, `shared.axiom_registry`, `shared/sdlc_github.py`.

### 2.3 Review Agent — `scripts/sdlc_review.py`

**Entry point:** `python -m scripts.sdlc_review --pr-number N`

**Logic:**

```
1. Fetch PR diff via `gh pr diff N`.
2. Fetch list of changed files.
3. For each changed file, fetch full current content (for context).
4. Query Qdrant for related codebase context (NOT the author's planning context).
5. Load axiom definitions and implications.
6. Build prompt:
   - System: review-focused instructions + axiom definitions.
   - User: diff + codebase context.
   - CRITICAL: No author reasoning, no planning docs, no implementation notes.
7. Call LiteLLM (Sonnet, different system prompt than author) with structured output:
   - verdict: Literal["approve", "request_changes"]
   - findings: list[{file, line, severity, description, suggestion}]
   - axiom_concerns: list[{axiom_id, concern, severity}]
   - summary: str
8. Post review via GitHub API (inline comments on specific lines where possible).
9. Output verdict for workflow consumption.
```

**Prompt design:** The reviewer system prompt emphasizes:
- You are an independent reviewer. You have not seen the implementation plan.
- Focus on: correctness bugs, security issues, axiom compliance, test coverage gaps.
- Do NOT comment on style (Ruff handles that) or formatting.
- Be specific: reference line numbers, suggest concrete fixes.
- If you find no issues, say so. Do not manufacture findings.

### 2.4 Axiom Compliance Judge — `scripts/sdlc_axiom_judge.py`

**Entry point:** `python -m scripts.sdlc_axiom_judge --pr-number N`

**Logic:**

```
1. Fetch PR diff via `gh pr diff N`.
2. Load all constitutional axioms and T0/T1 implications via shared.axiom_registry.
3. Run structural checks (deterministic):
   - Protected path detection (regex against changed files list).
   - Diff size bounds.
   - Commit message format.
4. Run semantic check:
   - Build prompt with diff + each axiom definition + its implications.
   - Call LiteLLM (Haiku) with structured output per axiom:
     - axiom_id: str
     - compliant: bool
     - tier_violated: str | None  # "T0", "T1", "T2"
     - reasoning: str
5. Aggregate: any T0 violation = block. T1+ = advisory.
6. Also call shared.axiom_enforcement.check_full() with a situation description
   derived from the PR title + diff summary — this checks precedent store.
7. Output combined structural + semantic + precedent verdict.
```

**Integration with existing code:** This is the key integration point. The judge:
- Uses `shared.axiom_enforcement.check_full()` for deterministic precedent lookup.
- Uses `shared.axiom_registry.load_axioms()` and `load_implications()` for axiom text.
- Adds an LLM semantic layer on top (Haiku judge) that the existing enforcement module does not have.

### 2.5 Orchestration State Machine

**Decision: Extend nothing. Use GitHub labels + workflow dispatch as the state machine.**

Rationale: The design doc suggests either GitHub Actions with job dependencies or LangGraph. GitHub Actions is the right choice for Layer 2 because:
- No new infrastructure (LangGraph would require a long-running process).
- State is visible in GitHub UI (labels, comments, checks).
- Transitions are auditable in workflow run logs.
- Timeouts and circuit breakers are built into GitHub Actions.

**State encoding via labels:**

| State | Label | Transition |
|-------|-------|------------|
| ISSUE_LABELED | `agent-eligible` | Issue labeled by human |
| TRIAGING | `sdlc:triaging` | Triage workflow starts |
| TRIAGED | `sdlc:triaged` + `triage:{type}` + `complexity:{size}` | Triage complete |
| PLANNING | `sdlc:planning` | Plan workflow starts |
| IMPLEMENTING | `sdlc:implementing` | Author agent starts |
| IN_REVIEW | `sdlc:in-review` + `review-round:N` | PR opened |
| FIXING | `sdlc:fixing` | Fixer agent starts |
| AXIOM_CHECKING | `sdlc:axiom-check` | Axiom gate starts |
| READY_FOR_HUMAN | `sdlc:ready-for-human` | All gates pass |
| NEEDS_HUMAN | `needs-human` | Escalation at any stage |
| MERGED | (PR merged) | Human merges |
| REJECTED | `sdlc:rejected` | Human closes PR |

**Transition enforcement:** Each workflow checks the expected label exists before proceeding. If the label is missing (e.g., someone manually removed it), the workflow exits cleanly with a warning comment.

**No new module needed.** The `shared/sdlc_github.py` utility handles label management. If orchestration complexity grows beyond what label-based state can handle, migration to LangGraph is the Layer 3 concern.

---

## 3. Integration with Existing Infrastructure

### 3.1 Langfuse Tracing from CI

**Problem:** Langfuse runs at `localhost:3000` on the operator's workstation. GitHub Actions runners cannot reach it directly.

**Options (ordered by preference):**

1. **Deferred export (recommended for initial rollout):**
   - Each script writes trace data to a local JSONL file during CI run.
   - A post-job step uploads the JSONL as a GitHub Actions artifact.
   - A separate workflow (or the operator manually) imports traces into Langfuse.
   - Pros: No network dependency. Traces are never lost.
   - Cons: Not real-time. Requires import step.

2. **Tailscale tunnel:**
   - If the operator's machine is on Tailscale (per POST-REBOOT-PLAN.md, Tailscale is planned), expose Langfuse on the tailnet.
   - GitHub Actions self-hosted runner on the same tailnet (or Tailscale GitHub Action for ephemeral access).
   - Pros: Real-time tracing. Uses existing `shared/langfuse_config.py` unchanged.
   - Cons: Depends on machine being online. Security surface.

3. **Langfuse Cloud (future):**
   - Migrate to Langfuse Cloud or expose via Cloudflare Tunnel.
   - Out of scope for initial rollout.

**Implementation for option 1:**

- New utility: `shared/langfuse_trace_export.py` — wraps OpenTelemetry's `SimpleSpanProcessor` with a `FileSpanExporter` that writes to JSONL.
- In CI, set env var `LANGFUSE_EXPORT_FILE=/tmp/langfuse-traces.jsonl`.
- `shared/langfuse_config.py` detects this env var and uses file export instead of HTTP export.
- Post-job step: `actions/upload-artifact@v4` uploads the trace file.
- Import script: `scripts/import_langfuse_traces.py` reads JSONL and POSTs to Langfuse API.

**Trace structure per SDLC run:**

```
Trace: sdlc-issue-{N}
  ├── Span: triage (model, input, output, cost)
  ├── Span: planning (model, input, output, cost, qdrant_queries)
  ├── Span: implementation (model, turns, files_modified, cost)
  ├── Span: review-round-1 (model, input, output, verdict, cost)
  ├── Span: fix-round-1 (if applicable)
  ├── Span: review-round-2 (if applicable)
  └── Span: axiom-gate (structural_result, semantic_result, precedent_result, cost)
```

### 3.2 Qdrant Context Retrieval from CI

**Problem:** Qdrant runs at `localhost:6333`. Same connectivity issue as Langfuse.

**Options:**

1. **Pre-computed context (recommended for initial rollout):**
   - The triage workflow runs on a self-hosted runner (the operator's machine) or uses Tailscale.
   - Alternatively: a nightly GitHub Action dumps a "codebase map" (file paths, docstrings, function signatures) to a JSON artifact. Planning/review agents use this static map instead of live Qdrant queries.
   - Pros: No runtime dependency on Qdrant. Reproducible.
   - Cons: Stale by up to 24h. Less precise than vector search.

2. **Self-hosted runner (recommended for Week 5+ rollout):**
   - Register the operator's machine as a GitHub Actions self-hosted runner.
   - All SDLC workflows run locally with full access to Qdrant, Langfuse, Ollama.
   - Pros: Full infrastructure access. Fastest. Cheapest (no GitHub compute).
   - Cons: Machine must be online. Security considerations (runner has repo write access).

3. **Qdrant Cloud (future):**
   - Migrate Qdrant to managed cloud. Out of scope for initial rollout.

**Recommended progression:**
- Weeks 1-4 (triage-only, planning-only): Use pre-computed codebase map. Qdrant access not critical for classification.
- Weeks 5+: Self-hosted runner. Full Qdrant access for implementation and review context.

**Codebase map generation:** New script `scripts/generate_codebase_map.py`:
- Walks `agents/`, `shared/`, `cockpit/`, `scripts/`.
- For each `.py` file: extracts module docstring, class names, function signatures (via `ast` module).
- Outputs JSON: `{ "files": [{ "path": "...", "docstring": "...", "classes": [...], "functions": [...] }] }`.
- Scheduled nightly via `.github/workflows/codebase-map.yml` and stored as release asset or in a dedicated branch.

### 3.3 Axiom Enforcement Module Integration

The existing `shared/axiom_enforcement.py` provides two paths that map directly to the axiom gate design:

| Gate tier | Enforcement path | Module function |
|-----------|-----------------|-----------------|
| Structural (T0 pattern match) | `check_fast()` | Pre-compiled `ComplianceRule` regex against diff content |
| Full (T0 + precedent) | `check_full()` | Loads YAML implications + queries precedent store |
| Semantic (LLM judge) | **New** | `scripts/sdlc_axiom_judge.py` adds LLM evaluation layer |

**Integration points:**

1. The axiom judge script calls `check_full(situation=<PR summary>)` to get deterministic compliance result.
2. It then runs the Haiku LLM judge for semantic evaluation that pattern matching cannot cover.
3. Results are merged: deterministic violations are hard blocks; LLM judge findings include reasoning.
4. If `check_full()` finds precedent violations, these are included in the PR comment for human context.

**No changes to `shared/axiom_enforcement.py` are needed.** The SDLC scripts consume its public API as-is.

---

## 4. Testing Strategy

### 4.1 Triage Agent Classification Accuracy

**Approach:** Golden-set evaluation.

1. **Build golden set:** Curate 30-50 past issues (from hapax-council and hapax-officium) with human-assigned type and complexity labels. Store in `test-data/sdlc/triage-golden-set.json`.
2. **Evaluation script:** `tests/test_sdlc_triage_eval.py`:
   - For each golden issue, run the triage prompt against a recorded LLM response (using `pytest-recording` or response fixtures).
   - Compare predicted `type` and `complexity` against ground truth.
   - Metrics: accuracy, confusion matrix, rejection false-positive rate (issues rejected that should have been accepted).
3. **Acceptance threshold:** >= 85% type accuracy, >= 75% complexity accuracy, < 10% false rejection rate.
4. **CI integration:** Run as a separate pytest mark (`@pytest.mark.eval`) excluded from normal CI. Run manually before prompt changes.

### 4.2 Adversarial Review Effectiveness

**Approach:** Seeded-bug evaluation.

1. **Build seeded-bug corpus:** Take 10-15 known-good PRs. For each, introduce a deliberate bug (off-by-one, missing null check, security issue, axiom violation). Store as patch files in `test-data/sdlc/seeded-bugs/`.
2. **Evaluation script:** `tests/test_sdlc_review_eval.py`:
   - For each seeded diff, run the review prompt.
   - Check whether the reviewer identified the seeded bug.
   - Check for false positives (findings on clean code).
3. **Metrics:** Bug detection rate (target > 80%), false positive rate (target < 20% of findings).
4. **Isolation verification:** Confirm that reviewer output changes when author reasoning is included vs. excluded (the review should be qualitatively different, proving isolation is meaningful).

### 4.3 Axiom Gate Correctness

**Approach:** Unit tests + boundary cases.

1. **Structural gate tests** (`tests/test_sdlc_axiom_gate.py`):
   - Protected path detection: test each protected path pattern matches correctly.
   - Diff size bounds: test boundary values (499, 500, 501 lines for S complexity).
   - Commit message format: test valid and invalid formats.
   - These are deterministic — standard pytest, run in CI.

2. **Semantic gate tests:**
   - Build 10-15 test diffs with known axiom implications:
     - Diff that adds multi-user auth code (violates Axiom 1 — should block).
     - Diff that removes health monitoring (violates Axiom 2 — should flag).
     - Diff that adds corporate features (violates Axiom 3 — should block).
     - Diff that is a clean refactor (should pass all axioms).
   - Store as fixtures in `test-data/sdlc/axiom-gate-cases/`.
   - Eval script checks Haiku judge verdicts against expected outcomes.

3. **Integration with existing enforcement tests:**
   - `shared/axiom_enforcement.py` already has `check_fast()` and `check_full()` as testable pure functions.
   - Add test cases in `tests/test_axiom_enforcement.py` (if not already present) for the specific situations the SDLC pipeline will generate.

### 4.4 End-to-End Pipeline Test

**Approach:** Dry-run mode.

- Add `--dry-run` flag to all 4 scripts. In dry-run mode:
  - LLM calls use recorded fixtures instead of live API.
  - GitHub operations are logged but not executed.
  - Output is written to stdout/file for inspection.
- End-to-end test: `tests/test_sdlc_pipeline_e2e.py` runs triage -> plan -> review -> axiom-gate in sequence using fixtures. Verifies state transitions and output formats.

---

## 5. Rollout Plan

Per the design doc, with specific implementation details:

### Week 1-2: Triage-Only Mode

**Goal:** Validate classification accuracy without any code generation risk.

**Implement:**
- `scripts/sdlc_triage.py`
- `shared/sdlc_github.py`
- `.github/workflows/sdlc-triage.yml`
- Golden-set test corpus + evaluation script

**Process:**
1. Operator labels 3-5 issues per week as `agent-eligible`.
2. Triage agent classifies and comments.
3. Operator reviews triage quality daily.
4. Tune prompt based on misclassifications.
5. Track metrics: accuracy, false rejection rate, latency.

**Exit criteria:** >= 85% type accuracy, >= 75% complexity accuracy over 20+ issues.

### Week 3-4: Planning Mode

**Goal:** Validate planning quality. Agent plans but does not implement.

**Implement:**
- `scripts/sdlc_plan.py`
- `scripts/generate_codebase_map.py` + nightly workflow
- Langfuse trace export (option 1: file-based)
- Planning evaluation (human review of plan quality)

**Process:**
1. Triaged S/M issues proceed to planning.
2. Agent posts implementation plan as issue comment.
3. Operator reviews plans, provides feedback via comments.
4. Track metrics: plan quality (human score 1-5), file identification accuracy, acceptance criteria completeness.

**Exit criteria:** Average plan quality score >= 3.5/5 over 15+ plans.

### Week 5-8: Full Pipeline on Chores

**Goal:** End-to-end pipeline on lowest-risk issue type.

**Implement:**
- `scripts/sdlc_review.py`
- `scripts/sdlc_axiom_judge.py`
- `.github/workflows/sdlc-implement.yml`
- `.github/workflows/sdlc-review.yml`
- `.github/workflows/sdlc-axiom-gate.yml`
- Self-hosted runner (for Qdrant/Langfuse access)
- Seeded-bug review evaluation

**Scope:** Only `chore` issues: dependency bumps, docstring improvements, test additions, config cleanup.

**Process:**
1. Triaged `chore` issues with complexity S/M proceed through full pipeline.
2. `bug` and `feature` issues stop at planning (human implements).
3. Operator reviews and merges all agent PRs (no auto-merge).
4. Track all success metrics from design doc.

**Exit criteria:** >= 70% PR acceptance rate (merged without major rework), review round average < 1.5, axiom gate first-pass rate >= 90%.

### Week 9-12: Expand to Bugs

**Goal:** Handle bug fixes autonomously.

**Changes:**
- Allow `bug` issues with complexity S/M through full pipeline.
- Tighten review prompt for bug-specific concerns (regression risk, edge cases).
- Add mutation testing gate for generated test changes.

**Exit criteria:** >= 75% PR acceptance rate across chore + bug, zero post-merge regressions attributed to agent PRs.

### Week 13+: Evaluate Features

**Goal:** Assess readiness for feature implementation.

**Decision criteria based on accumulated data:**
- PR acceptance rate stable at >= 80%.
- Technical debt metrics (ruff warnings, pyright errors) have not increased.
- Review round average < 1.5.
- Operator confidence in agent output (qualitative assessment).

**If criteria met:** Allow `feature` issues with complexity S only. Expand to M after 4 more weeks of stable metrics.

---

## 6. Dependencies on Layer 1

The following Layer 1 components must be stable before Layer 2 work begins:

### 6.1 Hard Dependencies (Must Be Operational)

| Layer 1 Component | Why Layer 2 Needs It | Stability Criteria |
|-------------------|---------------------|-------------------|
| CI workflow (`.github/workflows/ci.yml`) | Layer 2 PRs must pass the same 5-job CI gate | Running on all PRs for 4+ weeks with no false failures |
| `ANTHROPIC_API_KEY` repo secret | All SDLC agent invocations use it | Working in Layer 1 workflows |
| Branch protection rules | Agent PRs must go through the same protection as human PRs | Configured and enforced for 4+ weeks |
| Auto-fix workflow (`.github/workflows/auto-fix.yml`) | Agent-authored PRs that fail lint/type should be auto-fixed by Layer 1 before Layer 2 review | Auto-fix success rate >= 80% for lint/type errors |

### 6.2 Soft Dependencies (Should Be Operational)

| Layer 1 Component | Why | Mitigation If Absent |
|-------------------|-----|---------------------|
| Claude PR review (`.github/workflows/claude-review.yml`) | Validates that LLM review works in CI context | Layer 2 review workflow is a superset; can work without Layer 1 review |
| Auto-merge | Streamlines the final merge step | Human merges manually (always required for Layer 2 anyway) |
| CODEOWNERS | Protects sensitive paths | Layer 2 axiom gate provides equivalent protection |
| Merge queue | Prevents merge races | Not critical for low-volume agent PRs |

### 6.3 Infrastructure Dependencies

| Component | Required By | Status |
|-----------|------------|--------|
| Qdrant (localhost:6333) with populated codebase index | Planning agent, Review agent | Qdrant running; codebase index must be populated (existing `agents/ingest.py` handles this) |
| Ollama with `nomic-embed-text-v2-moe` | Embedding for Qdrant queries in CI | Running locally; need self-hosted runner or pre-computed map for CI access |
| Langfuse (localhost:3000) | Trace collection | Running locally; file-based export for CI until Tailscale or self-hosted runner |
| LiteLLM (localhost:4000) | Model routing | NOT needed in CI — scripts call Anthropic API directly via `ANTHROPIC_API_KEY`. LiteLLM is for local agent use only. CI uses the `anthropics/claude-code-action` or direct API calls. |

### 6.4 Stability Validation Checklist

Before starting Layer 2 implementation, verify:

- [ ] Layer 1 CI has run on >= 50 PRs without false failures.
- [ ] Auto-fix has successfully resolved >= 10 lint/type failures.
- [ ] Claude review has posted on >= 20 PRs with acceptable signal-to-noise.
- [ ] No Layer 1 workflow has required emergency disablement in the past 2 weeks.
- [ ] `shared/axiom_enforcement.py` API has been stable (no breaking changes) for 4+ weeks.
- [ ] Axiom YAML definitions (`axioms/`) have been stable for 2+ weeks.
- [ ] Monthly CI/review costs are within the Layer 1 budget estimate ($18-51/month).

---

## 7. File Summary

New files to create:

| File | Purpose |
|------|---------|
| `scripts/sdlc_triage.py` | Issue triage agent CLI |
| `scripts/sdlc_plan.py` | Planning agent CLI |
| `scripts/sdlc_review.py` | Adversarial review agent CLI |
| `scripts/sdlc_axiom_judge.py` | Axiom compliance judge CLI |
| `shared/sdlc_github.py` | GitHub CLI wrapper for issue/PR operations |
| `shared/langfuse_trace_export.py` | File-based trace export for CI |
| `scripts/generate_codebase_map.py` | Static codebase map for offline context |
| `scripts/import_langfuse_traces.py` | Import CI trace files into Langfuse |
| `.github/workflows/sdlc-triage.yml` | Triage workflow |
| `.github/workflows/sdlc-implement.yml` | Planning + implementation workflow |
| `.github/workflows/sdlc-review.yml` | Adversarial review workflow |
| `.github/workflows/sdlc-axiom-gate.yml` | Axiom compliance gate workflow |
| `.github/workflows/codebase-map.yml` | Nightly codebase map generation |
| `test-data/sdlc/triage-golden-set.json` | Triage evaluation corpus |
| `test-data/sdlc/seeded-bugs/` | Seeded-bug diffs for review evaluation |
| `test-data/sdlc/axiom-gate-cases/` | Axiom gate test fixtures |
| `tests/test_sdlc_triage_eval.py` | Triage accuracy evaluation |
| `tests/test_sdlc_review_eval.py` | Review effectiveness evaluation |
| `tests/test_sdlc_axiom_gate.py` | Axiom gate unit + eval tests |
| `tests/test_sdlc_pipeline_e2e.py` | End-to-end dry-run test |

No existing files are modified. The SDLC pipeline is additive.
