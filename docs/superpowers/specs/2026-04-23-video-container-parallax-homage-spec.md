# Spec — Video-Container + Mirror-Emissive HOMAGE Ward System

**Status:** design — approved, implementation not started
**Date:** 2026-04-23
**Research predecessor:** `docs/research/2026-04-23-video-container-parallax-homage-conversion.md`
**Operator decisions:** research doc §6 (locked 2026-04-23)

## 1. Goals

G1. Every HOMAGE ward ships with two legs — a **video container** and
    a **mirror emissive** — paired at the same semantic slot.
G2. The two legs render the **same content** in depth-offset form.
    The emissive leg must be **aesthetically complementary** to its
    video twin, not stylistically orthogonal.
G3. **Parallax** between the paired legs is first-class. It is
    driven by an audio-reactivity bed and manipulable by Hapax as an
    expressive / attention-directing act via the affordance
    pipeline.
G4. Each ward has a **frontable** state: it can break out of the
    shared-substrate mode, adopt its own bespoke video source, and
    foreground itself when Hapax needs to refer to it.
G5. **Reverie is promoted to a first-class HOMAGE ward** — layout-
    addressable, retirable by the choreographer, with its own pair.
    Reverie-the-substrate (the generative wgpu process) remains
    always-running; Reverie-the-ward (the full-frame display of
    that substrate) is retirable.
G6. The system satisfies existing governance invariants: no
    flashing, zero container opacity, face-obscure fail-closed,
    monetization risk-gated egress.

## 2. Non-goals

NG1. Operator-content surfaces (Obsidian pango overlays, album
     splattribution, vinyl platter) are NOT converted in this epic.
     They remain single-layer "operator-voice" wards outside the
     mirror-pair system.
NG2. No new camera hardware, decode paths, or external input
     sources. Video substrate comes from Reverie; opt-outs use
     feeds that already exist in the compositor.
NG3. No change to the WGSL pipeline, effect graph, or Reverie
     shader vocabulary. This is a compositor-side epic.
NG4. No restoration of Reverie's `pip-ur` always-on local view —
     that obligation died with Logos-Tauri retirement (research §6,
     decision 6).

## 3. Terminology

- **Ward** — a named unit of livestream overlay content with
  semantic identity (e.g. `activity_header`, `token_pole`,
  `sierpinski`, `reverie`).
- **Leg** — one of the two renderings of a ward. `video` leg
  or `emissive` leg.
- **Pair** — the coupling of a ward's two legs at the same
  layout slot.
- **Substrate** — the shared GPU-generated video source (Reverie
  RGBA) that all default video-leg wards sample from.
- **Crop** — the rectangular region of the substrate that a
  specific ward's video leg reads.
- **Integrated mode** — the default resting state; video leg = crop
  of substrate.
- **Fronted mode** — the active/emphasized state; video leg = the
  ward's own bespoke content, elevated on z, amplified.
- **Complementarity mode** — the rendering strategy the emissive
  leg uses to harmonize visually with its video twin. Named
  strategies defined in §7.
- **Parallax offset** — the per-leg 2D displacement applied at
  blit time. Different for video and emissive, producing the depth
  effect.
- **Frontable** — a ward that can enter fronted mode. Not all wards
  are frontable (see §6.4).

## 4. Architecture changes

### 4.1. Ward registry

Today: `SourceSchema` registers one source per `ward_id`.
After: a ward is a record `{ward_id, video_leg, emissive_leg,
pair_role}` where legs are SourceSchema references.

- `pair_role: "paired" | "solo"` — solo wards are back-compat
  (operator-content surfaces, anything that stays single-layer).
- `video_leg` / `emissive_leg` — optional; a paired ward with only
  one leg is a configuration error unless explicitly solo.
- Default rule: newly-defined wards are `paired`. Wards listed in
  §6.4 as explicit-solo stay solo.

### 4.2. Layout data model

`Assignment` today binds `source → surface`. After:

- **`PairedAssignment`** — binds `ward → anchor_surface` with a
  declarative **leg_geometry** per leg:
  ```yaml
  ward: activity_header
  anchor_surface: activity-header-top
  video_leg:
    geometry_delta: {x: 0, y: 0, w: 0, h: 0}
    z_offset: 0
  emissive_leg:
    geometry_delta: {x: 0, y: 0, w: 0, h: 0}
    z_offset: +2
  ```
  `geometry_delta` is an offset from the anchor; `{0,0,0,0}` is
  identity. `z_offset` is a relative z-plane jump.
- The existing `Assignment` model stays for solo wards. Paired
  wards use `PairedAssignment`. Layout loader dispatches by
  `pair_role`.

