---
case_id: CASE-AVSDLC-CUTOVER-20260623
version: 0
stage: S5_AUTHORIZATION_PACKET
status: implementation_authorized
created_utc: 2026-06-23T00:25:51Z
originator: cc-segprep
methodology: hapax-sdlc
risk_tier: T2_MED
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
axiom_compliance_result: "All 5 axioms satisfied: single_user (operator owns the broadcast); executive_function (cutover sequence is operator-gated at dogfood/flip); management_governance (the gate is the governed release path); interpersonal_transparency (warrant = support-adequate-to-purport, intrinsic); corporate_boundary (AV evidence stays in-band)."
consent_contract_required: false
source_mutation_scope: "shared/release_gate.py, scripts/screwm-cns-witness.py, agents/hapax_daimonion/avsdlc-runtime-witness-daemon.py, scripts/compositor-frame-capture.sh (retire-for-axis-a)"
implementation_scope: "AVSDLC cutover build-phase: gap-#4 receipt→frontmatter attachment-seam writer (folds gaps #3/#6), gap-#5 intent-record authoring, retire compositor-frame-capture.sh for seg-prep axis-A. Dogfood + flag-flip are OPERATOR-GATED (OD-2) and NOT authorized by this packet."
parent_spec: "~/Documents/Personal/30-areas/hapax/avsdlc-enforcement-design-2026-06-21.md"
parent_request: "REQ-20260623002551-avsdlc-cutover"
source_synthesis: "~/HANDOFF-synthesized-purview-2026-06-23.md"
sibling_cases: ["CASE-AVSDLC-VISUAL-EVAL-20260621", "CASE-AVSDLC-VISUAL-INTENT-20260622"]
operator_gated_remainder: ["dogfood-release (OD-2)", "avsdlc-cutover-flip (OD-2)"]
---

# CASE-AVSDLC-CUTOVER-20260623 — S5 authorization packet (build phase)

## What this authorizes
Implementation authority for the **build phase** of the AVSDLC cutover: the gap-#4 receipt→frontmatter
attachment-seam writer (the keystone), folding the daemon pass-through (#3) and witness-daemon-bringup (#6)
questions into the chosen one-shot-producer-invoked-by-the-release-step minting path; the gap-#5 intent-record
example; and retiring `scripts/compositor-frame-capture.sh` as the seg-prep axis-A witness path so the seam is
the sole pipe.

## What this does NOT authorize (operator-gated, OD-2)
- **dogfood-release** — the end-to-end visual release with the flag forced ON ad-hoc (go-live-adjacent empirical moment).
- **avsdlc-cutover-flip** — setting `HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE=on` in the canonical secrets env.

`release_authorized: false` reflects that the cutover flag-flip is operator-gated. The build-phase PRs carry
their own release-arm via the AVSDLC standing-arm delegation once review quorum accepts.

## Risk + guards
- The attachment-seam writer touches the **universal** PR release gate (`evaluate_avsdlc_release_gate`) — shared
  by cc-cns (cutover) and cc-segprep (axis-A releases). Sequence to avoid gate contention with the clean-canary.
- **Do NOT flip the flag before dogfood.** With zero frontmatter producers, flipping wedges every visual release
  including the active seg-prep materializer task.
- Rollback = unset the flag (verified OFF/unset everywhere today).

## Evidence
- Gate conjunct merged (#4271); live intent-record producer merged (#4274); witness drift taps live (#4273);
  env-consistency landed (#4279). All on origin/main `e717e5bb8`.
- ZERO frontmatter writers + ZERO receipt consumers verified by `git grep` (the gap).
