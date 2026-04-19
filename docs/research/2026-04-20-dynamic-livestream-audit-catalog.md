---
date: 2026-04-20
author: cascade research subagent (operator-directed, dispatched from the 14:08 TTS leak reckoning)
audience: alpha (executes dynamic audits), beta (livestream perf support), operator (verdict owner)
register: scientific, neutral, design-doc
status: research catalog — enumerates dynamic-behavior audit classes; does not itself execute audits
sibling:
  - docs/research/2026-04-20-livestream-audit-catalog.md    (STATIC, 104 audits — snapshot-in-time state)
  - docs/research/2026-04-20-cascade-audit-results.yaml     (cascade execution, 67)
  - docs/research/2026-04-20-audit-synthesis-final.md       (combined synthesis, 2 hard fails)
related:
  - docs/research/2026-04-20-ward-full-audit-alpha.md
  - docs/research/2026-04-19-content-programming-layer-design.md
  - docs/research/2026-04-14-audio-path-baseline.md
  - docs/logos-design-language.md
  - agents/studio_compositor/director_loop.py
  - agents/studio_compositor/structural_director.py
  - agents/studio_compositor/compositional_consumer.py
  - agents/studio_compositor/audio_ducking.py
  - agents/studio_compositor/homage/transitional_source.py
operator-directive-load-bearing: |
  "research what audits and tests should be run to thoroughly verify
  the livestream surface appearance, homage appearance, ward
  appearance, their behaviors both short and long-term + verify the
  director loop and content programming behaviors and effects both in
  the short and long term + verify the audio interactions are clean,
  intentional, and driven by the director loop and content programming
  succcesffully in such a way that the mix is ALWAYS good."
operator-reframes-2026-04-20: |
  (a) "Things are not in a good state right now. Not going live yet."
  (b) "Everything post-live livestream-related is now pre-live."
  (c) "Do not ever wait on me... Always be working. NO DOWNTIME."
incident-archetype: |
  2026-04-20 14:08 TTS slur leak. Observability blind spot + silent
  invariant break + multi-layer defence with one layer missing. The
  dynamic audit surface must close the same archetype for appearance,
  behavior, and mix: metrics on BOTH the happy path and the
  violation path, at every timescale.
---

# Dynamic Livestream Audit Catalog — Behavior Over Time

## §0. Document scope and the static/dynamic split

The sibling catalog (`2026-04-20-livestream-audit-catalog.md`, 104
rows, 18 sections) enumerates STATIC audits: configuration checksums,
graph-dump conformance, freshness gauges, fail-closed smoke tests,
pre-live gates. Those audits answer *is the thing wired correctly
right now?*

The present catalog enumerates DYNAMIC audits: behavior over time,
evolution across the session, degradation patterns, drift, long-loop
emergent misbehavior. These audits answer a different question —
*does it keep being correct while running, and does it stay correct
across two continuous hours of broadcast?*

The 14:08 TTS leak is the archetype for why this catalog is
necessary. The static catalog would have passed `speech_safety`'s
unit tests; the dynamic failure — a novel slur variant emitted by
the LLM after a successful redaction on an earlier variant —
materialises only in behavior-over-time. The static catalog checks
configuration; the dynamic catalog checks process.

The dynamic catalog is organised into 20 sections mirroring the
operator's verbatim ask, with four supplementary classes (§13–§16),
then wiring into infrastructure, testing harness, and pre-live
integration (§17–§20).

### 0.1 Cadence vocabulary

- **per-tick** — one compositor tick (33 ms at 30 fps, or
  compositional-consumer tick at ~200 ms); the fastest audit loop.
- **per-minute** — sampled at 60 s intervals; fine-grained dashboard.
- **per-session** — sampled once at session start, once at end;
  produces a per-session record.
- **per-stream** — sampled across the full live window (2 h typical);
  the longitudinal record.
- **continuous** — always-on gauge with alert wiring.
- **replay-only** — computed on a recorded session, not live; used
  for longitudinal analysis and post-mortem.

### 0.2 Signal types

- **gauge** — instantaneous value, e.g., p99 render duration right now.
- **rate** — count-over-time, e.g., director intents per minute.
- **envelope** — variance of a gauge across a window, e.g., how much
  does p99 wobble across a 5-minute window.
- **distributional** — full histogram not collapsed to a percentile,
  e.g., per-ward emphasis durations over a session.
- **invariant-violation counter** — Pattern-1 discipline: every
  invariant emits a hit counter AND a violation counter, so a silent
  break is observable.
- **mix-quality score** — composite score (§10) that collapses many
  signals into a single "is the mix good right now" value.

### 0.3 Pre-authoring consideration — the three archetypes

Before enumerating, it is worth naming the three failure archetypes
this catalog must cover, because they are structurally different and
need different instruments:

1. **Silent invariant break** (14:08 leak). The happy path fires,
   a *variant* slips past, no counter increments. Instrument: always
   a paired hit/violation counter; alert on violation rate > 0.
2. **Drift** (music-taste drift, ward emphasis burn-in, cross-surface
   coherence decay). The system works tick-by-tick; over an hour
   the aggregate distribution shifts. Instrument: rolling-window
   distributional comparison against a reference.
3. **Emergent misbehavior** (overlap-cascade, rapid preset cycling,
   stuck-frame). No single tick is wrong; the pattern across ticks
   is. Instrument: sliding-window pattern detector per §15.

All three show up across every subsection below.

---

## §1. Livestream composite appearance audits

The ultimate surface is the 1920×1080 (OUTPUT_WIDTH=1280 in live
environment per layout scale 0.6667) frame that reaches YouTube
after face-obscure, compositor tile, shader chain, cairo overlays,
and RTMP encode. Composite appearance audits target this frame
directly.

### 1.1 Per-tick legibility (short-term)

- **What it audits.** A sampled frame at 5-second intervals
  (`/dev/video42 → /tmp/v42-*.png`). For each sample, compute:
  text legibility of captions strip (OCR success rate ≥ 0.95 on
  rendered caption text), contrast ratio between active ward chrome
  and its background (≥ 4.5:1 per WCAG AA, relaxed for aesthetic
  wards per design language §3), ward-boundary crispness
  (edge-detection count in ward regions above a per-ward floor).
- **Why.** Broadcast legibility is not a subjective property; it
  can be measured objectively per sample. A ward that looks legible
  on the compositor monitor may be unreadable after YouTube's VP9
  encode.
- **Metric.** `hapax_composite_legibility_score_total{ward}` —
  per-ward legibility score, 0..1, sampled every 5 s.
- **Pass.** Rolling 1-min mean > 0.85 per ward; p05 (worst 5% of
  samples) > 0.70.
- **Cadence.** continuous.
- **Failure action.** Alert if any ward dips below p05 floor for
  > 60 s consecutive; operator sees "legibility degraded: `<ward>`"
  in Grafana.

### 1.2 Hero-camera coherence (short-term)

- **What it audits.** When the director selects a hero camera
  (`objective_hero_switcher.py`), the hero selection is visually
  obvious: the hero surface is the largest visible camera, it is
  not occluded by any ward, and the other cameras are visibly
  de-emphasised (PiP or hidden). The coherence check asserts these
  three properties per-tick.
- **Why.** A declared hero that is smaller than another surface, or
  occluded by a ward, or not visually distinct, is a compositional
  lie. The director issued an intent the surface did not honour.
- **Metric.** `hapax_hero_coherence_total` — pass/fail per hero
  switch event, plus continuous gauge
  `hapax_hero_coherence_gauge{hero}`.
- **Pass.** Every hero-switch event produces a coherent frame
  within 200 ms of the switch.
- **Cadence.** per-tick (on hero-switch) + continuous.

### 1.3 Safe-area and non-overlap discipline (short-term)

- **What it audits.** Extends static §3.7 (safe-area) to behavior:
  no ward animates OUT of the safe area during entry/exit
  choreography, no DVD-bouncing ward crosses the YouTube watermark
  zone, no scale-bump emphasis pushes a ward over an adjacent
  ward.
- **Why.** Static safe-area respects the design-language coords but
  misses animation overshoot. A scale-bump of 1.1× on a ward
  anchored at 5% from the edge is within safe area at rest but
  breaks it at the emphasis peak.
- **Metric.** `hapax_ward_overshoot_total{ward, direction}` —
  increments when any part of a ward's bbox crosses the safe-area
  boundary at any point in an emphasis envelope.
- **Pass.** Zero overshoots per session.
- **Cadence.** continuous.

### 1.4 Motion smoothness at 30 fps (short-term)

- **What it audits.** Inter-frame pixel-delta variance over a
  sliding 2-second window. Target: smooth enough that no
  perceivable judder, no frozen frame repeats, no black-frame
  insertion. Reference-free signal computable from
  `/dev/video42` alone.
- **Why.** Broadcast smoothness is measured in microstutters, not
  FPS count. The stream can report 30 fps while delivering 5
  consecutive identical frames interleaved with catch-up bursts,
  which looks like stutter to the viewer.
- **Metric.** `hapax_composite_motion_jitter_ms` — standard
  deviation of inter-frame delta times over 2-second window. Per
  EBU R128's temporal-measurement discipline applied to video.
- **Pass.** σ < 3 ms (within 10% of one frame interval).
- **Cadence.** continuous.
- **Reference.** `pVMAF` (§17) from Synamedia is the analogous
  livestream-appropriate no-reference video-quality signal.

### 1.5 Visual monotony resistance (long-term)

- **What it audits.** Across a rolling 10-minute window, the union
  of active wards, active preset family, and active hero camera
  produces a monotony score: does the same tuple recur beyond a
  threshold? A healthy stream varies; a stuck stream monotones.
