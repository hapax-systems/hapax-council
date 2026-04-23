# Master Plan — Video-Container + Mirror-Emissive HOMAGE Conversion

**Spec:** `docs/superpowers/specs/2026-04-23-video-container-parallax-homage-spec.md`
**Date:** 2026-04-23
**Owner:** TBD (delta drafted; alpha right-of-first-refusal on execution)

> **For agentic workers:** This is a MASTER plan covering 11 phases.
> Per-phase detailed plans (with TDD steps) are drafted as each phase
> is entered, not all up-front — the shape of later phases depends on
> what is learned in earlier ones. See §"Per-phase plan authoring"
> below for the trigger.

---

**Goal:** Convert the HOMAGE ward system to paired video-container +
mirror-emissive legs with parallax, promote Reverie to a first-class
ward, and introduce the `frontable` state machine. Ship in 11 phases,
each one independently mergeable.

**Architecture:** see spec §4 + §5. Key primitives: `WardPair`,
`SubstrateRegionCairoSource`, `parallax_signal.py`,
`HomagePackage.palette_response`, `front_state` in `WardProperties`.

**Tech Stack:** existing — Python 3.12, pydantic, cairo, shm_rgba
reader, Reverie wgpu pipeline. No new language/runtime.

---

## Phase sequence at a glance

| # | Phase | Scope | Risk | ETA |
|---|---|---|---|---|
| 1 | Docs | spec + research + this plan | none | shipped |
| 2 | Data model primitives | `pair_role`, WardPair, WardProperties, palette_response | low (all defaults solo) | 1–2 days |
| 3 | SubstrateRegionCairoSource | new source class + unit tests | low | 1 day |
| 4 | Reverie promotion | delete pip-ur hardcode; reverie.video + reverie.emissive | HIGH — touches fx_chain | 2–3 days |
| 5 | Pilot paired ward (activity_header) | first visible paired ward | medium | 1–2 days |
| 6 | Parallax signal manager | audio bed + intent overlay + clamp | medium | 2 days |
| 7 | Frontable state machine | states + transitions + envelopes | medium | 2–3 days |
| 8 | Complementarity modes | grid_responsive + edge_follow | medium | 3–4 days |
| 9 | Fleet rollout | 12 wards, one per PR | low per-PR, long overall | 1–2 weeks |
| 10 | Choreographer + director integration | pair-aware rotation + intent | medium | 2–3 days |
| 11 | Governance test pins | regression suite | low | 1–2 days |

Total envelope: **4–6 weeks serial, ~3 weeks with parallel fleet
rollout**.

---

## Phase 1 — Docs (shipped alongside this plan)

**Files:**
- Create: `docs/research/2026-04-23-video-container-parallax-homage-conversion.md`
- Create: `docs/superpowers/specs/2026-04-23-video-container-parallax-homage-spec.md`
- Create: `docs/superpowers/plans/2026-04-23-video-container-parallax-homage-master-plan.md` (this file)

**Steps:**
- [x] Research doc drafted with operator discussion context
- [x] Spec doc drafted with operator-locked decisions
- [x] Master plan (this doc)
- [ ] Relay handoff to alpha (`~/.cache/hapax/relay/delta-to-alpha-2026-04-23-video-container-epic.md`) — done
- [ ] Open single docs-only PR: spec + research + master plan + alpha relay note
- [ ] Merge gate: alpha has reviewed; operator has signed off on spec

**No code** in this phase. Back-compat by construction.

---

## Phase 2 — Data model primitives

**Goal:** add the paired-ward type system; no visible behaviour
change (all wards default to `solo`).

**Files:**
- Modify: `shared/compositor_model.py` — add `pair_role`, `pair_leg`,
  `ward_id` to `SourceSchema`
- Create: `shared/ward_pair.py` — `WardPair` record
- Modify: `agents/studio_compositor/ward_properties.py` — add
  `front_state`, `front_t0`, `parallax_scalar_video/emissive`,
  `crop_rect_override`
- Modify: `agents/studio_compositor/homage/rendering.py` — extend
  `HomagePackage` with optional `palette_response` field (definition
  only, no consumers yet)
- Create: `shared/palette_response.py` — `PaletteResponse` model +
  curve evaluator
- Test: `tests/shared/test_ward_pair.py`
- Test: `tests/shared/test_palette_response.py`
- Test: extend `tests/studio_compositor/test_ward_properties.py`

