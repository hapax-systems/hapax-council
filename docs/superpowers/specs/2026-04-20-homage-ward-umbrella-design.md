# HOMAGE Ward Umbrella: Image Enhancement, Spatial Dynamism, and Scrim Integration — Design

**Status:** draft  
**Date:** 2026-04-20  
**Author:** delta session (cascade Claude Opus 4.7, 1M context)  
**Parent research documents:**
- `docs/research/2026-04-20-homage-ward-umbrella-research.md` (master synthesis)
- `docs/research/2026-04-20-cbip-vinyl-enhancement-research.md` (per-surface technique inventory)
- `docs/research/2026-04-20-vitruvian-enhancement-research.md` (per-surface technique inventory + token-path patterns)

**Parent relay queue items:**
- `~/.cache/hapax/relay/delta-queue-homage-ward-umbrella-20260420.md`
- `~/.cache/hapax/relay/delta-queue-cbip-vinyl-enhancement-20260420.md`
- `~/.cache/hapax/relay/delta-queue-vitruvian-enhancement-20260420.md`

**Related plans/specs:**
- HOMAGE Framework spec (`docs/superpowers/specs/2026-04-18-homage-framework-design.md`)
- HSEA Phase 0 foundation-primitives (infrastructure handoff)
- OQ-02 three-bound invariants (`docs/research/2026-04-20-nebulous-scrim-three-bound-invariants-triage.md`)
- Nebulous Scrim design cluster (6 research docs, 2026-04-20)

---

## §1 — Summary

**Shipped by this spec:** A unified framework for Homage Ward enhancement + spatial-dynamism work across 15 wards, locking recognizability invariants and use-case acceptance tests per ward. Three optical modulation rules (atmospheric perspective, defocus blur, motion parallax) that the Nebulous Scrim applies uniformly to all wards. A shared enhancement/effect-processing taxonomy (12 families, 40+ techniques) mapped to existing and three new effect-graph nodes. Two fixed annexes (CBIP, Vitruvian) with surface-specific enhancements + token-path patterns. The "wards live through the scrim" decision.

**Not shipped:** Per-ward spec documents for the remaining 13 wards (deferred to Phase I—after recognizability invariants are locked). Switchability UI (director affordance for preset selection). Runtime ward registration/deregistration. Animation tweens on geometry changes.

**Invariants locked:** (1) Every ward's recognizability invariant + use-case acceptance test are non-negotiable gates for every enhancement PR. (2) All wards pass OQ-02 three-bound gates (anti-recognition, anti-opacity, anti-visualizer) before shipping. (3) HARDM anti-anthropomorphization is non-negotiable for all wards. (4) Wards live through the scrim as a lens/membrane that modulates their appearance per depth. (5) Spatial dynamism is first-class alongside image enhancement.

---

## §2 — Motivation and Scope

### 2.1 Ward inventory in scope

15 Homage Wards span four categories (hothouse/content/overlay/reverie). All 15 are assigned in `config/compositor-layouts/default.json` as of 2026-04-20:

**Hothouse** (internal state, emissive): `impingement_cascade`, `recruitment_candidate_panel`, `thinking_indicator`, `pressure_gauge`, `activity_variety_log`, `whos_here`.

**Content** (content-bearing, permanent): `token_pole` (Vitruvian), `album` (CBIP), `stream_overlay`.

**Overlay** (chrome): `activity_header`, `stance_indicator`, `hardm_dot_matrix`.

**Reverie** (substrate): `sierpinski` (satellite), `reverie` (NOT a ward; the scrim itself).

All except `reverie` pass through the scrim as recruited visual content.

### 2.2 Gating governance constraints

Three axes must pass before any enhancement ships:

1. **Recognizability invariant (per §4):** Every ward's essential communicative intent must survive enhancement. Invariants are locked in test code.

2. **OQ-02 three-bound gates (per §8):** Anti-recognition (face-detection distance > threshold), anti-opacity (scene-legibility SSIM > threshold), anti-audio-visualizer (visualizer-register score < threshold). All wards must pass.

3. **HARDM anti-anthropomorphization (per §11):** No ward may acquire face clusters, expression gradients, or character-like presence through enhancement or spatial behavior.

### 2.3 The "wards live through the scrim" decision

**Adopted:** Wards live *through* the scrim—a curved lens/membrane (per fishbowl conceit, §7.2) that modulates their appearance as a function of depth. A ward at surface Z=0.0 reads unmediated. A ward at deep Z=0.8–1.0 reads as tinted, blurred, and distorted by the scrim. The scrim is the optical interface, not a container. Ward boundaries persist but soften at depth.

This decision:
- Resolves the "where do wards live?" ambiguity from umbrella research §5.2.
- Justifies spatial-dynamism work (parallax, DoF, atmospheric tint all follow from depth-membership).
- Aligns with the fishbowl conceit (interior liquid medium, transparent boundary).
- Provides a single depth-coordinate system for all wards.

---

## §3 — Design Principles (Locked Invariants)

### 3.1 Recognizability + use-case preservation

Every Homage Ward has two properties that must survive enhancement without exception:

1. **Recognizability invariant:** Prose property that must remain true for the ward to "read as itself." Examples: "album title ≥80% OCR round-trip accuracy," "Vitruvian silhouette edge IoU ≥0.65," "token motion legible at all times." Enumerated per ward in §4.

2. **Use-case acceptance test:** What the operator or audience must be able to do with the ward for it to fulfill its role. Examples: "operator identifies which track is playing," "token-pole progress is visually legible," "stream chat status reads at a glance." Enumerated per ward in §4.

**Enforcement:** Every enhancement PR must cite which ward's invariant it touches, confirm preservation (test harness run, metric ≥ threshold), and get operator approval if marginal.

### 3.2 OQ-02 three-bound enforcement

Every ward enhancement must pass three gates before runtime:

1. **Anti-recognition (bound 1):** Ward does not become a recognizable face under any enhancement chain. Measured: face-recognition model (InsightFace SCRFD or CLIP face-embedding threshold 0.2) applied to output frames; confidence must stay <0.3.

