---
case_id: CASE-AVSDLC-VISUAL-EVAL-20260621
version: 0
stage: S5_AUTHORIZATION_PACKET
status: implementation_authorized
created_utc: 2026-06-22T02:35:00Z
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
axiom_compliance_result: "All 5 axioms satisfied. No auth/roles; reuses the operator coord key; errors include next actions; no employer data; no persistent non-operator state; LLMs prepare/humans deliver (release arm stays operator-gated for the governance-sensitive path)."
consent_contract_required: false
source_mutation_scope: "shared/governance/coord_capabilities.py, shared/release_gate.py, shared/avsdlc_witness.py, scripts/screwm-cns-witness.py, tests/hooks/test_avsdlc_enforcement.py, tests/shared/test_avsdlc_witness.py, evidence/CASE-AVSDLC-VISUAL-EVAL-20260621.md"
implementation_scope: "AVSDLC visual-evaluation extension (thin PR 2/N). Stop discarding the per-region perceptual evidence at the receipt boundary: the AVWitnessReceipt signs the capture `via` channel (so a non-OBS capture can be rejected) and binds a deterministic perceptual digest over the witness's per-region/per-artifact stats. Sets up the predict-then-confirm intent-as-predicate slice (PR 3/N)."
parent_spec: "~/Documents/Personal/30-areas/hapax/cns-visual-evaluation-requirements-2026-06-21.md"
---

# CASE-AVSDLC-VISUAL-EVAL-20260621

## Purpose

The Tier-C receipt landed in #4254 signs only **liveness** (`status` + `obs_moving` +
`content_hash`). The per-region perceptual machinery exists in the witnesses but is
**discarded at the receipt boundary** — so a scene that *moves* on air but renders the
*wrong thing* still passes, and the capture instrument is unverified. This case authorizes
the first extension that closes the accuracy/provenance leg: bind the capture channel and
the perceptual evidence into the signed receipt, en route to intent-legibility.

## Governing Principles

- interpersonal_transparency (88): a receipt that *carries* the perceptual evidence + the
  instrument that produced it makes a visual claim checkable instead of self-asserted.
- executive_function (95): errors name next actions.
- no_expert_system_rules: binds to perceived per-region stats, not hardcoded verdicts.
- management_governance (85): release arm stays operator-gated (governance-sensitive path).

## Risk Assessment

T1_LOW — additive, reversible, fully test-covered, backward-compatible. New receipt fields
(`via`, `perceptual_digest`) are optional with defaults; the `via`-enforcement is staged
behind `require_via` (default off) exactly like `require_signed_witness`. No fail-closed
gate at the live restart. `shared/governance/coord_capabilities.py` is governance-sensitive
→ frontier-review floor + operator release-arm at merge.

## Research Evidence (S1 Complete)

Workflow `wf_292da963` (throttled, 40 agents) produced the cited requirements report
(`parent_spec`). It read the #4254 receipt code and identified the dominant gaps: the
receipt collapses the manifest to two values and carries no intent/perceptual payload; the
capture `via` is emitted by the witness but never signed or verified.

## Plan (S2) — this thin PR (2/N): near-term path #1–2

1. `AVWitnessReceipt` gains signed `via` + `perceptual_digest` fields (optional, defaulted);
   `verify_av_witness_receipt` gains a staged `require_via` that rejects a non-OBS capture.
2. `avsdlc_witness` derives `via` + a deterministic `perceptual_digest` from the witness
   manifest and binds them into the minted receipt; `screwm-cns-witness` records the real
   capture channel in the manifest.
3. Tests: digest is deterministic + content-sensitive; tampering `via`/`perceptual_digest`
   fails verification; `require_via` rejects non-OBS; `emit_receipt` binds both.

**Out of scope (PR 3/N+, per parent_spec):** intent-as-predicate + hash-binding (the
predict-then-confirm core), full re-derivation of region stats from retained PNGs, CIEDE2000/
SSIM (validated), golden-frame infra, the shadow off-air control rig, the differential VLM
judge. Routing `visual`/`aesthetic` off `_has_any_field` follows once the predicate gate exists.

## Success Criteria

1. `uv run pytest tests/hooks/test_avsdlc_enforcement.py tests/shared/test_avsdlc_witness.py` green.
2. `ruff check` clean.
3. Tampering the signed `via` or `perceptual_digest` no longer verifies.
4. `require_via=True` blocks a non-OBS capture; the perceptual digest is deterministic and
   changes when the per-region stats change.
5. No existing receipt/gate/precheck test regresses (backward-compatible; staged switch off).
