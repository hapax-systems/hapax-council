---
case_id: CASE-AVSDLC-REALIZED-VECTOR-20260622
version: 0
stage: S5_AUTHORIZATION_PACKET
status: implementation_authorized
created_utc: 2026-06-22T05:00:00Z
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
axiom_compliance_result: "All 5 axioms satisfied. Pure computation, no auth/roles, no governance surface, no live-restart gate."
consent_contract_required: false
source_mutation_scope: "shared/avsdlc_realized_vector.py, scripts/vulture_whitelist.py, tests/shared/test_avsdlc_realized_vector.py, evidence/CASE-AVSDLC-REALIZED-VECTOR-20260622.md"
implementation_scope: "AVSDLC visual-eval PR 4a: the REALIZED per-region perceptual vector. A pure numpy function computing {luma, edge_energy} per vendored AESTHETIC region ROI from a captured frame — the input shape that shared.avsdlc_visual_intent.intent_pass consumes. No receipt/gate change (not governance-sensitive); the witness producer wiring + the gate conjunct (overall PASS = floors AND intent_pass) are subsequent slices."
parent_spec: "~/Documents/Personal/30-areas/hapax/cns-visual-evaluation-requirements-2026-06-21.md"
---

# CASE-AVSDLC-REALIZED-VECTOR-20260622

## Purpose

The intent mechanism (#4263) evaluates a pre-authored VisualIntentRecord against a
REALIZED per-region vector. This case authorizes producing that vector — the bridge
from "what the agent predicted" to "what actually rendered" — as a pure, tested
function, ahead of its witness producer + gate consumer.

## Risk Assessment

T1_LOW — pure numpy computation, no governance surface, no gate, no live-restart
boundary, fully test-covered with synthetic frames. The region ROIs are vendored
from the witness AESTHETIC_REGIONS with a drift pin.

## Plan (S2) — PR 4a

NEW `shared/avsdlc_realized_vector.py`: `PHASE1_REGION_ROIS` (vendored, pinned) +
`realized_vector_from_frame(frame, pov_label)` computing `{luma, edge_energy}` per
region ROI (Rec.601 luma; edge_energy = mean gradient magnitude). Tests: synthetic
white/black/edge frames, ROI isolation, RGB luma, the end-to-end synthetic white-blob
→ `intent_pass` False, and the ROI drift pin.

**Out of scope (next slices):** witness wiring (compute from live /dev/video52 frames
+ emit into the manifest/receipt); the gate conjunct (overall PASS = floors AND
intent_pass); CIEDE2000/SSIM; the staged require_intent switch; golden_ref.

## Success Criteria

`uv run pytest tests/shared/test_avsdlc_realized_vector.py` green; `ruff` clean; the
white-blob synthetic frame drives `intent_pass` False through a `luma<=10` critical
predicate; the ROI drift pin matches the witness constants.