- **Why.** Operator directive "do-nothing-interesting baseline" is
  preserved (a regression for task #158 CVS #19) but the *other*
  failure — over-varied churn — is equally bad. The measure is
  Shannon entropy over the (ward-set × preset-family × hero) tuple
  distribution; too high means churn, too low means freeze, a
  comfortable middle is the target.
- **Metric.** `hapax_composite_variety_entropy_bits` — rolling
  10-min entropy of the (ward-set, preset-family, hero) tuple.
- **Pass.** Entropy within a per-programme-role envelope:
  `listening` programme wants 1.0..2.0 bits (low variation),
  `hothouse-pressure` programme wants 3.5..5.0 bits (high).
- **Cadence.** per-minute; distribution computed at per-stream.
- **Long-term view.** Plot across sessions; trend-down or trend-up
  indicates drift.

### 1.6 Aesthetic evolution (long-term)

- **What it audits.** Successive 5-minute segments of a session
  should feel different from each other. Compute a per-segment
  "aesthetic fingerprint" (mean hue histogram, mean dynamic range,
  mean motion level, active preset family), diff segment N vs
  N-1. A healthy stream has segment-to-segment diff above a floor.
- **Why.** The 2-hour programme structure (§9 of the sibling
  content-programming design doc) requires programme transitions
  to be visibly distinct. A stream that renders all five programmes
  identically is failing the programme layer.
- **Metric.** `hapax_aesthetic_segment_diff` — cosine distance
  between consecutive 5-min aesthetic fingerprints.
- **Pass.** Distance > 0.15 on programme boundaries; <0.5 within a
  programme (not enough variation = monotony; too much = churn).
- **Cadence.** per-stream (post-hoc computation from v42 archive).

### 1.7 Package-swap smoothness (long-term)

- **What it audits.** When `homage-active-artefact.json` changes
  (HomagePackage swap — BITCHX / THINKING / STANCE / GUEST /
  RESEARCH / ABSENT), all 18 wards repaint within one tick. The
  *dynamic* check extends the static §3.4 pass by requiring zero
  "uncomposed-ward" frames during the transition — no single
  frame in the RTMP stream can have mixed old and new package
  chrome.
- **Why.** Static §3.4 confirms propagation "within 200 ms"; the
  viewer sees the frame-at-250ms and a frame with mixed chrome is
  broken.
- **Metric.**
  `hapax_package_swap_mixed_frame_rate{from_pkg,to_pkg}` — count
  of frames during the 200-ms transition window that contain
  chrome from both packages.
- **Pass.** Zero per swap event.
- **Cadence.** per-event (on swap), continuous.

### 1.8 Degraded-state degradation pattern (long-term)

- **What it audits.** When `budget_signal.py` publishes DEGRADED,
  the system is expected to reduce ward count, drop emphasis
  envelopes, and fall back to a reduced-content layout. The audit
  confirms the degradation is graceful: a defined sequence of
  wards drops in a defined order, rather than random freeze.
- **Why.** Degraded state is the system's public failure mode.
  Operator directive "HOMAGE go-live + live-iterate via
  DEGRADED-STREAM mode" means degradation is a first-class state,
  not an error.
- **Metric.**
  `hapax_degradation_sequence_conformance_total` — pass/fail per
  degradation event on whether the sequence matches spec.
- **Pass.** Every degradation follows the spec sequence documented
  in `shared/compositor_degradation.py` (to be authored;
  currently implicit).
- **Cadence.** per-event.

---

## §2. HOMAGE appearance audits — the BitchX-mIRC visual grammar

HOMAGE is the shared aesthetic across all 18 wards: BitchX/mIRC-16
palette, Px437 IBM VGA 8x16 typography, `»»»` marker glyphs,
CP437-scaled geometry, artefact-driven motion grammar. Dynamic
audits ensure the grammar holds across packages and across hours.

### 2.1 mIRC-16 palette fidelity (short-term)

- **What it audits.** Every rendered ward's dominant chrome pixels
  (sampled at a known point per ward) match the declared mIRC-16
  colour for the active package. The palette has only 16 colours;
  any sampled hex must map to one of them within ΔE-2000 ≤ 2
  (perceptual-colour distance).
- **Why.** mIRC-16 is load-bearing — drift to an off-palette
  colour (an accidental Tailwind hex, a colour-grade shader over-
  saturating a ward) breaks the aesthetic in a way that accumulates
  over a session.
- **Metric.** `hapax_homage_palette_deviations_total{ward,pkg}`.
- **Pass.** Zero deviations per minute.
- **Cadence.** continuous (5-s sample).

### 2.2 `»»»` marker presence and placement (short-term)

- **What it audits.** The `»»»` (triple right-angle-quote) marker
  appears on cue: every message in `impingement_cascade`, every
  row in `activity_variety_log`, every row in the grounding
  ticker. Each marker is rendered at the expected column offset
  in the Px437 grid.
- **Why.** A missing `»»»` marker is the equivalent of a broken
  tombstone character in mIRC — the viewer feels the shape is
  wrong even if they cannot articulate why.
- **Metric.** `hapax_homage_marker_coverage_ratio{surface}` —
  rendered markers / expected markers per surface.
- **Pass.** Ratio > 0.98 over a 1-min window (allowing brief
  render glitches).
- **Cadence.** continuous.

### 2.3 CP437 font crispness post-HARDM rework (short-term)

- **What it audits.** Post-HARDM-rework commit `7f32b1e53` moved
  HARDM to glyph-native Px437 rendering. The dynamic audit
  confirms the glyph raster matches the font file reference — not
  blurred, not antialiased inconsistently with other surfaces,
  not subjected to compositor-level bilinear scaling.
- **Why.** Font crispness is a dynamic property: a single frame
  can pass while a downstream resize operation blurs every frame
  thereafter.
- **Metric.** Static cross-check of sampled glyphs against font
  raster; `hapax_homage_font_crispness_score{surface}`.
- **Pass.** Score > 0.9 (strict match with ±1px tolerance).
- **Cadence.** continuous (minute sample).

### 2.4 Package-swap visual transition grammar (short-term)

- **What it audits.** When HomagePackage changes, the transition
  follows the grammar defined by the `HomageTransitionalSource`
  FSM: `HOLD → EXITING → ABSENT → ENTERING → HOLD` per ward,
  coordinated by the choreographer. No ward may skip a state; no
  two wards may collide at the ENTERING moment; the choreographer
  staggers entries per the active `homage_rotation_mode`
  (`steady`, `deliberate`, `rapid`, `burst`, `paused`).
- **Why.** Package-swap is the stream's punctuation — the moments
  where programmme transitions become visible. A sloppy swap
  undermines the programme-layer grammar.
- **Metric.** `hapax_package_swap_choreography_violations_total` —
  counts any FSM-skip, collision, or rotation-mode violation.
- **Pass.** Zero per swap.
- **Cadence.** per-event.

### 2.5 Aesthetic fatigue resistance (long-term)

- **What it audits.** Across a 2-hour session, does the aesthetic
  sustain viewer attention? Computed by: (a) package-variety
  entropy across session (does the stream cycle through packages
  appropriately?), (b) within-package variation (does a BITCHX
  segment of 30 min actually have internal variation, or does it
  lock in?), (c) motion-level variance at the segment level.
- **Why.** Operator directive (feedback_grounding_exhaustive and
  memory "livestream IS the research instrument") — aesthetic
  fatigue is a research-data quality issue, not just a viewer
  comfort issue.
- **Metric.** `hapax_homage_fatigue_index` — composite of the
  three sub-signals.
- **Pass.** Index below a per-programme envelope; tuned from
  replay data.
- **Cadence.** per-stream.
- **Long-term view.** Session-over-session trend indicates whether
  the programme layer is adapting.

### 2.6 HARDM dot-matrix cell-emphasis fairness (long-term)

- **What it audits.** The HARDM 256×256 dot-matrix fires
  cell-emphasis for recruitment events. Over a session, do cells
  fire with a distribution that tracks the underlying affordance
  activation, or does a handful of cells monopolise emphasis
  (burn-in)?
- **Why.** A HARDM that lights only 5 cells across a whole session
  tells the viewer the grid is decorative, not functional. A HARDM
  that fires every cell equally tells the viewer nothing is
  special. Neither is correct.
- **Metric.** `hapax_hardm_cell_firing_distribution` — histogram
  per session; entropy and top-k concentration.
- **Pass.** Entropy within tuned envelope; top-10 cells fire < 40%
  of total emphasis events.
- **Cadence.** per-stream (post-session computation).

---

## §3. Per-ward appearance audits

All 18 wards classified per the ward-audit table:

- **Chrome wards** (legible data overlays, always-on) — token_pole,
  stance_indicator, activity_header, pressure_gauge, whos_here,
  grounding_provenance_ticker, thinking_indicator.
- **Content wards** (volatile content, director-driven) —
  impingement_cascade, recruitment_candidate_panel,
  activity_variety_log, captions.
- **Hothouse wards** (research-instrument visible) —
  research_marker_overlay, chat_ambient.
- **Avatar wards** (iconic glyph-bearing) — album, token_pole
  (vitruvian), stream_overlay.

Plus: `hardm_dot_matrix` (background-sized structural field);
Reverie is a structural peer per §11 (not a ward).

### 3.1 Per-ward palette compliance over time (short-term)

- Per §2.1, evaluated per-ward. Each ward has a declared
  `_domain_accent("<ward>")` result from
  `agents/studio_compositor/homage/__init__.py`; the rendered ward
  must sample to that accent within ΔE-2000 ≤ 2.
- **Metric.** Sub-labels of §2.1 metric by ward.

### 3.2 Per-ward typography consistency (short-term)

- Each chrome ward renders specific text surfaces; audit confirms
  the rendered glyph geometry matches the declared Pango layout
  (font, size, weight, leading). A 2px drift in leading is a
  perceptible cumulative error.
- **Metric.** `hapax_ward_typography_drift{ward, dimension}` —
  sampled drift in pixels.
- **Pass.** All dimensions within ±1 px.

### 3.3 Animation cadence per ward (short-term)

- Each ward has a declared animation cadence (token_pole breathes
  at stance-indexed Hz: 1.0 nominal, 1.6 seeking, 0.7 cautious;
  thinking_indicator strobes at 2.5 Hz when thinking;
  pressure_gauge fills at the computed rate). Audit confirms the
  observed cadence matches declared within ±10%.
- **Metric.** `hapax_ward_cadence_drift_pct{ward}`.
- **Pass.** ±10%.

### 3.4 Transition FSM coverage per ward (short-term)

- Extends static §3.5. Dynamic audit asserts every ward exercises
  every FSM state across a 1-hour window, not just the observed
  subset. If a ward never EXITs, the animation grammar is half-
  degenerate even if all renders look correct.
- **Metric.** `hapax_ward_fsm_state_coverage{ward, state}` — count
  per state per hour.
- **Pass.** All 4 states (ABSENT, ENTERING, HOLD, EXITING) fire at
  least once per hour for wards that SHOULD rotate; B3-hotfix
  wards temporarily exempted.

### 3.5 Emphasis envelope visibility (short-term)

- When a ward is emphasised (`set_ward_properties(glow_radius_px,
  border_pulse_hz, scale_bump_pct, alpha, ttl_s)`), the emphasis
  must be visually detectable at the RTMP output (not just in the
  compositor's ward-properties file). Dynamic audit compares
  sampled emphasis frames to declared emphasis parameters:
  measured glow radius ≥ declared, measured pulse frequency
  matches declared ±10%, emphasis decays at TTL expiry.
- **Metric.**
  `hapax_emphasis_envelope_conformance_total{ward,parameter}`.
- **Pass.** Conformance > 0.95 per parameter.

### 3.6 Signal-driven dynamics per ward (short-term)

- For each ward with a declared signal input (token_pole ← token
  ledger, pressure_gauge ← hothouse pressure, stance_indicator ←
  stimmung.stance, thinking_indicator ← dmn.thinking, whos_here ←
  person-detection state, captions ← caption queue, etc), the
  dynamic audit asserts the signal change is reflected in the
  ward render within the declared latency budget.
- **Metric.**
  `hapax_ward_signal_response_latency_ms{ward}` —
  signal-change-timestamp to first-frame-with-change.
- **Pass.** p95 < 500 ms for all wards; p99 < 1.5 s.

### 3.7 Ward non-overlap invariance across motion (short-term)

- Static §3.2 confirms layout geometry has no overlaps. Dynamic
  §1.3 confirms animation respects safe area. This extends: no
  two non-`fx_chain_input` wards overlap at any frame during
  entry/exit animation. Emphasis scale-bump of ward A must not
  push it into ward B.
- **Metric.** `hapax_ward_runtime_overlap_total{ward_a, ward_b}`.
- **Pass.** Zero per session.

### 3.8 Content ward dynamic sufficiency (short-term)

- A content ward (impingement_cascade, recruitment_candidate_panel,
  activity_variety_log, captions) must show content when content
  exists. If `impingements.jsonl` is advancing but the
  impingement_cascade shows a frozen last message, the ward is
  degraded even though its static state is green.
- **Metric.**
  `hapax_content_ward_staleness_seconds{ward}` — seconds since
  last visible update while underlying signal is advancing.
- **Pass.** < 3× ward's declared cadence.

### 3.9 Per-ward appearance reference to ward-audit baseline

All 532 rows of alpha's ward-audit baseline
(`2026-04-20-ward-full-audit-alpha.md`) mapped to continuous
instruments via the metrics above. Sections §3–§18 of that audit
are deep enumerations; the dynamic catalog is the always-on
counterpart of the same surface.

---

## §4. Ward behaviors audits — short-term (per-tick to per-minute)

Where §3 asks "does the ward look right", §4 asks "does the ward
behave right on the timescale of ticks".

### 4.1 Recruitment firing rate per ward

- **Audits.** Per-ward recruitment rate — how often does the ward's
  declared affordance win a recruitment cycle? Per the unified
  semantic recruitment spec, each ward's `content_capability`
  capability is embedded in the affordances Qdrant collection and
  competes for recruitment. Over a 5-min window, its win count
  should track impingement relevance.
- **Why.** A ward whose recruitment rate is zero is dormant even if
  its static wiring is correct. A ward whose rate is 100% is
  starving others.
- **Metric.** `hapax_ward_recruitment_wins_total{ward}` rate.
- **Pass.** Per-ward rate within a tuned envelope (requires
  baseline run).

### 4.2 Emphasis envelope decay curves

- **Audits.** The glow / pulse / scale / alpha envelopes decay
  according to the `ttl_s` parameter of `set_ward_properties`.
  Dynamic audit samples the decay curve at 5 points across the
  TTL window and confirms monotonic decrease to baseline.
- **Why.** A stuck-on envelope (no decay) accumulates visual debt;
  every emphasis event adds to a permanent glow that eventually
  saturates the surface.
- **Metric.**
  `hapax_emphasis_decay_monotonicity{ward}` — pass/fail per event.
- **Pass.** Monotonic per event.

### 4.3 Signal→visual responsiveness (cross-reference §3.6)

- Extends §3.6: not just that the signal eventually renders, but
  that *every* signal change ≥ threshold renders. If the token
  ledger fires 100 ticks in 60 s and the token_pole renders only
  90, ten events were lost.
- **Metric.** `hapax_ward_signal_render_coverage_ratio{ward}`.
- **Pass.** > 0.95 per ward.

### 4.4 RD underlay tempo

- **Audits.** The reaction-diffusion shader (`rd` node in the
  8-pass pipeline) animates at a declared tempo that feeds the
  ward backgrounds. If the RD underlay freezes (uniforms wedged,
  `feedback` pass not advancing), every ward's background is
  static.
- **Metric.** `hapax_reverie_rd_variance_per_second` — computed
  pixel variance on the `rd` pass output.
- **Pass.** Variance > floor; zero-variance state alerts
  immediately.

### 4.5 Decay and ripple correctness (HARDM per-cell)

- **Audits.** Each HARDM cell that fires produces a ripple that
  decays to baseline within a declared TTL; adjacent cells
  propagate a visible ripple. Audit samples individual cells and
  confirms the ripple reaches and decays.
- **Metric.**
  `hapax_hardm_cell_ripple_conformance_total` — per-event
  pass/fail.
- **Pass.** > 0.95.

---

## §5. Ward behaviors audits — long-term (per-session to per-stream)

### 5.1 Ward rotation fairness

- **Audits.** Over a 1-hour window, emphasis events distribute
  across wards per a declared fairness envelope. No single ward
  monopolises > 30% of emphasis-events unless its programme
  explicitly declares it (a captions-forward programme is allowed
  to emphasise captions heavily).
- **Why.** Fairness is a viewer-comfort property AND a research-
  instrument property — a stream that emphasises only token_pole
  has effectively collapsed the 18-ward grid into a single-ward
  surface.
- **Metric.** `hapax_ward_emphasis_share_per_hour{ward}`.
- **Pass.** Gini coefficient across wards < 0.4 unless
  programme-declared.

### 5.2 Emphasis burn-in detection

- **Audits.** A ward that is emphasised repeatedly (≥ 10
  emphasis-ticks in a 5-min window) develops "burn-in" — the
  accumulated alpha saturation and glow residue make the ward
  look permanently-on, defeating the emphasis-envelope grammar.
  Detect by monitoring mean ward alpha over time.
- **Metric.** `hapax_ward_burn_in_mean_alpha{ward}`.
- **Pass.** Mean alpha returns to declared baseline between
  emphasis events.

### 5.3 Dormancy decay

- **Audits.** A ward that has NOT been recruited in the last 10
  minutes should fade gracefully (per choreographer rotation
  mode) — not freeze at its last emphasised state. Audit confirms
  dormant wards track their declared dormancy alpha curve.
- **Metric.** `hapax_ward_dormancy_alpha_drift{ward}`.
- **Pass.** Observed alpha tracks declared curve within ±0.05.

### 5.4 Salience redistribution

- **Audits.** When the active homage_rotation_mode changes
  (`steady` → `deliberate` → `rapid` → `burst` → `paused`), ward
  emphasis distribution redistributes per mode spec. In `steady`,
  ward_cap = 2; in `burst`, ward_cap expands; in `paused`, all
  emphasis drops to baseline.
- **Metric.** `hapax_rotation_mode_conformance{mode}` — per-mode
  compliance rate.
- **Pass.** > 0.9 per mode.

### 5.5 Long-horizon choreography coherence

- **Audits.** Over a 30-min window, the sequence of package swaps
  + rotation-mode changes + scene-mode transitions forms a
  legible arc. Measured by: autocorrelation of the scene-mode
  signal (smooth → correlated; jumpy → uncorrelated), first-
  difference variance (churn indicator), and package-revisit
  interval distribution.
- **Metric.**
  `hapax_choreography_autocorrelation_30m`.
- **Pass.** Within programme-role envelope.

---

## §6. Director loop behaviors — short-term

Director loop = narrative director (`director_loop.py`, ~30 s)
emitting DirectorIntent + NarrativeStructuralIntent, coupled with
the structural director (`structural_director.py`, ~90 s) emitting
StructuralIntent. Both feed `compositional_consumer.py` which
dispatches ward.highlight, ward_emphasis, placement-bias, and
rotation overrides.

### 6.1 Per-tick dispatch correctness

- **Audits.** Every DirectorIntent that declares a
  NarrativeStructuralIntent results in a compositional-consumer
  dispatch within 2 ticks. Each dispatch resolves to a ward
  emphasis or ward highlight event in `ward-properties.json`.
- **Metric.** `hapax_director_dispatch_latency_ms`.
- **Pass.** p95 < 500 ms.

### 6.2 Intent frequency vs stimmung

- **Audits.** Intent rate per minute correlates with current
  stimmung state. Low-stimmung (calm) expects ≤ 2 intents/min;
  high-stimmung (SEEKING, hothouse) expects ≥ 4/min. Static audit
  checks "a counter exists"; dynamic audit checks the distribution
  tracks the state.
- **Metric.** `hapax_director_intent_rate_by_stimmung{state}`.
- **Pass.** Rate within per-state envelope.

### 6.3 Grounding-provenance populated (alpha 12.1 remediation)

- **Audits.** The alpha pre-live audit found 99.3% of 454 recent
  intents had empty `grounding_provenance`. Dynamic audit tracks
  the population rate over time and alerts when it drops below
  0.95 (spec mandates provenance on every intent OR an
  UNGROUNDED warning per §4.9 of the director spec).
- **Metric.** `hapax_director_grounding_populated_ratio` paired
  with `hapax_director_ungrounded_warnings_total`. Pattern-1
  discipline (paired hit/violation).
- **Pass.** Populated + UNGROUNDED together > 0.99.
- **Critical.** This is the identified constitutional invariant
  break as of 2026-04-20; gate-blocking until fixed.

### 6.4 Compositional-consumer dispatch rate observable (alpha 12.4
remediation)

- **Audits.** Alpha found that `compositional_consumer.dispatch`
  invocations are happening empirically (508 ward.highlight hits
  observed) but no explicit rate metric exists. Add the metric
  and track it.
- **Metric.** `hapax_compositional_consumer_dispatch_total{intent_type}`.
- **Pass.** Rate > 0.5 / minute for `ward.highlight`; > 0.2 for
  `ward_emphasis`; > 0.1 for `placement_bias`.

### 6.5 Three-decisions coupling

- **Audits.** The director emits three coupled decisions per tick:
  activity label, narrative utterance, compositional intent. The
  three must be mutually consistent — an activity of
  "deep_listening" cannot pair with a compositional intent of
  "burst rotation". Static audit enumerates the grammar; dynamic
  audit confirms live intents respect it.
- **Metric.** `hapax_director_triple_coherence_total` +
  `...violations_total`.
- **Pass.** Violation rate < 1% per 100 intents.

### 6.6 LLM call budget tracking

- **Audits.** Director LLM calls (typically claude-sonnet via
  LiteLLM `balanced` route) budgeted by cost. Audit tracks spend-
  per-minute and alerts on runaway.
- **Metric.** `hapax_director_llm_cost_usd_per_minute`.
- **Pass.** < operator-declared budget.

### 6.7 Kokoro-truncation rate

- **Audits.** Per audio-path baseline §4, `director_loop._synthesize`
  truncates at 400 chars. Healthy rate: ~0.25 truncations/min in
  current measurement. Dynamic audit confirms the rate is stable;
  a spike indicates the LLM is producing longer utterances than
  the cap supports, which is a quality signal.
- **Metric.** `hapax_director_kokoro_truncation_rate_per_min`.
- **Pass.** Stable within ±50% of baseline; spike triggers
  investigation.

---

## §7. Director loop behaviors — long-term

### 7.1 Director drift detection

- **Audits.** Across a 2-hour session, does the director revisit
  the same compositional moves? Measured by: Jaccard distance
  between 5-min tuple-sets of (activity, intent-family, ward-
  emphasis target). A healthy director explores; a drifting
  director repeats.
- **Metric.** `hapax_director_tuple_revisit_rate_per_hour`.
- **Pass.** < 0.3 (more than 70% of 5-min windows are novel
  combinations).

### 7.2 Do-nothing-interesting baseline preserved

- **Audits.** Regression test for task #158 CVS #19. When
  stimmung is calm and no impingement pressure exists, the
  director should emit do-nothing-interesting intents at the
  baseline rate. Dynamic audit confirms this state is reachable
  and sustained.
- **Metric.** `hapax_director_baseline_rate_per_minute` +
  `hapax_director_stance_dwell_time{stance=nominal}`.
- **Pass.** Baseline reachable ≥ once per 20-min window; dwell
  time envelope within programme spec.

### 7.3 Research-objective-driven steering visible

- **Audits.** When the operator sets a research objective
  (`objective_hero_switcher.py` active, objectives overlay
  showing), does the director's subsequent output visibly reflect
  it? Measured by semantic-distance between director utterances
  and objective text (embed, cosine, rolling 5-min mean).
- **Metric.** `hapax_director_objective_alignment_cosine`.
- **Pass.** > 0.5 for 5-min windows during active objective.

### 7.4 Anti-personification compliance sustained

- **Audits.** Static check via `lint_personification.py`. Dynamic
  check extends: over the live stream, director utterances pass
  the lint at a rate > 0.99. A per-session fail rate > 0.5%
  indicates model drift.
- **Metric.** `hapax_director_personification_violations_total`.
- **Pass.** Zero per session.

### 7.5 Structural director scene-mode coherence

- **Audits.** Structural director fires ~90 s; its `scene_mode`
  changes should persist long enough to be legible (minimum 3-5
  minutes) but not so long that the stream monotones. Dynamic
  audit tracks scene-mode dwell-time distribution.
- **Metric.** `hapax_structural_scene_mode_dwell_s_histogram`.
- **Pass.** p05 > 120 s; p95 < 900 s.

### 7.6 Intent-to-realisation conversion ratio

- **Audits.** Not every emitted intent reaches broadcast
  (choreographer may defer, emphasis may be preempted, budget may
  drop it). Track the ratio (realised / emitted).
- **Metric.**
  `hapax_director_intent_realisation_ratio_per_hour`.
- **Pass.** > 0.80. A falling ratio indicates the choreographer
  is overwhelmed.

---

## §8. Content programming behaviors — short-term

Per `2026-04-19-content-programming-layer-design.md`, programmes
are bounded, named, typed spans with planned duration, content
directives, and constraint envelope on director behavior below.
Operator memory: **programmes EXPAND affordances, not REPLACE**
(`feedback_no_expert_system_rules`, `project_programmes_enable_grounding`,
`feedback_hapax_authors_programmes`). Soft priors, not hard gates.

### 8.1 Programme dispatch firing

- **Audits.** When a programme is entered (per the programme
  timeline authored by Hapax), a dispatch event fires: the
  programme's content directives expand the affordance space (via
  boost to programme-aligned capabilities) and the per-layer
  constraint envelope applies to director choices.
