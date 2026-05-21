---
title: "CCTV self-test remediation: 5 workitem disposition"
date: 2026-05-21
author: epsilon
status: disposition_complete
cc_task: 202605181934-disconfirm-cctv-r-p1-remediate-workitems
authority_case: CASE-202605181934-DISCONF
---

# CCTV Self-Test Remediation: 5 Workitem Disposition

All 5 unexecuted work items from the original REQ-20260516-cctv-self-test-remediation
now have a tracked disposition. None remain in ambiguous state.

## Item 1: Tool impact ablation experiment

| Field | Value |
|-------|-------|
| CC-task | `cctv-tool-ablation` (active) |
| Status | `offered`, assigned to alpha |
| WSJF | 8.0 |
| Disposition | **Tracked — awaiting claim execution** |
| Dependencies | `cctv-dead-code-activation` (done) |
| Acceptance | Full/restricted/none tool access on same claim set; measure score delta |
| Target | Deferred to next CCTV evaluation cycle (post-evidence-card infrastructure) |

## Item 2: CCTV methodology meta-publication

| Field | Value |
|-------|-------|
| CC-task | `publication-cctv-methodology` (active) |
| Status | `offered`, assigned to alpha |
| WSJF | 7.0 |
| Disposition | **Tracked — awaiting claim execution** |
| Dependencies | Publication pipeline readiness |
| Acceptance | Methodology paper draft at docs/publication-drafts/ |
| Target | Deferred to post-HN-launch publication window |

## Item 3: Segment prep Pass 3 rejection rate measurement

| Field | Value |
|-------|-------|
| CC-task | None (never decomposed) |
| Disposition | **Formally deferred — low value without tool ablation baseline** |
| Rationale | Pass 3 rejection rate is meaningful only relative to the tool-ablation findings from Item 1. Measuring it in isolation produces a number without a comparison baseline. |
| Remediation | Will be created as a cc-task blocked on `cctv-tool-ablation` when that task completes |
| Owner | Unassigned (will follow `cctv-tool-ablation` owner) |

## Item 4: Goodhart drift watchdog (score distribution stability)

| Field | Value |
|-------|-------|
| CC-task | None (never decomposed) |
| Disposition | **Formally deferred — requires sustained CCTV operation data** |
| Rationale | Drift detection needs a baseline distribution from ≥30 days of CCTV operation. Current CCTV runs are episodic (per-disconfirmation), not continuous. Building the watchdog before the baseline exists produces an untestable module. |
| Remediation | Will be created as a cc-task after the CCTV benchmark execution task (`cctv-benchmark-execution`) establishes a sustained baseline |
| Owner | Unassigned |

## Item 5: Inter-rater reliability study (30 excerpts, kappa >= 0.6)

| Field | Value |
|-------|-------|
| CC-task | None (never decomposed) |
| Disposition | **Formally deferred — requires second rater** |
| Rationale | Inter-rater reliability requires a second independent rater cold-scoring 30 excerpts. Single-operator system has no second rater available. The study is architecturally blocked, not just deprioritized. |
| Remediation | Defer until publication preparation phase when external validation is required. Create cc-task at that time with explicit rater recruitment plan. |
| Owner | Operator (requires human judgment about rater selection) |

## Summary

| # | Item | Disposition | Tracked? |
|---|------|-------------|----------|
| 1 | Tool ablation | Active cc-task, awaiting execution | Yes |
| 2 | Methodology publication | Active cc-task, awaiting execution | Yes |
| 3 | Pass 3 rejection rate | Deferred — depends on Item 1 | Yes (deferral documented) |
| 4 | Goodhart drift watchdog | Deferred — needs baseline data | Yes (deferral documented) |
| 5 | Inter-rater reliability | Deferred — needs second rater | Yes (deferral documented) |

No work item remains untracked or ambiguous.
