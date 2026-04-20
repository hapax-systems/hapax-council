---
date: 2026-04-20
author: alpha (Claude Opus 4.7, 1M context, planning subagent)
audience: operator + delta dispatcher + WSJF tracker
register: scientific, neutral
status: per-phase audit deliverable for D-28 gap audit NEW-1 (programme-layer near-miss exemplar)
related:
  - docs/superpowers/plans/2026-04-20-programme-layer-plan.md
  - docs/research/2026-04-20-total-workstream-gap-audit.md
  - docs/research/2026-04-19-content-programming-layer-design.md
  - docs/superpowers/plans/2026-04-19-homage-completion-plan.md
tags: [programme-layer, d-28, audit, gap-analysis]
---

# D-28 Programme-Layer Phase Audit

## Purpose

D-28 (gap audit NEW-1) identifies the programme-layer plan as a "near-miss
exemplar": a 12-phase plan whose primitives shipped under unrelated WSJF
items (D-26 monetization plumb, D-27 egress audit) but whose middle and
upper layers (planner LLM, transition choreographer, observability,
abort evaluator, e2e acceptance) remain unstarted and invisible to the
work-state surface. This document executes the per-phase status
determination requested by the gap audit and reconciles each phase to
the canonical CC-task vault SSOT.

The plan being audited is
`docs/superpowers/plans/2026-04-20-programme-layer-plan.md` (1556 lines,
12 phases, 4 families: P, G, C, T).

## §1. Per-phase status table

