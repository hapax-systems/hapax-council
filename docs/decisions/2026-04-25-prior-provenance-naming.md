# Decision: keep `Claim.prior_provenance_ref` (not `prior_provenance`)

**Date:** 2026-04-25
**Author:** beta
**Audit context:** v4 §3.4 row AUDIT-08 (WSJF 4) — spec-divergence cleanup

## Context

`docs/research/2026-04-24-universal-bayesian-claim-confidence.md` §3 names the field `prior_provenance` on the `Claim` Pydantic model. The shipped code (`shared/claim.py:119`) uses `prior_provenance_ref: str`. The naming divergence is undocumented; AUDIT-08 flagged it.

## Decision

**Retain `prior_provenance_ref` in code; amend the spec to canonicalize the `_ref` suffix.**

## Rationale

1. **Field semantics differ from spec intuition.** The spec phrasing reads as if `prior_provenance` is a structural attribute of the claim — a `PriorProvenance` instance attached to it. The code reality is that the field stores a YAML-key string that resolves into the `shared/prior_provenance.yaml` registry. The `_ref` suffix marks this as a reference, not the data itself. Removing the suffix would invite the misreading "this `Claim` carries its own `PriorProvenance` payload."

2. **Indirection is intentional.** Per HPX004 (audit gate now wired in #1358), provenance lives in a single registry file so multiple `Claim` instances of the same `claim_name` share a single source-of-truth derivation. If `Claim.prior_provenance` were a structural field, every claim instance would either carry the full `PriorProvenance` (denormalized; wasteful + drift-prone) or carry None (ambiguous). The `_ref` shape is the canonical normal form.

3. **Renaming would touch every consumer in Phase 6 cluster code.** `PresenceEngine`, `SpeakerIsOperatorEngine`, `SystemDegradedEngine` all set this field at construction or read it in tests. A rename in the middle of the audit-incorporated migration adds churn for no semantic gain.

4. **Reverse decision (rename code) was considered + rejected.** Pros: spec-fidelity, "obvious" naming. Cons: 4 file touches + 2 test classes + reviewer coordination across all 4 sessions for a cosmetic change. The cost-benefit favors documenting the divergence over performing it.

## Spec amendment required

`docs/research/2026-04-24-universal-bayesian-claim-confidence.md` §3 should be updated to read:

> **`prior_provenance_ref: str`** — YAML key into `shared/prior_provenance.yaml`. The provenance record itself is stored once per `claim_name` in the registry; this field carries the lookup key. CI rule HPX004 enforces that every key resolves.

This amendment lands in a follow-up doc PR; this decision doc captures the rationale + retains the existing code shape.

## Consequences

- Future Phase 6 cluster engines continue using `prior_provenance_ref` (no migration needed).
- Spec readers see the `_ref` suffix and understand it's a registry key (consistent with `shared/governance/publication_allowlist.py` etc. which similarly use `_ref`-suffixed strings for axiom-contract references).
- HPX004 validator continues catching unregistered claims at CI time; no test changes needed.

## References

- `shared/claim.py:119` — `Claim.prior_provenance_ref: str`
- `shared/prior_provenance.yaml` — the registry (3 entries: operator_present, speaker_is_operator, system_degraded)
- `scripts/check-claim-registry.py` — HPX003 + HPX004 validators (now CI-wired via #1358)
- `docs/operations/2026-04-25-workstream-realignment-v4-audit-incorporated.md` §3.4 row AUDIT-08