- **Metric.** `hapax_programme_enter_total{programme_id}` +
  `hapax_programme_exit_total{programme_id}`.
- **Pass.** Every programme boundary produces exactly one enter
  and one exit event.

### 8.2 Affordance expansion NOT replacement

- **Audits.** Per memory, a programme must EXPAND the affordance
  catalog (boost scores for aligned capabilities) not REPLACE it
  (hard gate). Dynamic audit injects a capability not mentioned
  by the programme and confirms it is still recruitable with a
  reduced-but-nonzero probability.
- **Metric.** `hapax_programme_expansion_verification_total` —
  pass/fail per test injection.
- **Pass.** Test injection recruitable in > 10% of cycles even
  under a programme that doesn't mention the capability.
- **Critical.** A pass of "0%" means the programme is acting as
  a hard gate and the architectural invariant is broken.

### 8.3 Recruitment candidate surfacing

- **Audits.** The `recruitment_candidate_panel` ward cycles the
  top-3 affordance candidates for the current impingement. Audit
  confirms panel updates track the underlying recruitment state
  (not stale, not stuck).
- **Metric.**
  `hapax_recruitment_candidate_panel_cycling_hz`.
- **Pass.** > 0.1 Hz (at least one update per 10 s).

### 8.4 Programme-layer gating vs pure-emergence balance

