# R-18 Qdrant Twin Collapse — Status Reconcile

**Authored:** 2026-05-02 by beta.
**cc-task:** `r18-qdrant-twin-collapse-reconcile` (WSJF 4.5, p3).
**Origin audit:** `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md` § R-18.
**Adjacent design task (separate):** `temporal-consent-contract-interval-boundary-design` (active, not collapsed into this reconcile).

The original R-18 framing — *"qdrant twin collapse: `agents/_axiom_precedents.py` vs `shared/axiom_precedents.py` duplicate constants risk drift"* — was an oversimplification. This doc reconciles the real architectural picture.

---

## TL;DR

R-18 is **partially shipped + structurally resolved**:

- The "twin pattern" (`agents/_*.py` vendoring subsets of `shared/*.py`) is **intentional** and **documented** at `agents/_config.py:1-3`. Twins exist so `agents/` keeps a small, stable internal API surface that doesn't pull in the full `shared/` module graph.
- The **drift detection** test pin shipped via PR #1656 (`tests/test_twin_constant_drift.py`) covers 2 of the 4 fat-twin pairs.
- A 5th pair (`agents/_impingement.py`) is **already collapsed** as a re-export shim — drift is structurally impossible.
- This PR extends the drift test to cover apperception (3rd pair) and adds a separate dimension-name-parity pin (4th pair, structural twin), bringing test coverage to **all known fat-twin pairs**.

The original "collapse" framing — meaning "merge twin into one canonical module" — is **not the right move**. The twin pattern is intentional; drift detection is the actual deliverable.

---

## The 5 known fat-twin pairs

| Canonical | Vendored | Vendored shape | Drift detection |
|---|---|---|---|
| `shared/axiom_precedents.py` (334 LOC) | `agents/_axiom_precedents.py` (359 LOC) | Fat twin + `CircuitBreaker` add-on | Pinned via `TWIN_PAIRS` (PR #1656) |
| `shared/axiom_enforcement.py` | `agents/_axiom_enforcement.py` | Fat twin | Pinned via `TWIN_PAIRS` (PR #1656) |
| `shared/apperception.py` (726 LOC) | `agents/_apperception.py` (826 LOC) | Fat twin + extras | **NEWLY pinned via `TWIN_PAIRS`** (this PR) |
| `shared/dimensions.py` (153 LOC) | `agents/_dimensions.py` (135 LOC) | Structural twin (two `DimensionDef` classes) | **NEWLY pinned via `test_dimension_name_parity_across_twins`** (this PR; structural shape requires projection-based comparison) |
| `shared/impingement.py` | `agents/_impingement.py` (3 LOC) | **Re-export shim** (`from shared.impingement import *`) | N/A — drift structurally impossible |

After this PR: **all 5 known fat-twin pairs have drift detection** (or are immune via shim).

---

## Why "collapse" is the wrong framing

The audit row R-18 framed this as *"resolve duplication"*. But:

1. **Twin vendoring is intentional architecture.** `agents/_config.py:1-3` documents the pattern: vendored modules keep `agents/` decoupled from the heavier `shared/` module graph. Removing the twins would force `agents/` to import the full `shared/*.py` chain, increasing import-time cost and coupling.

2. **Twins serve different consumers.** `agents/_axiom_precedents.py` adds a `CircuitBreaker` for in-agent failure containment that `shared/axiom_precedents.py` correctly omits (the shared version is the canonical store; the agents wrapper carries call-site resilience).

3. **The actual risk is constant drift, not module duplication.** Two stale copies of `COLLECTION = "axiom-precedents"` is fine. Two divergent copies (`COLLECTION = "axiom-precedents"` vs `COLLECTION = "axiom_precedents"`) silently partitions the qdrant collection across two writers. The drift-detection test is the right invariant.

4. **The 5th pair already shows the right pattern when full collapse IS appropriate.** `agents/_impingement.py` is just `from shared.impingement import *`. When a twin's vendored side has no domain-specific extras, the re-export shim collapses cleanly. The other 4 twins all have domain-specific extras that justify their separate existence.

---

## Acceptance criteria mapping (cc-task closure)

| Criterion | Status |
|---|---|
| Determine whether qdrant twin collapse was shipped, superseded, or still missing | **REFRAMED** — "collapse" was the wrong goal; "drift detection across all 5 pairs" is the right goal, now achieved by this PR + #1656 |
| Add closure evidence or split implementation accordingly | This doc + the extended `tests/test_twin_constant_drift.py` is the closure evidence |
| Keep TemporalConsent contract work linked but separate | YES — `temporal-consent-contract-interval-boundary-design` remains a separate active design task; not folded into this reconcile |

---

## Code changes in this PR

`tests/test_twin_constant_drift.py`:

- **Added apperception pair to `TWIN_PAIRS`** with 5 ruminative-loop tuning constants (`COHERENCE_FLOOR`, `COHERENCE_CEILING`, `DEFAULT_RELEVANCE_THRESHOLD`, `RUMINATION_LIMIT`, `RUMINATION_GATE_SECONDS`). Drift on these would silently bias the imagination ↔ apperception coupling on one side.
- **Added `test_dimension_name_parity_across_twins`** — a separate projection-based drift pin for the dimensions pair. Tuple equality fails on class identity (each module defines its own `DimensionDef`), so the test compares `(name, kind, interview_eligible)` projections instead. Drift here would partition profile-fact writes across two divergent dimension definitions.
- **Bumped `test_twin_pair_count_pinned` from 2 → 3** with a comment explaining the dimensions exclusion.

`docs/governance/r18-qdrant-twin-collapse-2026-04-26-reconcile.md` (this file):

- Reframes R-18 from "collapse" to "drift discipline".
- Documents all 5 fat-twin pairs and their treatment.
- Provides the prevent-requeue rule (below).

---

## Prevent-requeue note

**R-18 reconcile rule:** before claiming any "qdrant twin collapse" or "twin pair drift" follow-up, check this doc and `tests/test_twin_constant_drift.py`. If the pair is in `TWIN_PAIRS` (or covered by `test_dimension_name_parity_across_twins`), drift detection is in place — there is no further "collapse" work needed.

If a NEW twin pair appears (per the architecture documented in `agents/_config.py:1-3`), extend this test by adding a tuple to `TWIN_PAIRS` (for value pairs) or a new projection test (for structural pairs). The bumped count pin will force a deliberate update.

---

## Cross-references

- Source audit: `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md` § R-18
- Architecture doc: `agents/_config.py:1-3` (twin pattern explanation)
- Prior shipping: PR #1656 `test(audit): pin twin-pair shared-constant drift (R-18)`
- Adjacent design task: `temporal-consent-contract-interval-boundary-design` (active, separate)
- Pattern: `feedback_status_doc_pattern` memory ("defer-with-concrete-blockers governance status docs are a high-leverage autonomous tool")
- Companion reconcile: `docs/governance/alpha-audit-closeout-2026-04-20-reconcile.md` (PR #2260)
