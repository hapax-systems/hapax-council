---
case_id: CASE-AVSDLC-INTENT-GATE-20260622
version: 0
stage: S5_AUTHORIZATION_PACKET
status: implementation_authorized
created_utc: 2026-06-22T03:30:00Z
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
axiom_compliance_result: "All 5 axioms satisfied. The conjunct is staged behind require_intent (default OFF) so it never blocks a live AV merge until the operator cuts it over; it adds no auth/roles surface."
consent_contract_required: false
source_mutation_scope: "shared/governance/coord_capabilities.py, shared/release_gate.py, shared/avsdlc_witness.py, scripts/vulture_whitelist.py, tests/hooks/test_avsdlc_intent_conjunct.py, tests/shared/test_avsdlc_witness.py, evidence/CASE-AVSDLC-INTENT-GATE-20260622.md"
implementation_scope: "AVSDLC visual-eval PR 4b (the gate conjunct, where intent GATES). The universal release gate gains a staged require_intent switch (default OFF, env HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE): when ON, a visual/aesthetic/audiovisual change (or any task declaring avsdlc_intent_record) must have its pre-authored VisualIntentRecord CONFIRMED by the independent witness's signed AVWitnessReceipt — the receipt's signed intent_hash must equal intent_hash_from_record(declared) (swap-resistant) AND its signed intent_pass must be True (the realized vector satisfied the prediction), AND the receipt must bind the declared deployed bytes (avsdlc_intent_receipt_unbound blocks an unbound/portable verdict). AVWitnessReceipt gains the signed intent_pass field; shared.avsdlc_witness gains the pure producer helper intent_fields_from_record_and_frame. Governance-sensitive (touches shared/governance/ + the universal gate); armed via the AVSDLC standing delegation after independent review quorum-accept."
parent_spec: "~/Documents/Personal/30-areas/hapax/cns-visual-evaluation-requirements-2026-06-21.md"
---

# CASE-AVSDLC-INTENT-GATE-20260622

## Purpose

The intent mechanism (#4263) + the realized vector (#4264) are the two halves of
predict-then-confirm. This case wires them together into the release gate: under
`require_intent`, overall AVSDLC PASS becomes `floors_pass AND intent_pass AND
obs_moving`. A visual claim now mechanically CORRESPONDS to a prediction made
BEFORE the outcome, compared by an INDEPENDENT witness over the EXACT deployed
bytes — the author stops scoring their own work. This is the capstone of the
1/N→4a series.

## Risk Assessment

T1_LOW but GOVERNANCE-SENSITIVE (touches `shared/governance/coord_capabilities.py`
+ the universal `shared/release_gate.py`). Mitigations:
- **Staged**: `require_intent` defaults OFF (env-gated) → zero behavior change
  for any merge until the operator cuts it over; never wedges live AV air.
- **Additive receipt field**: `intent_pass` defaults False; old receipts parse
  unchanged. (Note: a receipt's HMAC covers the larger signing payload, so a
  receipt signed by pre-3/N code will not verify — moot in practice, the 30-min
  receipt TTL self-heals; receipts are live signals, not durable.)
- **Fail-closed**: every conjunct branch blocks (missing record / unparseable /
  unbound receipt / hash mismatch / not confirmed); two adversarial reviewers
  (forgery/bypass + fail-open/correctness lenses) found no CRITICAL/HIGH path.
- **Byte-bound**: the intent confirmation requires a declared content hash so a
  verdict minted for one change cannot confirm another within the TTL.

The single_user residual (coord signing key 0600-readable by the authoring uid)
is the acknowledged, accepted boundary — the defense is witness INDEPENDENCE
(a separate process computes the realized verdict), not cryptographic secrecy.

## Plan (S2) — PR 4b

- `shared/governance/coord_capabilities.py`: `AVWitnessReceipt.intent_pass: bool`
  folded into `_signing_payload` + `mint_av_witness_receipt` + `parse_av_receipt`.
- `shared/release_gate.py`: `require_intent` switch (env
  `HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE`); `_intent_conjunct_blockers` (record
  presence/parse → byte-binding → verified receipt → hash equality → intent_pass);
  `_verified_runtime_receipt` single-source-of-truth helper.
- `shared/avsdlc_witness.py`: `intent_fields_from_record_and_frame(record, frame,
  pov)` → `(intent_hash, intent_pass)` (lazy numpy; never raises on bad frame);
  `build_receipt_from_witness`/`emit_receipt` pass intent fields through.
- `scripts/vulture_whitelist.py`: the producer helper ships ahead of the live
  `screwm-cns-witness --intent-record` wiring (a tight follow-up slice).
- Tests: 12 new (receipt intent_pass round-trip/default/tamper; conjunct OFF-inert
  / missing-record / unparseable / hash-mismatch / not-confirmed / confirmed /
  non-visual-exempt / unbound; producer satisfying/contradicting/unparseable/
  bad-frame). Full 278-test regression across the universal gate + all AVSDLC
  suites green.

**Out of scope (next slices):** the live `screwm-cns-witness --intent-record`
producer wiring (compute from /dev/video52 frames + emit into the receipt);
`golden_ref` + production anti-vacuity baseline (golden-frame infra); the strict
cutover (operator flips `require_intent`); CIEDE2000/SSIM.

## Success Criteria

`uv run pytest` green across the universal gate + all AVSDLC suites (278 passed);
`ruff` + `pyright` clean; adversarial review (2 lenses) clean of CRITICAL/HIGH;
`require_intent` default OFF preserves exact pre-PR gate behavior.