- **Audits.** Track the fraction of director intents that are
  *within* the active programme's declared intent family vs
  *outside* it. A healthy programme shapes but does not prevent
  — 10-25% out-of-programme intents are expected (the soft-prior
  property).
- **Metric.**
  `hapax_director_in_programme_ratio{programme_id}`.
- **Pass.** Ratio in [0.75, 0.90]. Above 0.90 → programme is
  acting as hard gate. Below 0.75 → programme is ineffective.

### 8.5 Programme-internal dispatch cadence

- **Audits.** Programmes have a declared internal cadence (e.g.,
  `listening` programme: 45 s between transitions; `hothouse-
  pressure`: 20 s). Dynamic audit compares observed transition
  cadence to declared.
- **Metric.**
  `hapax_programme_dispatch_cadence_drift_pct{programme_id}`.
- **Pass.** ±20%.

### 8.6 Programme entry-exit ritual

- **Audits.** Per the programme layer design, programmes have
  entry and exit rituals (package swap, specific emphasis burst,
  narrative transition sentence). Audit confirms ritual fires on
  boundary.
- **Metric.**
  `hapax_programme_ritual_conformance_total{programme_id, boundary}`.
- **Pass.** Every boundary fires complete ritual.

---

## §9. Content programming behaviors — long-term

### 9.1 Programme exhaustion detection

- **Audits.** Does a programme deplete its affordance candidate
  pool? Over a 30-min `listening` programme, if the recruitment
  wins are concentrated on the same 2-3 capabilities, the
  programme has effectively exhausted its catalog. Measure
  Shannon entropy over recruitment wins per programme.
- **Metric.** `hapax_programme_recruitment_entropy_bits{programme_id}`.
- **Pass.** Entropy > 1.5 bits over programme lifetime.

### 9.2 Programme-author-is-Hapax invariant

- **Audits.** Per `feedback_hapax_authors_programmes`, programme
  authorship is fully Hapax-generated. Operator does NOT write
  programme skeletons / cue sheets. Audit statically confirms
  programme files in `~/hapax-state/programmes/` have the
  `author: hapax` frontmatter field AND dynamically confirms no
  operator-authored programmes ran during sessions.
- **Metric.** `hapax_programme_author_invariant_violations_total`.
- **Pass.** Zero.

### 9.3 Programme-as-soft-prior invariant

- **Audits.** Complement to §8.2 for long-term. Over a 2-hour
  session, the aggregate in-programme ratio (weighted across
  programmes) sits in the soft-prior band [0.75, 0.90]. An
  aggregate trend below 0.75 means programmes aren't shaping; a
  trend above 0.90 across many sessions means programmes have
  crystallised into gates.
- **Metric.**
  `hapax_programme_soft_prior_ratio_per_session`.
- **Pass.** In [0.75, 0.90].
- **Long-term view.** Session-over-session trend; drift toward
  hard gates is a systemic regression.

### 9.4 Programme library diversity

- **Audits.** Over a week or month, does Hapax generate a
  diverse programme library or does it crystallise to 3-4
  archetypes? Measured by pairwise semantic distance between
  generated programmes.
- **Metric.**
  `hapax_programme_library_diversity_cosine_weekly`.
- **Pass.** Mean pairwise distance > 0.3.

### 9.5 Programme sequencing coherence

- **Audits.** Does a 2-h show's programme sequence form a coherent
  arc? Rising arc, flat, declining, and episodic patterns are all
  valid but a random-walk ordering is not. Measured by
  programme-role-sequence regularity against expected show
  shapes (opening → work-block → interlude → pressure → wind-
  down).
- **Metric.**
  `hapax_programme_sequence_arc_score_per_session`.
- **Pass.** Score > threshold (tuned from replay).

### 9.6 Content grounding vs ungrounded expansion

- **Audits.** Per `project_programmes_enable_grounding`, programmes
  should EXPAND grounding opportunities — give the system more
  surfaces to ground against. Audit measures grounding rate
  within programme (from §6.3) — it should increase, not
  decrease.
