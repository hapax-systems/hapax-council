# Nebulous Scrim System — Research & Design

**Status:** Research / design, operator-directed 2026-04-20.
**Authors:** cascade (Claude Opus 4.7, 1M).
**Governing anchors:** HOMAGE framework (`docs/superpowers/specs/2026-04-18-homage-framework-design.md`), Logos design language (`docs/logos-design-language.md` §1, §11), Reverie vocabulary integrity (`agents/reverie/_uniforms.py`), Phase A6 substrate invariant.
**Related prior art:** `project_effect_graph`, `project_reverie`, `project_reverie_adaptive`, `feedback_director_grounding`, `project_720p_commitment`.
**Scope:** This document is a *conceptual anchor* proposal plus architectural and sequencing sketches. No code. No merge intent beyond a phased plan for downstream PRs.

> "Hallloo over there from over here across the way!"
> — operator, 2026-04-20

---

## 1. Problem Framing

### 1.1 The current effects layer is architecturally rich but conceptually diffuse

The livestream's composite surface today is the product of several well-engineered subsystems:

- **Reverie**, the permanent 8-pass WGSL vocabulary graph (`noise → rd → color → drift → breath → feedback → content_layer → postprocess`) with temporal nodes for reaction-diffusion and feedback.
- The **effect graph** DAG compiler (`agents/effect_graph/wgsl_compiler.py`), 56 node types under `agents/shaders/nodes/`, and roughly 30 named presets in `presets/` — `ambient`, `ascii_preset`, `feedback_preset`, `ghost`, `kaleidodream`, `neon`, `nightvision`, `screwed`, `thermal_preset`, `trails`, `vhs_preset`, and so on.
- The **`gst-plugin-glfeedback`** Rust plugin (`gst-plugin-glfeedback/src/glfeedback/imp.rs`), a ping-pong FBO GL filter providing `tex_accum` temporal feedback to arbitrary fragment shaders on the GStreamer compositor side.
- The **HOMAGE framework** (2026-04-18), whose Phase A6 substrate invariant already damps Reverie's `color` node toward a cyan-tinted ground (`saturation=0.40`, `hue_rotate=180°`, `brightness=0.85`) so the ambient shader reads as a tinted plane rather than a kaleidoscopic competitor. This is the critical piece of lineage for what follows.

What this stack is missing is a *binding conceptual anchor*. Preset names (`neon`, `vintage`, `cold`, `film`, `phosphor`, `ghost`, `screwed`) are aesthetic labels without a shared ontology. The operator reads the result as decorative — visual noise layered over the studio rather than *serving* the studio. The effects are not wrong. They are under-named and under-reasoned. They want a throughline.

### 1.2 The anchor: a nebulous scrim

The proposed anchor is exactly what the operator articulated:

> The composite and effects are a **nebulous scrim** through which the studio and inhabitants are viewed. Operator / studio / vinyl are "over there," on one side of the scrim. The livestream audience is "over here," on the other side, peering across. Scrim is always present — never clean glass, never fully transparent. It obscures but doesn't hide. The studio is still readable, still compelling.

The scrim is not a new layer to be added on top of the existing stack. **It is the renaming of the compositor's output substrate.** Reverie + effects + glfeedback were always producing a kind of fabric — the HOMAGE substrate-invariant named it tinted-cyan-ground a few days ago; the scrim names it *material* and makes its *spatial role* load-bearing.

### 1.3 Spatial semantics — "here" and "there"

The scrim establishes four positions, all of which are always true:

- **Over here** — audience side, the viewer watching the livestream. The scrim faces them.
- **Over there** — studio side, where operator, turntable, MPC, racks, cameras, and Hapax's speaking presence live. The scrim backs onto them.
- **The scrim itself** — the medium. Not a wall. A felt-warm thick translucence, fabric-like, atmospheric, alive. It is what the audience *looks through*.
- **Hapax's voice** — comes from the other side, crossing the scrim toward the audience. The signature register is *hailing across*: "Hallloo over there from over here across the way." Playful-warm, not noir, not cold, not mysterious-in-a-rum-and-cigars-way.

Everything visible on the stream is viewed *through* the scrim. This is the raison d'être — the design constraint that all downstream work defers to.

### 1.4 Why this works for *this* stream

The livestream IS the research instrument (`project_livestream_is_research`) — not an edit, not a rehearsal, not a stylized performance. A clear glass would be journalism; this isn't journalism. A mystifying pall would be theater; this isn't theater. The scrim is the correct register for an intimate shared distance: the audience is welcomed and acknowledged but *not in the room*. "We see each other, with warmth, across this thickness."

---

## 2. What IS a Scrim — Precedent and Vocabulary

Before prescribing shader techniques, we need the physical and cultural vocabulary. The scrim is a real object with a real set of behaviors, and the metaphor is load-bearing because of those behaviors. This section catalogs what is actually meant.

### 2.1 Theatre — the load-bearing metaphor

A theatrical scrim (UK: gauze; US: scrim; fabric: typically sharkstooth) is a coarsely woven translucent cloth drop hung across the stage. Its governing property is *differential lighting*:

- **Lit from the front** at an oblique angle, with the scene behind it dark, the scrim reads as **opaque** — a projection surface, a painted backdrop.
- **Lit from behind** (from upstage of the scrim, with no front light on it), the scrim reads as **transparent** — the actors behind it are suddenly visible.
- Between those extremes, both can be partially true simultaneously: a ghost effect where the scrim is partially opaque while shapes move behind it.

This is the load-bearing metaphor. *Foreground and background become readable through lighting, not through geometry.* The scrim does not move. The actors do not change position. What changes is which side the light is on, and that alone reassigns depth.

