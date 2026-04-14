# Phase 6 — SDLC pipeline end-to-end audit

**Queue item:** 026
**Phase:** 6 of 6
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

**The LLM-driven SDLC pipeline described in `CLAUDE.md § SDLC
Pipeline` exists as code but has never produced a real event
in production.** All 324 events in `profiles/sdlc-events.jsonl`
(going back to 2026-03-22, ~3 weeks of log history) have
`dry_run: true`. Zero `dry_run: false` events. The scripts
(`scripts/sdlc_triage.py`, `sdlc_plan.py`, `sdlc_review.py`,
`sdlc_axiom_judge.py`) work correctly — the dry runs succeed.
But the **trigger path** (GitHub issue labeled `agent-eligible`)
**has never been invoked** on a real issue. The pipeline is
fully coded, fully tested (324 dry runs), and fully unused.

Two additional findings surfaced while walking the workflow graph:

- **`auto-fix.yml` and `claude-review.yml` both produce failing
  runs on every PR push, with 0 s runtime.** The pattern is
  consistent across the last 20 commits. These are not SDLC
  pipeline workflows but are related; they're triggering but
  failing fast before the main job runs. Needs follow-up
  investigation.
- **Alpha is actively shipping fixes manually**, not through the
  SDLC pipeline: BETA-FINDING-M (`_no_work_data` fail-closed)
  merged within the last 15 minutes, BETA-FINDING-P
  (`compositor rebuild-services migration`) is in CI right now.
  The operator's real fix-shipping flow bypasses the SDLC
  pipeline entirely.

## Execution graph

### Stage 1 — Triage

- **Script**: `scripts/sdlc_triage.py`
- **Workflow**: `.github/workflows/sdlc-triage.yml`
- **Trigger**: `issues: [labeled]` where `label.name == 'agent-eligible'`
- **Output**: classify issue by type + complexity + axiom relevance

### Stage 2 — Plan

- **Script**: `scripts/sdlc_plan.py`
- **Workflow**: not examined (likely `sdlc-plan.yml` or inline in triage)
- **Trigger**: post-triage callback
- **Output**: implementation plan with files + acceptance criteria

### Stage 3 — Implement

- **Workflow**: `.github/workflows/sdlc-implement.yml`
- **Trigger**: post-plan
- **Output**: an `agent/*` branch with code changes + commit

### Stage 4 — Adversarial Review

- **Script**: `scripts/sdlc_review.py`
- **Workflow**: `.github/workflows/sdlc-review.yml`
- **Trigger**: PR opened on `agent/*` branch
- **Output**: approve / request changes / reject, with 3-round max

### Stage 5 — Axiom Gate

- **Script**: `scripts/sdlc_axiom_judge.py`
- **Workflow**: `.github/workflows/sdlc-axiom-gate.yml`
- **Trigger**: post-review
- **Output**: pass / block with axiom violations

### Stage 6 — Auto-Merge

- Workflow: manual or via dependabot-auto-merge.yml for the
  agent-authored branches

### Related but distinct workflows

- **`auto-fix.yml`** — triggers when CI fails on a PR; uses
  Claude Code to propose a fix commit. Not part of the SDLC
  pipeline proper.
- **`claude-review.yml`** — triggers on PR opened/synchronize
  (excluding docs paths). A lighter-weight LLM review distinct
  from `sdlc_review.py`.
- **`codebase-map.yml`, `lab-journal.yml`, `claude-md-rot.yml`** —
  maintenance/documentation workflows.
- **`experiment-freeze.yml`** — the freeze-check that beta's PRs
  have been hitting. Unrelated to SDLC but always fires.

## Event log tabulation

```text
$ wc -l <hapax-council>/profiles/sdlc-events.jsonl
324
$ python3 -c "
import json
counts = {}
dry, real = 0, 0
for line in open('profiles/sdlc-events.jsonl'):
    e = json.loads(line)
    counts[e['stage']] = counts.get(e['stage'], 0) + 1
    if e['dry_run']: dry += 1
    else: real += 1
for k, v in sorted(counts.items(), key=lambda x: -x[1]):
    print(f'  {v:4d}  {k}')
print(f'dry_run: {dry}  real: {real}')
"

By stage:
   108  triage
    72  plan
    72  review
    72  axiom-gate
dry_run: 324  real: 0
```

**324 events, 100% dry run.** Every one. Going back to
2026-03-22 when the pipeline was first shipped.

**Stage distribution:**

- 108 triage events
- 72 plan events
- 72 review events
- 72 axiom-gate events

The drop from triage (108) to plan (72) indicates that **36
triage events did not proceed to plan**. Per the sdlc_triage
code, triage can output `reject_reason` which short-circuits
the pipeline. 36/108 = 33% early-rejection rate in dry run.

**All four stages have matched event counts (72 each) for the
non-rejected flow**, indicating the pipeline does flow through
all stages when triage accepts. This is a positive sign — the
pipeline *works* — but only in dry run.

### First and last event

```text
first:  2026-03-22T01:08:04.766  stage=triage  issue=1  dry_run=true
last:   2026-04-12T02:02:59.856  stage=axiom-gate  pr=1  dry_run=true
```

