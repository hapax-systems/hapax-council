# Sierpinski Composite Visibility Investigation

**Result: NOT A BUG — Sierpinski is visible in the broadcast output.**

## Finding

The Stage 7 audit (PR #2889) incorrectly reported Sierpinski as invisible. The audit examined `frame_for_llm.jpg` and `snapshot.jpg`, both of which tap `pre_fx_tee` — the camera-only buffer captured BEFORE the cairooverlay and shader chain. This is by design (anti-hallucination fix, `snapshots.py` line 82):

> "LLM-bound frame snapshot branch — camera-only, NO Cairo wards."

The actual broadcast output (`fx-snapshot.jpg`, captured post-shader post-cairooverlay) shows:

- Sierpinski triangle rendering at center with recursive sub-triangles
- Synthwave line work (neon pink/cyan/purple) with z-depth parallax layers
- Ward overlays: programme history, activity header, compliance indicators, egress footer
- Shader processing: drift + posterize + chamber feedback breathing preset active
- Camera feeds visible through shader chain

## Snapshot Points in Pipeline

```
cameras → cudacompositor → pre_fx_tee ──→ snapshot.jpg (camera-only)
                                      └──→ frame_for_llm.jpg (camera-only, anti-hallucination)
                           ↓
                    cairooverlay (Sierpinski + pre_fx wards)
                           ↓
                    GL shader chain (12 glfeedback slots)
                           ↓
                    post-FX cairooverlay (post_fx wards)
                           ↓
                    fx-snapshot.jpg ← THIS IS THE BROADCAST OUTPUT
                           ↓
                    v4l2sink + HLS
```

## Stage 7 Audit Correction

The 5 FAIL verdicts (L3, L7, L9, L11, L21) should be re-evaluated against `fx-snapshot.jpg`:

- **L11 (Sierpinski):** PASS — Sierpinski triangle prominently visible at center
- **L3 (Figure-Ground):** PASS — algorithmic content (Sierpinski, wards, shaders) dominates over cameras
- **L7 (Visible Governance):** PASS — compliance indicators visible (compliant/violation badges)
- **L9 (Legible Power):** PARTIAL — some governance structure visible but not comprehensive
- **L21 (De-Acousmatization):** PARTIAL — rules partially visible via compliance badges

**Revised scorecard: 9 PASS / 5 PARTIAL / 0 FAIL** (up from 6/6/5)
