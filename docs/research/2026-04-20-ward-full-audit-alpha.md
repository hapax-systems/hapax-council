---
date: 2026-04-20
author: alpha (research subagent dispatched by cascade delta)
audience: alpha (execution)
register: scientific, neutral, post-live reckoning
status: audit checklist — one checkbox per per-ward per-dimension
         finding; alpha ticks live
related:
  - docs/superpowers/plans/2026-04-19-homage-completion-plan.md
  - docs/superpowers/plans/2026-04-20-programme-layer-plan.md
  - docs/research/2026-04-19-homage-aesthetic-reckoning.md  (vault)
  - agents/studio_compositor/ward_registry.py
  - agents/studio_compositor/ward_properties.py
  - agents/studio_compositor/homage/transitional_source.py
  - agents/studio_compositor/compositional_consumer.py
  - config/compositor-layouts/default.json
companion-audits:
  - task #171: broad wiring audit (audio / impingements / observability
    / systemd / SHM freshness). This ward audit goes DEEPER per ward on
    §1.4 SHM inputs and §5 prometheus; stays narrow on visual surface.
branch: hotfix/fallback-layout-assignment
operator-directive-load-bearing: |
  "do a full scale audit of every ward, assign to alpha: its
  appearance, placement, its behaviors, its functionality, its
  recruitment by director loop and content programming"
---

# Ward Full-Scale Audit (Post-Live Reckoning, alpha execution)

## §0. How to use this doc

This is a checklist, not a narrative. Every top-level section below
(§3–§18) is ONE ward. Every ward has six dimensions (Appearance,
Placement, Behaviors, Functionality, Director-Loop Recruitment,
Content-Programming Recruitment). Every dimension yields a small
cluster of TO-VERIFY-LIVE checkboxes. Alpha walks through each box,
executes the verification command(s), and ticks the result inline:

- `[x]` or `✅ verified against live /dev/video42 at <timestamp>`
- `[~]` or `⚠️ partial / degraded / unclear — detail`
- `[ ]` or `❌ broken — details + next-PR target`

Alpha does ONE commit per ward block completed, at the end of that
ward's section, titled `docs(audit): ward <id> post-live walk results`.
Cross-ward invariants (§19) and reverie substrate audit (§20) are two
more commits. Final commit is `docs(audit): ward audit complete,
execution queue drafted` and includes the §21 execution queue.

**Fixing while walking is FORBIDDEN in this pass.** This doc's
deliverable is an accurate map of the surface. Fixes happen in the
execution queue §21, each as its own PR, each with its own review
cycle. The sole exception: anything in the `live-egress / consent /
face-obscure` bucket — alpha stops the audit, pages the operator, and
takes emergency action per the face-obscure fail-closed protocol.

**Verification tooling assumed available:**

- `mpv v4l2:///dev/video42 --video-latency-hint=0 --no-audio` to watch
  the compositor output.
- `ffmpeg -i /dev/video42 -frames:v 1 /tmp/v42-$(date +%s).png` for
  pixel-level sampling.
- `jq` on SHM JSON files.
- `curl -s http://127.0.0.1:9482/metrics | grep hapax_homage_` for
  the prom pipeline.
- `stat --format=%Y <path>` for SHM freshness.
- `systemctl --user status studio-compositor` for service state.

**Coordinates note:** the layout JSON at
`config/compositor-layouts/default.json` is authored at 1920×1080.
The compositor rescales via `agents/studio_compositor/config.py::
LAYOUT_COORD_SCALE = OUTPUT_WIDTH / 1920.0` where
`OUTPUT_WIDTH = int(os.environ.get("HAPAX_COMPOSITOR_OUTPUT_WIDTH",
"1280"))`. Default live environment therefore scales every x/y/w/h
by 1280/1920 = 0.6667. Alpha applies that scale when sampling pixel
regions from the v4l2 output — a source authored at x=1260 y=20 lands
near x=840 y=13 on the 1280-wide render.

---

## §1. Workflow for alpha (top-down, section-by-section)

1. Open a live `mpv v4l2:///dev/video42` window on the side display.
2. `tail -F /dev/shm/hapax-compositor/homage-pending-transitions.json |
   jq .` in one terminal.
3. `watch -n 1 "jq 'keys' /dev/shm/hapax-compositor/ward-properties.json
   2>/dev/null"` in a second.
4. `curl -s http://127.0.0.1:9482/metrics | grep hapax_homage_ | head`
   in a third; refresh between wards.
5. For each ward §3–§18:
   a. Read the per-ward render class top-to-bottom.
   b. Sample the ward region from a fresh `/dev/video42` frame.
   c. Walk all six dimensions in order.
   d. Tick boxes, commit, move on.
6. Cross-ward invariants (§19) and Reverie substrate (§20) once all 16
   per-ward blocks are done.
7. Execution queue (§21) captures every ❌ finding as a numbered PR
   seed.

**Time budget:** ~10 minutes per ward × 16 wards ≈ 3 hours. Cross-ward
walk ~30 minutes. Reverie substrate ~15 minutes. Execution-queue
authorship ~20 minutes. Total ~4 hours wall-clock.

---

## §2. Ward-id index + quick-ref table

| # | ward_id | render class | file | natural w×h | surface id | pip/chrome region |
|---|---------|--------------|------|-------------|-------------|-------------------|
| 1 | `token_pole` | `TokenPoleCairoSource` | `agents/studio_compositor/token_pole.py:289` | 300×300 | `pip-ul` | pip upper-left |
| 2 | `hardm_dot_matrix` | `HardmDotMatrix` | `agents/studio_compositor/hardm_source.py:~400` | 256×256 | `hardm-dot-matrix-ur` | upper-right chrome (256 band) |
| 3 | `album` (aka album_overlay) | `AlbumOverlayCairoSource` | `agents/studio_compositor/album_overlay.py:236` | 400×520 | `pip-ll` | pip lower-left |
| 4 | `captions` | `CaptionsCairoSource` | `agents/studio_compositor/captions_source.py:118` | 1920×120 | `captions_strip` | bottom strip |
| 5 | `chat_ambient` | `ChatAmbientWard` (layout still points at `ChatKeywordLegendCairoSource` — B5 gap) | `agents/studio_compositor/chat_ambient_ward.py:177` | 560×40 | `chat-legend-right` | right chrome |
| 6 | `stance_indicator` | `StanceIndicatorCairoSource` | `agents/studio_compositor/legibility_sources.py:471` | 100×40 | `stance-indicator-tr` | upper-right chrome |
| 7 | `activity_header` | `ActivityHeaderCairoSource` | `agents/studio_compositor/legibility_sources.py:342` | 800×56 | `activity-header-top` | top strip |
| 8 | `grounding_provenance_ticker` | `GroundingProvenanceTickerCairoSource` | `agents/studio_compositor/legibility_sources.py:652` | 480×40 | `grounding-ticker-bl` | bottom-left chrome |
| 9 | `impingement_cascade` | `ImpingementCascadeCairoSource` | `agents/studio_compositor/hothouse_sources.py:229` | 480×360 | `impingement-cascade-midright` | mid-right |
| 10 | `recruitment_candidate_panel` | `RecruitmentCandidatePanelCairoSource` | `agents/studio_compositor/hothouse_sources.py:377` | 800×60 | `recruitment-candidate-top` | top band under activity header |
| 11 | `thinking_indicator` | `ThinkingIndicatorCairoSource` | `agents/studio_compositor/hothouse_sources.py:518` | 170×44 | `thinking-indicator-tr` | top-right chrome |
| 12 | `pressure_gauge` | `PressureGaugeCairoSource` | `agents/studio_compositor/hothouse_sources.py:608` | 300×52 | `pressure-gauge-ul` | upper-left chrome |
| 13 | `activity_variety_log` | `ActivityVarietyLogCairoSource` | `agents/studio_compositor/hothouse_sources.py:732` | 400×140 | `activity-variety-log-mid` | mid-centre ribbon |
| 14 | `whos_here` | `WhosHereCairoSource` | `agents/studio_compositor/hothouse_sources.py:863` | 230×46 | `whos-here-tr` | upper-right chrome |
| 15 | `stream_overlay` | `StreamOverlayCairoSource` | `agents/studio_compositor/stream_overlay.py:91` | 400×200 | `pip-lr` | pip lower-right |
| 16 | `research_marker_overlay` | `ResearchMarkerFrameSource` | `agents/studio_compositor/research_marker_overlay.py` | 1280×64 (conditional) | — (gated layer) | conditional banner |

**Registry source of truth:** `agents/studio_compositor/ward_registry.py::
populate_from_layout` (lines 86–118). Layout JSON sources land as
`WardCategory.CAIRO`; the registry is derived at compositor startup and
re-derived on layout swap.

**Shared base class:** every ward inherits from
`HomageTransitionalSource` (`agents/studio_compositor/homage/
transitional_source.py:69`), whose FSM is the choreographer-driven
`ABSENT → ENTERING → HOLD → EXITING` state machine. Note the 2026-04-18
hotfix at lines 90–110: `initial_state` now defaults to `HOLD`, not
`ABSENT`. Phase B3 of the homage-completion plan will drop the hotfix
and restore choreographer-driven entry dispatch; until then, `ABSENT →
ENTERING` transitions are NOT fired at startup and every ward in this
audit starts in `HOLD`.

---

## §3. Ward 1 — `token_pole`

**File(s):**
- Render class: `agents/studio_compositor/token_pole.py::TokenPoleCairoSource` lines 289–756
- Layout binding: `config/compositor-layouts/default.json` source id `token_pole` → surface id `pip-ul` (assignment lines 607–614; surface lines 262–280)
- Tests: `tests/studio_compositor/test_token_pole_emissive.py`,
  `tests/studio_compositor/test_token_pole_golden_image.py`,
  `tests/studio_compositor/test_token_pole_palette.py`
