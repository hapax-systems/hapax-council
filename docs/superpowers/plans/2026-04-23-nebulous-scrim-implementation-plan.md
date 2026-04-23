# Nebulous Scrim — Implementation Master Plan

**Spec:** `docs/research/2026-04-23-nebulous-scrim-design.md` (533 lines, operator-directed 2026-04-20)
**Backlog item:** #174 — Nebulous Scrim — new anchor concept for composite/effects/hero/cams
**Date:** 2026-04-23
**Owner:** TBD (delta drafted; alpha right-of-first-refusal on compositor-depth phases)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

---

**Goal:** Operationalize the Nebulous Scrim conceptual anchor into the compositor — rename the output substrate from "Reverie + effects + glfeedback" to "scrim," tag every ward + camera + source with a `scrim_depth`, route uniform depth-aware effects (atmospheric-perspective tint, differential blur, breath modulation) across all scrim-plane elements so the operator's flagged visual disparity (sierpinski vs HARDM vs BitchX wards) goes away.

**Architecture (from spec §5):** four conceptual layers — scrim pass (baseline, always on), behind-scrim (cameras), on-scrim (wards + avatars), in-front-of-scrim (pierce, rare). Each layer declares its depth via a new `scrim_depth` field on `Source` / per-pad uniform. Compositor honours the tag with per-depth atmospheric-perspective tint + differential blur + breath modulation applied uniformly.

**Tech stack:** existing — Python 3.12, pydantic `shared/compositor_model.py`, wgpu Reverie, GStreamer GL shader chain (`fx_chain.py`, `glfeedback`), cairo Cairo sources, Prometheus metrics. No new language runtimes. A few new shader nodes in Phase 9 (optional).

---

## Operator decision gates (BLOCK phase 1 entry until answered)

Spec §12 lists seven open questions. These need answers before Phase 1 ships. Marking each with proposed default + impact.

