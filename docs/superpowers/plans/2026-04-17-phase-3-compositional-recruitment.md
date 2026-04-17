# Phase 3 — Compositional Recruitment via AffordancePipeline

**Spec:** §3.1, §3.3, §5 Phase 3
**Goal:** Director emits `CompositionalImpingement`s to the existing DMN impingement stream; AffordancePipeline recruits capabilities from the new compositional catalog; the three shufflers (random_mode preset, youtube random.choice, objective_hero_switcher hardcoded map) are demoted to fallbacks or retired.

## File manifest

- **Create:** `shared/affordances/compositional/__init__.py`
- **Create:** `shared/affordances/compositional/camera_hero.py` — N `CameraHeroAffordance` instances per camera role × context class.
- **Create:** `shared/affordances/compositional/preset_family.py` — 4 preset-family capabilities (audio-reactive / calm-textural / glitch-dense / warm-minimal).
- **Create:** `shared/affordances/compositional/overlay_emphasis.py` — overlay.foreground.* and overlay.dim.* capabilities.
- **Create:** `shared/affordances/compositional/youtube_direction.py` — cut-to / advance-queue / cut-away.
- **Create:** `shared/affordances/compositional/attention_winner.py` — attention.winner.* per bid source.
- **Create:** `scripts/seed-compositional-affordances.py` — embeds descriptions into Qdrant `affordances` collection; idempotent.
- **Create:** `agents/studio_compositor/compositional_consumer.py` — reads pipeline recruitment → applies compositor mutations (hero-camera swap, preset-family bias, overlay alpha).
- **Create:** `agents/studio_compositor/preset_family_selector.py` — weighted-random pick of a specific preset within a recruited `fx.family.*`, respecting recent-use penalty + design-language hints.
- **Create (on first recruitment):** `/dev/shm/hapax-compositor/overlay-alpha-overrides.json` — `{"source_id": float}` alpha overrides; compositor's existing layout mutator reads and applies.
- **Create (on first recruitment):** `/dev/shm/hapax-compositor/hero-camera-override.json` — `{"camera_role": str, "ttl_s": float}`; compositor reads and hot-swaps main slot.
- **Create (on first recruitment):** `/dev/shm/hapax-compositor/recent-recruitment.json` — rolling log of `{family: last_recruited_ts}`; consumed by Phase 3 `random_mode` fallback gate.
- **Modify:** `agents/studio_compositor/random_mode.py` — `run()` checks if a `fx.family.*` capability was recruited within last N=60 s; skip if so.
- **Modify:** `agents/studio_compositor/director_loop.py::_reload_slot_from_playlist` — try `youtube.direction.advance-queue` recruitment first; fallback to `random.choice`.
- **Modify:** `agents/studio_compositor/director_loop.py::_act_on_intent` — write each `CompositionalImpingement` to `/dev/shm/hapax-dmn/impingements.jsonl`.
- **Retire:** `agents/studio_compositor/objective_hero_switcher.py::hero_for_active_objectives` as a *consumer* path (unit is already unwired; keep the mapping data as `ACTIVITY_HERO_MAP` export for reference but move the dispatch to the pipeline).
- **Modify:** `agents/attention_bids/dispatcher.py` — add `dispatch_recruited_winner(capability_name)` callable, invoked when pipeline recruits `attention.winner.*`.
- **Create:** `tests/affordances/test_compositional_recruitment.py`
- **Create:** `tests/studio_compositor/test_compositional_consumer.py`

## Tasks

- [ ] **3.1** — Write the compositional capability base class (or reuse existing Capability base from `shared/affordances/`; inspect code first). Each capability needs:
  - `name` (str, e.g. `"cam.hero.overhead.hardware-active"`)
  - `affordance_description` (Gibson-verb, 15-30 words, embedded into Qdrant).
  - `operational` (OperationalProperties: medium, consent_required).
  - `activate(context)` — called by pipeline on recruitment; writes a compositor-consumable signal to /dev/shm.