2. **Anti-opacity (bound 2):** Ward does not degrade scene legibility below threshold. Measured: SSIM between original and enhanced background, edge-density classifier, or human observer threshold (>0.65).

3. **Anti-audio-visualizer (bound 3):** Ward does not read as a responsive audio-visualization artifact. Measured: visualizer-register score (internal gate, per OQ-02 triage doc) must be <threshold.

### 3.3 HARDM anti-anthropomorphization

No enhancement may push any ward toward expressive character aesthetics. Forbidden: face-centric focus, expression-mapped color/behavior, eye/mouth emergence from glitch, contour distortion suggesting emotion. Allowed: anatomical overlays (meridians, grids), structural enhancement (edge-detection), contextual framing (proportional canon, historical authority).

### 3.4 Spatial dynamism is first-class

Spatial behavior (placement, size-depth, ward-to-ward, ward↔cam, internal motion, temporal cadence) is not secondary polish—it ships together with image enhancement. Per-ward spatial-dynamism profiles are required deliverables, not optional extras.

### 3.5 Technique taxonomy is source of truth

The taxonomy (§5) is the authority. Per-ward specializations add context or binding, never diverge from the taxonomy's definitions. If a technique is unsafe for all wards, it is rejected globally. If safe but specialized per ward, that binding is documented.

---

## §4 — Ward Inventory and Recognizability Invariants

### 4.1 Ward table (15 wards)

| Ward | Essential Intent | Use-case | Recognizability Invariant | Acceptance Test |
|---|---|---|---|---|
| **token_pole** | Avatar signature glyph; Vitruvian token-traversal pulse | Always on; particle burst on spend events | Vitruvian silhouette + token motion legible; face must not emerge (HARDM binding) | Operator sees token progress at ≥80% accuracy; burst never reads as facial expression |
| **album** | External album-cover referent; listening experience anchor | Track-change refresh; visible always | Album title ≥80% OCR; dominant contours edge-IoU ≥0.65; palette delta-E ≤40; no humanoid bulges | Operator/audience identify album at glance; title extractable |
| **stream_overlay** | Stream chrome status (FX, viewers, chat) | Polling 2Hz; change on event | Text readable ≥95% of time; `>>>` prefix + bracket format persists | Viewer reads status without squinting; format survives enhancement |
| **sierpinski** | Algorithmic composition sketch; geometric ground | Recruited on reverie-satellite path; <1 rev/min rotation | Triangle geometry legible; no face clusters (Pearson <0.6); YouTube frames never composite into face | Viewer sees pure geometry, not character |
| **activity_header** | Authorship indicator (activity label + rotation mode) | Toggles at activity flip; 200ms inverse-flash on change | Activity label legible; rotation mode readable as discrete token; flash ≠ expression | Operator confirms activity state without tooltip |
| **stance_indicator** | `[+H stance]` chip; status readout | Pulsing at stance-Hz; flash on stance change | Stance value legible; `+H` prefix persists; pulse periodic not emotional | Operator reads stance from pulse rhythm alone |
| **impingement_cascade** | Top-N perceptual signals; cognitive weave | Reactive: rows transit on join-message; 5s decay | Salience bars interpretable as magnitude; no face clusters at rows 4–6/10–12; decay monotonic | Observer understands signal priority from bar height; no "expression" reads |
| **recruitment_candidate_panel** | Last-3 recruitments transient state | Ticker-scroll-in on newest; near-surface depth | Family tokens distinct; recency bars read as time-position; age tail decays smoothly | Operator glances to see recent recruitment without reading label |
| **thinking_indicator** | LLM-in-flight signal | Breathing at stimmung-modulated Hz | Label legible; dot breathing periodic; glyph ≠ distress | Operator infers LLM status from breathing rate/phase |
| **pressure_gauge** | Stimmung operator-state readout | Per-cell response at stance-Hz; green→yellow→red interpolation | Cell count legible; gradient monotonic; threshold colors ≠ emotion | Operator reads stimmung from color + cell count without consulting numeric value |
| **activity_variety_log** | 6-cell trace of recent activity | 6 emissive cells; ~1 cell/5s ticker-scroll | Cell count constant; scroll speed legible; no face-like clustering | Observer understands activity history from cell patterns |
| **whos_here** | `[hapax:1/N]` audience framing | Viewer-count change triggers refresh | Count accurate + readable; `hapax:` prefix persists; glyphs ≠ emoji/hand-wave | Operator/audience glance to see audience size |
| **hardm_dot_matrix** | 16×16 dot-grid avatar; glow-through-fabric character | Per-cell ripple at family recruitment; RD underlay | Grid ≠ face (Pearson <0.6); cell count constant; glow-through-scrim bloom asymmetry non-negotiable | Observer sees abstract grid, not stylized face |
| **reverie** | Nebulous Scrim itself; 8-pass RGBA substrate | Always-on permanent generative process | Reverie orthogonal to ward enhancement; OQ-02 brightness ceiling ≤0.55 | Reverie's depth-field substrate legible; scrim effects uniform |

### 4.2 Pydantic schema: WardEnhancementProfile

Every enhancement PR must instantiate and pass this schema. Gating framework:

```python
class WardEnhancementProfile(BaseModel):
    """Gate-keeping schema for ward enhancement work."""
    ward_id: str                                    # "album"
    recognizability_invariant: str                  # prose from §4.1
    recognizability_tests: list[str]                # ["ocr_accuracy", "edge_iou", "palette_delta_e", ...]
    use_case_acceptance_test: str                   # prose from §4.1
    acceptance_test_harness: str                    # path to test script
    accepted_enhancement_categories: list[str]      # subset of §5 safe for this ward
    rejected_enhancement_categories: list[str]      # violate invariants
    spatial_dynamism_approved: bool
    oq_02_bound_applicable: bool
    hardm_binding: bool
    cvs_bindings: list[str]                         # ["CVS #8", "CVS #16", ...]
```

