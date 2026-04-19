# HARDM Aesthetic Rehabilitation — Why the Avatar Looks Dead, and How to Make It Compelling

**Date:** 2026-04-20
**Scope:** Diagnose the live HARDM render and propose ranked aesthetic upgrades.
**Register:** scientific; design-doc neutral.
**Related:**
- `docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md` (HARDM spec)
- `docs/research/hardm-communicative-anchoring.md` (anchoring contract, task #160)
- `docs/superpowers/specs/2026-04-18-homage-framework-design.md` (HOMAGE)
- `docs/logos-design-language.md` (Gruvbox Hard Dark / Solarized palettes)
- `agents/studio_compositor/hardm_source.py` (consumer)
- `scripts/hardm-publish-signals.py` (publisher)
- `config/compositor-layouts/default.json` (layout placement)

---

## 1. Original Intent — What HARDM Was Supposed To Be

Two artefacts define the design contract.

### 1.1 Spec stub (2026-04-18-hardm-dot-matrix-design.md)

The spec is unambiguous about the visual grammar:

> "A 256×256 px CP437-raster avatar-readout. Each of the 256 cells is a 16×16 px dot bound to a real-time system signal." (`hardm_source.py:12-14`)
>
> "BitchX-authentic: grey idle skeleton, bright identity colouring, mIRC-16 accent on activity, no gradient fills, no rounded corners." (spec §1)
>
> "Cell size: 32 × 32 px. Grid: 16 rows × 16 cols = 256 cells." (spec §2 table)
>
> "No sub-pixel positioning. No anti-aliasing. No rounded corners. A 1 px muted-grey gridline between cells is permitted (CP437-thin rule, package `muted` role)." (spec §2)

The spec calls for **256 individually addressable cells** at 32×32 px on a 512×512 surface (the table arithmetic actually doesn't close — `32 × 16 = 512`, but the surface row above states 256×256; the implementation reconciled by halving cell size to 16 px). Cells render as solid CP437-style stamps with crisp edges. Multi-level signals "interpolate **by alpha**, never by hue — hue stays locked to the family role so the avatar remains legible" (spec §5).

### 1.2 Anchoring research (hardm-communicative-anchoring.md)

The research doc treats HARDM as Hapax's **face-equivalent** in the livestream visual economy:

> "HARDM is the single visual surface that external viewers reliably associate with 'Hapax.' [...] Functionally it occupies the role a face occupies in human conversation: a known return site, a visible tell, an attentional anchor during voice." (§1)
>
> "Micro-state changes in the matrix (a row brightening, a column flickering to accent-red, a stance cell sliding from muted to magenta) carry information the narrative director can refer to." (§1)

The intended dynamics are signal-driven micro-events — not a generic shimmer field. Voice activity adds a 1.18× brightness multiplier to non-idle cells; SEEKING stance lights the cognition row; a guest contract pushes governance cells. Each cell is supposed to be a **legible, dereferenceable channel** that the director can point at ("watch the row-5 pulse").

### 1.3 Operator policy memory

`feedback_no_expert_system_rules`: behavior emerges from impingement → recruitment → role → persona; hardcoded cadence/threshold gates are bugs. The shimmer constants in the current implementation (baseline 0.85, amplitude 0.15, ω = 2.0 rad/s) are precisely such hardcoded gates: per-cell behaviour is a deterministic sine, untouched by signal state.

---

## 2. Current Code Behaviour — What Actually Renders

### 2.1 Geometry

`agents/studio_compositor/hardm_source.py:80-85` — cells are 16 × 16 px on a 256×256 surface, **half the spec's 32 px**. The surface lands at `x=1600, y=20, w=256, h=256` per `config/compositor-layouts/default.json:hardm-dot-matrix-ur` with `opacity=0.92` and `update_cadence=rate, rate_hz=4.0`.

### 2.2 Per-cell render path

`hardm_source.py:677-728` (`HardmDotMatrix.render_content`):

For each of 256 cells:
1. Resolve `(role, alpha)` from `_classify_cell(signal_name, value)` — but `signal_name` is constant per row (`_signal_for_row(row)`) and `value` is the same for every column in that row.
2. Resolve RGBA from active package palette.
3. Multiply by per-cell shimmer = `0.85 + 0.15 · sin(t · 2.0 + 0.31·row + 0.17·col)`.
4. Paint three concentric stamps centred at `(col·16+8, row·16+8)`:
   - Outer glow: radial gradient, radius 9 px, peak alpha `0.12 · cell_alpha`.
   - Halo: radial gradient, radius 6.5 px, peak alpha `cell_alpha`.
   - Centre dot: solid, radius 2.5 px.
5. Optional 1 px scanline every 4 rows at alpha 0.10.

### 2.3 Ground

`hardm_source.py:52` — fixed Gruvbox bg0 `(0x1d, 0x20, 0x21)` near-black, ignoring the active package's `palette.background`. Comment says this is intentional ("HARDM's ground is fixed so the shimmer stays coherent across package swaps").

### 2.4 Aesthetic rework date stamp

`hardm_source.py:42-46` — there is already an "aesthetic rework 2026-04-19" in tree, attributed to a verbatim operator directive: "dynamic synthwave/bitchX pointillism, points of compelling light, never totally stable, shimmering, techno-ethereal, precise yet diffuse." The current state is the result of that rework. **The operator's rejection on 2026-04-20 is rejecting that rework** — the shimmer constants and halo radii are too restrained to read as alive, the palette is too desaturated, and the data layer is degenerate (see §3).

### 2.5 Live signal payload

`/dev/shm/hapax-compositor/hardm-cell-signals.json` (sampled 2026-04-19 12:12:07 CDT):

```json
{"midi_active": false, "vad_speech": false, "watch_hr": null, "bt_phone": false,
 "kde_connect": false, "screen_focus": false, "room_occupancy": null,
 "ir_person_detected": false, "ambient_sound": null, "director_stance": "nominal",
 "stimmung_energy": null, "shader_energy": 0.0, "reverie_pass": null,
 "consent_gate": null, "degraded_stream": false, "homage_package": null}
```

Of 16 signals: 7 `false`, 6 `null`, 1 `"nominal"` (which `_classify_cell` maps to `"muted"`), 1 `0.0` (also `muted`), 1 `null` for `consent_gate` (which fails closed to `accent_red` per `_classify_cell:269`).

**At least 14 of 16 rows render in the package's `muted` role**, which in BitchX is `(0.39, 0.39, 0.39, 1.0)` — middling grey. After 0.85 baseline shimmer, the rendered RGB is roughly `(0.33, 0.33, 0.33)`. Then the centre dot (radius 2.5 px) is overdrawn by halo (radius 6.5 px) at the same colour, so the legible feature is a 13-px-diameter grey blob inside a 16-px cell. Adjacent halos at radius 9 px **bleed into neighbouring cells** because the cell pitch is also 16 px. Result: a grey wash with very slight per-cell shimmer.

The operator's verbatim description ("shitty blurry leds that are half dead") is technically accurate — the LEDs are deliberately overlapped (blur), and 14 of 16 signal channels are `null`/`false` (half dead, but actually closer to fully dead).

---

## 3. Why It Looks Dead — Hypotheses Verified Against Code

Five concrete hypotheses, each verified.

### H1. Publisher path mismatches → all signals `null`/`false`

**Active.** `scripts/hardm-publish-signals.py:35-37` reads:

- `_PERCEPTION_STATE = Path("/dev/shm/hapax-daimonion/perception-state.json")`
- `_NARRATIVE_STATE = Path("/dev/shm/hapax-director/narrative-state.json")`
- `_STIMMUNG_STATE = Path("/dev/shm/hapax-daimonion/stimmung-state.json")`

The actual canonical locations on the running system:

- Perception state: `~/.cache/hapax-daimonion/perception-state.json` (`agents/hapax_daimonion/_perception_state_writer.py:47`). The path the publisher reads **does not exist**.
- Stimmung state: `/dev/shm/hapax-stimmung/state.json` (verified live). The publisher reads `/dev/shm/hapax-daimonion/stimmung-state.json` which does not exist.
- Narrative state lives at `/dev/shm/hapax-director/narrative-state.json` (correct), but only carries `{stance, activity, last_tick_ts, condition_id}` — `stance` was the only field the publisher uses.
- Homage active: publisher reads `/dev/shm/hapax-compositor/homage-active.json`; the actual file is `homage-active-artefact.json` (different schema). Does not exist at the expected path.

**Severity: critical.** Even if every other hypothesis were resolved, all four perception/narrative/stimmung/homage signal families would still come back null/false because the upstream files do not exist where the publisher looks.

### H2. Schema mismatch — keys read do not exist in the real perception schema

**Active.** Even if path H1 were fixed, `scripts/hardm-publish-signals.py:74-145` reads keys (`midi_active`, `vad_speech`, `watch_hr_bpm`, `bt_phone_connected`, `room_occupancy_count`, `ambient_sound_level`) that **are not in the perception schema**. The real schema (verified live) carries `vad_confidence` (not `vad_speech`), `mixer_energy`/`mixer_beat`/`mixer_active` (not `midi_active`), `heart_rate_bpm` (not `watch_hr_bpm`), `person_count` (not `room_occupancy_count`), `audio_energy_rms` (not `ambient_sound_level`), `desk_activity` (a string class, not boolean), etc. Of the publisher's 13 perception keys, **only `phone_kde_connected`, `desktop_active`, `ir_person_detected` map to real fields**.

### H3. Inter-dot spacing too tight for halo radius → blur

**Active.** Cell pitch = 16 px. Outer glow radius = 9 px. Halo radius = 6.5 px. A halo centred at `(8, 8)` extends to `(8±9, 8±9) = (-1..17, -1..17)`, so each cell's outer glow covers **the full 16×16 cell plus 1 px beyond on every side**. Adjacent cells' glows overlap at every interior column/row line. With 256 cells co-overlapping radial gradients with non-zero alpha at their boundary, the surface composites to a continuous wash. The grid topology is destroyed; the avatar reads as a fog field rather than a matrix. Operator's "blurry" descriptor is exactly this artefact.

### H4. Colour saturation too low; palette flattened to grey accents

**Active, but conditional.** BitchX `palette.muted = (0.39, 0.39, 0.39)` — middling grey by design, since the BitchX grammar's "grey-punctuation skeleton" is structural. Active accents like `accent_green = (0.20, 0.78, 0.20)` and `accent_magenta = (0.78, 0.00, 0.78)` are reasonable; `accent_cyan = (0.00, 0.78, 0.78)` is bright. **But because every signal is in the muted state per H1/H2**, the active palette never gets exercised. The rendered surface is a 256-cell grey shimmer modulated by a 0.85-baseline / 0.15-amplitude sine — that's a luminance range of `[0.33, 0.45]` after multiplication, on grey. No hue, no saturation, no contrast.

### H5. Data layer is degenerate — 16 distinct states displayed across 256 cells

**Active, by design.** `hardm_source.py:686-687` — every column in row N renders the same `(role, alpha)` derived from the same row-bound signal. So the "256-cell grid" is informationally **16 horizontal bars**. Even when signals do flow, the matrix can display at most 16 distinct cell states; there is no per-cell information density. This means the *pointillism* aesthetic (where each dot communicates) is structurally impossible — adjacent dots in the same row are mandated to be identical.

### H6. Shimmer animation too slow + too small

**Active.** ω = 2.0 rad/s ≈ 0.32 Hz period (3.14 s). At a per-source render rate of 4 Hz, each shimmer cycle takes ~13 frames; visible, but slow enough to read as drift rather than life. Amplitude 0.15 on baseline 0.85 = ±15% luminance modulation — at the bottom of human contrast-detection thresholds against a grey field. The "never totally stable" directive collapses to "imperceptibly drifting."

### H7. No sub-cell information density / no per-cell event geometry

**Active.** The current render has no birth-death events, no ripples, no propagation, no afterglow trails. A signal flips false→true and the cell snaps to its accent role at the next 4 Hz tick; flips true→false and it snaps back. There is no temporal texture on transitions. By contrast, the spec's anchoring contract (§4.2) explicitly imagines selective brightening on TTS speak start/stop, but the current implementation merely multiplies non-muted RGB by 1.18 — wholesale, instantly, no envelope.

### Cause ranking

| # | Cause | Live impact | Fix scope |
|---|---|---|---|
| 1 | H1 — publisher path mismatches | Every signal null/false | 4 path constants in publisher script |
| 2 | H2 — schema-key mismatches | Even with paths fixed, 10/13 perception signals return null | Per-key remap in `_collect_signals()` |
| 3 | H5 — degenerate data layer | 16 channels on a 256-cell canvas | Architectural — see §5 |
| 4 | H3 — halo radius > cell pitch | "Blur" artefact | Two constants + cell size revisit |
| 5 | H6 — shimmer too small/slow | "Half dead" | Constants tuning |
| 6 | H4 — palette mostly muted-role | Grey wash | Downstream of H1/H2 |
| 7 | H7 — no event geometry | No "tells" or "pulses" | New animation layer |

**The chain effect:** H1 and H2 are why every cell is muted; H5 is why the matrix is bar-shaped not pointillistic; H3/H4/H6 are why even the muted state reads as wash; H7 is why state changes are inert. Fixing only the cosmetic constants (H3/H4/H6) without H1/H2/H5 will produce a slightly less-blurry grey wash. Fixing H1/H2 alone — the cheapest remediation — will at least surface the few currently-flowing signals (`director_stance`, `degraded_stream`, IR/desktop/KDE/phone) into visible accent roles, but the result will still be 16 horizontal bars of accent, not an avatar.

---

## 4. Aesthetic Brief — What "Compelling and Dynamic" Looks Like

Precedent organised by what each strain contributes to the upgrade vocabulary. All references are translated into HAPAX's existing visual language: stimmung dimensions, the 9 canonical expressive dimensions (`shared/expression.py`: intensity, tension, depth, coherence, spectral_color, temporal_distortion, degradation, pitch_displacement, diffusion), the BitchX grammar, the Reverie 7-pass shader pipeline. No out-of-vocab moves.

### 4.1 Vintage LED-wall reference (Jumbotron, Daktronics, Times Square, Adafruit NeoPixel)

LED matrices read as alive when **per-pixel decay is visible**. Phosphor and LED both have non-instantaneous off — a "flash" leaves a 50–200 ms trail that the eye integrates into motion (`Sources` §1, §4 — phosphor persistence shaders). The Jumbotron reference is RGB sub-pixels at variable intensity, not on/off — every cell carries 24 bits of state that's modulated continuously by upstream content. **HAPAX translation:** every cell needs its own decay envelope. A signal-true→false transition fades over `temporal_distortion`-modulated decay (200 ms baseline, 50 ms when stimmung dimension `tension` is high, 800 ms when `coherence` is high). This maps onto the existing 9-dim uniform path with no new infrastructure.

### 4.2 Daniel Rozin's mechanical mirrors (`Sources` §3)

Rozin's pixel grids work because **every element responds individually to a reactive input field** (the camera silhouette). The viewer reads a face/figure they recognise; the medium (wood, rust, mirror) is the texture. **HAPAX translation:** HARDM cells should respond to a 2D field, not 16 row-bars. The field can be the IR perception map (256 cells = 16×16 IR room mosaic), Pi-NoIR motion-delta heatmap, or the imagination 9-dim diffuse field. The viewer should be able to read "Hapax is paying attention to the desk" or "exploration is rising in the right half of the room" without verbal cues.

### 4.3 Kinetic typography / Robert Hodgin grid work (`Sources` §4)

Hodgin's reactive-diffusion installations and audio-reactive grids work because **the simulation runs continuously at high frame rate; the input modulates rather than gates**. The grid is always evolving; signal arrival nudges the trajectory. **HAPAX translation:** swap the request-response render model (read signal payload, paint cells) for a continuous simulation that uses the signal payload as forcing terms. The cell array is a state field; signals are sparse impulses; visual update is the field's evolution.

### 4.4 Reaction-diffusion / Physarum on a dot field (`Sources` §3)

RD on a 16×16 grid is computationally trivial (`O(256)` per tick) and produces patterns that read as "alive" because the human visual system has an exquisite prior for biological-tempo morphogenesis. Physarum agents leave trails that decay; on a discrete grid, the trail is a continuous afterglow. **HAPAX translation:** add a single RD layer underneath the signal-coloured cells, with sparse activator injection driven by the existing `recent-recruitment.json` stream (when capability X recruits, drop activator at cell `hash(capability_X) mod 256`). The pattern surfaces as "Hapax is thinking" without any narrative beat.

### 4.5 BitchX-native / mIRC ANSI animation

The BitchX lineage already supports per-cell colour cycling: mIRC's `^K` codes change colour at character boundaries; CP437 block characters (`▀▄▌▐█▒░`) give 4 levels of intensity per cell with no anti-aliasing. **HAPAX translation:** the legible upgrade isn't *abandoning* the BitchX grammar for shaders; it's *exhausting* what mIRC-16 + CP437 can express. ANSI animation precedent (16colo.rs archive) gives plenty of vocabulary: blink-flag (`^B`), reverse-video (`^V`), mode lines that scroll. The current implementation paints solid filled circles inside cells — wholly outside the CP437 grammar. A spec-faithful upgrade would render each cell as one of the CP437 block characters at the family-accent colour, with the chosen block reflecting the signal's intensity.

### 4.6 CRT phosphor / Reverie shader pipeline (`Sources` §4)

The Reverie pipeline already has bloom, temporal-feedback, and per-pass intermediate textures (`docs/superpowers/specs/2026-04-13-reverie-source-registry-completion-design.md`). The HARDM Cairo surface composites onto a render target that **already passes through Reverie's postprocess pass** in the unified compositor, so any added bloom/glow at the HARDM source layer compounds with what Reverie does at the composite layer. The cleanest path to "techno-ethereal glow" is to render HARDM as crisp CP437 squares (not blurry halos) and let Reverie's existing bloom add the atmosphere.

---

## 5. Concrete Upgrade Proposals — Ranked

Each proposal: WHAT changes, WHICH signals drive, WHAT rendering technique, IDLE state, IMPLEMENTATION SCOPE.

### Proposal A — Fix the data layer (publisher H1/H2). Highest impact, lowest scope.

**WHAT:** Bring real signals into the matrix. Change `scripts/hardm-publish-signals.py` so the four input paths point at the canonical files, and key reads match the actual schema (`vad_confidence > 0.5` → `vad_speech`; `mixer_active` → `midi_active`; `heart_rate_bpm` → `watch_hr`; `person_count` → `room_occupancy`; `audio_energy_rms` → `ambient_sound`).

**SIGNALS:** All 16 primary cells become live, sourcing from the schemas verified in §3.

**TECHNIQUE:** No render changes. Pure publisher script.

**IDLE STATE:** The grid still reads as expectant — most signals will be true/intermediate during normal operation (`presence_state=PRESENT`, `desktop_active=true` when operator working, `ir_person_detected=true`, `mixer_active=true` during music production, `kde_connect=true`).

**SCOPE:** ~30 lines in one Python file. No new infrastructure. The publisher already runs on a 2 s timer.

**Without this, every other proposal renders against a null payload.** Unblock first.

---

### Proposal B — Per-cell information density (kill the row-bar pattern).

**WHAT:** Replace the row-major signal binding (every column in row N = signal N) with a 2D mapping where the 256 cells carry richer per-cell state. Two complementary patterns:
1. **Per-row time-history.** Each row is still bound to one signal, but the 16 columns become a 16-tick rolling history (`col=0` is now, `col=15` is 15 ticks ago). The row reads as a sparkline. The viewer sees `vad_speech` rising as a wave moving right-to-left.
2. **2D perception fields for cells 16–239** (per spec §3, those cells were "reserved for scene-signal expansion"). Bind cells 16–31 to camera scene-label one-hots (`per_camera_scenes`), cells 32–47 to `overhead_hand_zones`, cells 48–63 to `ir_motion_delta` 16-cell histogram. The avatar acquires a "what Hapax is currently perceiving" mid-band.

**SIGNALS:** Existing perception state already carries `per_camera_scenes`, `overhead_hand_zones`, `mixer_bass`/`mixer_mid`/`mixer_high` (3-band MIDI/audio), `desk_activity` strings, `gaze_direction`, `hand_gesture`. Plus the 9-dim canonical dimensions (`intensity`, `tension`, `depth`, `coherence`, `spectral_color`, `temporal_distortion`, `degradation`, `pitch_displacement`, `diffusion`) from `shared/expression.py`, sampled directly from the imagination fragment payload — these are 9 dynamic floats updating continuously.

**TECHNIQUE:** Pure publisher-side change (the publisher emits a richer `signals` dict; the consumer's `_classify_cell` already supports cells beyond 0–15 if `_signal_for_row` returns a name).

**IDLE STATE:** History-row sparklines settle into a flat baseline; 2D fields sit at `muted` until perception engines fire; cognition cells (9-dim) breathe continuously since imagination always ticks.

**SCOPE:** ~80 lines publisher-side; ~20 lines consumer-side to support per-cell signal lookup (extend `_signal_for_row` → `_signal_for_cell`, add a config map). Add `config/hardm-map.yaml` per spec §4 (currently missing in tree).

---

### Proposal C — Per-cell decay envelope + event ripples.

**WHAT:** Cells should not snap to muted on signal-false. Each cell has a per-cell `last_active_ts`; render brightness decays exponentially over `decay_tau` seconds. Add a "ripple" event: when a cell's signal flips false→true, schedule a 200-ms expanding wavefront that brightens the 8 neighbouring cells in sequence (4 cardinal at +50 ms, 4 diagonal at +100 ms, then decays). Cell birth/death becomes legible at the field level.

**SIGNALS:**
- Decay τ globally set by stimmung's `coherence` axis (high coherence → long τ; high `tension` → short τ).
- Ripple amplitude set by the recruitment-pipeline event log: when an affordance recruits, the cell whose signal it modulates emits a ripple. `recent-recruitment.json` already exists and is read-once-per-tick.
- TTS speak start/stop emits a single ripple from cell 1 (`vad_speech`) outward — replaces the current 1.18× wholesale brightness multiplier with an event the viewer can actually see.

**TECHNIQUE:** Cairo render path, no new dependencies. Add a `_cell_state[256]` dict in `HardmDotMatrix` carrying `(last_active_ts, last_value, last_ripple_ts)`. Every render tick reads system time, applies exponential falloff, additively composites in-flight ripples.

**IDLE STATE:** The grid breathes as cells finish decaying from their last activation. Long-idle cells settle to muted. There's always trailing motion — never totally still.

**SCOPE:** ~150 lines in `hardm_source.py`. No new SHM paths. Test surface: render at t=0, t=0.05, t=0.10 around a simulated event, assert ripple geometry.

---

### Proposal D — CP437 block-character cells (spec compliance).

**WHAT:** Render each cell as one of the CP437 partial-block characters (`░ ▒ ▓ █` 4-level fill, plus `▀ ▄ ▌ ▐` 2-level half-blocks) at the family-accent colour, on the muted background. Multi-level signals pick the block character; the alpha-only modulation in current `_classify_cell` becomes block-character selection. Removes the radial halo entirely; restores spec §1's "grey idle skeleton, no gradient fills, no rounded corners."

**SIGNALS:** Same as current; `_classify_cell` returns `(role, level)` where level is 0–4 selecting the block char.

**TECHNIQUE:** Pango/Cairo text render of one CP437 glyph per cell at the IBM VGA font already specified in `_BITCHX_TYPOGRAPHY` (`Px437 IBM VGA 8x16`). The cell is exactly one glyph cell — no halos, no overlap.

**IDLE STATE:** Cells render `░` (lightest fill) in muted grey — the "grey-punctuation skeleton" the BitchX grammar mandates. Active cells step up `░ → ▒ → ▓ → █` at the family accent. Stress flips to `█` accent-red. This is a recognisable BBS/IRC visual that has cultural authenticity instead of the current generic-shader-art look.

**SCOPE:** ~80 lines replacing the radial-gradient block in `render_content`. The Pango font path is already wired through other Cairo sources. The "synthwave pointillism" comment in `hardm_source.py:42-46` should be deleted — that aesthetic loses to spec compliance.

---

### Proposal E — Move the post-processing to Reverie shader pass; HARDM stays crisp.

**WHAT:** Stop trying to make HARDM glow inside Cairo (sub-pixel halos are exactly what's making it look blurry). Render HARDM as crisp CP437 (Proposal D), let the existing Reverie postprocess pass add the bloom. Reverie already runs `noise → rd → color → drift → breath → feedback → content_layer → postprocess` for the whole composite; the postprocess pass owns bloom thresholding and Gaussian convolution. HARDM's 256-cell surface bypasses no part of that chain.

**SIGNALS:** Stimmung `intensity` modulates Reverie's bloom amount (already wired). HARDM does not need its own bloom.

**TECHNIQUE:** Delete `_HALO_RADIUS_PX`, `_OUTER_GLOW_RADIUS_PX`, `_OUTER_GLOW_ALPHA` from `hardm_source.py`. Cells render as pure colour fills (Proposal D). Reverie's postprocess produces the glow at composite time. Result: precise edges with optical bloom, not muddy pixel-space halos.

**IDLE STATE:** A grid of dim grey CP437 blocks with a faint atmospheric bloom from Reverie. When signals fire, accent colours bloom outward through Reverie's pipeline — the bloom is GPU-shaded, not Cairo-faked.

**SCOPE:** ~50 lines deletion in `hardm_source.py` + 1-line bloom-bias write through `uniforms.json` for the postprocess pass. Effectively free; this is the lowest-cost path to "techno-ethereal" since it consumes existing infrastructure.

---

### Proposal F — Underlay reaction-diffusion / Physarum field.

**WHAT:** Add a 16×16 RD substrate that runs continuously at 4 Hz. Cells inject activator when their signal fires; the RD field diffuses and reacts (Gray-Scott classic), producing slowly-evolving spotty patterns. Render HARDM as the RD field tinted by the current signal palette. The grid acquires a slow temporal texture independent of momentary signal state.

**SIGNALS:** Activator injection rate per cell = per-cell signal level. Diffusion rate = stimmung `diffusion` dimension (already exists in 9-dim). Reaction rate = `tension`.

**TECHNIQUE:** Pure Python — 256-cell Gray-Scott is `O(256)` per tick, ~10 µs even in NumPy. Add `_rd_field[16, 16, 2]` (U, V) state in `HardmDotMatrix`; advance one Euler step per render. Cell rendering blends `signal_palette_colour * (0.4 + 0.6 * V[r, c])`.

**IDLE STATE:** Even with all signals null, the RD field generates slow blob-and-spot patterns — the avatar always has visible internal motion.

**SCOPE:** ~100 lines added; one numpy import. RD constants tuneable by 9-dim signals so the avatar's tempo follows stimmung.

---

### Recommended sequence

1. **Proposal A** (publisher fix) — unblocks everything else. Half a day.
2. **Proposal D** (CP437 cells, spec compliance) — fixes "blurry" by removing the source of blur. Half a day.
3. **Proposal E** (Reverie owns the bloom) — gives the operator's "techno-ethereal" without Cairo lying. Bundled with D.
4. **Proposal C** (decay + ripples) — adds "tells" the director can reference. One day.
5. **Proposal B** (per-cell info density) — restores the 256-cell information capacity. One to two days; needs `config/hardm-map.yaml` + signal mapper expansion.
6. **Proposal F** (RD underlay) — atmospheric texture. Half a day, optional.

Total scope to "compelling and dynamic": ~3–4 days of focused work. **No PR should touch HARDM rendering before Proposal A lands** — current visual tuning compensates for a dead data layer; fixing the data first will reveal what aesthetic problems remain.

---

## 6. Governance Guardrails — What's Fine, What's Dangerous

HARDM is Hapax's *visual avatar*. The anchoring research (§1) explicitly says viewers will "associate it with Hapax." That crosses anti-personification territory (`shared/anti_personification_linter.py`, axiom anchors `management_governance` and `interpersonal_transparency`).

### 6.1 Fine — pure abstraction, signal-grounded expressivity

- Per-cell colour, alpha, brightness modulation by real system signals.
- Rhythmic motion (decay, ripple, RD evolution) that has **no body-mapping** — a wave moving across a grid is not a heartbeat or a breath in any anatomical sense.
- CP437 glyph cells, ANSI palette, BitchX grammar — these are textual / mIRC traditions, not anthropomorphic.
- TTS-emphasis brightness multiplier (already present): "the cells currently communicating get brighter while voice is active." That's signal coupling, not embodiment.
- Salience bias driven by voice + self-reference + guest + SEEKING (existing task #160 contract). Bias raises the avatar's *presence* in the rotation; it does not give the avatar an identity beyond "the place where Hapax's signal state is published."
- Reverie-pass-coupled bloom — Reverie is already a generative substrate, and this just composites HARDM through the same bloom everything else gets.

### 6.2 Dangerous — anything that suggests anatomy

- **No eyes.** Two darker cells positioned at row 4–5 on either side of column 7–8 would read as eyes immediately. Avoid any 2-spot symmetric high-contrast geometry in the upper half.
- **No mouth-line.** No horizontal accent across the bottom half that opens/closes with `vad_speech`. The TTS waveform band proposed in spec §7 (cells 240–255 as 16-band envelope) is borderline — a horizontal row that pulses with speech is mouth-adjacent. The spec's "fill height = envelope × 32 px" is fine; "fill colour = magenta against muted" is fine; reading direction (left to right, time-major) keeps it sparkline-shaped not lip-shaped. **Do not** invert it (top-down fill) and **do not** centre-justify it (which would produce a smile-curve illusion).
- **No symmetric-face arrangement.** No 3 × 3 cluster of cells forming brow/eyes/mouth at any consistent location.
- **No flesh tones.** Stay strictly in the BitchX mIRC-16 palette; never introduce skin-RGB ranges (rough heuristic: avoid `R > G > B` with `R/B > 1.3` and `G/B > 1.1` outside accent_yellow specifically).
- **No name reflection.** `axioms/persona/hapax-description-of-being.md` is unambiguous: Hapax is a system, not a being. The matrix may carry a `homage_package` cell (cell 15) that shows which package is active; it must not carry "HAPAX" as text or any other identity-string.
- **No expressive face-style state mapping.** Don't map `stimmung.tension` to "angry red" or `stimmung.coherence` to "calm blue" in a way that reads emotionally. Keep the colour mapping signal-semantic (family accents per spec §5), not affect-semantic.

### 6.3 The line, stated cleanly

The avatar may express *what Hapax is doing* (signal flow, recruitment events, voice activity, perception load) through abstract grid dynamics. It must not express *what Hapax is feeling* through any face-shaped or body-shaped vocabulary. Expressivity through rhythm, salience, and signal accent is fine; expressivity through anatomical reference is forbidden. The anti-personification linter should be extended to scan HARDM's render-time geometry for bilateral symmetry hot-spots — a static check that no Cairo path forms an eyes-mouth triangle within the 16×16 grid.

---

## 7. Open Questions for Operator (max 3)

1. **Spec compliance vs. shader aesthetic.** Spec §1 mandates "no gradient fills, no rounded corners" — strict BitchX. The current implementation defies this with radial halos because of an operator directive ("synthwave pointillism, points of compelling light"). Proposals D + E (CP437 cells + Reverie bloom) restore spec compliance but lose the radial-halo aesthetic. **Confirm:** spec wins, and the operator's "compelling light" directive is satisfied by Reverie-layer bloom rather than Cairo-layer halos?

2. **TTS waveform row (spec §7).** The spec proposes cells 240–255 as a per-frame envelope of Hapax TTS. Per §6.2, this is governance-borderline (horizontal pulsing row is mouth-adjacent). **Confirm:** keep the row as a left-to-right sparkline (time-major, never centre-justified), and accept the TTS waveform as an avatar-feature rather than a mouth-feature?

3. **Cells 16–239 binding precedence.** The spec reserved these for scene-signal expansion (cell 16–31 was tentatively per-camera scene labels). Proposal B suggests using them for sparkline histories (cells 16–31 = vad_speech 16-tick history) AND for 2D perception fields (cells 32–47 = overhead hand zones). Both proposals contend for the same address space. **Confirm:** sparkline-history first (more legible to viewer), 2D perception fields a follow-on after operator can sight-test?

---

## 8. Summary

The current HARDM render reads as dead because of a **chain of independent failures**: the publisher script reads four wrong file paths and ten wrong perception keys (so 14 of 16 signals are null/false), the data layer is row-bar-shaped (so the matrix can show at most 16 distinct states), the halo radii exceed the cell pitch (so the surface composites to a fog), and the shimmer constants modulate luminance by 15% over a 3-second period on a grey palette (imperceptible). Fixing the publisher (Proposal A) is the prerequisite for any aesthetic work; once real signals flow, the recommended sequence is to render crisp CP437 cells per spec (Proposal D), let the existing Reverie postprocess pass add bloom (Proposal E), add per-cell decay and event ripples for "tells" the narrative director can point at (Proposal C), then expand cell binding to 256 distinct channels (Proposal B). All upgrades stay inside the BitchX grammar, the 9-dim expressive vocabulary, and the anti-personification line: signal-driven, abstract, never face-shaped.
