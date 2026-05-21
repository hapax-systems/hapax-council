---
title: "Model-card precedents and redaction schema patterns"
date: 2026-05-21
author: epsilon
status: findings
cc_task: 20260521160230-public-evidence-phase0-research-prior-art
authority_case: CASE-EVIDENCE-ADMISSION-20260521
---

# Model-Card Precedents and Redaction Schema Patterns

## 1. Surveyed sources

### 1.1 Hugging Face Model Cards (OpenHermes format)

Standard fields: `model_name`, `model_type`, `license`, `language`, `tags`,
`datasets`, `metrics`, `library_name`, `pipeline_tag`. Structured sections:
Model Description, Intended Uses, Limitations, Training Data, Evaluation
Results, Citation.

Relevant patterns:
- **Limitations section** is mandatory, not optional — model cards that omit it
  are flagged by the Hub validator
- **Evaluation results** carry metric name + value + dataset + verified status
- **License** is a constrained enum, not free text

### 1.2 Croissant (MLCommons data card schema)

JSON-LD structured metadata for datasets. Fields: `name`, `description`,
`license`, `creator`, `datePublished`, `distribution`, `recordSet`,
`field` (with `dataType`, `source`).

Relevant patterns:
- **Provenance chain**: each `field` references a `source` with extraction method
- **Schema versioning**: `@context` pins the vocabulary version
- **Distribution** separates the metadata from the artifact location

### 1.3 FAIR Data Card (GO FAIR)

Findable, Accessible, Interoperable, Reusable. Metadata fields: persistent
identifier, rich metadata, data access protocol, provenance, license,
domain-relevant community standards.

Relevant patterns:
- **Persistent identifier** requirement (DOI, ORCID) — cards must be citable
- **Access protocol** is explicit (not implied) — fail-closed on ambiguity
- **Reuse conditions** are machine-readable, not prose

### 1.4 Hapax source-quality ledger (existing)

`shared/grounding_provider_router.py` uses `source_quality` as a field in
provider configs. `shared/cross_surface_event_contract.py` defines
`FanoutDecision` (allow/redact/hold/deny) for cross-surface event routing.

Relevant patterns:
- **Tier-based quality** (High/Medium/Low) rather than numeric scores
- **Fail-closed redaction**: `FanoutDecision` defaults to `redact` or `deny`
  when surface contract conditions aren't met
- **Per-surface allowlists**: each surface declares `allowed_actions` as a tuple

### 1.5 Hapax `CapabilityEvidenceCard` (just implemented)

`shared/capability_evidence_card.py` defines the internal evidence card with
`lifecycle_status`, `privacy_class`, `consumer_permissions`, `cannot_prove`,
`blocking_card_ids`, `freshness_deadline`.

Relevant patterns:
- **Admissibility predicate** with structured rejection reasons
- **Privacy hierarchy** (public < internal < operator_only < consent_gated)
- **Negative evidence** (`cannot_prove`) as a first-class field

## 2. Candidate fields for HapaxConceptCard (5+)

| Field | Type | Source precedent | Rationale |
|-------|------|-----------------|-----------|
| `concept_id` | str | Croissant `name` + FAIR persistent ID | Stable reference across versions |
| `concept_name` | str | HF `model_name` | Human-readable |
| `description` | str | HF Model Description | What the concept is |
| `provenance_chain` | list[str] | Croissant `source`, FAIR provenance | How the concept was derived (research → spec → impl) |
| `claim_ceiling` | enum | Hapax `public_claim_ceiling` | Maximum claim strength (no_claim / internal_only / publication_witness / peer_reviewed) |
| `what_this_does_not_prove` | str | HF Limitations, CE `cannot_prove` | Explicit negative — what the concept's existence does NOT establish |
| `related_concepts` | list[str] | Croissant `field.source` | Cross-references to other concept cards |
| `version` | str | Croissant `@context` versioning | Schema version for forward compatibility |

## 3. Candidate fields for PublicSafeEvidenceCard (5+)

| Field | Type | Source precedent | Rationale |
|-------|------|-----------------|-----------|
| `evidence_id` | str | FAIR persistent ID | Citable reference |
| `source_card_id` | str | CE `card_id` | Links to internal `CapabilityEvidenceCard` |
| `public_claim` | str | HF Evaluation Results | What the evidence supports (redacted from internal claim) |
| `redaction_policy` | enum | Hapax `FanoutDecision` | What was removed: `none` / `names` / `values` / `full` |
| `redacted_fields` | list[str] | Croissant field-level metadata | Which fields were redacted and why |
| `privacy_clearance` | enum | CE `PrivacyClass` | Minimum privacy context for this card to be shown |
| `limitations` | list[str] | HF Limitations | What this evidence does not prove (public version) |
| `methodology_ref` | str | HF Training Data section | How the evidence was collected |
| `freshness_window` | str | CE `freshness_deadline` | When the evidence expires |

## 4. Redaction/allowlist pattern: fail-closed semantics

**Existing pattern**: `shared/cross_surface_event_contract.py`

```python
type FanoutDecision = Literal["allow", "redact", "hold", "deny"]

@dataclass(frozen=True)
class SurfaceContract:
    allowed_actions: tuple[str, ...]
    # If an action is not in allowed_actions, it is denied by default
```

**Fail-closed behavior**: The `FanoutDecision` defaults to the most restrictive
option when conditions aren't met. Each surface declares its own allowlist;
unlisted actions are implicitly denied. This is the correct pattern for
evidence cards:

- A `PublicSafeEvidenceCard` should only include fields explicitly listed in the
  public allowlist
- Any field NOT in the allowlist is redacted before publication
- The allowlist is per-card-type, not per-instance — changing what's public
  requires a schema change, not a runtime flag

## 5. Gaps between precedents and Hapax requirements

| Gap | Precedent state | Hapax need |
|-----|----------------|------------|
| **Novel-concept provenance** | Croissant tracks dataset lineage; HF tracks training data | Hapax needs concept → research → spec → implementation provenance chains that cross repo/vault boundaries |
| **Claim ceiling** | HF has no ceiling concept; Croissant has license | Hapax needs graduated claim authority (no_claim through peer_reviewed) as an enum, not a license |
| **what_this_does_not_prove** | HF Limitations is prose; CE `cannot_prove` is a single string | Public cards need structured negative evidence that matches the positive claim shape |
| **Cross-card blocking** | No precedent in HF/Croissant/FAIR | CE has `blocking_card_ids`; public cards need a way to say "this evidence is blocked by missing evidence X" |
| **Redaction audit trail** | No precedent for recording what was redacted and why | PublicSafeEvidenceCard needs `redacted_fields` + `redaction_policy` so the public card is self-documenting about its own incompleteness |
| **Operator-only provenance** | All precedents assume public/team access | Some provenance steps (e.g., "operator experienced X during livestream") are consent-gated and cannot appear in public cards |
