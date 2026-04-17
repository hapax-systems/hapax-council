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
- *(phases 1-9 ship here)*
