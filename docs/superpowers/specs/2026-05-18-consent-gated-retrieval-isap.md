# Consent-Gated Retrieval — Implementation Slice Authorization Packet

> **Authority Case:** CASE-CONSENT-GATED-RETRIEVAL-20260518
> **Risk Tier:** T2_MODERATE
> **Parent Research:** docs/research/2026-03-15-consent-gated-retrieval-research.md
> **Axiom Compliance:** interpersonal_transparency (weight 88) — primary driver

## Scope

Add query-time consent filtering to all retrieval paths. The ConsentGatedWriter
gates persistence; this gates reads. Three deliverables:

### D1: ConsentGatedReader

Wrapper for Qdrant search and markdown file reads that filters results by
checking `person_ids` metadata against active ConsentRegistry contracts.

- Input: query vector + ConsentRegistry
- Build Qdrant payload filter: exclude points where `person_ids` intersects
  non-consented set
- Log filtered-out count (never content) to audit
- Return only consent-clean results

Files: `shared/governance/consent_gated_reader.py` (new)

### D2: Graceful Degradation Levels

Four-level degradation instead of binary allow/deny:
1. Full access (consent active)
2. Abstraction (replace names with counts)
3. Existence acknowledgment ("details withheld pending consent")
4. Total suppression (sensitive categories only)

Files: `shared/governance/consent_degradation.py` (new)

### D3: Legacy Data Retroactive Labeling

Batch scan existing Qdrant collections for person mentions. Tag points
with `person_ids` metadata. Quarantine ambiguous points until cleared.

Files: `scripts/consent-retroactive-label` (new)

## Mutation Surface

- source: `shared/governance/` (2 new files)
- source: `scripts/` (1 new file)
- No runtime config changes
- No PipeWire/systemd changes

## Evidence Gates

- [ ] ConsentGatedReader unit tests with mock Qdrant
- [ ] Degradation level tests for all 4 levels
- [ ] Retroactive labeling dry-run on smallest collection
- [ ] Axiom compliance: interpersonal_transparency satisfied
