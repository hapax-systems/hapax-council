# Video-Container + Mirror-Emissive HOMAGE Ward Conversion — Research

**Date:** 2026-04-23
**Session:** delta (research only — no implementation)
**Operator directive:**
> I want the entire homage ward system to be converted to video-container
> wards by default that also have mirror emissive homage wards. Doing
> this will let us double down on parallax effects. Reverie also needs
> to be converted to a first-class homage ward. Research all the
> implications and we will discuss.

## 1. Interpretation of the directive

Three coupled changes:

1. **Every HOMAGE ward ships as a video-container by default.** The ward
   shape (geometry, mask, "what region of the canvas this ward owns") is
   kept; the default *content* inside that region is a live video frame
   rather than an emissive drawing.
2. **Every video-container ward has a mirror emissive ward.** The
   BitchX-grammar / dot-matrix / glyph renderings we have today don't
   disappear — they become the *twin* of the video-container version.
   Both coexist at the same semantic slot so parallax can operate on
   the pair.
3. **Parallax is now first-class.** The two layers are offset relative
   to each other along a motion axis (position, scale, and/or depth
   stack) driven by some signal. That signal is what gives the scene
   the felt sense of depth.

Plus: **Reverie** ceases to be a dedicated bespoke surface at `pip-ur`
and becomes one of the N wards, with the same dual-layer treatment as
everything else.

## 2. Current architecture as leverage surface

What we already have that this rests on:

- **Sierpinski is the existence-proof** for video-container HOMAGE
  wards. It's a `HomageTransitionalSource` whose `render_content()`
  blits `cairo.ImageSurface` frames (loaded from
  `~/hapax-state/yt-slots/slot_N.jpg`) into per-slot triangular
  regions. The geometry is the ward; the video frames are the content.
- **Reverie is already an `external_rgba` substrate** piped through
  `/dev/shm/hapax-sources/reverie.rgba` into the compositor via
  `ShmRgbaReader`. `source_registry.py:195` already treats the Reverie
  slot as a first-class external source. So "reverie frames as video
  substrate" is a one-line reassignment — the pipe exists.
- **Ward properties** (`ward_properties.py`) already carry
  `position_offset_x/y`, `drift_type/hz/amplitude_px`, `scale`,
  `alpha`, `z_plane`, and `z_index_float`. Parallax is a natural fit
  onto these fields, not a new coordinate system.
- **`z_plane_constants.py`** already stratifies wards across depth
  planes (`back-scrim`, `mid-scrim`, `on-scrim`, `fronting`). Adding a
  *behind-ward video plane* and a *fronting emissive plane* slots into
  the existing ladder.
- **Cairo sources** already render on background threads
  (`CairoSourceRunner`). A ward's emissive layer and video layer can
  be two independent runners feeding the same screen region at
  different Z.
- **HomagePackage** already owns the emissive colour palette + BitchX
  grammar. It has no video side yet — that's new.

## 3. What has to change

### 3.1. The ward abstraction

Today a ward is one source → one surface → one Z. After:

- A ward becomes a **named pair** (`ward_id.video`, `ward_id.emissive`).
- Either leg can be omitted at layout time, but the default is both.
- `SourceSchema` gets a `pair_role` field (`video` | `emissive` |
  `solo`); `solo` is the back-compat value for wards that aren't being
  paired (token_pole? sierpinski-itself? see §9).
- Layout is extended with `paired_placement`: one anchor geometry,
  then a declarative offset per leg (e.g. `video_offset_x=−8`,
  `emissive_offset_x=+8`) so parallax is expressed at layout time, not
  hand-wired into every ward.

### 3.2. Video substrate — where the frames come from

Three plausible sources; the choice shapes the rest of the design:

**A. Reverie is the universal substrate.** Every video-container ward
reads a *region* of the Reverie canvas. Parallax is cheap: the ward
samples a shifted rect from the shared texture. One GPU pipeline feeds
N ward containers. This is also the cleanest way to make
"Reverie-as-ward" real — Reverie's own video-container shows the
full-frame substrate; every other ward's video-container shows a
crop/filter/mask of it. **This matches the "doubling down on parallax"
language best** — parallax between wards is automatic when the
substrate is shared.