| # | Question | Proposed default | Phase blocked |
|---|----------|------------------|---------------|
| 1 | Face-obscure before or after scrim? | **Before** (at producer layer, per #129) — scrim inherits already-obscured pixels | Phase 2 |
| 2 | Baseline scrim density | **Medium (~0.50)** — programme modulates | Phase 1, Phase 5 |
| 3 | `scrim.pierce` cadence | **Rare ritual** (~120s + explicit moments) | Phase 8 |
| 4 | Seasonal / time-of-day variants? | **No** — working-mode primary, programme secondary | Phase 5 |
| 5 | Warm-cloth vs cool-mist default in R&D | **Cool-mist cyan** (carries forward A6 substrate invariant) | Phase 1, Phase 3 |
| 6 | Mapping to 5-channel mixer | **Each scrim profile = mixer operating point** (spec §13) | Phase 6 |
| 7 | Can scrim fully part once per session? | Operator taste | Phase 8 |
| 8 | Camera PiP size vs. scrim density | **Size stays fixed; only scrim changes** | Phase 4 |

**Gate policy:** operator confirms defaults (or picks alternatives) before Phase 1 branches. I will not speculate on these.

---

## Phase sequence

All phases shippable independently. Each lands as one PR. Phases 1–4 serial; 5–8 can parallelize after Phase 2 lands.

### Phase 0 — Docs (this plan + spec re-location)

**Files:**
- Move: `docs/research/2026-04-20-nebulous-scrim-design.md` → stays in place; it IS the spec (533 lines, thorough enough)
- Create: `docs/superpowers/plans/2026-04-23-nebulous-scrim-implementation-plan.md` (this file)
- Update: `reference_nebulous_scrim.md` memory pointer

**Steps:**
- [x] Write this plan
- [ ] Ship docs-only PR
- [ ] Operator resolves the 8 decision-gate questions (§Operator decision gates above)
- [ ] Alpha review on spec + plan; claims or declines execution ownership on Phases 4 + 5 (compositor-depth coupling)

**Blast radius:** none (docs only). Back-compat by construction.

---

### Phase 1 — `scrim_baseline` WGSL preset

**Goal:** one new Reverie preset that reconfigures the existing 8-pass graph for gauzy-warm baseline output. No new shader nodes. Structural director picks this preset by default.

**Files:**
- Create: `presets/scrim_baseline.json`
- Modify: `agents/studio_compositor/preset_family_selector.py` — add `scrim_baseline` as the default family
- Test: `tests/test_scrim_baseline_preset.py` (schema + uniform bounds)

**Spec reference:** §3 (techniques 1, 2, 4, 6, 9, 13 — the gauzy-warm set). Baseline config per §5.5: noise low-freq, drift slow, breath 0.2 Hz, colorgrade damped to package accent, postprocess light.

**Acceptance:**
- Preset validates against Reverie `_uniforms` plan schema v2
- Loading the preset produces the expected scrim-feel (operator visual sign-off)
- Cost ≤ 1.5ms GPU at 1280×720 (per §9.6)
- Fallback path: missing preset file → current behaviour (not hard-failed)

**Gate:** operator resolves questions #2 (density) and #5 (warm vs cool) before branching.

---

### Phase 2 — `scrim_depth` tagging

**Goal:** every source declares its scrim depth. The compositor's render loop honours the tag via per-pad uniform. Defaults preserve current behaviour.

**Files:**
- Modify: `shared/compositor_model.py` — add `scrim_depth: Literal["beyond", "behind", "surface", "pierce"] | None = None` to `Source`
- Modify: `agents/studio_compositor/compositor.py` — apply defaults: cameras → `"behind"`, legibility wards → `"surface"`, avatars (`token_pole`, `hardm_dot_matrix`) → `"surface"` (with pierce-capable), `album_overlay` → `"beyond"`, Reverie → scrim itself (special-cased)
- Modify: `agents/studio_compositor/fx_chain.py` — consume the tag into per-pad uniforms on pad creation
- Modify: `config/compositor-layouts/default.json` — add explicit `scrim_depth` field to each source; unset fields fall through to defaults
- Test: `tests/studio_compositor/test_scrim_depth_tagging.py`

**Spec reference:** §5.2, §6 (ward inventory by depth band).

**Ward-by-ward default map (§6):**

| Ward | scrim_depth |
|------|-------------|
| activity_header, stance_indicator, chat_ambient, grounding_provenance_ticker, captions_source, stream_overlay, research_marker_overlay | `surface` |
| impingement_cascade, recruitment_candidate_panel, thinking_indicator, activity_variety_log, whos_here, pressure_gauge | `surface` (near-surface, soft-blurred by Phase 4) |
| token_pole, hardm_dot_matrix | `surface` (pierce-capable) |
| album_overlay, sierpinski_renderer | `beyond` |
| Camera PiPs (brio-*, c920-*) | `behind` |

**Note:** sierpinski goes to `beyond`, NOT `surface`. The operator's original visual complaint ("sierp doesn't match other homage wards") was diagnosed (research doc §4) as a z-plane issue — sierpinski was grandfathered to `on-scrim` and missed attenuation. In the scrim reconception, sierpinski is "what the audience peers at" (§6.4), which is `beyond`.

**Acceptance:**
- All existing tests pass with defaults
- `scrim_depth` unset = current behaviour (back-compat)
- Per-pad uniform threads through to shader plans
- Prometheus counter `hapax_scrim_depth_tag_total{depth}` emitted per tick

**Risk:** HIGH — this touches the compositor's core source model. Alpha right-of-first-refusal.

**Gate:** operator confirms question #1 (face-obscure ordering).

---

### Phase 3 — Atmospheric-perspective tinting

**Goal:** per-depth `colorgrade` pass biases each source toward the scrim's dominant hue. Near = full chroma, distant = washes toward tint.

**Files:**
- Modify: `agents/studio_compositor/fx_chain.py` — inject per-pad `colorgrade` uniforms based on `scrim_depth`
- Modify: `agents/shaders/nodes/colorgrade.wgsl` — add `atmospheric_bias` param (amount to wash toward package accent)
- Test: `tests/test_atmospheric_perspective.py` — synthetic input, verify output chroma shift per depth

**Spec reference:** §4.3, §5.3.

**Acceptance:**
- `beyond` sources visibly tinted toward package accent (~30% chroma washed)
- `surface` sources unaffected (0% shift)
- `behind` sources partially tinted (~15% shift)
- Operator visual sign-off

**Gate:** operator confirms question #5 (warm vs cool tint).

---

### Phase 4 — Differential blur

**Goal:** per-depth Gaussian blur stage. Cheap; radius proportional to depth.

**Files:**
- Create: `agents/shaders/nodes/depth_blur.wgsl` (separable Gaussian)
- Modify: `agents/studio_compositor/fx_chain.py` — thread `blur_radius_px` per pad
- Test: `tests/test_depth_blur.py`

**Spec reference:** §4.1, §5.3.

**Acceptance:**
- `behind` cameras at radius ~1.5px (soft-blur)
- `surface` wards unblurred
- `beyond` sources at radius ~3px
- Cost budget: ≤ 0.3ms GPU (box-blur fallback if over)
- Operator sign-off

**Gate:** operator confirms question #8 (PiP sizing under deep scrim).

---

### Phase 5 — Programme-scrim-density soft prior

**Goal:** programme → scrim parameter envelope. Structural director picks `scrim_profile` per programme (gauzy_quiet / moire_crackle / warm_haze / etc. — §13).

**Files:**
- Modify: `agents/studio_compositor/structural_director.py` — `scrim_profile` selection per programme
- Modify: `agents/studio_compositor/programme_context.py` — expose programme → scrim-profile map
- Create: `shared/scrim_profiles.py` — registry of 7 canonical profiles (§13 taxonomy)
- Test: `tests/studio_compositor/test_programme_scrim_profile.py`

**Spec reference:** §7, §13.

**Gate:** operator confirms question #4 (time-of-day variants) + #6 (5-channel mixer mapping).

---

### Phase 6 — Preset-family reorganization

**Goal:** re-label 30 existing decorative presets into scrim profiles. Decorative names preserved as aliases.

**Files:**
- Modify: each of 30 preset JSONs under `presets/` — add `scrim_profile` alias metadata
- Modify: `agents/studio_compositor/preset_family_selector.py` — selection now scrim-profile-aware
- Create: `shared/preset_alias_map.py` — maps old names to scrim profiles
- Test: `tests/test_preset_alias_mapping.py`

**Spec reference:** §13 taxonomy. Seven canonical profiles:
- `gauzy_quiet` (warm low-density) — replaces `ambient`, `clean`
- `warm_haze` — replaces `heartbeat`, partial `trails`
- `moire_crackle` — replaces `vhs_preset`, `neon`, `glitch_blocks_preset`
- `clarity_peak` — replaces `clean`, `silhouette`
- `dissolving` — replaces `screwed`, `ghost`
- `ritual_open` (new) — no decorative predecessor
- `rain_streak` (context-bound, interludes only)

**Gate:** none (can parallelize with Phase 5).

---

### Phase 7 — Hapax-voice scrim filter

**Goal:** PipeWire preset `voice-fx-scrim.conf` with cloth-filtered reverb. Activated when scrim is active (always, by §9.1).

**Files:**
- Create: `config/pipewire/voice-fx-scrim.conf`
- Modify: `systemd/overrides/hapax-daimonion.service.d/voice-fx.conf` — default to scrim preset
- Doc: `config/pipewire/README.md` — document the new preset

**Spec reference:** §8.1. Filter: low-pass ~6.5kHz, short reverb ~150ms tail at 12–15% wet, light stereo spread.

**Gate:** none (independent of compositor phases).

---

### Phase 8 — `scrim.pierce` intent family

**Goal:** new `IntentFamily` member. Choreographer honours pierce by writing radial density modulation into scrim pass uniforms.

**Files:**
- Modify: `agents/studio_compositor/homage/choreographer.py` — add `scrim.pierce` intent
- Modify: `agents/studio_compositor/director_loop.py` — director can emit pierce intent
- Modify: `agents/studio_compositor/compositional_consumer.py` — affordance dispatch for pierce
- Test: `tests/studio_compositor/test_scrim_pierce.py` — deterministic envelope frame-buffer test

**Spec reference:** §8.3, §10.2. Envelope: density 1.0 → 0.3 → 1.0 cosine over ~1.5s, radius ~240px, cadence per §12 question #3.

**Gate:** operator confirms question #3 (pierce cadence) + #7 (can scrim fully part).

---

### Phase 9 — New shader nodes (optional, enriching)

**Goal:** six new WGSL nodes for richer scrim vocabulary. Each added individually, each independently reversible.

**Files (one per node):**
- `agents/shaders/nodes/weave.wgsl` (fabric-weave texture, highest priority)
- `agents/shaders/nodes/dust_motes.wgsl` (slow drifting specks, high priority)
- `agents/shaders/nodes/particulate.wgsl`
- `agents/shaders/nodes/smudge.wgsl`
- `agents/shaders/nodes/rain_glass.wgsl` (context-bound, interlude use)
- `agents/shaders/nodes/lace.wgsl`

**Each node:** WGSL shader + Python node class + preset demo + unit test. ~1–2 days per node.

**Priority order:** `weave` first (it's the fabric), then `dust_motes` (depth cue), then the rest as operator requests.

---

## Phase ownership

- **Phase 0 (this doc):** delta
- **Phase 1 (scrim_baseline preset):** either; delta default
- **Phase 2 (scrim_depth tagging):** alpha right-of-first-refusal (core compositor model change)
- **Phase 3–4 (atmospheric tint + blur):** alpha right-of-first-refusal (shader pipeline)
- **Phase 5–7 (programme, preset reorg, voice filter):** either; partitionable
- **Phase 8 (pierce intent):** either; prefer coordinator of director_loop work
- **Phase 9 (new nodes):** individual ownership per node

---

## Rollout + rehearsal

Per spec §11 and existing HOMAGE rehearsal pattern:
- 30-min private-mode rehearsal via `scripts/rehearsal-capture.sh` before live egress on each phase
- Visual-contrast audit vs. previous phase
- Prometheus cardinality bounded
- No new director-activity rate spikes

**Verify visual work with frame grabs** (per operator 2026-04-23 directive). Every phase shipping visible change attaches a before/after livestream capture to the PR.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Spec is thorough but operator hasn't resolved §12 open questions | Gate Phase 1 on operator decisions; don't speculate |
| Main CI still red (project_main_ci_red_20260420 memory) | Phase 0 (docs) safe; Phase 1+ wants main green |
| Alpha actively shipping compositor changes | Joint-phase flag on Phases 2+3+4; coordinate via relay |
| Performance budget tight (1.5ms/frame) | Measure per phase; fallback to cheaper passes (box-blur → Gaussian) if over |
| Preset-family reorg (Phase 6) could break recruitment cadence | Aliases preserved; decorative names still work |
| Demonetization safety | Spec §9.3 explicit: scrim obscures perceptually but not semantically; Ring 2 classifier sees through |
| Consent face-obscure | Spec §9.4 explicit: face-obscure runs before scrim, authoritative |

---

## What this fixes for the operator's current complaint

**Sierpinski visual disparity vs HARDM + BitchX wards** — diagnosed as a z-plane assignment issue (sierp was grandfathered to `on-scrim`, missing depth attenuation). In the scrim reconception, sierpinski is `beyond` (spec §6.4), which is the *correct* semantic position (what the audience peers at). After Phase 2+3+4 land, sierpinski will receive atmospheric-perspective tint + differential blur like album_overlay and camera PiPs — visually unified with other scrim-plane elements.

---

## Coordination protocol with alpha

Same as the video-container epic (PR #1241 docs):
- Right of first refusal within 24h of phase entry notification
- Joint-phase flags: Phase 2 (compositor model), Phase 3 (shader chain), Phase 4 (blur pipeline)
- Relay cadence: phase-entry + phase-complete notes in `~/.cache/hapax/relay/delta-to-alpha-*.md`
- Visual capture attached to every visible-change PR

---

## What could derail this

- Operator decisions on §12 not resolved → Phase 1 blocked
- Main CI doesn't recover → regression signal-to-noise too low for safe shipping
- Alpha + delta stepping on each other's compositor edits
- Performance budget busted by atmospheric-perspective tint layer → fallback to cheaper strategy

---

## What this explicitly does NOT do

- Does not rewrite Reverie
- Does not replace the existing 8-pass WGSL graph
- Does not retire the 30 decorative presets (they survive as aliases)
- Does not change face-obscure, demonetization, or consent pipelines
- Does not alter the 720p commitment

This is a reframing epic, not a rewrite.