- [ ] **3.2** — Enumerate camera-hero affordances: for each (camera_role, context_tag) pair that makes sense, produce one capability. Sample list: `(overhead, hardware-active)`, `(overhead, vinyl-active)`, `(overhead, mpc-pads-active)`, `(operator-brio, conversing)`, `(operator-brio, reacting-to-chat)`, `(desk-c920, writing-reading)`, `(desk-c920, focused-desk-work)`, `(room-c920, ambient-chill)`, `(synths-brio, beatmaking)`. 8-12 total at Phase 3; more can be added later.
- [ ] **3.3** — Preset-family affordances: 4 families, each with a description and a list of preset names from `agents/effect_graph/presets/` that belong to the family. Activation writes the chosen preset name (weighted-random within family) to `graph-mutation.json`.
- [ ] **3.4** — Overlay affordances: `overlay.foreground.{album, captions, chat-legend, activity-header, grounding-ticker}` and `overlay.dim.all-chrome`. Activation adjusts `/dev/shm/hapax-compositor/overlay-alpha-overrides.json` which the compositor reads.
- [ ] **3.5** — YouTube direction affordances + attention winner affordances.
- [ ] **3.6** — Write seeding script. Use the existing embedding path (look at the Qdrant insertion pattern in the affordance-setup code). Idempotent: given a description hash, upsert-by-id.
- [ ] **3.7** — Write tests: construct a synthetic impingement narrative (e.g., "the operator is at the turntable and music is playing"); run `AffordancePipeline.select` against the test-mode seeded collection; assert the winning capability includes `cam.hero.overhead.*`. This is the integration sanity check.
- [ ] **3.8** — Implement `compositional_consumer.py`:
  - Watches `/dev/shm/hapax-affordance/recruited.jsonl` (pipeline writes there) — OR wires directly in-process if the pipeline runs in the compositor (check).
  - On recruitment:
    - `cam.hero.*` → set hero-camera override file, signal compositor's `ChatSlotRotator` / `HeroSwitcher` (or equivalent).
    - `fx.family.*` → call preset-family selector, write `graph-mutation.json`.
    - `overlay.*` → update `overlay-alpha-overrides.json`.
    - `youtube.direction.*` → call director's `_reload_slot_from_playlist` or a direct YouTube queue method.
    - `attention.winner.*` → call dispatcher.
- [ ] **3.9** — Modify `random_mode.run()` to check the last-recruitment timestamp file; if within 60 s of a `fx.family.*` recruitment, skip this iteration.
- [ ] **3.10** — Modify director `_act_on_intent` to emit `CompositionalImpingement`s as impingements to the DMN stream.
  - Each impingement's `narrative` field is the text to embed; `dimensions` and `material` come from the director's LLM output; `salience` from the director's own salience estimate.
- [ ] **3.11** — End-to-end test: fixture director output → writes to test impingement stream → pipeline recruits → consumer applies → assert compositor state changed.
- [ ] **3.12** — Run ruff + pyright.
- [ ] **3.13** — Seed script run against dev Qdrant (or test container).
- [ ] **3.14** — Commit in 3-4 focused commits:
  - `feat(affordances): compositional capability catalog (camera.hero, preset.bias, overlay, youtube, attention)`
  - `feat(affordances): Qdrant seeding script for compositional affordances`
  - `feat(compositor): CompositionalConsumer translates pipeline recruitment to compositor mutations`
  - `refactor(compositor): demote random_mode + hardcoded hero switcher to fallbacks`
- [ ] **3.15** — Restart studio-compositor + imagination-loop + reverie. Monitor 60 s. Capture frame. Expect: compositor mutations driven by recruited capabilities now observable in the output.
- [ ] **3.16** — Mark Phase 3 ✓.

## Acceptance criteria

- Qdrant `affordances` collection contains the new compositional capabilities, searchable by narrative.
- Director emits impingements every tick; pipeline recruits ≥1 capability per 2 ticks (on average).
- `random_mode` preset rotation fires only when no `fx.family.*` has been recruited recently.
- Hero-camera switch observable: set up synthetic "turntable active" impingement → hero switches to overhead or synths camera within 5 s.
- Tests: ≥3 new unit tests + 1 integration test; all green.

## Test strategy

- Unit: each capability's `activate()` writes expected state file.
- Integration (with running Qdrant): seed → search → assert expected recruitment.
- Smoke (live): inject synthetic impingement via CLI helper, observe compositor reaction.

## Rollback

Revert compositional_consumer imports in compositor; compositor falls back to previous behavior. Random_mode's gate is idempotent (no-op when no recruitment flag present).

## Risks

- Qdrant seed must not duplicate IDs if run twice. Use content-hash IDs.
- Pipeline recruitment and compositor mutation must be fast enough (<500 ms) for director cadence. Measure in tests.
- OBS v4l2 consumer must not lose frames during layout mutation — `hero-camera` swap already exercised in prior epics (camera 24/7 resilience).