**Acceptance:**
- All existing tests pass (defaults preserve old behaviour).
- New Pydantic models validate round-trip.
- Palette-response curve evaluator produces expected LAB shifts for
  synthetic substrate inputs.
- Config/default.json parses unchanged (no new required fields).

**Risk:** low. Pure additions.

**Per-phase plan trigger:** author a TDD task-breakdown plan for
Phase 2 once Phase 1 docs merge and alpha clears the spec.

---

## Phase 3 — SubstrateRegionCairoSource

**Goal:** new source class that blits a rectangular crop of the
Reverie RGBA substrate into a Cairo surface. This is the video-leg
primitive for substrate-default wards.

**Files:**
- Create: `agents/studio_compositor/substrate_region_source.py`
- Modify: `agents/studio_compositor/cairo_sources/__init__.py` —
  register the new class
- Create: `tests/studio_compositor/test_substrate_region_source.py`

**Acceptance:**
- Reads shm substrate via existing `ShmRgbaReader`.
- Crop rect parameter respected; default crop = source's anchor
  geometry normalized to substrate canvas.
- Graceful degradation: substrate missing → transparent fill +
  logged freshness miss (no exception, no blit noise).
- Crop offset parameter exercised by tests.
- Unit test: synthetic substrate RGBA → expected pixel at known
  crop.

**Risk:** low. No layout wiring yet.

---

## Phase 4 — Reverie promotion (HIGH RISK — touches fx_chain)

**Goal:** move Reverie from hardcoded `external_rgba` at `pip-ur` to
a layout-declared paired ward.

**Files:**
- Modify: `agents/studio_compositor/compositor.py` — remove hardcoded
  Reverie SourceSchema + Assignment; move to layout JSON
- Modify: `config/compositor-layouts/default.json` — add
  `reverie.video` paired source + assignment at `pip-ur` (so default
  position preserved)
- Create: `agents/studio_compositor/reverie_emissive_source.py` —
  BitchX-grammar readout of 9-dim state
- Modify: `agents/studio_compositor/fx_chain.py` — replace any
  `reverie` literal assumptions with layout-driven lookups (likely
  grep + substitute; needs care with the layer-resolver)
- Modify: `agents/studio_compositor/source_registry.py` — the
  Reverie comment at line 195 becomes stale; remove the literal
- Modify: `agents/studio_compositor/imagination_loop.py` (if present)
  and `agents/hapax_reverie/*.py` — check for any assumption that
  the Reverie ward is always visible; it isn't any more
- Test: new `tests/studio_compositor/test_reverie_as_ward.py` —
  layout without reverie assignment works end-to-end

**Acceptance:**
- Default layout renders identically to today (Reverie still at
  pip-ur).
- Layout with reverie assignment removed does not crash.
- `reverie.emissive` source renders a compact 9-dim gauge grid.
- All fx_chain tests still pass.
- Live-stream smoke: Reverie visible, ward retirement via
  `WardProperties.visible=False` works.

**Risk:** HIGH. fx_chain has implicit Reverie assumptions; Gemini
audit / alpha's recent HOMAGE work may have touched the same code
paths. Must coordinate with alpha before entry.

---

## Phase 5 — Pilot paired ward (activity_header)

**Goal:** first visible paired ward. Minimal parallax (static bed
audio only, no intent overlay yet).

**Files:**
- Modify: `config/compositor-layouts/default.json` — add
  `activity_header.video` (SubstrateRegionCairoSource at the
  activity-header-top geometry) + `PairedAssignment` record
- Modify: `agents/studio_compositor/compositor.py` — hardcoded
  fallback mirrors the default.json change
- Modify: `agents/studio_compositor/legibility_sources.py` — the
  existing `ActivityHeaderCairoSource` gains a `complementarity_
  mode` + palette response hook (palette_sync baseline — just sample
  substrate dominant hue, remap accent_cyan)
- Test: `tests/studio_compositor/test_activity_header_paired.py`

**Acceptance:**
- activity_header renders with two legs, slight parallax offset,
  visibly synchronized.
- Livestream capture before/after attached to PR.
- Regression: all existing activity_header tests pass.
- Palette shift visible but not garish (operator sign-off gate).

**Risk:** medium. Aesthetic judgement call on palette_sync
calibration.

---

## Phase 6 — Parallax signal manager

