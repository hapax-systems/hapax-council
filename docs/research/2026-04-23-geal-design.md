# GEAL — Grounding Expression Anchoring Layer

**Status:** research + design proposal — awaits operator sign-off before implementation.
**Date:** 2026-04-23.
**Author:** delta (Claude), from parallel agent research (6 coherent touch-point investigations).
**Supersedes:** HARDM (task #121, research/2026-04-20-hardm-aesthetic-rehab.md, task #189).
**Related:** `docs/superpowers/specs/2026-04-23-video-container-parallax-homage-spec.md` (GEAL sits inside the HOMAGE Phase 4 Sierpinski pair); `docs/research/2026-04-20-nebulous-scrim-design.md`.

---

## 0. One-paragraph framing

**GEAL is not Hapax's face.** GEAL is a layer of expressive capability that lives inside the central Sierpinski triangle and — by extending the Sierpinski grammar itself under three real-time signal channels (voice, stance, grounding extrusions) — makes the triangle visibly, unmistakably *Hapax* as an entity. HARDM tried to be the face-equivalent through a signal-bound CP437 grid; the grid lacked a legible entity-geometry without tipping into face-parade, and the "dot-matrix" framing invited cell-level decoration over structural expression. GEAL refuses the grid entirely. It treats the Sierpinski triangle — already a mature, governed, recursive geometric object with viewer identity — as *the* avatar, and adds an expression layer that rides on the grammar the triangle already speaks: self-similarity, recursive subdivision, vertex/edge/midpoint hierarchy, three-fold symmetry, center-void-as-load-bearing. The ship test is the **pronoun test**: a naive viewer watching for 15 seconds says *"what is that thing"* (entity) rather than *"what is that visual"* (decoration). If GEAL doesn't clear that bar, it fails and we rebuild.

---

## 1. HARDM retirement

HARDM is retired. Reason, compressed: *a grid of signal-coloured cells never cohered into an avatar because the legible-at-a-glance geometry a viewer needs to anchor on is precisely the bilateral/symmetric/figure geometry the anti-anthropomorphization mandate forbids — the grid was too abstract to function as an anchor and too structured to be innocuous.* PR #1245 already retired the blink-on-event envelope; operator flagged the whole surface for replacement 2026-04-23.

Retirement mechanics (Phase 0, before GEAL code lands):

- Move `agents/studio_compositor/hardm_source.py` to `agents/studio_compositor/_retired/hardm_source.py` with a header note pointing at this doc.
- Remove HARDM from layout defaults + choreographer ward catalog. Keep the ward id reserved so historical logs remain parseable.
- Archive `docs/research/2026-04-20-hardm-aesthetic-rehab.md` + `docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md` under `docs/archive/homage-hardm/` with a README pointing here.
- Delete HARDM entries from the ward-properties z-plane defaults table (scrim step 1 had HARDM on mid-scrim; GEAL inherits that slot inside the Sierpinski instead).
- Governance carry-forward: every anti-anthropomorphization test written for HARDM is preserved and extended to GEAL (see §8).

The CVS #16 persona linter (`shared/anti_personification_linter.py`) and the `axioms/persona/hapax-description-of-being.md` §6 rules carry over unchanged. HARDM's lesson — not the implementation — is what survives.

---

## 2. Anti-anthropomorphization invariants (governance gate)

A GEAL variant passes this gate or does not ship. Ten boolean checks; all must be TRUE.

1. No geometry in the upper half of the render forms two high-contrast spots with bilateral symmetry about the vertical axis (no eye-pair geometry).
2. No horizontal feature in the lower half opens/closes synchronously with `vad_speech` or TTS emphasis (no mouth-motion).
3. No 3×3 or larger cluster consistently lights in eyes-nose-mouth arrangement at any single location across a session.
4. Colour mapping is signal-semantic (which signal is firing) — never affect-semantic (what Hapax is "feeling").
5. All colour transitions use continuous envelopes (sine, log-decay, ease); no step-functions faster than 200 ms (carry-forward from PR #1245's blink retirement).
6. No flesh-tone RGB ranges are reachable from any signal combination.
7. Every visible modulation traces to a grep-able signal in `/dev/shm/` or `shared/`. No hardcoded breathing/heartbeat sines.
8. No glyph or path spells "Hapax" or uses gendered pronouns; no personality nouns in comments or labels.
9. Scale-up means more cells/density/complexity activated — NEVER more-expressive cells (the ANT primary-framing rule).
10. A naïve viewer shown the render with no context reads "system signal display" / "algorithmic pattern" / "entity" — never "character" or "face."

Enforcement lives in §8.

---

## 3. Aesthetic invariants (ship gate)

Five principles distilled from the non-face canon — each motivated by a reference class that earns the principle:

1. **Intentional asymmetry under a symmetric law.** The Monolith is perfectly proportioned but appears *placed*, not grown. Entity-ness = a lawful system making willful-looking choices inside its law. Sierpinski is the law; GEAL's willfulness rides on top.
2. **A point-of-attention that isn't a face.** Heptapod ink has an emission locus. Companion Cube has a heart. Zima Blue has a pool-centroid. GEAL needs a *where-it-is-looking-from* without eyes — a density centroid, a phase origin, a recursion seed.
3. **Response latency with shape.** Entities pause before responding. Decoration doesn't. Arrival's ink pauses, gathers, *commits*. Three-phase curves (anticipate / commit / settle) on every reactive event.
4. **Internal state leakage.** You see it *thinking* before it speaks. Zima Blue's tile-pool is pre-cognitive. GEAL surfaces motion the viewer catches that wasn't *for* them.
5. **Scale-coherent self-similarity.** Entities are recognisably themselves at every zoom. Sierpinski has this natively; GEAL's additions must also hold at every depth level.

The ship criterion is the **pronoun test** (§0). It is testable: present the rendering to a naïve viewer for 15 s silent; record their first-question pronoun. Ship if *thing*; reject if *visual*.

Hard-coded aesthetic refusals:

- **No particle-cloud haze** (the Anadol screensaver trap).
- **No colour-as-emotion mapping** (red = angry etc. — infantile; Gruvbox palette is 95% fixed).
- **No radial-symmetry cliché** (even though Sierpinski is symmetric, avoid the *lotus* / *mandala* read).
- **No beat-synced pulse-to-volume** (HARDM failure mode — reads as VU meter).
- **No text-in-a-box overlays inside the triangle** (that's GEM's job, not GEAL's).
- **No glitch-VHS effects** (dated; non-Sierpinski grammar).
- **No linear reactivity** (amplitude → brightness mapping — ambient-decoration tell).

---

## 4. Geometric vocabulary — what "extending Sierpinski" means

The Sierpinski renderer today (`sierpinski_renderer.py`) does a 2-level recursion, equilateral primary at 75% height, 13 triangles total (1 root + 3 L1 corners + 1 L1 centre void + 9 L2), stroke-not-fill line work, synthwave palette cycled by position + time, audio-reactive stroke width, glow-and-core double-stroke, inscribed 16:9 rects for YT video in the three L2 corners, a waveform fill in the L1 centre void.

**Fundamentals GEAL honours** (derived from the renderer + agents 1 + 3 + 6 converged findings):

- **Dyadic self-similarity** — divide-by-midpoint is the only legal subdivision move.
- **Edge-not-fill primacy** — the lines ARE the object. Voids are load-bearing.
- **Discrete recursion levels** — L0 / L1 / L2 are semantic; GEAL may reveal L3 / L4 under activation, but the levels remain discrete (no smoothly interpolated "depth 2.4").
- **Legal positions only** — vertices, edges, midpoints, centroids are the only anchor points. No freely-placed points except via chaos-game (which is algorithmically legal).
- **Three-fold rotational symmetry with centre-void as negative space** — the centre is not empty by accident; it is structurally where Sierpinski excludes. GEAL respects the exclusion or makes its violation meaningful.

Any GEAL primitive that respects (a)–(e) will *read as the Sierpinski speaking* rather than *drawn on top of Sierpinski*. This is the single most important authorial constraint.

---

## 5. Three expression channels

Each channel has ranked primitives from §6 of its research agent. Top two are called out; the rest are the menu for v2/v3.

### 5.1. Channel 1 — Voice (Hapax speaking)

Signal availability today (agent 2 + 5 findings):

- `/dev/shm/hapax-compositor/voice-state.json` — `{tts_active, operator_speech_active}`. Live. 10–50 ms lag.
- `/dev/shm/hapax-compositor/homage-voice-register.json` — register enum. Event-driven, seconds–minutes cadence.
- `compositor._cached_audio["mixer_energy"]` — already cached, ~10 ms DSP latency. Currently used by Sierpinski stroke-width.
- **TTS PCM envelope — NOT CURRENTLY TAPPED.** Phase 2 work: new `tts_envelope_publisher.py` on CpalRunner side writes a ~100 Hz RMS ring into `/dev/shm/hapax-daimonion/tts-envelope.f32`. 1-day work, brings voice→visual lag to ≤50 ms.

Primitive rank (top 2 bolded):

- **V1 — Chladni/nodal ignition of sub-triangles.** `spectral_centroid × rms` selects 1–3 of the 13 sub-triangles to *go still* (filled, opaque) while the rest dither under noise. High centroid lights apex triangles, low centroid lights base triangles, intensity = fill saturation. The figure announces its resonance; no scroll, no bars. Reads as Chladni-in-Sierpinski.
- **V2 — Vertex halos at F0.** The three primary vertices get soft radial halos. Pitch F0 → halo radius; voicing probability → opacity; vertex identity encodes register (apex = announcing, left = conversing, right = textmode — matches the register enum cadence). Breathes at syllabic rate, not sample rate.
- V3 — Edge weight as voicing × envelope (width + dash pattern modulation).
- V4 — Phoneme-glyph accumulation in the centre void (IPA-adjacent marks fading over 2–4 s; requires Kokoro phoneme hook).
- V5 — Register-driven recursion depth (announcing → L1, conversing → L2, textmode → L3 — slow crossfade on register change).
- V6 — Orbiting sweep-scan sampler ("where the sweep touches an edge, that edge fires").
- V7 — Coherence jitter on sub-triangle centroids (tension → locked geometry, low coherence → quantized shimmer).

### 5.2. Channel 2 — Stance (Hapax's posture)

Signal: `SystemStimmung.overall_stance` from `/dev/shm/hapax-dmn/stimmung.json`. Taxonomy (from `shared/stimmung.py::Stance`): NOMINAL, SEEKING, CAUTIOUS, DEGRADED, CRITICAL. Five discrete values, infrequent transitions.

- **S1 — Recursive-depth breathing.** Sierpinski's iteration depth *is* Hapax's concentration. NOMINAL = depth 5, SEEKING = depth 6–7 with outward probes into voids, CAUTIOUS = depth 3 (defensive simplification), DEGRADED = depth 2, CRITICAL = depth 1 + outline only. Transitions cross-fade depth over 300–400 ms. **This is the single most agreed-upon primitive across agents — it arrived independently from three separate research directions.** Depth is arithmetic; it cannot anthropomorphize.
- **S2 — Apex-weight redistribution.** Three corners carry weights summing to 1.0 biasing sub-triangle luminance. NOMINAL = balanced (0.33/0.33/0.33), SEEKING = top apex lifts to 0.55, CAUTIOUS = bottom-two lift with hollow centre, DEGRADED = one corner dark, CRITICAL = all three corners dark, only mid-edges glow. Maps attentional posture without body.
- S3 — Chromatic register swap (palette-role permutation per stance, not hue shift).
- S4 — Edge-tension jitter (rigid CRITICAL, alert SEEKING, calm NOMINAL amplitude).
- S5 — Cantor-dust density in the three forbidden interior void triangles (rises with SEEKING, drops to zero at DEGRADED).
- S6 — Whole-triangle slow rotation (≤6 °/s, pauses dead-still at CAUTIOUS).

### 5.3. Channel 3 — Grounding extrusions (Hapax's context-of-attention)

Operator coinage: moments where Hapax's grounding in a specific real-world context becomes visible. Analogous to a person's face lighting at recognition or furrowing at puzzlement — non-facial. Already partially modelled: `DirectorIntent.grounding_provenance` carries a per-tick citation list; GEAL's job is to make *the moment of latching* visible, not the citation itself.

Source classes map to triangle apices:

- Operator-perception (InsightFace match, Pi NoIR gaze, room-change) → **top apex**.
- RAG / memory / vault-note retrieval → **bottom-left apex**.
- Chat / world / music-match / SoundCloud → **bottom-right apex**.
- Imagination-converge (cross-source corroboration) → **all three apices simultaneously collapsing inward**.

Primitives:

- **G1 — Wavefront ripple from apex-of-origin.** A 200–800 ms travelling wavefront from the source apex across the recursion tree. Brightness pulse moves along the self-similar edges. Recognition source is legible *from geometry*, not from text overlay. Viewers learn the three-apex grammar in minutes without ever being told.
- **G2 — Sub-triangle latch-and-fade.** A single depth-N sub-triangle is selected per extrusion via `hash(source_id)` and latched at full accent for 150–300 ms, then decays over 1000–1500 ms. Repeated recognitions of the same source class → same cell → the viewer learns "that cell = that thing." HARDM's cell-assignment replacement, tied to fractal geometry not an arbitrary grid.
- G3 — Centroid pulse on surprise (low-probability events trigger a 180 ms radial centroid halo; reserved rare).
- G4 — Edge-trace reach on retrieval (three outer edges light in 60 ms sequence, 220 ms total).
- G5 — Recursion-depth pulse on imagination-converge (depth +2 for 400 ms, then return — "I just saw it clearly").
- G6 — Perception-anchor hop between apex regions (300 ms diacritic marker hop tracking operator gaze, no "gaze simulation").

---

## 6. The recommended MVP — six primitives, one Sierpinski

Based on agent convergence, the recommended v1 GEAL set:

| Channel | Primitive | Convergence signal |
|---|---|---|
| Voice | V1 (Chladni sub-triangle ignition) | Agents 2, 6 |
| Voice | V2 (vertex halos at F0) | Agents 1, 2 |
| Stance | S1 (recursive-depth breathing) | Agents 1, 3, 6 — three-way convergence |
| Stance | S2 (apex-weight redistribution) | Agent 3 |
| Grounding | G1 (wavefront ripple from apex-of-origin) | Agent 3 |
| Grounding | G2 (sub-triangle latch-and-fade) | Agents 1 (primitive #1), 3 |

Note the overlaps: V1 uses sub-triangle states; G2 uses sub-triangle states; S1 uses depth; G5 uses depth. **These compose rather than collide** because each channel drives a different attribute of the same primitive: V1 modulates *fill*, G2 modulates *accent latch*, S1 modulates *max depth*, G5 modulates *depth pulse offset*. The rendering pipeline has one state (per-sub-triangle attributes, per-depth-level weights) that all three channels write into — no layering, no occlusion.

---

## 7. Temporal curve discipline

Every GEAL primitive uses the three-phase envelope pattern: **anticipate (80–200 ms) → commit (60–120 ms) → settle (400–900 ms)**. No linear reactivity. No step functions < 200 ms. The curve shape IS what makes the difference between entity-read and decoration-read (agent 6 finding).

Idle state (no voice, no stance change, no grounding events for > 3 s) runs Verostko-style slow stroke accretion — recursion edges accumulate fine sub-marks at ~0.5 Hz. *Idle is not frozen; idle is composed.*

---

## 8. Governance hooks

- **Anti-personification linter extension.** Add a `geal_geometry` rule family to `shared/anti_personification_linter.py`: regex gate on any file matching `agents/studio_compositor/geal_*.py` that mentions `eye`, `mouth`, `face`, `brow`, `smile`, `blink`, `wink`, `breath`, `heartbeat` outside an explicit refusal comment.
- **Bilateral-symmetry runtime guard.** Unit test rasterises GEAL output at representative states and asserts no bilateral-symmetry hotspot exceeds threshold in the upper half. Compute autocorrelation across the vertical axis; fail if mirror-correlation > 0.85 on high-luminance cells.
- **Blink-floor test.** Assert no GEAL output channel has a discrete on/off event with rise/fall < 200 ms. (Inherits PR #1245's rule.)
- **Spec assertion.** Every GEAL PR cites which §2 invariant its render output does not violate.
- **Shimmer-constant linter.** Reject literal `sin(...)` / `cos(...)` multipliers on colour channels not sourced from stimmung or signal payload (`feedback_no_expert_system_rules` enforcement).
- **Visual-regression goldens.** Each GEAL render mode ships a golden PNG; operator signs off before merge.
- **Pronoun test as acceptance gate.** Show the rendering to three naïve viewers for 15 s silent; count *thing* vs *visual* first-questions. Ship criterion: ≥ 2 of 3 say *thing*. If < 2, redesign, don't patch.

---

## 9. Technical path

Compiled from agent 5's feasibility read.

### Phase 0 — HARDM retirement (half day)

- Move HARDM source + spec to `_retired/` + `archive/`.
- Remove from ward catalog, layout defaults, z-plane defaults.
- Pin regression tests for anti-personification carry-forward.

### Phase 1 — Cairo MVP inside the Sierpinski (1–2 days)

- New `agents/studio_compositor/geal_source.py` — `GealCairoSource(CairoSource)` class rendering into the Sierpinski's cached centre void rect + sub-triangle geometry cache.
- Mount in `fx_chain.py:573-587` as a second CairoSource alongside `_sierpinski_renderer`.
- Signals wired: `voice-state.json`, `homage-voice-register.json`, `hapax-stimmung/state.json`, `director-intent` grounding list deltas, `_cached_audio` mixer energy.
- MVP primitive set: **S1 (recursive-depth breathing) + V2 (vertex halos) + G1 (wavefront ripple)** — three from three channels, highest-confidence across agents.
- Cadence: 15 fps background, budget 8 ms per tick.
- Ward-gated via existing `ward_render_scope`. Default OFF until §8 gates pass.

### Phase 2 — TTS envelope tap for tight voice sync (2–3 days)

- New `agents/hapax_daimonion/tts_envelope_publisher.py` in CpalRunner's playback callback — per-frame RMS + spectral-centroid + ZCR into `/dev/shm/hapax-daimonion/tts-envelope.f32` (mmap, lock-free ring).
- GEAL reads last 8–16 samples each tick at ~30 fps.
- Brings voice → visual lag into ≤50 ms band, activating V1 (Chladni ignition).

### Phase 3 — Add S2, G2, grounding-extrusion wiring (2 days)

- S2 apex-weight redistribution on stance transitions.
- G2 sub-triangle latch-and-fade on grounding-provenance list deltas.
- G1 wavefront refinements once real grounding event classes are defined in the source taxonomy.

### Phase 4 — WGSL parity node (1 week, optional)

- New `agents/shaders/nodes/geal.{wgsl,json}` — GPU parity of the Cairo primitives.
- Closes the gap when Reverie becomes the active source (Cairo path is not composited in that state).
- Retire Cairo GEAL only once WGSL has visual parity goldens signed off.

Risk callouts inherited from agent 5: (a) centre void already has waveform — Phase 1 must decide composite vs replace; (b) 10 fps cadence is quantisation at 100 ms — Phase 2 lifts to 30 fps; (c) WGSL-path bypass when Reverie is active — Phase 4 resolves; (d) TTS state lag from pipecat vs actual Kokoro audio — Phase 2 CPAL tap is the correct source.

---

## 10. Operator decisions before Phase 1

Six calls that unblock implementation. Single yes/no per row is enough.

1. **Centre-void waveform coexistence.** The Sierpinski centre void currently has a waveform fill. GEAL's V1 / G1 / G5 also want that space. Options: (a) retire the waveform and replace with V1, (b) composite waveform below GEAL with low alpha, (c) move GEAL's centre-keyed primitives to the L2 interior ring. Recommended: **(a)** — waveform is a VU-meter-like read; V1's Chladni ignition is the more entity-coherent use.
2. **Sierpinski audio-reactive stroke coupling.** The existing renderer modulates stroke width with `mixer_energy`. Should GEAL share that modulation, override it, or run independently? Recommended: **GEAL shares** — one source of truth per attribute, driven by GEAL's signal pipeline.
3. **Director-intent grounding_provenance deltas.** Are current source-class tags in `grounding_provenance` distinct enough to cleanly bucket into the three apex classes? If no, GEAL ships a thin shim; if yes, direct map. Answer requires reading recent stream recordings.
4. **Register enum → recursion depth (V5).** Should announcing / conversing / textmode literally change visible recursion depth on the livestream, or is that too strong a visible signal for register (which is also conveyed by voice timbre)? Recommended: **V5 off in v1**, revisit after V2 (vertex halos encoding register via apex identity) is observed.
5. **Pronoun-test viewers.** Who are the three naïve viewers for the acceptance gate? Typically friends or livestream viewers the first time they see the new Sierpinski. Do not let anyone who's read this doc be a naïve viewer.
6. **HARDM retirement timing.** Retire before Phase 1 lands GEAL (so the livestream never runs two dot-matrix-adjacent surfaces), or keep HARDM live until GEAL hits acceptance? Recommended: **retire at Phase 0**, accept a brief window without Hapax signal-display visible while GEAL comes up. HARDM isn't earning its slot today.

---

## 11. Acceptance summary

GEAL v1 ships when all of the following are simultaneously true:

- §2 anti-anthropomorphization invariants 1–10 all TRUE.
- §8 governance hooks in place and passing.
- §6 MVP primitive set rendered.
- Temporal-curve discipline (§7) holds — no linear reactivity, no fast steps.
- Pronoun test: ≥ 2 of 3 naïve viewers say *thing* within 15 s silent observation.
- Frame budget maintained (≤8 ms/tick Cairo, signal chain ≤50 ms voice lag post-Phase 2).

If any fails, GEAL does not ship. The bar is the pronoun test — not the checklist.

---

## 12. Appendix — research traces

This doc synthesises six parallel agent investigations on 2026-04-23:

- **Agent 1** — Sierpinski visual grammar + inner-triangle geometry (8 primitives ranked).
- **Agent 2** — Voice-as-expression, non-anthropomorphic (8 mappings ranked; TTS PCM tap feasibility).
- **Agent 3** — Stance + grounding extrusions (S1–S6 + G1–G6 primitives).
- **Agent 4** — Anti-anthropomorphization + HARDM retirement learnings (10-item invariant checklist).
- **Agent 5** — Technical integration (Cairo-first, 4-phase implementation path, risk callouts).
- **Agent 6** — Aesthetic references + the "astoundingly beautiful" bar (5 entity-principles + ship test + refusal list).

Three-agent convergence on **recursive-depth breathing (S1)** as top primitive. Two-agent convergence on **vertex halos (V2)** and **sub-triangle sets (V1 / G2)** as organising primitives. All agents independently flagged the HARDM framing shift ("face-equivalent" → "signal-surface inside the Sierpinski") as architecturally necessary.

This proposal pauses here for operator sign-off on §10 before any code lands.
