---
date: 2026-05-03
status: design — spec only; implementation a separate downstream cc-task
amends:
  - docs/superpowers/specs/2026-03-29-reverie-bachelard-design.md
  - docs/research/2026-05-03-bachelard-amendment-7-design.md
  - docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md
  - docs/research/2026-05-03-bachelard-amendment-9-drawers-design.md
related_tasks:
  - "cc-task bachelard-amendment-10-nests-shells-design"
---

# Bachelard Amendment 10 — Phenomenology of Nests/Shells

## Decision

**Amendment 10 combines Nests (ch. IV) + Shells (ch. V)** into a single phenomenological register: **protective enclosure that holds without imprisoning**. Bachelard treats nest and shell as paired figures of refuge — the nest is open-but-cradling, the shell is closed-but-disclosable — and their phenomenology converges on the *image of the protective interior*.

This concludes the original Jr-packet 4-chapter coverage (Roundness, Miniature, Drawers, Nests-Shells). No further amendments planned without a new aesthetic-references packet from operator.

| Why combined | Bachelard treats them as paired figures throughout chapters IV+V; the protective-interior phenomenology is the unifying thread. Splitting into A10 (Nests) + A11 (Shells) would risk hairsplitting beyond useful resolution. |

## 1. Concept summary

Bachelard's nest+shell is the phenomenology of **the protective interior** — *"In a remote past, a remoter past than any in which the dead have lived, the shell, an empty shell, like an abandoned shell, was the sign of a refuge."* (ch. V §1). And on nests: *"The nest, the secret heart of a tree, the secret of the world."* (ch. IV §3).

For Hapax Reverie, nests-shells is the visual register of **gathering-as-protection** without the inward-contraction of A7 Roundness:

| Axis | Roundness (A7) | Nests-Shells (A10) |
|------|----------------|--------------------|
| Direction | Inward / centered | Inward + perimeter-defended |
| Composition | Concentric coherence around centroid | Centroid + soft boundary that holds |
| Operator stance | Settling, focused | Held, sheltered, not-needing-defense |
| Time | Slow contraction | Stable held-state |
| Phenomenology | Self-completing | Self-protected (gentler) |

A10 differs from A7 by adding a **perimeter** — the field doesn't just contract; it acquires a soft holding-edge. Bachelard's nest "is at the same time inhabited and uninhabited" — the soft boundary is felt without being a hard wall.

## 2. Relation to Amendments 1-9

- **#1 Materialization** — content crystallizes from procedural noise. Nests-Shells biases materialization toward the nest's interior region (a soft elliptical area centered on the centroid).
- **#2 Dwelling/Trace** — content leaves traces. Nests-Shells extends trace duration within the nest interior (the nest "remembers" longer than the open field).
- **#3 Material Quality** — material_id. Nests-Shells pairs naturally with **earth** (substantial holding) and **water** (refuge of containment). Resists **fire** (which breaks containment). Soft preference.
- **#4 Reverberation** — feedback echo. Nests-Shells's soft perimeter creates a partial reflection — feedback bounces back from the nest edge with damped intensity.
- **#5 Immensity** — outward expansion. Nests-Shells DAMPS immensity (the field has a perimeter; immense-feel diminishes). Mild damping vs Roundness's stronger inward sign-flip.
- **#6 Soft Escalation** — pacing. Nests-Shells transitions in/out follow soft-escalation (no sudden enclosure pop-ups).
- **#7 Roundness** — inward-self / centered. Compatible. Roundness contracts the field; Nests-Shells adds perimeter. Both can be active. Together: contracted-and-held — strongest "I am safe to focus" signal.
- **#8 Miniature** — inward-detail. Compatible. Detail amplification within the nest interior.
- **#9 Drawers** — disclosure events. Compatible. A drawer opens INSIDE the nest is a particularly intimate disclosure register (the contents are revealed within the protected interior).

A10 composes with everything; it adds a new spatial dimension (perimeter) that the others don't touch.

## 3. 9-dim parameter envelope

