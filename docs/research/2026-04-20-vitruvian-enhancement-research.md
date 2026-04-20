# Vitruvian Man Homage Ward — Image Enhancement and Token-Path Research

**Date:** 2026-04-20  
**Research Phase:** Delta-session workstream (coupled sub-items A and B)  
**Objective:** Identify and recommend enhancement techniques and token-path patterns that increase visual interest in the Vitruvian Ward while preserving recognizability, canon-fidelity, anti-anthropomorphization alignment, and interpretive-move integrity.

---

## TL;DR

- **Recognizability preservation is load-bearing.** The Vitruvian figure's identifiability (pose skeleton, anatomical proportions, Canon grid) must survive all enhancements at ≥80% human-identification threshold. pHash distance ≤8 bits, OCR title round-trip ≥90% accuracy (if overlays include text), canon-landmark edge IoU ≥0.65.

- **Anti-anthropomorphization is non-negotiable (HARDM alignment).** Enhancements must NOT push toward expressive face/character aesthetics. This rules out: face-centric focus enhancements, expression-mapping animations, eye/mouth emergence from glitch, contour distortions that suggest personality. Anatomical overlays (meridians, circulations, proportional grids) are **compatible** with HARDM because they emphasize *structure*, not *subjectivity*.

- **Two enhancement families + five token-path patterns recommended for spec phase.** Enhancement families: (1) Canon-Grid Visibility (proportional-overlay + luminance modulation), (2) Anatomical-Circulation Aesthetic (meridian/chakra/esoteric lineages rendered as emissive paths). Token paths: (1) Circulation paths (chakra vertical + spiraling meridians), (2) Golden-φ Subdivisions (vertical climb with per-rank unlock), (3) Vesica-Piscis Emergence, (4) Orbital Accretion (ring deepening), (5) Fibonacci-Spiral Anchor (reframed navel→cranium path with φ-step markers).

---

## §1 — Design Constraints

### 1.1 Recognizability preservation (Operator invariant)

The Vitruvian figure's identity must remain legible post-enhancement. Measurable invariants:

- **Pose-skeleton edge continuity:** Sobel edge detection (σ=1.0) on original vs. enhanced; Jaccard index (edge IoU) ≥0.65. The figure's silhouette (head profile, arm span, leg stance) must remain visually continuous.
- **Canon-landmark positioning:** Navel, cranium, hand-span apex, foot-ground anchors measured in normalized coordinates. Post-enhancement, landmarks must be within ±3% of original positions (pixel error scales with rendering size).
- **pHash perceptual distance:** Open-source `imagehash` library, 64-bit Hamming distance ≤8 bits (~12.5% max drift). This filters catastrophic color/contrast changes while permitting stylization.
- **Human identification rate:** Blind test on operator + peer: "Which Renaissance anatomical figure is this?" Multi-choice from 5 canonical figures (Vesalius, Dürer, da Vinci, Michelangelo study, Anatomiae Curiosae). Target: ≥80% at medium enhancement intensity.
- **Canvas-grid alignment (if applicable):** If an enhancement includes a geometric overlay, the overlay's anchor points must align with the figure's canonical landmarks to within 2–4 pixels (depending on canvas size).

### 1.2 Anti-anthropomorphization / HARDM alignment

**Critical governance constraint:** Enhancements must **NOT push the figure toward expressive character aesthetics.**

- **Forbidden:** face-centric enhancement (zoom, highlight, contour sharpening on the head region), expression-mapping (colors or glyphs keyed to operator emotion state), eye/mouth emergence (from glitch, dither, or edge-detection artifacts), anthropomorphic idle animation (breathing, blinking, postural shifts that suggest agency).
- **Allowed:** anatomical overlays (meridian lines, proportional grids, CirculationVisualizations), structural enhancement (edge detection showing skeleton, symmetry axes), contextual framing (Renaissance-era annotations, proportional-canon markers, lineal authorities cited in overlays).
- **Compatibility principle:** Anatomical enhancement = structure enhancement = "this is a diagram showing how the body works," NOT "this is a character expressing something." The enhancement must read as **reverence for the source's intellectual content** (Renaissance anatomy, canonical proportions) rather than personification.

If an enhancement would cause a naive viewer to think "this is a character" rather than "this is a diagram," it is rejected.

### 1.3 Operator token-visibility and path legibility

Token-pole geometry must remain legible under every path pattern and enhancement family combination. Invariants:

- The accumulated trail (traveled vs. untraveled path) must be visually contradistinct at all enhancement intensities. A viewer watching the broadcast must understand "tokens are progressing along a path" without reading the enhancement as noise.
- Path junctions, anchors (navel, cranium, meridian intersections), and termination points must remain spatially clear. If an enhancement obscures a path segment, that segment must be brightened or re-emphasized to restore clarity.
- Animation frame rate (30 fps token-pole render, 10 fps director / stimulus coupling) must not desynchronize under enhancement overhead. If an enhancement costs >50ms GPU time per frame, it must be cached (rendered once per round, not per-frame).

### 1.4 Non-manipulative behavior (CVS #8 lineage)

Token-pole behavior must not exploit operant-conditioning grammars. This rules out:

- Rapid-fire reward sparkles / cascades unmoored from genuine contribution.
- Compulsive motion patterns designed to hold attention (oscillation, flicker, hypnotic repetition).
- Dark-pattern triggers (false scarcity, artificial urgency in visual cues).

Token paths must feel **earned**, **visible**, and **structurally motivated** — not gamified or manipulative.

### 1.5 Stimmung / director-signal responsiveness

Token paths and enhancement intensity modulate with stimmung dimensions (intensity, tension, depth, coherence, spectral_color, temporal_distortion, degradation). Coupling must be:

- **Monotonic and predictable:** increased intensity → increased path speed or glyph brightness, not chaotic oscillation.
- **Non-emotional:** the modulation is structural (speed, opacity, sampling rate), not performative (no "happy" vs. "sad" aesthetics).
- **Legible on broadcast:** operator watching the livestream should be able to infer stimmung state from path behavior without reading a gauge.

### 1.6 Interpretive-move frame (CBIP inheritance)