- **Metric.**
  `hapax_director_grounding_populated_ratio_by_programme`.
- **Pass.** Ratio during programme ≥ ratio outside programme.

---

## §10. Audio interaction audits — clean, intentional, director-driven

The operator's test: "is the mix ALWAYS good?" For this to be a
testable invariant, "good mix" must have a measurable definition.
The proposal: every audible thing reaching broadcast is either (a)
operator-intended, or (b) Hapax-driven via director loop /
content programme. Silence is a positive choice, not a failure.

### 10.1 Definition of a "mix-quality" score

A continuous per-second score `MixQuality(t) ∈ [0, 1]` computed as
a weighted product of six sub-signals:

```
MixQuality(t) = w_loudness  · Loudness(t)
              · w_balance   · Balance(t)
              · w_clarity   · SpeechClarity(t)
              · w_intent    · Intentionality(t)
              · w_dynamics  · DynamicRange(t)
              · w_coherence · AVCoherence(t)
```

Each sub-signal is [0,1]. Weights operator-tuned. Default:
`w_intent=0.25, w_clarity=0.2, w_loudness=0.15, w_balance=0.15,
w_dynamics=0.15, w_coherence=0.1`. Rationale: intentionality is
the operator's primary concern; clarity is the audience's.

### 10.2 Loudness — EBU R128

- **What it audits.** Integrated loudness (-23 LUFS ±1 LU), short-
  term 3-s loudness (no 5-s window above -12 LUFS), true peak
  (-1 dBTP ceiling), loudness range (per EBU R128 s2 streaming
  supplement, 5..20 LU).
- **Reference.** Per EBU R128 s2, streaming is targeted at -18
  LUFS for YouTube; ±1 LU tolerance for live. See
  `docs/research/` external citations section.
- **Metric.** `hapax_broadcast_lufs_integrated`,
  `hapax_broadcast_lufs_short_term`,
  `hapax_broadcast_true_peak_dbtp`,
  `hapax_broadcast_lra_lu`.
- **Loudness(t)** score: 1.0 inside spec, smooth falloff outside.
- **Cadence.** continuous (10 Hz short-term per R128 spec).

### 10.3 Balance — per-source RMS envelope

- **What it audits.** Operator mic, TTS, YT, vinyl, contact-mic
  each at declared target level. Operator mic sits above TTS
  which sits above any music source by declared margins (typically
  operator mic -12 dBFS, TTS -15 dBFS, music -22 dBFS during
  speech).
- **Metric.** `hapax_broadcast_source_rms_dbfs{source}` at 10 Hz.
- **Balance(t)** score: product of per-pair margin compliances.
- **Cadence.** continuous.

### 10.4 Speech clarity — concurrent-speaker detection

- **What it audits.** When operator speaks AND TTS speaks AND a
  music source plays AND chat ambient is audible, is the speech
  still intelligible? Proxy via VAD output for each source;
  speech-over-speech penalises clarity.
- **Metric.** `hapax_broadcast_concurrent_speech_rate_per_minute`.
- **SpeechClarity(t)** score: 1.0 when ≤1 voice active, 0.6 when
  2, 0.2 when 3+.
- **Cadence.** continuous.

### 10.5 Intentionality — every audible thing has a source tag

- **What it audits.** Every audible chunk reaching broadcast is
  tagged with its source: operator-mic, tts, yt-player-slot-N,
  vinyl, contact-mic, chime, fx-overlay. Any untagged audio is
  a mix-quality violation — either an accidental bleed or a
  missing wiring tag.
- **Metric.** `hapax_broadcast_untagged_audio_rate_pct`.
- **Intentionality(t)** score: 1.0 - untagged_rate; floor at 0.
- **Cadence.** continuous.

### 10.6 Dynamic range — PLR and session-level dynamics

- **What it audits.** Per-session PLR (peak-to-loudness ratio)
  and LRA (loudness range). Streaming platforms normalise loudness
  but reward dynamics; a stream with LRA ≈ 2 LU sounds flat and
  compressed; LRA ≈ 15 sounds dynamic and clear.
- **Metric.** `hapax_broadcast_plr_per_minute`,
  `hapax_broadcast_lra_per_5_min`.
- **DynamicRange(t)** score: 1.0 when LRA in [5, 15].
- **Cadence.** per-minute and per-5-min.

### 10.7 AV-coherence — audio tracks what's visually emphasised

- **What it audits.** §13 (cross-surface coherence) drives this
  sub-signal. When the director visually emphasises track T, the
  audio level of track T rises (or competing sources duck).
  Coherence is the correlation between declared visual emphasis
  and observed audio levels at the 1-s resolution.
- **Metric.** `hapax_av_coherence_correlation_1s`.
- **AVCoherence(t)** score: coherence coefficient.
- **Cadence.** continuous.

### 10.8 The aggregate "mix is always good" test

- **Pass.** `MixQuality(t) > 0.7` for > 95% of stream-seconds;
  `MixQuality(t) > 0.85` for 5-min moving average > 90% of
  windows; no stream-second below 0.3 (catastrophic).
- **Operator veto.** On replay, operator subjectively listens to
  any stream-second where MixQuality < 0.7 and confirms the
  score tracks their ear. Calibration loop tunes weights.
- **Cadence.** continuous (score); per-stream (aggregate pass).

---

## §11. Specific director-driven and programme-driven audio audits

### 11.1 Director-driven ducking

- **Audits.** When Hapax decides to speak (CPAL impingement → TTS
  emit), the AudioDuckingController (`audio_ducking.py:116`) FSM
  transitions normal → voice_active (or yt_active →
  both_active), the YT source audio ducks within a declared tail
  (typically 100-200 ms attack, 300-500 ms release), and the
  voice-over-ytube-duck.conf PipeWire filter chain applies sink-
  level gain modulation.
- **Why.** Alpha 4.4 incident: `voice-over-ytube-duck.conf`
  MISSING. Multi-layer duck (producer publishes state → FSM
  transitions → PipeWire filter → youtube-player wpctl re-mute)
  requires ALL layers. Static §4.9 checks "file exists";
  dynamic audit checks the duck audibly happens.
- **Metric.** `hapax_duck_applied_total{from_state, to_state}`,
  `hapax_duck_attack_ms_p95`, `hapax_duck_release_ms_p95`,
  `hapax_duck_magnitude_db_p50`.
- **Pass.** Attack < 200 ms p95; release < 500 ms p95; magnitude
  ≥ 6 dB (audible duck).

### 11.2 Director-driven audio emphasis

- **Audits.** When the director decides to highlight a track
  (narrative: "turn this one up"), the corresponding audio
  source's level rises and others duck. Extends §11.1 from
  binary-duck to graded-emphasis.
- **Metric.** `hapax_audio_emphasis_events_total{source}`,
  `hapax_audio_emphasis_realisation_ratio` (did the level
  actually change?).
- **Pass.** Realisation ratio > 0.95.

### 11.3 Content-programming-driven mix shifts

- **Audits.** Programmes declare level profiles — a `listening`
  programme brings instrumentation forward and TTS down; a
  `hothouse-pressure` programme raises TTS and ducks music.
  Audit confirms programme entry triggers the level shift and
  programme exit restores the default.
- **Metric.**
  `hapax_programme_level_shift_conformance_total{programme_id}`.
- **Pass.** Every programme boundary produces the declared
  level-shift within 2 s.

### 11.4 Multi-source sync quality

- **Audits.** When operator + TTS + YT + vinyl are all active,
  the mix retains intelligibility. Extends §10.4. Test with
  synthetic four-source overlap and score per MixQuality(t).
- **Metric.** Covered by §10 aggregate under worst-case load.
- **Pass.** MixQuality > 0.6 even under four-source overlap.

### 11.5 Silence as a positive choice

- **Audits.** When the director decides not to speak (intent
  family: `do-nothing-interesting`), the silence should be
  deliberate — operator mic off-air OR TTS silent OR both — not
  an accidental absence caused by TTS failing. Distinguish via
  the director-intent record: if `last_intent.family ==
  "do_nothing" && broadcast_silence_duration > 0`, it's a
  positive choice; if `last_intent.family == "speak" &&
  broadcast_silence_duration > 0`, it's a TTS failure.
- **Metric.** `hapax_intentional_silence_total` vs
  `hapax_failed_tts_silence_total`.
- **Pass.** Ratio intentional / total-silence > 0.9.

### 11.6 YT audio ducking sink-level verification

- **Audits.** Specifically targets alpha 4.4 — confirm
  `voice-over-ytube-duck.conf` installed AND active AND applying
  gain when voice detected. Dynamic audit beyond static "file
  exists" check: RMS sample of YT source during a voice event
  should show 6-20 dB reduction.
- **Metric.** `hapax_yt_duck_sink_level_reduction_db_p50`.
- **Pass.** > 6 dB during voice events.

### 11.7 Ducking release not swallowed by next intent

- **Audits.** A pathological case: if TTS emits back-to-back
  utterances with gaps < 500 ms, the duck never releases and
  the audience misses the YT content entirely. Audit tracks
  duck-release-ratio over a 5-min window.
- **Metric.** `hapax_duck_release_ratio_per_5m` — total
  release-duration / total window.
- **Pass.** > 0.3 (the YT source is heard at full level at least
  30% of the window).

### 11.8 Operator-mic bleed into TTS path