| Phase | Title | Status | Evidence | Next action |
|-------|-------|--------|----------|-------------|
| 1 | `Programme` Pydantic primitive + affordance-expander properties | SHIPPED | `shared/programme.py` exists; `tests/shared/test_programme.py` + `test_programme_monetization_opt_ins.py` present; commit `f6cc0b42b feat(programme): Pydantic primitive — soft-prior envelope, no hard gates`; soft-prior-only validator pattern visible in source. | None — close phase task. |
| 2 | ProgrammePlanStore — persist + rotate plans | SHIPPED (with deviation) | `shared/programme_store.py` exists (filed under `shared/` not `agents/programme_manager/` per plan); `tests/shared/test_programme_store.py` + `test_programme_store_crash_safety.py` present; commit `1917e939e feat(programme): ProgrammePlanStore persistence + active-singleton invariant (Phase 2)`; D-24 partial follow-up `a40c63fbc` added size warning + Hypothesis property tests. | Note path deviation in close note — Phase 7's `agents/programme_manager/` package will need to import from `shared.programme_store` rather than the planned `agents.programme_manager.plan_store`. |
| 3 | Hapax-authored programme planner LLM | NOT_STARTED | `agents/programme_manager/` directory does not exist; no `planner.py`, no `prompts/programme_plan.md`, no `tests/programme_manager/`. No git history mentions a programme planner LLM call. | Dispatch as L-sized subagent (500-750 LOC + 400 tests + prompt). Operator-time-critical because Phase 7, 10 block on it. |
| 4 | Affordance pipeline — programme as soft prior scoring input | PARTIAL (governance plumb only, scoring bias missing) | `shared/affordance_pipeline.py:166-174` and `:379-392` cache the active programme via `default_store().active_programme()` at a 1s TTL; the value is consumed by the monetization gate (D-26 commit `866b66499 feat(governance): D-26 — wire active Programme into MonetizationRiskGate`) and tested in `tests/test_affordance_pipeline_d26_programme_plumb.py`. However, the plan's `_apply_programme_bias(candidates, programme)` helper — the actual soft-prior scoring multiplier — is NOT implemented; `AffordancePipeline.select` does not accept a `programme` parameter or apply `programme.bias_multiplier(name)` to candidate scores. The grounding-expansion invariant counter `hapax_programme_candidate_set_reduction_total` is not emitted. | Dispatch as M subagent. The plumb is half done (programme is read on the hot path); the missing half is the score-multiplier composition + the no-shrink invariant test + the Prometheus counter. |
| 5 | Structural director — programme-aware emission | NOT_STARTED | `agents/studio_compositor/structural_director.py` contains zero `programme` references (case-insensitive grep, 0 matches); `shared/director_intent.py` has no `programme_id` field on `StructuralIntent`; no `agents/studio_compositor/prompts/structural_director.md` programme section. | Dispatch as M. Test rig requires a mocked planner (Phase 3) but module change is independently testable. |
| 6 | CPAL speech-production — programme-owned should_surface bias (retires F5) | NOT_STARTED | `agents/hapax_daimonion/cpal/` contains zero programme references; the F5 short-circuit at `agents/run_loops_aux.py:445-449` is still present and `DEFAULT_SURFACE_THRESHOLD` is still hardcoded with no programme bias multiplier. | Dispatch as M. Blocks programme-driven listening / hothouse contrast at the speech surface. Also closes the open F5 retirement item from the homage plan. |
| 7 | Programme transition choreographer | NOT_STARTED | `agents/programme_manager/` does not exist; no `transition.py`, no `manager.py`. The ProgrammeManager loop that advances PENDING → ACTIVE → COMPLETED through planned lifecycle is the missing meso-tier daemon. | Dispatch as L. Architectural keystone — without this, the programme primitive (Phase 1) and store (Phase 2) sit dormant. |
| 8 | Reverie palette range per programme | NOT_STARTED | `agents/visual_layer_aggregator/` contains zero programme references; `substrate_writer.py` doesn't read `active_programme.constraints.reverie_saturation_target`. Homage plan A6 (substrate damping under BitchX) is shipped but is not programme-aware. | Dispatch as M. Quick win because A6 plumbing already exists; this phase reskins the target-source from per-package-default to programme-owned. |
| 9 | Observability — programme metrics + per-programme JSONL | PARTIAL (one peripheral metric only, no programme-keyed module) | D-27 commit `1fb58b0b7 feat(governance): D-27 — wire MonetizationRiskGate.assess() to egress audit` shipped a single egress-audit metric, but `shared/programme_observability.py` does NOT exist; the seven planned `hapax_programme_*` metric families are not emitted; `~/hapax-state/programmes/<show_id>/<programme-id>.jsonl` outcome log is not written; `grafana/dashboards/programme-layer.json` is absent. The two grounding-expansion invariant metrics (`candidate_set_reduction_total`, `soft_prior_overridden_total`) — the most architecturally load-bearing observability in the plan — are unshipped. | Dispatch as M. Cannot land before Phase 4 is fully implemented (the soft-prior override counter increments in the scoring path Phase 4 owns) and Phase 7 (the JSONL log writer is on the ProgrammeManager lifecycle hooks). |
| 10 | Abort predicate evaluator + re-plan | NOT_STARTED | No `agents/programme_manager/abort_evaluator.py`; no predicate registry (`operator_left_room_for_10min`, `impingement_pressure_above_0.8_for_3min`, `consent_contract_expired`, `vinyl_side_a_finished`, `operator_voice_contradicts_programme_intent`); no 5s-veto window machinery; no re-plan path through Phase 3's planner. | Dispatch as M. Strict blocker is Phase 3 + Phase 7. |
| 11 | Integration with homage B3 — choreographer rotation_mode unlocked | NOT_STARTED | `agents/studio_compositor/homage/choreographer.py` contains zero programme references; `homage_rotation_mode_priors` from the programme envelope is not consumed by the rotation-mode selector. Homage B3 + B4 are shipped (per `docs/superpowers/plans/2026-04-19-homage-completion-plan.md`) so the integration prerequisite holds; the programme-side hook is the missing piece. | Dispatch as M after Phase 5 + 7 land. |
| 12 | End-to-end acceptance — 30-min 3-programme stream | NOT_STARTED | No `scripts/run-programme-layer-acceptance.sh`; no `docs/runbooks/programme-layer-acceptance.md`; no `tests/integration/test_programme_layer_e2e.py`. Terminal acceptance gate, blocked on all preceding phases. | Cannot dispatch until Phases 3, 5, 6, 7, 8, 9, 10, 11 complete. Hold in vault `offered` state with `priority: high` (this is the gate the programme layer becomes "live" against). |

**Tally:** 2 SHIPPED, 2 PARTIAL, 8 NOT_STARTED.

## §2. Cross-link to adjacent shipped work

The programme layer's primitives shipped not in service of the
programme-layer plan but as plumbing for adjacent governance epics —
hence the D-28 "near-miss" framing. Specifically:

