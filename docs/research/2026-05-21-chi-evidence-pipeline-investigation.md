# CHI 2027 Evidence Pipeline — Root Cause Investigation

**Date:** 2026-05-21
**Author:** epsilon
**Task:** 202605181934-disconfirm-perspe-p0-confirm-rootcause
**Parent request:** REQ-202605181934-disconfirm-perspective-chi-evidence-pipeline-rescue
**Source:** CCTV Disconfirmation mode adversarial analysis (2026-05-18)
**Severity:** High (P0)

## Verdict: PARTIALLY VALID — mischaracterized as pipeline failure

The CHI 2027 evidence infrastructure is genuinely unbuilt, but the probe's characterization as a "pipeline rescue" requiring "cherry-pick grafting-conditions" is incorrect. The work is unstarted planned work in its correct dependency position, not a broken pipeline.

## What the probe claimed

- "CHI 2027 evidence pipeline rescue"
- "Cherry-pick grafting-conditions"
- "Create annotation/export scripts (Sep 10 deadline)"

## What the investigation found

### The evidence pipeline is planned, not broken

Track C of the Hapax Perspective Implementation Plan (2026-05-17) defines the CHI evidence infrastructure as **Task 10 — the last task**, explicitly scheduled "AFTER all tracks." Four files are planned but unbuilt:

| Planned file | Status | Purpose |
|-------------|--------|---------|
| `scripts/chi-episode-annotate.py` | Does not exist | Episode coding tool |
| `scripts/chi-data-export.py` | Does not exist | Publication-quality figure export |
| `shared/grafting_conditions.py` | Does not exist | Grafting condition definitions |
| `tests/shared/test_grafting_conditions.py` | Does not exist | Tests for grafting conditions |

These files were never created because their dependencies (Track A: eigenform/sensing, Track B: governance/voice) are still in progress.

### No grafting conditions exist to cherry-pick

`shared/grafting_conditions.py` is a planned module that has never been written. Zero references to `grafting_conditions`, `GraftingCondition`, or any related symbol exist in the Python codebase. The probe's instruction to "cherry-pick grafting-conditions" refers to a module that does not exist.

### Dependencies are correctly ordered

The execution order from the implementation plan:

```
PARALLEL START:
  Track A: eigenform fix → persist → density spike
  Track B: CCTV fix | assertions
  Track C: langfuse retention (config only)
...
AFTER all tracks:
  Task 10: CHI evidence infrastructure (REQ-09)
```

Task 10 is intentionally last because it consumes outputs from all other tracks.

### Timeline is feasible

The CCTV perspective requests script itself quantifies the gap correctly:

- **Deadline:** Sep 10, 2026 (CHI 2027, listed as "stretch, earlier" venue for Paper C)
- **Engineering effort:** ~10 days total for all infrastructure gaps
- **Data collection window:** 8 weeks starting ~Jun 13
- **Days available (as of plan date):** 117

The binding constraint is data collection time, not engineering effort.

### Dependencies exist and are functional

Two of the planned dependencies for REQ-09 already exist:

| Dependency | Status |
|-----------|--------|
| `shared/eigenform_logger.py` | Exists (3.4KB), functional |
| `agents/hapax_daimonion/grounding_ledger.py` | Exists (13.7KB), functional |

## Root cause of false characterization

The CCTV disconfirmation probe aggregated the absence of Track C implementation and reframed it as a "pipeline failure" requiring "rescue." The key errors:

1. **"Rescue" implies breakage** — nothing is broken; the infrastructure is unstarted per plan
2. **"Cherry-pick grafting-conditions"** references a module that has never existed
3. **The probe ignored the implementation plan's dependency ordering** — Track C is correctly scheduled last
4. **The probe's own perspective requests** (CHI-1 through CHI-5 in `scripts/run_cctv_perspective_requests.py`) correctly identify the gaps without framing them as failures

## Downstream impact

The downstream tasks should be reassessed:

- **p1-cherry-pick-grafting**: Should be retitled to "implement grafting conditions module" — there is nothing to cherry-pick
- **p1-annotation-scripts**: Valid planned work, but not a rescue operation
- **p1-export-scripts**: Valid planned work, correctly scoped
- **p2-integration-test / p3-reprobe**: Premature until Track A/B dependencies complete

None of these tasks represent urgent rescue work. They are correctly planned implementation tasks that should execute in dependency order per the existing plan.

## File Reference

| File | Role |
|------|------|
| `docs/superpowers/plans/2026-05-17-hapax-perspective-implementation.md` | Implementation plan defining Track C |
| `docs/superpowers/plans/publication-strategy.md:238` | CHI 2027 venue entry (Sep 2026 deadline) |
| `scripts/run_cctv_perspective_requests.py:171-206` | CCTV perspective probes CHI-1 through CHI-5 |
| `shared/eigenform_logger.py` | Existing dependency (functional) |
| `agents/hapax_daimonion/grounding_ledger.py` | Existing dependency (functional) |
