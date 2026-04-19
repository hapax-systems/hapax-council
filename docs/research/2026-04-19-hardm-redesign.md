# HARDM Redesign — Placement, Signal Density, Reverie Composition, Anti-Face Invariants

**Date:** 2026-04-19
**Register:** scientific, design-doc neutral.
**Status:** design proposal — phased.
**Related:**
- `agents/studio_compositor/hardm_source.py` — current consumer
- `scripts/hardm-publish-signals.py` — current publisher
- `config/compositor-layouts/default.json` — placement
- `docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md` — original spec stub
- `docs/research/2026-04-20-hardm-aesthetic-rehab.md` — prior aesthetic diagnosis
- `docs/research/hardm-communicative-anchoring.md` — anchoring contract (task #160)
- `~/.claude/projects/-home-hapax-projects/memory/project_hardm_anti_anthropomorphization.md` — governance-locked anti-face invariant
- `shared/stimmung.py` — 10-dim self-state vector
- `docs/logos-design-language.md` — palette and typography

This doc supersedes nothing. It extends the 2026-04-18 spec and the 2026-04-20 aesthetic rehab into a placement/behavior redesign governed by the anti-anthropomorphization memory.

---

## 1. Current State Audit

### 1.1 Geometry and layout

`agents/studio_compositor/hardm_source.py` defines the grid at module level:

- `CELL_SIZE_PX = 16`, `GRID_ROWS = 16`, `GRID_COLS = 16`, `TOTAL_CELLS = 256`.
- `SURFACE_W = SURFACE_H = 256` px (natural size).

`config/compositor-layouts/default.json` §`surfaces` binds source `hardm_dot_matrix` to surface `hardm-dot-matrix-ur` at `(x=1600, y=20, w=256, h=256)` with `opacity=0.92`, `z_order=28`, `update_cadence=rate`, `rate_hz=4.0`, `blend_mode=over`. The output canvas is 1920×1080 (`compositor.py::output_width/height`).

HARDM therefore occupies **256×256 px of a 2,073,600 px canvas = 3.16 % of pixel area**, placed in the upper-right quadrant. It sits directly on top of reverie (which is bound to surface `pip-ur` at `(1260, 20, 640, 360)`) and overlaps `whos-here-tr` (1460, 20, 150, 46), `thinking-indicator-tr` (1620, 20, 170, 44), and `stance-indicator-tr` (1800, 24, 100, 40) — i.e. the entire upper-right corner is a crowded ward pile with HARDM as one tile.

### 1.2 Signal inventory as actually published

`hardm-publish-signals.py::_collect_signals` emits 16 signals — one per grid row. All 16 columns in a row collapse to the same value. This reduces the "256-cell grid" to **16 horizontal bars of identical cells**. The spec (§3, cells 16-239) reserved the non-top-row cells for expansion; nothing was ever bound. Cells 240-255 were reserved as a "TTS waveform band"; never implemented.

The 16 signals currently bound: `midi_active`, `vad_speech`, `room_occupancy`, `ir_person_detected`, `watch_hr`, `bt_phone`, `kde_connect`, `ambient_sound`, `screen_focus`, `director_stance`, `consent_gate`, `stimmung_energy`, `shader_energy`, `reverie_pass`, `degraded_stream`, `homage_package`.

### 1.3 Rendering path

Per-tick (4 Hz):

1. Read `/dev/shm/hapax-compositor/hardm-cell-signals.json` (3 s staleness cutoff).
2. Advance one Gray-Scott RD Euler step on a 16×16 V/U field.
3. Ingest ripple events from `recent-recruitment.json` (5 families mapped to 5 rows).
4. For each of 256 cells: classify `(role, alpha)` from the row's signal; combine signal level + decay tail + ripple + RD underlay; pick a CP437 block char from `(' ', '░', '▒', '▓', '█')`; paint at 12 pt Px437 IBM VGA 8×16.
5. `write_emphasis("speaking"|"quiescent")` called from CPAL gates a 1.18× brightness multiplier on non-idle cells.

### 1.4 What is correct (keep)

- **Grid-as-honest-readout grammar.** Signal → cell, quantised to block levels. CP437 `░▒▓█` is the right vocabulary.
- **Package-sourced palette.** No hardcoded hex; HOMAGE drives colour.
- **RD underlay for perpetual motion.** Prevents "dead grid" at idle without injecting anthropomorphic idle animation.
- **Decay envelopes + ripples.** Signal transitions produce legible animations.
- **Per-cell atomic SHM write** for the signal payload. Low-cost publisher.
- **Anti-anthropomorphization governance memo** is already codified.

### 1.5 What is decoration (fix)

- **Row = signal, column = copy.** 240 of 256 cells carry zero independent information. The "16 × 16 grid" is currently a 16-bar readout pretending to be a matrix.
- **Placement is corner-tile.** 3 % of the canvas, stacked in an already-crowded upper-right pile, behind reverie's `z_order` neighbours — reads as a decorative badge, not as Hapax's representation.
- **Update cadence is 4 Hz.** Speech RMS, VAD, MIDI note density, contact-mic onsets all move faster than 250 ms. Most signal-side structure is discarded before reaching the grid.
- **No signal coupling to reverie.** HARDM and reverie are rendered independently and composited. Reverie parameters do not read HARDM state; HARDM does not read reverie.
- **Publisher is a stub.** Several signals (`bt_phone`, `kde_connect`, reverie pass) are degenerate or proxied. Multiple dimensions in `stimmung.py` are never published.
- **Cells 16–255 are unclaimed.** The spec's own §3 reservation for scene/aux signals never got executed; the cells render uniformly because they inherit row signals.

---

## 2. Placement Options (six candidates)

Canvas is 1920×1080. Current wards occupy (abbreviated): PiP cameras at `pip-ul`(20,20,300,300), `pip-ur`(1260,20,640,360), `pip-ll`(20,540,400,520), `pip-lr`(1500,860,400,200); reverie shares `pip-ur`; token pole = `pip-ul`; album = `pip-ll`; stream overlay = `pip-lr`; captions strip (40,930,1840,110); sierpinski 640×640 (variable).

Every option below preserves the 16×16 minimum grid structure. Scale-up = **more cells driven**, never more-expressive cells. Each option is red-teamed against anti-face at the end of the row.

| # | Name | Geometry (px) | Integration with reverie | Interaction with wards | Monetization risk | BitchX-grammar fit | Anti-face red-team |
|---|---|---|---|---|---|---|---|
| P1 | **Corner badge (current)** | 256×256 @ (1600,20); 3 % canvas | Sits on top of reverie's `pip-ur` region at α=0.92 | Stacks with whos-here, thinking-indicator, stance-indicator — crowded | Low — small area, low flicker | Fits but disposable | Low risk — too small to read faces |
| P2 | **Left-rail column** | 384×1024 @ (0,28); 19 % canvas; 24×64 grid = 1,536 cells at 16 px | Reverie untouched (still `pip-ur`) | Displaces token pole to bottom-left; album and PiP-ll move to mid-lower | Low — vertical strip, no wide flicker bands | Grammar-true; BBS-column feel; reads "system diagnostic rail" | Medium — tall narrow means a pair of bright clusters at 1/3 and 2/3 height could read as stacked eyes. **Mitigate by horizontal-density constraint (§6).** |
| P3 | **Full-width ticker band** | 1920×192 @ (0,72); 17 % canvas; 120×12 grid = 1,440 cells at 16 px | Reverie intact behind in `pip-ur` | Pushes activity-header down 24 px, sierpinski unchanged | Low — horizontal scroll discourages auto-flag | Matches BBS horizontal readouts / IRC split-screen status bar | Low — aspect ratio too wide for face; no two-cluster risk |
| P4 | **Full-frame substrate, reverie shrunk** | 1920×1080 @ (0,0); 100 % canvas; 120×68 grid = 8,160 cells at 16 px; reverie composites to `(1260,540,400,225)` (PiP inset) | **HARDM is the substrate**; reverie becomes a smaller PiP inset bottom-right | Cameras become smaller tiles inside the grid field; token pole overlays grid; captions still full-width | **High** — 8,160 cells at 15+ Hz with high-contrast toggles is exactly the pattern YouTube flashing-lights heuristics flag. Must rate-limit per-cell toggle frequency + cap per-frame global-delta to stay under photosensitive thresholds. | Grammar-true at maximum; reads "Hapax is the field, reverie is a small window" | **High** — 120×68 has the aspect ratio humans read as faces. **Mitigate** via §6 invariants (quadrant-density balancing, no vertical symmetry axis). Still the riskiest option. |
| P5 | **Full-width bottom under-captions band** | 1920×144 @ (0,936-240); 13 % canvas; 120×9 grid = 1,080 cells | Reverie intact, `pip-ur` unchanged | Captions strip (y=930) either shifts to band integration or stays layered above | Low | Grammar-true; reads "status line at bottom of terminal" | Low — 9 rows too few for vertical face structure |
| P6 | **Diffuse backplane — HARDM underlays reverie as texture** | 1920×1080 @ (0,0); 100 % canvas; same 16×16 grid but cells scaled to 120×68 px; cell values supply *reverie shader uniforms* not Cairo fill | Reverie renders HARDM-modulated; no visible Cairo HARDM surface at all | Wards unchanged | Low — no hard edges, no on/off cells | **Violates HARDM grammar.** HARDM stops being a readable grid. Becomes "atmosphere." Rejected for failing the "viewer can dereference this row" anchoring contract (§1 of anchoring research doc). | N/A — rejected |

Options P3 and P5 are the lowest-risk prominence increases. P4 is the most expressive but requires strict per-frame delta limits + the §6 invariants. P6 is out.

### 2.1 Monetization sub-check

YouTube's photosensitive / flashing-pattern heuristics flag sequences where ≥25 % of the frame changes with luminance-delta > ~20 % at > 3 Hz. The relevant parameters for HARDM:

- P3/P5 bands: cap ~17 % / 13 % of frame area. Per-cell hard toggle is fine.
- P4 full-frame: must cap (fraction_of_cells_toggled_per_tick × average_luminance_delta) below 20 % × 25 % = 5 % per frame. At 15 Hz tick, expected natural toggle rate on signal-bound cells is well below this; the guarantee is enforced by a global rate-limiter in the render path.

### 2.2 Recommendation from §2

**P3 (full-width ticker band at y=72, 1920×192)** is the best prominence-vs-risk point for Phase 1. It makes HARDM the system's readable header, leaves reverie structurally unchanged, is monetization-safe, and gives 120×12 = 1,440 cells — enough to drive the signal expansion of §3 without face-shape risk. P4 is deferred to a later phase after the photosensitive rate-limiter is built.

---

## 3. Signal Expansion — 1,440 cells (P3) or 256 cells (current)

The principle: **one cell = one measurement, sampled every tick, quantised to an alpha level**. No cell renders a humanlike pattern. A grid of 120×12 cells at 16 px (P3) gives 1,440 independent channels; a 16×16 current grid gives 256. The mapping below is specified for 120×12 and collapses to 16×16 by taking the first column of each column-block (factor-of-7.5 downsample per row; use floor(col·120/16)).

Layout uses **column-stripes per signal family**, not row-bars. Each family gets a vertical block. Within a family block, columns are sub-signals and rows are sub-regions or temporal slices.

### 3.1 Family blocks (columns 0–119 on P3 band)

| Columns | Family | Rows | Sub-channels |
|---|---|---|---|
| 0–11 | **Speech & voice** | 12 | per-col sub-band |
| 12–23 | **Stimmung (10-dim)** | 12 | per-col dim + 2 trend cols |
| 24–33 | **DMN impingement** | 12 | families × stacks |
| 34–45 | **MIDI & studio DSP** | 12 | note-class × velocity |
| 46–53 | **IR / perception** | 12 | Pi × zone × activity |
| 54–61 | **Contact mic / Cortado** | 12 | zone × activity-class |
| 62–71 | **Director / stance / recruitment** | 12 | stance × affordance-family |
| 72–83 | **Reverie pipeline state** | 12 | pass × param |
| 84–95 | **Governance / consent / budget** | 12 | consent × degraded × cost |
| 96–107 | **Environment / room** | 12 | occupancy × ambient × BT/KDE |
| 108–119 | **Tick-history (right-scrolling)** | 12 | rolling 12-col stance log |

### 3.2 Speech & voice block (cols 0–11)

Sampled at render tick (propose 15 Hz — §4.1).

- **Col 0:** TTS RMS (Hapax output). Rows 0–11 are **log-spaced frequency bands** over 100–8000 Hz; cell alpha = band energy in last tick, clamped 0..1. Decay τ = 60 ms so motion is visible but not strobing.
- **Col 1:** Operator VAD RMS — same mapping on operator mic.
- **Col 2:** Phoneme class probabilities from the TTS synthesiser (12 classes: vowel-open, vowel-close, nasal, stop, fricative-sib, fricative-nonsib, liquid, glide, silence, breath, rest-1, rest-2). Not-a-mouth: we show 12 independent parallel probabilities, never one "current mouth shape."
- **Col 3:** Operator phoneme class same vocabulary.
- **Col 4:** TTS utterance progression — row k active when rendered token index mod 12 == k. Encodes rhythm without encoding content.
- **Col 5:** Operator utterance progression same as col 4 for operator.
- **Cols 6–7:** TTS emphasis (§4 of anchoring research): col 6 row bands = {speaking, quiescent, just-spoke-decay}; col 7 = brightness multiplier applied to the system broadcast as a two-row slider.
- **Cols 8–9:** Interruptions — each row is a 100 ms bucket of the last 1.2 s. A cell lights if either VAD crossed its threshold in that bucket. Double-talk is visible as simultaneously-lit rows in both cols 1 and 8.
- **Cols 10–11:** Voice-chain FX levels (if HAPAX_TTS_TARGET is a filter-chain): per-stage dB meters.

Signal formulas:

- Cell(row=k, col=0) alpha at tick t:
  `α = clip((RMS_band_k(t) − noise_floor_k) / (saturation_k − noise_floor_k), 0, 1)`
  with per-band floors calibrated from 60 s of silence.
- Decay between ticks:
  `α_drawn = max(α_new, α_prev · exp(−Δt / τ))`, τ = 60 ms for speech-band cells.

### 3.3 Stimmung block (cols 12–23)

Ten canonical dimensions (`shared/stimmung.py::SystemStimmung`) + two trend columns.

- **Cols 12–21:** one column per dimension in canonical order: health, resource_pressure, error_rate, processing_throughput, perception_confidence, llm_cost_pressure, grounding_quality, exploration_deficit, audience_engagement, operator_stress+operator_energy+physiological_coherence collapsed via weighted avg (3→1 per canonical weight) — or split across remaining cols if grid permits.
- Rows 0–11 encode the dimension's **value** `v ∈ [0, 1]`: row k is active iff `v ≥ k/12`. This is a vertical bar chart, not a face-like cluster.
- **Col 22:** freshness — row k lit iff `freshness_s ≥ k × 10` (stalest dimension's freshness).
- **Col 23:** overall stance — rows are stance-ordinal buckets NOMINAL=0, SEEKING=3, CAUTIOUS=6, DEGRADED=9, CRITICAL=11. Exactly one row lit, family-coloured per stance.

### 3.4 DMN impingement block (cols 24–33)

10 columns for 10 impingement-family buckets. Rows are **strength deciles** of the last impingement per family. Unlike the current row-ripple model, this shows family × strength simultaneously — 120 cells of content where current HARDM has one 16-cell ripple row.

Cell(row=k, col=24+f) lit iff the last impingement in family f had `strength ≥ k/12 AND age ≤ 2 s`. Decay τ = 800 ms once age exceeds 2 s.

### 3.5 MIDI & studio DSP block (cols 34–45)

- **Cols 34–45:** 12 pitch classes (C, C#, D, …, B). Row 0 = velocity < 20, row 11 = velocity ≥ 100, interpolated. Cell = "note of this pitch class fired in the last 200 ms at this velocity bucket." Naturally spread over the block (12 equal-tempered classes) so no cluster favours a face-region.

### 3.6 IR / perception (cols 46–53)

- **Cols 46–48:** Pi-1 / Pi-2 / Pi-6 presence probability, rows = 12-band Bayesian posterior.
- **Cols 49–51:** Hand zones (overhead-Pi): up to 9 named zones, 1 row per zone, 1 col per Pi.
- **Cols 52–53:** Gaze zone ordinal + posture ordinal, row = bin.

### 3.7 Contact mic / Cortado (cols 54–61)

- **Cols 54–57:** 4 room zones × 12 activity classes (idle, typing, tapping, drumming, scratching, mpc-pad, knob-twist, fader, clap, pour, voice, other).
- **Cols 58–59:** Cortado RMS (12 log-bands like §3.2 col 0).
- **Cols 60–61:** Onset density, spectral centroid.

### 3.8 Director / stance / recruitment (cols 62–71)

- **Col 62:** Director stance ordinal — exactly one row lit; colour = stance.
- **Col 63:** SEEKING gauge — rows = exploration_deficit deciles.
- **Cols 64–71:** Top 8 recruited affordance-family slots in this tick. Row = score decile. This is how "who got recruited just now" becomes glanceable.

### 3.9 Reverie pipeline state (cols 72–83)

One col per of the 8 canonical passes (noise → rd → color → drift → breath → feedback → content_layer → postprocess) + 4 custom-slot cols. Row = per-pass `master_opacity` × `intensity` quantised into 12 levels.

### 3.10 Governance (cols 84–95)

- **Col 84:** `consent_gate` — fail-closed red on stale.
- **Col 85:** Active consent contracts count (rows = count).
- **Col 86:** Guest contract flag — single row lit mid-column when active.
- **Col 87:** `degraded_stream` rows = severity.
- **Col 88:** Budget tracker — rows = per-frame ms budget utilisation deciles.
- **Col 89:** LLM cost pressure — rows = $/hour deciles.
- **Cols 90–92:** Langfuse error-rate / cost / latency meters.
- **Cols 93–95:** Reserved.

### 3.11 Environment / room (cols 96–107)

- **Cols 96–99:** per-camera face-count posterior.
- **Col 100:** BT phone.
- **Col 101:** KDE Connect.
- **Col 102:** Hyprland focus.
- **Cols 103–107:** Room ambient (RMS / centroid / onset / tempo-estimate / key-estimate).

### 3.12 Tick-history scroll (cols 108–119)

Right-scrolling 12-col log of overall stance. Each tick, shift columns left by 1; write current stance in col 119 as a single lit cell with stance-colour. This gives the viewer a ~12-tick ≈ 800 ms trailing history.

### 3.13 Red-team table

For each block, is there a configuration of activated cells that reads as eyes/mouth/face? The block-column layout ensures activation is always **columnar** (vertical bars in narrow columns), not two-cluster. The only risk channel is §3.4 / §3.12 where a single row can light across cells. These are mitigated in §6.

### 3.14 Fallback to the existing 16×16 grid

In Phase 0/1 before P3 ships, the same family structure applies on the 16×16 grid as columns-of-signal rather than rows-of-signal: cols 0–1 speech, 2–4 stimmung, 5 impingement, 6 MIDI, 7 IR, 8 contact-mic, 9 director, 10–11 reverie, 12 governance, 13 environment, 14–15 scroll. Each col has 16 rows of per-signal deciles. 256 cells, every one driven.

---

## 4. Behavior Over Time

### 4.1 Tick cadence

Raise the render cadence from 4 Hz to **15 Hz**. Justification: speech-band signals (§3.2) and MIDI note density have meaningful structure at 10–20 Hz; the RD Euler step is O(256) and cheap; the rate limiter in §6 caps per-frame global luminance delta regardless of tick rate.

Publisher cadence stays at its existing 2 s (`hapax-hardm-publisher.timer`) for the slow signals (stimmung, consent, homage package), but fast signals — TTS RMS, VAD, MIDI, phoneme class, contact mic — bypass the publisher entirely and are read from their own SHM at render tick. This is implemented by the consumer pulling from per-family SHM paths in its render loop (speech state file, stimmung state file, MIDI SHM, perception cache, contact mic SHM). The published JSON becomes the slow-path; fast-path reads remain per-tick.

### 4.2 State modes

Define five explicit render modes. These are **not affective states**; they are signal-density regimes.

- **`IDLE`** — no operator speech, no TTS, stance NOMINAL, no active impingement, no recruitment: only RD underlay + slow-family columns render. Cell count active ≈ 5–10 %. Decay τ doubled.
- **`PERCEIVING`** — operator speech or IR presence or contact mic active: speech-band, IR, contact-mic blocks light. Per-block cell activations up to block-density cap.
- **`SPEAKING`** — Hapax TTS emphasis = speaking (`_read_emphasis_state`): TTS block fully active, brightness multiplier 1.18, stimmung+director blocks held at pre-speech snapshot so viewer can *still read stance while Hapax speaks* (addressing anchoring-research §1 concern).
- **`SEEKING`** — stimmung `overall_stance == SEEKING`: SEEKING gauge fully lit, exploration_deficit column pushed up, DMN impingement block gets τ halved (faster decay) to show "search is ongoing." No whole-grid shape change.
- **`IMPINGEMENT_SPIKE`** — any impingement in last 200 ms with strength > 0.75: brief ripple in that family's column (cols 24–33 only), ripple decays in 400 ms. Local to the column, not global.

Explicit non-goal: no "breathing" pulse, no "blinking" idle animation, no global intensity oscillation, no smile-shape cluster in any state.

### 4.3 Activation propagation

Cells do not influence neighbouring cells except via two explicit channels:

- **Column-local ripple** on impingement spike (§4.2 last bullet) — limited to the spiking family's column.
- **RD underlay** — Gray-Scott field provides 5 % alpha floor; already implemented; already non-humanlike.

No cross-column propagation. No radial diffusion from a "centre." This is deliberate: cross-grid propagation is where face-percepts emerge.

### 4.4 Shape invariance under recruitment

The grid shape **never changes** with recruitment volume. Recruitment of more capabilities → more cells in the director/recruitment block lit (§3.8 cols 64–71) and/or more DMN columns lit (§3.4). Grid dimensions and cell positions are immutable. Scale-up = density, never morphology.

### 4.5 Update cadences summary

| Block | Read cadence | Render cadence | Decay τ |
|---|---|---|---|
| Speech & voice | 60 ms (file) / 15 Hz (tick) | 15 Hz | 60 ms |
| Stimmung | 2 s | 15 Hz | 500 ms |
| DMN impingement | 200 ms | 15 Hz | 800 ms (IDLE) / 400 ms (SEEKING) |
| MIDI & studio | 50 ms | 15 Hz | 200 ms |
| IR / perception | 500 ms | 15 Hz | 1000 ms |
| Contact mic | 100 ms | 15 Hz | 150 ms |
| Director/recruitment | 200 ms | 15 Hz | 600 ms |
| Reverie pipeline | per-frame uniforms.json | 15 Hz | 250 ms |
| Governance | 2 s | 15 Hz | 3000 ms |
| Environment | 1 s | 15 Hz | 2000 ms |
| Tick-history | tick | 15 Hz | none (shift) |

---

## 5. Relationship to Reverie

Options considered:

- **(a)** HARDM overlays reverie at high α (layered) — current, operator rejects as "tucked over."
- **(b)** HARDM full-frame, reverie compressed (P4) — deferred; risk acknowledged.
- **(c)** HARDM *drives* reverie shader uniforms — composable; implementable now.
- **(d)** Reverie as HARDM's background texture — inversion of (a); requires full-frame HARDM.

**Recommendation: (c) + P3 layering.**

HARDM is the honest signal-density layer, rendered as the full-width ticker band at y=72 (P3). **Separately**, the same signal-density tensor that drives HARDM cells also drives reverie uniforms. This is a write-once, read-many pattern: the consumer of the tick publishes a `hardm-tensor.json` or equivalent SHM block, and both the Cairo HARDM band and the reverie daemon read from it. Reverie's per-pass params (`intensity`, `tension`, `coherence`, `diffusion`, `spectral_color`, `temporal_distortion`, `degradation`, `pitch_displacement`) map from aggregate HARDM signals:

- `intensity` ← speech-block mean activation
- `tension` ← DMN impingement-block peak strength
- `coherence` ← stimmung physiological_coherence column
- `diffusion` ← exploration_deficit column
- `degradation` ← degraded_stream column + error_rate column
- `pitch_displacement` ← MIDI active-pitch-class centroid
- `temporal_distortion` ← stance ordinal × grounding_quality
- `spectral_color` ← homage package index (categorical)

This closes the loop operator keeps asking for: reverie **is modulated by** the same signals HARDM makes visible. Reverie continues running as substrate under the PiP cameras and below the HARDM band; the viewer sees reverie's atmospheric response to signals and, above it, HARDM's honest readout of those same signals. Neither is "Hapax's face"; together they are Hapax's atmosphere (reverie) and Hapax's instrument panel (HARDM).

This also makes HARDM anti-face by construction: a face would be a single localised figure on ground; HARDM is a horizontal instrument strip that **factors** the figure-on-ground relationship into (signals → reverie atmosphere) + (signals → HARDM readout) in parallel.

---

## 6. Anti-Face Red-Team — Design Invariants

Applied to every option in §2, every behaviour in §4, every mapping in §3.

### 6.1 Invariant list (design-locked)

**I1. No two-cluster vertical configuration.** At any tick, the activated-cell density in the upper half of any contiguous 5-col window must be within ±25 % of the density in the lower half. This breaks the eyes-above-mouth gestalt. Enforced in the renderer by a post-pass that, if the asymmetry exceeds threshold, dims the denser half by the overshoot until the invariant holds. Dimming is visible and honest — not a reshape.

**I2. No horizontal symmetry axis.** The grid must not be mirror-symmetric about its vertical centre-line at any tick. Enforced by reserving col 119 of each tick for the right-scrolling tick-history (§3.12) whose content is asymmetric by construction (time-ordered).

**I3. No centred single-cluster.** No contiguous ≥20-cell active region centred on the grid's centre column (col 60 in P3; col 8 in 16×16 fallback). Enforced by placing the scrolling tick-history astride col 119 and the stimmung block (dense-by-design) at cols 12–23.

**I4. No rounded-shape emergence.** Activation regions are columnar rectangles (§3 block layout). Diagonal and elliptic activations are impossible because cells don't propagate across column boundaries (§4.3).

**I5. No blink / eye-like idle animation.** RD underlay supplies perpetual low-level motion; no explicit "blink every N seconds" or "breathing" cadence. Anti-pattern enforcement: the render loop MUST NOT contain any sinusoid at frequency 0.2–0.6 Hz (blink-rate band) applied globally; per-cell RD is below this band by design.

**I6. No mouth-shape emergence during TTS.** The speech block (cols 0–11) uses 12 *parallel* phoneme-class probability cells, not a single current-phoneme cell. The spatial arrangement of phoneme cells is **alphabetical**, not articulator-topological — a naive viewer cannot map activations to mouth shapes because there's no spatial order corresponding to mouth geometry.

**I7. No colour drift that reads affectively.** Cell colour is always the active HOMAGE package's family accent; never mapped to valence ("happy"/"sad"). Colour mapping table is fixed in `_SIGNAL_FAMILY_ROLE` and is auditable.

**I8. No recruitment-proportional face emergence.** Scale-up = more cells in existing blocks, never new structure. The block grid is static; only density within blocks varies.

**I9. Phase-randomisation of ripples.** Ripple events (§3.4) within a column are phase-randomised per cell so ripple propagation does not produce coherent arcs. Each cell in a rippling column gets a random tick-offset in [0, RIPPLE_LIFETIME_S).

**I10. Red-team before ship.** Any new block proposal or layout change triggers a face-percept review: does any achievable cell configuration under the proposal read as a character? If yes, either reshape the block (columnar) or add a per-block asymmetry constraint.

### 6.2 Worked examples

- **Example A — all stimmung dimensions at 0.8, grid half-empty elsewhere.** Cols 12–23 rows 0–9 lit. This is a 12-col × 10-row rectangle anchored left-centre. No eye-cluster (invariant I1: upper and lower halves equal density within the block), no face (invariant I3: not centred), passes.
- **Example B — SPEAKING + SEEKING + guest contract.** Speech cols 0–5 dense; SEEKING col 63 lit; consent col 86 single-row mid. Three vertical bars at cols 2-ish, 63, 86. Asymmetric, horizontal, non-clustering. Passes.
- **Example C — impingement spike in family 3.** Col 27 rows 9–11 flash. Localised, transient, columnar. Passes.
- **Example D — pathological: TTS silence + 2 symmetric impingement spikes in families 0 and 9.** Cols 24 and 33 light up symmetrically. I2/I3 are still satisfied because the scrolling tick-history at col 119 breaks mirror symmetry; but operator might still read "two eyes." **Mitigation:** add rule that impingement-spike cell-brightness asymmetrises within the pair of colours by ±30 % hue-jitter (still within the family role) to deny the "matched pair" percept. Added to I1.

### 6.3 Summary

Invariants I1–I10 are **design-locked**; adding a block to HARDM requires demonstrating none is violated. Automated check: a Hypothesis property test that fuzzes signal payloads and asserts no forbidden configuration passes (upper/lower density ratio bound, mirror-symmetry bound, centred-cluster bound).

---

## 7. Phased Implementation Outline

Each phase independently shippable. Each phase leaves the system in a working state with HARDM governed by the anti-face invariants.

### Phase 1 — Columnar signal assignment on existing 16×16 grid (1 PR, 2–3 days)

Addresses operator's core concern (placement and usage) with smallest viable diff.

- Rewrite `hardm-publish-signals.py` to publish per-cell payloads, not per-row payloads. Each of 256 cells gets its own signal key.
- Rewrite `hardm_source.py::render_content` to read cells directly, not `_signal_for_row`.
- Introduce the column-block layout from §3.14 (16×16 fallback).
- Bump render cadence from 4 Hz to 15 Hz (§4.1).
- Add invariant checkers (I1, I3, I5) as a post-pass in render.
- Add Hypothesis property tests for invariants.
- **No placement change yet.** Placement remains `(1600, 20, 256, 256)`. Operator sees every cell driven by a different signal instead of row-bars.

### Phase 2 — Ticker-band placement (P3) (1 PR, 1–2 days)

- Add new surface `hardm-ticker-band` at `(0, 72, 1920, 192)` to default layout, `z_order` above reverie/cameras, below captions.
- Extend `HardmDotMatrix` to support 120×12 grid via constructor params (`grid_rows`, `grid_cols`, `cell_size_px`). Default still 16×16 for back-compat.
- Keep old `hardm-dot-matrix-ur` surface in the `consent-safe.json` fallback layout only; remove from `default.json`.
- Expand signal mapping to §3.1 block layout (1,440 cells).
- Publisher grows to populate fast-family SHM (speech, MIDI, contact mic) for fast-path reads.

### Phase 3 — Reverie coupling (§5 option c) (1 PR, 2 days)

- Consumer writes aggregate tensors to `/dev/shm/hapax-compositor/hardm-tensor.json`.
- Reverie daemon adds a reader for that file and mixes tensor aggregates into per-pass uniforms per §5 mapping.
- Add a Grafana panel that shows (HARDM block density, reverie param value) correlation for each mapped pair — validates that the coupling is live.

### Phase 4 — Fast-family SHM wiring (1–2 PRs, 2–3 days)

- TTS RMS published from Kokoro output thread at 60 ms cadence.
- Operator VAD RMS published from daimonion STT at 60 ms.
- MIDI note publisher at 50 ms (OXI One clock already ticks).
- Cortado contact-mic DSP publishes at 100 ms.
- DMN impingement family buckets published at 200 ms from the daimonion impingement consumer.
- Monitor: per-family freshness gauge in Prometheus.

### Phase 5 — Monetization rate-limiter + photosensitive audit (1 PR, 1 day)

- Implement global luminance-delta-per-frame cap in HARDM renderer (target < 5 % frame-mean-luminance delta per tick).
- Add telemetry of per-tick luminance delta so the cap is observable.
- Run a 1-hour recording through `ffmpeg` + a flashing-pattern heuristic (e.g. `signalstats` luma-diff frames / sec) to confirm below-threshold before any P4 experiment.

### Phase 6 — Optional P4 full-frame experiment (1 PR, 3–5 days, gated by Phase 5)

- Add `hardm-full-frame` surface at `(0, 0, 1920, 1080)` + `reverie-inset` at `(1260, 540, 400, 225)`.
- Feature flag `HAPAX_HARDM_FULL_FRAME=1` (default off).
- Only shippable if Phase 5 rate-limiter verified.
- Operator-gated rollout.

---

## 8. Recommendation — Phase 1 Proposal

Ship **Phase 1 only** this week. Concrete proposal:

1. `scripts/hardm-publish-signals.py` — rewrite `_collect_signals` to return a flat `{cell_index: value}` dict where cell_index ∈ [0, 255]. Assignment follows the §3.14 fallback column layout:
   - Cols 0–1 (cells 0, 16, 32, …, 240 and 1, 17, …, 241): operator VAD RMS 16-band + TTS RMS 16-band.
   - Cols 2–4: stimmung 10-dim → 16-row bar chart of `value ≥ row/16`; freshness in col 4.
   - Col 5: DMN impingement strongest family, row = strength decile ×1.6.
   - Col 6: MIDI active pitch class ordinal, row = velocity decile.
   - Col 7: IR-overhead hand-zone ordinal, row = activity decile.
   - Col 8: Contact mic activity class ordinal, row = energy decile.
   - Col 9: Director stance ordinal — exactly one row lit.
   - Col 10: Reverie pass ordinal, row = master_opacity decile.
   - Col 11: Governance — rows 0–7 consent state, 8–11 degraded severity, 12–15 budget decile.
   - Col 12: Environment — rows = room_occupancy + BT + KDE + Hyprland focus flags.
   - Col 13: Homage package ordinal — single row lit.
   - Cols 14–15: Tick-history scroll (shift-left each render tick, write current stance in col 15 row = stance ordinal).
2. `agents/studio_compositor/hardm_source.py` —
   - Remove `_signal_for_row`; replace with `_signal_for_cell(idx: int)`.
   - In `render_content`, iterate `for idx in range(TOTAL_CELLS)` reading the per-cell payload.
   - Add post-pass `_enforce_invariants()` implementing I1 (upper/lower density bound), I3 (no centred cluster), I5 (no global blink cadence — static guard, nothing to enforce per-tick).
   - Change render cadence: update `config/compositor-layouts/default.json` surface `hardm-dot-matrix-ur` → `rate_hz: 15.0`.
3. `tests/studio_compositor/test_hardm_invariants.py` — Hypothesis property tests:
   - Fuzz signal payloads over 256 cells with values in `[0, 1] ∪ {None, "stress", True, False}`.
   - For each fuzzed payload, render and assert: upper-half density / lower-half density ∈ [0.75, 1.33]; no ≥ 20-cell contiguous active region centred on col 7–8; no 2-cluster vertical pattern.
4. `config/compositor-layouts/default.json` — **no placement change in Phase 1.** Geometry stays at `(1600, 20, 256, 256)`. Phase 2 moves to the P3 band.

### 8.1 Justification

- **Smallest diff that addresses the operator's core concern.** "Used wrong" is the bigger complaint than "placed wrong"; fixing every cell to a distinct signal is the biggest legibility gain per line of code.
- **No placement risk.** Keeps the existing surface, HOMAGE contract, consent-safe fallback, and monetization envelope unchanged.
- **Unblocks Phase 2 without committing to P3 aesthetics.** Column-block layout translates directly to 120×12 when Phase 2 is ready.
- **Enforces anti-face invariants from Phase 1.** The governance-locked memory becomes executable (Hypothesis tests) rather than aspirational.
- **Demonstrably 256 independent channels.** When the operator next looks at HARDM, they see speech bands moving at 15 Hz alongside stimmung bars and MIDI pitch-class blinks — honest signal density on a grid, as the anti-anthropomorphization governance demands.
- **Deferred decisions are explicit.** Placement (Phase 2), reverie coupling (Phase 3), fast-family SHM (Phase 4), and monetization-gated expansion (Phase 5/6) all have concrete acceptance criteria.

One ship. No hedging. If Phase 1 lands and the operator still sees a tucked-over corner decoration, Phase 2 ships next.