**B. Per-ward independent video sources.** Each ward picks its own
feed (YouTube slot, camera, imagination preset, recorded clip). More
expressive, but multiplies decode cost, VRAM, and governance
surface-area (every feed needs face-obscure + monetization gates). It
also makes inter-ward parallax arbitrary — the videos don't share a
coordinate system, so "parallax between them" is metaphor, not actual
perspective.

**C. Hybrid: one shared substrate, per-ward override.** Reverie is the
default; a ward can opt into its own feed when it has a good reason
(sierpinski keeps YouTube slots, album keeps the cover image,
vinyl-platter keeps the camera feed). Most wards inherit the default
and get free parallax; the handful with strong content identity keep
their bespoke video.

Option C is the likely sweet spot — cheap by default, expressive
where it earns it.

### 3.3. Parallax mechanics

Parallax needs a **motion axis** and a **signal**. Candidate axes:

- **Position parallax**: video layer and emissive layer translate by
  different scalars of the same motion vector (classic 2D parallax).
- **Scale parallax**: one layer scales faster than the other under a
  zoom signal (gives breathing-depth).
- **Depth parallax**: the layers sit on different Z planes and a
  fronting blur / chromatic-aberration shift is applied proportional
  to "distance" (fake 3D).
- **Crop parallax (Reverie-substrate only)**: both layers read the
  shared substrate, but at different crop offsets — the *content* of
  the video shifts under the emissive overlay.

Signals that could drive parallax:

- **Audio reactivity** (bass_band / mid_band / treble_band from
  `shared/audio_reactivity.read_shm_snapshot`) — already wired into
  album_overlay, natural fit.
- **IR gaze / head-pose** (`ir_head_pose_yaw`, `ir_gaze_zone`) — the
  operator's actual head movement drives actual parallax. Strongest
  "real depth" signal but costs realism if gaze tracker is jittery.
- **Stimmung vector** (valence/arousal/intensity) — slower, mood-
  locked parallax. Useful as a bias; too slow to be the only signal.
- **Director intent** (`StructuralIntent`, `programme_beat`) — discrete
  shifts on beat boundaries; good for punctuation, not continuous
  motion.
- **Time** — a constant small drift. Safe fallback when no stronger
  signal fires. Must obey the 2026-04-23 no-blinking directive:
  smooth envelopes, no flashes.

Realistic mix: IR-gaze as primary when present, audio as fallback,
time as idle bias.

### 3.4. Reverie promotion to first-class ward

Reverie currently holds a fixed geometry (`pip-ur`, 640×360). As a
HOMAGE ward:

- Reverie registers two legs: `reverie.video` (the wgpu RGBA stream)
  and `reverie.emissive` (a BitchX readout of its 9-dim state —
  intensity, tension, depth, coherence, spectral_color, temporal_
  distortion, degradation, pitch_displacement, diffusion — rendered
  as a small grid of labelled gauges). The emissive leg is new.
- Reverie becomes subject to the affordance pipeline like any other
  ward — gets `WardProperties`, can be recruited, can be placed by
  the director, can be retired by the choreographer. Loses its
  hardcoded `pip-ur` anchor (but still *defaults* there in the layout
  file, same way token-pole defaults to pip-ul).
- If Reverie is the shared video substrate (option A/C above), then
  the distinction between "Reverie ward" and "the substrate every
  other video-container samples from" collapses nicely: Reverie's own
  ward *is* the full-frame view of what all the other wards are
  cropping from. That's architecturally elegant.
- Loss: Reverie's dedicated fixed surface goes away. Anything that
  assumed "Reverie always at pip-ur" has to read the layout instead.
  Mostly benign — the fx_chain layer-resolver already works through
  the layout.

### 3.5. Compositor render loop

Cairo overlay callback already does one pass per tick. With paired
wards:

