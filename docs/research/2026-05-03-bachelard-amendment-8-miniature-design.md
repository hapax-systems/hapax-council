---
date: 2026-05-03
status: design — spec only; implementation a separate downstream cc-task
amends:
  - docs/superpowers/specs/2026-03-29-reverie-bachelard-design.md
  - docs/research/2026-05-03-bachelard-amendment-7-design.md
related_tasks:
  - "cc-task bachelard-amendment-8-miniature-design"
  - "cc-task jr-bachelard-amendment-7-roundness-design (sibling)"
---

# Bachelard Amendment 8 — Phenomenology of Miniature

## Decision

**Amendment 8 is the Phenomenology of Miniature** (*La poétique de l'espace*, ch. VII). Selected as the next-best-distinct chapter after Roundness (Amendment 7) per the Amendment-7 design doc's deferred candidates table:

| Candidate (deferred at A7 selection) | Reason for deferral | Amendment-8 fitness |
|---|---|---|
| **Miniature** | Adjacent to material-quality fragments (#3) | Reasonable distinctness — material quality differentiates substance, miniature differentiates **scale of attention**. Worth shipping next. |
| Drawers/Wardrobes | Adjacent to dwelling/trace (#2) | Defer to Amendment 9. |
| Nests-Shells | Adjacent to immensity (#5) + reverberation (#4) | Defer; weakest distinctness. |

Miniature wins on (a) operational anchor in scale-of-attention (a single visual-chain knob), and (b) clear pairing with Roundness (#7 = inward-self / centered; #8 = inward-detail / scale-contracted). The two amendments compose along the same inward axis but at different layers.

## 1. Concept summary

Bachelard's miniature is not the simple act of making things small. It is the phenomenological stance of **finding immensity in the small** — *"in our enchantment, we have lost all sense of relation. The miniature deploys to the dimensions of a universe."* (Bachelard ch. VII §3, on the model of Mlle Saint-Marcoux's *Mes étoiles*).

For Hapax Reverie, miniature is the visual register of **detail-becomes-world** — when attention contracts to a single fragment, that fragment expands into something with its own internal texture, depth, and modal richness. The opposite of the wide aerial overview (Amendment 5 immensity); the cousin of inward-gathering (Amendment 7 roundness) but at a different layer.

| Axis | Immensity (#5) | Roundness (#7) | Miniature (#8) |
|------|----------------|----------------|----------------|
| Direction | Outward, expansive | Inward, gathered | Inward, scale-contracted |
| Composition | Wide spatial dispersion | Concentric coherence | Centroid-detail amplification |
| Operator stance | Wonder, openness | Settling, focused | Absorbed, lost-in-detail |
| Time | Slow accumulation | Slow contraction | Rapid texture-discovery |
| Pairs with | depth ↑ | depth × −1.0 (inward) | (orthogonal — see §3) |

Roundness contracts the field around a centroid. Miniature contracts attention onto a single textural detail and expands its internal complexity. **They compose** — when both fire, the centroid IS the texture-amplified detail.

## 2. Relation to Amendments 1-7

- **#1 Materialization** — content crystallizes from procedural noise. Miniature modulates the **NOISE GRAIN**: under high miniature, the materialization noise frequency increases (smaller-scale crystals form). Detail at the pixel level rather than at the field level.
- **#2 Dwelling/Trace** — content leaves traces. Miniature biases trace **SHAPE** toward small, dense traces (vs. wide diffuse traces under low miniature). The trace becomes a textural mark, not a wash.
- **#3 Material Quality** — material_id (water/fire/earth/air/void). Miniature pairs naturally with **earth** (granular, textured) and **water** (refractive, internally complex). Resists **air** (which is best at large scale) and **void** (which is best as silence/absence). Soft preference, not a hard rule.
- **#4 Reverberation** — feedback echo. Miniature **REDUCES** the feedback radius — afterimages are tighter and more localized, less spread.
- **#5 Immensity** — outward expansion via depth dimension. Miniature is the **inverse-scale** counterpoint. NOT a sign-flip on depth (that's Roundness #7's role); instead a **frequency multiplier** on the spatial-detail uniforms.
- **#6 Soft Escalation** — pacing of intensity changes. Miniature is **rapid-onset** (vs. soft-escalation #6). When miniature fires, it fires at full strength within ~200 ms because the phenomenology is "suddenly noticing detail" — not a slow gather.
- **#7 Roundness** — inward-gathered centeredness. Miniature COMPOSES with roundness rather than competing. When both fire simultaneously, the centroid IS the texture-amplified detail. **Miniature is the inner layer; roundness is the outer envelope.** See §6 for precedence.

## 3. 9-dim parameter envelope

Miniature amplifies and damps the 9 GPU uniform dimensions as follows. Note the explicit deltas vs Roundness (#7) — many dims are touched by both, but in different proportions and along different axes:

| Dim | Miniature multiplier | Roundness multiplier (A7) | Why miniature differs |
|-----|---------------------|---------------------------|-----------------------|
| **intensity** | × 1.20 (mild amplify) | × 0.85 (mild damp) | Detail demands attention; loud-quietly. Contra Roundness which damps. |
| **tension** | × 0.70 (mild damp) | × 0.50 (strong damp) | Absorbed-in-detail is calmer than restless, but more present than fully settled. |
| **depth** | × 1.0 (unchanged) | × −1.0 (sign-flip) | Miniature does NOT consume depth. (Free for compositor use.) |
| **coherence** | × 1.0 (unchanged) | × 1.6 (amplify) | Miniature is locally coherent (per-detail) but globally polysemic; net unchanged. |
| **spectral_color** | × 1.30 (amplify) | × 1.0 (unchanged) | Detail is chromatically richer — micro-textures show all hues. Roundness is restraint; miniature is display. |
| **temporal_distortion** | × 1.0 (unchanged) | × 0.40 (strong damp) | Miniature can be still OR animated — orthogonal to time. Roundness damps time toward stillness. |
| **degradation** | × 0.90 (mild damp) | × 0.70 (damp) | Detail demands legibility; some damping but less than roundness. |
| **pitch_displacement** | × 1.10 (mild amplify) | × 0.80 (mild damp) | Detail gains expressivity from pitch variation. Roundness damps it. |
| **diffusion** | × 0.50 (strong damp) | × 1.4 (amplify) | Miniature is THE OPPOSITE of diffusion — sharpened detail. **Strong axis-divergence from Roundness.** |

The two amendments differ most sharply on: **diffusion** (miniature × 0.5 vs roundness × 1.4 — opposite ends), **spectral_color** (miniature × 1.30 vs roundness × 1.0 — miniature is chromatically louder), and **depth** (miniature unchanged vs roundness sign-flipped). The shared damping (tension, degradation, pitch_displacement) reflects the common inward-direction axis.

Miniature is sourced as a **derived** dimension (no new uniform slot), computed at the visual-chain layer from `(operator_close_attention_signal ∧ low_motion ∧ high_local_visual_complexity)` where:

- `operator_close_attention_signal` = stance == "nominal" AND ir_gaze_zone in {center, near-center} for >5s
- `low_motion` = visual_chain motion_score < 0.3
- `high_local_visual_complexity` = max_novelty_score > 0.5 in any single component

This intersection of stance + gaze + scene complexity defines "operator is absorbed in something detail-rich."

## 4. Shader topology

No new WGSL nodes. Miniature is implemented as a **modulation pass at the visual_chain layer** (same architecture as Amendments 7 + Mode-Tint). Specifically:

- `noise.frequency` × `(1.0 + 1.5 * miniature)` — fine-grained noise texture under miniature; coarse texture without it. **The signature knob.**
- `noise.amplitude` × `(1.0 - 0.3 * miniature)` — tighter noise (lower amplitude) so the higher frequency doesn't overwhelm.
- `feedback.zoom` × `(1.0 - 0.3 * miniature)` — feedback contracts to 1.0 (no zoom growth) under miniature; suppresses the "zooming out" feel.
- `feedback.trace_radius` × `(1.0 - 0.6 * miniature)` — afterimage traces tighten.
- `colorgrade.contrast` × `(1.0 + 0.4 * miniature)` — texture-detail demands contrast to be visible.
- `colorgrade.saturation` × `(1.0 + 0.3 * miniature)` — micro-textures benefit from chromatic richness.
- `breath.amplitude` × `(1.0 - 0.5 * miniature)` — breath is large-scale; damp it during detail-attention.
- `drift.amplitude` × `(1.0 - 0.5 * miniature)` — drift is dispersive; tighten it during miniature.

Implementation lives in a new helper `_apply_miniature_bias(uniforms, miniature_factor)` in `agents/reverie/_uniforms.py`, called AFTER `_apply_roundness_bias` (when that ships) and AFTER `_apply_mode_palette_tint`, but BEFORE `_apply_homage_package_damping`. Composition order:

1. plan_defaults + chain_deltas (existing)
2. mode tint (existing — `_apply_mode_palette_tint`)
3. roundness bias (Amendment 7 impl, downstream — `_apply_roundness_bias`)
4. **miniature bias (Amendment 8 impl, downstream — `_apply_miniature_bias`)** ← new
5. homage damping (existing — `_apply_homage_package_damping`)
6. programme override (existing)

The miniature factor is read from a new shared signal at `/dev/shm/hapax-stimmung/miniature.json` (computed by VLA per §3 derivation rule).

## 5. Compositor interaction

### Sierpinski overlays

Miniature has the inverse effect from Roundness on Sierpinski subdivision:
- Roundness contracts depth 4→2 (fewer slots, held longer)
- **Miniature expands depth 4→6 (more slots, finer subdivision, each slot showing a detail-fragment)**

When both fire simultaneously: the OUTER triangle (roundness) is at depth 2 anchored to centroid; the INNER triangle slots (miniature) re-subdivide internally to depth 6. Net effect: a single centered triangle whose interior is densely fractalized. Operator's eye reads as "absorbed in the detail-rich inner texture."

### Token pole

Miniature has a complementary effect on token-pole compared to roundness:
- Roundness damps saturation × 0.6 + slows tick rate 0.6×
- **Miniature amplifies tick-precision (sub-tick subdivisions visible) without changing saturation**

The pole shows finer-grained level deltas under miniature — the operator can see micro-modulations that would be invisible at default precision.

### Reverie content placement

Under miniature, content slot placement gains **detail-density bias**: instead of single-large-slot (roundness) or peripheral (low-salience), content materializes as **multiple smaller fragments** in a tight cluster around the centroid. The slot opacity logic from Amendment 1 is augmented:

```python
# Under miniature, prefer multiple smaller materializations over one big.
# Conceptual; pseudocode:
if miniature_factor > 0.5:
    # Splay across multiple slot positions with smaller per-slot opacity.
    splay_slots = 4  # default 1 large slot; miniature → 4 small.
    per_slot_opacity = base_opacity / 1.5  # reduce per-slot to keep total constant.
```

## 6. Anti-pattern list

The implementation MUST NOT use any of the following — they are the obvious-but-wrong shortcuts that defeat miniature's phenomenological intent:

- **Literal scaling-down of content (downscale rendering, viewport zoom-out).** Bachelard's miniature is *finding immensity in the small*, NOT *making things small*. A viewport zoom-out reads as "stepping back," the OPPOSITE of leaning-in-to-detail.
- **Zoom-tunneling / dolly-zoom / forced perspective.** These are spatial-trickery effects that draw attention to the lens. Miniature is about absorbed presence with the small thing AS-IT-IS, not motion through space.
- **A "miniature" preset.** Same anti-pattern as Roundness: per `feedback_no_presets_use_parametric_modulation`, miniature is a MODULATION REGIME, not a discrete preset.
- **A "miniature" affordance.** Composition, not selection.
- **High-frequency strobing or flicker effects misread as "detail."** Detail is texture, not flicker. Strobing reads as glitch (Amendment-3 "fire" register), not absorbed-attention.
- **Unbounded noise frequency amplification.** The `× (1.0 + 1.5 * miniature)` cap on noise.frequency is intentional. Beyond ~3× the default, noise becomes aliased moiré on the GPU and reads as digital artifact, not micro-texture. Pin the multiplier.

## 7. Coordination with Amendment 7 (Roundness) — composition + precedence

Both amendments are visual_chain-layer modulation passes. They compose multiplicatively on the dims they share. Order of application: **roundness first, miniature second** (so miniature's signature `noise.frequency` amplification operates AFTER roundness's drift-damping has settled the field).

When both fire (operator absorbed in centroid detail under settled stance):
- Outer envelope: roundness contracts the field around the centroid (sierpinski depth 2, slowed breath, damped drift, centroid-pulled trace).
- Inner detail: miniature amplifies frequency at that centroid (sierpinski inner-depth 6, increased contrast/saturation, tightened trace-radius, damped diffusion).

Net visual: a single centered, slowly-breathing, internally-fractal-rich shape that occupies the field. **This is the canonical "operator absorbed in their work" stance**, and the two amendments are co-designed to produce it.

When only ONE fires:
- Roundness alone: centered slow-breathing field with default texture. Reads as "settling-into-work-without-task-detail."
- Miniature alone: detail-amplified texture without centroid bias. Reads as "noticing detail in any part of the field" — appropriate when operator's gaze wanders toward something interesting at the periphery.

## 8. Implementation footprint (downstream cc-task scope)

Spec only — implementation is a separate downstream cc-task `bachelard-amendment-8-miniature-impl`. Estimated:

- `agents/reverie/_uniforms.py` — add `_apply_miniature_bias(uniforms, factor)` helper + call in `write_uniforms` per §4 order. ~70 lines.
- `agents/visual_chain.py` — add `compute_miniature_factor()` reading the §3 signal-intersection. ~40 lines.
- New shared signal at `/dev/shm/hapax-stimmung/miniature.json` published by VLA. ~25 lines.
- `agents/studio_compositor/sierpinski_renderer.py` — read miniature signal, expand inner subdivision depth + interact with roundness's outer-depth contraction. ~40 lines.
- `agents/studio_compositor/token_pole.py` — read miniature signal, amplify tick-precision. ~20 lines.
- `agents/reverie/content_layer.py` (if it exists; otherwise the slot-placement code in mixer) — splay multi-slot detail under miniature. ~50 lines.
- Tests: ~150 lines (factor computation under various stance/gaze/complexity combos; pin uniform modulation; pin Sierpinski inner-depth; pin token-pole precision; pin slot splay).

Total: ~400 LOC across 6 files. Bigger than Amendment 7 (~290 LOC across 5 files) because it touches more compositor surfaces. Still bounded for a single PR.

## 9. Validation plan (downstream)

The downstream impl cc-task should pin:

1. Miniature factor 0 ↔ baseline behavior is byte-identical (no regression).
2. Miniature factor 1 ↔ all named modulations apply (noise.frequency × 2.5, contrast × 1.4, etc.).
3. **Composition with Roundness**: when both factor are 1, the visible effect is the union of both — outer roundness envelope + inner miniature texture. Pin via Sierpinski subdivision depth: outer = 2 (roundness), inner = 6 (miniature). Net depth pattern: `[2, 6]` (vs default `[4]`).
4. Mode-orthogonality: miniature applies regardless of working_mode (research/rnd/fortress) since it's a stance-bound register.
5. Operator-side acceptance: live livestream comparison — moments where operator is leaning into detail should read as visibly more textured + chromatically richer than wide-attention moments.

## 10. Out-of-scope

- Implementation (separate downstream cc-task `bachelard-amendment-8-miniature-impl`).
- Audio-domain analogue of miniature (separate phenomenology).
- Operator-tunable miniature thresholds (the signal-intersection rule is fixed at first ship; tuning is a follow-up if defaults don't sit well).
- Drawers/Wardrobes (Amendment 9 candidate) and Nests-Shells (Amendment 10 candidate) — deferred.
