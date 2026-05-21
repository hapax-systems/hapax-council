# Governance Algebraic Hardening Test Coverage — Verification

**Date:** 2026-05-21
**Author:** epsilon
**Task:** 202605181934-disconfirm-govern-p0-confirm-rootcause
**Parent request:** REQ-202605181934-disconfirm-governance-algebraic-test-coverage
**Source:** CCTV Disconfirmation mode adversarial analysis (2026-05-18)

## Verdict: DISCONFIRMED (false positive)

The disconfirmation probe finding that "axiom backstop, replay harness, refusal registry have zero unit tests" is **incorrect**. All three modules have comprehensive test suites with high coverage.

## Module Inventory and Coverage

### 1. Axiom Backstop = `shared/axiom_enforcement.py`

The term "axiom backstop" does not appear in the codebase. The module serving this function is `shared/axiom_enforcement.py` (368 lines) — framework-agnostic axiom enforcement with hot/cold split (`check_fast` for inline <1ms evaluation, `check_full` for deferred Qdrant + YAML compliance checks).

| Metric | Value |
|--------|-------|
| Module path | `shared/axiom_enforcement.py` |
| Lines | 368 |
| Statements | 105 |
| Test file | `tests/test_axiom_enforcement.py` (232 lines) |
| Additional test file | `tests/test_axiom_enforcement_governance.py` |
| Tests | 31 (20 in primary file) |
| Line coverage | **89%** (12 statements missed) |
| Missed lines | 231-236, 246-248, 308, 311, 342-346 |
| Test classes | TestSchemaVer, TestCheckFast, TestCompileRules, TestCheckFull, TestRefusalBriefEmission |

Related modules with their own test suites:
- `shared/axiom_enforcer.py` with `tests/test_axiom_enforcer_runbook.py` and `tests/test_axiom_enforcer_transition.py`

### 2. Replay Harness = `packages/agentgov/src/agentgov/replay.py`

| Metric | Value |
|--------|-------|
| Module path | `packages/agentgov/src/agentgov/replay.py` |
| Lines | 118 |
| Test file | `packages/agentgov/tests/test_replay.py` (169 lines) |
| Tests | 15 |
| All pass | Yes |
| Test classes | TestReplayDecision, TestReplayBatch, TestEscalation, TestReplayProperties |
| Property tests | Yes — Hypothesis with 50+ examples |

Coverage measurement was blocked by the agentgov subpackage's isolated virtual environment lacking pytest-cov, but the test suite covers: replay decisions (same outcome, regression, denied-now-allowed), batch aggregation, escalation extraction, ntfy formatting, and property-based invariants.

### 3. Refusal Registry = `shared/refusal_registry.py`

| Metric | Value |
|--------|-------|
| Module path | `shared/refusal_registry.py` |
| Lines | 145 |
| Statements | 89 |
| Test file | `tests/test_refusal_registry.py` (84 lines) |
| Tests | 8 |
| Line coverage | **94%** (5 statements missed) |
| Missed lines | 50-51, 73, 75, 118 |
| Test classes | TestRegistryCompleteness, TestQueryFunctions, TestFrontmatterConsistency |

Additional refusal-related test files in the codebase: 12+ files covering refusal brief publishing, rendering, feedback, correspondence, lifecycle integration, and obligation models.

## Root Cause of False Finding

The disconfirmation probe's "zero unit tests" finding is a false positive caused by:

1. **Name mismatch.** The probe searched for "axiom backstop" — a term that appears nowhere in the codebase. The actual module is `axiom_enforcement`.

2. **Subpackage blindness.** The replay harness lives in `packages/agentgov/`, a subpackage with its own `pyproject.toml` and test directory. A naive search of `tests/` at the project root would miss `packages/agentgov/tests/test_replay.py`.

3. **Possible scope confusion.** The probe may have been looking for "algebraic hardening" tests as a distinct category rather than the unit tests that exercise the same modules.

## Coverage Configuration

No coverage exclusion patterns exist in `pyproject.toml` or `.coveragerc` that would hide these modules. Test markers (`llm`, `contract`, `e2e`, `revocation_drill`) are default-deselected but none apply to the governance test files. All governance tests run in the default `pytest` invocation.

## Downstream Impact

The three phase 1 tasks blocked by this finding should be re-evaluated:
- `202605181934-disconfirm-govern-p1-write-axiom-backstop-tests` — axiom enforcement already has 89% coverage
- `202605181934-disconfirm-govern-p1-write-replay-harness-tests` — replay harness already has 15 tests including property-based
- `202605181934-disconfirm-govern-p1-write-refusal-registry-tests` — refusal registry already has 94% coverage

These tasks may be closeable as already-satisfied, or narrowed to cover only the specific missed lines identified above.

## Test Run Evidence

```
$ uv run pytest tests/test_refusal_registry.py tests/test_axiom_enforcement.py -v
============================== 31 passed in 4.45s ==============================

$ uv run pytest packages/agentgov/tests/test_replay.py -v
============================== 15 passed in 0.22s ==============================

$ uv run pytest tests/test_refusal_registry.py tests/test_axiom_enforcement.py \
    --cov=shared.refusal_registry --cov=shared.axiom_enforcement --cov-report=term-missing
Name                          Stmts   Miss  Cover   Missing
-----------------------------------------------------------
shared/axiom_enforcement.py     105     12    89%   231-236, 246-248, 308, 311, 342-346
shared/refusal_registry.py       89      5    94%   50-51, 73, 75, 118
-----------------------------------------------------------
TOTAL                           194     17    91%
```