### 4.3. Substrate source

New cairo source type: **`SubstrateRegionCairoSource`**.

- Reads Reverie's RGBA frame from `/dev/shm/hapax-sources/reverie.
  rgba` via the existing `ShmRgbaReader`.
- Blits a *crop rectangle* from the substrate into the ward's
  surface. Crop rectangle defaults to the ward's anchor geometry
  normalized to the substrate canvas (1920×1080 → substrate
  coordinate).
- Crop is NOT fixed: per-frame it can shift (parallax crop offset),
  scale (zoom into substrate), or be masked by a per-ward shape
  (sierpinski keeps its fractal mask).
- Sits at the same tick cadence as other cairo sources
  (`CairoSourceRunner`). One instance per video leg.

### 4.4. Ward emissive layer

Today: each ward is a Cairo source class (e.g. `ActivityHeader
CairoSource`) that draws glyphs, text, gauges.
After: those classes become the **emissive leg** of their ward
pair. Their rendering is unchanged structurally but gains:

- A **complementarity_mode** field on the ward's HomagePackage
  mapping (§7).
- Access to the current substrate colour/intensity state so the
  complementarity strategies can react.

### 4.5. Compositor render loop

Current loop: cairo sources render on background threads, cached
surfaces blit into the compositor overlay on the streaming thread.

After, per tick:

1. Reverie substrate frame arrives via shm (unchanged).
2. Each video leg's `SubstrateRegionCairoSource` (or bespoke video
   source for fronted/opt-out wards) samples its crop and prepares
   its cached surface.
3. Each emissive leg renders glyphs/gauges via its existing
   renderer, modulated by the active complementarity mode.
4. Compositor draws passes in z-order:
   - Camera/main layer
   - Solo wards (operator-content surfaces, sierpinski geometry
     mask etc.) at their z
   - Paired wards: video leg → emissive leg, with per-leg parallax
     offsets applied at blit time
5. Shader chain runs over the composite.

### 4.6. Parallax signal manager

New module: `agents/studio_compositor/parallax_signal.py`.

- Reads audio reactivity from `shared.audio_reactivity.
  read_shm_snapshot` (`bass_band`, `mid_band`, `treble_band`,
  `rms`, `onset`).
- Reads Hapax manipulation overrides from a new shm file:
  `/dev/shm/hapax-compositor/parallax-intent.json`, written by
  the affordance pipeline / director loop when Hapax wants to
  direct parallax deliberately.
- Emits a per-ward parallax vector `(dx_video, dy_video, dx_
  emissive, dy_emissive, dz)` per tick.
- Deterministic smoothing: low-pass over N ticks (no direct
  sinusoidal modulation — the existing no-flash + no-drift
  invariants apply).
- **Clamp**: per-ward offsets are clamped to the ward's anchor
  rect so wards cannot pan off-canvas (learned from the 2026-04-
  23 position-drift incident, PR #1237).
- Parallax amplitude base: audio RMS. Hapax can add an overlay
  vector on top via parallax-intent.json (direction + magnitude +
  decay).

### 4.7. Reverie ward promotion

- `reverie.video` = full-frame substrate view at `pip-ur` by
  default (same geometry as today).
- `reverie.emissive` = new BitchX-grammar readout of the 9-dim
  state (intensity, tension, depth, coherence, spectral_color,
  temporal_distortion, degradation, pitch_displacement, diffusion)
  rendered as a compact labelled grid.
- Reverie becomes recruitable / retirable via the affordance
  pipeline. The hardcoded `pip-ur` assumption in
  `compositor.py` and `fx_chain` resolvers is replaced by
  layout-driven lookups.
- Reverie-the-substrate (`/dev/shm/hapax-sources/reverie.rgba`
  writer) remains always-running regardless of whether the ward
  is visible — it's the source-of-truth for all other wards'
  video legs.

## 5. Data model deltas

### 5.1. `SourceSchema` additions

```python
class SourceSchema(BaseModel):
    id: str
    kind: str
    backend: str
    params: dict
    # NEW:
    pair_role: Literal["paired", "solo"] = "solo"
    # NEW: which leg of the pair this source IS, if paired.
    pair_leg: Literal["video", "emissive", None] = None
    # NEW: the ward_id the leg belongs to (for paired sources).
    ward_id: str | None = None