- **Audits.** Operator voice must not bleed into the TTS path
  (causes echo into operator's headphones). Detect by
  cross-correlation between operator-mic signal and
  TTS-synthesis-output.
- **Metric.** `hapax_mic_to_tts_bleed_correlation`.
- **Pass.** < 0.1.

---

## §12. Audio long-term

### 12.1 Mix-quality drift across 2-hour stream

- **Audits.** Plot `MixQuality(t)` across a full session; look
  for systematic drift. A healthy session shows variance around
  a stable mean; a drifting session shows a declining trend
  (mix degrades as session progresses — operator fatigue,
  level drift, DSP accumulator error).
- **Metric.** `hapax_mix_quality_linear_trend_per_hour`.
- **Pass.** |slope| < 0.05 per hour.

### 12.2 End-to-end latency chain

- **Audits.** Operator speech → impingement → director → TTS →
  broadcast. Budget: < 3 s. Chat ambient → token pole update →
  visual emphasis → audio emphasis. Budget: < 10 s.
- **Metric.**
  `hapax_e2e_latency_chain_ms_p95{chain}`.
- **Pass.** Within declared budget per chain.

### 12.3 Vinyl / YT source exhaustion

- **Audits.** When a vinyl side ends or a YT playlist completes,
  the system should detect, alert, and offer the next source.
  Audit tracks detection latency.
- **Metric.** `hapax_source_exhaustion_detection_latency_s`.
- **Pass.** < 5 s.

### 12.4 Music-taste drift

- **Audits.** Per operator memory "stick to operator's curated
  music taste", the system's auto-queued tracks should track
  the operator's declared curation. Measured by cosine distance
  between queued-track embeddings and operator-curated-playlist
  embeddings.
- **Metric.** `hapax_music_taste_drift_cosine_per_session`.
- **Pass.** > 0.8.

### 12.5 Loudness drift across session

- **Audits.** Integrated loudness is session-level. Audit tracks
  session-integrated LUFS and per-10-min-block LUFS.
  Per-block drift signals a mix problem.
- **Metric.** `hapax_loudness_per_block_lufs`,
  `hapax_loudness_block_variance_lu`.
- **Pass.** Variance < 3 LU across session.

### 12.6 Silence-share across session

- **Audits.** Fraction of stream-seconds with broadcast-RMS <
  -50 dBFS. Healthy: 10-25% (natural breath / intentional
  silence). Unhealthy: < 5% (too busy, operator never rests)
  or > 35% (dead air).
- **Metric.** `hapax_broadcast_silence_share_per_session`.
- **Pass.** In [0.10, 0.25].

---

## §13. Cross-surface coherence (audiovisual coherence)

A new audit class emerging from the operator's insistence that the
mix is clean AND the visual surface is coherent. The two must agree:
when visual emphasises track A, audio brings track A forward; when
visual de-emphasises track A, audio ducks it. Divergence is a class
of misbehavior invisible to either axis alone.

### 13.1 Director decision → audio and visual both respond

- **Audits.** Sample director intents over a 5-min window; for
  each intent, verify that visual and audio both moved in the
  declared direction.
- **Metric.** `hapax_av_coherence_per_intent_pass_rate`.
- **Pass.** > 0.9.

### 13.2 Emphasis-envelope audio pairing

- **Audits.** When a ward is emphasised AND the ward corresponds
  to an audio source (token_pole ↔ TTS / narration, album ↔
  music source, captions ↔ operator voice), the audio source's
  level follows the emphasis envelope.
- **Metric.** `hapax_ward_audio_pairing_correlation`.
- **Pass.** > 0.6 for paired wards.

### 13.3 Silence-vs-visual paradox detection

- **Audits.** If the visual surface shows a lot of activity (many
  active wards, high RD variance, fast package swaps) but the
  audio is silent, the experience is dissonant. Conversely, loud
  audio with frozen visual is also dissonant.
- **Metric.** `hapax_av_energy_balance_ratio` — (audio RMS
  rolling-mean) × (visual motion rolling-mean).
- **Pass.** Ratio within [0.2, 5.0] (neither axis dominates).

### 13.4 Temporal offset between visual and audio emphasis

- **Audits.** Visual emphasis and audio emphasis should arrive
  within a perceptual-binding window (~200 ms). Detect via
  cross-correlation of visual-emphasis-timestamps and
  audio-level-change-timestamps.
- **Metric.** `hapax_av_temporal_offset_ms_p95`.
- **Pass.** < 200 ms.

### 13.5 Cross-surface budget coherence

- **Audits.** When the BudgetTracker is at 90% and compositor is
  struggling, audio should also degrade gracefully rather than
  pressing onward. Not covered by current infra; new instrument.
- **Metric.** `hapax_av_budget_coupling_coherence`.
- **Pass.** When compositor degraded, audio-only-critical path
  (operator + TTS) continues; non-critical (YT playback at full
  bandwidth) degrades.

---

## §14. Livestream-as-research-instrument integrity

Per operator memory `project_livestream_is_research`, **all R&D
happens via livestream**. Per LRR phases 4 + 8, the livestream IS
the research instrument. Dynamic audits verify this constitutive
property, not just the system's surface properties.

### 14.1 Research objective visibility

- **Audits.** When an operator research objective is active (per
  `objectives_overlay.py`), it is visible on stream (overlay
  rendered) AND it is driving director behavior (§7.3 coherence
  metric) AND it is feeding the chronicle record.
- **Metric.** `hapax_research_objective_three_path_conformance`.
- **Pass.** All three paths green per objective-active minute.

### 14.2 Chronicle population rate

- **Audits.** The chronicle (`hapax-state/chronicle/`) receives
  runtime-observed events at declared rate. Dynamic audit tracks
  chronicle write rate per minute vs expected.
- **Metric.** `hapax_chronicle_write_rate_per_minute`.
- **Pass.** Within declared envelope.

### 14.3 Research-condition currency

- **Audits.** The active research condition
  (`hapax-state/research-registry/<id>/condition.yaml`) has
  non-expired scope; its declared frozen files match runtime;
  observations from this session attach correctly.
- **Metric.** `hapax_research_condition_currency_score`.
- **Pass.** > 0.95.

### 14.4 Measure timeseries attribution

- **Audits.** Per LRR sprint measures, this session's observations
  attach to the correct measure row; no orphan rows; no duplicate
  attachments.
- **Metric.** `hapax_measure_attribution_integrity_total`.
- **Pass.** Zero orphans or duplicates per session.

### 14.5 Condition-id propagation to every artefact

- **Audits.** Every artefact produced during session (v42 frame
  archive pointer, chronicle entry, qdrant write, chat archive)
  carries the active condition_id. Missing condition_id means
  the observation cannot be attributed.
- **Metric.**
  `hapax_condition_id_propagation_coverage_ratio`.
- **Pass.** > 0.99.

### 14.6 Hypothesis-conclusion record integrity

- **Audits.** When a hypothesis is declared at session start and
  a conclusion is declared at end, both are recorded and linked
  to the condition.
- **Metric.** `hapax_hypothesis_conclusion_linkage_per_session`.
- **Pass.** One hypothesis-conclusion pair per session when
  applicable.

---

## §15. Emergent misbehavior detectors

The 14:08 TTS leak was emergent — no single-tick check would have
caught it. Emergent misbehaviors require sliding-window pattern
detectors. Seven classes proposed:

### 15.1 Rapid preset cycling detector

- **Audits.** Preset family changes > 3 times in a 60-s window.
  Signature of an unstable structural director.
- **Metric.** `hapax_preset_family_change_rate_per_minute`.
- **Pass.** ≤ 3 per minute sustained.
- **Failure action.** Throttle the structural director; alert.

### 15.2 Ward flashing epilepsy-triggering frequency

- **Audits.** No ward pulses at 3-55 Hz (W3C photosensitive-
  epilepsy guidance) for > 0.5 s continuously. A glow_radius +
  border_pulse combination at 6 Hz sustained is an accessibility
  violation AND a health hazard.
- **Metric.** `hapax_ward_risky_frequency_violations_total`.
- **Pass.** Zero.

### 15.3 Stuck-frame detector

- **Audits.** Inter-frame pixel-delta below a floor for > 2
  seconds (silent compositor pump failure — frames flowing but
  no content change). Distinguishes from legitimate still
  frames by checking whether source signals were advancing
  while the frame was static.
- **Metric.** `hapax_stuck_frame_total`.
- **Pass.** Zero per session.

### 15.4 Silent compositor (render-but-no-motion)

- **Audits.** Reverie pool_reuse_ratio > 0 AND compositor frames
  publishing AND ward-properties updating AND /dev/video42 fresh
  BUT inter-frame pixel-delta below floor. Degenerate combo
  flags a late-stage freeze.
- **Metric.** `hapax_silent_compositor_total`.
- **Pass.** Zero.

### 15.5 Overlap-cascade detector

- **Audits.** A chain of emphasis-envelope triggers that never
  resolve — ward A emphasised triggers ward B emphasised triggers
  ward A again, ad infinitum. Detect via emphasis-event graph
  cycles.
- **Metric.**
  `hapax_emphasis_cycle_chain_depth_p99`.
- **Pass.** < 5 (no chain deeper than 5 hops).

### 15.6 Director monoculture detector

- **Audits.** Director emits the same (intent_family, ward_target)
  pair > 5 times in a row. Indicates the director has stalled on
  one compositional move.
- **Metric.** `hapax_director_intent_monoculture_runs_total`.
- **Pass.** Zero runs ≥ 5.

### 15.7 Audio-visual disagreement accumulation

- **Audits.** Per §13, `av_coherence_correlation_1s` below
  threshold for > 60 s. Indicates the director's spoken
  intentions are out of sync with the surface.
- **Metric.** `hapax_av_disagreement_duration_s_p99`.
- **Pass.** < 60 s.

### 15.8 Slur-variant emergence

- **Audits.** LLM emits a token matching the slur-variant
  regex (widened per 303e5fd2a) AT ALL — even if caught by gate.
  Rising rate indicates prompt-level (task #165) not yet
  effective.
- **Metric.**
  `hapax_llm_slur_variant_emissions_per_hour`.
- **Pass.** < 1 per hour (decreasing trend expected post-165).
- **Critical.** This is the 14:08 archetype; tracking the
  emission, not just the gate hit, is what makes the silent
  break observable.

---

## §16. Short-loop vs long-loop observability split

### 16.1 Must be real-time (audience-visible issues)

All of these require ≤ 10-s detection latency because the audience
sees / hears the issue immediately:

- §1.1 legibility, §1.2 hero coherence, §1.4 motion smoothness
- §2.1 palette fidelity, §2.2 marker presence
- §3.5 emphasis envelope, §3.6 signal response
- §6.1 dispatch correctness, §6.3 grounding provenance (critical)
- §10.2 loudness, §10.4 clarity, §10.5 intentionality
- §11.1 ducking, §11.5 silence-as-choice
- §15 all detectors

Implementation: Prometheus gauge, scraped at 1-s interval,
Grafana alert with ntfy routing.

### 16.2 Can be near-real-time (ops-visible issues)

- §1.5 monotony, §5.1 fairness, §5.4 salience redistribution
- §6.2 intent-frequency vs stimmung, §6.7 truncation rate
- §8.4 programme-layer gating, §11.4 multi-source sync

Implementation: Prometheus + 30-s scrape, alert at 5-min window.

### 16.3 Can be post-hoc (research and drift)

- §1.6 aesthetic evolution, §1.8 degraded sequence
- §5.5 long-horizon choreography, §7.1 director drift
- §9.1 programme exhaustion, §9.3 soft-prior invariant
- §12.1 mix-quality drift, §12.4 music-taste drift
- §14.2 chronicle population

Implementation: daily scheduled job (`/home/hapax/.cache/hapax/
dynamic-audit.d/`), replay-on-recording.

### 16.4 Continuous-only vs on-demand

- **Continuous** — must run always: §1.1, §2.1, §3.5, §6.3, §10,
  §11.1, §15.
- **On-demand** — run on explicit trigger: §1.8 degraded sequence
  replay, §5.5 choreography coherence (recurring analysis), §9.1
  programme exhaustion, §14.6 hypothesis-conclusion linkage.

---

## §17. Testing infrastructure

### 17.1 Livestream replay harness

The 18-section dynamic catalog needs a *replay* mode: run audits
against a recorded session, not a live one. Required for §16.3
post-hoc audits and for regression testing of fixes.

- **Architecture.** Session records retained in
  `~/hapax-state/session-recordings/<date>/`: v42 frame archive
  (1 fps keyframe + motion deltas), broadcast audio
  (-18 LUFS WAV at 48 kHz), director-intent jsonl, ward-properties
  snapshots at 1 Hz, SHM publisher logs. Not long-term retained
  (disabled archival per CLAUDE.md) — retained only for the
  immediate post-session window.
- **Replay engine.** `scripts/replay-session.py` re-plays the
  jsonl streams against the audit suite, producing the same
  Prometheus counters as live.
- **Regression usage.** When a bug is fixed, the session where
  the bug manifested is replayed; audits must now pass.

### 17.2 Frame-by-frame diff against goldens

Extends static §3.1 golden-image to motion: per-second delta
against "expected motion envelope" rather than expected pixel
values. Goldens become motion-signatures, not frame-signatures.

- **Implementation.** `tests/studio_compositor/golden_motion/`
  per ward. Each golden is a 10-s RGBA-delta sequence.
- **Metric.** Per-ward motion-delta cosine to golden.
- **Pass.** > 0.85.

### 17.3 Audio-spectral comparison

For mix-quality audits in §10-12, spectral analysis of the
broadcast audio against per-source spectral signatures:
operator mic (typically 200-8000 Hz speech band), TTS (Kokoro
signature 100-10000 Hz), music (full band), vinyl (below 50 Hz
rumble possible). Any unexpected spectrum (ground-loop hum at
60 Hz, USB noise spike) raises a flag.

- **Implementation.** FFT on broadcast audio in 100-ms windows;
  compare against per-source signatures.
- **Metric.** `hapax_broadcast_spectrum_anomaly_score`.

### 17.4 Longitudinal dashboard

A single Grafana dashboard plotting the key per-stream scores
across the session history: MixQuality, director coherence,
programme-soft-prior-ratio, aesthetic-fingerprint-diff. Operator
reads at week boundary to detect drift patterns invisible at
session granularity.

- **Location.** `grafana/dashboards/livestream-longitudinal.json`.
- **Data source.** Prometheus with 90-day retention plus
  PostgreSQL-backed per-session record.

### 17.5 Synthetic livestream harness

For pre-live warmup (§18) and for CI regression: a deterministic
synthetic session that exercises every ward, emphasis envelope,
package swap, programme transition, and audio configuration. 15
minutes, reproducible, pass/fail per audit row.

- **Location.** `scripts/synthetic-livestream.py`.
- **Fixtures.** Controlled impingement injections, fake YT
  source, fake vinyl source, fake operator mic VAD.

### 17.6 Chaos testing

For resilience: randomly inject faults during a synthetic session
(OOM, USB bus-kick, shader-recompile stall, face-obscure detector
crash) and assert the audit row for that failure mode passes
(the degraded behavior is correct).

- **Location.** `scripts/chaos-synthetic-livestream.py`.

### 17.7 Property-based testing for invariants

Per Hypothesis library (council-standard), invariants like
"every director intent has populated grounding_provenance OR an
UNGROUNDED warning" expressed as properties, then tested against
random generated intent streams.

### 17.8 Replay-based emergent-misbehavior hunt

Periodically replay the past N sessions and apply the §15
emergent-misbehavior detectors; any detector that fires on a
past session that was considered healthy indicates the detector
is newly catching a latent pattern (good) OR the detector is
mis-calibrated (tune).

---

## §18. Pre-live gate integration

The static catalog's §17 top-priority gate has 30 rows and is
configuration-shaped. The dynamic catalog adds a **warmup
protocol**: a 15-min synthetic livestream runs before any real
session, the synthetic session is audited against the dynamic
catalog, and the green-verdict is the go-live predicate.

### 18.1 Warmup protocol

```
T-15:00  operator triggers pre-live warmup via Stream Deck button
T-15:00  scripts/synthetic-livestream.py starts; all ward
         producers publish, shaders compile, RTMP test-push to
         local MediaMTX (not YouTube)
T-15:00  dynamic-audit-suite starts scraping; 15-min window
T-13:00  synthetic programme 1 (listening) enters; programme-
         boundary audits fire
T-10:00  package swap triggered; §2.4 swap grammar audit
T-08:00  synthetic hostile chat injection; §1.2 sibling check
         plus §15.7 slur-variant detector
T-06:00  synthetic multi-source audio overlap; §10 MixQuality,
         §11.1 ducking under contention
T-04:00  synthetic degradation triggered; §1.8 degraded pattern
T-02:00  synthetic recovery; system returns to normal
T-00:30  warmup session ends; audit verdict computed
T-00:30  if green → live-egress unlock; operator may start real
         stream
```

### 18.2 Warmup verdict

Gate passes iff:
1. Every §16.1 continuous gauge was in-spec for > 95% of warmup.
2. Every §16.2 near-real-time audit passed at least once.
3. Every §15 emergent-misbehavior detector returned zero hits.
4. MixQuality(t) mean > 0.85 across warmup.
5. No `hapax_director_grounding_populated_ratio` < 0.95 event.
6. No `hapax_programme_expansion_verification_total` fails.

### 18.3 Warmup verdict failure handling

On red verdict, operator sees: (a) which rows failed, (b) which
of the static-catalog §17 remediations are relevant, (c) option
to force-bypass with explicit `--force` + justification logged.

### 18.4 Relation to static pre-live gate

The static gate (30 rows) runs FIRST; if green, the warmup
harness runs; if warmup green, go live. Two-stage pass.

### 18.5 Warmup-to-real transition

At T-0, the audit suite continues running against the real
session, re-scoped to `stream-type=real` labels. Prometheus
dashboards segment warmup data from real data.

---

## §19. Operator-action items (human-in-the-loop)

Some audits cannot be automated. These are dynamic equivalents of
the static catalog's semi-automated rows. Enumerate specifically
what the operator alone can verify:

### 19.1 Aesthetic judgment

- Does the stream feel right? The composite surface has a
  subjective quality that no automated audit captures. After a
  15-min warmup session, the operator samples 3 consecutive
  minutes and confirms or rejects.
- **Cadence.** pre-live (warmup sample).

### 19.2 Mix ear-check

- Operator listens on monitor speakers (or reference headphones)
  to a 2-min synthetic-four-source-overlap and confirms the mix
  is good. Calibrates MixQuality weights; operator is ground
  truth.
- **Cadence.** pre-live + monthly recalibration.

### 19.3 Programme flow feel

- Does the programme transition sequence read as a coherent
  show? Read the programme timeline (authored by Hapax per
  §9.2); does the operator agree with the sequence?
- **Cadence.** pre-live.

### 19.4 Director utterance veto

- Operator reads a 5-intent sample of director utterances
  from the immediately prior session and flags anything that
  felt wrong: miscalibrated tone, incorrect grounding reference,
  off-topic. Feeds the tuning loop.
- **Cadence.** per-session end (10 min).

### 19.5 Package-choice audit

- Operator confirms the active HomagePackage matches their
  intended aesthetic for the session. Mis-package choice
  cascades into every ward and cannot be auto-detected.
- **Cadence.** pre-live.

### 19.6 Subjective intentionality check

- For a 5-min sample of the stream, the operator listens and
  identifies any audio chunk that felt unintentional. Each such
  chunk is a §10.5 intentionality violation the automated
  tagger missed.
- **Cadence.** per-session (post).

### 19.7 Eye-gut coherence check

- Operator watches 3 min of stream in monitor mode and confirms
  visual and audio agree. Disagreement not caught by §13
  metrics is a calibration signal.
- **Cadence.** per-session.

### 19.8 Camera framing

- Operator confirms each camera's framing is broadcast-ready
  (operator-preferred composition, non-sensitive background,
  lighting acceptable). Per operator cadence — rig-migration
  warrants full re-check.
- **Cadence.** pre-live; rig-change.

---

## §20. Open questions (max 5)

### 20.1 MixQuality weight calibration

The weights in §10.1 are proposed but not operator-calibrated.
Calibration requires a replay loop: operator listens to past
sessions, scores subjectively, regression fits weights. Open:
when is this calibration work scheduled? Does it need a pre-live
precedent?

### 20.2 Programme-authored-by-Hapax invariant measurement

Operator memory says "programme authorship is fully
Hapax-generated". How is this enforced at the code level today?
The §9.2 audit is proposed but the current implementation
surface is thin — if the operator hand-edits a programme file
to tune test behavior, is that acceptable? What is the boundary
between operator-authored constraint and operator-authored
programme?

### 20.3 Pre-live warmup duration

15 minutes proposed; is that long enough to surface the slow
emergent misbehaviors (§15) that only appear after 30+ minutes?
A 2-hour warmup obviously defeats the point. Trade-off
unresolved.

### 20.4 Post-hoc audit replay storage retention

Archival is disabled per consent / axiom policy. Replay-based
audits need the past session. How long does the session-
recording pocket retain (e.g., N days)? What is deleted
immediately vs retained? Needs explicit policy bake.

### 20.5 Degraded-stream MixQuality floor

Per operator directive "HOMAGE go-live + live-iterate via
DEGRADED-STREAM mode", degraded state is first-class. What
MixQuality floor is acceptable during degraded? 0.5? 0.6?
Below the healthy-state 0.7? Whatever the number is must be
declared pre-live, not discovered mid-stream.

---

## Appendix A. Summary table — 104 dynamic audit classes

| § | Class | Cadence | Critical path | Alpha-pre-live-link |
|---|-------|---------|---------------|---------------------|
| 1.1 | Legibility | continuous | yes | — |
| 1.2 | Hero coherence | continuous | yes | — |
| 1.3 | Safe-area dynamic | continuous | yes | static §3.7 |
| 1.4 | Motion smoothness | continuous | yes | — |
| 1.5 | Monotony resistance | per-minute | no | — |
| 1.6 | Aesthetic evolution | per-stream | no | — |
| 1.7 | Package-swap smoothness | per-event | yes | static §3.4 |
| 1.8 | Degraded pattern | per-event | yes | — |
| 2.1 | Palette fidelity | continuous | yes | — |
| 2.2 | Marker presence | continuous | no | — |
| 2.3 | Font crispness | continuous | no | — |
| 2.4 | Swap grammar | per-event | yes | — |
| 2.5 | Fatigue resistance | per-stream | no | — |
| 2.6 | HARDM fairness | per-stream | no | — |
| 3.1 | Per-ward palette | continuous | yes | — |
| 3.2 | Typography drift | continuous | no | — |
| 3.3 | Animation cadence | continuous | no | — |
| 3.4 | FSM coverage | continuous | no | static §3.5 |
| 3.5 | Emphasis envelope | continuous | yes | static §3.6 |
| 3.6 | Signal responsiveness | continuous | yes | — |
| 3.7 | Runtime non-overlap | continuous | yes | — |
| 3.8 | Content sufficiency | continuous | yes | — |
| 4.1 | Recruitment rate | per-minute | no | — |
| 4.2 | Envelope decay | per-event | yes | — |
| 4.3 | Signal render coverage | continuous | yes | — |
| 4.4 | RD tempo | continuous | no | — |
| 4.5 | HARDM ripple | per-event | no | — |
| 5.1 | Ward fairness | per-hour | no | — |
| 5.2 | Burn-in detection | per-5min | yes | — |
| 5.3 | Dormancy decay | per-10min | no | — |
| 5.4 | Salience redistribution | per-event | no | — |
| 5.5 | Choreography coherence | per-30min | no | — |
| 6.1 | Per-tick dispatch | continuous | yes | — |
| 6.2 | Intent-frequency | per-minute | no | — |
| 6.3 | Grounding populated | continuous | **CRITICAL** | alpha 12.1 |
| 6.4 | Consumer dispatch rate | continuous | yes | alpha 12.4 |
| 6.5 | Triple coherence | per-minute | yes | — |
| 6.6 | LLM cost | per-minute | no | — |
| 6.7 | Truncation rate | per-minute | no | baseline §4 |
| 7.1 | Director drift | per-hour | no | — |
| 7.2 | Baseline preserved | per-session | yes | task #158 |
| 7.3 | Objective steering | per-minute | yes | — |
| 7.4 | Personification | continuous | yes | — |
| 7.5 | Scene-mode dwell | per-session | no | — |
| 7.6 | Realisation ratio | per-hour | yes | — |
| 8.1 | Programme dispatch | per-event | yes | — |
| 8.2 | Expansion NOT replacement | per-event | **CRITICAL** | memory invariant |
| 8.3 | Candidate cycling | continuous | no | — |
| 8.4 | Soft-prior balance | per-hour | **CRITICAL** | memory invariant |
| 8.5 | Internal cadence | per-event | no | — |
| 8.6 | Ritual conformance | per-event | no | — |
| 9.1 | Exhaustion detection | per-programme | yes | — |
| 9.2 | Author-is-Hapax | per-session | **CRITICAL** | memory invariant |
| 9.3 | Soft-prior sustained | per-session | yes | — |
| 9.4 | Library diversity | weekly | no | — |
| 9.5 | Sequence coherence | per-session | no | — |
| 9.6 | Grounding within programme | per-programme | yes | — |
| 10.2 | R128 loudness | continuous | yes | — |
| 10.3 | Source balance | continuous | yes | — |
| 10.4 | Speech clarity | continuous | yes | — |
| 10.5 | Intentionality tags | continuous | yes | — |
| 10.6 | PLR / LRA dynamics | per-minute | no | — |
| 10.7 | AV coherence | continuous | yes | — |
| 10.8 | MixQuality aggregate | continuous | yes | — |
| 11.1 | Director-driven duck | per-event | yes | alpha 4.4 |
| 11.2 | Audio emphasis realisation | per-event | yes | — |
| 11.3 | Programme-driven level shifts | per-event | yes | — |
| 11.4 | Multi-source sync quality | continuous | yes | — |
| 11.5 | Silence as choice | continuous | yes | — |
| 11.6 | Sink-level duck verified | per-event | yes | alpha 4.4 |
| 11.7 | Duck-release ratio | per-5min | no | — |
| 11.8 | Mic-TTS bleed | continuous | no | — |
| 12.1 | MixQuality drift | per-stream | yes | — |
| 12.2 | E2E latency chain | continuous | no | — |
| 12.3 | Source exhaustion | per-event | no | — |
| 12.4 | Music-taste drift | per-session | yes | memory |
| 12.5 | Loudness drift | per-session | no | — |
| 12.6 | Silence share | per-session | no | — |
| 13.1 | AV per-intent pass | per-event | yes | — |
| 13.2 | Emphasis audio pair | continuous | yes | — |
| 13.3 | AV paradox | continuous | yes | — |
| 13.4 | AV temporal offset | continuous | yes | — |
| 13.5 | Budget-coupled AV | continuous | no | — |
| 14.1 | Research 3-path | per-minute | yes | LRR |
| 14.2 | Chronicle rate | per-minute | no | — |
| 14.3 | Condition currency | per-session | yes | — |
| 14.4 | Measure attribution | per-session | yes | — |
| 14.5 | Condition-id coverage | continuous | yes | — |
| 14.6 | Hypothesis-conclusion | per-session | no | — |
| 15.1 | Rapid preset cycling | continuous | yes | — |
| 15.2 | Epilepsy frequencies | continuous | yes | W3C |
| 15.3 | Stuck-frame | continuous | yes | — |
| 15.4 | Silent compositor | continuous | yes | — |
| 15.5 | Overlap-cascade | continuous | yes | — |
| 15.6 | Director monoculture | continuous | yes | — |
| 15.7 | AV disagreement | continuous | yes | — |
| 15.8 | Slur-variant emergence | continuous | **CRITICAL** | 14:08 archetype |

---

## Appendix B. External references

- [EBU R 128 (2023, s2 streaming supplement)](https://tech.ebu.ch/publications/r128s2)
  — Integrated / short-term / momentary loudness methodology and
  streaming-specific targets. Foundation for §10.2.
- [EBU R 128 baseline (2010, v3 2014)](https://tech.ebu.ch/docs/r/r128.pdf)
  — Original loudness normalisation recommendation. -23 LUFS
  target, ±1 LU for live.
- [Peak to Loudness Ratio (PLR) — Production Advice](https://productionadvice.co.uk/plr/)
  — Foundation for §10.6 dynamic-range measurement.
- [Synamedia Video Quality Measurement (PSNR / SSIM / VMAF /
  pVMAF)](https://www.synamedia.com/blog/a-brief-history-of-video-quality-measurement-from-psnr-to-vmaf-and-beyond/)
  — Reference for §1.4 / §1.5 no-reference video quality and
  §17.2 motion-golden technique.
- [BBC Redux](https://en.wikipedia.org/wiki/BBC_Redux)
  — Broadcast compliance archive precedent. Retention + replay
  pattern for §17.1 and §18 warmup.
- [Twitch Inspector](https://inspector.twitch.tv/) — Pre-stream
  ingest health check precedent; analogue for our §18 warmup.
- [Broadcast compliance logging (Actus Digital)](https://actusdigital.com/broadcast-compliance/)
  — Continuous compliance-monitoring architecture pattern;
  reference for §17.4 longitudinal dashboard.
- [Auphonic](https://auphonic.com/) — Automated mix + loudness
  normalisation; reference for §10 mix-quality scoring.
- [pVMAF (Synamedia)](https://www.synamedia.com/blog/a-brief-history-of-video-quality-measurement-from-psnr-to-vmaf-and-beyond/)
  — Lightweight predictor-based VMAF for live environments;
  design analogue for §1.4.
- W3C Web Content Accessibility Guidelines (flashing content
  limits) — Foundation for §15.2 epilepsy frequency detector.

---

## Appendix C. Relation to 2026-04-20 14:08 incident

The 14:08 TTS leak would be caught by these audits in this
catalog (if deployed):

- §15.8 — slur-variant emergence counter increments on LLM
  producing `niggah` / `niggaz` / other variants, independent of
  whether the regex catches them. First-time emission triggers
  alert even if the gate redacts.
- §10.5 — intentionality audit: the slur-variant TTS synthesis
  was tagged (source=tts) but the downstream audio reaching
  broadcast contained an un-redacted token. A paired audit
  comparing TTS-input-text to TTS-audio-ASR output (new
  last-chance audio-side filter) would catch the gap.
- §6.3 — grounding-provenance populated: the director intent
  that generated the slur-laden commentary probably had empty
  grounding_provenance per the alpha 99.3% figure. If provenance
  were populated, the programme context + monetization-safe
  directive would have been in-scope and prompt-level (task
  #165) would have fired.
- §8.2 — programme expansion NOT replacement. If a
  rap-commentary programme were active, it should have expanded
  the grounding catalog to include rap-lyric vocabulary AND
  monetization-safety constraints. A programme that expanded the
  LLM's vocabulary without expanding the constraint layer was
  the precondition of the leak.

All four audits are CRITICAL-tier in Appendix A. Together they
describe the multi-layer defence-in-depth gap that §2 (cross-
cutting pattern 2) of the synthesis-final identified.
