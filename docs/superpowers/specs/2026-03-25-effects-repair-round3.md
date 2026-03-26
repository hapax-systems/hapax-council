# Effects System Repair Round 3 — Design Specification

**Date**: 2026-03-25
**Scope**: Additive saturation fix, Trap visibility, GPU shader parameter tuning

---

## 1. Problem Statement

Round 2 smoke test confirmed systemic fixes (drift, trail categories, scanlines) working. Three remaining issues:

1. **Additive saturation** — Ghost and Trails saturate to white in static areas. The `lighter` blend equilibrium math is broken: `mainAlpha` is 3.5-4.7x higher than `6 × fadeAlpha`. New frame additions vastly outpace fade.
2. **Trap too dark** — multiply blend with 4 trails at brightness(0.4) + vignette(0.55) crushes everything to near-black.
3. **GPU shader effects too subtle** — Pixsort thresholds too wide (84% of pixels qualify → subtle). Slit-scan displacement too small (2.4% max) + desaturated (saturate 0.8 kills chromatic shift).

---

## 2. Fix 1: Rebalance Additive Trail Equilibrium

**Root cause**: The `mainAlpha` formula yields ~0.104 per new JPEG arrival. Fade runs at ~0.0049 per rAF tick, but new JPEGs only arrive every ~6 ticks. Net energy per cycle: `0.104 - (6 × 0.0049) = 0.104 - 0.029 = +0.075`. Each cycle adds +0.075 net brightness. Static areas saturate to white in ~13 cycles (~1.3 seconds).

**Fix**: Reduce `mainAlpha` for `lighter` blend so that equilibrium is reached before clipping.

Target equilibrium: `mainAlpha ≈ 6 × fadeAlpha` (net zero energy change when content is static).

For Ghost: `6 × 0.00487 = 0.029`. So `mainAlpha` should be ~0.03, not 0.104.

Current formula: `mainAlpha = 0.08 + (opacity × 0.12) / sqrt(count)`

New formula: `mainAlpha = 0.02 + (opacity × 0.04) / sqrt(count)`

This yields:
- Ghost: `0.02 + (0.45 × 0.04) / 2.236 = 0.02 + 0.008 = 0.028` ← equilibrium with fade
- Trails: `0.02 + (0.75 × 0.04) / 3.464 = 0.02 + 0.0087 = 0.029` ← equilibrium with fade

The effect: each new frame adds a subtle contribution that exactly balances the fade rate. Moving objects create visible trails because their old position fades while their new position appears. Static areas reach equilibrium and stop brightening.

**File**: `CompositeCanvas.tsx` — change `mainAlpha` formula for `lighter` in `computeTrailAlphas`.

---

## 3. Fix 2: Trap Visibility

**Root cause**: Multiply blend with 4 trails at trail brightness(0.4) compounds darkening aggressively. Each multiply pass reduces brightness by `1 - (1 - brightness_factor × opacity)` compounding.

**Fix**: Two changes:
1. Reduce trail count from 4 to 2 (fewer multiply passes = less darkening)
2. Increase trail filter brightness from 0.4 to 0.6 (less aggressive per-pass darkening)

This keeps the "dominant black with tunneled view" character but lets the subject remain visible.

**File**: `compositePresets.ts` — Trap preset: `trail.count: 4 → 2`, `trail.filter` brightness `0.4 → 0.6`.

---

## 4. Fix 3: GPU Shader Parameter Tuning

### Pixsort — narrow the threshold window

Current: `threshold_low: 0.08, threshold_high: 0.92` — 84% of pixels qualify for sorting. The effect is too uniform.

New: `threshold_low: 0.25, threshold_high: 0.75` — 50% window. Dark shadows and bright highlights stay untouched, creating the characteristic alternating bands of sorted chaos and pristine image.

Also remove the frontend sepia tint (`sepia(0.15)` in colorFilter) which warms/muddies the sorted output.

**Files**: `studio_effects.py` — pixsort_params thresholds. `compositePresets.ts` — Pixsort colorFilter remove sepia.

### Slit-scan — increase displacement and saturation

Current: `warp_amount: 0.6` → max 2.4% displacement. `saturate(0.8)` in frontend kills chromatic shift.

New: `warp_amount: 1.5` → max 6% displacement (visually dramatic). Frontend `saturate(0.8) → saturate(1.2)` to amplify RGB chromatic separation.

**Files**: `studio_effects.py` — slitscan_params warp_amount. `compositePresets.ts` — Slit-scan colorFilter saturate.

---

## 5. Summary of Changes

| File | Changes |
|------|---------|
| `CompositeCanvas.tsx` | `mainAlpha` lighter formula: `0.02 + (opacity * 0.04) / sqrt(count)` |
| `compositePresets.ts` | Trap: trail count 4→2, trail brightness 0.4→0.6. Pixsort: remove sepia(0.15). Slit-scan: saturate 0.8→1.2 |
| `studio_effects.py` | Pixsort: threshold_low 0.08→0.25, threshold_high 0.92→0.75. Slit-scan: warp_amount 0.6→1.5 |