```

### 5.2. `Ward` — new top-level record

New file: `shared/ward_pair.py`.

```python
class WardPair(BaseModel):
    ward_id: str
    video_leg_source: str       # SourceSchema.id of video leg
    emissive_leg_source: str    # SourceSchema.id of emissive leg
    frontable: bool = True      # can this ward enter fronted mode
    front_video_source: str | None = None
                                # bespoke source used when fronted
                                # (None = fall back to video_leg)
    complementarity_mode: Literal[
        "palette_sync",
        "grid_responsive",
        "edge_follow",
        "none",                 # stylistically independent (legacy)
    ] = "palette_sync"
```

`pair_role="solo"` wards don't have a WardPair record.

### 5.3. `WardProperties` additions

```python
class WardProperties(BaseModel):
    # existing fields preserved
    # NEW:
    front_state: Literal["integrated", "fronting", "fronted",
                         "defronting"] = "integrated"
    front_t0: float | None = None       # timestamp of last transition
    parallax_scalar_video: float = 1.0  # leg-specific scaling of
    parallax_scalar_emissive: float = 1.0
                                        # the parallax manager's
                                        # output vector
    crop_rect_override: tuple[float, float, float, float] | None = None
                                        # fronted mode may set a
                                        # custom crop for the video
                                        # leg
```

### 5.4. `HomagePackage` additions

```python
class HomagePackage(BaseModel):
    # existing: typography, grammar, colour roles, etc.
    # NEW: palette response function (for palette_sync mode)
    palette_response: PaletteResponse | None = None

class PaletteResponse(BaseModel):
    # Maps substrate state -> colour role override.
    # Each colour role (e.g. "accent_cyan") has a modulation curve:
    # - base: the default colour role value
    # - respond_to: which substrate dim drives the modulation
    # - curve: linear | sigmoid | step
    # - amplitude: max shift in LAB space
    ...
