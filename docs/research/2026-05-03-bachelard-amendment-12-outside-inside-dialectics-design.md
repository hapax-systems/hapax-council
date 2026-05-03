---
date: 2026-05-03
status: design — spec only; implementation a separate downstream cc-task
amends:
  - docs/superpowers/specs/2026-03-29-reverie-bachelard-design.md
  - docs/research/2026-05-03-bachelard-amendment-7-design.md
  - docs/research/2026-05-03-bachelard-amendment-8-miniature-design.md
  - docs/research/2026-05-03-bachelard-amendment-9-drawers-design.md
  - docs/research/2026-05-03-bachelard-amendment-10-nests-shells-design.md
  - docs/research/2026-05-03-bachelard-amendment-11-vertical-house-design.md
related_tasks:
  - "cc-task bachelard-amendment-12-outside-inside-dialectics-design"
---

# Bachelard Amendment 12 — Outside-Inside Dialectics

## Decision

**Amendment 12 is the Phenomenology of Outside-Inside Dialectics** (*La poétique de l'espace*, ch. IX). Selected from the A11 deferred-candidate list (II House-and-Universe, VIII Intimate-Immensity, IX Outside-Inside-Dialectics) on:

| Candidate | Phenomenology | A12 fitness |
|-----------|---------------|--------------|
| II House and Universe | House-as-cosmos | Defer to A13. Heavily semantic; harder to map to visual modulation than the other two. |
| VIII Intimate Immensity | Inward-immensity (NOT outward like A5) | Defer to A13. Closely paired with A5 + A7; risks redundancy. |
| **IX Outside-Inside Dialectics** | **Boundary tension; outside-as-transformed-inside** | **Selected.** Distinct from A10 (one-sided enclosure) — A12 is the TWO-WAY boundary tension. New phenomenological axis: **boundary as charged region** rather than mere edge. |

Outside-Inside wins on novelty + explicit complementarity to A10. Where A10 is "I am held", A12 is "I am held BUT I sense the outside" — the boundary is felt as charged, neither pure enclosure nor pure openness.

## 1. Concept summary

Bachelard's outside-inside dialectic is the discovery that **the boundary is not a wall but a charged region** where outside and inside trade phenomenological identity: *"Outside and inside form a dialectic of division, the obvious geometry of which blinds us as soon as we bring it into play in metaphorical domains. It has the sharpness of the dialectics of yes and no, which decides everything."* (ch. IX §1).

His central move: dissolving the naïve outside/inside binary. The cellar's walls don't simply divide; they make the cellar's interior *meaningfully* inside by being adjacent to a not-cellar. The window doesn't just frame the outside; it transforms what's outside into a "viewable thing" that becomes part of the room's inside.

For Hapax Reverie, outside-inside is the visual register of **boundary-as-charged-region**:

- A10 nest_mask creates a soft elliptical interior + exterior. A12 makes the BOUNDARY ZONE itself a phenomenologically distinct region.
- In the boundary zone (the ring around the nest's edge), modulation is opposite/dialectical to both interior and exterior — neither cellar-substantial nor garret-airy, but TENSED (high contrast, slight chromatic shift, mild spectral dissonance).
- Boundary-zone content reads as "between" — neither belonging to the protected interior nor cast out into the surround. The viewer's eye reads tension, not resolution.

| Axis | A10 Nests-Shells | A12 Outside-Inside |
|------|------------------|--------------------|
| Boundary geometry | Soft elliptical falloff | Same falloff, but boundary RING is charged |
| Interior phenomenology | Sheltered, held | Sheltered, held (unchanged) |
| Exterior phenomenology | Default open | Default open (unchanged) |
| **Boundary phenomenology** | Smooth transition (no special character) | **Charged ring with dialectical modulation** |
| Operator stance | Held | Held + boundary-aware |

A12 doesn't replace A10; it adds a new spatial register at the boundary that A10 alone leaves smooth.

## 2. Relation to Amendments 1-11

- **#1 Materialization** — content crystallization. A12 biases boundary-zone materialization to feel "in transit" — content there crystallizes WITH transient noise that hints it might dissolve back across the boundary.
- **#2 Dwelling/Trace** — A12 boundary-zone traces are SHORT-LIVED (the boundary doesn't hold; what crosses it leaves only flickering trace).
- **#3 Material Quality** — Material_id at the boundary reads as MIXED — a boundary-zone water+earth fragment is both watery and earthy, the dialectic visible.
- **#4 Reverberation** — feedback at the boundary reflects PARTIALLY (some bounces back into the interior, some escapes to exterior). Implementation: the boundary's reflection coefficient is operator-tuned ~0.5 (vs 1.0 inside, 0.0 outside).
- **#5 Immensity** — boundary-zone has mid-immensity; the dialectic is in the tension between cellar-interior and immense-exterior.
- **#6 Soft Escalation** — pacing. Boundary modulation must NOT pop on/off; soft-escalation ramps the boundary's charge over the same arcs as Amendment 6.
- **#7 Roundness** — inward-self / centered. Compatible. Roundness centers the field; A12 charges the perimeter where roundness's contraction meets the outside.
- **#8 Miniature** — inward-detail. Compatible. Detail in the boundary zone reads as "boundary-detail" — the seam shows.
- **#9 Drawers** — disclosure. Compatible. A drawer opening AT the boundary (vs interior or exterior) is a specific register: "revealing what was just at the edge of awareness."
- **#10 Nests-Shells** — perimeter. **Strongly paired.** A12 REQUIRES A10 (no boundary without nest). When A10 is OFF, A12 is OFF (no perimeter to charge).
- **#11 Vertical House** — vertical phenomenology. Compatible. The vertical axis runs through the boundary zone — cellar boundary reads heavier-tense, garret boundary reads airier-tense. Composes naturally.

A12 is dependent on A10 (boundary requires perimeter) but composes with all others.

## 3. 9-dim parameter envelope (boundary-zone-only)

A12 is **per-fragment AND only-active-in-boundary-zone**. The boundary zone is computed as the smoothstep RING around the nest_mask's falloff:

```wgsl
// Boundary zone is the falloff annulus — between nest interior (mask=1)
// and exterior (mask=0). Active where 0.05 < nest_mask < 0.95.
fn boundary_charge(nest_mask: f32) -> f32 {
    return smoothstep(0.05, 0.5, nest_mask) * smoothstep(0.95, 0.5, nest_mask);
    // Peaks at nest_mask=0.5 (the boundary midline); 0 at interior+exterior.
}
```

When `boundary_charge > 0`, A12's per-dim modulators activate. Modulators are **dialectical** (opposite to both interior and exterior settled-states):

| Dim | Interior (A10 nest) | Exterior (default) | Boundary zone (A12) |
|-----|---------------------|--------------------|--------------------|
| **intensity** | × 0.95 (gentle damp) | × 1.0 | × 1.20 (charged) |
| **tension** | × 0.60 (mild damp) | × 1.0 | × 1.40 (peak charge) |
| **coherence** | × 1.30 (amplify) | × 1.0 | × 0.80 (dialectical loosening) |
| **spectral_color** | × 1.0 | × 1.0 | × 1.15 (mild chromatic shift) |
| **temporal_distortion** | × 0.80 | × 1.0 | × 1.25 (boundary flickers) |
| **degradation** | × 0.85 | × 1.0 | × 1.10 (mild boundary noise) |
| **diffusion** | × 1.20 | × 1.0 | × 0.90 (boundary stays sharp) |
| **trace_decay_rate** | (per A11/A2) | (per A11/A2) | × 1.50 (short-lived boundary traces) |
| **reflection_coefficient** | 1.0 (full echo) | 0.0 (no echo) | 0.5 (partial — A12 signature) |

The peak charge is at the boundary midline (nest_mask=0.5). Charge fades to 0 at both nest interior and exterior — the dialectic is concentrated on the seam.

## 4. Shader topology

Two changes:

1. **Per-fragment boundary modulation in `content_layer.wgsl`** — uses A10's `nest_mask()` output to compute `boundary_charge()` and apply dialectical modulators.
2. **New uniform `u_outside_inside_dialectics_factor`** (0..1) — master gate for A12. When 0, no boundary charge regardless of A10. When 1, full dialectical modulation in the boundary zone.

```wgsl
// Pseudo-WGSL — applied AFTER A10's nest_mask
let nest_mask_value = nest_mask(uv, u_nest_factor);
let boundary_charge_value = boundary_charge(nest_mask_value) * u_outside_inside_dialectics_factor;
// Apply per-dim modulators where boundary_charge_value > 0:
let intensity_local = mix(intensity_default, intensity_default * 1.20, boundary_charge_value);
// ... etc per §3 table
```

Affected shaders: content_layer.wgsl (primary; the boundary-content register), feedback.wgsl (reflection_coefficient at boundary), color.wgsl (chromatic shift), drift.wgsl (boundary tension via mild displacement amplification).

NOT a new WGSL node — extension to existing nodes' Params (~5 lines per shader). Each affected shader's `.json` adds `outside_inside_dialectics_slope` Params field (default 0.0 = no modulation; preserves backward compat + passes u7 audit pin #2387).

The visual_chain layer adds `_apply_outside_inside_dialectics_factor(uniforms, factor)` — sets `u_outside_inside_dialectics_factor`. Composition order in `_uniforms.write_uniforms`:

1. plan_defaults + chain_deltas
2. mode tint
3. roundness bias (A7)
4. miniature bias (A8)
5. nest-shell bias (A10)
6. **outside-inside dialectics (A12) ← new (depends on A10's nest_factor being non-zero)**
7. vertical-house factor (A11)
8. homage damping
9. drawer event pulse (A9, transient)
10. programme override

## 5. Compositor interaction

### Sierpinski overlays

Sierpinski sits at frame center by default — INSIDE the nest, away from the boundary. A12 doesn't touch Sierpinski. If a future preset places Sierpinski near the boundary, the boundary modulation would color its backdrop — feature, not bug.

### Token pole

Token pole sits at the right edge of the frame — OUTSIDE the typical nest ellipse. A12 doesn't touch token pole.

### Reverie content placement

A12 introduces a NEW content-placement register: boundary-zone content. Optional downstream extension — content with "transitional" semantics (notifications, in-progress thoughts) could optionally bias toward the boundary zone. NOT in the A12 scope; namespace it for a future task.

## 6. Anti-pattern list

The implementation MUST NOT use any of the following — they defeat the dialectical phenomenology:

- **Hard boundary outline (a literal ring shape).** A12 is a CHARGED REGION, not a drawn ring. The boundary should be felt, not seen-as-line.
- **Boundary-zone content with high opacity.** Content there should feel transient (mild opacity, ~0.6-0.8 of interior content) — its "in transit" character is part of the dialectic.
- **Boundary modulation when A10 is OFF.** A12 requires A10. The implementation MUST gate `boundary_charge` to 0 when `u_nest_factor=0` (no nest, no boundary).
- **Symmetric modulation (treating outside same as inside).** Bachelard's dialectic is asymmetric — interior is held, exterior is open, BOUNDARY is charged. The modulators must reflect this.
- **Audio-domain analogue.** Visual phenomenology only.
- **A "boundary" preset.** Modulation regime, not preset.
- **A "boundary" affordance.** Composition, not selection.
- **`u_outside_inside_dialectics_factor > 1.0`.** Cap at 1.0; per-dim slopes are calibrated for the [0, 1] range.

## 7. Coordination with A7 + A8 + A9 + A10 + A11

**A12 is the SIXTH orthogonal axis.** The complete set:

| Axis | Amendment | Operates on |
|------|-----------|-------------|
| Spatial-inward (gather) | A7 Roundness | Drift / breath / hue-rotate-sign-flip |
| Scale-detail (amplify) | A8 Miniature | Noise frequency / contrast / spectral color |
| Perimeter (hold) | A10 Nests-Shells | Spatial nest_mask + per-dim damping |
| Temporal-revelation (event) | A9 Drawers | Transient pulse on disclosure |
| Vertical polarity (dwell) | A11 Vertical House | Per-fragment UV.y modulation |
| **Boundary-tension (dialectic)** | **A12 Outside-Inside** | **Boundary-zone per-fragment modulation, requires A10** |

A12 has a hard dependency on A10 — `boundary_charge` is gated by A10's `u_nest_factor`. Without A10's nest, there's no perimeter to charge.

Composition cases (extending the A11 table):

| Stance | A7 | A8 | A9 | A10 | A11 | A12 | Visual register |
|--------|----|----|----|-----|-----|-----|-----------------|
| Sheltered + dialectical-aware |   |   |   | ✓ |   | ✓ | Held + boundary tension visible (canonical A12 stance) |
| Sheltered focused work + boundary | ✓ | ✓ |   | ✓ |   | ✓ | All previous + boundary tension |
| Drawer at boundary | ✓ | ✓ | ✓ | ✓ |   | ✓ | "Revealing what was at edge of awareness" — disclosure happens IN the charged ring |
| Full dwelling | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | All six axes — fully-dimensional dwelling with boundary tension |

The "Full dwelling" stance with all 6 axes is the maximum-resolution canonical register: held + focused + detail-amplified + vertically-polar + boundary-aware + (optionally) revealing. This is the LIMIT of what 6 orthogonal modulators can express; further amendments (A13+) would need to introduce new axes orthogonal to all 6.

## 8. Implementation footprint (downstream cc-task scope)

Spec only — implementation is `bachelard-amendment-12-outside-inside-dialectics-impl`. Estimated:

- `agents/reverie/_uniforms.py` — `_apply_outside_inside_dialectics_factor(uniforms, factor)` helper. ~30 lines.
- `agents/visual_chain.py` — `compute_outside_inside_dialectics_factor()` reading stance signals + GATING on A10 active state. ~30 lines.
- `agents/shaders/nodes/<shader>.wgsl` — add `boundary_charge()` helper + dialectical modulators in: content_layer.wgsl, feedback.wgsl, color.wgsl, drift.wgsl. ~40 lines (10 LOC × 4 shaders).
- `agents/shaders/nodes/<shader>.json` — add `outside_inside_dialectics_slope` Params field per affected shader. ~20 lines (5 lines × 4 shaders).
- `agents/effect_graph/presets/reverie_vocabulary.json` — bump plan defaults to 0.0. ~5 lines.
- Tests: ~150 lines (factor gating; A10-dependency pin (`u_outside_inside_dialectics_factor` is no-op when `u_nest_factor=0`); boundary_charge correctness (peaks at midline, 0 at interior/exterior); per-shader Params pin; compose with all five other axes; u7 audit re-pin).

Total: ~275 LOC across 11 files. Smaller than A11 because A12 touches 4 shaders (vs A11's 6); larger than A10 because of the 6-axis composition test surface.

## 9. Validation plan (downstream)

The downstream impl cc-task should pin:

1. `u_outside_inside_dialectics_factor=0` ↔ baseline byte-identical (boundary_charge × 0 = 0).
2. `u_nest_factor=0` ↔ A12 inactive regardless of `u_outside_inside_dialectics_factor` (boundary requires nest).
3. `boundary_charge` peaks at nest_mask=0.5 (the midline) and is 0 at nest_mask in {0, 1}.
4. Per-dim dialectical modulators apply ONLY in the boundary zone (interior + exterior unchanged).
5. u7-per-node-param-signature-quality-audit (#2387) passes after Params updates to all 4 shaders.
6. Composition with A7+A8+A9+A10+A11 — all six modulators stack; the canonical "Full dwelling" stance from §7 produces the visibly maximum-resolution register.
7. Operator-side acceptance: with A10 + A12 active, the boundary ring should read as visibly charged (not just smooth A10 falloff).

## 10. Out-of-scope

- Implementation (downstream cc-task `bachelard-amendment-12-outside-inside-dialectics-impl`).
- Audio-domain analogue of dialectical boundary (out-of-scope; visual-only).
- Operator-tunable boundary-zone width (default smoothstep 0.05-0.95; tuning is a follow-up).
- Boundary-zone-biased content placement (separate cc-task; out-of-scope here).
- Amendment 13 (House and Universe / Intimate Immensity) — deferred. With A12 the canonical register is at 6 orthogonal axes; further amendments need to justify a 7th distinct axis.