**D-26 (`feat(governance): D-26 — wire active Programme into MonetizationRiskGate (Phase 5 plumb)`).** Drove the Phase 1 primitive
(`shared/programme.py`) and Phase 2 store (`shared/programme_store.py`)
to ship as a side-effect of needing a way to attach
`monetization_opt_ins` to a runtime-current Programme. The Phase 5 the
commit message references is *D-26 governance Phase 5*, NOT
programme-layer Phase 5 (structural director); naming collision is
unfortunate but real. Result: Phase 1 SHIPPED in full; Phase 2 SHIPPED
with a path deviation (`shared/programme_store.py` instead of the
planned `agents/programme_manager/plan_store.py`); Phase 4 SHIPPED only
the active-programme cache + monetization gate consumer, NOT the
soft-prior scoring multiplier the programme plan called for.

**D-27 (`feat(governance): D-27 — wire MonetizationRiskGate.assess() to egress audit`).** Wired one Programme-keyed metric (the
monetization-risk egress audit counter) into the observability stream.
This counts as a sliver of programme-layer Phase 9 — programme_id is in
the metric labels — but the seven planned `hapax_programme_*` families
and the per-programme JSONL outcome log remain unshipped. Phase 9
status is therefore PARTIAL, not SHIPPED.

**D-24 (`feat(governance): D-24 partial — programme_store size warning + Hypothesis property tests`).** Added Hypothesis property-based tests
for `programme_store.py` and a size warning when the store grows
beyond a soft cap. This hardens Phase 2 but doesn't add new surface;
already counted under Phase 2 SHIPPED.

**Demonet Phase 5/11 (`feat(demonet): Programme.monetization_opt_ins end-to-end (Phase 5)` + `feat(demonet): quiet-frame programme — zero-opt-in safety hold (Phase 11)`).** Drove the `monetization_opt_ins` field on
the Programme primitive. Confirms Phase 1's affordance-expander
property invariants survive contact with a real consumer (the
demonet egress gate); no Phase 1 follow-up needed.

**Voice-tier (`feat(voice-tier): role/stance resolver + programme band override (Phase 3a)`).** Programme has been wired into the voice-tier
band override resolver. This is *adjacent* to programme-layer Phase 6
(CPAL should_surface bias) but is not the same surface — voice-tier
band is a downstream model-routing decision; should_surface is the
upstream "do I speak at all" gate. Phase 6 remains NOT_STARTED.

The pattern: **adjacent governance / monetization work has
opportunistically consumed the programme primitive as plumbing,
shipping the bottom 2 layers and a sliver of the middle, while the
plan's 8 unshipped phases (which are the *programmatic* meso-tier
behaviour, not the *governance* monetization plumbing) sit invisible
because no WSJF item names them.** D-28's job is to surface them.

## §3. Recommended sequencing

The plan's §3 critical path is `1 → 2 → 3 → 7 → 10 → 12`. With Phases
1 + 2 SHIPPED and Phase 4 PARTIAL, the next-action ordering for the
remaining 10 phases (8 unstarted + 2 partial) collapses to:

1. **Finish Phase 4 first** (M, ~2h). Convert the existing programme-on-
   the-hot-path plumb into the soft-prior scoring multiplier. This
   unblocks Phase 9's invariant metrics and Phase 6's CPAL bias
   composition. The change is localised to
   `shared/affordance_pipeline.py` and additive — existing tests
   shouldn't drift.

2. **Dispatch Phases 3, 5, 8 in parallel** (L + M + M). All depend
   only on Phase 1 + 2 (Phase 5 mock-tests without 3); none touch
   each other's files. ~4h wall-clock with 3 concurrent subagents.

3. **Then Phase 7** (L, ~4h). Strictly serial — needs 1, 2, 4 done.
   This is the keystone that turns the inert primitive + store +
   pipeline plumbing into a running ProgrammeManager loop with a
   real lifecycle.

4. **Then Phases 6, 9 in parallel** (M + M). Phase 6 needs 1 + 4;
   Phase 9 needs 1, 2, 4, 7 — both are reachable now. ~2-3h
   wall-clock.

5. **Then Phase 10, 11 in parallel** (M + M). Both need 7; Phase 10
   needs 3 also. ~2-3h wall-clock.

6. **Finally Phase 12** (M, ~2h script + test + runbook). Operator-
   walked terminal gate.

Total compressed wall-clock: ~14-16h with 3-4 concurrent subagents
per batch where possible. Strictly serial floor (single-subagent
sequencing): ~22-26h.

