---
date: 2026-05-03
status: design — spec only; implementation a separate downstream cc-task
amends:
  - docs/superpowers/specs/2026-03-29-reverie-bachelard-design.md
  - docs/research/2026-05-03-bachelard-amendment-7-design.md
  - docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md
  - docs/research/2026-05-03-bachelard-amendment-9-drawers-design.md
  - docs/research/2026-05-03-bachelard-amendment-10-nests-shells-design.md
related_tasks:
  - "cc-task bachelard-amendment-11-vertical-house-design"
---

# Bachelard Amendment 11 — Phenomenology of Vertical House (Cellar / Garret / Hut)

## Decision

**Amendment 11 is the Phenomenology of Vertical House** (*La poétique de l'espace*, ch. I "The House. From Cellar to Garret. The Significance of the Hut"). Goes beyond the Jr-packet 4-chapter coverage to introduce a **genuinely-novel axis** that none of A1-A10 touch: **verticality**.

Bachelard's vertical phenomenology of the house:
- **Cellar** — depth, unconscious, root, roundness-without-light. The unrationalized substrate.
- **Garret** — height, rational clarity, dream-air, the place of intellectual reverie.
- **Hut** — the grounded center, neither high nor low, the elemental refuge.

A1-A10 are spatial-horizontal (Roundness centroid, Miniature scale, Drawers events, Nests-Shells perimeter), scale (A8), temporal (A9). **None operate along the vertical axis.** A11 fills this gap — the dwelling has up and down, and visual phenomenology should honor that.

Amendment 11 candidates considered:
| Chapter | Phenomenology | Selection notes |
|---------|---------------|-----------------|
| **I — House from Cellar to Garret** | **Vertical axis** | **Selected.** Genuinely-novel axis; bigger phenomenological territory than the others. |
| II — House and Universe | House as cosmos | Defer to A12. Heavily semantic; harder to map to visual modulation. |
| VIII — Intimate Immensity | Inward-immensity (NOT outward like A5) | Defer to A12. Closely paired with existing #5 + A7; risks redundancy. |
| IX — Outside-Inside Dialectics | Boundary phenomenology | Defer; partially covered by A10 nest perimeter. |

Vertical House wins on novelty + clean implementation surface (UV.y axis is unused by A1-A10).

## 1. Concept summary

Bachelard's vertical house is not a literal multi-story building. It is the phenomenology of **the dwelling's vertical poles** — the cellar's depth-of-substrate (where forgotten things wait), the garret's height-of-clarity (where rational reverie happens), the hut's groundedness (the elemental refuge). *"The verticality of the house is provided by the polarity of the cellar and the attic."* (ch. I §3).

For Hapax Reverie, vertical house is the visual register of **vertical polarity in the visual field**:

- **Bottom of frame (cellar register)**: substrate-richer, denser noise texture, slower temporal modulation, lower-saturation. Reads as ground / earth / unconscious depth.
- **Top of frame (garret register)**: airier, lower amplitude noise, faster temporal modulation, higher saturation, more chromatic clarity. Reads as sky / air / rational clarity.
- **Middle band (hut register)**: balanced, the canonical default — the grounded center where most content lives by default.

Operator's eye reads the vertical axis intuitively (we read top-to-bottom in Western orientation; bottom-heavy implies weight, top-heavy implies levity). A11 makes the visual field LIVE this polarity rather than treating UV.y as homogeneous.

## 2. Relation to Amendments 1-10

- **#1 Materialization** — content crystallizes from procedural noise. A11 modulates the **noise field's CHARACTER along UV.y** (denser at bottom, lighter at top). Materialization still happens everywhere; the substrate it crystallizes from is now vertically-polar.
- **#2 Dwelling/Trace** — content traces. A11 biases trace persistence by vertical position: bottom traces last longer (cellar-as-memory); top traces fade faster (garret-as-fleeting-thought).
- **#3 Material Quality** — material_id. A11 pairs:
  * **earth** with cellar register (bottom) — substantial holding
  * **air** with garret register (top) — lightness
  * **water** sits well anywhere
  * **fire** + **void** orthogonal to vertical
- **#4 Reverberation** — feedback. A11 biases feedback decay by vertical position: bottom decays slower (cellar-resonance); top decays faster.
- **#5 Immensity** — outward. A11 amplifies immensity at TOP of frame (garret-immensity = sky-immensity); damps at BOTTOM (cellar is enclosed).
- **#6 Soft Escalation** — pacing. A11 transitions between vertical register modes follow soft-escalation.
- **#7 Roundness** — inward-self / centered. Compatible. The roundness centroid sits at the HUT register (vertical middle). A11 makes that "centered" location MEAN something — the hut is the canonical center.
- **#8 Miniature** — inward-detail. Compatible. Detail at bottom of frame reads as cellar-substrate-detail (richer, denser); at top reads as garret-clarity-detail (sharper, sparser).
- **#9 Drawers** — disclosure. Compatible. A drawer opening in the GARRET region reads as "intellectual revelation"; in the CELLAR region reads as "uncovering forgotten substrate"; in the HUT region (default) reads as "everyday revealing." The vertical position of disclosure carries phenomenological weight.
- **#10 Nests-Shells** — perimeter. Compatible. The nest sits at the HUT register by default (grounded refuge). When nest is active AND A11 fires, the nest's elliptical perimeter is offset slightly downward (the nest belongs to the hut/cellar registers, not the garret).

A11 composes with everything; introduces a new spatial dimension (vertical polarity) that the others don't touch.

## 3. 9-dim parameter envelope (vertical-position-dependent)

A11 differs from A1-A10 in that its modulation is **per-fragment** rather than uniform across the field. The visual_chain doesn't apply a global per-tick multiplier; instead, the WGSL shaders compute a vertical-position-dependent multiplier per pixel.

The vertical_factor at UV.y is: `vertical_factor = (uv.y - 0.5) * 2.0` (range -1.0 at bottom to +1.0 at top, 0 at middle).

Per-dim per-fragment modulation (applied in WGSL when A11 is active):

| Dim | Bottom (vertical_factor=-1) | Middle (=0) | Top (=+1) |
|-----|------------------------------|--------------|-----------|
| **noise.amplitude** | × 1.30 (denser substrate) | × 1.0 | × 0.70 (airier) |
| **noise.frequency** | × 1.20 (richer texture) | × 1.0 | × 0.85 (sparser) |
| **temporal_distortion** | × 0.70 (slower time) | × 1.0 | × 1.30 (faster) |
| **spectral_color** | × 0.80 (lower saturation) | × 1.0 | × 1.20 (higher) |
| **diffusion** | × 1.10 | × 1.0 | × 0.90 |
| **trace_decay_rate** | × 0.70 (cellar memory persists) | × 1.0 | × 1.30 (garret thoughts fleeting) |
| **immensity_factor** | × 0.70 (cellar enclosed) | × 1.0 | × 1.30 (garret-sky) |
| **intensity** | × 1.0 (orthogonal) | × 1.0 | × 1.0 |
| **coherence** | × 1.0 (orthogonal) | × 1.0 | × 1.0 |

The middle row (vertical_factor=0) matches the existing baseline — A11 fully active = no modulation at the centerline. This means existing presets that center their content stay byte-identical at their working location.

A11 as a whole is gated by a single `u_vertical_house_factor` (0..1). When 0, the per-dim modulation is identity. When 1, full vertical polarity applies.

## 4. Shader topology

Two changes:

1. **Per-fragment modulation in core WGSL nodes** — the relevant per-fragment-modulating shaders (noise.wgsl, drift.wgsl, breath.wgsl, color.wgsl, feedback.wgsl) need access to `uv.y` and `u_vertical_house_factor`. These shaders ALREADY get UV (per the existing fragment pipeline); the new uniform is added to the Params struct of each affected node.
2. **Visual_chain layer** — `_apply_vertical_house_factor(uniforms, factor)` writes `u_vertical_house_factor` per node that consumes it.

The per-fragment modulation is implemented as a small WGSL helper `vertical_modulate(value, uv_y, vertical_factor, slope)`:

```wgsl
// Pseudo-WGSL — modulate a value by vertical position
fn vertical_modulate(value: f32, uv_y: f32, vertical_factor: f32, slope: f32) -> f32 {
    // vertical_factor is the A11 master gate (0..1)
    // slope is the per-dim slope (e.g. +0.30 for noise.amplitude, -0.30 for top-airier)
    // Per-fragment multiplier: 1.0 at uv.y=0.5, falls/rises linearly to ±slope at uv.y=0/1.
    let centered = (uv_y - 0.5) * 2.0;  // -1 at bottom, +1 at top
    let multiplier = 1.0 + (slope * centered * vertical_factor);
    return value * multiplier;
}
```

Each affected shader inserts ONE `vertical_modulate(...)` call on its primary value. ~5 lines per shader.

NOT a new WGSL node — it's a per-fragment modulation extension to existing nodes. The affected nodes' .json specs need a new `vertical_house_slope` Params field (default 0.0 = no modulation, preserves backward compat — pass the u7 audit pin #2387).

The visual_chain layer adds `_apply_vertical_house_factor(uniforms, factor)` — sets `u_vertical_house_factor` on every node that has the slope field.

Composition order in `_uniforms.write_uniforms`:
1. plan_defaults + chain_deltas
2. mode tint
3. roundness bias (A7)
4. miniature bias (A8)
5. nest-shell bias (A10)
6. **vertical-house factor (A11) ← new** (writes single uniform; per-fragment work happens in WGSL)
7. homage damping
8. drawer event pulse (A9, transient)
9. programme override

## 5. Compositor interaction

### Sierpinski overlays

A11 is fully UV-based, so Sierpinski (which is its own geometry) is unaffected. The Sierpinski's vertical placement WITHIN the frame DOES interact with A11's per-fragment modulation — Sierpinski near the top reads with garret-character backdrop, near the bottom with cellar-character. No code change required.

### Token pole

Token pole is a vertical strip on the right edge. It naturally crosses all three registers (cellar/hut/garret). A11's per-fragment modulation will color the pole's background according to vertical position — a feature, not a bug. No code change.

### Reverie content placement

Content placement (Amendment 1) gets a NEW operator-meaningful semantic: vertical placement now communicates phenomenological register. A future content-placement pass could optionally bias placement based on the content's "feeling" (e.g. ground-truth-like content → cellar; abstract/aspirational content → garret). Out-of-scope for A11; namespace it for a downstream cc-task.

## 6. Anti-pattern list

The implementation MUST NOT use any of the following — they defeat the vertical phenomenology:

- **Literal split-screen at the horizon line.** A11 is *gradient*, not *partition*. A hard horizon reads as a graphic-design choice, not a phenomenological gradient.
- **Color-coding the cellar/garret with discrete palette swaps.** The chromatic shift is gradual (the spectral_color slope is small ±0.20). Big palette swaps read as theme-switching.
- **Inverted gradients (top-heavy bottom-light).** Operator's vestibular system reads bottom-heavy as grounded; flipping it makes the frame feel wrong.
- **Per-fragment vertical wobble (animated UV.y).** Vertical polarity is STABLE — animating the UV.y axis breaks the dwelling phenomenology.
- **A "vertical-house" preset.** Modulation regime, not preset.
- **A "vertical-house" affordance.** Composition, not selection.
- **u_vertical_house_factor > 1.0.** Cap at 1.0 in the visual_chain layer; per-dim slopes are calibrated for the [0, 1] range.

## 7. Coordination with A7 + A8 + A9 + A10

**All five compose** — A11 is the FIFTH orthogonal axis. The complete set:

| Axis | Amendment | Operates on |
|------|-----------|-------------|
| Spatial-inward (gather) | A7 Roundness | Drift / breath / hue-rotate-sign-flip |
| Scale-detail (amplify) | A8 Miniature | Noise frequency / contrast / spectral color |
| Perimeter (hold) | A10 Nests-Shells | Spatial nest_mask + per-dim damping |
| Temporal-revelation (event) | A9 Drawers | Transient pulse on disclosure |
| **Vertical polarity (dwell)** | **A11 Vertical House** | **Per-fragment UV.y modulation** |

Composition cases (canonical stances) — extending the A10 table:

| Stance | A7 | A8 | A9 | A10 | A11 | Visual register |
|--------|----|----|----|-----|-----|-----------------|
| Centered work, default vertical | ✓ | ✓ |   |   |   | A7+A8 canonical (existing) |
| Sheltered focused work | ✓ | ✓ |   | ✓ |   | A7+A8+A10 maximum-shelter (existing) |
| Sheltered focused work, vertically-polar | ✓ | ✓ |   | ✓ | ✓ | All five — fully-dimensional dwelling |
| Garret-revelation (drawer in upper region) |   |   | ✓ |   | ✓ | "Intellectual epiphany" register |
| Cellar-revelation (drawer in lower region) |   |   | ✓ |   | ✓ | "Uncovering forgotten substrate" register |
| Sheltered work + cellar-revelation |   |   | ✓ | ✓ | ✓ | "Operator inspects substrate from refuge" |

Per the A11 gating logic, vertical_factor is sourced from operator stance + whether content is currently bottom-or-top weighted. Default is 0.5 (mild polarity; never fully off) so the visual surface always carries SOME vertical character — the dwelling is always vertical even at rest.

## 8. Implementation footprint (downstream cc-task scope)

Spec only — implementation is `bachelard-amendment-11-vertical-house-impl`. Estimated:

- `agents/reverie/_uniforms.py` — `_apply_vertical_house_factor(uniforms, factor)` helper. ~30 lines.
- `agents/visual_chain.py` — `compute_vertical_house_factor()` reading default 0.5 + stance-based modulators. ~30 lines.
- `agents/shaders/nodes/<shader>.wgsl` — add `vertical_modulate()` helper + insert one call in each of: noise.wgsl, drift.wgsl, breath.wgsl, color.wgsl, feedback.wgsl, content_layer.wgsl. ~60 lines (10 LOC × 6 shaders).
- `agents/shaders/nodes/<shader>.json` — add `vertical_house_slope` Params field to each affected shader (must pass u7 audit #2387). ~30 lines (5 lines × 6 shaders).
- `agents/effect_graph/presets/reverie_vocabulary.json` — bump plan defaults for new params to 0.0. ~10 lines.
- Tests: ~150 lines (factor gating; per-shader Params pin update; compose with A7-A10; stance-based factor computation; default 0.5 baseline).

Total: ~310 LOC across 14 files (most files small edits — 5-10 LOC each). Bigger than A10's ~283 LOC because A11 touches 6 shaders rather than just one (content_layer).

## 9. Validation plan (downstream)

The downstream impl cc-task should pin:

1. `u_vertical_house_factor=0` ↔ baseline behavior byte-identical (vertical_modulate returns value × 1.0).
2. `u_vertical_house_factor=1` AND `vertical_house_slope=+0.30` on noise.amplitude → bottom shows ×1.30 amplitude, top shows ×0.70.
3. UV.y=0.5 ALWAYS produces unmodified value regardless of factor (the centerline is the canonical baseline).
4. u7-per-node-param-signature-quality-audit (#2387) passes after Params updates to all 6 shaders.
5. Composition with A7+A8+A9+A10: all five orthogonal modulators stack without truncation; the canonical-five stances from §7 produce visibly distinct visual registers.
6. Operator-side acceptance: live livestream — verify cellar register (bottom) reads denser/slower; garret (top) reads airier/faster; hut (middle) reads as default.

## 10. Out-of-scope

- Implementation (downstream cc-task `bachelard-amendment-11-vertical-house-impl`).
- Audio-domain analogue of verticality (out-of-scope; visual-only).
- Operator-tunable per-shader slopes (defaults fixed at first ship; tuning is a follow-up if defaults don't sit well).
- Content-feeling-driven vertical placement (separate cc-task; out-of-scope here).
- Amendment 12 (House and Universe / Intimate Immensity / Outside-Inside Dialectics) — deferred. Future amendments require either operator-prioritization or new aesthetic-references research.