- Back pass: all `*.video` sources blit in Z-order.
- Middle pass: operator-content surfaces (Obsidian overlays, album
  imagery, sierpinski — the "operator voice" channel from §1 of this
  doc's companion conversation).
- Front pass: all `*.emissive` sources blit in Z-order, with parallax
  offsets applied.
- Shader chain runs over the composited result (same as today).

Parallax offsets are applied per-frame at the source→surface
projection step, not baked into the source cache. Cheap.

### 3.6. Governance carryover

- **No-flashing (2026-04-23)** — parallax motion must use smooth
  envelopes (ease/sine/log); no frame-level snaps. The neutralization
  of `position_offset_x/y` we just shipped in PR #1237 has to be
  **unwound selectively** for this work: the drift mechanism was the
  right primitive, but right-edge clipping was the off-screen culprit.
  Solution: re-enable position_offset, but constrain each ward's
  offset to stay within the ward's surface rect (clip, don't pan off).
- **Zero-container-opacity (2026-04-23)** — the emissive leg still has
  to follow this. No background rectangles, no border strokes. Text
  with outline contrast, glyphs on transparent field.
- **Face-obscure fail-closed** — if reverie substrate ever composites
  camera frames (it currently doesn't directly — cameras go through
  `face_obscure_pipeline` first), the same gate protects it. If a
  ward opts into its own camera feed (option C), it must go through
  `face_obscure_integration` upstream.
- **Monetization risk gate** — every video-container ward is now a
  broadcast surface. Ring 2 pre-render classifier
  (`de-monetization Phase 3`) already classifies risk on content
  going to livestream; this fans out to N video containers.
- **Ward count / HOMAGE ward registry (OQ-02)** — the ward taxonomy
  doubles. Registry and choreographer need updating; tests that count
  wards (see `tests/studio_compositor/test_homage_ward_count.py` if it
  exists) need new expected values.

### 3.7. Performance envelope

Back-of-envelope:

- **Current**: 1 Reverie wgpu pipeline, ~12 Cairo sources, 1 shader
  chain, 30 fps, fits under budget.
- **After (option C)**: 1 Reverie wgpu pipeline, ~24 Cairo sources
  (12 video + 12 emissive), 1 shader chain, parallax offset math
  per-frame per ward. Cairo cost scales linearly with surface count;
  video-container sources are cheap (blit a region of the shared
  substrate + clip) compared to text-rendering sources. Should fit.
- **VRAM**: no change from baseline if option A/C. Option B (per-ward
  independent video) could 2–3× VRAM; not recommended while TabbyAPI
  owns ~22 GiB on the 3090.
- **Parallax math** is a per-frame add per ward — trivial.

The lurking cost is Cairo surface allocation churn. The existing
transient texture pool pattern (already in `DynamicPipeline` for
Reverie) should be extended to the Cairo side.

## 4. What stays single-layer

Not every ward benefits from a video twin. Candidates to remain
`pair_role=solo`:

- **Sierpinski** — it's already a video container; the emissive
  version would duplicate what the substrate shows. Sierpinski's
  semantics IS the fractal geometry.
- **Album overlay** — splattribution text IS the ward. A video layer
  behind it would compete with the album-cover image.
- **Vinyl-platter** — the camera feed of the actual platter is the
  ward.
- **HARDM dot-matrix** — the grid is the ward; a video backing would
  drown the emissive encoding. Unless the "video" is the operator's
  own camera feed filtered through the dot-matrix threshold, which
  would be an interesting HARDM-native dual form. Worth debating.
- **Captions** (if ever re-enabled) — pure legibility; no benefit from
  a video twin.

Everything else (the BitchX chrome-wards: activity_header,
stance_indicator, grounding_provenance_ticker, pressure_gauge,
thinking_indicator, whos_here, recruitment_candidate_panel,
impingement_cascade, activity_variety_log, gem) is a strong candidate
for the dual pattern.

## 5. Sequence of change (if approved)

Probable phase order, each phase shippable:

