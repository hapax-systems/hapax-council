# Compositor Temporal GLSL Slitscan/Stutter Live Evidence

**Date:** 2026-05-20T16:50Z
**Authority:** REQ-20260518225227-compositor-incident-recovery-ledger
**Witness:** delta session
**Verdict:** Constraint mechanism cannot isolate slitscan/stutter from anchored nodes; stutter observed in pipeline, slitscan not recruited

## 1. Targeted Audit Execution

**Command:**
```
scripts/live-effect-permutation-audit.py \
  --ad-hoc-label slitscan-stutter-temporal \
  --ad-hoc-effects slitscan,stutter,breathing,drift,bloom \
  --duration 30 --confirm-live-service-control
```

**Result:** `RuntimeError: plan did not constrain to slitscan-stutter-temporal`

The drift engine's constraint mechanism failed to limit the active pipeline to only the allowed set. Anchored nodes (fluid_sim, noise_overlay, feedback_bookend, postprocess_bookend, thermal, threshold, etc.) override the constraint and persist across set changes.

## 2. Effect Presence Evidence

| Effect | Observed in Pipeline | Notes |
|--------|---------------------|-------|
| stutter | Yes (slot3_3_stutter) | Present in both audit attempts |
| slitscan | No | Listed as "allowed" but drift engine did not recruit it |
| fb (feedback bookend) | Yes | Anchor, always present |
| post (postprocess bookend) | Yes | Anchor, always present |

## 3. Constraint Failure Analysis

Two consecutive audit attempts showed the same pattern:
- **Allowed set:** bloom, breathing, drift, fb, post, slitscan, stutter
- **Actual pipeline:** 22 nodes including 7 anchored nodes not in the allowed set
- **Root cause:** The drift engine's anchor mechanism preserves nodes across constraint changes, preventing clean isolation of target effects

This means slitscan and stutter **cannot be evaluated in isolation** with the current constraint tooling. Admitting them into live recruitment requires either:
1. An anchor-aware constraint mechanism that can suppress anchors during audit
2. Direct shader-level testing outside the drift engine
3. Operator manual observation during an unconstrained drift window

## 4. Fourth-Wall / Freeze Evidence

During the audit window (approximately 70s of runtime):
- The output did NOT freeze — cameras continued rendering
- No fourth-wall pane overlay was observed
- `stutter` appeared in pipeline slots but the overall compositor remained responsive
- Effect drift state showed 0 gap entries before and after

## 5. Post-Audit Surface Preflight

```json
{
  "state": "healthy",
  "service_active": true,
  "restored": true,
  "full_surface_failures": [],
  "reasons": []
}
```

All cameras active (6 RGB + 3 IR), frame ages <0.2s, no containment flags, no full-surface failures.

## 6. Residual Risks

| Risk | Severity | Follow-Up |
|------|----------|-----------|
| slitscan not observed in pipeline — no positive evidence | High | Requires dedicated slitscan-only test or operator observation |
| Constraint mechanism cannot isolate target effects | Medium | `compositor-audio-reactive-temporal-candidate-source-bound-repair` |
| stutter observed but not in clean isolation | Medium | Evidence is partial — stutter coexisted with 20+ other effects |

## 7. Recommendation

**Do not admit slitscan into live recruitment** without positive evidence of non-freeze behavior. Stutter has partial positive evidence (observed in pipeline without freeze) but needs clean isolation before full admission.
