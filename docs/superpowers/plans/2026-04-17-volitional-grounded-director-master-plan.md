# Volitional Grounded Director — Master Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution, or superpowers:subagent-driven-development for per-task dispatch. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the volition→composition→legibility loop on the studio compositor — replace three unsupervised shufflers with a grounded director that reads a structured perceptual field (all existing classifiers) and emits directorial intent through the existing AffordancePipeline, with multi-rate hierarchy, legibility-on-frame, and research observability.

**Architecture:** Director emits `DirectorIntent` + `CompositionalImpingement`s (never direct capability invocations). Pipeline recruits compositional affordances (camera.hero.*, fx.family.*, overlay.foreground.*, youtube.direction.*, attention.winner.*). Twitch (4 s deterministic) + Narrative (20 s grounded-LLM) + Structural (150 s grounded-LLM) rates. Cairo legibility surfaces render stance/activity/captions/chat-legend/grounding-ticker.

**Tech Stack:** Python 3.12 / Pydantic v2 / LiteLLM (Command R 08-2024) / Cairo / GStreamer / existing AffordancePipeline / Qdrant / Langfuse / Prometheus.

**Spec:** `docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md`

**Branch:** `volitional-director` (PR #1017)

---

## Phase map

| Phase | Summary | Plan file | Executable? |
|-------|---------|-----------|-------------|
| 0 | Reverie BGRA fix | *(shipped, commit 2377fee66)* | ✓ done |
| 1 | Director intent signature + prompt caching | `phase-1-director-intent.md` | ✓ |
| 2 | Structured PerceptualField | `phase-2-perceptual-field.md` | ✓ |
| 3 | Compositional recruitment (retire shufflers) | `phase-3-compositional-recruitment.md` | ✓ |
| 4 | Legibility surfaces | `phase-4-legibility-surfaces.md` | ✓ |
| 5 | Multi-rate directorial hierarchy | `phase-5-multi-rate-hierarchy.md` | ✓ |
| 6 | Consent live-egress gate | `phase-6-consent-live-egress.md` | ✓ |
| 7 | Research observability | `phase-7-research-observability.md` | ✓ |
| 8 | DEVIATION + condition declaration | `phase-8-deviation-condition.md` | ✓ |
| 9 | Visual audit + rehearsal | `phase-9-rehearsal.md` | manual |

Execution is serial. Each phase ends with: tests pass, commit, compositor restart + visual smoke, mark phase complete in this master plan, continue.

## Execution protocol

**Before each phase:**
1. Read the phase plan end-to-end once.
2. Check that no prerequisite phase has regressed (previous phases' tests still pass).
3. Pull latest from origin/main and rebase volitional-director if needed (only if origin/main moved).

**During each phase:**
1. Follow the task steps verbatim.
2. Use TDD: write failing test → verify fail → implement → verify pass → commit.
3. Run ruff + pyright before commit. Fix any issue.
4. Commit with a clear message; no `--no-verify`.

**After each phase:**
1. Run `systemctl --user restart studio-compositor.service` (or `rebuild-services.timer` waits).
2. Capture a 1920×1080 frame from `/dev/video42`.
3. Visual smoke: confirm nothing regressed (reverie still shows content, cameras still feed, overlays still present).
4. Mark the phase's checkbox in this file; append a one-line note to the Changelog at the bottom.

**Rollback:** per-phase rollback procedures live in the spec §9. Runtime flags: `HAPAX_DIRECTOR_MODEL_LEGACY=1` (restores pre-epic director), `HAPAX_COMPOSITOR_LAYOUT=default-legacy.json` (restores pre-epic layout). Both implemented as part of Phase 1 and Phase 4 respectively.

## Branch discipline

- **Single branch for the whole epic:** `volitional-director` / PR #1017.
- Commit granularity: one commit per logical step within a phase; multiple commits per phase acceptable; phase ends with a squashed-summary commit OR a clean chain of commits (pick per-phase based on complexity).
- No branch switches except to pull/rebase origin/main.
- Force-push only to clean up commit history within the epic — never to rewrite history a reviewer might have already seen. Prefer new commits.

## Audit gate

Before Phase 1 begins: perform the self-audit described in the writing-plans skill:
1. Spec coverage — each phase ties back to a numbered section of the design spec.
2. Placeholder scan — no TBDs, no "similar to Task N"; each phase plan contains complete code blocks for each step.
3. Type consistency — Pydantic model field names used in Phase 1 match those referenced in Phases 2-7.
4. Open questions — surface any findings from the audit that change the phase plans; fix inline.

Audit fixes land before Phase 1's first commit.

## Changelog

- 2026-04-17 (alpha) — master plan created.
- 2026-04-17 (alpha) — Phase 0 shipped (commit 2377fee66, BGRA fix).
- 2026-04-17 (alpha) — self-audit run; 5 fixes applied (narrative-state.json for twitch, overlay-alpha-overrides + hero-camera-override + recent-recruitment SHM files explicit, preset_family_selector.py named, condition_id reader doc, DMN impingement cross-consumption risk flagged in spec §13).
- 2026-04-17 (alpha) — Phase 1 shipped (DirectorIntent + wiring, 2 commits, 31 tests). Legacy flag `HAPAX_DIRECTOR_MODEL_LEGACY=1` works; JSONL + narrative-state.json writing on every director tick.
- 2026-04-17 (alpha) — Phase 2 shipped (PerceptualField + director-prompt integration, 1 commit, +14 tests). Every existing classifier/detector reaches the director as typed JSON inside `<Perceptual Field>` block. No new sensors.
- *(phases 3-9 ship here)*

## Resumption notes (for the session that continues this epic)

**Where we are:** commits on `volitional-director` through `d9b1fc861`. Phases 0, 1, 2 shipped cleanly. Test suites green (Phase 1: 31 tests; Phase 2: 14 tests; total 45). Two pre-existing unrelated test failures in `test_compositor_wiring.py` (expected set lacks `captions` but origin/main layout has it; not our fault, not blocking).

**What the running system looks like now:**
- Director emits `DirectorIntent` (behind the scenes — LLM still returns `{activity, react}` until Phase 3 teaches it the richer shape).
- `~/hapax-state/stream-experiment/director-intent.jsonl` accumulates one line per tick.
- `/dev/shm/hapax-director/narrative-state.json` exists with current stance/activity.
- Director prompt contains `## Perceptual Field` block with full structured JSON of contact-mic / MIDI / vision / IR / stimmung / album / chat-aggregate / presence / context signals.
- Legacy flag `HAPAX_DIRECTOR_MODEL_LEGACY=1` bypasses new behavior cleanly.

**Next up: Phase 3.** `docs/superpowers/plans/2026-04-17-phase-3-compositional-recruitment.md` is the executable plan. Scope:
- Create compositional capability catalog (camera.hero.*, fx.family.*, overlay.foreground.*, youtube.direction.*, attention.winner.*) under `shared/affordances/compositional/`.
- Seed Qdrant `affordances` collection with the catalog.
- Create `agents/studio_compositor/compositional_consumer.py` that translates pipeline recruitments into compositor mutations.
- Demote `random_mode` and `_reload_slot_from_playlist` to fallbacks; retire `objective_hero_switcher` direct-dispatch path.
- Wire attention-bid dispatch to recruitment.

Phase 3 is the largest remaining phase. Allow ~2-3 hours of uninterrupted execution context.

**Phases 4-9** are smaller and well-scoped per their plans. Phase 8 (DEVIATION record + new condition declaration) must ship before Phase 9 rehearsal attempts activation.

**Not-yet-done that's external to this plan:** the dirty state in the `hapax-council` main worktree (78 D-staged files from a prior aborted cleanup) remains untouched. It's unrelated to this epic. Operator should either `git restore` those paths or investigate before the next main-worktree push.

**Rehearsal timing:** per `docs/research/2026-04-17-expected-behavior-at-launch.md §4`, the first real live attempt goes via 30-minute private rehearsal. Phase 9 owns this gate. Until Phases 3-7 land, the system runs in Phase 0-2 configuration (PerceptualField in prompt, no compositional recruitment yet, no multi-rate, no new legibility surfaces).