1. **Spec + design doc.** Nail paired_placement, pair_role,
   Reverie-as-ward semantics, parallax signal precedence.
2. **Ward pair primitive.** Extend `SourceSchema` + `Layout` +
   `ward_registry` to support `pair_role`. No visible change yet;
   everything defaults to `solo`.
3. **Reverie promotion.** Move Reverie's registration from hardcoded
   to layout-driven; keep its pip-ur default. Add the `reverie.
   emissive` BitchX-grammar readout. Retire the `pip-ur` literal
   assumption in fx_chain resolvers.
4. **Shared-substrate video source.** New `SubstrateRegionCairoSource`
   that reads a crop of Reverie's RGBA and blits it into an arbitrary
   surface region. Enables video-container rendering without per-ward
   decoders.
5. **First paired ward.** Pick one BitchX ward (activity_header is a
   good candidate — bounded, low risk, isolated). Ship its video
   twin. Wire parallax with audio signal. Validate visually on
   livestream.
6. **Parallax signal manager.** Separate component that reads
   IR gaze / audio / stimmung / time and emits a per-ward parallax
   offset vector per frame. Consumers read from this instead of
   computing their own.
7. **Fleet rollout.** Remaining BitchX wards converted. One per PR.
   Each with before/after livestream capture.
8. **Choreographer update.** Rotation + activation logic updated to
   treat pairs as units, with emphasis rules ("under voice,
   emissive-dominant"; "under music, video-dominant").
9. **Governance test pins.** No-flash, zero-opacity, face-obscure
   regression tests extended to the paired surfaces.

## 6. Decisions (locked 2026-04-23)

1. **Video substrate: HYBRID (option C).** Reverie is the default
   shared substrate; wards with strong content identity (sierpinski
   slots, album cover, vinyl platter, camera-feed wards) opt out and
   carry their own feed.
2. **Parallax signal: AUDIO + HAPAX MANIPULATION.** Audio reactivity
   is the continuous bed signal. On top of that, Hapax can
   deliberately manipulate parallax as an expressive act (recruited
   via the affordance pipeline / director intent). Parallax becomes
   a tool Hapax uses to direct attention — "when Hapax emphasizes X,
   the parallax pulls X forward." IR-gaze and stimmung are not
   primary inputs here.
3. **Mirror semantics: SAME thing, depth-offset.** Both legs show
   the same content; the emissive twin is a complementary rendering
   of the video, offset for depth. **Aesthetic complementarity is
   load-bearing** — the emissive layer must visually harmonize with
   its video twin, not just sit on top of it. This is the design
   problem that makes or breaks the look.
4. **Sierpinski: pairs.** Gets an emissive mirror like everything
   else. Plus a new concept: when a ward's video is a crop of the
   shared substrate, content inside the ward is hard to see against
   the rest of the canvas (the substrate leaks in from all sides).
   So when Hapax wants to *talk about* a specific video — foreground
   it, make it the figure on the ground — the ward becomes
   **frontable**: it pops out of substrate mode into its own
   distinct, elevated surface. See §6a below.
5. **Operator-content surfaces:** deferred — not affected by this
   epic; remains as today.
6. **Reverie is NOT always-on in the livestream.** The always-on
   guarantee existed for the operator's local view, which died with
   the Logos Tauri retirement and is not currently replaceable.
   Reverie the HOMAGE ward can be retired by the choreographer like
   any other ward. *Implication:* Reverie-the-substrate (the
   generative wgpu process) stays always-running because it's what
   the video-containers sample from; Reverie-the-ward (the
   full-frame view surfaced at a layout slot) is retirable.

## 6a. The "frontable" state

A video-container ward has two modes:

- **Integrated** (default). Ward renders a crop of the shared Reverie
  substrate. Content blends into the rest of the canvas; emissive
  twin parallax-offsets over it. This is the ambient resting state.
- **Fronted.** Ward breaks out of substrate mode: it jumps to a
  fronting z-plane, scales up, opacity amplifies, parallax amplitude
  increases, and — critically — the video source switches from
  "crop of the shared substrate" to the ward's own content (what the
  ward "is really about" — sierpinski's active YouTube slot, a
  camera feed, a replay clip, etc.). The emissive twin tracks
  forward with it.