**Goal:** separate parallax-signal component; ward render loop reads
per-tick vector from it rather than computing its own.

**Files:**
- Create: `agents/studio_compositor/parallax_signal.py`
- Create: `tests/studio_compositor/test_parallax_signal.py`
- Modify: `agents/studio_compositor/substrate_region_source.py` —
  consume parallax vector for per-frame crop offset
- Modify: `agents/studio_compositor/compile.py` (or the cairo blit
  path) — apply parallax offset to emissive leg blit position
- Modify: `agents/director_loop.py` (alpha's territory — check
  first) — write parallax intent to shm when emphasis is directed
- Modify: `agents/hapax_daimonion/cpal_runner.py` — write parallax
  intent on speech emphasis
- Modify: `agents/studio_compositor/compositional_consumer.py` —
  affordance pipeline can recruit parallax intent

**Acceptance:**
- Audio-driven parallax visible on pilot ward under test tones.
- Hapax-written intent overlay produces directed parallax (e.g.
  director writes "focus activity_header" → activity_header parallax
  amplifies toward camera for 2s, decays).
- Clamp prevents off-canvas pan under any input magnitude.
- No flashing (per regression test).

**Risk:** medium. Cross-system writes from director + CPAL + affordance
pipeline — needs integration discipline.

---

## Phase 7 — Frontable state machine

**Goal:** implement spec §6.1–§6.3. Pilot on activity_header.

**Files:**
- Create: `agents/studio_compositor/front_state_machine.py`
- Modify: `agents/studio_compositor/ward_properties.py` — integrate
  state machine; front_state transitions driven by the new module
- Modify: per-ward emissive sources — read front_state, adjust
  opacity / brightness during fronted/fronting envelopes
- Modify: `agents/studio_compositor/substrate_region_source.py` —
  swap to front_video_source when `front_state=="fronted"`
- Modify: `agents/studio_compositor/director_loop.py` (or its
  successor) — emit front-intent events
- Test: `tests/studio_compositor/test_front_state_machine.py`
- Test: `tests/studio_compositor/test_front_envelopes.py`

**Acceptance:**
- Trigger from director picks activity_header, ward transitions
  smoothly integrated→fronting→fronted; un-fronts on intent boundary.
- No alpha flash or geometry snap (regression test).
- CPAL speech trigger works: speak "activity header" (or equivalent
  lex), ward fronts.
- Envelope durations configurable; defaults 400ms front-in, 600ms
  front-out.

**Risk:** medium. State-machine correctness + integration with
multiple async writers.

---

## Phase 8 — Complementarity modes (grid_responsive, edge_follow)

**Goal:** implement the remaining two complementarity strategies.
Assign per-ward modes.

**Files:**
- Modify: `agents/studio_compositor/homage/emissive_base.py` —
  add `grid_responsive` hook; emissive renderers query substrate
  state for density / cell size
- Create: `agents/studio_compositor/edge_follow.py` — substrate
  crop edge detection + mark placement helper
- Modify: per-ward emissive source classes — opt into one of the
  three modes via HomagePackage
- Test: `tests/studio_compositor/test_complementarity_modes.py` —
  palette_sync / grid_responsive / edge_follow produce expected
  outputs under synthetic substrate inputs

**Acceptance:**
- Each mode visually distinguishable on pilot ward.
- Per-ward mode assignment works and persists across restarts.
- Operator A/B validation on livestream (captures attached to PR).

**Risk:** medium. Aesthetic judgement calls; may iterate with
operator before locking defaults.

---

## Phase 9 — Fleet rollout (1 ward per PR)

**Goal:** convert the remaining BitchX wards. One per PR, each with
before/after livestream capture.

**Order** (risk-ordered, least to most):

1. stance_indicator
2. thinking_indicator
3. whos_here
4. pressure_gauge
5. grounding_provenance_ticker
6. recruitment_candidate_panel
7. impingement_cascade
8. activity_variety_log
9. gem
10. hardm (dot-matrix needs grid_responsive mode specifically)
11. token_pole (vitruvian behind/over Reverie crop — aesthetic risk)
12. sierpinski (paired — its own video feed stays, emissive is new
    9-slot state readout)

Each PR:
- Pair definition in layout JSON + compositor.py fallback
- Complementarity mode assignment
- Front-source assignment (if frontable)
- Regression visual capture
- Operator sign-off gate on aesthetic