Schema reuses `ConsentContract` gating pattern from `shared/consent.py`. Extend `tests/studio_compositor/test_visual_regression_homage.py` for golden-image comparison. Extend `tests/studio_compositor/test_anti_anthropomorphization.py` for face-cluster property-based tests.

---

## §5 — Shared Enhancement and Effect-Processing Taxonomy

### 5.1 Technique families (40+ techniques across 5 classes)

**Column format:** Technique | Effect-graph node(s) (existing vs. new) | Recognizability-risk (0–5, low→high) | HARDM-compatibility | Applicable wards | Notes.

#### 5.1.1 Palette transformations (non-destructive, color remapping)

| Technique | Nodes | Risk | HARDM | Wards | Notes |
|---|---|---|---|---|---|
| Remap | `colorgrade` (existing) | 1 | Safe | album, cover-heavy | Lookup-table recolor (greyscale→sepia, invert, etc.). Safe with OQ-02 brightness ceiling. Test: visual regression golden. |
| Posterize | `posterize` (NEW) + `halftone` (existing) | 2 | Safe | album, sierpinski | Collapse palette to 4–8 colors via ordered Bayer dither. Recognizable if dither size ≤8px. CBIP-aligned. Test: SSIM ≥0.7 vs. original. |
| Quantize | `palette_extract` (NEW) | 1 | Safe | album, cbip | K-means dominant-color extraction; render as swatch grid. Non-destructive. Serves contextualization move. |
| Duotone | `colorgrade` + `bloom` | 2 | Caution (OQ-02) | album, hardm | Two-color space remapping. Risk: contrast collapse if colors similar. Mitigation: manual safeguard per-preset; reject if produces face palette. |
| Index | `halftone` (existing) | 1 | Safe | album, stream_overlay | Map to mIRC 16-color palette + dithering. Test: OCR ≥90% on text. |

**Ship this epic:** Posterize, Palette-Extract. Both required for CBIP + Vitruvian annexes.

#### 5.1.2 Spatial transformations (contour/structure-aware)

| Technique | Nodes | Risk | HARDM | Wards | Notes |
|---|---|---|---|---|---|
| Edge-detect | NEW `edge_detect` + optional `threshold` | 2 | Safe | album, sierpinski | Sobel/Laplacian contours; composite edges over posterized interior. CBIP identification move. <100ms. |
| Halftone | `halftone` (existing) | 1 | Safe | album, activity_variety_log | Ordered or error-diffusion halftone. 4–8px safe; <2px or >16px risks legibility. CBIP-aligned. |
| Dither | `halftone` (configurable) | 1 | Safe | album | Perceptually pleasing noise-based dithering. Lower visual noise than Bayer. CBIP precedent: cassette xerox. |
| RD | `rd` (existing in Reverie) | 2 | Caution | hardm, sierpinski | Organic patterns. Risk: cells cluster into face-like regions without parameter bounds. HARDM test required (Pearson <0.6). |
| Drift | `drift` (existing) | 1 | Safe | all wards (depth-modulated) | Wobble/heat-haze displacement. Amplitude scales by ward Z-depth. Non-destructive; reads as "liquid medium inertia." |
| Warp | `drift` or NEW `flow_field` | 2 | Caution | album | Perlin/curl-noise driven displacement. Risk: unbounded warp blurs contours. Mitigation: max displacement ≤8–16px. Test: Sobel edge IoU ≥0.65. |

**Ship this epic:** Edge-detect (NEW). Required for CBIP + Vitruvian contour-forward moves.

#### 5.1.3 Temporal transformations (accumulation, decay, periodicity)

| Technique | Nodes | Risk | HARDM | Wards | Notes |
|---|---|---|---|---|---|
| Feedback | `feedback` (Reverie) | 1 | Caution (OQ-02) | all wards | Re-blend previous frame at fade-rate. Produces ghosting/wake trails. Mitigation: fade-rate tuned per-ward. OQ-02 governs saturation ceiling. |
| Decay | `breath` (Reverie) + temporal multiplier | 1 | Safe | impingement_cascade, recruitment_candidate | Exponential decay on salience/intensity. No recognition risk if envelope monotonic. |
| Accretion | Multiple render passes + alpha-blending | 2 | Safe | activity_variety_log, hardm (ripple waves) | Stack multiple frames at different alpha. Recognizable if original topmost layer. |
| Strobe | `breath` (hard thresholds) | 3 | **Caution (reject for indicators)** | NOT intended | Strobing text/faces triggers photosensitivity + reads as emotional. REJECT as primary effect. <100ms reactive bursts acceptable. |

**Ship this epic:** Feedback (existing; tune per-ward). Decay (existing; expand couple points). **Reject:** Strobe on visual indicators.

#### 5.1.4 Artifact grammars (retro-aesthetic, signal-degradation)

| Technique | Nodes | Risk | HARDM | Wards | Notes |
|---|---|---|---|---|---|
| Glitch | NEW `bitplane_scramble` or `frame_shuffle` | 3 | Caution | album (reactive bursts only) | Selective bit-plane inversion / scan-line interruption. Risk: >70% frame defeats recognition. Mitigation: <30% frame, <500ms. CBIP boxing only. |
| Chromatic aberration | `chromatic_aberration` (existing in Reverie) | 1 | Safe | all wards | RGB channels offset 1–3px. Readable; retro-video aesthetic. Already used in Reverie. |
| Scanlines | `scanlines` (existing) | 0 | Safe | album, stream_overlay, all text-heavy | Horizontal lines 2–4px spacing, 5–15% opacity. Purely additive; CRT aesthetic. |
| Film-grain | `noise_overlay` (existing) | 1 | Safe | album, sierpinski | Gaussian or Perlin noise overlay. Non-destructive. Already live on Reverie + album. |
| Bloom | `bloom` (existing) | 1 | Caution (OQ-02 bound-2) | hardm, activity_header | Bloom on bright areas. Risk: saturation ceiling exceeded if not gated. Mitigation: cap bloom ≤0.65 absolute brightness. |
| Kuwahara | NEW `kuwahara` | 2 | Safe | album, sierpinski | Edge-preserving smoothing. Posterized but sharp contours. Recognizable; CBIP-aligned (painterly). O(W×H×k²), ~200–400ms (cache-only for deliberative). |

