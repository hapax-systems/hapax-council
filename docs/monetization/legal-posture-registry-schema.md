---
title: "Tax/Legal-Posture Registry — Schema and Honest-Dark Gate"
type: design
created: 2026-06-30
authority_case: CASE-SDLC-REFORM-001
parent_request: REQ-20260628-mdlc-tax-legal-posture-registry
parent_spec: hapax-council/docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md
cc_task: 20260628-registry-phase0-schema-and-honest-dark-gate
tags: [design, legal-registry, g2, mdlc, monetization, governance]
status: active
---

# Tax/Legal-Posture Registry — Schema and Honest-Dark Gate

The g2 substrate for every arbitrage surface. Without this registry, "legal in venue" is a vibe-check, not a gate.

## 1. Purpose

This document defines the **legal-posture registry**: a per-surface, per-venue, per-instrument record of whether Hapax has legal clearance to operate a given monetization or arbitrage surface in a given jurisdiction. It is the machine-readable substrate behind the **g2 gate** ("legal in venue").

**Design principles:**
- **Honest-dark by presence.** A DARK row explicitly claims "no clearance." A missing row is equivalent to DARK — absence is not ambiguity, it is a fail-closed gate.
- **Cited authority per venue.** Every non-DARK verdict must cite a specific statute, regulation, ToS clause, or legal opinion. "Probably fine" is not a citation.
- **Operator axiology floor.** The registry is operator-signed. No automated process may upgrade a verdict from DARK to LIT or PARTIAL without operator review and signature.
- **Fail-closed admission.** A disposition touching a surface+venue+instrument tuple without a LIT g2 row in this registry does not commit.

## 2. Registry Row Schema

Each row in the registry represents one `(surface, venue, instrument)` tuple and its legal-posture assessment.

### 2.1 Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `surface` | string (enum) | **yes** | The arbitrage or monetization surface. One of: `prediction_market`, `bug_bounty`, `whistleblower`, `white_label`, `data_exhaust`, `receive_only_rail`, or future surfaces added by operator. |
| `venue` | string | **yes** | Jurisdiction or platform. For geographic: ISO 3166-1 alpha-2 country code or US state postal abbreviation (e.g., `US-MN`, `US-NV`, `GB`). For platform-specific: platform identifier (e.g., `kalshi`, `polymarket`, `anthropic`, `hackerone`). |
| `instrument` | string | **yes** | The specific instrument, product, or mechanism within the surface (e.g., `event_contract`, `binary_option`, `ach_receive`, `sec_tip`, `b2b_resale`). Use `*` for surface-wide venue assessment. |
| `g2_verdict` | string (enum) | **yes** | Legal-posture verdict. One of: `LIT`, `PARTIAL`, `DARK`. See §3 for semantics. |
| `citation` | string | **yes** | Statute, regulation, ToS clause, case law, or legal opinion backing the verdict. DARK rows cite the reason for darkness (e.g., "state gambling ban", "no research completed"). |
| `authority_basis` | string | **yes** | The category of legal authority cited. One of: `statute`, `regulation`, `case_law`, `tos_clause`, `legal_opinion`, `agency_guidance`, `no_research`, `operator_judgment`. |
| `review_date` | date (ISO 8601) | **yes** | Date of last substantive review of this row's legal analysis. |
| `freshness_ttl_days` | integer | **yes** | Maximum days after `review_date` before this row degrades to stale. Default: 180. High-volatility venues (e.g., prediction markets with active litigation) should use 90 or shorter. |
| `operator_signed` | boolean | **yes** | Whether the operator has reviewed and signed off on this verdict. An unsigned row is treated as DARK regardless of its stated `g2_verdict`. |
| `operator_sign_date` | date (ISO 8601) | if signed | Date of operator signature. |
| `notes` | string | no | Free-text notes, caveats, pending research questions. |
| `open_questions` | list[string] | no | Unresolved legal questions that affect this verdict. A row with open questions cannot be LIT (it is at most PARTIAL). |
| `blocks_surfaces` | list[string] | no | Other surfaces or tasks this row gates. For cross-reference. |
| `source_task` | string | no | The cc-task or research task that produced this row. |
| `supersedes` | string | no | Row ID this entry supersedes (for amendment tracking). |

### 2.2 Row Identity

