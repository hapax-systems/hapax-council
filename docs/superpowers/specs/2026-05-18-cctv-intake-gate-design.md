# CCTV Intake Gate — Request Hardener, Research Loop, Task Decomposition

> **Authority Case:** CASE-SDLC-COMPLETION-GATE-20260518
> **WSJF:** 14.0 (highest in queue)
> **Status:** Design complete, implementation authorized

## Problem

Requests enter the system and sit indefinitely with no quality evaluation,
no WSJF scoring, and no task decomposition. The CCTV disconfirmation sweep
found 62% of requests are "weakened" — gaps trace to insufficient intake.

## Architecture

### Three new CCTV capabilities

**1. INTAKE mode** — evaluates request specificity. Produces accept/reject/harden verdict.

**2. RESEARCH_ASSESSMENT mode** — for research-backed requests, maps implementable vs theoretical.

**3. Request Decomposer** — produces full task graph atomically from accepted requests.

### Decision flow

```
Request arrives (status: captured)
        |
        v
  CCTV INTAKE mode (3-model panel: opus + balanced + gemini-3-pro)
        |
   +----+------+----------+---------+
   |           |          |         |
 READY      HARDEN    RESEARCH   REJECT
   |           |          |         |
   v           v          v         v
 Decomposer  Return    CCTV       Close with
 creates     with      RESEARCH   rationale
 ALL tasks   specific  _ASSESSMENT
 atomically  feedback     |
                     +----+----+
                     |         |
                   READY    HARDEN
                     |         |
                     v         v
                  Decomposer  Return with
                  creates     "research says
                  tasks for   X is speculative,
                  READY items narrow to Y"
```

### Fail-closed on all paths
- All council members fail → NEEDS_HARDENING (not advance)
- Convergence HUNG → NEEDS_HARDENING (disagreement = insufficient spec)
- CCTV unreachable → request cannot advance (absent gate = blocker)
- Decomposer LLM fails → request stays captured
- Any task write fails → all rolled back (atomic write)

## Scoring Dimensions (8 axes, weighted composite)

| # | Dimension | Weight | Scale | Threshold |
|---|-----------|--------|-------|-----------|
| 1 | Outcome Concreteness | 0.20 | 1-5 | >= 3 |
| 2 | Scope Boundedness | 0.15 | 1-5 | >= 3 |
| 3 | Decomposability | 0.15 | 1-5 | >= 3 |
| 4 | Artifact Specificity | 0.10 | 1-5 | >= 3 |
| 5 | Verification Seed | 0.15 | 1-5 | >= 3 |
| 6 | Forcing Function | 0.10 | bool | present |
| 7 | Authority Surface Clarity | 0.05 | bool | true |
| 8 | Single-Request Singularity | 0.10 | 1-5 | >= 3 |

Composite >= 3.0 AND no dimension below 2. Rejection feedback is
prescriptive per dimension (tells requester exactly what to add).

## Research Implementability Map

For requests referencing research docs, each deliverable classified:

| Class | Score Pattern | Task Treatment |
|-------|-------------|----------------|
| READY | All axes >= 4 | Becomes build cc-task |
| NEEDS_DESIGN | Any axis 3 | Becomes design task (output: spec) |
| THEORETICAL | Any axis <= 2 | Stays as research reference, NOT a task |
| BLOCKED | Axis <= 2 + missing dep | Blocked task with depends_on |

4 implementability axes: code_path_clarity, dependency_readiness,
interface_definition, scope_boundedness.

Only READY and NEEDS_DESIGN items become tasks. THEORETICAL items are
explicitly excluded from fulfillment checks. This prevents the pattern
where 6-deliverable research produces 6 tasks but only 2 are buildable.

## Task Decomposition Engine

### Invariant

After intake processes a request, either:
- The request is REJECTED with specific reasons, OR
- EVERY task needed to fulfill it EXISTS with linkage, ordering, and AC

No stubs. No piecemeal. No "decompose later."

### Two-pass architecture

**Pass 1 — Decomposition Agent:** LLM reads request body + cc-task schema,
produces `RequestDecomposition` (list of `TaskSpec` objects).

**Pass 2 — Deterministic Validator:** Checks DAG validity, no duplicate IDs,
depends_on resolution, parent_request linkage, AC presence, WSJF plausibility.

### Atomic write

All tasks written via tmpfile+rename. Crash during write = zero partial files.
Any rename failure = full rollback. Request status only updates after all
tasks successfully land.

### WSJF distribution

When request provides per-phase WSJF: use directly.
When absent: phase-decay at 0.85x per phase depth. Critical-path tasks
(most downstream dependents) get +0.5 boost.

### Output model

```python
class TaskSpec(BaseModel):
    task_id: str
    title: str
    kind: Literal["build", "operator_action", "research_packet", "verification"]
    priority: str
    wsjf: float
    depends_on: list[str]
    phase_index: int
    parent_request: str
    authority_case: str
    quality_floor: str
    mutation_surface: str
    effort_class: str
    acceptance_criteria: list[str]  # concrete, testable

class RequestDecomposition(BaseModel):
    request_id: str
    tasks: list[TaskSpec]
    # DAG + completeness validators run automatically
```

## Implementation Plan

| # | Deliverable | Files | Effort |
|---|------------|-------|--------|
| 1 | IntakeHardeningRubric + IntakeVerdict | deliberative_council/modes/intake.py, rubrics.py | 4h |
| 2 | ResearchImplementabilityRubric + Map | deliberative_council/modes/implementability.py | 4h |
| 3 | Request Decomposer core | agents/request_decomposer/core.py | 6h |
| 4 | Atomic write + validator | agents/request_decomposer/writer.py | 3h |
| 5 | Wire into request-intake-consumer | scripts/request-intake-consumer | 3h |
| 6 | End-to-end test | tests/agents/test_request_decomposer.py | 2h |

Total: ~22h across 6 deliverables. All ship on one branch.