## §4. Total LOC estimate for not-started + partial work

Per the plan's per-phase Size column (S = ≤200 LOC, M = 200-500, L = 500-1500), counting module + test LOC inclusive:

| Phase | Size | Module LOC | Test LOC | Other (prompt/dashboard/runbook) | Subtotal |
|-------|------|-----------:|---------:|---------------------------------:|---------:|
| 3 | L | 500-750 | 400 | 150 (prompt) | 1050-1300 |
| 4 (remaining) | M | 150-300 | 300 | — | 450-600 |
| 5 | M | 300-500 | 300 | — | 600-800 |
| 6 | M | 200-400 | 250 | — | 450-650 |
| 7 | L | 500-800 | 500 | — | 1000-1300 |
| 8 | M | 150-300 | 200 | — | 350-500 |
| 9 (remaining) | M | 400-600 | 300 | 200 (Grafana JSON) | 900-1100 |
| 10 | M | 350-550 | 300 | — | 650-850 |
| 11 | M | 200-350 | 250 | — | 450-600 |
| 12 | M | 200 | 300 | 100 (runbook) | 600 |
| **Total** | | **2950-4750** | **3100** | **450** | **6500-8300** |

Operator total: **~6.5k-8.3k LOC** spanning ~22-26h serial subagent
work or ~14-16h with parallel dispatch. The plan's §3 wall-clock
estimate (10-12h) assumed all phases fresh; with Phase 1 + 2 already
shipped and Phase 4 half-done, the remaining floor is slightly lower.

## §5. Vault SSOT reconciliation

Per D-30, the canonical work-state surface is
`~/Documents/Personal/20-projects/hapax-cc-tasks/`. As part of this
audit, twelve cc-task notes have been filed:

- `closed/programme-layer-phase-1-pydantic-primitive.md` (status: done)
- `closed/programme-layer-phase-2-plan-store.md` (status: done)
- `active/programme-layer-phase-3-planner-llm.md` (status: offered)
- `active/programme-layer-phase-4-soft-prior-scoring.md` (status: claimed — adjacent partial work touched it via D-26/D-27)
- `active/programme-layer-phase-5-structural-director.md` (status: offered)
- `active/programme-layer-phase-6-cpal-threshold.md` (status: offered)
- `active/programme-layer-phase-7-transition-choreographer.md` (status: offered)
- `active/programme-layer-phase-8-reverie-palette.md` (status: offered)
- `active/programme-layer-phase-9-observability.md` (status: claimed — adjacent partial work touched it via D-27)
- `active/programme-layer-phase-10-abort-evaluator.md` (status: offered)
- `active/programme-layer-phase-11-choreographer-rotation.md` (status: offered)
- `active/programme-layer-phase-12-e2e-acceptance.md` (status: offered)

Notes carry `parent_plan: docs/superpowers/plans/2026-04-20-programme-layer-plan.md` and
`tags: [programme-layer, d-28]` so a Dataview query
`type: cc-task AND contains(tags, "programme-layer")` surfaces the
entire epic to the operator dashboard. WSJF estimates derive from the
plan's per-phase Size column (M ≈ 5, L ≈ 8) plus criticality lift
(Phase 12 e2e is the highest at 13; the keystone Phase 7 is 13 also;
Phase 4 + 9 PARTIALs are 8 — finish-the-half-done is high-value).

## §6. Conclusion — D-28 NEW-1 closure

D-28's gap-audit characterisation is verified: 2 of 12 phases are
SHIPPED but only as a side-effect of D-26 / D-27 monetization
governance; 2 are PARTIAL (the soft-prior scoring path in Phase 4 and
the observability surface in Phase 9 are sliver-shipped via the same
adjacent epics); 8 are unstarted and were invisible to the work-state
surface until this audit. The vault notes filed alongside this
document make the unshipped 10 (8 + 2) phases visible as concrete,
WSJF-rankable, claimable work items per the D-30 SSOT. Recommended
next action: dispatch Phase 4 finish (smallest, highest-leverage,
unblocks 6 + 9), then fan out 3/5/8 in parallel.

The "near-miss exemplar" framing holds because the plan is dispatchable
as written — its phases, dependencies, success criteria, and grounding
invariants are all specified. The blocker is queue visibility, not
spec quality. Reconciling to the vault SSOT closes that blocker.