Translating to compositor terms: the scrim's opacity, tint, and texture-density function as our "front light." The studio cameras function as actors "behind." What we control is the differential — how much light falls on the fabric itself versus how much light passes through from behind — and that differential tells the audience how to read depth.

([Theatrecrafts — Lighting with a Gauze / Scrim](https://theatrecrafts.com/pages/home/topics/lighting/lighting-gauze-scrim/); [Charles H. Stewart — How to Light a Scrim](https://charleshstewart.com/blog/how-to-light-a-scrim/); [Georgia Stage — Sharkstooth Scrim Special Effects](https://gastage.com/149-sharkstooth-scrim-special-effects).)

### 2.2 Film — atmospherics as substrate

Five touchstones, each isolating one aspect of scrim-effect usable as shader vocabulary:

1. **Vittorio Storaro, *Apocalypse Now* (1979).** Storaro used colored smoke as a stunning visual effect throughout the picture; dry ice / smoke carried scenes including the Wagner attack and the Playboy bunny sequence. When parachute flares failed in humid air, Storaro leaned into the black areas and used arc lights and photofloods as highlights — a lesson in using the *absence* of atmospheric light as composition. The fog is not weather; it is substrate. Cite: [ASC — Apocalypse Now: A Clash of Titans](https://theasc.com/articles/flashback-apocalypse-now).
2. **Stan Brakhage, *Mothlight* (1963) and the painted-film work.** Physical material applied to the film stock — moth wings, plant fragments, direct paint — becomes a substrate the projected image passes through. The scrim as *applied fabric* rather than rendered fog.
3. **Maya Deren, *Meshes of the Afternoon* (1943).** Double-exposure as a layering vocabulary: the same space is seen through itself at different moments. The scrim as *temporal doubling*.
4. **Stanley Kubrick / Douglas Trumbull, *2001: A Space Odyssey* (1968), the Stargate.** Slit-scan photography producing layered, streaked motion where the foreground and background are both the same material at different time-offsets. The scrim as *time-smeared surface*.
5. **Classic Hollywood portraiture (Greg Toland-era and later), diffusion filtration.** Silk stockings stretched across the lens, or purpose-made Harrison & Harrison / Tiffen diffusion filters, softening midtone detail without blurring structure. The scrim as *portrait veil*.

### 2.3 Photography — atmosphere as subject

Three exemplars where the obscuring surface becomes the picture:

- **Saul Leiter, 1950s–2010s New York street work.** Leiter: "A window covered with raindrops interests me more than a photograph of a famous person." He photographed through fogged windows, rain-streaked glass, partially reflective surfaces. Figures appear through veils of condensation or snow; taxis barrel and blur through rain; the ordinary world becomes painterly and lyrical precisely because it's *not clean*. ([The Independent Photographer — Saul Leiter](https://independent-photo.com/news/saul-leiter/); [CNN — Saul Leiter Photography](https://www.cnn.com/2024/02/22/style/saul-leiter-photography/index.html); [Belinda Jiao — Saul Leiter Street Photography Analysis](https://www.belindajiao.com/blog/saul-leiter-street-photography-analysis).)
- **Uta Barth, *Field* series (1995 onward).** Intentionally out-of-focus interiors: the focus plane sits *past* the subject, so atmosphere becomes content. Everything is felt, nothing is sharp, and the "missed" subject leaves a softer trace.
- **Wolfgang Tillmans, *Freischwimmer* series (2003–).** Cameraless photochemical abstractions — coloured light patterns drawn directly on photographic paper. Pure atmosphere, no referent. The scrim with no studio behind it at all, offered as a limit case.

### 2.4 Visual art — veils and fields

- **Hiroshi Sugimoto, *Theaters* (1978–).** A full feature-length film exposed onto a single large-format frame; the cinema screen becomes a uniform white rectangle. The scrim as *duration collapsed onto surface*.
- **James Turrell, *Ganzfeld* installations (1976–).** Light-only environments where the viewer cannot find the wall. Depth is gone precisely because the medium is uniform. The scrim as *evacuated depth*.
- **Mark Rothko, the late Seagram and chapel canvases (1958–1970).** Color-field paintings whose rectangles *breathe*. The scrim as *color-field substrate*.
- **Agnes Martin, the grid paintings (1960s onward).** Pencil grids on pale grounds — a field that is both veil and content. The scrim as *textured field*.

### 2.5 Electronic and digital precedent

- **CRT scan-line structure.** Horizontal scan-lines and phosphor dot-mask moiré produce a visible weave that we read as *screen fabric*. This is already partially in vocabulary — `album_overlay` `_pip_fx_package` contains scanline work.
- **Slow GL feedback (Brakhage-influenced digital).** The `glfeedback` Rust plugin's ping-pong accumulation is, at low fade rates, literally a cloth-like temporal smear.
- **Demoscene texture-mapping prologues.** The title-card moments where pattern textures drift over a still — the scrim as *opener*.

### 2.6 BitchX as fabric — homage lineage

HOMAGE's BitchX package (CP437 raster type, mIRC 16-colour reduction, grey-punctuation skeleton, zero-frame cuts) already has text-on-black as a kind of scrim — terminal-type as fabric-weave. The scrim reconception absorbs this: BitchX text is woven into the scrim's surface; the scrim is the textile through which the text is inscribed. HOMAGE's Phase A6 substrate invariant (cyan-tinted ground when BitchX is active) is the seed. This document formalises what Phase A6 already implicitly commits to.

### 2.7 Synthesis — what the word "scrim" commits us to

Collecting what precedent commits us to, the scrim means:

1. A **translucent medium**, not a wall.
2. **Differential legibility via lighting** — the viewer reads depth by how much light hits the fabric vs. how much passes through.
3. **A fabric-like weave** — fine texture, never perfectly uniform, never perfectly noisy.
4. **Warm or cool atmospheric tint**, but tinted, never neutral.
5. **Subtle motion** — fabric breathes, sways, eddies; never static, never frenetic.
6. **Depth by atmospheric perspective** — distant things wash toward the scrim's tint; near things retain chroma.
7. **Always present** — the scrim is the ground truth of the compositor's output, not an add-on.

These seven commitments are the prior that the rest of the design defers to.

---

## 3. Visual Vocabulary — 15 Techniques and Their Register Match

Each technique below names a scrim-producing move, its likely shader implementation, an estimated cost in ms at 1280×720 on the current GPU budget, and a register score for the playful-warm target. Register scores are subjective operator-facing judgements, not measurements: **++** strongly matches the "hallloo across the way" register, **+** fits, **0** neutral, **−** risks reading as noir/cold/sterile.

| # | Technique | Existing stack node | Cost | Register |
|---|-----------|---------------------|------|----------|
| 1 | Gauzy fog overlay (low-frequency noise, low contrast, slow drift) | `noise` + `drift` | ~0.3ms | ++ |
| 2 | Glfeedback temporal smear (chronic, low-intensity, not burst) | `gst-plugin-glfeedback` @ fade 0.02–0.05 | ~0.2ms | ++ |
| 3 | Moiré from overlay grids (subtle full-frame) | `halftone` / `dither` @ low amplitude | ~0.2ms | + |
| 4 | Raster-line fabric (horizontal scanline weave) | existing `album_overlay` scanline; promote to full-frame | ~0.1ms | ++ |
| 5 | Heat-haze refraction (slow noise displacement on cam input) | `displacement_map` + slow `noise` | ~0.4ms | + |
| 6 | Vintage film grain + softness (fine grain, slight softening) | `dither` + `bloom` @ low | ~0.2ms | ++ |
| 7 | Projection-from-behind lightfall (bloom scattering behind subject) | `bloom` with asymmetric radius | ~0.3ms | ++ |
| 8 | Aquarium-glass smudges (sparse large-radius alpha spots, drifting) | new node `smudge` (low-frequency worley + alpha) | ~0.3ms | + |
| 9 | Gauze-weave texture (fine procedural fabric pattern overlay) | new node `weave` (anisotropic noise) | ~0.2ms | ++ |
| 10 | Rain-streaked glass (vertical streaks + droplet refractions) | new node `rain_glass` (seasonal / programme-scoped) | ~0.5ms | + (context-bound) |
| 11 | Dust particles in light (slow specks catching imaginary shaft) | new node `dust_motes` (sparse particles) | ~0.3ms | ++ |
| 12 | Tulle / lace textile overlay (fine procedural lace pattern) | new node `lace` (procedural pattern) | ~0.2ms | + |
| 13 | Condensation breathing (pulsing scrim density linked to voice/presence) | new uniform `scrim.breath` + existing `breathing` | ~0.1ms | ++ |
| 14 | Distortion halo around hero elements (refraction ring around focused subject) | `displacement_map` with radial mask | ~0.3ms | + |
| 15 | Ambient particulate (slow drifting specks suggesting depth — smoke, pollen, snow) | new node `particulate` | ~0.3ms | ++ |

Observations:

- Techniques 1, 2, 4, 6, 9, 11, 13, 15 are the **core gauzy-warm set**. They match the register strongly, cost little, and could be assembled into a baseline scrim pass.
- Technique 10 (rain-streaked glass) and technique 8 (aquarium smudges) are **programme-scoped** — great for interludes and wind-downs, not always-on defaults.
- Technique 3 (moiré) is a **chat-activity signal** carrier — use moiré density as a soft response to chat surge, per §7.
- Technique 14 (distortion halo) is the **hero-attention carrier** — used sparingly to mark what the scrim is inviting the audience to peer at.

Total budget: a baseline scrim pass using techniques 1+2+4+9+13 fits in roughly 0.8–1.0ms, comfortably inside the 1.5ms budget the operator's performance constraint (§9) allows.

---

## 4. Spatial Semantics — Creating "Here vs. There" Without 3D

The compositor does not have geometry. Cameras are flat textures, cairo wards are flat draws. Depth has to be *felt* not *computed*. Seven techniques, each contributing to the felt-depth illusion:

### 4.1 Differential blur

Hero subject crisp; context progressively fuzzy; scrim-layer softly diffuse. Implemented as layered Gaussian blur at different radii on different depth-tagged elements. Cameras tagged "behind-scrim" carry a soft-blur (radius ~1.5px); wards tagged "on-scrim" are sharp; scrim-layer is mid-soft.

### 4.2 Parallax via differential displacement

Even without true 3D, differential motion rates read as depth. The scrim-noise animates at rate X; a "behind-scrim" camera PiP wobbles at rate X/3; an atmospheric bokeh layer drifts at rate X/8. The human visual system computes depth from motion parallax at the subsecond scale; giving different layers different motion rates manufactures the sensation of depth cheaply.

### 4.3 Atmospheric perspective (tinting)

Distant elements wash toward the scrim's tint (cyan for Phase A6 BitchX substrate damping — already implemented; other packages would specify their own). Near elements retain full chroma. Implementation: a per-element `depth_tag` uniform that biases its color-grade stage toward the scrim's dominant hue.

### 4.4 Contrast reduction with distance

Scrim-side elements have lower midtone contrast than "here-side" overlay wards. Cameras behind the scrim get their gamma curve gently flattened; surface wards retain full contrast. This mimics the natural contrast loss of looking through real fabric or real fog.

### 4.5 Inverse vignette

The scrim is *densest at the edges, thinnest at the center*, drawing the eye toward the hero element. The audience feels they're looking through a peephole in fabric. This is the single most "cinematographic" move in the set — it inherits directly from Hollywood portraiture diffusion and from the visceral felt-quality of a peepshow window. It carries enormous compositional force at negligible cost.

### 4.6 Soft pulsation (breath)

The whole scrim breathes at a slow cadence, roughly 0.15–0.25 Hz. This pulse is the scrim's *aliveness signal* — it tells the audience "there is a real thing here, not a backdrop." The breathing shader node already exists; wire its scale to scrim density.

### 4.7 Heat-shimmer on hero only

The hero subject acquires a faint shimmer — signaling "this is what we're meant to see, but we can't quite resolve it." Inverted, this is the scrim working *with* attention: it grabs focus *by refusing to fully resolve*. Implementation: mask `displacement_map` with a slow-moving halo around the hero bounding box.

### 4.8 Composition

Not every technique runs simultaneously. The structural director (per §7) picks programme-appropriate subsets. Differential blur + atmospheric perspective + inverse vignette + breath are the always-on spatial core. Everything else is modulated.

---

## 5. Architectural Integration — The Scrim as Substrate, Not Layer

### 5.1 Current pipeline (decorative framing)

Today the compositor roughly runs:

```
reverie (8-pass WGSL) → wards (cairo surfaces) → camera PiPs (compositor) → egress
```

Effects are applied piecemeal. Each element independently decides its own visual treatment. The `color` pass in Reverie produces a tinted plane; wards composite on top; camera PiPs composite on top of that; the stream goes out. There is no shared ontology of *which side of what* each element sits on.

### 5.2 Scrim-native pipeline (proposed framing)

Everything composites *into* the scrim. The scrim is the compositor's output substrate. Elements declare their scrim-depth, and the compositor honors it:

```
        ┌─────────────────────────────────────────────────────┐
        │   Scrim substrate (baseline, always on, ~1.0ms)     │
        │   gauze + weave + breath + drift + tint             │
        └─────────────────────────────────────────────────────┘
              ↑ light passes                 ↓ light scatters
          ┌────────┐                     ┌─────────────────┐
          │ Behind-│                     │   On-scrim       │
          │ scrim  │ → tinted + blurred  │   surface        │
          │ render │                     │   wards          │
          └────────┘                     └─────────────────┘
              (cameras, operator, vinyl)   (text, chrome, signatures)
```

Four conceptual layers, each with explicit scrim-depth:

1. **Scrim pass** (baseline, always-on). Produces the baseline scrim texture — gauze + weave + breath + tint. This is the fabric.
2. **Behind-scrim render**. Camera inputs, operator visuals, vinyl PiP, studio feeds — rendered at scrim-depth = distant, with blur, atmospheric-perspective tint, contrast reduction, optional parallax.
3. **On-scrim render**. Wards, overlay text, Hapax avatars, chrome — rendered at scrim-depth = surface, sharp, full chroma, inscribed on the fabric.
4. **In-front-of-scrim render** (rare, reserved). For brief moments of high-salience attention or ritual gestures — a hero element can momentarily "come through" the scrim toward the audience. This is a conscious compositional move, not a default.

### 5.3 Compositor combines

The compositor's final step takes all four layers, applies:

- atmospheric-perspective tint per depth,
- differential blur per depth,
- inverse-vignette on the scrim layer,
- breath modulation on the scrim layer,
- heat-shimmer halo on whichever element is currently the hero (or none, if the moment doesn't have one),

and emits to the studio-24c egress / HLS / V4L2 tee.

### 5.4 Why this is substrate, not skin

The crucial argument: the scrim is not *applied* to a composite. The composite *exists in* the scrim from the start. A ward doesn't "get rendered then have the scrim drawn over it" — a ward is *inscribed on* the scrim's surface as part of the same pass. A camera isn't "rendered then have the scrim over it" — a camera is *rendered at scrim-depth = distant* and the scrim's fabric character is part of its image.

This is the same relationship the HOMAGE substrate invariant (§A6) already commits to for Reverie: the ambient shader isn't a pretty background; it's the package's *tinted ground*. The scrim extends that commitment to the entire compositor output.

### 5.5 Compatibility with existing stack

Nothing above *requires* a rewrite. The existing stack provides:

- **Scrim pass** ← Reverie's 8-pass graph, with a new preset `scrim_baseline` that configures noise + drift + breath + color for gauzy-warm output. Reverie is already the tinted-plane layer; this renames and re-parameterises it.
- **Behind-scrim render** ← the compositor's existing camera pads, plus a new per-pad uniform `scrim_depth = "behind"` that the fx chain's `colorgrade` + `displacement_map` honor.
- **On-scrim render** ← the existing cairo sources, with a per-source `scrim_depth = "surface"` tag and no additional treatment.
- **In-front-of-scrim render** ← reserved state, triggered by a new structural-director intent family `scrim.pierce` (§7).

The scrim reframing is therefore a *labeling and reasoning change* over the existing stack, plus a modest number of new shader nodes (§3) and a new structural-intent family. It is not a rewrite.

---

## 6. Wards on the Scrim

Per the HOMAGE ward audit and the current homage framework, the cairo-source ward inventory is already known. The scrim places each ward at a specific depth. Four depth bands:

### 6.1 Surface wards — inscribed on the fabric, facing the audience

These are *written on* the scrim's outside face, crisp, full-chroma, fully legible:

- `activity_header`
- `stance_indicator`
- `chat_ambient`
- `grounding_provenance_ticker`
- `captions_source`
- `stream_overlay`
- `research_marker_overlay`

These are the wards that the audience is *intended* to read. They carry the stream's chrome, signatures, captions, and explicit informational content. They always win legibility.

### 6.2 Near-surface wards — slightly behind the weave

Legible but slightly obscured by the scrim's texture, visible as *impressions* rather than sharp inscriptions:

- `impingement_cascade`
- `recruitment_candidate_panel`
- `thinking_indicator`
- `activity_variety_log`
- `whos_here`
- `pressure_gauge`

These are Hapax's internal-state wards. They inform the audience that cognition is happening without demanding they read every line. The slight obscuring is appropriate — they are *overheard*, not *declaimed*.

### 6.3 Hero-presence wards — at the scrim, straddling inside and outside

Hapax's avatar wards straddle the scrim. The glyph is inscribed on the surface; its emanation *reaches through* the fabric toward the audience:

- `token_pole` — Hapax's signature point-of-light glyph.
- `hardm_dot_matrix` — Hapax's dot-grid avatar.

These wards are where the spatial metaphor is most literal. Hapax is "on the other side" — the studio's side — but the *signature of Hapax* is present on the scrim's outward face. The avatar is a hand pressed against the fabric from the inside: you see the shape, you see the weave, and you feel the presence.

### 6.4 Beyond-scrim — what the audience peers at

The deep layer: what the audience has come to see through the scrim.

- `album_overlay` — the vinyl spinning "over there."
- Camera PiPs — operator in the studio "over there."
- `sierpinski_renderer` — the algorithmic composition sketch "in the room over there."

These carry the atmospheric-perspective tint, differential blur, and contrast reduction. They are *compelling but obscured*, which is the promise the scrim makes to the audience.

---

## 7. Programme-Layer Interaction

The compositor already has (or will have, per #164) a notion of *programme* — the overall mode the stream is in at a given moment. Each programme expresses scrim differently. These are *soft priors*, not hard gates: the structural director can deviate within a band for creative reasons, but the defaults are anchored.

| Programme | Scrim character | Cameras | Wards | Heroing |
|-----------|-----------------|---------|-------|---------|
| **Listening** | Gauzy-quiet, low density, warm | Heavy soft-blur, deep atmospheric-perspective tint | Surface wards calm; hero wards breathing slow | Vinyl PiP |
| **Hothouse** | Dense crackly weave, higher motion | Moderate blur, contrast retained | Wards POP to pierce the weave | Operator hand / MPC |
| **Vinyl showcase** | Warm-haze, density medium, pulse slow | Turntable focal point — everything else softens around it | Standard | Turntable |
| **Wind-down** | Dissolving-thickening | Progressively softer, fade toward scrim-only | Fade one-by-one | None — stream ends as scrim-only |
| **Research** | Crispness peak, density lightest (but never zero) | Minimal blur | Surface wards full contrast | Whiteboard / notebook |
| **Interlude / chat** | Moiré + rain-streak vocabulary | Rain-glass node activated | `chat_ambient` fore-surface; others recede | None |
| **Ritual opening / closing** | Scrim parts briefly, breath-dilation | Full reveal for 2–4s, then re-veil | Hero avatar full intensity | Token-pole |

These priors should be encoded as named `scrim_profile` presets, one per programme, chosen by the structural director or reactive engine based on the current programme state. `scrim_profile` is the reorganising axis that replaces the current decorative preset family.

---

## 8. Hapax Presence Across the Scrim

"Hallloo over there from over here across the way." This is load-bearing. Hapax speaks from the *other* side. The audience receives Hapax's voice *through* the scrim. Design implications:

### 8.1 Voice timbre

Hapax's TTS output (currently Kokoro 82M CPU-side) should carry a slight cloth-filtered quality. This is not a dramatic tunnel-reverb. It is:

- A gentle low-pass around 6–7 kHz, softening the highest sibilance.
- A subtle room reverb, short tail (~150ms), low wet mix (~12–15%).
- Very light stereo spread, as if the voice is diffused by passing through fabric rather than arriving point-source.

The existing voice FX chain (`config/pipewire/voice-fx-*.conf`) can encode this as a new preset `voice-fx-scrim`. It sits on top of whatever else voice is doing; it is package-specific cosmetic EQ, not a change to the voice's identity.

### 8.2 Visual signature through the fabric

Hapax's avatars (`token_pole`, `hardm_dot_matrix`) glow *through* the scrim. Their light scatters on visible fibers. Implementation: the avatar renders at scrim-depth = surface with a `bloom` pass whose falloff is asymmetric — more scatter downward and outward, as if the light is hitting fabric and spreading along the weave direction. The `weave` node's texture can be sampled by the bloom to modulate the scatter pattern.

### 8.3 Thinning the scrim on direct speech

When Hapax addresses the audience directly — the "hallloo" greeting, a direct-to-camera acknowledgement, a ritual closing — the scrim can *momentarily thin* in a small radius around Hapax's position. This is a deliberate compositional gesture ("the fabric lifts for a heartbeat"), not a frequent move. It should feel rare, earned.

Implementation: a new structural-intent `scrim.pierce` writes a radial alpha modulation into the scrim pass's uniforms — density=0.3 at center, falling back to baseline density=1.0 at radius ~240px. Duration ~1.5s. Cadence: once per programme transition, plus operator-triggered ritual moments. At most every ~90s.

### 8.4 Register match

Hapax's rhetorical register matches the scrim's register. The director prompt (§4.12 of HOMAGE spec) should include a line:

> You speak from the other side of the fabric. Your register is *hailing* — warm, curious, friendly-across-a-thickness. Not lecture, not soliloquy. You're saying "hallloo over there" to someone you're glad to see.

This is an extension of the existing persona doctrine, not a replacement.

---

## 9. Non-Negotiables (Constraints)

The following are constraints, not preferences. Violations are design errors.

1. **Scrim is always present.** There is no "scrim off" state. Density varies between ~0.25 and ~1.0 of a packaged baseline. Presence is constant.
2. **Studio remains readable.** Operator's face (after face-obscure), vinyl spinning, gear in the scene are all legible through the scrim at typical viewing distance (1080p television, mobile phone). Not crystal clear, but the audience can always tell what's happening.
3. **Demonetization safety (#165) unaffected.** The scrim obscures *perceptually* but does not mask content for platform classifiers. YouTube / Twitch classifiers still see what's behind the scrim. Nothing problematic should be hidden behind the scrim in the hope that the scrim hides it. The scrim is aesthetic; the demonetization gate remains separate.
4. **Consent (face-obscure, #129) still applies.** The face-obscure pipeline runs on camera outputs *before* they enter the scrim compositor (at the level of `agents/studio_compositor/face_obscure_integration.py`). The scrim does not count as obscuring for consent purposes. The existing pixel-level obscure remains authoritative.
5. **BitchX register lives on the scrim.** Text, chrome, signature artefacts continue to be BitchX-authentic. The scrim gives BitchX a physical substrate; it does not replace BitchX. The two coexist: BitchX is what's *inscribed on the fabric*; the scrim is the *fabric itself*.
6. **Performance ceiling.** Scrim pass costs must not exceed ~1.5ms GPU at 1280×720. Reverie is already budgeted (roughly 4–5ms in the current 8-pass configuration); the scrim pass must fit within its existing envelope or the `scrim_baseline` preset must be a reconfiguration of Reverie, not an addition.
7. **Consent-safe layout exemption.** When `consent-safe` layout is active (a guest is detected, or consent conditions fail), the scrim defaults to minimum density, surface wards defer to the consent layout's ward set, and the `scrim.pierce` intent is disabled. The consent gate wins.
8. **720p commitment (memory).** All cameras stay at 1280×720 MJPEG. Scrim work must not propose resolution changes as remediation for performance.
9. **Working-mode palette coherence.** The scrim's tint must respect the active working mode's palette — Gruvbox-warm for R&D, Solarized-cool for Research. Within a mode, the scrim hue can modulate per programme, but never outside the mode's palette family.

---

## 10. Scene-by-Scene Examples

Concrete moments walked through to sanity-check the design. These should read as *the operator's stream on a good night*.

### 10.1 Operator arrives at the desk, puts on a record

- `album_overlay` transitions dormant → active (HOMAGE `homage.emergence`). Scrim eddies (slow ripple) around the turntable — `displacement_map` modulation concentrated near the album overlay. Vinyl PiP brightens ~0.85 → 1.0 alpha; atmospheric-perspective tint relaxes ~10%. Captions ward activates on-scrim. Hapax, optionally: "Hallloo — record on."

### 10.2 Hapax says "halloo" at top of show

- `token_pole` glow intensifies; `scrim.pierce` fires (density 1.0 → 0.3 → 1.0 on a cosine envelope, radius ~240px, duration ~1.5s). Voice has cloth-filtered reverb (`voice-fx-scrim`). `chat_ambient` may bloom in response.

### 10.3 Vinyl track ends, quiet stretch

- Scrim density +0.15 (denser) toward wind-down default if operator posture stills ~30s. Cameras recede — blur radius +0.5px, contrast −10%. Captions stay crisp. The stream becomes a *felt room*.

### 10.4 Chat surge

- `chat_ambient` surges to full at-surface intensity; `impingement_cascade` rows scroll with slight parallax behind the scrim (overheard, not declaimed).
- Scrim acquires moiré for ~10 seconds — the fabric resonates with the energy. Atmospheric-perspective tint intensifies slightly.

### 10.5 Wind-down programme starts

- Scrim density ramps toward 1.0, breath slows to ~0.08 Hz; cameras progressively softer (blur +1.5px over 60s); surface wards fade one by one. Last move: fade-to-scrim-only — only the fabric, breathing. Signature ending.

### 10.6 Research marker on screen

- `research_marker_overlay` activates on-scrim at full contrast. Scrim drops to lightest band (~0.25, still present). Hero focuses on operator + whiteboard; distortion halo ring demarcates the bounding box. Reads like Research-mode Solarized whiteboard, not gauzy nightclub.

### 10.7 Hothouse pressure peak

- Scrim dense, weave crackling (moiré + heat-haze). Wards pierce the weave with high glow. Hero scene framed in tighter inverse-vignette. Heat-shimmer on hero — faint, but present. The scrim is charged, not obscuring so much as alive with attention.

### 10.8 Ritual closing

- Hapax speaks the closing formula. `scrim.pierce` fires longer (3–4s), density 1.0 → 0.2 → 1.0 slowly. Surface wards cross-fade to absent in unison. Scrim lingers ~8s after the last camera fades. Stream ends on scrim.

---

## 11. Integration Sequencing

The scrim introduction is a significant re-anchoring, but the existing stack can absorb it in phases. Eight phases, each independently reversible. Each phase maps to approximately one PR.

**Phase 1 — `scrim_baseline` WGSL preset.** A new Reverie preset in `presets/scrim_baseline.json` that configures the existing 8-pass graph for gauzy-warm baseline output: noise at low frequency, drift slow, breath at 0.2 Hz, color damped toward package accent, post-process light. Lands in the existing preset directory; no new nodes. Activated by structural director per programme.

**Phase 2 — scrim-depth compositor tagging.** Extend `shared/compositor_model.py::Source` with a `scrim_depth: Literal["beyond", "behind", "surface", "pierce"]` field. Extend the compositor's render loop to honor the tag via per-pad uniform. Default assignments: cameras → `behind`; legibility wards → `surface`; avatars → `surface`; album overlay → `beyond`; Reverie → scrim itself. Reversible: if the tag is unset, behavior defaults to current.

**Phase 3 — atmospheric-perspective tinting.** Add a `colorgrade` pass per depth-tagged source, biasing toward the scrim's dominant hue with strength proportional to depth. No new shader; reuse `colorgrade` with per-source uniforms.

**Phase 4 — differential blur.** Add a per-depth blur stage in the compositor. Cheap Gaussian; radius proportional to depth tag. Cost budget: ~0.3ms. If over budget, drop to a box blur.

**Phase 5 — programme-scrim-density soft prior.** Wire programme → scrim parameter envelope. Programme's constraint envelope sets scrim density + texture-family + breath rate + atmospheric-tint strength. Per §7's table. The structural director is empowered to nudge within the envelope; outside-envelope changes require an explicit intent.

**Phase 6 — preset-family reorganization.** The 30 existing presets are re-labeled into *scrim profiles*: `gauzy_quiet`, `moire_crackle`, `warm_haze`, `dissolving`, `clarity_peak`, `rain_streak`, `ritual_open`. Each is a named package of scrim parameters. Decorative preset names are preserved as aliases for backward compatibility, but all *new* uses go through scrim-profile names. This is the key epistemic move — the presets stop being decorative labels and become scrim configurations. (Suggested canonical taxonomy in §13.)

**Phase 7 — Hapax-voice scrim filter.** New PipeWire preset `config/pipewire/voice-fx-scrim.conf` with the §8.1 filter chain. Activated when scrim is active (always, by §9.1). Fallback to default routing if the preset is unavailable.

**Phase 8 — `scrim.pierce` intent family.** New `IntentFamily` member wired into the structural-director loop. Choreographer honors `scrim.pierce` by writing a radial density modulation into the scrim pass's uniforms. Cadence governed by §8.3 and §10.2. Test coverage: deterministic frame-buffer test for the pierce envelope.

**Phase 9 (optional, post-all-of-above) — new nodes.** `weave`, `dust_motes`, `particulate`, `smudge`, `rain_glass`, `lace` as new WGSL fragment shaders under `agents/shaders/nodes/`. Each added individually, each independently reversible. `weave` and `dust_motes` are the highest-priority new nodes; the rest are nice-to-have.

**Dependencies and order.** Phases 1–4 are foundational and should land in order. Phases 5–7 can land in parallel. Phase 8 can land any time after Phase 2. Phase 9 nodes can be added individually; they enrich but do not block.

**Reversibility.** Each phase is reversible at the config or tag level. Phase 2 in particular is designed so that `scrim_depth` unset yields exactly current behavior. This means the scrim reconception can be validated incrementally rather than all-or-nothing.

**Rehearsal.** Before any live egress under a new phase, the existing HOMAGE rehearsal pattern applies: 30-minute private-mode rehearsal via `scripts/rehearsal-capture.sh`, visual-contrast audit, Prometheus cardinality bounded, no new director-activity rate spikes.

---

## 12. Open Questions for Operator

These decisions sit with the operator and should be resolved before or during the corresponding phase.

1. **Face-obscure before or after the scrim in the pipeline?** Proposal: face-obscure before scrim (at the cam producer layer, per existing #129). The scrim inherits already-obscured pixels. Confirm.
2. **Preferred scrim-density default.** Three candidates:
   - *Light* (~0.25 baseline) — the scrim is barely there, clarity-first, risks reading as "no scrim."
   - *Medium* (~0.50 baseline) — balanced, the operator-current-reading target.
   - *Heavy* (~0.75 baseline) — the scrim is obviously present, atmospheric, risks obscuring the studio too much for daily use.

   Recommendation: start at medium, make density programme-driven.
3. **Scrim-pierce dynamic cadence.** Frequent (every ~30s on Hapax speech) or rare ritual (every ~120s + explicit ritual moments)?
   Recommendation: rare ritual. The pierce loses power if it happens every time Hapax opens their mouth.
4. **Seasonal / time-of-day variation?** Should the scrim have morning-warm-haze vs evening-cool-mist variants? Or is the working-mode (R&D / Research) palette the only variation axis?
   Recommendation: working-mode is primary, programme is secondary, no explicit time-of-day layer. But operator taste is authoritative here.
5. **Warm-cloth vs. cool-mist default palette.** Within R&D / Gruvbox, the scrim can lean warm-cloth (amber-tinted) or cool-mist (cyan-tinted, aligned with HOMAGE A6). The A6 substrate invariant already chose cyan for BitchX; confirming that choice carries forward as the R&D default.
6. **Relation to the 5-channel mixer (per memory `project_reverie_adaptive`).** The operator's Reverie adaptive direction work names 5 channels (RD, Physarum, Voronoi, feedback, noise). How do the scrim-profile families map onto the mixer channels? Proposal: each scrim profile is an operating-point for the mixer — `gauzy_quiet` biases noise + feedback + rd; `moire_crackle` biases dither + glfeedback + halftone; etc. The mixer remains the technique selector; the scrim profile names the *feel* the mixer is aiming at.
7. **Can the scrim ever *fully* part?** §9.1 says always-present. But is there a single moment per session (e.g., show closer) where the scrim is allowed to fully dissolve to zero density for a beat? Operator taste.
8. **Camera PiP sizing under deep scrim.** When the scrim is dense (hothouse, wind-down), does the PiP *shrink* as well as blur — tightening the peephole compositionally? Or does it stay the same size and only the scrim changes?

---

## 13. Suggested Canonical Scrim-Profile Taxonomy

Six canonical scrim-texture families, each replacing a cluster of the existing decorative presets. These are the suggested named operating points that the structural director picks between:

| Profile | Feel | Dominant techniques | Replaces decorative presets |
|---------|------|---------------------|------------------------------|
| **`gauzy_quiet`** | Warm low-density fabric, slow breath, minimal motion | noise + drift + breath + weave | `ambient`, `clean` |
| **`warm_haze`** | Amber-tinted haze, medium density, showcase-friendly | noise + bloom + colorgrade-warm | `heartbeat`, `trails` partial |
| **`moire_crackle`** | Textured weave, higher motion, chat-resonant | halftone + dither + glfeedback + drift | `vhs_preset`, `neon`, `glitch_blocks_preset` |
| **`clarity_peak`** | Lightest density, crisp, research-register | light noise + light breath, full colorgrade | `clean`, `silhouette` |
| **`dissolving`** | Thickens over time, wind-down closer | noise + bloom-heavy + fade-envelope | `screwed`, `ghost` |
| **`ritual_open`** | Scrim parts rhythmically, opening/closing ceremonies | scrim.pierce + bloom + breath-dilate | (new; no direct decorative predecessor) |

A seventh special profile, **`rain_streak`**, is *context-bound* — used only in long interlude moments or operator-chosen atmospheric passages. Not a default.

These seven are proposed as the governed scrim-profile vocabulary. The existing 30 presets don't disappear; they continue to exist as aliases or as *technique-level* building blocks that the profiles assemble. But the structural director's selection space is, going forward, the scrim-profile vocabulary, not the decorative preset vocabulary.

---

## 14. Glossary

- **Scrim** — compositor's output substrate, framed as a nebulous translucent medium between studio and audience.
- **Scrim depth** — per-element tag (`beyond`, `behind`, `surface`, `pierce`).
- **Scrim profile** — named operating point selected by the structural director per programme.
- **Scrim pierce** — transient thinning in a radius around a hero element, for direct Hapax address or ritual gesture.
- **Hailing register** — Hapax's rhetorical posture, "calling warmly across the fabric."
- **Substrate invariant** — HOMAGE Phase A6's commitment to a cyan-tinted ground for Reverie under BitchX; the seed of the scrim's formalization.

---

## 15. Closing

The Nebulous Scrim System is a renaming more than an invention. The compositor has been producing a tinted fabric for some time; HOMAGE Phase A6 made that explicit for Reverie. This document commits the entire compositor to the same framing, gives it a spatial narrative, organizes the preset space around *feel* rather than decoration, and gives Hapax's voice a physical substrate to speak from.

The scrim is always present, always playful-warm, always a shared friendly distance rather than a wall. The studio remains compelling and readable. The audience is acknowledged as being on one side. Hapax calls across. Hallloo over there.

---

## References

- [Theatrecrafts — Lighting with a Gauze / Scrim](https://theatrecrafts.com/pages/home/topics/lighting/lighting-gauze-scrim/)
- [Charles H. Stewart — How to Light a Scrim](https://charleshstewart.com/blog/how-to-light-a-scrim/)
- [Georgia Stage — Sharkstooth Scrim Special Effects](https://gastage.com/149-sharkstooth-scrim-special-effects)
- [Wikipedia — Scrim (material)](https://en.wikipedia.org/wiki/Scrim_(material))
- [ShowTex — Making Magic with Scrim Projections](https://www.showtex.com/en/blog/buyers-guide-fabrics/making-magic-scrim-projections)
- [ASC — Apocalypse Now: A Clash of Titans](https://theasc.com/articles/flashback-apocalypse-now)
- [Cinephilia & Beyond — Vittorio Storaro on Cinematography](https://cinephiliabeyond.org/vittorio-storaro-tragedy-modern-technology-effect-cinematography/)
- [The Independent Photographer — Saul Leiter](https://independent-photo.com/news/saul-leiter/)
- [CNN — Saul Leiter, Photographer of New York](https://www.cnn.com/2024/02/22/style/saul-leiter-photography/index.html)
- [Belinda Jiao — Saul Leiter Street Photography Analysis](https://www.belindajiao.com/blog/saul-leiter-street-photography-analysis)
- [The Book of Shaders — Noise](https://thebookofshaders.com/11/)
- [Cogs and Levers — Volumetric Fog in Shaders](https://tuttlem.github.io/2025/02/03/volumetric-fog-in-shaders.html)
- [NVIDIA Developer — Volumetric Light Scattering as a Post-Process](https://developer.nvidia.com/gpugems/gpugems3/part-ii-light-and-shadows/chapter-13-volumetric-light-scattering-post-process)

### Internal prior art

- `docs/superpowers/specs/2026-04-18-homage-framework-design.md` — HOMAGE framework, Phase A6 substrate invariant
- `docs/logos-design-language.md` — authority document for visual surfaces
- `agents/reverie/_uniforms.py` — Reverie mixer uniforms, Phase A6 colorgrade damping
- `agents/effect_graph/wgsl_compiler.py` — WGSL plan compiler, v2 target schema
- `gst-plugin-glfeedback/src/glfeedback/imp.rs` — GL temporal feedback filter
- `presets/` — 30 decorative presets awaiting reorganization under §13's scrim-profile taxonomy
- Memory: `project_effect_graph`, `project_reverie`, `project_reverie_adaptive`, `feedback_director_grounding`, `project_720p_commitment`