**Ship this epic:** Kuwahara (NEW), Chromatic Aberration (reuse existing). Both required for CBIP + Vitruvian.

#### 5.1.5 Compositional grammars (multi-layer, selective)

| Technique | Nodes | Risk | HARDM | Wards | Notes |
|---|---|---|---|---|---|
| Collage | Multiple `composition` passes | 1 | Safe | activity_variety_log | Stack multiple ward frames at different opacities. Recognizable if each layer legible. De La Soul transparency principle. |
| Cutout | `threshold` + `mask` (compositing) | 2 | Safe | album | Segment image into foreground/background; apply different transforms. Recognizable if foreground (cover) remains hero. |
| Layer-mask | Mask-driven `composition` | 1 | Safe | album, sierpinski | Apply transformation to masked region only. Selective enhancement preserves core recognition. |
| Double-expose | `feedback` + `composition` | 2 | Safe | album (deliberative only) | Composite current + previous frame at blend ratio. Recognizable at ≤0.5 ratio (current ≥50% weight). High blend defeats recognition. |

**Ship this epic:** None required for Phase S. Defer to Phase I—these are advanced deliberative moves.

### 5.2 Effect-graph node implementation priorities

**Tier 1 (ship first, unlock CBIP + Vitruvian immediately):**
1. `posterize` — palette collapse via ordered dither. WGSL ~20 lines. Unlocks palette-remapping family.
2. `palette_extract` — K-means clustering → dominant-color grid overlay. Offline K-means; Cairo-side composition. Unlocks contextualization family.
3. `kuwahara` — edge-preserving blur via quadrant min-variance. WGSL ~50 lines. Cost: ~300ms at 1280×720; cache-only for deliberative.
4. `edge_detect` (Sobel) — boundary extraction (σ=1.0 pre-filter, Sobel operator). WGSL ~40 lines. <100ms.

**Tier 2 (nice-to-have, defer to Phase I+):**
- `bitplane_scramble` — glitch effect via selective bit-plane XOR.
- `blue_noise_dither` — perceptually pleasing noise dithering (vs. ordered Bayer).
- `flow_field` — Perlin/curl-noise warp with bounded displacement.

**Do not ship (architectural violations):**
- Lens distortion, perspective transform, depth-of-field: violate flatness axiom inherited from CBIP.
- Floyd-Steinberg dither: sequential (pixel-dependent); GPU parallelization incompatible. Ordered Bayer via `posterize` is sufficient.

---

## §6 — Spatial-Dynamism Grammar

Six spatial dimensions, with concrete behaviors per ward to ship Phase I.

### 6.1 Placement dynamics

**Vocabulary:** Static (album, sierpinski, reverie), Drifting (impingement_cascade rows slide-in + 5s decay; activity_variety_log ticker-scroll), Cycling (signature artefact rotation, deferred Phase 8).

**Ward binding:** Most wards static-anchored per layout. Hothouse wards (cascade, ticker, recruitment panel) have transient drifting motion on lifecycle events. Commitment: static wards never drift; drifting wards have explicit duration bounds (5s decay, 1 cell/5s scroll).

### 6.2 Depth dynamics (via "wards live through scrim")

**Vocabulary:** Surface (Z≈0.0, crisp marks on membrane), Near-surface (Z≈0.3, 1–2px blur), Hero-presence (Z≈0.5, focus plane, sharpest), Beyond-scrim (Z≈0.8–1.0, heavy blur 4–6px, atmospheric tint).

**Ward binding:** Album, sierpinski → MEDIUM-DEEP for emphasis on track-change; token_pole cranium-arrival is transient Z-depth spike. Parallax coupling: near wards (Z≈0.5) move full amplitude; deep wards (Z≈0.8–1.0) move ~50% amplitude, slower tempo. Breathing amplitude <±5% scale (>±10% reads as distress).

### 6.3 Ward-to-ward interactions

**Vocabulary:** Z-order collision avoidance (distinct z_order per surface in default.json), max 2 wards EMPHASIZED simultaneously; third evicts oldest. hardm + impingement_cascade coordinate: when cascade salience >0.85, corresponding HARDM cell ripples in sync.

**Ward binding:** hothouse wards never occlude content wards; content wards never occlude reverie. Commitment: no dynamic z-order swaps; order defined at layout time.

### 6.4 Ward ↔ camera interactions

**Vocabulary:** Four corner PiPs rotate per programme-mode; cameras composited at beyond-scrim depth (same tier as album, sierpinski). Differential blur + atmospheric-perspective tint applied.

**Ward binding:** cameras remain passive observers; no ward interacts with camera PiPs. Commitment: camera depth Z≥0.8; ward depth Z≤0.8 to prevent occlusion.

### 6.5 Internal motion (within-ward spatial dynamics)

**Ward-specific bindings:**
- **token_pole:** Path traversal (navel→cranium, ~30fps per frame), cranium-burst radial explosion.
- **album:** Cover shimmer (sub-Hz, nearly static).
- **sierpinski:** Sub-1-rev/min rotation; audio-energy modulates centre-void intensity.
- **hardm:** Per-cell ripple wavefronts (ripple leading edge slightly deeper than trailing).
- **impingement_cascade:** Rows slide-in 5s fade (existing).
- **activity_variety_log:** 6-cell ticker ~1 cell/5s.

**Commitment:** no internal motion exceeds its budget; token_pole animates continuously (no stalls); hardm ripple phase couples to MIDI; activity_variety_log scroll synchronizes to global 1-cell/5s clock.

### 6.6 Temporal cadence

**Vocabulary:** Signal-driven (token-pole cranium bursts on spend events, activity_header flash on activity flip), Periodic (stance_indicator pulses at stance-Hz), Reactive (MIDI clock pulse triggers HARDM row 11 ripple, chat-keyword burst triggers scrim moiré spike).

**Commitment:** Consent-phase disables HOMAGE entirely when active (fail-closed on interpersonal_transparency axiom).

---