**Risk:** low per-PR; long overall (~2 weeks elapsed if serial).

---

## Phase 10 — Choreographer + director integration

**Goal:** upstream systems become pair-aware.

**Files:**
- Modify: `agents/studio_compositor/homage/choreographer.py` —
  rotation + activation logic treats pairs as units; "emphasis"
  semantics map to front-intent
- Modify: `agents/studio_compositor/director_loop.py` — director
  prompt additions (spec §6 in director prompt doc) about paired
  wards + fronting affordance + parallax intent
- Modify: `agents/studio_compositor/compositional_consumer.py` —
  affordance pipeline can recruit a ward's front state (not just
  its visibility)
- Test: `tests/studio_compositor/test_choreographer_pair_aware.py`

**Acceptance:**
- Choreographer rotation cycles pairs correctly.
- Director LLM given sample scenarios recruits pairs and
  manipulates parallax sensibly (judged by diff against baseline
  outputs on a curated scenario set).
- Programme integration: a programme can declare "wards A and B in
  pair-mode, C fronted" and it just works.

**Risk:** medium. Prompt-engineering iterations expected.

---

## Phase 11 — Governance test pins

**Goal:** regression suite extended to paired surfaces.

**Files:**
- Modify: `tests/studio_compositor/test_no_flashing_wards.py` —
  extend scan to paired wards and parallax output
- Create: `tests/studio_compositor/test_parallax_clamp.py` — no
  off-canvas pan under any intent magnitude
- Create: `tests/studio_compositor/test_complementarity_contract.py`
  — every paired ward has a declared mode; all emissive legs respect
  zero-opacity invariant
- Create: `tests/studio_compositor/test_front_state_invariants.py` —
  all transitions smooth-enveloped; no alpha snap
- Modify: `tests/studio_compositor/test_homage_ward_count.py` (if
  it exists) — new expected counts

**Acceptance:**
- Full suite green.
- Synthetic adversarial inputs (extreme audio spikes, rapid
  director intent flips) produce smooth output, no regression.

**Risk:** low.

---

## Per-phase plan authoring

Each phase beyond 1 gets its own detailed TDD-style plan authored at
the start of that phase, NOT all up-front. Reason: later phases'
structure depends on concrete behaviour learned in earlier ones
(e.g. Phase 8's complementarity-mode implementations depend on what
the Phase 5 pilot reveals about palette_sync calibration).

Per-phase plans live at
`docs/superpowers/plans/2026-04-{23+offset}-video-container-phase-N-*.md`
and follow the full TDD bite-sized-task template.

Delta (or whoever owns the phase) drafts each phase's plan before
branching.

---

## Coordination protocol with alpha

- **Right of first refusal:** alpha claims any phase within 24h of
  delta's phase-entry notification. If unclaimed, delta proceeds.
- **Joint phases:** Phase 4 (Reverie promotion) and Phase 10
  (director integration) are flagged joint — require explicit
  coordination doc before branching.
- **Relay cadence:** phase-entry note + phase-complete note in
  `~/.cache/hapax/relay/delta-to-alpha-*.md`.
- **Visual review:** every phase that ships visible change gets a
  livestream-capture attached to the PR for operator sign-off.

---

## What could derail this

- **Aesthetic rejection** at Phase 5 pilot: if palette_sync doesn't
  produce a coherent look, the whole direction is questioned. Build
  in an explicit operator sign-off gate at Phase 5 PR.
- **Reverie promotion depth (Phase 4)**: if fx_chain has more
  hidden assumptions than grep suggests, Phase 4 expands. Budget
  extra room.
- **Main CI staying red**: if main typecheck doesn't recover,
  regressions become invisible. Phase 2+ should gate on main-green.
- **Alpha + delta stepping on each other**: addressed by right-of-
  first-refusal + joint-phase flags, but real risk. Watch the
  relay daily.
- **Operator direction shift**: likely. When a shift happens, the
  phase sequence is a plan not a contract — re-derive from
  new constraints.

---

## Ownership

- **Spec custodian:** delta (current)
- **Phase 2 candidate owner:** delta
- **Phase 3 candidate owner:** delta
- **Phase 4 candidate owner:** alpha (Reverie depth) — delta to
  assist
- **Phase 5 pilot:** whichever session has operator bandwidth for
  the aesthetic review
- **Later phases:** decided per relay at phase entry
