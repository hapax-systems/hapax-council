# HOMAGE Ward Umbrella Research — Image Enhancement, Spatial Dynamism, and Scrim Integration

**Status:** Research / design, operator-directed 2026-04-20.
**Authors:** cascade (Claude Opus 4.7, 1M).
**Audience:** Engineering (delta/beta), operator, specification authority.
**Position:** Master synthesis. Absorbs CBIP technique inventory (2026-04-20-cbip-vinyl-enhancement-research.md); structures for Vitruvian annexes. Cross-links to scrim research bundle (six docs, 2026-04-20).

**Governing anchors:** HOMAGE framework spec (`docs/superpowers/specs/2026-04-18-homage-framework-design.md`), Nebulous Scrim (`docs/research/2026-04-20-nebulous-scrim-design.md` + 6-doc cluster), Ward inventory integration (`docs/research/2026-04-20-homage-scrim-6-ward-inventory-integration.md`), HARDM anti-anthropomorphization, default layout (`config/compositor-layouts/default.json`), effect-graph primitives (`agents/effect_graph/`), CVS governance (#8 non-manipulation, #16 anti-personification).

---

## TL;DR

1. **Umbrella thesis:** Every Homage Ward has a recognizability invariant (property that must remain true for the ward to "read as itself") and a use-case acceptance test (what operator/audience must be able to do). Enhancement and spatial-dynamism work must preserve BOTH.

2. **Scrim answer:** Homage Wards live *through* the scrim—the scrim is a lens/membrane that modulates ward appearance (tint, blur, distortion) per depth band, but wards retain communicative integrity across all layers. Ward boundaries persist; they may appear as partial impressions at deep tiers.

3. **Lead recommendation:** Establish recognizability-preservation framework (§4) as YAML schema in `shared/ward_enhancement_schema.py`, gating every enhancement PR. Ship OQ-02 Phase 1 (Nebulous Scrim three-bound invariants) BEFORE ward-specific enhancements land; it gates brightness ceiling, anti-recognition bounds, and audio-visualizer rejection.

---

## §1 — Ward Inventory and Essential Intent

15 total wards (all in default.json). For each: name, intent, use-case, visual grammar, recognizability invariant.

| Ward | Intent | Use-case | Visual Grammar | Recognizability Invariant |
|---|---|---|---|---|
| **`token_pole`** | Avatar signature glyph; Vitruvian pulse. | Always on; cranium-burst on spend events. | 300×300 image + animated path + glyph + particle explosion. | Vitruvian silhouette + token motion legible; no face features beyond reference image; no face-like particle clustering (HARDM). |
| **`album`** | External operator referent; foundational to listening. | Track-change triggers; visible always. | Cover image + Px437 text + scanlines + dither + border. | Title ≥80% OCR; edge IoU ≥0.65; palette delta-E ≤40 CIELAB; no humanoid bulges or face-tinted scrim. |
| **`stream_overlay`** | Stream chrome (FX, viewers, chat). | Polling 2Hz; updates on change. | 3-line Px437 text: `>>> [FX\|...]`, `>>> [VIEWERS\|N]`, `>>> [CHAT\|...]`. | Text always readable; format preserves `>>>` marker + brackets; no "winking" glyphs. |
| **`sierpinski`** | Algorithmic-composition sketch; geometric ground. | Affordance-recruited; slow-rotating <1 rev/min. | 2-level triangle + 3 YouTube-frame corners + waveform centre. | Triangle geometry recognizable; YouTube frames never form face composite. |
| **`reverie`** | NOT a ward; the scrim itself (RGBA substrate). | Always on; generative process. | 8-pass wgpu vocabulary graph. | Orthogonal to ward enhancement; brightness ceiling (OQ-02 ≤0.55) applies uniformly. |
| **`activity_header`** | Authorship indicator; which activity + rotation mode. | Activity flip triggers; optional 200ms flash. | `>>> [ACTIVITY \| gloss] :: [ROTATION:<mode>]` Px437. | Activity label readable; rotation mode discrete (not emoji); flash not "expression." |
| **`stance_indicator`** | `[+H <stance>]` chip; pulsing legibility surface. | Stance-Hz breathing; flash on stance change. | `[+H stance]` Px437 + breathing pulse. | Stance value readable; `+H` prefix persists; pulsing periodic (not emotional). |
| **`impingement_cascade`** | Top-N perceptual signals with 5s decay; cognitive weave. | Reactive row transit on impingement. | Stacked emissive rows: dot + id + salience bar + family accent. | Salience bars read as magnitude; no face-zone clusters (no eyes at rows 4-6, no mouth at 10-12). |
| **`recruitment_candidate_panel`** | Last-3 recruitments; transient hothouse signal. | Ticker-scroll-in on newest cell. | 3 cells: family token + recency bar + age tail. | Tokens distinct; bars read as time-position (not expression). |
| **`thinking_indicator`** | LLM in-flight breathing dot + label. | Breathing at stance-Hz while in-flight; 6Hz update. | Dot (muted/cyan + breathing) + `[thinking...]` label. | Label readable; breathing periodic (not distress); no anthropomorphization. |
| **`pressure_gauge`** | 32-cell CP437 pressure bar; stimmung readout. | Per-cell at stance-Hz; green→yellow→red. | 32-cell half-block bar + label. | Cell count legible; gradient monotonic (not smile/frown curve). |
| **`activity_variety_log`** | 6-cell ticker, slow scroll; recent activity trace. | Scroll at ~1 cell/5s. | 6 emissive cells, ticker motion. | Cell count constant; scroll legible (not stutter); no facial clusters. |
| **`whos_here`** | `[hapax:1/N]` audience framing; you-are-here broadcast signal. | Viewer-count change triggers refresh. | `[hapax:1/N]` Px437 + emissive 1 and N glyphs. | Count accurate + readable; format persists `hapax:` prefix; no emoji/hand-wave. |
| **`hardm_dot_matrix`** | 16×16 avatar; Hapax's representational form. | Per-cell ripple on recruitment; RD underlay. | 16×16 CP437 blocks (░▒▓█) over RD underlay. | Grid never face-like (Pearson <0.6 with face-mask); cell count constant; glow-through-scrim persistent. |

**North star:** Recognizability invariants gate ALL enhancement proposals. Every PR must cite which row's invariant it preserves.

---

## §2 — Enhancement + Effect-Processing Taxonomy

Organized by transformation class. For each: nodes (existing/NEW), recognizability risk (0–5), HARDM alignment, wards.

### 2.1 Palette transformations
- **Remap** (`colorgrade`): Recolor via lookup table; safe. Risk 1. Wards: album, cover-heavy.
- **Posterize** (`posterize`-NEW + `halftone`): Collapse to 4–8 colors; safe if dither ≤8px. Risk 2. Wards: album, sierpinski.
- **Quantize** (`palette_extract`-NEW): K-means dominant-color extraction; safe, non-destructive. Risk 1. Wards: album.
- **Duotone** (`colorgrade` + `bloom`): Two-color space. Risk 2 (caution: OQ-02). Wards: album, hardm.
- **Index** (`halftone`): mIRC 16-color + dither; safe if dither applied. Risk 1. Wards: album, stream_overlay.

### 2.2 Spatial transformations
- **Edge-detect** (`edge_detect`-NEW + `threshold`): Sobel contours over posterized interior; safe. Risk 2. Wards: album, sierpinski.
- **Halftone** (`halftone`): Ordered/error-diffusion, 4–8px safe; <2px or >16px risks legibility. Risk 1. Wards: album, activity_variety_log.
- **Dither** (`blue_noise_dither`-NEW): Blue-noise perceptually pleasing. Risk 1. Wards: album.
- **RD** (`rd`): Organic patterns; HARDM test required (Pearson <0.6). Risk 2. Wards: hardm, sierpinski-satellite.
- **Drift** (`drift`): UV displacement, amplitude scaled by Z (deep wards move less). Risk 1. Wards: all (depth-modulated).
- **Warp** (`drift` configured): Perlin/curl-noise; max displacement ≤8–16px. Risk 2. Wards: album.

### 2.3 Temporal transformations
- **Feedback** (`feedback`): Ghosting/wake trails; fade-rate per-ward. Risk 1. Wards: all.
- **Decay** (`breath` + temporal multiplier): Exponential envelope. Risk 1. Wards: impingement_cascade, recruitment_candidate.
- **Accretion** (multiple passes): Layering; safe if original topmost. Risk 2. Wards: activity_variety_log, hardm.
- **Strobe** (`breath` hard thresholds): REJECT for indicator wards; <100ms reactive bursts acceptable. Risk 3.

### 2.4 Artifacts
- **Glitch** (`bitplane_scramble`-NEW): <30% frame, <500ms; CBIP reactive-round only. Risk 3. Wards: album.
- **Chromatic aberration** (`chromatic_aberration`): RGB offset 1–3px; readable, retro. Risk 1. Wards: all.
- **Scanlines** (`scanlines`): 2–4px spacing, 5–15% opacity; additive. Risk 0. Wards: album, stream_overlay, text-heavy.
- **Film-grain** (`noise_overlay`): Gaussian/Perlin additive. Risk 1. Wards: album, sierpinski.
- **Bloom** (`bloom`): OQ-02 gated (bound-2). Risk 1 (caution: brightness ceiling). Wards: hardm, activity_header.
- **Kuwahara** (`kuwahara`-NEW): Edge-preserving smoothing; posterized but sharp. Risk 2. Wards: album, sierpinski.

### 2.5 Compositional
- **Collage** (multiple passes): Stack at different alpha; safe if each layer legible. Risk 1.
- **Cutout** (`threshold` + `mask`): Segment foreground/background; apply different transforms. Risk 2.
- **Layer-mask** (mask-driven `composition`): Selective effect per region. Risk 1.
- **Double-expose** (`feedback` + `composition`): Current ≥50% weight; high weight defeats recognition. Risk 2.

---

## §3 — Spatial-Dynamism Grammar

**Placement:** Static (album, sierpinski, reverie), Drifting (impingement_cascade, activity_variety_log), Swapping (none yet), Cycling (signature artefacts).

**Position = salience signal:** Surface wards "declaimed" (high-visibility), near-surface "overheard" (mid-frame, lower luminance), beyond-scrim "peered at" (background).

**Depth dynamics:** Album transits MEDIUM-DEEP on track-change emphasis. Token-pole cranium burst is transient zoom. Parallax via `1/(1+Z)` scaling: near wards move more/faster, deep wards move less/slower. Breathing amplitude <±5% (not >±10%, which reads as distress).

**Ward-to-ward:** Z-order collision avoidance (distinct z_order per surface). Max 2 wards EMPHASIZED simultaneously (§7.1). hardm + impingement_cascade coordinate salience: when cascade >0.85, corresponding hardm cell ripples in sync.

**Ward ↔ cam:** Four corner PiPs rotate per programme-mode. Cameras at beyond-scrim depth (same tier as album). Differential blur + atmospheric-perspective tint per scrim doc §4.

**Internal motion:** token_pole path traversal (navel→cranium, ~30fps), cranium-burst radial explosion; album cover shimmer (sub-Hz); sierpinski sub-1-rev/min rotation (audio-energy modulates centre-void); hardm per-cell ripple wavefronts (ripple leading edge deeper); impingement_cascade rows slide in 5s fade; activity_variety_log ticker ~1 cell/5s.

**Temporal cadence:** token_pole bursts on spend (signal-driven). activity_header flashes on flip (reactive). stance_indicator pulses at stance-Hz (periodic). MIDI clock pulse triggers HARDM row 11 ripple. Chat-keyword bursts trigger scrim moiré density spike. Consent-phase gate disables HOMAGE when needed.

---

## §4 — Recognizability + Use-Case-Intent Framework

### 4.1 Recognizability invariant
Property that must remain true for ward to "read as itself." Per §1 table.

### 4.2 Use-case acceptance test
What operator/audience must be able to do. Per §1 table.

### 4.3 Pydantic schema
`shared/ward_enhancement_schema.py`:
```python
class WardEnhancementProfile(BaseModel):
    ward_id: str  # e.g., "album"
    recognizability_invariant: str  # prose from §1
    recognizability_tests: list[str]  # "ocr_accuracy", "edge_iou", "palette_delta_e", "pearson_face_correlation"
    use_case_acceptance_test: str  # prose from §1
    accepted_enhancement_categories: list[str]  # subset of §2 techniques
    rejected_enhancement_categories: list[str]  # violate invariants
    spatial_dynamism_approved: bool
    oq_02_bound_applicable: bool
    hardm_binding: bool
    cvs_bindings: list[str]  # e.g., ["CVS #8", "CVS #16"]
```

---

## §5 — The Nebulous Scrim Inner-Space Question

### 5.1 Inner space definition
**Plain:** Substrate volume *inside* transparent boundary. Scrim is curved membrane (glass bowl/lens); audience peers through. Inside is liquid medium with measurable depth. Wards inhabit at assigned depth bands. Medium is Reverie 8-pass shader graph (substrate texture). Boundary tints, distorts, refracts per Snell's law and atmospheric perspective.

### 5.2 Ward-scrim relationship
**Answer: Wards live *through* the scrim.**

Scrim is lens/membrane, not container. Ward at Z=0.0 (surface) unmediated; at Z=1.0 (deep) tinted, blurred, distorted by scrim. Scrim is optical interface, not separate layer. Consistent with fishbowl conceit, optical histories (Snell, Newton, da Vinci), and technical implementation (depth-conditioned blur, tint, parallax in compositor).

### 5.3 Scrim modulates appearance
**Yes, uniformly and measurably.**

Three optical cues (scrim doc Pt. 4 §1):
1. **Atmospheric perspective (tint):** Color LERPs toward scrim tint (cyan for BitchX) by ~30% as Z increases. Z=1.0 full blend; Z=0.0 zero blend.
2. **Defocus blur (DoF):** Focus plane Z=0.5 (default, hero-presence). Wards blur proportional to |Z - focus|. Near wards blur approaching camera; deep wards blur receding.
3. **Motion parallax:** Ward amplitude scales by `1/(1+Z)`. Near moves more/faster; deep moves less/slower.

Uniform across all wards. Configuration per-package (BitchX: 30% tint + 2px max blur).

### 5.4 Ward boundaries under scrim
**Persist but appear as partial impressions at deep tiers.**

- **Surface (Z≈0.0):** Sharp, fully opaque, hard edges.
- **Near-surface (Z≈0.3):** 1–2px blur applied, slightly softened.
- **Hero-presence (Z≈0.5):** Focus plane, sharpest.
- **Beyond-scrim (Z≈0.8–1.0):** Heavy blur (4–6px), atmospheric tint; reads as impression not crisp object.

HARDM: 16×16 grid blurs as unit (not per-cell) preserving silhouette; interior cell boundaries soften.

### 5.5 Scrim: meta-ward or categorical different?
**Categorical different.**

Reverie (scrim) is NOT a ward: no CairoSource, no cached surface, no transition_state, not recruited. Always-on, permanent, structural.

**Scrim is medium, not message.** Wards are message. Vitrine (scrim) frames contents (wards). API: compositor reads Reverie from `/dev/shm/hapax-sources/reverie.rgba`, composites as baseline, applies depth-conditioned modulation to each ward, composites in Z-order over scrim.

### 5.6 How scrim informs spatial-dynamism (§3)
Directly: Depth bands are scrim-defined (optical/perceptual). Parallax makes sense because scrim is viscous medium (deep objects move slower due to drag). Brightness ceiling (OQ-02 bound-2, ≤0.65) is scrim property. Signature artefact rotation may couple to scrim's coherence dimension (high coherence → faster rotation; low → slower).

---

## §6 — Reactive Coupling Grammar

Signal → Ward parameter surface → Exposed wards → Coupling strength.

| Signal | Parameter | Wards | Strength |
|---|---|---|---|
| Spend event | token_pole path + burst intensity | token_pole | Strong |
| Track change | album cover + emphasis depth | album | Strong |
| Chat keyword burst | stream_overlay density + scrim moiré | stream_overlay + reverie | Medium |
| Activity flip | activity_header flash + stance_indicator Hz | both | Medium |
| LLM in-flight | thinking_indicator breathing | thinking_indicator | Medium |
| Stimmung dims | pressure_gauge colors + hardm ripple speed | both | Medium |
| Audio energy | sierpinski waveform + reverie feedback fade | both | Weak |
| Operator attention (IR + desktop) | pressure_gauge scrim-parting radius | pressure_gauge | Weak |
| Impingements | cascade row stack + salience bar | impingement_cascade | Strong |
| Recruitment | recruitment ticker + hardm ripple seed | both | Medium |
| Viewer-count change | whos_here label + emphasis | whos_here | Weak |

**All signals existing; no new sources invented.**

---

## §7 — Governance Cross-Check

| Invariant | Axiom | Violation | Enforcement |
|---|---|---|---|
| HARDM anti-anthropomorphization | CVS | Face clusters (Pearson >0.6), face-bulge under depth. | `test_anti_anthropomorphization.py`, property-based, reject if fails. |
| CVS #8 non-manipulation | CVS | Reward face (smiling), punishment face (frowning). | Code review + operator spot-check on regression goldens. |
| CVS #16 anti-personification | CVS | Emoji, emoticon, first-person character cues. | Code review + regression goldens. |
| Ring2 WARD classifier | Governance | Ad, influencer-ified, copywriting (unlikely). | Inherits existing WARD classifier. |
| Consent-phase visibility | `interpersonal_transparency` | Persistent state about non-operator persons. | Consent gate in AffordancePipeline; HOMAGE disabled in consent-safe layout. |
| Recognizability invariant | Umbrella §4 | Enhancement alters essential intent. | WardEnhancementProfile schema; test harness confirms acceptance test passes. |
| OQ-02 brightness (bound-2) | OQ-02 | Composited brightness >0.65 under scrim + bloom. | New CI gate: brightness oracle at compose, reject if exceeded. Precedent: D-25 (commit 863509ac9). |
| OQ-02 anti-recognition (bound-1) | OQ-02 | Content easily recognized as face. | Face-recognition detector (CLIP/InsightFace, threshold 0.2); reject if confidence >0.3. |

---

## §8 — Sibling Research Cross-Reference

**CBIP vinyl enhancement research** (EXISTS): Enumerates CBIP-specific constraints (hermeneutic moves: identification, contextualization, argument, hand-off; recognizability metrics: ≥80% OCR, edge IoU ≥0.65, delta-E ≤40; chess-boxing cadence). Technique inventory §2.1–2.4 (poster traditions, constrained-sampling, signal-processing, hip-hop lineages) CONSISTENT with §2 above but CBIP-contextualized. Recommendations: posterize, kuwahara, halftone, palette-extract primary moves; glitch reactive-bursts only.

**Vitruvian enhancement research** (NOT YET): Will cover token_pole-specific enhancements (particle systems, path animation, glyph transforms). Should reuse §2 techniques; focus on spatial motion not static image processing. Coordinate with §3 spatial-dynamism.

**Consistency:** CBIP technique inventory is subset of §2 shared taxonomy. CBIP hermeneutic moves (identification/contextualization/argument/hand-off) are upstream context (why we want enhancement); §4 metrics are downstream gate (how we validate it worked). Both necessary; neither sufficient alone.

**Structure recommendation:** Collapse CBIP and Vitruvian into 1–2 page annexes reusing §2 taxonomy without duplication, adding surface-specific constraints, referencing §4 framework, plugging tests into schema. Umbrella doc is single source of truth for shared grammar.

---

## §9 — Umbrella Spec Skeleton

**Phase 1: Framework + gating**
- Implement WardEnhancementProfile schema.
- Authorize OQ-02 Phase 1 (metric authoring + oracle).
- Commit recognizability invariants into schema.

**Phases 2–3: Album enhancements** (CBIP-primary)
- Implement palette/spatial transformations (§2.1–2.2).
- Confirmation tests (OCR, edge IoU, palette delta-E).

**Phases 4–5: Temporal + artifacts**
- Implement feedback, decay, glitch, chromatic_aberration, film-grain.
- Enforce glitch-only-in-reactive (<30% frame, <500ms).

**Phases 6–7: Spatial-dynamism**
- Parallax amplitude scaling (`1/(1+Z)`).
- Focus-plane depth-of-field blur.
- Atmospheric-perspective tint.

**Phases 8–9: Ward-specific**
- Album: CBIP enhancements + hermeneutic moves.
- Vitruvian (token_pole): particles + path variants.

**Phases 10–11: Integration + rehearsal**
- Composer orchestration under per-programme presets.
- Affordance-pipeline recruitment.
- Rehearsal gate + operator visual-acceptance test.

**Phase 12: Governance + observability**
- OQ-02 completion (bounds at compose time).
- Prometheus observability.
- Research-condition updates if needed.

---

## §10 — Open Questions for Operator

1. **Scrim answer confirmation (§5.2):** Approve "wards live *through* the scrim" or propose alternative?
2. **Enhancement vs. spatial-dynamism priority:** Which wards first? Recommend: album (enhancement), token_pole (spatial-dynamism), hardm (both parallel).
3. **Recognizability threshold:** Default 80% quantitative metrics acceptable for all wards or adjust per-ward?
4. **Enhancement profile switchability:** Operator-selectable per programme, director-driven, or mixed?
5. **Reverence ceiling:** Any wards that must NEVER be enhanced? Recommend: reverie (orthogonal).
6. **OQ-02 Phase 1 launch:** Prioritize before any ward-specific enhancement work?

---

## §11 — Lead Recommendation

**Ship OQ-02 Phase 1 (Nebulous Scrim three-bound-invariants) before any ward-specific enhancement implementation.** The three bounds (anti-recognition, anti-opacity, anti-audio-visualizer) gate EVERY future scrim effect and enhancement chain. OQ-02 Phase 1 is small (JS=3) and unblocks the entire scrim-bundle epic (six research docs currently un-implemented). Parallel: Establish WardEnhancementProfile schema as gate-keeping framework. These two moves provide upper-bound (OQ-02 invariants) and per-ward tracking (enhancement schema) for safe, incremental shipping.

---

## §12 — Sources

**Hapax codebase:** default.json, cairo_sources/__init__.py, ward implementations, homage_package.py, CBIP research, fishbowl conceit, ward inventory doc, HOMAGE spec, scrim design + 6 docs, OQ-02 triage, HARDM memory, effect_graph.

**External:** da Vinci (*Treatise on Painting*, aerial perspective), Snellius/Ibn Sahl (refraction), Newton (*Opticks*, chromatic dispersion), Kuwahara (1976), Merrillees & Turk (2002), OEN Sensation & Perception Ch. 9, Piter Pasma (depth cues), CG Spectrum (*Spider-Verse*).