Nests-Shells is a **steady-state** modulation (like A7+A8, unlike A9's transient pulse):

| Dim | Nests-Shells multiplier | Why |
|-----|------------------------|-----|
| **intensity** | × 0.95 (gentle damp) | Held-state is calm but present. |
| **tension** | × 0.60 (mild damp) | Sheltered = relaxed but not absent. |
| **depth** | × 0.85 (mild damp) | Field has a perimeter; immensity is bounded. |
| **coherence** | × 1.30 (amplify) | The nest IS coherent — it holds shape. |
| **spectral_color** | × 1.0 | Orthogonal. |
| **temporal_distortion** | × 0.80 (mild damp) | Held-state is temporally stable. |
| **degradation** | × 0.85 (mild damp) | Sheltered surfaces stay legible. |
| **pitch_displacement** | × 0.90 (mild damp) | Stable pitch — no anxious modulation. |
| **diffusion** | × 1.20 (mild amplify) | Soft perimeter reads as gentle diffusion at edges. |

A10's signature is the perimeter — implemented via the visual_chain's per-fragment opacity gradient (high inside the nest ellipse, fading at the edge). Not via a single uniform dim but via a **spatial mask** on the content_layer.

A10 is sourced as a derived dimension from `(operator_stance == "nominal" ∨ "settling") ∧ NOT exploration_seeking ∧ low_audio_arousal`. Combined with the visual_chain context: when these conditions hold, the field reads as held.

## 4. Shader topology

Two changes:

1. **Per-dim modulation** (per §3) at the visual_chain layer — same pattern as A7+A8.
2. **Spatial nest mask** at the content_layer level — the new piece. The content_layer.wgsl computes its per-fragment opacity (Amendment 1) using the procedural noise field; A10 modulates this opacity by an additional ELLIPTICAL FALLOFF centered at the centroid:

```wgsl
// Pseudo-WGSL — read from a new uniform `u_nest_factor` (0..1)
fn nest_mask(uv: vec2<f32>, nest_factor: f32) -> f32 {
    let centered = uv - vec2<f32>(0.5, 0.5);
    let dist_sq = dot(centered, centered);
    // Soft ellipse: opacity = 1.0 inside radius 0.3, falls to 0.0 by 0.5.
    let inside = smoothstep(0.5, 0.3, sqrt(dist_sq));
    // Mix: nest_factor=0 → no mask (pass through 1.0); =1 → full mask.
    return mix(1.0, inside, nest_factor);
}
```

This requires a new `u_nest_factor` uniform field (single float). NOT a new WGSL node — it's an extension to the existing `content_layer.wgsl` Params struct. Implementation cc-task should add this as an optional uniform with default `nest_factor=0.0` so existing behavior is unchanged.

The visual_chain layer adds `_apply_nest_shell_bias(uniforms, factor)` — sets `u_nest_factor` AND applies per-dim modulators per §3.

Composition order in `_uniforms.write_uniforms`:
1. plan_defaults + chain_deltas
2. mode tint
3. roundness bias (A7)
4. miniature bias (A8)
5. **nest-shell bias (A10) ← new**
6. homage damping
7. drawer event pulse (A9, transient overlay)
8. programme override

## 5. Compositor interaction

### Sierpinski overlays

Sierpinski is unaffected by A10 — its triangular geometry is its own register. Operator's eye reads the nest as the field-level enclosure; the Sierpinski sits inside it without modification.

### Token pole

Token pole sits at the right edge of the frame. Under nest-shell, the pole's right-edge position COULD be interpreted as "outside the nest" — but the operator-meaningful semantic is that the pole reports system state independently of the nest's protective interior. So: **token pole is unaffected by A10**.

### Reverie content placement

Content materializes inside the nest ellipse (per §4 nest_mask). Outside the ellipse, content is masked out. This is the FIRST amendment to spatially gate where content can appear (vs A1-A9 which all let content materialize anywhere in the field).

## 6. Anti-pattern list

The implementation MUST NOT use any of the following — they defeat the protective-interior phenomenology:

- **Hard borders / walls / fences.** Bachelard's nest is *soft and inhabited*; a hard wall reads as imprisonment, the OPPOSITE of refuge. The smoothstep falloff (§4) MUST be soft (>0.1 falloff width).
- **Cage / lattice patterns.** Defeats the open-but-cradling phenomenology.
- **Vignettes that go full-black at the edges.** Vignette is fine as long as the falloff stays soft AND retains some visual richness at the edge.
- **Centroid bias to the EXACT center pixel.** The nest is centered but not pixel-precise; `centered = uv - vec2<f32>(0.5, 0.5)` is fine because the smoothstep handles fuzziness.
- **A "nest" preset.** Modulation regime, not preset.
- **A "nest" affordance.** Composition, not selection.
- **Coupling to operator audio (heart-rate driven, etc.).** Nest is visual phenomenology only.

## 7. Coordination with A7 + A8 + A9

**All four compose** — A7, A8, A9, A10 are designed as orthogonal axes:

| Axis | Amendment | Operates on |
|------|-----------|-------------|
| Spatial-inward (gather) | A7 Roundness | Drift / breath / hue-rotate-sign-flip |
| Scale-detail (amplify) | A8 Miniature | Noise frequency / contrast / spectral color |
| Perimeter (hold) | A10 Nests-Shells | Spatial nest_mask + per-dim damping |
| Temporal-revelation (event) | A9 Drawers | Transient pulse on disclosure |

**Composition cases** (canonical stances):

| Stance | A7 | A8 | A9 | A10 | Visual register |
|--------|----|----|----|-----|------------------|
| Operator absorbed in centroid detail | ✓ | ✓ |   |   | Inner texture + outer envelope (A7+A8 canonical) |
| Operator absorbed inspecting revealed item | ✓ | ✓ | ✓ |   | Above + brief disclosure pulse |
| Operator sheltered, focused | ✓ |   |   | ✓ | Centered + held (gentlest) |
| Operator sheltered, working with detail | ✓ | ✓ |   | ✓ | Held nest + inner texture (most-protected work mode) |
| Drawer opens inside nest | ✓ | ✓ | ✓ | ✓ | All four — most intimate disclosure register |

The full composition (all four ON) is the **maximum-shelter, full-attention** stance. Operator is held, focused, detail-amplified, and a specific item is being revealed. The phenomenology converges to *"This moment, this content, this shelter, this detail — fully present."*

## 8. Implementation footprint (downstream cc-task scope)

Spec only — implementation is `bachelard-amendment-10-nests-shells-impl`. Estimated:

- `agents/reverie/_uniforms.py` — `_apply_nest_shell_bias(uniforms, factor)` helper. ~50 lines.
- `agents/visual_chain.py` — `compute_nest_shell_factor()` reading the §3 stance-intersection. ~30 lines.
- `agents/shaders/nodes/content_layer.wgsl` — add `u_nest_factor` uniform field + `nest_mask()` helper + opacity multiplication. ~30 lines (WGSL is verbose).
- `agents/shaders/nodes/content_layer.json` — add `nest_factor` param to the Params spec (must pass u7 audit pin — `default: 0.0`, `min: 0.0`, `max: 1.0`, `type: float`). ~5 lines.
- `agents/effect_graph/presets/reverie_vocabulary.json` — bump plan default for content_layer.nest_factor to 0.0. ~3 lines.
- `agents/reverie/content_layer.py` (or mixer) — pass nest_factor through to GPU. ~15 lines.
- Tests: ~150 lines (factor computation under various stance combos; pin uniform damping; pin spatial mask softness; pin u7 spec audit still passes; pin composition with A7/A8/A9).

Total: ~283 LOC across 7 files. Smaller than A8/A9 because A10's signature change is a single uniform + WGSL helper rather than a new manager component.

## 9. Validation plan (downstream)

The downstream impl cc-task should pin:

1. nest_factor=0 ↔ baseline behavior byte-identical (no regression; the `mix(1.0, inside, 0.0)` in the WGSL returns 1.0 = pass-through).
2. nest_factor=1 ↔ content outside ellipse is fully masked.
3. Soft-falloff width ≥ 0.1 (no hard walls — Anti-Pattern §6).
4. Composition with A7+A8+A9: all four modulators stack without truncation; canonical stance from §7 produces visible shelter+focus+disclosure.
5. u7-per-node-param-signature-audit (#2387) still passes after content_layer.json adds nest_factor.
6. Operator-side acceptance: live livestream — sheltered moments visibly read as held + bounded.

## 10. Out-of-scope

- Implementation (downstream cc-task `bachelard-amendment-10-nests-shells-impl`).
- Audio-domain analogue of shelter.
- Operator-tunable nest_factor (default fixed at first ship).
- An 11th amendment — the original Jr-packet 4-chapter coverage is now complete with A7+A8+A9+A10. Future amendments require new aesthetic-references research from operator.