A row is uniquely identified by the tuple `(surface, venue, instrument)`. There MUST NOT be duplicate rows for the same tuple. If a legal posture changes, the existing row is updated (with `supersedes` pointing to the prior version if archived).

### 2.3 Compound Key Semantics

- A row with `instrument: "*"` applies to all instruments on that surface+venue unless a more specific row exists.
- Specificity: `(surface, venue, instrument)` > `(surface, venue, *)` > `(surface, *, instrument)` > `(surface, *, *)`.
- Venue-specific rows outrank global instrument defaults because g2 is a legal-in-venue gate; the wildcard-venue instrument row exists for deterministic fallback only.
- The most specific matching row wins. If the most specific match is DARK, the disposition is blocked regardless of less-specific LIT rows.

## 3. G2 Verdict Semantics — LIT / PARTIAL / DARK

### 3.1 LIT (Legal, Investigated, Tracked)

**Meaning:** The operator has affirmatively determined, based on cited legal authority, that operating this surface+venue+instrument is legal and the legal basis is documented.

**Requirements for LIT:**
- `citation` must reference a specific statute, regulation, ToS clause, or legal opinion.
- `authority_basis` must be a value other than `no_research` or `operator_judgment`.
- `open_questions` must be empty (no unresolved questions).
- `operator_signed` must be `true`.
- Row must not be stale (see §4).

**Effect:** The g2 gate passes. The disposition may proceed.

### 3.2 PARTIAL (Partially Cleared, Caveats Apply)

**Meaning:** Some legal basis exists but there are unresolved questions, jurisdictional ambiguity, or conditions that limit the clearance.

**Requirements for PARTIAL:**
- `citation` must reference the partial basis.
- `open_questions` should document what remains unresolved.
- `operator_signed` must be `true`.
- Row must not be stale.

**Effect:** The g2 gate passes with advisory warning. The disposition may proceed but the open questions are surfaced as a governance advisory. A PARTIAL verdict with stale review degrades to DARK.

### 3.3 DARK (No Clearance)

**Meaning:** No legal clearance exists. This is an honest claim: "we do not have clearance to operate here." DARK is not a temporary state of ignorance dressed as caution — it is the explicit, auditable statement that this tuple has no legal basis.

**Why "honest-dark":** A DARK row is more informative than a missing row. It records *that* the question was asked and *why* clearance is absent (ban, no research, active litigation, etc.). The registry is honest about darkness: a DARK row claims no clearance, not "probably fine but we haven't checked."

**Requirements for DARK:**
- `citation` must state why clearance is absent (e.g., "MN state gambling ban — Minn. Stat. §609.76", "no research completed", "active litigation — WA v. Kalshi Mar 2026").
- `operator_signed` may be `false` (DARK is the safe default; operator sign-off confirms the analysis is complete but is not required for the gate to close).

**Effect:** The g2 gate fails closed. The disposition does not commit.

### 3.4 Absence = DARK

A `(surface, venue, instrument)` tuple with **no row in the registry** is treated identically to DARK for gate purposes. The g2 gate fails closed on absence.

**Why absence fails closed:** The registry's purpose is to provide *affirmative evidence* of legal clearance. Silence is not clearance. Any surface+venue+instrument that has not been researched and recorded is blocked by construction.

## 4. Freshness Gate

### 4.1 Staleness Rules

A row becomes **stale** when `current_date - review_date > freshness_ttl_days`.

**Staleness effects:**
- A stale LIT row degrades to **DARK** (clearance withdrawn until re-reviewed).
- A stale PARTIAL row degrades to **DARK** (clearance withdrawn until re-reviewed).
- A stale DARK row remains DARK (staleness cannot make darkness worse).

### 4.2 Freshness TTL Guidelines

| Volatility Class | Default TTL | Examples |
|---|---|---|
| **High** (active litigation, recent regulatory change) | 90 days | Prediction markets (Kalshi/WA litigation), BIPA venues, ECCN classifications under review |
| **Standard** (stable statutory basis) | 180 days | Established ToS clauses, settled case law, stable state statutes |
| **Low** (constitutional/structural) | 365 days | First Amendment protections, federal preemption holdings |

### 4.3 Review Cadence

The operator should review all non-DARK rows at least once per `freshness_ttl_days`. A cron-equivalent advisory (or `coord.why-blocked` on stale rows) surfaces rows approaching or past their TTL.

## 5. G2 Gate Contract

### 5.1 Gate Predicate

