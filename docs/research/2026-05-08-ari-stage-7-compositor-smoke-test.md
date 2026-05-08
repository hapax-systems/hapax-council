# ARI Stage 7 — Full Compositor Smoke Test

Captured 2026-05-08T07:33Z. 22 active ward sources, zero skips, unified reactivity bus live with `mixer` source active.

## Frame Analysis

Camera tiles (5 feeds) occupy upper-left ~40% of the 1280×720 frame. Remaining ~60% is dark. Red/warm Gruvbox-hard-dark color grading applied. No visible Sierpinski triangle, no visible ward overlays, no visible governance text despite 22 sources actively rendering on background threads.

## L-Principle Evaluation

### PASS

| # | Principle | Evidence |
|---|-----------|----------|
| L2 | Negative Space | ~60% dark space is deliberate, active compositional element |
| L4 | Common Fate | Structural: tests verify r > 0.95 between raw/smoothed energy (PR #2887). Audio bus live. |
| L8 | Anti-Spectator-Buyer | 5 camera angles, no hero shot. Operator is one tile among many. |
| L19 | Synchresis | Structural: α=1.0 passthrough, <1 frame latency. Tests verify r > 0.3 threshold. |
| L22 | Voice Temporal Linearization | Director reads audio state for density decisions (commit 7b9392d). |
| L25 | Multistability | Dark composition admits multiple stable interpretations. |

### PARTIAL

| # | Principle | Status | Gap |
|---|-----------|--------|-----|
| L1 | Force-Field | Layout uses asymmetric balance | Force field heavily weighted to upper-left corner. Camera cluster creates single attractor, not a field. |
| L5 | Pragnanz Range | Current frame is in "leveling" | No evidence of oscillation toward "sharpening" — static low complexity. |
| L10 | Iconostasis | Shader color grading creates threshold | Scrim effect is subtle — removes more than it adds. Needs stronger computational transformation. |
| L12 | Vertical Being | Z-plane constants exist in code | Not perceptible in 2D output. Need visual depth cues. |
| L14 | Material Imagination | Red processing is recognizably computational | Too subtle. Shader chain should produce more obviously non-photographic output. |
| L17 | Form/Material Collision | Color grade contradicts raw camera material | Contradiction is weak. Form and material currently agree (both warm/dark). |

### FAIL

| # | Principle | Failure |
|---|-----------|---------|
| L3 | Figure-Ground | **Cameras are figure, not ground.** Algorithmic content (Sierpinski, wards) should dominate visually, but cameras are the only visible content. Inverted. |
| L7 | Visible Governance | **No governance axioms visible.** 22 wards render but produce no visible output in the frame. |
| L9 | Legible Power | **No power structure indicators visible.** Broadcast governance is hidden. |
| L11 | Sierpinski as Reverse Perspective | **Sierpinski not visible.** Source renders (avg 524ms) but output not reaching the composite frame. This is the gravitational center — its absence is the primary deficiency. |
| L21 | Governance De-Acousmatization | **Rules not visible.** No operational limits rendered on the broadcast surface. |

### NOT VERIFIABLE (static frame)

| # | Principle | Reason |
|---|-----------|--------|
| L4 | Common Fate (temporal) | Requires multi-frame observation |
| L5 | Pragnanz oscillation | Requires time-series observation |
| L19 | Synchresis (live) | Requires audio playback |
| L22 | Voice response (live) | Requires TTS activity |

### NOT FOUND IN CODEBASE (of 25)

L6, L13, L15, L16, L18, L20, L23, L24 — referenced in task but not documented in any ARI task file. May exist in the theoretical-corpus document outside the repo.

## Root Cause: Wards Rendering But Not Visible

The degraded.json shows 22 sources actively rendering (Sierpinski avg 524ms, gem avg 276ms, token_pole avg 394ms). Yet the composite frame shows only cameras. The `post_fx` assignment blitting layer runs after shaders but the ward surfaces appear to render to locations outside the visible camera tile region or at insufficient opacity/contrast against the dark background.

**Hypothesis:** The ward surfaces are positioned and sized correctly per the layout, but the `pip_draw_from_layout()` compositing step paints them into the dark area where they blend invisibly with the black background (Gruvbox #282828 wards on #1d2021 background).

## Priority Gaps for Next Iteration

1. **Sierpinski visibility** (L11) — highest priority. The gravitational center must be visible.
2. **Ward contrast** (L3, L7, L9, L21) — wards render but don't appear. Need contrast/brightness floor or background panel.
3. **Shader intensity** (L10, L14, L17) — scrim/shader processing needs to be more aggressive to create clear figure-ground separation.
4. **Force-field balance** (L1) — camera cluster is too compact. Distribute visual weight.

## Evidence

- Frame: `/dev/shm/hapax-compositor/frame_for_llm.jpg` (captured to PR)
- Audio: `compositor-inspect-audio` shows unified reactivity bus live, mixer source active
- Health: 22/22 sources rendering, 0 skips, 0 degraded
- Tests: 10 correlation tests pass (PR #2887), 8 tightness tests pass
