---
date: 2026-05-03
status: design — spec only; implementation a separate downstream cc-task
amends:
  - docs/superpowers/specs/2026-03-29-reverie-bachelard-design.md
related_tasks:
  - "cc-task jr-bachelard-amendment-7-roundness-design"
  - "cc-task jr-vinyl-tape-glitch-preset-family-pool (non-collision discussion §6)"
---

# Bachelard Amendment 7 — Phenomenology of Roundness

## Decision

**Amendment 7 is the Phenomenology of Roundness** (*La poétique de l'espace*, ch. X). The four candidate chapters from the Jr aesthetic-references packet — Roundness, Miniature, Drawers/Wardrobes, Nests-Shells — were evaluated against the existing 6-amendment surface for distinctness:

| Candidate | Existing amendment that already covers nearby phenomenology | Verdict |
|-----------|--------------------------------------------------------------|---------|
| **Roundness** | None. Existing immensity (#5) is *outward / expansive*; roundness is *inward / self-completing*. | **Selected** — strongest visual contrast. |
| Miniature | Adjacent to material-quality fragments (#3) which already addresses scale-of-attention via material-class differentiation. Risk of redundancy. | Defer to Amendment 8 candidate. |
| Drawers/Wardrobes | Adjacent to dwelling/trace (#2) which already encodes "the space remembers". Drawers extend this with *concealment-then-disclosure*; novel but secondary. | Defer to Amendment 8 candidate. |
| Nests-Shells | Adjacent to immensity (#5) and reverberation (#4) — Bachelard treats the nest as the protective miniature of immensity. Closest semantic overlap with existing six. | Defer; weakest distinctness. |

Roundness wins on (a) strongest visual contrast to the immensity register already in flight (#5), and (b) clearest single-shader-knob anchor (radial-vs-rectilinear coherence — see §3 below).

## 1. Concept summary

Bachelard's roundness is not the geometric circle. It is the phenomenology of *being-with-self* — the gathered, self-completing, centered presence of an entity that is "round" in its mode of existence. *"Life is round"* (Bachelard, ch. X §1, citing Van Gogh). *"When the philosopher seeks images of being, he often turns to images of roundness."*

For Hapax Reverie, roundness is the inverse modulation surface to **immensity** (Amendment 5):

| Axis | Immensity (Amendment 5) | Roundness (Amendment 7) |
|------|-------------------------|--------------------------|
| Movement | Outward, expansive, depth → infinity | Inward, gathering, depth → centered self |
| Composition | Wide spatial dispersion across the field | Concentric coherence around a centroid |
| Time | Slow accumulation over the dwell | Slow contraction onto a present moment |
| Operator stance bias | Wonder, openness, curiosity-distant | Settling, focused, present-with-self |

Roundness is the visual register of the operator *settling into* the work — the inverse of restless openness. It pairs with the rest stance (`overall_stance == "nominal"` AND `exploration_deficit < 0.2` AND no audio onset for >30s).

## 2. Relation to existing 6 amendments

- **#1 Materialization** — content crystallizes from procedural noise. Roundness modulates the SHAPE of crystallization: under high roundness, content materializes from the centroid outward in concentric rings (vs corner-incubation under low salience).
- **#2 Dwelling/Trace** — content leaves traces that decay slower in dwell-zones. Roundness biases trace placement toward the field centroid, so dwell-traces contract over time toward a self-centered mark rather than fanning across the field.
- **#3 Material Quality** — `material_id` (water/fire/earth/air/void). Roundness is orthogonal to material quality but pairs naturally with **earth** and **water** (gathered, settled materials) and resists **fire** and **air** (dispersive). The pairing is a soft preference, not a hard rule.
- **#4 Reverberation** — feedback echo with afterimage decay. Roundness biases the feedback-feedback warp center so reverberations spiral inward to the centroid rather than drift across the field.
- **#5 Immensity** — outward expansion via `depth` dimension. Roundness uses the **same underlying depth uniform** but reads the OPPOSITE gradient: high `depth` → immense (existing); high `roundness` → inverse-immense (new). Mathematical anti-correlation, not parameter conflict — see §3.
- **#6 Soft Escalation** — pacing of intensity changes. Roundness is escalation-orthogonal; it modulates spatial composition, not intensity over time.

No collision with existing six. Composes with all of them.

## 3. 9-dim parameter envelope

Roundness amplifies and damps the 9 GPU uniform dimensions as follows. Each entry is a multiplier applied alongside the existing per-dim base modulation:

| Dim | Roundness multiplier | Why |
|-----|---------------------|-----|
| **intensity** | × 0.85 (slight damp) | Settled stance reads as quieter, not louder. |
| **tension** | × 0.50 (strong damp) | Centeredness is the opposite of held tension. |
| **depth** | × −1.0 (sign-flip) | Roundness consumes the depth uniform in reverse — high `depth` reads outward (#5), high `roundness × depth` reads inward. The shader reads `(1.0 − roundness * depth_clamped)` for centroid-pull terms. |
| **coherence** | × 1.6 (amplify) | Roundness IS coherence around a centroid. |
| **spectral_color** | unchanged (× 1.0) | Color register is independent. |
| **temporal_distortion** | × 0.40 (strong damp) | Settled = stable in time. |
| **degradation** | × 0.70 (damp) | Roundness reads as held-together, not falling-apart. |
| **pitch_displacement** | × 0.80 (mild damp) | Pitch modulation is dispersive; centeredness damps it. |
| **diffusion** | × 1.4 (amplify) | Diffusion biases inward when paired with roundness — see §4 shader topology. |

Roundness itself is sourced as a *derived* dimension, not a 10th uniform: it is computed at the visual-chain layer from `(rest_stance ∧ low_exploration_deficit ∧ silence_duration > 30s)`. The shader does not need a new uniform slot — roundness modulates EXISTING uniforms before they reach the GPU.

## 4. Shader topology

No new WGSL nodes. Roundness is implemented as a **modulation pass at the visual_chain layer** that reweights existing per-node params before they're written to `uniforms.json`. Specifically:

- `drift.amplitude` × `(1.0 − 0.7 * roundness)` — drift is dispersive; damp it.
- `drift.coherence` × `(1.0 + 0.6 * roundness)` — coherent drift survives roundness.
- `noise.amplitude` × `(1.0 − 0.5 * roundness)` — high-amplitude noise is anti-roundness.
- `feedback.zoom` modulated centroid-pulled (see Amendment 4 trace_center): under roundness, the feedback zoom-center pulls toward (0.5, 0.5) regardless of the trace center. Pinned via a new visual_chain knob `roundness_centroid_pull` ∈ [0, 1] that interpolates `feedback.trace_center_x/y` toward (0.5, 0.5) as roundness rises.
- `breath.rate` × `(1.0 − 0.4 * roundness)` — slow breath under roundness; settle.
- `colorgrade.saturation` × `(1.0 − 0.3 * roundness)` — mild desaturation; centered presence reads as restraint, not chromatic vibrancy.

These are all **additive multipliers on top of existing chain deltas** — they don't replace the chain's per-node modulation, they bias it. Existing presets continue to work unchanged; roundness ships as a "background mood" that contracts the field whenever the stance + silence conditions hold.

The implementation lives entirely in `agents/reverie/_uniforms.py::write_uniforms` (extension, not rewrite). A new helper `_apply_roundness_bias(uniforms, roundness_factor)` runs AFTER the homage damping and AFTER the mode-tint pass (so homage stays authoritative over aesthetics, and roundness contracts what the mode tint produces). The roundness factor is read from a new shared signal at `/dev/shm/hapax-stimmung/roundness.json` (computed by VLA).

## 5. Compositor interaction

Roundness affects compositor surfaces beyond the WGSL pipeline:

### Sierpinski overlays

The Sierpinski triangle ward (`agents/studio_compositor/sierpinski_renderer.py`) carries operator content (YouTube frames in slots) within a self-similar fractal triangle. Under roundness:
- The fractal subdivision *contracts*: target subdivision depth decays from 4 levels (default) to 2 levels as roundness rises. Fewer slots, but each slot held longer.
- The triangle's chrome (border lines, corner gems) gain a slight inward shadow — the geometry stays triangular but the visual weight pulls toward the centroid via a soft inner-glow Cairo pass.
- The triangle's centroid-vs-frame placement shifts: under high roundness, the triangle anchors to frame center even if the layout normally offsets it (e.g., `default-legacy` layout's slight rightward bias is overridden).

### Token pole

The `token_pole` Cairo source (right-edge token meter) reads as a vertical strip. Under roundness:
- The pole's color-band saturation damps (× 0.6 of normal) — the pole reads as a quiet companion, not a competitor for centerpiece attention.
- The token-fill animation slows: the pole's level-ticks animate at 0.6× rate so the pole feels still rather than restless.
- No geometry change — the pole stays where it is.

### Reverie content placement

The reverie content layer's slot opacities (Amendment 1) gain a centroid bias under roundness: even at low salience, content materializes near the centroid rather than at the corners. This is the inversion of the existing low-salience corner-incubation rule:

```python
# Existing (Amendment 1): low salience → peripheral placement
center_pull = base_opacity
corner_offset = (1.0 - center_pull) * 0.3
# Amendment 7 modulation: roundness damps the corner_offset
corner_offset *= (1.0 - 0.8 * roundness_factor)  # high roundness ⇒ corner offset → 0
```

## 6. Anti-pattern list

The implementation MUST NOT use any of the following — they are the obvious-but-wrong shortcuts to roundness that would defeat its phenomenological intent:

- **Simple barrel distortion / fisheye / radial blur.** Bachelard's roundness is *being-with-self*, not lens distortion. A fisheye effect is a geometry trick that draws attention to the lens, the OPPOSITE of self-presence. (The existing `fisheye_pulse` preset is fine within its own register — but roundness must not lean on radial-warp shaders.)
- **A literal circle vignette overlay.** The Sierpinski ward's geometry is triangular, the operator's frame is rectangular. Roundness MUST modulate composition WITHIN existing geometries, not impose a new circular frame.
- **Centroid-pulled chromatic aberration.** Chromatic aberration reads as glitch / digital artifact — anti-rolling-into-self.
- **Soft-focus / Gaussian blur over the entire field.** The "softness" of roundness is compositional (centroid pull, slowed motion), not optical. A blur erases material quality (Amendment 3) — anti-amendment.
- **A new "roundness" preset.** Roundness is a MODULATION REGIME, not a preset. Per operator memory `feedback_no_presets_use_parametric_modulation`: "variance comes from constrained parametric modulation, not preset count." Roundness modulates ALL existing presets when the stance condition holds; it does NOT add a discrete preset.
- **A "roundness" affordance in `shared/affordance_registry.py`.** Roundness is an ambient register, not a recruitable capability. It is computed and applied in the visual_chain regardless of recruitment state. (Composition, not selection.)

## 7. Coordination with `jr-vinyl-tape-glitch-preset-family-pool`

The vinyl/tape/glitch preset family pool (cc-task `jr-vinyl-tape-glitch-preset-family-pool`) adds 12 presets across 3 lineages. Coordination:

- **Roundness biases ALL preset families uniformly.** When the stance condition holds, vinyl/tape/glitch presets are run through the same roundness modulation as calm-textural / audio-reactive / glitch-dense / warm-minimal. No special-casing.
- **Two of the proposed glitch presets in the Jr packet (digital-glitch lineage) are HIGH-amplitude noise.** Under roundness, the visual_chain's `noise.amplitude × (1.0 − 0.5 * roundness)` damping bias automatically pulls those presets back toward field-coherent territory. No per-preset overrides needed.
- **Tape-saturation lineage pairs naturally with roundness** — tape's slow-breath and warm-coherence registers reinforce centeredness. The vinyl/tape/glitch family-name implies the tape sub-lineage will dominate when roundness is active and audio-reactive demand is low.

## 8. Implementation footprint (downstream cc-task scope)

Spec only — implementation is a separate downstream cc-task. The estimated footprint:

- `agents/reverie/_uniforms.py` — add `_apply_roundness_bias(uniforms, factor)` helper + call in `write_uniforms` AFTER mode-tint and BEFORE homage damping (homage stays authoritative). ~60 lines of code.
- `agents/visual_chain.py` — add `compute_roundness_factor()` reading stance + exploration deficit + silence duration. ~30 lines.
- New shared signal at `/dev/shm/hapax-stimmung/roundness.json` published by VLA. ~20 lines.
- `agents/studio_compositor/sierpinski_renderer.py` — read roundness signal, modulate subdivision depth + inward-glow + center-anchor. ~40 lines.
- `agents/studio_compositor/token_pole.py` — read roundness signal, damp saturation + slow tick rate. ~20 lines.
- Tests: ~120 lines (compute roundness factor under various stance combos; pin uniform damping; pin Sierpinski depth modulation; pin token-pole damping).

Total: ~290 LOC implementation + tests across 5 files. Bounded for a single PR.

## 9. Validation plan (downstream)

The implementation cc-task should pin:

1. Roundness factor 0 ↔ baseline behavior is byte-identical (no regression on existing surfaces).
2. Roundness factor 1 ↔ all named modulations apply (drift damped, breath slowed, Sierpinski depth contracted, etc.).
3. Mode flip (research ↔ rnd) under roundness > 0 does NOT affect the roundness modulation (modes are aesthetic registers; roundness is a stance-bound register orthogonal to mode).
4. Operator-side acceptance: live livestream comparison — settling-into-work moments should read as visibly more centered than restless-curiosity moments.

## 10. Out-of-scope

- Implementation (separate downstream cc-task `bachelard-amendment-7-roundness-impl`).
- Audio-domain analogue of roundness (Bachelard's roundness is visual-spatial; the audio register has its own phenomenology and is not addressed here).
- Operator-tunable roundness threshold (the stance condition is fixed at first ship; threshold tuning is a follow-up if the default doesn't sit well).