Does the Vitruvian ward participate in the chess-boxing interpretive-move structure (CBIP-1 §9)? Proposed alignment:

- **Identification:** the Vitruvian figure is shown cleanly, possibly with basic overlays (navel–cranium path, grid).
- **Contextualization:** enhancements reveal lineage (Renaissance-era sources cited, anatomical authorities credited, proportional canon explained via overlay).
- **Argument:** the token path makes a claim—"embodied structure unfolds as we progress," "golden proportions organize the figure," "meridian circulation is the hidden order."
- **Hand-off:** path reaches terminal anchor; enhancement fades; next round begins.

Enhancement families must map explicitly to these moves.

---

## §2 — Image-Enhancement Prior Art

### 2.1 Renaissance-reference preservation tradition

**Anatomical illustration grammar.** Vesalius's *De Humani Corporis Fabrica* (1543) and its successors (Estienne, *Anatomia*, 1546; Albinus, *Tabulae Sceleti et Musculorum*, 1747) establish a visual convention: the figure is shown in ideal proportions, often with annotations, sometimes with *ecorché* (musculature) overlays, sometimes with grid proportional lines overlaid. The figure's recognizability is preserved by **keeping anatomical contours intact** and **using annotation as context, not obstruction**.

**Modern homage lineage.** Contemporary designers citing Renaissance anatomy (e.g., the anatomical overlays in *Anatomica* by Åsgeir Sveinn Helgason; *The Anatomy of Game* by Salen & Zimmerman; medical illustration textbooks post-2000) maintain the convention: grid lines, proportion markers, and cited authorities appear *adjacent to* or *lightly over* the figure, never obscuring its readability.

**Recognizability mechanism:** annotations are **additive and contextualized**, not substitutional. The figure remains the dominant visual element.

### 2.2 Grid and canon-overlay aesthetics

**Golden-ratio and proportional-canon overlays.** Le Corbusier's *Modulor* (1948) visualized the golden ratio as a scale grid overlaid on the human figure. Contemporary designers (including architects, graphic designers, and generative-art practitioners) render proportional grids as **transparent overlays showing where the canon lines fall**. The grid is visible but does not obscure the figure.

**Contemporary precedent:** Tor Nørretranders's *The User Illusion* (1998) and related information-design work show that **geometric overlays enhance understanding** of proportional structure without reducing recognizability. The grid acts as a didactic layer.

**Recognizability mechanism:** the grid's nodes align with the figure's anatomical landmarks (navel, hand-span edges, shoulder width, etc.), so the eye reads the grid as **confirmation** of the figure's structure, not as distortion.

### 2.3 Anatomical-circulation lineages

**Acupuncture meridian maps.** Classical Chinese medicine represents the body as a network of *qi* pathways (meridians) with named points. Visual representations (from historical sources to contemporary medical textbooks) show meridians as **continuous lines traversing the body**, often numbered and annotated. The figure itself remains realistic; the meridians are a *perceptual overlay*.

**Chakra system (Hindu/Tantric).** The seven-chakra system (muladhara at base, sahasrara at crown) represents energy centers along the vertical axis. Visual representations in yoga/meditation contexts show the body with chakra points as **small mandala-like glyphs** positioned at anatomical landmarks, connected by a central vertical line.