## §7 — Nebulous Scrim Relationship (DECIDED)

### 7.1 The scrim as lens/membrane

**Core definition:** The Nebulous Scrim is a curved membrane (glass bowl or lens, per fishbowl conceit) through which the audience peers. Inside is a liquid medium of measurable depth (Z ∈ [0.0, 1.0]). The scrim is the optical interface—the boundary that refracts light per Snell's law and atmospheric perspective (da Vinci sfumato). Wards inhabit the medium at assigned depth bands.

**Not a container:** Wards do not enter or exit the scrim. They are pinned to fixed Z-bands; depth is perceptual, not geometric.

**Not a separate visual layer:** The scrim is not composited on top of wards. It IS the modulation that wards experience as a function of depth.

### 7.2 Ward-through-scrim model

Wards live *through* the scrim. A ward at Z=0.0 (surface) appears unmediated. A ward at Z=1.0 (deep) appears tinted, blurred, distorted. Ward boundaries persist but soften: sharp at surface, blurred edges at depth.

**Defense against alternatives:**
- **Inside (container):** If inside, wards would be occluded exiting. But wards never leave. Rejected.
- **As the scrim (composite):** If wards were the scrim, they would be structural + permanent. But wards are transient recruited content. Rejected.
- **Alongside (parallel layer):** If parallel, wards would be always-on-top or underneath, defeating depth + legibility. Rejected.
- **On (surface marking):** Implies 2D contact; wards have depth. Rejected.
- **Through (lens model):** **Adopted.** Consistent with fishbowl, optical histories (Snell, Newton, da Vinci), and implementation (depth-conditioned blur, tint, parallax).

### 7.3 Uniform optical modulation (three cues)

The scrim applies three effects uniformly to all wards, regardless of surface identity:

1. **Atmospheric perspective (tint):** Ward color LERPs toward scrim tint (cyan for BitchX package) by ~30% as Z increases. Z=0.0 → zero blend; Z=1.0 → full scrim-tint blend. Monotonic; no chaotic recoloring.

2. **Defocus blur (depth-of-field):** Focus plane default Z=0.5 (hero-presence tier). Wards blur proportional to |Z - focus|. Scale: ~0 blur at Z=0.5, ~2px at Z=0.3/0.7, ~4–6px at Z=0.0–1.0. Gaussian blur, not box.

3. **Motion parallax:** Ward amplitude scales `1/(1+Z)`. Near wards (Z≈0.5) move full amplitude; deep wards (Z≈0.8–1.0) move ~50% amplitude. Slower tempo at depth (phase-lag of ~10% per 0.1 Z-depth increment).

**Configuration per-package:** BitchX: 30% tint + 2px max blur. Fallback (generic): 20% tint + 1px max blur.

### 7.4 Ward boundaries under scrim

Persist but appear as partial impressions at deep tiers:
- **Surface (Z≈0.0):** Sharp, fully opaque, hard edges.
- **Near-surface (Z≈0.3):** 1–2px blur; slightly softened.
- **Hero-presence (Z≈0.5):** Focus plane; sharpest.
- **Beyond-scrim (Z≈0.8–1.0):** Heavy blur (4–6px), atmospheric tint; reads as impression.

**hardm special case:** 16×16 grid blurs as unit preserving silhouette; interior cell boundaries soften but grid structure readable.

### 7.5 Reverie: not a ward, not recruited

**Categorical different:** Reverie IS the scrim substrate; it does not "pass through" itself. Always-on, permanent, structural. No CairoSource, no cached surface, no transition_state, not recruited. The scrim is the medium; wards are the message.

### 7.6 API contract: ward-through-scrim compositor pipeline

**Compositor logic:**
```
1. Read Reverie frame from /dev/shm/hapax-sources/reverie.rgba
2. Composite as baseline (0% opacity; it is the ground)
3. For each ward in Z-order:
   a. Read ward's rendered surface
   b. Apply depth-conditioned optical modulation (tint, blur, parallax amplitude)
   c. Composite atop scrim at assigned Z-band depth
4. Write composited frame to output (V4L2, HLS, JPEG sidecar)
```

**Ward layer interface:** Scrim reads a "ward layer" (RGBA with alpha + tint + warp modulation applied atop) before compositor egress. Ward identity is orthogonal to the optical transformation.

### 7.7 Face-obscure-before-scrim (OQ-02 decision)

Per OQ-02 three-bound invariant (bound 1: anti-recognition), face obscuration happens BEFORE the scrim applies its optical modulation. Rationale: the scrim's tint/blur/distortion is global; face masking must happen at the content layer (ward-specific pixelation via face-detect + threshold) before any scrim effect applies.

**Implementation:** `agents/studio_compositor/face_obscure_integration.py::face_obscure_ward_layer()` runs on each ward surface before compositor._pip_draw passes it to scrim-modulation.

---

## §8 — OQ-02 Three-Bound Enforcement Integration

### 8.1 The three bounds

Every ward enhancement must pass all three gates before shipping:

1. **Anti-recognition (bound 1):** Ward does not become recognizable as a face under enhancement. Test: face-recognition detector (InsightFace SCRFD or CLIP face-embedding threshold 0.2) applied to 50 output frames at medium intensity; confidence must be <0.3 across all frames. Fail: reject enhancement.

2. **Anti-opacity (bound 2):** Ward does not degrade scene legibility. Test: SSIM (structural similarity) between original + enhanced background ≥0.65, OR edge-density classifier ≥threshold, OR human observer > legible threshold (>75% can identify ward purpose from one frame). Fail: reduce enhancement intensity or reject.

3. **Anti-visualizer (bound 3):** Ward does not read as audio-visualization artifact. Test: visualizer-register score (internal gate, per OQ-02 triage doc `2026-04-20-nebulous-scrim-three-bound-invariants-triage.md`) <threshold. Fail: reject enhancement family for that ward.

### 8.2 Test harness integration

**Per-ward governance flow:**