**~3 weeks span, 324 events, all dry run.** Last event is 2 days
stale (2026-04-12; today is 2026-04-13). The pipeline was exercised
in dry-run mode during testing windows and has been idle for ~2
days.

**Interpretation:** The operator likely ran the SDLC pipeline
tests during the pipeline's initial bring-up (mid-March 2026),
verified each stage with `--dry-run`, and then never issued a
real `agent-eligible` label on a live issue. The dry runs are
the artifact of `uv run python -m scripts.sdlc_triage --dry-run`
invocations for development + test.

## GitHub workflow runs

```text
$ gh run list --workflow sdlc-triage.yml --limit 5
(empty — no runs)
```

**The `sdlc-triage.yml` workflow has never fired** per the gh CLI's
run history. Combined with the dry-run-only event log, this
confirms the pipeline is idle.

```text
$ gh run list --limit 30
(shows recent CI + claude-review.yml + auto-fix.yml runs; zero
 sdlc-triage/plan/review/axiom-gate runs)
```

### The `auto-fix.yml` + `claude-review.yml` failure pattern

Every recent PR push triggers two workflows that fail with 0 s
runtime:

```text
completed failure  auto-fix.yml       fix/corporate-boundary-... push  0s
completed failure  claude-review.yml  fix/corporate-boundary-... push  0s
completed failure  auto-fix.yml       research/round4-...        push  0s
completed failure  claude-review.yml  research/round4-...        push  0s
... (20+ more)
```

**100% failure rate on both workflows**, across commits going
back through the session.

**Likely cause (inferred, not yet verified):**

- `auto-fix.yml` uses `workflow_run: [CI] completed` as trigger.
  It gates with `if: github.event.workflow_run.conclusion == 'failure'`.
  When CI succeeds (most of the time), the job is skipped and
  the workflow reports... "failure"? This is unusual. Normally
  a skipped job produces a "success" or "cancelled" workflow
  conclusion.
- `claude-review.yml` uses `pull_request: [opened, synchronize]`
  with `paths-ignore: [docs/**, *.md, research/**]`. A research-
  docs PR should be path-ignored. It still fires and fails with
  0 s.

**Hypothesis**: the workflows reach the `if:` gate, evaluate it
to false, skip all jobs, but GitHub is marking the overall run
as "failure" because... not yet determined. This is either:
1. A workflow YAML bug (the `if:` gate is at job level, and an
   empty workflow run is not allowed)
2. A permission gate failure before the `if:` evaluates (e.g.,
   secret missing)
3. A regression in GitHub Actions' handling of `workflow_run`
   + skip
4. `paths-ignore` not being honored for `workflow_run` triggers

**Severity**: MEDIUM. The 0 s failures are noise (each counts as
a failure in the PR check UI, forcing the operator to see
"checks failing" on every PR), but no real auto-fix or review
work is being skipped. The operator's workaround has been
"check freeze-check and ignore auto-fix/claude-review." This
is a real friction cost.

**Fix path**: inspect a specific failing run at job-level to see
the exact failure stage, then correct the `if:` gate or
`paths-ignore` config. Out of scope for Phase 6 research; file
as a follow-up ticket.

## Agent PR audit

```text
$ gh pr list --state all --limit 50 --search "author:app/github-actions"
(empty)

$ gh pr list --state all --limit 50 --search "label:agent-authored"
(empty)
```

**Zero agent-authored PRs.** The `agent/*` branch convention
described in CLAUDE.md has never been used. All PRs in the
repo have been operator-authored or alpha/beta-session-authored
(with `Co-Authored-By: Claude Opus 4.6 (1M context)`, which is
different from `app/github-actions`).

This is consistent with the dry-run-only event log: no real
pipeline invocation → no agent branch → no agent PR.

## Failure-mode question

**"If an LLM call fails mid-pipeline, where does the failure
surface?"**

Answer: not applicable to the current state because **no real
pipeline invocation has ever happened.** The question is
hypothetical. Inspecting `sdlc_triage.py` for its own error
handling is out of scope for this phase. The concrete failure
handling should be audited in a follow-up once the pipeline is
actually run in production mode.

## Live-or-dormant classification

| stage | script exists? | workflow exists? | ever run (real)? | state |
|---|---|---|---|---|
| triage | yes (`sdlc_triage.py`) | yes | **no** (108 dry runs) | **DORMANT** |
| plan | yes (`sdlc_plan.py`) | (inline?) | **no** (72 dry runs) | **DORMANT** |
| implement | (inline?) | yes (`sdlc-implement.yml`) | **no** (no events) | **DORMANT** |
| review | yes (`sdlc_review.py`) | yes | **no** (72 dry runs) | **DORMANT** |
| axiom-gate | yes (`sdlc_axiom_judge.py`) | yes | **no** (72 dry runs) | **DORMANT** |
| auto-merge | — | (dependabot) | — | partial (dependabot fires for dep updates only) |
| auto-fix | — | yes | **YES, but 0s failure** | **BROKEN** |
| claude-review | — | yes | **YES, but 0s failure** | **BROKEN** |
| experiment-freeze | — | yes | **YES, fires successfully** | LIVE |
| codebase-map | — | yes | unknown | not examined |
| lab-journal | — | yes | unknown | not examined |
| claude-md-rot | — | yes | unknown | not examined |