**Fronting is a Hapax-driven affordance.** Triggered by:
- Director intent that picks out a specific ward for emphasis.
- Recruitment pipeline scoring the ward high (it's what Hapax cares
  about this tick).
- Voice/CPAL signal — when Hapax speaks ABOUT a ward, that ward
  fronts.

**Un-fronting** happens on director boundary, recruitment decay, or
speech-end. Must be gated and smoothed (no flash-pops).

## 6b. Aesthetic complementarity — the hard problem

Because mirror semantics is "same thing, depth-offset" (decision 3),
the emissive twin cannot sit in stylistic opposition to the video. If
the video is a flowing Reverie-shader crop (organic, chromatic,
material-driven) and the emissive twin is a hard BitchX terminal
grid, they will look like two surfaces from different universes — the
"parallax" reads as "collage", not "depth."

Possible complementarity mechanisms (not mutually exclusive):

- **Palette sync**: emissive colours are sampled from the video's
  dominant chroma at the current crop — emissive inherits video's
  colour field. Shifts live with Reverie's `spectral_color` and the
  active material (water/fire/earth/air/void).
- **Glyph/grid responsiveness**: the emissive layer's grid density,
  line weight, or glyph choice responds to Reverie's
  `intensity`/`tension`/`coherence` — dense calm glyph-field over
  coherent substrate, sparse turbulent marks over chaotic substrate.
- **Shape coherence**: emissive marks trace the contours of the
  video substrate (edge-follow), not a fixed BitchX grid.
- **HomagePackage as Reverie-reactive**: the package specifies a
  *response curve*, not fixed colours — palette floats with the
  substrate's 9-dim state. This is the biggest change; it could
  mean authoring one "palette response function" per ward instead
  of today's static colour roles.
- **Typography still fixed**: the IRC/BitchX glyph vocabulary
  survives, but the way those glyphs *appear* (density, colour,
  motion, edge) becomes substrate-aware.

This is a real design risk. The BitchX/IRC thesis of the current
HOMAGE package is a strong aesthetic identity; making it
substrate-reactive could thin that identity out to nothing. The
upside is a coherent layered scene; the downside is losing the
thing that makes HOMAGE legible as HOMAGE.

**Recommendation:** draft 2–3 complementarity mechanisms as
*rendering modes* (e.g. `palette_sync`, `edge_follow`,
`grid_responsive`), let each ward opt into a mode, and validate on
a single paired ward before rolling out.

## 7. Risks

- **Main CI is red** (#project_main_ci_red_20260420). A change this
  big wants main green first or the signal-to-noise on regression
  detection goes to zero.
- **Alpha is shipping 12+ PRs/day** in compositor space today. Large
  refactor of ward primitives collides with alpha's in-flight work.
  This wants a coordination window, not parallel shipping.
- **Semantic redaction** — if video-container wards ever carry chat
  or operator-identifiable content, the existing PII/consent gates
  must fan out to the new surfaces. Missing that is an axiom breach.
- **Aesthetic debt**: the jump from "BitchX terminal text" to "video
  substrate with text overlay" is a real stylistic pivot. The HOMAGE
  package spec assumes a late-90s IRC-client aesthetic — if we now
  have video everywhere, that aesthetic thesis may need revisiting.

## 8. Summary

The directive is coherent, the substrate exists, and the decisions
are locked (§6). The design problems that remain are mostly
mechanical (ward-pair primitive, substrate-region source, parallax
signal manager) plus one hard one: **aesthetic complementarity
between emissive twin and Reverie video crop** (§6b).

Next step: spec document that pins down the `frontable` state
machine, the complementarity rendering modes, the paired_placement
schema, and the phase sequence. Then plan. Then implement on a
single paired ward and validate on livestream before the fleet
rollout.