The g2 gate is a presence-check against this registry. Formally:

```text
g2_gate(surface, venue, instrument) → { PASS, PASS_WITH_ADVISORY, FAIL }

1. Find the most specific matching row R for (surface, venue, instrument), using this deterministic order:
   a. (surface, venue, instrument)
   b. (surface, venue, *)
   c. (surface, *, instrument)
   d. (surface, *, *)
2. If no row exists → FAIL (absence = DARK).
3. If R.operator_signed == false AND R.g2_verdict != DARK → FAIL (unsigned non-DARK is invalid).
4. Compute effective_verdict:
   a. If R is stale AND R.g2_verdict != DARK → effective_verdict = DARK.
   b. Otherwise → effective_verdict = R.g2_verdict.
5. If effective_verdict == LIT → PASS.
6. If effective_verdict == PARTIAL → PASS_WITH_ADVISORY (surface open_questions + staleness warning).
7. If effective_verdict == DARK → FAIL.
```

### 5.2 Fail-Closed Invariant

**A disposition touching a surface+venue+instrument tuple MUST NOT commit if `g2_gate()` returns FAIL.** This is a hard gate, not an advisory. The only escape is:
- Add or update a registry row with LIT or PARTIAL verdict.
- Obtain operator signature.
- Ensure freshness.

There is no `HAPAX_G2_OFF` env var. There is no bypass. The gate reads the registry file directly (daemon-independent, per the parent spec §4.4). If the registry file is missing or unreadable, the gate fails closed on all tuples.

### 5.3 Gate Placement

The g2 gate fires at:
- **Disposition commit time** — before any monetization or arbitrage disposition is persisted.
- **Disposition planning time** (advisory) — `coord.why-blocked` can dry-run g2 and report missing/stale/DARK rows before work begins.

### 5.4 Recheck Commands

Until the source gate exists, reviewers can recheck the registry contract with deterministic text/YAML checks:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml
registry = Path("docs/monetization/legal-posture-registry.yaml")
schema = Path("docs/monetization/legal-posture-registry-schema.md").read_text()
data = yaml.safe_load(registry.read_text())
assert data["schema_version"] == "1.0.0"
rows = data["rows"]
keys = [(row["surface"], row["venue"], row["instrument"]) for row in rows]
assert len(keys) == len(set(keys)), "duplicate registry tuple"
assert all(row["g2_verdict"] == "DARK" for row in rows)
assert all(
    row["operator_signed"] is True or row["g2_verdict"] == "DARK"
    for row in rows
), "unsigned non-DARK row"
assert len([
    row for row in rows
    if row.get("source_task") == "20260628-registry-phase3-bug-bounty-subtree"
]) == 7
assert len([
    row for row in rows
    if row.get("source_task") == "20260628-registry-phase5-white-label-subtree"
]) == 6
assert len([
    row for row in rows
    if row.get("source_task") == "20260628-registry-phase6-data-exhaust-subtree"
]) == 9
assert "(surface, *, instrument)" in schema
assert "If R is stale AND R.g2_verdict != DARK" in schema
assert "If no row exists → FAIL" in schema
print(f"legal-posture registry recheck OK: {len(rows)} rows")
PY
```

## 6. Common Row Template for Follow-On Subtrees

Each of the 6 follow-on subtree tasks (phases 1–6) seeds rows into this registry for their surface. The following YAML template is the common structure every subtree MUST use:

```yaml
# Template: one registry row
- surface: <surface_enum>           # prediction_market | bug_bounty | whistleblower | white_label | data_exhaust | receive_only_rail
  venue: <venue_id>                 # ISO 3166-1 alpha-2 or US state postal (e.g., US-MN) or platform ID (e.g., kalshi)
  instrument: <instrument_id>       # Specific instrument or "*" for surface-wide
  g2_verdict: <LIT|PARTIAL|DARK>
  citation: >
    <Specific statute, regulation, ToS clause, case law, or reason for DARK.
    Must be a real citation, not "probably fine.">
  authority_basis: <statute|regulation|case_law|tos_clause|legal_opinion|agency_guidance|no_research|operator_judgment>
  review_date: <YYYY-MM-DD>
  freshness_ttl_days: <90|180|365>  # Choose based on volatility class (§4.2)
  operator_signed: <true|false>
  operator_sign_date: <YYYY-MM-DD or null>
  notes: <optional free-text>
  open_questions:                   # Must be empty for LIT
    - <question if any>
  blocks_surfaces:                  # Optional cross-references
    - <surface or task blocked by this row>
  source_task: <cc-task-id that produced this row>