- Goldens:
  - `tests/studio_compositor/golden_images/wards/token_pole_300x300.png`
  - `tests/studio_compositor/golden_images/emphasis/token_pole_300x300.png`
  - `tests/studio_compositor/golden_images/token_pole_natural_300x300.png` (legacy, pre-emissive)

### 3.1 Appearance — spec vs observed

- [ ] **Palette:** renders in BitchX mIRC-16 + grey-punctuation skeleton. Limbs are 16-colour mIRC strokes, background is Gruvbox bg0. Sample pip-ul region (scaled: x≈13 y≈13 w≈200 h≈200 at 1280 output); dominant hue should be near-black + palette accent, NOT sepia.
- [ ] **Typography:** status row `>>> [TOKEN | <pole>:<value>/<threshold>]` in Px437 IBM VGA 8x16 via Pango. Compare glyph raster against `/usr/share/fonts/TTF/Px437_IBM_VGA_8x16.ttf`.
- [ ] **Emissive primitives:** Vitruvian figure present; token glyph at navel = centre dot (accent_yellow) + halo (accent_magenta α=0.45) + outer bloom (accent_yellow α=0.12). Reckoning §3 flags "smiley face" as pre-emissive; confirm smiley is GONE.
- [ ] **Shimmer:** limbs + navel glyph pulse at stance-indexed Hz (nominal 1.0, seeking 1.6, cautious 0.7, degraded 0.5, critical 2.4). 10-second capture; observe temporal alpha variance.
- [ ] **Signature artefacts:** on token tick, status row fires 200 ms inverse-flash (`topic-change` vocab). On explosion, `mode-change` flash on whole ward + 2 s `[+k pole crested]` row from `signature_artefacts`.
- [ ] **Emphasis border:** when `ward.highlight.token_pole` lands or `ward_emphasis: [token_pole]` fires, `glow_radius_px=14` + `border_pulse_hz=2.0` visible on pip-ul border. Force via synthetic structural-intent entry; confirm visual change within 200 ms.

### 3.2 Placement — layout geometry

- [ ] Surface id `pip-ul` exists: `jq '.surfaces[] | select(.id=="pip-ul")' config/compositor-layouts/default.json` → geometry `{x:20,y:20,w:300,h:300,z_order:10}`.
- [ ] Rescaled coords: x=20→≈13, y=20→≈13, w=300→≈200, h=300→≈200 at OUTPUT_WIDTH=1280.
- [ ] No overlap at z_order 10 with: `pip-ur` (z 10 too, but x 1260+), `pip-ll` (z 10, x 20 y 540 — separates vertically), `pressure-gauge-ul` (z 24, y 336 — sits below token_pole). Enumerate and confirm clean.
- [ ] Correct pip region per homage plan §1.2: pip-ul = "upper-left Vitruvian Man + token point-of-light". ✅ by layout.
- [ ] Anchored vs floating: ANCHORED. Ward does not DVD-bounce. Token glyph may orbit the navel inside the figure; limbs may shimmer in place.

### 3.3 Behaviors — FSM + transitions

- [ ] FSM: currently defaults to `HOLD` per the 2026-04-18 hotfix (`transitional_source.py:86`). B3 will revert. Live-check: `tail -20 /dev/shm/hapax-compositor/homage-pending-transitions.json | jq '.transitions[] | select(.source_id=="token_pole")'` — expect zero entries pre-B3.
- [ ] Entry transition: no-op pre-B3; B3 will make compositor startup dispatch `ticker-scroll-in` to token_pole, FSM advances ABSENT → ENTERING → HOLD. Baseline for B3: confirm zero entry transitions fire today.
- [ ] State-change flash: 200 ms inverse-flash on token tick. Force via a synthetic token-ledger entry at `/dev/shm/hapax-compositor/token-ledger.json`; observe flash.
- [ ] Breathing alpha at stance-indexed Hz: 1.0 Hz nominal. `jq '.stance' /dev/shm/hapax-stimmung/state.json` to get current stance; count alpha cycles in a 10-second capture; match expected Hz within ±0.1.
- [ ] Slide-in: N/A (token_pole is anchored, not scrolling). Signature artefact `[+k pole crested]` slides in on explosion.
- [ ] Netsplit-burst: only under `homage_rotation_mode=burst` (B4, not yet shipped). Note deferred.

### 3.4 Functionality — data inputs + degradation

