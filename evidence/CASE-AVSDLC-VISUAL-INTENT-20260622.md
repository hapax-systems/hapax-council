---
case_id: CASE-AVSDLC-VISUAL-INTENT-20260622
version: 0
stage: S5_AUTHORIZATION_PACKET
status: implementation_authorized
created_utc: 2026-06-22T03:40:00Z
originator: cc-cns-mig
methodology: hapax-sdlc
risk_tier: T1_LOW
source_mutation_authorized: true
docs_mutation_authorized: true
vault_mutation_authorized: true
implementation_authorized: true
release_authorized: false
public_current: false
axiom_mutation_authorized: false
plan_accepted: true
plan_grants_implementation_authority: true
axiom_compliance_checked: true
axiom_compliance_result: "All 5 axioms satisfied. single_user: the module honestly names that a self-authored intent can be weak-but-true and that the anti-vacuity guard covers absence/triviality, not adversarial weakness (witness independence — a PR 4/N property — is the self-collusion defense). No auth/roles; reuses the operator coord key; no employer data; no persistent non-operator state; release arm stays operator-delegated for the governance-sensitive path."
consent_contract_required: false
source_mutation_scope: "shared/avsdlc_visual_intent.py, shared/governance/coord_capabilities.py, tests/shared/test_avsdlc_visual_intent.py, tests/shared/test_avsdlc_receipt_provenance.py, evidence/CASE-AVSDLC-VISUAL-INTENT-20260622.md"
implementation_scope: "AVSDLC visual-evaluation, thin PR 3/N: the intent-as-predicate (predict-then-confirm) MECHANISM. A VisualIntentRecord of falsifiable per-region predicates, an allowlist-validating parser, a canonical note-excluding intent_hash, an anti-vacuity guard, and a pure critical-AND evaluator — exercised entirely with synthetic realized/baseline vectors. The receipt gains a signed intent_hash (TAMPER-EVIDENCE only). Witness realized-vector computation, gate wiring (overall PASS = floors AND intent_pass), and the production baseline are PR 4/N."
parent_spec: "~/Documents/Personal/30-areas/hapax/cns-visual-evaluation-requirements-2026-06-21.md"
---

# CASE-AVSDLC-VISUAL-INTENT-20260622

## Purpose

The research's dominant finding: visual evaluation's missing leg is INTENT-LEGIBILITY.
A `% white 22%→0.00%` number authored *after* the change and self-scored is not a
checkable claim. The antidote (parent_spec §3) is predict-then-confirm: pre-authored
falsifiable predicates, hash-bound to the deployed bytes, confirmed by an independent
witness. This case authorizes the first slice — the MECHANISM — so the rest (witness
realized-vector + gate conjunct) can drop onto a tested foundation.

## Governing Principles

- interpersonal_transparency (88): a claim now corresponds to a prediction made BEFORE
  the outcome, mechanically checkable — not the author scoring their own work.
- no_expert_system_rules: predicates over PERCEIVED per-region metrics, not hardcoded verdicts.
- single_user (100): honestly named — anti-vacuity guards absence/triviality, not adversarial
  weakness; witness independence (PR 4/N) is the self-collusion defense.
- management_governance (85): release arm stays operator-delegated (governance-sensitive path).

## Risk Assessment

T1_LOW — additive, reversible, fully test-covered (39 new tests), backward-compatible. The
new receipt field `intent_hash` is optional/defaulted, signed for TAMPER-EVIDENCE only
(no new verify behavior, no gate). `shared/governance/coord_capabilities.py` is
governance-sensitive → frontier-review floor + operator release-arm. No fail-closed gate at
the live restart (PR 3/N adds no gate at all). The intent module is dependency-light
(stdlib only), mirroring `coord_capabilities`.

## Research Evidence (S1 Complete)

Parent_spec (workflow `wf_292da963`) §3 defines the predict-then-confirm protocol. The
thin-slice scoping + the honesty corrections (intent_hash is tamper-evidence not
correspondence; drop the unconstrained `golden_ref`; pin anti-vacuity's synthetic baseline)
came from a 5-agent design workflow (`wf_a2a74363`) whose adversarial critic returned
needs-revision — all three must-fixes are applied here.

## Plan (S2) — this thin PR (3/N): the mechanism

1. NEW `shared/avsdlc_visual_intent.py`: `VisualIntentPredicate` + `VisualIntentRecord`
   (frozen) + `parse_intent_record` (vendored Phase-1 allowlists; rejects empty/unknown) +
   `serialize_intent_record` + `intent_hash_from_record` (canonical, note-excluding,
   order-significant) + `anti_vacuity_check` (pure, synthetic baseline) + `intent_pass`
   (critical-AND + non-critical floor, fail-closed).
2. `AVWitnessReceipt` gains one signed field `intent_hash` (tamper-evidence; mirrors how
   #4258 added via/perceptual_digest).
3. Tests: schema/parse/anti-vacuity/evaluator (new file) + receipt intent_hash round-trip +
   tamper + backward-compat; a drift-pin tying the vendored region allowlist to the witness.

**Out of scope (PR 4/N+):** witness realized-vector computation from frames; gate wiring
(overall PASS = floors AND intent_pass); the production baseline for anti-vacuity; the
`require_intent` switch; `golden_ref` (added when its semantics are pinned + a producer
fills it); per-region white_fraction / CIEDE2000 / SSIM; the differential VLM judge; the
shadow off-air rig.

## Success Criteria

1. `uv run pytest tests/shared/test_avsdlc_visual_intent.py tests/shared/test_avsdlc_receipt_provenance.py` green.
2. `ruff check` clean.
3. Tampering the signed `intent_hash` no longer verifies.
4. `intent_pass` is fail-closed (empty/unresolvable → False); critical-AND + floor correct;
   the synthetic-white-blob adversarial case fails.
5. `anti_vacuity_check` rejects all-true-on-baseline + no-resolvable; the region allowlist
   drift-pin matches the witness constants; no existing receipt/gate test regresses.