```

### 6.1 Subtree Responsibilities

| Phase | cc-task suffix | Surface | Scope |
|---|---|---|---|
| 1 | `registry-phase1-operator-state-of-residence-confirmation` | all | Operator state of residence confirmation — the binary GREEN/RED fact gating prediction_market and any state-specific surface |
| 2 | `registry-phase2-prediction-market-subtree` | `prediction_market` | §1256 vs gambling, OBBBA 90% loss cap, 50-state matrix, Kalshi/Polymarket ToS |
| 3 | `registry-phase3-bug-bounty-subtree` | `bug_bounty` | License Exception ACE deemed-export, ECCN 4D004 tooling, §1201, hobby-loss |
| 4 | `registry-phase4-whistleblower-subtree` | `whistleblower` | SEC original-information doctrine, 18 USC §873 extortion tripwire, file-to-government-first |
| 5 | `registry-phase5-white-label-subtree` | `white_label` | Anthropic "competing product" clause, FTC §5 B2B-undisclosed, open-weight license audit |
| 6 | `registry-phase6-data-exhaust-subtree` | `data_exhaust` | BIPA/CUBI/WA-MHMD self-sale, PADFAA data-broker, deidentification standard |

Each subtree task:
1. Researches the legal landscape for its surface across relevant venues.
2. Produces registry rows using the template above.
3. Appends rows to `docs/monetization/legal-posture-registry.yaml`.
4. Documents research methodology and sources in a companion research doc.
5. Marks unresolved questions as `open_questions` (forcing PARTIAL at most).
6. Submits for operator review and signature.

## 7. Registry File Location and Format

**File:** `docs/monetization/legal-posture-registry.yaml`
**Format:** YAML (machine-readable, diffable, grep-friendly)

The registry file has a header section and a rows section:

```yaml
---
# Legal-Posture Registry
# Schema version: 1.0.0
# Authority: CASE-SDLC-REFORM-001
# Parent request: REQ-20260628-mdlc-tax-legal-posture-registry
# Gate contract: docs/monetization/legal-posture-registry-schema.md §5
#
# This file is the SSOT for g2 ("legal in venue") gate decisions.
# Absence of a row = DARK (fail-closed).
# Do not add rows without cited legal authority.
# Do not upgrade DARK→LIT/PARTIAL without operator signature.

schema_version: "1.0.0"
schema_doc: docs/monetization/legal-posture-registry-schema.md
last_updated: <YYYY-MM-DD>
update_author: <cc-task-id or operator>

surfaces:
  - prediction_market
  - bug_bounty
  - whistleblower
  - white_label
  - data_exhaust
  - receive_only_rail

rows:
  # Rows are appended by subtree tasks (phases 1-6).
  # Each row follows the template in §6 of the schema doc.
  []
```

## 8. Relationship to Existing Monetization Architecture

This registry is **complementary** to the existing monetization rails architecture:

| Existing | This Registry |
|---|---|
| `MonetizationRiskGate` (4-level risk classification) | g2 gate (per-venue legal clearance) |
| Rails capability matrix (10 receive-only rails) | Legal-posture rows for `receive_only_rail` surface per venue |
| Axiom enforcement (constitutive rules) | Operator axiology floor on verdicts |

The g2 gate is **upstream** of the `MonetizationRiskGate`. A surface must pass g2 (legal in venue) before reaching the risk classification layer. A LIT g2 row does not mean the risk is low — it means the activity is legal. Risk classification is a separate, downstream concern.

## 9. Amendment Protocol

1. **Adding a row:** Requires research, citation, and operator signature (for non-DARK). File via a cc-task referencing this schema.
2. **Upgrading DARK → PARTIAL or LIT:** Requires new legal research, updated citation, and operator re-signature. The prior row's `supersedes` field tracks the chain.
3. **Downgrading LIT/PARTIAL → DARK:** Any agent or automated process may downgrade to DARK (fail-safe direction). Operator notification required but not blocking.
4. **Staleness auto-downgrade:** Automated per §4. No operator action required for the downgrade itself, but notification surfaces the stale row.
5. **Schema evolution:** Changes to this schema document require a cc-task under `CASE-SDLC-REFORM-001`.
