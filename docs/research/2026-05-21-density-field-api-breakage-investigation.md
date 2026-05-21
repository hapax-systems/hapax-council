# Density Field API Breakage — Root Cause Investigation

**Date:** 2026-05-21
**Author:** epsilon
**Task:** 202605181934-disconfirm-perspe-p0-investigate-root-cause
**Parent request:** REQ-202605181934-disconfirm-perspective-density-field-api-reconciliation
**Source:** CCTV Disconfirmation mode adversarial analysis (2026-05-18)
**Severity:** Critical (P0)

## Verdict: DISCONFIRMED (entirely false)

The claim that the density field API has 9 broken tests due to a `compute_density_state` function requiring a shim or migration is **incorrect on all counts**:

1. `compute_density_state` does not exist and has never existed in this codebase
2. Zero density-related tests are broken — all 35 pass
3. No API contract mismatch exists between the density field interface and any consumer

## Investigation Findings

### `compute_density_state` does not exist

Exhaustive search across the entire codebase:

```
grep -r "compute_density_state" . → 0 matches
grep -r "compute_density" . → 0 matches
```

The function named in the finding has no definition, no call site, no import, no comment reference, and no git history entry anywhere in the repository.

### The actual density field API

Three density-related modules exist, all with stable, tested interfaces:

| Module | Class/Function | Role |
|--------|---------------|------|
| `agents/density_field.py` | `DensityFieldCompute` | Primary density field calculator. `tick()` method writes temporal mode to SHM |
| `agents/programme_loop.py` | `_gather_density_field()` | Gathers density state for programme planning |
| `shared/information_density.py` | `InformationDensityField` | Shared density field abstraction |

### All 35 density-related tests pass

Three test suites cover the density field surface:

| Test file | Tests | Result |
|-----------|-------|--------|
| `tests/test_density_field.py` | 8 | All pass |
| `tests/programme_manager/test_planner_density_field.py` | 10 | All pass |
| `tests/test_information_density.py` | 17 | All pass |

No broken tests, no assertion failures, no import errors, no deprecation warnings.

### No VLA consumer breakage

The VLA (Visual Layer Aggregator) consumer of density field data operates through the SHM interface at `/dev/shm/hapax-compositor/`. The `DensityFieldCompute.tick()` method writes temporal mode data to this path. The write path is tested and functional. No consumer has reported failures or API mismatches.

## Root Cause of False Finding

The disconfirmation probe fabricated a function name (`compute_density_state`) that does not correspond to any symbol in the codebase. The 9 broken tests likewise do not exist. The probe may have:

1. Hallucinated the function name from partial knowledge of the `DensityFieldCompute` class
2. Confused density field internals with another subsystem's API
3. Invented a plausible-sounding API surface that doesn't match the actual implementation

This is a complete fabrication — not a misinterpretation of real evidence.

## Downstream Impact

The phase 1 task (`202605181934-disconfirm-perspe-p1-implement-fix`) and phase 2 verification task should be cancelled or marked as unnecessary. There is no fix to implement and no API to reconcile.

## File Reference

| File | Role |
|------|------|
| `agents/density_field.py` | `DensityFieldCompute` class — primary density calculator |
| `agents/programme_loop.py` | `_gather_density_field()` — density state aggregation |
| `shared/information_density.py` | `InformationDensityField` — shared density abstraction |
| `tests/test_density_field.py` | 8 unit tests (all pass) |
| `tests/programme_manager/test_planner_density_field.py` | 10 planner tests (all pass) |
| `tests/test_information_density.py` | 17 information density tests (all pass) |
