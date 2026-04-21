# Retire Effect Shuffle Mode — Implementation Plan

**Research:** `docs/research/2026-04-20-retire-effect-shuffle-design.md`
**CC-task:** `ef7b-175` (Retire EFFECT shuffle mode — research + plan)
**Operator directive (2026-04-19):** *"effect shuffle mode should be totally removed it's a crutch."*
**Architectural anchor:** `feedback_no_expert_system_rules` — randomness is a release-valve substituting for grounded recruitment.

## Hard dependency

**#166 preset variety must land first.** Shuffle is the release-valve that hides the recruitment-surface collapse. Removing it before Phases 2–5 of the preset-variety plan ship would visibly collapse variety. Phase 2 of this plan is a gate-check that enforces this.

## Phase 1 — Instrumentation + 24h baseline

Branch: `feat/shuffle-retire-instrumentation`. Single PR.

- [ ] Rename Prometheus counter `hapax_random_mode_pick_total` → `hapax_effect_shuffle_fires_total`
- [ ] Add `site` label with values: `S1-family`, `S1-fallback`, `S2-uniform`, `S3` (chat reactor), `S4` (director loop), `S5` (preset family selector), `S6` (playlist), `S7` (UI shuffle button)
- [ ] Update call sites in:
  - [ ] `agents/studio_compositor/random_mode.py`
  - [ ] `agents/studio_compositor/preset_family_selector.py`
  - [ ] `agents/studio_compositor/director_loop.py`
- [ ] Add `POST /api/studio/effects/shuffle-event` endpoint to register S7 (UI button) fires
- [ ] Author `scripts/measure-shuffle-baseline.py` and capture 24h baseline JSON to `docs/research/shuffle-baseline-2026-04-21.json`
- [ ] Update Grafana dashboard panel for new metric name
- [ ] Acceptance: 24h of post-deploy data shows the per-site distribution operator can read

Size: S.

## Phase 2 — Precondition gate-check (no code change)

- [ ] Author `scripts/gate-shuffle-retirement.py` validating these #166 preset-variety acceptance gates:
  - [ ] Phase 9 of the variety plan passed on `main`
  - [ ] Shannon entropy ≥1.0 across last 60 min of preset family picks
  - [ ] Zero `calm-textural` family in control-flow logs (monoculture broken)
  - [ ] `_RecencyTracker` + `ActivationState.decay_unused` present in code
  - [ ] Affordance-catalog audit reports zero <3-member families
- [ ] Gate PASS unblocks Phase 3
- [ ] Gate FAIL: do NOT proceed; fix the upstream variety surface first

Size: S.

## Phase 3 — Retire S2 (uniform-fallback inside `random_mode`)

Branch: `refactor/shuffle-s2-retire`. Single PR.

- [ ] Delete `random_mode.py:148-154` (uniform-random across whole corpus)
- [ ] Update tests asserting uniform-fallback behavior — flip to assert no-mutation when no family recruited
- [ ] Acceptance: `hapax_effect_shuffle_fires_total{site="S2-uniform"}` rate drops to 0; entropy unchanged

Size: S.

## Phase 4 — Retire S1 `neutral-ambient` family-fallback

Branch: `refactor/shuffle-s1-retire`. Single PR.

- [ ] Delete `random_mode.py:143-145` (neutral-ambient family fallback when no recruitment)
- [ ] When no family recruited, loop sleeps and produces no mutation
- [ ] Update `tests/studio_compositor/test_closed_loop_wiring.py`
- [ ] Acceptance: `hapax_effect_shuffle_fires_total{site="S1-fallback"}` drops to 0; `hapax_preset_family_histogram` entropy holds ≥1.0
- [ ] If entropy regresses: do NOT restore shuffle. Investigate #166 decay/impingement instead.

Size: S.

## Phase 5 — Delete `random_mode.py` + helpers + UI shuffle button

Branch: `refactor/shuffle-final-removal`. Three atomic commits in one PR.

- [ ] **5a** — Create `agents/studio_compositor/preset_corpus.py` with the I/O helpers `random_mode.py` exposes (`load_corpus`, etc.); update `chat_reactor.py` import
- [ ] **5b** — Delete `random_mode.py`, `/dev/shm/hapax-compositor/random-mode.txt`, `emit_random_mode_pick` helper; update Prometheus dashboard
- [ ] **5c** — Delete S7 UI shuffle: remove `generateRandomSequence`, `shuffleModeRef`, `handleShuffle`, the shuffle button from `hapax-logos/src/components/graph/SequenceBar.tsx`. Replace with programme-dropdown if task #164 shipped; otherwise leave a TODO referencing #164.

Size: M.

## Phase 6 — Post-retirement observation + scrim relabel (R7)

- [ ] 60-min operator-read acceptance:
  - [ ] Entropy ≥1.5 across the 60-min window
  - [ ] `hapax_effect_shuffle_fires_total{site!="S6-playlist"}` == 0 across all non-playlist sites
  - [ ] Subjective: operator reports "3 of 5 families show without feeling random"
- [ ] R7 scrim-family relabel as follow-up PR, gated on task #174 (nebulous scrim) landing

Size: S + M.

## Critical path

#166 Phases 2/3/4/5 land + pass acceptance → this plan's Phase 1 instruments + 24h baseline → Phase 2 gate-check → Phases 3–5 delete shuffle in three ordered steps → Phase 6 observes + integrates with #174 scrim reorganisation.

## Out of scope

- General "shuffle anywhere in the codebase" retirement — this plan only touches the **effect/preset shuffle** path
- The `S6-playlist` random pick (operator-controlled rotation through a curated list) stays — it is operator intention, not pipeline release-valve
- Director-loop call-sites that emit `preset.bias.shuffle` intent_family — those become no-ops once Phase 5 lands; cleanup is bundled in 5b

## Why no implementation in this plan

Per `feedback_systematic_plans` — sequenced plan covers ALL findings before shipping any fix. Implementation phases ship via their own PRs after the plan is reviewed.