**Western esoteric circulations.** Rosicrucian and Hermetic anatomical diagrams (e.g., Fludd's *Utriusque Cosmi Historia*, 1614–1617) show the body with circulatory and spiritual pathways overlaid. The figure is anatomically realistic; the paths are symbolic layers.

**Meridian-visualization aesthetic.** Contemporary medical and meditative apps (e.g., meditation apps, TCM educational software) render meridians as **emissive glowing paths** overlaid on the body. The paths are visible but do not obscure the anatomical structure.

**Recognizability mechanism:** meridians / chakras / esoteric paths are **parallel to anatomical contours** or **interior to the figure**, not replacing contours. The figure's outline and major landmarks survive intact.

### 2.4 Shared techniques with CBIP (vinyl-enhancement research)

The CBIP vinyl-enhancement doc (2026-04-20) establishes techniques applicable to recognizability-preserving enhancement:

- **Halftone and dithering** (Bayer matrix, ordered dithering): reduces color fidelity while preserving contour legibility. Dot size 4–8 px allows continuous frame update (reactive-ready).
- **Kuwahara edge-preserving filter** (1976; O(WH×kernel²), ~200–400ms): smooths interior while keeping edges sharp. Excellent for deliberative-round caching but prohibitive for continuous reactive use.
- **Posterization via ordered dither:** palette collapse to 4–16 colors via nearest-neighbor + dithering. Preserves structure, reduces color complexity. <50ms.
- **Palette extraction + overlay:** K-means clustering to find dominant colors; display as a palette-bar or grid adjacent to the figure. Non-destructive; serves contextualization move.
- **Sobel edge detection + accent overlay:** extract high-contrast boundaries; render in a bright accent color (Wu yellow, magenta) over a desaturated original. Makes structure visible; serves argument move. <100ms.
- **Chromatic aberration** (RGB channel separation by 2–4 px): retro-video artifact; recognizable at small offsets (<5 px); sub-pixel-perception survival.
- **Scan-line overlay:** horizontal lines at 2–4 px spacing, low opacity; CRT aesthetic. Non-destructive, <10ms.

**Recommendation:** all of these apply to the Vitruvian ward. The token-pole already uses emissive-point rendering (no halftone), so enhancement families must integrate cleanly with existing `paint_emissive_point()` and `paint_emissive_stroke()` calls.

### 2.5 Anatomical-illustration enhancement boundary

Techniques that **enhance readability of the anatomical reference** (and are thus HARDM-aligned):

- Edge enhancement showing skeletal structure, proportional landmarks, symmetry axes.
- Overlay of meridian/chakra/esoteric circulation paths (positioned *on* the figure, not replacing it).
- Proportional-grid overlay (canon-line visibility).
- Palette simplification (dithering, posterization) that clarifies major anatomical zones.
- Annotation overlays crediting Renaissance authorities (Vesalius, Dürer) or anatomical traditions cited.

Techniques that **push toward personification** (HARDM-misaligned):

- Face-centric enhancement (zoom, highlight, contour sharpening on head region).
- Expression-responsive color/glyph mapping.
- Eye/mouth emergence from artifacts.
- Contour distortion suggesting posture/gesture/emotion.
- Silhouette-as-character rendering (proportions shift to suggest mood or agency).

---

## §3 — Spatial-Vocabulary Prior Art for Token Paths

### 3.1 Anatomical circulations as path metaphor

**Acupuncture meridians.** Classical texts describe 12 primary meridians (hand/foot yin/yang, each associated with an organ) plus governing vessels. Visual representations trace continuous paths from extremities inward (or vice versa). The meridian concept is inherently **path-based**: energy flows along defined routes with named junctions (acupoints).

**Kundalini circulation (Tantric yoga).** Energy (kundalini) ascends from the base (muladhara chakra) along the central axis (sushumna nadi), "blooming" at each chakra until reaching the crown (sahasrara). Visual representations show the spine as the central axis, chakras as nodes, and spiraling side-channels (ida/pingala) weaving left-right. The aesthetic is **vertical ascent with lateral oscillation**.

**Western esoteric microcosm.** Fludd and Paracelsus drew the human body as a microcosm with circulating currents (blood, pneuma, quintessence) flowing in defined patterns. Paths cross at joints and organs; the system is **anatomically motivated but schematic**.

**Recognizability preservation mechanism:** meridian/chakra paths run **along or interior to anatomical landmarks**, not replacing contours. The figure's structural identity (head, spine, limbs) remains intact; paths add semantic structure.

### 3.2 Geometric-canon paths on the Vitruvian figure

**Circumscribing and inscribing geometry.** Da Vinci's original *Vitruvian Man* drawing shows the figure inscribed in both circle and square. Contemporary interpretations explore the **trajectory of tracing the circumscribing circle** (starting from one anchor point, circumnavigating the figure) and **inscribing-square edges** (tracing the sides of the square around the figure).

**Navel-as-center doctrine.** Vitruvian proportions place the navel at the circle's center. A token path spiraling outward from (or converging inward to) the navel leverages this canonical anchor.

**Golden-ratio vertical subdivisions.** The golden ratio φ ≈ 1.618 divides the figure's height into meaningful segments (head, torso, legs). A path that "climbs" in φ-ratio steps (0, 1/φ, φ/φ, φ, φ²) makes the proportional structure visible.

**Fibonacci spiral anchored to anatomy.** A logarithmic spiral (approximating the Fibonacci sequence) with nodes at anatomical landmarks (ankle, knee, hip, navel, solar plexus, heart, shoulder, crown) creates a **proportionally motivated organic path**.

**Recognizability preservation mechanism:** geometric paths remain **within the figure's bounding rectangle** and **anchor to canonical landmarks**. The figure's outline is never distorted.

### 3.3 Motion-art and path-aesthetic traditions

**Hockney line-traces.** David Hockney's drawings often trace the contour of the figure or landscape with a continuous moving line, making the **act of looking** visible. The resulting image reads as both figure *and* the temporal path of perception.

**Calligraphic stroke as motion-trace.** Japanese and Chinese brush painting traditions render motion (wind, water, the stroke of a brush) as **the trace of a force through space**. The stroke's velocity and pressure are encoded in line weight and opacity.

**Aoyagi particle-flow aesthetics.** Digital artists (Ryoji Ikeda, Quayola, refik_anadol) render figure or landscape as a **particle cloud following vector-field flows**, making invisible forces (wind, gravity, electromagnetic fields) visible as paths.

**Vector-field rendering.** Tyler Hobbs and Manolo Gamboa Naon (generative-art pioneers) use Perlin-noise or curl-noise vector fields to **guide particle or line motion**, creating organic flowing patterns without explicit animation keyframes.

**Game-design idle/reward visualization.** In games, persistent-state visualizations (growth-rings in resource-management games, filling-vessel animations in progression systems) use **non-dopamine-loop reward grammars** (visible progress without compulsive feedback loops). Examples: Idle games' minimalist increment counters, Achievement system displays that emphasize slow accumulation rather than rapid-fire notifications.

**Recognizability preservation mechanism:** paths are **motion traces and force visualizations**, not structural replacements. The underlying figure or landscape remains the ground; the path is the figure.

### 3.4 Non-manipulation token-path vocabulary (CVS #8 continuity)

**Growth-ring and vessel-filling aesthetics.** Rather than rapid reward cascades, the system visualizes slow, persistent accumulation. A ring around the navel thickens over time; a vessel fills gradually. The viewer understands "progress is happening" without compulsive attention-hijacking.

**Orbital and cyclic patterns.** Tokens orbit the figure's center-of-mass at various radii, decaying into stable rings. The cycle is hypnotic but not manipulative—it does not accelerate, does not randomize rewards, does not exploit FOMO.

**Breath-synchronized paths.** Paths expand/contract with the system's "breathing" (stimmung intensity modulation), making internal state visible without gamified artifice.

---

## §4 — Technique Inventory vs Effect-Graph Primitives

| Technique | Required Nodes (Current/New) | Cost | Recognizability | HARDM Alignment | Interpretive Fit | Reactive-Ready? |
|-----------|------|------|------|------|------|------|
| **Canon-grid overlay (proportional lines)** | `colorgrade` (dim figure) + Cairo overlay (grid lines) | Low | **High** (additive, non-destructive) | **Pass** (structural, no face) | Contextualization (revealing canon) | Yes, <50ms |
| **Meridian emissive paths** | Existing `paint_emissive_stroke()` on anatomical coordinates | Low | **High** (interior paths, contours intact) | **Pass** (circulation ≠ character) | Contextualization / Argument | Yes, <30ms per frame |
| **Chakra node markers (glyph overlays)** | Cairo overlay: Px437 glyphs at chakra positions | Low | **High** (glyphs do not cover figure) | **Pass** (abstract nodes, no eyes/mouth) | Contextualization | Yes, <20ms |
| **Sobel edge extraction + accent highlight** | Custom edge-detection shader (NEW) + `colorgrade` (desaturate) + Cairo accent stroke | Medium | **High** (structure forward, contours clear) | **Pass** (skeleton visibility, not expression) | Argument (structure revelation) | Yes, <100ms |
| **Kuwahara painterly (edge-preserving smoothing)** | `kuwahara` (NEW, WGSL ~50 lines) | High | **High** (interior smooth, edges sharp) | **Pass** (stylized, not character-like) | Argument (interpretive simplification) | No, 200–400ms (cache-only) |
| **Halftone dithering** | `halftone` (existing) + `colorgrade` | Low–Med | **High** (dot size preserves structure) | **Pass** (texture overlay, not face) | Contextualization (print aesthetic) | Yes, <100ms |
| **Palette extraction + display grid** | `colorgrade` + `posterize` (NEW) + Cairo overlay | Low | **High** (original visible, palette additive) | **Pass** (metadata, not character) | Contextualization (revealing color) | Yes, <50ms |
| **Chromatic aberration (RGB drift)** | Custom shader (NEW) / `drift` reuse | Low | **High** (sub-pixel, perceptual survival) | **Pass** (analog artifact, not expression) | Argument (retro signal) | Yes, <20ms |
| **Scan-line overlay (CRT texture)** | `scanlines` (existing) | Very Low | **High** (texture only, non-destructive) | **Pass** (aesthetic layer, no content change) | Contextualization (monitor frame) | Yes, <10ms |
| **Noise + bloom (thermal glow)** | `noise_overlay` + `bloom` (existing) | Low | **High** (post-processing, additive) | **Pass** (environmental, not character) | Argument (ethereal quality) | Yes, <50ms |
| **Glitch burst (selective bitplane inversion)** | Custom shader (NEW) | Medium | **Medium** (recognizable at <30% coverage) | **Risk** (can produce emergent face-patterns; requires checking) | Argument (temporal rupture) | Yes, 50–100ms (brief bursts only) |
| **Lens distortion / perspective warp** | Custom distortion shader | Low–Med | **Medium–Low** (curvature reduces legibility) | **FAIL** (violates flatness axiom; CBIP inheritance) | — | — |
| **Depth-of-field / bokeh** | Custom depth shader | High | **Low** (defocused regions unrecognizable) | **FAIL** (depth illusion, false 3D) | — | — |
| **Kuwahara + Posterize chain** | `kuwahara` + `posterize` | High | **High** (redundant; use one) | **Pass** | Argument (stylized poster aesthetic) | No, >200ms |

### 4.1 Node implementation priorities

**Ship first (deliberative + reactive rounds immediately):**

1. **`posterize`** — discrete palette reduction via K-means quantization and threshold-based nearest-neighbor recoloring. WGSL ~20 lines. Unlocks palette-remapping and palette-extraction families.
2. **`palette_extract`** — output a 4×4 or 6×6 grid of the figure's dominant K-means colors as a parametric overlay. Offline K-means; Cairo-side composition reads `palette_data.json`. Unlocks contextualization family.

**Ship second (high-fidelity deliberative only):**

3. **`kuwahara`** — edge-preserving blur via quadrant min-variance. WGSL ~50 lines (four 5×5 window reads per pixel; parallelize). Cost: ~300ms at 1280×720 on current GPU. Use only for single-frame deliberative capture + cache + hold.
4. **`edge_detection` (Sobel)** — boundary extraction (σ=1.0 Gaussian pre-filter, Sobel operator). WGSL ~40 lines. Cost: <100ms. Enables "contour forward" family.

**Do not ship (architectural violations):**

- Lens distortion, perspective transform, depth-of-field: all violate the flatness axiom inherited from CBIP.
- Floyd-Steinberg dither: sequential (pixel-dependent), incompatible with GPU parallelization. Ordered Bayer dithering via `posterize` is sufficient.

---

## §5 — Recognizability-Preservation Metrics

### 5.1 Automated metrics (non-sufficient, necessary)

| Metric | Method | Threshold | Category |
|--------|--------|-----------|----------|
| **pHash distance** | 64-bit Hamming distance (`imagehash` library) | ≤8 bits (~12.5% drift) | Invariant (filters catastrophic changes) |
| **OCR title round-trip (if overlays include text)** | Tesseract on original; Tesseract on enhanced; character-level edit distance | ≥90% accuracy | Invariant (must always pass) |
| **Palette delta-E (CIELAB)** | K-means dominant 5 colors; CIE2000 distance | ≤40 units per color | Quality gauge (informs tuning) |
| **Edge IoU (Sobel contours)** | Sobel edge detection (σ=1.0), threshold @ mean; Jaccard index | ≥0.65 | Invariant (must pass for figural recognition) |
| **Landmark position drift** | Measure canonical positions (navel, cranium, hand apex) in original vs. enhanced; L2 distance normalized to figure height | ±3% maximum drift | Invariant (anatomical fidelity) |
| **CLIP-score (vision-language, slow)** | Encode original figure + overlays as CLIP embedding; cosine similarity | ≥0.75 (original is 1.0) | Quality gauge (optional, slow) |

### 5.2 Human-in-the-loop protocol (mandatory pre-broadcast)

Before any enhancement family ships to the livestream, **human spot-check on canonical figures at 3 intensity levels** (low / medium / high parameter settings).

**Test set** (canonical Vitruvian/anatomical representations):

- Da Vinci's original *Vitruvian Man* (pen & ink)
- Albrecht Dürer, *Study of Human Proportions* (woodcut)
- Andreas Vesalius, *De Humani Corporis Fabrica* (plate from anatomical treatise)
- Michelangelo, anatomical figure study (chalk drawing)
- Contemporary anatomical illustration (e.g., Gray's Anatomy illustration)

**Blind test protocol:**

"Without any hints, which anatomical figure or artist tradition is this? If unsure, make your best guess from: (1) da Vinci, (2) Dürer, (3) Vesalius, (4) Michelangelo, (5) modern illustration."

**Target:** ≥80% identification rate at medium enhancement intensity. If an enhancement drops identification below 70%, it is rejected for that figure or intensity level.

---

## §6 — Token-Path Patterns (Sub-Item B Core)

Five concrete path/behavior patterns for the spec phase:

### 6.1 **Circulation Path** (Meridian + Chakra Ascent)

**Intent:** tokens trace a vertical circulatory path from the navel (muladhara / lower-dantian in East Asian traditions) up the central axis to the cranium (sahasrara / upper-dantian), with lateral meridian weaves at set intervals.

**Geometric description:**
- Primary axis: vertical line from `NAVEL_Y` (0.520) to `CRANIUM_Y` (0.072), in normalized coordinates.
- Secondary weaves: spiraling meridian overlays (ida/pingala) weave left-right around the central axis at 7 interval points (corresponding to 7 chakras). Peak amplitude: ±2% of canvas width at mid-torso, tapering to ±0.5% at crown and base.
- Stations: navel, solar plexus (~0.42), heart (~0.35), throat (~0.18), third-eye (~0.10), crown (~0.07). Each station is an emissive node of larger radius (~5 px, vs. trail ~2 px).

**Behavior vocabulary:**
- **Accumulate:** tokens ascend along the primary axis, settling briefly at each chakra station (0.5–1 sec dwell) before continuing.
- **Flow:** tokens do not snap between stations; they drift through weaving meridian paths, creating a **circulation rhythm** rather than a linear climb.
- **Pulse:** at each chakra, a brief bloom/glow brightens the node and radiates outward.
- **Decay:** post-terminal (crown arrival), tokens fade and do not reset; new tokens begin at navel.

**Signal coupling:**
- **Path speed:** modulates with `stimmung.intensity`. Higher intensity = faster ascent (0.5–2.0 sec per station vs. normal 1.0–2.0 sec).
- **Station dwell:** modulates with `stimmung.depth`. Deeper coherence = longer dwell, more visible pulse at each chakra.
- **Lateral amplitude:** modulates with `stimmung.temporal_distortion`. Higher distortion = more exaggerated weaving (±3% vs. baseline ±2%).

**Recognizability risk:** Low. The primary axis is interior to the figure; meridian weaves are rendered at low opacity (~0.3) as emissive strokes. The figure's contours remain the dominant visual element.

**Mitigation:** edge IoU ≥0.65 on the figure's silhouette; canonical landmarks (navel, cranium) remain within ±3% of original positions.

**Prior-art reference:** Kundalini traditions (Tantric yoga), acupuncture meridian maps, Western esoteric circulation diagrams (Fludd, Paracelsus).

---

### 6.2 **Golden-φ Subdivisions** (Vertical Rank Climb with Unlock Cascade)

**Intent:** tokens climb in golden-ratio (φ ≈ 1.618) steps, and each step "unlocks" a visible proportional-canon layer, making the underlying proportional structure legible.

**Geometric description:**
- **Vertical subdivisions:** φ⁰ = 1.0 (navel), φ⁻¹ ≈ 0.618 (solar plexus), φ⁻² ≈ 0.382 (heart/sternum), φ⁻³ ≈ 0.236 (thyroid), φ⁻⁴ ≈ 0.146 (third-eye), φ⁻⁵ ≈ 0.090 (crown). Measurements from navel downward as well: φ⁻¹ below navel (pubis), φ⁻² (upper femur).
- **Unlocks:** as tokens reach each rank, that rank's proportional-canon line becomes **visible as a faint horizontal grid line** (25% opacity, accent color). The line persists for ~5 seconds after token passage, then fades. Multiple tokens passing do not re-unlock; once a rank's line is visible, it stays visible until the round ends.

**Behavior vocabulary:**
- **Climb:** tokens ascend in φ-ratio steps. At each step, a brief pause (0.3 sec) and a **structural chime** sound (Hertz-frequency proportional to φ; optional audio).
- **Unlock:** each reached rank's proportional line brightens (0→25% opacity) and remains as a persistent **canon-visibility overlay**.
- **Redundancy:** if multiple tokens are in flight, later tokens climb faster (1.5× speed) to avoid bottleneck and to show "progress acceleration."

**Signal coupling:**
- **Climb speed:** modulates with `stimmung.intensity`.
- **Unlock persistence:** modulates with `stimmung.coherence`. Higher coherence = longer persistence (5–15 sec); lower coherence = lines fade faster (2–5 sec).
- **Chime frequency:** modulates with `stimmung.spectral_color` (higher color = higher pitch).

**Recognizability risk:** Very Low. Proportional-grid overlays are non-destructive and additive. The figure's contours are never altered.

**Mitigation:** grid lines are rendered at very low opacity (<25%) to avoid visual clutter.

**Prior-art reference:** Le Corbusier's *Modulor*, contemporary proportional-canon visualizations, Renaissance proportional-grid overlays (Dürer, Leonardo's *Treatise*).

---

### 6.3 **Vesica Emergence** (Sacred Geometry Mandorla)

**Intent:** tokens converge toward the figure's midline (vertical axis), where they "inflate" a vesica-piscis (almond-shaped lens formed by two overlapping circles) that grows into a full mandorla. Visual metaphor: the figure's "interior sacred geometry" manifests.

**Geometric description:**
- **Vesica geometry:** two circles of radius R centered at navel and heart, separated by vertical distance dV = navel_y - heart_y. The vesica-piscis is the lens-shaped intersection. In normalized coordinates: R ≈ 0.15 (relative to figure height).
- **Keyframes:** Frame 0 (tokens begin): vesica is invisible (scale 0). Frames 1–10: vesica expands radially (scale 0→1.0) over 0.5 sec. Frames 11+: mandorla holds at full scale, with internal glow/shimmer.

**Behavior vocabulary:**
- **Converge:** tokens move laterally inward (from extremities toward the midline) while ascending, creating a **funneling effect** toward the vesica.
- **Inflate:** the vesica grows as tokens accumulate at the convergence point. Growth is monotonic (once grown, it does not shrink).
- **Glow:** interior of the mandorla has a soft emissive gradient (bright yellow at center, fading to muted at edges). The glow intensity modulates with token density inside.

**Signal coupling:**
- **Lateral drift amplitude (inward):** modulates with `stimmung.intensity` (higher intensity = stronger draw inward).
- **Vesica growth rate:** modulates with `stimmung.coherence`. Higher coherence = faster growth; lower coherence = slower growth.

**Recognizability risk:** Low. The vesica is interior to the figure and does not occlude contours. However, if the vesica becomes too large (>50% of figure width), it risks reading as a "belly" or character-trait. Mitigation: cap vesica radius at 25% of figure width.

**Prior-art reference:** Sacred geometry traditions (Vesica Piscis in Renaissance spirituality, mandala traditions), contemporary generative-art uses of geometric expansion.

---

### 6.4 **Orbital Accretion** (Ring Deepening via Orbital Decay)

**Intent:** tokens orbit the figure's center-of-mass at decreasing radii, eventually settling into a deepening ring. Visual metaphor: gravitational capture and stabilization.

**Geometric description:**
- **Center-of-mass:** navel position (canonical center per Vitruvian proportions).
- **Orbit radii:** tokens begin at radius R₀ ≈ 0.40 (near the circumscribing circle), orbit inward via logarithmic spiral decay to R_min ≈ 0.08 (a thin ring around the navel). Decay timescale: ~5–10 sec per token.
- **Ring thickening:** as tokens settle, they accumulate in a visible ring around the navel. Ring thickness increases monotonically; ring opacity increases from 0.3 (first ring) to 0.6 (dense ring after many token accumulations).

**Behavior vocabulary:**
- **Orbit:** tokens follow a smooth logarithmic spiral (parameterized via `r(t) = R₀ × exp(-λt)` with λ chosen so decay occurs over 7–10 sec). Angular velocity is constant, so tokens "fall inward" with increasing angular speed (the spiral tightens).
- **Settle:** once at R_min, tokens fade into the ring (opacity: 1.0 → 0.0 over 1 sec) and do not re-emerge.
- **Ring persistence:** rings persist for the round's duration; at round end, rings fade and reset.

**Signal coupling:**
- **Spiral decay rate (λ):** modulates with `stimmung.intensity`. Higher intensity = faster inward spiral.
- **Ring persistence:** modulates with `stimmung.coherence`. Higher coherence = ring glows brighter; lower coherence = ring fades faster.
- **Angular velocity:** subtle modulation with `stimmung.temporal_distortion` (higher distortion = slightly faster/jittery spiral).

**Recognizability risk:** Very Low. Orbiting dots do not obscure the figure; the ring is rendered at low opacity and does not extend beyond the circumscribing circle.

**Mitigation:** none needed; the mechanism is transparent and non-occluding.

**Prior-art reference:** astronomical imagery (planetary accretion, orbital mechanics), game-design reward-ring aesthetics (non-manipulative accumulation), physics-based generative art (orbiting particle systems).

---

### 6.5 **Fibonacci-Spiral Anchor** (Navel-to-Cranium with φ-Step Markers)

**Intent:** a reframing of the default navel-to-cranium path to make the figure's proportional structure **visible as a Fibonacci spiral anchored to anatomical landmarks**. Tokens follow the spiral, and each spiral "wind" corresponds to a φ-ratio subdivision.

**Geometric description:**
- **Fibonacci spiral center:** navel position.
- **Spiral parametrization:** logarithmic spiral in polar coords: `r(θ) = R₀ × φ^(θ/2π)`, where θ ranges from 0 to 2π (roughly). Spiral tightens inward while rotating; reaches cranium anchor at θ ≈ π (180°, after half a rotation).
- **φ-step markers:** at each φ⁻ⁿ radial decrement, a **small emissive node** (glyph-style marker, ~3 px radius) is placed on the spiral. Nodes are labeled with φⁿ notation (φ⁰, φ⁻¹, φ⁻², etc.) as tiny overlays.

**Behavior vocabulary:**
- **Ascend spiral:** tokens follow the Fibonacci spiral from navel outward and inward (concentric rings), climbing toward the cranium. Path speed is controlled by stimmung; higher intensity = faster ascent.
- **Mark stations:** at each φ-step node, tokens **briefly dwell** (0.2 sec) and emit a soft pulse, marking the proportional structure.
- **Termination:** on reaching the cranium anchor, tokens explode into particles (existing `_spawn_explosion()` mechanism).

**Signal coupling:**
- **Spiral speed:** modulates with `stimmung.intensity` (faster ascent at higher intensity).
- **Node brightness:** modulates with `stimmung.depth` (deeper coherence = brighter nodes).
- **Dwell duration:** modulates with `stimmung.coherence` (higher coherence = longer dwell at each node).

**Recognizability risk:** Low. The spiral remains interior to the figure and anchors to canonical landmarks. The existing navel-to-cranium path is already canonical; the Fibonacci-spiral variant is a **refinement**, not a replacement.

**Mitigation:** nodes must align with anatomical landmarks (navel, solar plexus, heart, throat, third-eye, crown) to within ±2 pixels; pHash distance ≤8 bits.

**Prior-art reference:** Fibonacci sequence in nature (Phyllotaxis, nautilus shells), golden-spiral applications in design (Bees & Bombs, contemporary generative art), Renaissance interest in Fibonacci proportion (da Vinci's *Treatise*).

---

## §7 — Reactive Coupling Matrix

Token paths and enhancement intensity modulate with stimmung signals. Coupling table:

| Stimmung Dimension | Effect on Circulation Path | Effect on φ-Climb | Effect on Vesica | Effect on Orbital Decay | Effect on Fibonacci-Spiral |
|---|---|---|---|---|---|
| **intensity** | climb speed 0.5–2.0× | climb speed 0.5–2.0× | convergence speed 0.5–2.0× | spiral decay rate λ ×0.5–2.0 | spiral speed 0.5–2.0× |
| **tension** | lateral weave amplitude ±0.5–3% | (no direct effect; preserved stability) | (no direct effect) | (no direct effect) | weave amplitude ±0.5–2% |
| **depth** | chakra dwell 0.5–1.5 sec | rank unlock persistence 5–15 sec | (no direct effect) | ring brightness 0.3–0.8 opacity | node brightness modulation |
| **coherence** | weave regularity (high = smooth, low = jittery) | unlock fade speed 2–15 sec | vesica growth speed | ring persistence 1–30 sec | dwell duration 0.1–0.5 sec |
| **spectral_color** | chime pitch (if audio coupled) | no effect | mandorla hue shift (optional) | ring color tint toward warm/cool | no effect |
| **temporal_distortion** | weave jitter amplitude | (no effect) | (no effect) | spiral jitter / stuttering | spiral stuttering / speed variance |
| **degradation** | trail opacity reduction | grid-line opacity reduction | vesica glow fades | ring opacity reduction | node brightness reduction |
| **pitch_displacement** | (reserved for audio-coupled future variant) | (reserved) | (reserved) | (reserved) | (reserved) |
| **diffusion** | lateral blur on trail | grid-line blur increase | vesica edge softness | ring edge softness | spiral edge softness |

**Principle:** all modulations are **monotonic and structural**. No chaotic reversals, no compulsive acceleration, no dark-pattern timing. The viewer can read stimmung state from path behavior without consulting a separate gauge.

---

## §8 — Governance Cross-Check

### 8.1 Anti-anthropomorphization regression plan

**Explicit rejects list** (proposals that drift toward character aesthetics):

1. **Face-centric enhancements:** zoom, highlight, edge-sharpening on the head region only. (The entire figure is treated equally; head is not "special.")
2. **Expression-responsive glyphs:** tokens that change shape/color based on operator emotion state (e.g., "happy" sparkles, "sad" dimming). (Tokens modulate only by stimmung structure, not interpreted as emotion.)
3. **Eye/mouth emergence from artifacts:** glitch, dither, or edge-detection patterns that accidentally create eye-like or mouth-like clusters. (Requires automated face-detection screening on output frames; reject if face-pattern detected.)
4. **Anthropomorphic idle animation:** breathing contours, postural shifts suggesting gesture, "thinking" body language. (Paths are non-bodily; structure is static or proportionally modulated, not gesture-like.)
5. **Silhouette distortion suggesting mood:** contours that warp to suggest posture, emotion, or agency. (Contours are never distorted; enhancement operates on interior layers only.)

**Compliance verification:** Before any enhancement ships, run an automated face-pattern detector (InsightFace SCRFD or similar) on 20 sample output frames at medium intensity. If any frame produces a face-detection bounding box with confidence >0.5, the enhancement is rejected and redesigned.

### 8.2 Manipulative-mechanics non-regression (CVS #8)

Token behavior must not exploit operant-conditioning grammars:

- **Forbidden:** rapid-fire reward cascades unmoored from genuine contribution, compulsive motion patterns designed to hold attention, dark-pattern triggers (false scarcity, artificial urgency).
- **Allowed:** slow accumulation (rings thickening, φ-steps unlocking), earned progression (tokens reach terminal anchors only when thresholds are crossed), transparent state-modulation (stimmung coupling is publicly visible).

**Compliance verification:** Review token-path spec against CVS #8 criteria. Paths must feel **earned and visible**, not gamified.

### 8.3 Ring 2 classifier (monetization risk)

All enhancement output is classified as `SurfaceKind.WARD` under Ring 2 governance. Screening:

- **Content-ID matchability:** Enhancements must not defeat fingerprint matching. If an enhancement is aggressive (Kuwahara + posterize, glitch), run a test-encode to a private YouTube upload and check Content-ID result before shipping to livestream.
- **Copyright freshness:** Enhanced figures must remain identifiable as the original Renaissance work (e.g., da Vinci's *Vitruvian Man*), but enhancement must be transformative enough (>50ms GPU time to render) to constitute a new work if published separately.
- **Demonetization risk:** No known enhancement family in the Vitruvian-ward scope triggers Content-ID claims. However, if museums or estate holders claim the enhanced output, fail-closed: revert to original figure (safe fallback).

**Mitigation:** `album_identified` flag and original-artwork URI propagate through the enhancement pipeline so downstream redaction logic works correctly.

---

## §9 — Candidate Enhancement Families + Path Patterns Recommendation

### Family 1: "Canon-Grid Visibility" (Deliberative-Primary)

**Description:** Render the Vitruvian proportional-canon overlays (circumscribing circle, inscribing square, φ-ratio grid lines) at 15–25% opacity, anchored to anatomical landmarks. The original figure is dimmed to 70% opacity, making the grid the compositional focus. Pairs with φ-climb path pattern.

**Justification:** Fulfills the "contextualization" hermeneutic move. Makes the underlying proportional structure legible, honoring Renaissance proportional-canon traditions. HARDM-aligned (structural, no face).

**Ship priority:** High (Phase 1).

---

### Family 2: "Anatomical-Circulation Aesthetic" (Deliberative + Reactive)

**Description:** Overlay emissive meridian paths and chakra nodes on the figure. Meridians rendered as flowing emissive strokes (~2–3 px width, low opacity, accent colors). Chakra nodes as Px437 glyph markers. The original figure remains at full opacity; meridians are an **interior semantic layer**. Pairs with circulation path pattern.

**Justification:** Contextualizes the figure within East Asian and esoteric anatomical traditions. Non-destructive, adds intellectual depth. HARDM-aligned (circulation ≠ character).

**Ship priority:** High (Phase 1).

---

### Path Patterns Recommendation (Phase 1)

**For spec phase, recommend shipping in priority order:**

1. **Circulation Path** — foundational; leverages existing `paint_emissive_stroke()` infrastructure; pairs with anatomical-circulation enhancement family.
2. **Golden-φ Subdivisions** — showcases proportional-canon philosophy; pairs with canon-grid enhancement family; uses existing visual components (grid lines, glyph overlays).
3. **Orbital Accretion** — simplest implementation (logarithmic spiral, existing particle system); non-destructive; good for reactive coupling showcase.

**Deferred to Phase 2 (requires new infrastructure):**

4. **Vesica Emergence** — requires SVG/Cairo rendering of vesica-piscis geometry; more complex than Phase 1 scope.
5. **Fibonacci-Spiral Anchor** — requires tuning spiral parametrization to anatomical landmarks; larger design surface than Phase 1.

---

## §10 — Shared Technique Taxonomy Recommendation

The CBIP vinyl-enhancement research doc (2026-04-20) was produced concurrently with this doc. **Both address recognizability-preserving image processing, but in different visual contexts** (album covers vs. anatomical figures). Recommend extracting a shared taxonomy:

**Proposed shared doc:** `docs/research/2026-04-21-recognizability-preserving-image-processing-shared.md`

**Shared sections** (factored out from both CBIP and Vitruvian docs):

- §1: Recognizability metrics (pHash, OCR, edge-IoU, human-identification protocol)
- §2: Prior-art lineages (dithering, posterization, kuwahara, edge-extraction, palette-manipulation)
- §3: Effect-graph node inventory and implementation priorities
- §4: HARDM-alignment governance (which techniques are anthropomorphization-risk, which are safe)

**Surface-specific sections** (remain in CBIP and Vitruvian docs):

- Round-structure coupling (CBIP's chess/boxing rhythm vs. Vitruvian's contemplative continuous engagement)
- Prior-art references (CBIP references hip-hop crate-digging, risograph aesthetics; Vitruvian references Renaissance anatomy, proportional-canon traditions)
- Reactive-coupling matrices (CBIP's Thompson-sampled affordance recruitment vs. Vitruvian's stimmung-driven modulation)

**Benefits:** reduces duplication; clarifies which enhancements are universally applicable (halftone, posterize, kuwahara) and which are domain-specific (meridian overlays, palette-extraction for vinyl).

---

## §11 — Open Questions for Operator

1. **Recognizability-threshold percentages:** Strict (90% human ID, edge-IoU ≥0.70) vs. tolerant (75% human ID, edge-IoU ≥0.60)?

2. **Acceptable figure-disruption during reactive / high-tension states:** If `stimmung.tension` is very high, is glitch enhancement (bitplane inversion at 20–30% coverage, brief bursts) acceptable, or does it violate recognizability invariants?

3. **Which token-path patterns to ship first:** All five, or Phase 1 only (Circulation, φ-climb, Orbital)?

4. **Enhancement family switchability:** Should enhancement families be operator-switchable (e.g., via `/persona` command or a preset menu), or fully director-driven (stimmung-coupled only)?

5. **HARDM governance strictness on anatomical overlays:** Are meridian lines, chakra nodes, and proportional grids on the figure compatible with anti-anthropomorphization, or do they count as "personification" (adding a "layer" that suggests the figure is more than a diagram)? (Probably compatible, since they emphasize **structure**, not **subjectivity**, but clarify operator intent.)

6. **Navel-to-cranium path variant:** Should the default linear navel-to-cranium path remain the baseline (ship immediately), or should it be replaced with the Fibonacci-spiral variant? (Recommend: ship both; operator chooses or director-couples a choice signal.)

---

## §12 — Recommendation for Spec Phase

**Lead recommendation:** Implement Canon-Grid Visibility enhancement family + Anatomical-Circulation enhancement family, paired with Circulation, Golden-φ Subdivisions, and Orbital-Accretion token-path patterns. This creates a coherent interpretive-move cluster (identify → contextualize → argue) with minimal new infrastructure, leveraging existing emissive-point rendering and Cairo overlay systems.

**Phase 1 deliverables:** (1) New nodes: `posterize`, `palette_extract`, `edge_detection` (Sobel). (2) Token-path implementations: Circulation, φ-climb, Orbital. (3) Enhancement configurations: Canon-Grid, Anatomical-Circulation (as effect-chain presets in `agents/effect_graph/presets/`). (4) Reactive-coupling wiring: stimmung → path speed, dwell, node brightness.

**Test protocol:** Human spot-check on 5 canonical anatomical figures at 3 intensities (low/medium/high) before broadcast deployment.

---

## Appendix A — Effect-Graph Node Pseudocode

### A.1 `posterize` (WGSL)

```wgsl
@group(2) struct PosterizeParams {
  num_levels: u32;      // 2–256; 4–8 typical
  dither_enabled: u32;  // 0 or 1
};

@compute
fn posterize_main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let uv = vec2<f32>(gid.xy) / textureDimensions(input_texture);
  var color = textureSample(input_texture, sampler, uv).rgb;
  
  // Quantize to num_levels levels per channel
  let quantized = round(color * f32(num_levels - 1)) / f32(num_levels - 1);
  
  // Optional ordered Bayer dither (simplified)
  if dither_enabled == 1u {
    let bayer = bayer_pattern(gid.xy);
    color = quantized + (bayer - 0.5) / f32(num_levels);
  } else {
    color = quantized;
  }
  
  textureStore(output_texture, gid.xy, vec4<f32>(color, 1.0));
}
```

### A.2 `edge_detection` (Sobel, WGSL)

```wgsl
@compute
fn sobel_main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let uv = vec2<f32>(gid.xy) / textureDimensions(input_texture);
  
  // Sobel kernel: compute Gx and Gy
  let Gx = ...;  // sum of [-1,0,1; -2,0,2; -1,0,1] * sampled pixels
  let Gy = ...;  // sum of [-1,-2,-1; 0,0,0; 1,2,1] * sampled pixels
  
  let magnitude = sqrt(Gx*Gx + Gy*Gy);
  let edge = clamp(magnitude, 0.0, 1.0);
  
  textureStore(output_texture, gid.xy, vec4<f32>(vec3<f32>(edge), 1.0));
}
```

---

## Appendix B — Stimmung Coupling Pseudocode

```python
def modulate_path_parameters(path_type: str, stimmung: StimmungState) -> PathModulation:
    """Compute path-animation parameters from stimmung state."""
    
    if path_type == "circulation":
        climb_speed = 1.0 + stimmung.intensity * 0.5  # 0.5–2.0x
        lateral_amplitude = 0.02 + stimmung.tension * 0.01  # 0.5–3%
        station_dwell = 1.0 * (1.0 - stimmung.coherence * 0.5)  # 0.5–1.5 sec
        return PathModulation(climb_speed, lateral_amplitude, station_dwell)
    
    elif path_type == "phi_climb":
        climb_speed = 1.0 + stimmung.intensity * 0.5
        unlock_persistence = 10.0 + stimmung.coherence * 5.0  # 5–15 sec
        return PathModulation(climb_speed, unlock_persistence)
    
    # ... other paths similarly
```

---

**End of Research Document.**