```

Palette response is optional — packages without it fall back to
static roles. This keeps the BitchX authenticity-pinned package
viable while allowing the video-reactive one to coexist.

### 5.5. Parallax intent schema

New shm file: `/dev/shm/hapax-compositor/parallax-intent.json`.

```json
{
  "ts": 1713902400.0,
  "ward_id": "activity_header",
  "direction": {"dx": 0, "dy": -8},
  "magnitude": 1.5,
  "decay_s": 2.0,
  "reason": "hapax_voice_emphasis"
}
```

Writers: director_loop, affordance pipeline, CPAL on spontaneous
speech. Reader: parallax_signal manager.

## 6. Frontable state machine

### 6.1. States

- **integrated** (default) — video leg = substrate crop; ambient
  parallax only; z at ward's nominal plane.
- **fronting** — transitioning to fronted; ward rises in z,
  opacity ramps, crop begins expanding; video source begins
  swap. Bounded duration (default 400 ms, smooth envelope).
- **fronted** — ward at fronting z-plane, video leg uses
  `front_video_source` (or falls back to the ward's own video
  leg if unset), parallax scalar amplified, emissive leg
  brightened.
- **defronting** — transitioning back to integrated. Mirror of
  fronting. Bounded duration (default 600 ms — slower exit
  feels less abrupt).

### 6.2. Transitions

- `integrated → fronting` on:
  - Director intent naming the ward.
  - Affordance recruitment with `frontable_boost` tag and score
    above the front threshold.
  - CPAL detecting Hapax speaking about the ward (lexical match
    against ward_id or ward aliases).
- `fronting → fronted` on envelope completion (auto).
- `fronted → defronting` on:
  - Director intent boundary (new intent selected).
  - Recruitment score decay below threshold.
  - CPAL speech-end + grace period (1.5 s).
  - Manual ward_property set.
- `defronting → integrated` on envelope completion (auto).

### 6.3. Envelopes

Smooth (ease-in-out cubic) on all transitions. No snap pops. The
no-flashing directive (2026-04-23) applies — no alpha flash, no
geometry flash.

### 6.4. Frontable-by-default eligibility

- **Frontable** (default true): all BitchX wards (activity_header,
  stance_indicator, grounding_provenance_ticker, pressure_gauge,
  thinking_indicator, whos_here, recruitment_candidate_panel,
  impingement_cascade, activity_variety_log, gem), hardm,
  reverie, token_pole, sierpinski.
- **Not frontable**: operator-content wards (Obsidian overlays,
  album, vinyl-platter) — they're solo and always rendered at
  their own terms.

## 7. Complementarity modes

The emissive leg's relationship to its video twin. One mode per
paired ward; set on the HomagePackage mapping.

### 7.1. `palette_sync`

Emissive colours are sampled from the video substrate at the
ward's crop. The ward reads the substrate's dominant hue or a
specific 9-dim state (e.g. `spectral_color`) per frame and
remaps the HomagePackage colour roles through that. BitchX grammar
is preserved; only the palette breathes with the video.

**Implementation:** `HomagePackage.palette_response` defines how
each role shifts. Reader samples substrate state from the
imagination state file (`/dev/shm/hapax-imagination/current.json`)
and applies the modulation before the emissive leg renders.

### 7.2. `grid_responsive`

The emissive layer's glyph density, line weight, or cell size
responds to Reverie's `coherence` / `tension` / `intensity`. Dense
calm glyph-field over coherent substrate; sparse turbulent marks
over chaotic substrate. Glyph vocabulary preserved; layout
parameters mutated.

**Implementation:** Each emissive source class gains a
`responsive_params()` method returning the current grid
parameters (density, line weight, cell size) as a function of
substrate state. Used in `render_content`.

### 7.3. `edge_follow`

Emissive marks (glyphs, pips, tick-marks) are placed along the
edge contours of the video substrate — not on a fixed grid.
Produces a layered texture where the emissive reads as an
"annotation" of the video. Highest rendering cost.

**Implementation:** substrate crop is edge-filtered (simple
Sobel) once per tick; emissive layer places marks at sampled
edge points.

### 7.4. `none`

Emissive renders exactly as today. Useful for legacy packages
(e.g. a future "pure BitchX" package that operates independently
of Reverie). Back-compat escape hatch.

### 7.5. Mode selection per ward

Decided in the HomagePackage mapping. Default: `palette_sync`.
Can be overridden per ward for experimentation.

## 8. Governance invariants

All existing invariants carry forward:

- **No flashing** (2026-04-23) — emissive and video legs use
  smooth envelopes on every transition (parallax, front state,
  mode changes). `test_no_flashing_wards.py` regression pins
  extend to cover paired wards + parallax motion.
- **Zero container opacity** (2026-04-23) — the emissive leg
  continues to have zero background/border chrome. Text + glyphs
  with outline contrast only. This is unchanged by the video
  leg's presence — the video leg IS the "background" now, and
  it's content, not chrome.
- **Face-obscure fail-closed** — Reverie substrate does not
  composite camera frames directly; per-ward opt-out video
  sources that DO use cameras (vinyl_platter, follow-mode)
  already route through `face_obscure_integration`. This epic
  does not introduce new camera paths.
- **Monetization risk gate** — the Ring 2 pre-render classifier
  runs on the composited output, not per-leg. One surface
  classified, same as today.
- **No position drift off-canvas** — parallax offsets clamped to
  ward anchor rect. The 2026-04-23 position-offset neutralization
  (PR #1237) is selectively unwound: the offset mechanism is
  restored for paired wards but with per-ward clamping instead of
  unconstrained drift.
- **No-blinking HOMAGE wards** (2026-04-21) — parallax uses
  low-pass envelopes; no hard on/off; no high-frequency
  modulation.
- **Operator speech never dropped** — fronting on CPAL speech
  uses the existing speech-event path; no new cooldown.

## 9. Implementation phases

All phases shippable independently. Each phase ends in a PR with
regression tests.

### Phase 1 — Spec + plan docs (this doc + the plan doc)
No code.

### Phase 2 — Data model primitives
- Add `pair_role`, `pair_leg`, `ward_id` to SourceSchema.
- Add `WardPair` Pydantic model.
- Add fields to `WardProperties`.
- Extend `HomagePackage` with optional `palette_response`.
- All wards default to `pair_role="solo"` — no visible change.

### Phase 3 — SubstrateRegionCairoSource
- New source class reading crops from Reverie substrate.
- Register the class with `cairo_sources/__init__.py`.
- Unit tests: crop math, substrate-miss fallback, clamp behaviour.
- No layout wiring yet.

### Phase 4 — Reverie promotion
- Move Reverie's SourceSchema from hardcoded `external_rgba` to a
  layout-declared paired source (`reverie.video` +
  `reverie.emissive`).
- Add `ReverieEmissiveCairoSource` (BitchX gauge readout of
  9-dim state).
- Retire always-on hardcoding; make Reverie recruitable/retirable.
- Regression test: layout without reverie assignment validates
  and runs.

### Phase 5 — First paired ward (pilot)
- Convert `activity_header` to paired. `activity_header.video` =
  SubstrateRegionCairoSource; `activity_header.emissive` = current
  source.
- Set `complementarity_mode="palette_sync"` on its HomagePackage
  mapping.
- Wire parallax-signal-manager (§4.6) in its minimal form: audio
  bed only, no Hapax-intent override yet.
- Ship; capture before/after livestream frames; validate visual.

### Phase 6 — Parallax signal manager complete
- Add parallax-intent.json reader.
- Wire director_loop + affordance pipeline + CPAL to write
  intent events.
- Extend the pilot ward to respond to intent-driven parallax.

### Phase 7 — Frontable state machine
- Implement state machine in ward_properties.
- Add transition triggers (director/recruitment/CPAL).
- Pilot on activity_header (fronted when Hapax says "right now
  I'm authoring…"). Front video source = a dedicated Reverie
  preset or an identity feed; TBD per ward.

### Phase 8 — Complementarity modes (grid_responsive, edge_follow)
- Implement the remaining two modes.
- Assign per-ward modes.
- A/B visual validation.

### Phase 9 — Fleet rollout
- Convert remaining BitchX wards one per PR. Each PR includes:
  - Pair definition
  - SubstrateRegionCairoSource layout wiring
  - HomagePackage complementarity mode assignment
  - Front-source assignment (if frontable)
  - Regression visual capture
- Order: activity_header (pilot), stance_indicator,
  thinking_indicator, whos_here, pressure_gauge, grounding_
  provenance_ticker, recruitment_candidate_panel,
  impingement_cascade, activity_variety_log, gem, hardm,
  token_pole, sierpinski, reverie (already done in Phase 4).

### Phase 10 — Choreographer + director integration
- Teach the HOMAGE choreographer to treat pairs as units.
- Director prompt additions: when and how to front a ward, how
  to manipulate parallax intent.
- Programme integration: rotation modes understand pairs.

### Phase 11 — Governance test pins
- Extend `test_no_flashing_wards.py` for paired wards.
- New `test_parallax_clamp.py` — no off-canvas pan under any
  intent magnitude.
- New `test_complementarity_modes.py` — palette_sync produces
  expected LAB shift under synthetic substrate input.
- New `test_front_state_machine.py` — envelope smoothness,
  transition boundaries.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Aesthetic thinning of HOMAGE identity under palette_sync | Draft all 3 modes before fleet rollout; validate pilot with operator before propagating. Package response curves authored, not auto-derived. |
| Main CI red during epic | Gate Phase 2 entry on main going green; Phase 1 (docs) is safe regardless. |
| Collision with alpha's in-flight HOMAGE work | Coordinate via relay handoff before each phase; delta drafts, alpha has right of first refusal on execution. |
| Parallax amplifies any hidden flash/drift | Extend regression suite first (Phase 1 companion), before implementing. |
| Reverie substrate missing during ward render | SubstrateRegionCairoSource falls back to solid-ground fill (package `background` role at alpha 0 = transparent — no visible chrome). Log missing-substrate event. |
| Front-source undefined for a frontable ward | Typed default: fall back to ward's own video_leg_source (substrate crop) even when fronted. Fronting still shifts z + opacity, just not content. |
| VRAM pressure | Reverie substrate is shared (one producer, N consumers). No new decoders in Phase 1–9. Per-ward opt-out feeds (camera, YouTube) already accounted for. |

## 11. Metrics

Observability additions:

- `hapax_ward_front_state{ward_id}` — current state (gauge, 0..3).
- `hapax_ward_front_transitions_total{ward_id,from,to}` — counter.
- `hapax_parallax_offset_magnitude{ward_id,leg}` — histogram.
- `hapax_complementarity_mode{ward_id}` — info (label).
- `hapax_substrate_region_reads_total` / `…_misses_total` — counter.

All on port `:9482` with the other compositor metrics.

## 12. Backward compatibility

- All wards start as `pair_role="solo"` in Phase 2. No visible
  change until Phase 4 (Reverie promotion) and Phase 5 (pilot).
- Layout JSON files without paired_placement fields parse as
  today — solo wards untouched.
- HomagePackage without `palette_response` behaves as today —
  static colours.
- Affordance pipeline, director loop, CPAL continue to work on
  ward_ids; pair-awareness is an additive capability.
- The chat_ambient retirement (PR #1239) remains valid; no
  paired version planned for it.

## 13. Open items (parked, not blocking)

- Whether HARDM's existing dot-matrix aesthetic qualifies as
  "video substrate enough" to stay solo. Leaning: pair, with
  `complementarity_mode="grid_responsive"`.
- Whether token-pole's glyph rendering gets a video twin or stays
  solo. Leaning: pair, with Reverie crop behind the vitruvian
  figure.
- Whether the Hapax-intent parallax vector is authored or
  LLM-emitted. Leaning: both — affordance pipeline emits discrete
  events, director LLM can request custom vectors.
- Specific Hapax speech triggers for fronting — needs a lexical
  table mapping phrases to ward_ids. Parked for Phase 7.