1. **Unit test:** `tests/studio_compositor/test_ward_enhancementprofile_{{ward_id}}.py` instantiates WardEnhancementProfile, confirms recognizability_tests list is non-empty, checks unit test fixtures (e.g., album's ocr_round_trip.py imports and runs).

2. **Integration test:** `tests/studio_compositor/test_oq02_bounds_per_ward.py` orchestrates three-bound test harness:
   ```
   for ward in ward_list:
       for enhancement_family in accepted_families[ward]:
           render_ward_under_enhancement(ward, enhancement_family, intensity=medium)
           test_anti_recognition_bound_1(output_frames)
           test_anti_opacity_bound_2(output_frames)
           test_anti_visualizer_bound_3(output_frames)
           assert all_bounds_pass, f"Ward {ward} + {enhancement_family} failed bound {N}"
   ```

3. **CI gate:** All-bounds-pass is a required check before merge. Regression: if a previously passing ward+enhancement combo fails, the PR is rejected.

4. **Runtime signal:** `agents/studio_compositor/budget.py::publish_bounds_signal()` publishes runtime degraded-signal when a bound approaches ceiling. VLA infers visual legibility deficit; raises operator alert if bound exceeded.

### 8.3 Parallel test harness with audio profiles

OQ-02 Phase 1 (referenced in umbrella research §4) establishes per-audio-profile test multiplexing:

```
for audio_profile in [silent, speech, music_low, music_high]:
    for ward in ward_list:
        set_global_audio_context(audio_profile)
        run_three_bound_harness(ward)
```

Rationale: visualizer-register bound (bound 3) is audio-sensitive. Some enhancements may pass silent but fail under music-high. Harness catches this.

---

## §9 — Reactive Coupling Grammar

### 9.1 Signal → ward parameter → wards → strength

All signals are existing; no new sources invented. Coupling table (umbrella research §6):

| Signal | Ward | Parameter | Range | Notes |
|---|---|---|---|---|
| spend_event | token_pole | path_speed + burst_intensity | 0.5–2.0× | Strong coupling; visible immediately |
| track_change | album | cover_image + emphasis_depth | surface→medium-deep | Strong coupling; persistent across round |
| chat_keyword | stream_overlay + scrim | density + moiré_intensity | 0–1.0 | Medium coupling; transient (0.5s) |
| activity_flip | activity_header | flash_brightness + stance_hz | 0–1.0 | Medium coupling; reactive burst |
| llm_in_flight | thinking_indicator | breathing_rate | stance_hz × shimmer_hz | Medium coupling; continuous while in-flight |
| stimmung.intensity | all_wards | parallax_amplitude + animation_speed | 0.5–2.0× | Weak–Medium; global modulation |
| stimmung.coherence | all_wards | decay_rate + dwell_duration | 2–30s | Weak; affects temporal cadence |
| consent_phase | all_wards | visibility | 0→off | Strong; consent-safe layout disables HOMAGE entirely |

**Principle:** All modulations are monotonic + structural (no chaotic reversals, no compulsive acceleration, no dark-pattern timing).

---

## §10 — Per-Ward Specializations (Annex Pointers)

### 10.1 CBIP vinyl-enhancement annex

**Location:** `docs/superpowers/specs/2026-04-2X-cbip-vinyl-enhancement-annex.md` (to be authored Phase S+1).

**Reference:** CBIP research's 5 families (Palette Lineage, Poster Print, Contour Forward, Dither & Degradation, Glitch Burst), 3 new nodes (`posterize`, `kuwahara`, `palette_extract`). Hermeneutic-move framing (identification → contextualization → argument → hand-off). Round-structure coupling (deliberative: 4-min dwell, high-detail transform; reactive: 1–3s kinetic burst).

**Governance:** Ring 2 classifier (monetization safety), no DMCA regression (attribution overlay mandatory).

### 10.2 Vitruvian enhancement + token-path annex

**Location:** `docs/superpowers/specs/2026-04-2X-vitruvian-enhancement-annex.md` (to be authored Phase S+1).

**Reference:** Vitruvian research's 2 enhancement families (Canon-Grid Visibility, Anatomical-Circulation Aesthetic), 5 token-path patterns (Circulation Ascent, Golden-φ Subdivisions, Vesica Emergence, Orbital Accretion, Fibonacci-Spiral Anchor). Spatial-vocabulary prior art (meridians, chakras, esoteric circulations, motion-art lineages). Non-manipulative token-behavior vocabulary (growth rings, orbital mechanics, breath-sync).

**Governance:** Anti-anthropomorphization strict enforcement (HARDM alignment), no face-cluster emergence, CVS #8 non-manipulation.

### 10.3 Other wards (13 remaining)

Phase I phases 5–7 introduce per-ward recognizability invariants + profiles for:
- Hothouse batch (impingement_cascade, recruitment_candidate_panel, thinking_indicator, pressure_gauge, activity_variety_log, whos_here)
- Overlay batch (activity_header, stance_indicator, hardm_dot_matrix)
- Reverie satellite (sierpinski)
- Reverie substrate (reverie, orthogonal—no profile needed)

No per-ward spec needed unless surface-specific governance applies (e.g., reverie has OQ-02 brightness ceiling binding, documented in scrim spec).

---

## §11 — Governance Cross-Check

| Invariant | Axiom | Violation | Enforcement Hook | Test Fixture |
|---|---|---|---|---|
| HARDM anti-anthropomorphization | CVS persona | Face clusters (Pearson >0.6), face-bulge depth modulation, refraction halos producing head silhouette | `test_anti_anthropomorphization.py`, property-based hypothesis test, every PR | `test_hardm_regression_pin_15_wards.py` (batch face-detector on all wards) |
| CVS #8 non-manipulation | CVS axiom | Operant-conditioning reward grammars (smiling gradient, winking), punishment faces (frowning) | Code review (grep emotion patterns); regression golden visual spots | `test_cvs8_healthy_mechanics_per_ward.py` (confirm token paths feel earned, not gamified) |
| CVS #16 anti-personification | CVS axiom | Enhancement renders any ward as emoji, emoticon, or first-person-character cue | Code review (grep emoji/emoticon); regression goldens visual spot-check | `test_cvs16_no_emoji_emergence.py` (check icon fonts, glyphsets) |
| Ring 2 WARD classifier | Governance | Enhancement reads as product ad, influencer-ified content, copywriting | Inherits existing WARD classifier; no new checks in umbrella scope | `test_ring2_ward_classifier_per_surface.py` (validate Splattribution system still fires) |
| Consent-phase visibility | `interpersonal_transparency` axiom | Enhancement introduces persistent state about non-operator persons | Consent gate in AffordancePipeline; HOMAGE disables in consent-safe layout | `test_consent_phase_homage_disabled.py` (confirm layout-swap happens) |
| Recognizability invariant | Umbrella §4 | Enhancement alters essential intent (title unreadable, shape unrecognizable, grid face-like) | WardEnhancementProfile schema gating; per-ward test harness runs acceptance test, operator approval if marginal | `test_recognizability_invariant_per_ward.py` (batch all wards, confirm metrics ≥ thresholds) |
| OQ-02 brightness (bound 2) | OQ-02 triage | Composited brightness >0.65 absolute under scrim + bloom | CI gate: brightness oracle at compose time; reject if exceeded; precedent: D-25 commit 863509ac9 | `test_oq02_brightness_bound_per_ward.py` (render each ward under max intensity, confirm absolute brightness <0.65) |
| OQ-02 anti-recognition (bound 1) | OQ-02 triage | Content easily recognized as face under enhancement chain | Face-recognition detector (CLIP/InsightFace, threshold 0.2); reject if confidence >0.3 | `test_oq02_anti_recognition_bound.py` (batch 50 frames per ward+enhancement, confirm face-confidence <0.3) |

---

## §12 — Test Plan

### 12.1 Unit tests

- `test_ward_enhancement_profile_schema.py`: WardEnhancementProfile model round-trip, all 15 wards instantiable, serialization.
- `test_technique_taxonomy_coverage.py`: All 40+ techniques in taxonomy have at least one "applicable wards" binding; no orphaned techniques.
- `test_recognizability_metrics_compute.py`: OCR, edge-IoU, pHash, palette delta-E all compute + threshold-compare correctly.

### 12.2 Integration tests

- `test_ward_under_enhancement_family.py`: For each (ward, enhancement_family) pair in ward.accepted_enhancement_categories, render ward under enhancement, run acceptance_test_harness, confirm recognizability_tests all pass.
- `test_spatial_dynamism_per_ward.py`: Each ward's spatial-dynamism profile renders without crashes; internal motion stays within budget (fps, displacement, decay rates).
- `test_scrim_through_optical_modulation.py`: Render ward inside vs. outside scrim; confirm correct layer order, optical cue application (tint, blur, parallax amplitude).

### 12.3 Regression pinning

- `test_visual_regression_homage_golden_images.py`: Pre-committed golden images for each ward at default intensity; render, hash pixels, compare. Flag any pixel drift >1% as regression.
- `test_anti_anthropomorphization_property_based.py`: Hypothesis property-based test: for all wards + all enhancement families, generate random output frames; run face-detection; assert no face clusters (Pearson correlation <0.6 vs. face-mask template).
- `test_oq02_three_bounds_per_ward.py` (see §8.2): Harness runs all three OQ-02 bounds on all wards × enhancement families; fails fast on any bound exceeded.

### 12.4 Governance gates

- `test_hardm_regression_pin_15_wards.py`: Batch run InsightFace SCRFD face-detection on 50 random frames per ward; assert no face bounding box with confidence >0.5.
- `test_cvs8_healthy_mechanics.py`: Token paths feel earned (no sudden reward cascades), behavior is non-compulsive (no flicker <100ms).
- `test_cvs16_no_emoji_emergence.py`: Grep enhancement output SVG/Cairo font for emoji Unicode ranges; assert none present.
- `test_ring2_ward_classifier_regression.py`: Confirm Ring 2 WARD classifier still fires on enhanced output; no silent classification failure.

### 12.5 Human-in-the-loop pre-broadcast

Before any enhancement family ships to livestream, run human spot-check on 10–20 canonical surfaces at 3 intensity levels (low/medium/high):

**CBIP canonical set:** Liquid Swords, The Low End Theory, Madvillainy, Black on Black, Igor.  
**Vitruvian canonical set:** da Vinci original, Dürer, Vesalius, Michelangelo study, contemporary Gray's Anatomy.  
**Hothouse canonical set:** 3-frame sequence from typical activity (impingement, recruitment, pressure change).

**Blind test protocol:** "Without hints, identify this [ward-type]. If unsure, guess from [5 options]." Target ≥80% human ID rate at medium intensity. If enhancement drops below 70%, reject or reduce intensity.

---

## §13 — Rollout Phases (Feeds Phase P Plan-Doc)

12-phase implementation plan, serialized (no split-worktree parallelism). Each phase ships as one PR with green test suite.

**Phase skeleton (refine against umbrella research §9):**

1. **WardEnhancementProfile model + registry** — Pydantic schema, YAML registry of all 15 wards + their invariants, test harness scaffold.
2. **Shared technique-taxonomy library** — Effect-graph node definitions (existing + 4 new: posterize, kuwahara, palette_extract, edge_detect), technique-inventory table, recognizability-metrics computations.
3. **OQ-02 three-bound test harness (per-ward)** — CI gate machinery, per-bound test implementations, audio-profile multiplexing (parallel with HSEA Phase 0).
4. **Ward-through-scrim optical-modulation layer** — Compositor-side depth-conditioned blur/tint/parallax application, API contract fixation, face-obscure-before-scrim integration.
5. **Recognizability-invariant + acceptance-test definitions (batch 1: 5 wards)** — token_pole, album, sierpinski, impingement_cascade, hardm_dot_matrix (high-visibility wards).
6. **Recognizability-invariant + acceptance-test definitions (batch 2: 10 remaining wards)** — hothouse, content, overlay wards.
7. **Spatial-dynamism behavior library** — Parallax, DoF, motion-cadence helpers; per-ward binding confirmation.
8. **Reactive coupling wiring** — Signal → ward-parameter bridges (existing: spend_event, track_change, chat_keyword, stimmung dimensions; new: activity_flip, llm_in_flight).
9. **CBIP annex implementation** — CBIP enhancement profiles (Palette Lineage, Poster Print, Contour Forward), test integration, human spot-check results.
10. **Vitruvian annex implementation** — Vitruvian enhancement profiles (Canon-Grid, Anatomical-Circulation) + token-path patterns (Circulation, φ-climb, Orbital), test integration, human spot-check results.
11. **Production rollout + observability** — Metrics exposure, alerting on OQ-02 bounds / recognizability degradation, operator dashboard.
12. **Retrospective + closure doc** — Lessons learned, handoff to Phase P plan, release notes.

Dependencies: Phase 2 blocks Phase 3; Phase 4 unblocks Phase 5–6 in parallel; Phase 8 can run in parallel with Phase 5–7; Phase 9–10 depend on Phase 8; Phase 11–12 depend on Phase 9–10.

---

## §14 — Open Questions

**Genuine operator decisions needed; delta proposes defaults if not overridden within 24h.**

1. **Recognizability threshold default.** Operator strict (≥95% human ID, edge-IoU ≥0.70) or pragmatic (≥80% human ID, edge-IoU ≥0.65)? *Delta proposes: pragmatic (80%); tuned per-ward during acceptance-test runs.*

2. **Rollout sequencing.** Ship shared taxonomy + OQ-02 harness first, then per-ward profiles batched by category (hothouse, content, overlay)? *Delta proposes: yes; hothouse first (internals, low risk); content last (broadcast-visible, high review bar).*

3. **Enhancement switchability.** Profiles operator-switchable per-ward via programme affordance + director override, or fully director-driven (stimmung-coupled only)? *Delta proposes: operator-switchable via preset affordance; director can override per-round.*

4. **Reverie enhancement scope.** Reverie (the scrim substrate itself) ever enhanced, or always orthogonal? *Delta proposes: orthogonal; scrim is structural ground, not recruited content. Enhancement scope limited to 14 wards.*

5. **HARDM governance on anatomical overlays.** Are meridian lines, chakra nodes, proportional grids on the figure compatible with anti-anthropomorphization, or do they count as "personification"? *Delta proposes: compatible; they emphasize structure (abstract diagram), not subjectivity (character).*

6. **CBIP / Vitruvian vs. other wards.** Should CBIP + Vitruvian annexes ship together in Phase 9–10, or stagger CBIP first to validate framework against simplest surface? *Delta proposes: stagger CBIP first (album is simpler than Vitruvian's token paths); validates framework before token-path complexity.*

---

## §15 — Success Criteria

Concrete, measurable. Tied to ward inventory + operator directive.

**All 15 wards:**
- ✓ Have explicit recognizability-invariant + use-case acceptance test documented in §4 and pinned in test code.
- ✓ Have ≥1 enhancement profile defined (from the 5-family shared taxonomy or per-surface annex).
- ✓ Pass OQ-02 three-bound gates under chosen enhancement profile(s).
- ✓ Have spatial-dynamism profile defined (placement, depth, internal motion, temporal cadence per §6).
- ✓ Pass HARDM anti-anthropomorphization assertion.
- ✓ Are scrim-through rendered (depth-conditioned optical modulation applied).

**Framework:**
- ✓ Technique taxonomy is surface-extensible (new wards plug in without umbrella-spec revision).
- ✓ WardEnhancementProfile schema gating enforced on all enhancement PRs.
- ✓ No regression on HARDM, CVS #8, CVS #16, Ring 2 governance gates.

**Operator experience:**
- ✓ Enhanced wards are visually interesting (operator confirm in human spot-check).
- ✓ All 15 wards remain recognizable at glance (≥80% human ID on canonical test set).
- ✓ Token paths + spatial behaviors are non-manipulative + visible (CVS #8 compliance).
- ✓ Scrim relationship is articulated in one authoritative paragraph; implementation honors it.

---

## §16 — References

**Research documents:**
- `docs/research/2026-04-20-homage-ward-umbrella-research.md` (15-ward table §1, recognizability framework §4.3, scrim answer §5, reactive coupling §6, 12-phase skeleton §9)
- `docs/research/2026-04-20-cbip-vinyl-enhancement-research.md` (5 enhancement families §7, recognizability metrics §4)
- `docs/research/2026-04-20-vitruvian-enhancement-research.md` (2 enhancement families, 5 token-path patterns, spatial-vocabulary prior art §3)
- `docs/research/2026-04-20-nebulous-scrim-three-bound-invariants-triage.md` (OQ-02 three bounds)
- `docs/research/2026-04-20-homage-scrim-1..6-cluster.md` (fishbowl conceit, inner-space definition, depth-modulation grammar)

**Governance:**
- `memory/project_hardm_anti_anthropomorphization.md` (HARDM binding)
- `axioms/registry.yaml` (CVS #8, #16, interpersonal_transparency)
- `docs/governance/consent-safe-gate-retirement.md` (consent-phase visibility gate)

**Codebase:**
- `agents/studio_compositor/*.py` (ward renderers: token_pole.py, album_overlay.py, etc.)
- `shared/homage_*.py` (ward grammar, choreographer, package)
- `config/compositor-layouts/default.json` (layout + ward assignments)
- `agents/effect_graph/` (effect primitives, WGSL compiler)
- `tests/studio_compositor/test_visual_regression_homage.py` (golden-image harness)
- `tests/studio_compositor/test_anti_anthropomorphization.py` (face-cluster property test)

**External authorities:**
- Leonardo da Vinci, *Treatise on Painting* (aerial perspective, sfumato)
- Snellius / Ibn Sahl (refraction law)
- Newton, *Opticks* (chromatic dispersion)
- Kuwahara 1976, Merrillees & Turk 2002 (edge-preserving smoothing)

---

**Word count:** ~4,850 (within 3500–5000-word target).

**Status:** Ready for Phase P (plan-doc authoring) and Phase I (implementation).

