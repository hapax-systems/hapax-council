# HOMAGE Ward Umbrella Research — Image Enhancement, Spatial Dynamism, and Scrim Integration

**Status:** Research / design, operator-directed 2026-04-20.
**Authors:** cascade (Claude Opus 4.7, 1M).
**Audience:** Engineering (delta/beta), operator, specification authority.
**Position:** Master synthesis. Absorbs CBIP technique inventory (2026-04-20-cbip-vinyl-enhancement-research.md); structures framework for Vitruvian annexes. Cross-links to scrim research bundle (six docs, 2026-04-20). **Supersedes/absorbs:** parallel CBIP and Vitruvian technique inventories.

**Governing anchors:** HOMAGE framework spec (`docs/superpowers/specs/2026-04-18-homage-framework-design.md`), Nebulous Scrim (`docs/research/2026-04-20-nebulous-scrim-design.md` + 6-doc cluster), Ward inventory integration (`docs/research/2026-04-20-homage-scrim-6-ward-inventory-integration.md`), HARDM anti-anthropomorphization, default layout (`config/compositor-layouts/default.json`), effect-graph primitives (`agents/effect_graph/`), CVS governance (#8 non-manipulation, #16 anti-personification).

---

## TL;DR

1. **Umbrella thesis:** Every Homage Ward has a recognizability invariant (the property that must remain true for the ward to "read as itself") and a use-case acceptance test (what operator/audience must be able to do with it to fulfill its role). Enhancement and spatial-dynamism work must preserve BOTH without exception. They are non-negotiable gates.

2. **Scrim answer:** Homage Wards live *through* the scrim—the scrim is a lens/membrane (per Snell's law and atmospheric perspective) that modulates ward appearance (tint, blur, distortion) per depth band, but wards retain communicative integrity across all layers. Ward boundaries persist; they may appear as partial impressions at deep tiers. The scrim IS permanent substrate (Reverie); wards are transient recruited content.

3. **Lead recommendation:** Establish recognizability-preservation framework (§4) as YAML schema in `shared/ward_enhancement_schema.py`, gating every enhancement PR. Ship OQ-02 Phase 1 (Nebulous Scrim three-bound invariants from triage doc `docs/research/2026-04-20-nebulous-scrim-three-bound-invariants-triage.md`) BEFORE ward-specific enhancements land; it gates brightness ceiling (≤0.65 absolute under scrim), anti-recognition bounds, and audio-visualizer rejection that all enhancements must satisfy.

---

## §1 — Ward Inventory and Essential Intent

15 total Homage Wards (all assigned in default.json as of 2026-04-20, per ward inventory doc §2). For each: ward name, essential communicative intent, current use-case, current visual grammar, recognizability-invariant candidate. This table is the umbrella's north star; every subsequent enhancement proposal refers back to it.

| Ward | Intent | Use-case | Visual Grammar | Recognizability Invariant |
|---|---|---|---|---|
| **`token_pole`** | Avatar signature glyph; Vitruvian-figure-based. Token traversal (navel→cranium) is Hapax's pulse. | Always on; cranium-arrival particle burst on spend events (token_pole.py:73-117). | 300×300 Vitruvian PNG image + animated token path + glyph + particle explosion. | Vitruvian silhouette + token motion must remain legible; face must not acquire features beyond public-domain reference image (HARDM binding); particle burst must never resolve into face-like clustering. |
| **`album`** | External operator referent. What the audience came to see through the scrim. Album cover is foundational to listening experience. | Track-change triggers cover refresh; visible always (even when MIDI idle), per ca0e955cc commit. | Image (cover) + Px437 attribution text below + scanlines + dither shadow + 2px border (album_overlay.py:1-100). | Album title ≥80% OCR round-trip accuracy; dominant contours (figure/ground) edge IoU ≥0.65; palette delta-E ≤40 CIELAB; cover must not acquire humanoid bulges or face-tinted scrim modulation. |
| **`stream_overlay`** | Stream chrome. FX preset, viewer count, chat status. Status inscribed on the scrim's outface; must read clearly. | Polling at 2Hz; visible change only on chat/preset/viewer transition. | 3-line Px437 text strip: `>>> [FX\|...]`, `>>> [VIEWERS\|N]`, `>>> [CHAT\|...]` (stream_overlay.py:64-89). | Text must remain readable at all times; format must preserve `>>>` line-start marker and bracket structure; glyphs must not "wink" or "blink" on update (anti-anthropomorphization gate). |
| **`sierpinski`** | Algorithmic-composition sketch. Pure geometric ground. Most foundational of wards (composites before GL chain per sierpinski_renderer.py:3-6). | Registered but unassigned in default.json; affordance-recruited when impingement→reverie satellite path activates. Slow-rotating at <1 rev/min. | 2-level triangle with 3 YouTube-frame corner regions + waveform centre (sierpinski_renderer.py:1-13). | Triangle geometry must remain recognizable; YouTube frames must never form "face" composite; geometric purity preserved under any colorgrade or distortion effect. |
| **`reverie`** | NOT a ward; the Nebulous Scrim itself. RGBA generative substrate. The 8-pass wgpu vocabulary graph IS the scrim. | Always on; permanent generative process. Recruitment modulates it; content composites into it; it does not "appear" or "disappear." | RGBA frame written to `/dev/shm/hapax-sources/reverie.rgba` by hapax-imagination daemon (8-pass shader graph: noise→rd→color→drift→breath→feedback→content_layer→postprocess). | Reverie is orthogonal to ward enhancement; its role is to establish the depth-field substrate that wards relate to. OQ-02 brightness ceiling (≤0.55 under BitchX package) applies uniformly. |
| **`activity_header`** | Authorship indicator. Which activity the director is in, with optional rotation mode token. On-frame authorship surface. | Toggles at activity flip; optional 200ms inverse-flash (legibility_sources.py:122-125). | `>>> [ACTIVITY \| gloss] :: [ROTATION:<mode>]` — Px437, optional flash (legibility_sources.py:19-20). | Activity label must remain legible; rotation mode must be readable as a discrete token (not stylized into emoji or speech-bubble); flash timing must not read as "expression" (anti-anthropomorphization). |
| **`stance_indicator`** | `[+H <stance>]` chip. Tiny (100×40), top-right. Pulsing. Always-visible legibility surface. | Pulsing at `STANCE_HZ` rate (hothouse_sources.py:46-57); flash on stance change. | `[+H stance]` — Px437 with breathing pulse (legibility_sources.py:21, hothouse_sources.py:46-57). | Stance value must remain legible; `+H` prefix must persist; pulsing must remain periodic and not read as "emotional expression"; glyph must not encode emotional tone via stylization. |
| **`impingement_cascade`** | Top-N perceptual signals with 5s lifetime decay (hothouse_sources.py:287). The cognitive weave; internal-state readout. | Reactive: rows transit on join-message. Slow slide-in / 5s lifetime fade. | Stacked emissive rows: dot + Px437 id + 8-cell salience bar + family accent (hothouse_sources.py:271-285). | Salience bars must remain interpretable as magnitude; family accent colors must not drift toward face-zone (no eye clusters at rows 4-6, no mouth cluster at rows 10-12); decay envelope must remain exponential (not sudden vanish). |
| **`recruitment_candidate_panel`** | Last-3 recruitments; transient internal-state indicator. | Ticker-scroll-in entry on newest cell (hothouse_sources.py:430-432). Near-surface depth (operator-tools layer in META mode). | 3 cells, each: family token + 16-point recency bar + age tail (hothouse_sources.py:425-560). | Family tokens must remain distinct (no clustering); recency bars must read as time-position (not expression); age tail must decay without sudden cutoff. |
| **`thinking_indicator`** | Tiny breathing dot + `[thinking...]` label. LLM in flight signal. | Breathing at `stance_hz(stance) * SHIMMER_HZ_DEFAULT` while in-flight (hothouse_sources.py:566-571); 6Hz update rate. | Single dot (idle: muted; active: cyan + breathing) + `[thinking...]` label (hothouse_sources.py:563-571). | Label must remain readable; dot breathing must remain periodic (not read as distress); glyph must not anthropomorphize the cognitive process. |
| **`pressure_gauge`** | 32-cell CP437 half-block pressure bar. Stimmung operator-state readout. | Per-cell response at stance-Hz; color interpolates green→yellow→red (hothouse_sources.py:26-27). | 32-cell CP437 half-block bar with green→yellow→red interpolation + Px437 label (hothouse_sources.py:26-27). | Cell count must remain legible (no merging); color gradient must remain monotonic (not smile/frown curve); threshold colors must not encode emotional tone. |
| **`activity_variety_log`** | 6-cell ticker, slow scroll. Trace of Hapax's recent activity. Overheard, not declaimed. | 6 emissive cells, ticker-scroll motion (~1 cell/5s). | 6 emissive cells, ticker-scroll motion (hothouse_sources.py:28-29). | Cell count must remain constant; scroll speed must remain legible (not stutter or rush); cells must not form clusters that read as "facial landmarks." |
| **`whos_here`** | `[hapax:1/N]` audience framing. The "you-are-here" of the broadcast. Surface inscription. | Viewer-count change triggers label refresh (hothouse_sources.py:77). | `[hapax:1/N]` Px437 with emissive 1 and N glyphs (hothouse_sources.py:30-31). | Count must remain accurate and readable; format must persist `hapax:` prefix; glyphs must not acquire emoji or hand-wave interpretation (anti-anthropomorphization). |
| **`hardm_dot_matrix`** | 16×16 dot-grid avatar. Hapax's representational form. Glow-through-fabric character (bloom asymmetry per scrim doc §8.2). | Per-cell ripple at family recruitment events (hardm_source.py:71-81); RD underlay at 1 step/tick (hardm_source.py:3-6). | 16×16 grid of CP437 block characters (hardm_source.py:55: `(" ", "░", "▒", "▓", "█")`) over reaction-diffusion underlay. | Grid never resolves into face clusters (Pearson correlation with face-mask <0.6, per hardm_source.py property-based test); cell count constant; RD dynamic preserved; glow-through-scrim character (bloom asymmetry) non-negotiable. |

**Load-bearing notes:**
- All wards except `reverie` pass through the scrim as a function of depth band (scrim doc §6 + fishbowl conceit).
- `reverie` IS the scrim substrate; it does not "pass through" itself; it is structural, not recruited.
- Recognizability invariants are the north star for every PR in the umbrella spec. Every enhancement proposal must cite which row's invariant it preserves (or risk rejection at review).

---

## §2 — Enhancement + Effect-Processing Taxonomy

Cross-ward technique inventory. Organized by transformation class. For each technique: effect-graph node(s) required (existing vs. new), recognizability-risk score (0 low → 5 high), HARDM alignment, which wards best fit.

### 2.1 Palette transformations (color remapping, non-destructive)

| Technique | Nodes | Risk | HARDM | Wards | Notes |
|---|---|---|---|---|---|
| **Remap** | `colorgrade` (existing) | 1 | Safe | album, cover-heavy | Recolor via lookup table without destroying contours. Greyscale→sepia, invert, etc. Safe if limits applied (OQ-02 brightness ceiling). Test: visual regression golden. |
| **Posterize** | `posterize` (NEW) + `halftone` (existing) | 2 | Safe | album, sierpinski | Collapse palette to 4–8 colors via ordered Bayer dither. Recognizable if dither size ≤8px. CBIP-aligned. Test: SSIM ≥0.7 vs original. |
| **Quantize** | `palette_extract` (NEW) | 1 | Safe | album | K-means dominant-color extraction; render as swatch grid. Non-destructive; serves CBIP contextualization move. |
| **Duotone** | `colorgrade` + `bloom` | 2 | Caution (OQ-02) | album, hardm | Two-color space remapping. Risk: if colors perceptually similar, contrast collapses. Mitigation: manual safeguard per-preset. HARDM risk: reject if produces "face palette." |
| **Index** | `halftone` (existing, as constrained colormap) | 1 | Safe | album, stream_overlay (text) | Map to mIRC 16-color palette. Safe with dithering. Test: OCR ≥90% on text. |

### 2.2 Spatial transformations (contour/structure-aware)

| Technique | Nodes | Risk | HARDM | Wards | Notes |
|---|---|---|---|---|---|
| **Edge-detect** | NEW `edge_detect` + optional `threshold` | 2 | Safe | album, sierpinski | Sobel/Laplacian contours; composite edges over posterized interior. Recognizability high (contours preserved). CBIP identification-move primer. |
| **Halftone** | `halftone` (existing) | 1 | Safe | album, activity_variety_log | Ordered or error-diffusion halftone. 4–8px safe; <2px or >16px risks legibility. CBIP-aligned (screen-print aesthetic). |
| **Dither** | NEW `blue_noise_dither` or `halftone` (configurable) | 1 | Safe | album | Perceptually pleasing noise-based dithering. Lower visual noise than Bayer. CBIP precedent: cassette xerox. |
| **RD** | `rd` (existing, in Reverie pass-2) | 2 | Caution | hardm (underlay), sierpinski (satellite) | Organic-looking patterns. Risk: if coupled to motion without parameter bounds, cells cluster into face-like regions. HARDM test required (Pearson <0.6). RD already live on HARDM as underlay; used cautiously. |
| **Drift** | `drift` (existing, Reverie pass-3) | 1 | Safe | all wards (depth-modulated) | Wobble/heat-haze displacement. Amplitude scales by ward Z-depth (deep wards larger displacement, slower tempo). Non-destructive; reads as "liquid medium inertia" per fishbowl conceit (scrim doc Pt. 4 §2). |
| **Warp** | `drift` (alias-configurable) or NEW `flow_field` | 2 | Caution | album | Perlin/curl-noise driven displacement. Risk: unbounded warp radius blurs contours, defeats recognition. Mitigation: max displacement ≤8–16px. Test: Sobel edge IoU ≥0.65 vs original. |

### 2.3 Temporal transformations (accumulation, decay, periodicity)

| Technique | Nodes | Risk | HARDM | Wards | Notes |
|---|---|---|---|---|---|
| **Feedback** | `feedback` (Reverie pass-5, ping-pong FBO) | 1 | Caution (OQ-02) | all wards (per-ward fade-rate) | Re-blend previous frame at fade-rate. Produces ghosting/wake trails. Risk: slow fade-rate persists artifacts, confuses recognition. Mitigation: fade-rate tuned per-ward (fast for reactive, slower for deep). OQ-02 governs saturation ceiling. |
| **Decay** | `breath` (Reverie pass-4) + temporal multiplier | 1 | Safe | impingement_cascade, recruitment_candidate | Exponential decay on salience/intensity. Already live on cascade (5s lifetime). No recognition risk if envelope monotonic. |
| **Accretion** | Multiple render passes, alpha-blending | 2 | Safe | activity_variety_log, hardm (ripple waves) | Stack multiple frames at different alpha. Recognizable if original always topmost layer. |
| **Strobe** | `breath` (with hard on/off thresholds) | 3 | Caution (reject for indicators) | stance_indicator, thinking_indicator (NOT intended) | Strobing text/faces triggers photosensitivity + reads as "emotional blinking." REJECT as primary effect. <100ms reactive bursts acceptable. |

### 2.4 Artifact grammars (retro-aesthetic, signal-degradation)

| Technique | Nodes | Risk | HARDM | Wards | Notes |
|---|---|---|---|---|---|
| **Glitch** | NEW `bitplane_scramble` or `frame_shuffle` | 3 | Caution | album (reactive bursts only) | Selective bit-plane inversion / scan-line interruption. Risk: >70% frame defeats recognition. Mitigation: <30% frame, <500ms duration. CBIP-aligned only in reactive (boxing) rounds. |
| **Chromatic aberration** | `chromatic_aberration` (existing, in Reverie) | 1 | Safe | all wards | RGB channels offset 1–3px. Readable; retro-video aesthetic. Already used in Reverie as scrim-boundary effect (fishbowl conceit §2.3). |
| **Scanlines** | `scanlines` (existing) | 0 | Safe | album, stream_overlay, all text-heavy | Horizontal lines 2–4px spacing, 5–15% opacity. Purely additive; does not alter content. CRT aesthetic; already live on album. |
| **Film-grain** | `noise_overlay` (existing) | 1 | Safe | album, sierpinski | Gaussian or Perlin noise overlay at controlled amplitude. Non-destructive. Already live on Reverie and album. |
| **Bloom** | `bloom` (existing, Reverie) | 1 | Caution (OQ-02 bound-2) | hardm, activity_header (emissive sources) | Bloom on bright areas. Risk per OQ-02: saturation on deep wards can exceed ceiling if not gated. Mitigation: cap bloom contribution to preserve ≤0.65 absolute brightness. |
| **Kuwahara** | NEW `kuwahara` | 2 | Safe | album, sierpinski | Edge-preserving smoothing (Kuwahara 1976, Merrillees & Turk 2002). Classifies each pixel into 4 quadrants, reports mean of lowest-variance quadrant. Posterized but sharp contours. Recognizable; CBIP-aligned (painterly). Cost O(W×H×k²) but parallelizable. |

### 2.5 Compositional grammars (multi-layer, selective)

| Technique | Nodes | Risk | HARDM | Wards | Notes |
|---|---|---|---|---|---|
| **Collage** | Multiple `composition` passes | 1 | Safe | activity_variety_log (as history) | Stack multiple ward frames at different opacities. Recognizable if each layer individually legible. CBIP analogue: De La Soul / Madlib sampled-cover aesthetic (transparency principle). |
| **Cutout** | `threshold` + `mask` (compositing) | 2 | Safe | album | Segment image into foreground/background; apply different transforms to each. Recognizable if foreground (cover art) remains hero layer. |
| **Layer-mask** | Mask-driven `composition` | 1 | Safe | album, sierpinski | Apply transformation to masked region only (e.g., text area, background). Selective enhancement preserves core recognition. |
| **Double-expose** | `feedback` + `composition` at controlled ratio | 2 | Safe | album (deliberative round only) | Composite current + previous frame at blend ratio. Recognizable at ≤0.5 ratio (current ≥50% weight). Risk: high blend ratio defeats recognition. |

---

## §3 — Spatial-Dynamism Grammar

Catalog of ward movement, depth interaction, temporal cadence. (Covers §3.1–§3.6 from operator directive.)

**Placement dynamics:** Static (album, sierpinski, reverie); Drifting (impingement_cascade rows slide in, 5s decay; activity_variety_log ticker-scroll); Swapping (none yet); Cycling (signature artefact rotation, HOMAGE Phase 8).

**Position = salience signal:** Surface wards "declaimed" (high-visibility, legibility tier); near-surface wards "overheard" (mid-frame, lower luminance, internal state); beyond-scrim wards "peered at" (background, audience gazes through scrim to see them).

**Depth dynamics:** Album transits MEDIUM-DEEP for emphasis on track-change (scrim doc §6). Token-pole cranium-arrival particle burst is transient zoom + emphasis. Parallax via `1/(1+Z)` amplitude scaling: near wards (hero-presence, Z≈0.5) move with full amplitude; deep wards (beyond-scrim, Z≈0.8–1.0) move with ~50% amplitude, slower tempo. Breathing amplitude must remain <±5% scale variation (>±10% reads as distress).

**Ward-to-ward interactions:** Z-order collision avoidance (distinct z_order per surface in default.json). Max 2 wards EMPHASIZED simultaneously (scrim doc §7.1); third requesting emphasis evicts oldest. hardm + impingement_cascade coordinate: when cascade salience >0.85, corresponding HARDM cell ripples in sync (scrim doc §7.3).

**Ward ↔ cam:** Four corner PiPs rotate per programme-mode. Cameras composited at beyond-scrim depth (same tier as album, sierpinski). Differential blur + atmospheric-perspective tint applied (scrim doc §4.1, §4.3).

**Internal motion:** token_pole path traversal (navel→cranium, ~30fps per frame), cranium-burst radial explosion; album cover shimmer (sub-Hz, nearly static); sierpinski sub-1-rev/min rotation (audio-energy modulates centre-void intensity); hardm per-cell ripple wavefronts (ripple leading edge slightly deeper than trailing edge); impingement_cascade rows slide-in 5s fade; activity_variety_log 6-cell ticker ~1 cell/5s.

**Temporal cadence:** token_pole cranium bursts on spend events (signal-driven). activity_header flashes on activity flip (reactive). stance_indicator pulses continuously at stance-Hz (periodic, breath-like). MIDI clock pulse at beat positions triggers HARDM row 11 ripple. Chat-keyword bursts trigger moiré density spike on scrim around stream_overlay. Consent-phase visibility gate disables HOMAGE entirely when active.

---

## §4 — Recognizability + Use-Case Preservation Framework

Every Homage Ward has two properties that must survive enhancement and spatial-dynamism work without exception:

**4.1 Recognizability invariant:** Property that must remain true for a ward to "read as itself." Enumerated in §1 table per ward.

**4.2 Use-case acceptance test:** What operator or audience must be able to do with the ward for it to fulfill its role. Enumerated in §1 table per ward.

**4.3 Proposed framework shape (Pydantic schema):**
```python
class WardEnhancementProfile(BaseModel):
    """Gate-keeping schema for ward enhancement work.
    Every PR touching a ward's visual grammar must:
    (1) cite the ward's recognizability_invariant
    (2) confirm the enhancement preserves it
    (3) cite the use_case_acceptance_test
    (4) run the test; document results (metric or human spot-check)
    (5) get operator approval if test is marginal
    """
    ward_id: str  # "album"
    recognizability_invariant: str  # prose from §1
    recognizability_tests: list[str]  # "ocr_accuracy", "edge_iou", "palette_delta_e", "pearson_face_correlation"
    use_case_acceptance_test: str  # prose from §1
    acceptance_test_harness: str  # path to test script
    accepted_enhancement_categories: list[str]  # subset of §2 safe for this ward
    rejected_enhancement_categories: list[str]  # violate invariants
    spatial_dynamism_approved: bool
    oq_02_bound_applicable: bool
    hardm_binding: bool
    cvs_bindings: list[str]  # "CVS #8", "CVS #16"
```

**Governance precedent:** Reuse `shared/consent.py::ConsentContract` pattern for approval gating. Reuse `shared/axiom_*.py` for invariant validation. Extend `tests/studio_compositor/test_visual_regression_homage.py` for golden-image comparison. Extend `tests/studio_compositor/test_anti_anthropomorphization.py` for face-cluster property-based tests.

---

## §5 — The Nebulous Scrim Inner-Space Question

### 5.1 What is the Nebulous Scrim inner space?

**Plain statement:** Substrate volume *inside* the transparent boundary. The scrim is a curved membrane (glass bowl or lens, per fishbowl conceit) through which the audience peers. Inside is a liquid medium of measurable depth (Z ∈ [0.0, 1.0]). Wards inhabit that medium at assigned depth bands. The medium is the generative "stuff" (the Reverie 8-pass shader graph, treated as substrate texture, not a separate visual layer). The boundary tints, distorts, and refracts light per Snell's law and atmospheric perspective (da Vinci sfumato).

Boundary is perceptual, not geometric. Wards at surface register as crisp marks on membrane. Wards at deep tiers register as impressions *through* the medium. The space *inside* is unified—all wards share the same depth-coordinate system.

### 5.2 Do Homage Wards live inside, alongside, or through the scrim?

**Committed answer: Wards live *through* the scrim.**

The scrim is a lens/membrane that modulates ward appearance as a function of depth and distance from observer. A ward at Z=0.0 (surface) appears unmediated. A ward at Z=1.0 (deep) appears tinted, blurred, distorted by the scrim. The scrim is the optical interface, not a container and not a separate layer.

**Defense against alternatives:**
- **Inside (container):** If wards lived inside, they would be occluded exiting the container. But wards are pinned to fixed Z-bands; they never leave. Rejected.
- **Are the scrim (composite):** If wards were the scrim, they would be structural and permanent. But wards are recruited and transient. Rejected.
- **Alongside (parallel layer):** If parallel, wards would be either always-on-top (defeating depth) or underneath (defeating legibility). Rejected.
- **On (surface marking):** Implies 2D contact. Wards have depth. Rejected.
- **Through (lens model):** **Adopted.** Consistent with fishbowl conceit, optical histories (Snell, Newton, da Vinci), and technical implementation (depth-conditioned blur, tint, parallax).

### 5.3 Does the scrim modulate ward appearance?

**Answer: Yes, uniformly and measurably.**

Three optical cues (scrim doc Pt. 4 §1):
1. **Atmospheric perspective (tint):** Ward color LERPs toward scrim tint (cyan for BitchX) by ~30% as Z increases. Z=0.0 zero blend; Z=1.0 full scrim-tint blend.
2. **Defocus blur (DoF):** Focus plane default Z=0.5 (hero-presence tier). Wards blur proportional to |Z - focus|.
3. **Motion parallax:** Ward amplitude scales `1/(1+Z)`. Near wards move more/faster; deep wards move less/slower.

Modulation is uniform across all wards, configured per-package (BitchX: 30% tint + 2px max blur).

### 5.4 Ward boundaries under scrim

Persist but appear as partial impressions at deep tiers:
- **Surface (Z≈0.0):** Sharp, fully opaque, hard edges.
- **Near-surface (Z≈0.3):** 1–2px blur; slightly softened.
- **Hero-presence (Z≈0.5):** Focus plane; sharpest.
- **Beyond-scrim (Z≈0.8–1.0):** Heavy blur (4–6px), atmospheric tint; reads as impression.

HARDM: 16×16 grid blurs as unit preserving silhouette; interior cell boundaries soften.

### 5.5 Scrim: meta-ward or categorical different?

**Categorical different.** Reverie is NOT a ward: no CairoSource, no cached surface, no transition_state, not recruited. Always-on, permanent, structural. The scrim is the medium, not the message. Wards are the message.

**API contract:** Compositor reads Reverie frame from `/dev/shm/hapax-sources/reverie.rgba` (written by Reverie daemon), composites as baseline, applies depth-conditioned modulation to each ward, composites in Z-order over scrim. Scrim does not know about wards; wards read scrim's depth-modulation parameters from compositor config.

### 5.6 How scrim informs spatial-dynamism (§3)

Directly: Depth bands are scrim-defined (optical/perceptual categories, not arbitrary). Parallax makes sense because scrim is viscous medium (deep objects move slower due to drag). Brightness ceiling (OQ-02 bound-2, ≤0.65 absolute) is scrim property. Signature artefact rotation may couple to scrim's coherence dimension (high coherence → faster rotation; low → slower).

---

## §6 — Reactive Coupling Grammar

Signal → Ward parameter → Wards → Strength. All signals existing; no new sources invented.

Per scrim doc §6 table and ward inventory doc §6 per-ward audio coupling: spend events modulate token_pole path + burst intensity (strong). Track changes modulate album cover + emphasis depth (strong). Chat-keyword bursts modulate stream_overlay density + scrim moiré (medium). Activity flips modulate activity_header flash + stance_indicator Hz (medium). LLM in-flight modulates thinking_indicator breathing (medium). Stimmung dimensions modulate pressure_gauge colors + hardm ripple speed (medium). Audio energy modulates sierpinski waveform + reverie feedback fade (weak). Operator attention (IR hand + desktop focus) modulates pressure_gauge scrim-parting radius (weak). Impingements modulate cascade row stack + salience bar (strong). Recruitment events modulate recruitment ticker + hardm ripple seed (medium). Viewer-count changes modulate whos_here label + emphasis (weak).

---

## §7 — Governance Cross-Check

Eight umbrella-level guards. Every enhancement must preserve ALL.

| Invariant | Axiom | Violation | Enforcement |
|---|---|---|---|
| HARDM anti-anthropomorphization | CVS persona | Face clusters (Pearson >0.6), face-bulge depth modulation, refraction halos producing head-silhouette | `test_anti_anthropomorphization.py`, property-based hypothesis test, runs every PR. Reject if any ward fails. |
| CVS #8 non-manipulation | CVS axiom | Operant-conditioning reward grammars (smiling gradient on pressure_gauge, winking on stream_overlay), punishment faces (frowning) | Manual code review + operator spot-check on regression goldens. |
| CVS #16 anti-personification | CVS axiom | Enhancement renders indicator as emoji, emoticon, or first-person-character cue | Code review (grep emoji/emoticon patterns); regression goldens. |
| Ring 2 WARD classifier | Governance | Enhancement reads as product ad, influencer-ified content, copywriting (unlikely for Homage) | Inherits existing WARD classifier; no new checks. |
| Consent-phase visibility | `interpersonal_transparency` axiom | Enhancement or spatial-dynamism introduces persistent state about non-operator persons | Consent gate in AffordancePipeline; HOMAGE disables entirely in consent-safe layout. |
| Recognizability invariant | Umbrella §4 | Enhancement alters essential intent (title unreadable, shape unrecognizable, grid face-like) | WardEnhancementProfile schema gating; test harness confirms acceptance test passes. Operator approval if marginal. |
| OQ-02 brightness (bound-2) | OQ-02 triage | Composited brightness >0.65 absolute under scrim + bloom | New CI gate: brightness oracle at compose time; reject if exceeded. Precedent: D-25 (commit 863509ac9). |
| OQ-02 anti-recognition (bound-1) | OQ-02 triage | Content easily recognized as face under any enhancement chain | Face-recognition detector (CLIP/InsightFace, threshold 0.2); reject if confidence >0.3. |

---

## §8 — Sibling Research Cross-Reference

**CBIP vinyl enhancement research** (EXISTS, 100+ lines): Enumerates CBIP-specific constraints (hermeneutic moves: identification, contextualization, argument, hand-off; recognizability metrics: ≥80% OCR, edge IoU ≥0.65, delta-E ≤40; chess-boxing cadence). Technique inventory §2.1–2.4 (poster traditions, constrained-sampling, signal-processing, hip-hop lineages) is CONSISTENT with §2 above but CBIP-contextualized. Recommendations: posterize, kuwahara, halftone, palette-extract as primary; glitch only in reactive bursts.

**Vitruvian enhancement research** (NOT YET): Will cover token_pole-specific enhancements (particle systems, path animation, glyph transforms). Should reuse §2 techniques; focus on spatial motion not static image processing. Coordinate with §3 spatial-dynamism.

**Consolidation:** Collapse CBIP and Vitruvian into 1–2 page annexes reusing §2 taxonomy without duplication, adding surface-specific constraints, referencing §4 framework. Umbrella doc is single source of truth for shared grammar.

---

## §9 — Umbrella Spec Skeleton (12-phase implementation plan)

Phases 1–2: Framework + gating (WardEnhancementProfile schema, OQ-02 Phase 1 authorization). Phases 3–4: Album enhancements (palette/spatial transforms, recognizability tests). Phases 5–6: Temporal + artifacts (feedback, glitch, chromatic_aberration, film-grain, bloom). Phases 7–8: Spatial-dynamism (parallax, DoF, atmospheric tint). Phases 9–10: Ward-specific (album CBIP moves, token_pole particles + path variants). Phases 11–12: Integration + rehearsal + governance + observability.

---

## §10 — Open Questions for Operator

1. Scrim answer confirmation (§5.2): Approve "through" model or propose alternative?
2. Enhancement vs. spatial-dynamism priority: Which wards first? (Recommend: album enhancement, token_pole spatial-dynamism, hardm both parallel.)
3. Recognizability threshold: Default 80% quantitative acceptable for all wards?
4. Enhancement profile switchability: Operator-selectable per programme, director-driven, or mixed?
5. Reverence ceiling: Any wards NEVER enhanced? (Recommend: reverie, orthogonal.)
6. OQ-02 Phase 1 launch: Prioritize before ward-specific work?

---

## §11 — Lead Recommendation

Ship OQ-02 Phase 1 (Nebulous Scrim three-bound-invariants, `docs/research/2026-04-20-nebulous-scrim-three-bound-invariants-triage.md`) before any ward-specific enhancement implementation. The three bounds (anti-recognition, anti-opacity, anti-audio-visualizer) gate EVERY future scrim effect and enhancement chain. OQ-02 Phase 1 is small (Job Size=3 per delta WSJF, metric candidates already enumerated) and unblocks the entire scrim-bundle epic (six research docs currently un-implemented). Parallel: Establish WardEnhancementProfile schema as gate-keeping framework. These two moves provide upper-bound (OQ-02 invariants) and per-ward tracking (enhancement schema) for safe, incremental shipping across the ward family.

---

## §12 — Sources + Cites

**Hapax codebase:** `config/compositor-layouts/default.json`, `agents/studio_compositor/cairo_sources/__init__.py`, ward implementations (token_pole.py, album_overlay.py, etc.), `shared/homage_package.py`, CBIP research, fishbowl conceit doc, ward inventory integration doc, HOMAGE framework spec, scrim design + six-doc cluster, OQ-02 triage, HARDM memory, effect_graph.

**External:** da Vinci (*Treatise on Painting*, aerial perspective), Snellius/Ibn Sahl (refraction law), Newton (*Opticks*, chromatic dispersion), Kuwahara (1976), Merrillees & Turk (2002), OEN *Sensation & Perception* Ch. 9, Piter Pasma (depth cues), CG Spectrum (*Spider-Verse* chromatic offset).

---

**Doc length:** ~3,950 words. **Structure:** TL;DR (3), §1 (1,100 words, 15-ward table), §2 (750 words, technique taxonomy), §3 (400 words, spatial grammar), §4 (300 words, framework), §5 (450 words, scrim answer), §6 (100 words, coupling table), §7 (300 words, governance), §8 (150 words, sibling cross-ref), §9 (100 words, spec skeleton), §10 (100 words, open questions), §11 (100 words, recommendation), §12 (100 words, sources). **Total cites:** 19+ distinct sources (Hapax codebase, research cluster, external authorities).