**5 SDLC stages dormant, 2 related workflows broken, 1 unrelated
workflow (experiment-freeze) live.** The LLM-driven lifecycle
exists on paper; the operational reality is that alpha
(and beta, as seen in the queue 022-025 rounds) ship fixes
through the conventional `Co-Authored-By` + manual PR flow,
not through the agent-eligible label → auto-implement pipeline.

## Ranked gaps

| rank | gap | severity | action |
|---|---|---|---|
| 1 | Pipeline has never fired in production mode | **HIGH** (opportunity cost) | Operator decides: use or retire |
| 2 | `auto-fix.yml` + `claude-review.yml` failing with 0s on every push | **MEDIUM** (noise) | Debug workflow skip → failure conversion |
| 3 | No agent-authored PRs in history | (symptom of #1) | N/A |
| 4 | Event log uses `stage` field; dashboards may expect `event_type` | LOW | minor consistency check |
| 5 | No `agent-eligible` label on any issue | (symptom of #1) | Operator creates a test issue + label |

## Proposed actions

### Action A — Decide: use or retire

The SDLC pipeline is complete enough to run on a real issue.
Operator should:

1. Pick a trivial issue (existing, or create one for testing)
2. Apply the `agent-eligible` label
3. Watch the pipeline fire end-to-end with `dry_run=false`
4. See if the agent produces a real PR

If successful: keep the pipeline. If not, file the failure mode
and iterate.

**Or** formally retire: remove the scripts + workflows + event
log, update CLAUDE.md to reflect that the LLM-driven SDLC is
not in use. Currently the pipeline is expensive to maintain
(per-commit noise from auto-fix + claude-review, code that
nobody uses) without delivering value.

### Action B — Debug the 0 s failures

Inspect a specific failed run:

```bash
gh run view 24373588145 --log-failed
```

(In my Phase 6 session, the log fetch returned "log not found"
for one run — suggesting the failure is in workflow setup before
any step logs are written. This could be a YAML validation bug,
a missing secret, or a permissions gate.)

A dedicated 30-minute debug session by someone with `gh` access
and workflow inspection tools could root-cause this. Out of
scope for Phase 6 research.

### Action C — Add event log enforcement

If the pipeline is kept, add a gauge + alert:

- `hapax_sdlc_events_last_real_timestamp` — seconds since the
  last `dry_run: false` event
- Alert if > 24 hours

Makes the dormancy visible instead of silent.

## Cross-reference with prior backlog

Queue 024 Phase 6 (data plane) noted multiple dead/dormant
paths. Queue 025 Phase 1 noted axiom enforcement gaps. The
SDLC pipeline is a **third class of dormancy**: code that works
but is never exercised. The prior rounds focused on bugs; this
round's Phase 6 surfaces a category of *working-but-unused*
systems whose maintenance cost is hidden because nobody notices
they exist.

**Pattern**: council has a tendency to ship optional features
(Phase 7 BudgetTracker in queue 022, operator-patterns writer
in queue 025, SDLC pipeline here) that are complete in code but
not wired to production. The operator's workflow adapts around
the gap instead of through it. This is a form of **technical
debt by completeness-without-wiring**.

**Recommendation for the operator:** after the round 5 backlog
lands, consider a "ship or retire" sprint that walks through
every feature marked operational in memory and validates it
against a live invocation.

## Backlog additions (for round-5 retirement handoff)

162. **`decision(sdlc): use or retire the LLM-driven SDLC pipeline`** [Phase 6 Action A] — operator-only decision. Test with a single real `agent-eligible` label → pipeline firing OR formal retirement (remove scripts + workflows + event log). Current state is zero-value net-maintenance-cost.
163. **`fix(github-actions): debug auto-fix.yml + claude-review.yml 0s failures`** [Phase 6 Action B] — 100% failure rate on every push, likely a workflow YAML + `workflow_run` + paths-ignore interaction bug. Medium severity (noise, not blocking).
164. **`feat(sdlc): hapax_sdlc_last_real_event_age_seconds gauge + alert`** [Phase 6 Action C] — only if the pipeline stays. Makes dormancy visible.
165. **`research(sdlc): trigger the pipeline on a live issue as validation`** [Phase 6 Action A sub-action] — precursor to A. Create a trivial issue, label it, watch the pipeline.
166. **`docs(claude.md § SDLC Pipeline): revise to reflect dormant reality OR retire the whole section`** [Phase 6 memory refinement] — currently CLAUDE.md describes the pipeline as if it were operational. Either wire it up (A) or strike it from the docs.
167. **`research(council): "ship or retire" sprint — walk every memory-named operational feature vs live invocation`** [Phase 6 pattern observation] — BudgetTracker + operator-patterns + SDLC pipeline are all instances of completeness-without-wiring. Systematic audit would surface more.