- [ ] SHM inputs: `/dev/shm/hapax-compositor/token-ledger.json` (line 44). Also reads stance from stimmung for pulse rate (verify by grep within render path).
- [ ] Input freshness: token-ledger should update whenever poles change. `stat --format=%Y /dev/shm/hapax-compositor/token-ledger.json`; stale >5 minutes means ledger updater is dead (investigate separately per task #171).
- [ ] Missing-input graceful degradation: delete ledger temporarily (stop service first); ward should render fallback figure without crashing. Confirm "missing /dev/shm file" path is tolerant (already noted in render class docstring around line 641).
- [ ] Prom metrics: `hapax_homage_render_cadence_hz{ward="token_pole"}`, `hapax_homage_transition_total{ward="token_pole",...}`, `hapax_homage_emphasis_applied_total{ward="token_pole",...}`. Alpha: `curl :9482/metrics | grep 'token_pole'`.
- [ ] Ward-properties modulation: `jq '.wards.token_pole' /dev/shm/hapax-compositor/ward-properties.json`; when emphasised the envelope should be `glow_radius_px=14, border_pulse_hz=2.0, scale_bump_pct=0.06, alpha=1.0`.
- [ ] Consent + face-obscure: ward shows no operator-identified camera content. No consent surface risk.

### 3.5 Director-loop recruitment — intent_family → this ward

- [ ] Intent-family targets: `ward.highlight.token_pole`, `ward.highlight.token_pole.<modifier>` (per `dispatch_ward_highlight` at `compositional_consumer.py:547`), `overlay.emphasis.token_pole`, `structural_intent.ward_emphasis: [token_pole]`.
- [ ] Dispatch path: narrative-director writes `compositional_impingements[*].intent_family=ward.highlight.token_pole.<mod>` → `compositional_consumer.dispatch` at line 963 routes to `dispatch_ward_highlight` → `_apply_emphasis("token_pole", salience)` at line 1248 → `set_ward_properties("token_pole", merged, ttl_s)` at line 1294.
- [ ] Recent recruitment count: `tail -500 ~/hapax-state/stream-experiment/director-intent.jsonl | jq 'select(.compositional_impingements) | .compositional_impingements[] | select(.intent_family | startswith("ward.highlight.token_pole"))' | wc -l`. If 0, director has never nominated token_pole.
- [ ] Emphasis-applied metric: `curl :9482/metrics | grep 'hapax_homage_emphasis_applied_total.*ward="token_pole"'` — ≥1 if ever emphasised post-restart.
- [ ] Structural intent emphasis: `tail -20 ~/hapax-state/stream-experiment/director-intent.jsonl | jq '.structural_intent.ward_emphasis[]'`. Pre-B0 (blinding-defaults audit) this likely returns null / empty. Document the baseline.

### 3.6 Content-programming recruitment — per task #164

- [ ] Programme role: during `listening` programmes the token glyph reads as an ambient pulse; during `hothouse` programmes the full token ledger is legible. The ward is never HARD-GATED — programmes bias, never remove.
- [ ] Programme soft-prior: per `docs/superpowers/plans/2026-04-20-programme-layer-plan.md` §2, token_pole can be biased up/down as part of `constraint_envelope.visual_emphasis_weights`. Verify the pipeline receives this bias; the ward's emphasis probability should rise under token-centric programmes.
- [ ] Affordance-catalog registration: `hapax query 'ward.highlight.token_pole' --limit 5` should surface the token-pole emphasis capability with a Gibson-verb description. Reckoning §3 flags that ward.highlight capabilities are sparse in the `affordances` collection; if zero hits, this is a ❌ for the catalog, not the ward.
- [ ] Expand-not-replace: simulate a programme that de-prioritises token_pole; confirm the ward still fires when an impingement's salience beats the programme bias (token-tick at high salience must override a programme that nominally downweights token_pole).
- [ ] Hapax-authored vs vault-authored: `grep -R 'type: programme' ~/Documents/Personal/` should return zero matches; `grep -R 'type: ward-config' ~/Documents/Personal/` zero matches. Vault is read-only perception input for programmes.

---

## §4. Ward 2 — `hardm_dot_matrix`

**File(s):**
- Render class: `agents/studio_compositor/hardm_source.py::HardmDotMatrix` lines ~150–779 (render cells at ~621–739 — exemplar emissive pattern the rest of A2/A3/A4 crib from).
- Layout binding: source `hardm_dot_matrix` → surface `hardm-dot-matrix-ur` (surface lines 587–604; assignment lines 717–723).
- Tests: `tests/studio_compositor/test_hardm_source.py`,
  `tests/studio_compositor/test_hardm_anchoring.py`
- Goldens:
  - `tests/studio_compositor/golden_images/wards/hardm_dot_matrix_256x256.png`
  - `tests/studio_compositor/golden_images/emphasis/hardm_dot_matrix_256x256.png`

### 4.1 Appearance

- [ ] Palette: 16×16 grid of centre dot + halo cells in mIRC-16 palette against Gruvbox bg0. Should read as pointillism — no flat rectangles.
- [ ] Typography: no text in this ward (dot-matrix only). Confirm by visual inspection.
- [ ] Emissive primitives: centre dot + halo + outer-glow per cell. Scanline overlay via `paint_scanlines` (CRT raster hint). This is the A1 reference implementation; goldens should match within ±4 per channel.
- [ ] Shimmer: per-cell phase-offset shimmer at SHIMMER_HZ_DEFAULT. 10-second capture; observe temporal variation.
- [ ] Signature artefacts: cell signals from `/dev/shm/hapax-compositor/hardm-cell-signals.json` drive individual cell intensity. Voice emphasis (CPAL mid-utterance, B6) raises halo radius by 1.5× during HARDM-emphasised windows.
- [ ] Emphasis border: ward.highlight.hardm_dot_matrix lands a 14 px glow + 2 Hz border pulse.

### 4.2 Placement

- [ ] Surface id `hardm-dot-matrix-ur`: `{x:1600,y:20,w:256,h:256,z_order:28}` at 1920 authored scale. At 1280 output: x≈1067, y≈13, w≈171, h≈171.
- [ ] No overlap at z_order 28 with: `whos-here-tr` (z 26, x 1460 y 20), `thinking-indicator-tr` (z 26, x 1620 y 20), `stance-indicator-tr` (z 35, x 1800 y 24). HARDM z=28 sits above whos_here and thinking_indicator; confirm occlusion is intentional.
- [ ] Region: upper-right chrome (256-band). ✅ by layout.
- [ ] Anchored: fixed.

### 4.3 Behaviors

- [ ] FSM: currently HOLD (post-hotfix). B3 pending.
- [ ] Entry: no-op pre-B3.
- [ ] Cell-level flash: drive a synthetic cell signal with salience=1.0 at an edge cell; confirm that cell brightens.
- [ ] Breathing alpha: per-cell phase offsets + stance-indexed global pulse.
- [ ] Slide-in: N/A (cell-level).
- [ ] Netsplit-burst: B4 — halo radius 1.5× bump during burst.

### 4.4 Functionality

- [ ] SHM inputs: `/dev/shm/hapax-compositor/hardm-cell-signals.json` (publisher side unclear — audit separately per task #171); voice-state at `/dev/shm/hapax-compositor/voice-state.json`; HARDM emphasis at `/dev/shm/hapax-compositor/hardm-emphasis.json`; stimmung at `/dev/shm/hapax-stimmung/state.json`; operator-cue at `/dev/shm/hapax-director/operator-cue.json`.
- [ ] Input freshness: cell-signals should update per impingement; voice-state per CPAL event; emphasis per director tick; stimmung per stimmung loop.
- [ ] Missing-input: all inputs optional; ward degrades to uniform pulse baseline.
- [ ] Prom metrics: same six as token_pole, labeled `ward="hardm_dot_matrix"`.
- [ ] Ward-properties modulation: emphasis envelope should be visible on HARDM border during CPAL speech windows.
- [ ] Consent: no operator content.

### 4.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.hardm_dot_matrix.*`, `overlay.emphasis.hardm_dot_matrix`, `structural_intent.ward_emphasis`. HARDM + album are the current-baseline two wards that DO get emphasis (reckoning §3.4); verify.
- [ ] Dispatch path: same as token_pole.
- [ ] Recent recruitment count: `wc -l` the director-intent hits; HARDM should be high compared to other wards.
- [ ] Emphasis-applied metric: `curl :9482/metrics | grep 'ward="hardm_dot_matrix"'`; should be ≥1.
- [ ] Structural intent emphasis: `tail -20 director-intent.jsonl | jq '.structural_intent.ward_emphasis[]'`; pre-B0 may be empty.

### 4.6 Content-programming recruitment

- [ ] Programme role: HARDM is the cross-modal voice-coupling surface; during `spoken-hothouse` programmes it's dominant, during pure-listening programmes it's quiescent.
- [ ] Programme soft-prior: HARDM biases FX-chain preset family toward `neon` (B6) during emphasis — this is a cross-modal programme hook.
- [ ] Affordance-catalog: `ward.highlight.hardm_dot_matrix.*` entries in Qdrant.
- [ ] Expand-not-replace: HARDM still fires on voice activity even during programmes that downweight it.
- [ ] Hapax-authored: confirm no vault ward-config.

---

## §5. Ward 3 — `album` (album_overlay)

**File(s):**
- Render class: `agents/studio_compositor/album_overlay.py::AlbumOverlayCairoSource` lines 236–403
- Layout binding: source `album` → surface `pip-ll` (surface lines 299–315; assignment lines 622–629)
- Tests: `tests/studio_compositor/test_album_overlay_emissive.py`
- Goldens:
  - `tests/studio_compositor/golden_images/wards/album_overlay_300x450.png`
  - `tests/studio_compositor/golden_images/emphasis/album_overlay_300x450.png`
  - `tests/studio_compositor/golden_images/vinyl_platter_33rpm.png` (related)

### 5.1 Appearance

- [ ] Palette: cover quantised to mIRC-16 via `Image.quantize(palette=mIRC16_palette_image, dither=ORDERED)`. Reckoning §3.2 flagged the five legacy `_pip_fx_vintage/cold/neon/film/phosphor` variants as pre-emissive; confirm ALL five are gone and replaced by a single `_pip_fx_package(cr, w, h, pkg)`.
- [ ] Typography: splattribution above the cover in `package.typography.primary_font_family` (Px437 IBM VGA 8x16 14) via `text_render.render_text` (Pango). No `JetBrains Mono Bold 10` literal anywhere in the file.
- [ ] Emissive primitives: scanlines every 3 px in muted role, ordered-dither shadow in accent_magenta along bottom 25%, 2 px sharp border in domain accent.
- [ ] Shimmer: not per-cell; border pulses on ward emphasis.
- [ ] Signature artefacts: on track change, cover swaps via `ticker-scroll-in` (slide right-to-left 400 ms).
- [ ] Emphasis border: album + HARDM are the current baseline emphasis-recipients; 14 px glow + 2 Hz pulse should be visible on most ticks.

### 5.2 Placement

- [ ] Surface id `pip-ll`: `{x:20,y:540,w:400,h:520,z_order:10}` at 1920 scale → at 1280 out: x≈13, y≈360, w≈267, h≈347. Note: source declares `natural_w=400, natural_h=520` but the source JSON has `"natural_h": 520` and surface has `h: 520`. At rescale the h becomes 347 and the aspect stretches or letterboxes — verify the blit path preserves aspect.
- [ ] No overlap at z_order 10 with captions_strip (z 20, y 930 — below album so captions can cover the lower 40 px if album extends that far; album h=347 stops at y≈707, captions start at y≈620 at 1280 out ≈ y 620 — wait, 930×(1280/1920)=620, overlap y range [360,707] vs [620,693] = 73 px overlap). FLAG: potential visual overlap between album lower portion and captions strip at 1280 output — sample live to confirm.
- [ ] Region: pip lower-left ✅.
- [ ] Anchored: fixed; cover slides during `ticker-scroll-in` on track change.

### 5.3 Behaviors

- [ ] FSM: HOLD default (hotfix).
- [ ] Entry: on track change, `ticker-scroll-in`. Force a synthetic cover change via replacing `/dev/shm/hapax-compositor/album-cover.png`; observe slide.
- [ ] Flash: no per-tick flash; border pulses on emphasis only.
- [ ] Breathing alpha: N/A on cover itself; border pulses.
- [ ] Slide-in: 400 ms right-to-left on track change. Confirm duration via frame-count in v4l2 capture.
- [ ] Netsplit-burst: B4.

### 5.4 Functionality

- [ ] SHM inputs: `/dev/shm/hapax-compositor/album-cover.png` (line 43), `/dev/shm/hapax-compositor/music-attribution.txt` (line 44).
- [ ] Input freshness: updated by the music-surfacing agent; `stat --format=%Y` both files.
- [ ] Missing-input: fallback to dark rectangle with no attribution; don't crash.
- [ ] Prom metrics: 6 standard, ward="album".
- [ ] Ward-properties modulation: active baseline.
- [ ] Consent: music attribution may surface third-party names. No operator content.

### 5.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.album.*`, `overlay.emphasis.album`, `structural_intent.ward_emphasis`.
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: high (album + HARDM are the two recipients today).
- [ ] Emphasis-applied metric: ≥1.
- [ ] Structural intent emphasis: check baseline.

### 5.6 Content-programming recruitment

- [ ] Programme role: during `music-foregrounded` programmes album is dominant; during `discourse-foregrounded` programmes it sits as ambient chrome.
- [ ] Programme soft-prior: constraint envelope can bias album visual weight.
- [ ] Affordance-catalog: `ward.highlight.album.*` entries.
- [ ] Expand-not-replace: album still appears even in discourse programmes (at lower salience).
- [ ] Hapax-authored: confirm.

---

## §6. Ward 4 — `captions`

**File(s):**
- Render class: `agents/studio_compositor/captions_source.py::CaptionsCairoSource` lines 118–220
- Layout binding: source `captions` → surface `captions_strip` (surface lines 335–352; assignment lines 668–674)
- Tests: `tests/studio_compositor/test_captions_in_default_layout.py`,
  `test_captions_pango.py`,
  `test_captions_source.py`
- Goldens:
  - `tests/studio_compositor/golden_images/wards/captions_1280x80.png`
  - `tests/studio_compositor/golden_images/emphasis/captions_1280x80.png`

### 6.1 Appearance

- [ ] Palette: Px437 in content-colour role on semi-transparent dark band. No colour explosion.
- [ ] Typography: `STYLE_SCIENTIFIC.font_description="Px437 IBM VGA 8x16 22"`, `STYLE_PUBLIC.font_description="Px437 IBM VGA 8x16 36"`. Module-level probe at lines 75–90 emits a loud WARN if Px437 missing. Alpha: `journalctl --user -u studio-compositor --since "1 hour ago" | grep "Px437"` — should be empty.
- [ ] Emissive primitives: none (captions are text). STT line does 200 ms crossfade on line change.
- [ ] Shimmer: none.
- [ ] Signature artefacts: N/A.
- [ ] Emphasis border: 14 px glow + 2 Hz pulse when emphasised.

### 6.2 Placement

- [ ] Surface id `captions_strip`: `{x:40,y:930,w:1840,h:110,z_order:20}` at 1920 → at 1280 out: x≈27, y≈620, w≈1227, h≈73.
- [ ] Source params: `natural_w=1920, natural_h=120` (line 130+ area). Captions natural size is larger than surface; the blit-scaled path downscales to surface rect. Confirm font size stays readable at the scaled rect.
- [ ] z_order 20 above activity_variety_log (z 24? wait, activity_variety_log is z=24, captions z=20 → captions BELOW activity_variety_log). Double-check layout z ordering: higher z = above; captions at 20 sits below activity_variety_log (24). But captions y=620, activity_variety_log y≈360 — no geometric overlap. OK.
- [ ] Region: bottom strip ✅.
- [ ] Anchored: fixed.

### 6.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: N/A; STT line does 200 ms crossfade.
- [ ] Breathing alpha: NONE — captions must remain maximally legible. Any breathing alpha here is a bug.
- [ ] Slide-in: caption lines crossfade; no slide.
- [ ] Netsplit-burst: should NOT clear captions — captions are consent-essential.

### 6.4 Functionality

- [ ] SHM inputs: `/dev/shm/hapax-daimonion/stt-recent.txt` (line 36). Single source.
- [ ] Input freshness: updated per STT emission.
- [ ] Missing-input: show empty band with no text; must not crash.
- [ ] Prom metrics: standard six.
- [ ] Ward-properties modulation: emphasis envelope applied to border.
- [ ] Consent: captions REVEAL operator speech content. Consent check: captions are governed by the audio-capture consent contract, not the face-obscure path. Verify STT line display honours the consent state cached in `shared/consent.py`. If the operator has NOT consented to live captions in the current session, the strip should either be empty or show `[consent pending]`.

### 6.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.captions`, `overlay.emphasis.captions`.
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: check.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: check.

### 6.6 Content-programming recruitment

- [ ] Programme role: captions are a constant — active in every programme; programme modulates style (scientific vs public) via a working-mode bias, not by gating captions off.
- [ ] Programme soft-prior: visibility weight can vary; never zeroed.
- [ ] Affordance-catalog: `ward.highlight.captions` entry.
- [ ] Expand-not-replace: captions always present when consent is active.
- [ ] Hapax-authored: confirm.

---

## §7. Ward 5 — `chat_ambient`

**File(s):**
- Render class: `agents/studio_compositor/chat_ambient_ward.py::ChatAmbientWard` lines 177–339 (spec-authored target); legacy
  `agents/studio_compositor/legibility_sources.py::ChatKeywordLegendCairoSource` lines 557+ still bound by default.json until Phase B5 of homage-completion-plan ships.
- Layout binding: source `chat_ambient` → surface `chat-legend-right` (assignment lines 653–660; surface lines 443–460). The source params carry `"class_name": "ChatAmbientWard"` — inspect live to confirm layout JSON has been updated (reckoning §3.5 flagged the gap).
- Tests: none dedicated yet (listed as Phase B5 deliverable).
- Goldens:
  - `tests/studio_compositor/golden_images/wards/chat_ambient_800x120.png`
  - `tests/studio_compositor/golden_images/emphasis/chat_ambient_800x120.png`

### 7.1 Appearance

- [ ] Palette: aggregate-only cells in mIRC-16. `[Users(#hapax:1/N)]`, `[Mode +v +H]`, rate-gauge blocks in CP437 half-block emissive cells.
- [ ] Typography: Px437 via `text_render.render_text`. NO direct `cr.show_text` in `chat_ambient_ward.py`.
- [ ] Emissive primitives: rate-gauge cells as centre dot + halo.
- [ ] Shimmer: per-cell at SHIMMER_HZ_DEFAULT.
- [ ] Signature artefacts: none beyond the BitchX header grammar.
- [ ] Emphasis border: standard.

### 7.2 Placement

- [ ] Surface id `chat-legend-right`: `{x:1760,y:400,w:160,h:400,z_order:20}` at 1920 → x≈1173, y≈267, w≈107, h≈267 at 1280 out. Note: source natural_w=560, natural_h=40 — massive aspect mismatch to a 160×400 region (vertical strip vs horizontal strip). FLAG: this is either a layout authoring bug or the ward is intended to render rotated 90°. Alpha: sample the region live; if the cells are horizontal across a vertical strip, the layout binding is wrong.
- [ ] No overlap at z 20 with: impingement-cascade-midright (z 24, x 1260 y 400 w 480 h 360 — OVERLAP x range [1260,1740] and chat_ambient at x 1760 — no geometric overlap (they abut). OK.
- [ ] Region: right chrome ✅.
- [ ] Anchored: fixed.

### 7.3 Behaviors

- [ ] FSM: HOLD default.
- [ ] Entry: no-op pre-B3; after B3, `ticker-scroll-in` on startup.
- [ ] Flash: on mode-change (ward-mode or chat-mode), 200 ms inverse-flash.
- [ ] Breathing alpha: cells breathe at 0.3 Hz.
- [ ] Slide-in: new rate-gauge blocks enter via `join-message` when chat activity spikes.
- [ ] Netsplit-burst: B4.

### 7.4 Functionality

- [ ] SHM inputs: inspect `chat_ambient_ward.py` render() body — likely reads chat state from `/dev/shm/hapax-compositor/chat-state.json` or similar; the ward is aggregate-only so it must NOT persist per-author state. Confirm no author names appear.
- [ ] Input freshness: per chat-signal cadence.
- [ ] Missing-input: render default `[Users(#hapax:1/0)] [Mode +v +H]` no-op state.
- [ ] Prom metrics: standard six.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: aggregate-only enforced. No per-author state anywhere in render path (caplog test should pin this).

### 7.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.chat_ambient`, `overlay.emphasis.chat_ambient`.
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: check.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: check.

### 7.6 Content-programming recruitment

- [ ] Programme role: chat-aware programmes bias this ward up; focus-mode programmes keep it as low chrome.
- [ ] Programme soft-prior: visibility weight.
- [ ] Affordance-catalog: `ward.highlight.chat_ambient`.
- [ ] Expand-not-replace: always present, biased by programme.
- [ ] Hapax-authored: confirm.

---

## §8. Ward 6 — `stance_indicator`

**File(s):**
- Render class: `agents/studio_compositor/legibility_sources.py::StanceIndicatorCairoSource` lines 471–556
- Layout binding: source `stance_indicator` → surface `stance-indicator-tr` (surface lines 425–442; assignment lines 645–652)
- Tests: `tests/studio_compositor/test_ward_render_scope.py` (indirectly)
- Goldens:
  - `tests/studio_compositor/golden_images/wards/stance_indicator_100x40.png`
  - `tests/studio_compositor/golden_images/emphasis/stance_indicator_100x40.png`

### 8.1 Appearance

- [ ] Palette: `[+H STANCE]` with brackets + `+H` in muted role, stance label in stance role colour.
- [ ] Typography: Px437. No direct `cr.show_text` after A3.
- [ ] Emissive primitives: brackets + label glyphs as point-of-light.
- [ ] Shimmer: stance-indexed pulse on label glyphs.
- [ ] Signature artefacts: on stance change, 200 ms inverse-flash on whole ward.
- [ ] Emphasis border: standard.

### 8.2 Placement

- [ ] Surface id `stance-indicator-tr`: `{x:1800,y:24,w:100,h:40,z_order:35}`. At 1280 out: x≈1200, y≈16, w≈67, h≈27.
- [ ] z=35 is the highest chrome z-order — stance indicator sits above everything else in the top-right cluster. Confirm occlusion order: stance above hardm (28), whos_here (26), thinking_indicator (26).
- [ ] Region: upper-right chrome ✅.
- [ ] Anchored: fixed.

### 8.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: 200 ms inverse-flash on stance change. Force via writing a new stance to `/dev/shm/hapax-stimmung/state.json`; observe.
- [ ] Breathing alpha: stance-indexed (1.0 Hz nominal, etc.).
- [ ] Slide-in: N/A.
- [ ] Netsplit-burst: stance_indicator should NOT be cleared by netsplit — it's a persistent-context ward.

### 8.4 Functionality

- [ ] SHM inputs: `/dev/shm/hapax-stimmung/state.json` for current stance.
- [ ] Input freshness: per stimmung-loop cadence.
- [ ] Missing-input: render `[+H ?]` fallback.
- [ ] Prom metrics: standard.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: no operator content.

### 8.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.stance_indicator` (rare — stance is usually a passive display, not an emphasis target).
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: likely low.
- [ ] Emphasis-applied metric: may be 0 (document baseline).
- [ ] Structural intent emphasis: check.

### 8.6 Content-programming recruitment

- [ ] Programme role: always present; programme doesn't vary its emphasis much.
- [ ] Programme soft-prior: low variability.
- [ ] Affordance-catalog: `ward.highlight.stance_indicator` may be absent (low priority to author).
- [ ] Expand-not-replace: always present.
- [ ] Hapax-authored: confirm.

---

## §9. Ward 7 — `activity_header`

**File(s):**
- Render class: `agents/studio_compositor/legibility_sources.py::ActivityHeaderCairoSource` lines 342–470
- Layout binding: source `activity_header` → surface `activity-header-top` (surface lines 407–424; assignment lines 637–644)
- Tests: `tests/studio_compositor/test_activity_override.py`,
  `test_activity_scoring.py`
- Goldens:
  - `tests/studio_compositor/golden_images/wards/activity_header_800x56.png`
  - `tests/studio_compositor/golden_images/emphasis/activity_header_800x56.png`

### 9.1 Appearance

- [ ] Palette: `>>> [ACTIVITY | gloss] :: [ROTATION|<mode>]` in Px437. Rotation token coloured by mode: steady=muted, deliberate=accent_cyan, rapid=accent_yellow, burst=accent_red.
- [ ] Typography: Px437 via `text_render`. Brackets + chevrons as `paint_emissive_glyph`, gloss text via Pango at 14 px.
- [ ] Emissive primitives: chevron `>>>` each a centre-dot + halo glyph; brackets likewise. Gloss text is Pango-rendered.
- [ ] Shimmer: chevron glyphs shimmer at stance-indexed Hz.
- [ ] Signature artefacts: on activity change, whole ward inverse-flashes for 200 ms (`mode-change` vocab).
- [ ] Emphasis border: standard.

### 9.2 Placement

- [ ] Surface `activity-header-top`: `{x:560,y:16,w:800,h:56,z_order:30}` at 1920 → x≈373, y≈11, w≈533, h≈37 at 1280 out.
- [ ] z=30 is above captions (20) and most mid-strip wards. Activity header dominates the top-centre band.
- [ ] Region: top strip ✅.
- [ ] Anchored: fixed.

### 9.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: 200 ms inverse-flash on activity change.
- [ ] Breathing alpha: chevrons pulse.
- [ ] Slide-in: N/A for the header itself; gloss text can crossfade on activity change (200 ms).
- [ ] Netsplit-burst: should NOT clear activity_header — it's persistent context.

### 9.4 Functionality

- [ ] SHM inputs: `/dev/shm/hapax-director/narrative-state.json`, `/dev/shm/hapax-director/narrative-latest-intent.json`, `/dev/shm/hapax-director/narrative-structural-intent.json` (for rotation_mode display); also `/dev/shm/hapax-structural/intent.json` (slow structural tier).
- [ ] Input freshness: `stat --format=%Y` each. The blinding-defaults audit flagged narrative-structural-intent.json as hours-stale — document baseline.
- [ ] Missing-input: render `>>> [ACTIVITY | —]` fallback.
- [ ] Prom metrics: standard.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: activity gloss could leak content — verify the gloss is derived from narrative labels, not raw transcript.

### 9.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.activity_header` (rare — header is passive).
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: likely low.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: low.

### 9.6 Content-programming recruitment

- [ ] Programme role: header glosses the programme boundary too — at programme transitions, the ward's gloss updates to reflect the new programme's activity.
- [ ] Programme soft-prior: rotation-mode value comes from the structural tier.
- [ ] Affordance-catalog: `ward.highlight.activity_header` likely absent — document.
- [ ] Expand-not-replace: always present.
- [ ] Hapax-authored: confirm.

---

## §10. Ward 8 — `grounding_provenance_ticker`

**File(s):**
- Render class: `agents/studio_compositor/legibility_sources.py::GroundingProvenanceTickerCairoSource` lines 652–864
- Layout binding: source `grounding_provenance_ticker` → surface `grounding-ticker-bl` (surface lines 461–478; assignment lines 661–667)
- Tests: (covered by the visual-regression + palette tests)
- Goldens:
  - `tests/studio_compositor/golden_images/wards/grounding_provenance_ticker_480x40.png`
  - `tests/studio_compositor/golden_images/emphasis/grounding_provenance_ticker_480x40.png`

### 10.1 Appearance

- [ ] Palette: `* <signal>` rows, `*` as 3-px centre dot in muted role, signal names in bright role.
- [ ] Typography: Px437 via Pango.
- [ ] Emissive primitives: dots per row + halo.
- [ ] Shimmer: per-row phase-offset.
- [ ] Signature artefacts: each new grounding row enters via `join-message` slide-in.
- [ ] Emphasis border: standard.

### 10.2 Placement

- [ ] Surface `grounding-ticker-bl`: `{x:16,y:900,w:480,h:40,z_order:22}` at 1920 → x≈11, y≈600, w≈320, h≈27 at 1280 out.
- [ ] z=22: sits above captions (20) in the bottom-left. No visual overlap with captions y=620 — grounding ticker ends at y=627.
- [ ] Region: bottom-left chrome ✅.
- [ ] Anchored: fixed.

### 10.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: none.
- [ ] Breathing alpha: empty-state breathes at 0.3 Hz with `* (ungrounded)` text.
- [ ] Slide-in: new rows `join-message` from left.
- [ ] Netsplit-burst: may clear the ticker; repopulate from grounding log.

### 10.4 Functionality

- [ ] SHM inputs: grounding provenance log (exact SHM path inspect in render class — likely `/dev/shm/hapax-director/grounding-provenance.jsonl` or similar).
- [ ] Input freshness: per grounding event.
- [ ] Missing-input: `* (ungrounded)` fallback.
- [ ] Prom metrics: standard.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: grounding signals are non-content; safe.

### 10.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.grounding_provenance_ticker` (rare).
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: low.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: low.

### 10.6 Content-programming recruitment

- [ ] Programme role: research programmes bias up (should be dominant); music programmes bias down.
- [ ] Programme soft-prior: visibility weight.
- [ ] Affordance-catalog: `ward.highlight.grounding_provenance_ticker`.
- [ ] Expand-not-replace: always present.
- [ ] Hapax-authored: confirm.

---

## §11. Ward 9 — `impingement_cascade`

**File(s):**
- Render class: `agents/studio_compositor/hothouse_sources.py::ImpingementCascadeCairoSource` lines 229–376
- Layout binding: source `impingement_cascade` → surface `impingement-cascade-midright` (surface lines 479–496; assignment lines 675–681)
- Tests: covered by `test_homage_phase_12.py`, `test_homage_observability.py`
- Goldens:
  - `tests/studio_compositor/golden_images/wards/impingement_cascade_480x360.png`
  - `tests/studio_compositor/golden_images/emphasis/impingement_cascade_480x360.png`

### 11.1 Appearance

- [ ] Palette: `* <id> [salience|<bar>|family|<accent>]` rows. Each row's accent colour interpolated from family role.
- [ ] Typography: Px437 for IDs; accents rendered via `paint_emissive_point`.
- [ ] Emissive primitives: per-row centre dot + salience bar of 8 emissive cells + family-accent point.
- [ ] Shimmer: per-cell within salience bar.
- [ ] Signature artefacts: new rows enter via `join-message` (slide-in from left with ghost trail, 200 ms). Old rows decay alpha 1/lifetime over 5 s.
- [ ] Emphasis border: standard.

### 11.2 Placement

- [ ] Surface `impingement-cascade-midright`: `{x:1260,y:400,w:480,h:360,z_order:24}` at 1920 → x≈840, y≈267, w≈320, h≈240 at 1280 out.
- [ ] z=24 sits above captions (20) but below HARDM (28). Geometric: HARDM y≤276 + h=256 ends at y=532 — no overlap with impingement_cascade starting y=267 at 1280 out? Actually hardm-dot-matrix-ur at 1920 y=20 → 1280 y=13, h=171, ends y=184 → clear separation from impingement at y=267.
- [ ] Region: mid-right ✅.
- [ ] Anchored: fixed; rows slide within the region.

### 11.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: none on the ward; per-row ghost-trail instead.
- [ ] Breathing alpha: per-row fade-over-lifetime.
- [ ] Slide-in: 200 ms join-message per new row.
- [ ] Netsplit-burst: B4 — clears all rows, re-populates over 600 ms.

### 11.4 Functionality

- [ ] SHM inputs: `/dev/shm/hapax-dmn/impingements.jsonl` (read-only; daimonion writes). Inspect render class for exact path.
- [ ] Input freshness: per impingement (high-frequency).
- [ ] Missing-input: render empty frame with no rows; must not crash.
- [ ] Prom metrics: standard + per-row counts.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: impingement IDs are internal signal names; safe.

### 11.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.impingement_cascade` (rare — cascade is self-driving).
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: likely low.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: low.

### 11.6 Content-programming recruitment

- [ ] Programme role: hothouse programmes bias up; quiet-work programmes bias down.
- [ ] Programme soft-prior: visibility weight + row-density cap.
- [ ] Affordance-catalog: `ward.highlight.impingement_cascade`.
- [ ] Expand-not-replace: always present.
- [ ] Hapax-authored: confirm.

---

## §12. Ward 10 — `recruitment_candidate_panel`

**File(s):**
- Render class: `agents/studio_compositor/hothouse_sources.py::RecruitmentCandidatePanelCairoSource` lines 377–517
- Layout binding: source `recruitment_candidate_panel` → surface `recruitment-candidate-top` (surface lines 497–514; assignment lines 682–688)
- Tests: covered by hothouse test suite
- Goldens:
  - `tests/studio_compositor/golden_images/wards/recruitment_candidate_panel_800x60.png`
  - `tests/studio_compositor/golden_images/emphasis/recruitment_candidate_panel_800x60.png`

### 12.1 Appearance

- [ ] Palette: three cells, each: capability name in Px437 + emissive halo in family accent + salience-bar of emissive points.
- [ ] Typography: Px437 via Pango.
- [ ] Emissive primitives: per-cell halo + bar cells.
- [ ] Shimmer: per-cell stance-indexed.
- [ ] Signature artefacts: entry is `ticker-scroll-in`.
- [ ] Emphasis border: standard.

### 12.2 Placement

- [ ] Surface `recruitment-candidate-top`: `{x:560,y:80,w:800,h:60,z_order:24}` at 1920 → x≈373, y≈53, w≈533, h≈40 at 1280 out.
- [ ] z=24; sits just under activity_header (z=30 at y=11 h=37), no geometric overlap at 1280 out (activity ends y=48, recruitment starts y=53).
- [ ] Region: top band under activity_header ✅.
- [ ] Anchored: fixed; cells scroll within.

### 12.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: none on the ward.
- [ ] Breathing alpha: per-cell.
- [ ] Slide-in: new recruitment cells scroll in from right, oldest exits left.
- [ ] Netsplit-burst: B4.

### 12.4 Functionality

- [ ] SHM inputs: `/dev/shm/hapax-compositor/recent-recruitment.json` (line 76 of hothouse_sources.py).
- [ ] Input freshness: per recruitment event.
- [ ] Missing-input: empty panel.
- [ ] Prom metrics: standard.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: capability names are public; safe.

### 12.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.recruitment_candidate_panel` (rare).
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: likely low.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: low.

### 12.6 Content-programming recruitment

- [ ] Programme role: introspective/capability-demo programmes bias up; everyday programmes bias down.
- [ ] Programme soft-prior: visibility weight.
- [ ] Affordance-catalog: `ward.highlight.recruitment_candidate_panel`.
- [ ] Expand-not-replace: always present.
- [ ] Hapax-authored: confirm.

---

## §13. Ward 11 — `thinking_indicator`

**File(s):**
- Render class: `agents/studio_compositor/hothouse_sources.py::ThinkingIndicatorCairoSource` lines 518–607
- Layout binding: source `thinking_indicator` → surface `thinking-indicator-tr` (surface lines 515–532; assignment lines 689–695)
- Tests: covered by hothouse test suite
- Goldens:
  - `tests/studio_compositor/golden_images/wards/thinking_indicator_170x44.png`
  - `tests/studio_compositor/golden_images/emphasis/thinking_indicator_170x44.png`

### 13.1 Appearance

- [ ] Palette: pulsing point-of-light at the left edge; when LLM mid-flight, `[thinking...]` Px437 label fades in beside it.
- [ ] Typography: Px437.
- [ ] Emissive primitives: breathing centre dot + halo.
- [ ] Shimmer: stance-indexed Hz; amplitude amplifies when LLM in flight.
- [ ] Signature artefacts: none.
- [ ] Emphasis border: standard.

### 13.2 Placement

- [ ] Surface `thinking-indicator-tr`: `{x:1620,y:20,w:170,h:44,z_order:26}` at 1920 → x≈1080, y≈13, w≈113, h≈29 at 1280 out.
- [ ] z=26. Overlap with: hardm (z=28 at x 1067 → OVERLAP x range [1080,1193] vs HARDM [1067,1238]). CRITICAL: thinking_indicator sits under HARDM (z 28 > 26). HARDM occludes thinking_indicator. This may be intentional (thinking indicator only visible when HARDM is not present), OR it may be a layout bug. FLAG for operator review.
- [ ] Region: upper-right chrome.
- [ ] Anchored: fixed.

### 13.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: none.
- [ ] Breathing alpha: stance-indexed Hz; increases amplitude when LLM in flight.
- [ ] Slide-in: label `[thinking...]` fades in when LLM in flight.
- [ ] Netsplit-burst: should NOT clear — thinking indicator is live-state.

### 13.4 Functionality

- [ ] SHM inputs: `/dev/shm/hapax-director/llm-in-flight.json` (line 71 of hothouse_sources.py), stimmung for stance.
- [ ] Input freshness: per LLM call; stale >30 s means the flight tracker is stuck.
- [ ] Missing-input: pulse baseline at nominal Hz.
- [ ] Prom metrics: standard + maybe an `llm_in_flight` gauge.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: safe.

### 13.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.thinking_indicator` (rare — thinking is passive signal).
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: likely low.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: low.

### 13.6 Content-programming recruitment

- [ ] Programme role: listening/quiet programmes should see this quiescent; hothouse programmes see it frequently lit.
- [ ] Programme soft-prior: visibility weight.
- [ ] Affordance-catalog: `ward.highlight.thinking_indicator`.
- [ ] Expand-not-replace: always present.
- [ ] Hapax-authored: confirm.

---

## §14. Ward 12 — `pressure_gauge`

**File(s):**
- Render class: `agents/studio_compositor/hothouse_sources.py::PressureGaugeCairoSource` lines 608–731
- Layout binding: source `pressure_gauge` → surface `pressure-gauge-ul` (surface lines 533–550; assignment lines 696–702)
- Tests: covered by hothouse test suite
- Goldens:
  - `tests/studio_compositor/golden_images/wards/pressure_gauge_300x52.png`
  - `tests/studio_compositor/golden_images/emphasis/pressure_gauge_300x52.png`

### 14.1 Appearance

- [ ] Palette: 32 CP437 half-block cells, hue interpolated accent_green → accent_yellow → accent_red by fill level. Label `>>> [PRESSURE | <count>/<saturation%>]` in Px437 above cells.
- [ ] Typography: Px437.
- [ ] Emissive primitives: per-cell centre dot + halo; flat red bar MUST be gone.
- [ ] Shimmer: per-cell phase offsets.
- [ ] Signature artefacts: none.
- [ ] Emphasis border: standard.

### 14.2 Placement

- [ ] Surface `pressure-gauge-ul`: `{x:20,y:336,w:300,h:52,z_order:24}` at 1920 → x≈13, y≈224, w≈200, h≈35 at 1280 out.
- [ ] z=24 sits above pip-ul (z 10 at y≈13 h≈200, ends y=213). No overlap — pressure_gauge starts y=224.
- [ ] Region: upper-left chrome ✅ (just below token_pole).
- [ ] Anchored: fixed.

### 14.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: on cell-fill crossing threshold, per-cell flash.
- [ ] Breathing alpha: per-cell shimmer.
- [ ] Slide-in: N/A.
- [ ] Netsplit-burst: should NOT clear — pressure is persistent state.

### 14.4 Functionality

- [ ] SHM inputs: stimmung pressure field at `/dev/shm/hapax-stimmung/state.json`, possibly a dedicated `/dev/shm/hapax-dmn/pressure.json`.
- [ ] Input freshness: per stimmung tick.
- [ ] Missing-input: empty cells.
- [ ] Prom metrics: standard.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: safe.

### 14.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.pressure_gauge`.
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: likely low.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: low.

### 14.6 Content-programming recruitment

- [ ] Programme role: hothouse programmes elevate this to dominant; other programmes keep it as ambient.
- [ ] Programme soft-prior: visibility weight.
- [ ] Affordance-catalog: `ward.highlight.pressure_gauge`.
- [ ] Expand-not-replace: always present.
- [ ] Hapax-authored: confirm.

---

## §15. Ward 13 — `activity_variety_log`

**File(s):**
- Render class: `agents/studio_compositor/hothouse_sources.py::ActivityVarietyLogCairoSource` lines 732–862
- Layout binding: source `activity_variety_log` → surface `activity-variety-log-mid` (surface lines 551–568; assignment lines 703–709)
- Tests: covered
- Goldens:
  - `tests/studio_compositor/golden_images/wards/activity_variety_log_400x140.png`
  - `tests/studio_compositor/golden_images/emphasis/activity_variety_log_400x140.png`

### 15.1 Appearance

- [ ] Palette: 6 cells (oldest leftmost), each emissive name+intensity.
- [ ] Typography: Px437.
- [ ] Emissive primitives: per-cell point-of-light glyphs.
- [ ] Shimmer: per-cell.
- [ ] Signature artefacts: new entries `ticker-scroll-in` from right; oldest `ticker-scroll-out` left.
- [ ] Emphasis border: standard.

### 15.2 Placement

- [ ] Surface `activity-variety-log-mid`: `{x:440,y:540,w:400,h:140,z_order:24}` at 1920 → x≈293, y≈360, w≈267, h≈93 at 1280 out.
- [ ] z=24. Overlap check: album at pip-ll (x 13 y 360 w 267 h 347 at 1280 out) — activity_variety starts x=293, album ends x=280. No overlap, clean separation.
- [ ] Region: mid-centre ribbon ✅.
- [ ] Anchored: fixed; cells scroll within.

### 15.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: on new activity entry, 200 ms flash on new cell.
- [ ] Breathing alpha: per-cell.
- [ ] Slide-in: ticker-scroll-in from right on new entry.
- [ ] Netsplit-burst: B4.

### 15.4 Functionality

- [ ] SHM inputs: activity log SHM path (inspect render class — likely `/dev/shm/hapax-dmn/recent-activity.json`).
- [ ] Input freshness: per activity event.
- [ ] Missing-input: empty cells.
- [ ] Prom metrics: standard.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: activity names are internal labels; safe.

### 15.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.activity_variety_log`.
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: likely low.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: low.

### 15.6 Content-programming recruitment

- [ ] Programme role: introspective programmes bias up; everyday programmes bias down.
- [ ] Programme soft-prior: visibility weight.
- [ ] Affordance-catalog: `ward.highlight.activity_variety_log`.
- [ ] Expand-not-replace: always present.
- [ ] Hapax-authored: confirm.

---

## §16. Ward 14 — `whos_here`

**File(s):**
- Render class: `agents/studio_compositor/hothouse_sources.py::WhosHereCairoSource` lines 863–997
- Layout binding: source `whos_here` → surface `whos-here-tr` (surface lines 569–586; assignment lines 710–716)
- Tests: covered
- Goldens:
  - `tests/studio_compositor/golden_images/wards/whos_here_230x46.png`
  - `tests/studio_compositor/golden_images/emphasis/whos_here_230x46.png`

### 16.1 Appearance

- [ ] Palette: `[hapax:1/N]` in Px437 with `1` in stance role colour, `N` in audience role colour.
- [ ] Typography: Px437.
- [ ] Emissive primitives: `1` and `N` as point-of-light glyphs.
- [ ] Shimmer: stance-indexed on `1`.
- [ ] Signature artefacts: on N change, 200 ms flash on the N glyph.
- [ ] Emphasis border: standard.

### 16.2 Placement

- [ ] Surface `whos-here-tr`: `{x:1460,y:20,w:150,h:46,z_order:26}` at 1920 → x≈973, y≈13, w≈100, h≈31 at 1280 out.
- [ ] z=26. Overlap check: thinking_indicator x=1080 (overlap check with whos_here ending x=1073 — no overlap). HARDM at x 1067 y 13 → abuts whos_here's right edge at x=1073. Layout is tight; verify no 1-px glyph bleed at runtime.
- [ ] Region: upper-right chrome ✅.
- [ ] Anchored: fixed.

### 16.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: on N change.
- [ ] Breathing alpha: on `1`.
- [ ] Slide-in: N/A.
- [ ] Netsplit-burst: should NOT clear — who's-here is consent-essential context.

### 16.4 Functionality

- [ ] SHM inputs: `/dev/shm/hapax-compositor/youtube-viewer-count.txt` (line 77 of hothouse_sources.py). Aggregate-only count — no author names.
- [ ] Input freshness: per viewer-count pump.
- [ ] Missing-input: `[hapax:1/?]` fallback.
- [ ] Prom metrics: standard.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: aggregate-only; verify no author names anywhere in render path.

### 16.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.whos_here` (rare).
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: likely low.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: low.

### 16.6 Content-programming recruitment

- [ ] Programme role: always present; programme doesn't gate.
- [ ] Programme soft-prior: low variability.
- [ ] Affordance-catalog: `ward.highlight.whos_here`.
- [ ] Expand-not-replace: always present.
- [ ] Hapax-authored: confirm.

---

## §17. Ward 15 — `stream_overlay`

**File(s):**
- Render class: `agents/studio_compositor/stream_overlay.py::StreamOverlayCairoSource` lines 91–161
- Layout binding: source `stream_overlay` → surface `pip-lr` (surface lines 317–333; assignment lines 630–636)
- Tests: `tests/studio_compositor/test_stream_overlay_emissive.py`
- Goldens:
  - `tests/studio_compositor/golden_images/wards/stream_overlay_400x200.png`
  - `tests/studio_compositor/golden_images/emphasis/stream_overlay_400x200.png`

### 17.1 Appearance

- [ ] Palette: three rows `>>> [FX|<chain>]`, `>>> [VIEWERS|<count>]`, `>>> [CHAT|<status>]` in emissive Px437.
- [ ] Typography: Px437 via Pango.
- [ ] Emissive primitives: chevron + bracket as centre-dot glyphs.
- [ ] Shimmer: stance-indexed on chevrons.
- [ ] Signature artefacts: row inverse-flash on value change (200 ms).
- [ ] Emphasis border: standard.

### 17.2 Placement

- [ ] Surface `pip-lr`: `{x:1500,y:860,w:400,h:200,z_order:10}` at 1920 → x≈1000, y≈573, w≈267, h≈133 at 1280 out.
- [ ] z=10; sits below most chrome. No geometric overlaps with impingement_cascade (y 267 h 240, ends y 507) or captions (y 620 h 73, ends y 693) — stream_overlay y range [573, 706], OVERLAPS captions y range [620, 693]. FLAG: stream_overlay at z=10 is BELOW captions at z=20, so captions occlude stream_overlay's middle 73 px. Likely intentional (captions are supposed to dominate the bottom when speech is live), but document.
- [ ] Region: pip lower-right ✅.
- [ ] Anchored: fixed.

### 17.3 Behaviors

- [ ] FSM: HOLD.
- [ ] Entry: no-op pre-B3.
- [ ] Flash: per-row on value change.
- [ ] Breathing alpha: chevrons pulse.
- [ ] Slide-in: N/A.
- [ ] Netsplit-burst: B4.

### 17.4 Functionality

- [ ] SHM inputs: SHM_DIR constant at line 30 (`/dev/shm/hapax-compositor`). Reads FX chain state, viewer count, chat status from sub-paths under SHM_DIR. Inspect render class for specific files.
- [ ] Input freshness: per input cadence.
- [ ] Missing-input: `[—|—]` fallback rows.
- [ ] Prom metrics: standard.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: aggregate chat status; no per-author state.

### 17.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.stream_overlay` (rare — stream_overlay is passive display).
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: likely low.
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: low.

### 17.6 Content-programming recruitment

- [ ] Programme role: persistent chrome in all programmes.
- [ ] Programme soft-prior: visibility weight.
- [ ] Affordance-catalog: `ward.highlight.stream_overlay`.
- [ ] Expand-not-replace: always present.
- [ ] Hapax-authored: confirm.

---

## §18. Ward 16 — `research_marker_overlay`

**File(s):**
- Render class: `agents/studio_compositor/research_marker_overlay.py` (class name likely `ResearchMarkerFrameSource` or similar); companion `research_marker_frame_source.py`
- Layout binding: conditional (research-mode only). No dedicated surface in `default.json`; surfacing behaviour is runtime-gated on `working_mode=research` + marker event.
- Tests: `tests/studio_compositor/test_research_marker_emissive.py`,
  `test_research_marker_frame_source.py`
- Goldens:
  - `tests/studio_compositor/golden_images/wards/research_marker_overlay_1280x64.png`
  - `tests/studio_compositor/golden_images/emphasis/research_marker_overlay_1280x64.png`

### 18.1 Appearance

- [ ] Palette: banner across full width, Px437 `>>> [RESEARCH MARKER] <HH:MM:SS>`. Marker label rendered as point-of-light per character.
- [ ] Typography: Px437.
- [ ] Emissive primitives: per-character point-of-light glyphs.
- [ ] Shimmer: stance-indexed.
- [ ] Signature artefacts: banner `zero-cut-in` on marker creation; `zero-cut-out` after `HAPAX_RESEARCH_MARKER_TTL_S` seconds (default 10 s).
- [ ] Emphasis border: standard.

### 18.2 Placement

- [ ] Conditional visibility: only when `/dev/shm/hapax-compositor/research-marker.json` has a recent entry (within TTL). Default state is ABSENT.
- [ ] Surface: probably added dynamically; verify via compositor startup log that the research_marker surface is registered.
- [ ] Region: full-width top banner (1280×64 per goldens).
- [ ] Anchored: fixed, full-width.

### 18.3 Behaviors

- [ ] FSM: THIS ward is the one where the ABSENT default would be correct — banner should be invisible outside marker windows. The hotfix that flips ALL wards to HOLD-default may be making the banner always-visible; verify the ward explicitly passes `initial_state=TransitionState.ABSENT` in its `HomageTransitionalSource.__init__` call.
- [ ] Entry: `zero-cut-in` on marker event.
- [ ] Exit: `zero-cut-out` after TTL.
- [ ] Flash: N/A.
- [ ] Breathing alpha: per-character glyph shimmer.
- [ ] Slide-in: zero-cut (no slide).
- [ ] Netsplit-burst: banner should override netsplit; marker trumps rotation.

### 18.4 Functionality

- [ ] SHM inputs: `/dev/shm/hapax-compositor/research-marker.json` (line 32 of research_marker_overlay.py).
- [ ] Input freshness: per marker event.
- [ ] Missing-input: banner ABSENT.
- [ ] Prom metrics: standard + marker-specific counter.
- [ ] Ward-properties modulation: standard.
- [ ] Consent: research markers are metadata labels; safe.

### 18.5 Director-loop recruitment

- [ ] Intent-family: `ward.highlight.research_marker_overlay` (rare — markers are operator-driven).
- [ ] Dispatch path: standard.
- [ ] Recent recruitment count: very low (marker is externally triggered).
- [ ] Emphasis-applied metric: check.
- [ ] Structural intent emphasis: very low.

### 18.6 Content-programming recruitment

- [ ] Programme role: research-mode programmes only; shows marker events during the stream-is-research-instrument window.
- [ ] Programme soft-prior: gated by working_mode; programme can bias the marker banner to stay longer / shorter.
- [ ] Affordance-catalog: `ward.highlight.research_marker_overlay`.
- [ ] Expand-not-replace: banner only appears when a marker event fires; programmes cannot force it on without an event.
- [ ] Hapax-authored: confirm.

---

## §19. Cross-ward invariants

Tick each once all per-ward walks are complete.

- [ ] **Z-order total ordering documented.** Enumerate every z_order
  assignment in `config/compositor-layouts/default.json` (grep
  `z_order`); produce a sorted list (low-to-high = back-to-front) and
  confirm no two surfaces share a z_order AND geometric overlap.
  Flagged overlaps: stream_overlay (z=10) vs captions (z=20) on bottom
  strip; thinking_indicator (z=26) vs hardm (z=28) on upper-right;
  chat-legend-right (z=20) vs impingement-cascade (z=24) abutting.
- [ ] **Every ward has an emphasis-on + emphasis-off golden image.** Count
  goldens in `tests/studio_compositor/golden_images/wards/` and
  `.../emphasis/` — expect 16 each (32 total). Confirmed 16 in each at
  audit time.
- [ ] **Every ward has a test file.** `ls tests/studio_compositor/test_*.py`
  enumerate. Hothouse wards share `test_homage_*.py`, which is fine but
  means per-ward isolation is weak — flag for future granularity.
- [ ] **Every ward emits the six Phase-C1 metrics.** `curl :9482/metrics |
  grep hapax_homage_ | sort -u`. Expect:
  `hapax_homage_transition_total`, `hapax_homage_emphasis_applied_total`,
  `hapax_homage_render_cadence_hz`, `hapax_homage_rotation_mode`,
  `hapax_homage_active_package`,
  `hapax_homage_substrate_saturation_target`, plus
  `hapax_homage_choreographer_rejection_total`,
  `hapax_homage_choreographer_substrate_skip_total`,
  `hapax_homage_violation_total`,
  `hapax_homage_signature_artefact_emitted_total`,
  `hapax_homage_package_active` (per `shared/director_observability.py`).
- [ ] **Wards never import GTK / Pango before startup ProbePango check.**
  `grep -R 'from gi.repository import' agents/studio_compositor/`
  should show the import in a function body or guarded by
  `warn_if_missing_homage_fonts` call order.
- [ ] **No ward renders via `cr.show_text` directly** (post-A5). `grep -R
  'show_text' agents/studio_compositor/ --include=*.py` should return
  only vestigial instances or legacy shims; every active text path
  flows through `text_render.render_text` (Pango).
- [ ] **Every ward is registered in `ward_registry._REGISTRY` after
  startup.** Call `populate_from_layout(active_layout)` in a test,
  assert all 16 ids present.
- [ ] **Every ward has a `natural_w` + `natural_h` declared in layout
  JSON source.** Confirm via `jq '.sources[] | {id, natural:
  .params.natural_w, h: .params.natural_h}' default.json`.
- [ ] **Ward-properties.json is authored with at most one entry per
  ward + "all".** `jq '.wards | keys' ward-properties.json`. Any key
  other than a known ward-id or "all" is a drift bug.
- [ ] **Homage-pending-transitions.json queue size is bounded.** `jq
  '.transitions | length' homage-pending-transitions.json`. Pre-B3, queue
  size may be >200 because wards never drain (FSM stuck at HOLD ignores
  incoming entries). Post-B3, expect ≤50 steady-state.

---

## §20. Reverie substrate (not a ward, but the ground)

The Reverie (wgpu shader pipeline, rendered by `hapax-imagination`
daemon, composited via the `reverie` external_rgba source at
`config/compositor-layouts/default.json` lines 55–65) is not a ward but
is the visual GROUND underneath every ward. Audit it here briefly so
the per-ward results have a comparison baseline.

- [ ] **Saturation damping active:** `jq
  '."colorgrade.saturation"' /dev/shm/hapax-imagination/uniforms.json`
  should return ≤0.55 when the active HOMAGE package is BitchX. Expected
  range [0.35, 0.55].
- [ ] **Hue-rotate toward accent:** `jq '."colorgrade.hue_rotate"'
  uniforms.json` should return ~180.0 (cyan) under BitchX.
- [ ] **Brightness:** `jq '."colorgrade.brightness"' uniforms.json` ~0.85.
- [ ] **Substrate reads as tinted cyan ground, NOT kaleidoscope.** Sample
  upper-right pip region (reverie lives at pip-ur), confirm dominant
  hue is cyan-leaning and movement is slow/breathing, not high-
  saturation flickering.
- [ ] **Active package broadcast:** `jq '.package_name'
  /dev/shm/hapax-compositor/homage-substrate-package.json` should
  return `bitchx`. Timestamp should be recent (updated per choreographer
  tick).
- [ ] **Substrate does not occlude wards:** reverie surface is at pip-ur
  (z=10, x=1260 y=20 w=640 h=360 at 1920 → x=840 y=13 w=427 h=240 at
  1280 out). No ward at z≥10 sits in this region except HARDM (z=28,
  x=1067 y=13 w=171 h=171) — HARDM OVERLAPS reverie pip. HARDM at z=28
  occludes reverie in the HARDM rect. Confirm this is intentional.
- [ ] **`custom[4].x` coupled to choreographer transition energy:**
  `jq '.custom.0' uniforms.json` may expose the channel; if not, inspect
  the uniform layout for where transition energy lands. On netsplit-
  burst, saturation should lift +10% momentarily.

---

## §21. Execution protocol (alpha opens one PR per ❌ finding)

Once the audit is complete, alpha converts every ❌ finding into a PR
entry in this execution queue. Ordering rule:

1. **Emergency stop:** anything affecting `live-egress`, `consent`, or
   `face-obscure` → alpha pauses the stream, pages the operator,
   reverts to consent-safe layout. This queue does NOT apply to those
   findings.
2. **Highest priority:** findings that make a ward INVISIBLE or
   UNRENDERABLE (natural_w/h missing, surface id missing, render class
   crash).
3. **High:** findings that break the emissive grammar (flat-fill
   fallback, wrong font, show_text instead of Pango).
4. **Medium:** findings in §5 recruitment (intent_family never hits this
   ward) or §6 programme soft-prior wiring.
5. **Low:** findings in §4 graceful degradation (missing-input behavior)
   when no live outage is observed.
6. **Deferred:** B3/B4-gated findings (FSM un-bypass, rotation_mode
   activation) — these are already in the homage-completion plan;
   reference that plan's phase id instead of opening a new PR.

**PR template (one per finding):**

```
fix(ward/<ward_id>): <dimension> — <one-line description>

Audit entry: docs/research/2026-04-20-ward-full-audit-alpha.md §<N>.<D>
Finding: <quote the ❌ from the audit>
Fix: <one paragraph>
Verification: <command + expected output>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

**Blocking requirement:** alpha does NOT pick a new finding from this
queue while a previous finding's PR is unmerged (per workspace CLAUDE.md
`branch-discipline`). One finding → one branch → one PR → merge → next.

**Anticipated top 5 wards most likely to have ❌ per-dimension findings:**

1. **`chat_ambient`** — layout binding still points at
   `ChatKeywordLegendCairoSource` per reckoning §3.5; natural size
   560×40 vs surface 160×400 is an aspect mismatch; Phase B5 of the
   homage-completion plan will fix. Expected ≥3 ❌.
2. **`captions`** — Pango Px437 startup probe may WARN; font
   installation drift; consent-path gating for STT display. Expected
   ≥2 ❌.
3. **`research_marker_overlay`** — the hotfix at `transitional_source
   .py:86` defaults ALL wards to HOLD, which for this ward means the
   banner may be ALWAYS-VISIBLE when it should be ABSENT by default.
   Alpha MUST verify the ward explicitly passes
   `initial_state=TransitionState.ABSENT` in its init. Expected ≥1 ❌
   if the override is missing.
4. **`thinking_indicator`** — z_order conflict with HARDM (thinking z=26
   under HARDM z=28, geometric overlap at upper-right). Likely ≥1 ❌
   for the occlusion depending on operator intent.
5. **`stream_overlay`** — z=10 below captions (z=20) with 73 px
   geometric overlap; likely intentional but document. Expected ≥1 ❌
   or ⚠️ for the placement drift.

**Anticipated cross-ward ❌ (§19):**
- Every ward today sits at FSM state HOLD due to the
  `transitional_source.py` hotfix — not a ward-specific ❌ but a
  system-wide one that Phase B3 will resolve. Document one ❌ at §19
  pointing at the homage-completion plan Phase B3.
- `ward.highlight.<id>` capabilities may be sparse in Qdrant
  `affordances` collection (reckoning §3.6) — document one ❌ at §19
  pointing at a capability-registration PR.

**Anticipated reverie ❌ (§20):**
- Saturation damping may still be undamped (reckoning §3.7, Phase A6
  of the homage-completion plan) — document one ❌ at §20 pointing at
  Phase A6.

---

## §22. Audit stats (filled in on completion)

- Wards walked: <NN>/16
- Total checkboxes: ~130 (16 wards × 6 dims × 5-6 items + §19 ten + §20 seven + §21 zero)
- ❌ findings: <NN>
- ⚠️ findings: <NN>
- ✅ clean: <NN>
- PR queue entries (§21): <NN>
- Commits on `hotfix/fallback-layout-assignment` at audit close: <N>
- Audit walk wall-clock: <H:MM>

---

## §23. References

- `docs/superpowers/plans/2026-04-19-homage-completion-plan.md` — the
  phases A1–E that will fix most of this audit's ❌ findings.
- `docs/superpowers/plans/2026-04-20-programme-layer-plan.md` — the
  meso-layer that §6 of each ward assumes.
- `docs/research/2026-04-19-homage-aesthetic-reckoning.md` (vault at
  `~/Documents/Personal/20-projects/hapax-research/
  2026-04-19-homage-aesthetic-reckoning.md`) — the operator's
  diagnosis that this audit enumerates against.
- Memory files: `project_programmes_enable_grounding`,
  `feedback_hapax_authors_programmes`, `feedback_no_expert_system_rules`,
  `feedback_grounding_exhaustive`.
- Companion audit (task #171): broad wiring audit — refer there for
  audio routing, systemd, SHM freshness, observability-layer depth.

---

(End of audit doc. Next action: alpha walks §3–§18 per the workflow in
§1; ticks boxes; commits per-ward; converts ❌ findings into §21 PR
queue entries; opens those PRs in priority order.)
