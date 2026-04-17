# Phase 8 — DEVIATION Record + Condition Declaration

**Spec:** §12 research-condition declaration, §5 Phase 8
**Goal:** The epic substantially changes director behavior mid-Phase-A. Per LRR Phase 1 research-registry discipline + the frozen-files commitment under `cond-phase-a-persona-doc-qwen-001`, file a DEVIATION record and declare a new condition. Update RESEARCH-STATE.md.

## File manifest

- **Create:** `research/deviations/2026-04-17-volitional-director.md` — DEVIATION record with rationale, scope, rollback plan.
- **Create:** `research/conditions/cond-phase-a-volitional-director-001.md` — new condition declaration.
- **Modify:** `research/registry.jsonl` — add the new condition entry (append-only).
- **Modify:** `agents/hapax_daimonion/proofs/RESEARCH-STATE.md` — reflect the new condition + epic status.
- **Modify:** `/dev/shm/hapax-compositor/research-marker.json` setter — per LRR Phase 1 `research-registry.py open` command, declare the new condition as active.

## DEVIATION record content

Format per `research/deviations/` existing templates. Fields:

- **Date:** 2026-04-17
- **Condition of record:** `cond-phase-a-persona-doc-qwen-001`
- **Direction:** replacement — the volitional-director epic supersedes the persona-doc-only condition with a richer condition that includes persona-doc + perceptual-field + compositional-impingements + multi-rate.
- **Rationale:** operator directive 2026-04-17 (ontological reframing: livestream is the enactment of volitional grounded authorship). Directive scope is architecturally separable from persona-doc activation; extending the current condition would mix factors; declaring a new condition preserves clean A/B comparability.
- **Data impact:** Phase A accumulated sessions under `cond-phase-a-persona-doc-qwen-001` remain valid. New sessions under the new condition are analyzed separately. MCMC BEST analysis will treat as separate strata.
- **Rollback plan:** runtime flags `HAPAX_DIRECTOR_MODEL_LEGACY=1` + `HAPAX_COMPOSITOR_LAYOUT=default-legacy.json` + stopping twitch/structural units reverts to pre-epic behavior → condition `cond-phase-a-persona-doc-qwen-001` resumes.
- **Scope boundary:** does NOT touch frozen files (`grounding_ledger.py`, `grounding_evaluator.py`, `stats.py`, `experiment_runner.py`, `eval_grounding.py`, `proofs/`, `conversation_pipeline.py`, `persona.py`, `conversational_policy.py`). Verified at epic scope.
- **Approval:** operator pre-authorized 2026-04-17 ("execute without intervention, we can always adjust later"). DEVIATION filed for audit trail.

## Condition declaration content

Format per `research/conditions/` existing templates. Fields:

- **Condition ID:** `cond-phase-a-volitional-director-001`
- **Parent condition:** `cond-phase-a-persona-doc-qwen-001`
- **Declared:** 2026-04-17
- **Delta description:** enumerates the concrete changes relative to parent:
  1. Director output: `DirectorIntent` (13-activity + stance + grounding_provenance + compositional_impingements) vs parent's `{activity, react}`.
  2. Director input: `PerceptualField` structured JSON vs parent's stimmung-prose.
  3. Compositional recruitment: capabilities recruited via `AffordancePipeline` impingements vs parent's three shufflers.
  4. Legibility: 5 new Cairo surfaces (stance_indicator, activity_header, captions, chat_legend, provenance_ticker) vs parent's 4 PiPs + stream_overlay.
  5. Multi-rate: twitch (4 s) + narrative (20 s) + structural (150 s) vs parent's narrative (8 s) only.
  6. Consent gate: live-video egress compose-safe on guest detection vs parent's recording/Qdrant-only gate.
  7. Observability: grounding_provenance + palette_coverage + twitch_move metrics added.
- **Measurable hypotheses (tied to Bayesian validation Claim set):**
  - H1: grounding_provenance coverage is ≥3 signals per narrative tick on average (vs parent's 0-1).
  - H2: palette_coverage_ratio 10-min window ≥ 0.5 (4+ families out of ~8 active).
  - H3: stance/activity transition rate increases without Langfuse latency regression.
  - H4: clarifying-question rate (RIFTS) does NOT worsen vs parent (non-inferiority).
- **Activation criteria:** all of:
  - Phases 0-7 of the volitional-director epic merged to main.
  - Phase 9 rehearsal (30-min private) passes (activity distribution within ±10% of predicted, no stacktraces, visual audit clean).
  - Operator sign-off on DEVIATION record (implicit per directive).
- **Rollback criteria:**
  - Clarifying-question rate regresses &gt;2% vs parent baseline.
  - ≥5 director parse failures per 10 min sustained.
  - Operator override command.
- **Sample size target:** ≥8 sessions post-activation (matches parent's ongoing sample target).

## Tasks

- [ ] **8.1** — Locate DEVIATION template: `ls research/deviations/*.md | head -3` — read an example, match format.
- [ ] **8.2** — Locate condition template: `ls research/conditions/*.md | head -3` — read an example, match format.
- [ ] **8.3** — Write `research/deviations/2026-04-17-volitional-director.md` per the content above.
- [ ] **8.4** — Write `research/conditions/cond-phase-a-volitional-director-001.md` per the content above.
- [ ] **8.5** — Append to `research/registry.jsonl` one line:
  ```json
  {"id": "cond-phase-a-volitional-director-001", "parent": "cond-phase-a-persona-doc-qwen-001", "declared_at": "2026-04-17T...", "status": "declared-not-yet-active", "source": "alpha", "spec": "docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md"}
  ```
- [ ] **8.6** — Update `agents/hapax_daimonion/proofs/RESEARCH-STATE.md` with:
  - Epic status: active (2026-04-17).
  - New condition id declared; activation pending Phase 9.
  - Operator directive date + summary.
- [ ] **8.7** — Commit: `research(deviation): volitional-director epic — declare cond-phase-a-volitional-director-001`.
- [ ] **8.8** — Do NOT activate the condition yet. Activation is Phase 9's gate.
- [ ] **8.9** — Mark Phase 8 ✓.

## Acceptance criteria

- DEVIATION record exists at the expected path, matches existing format.
- New condition declared in `research/conditions/` and appended to `research/registry.jsonl`.
- RESEARCH-STATE.md reflects the change.
- Registry.jsonl remains append-only; no prior entries modified.
- Condition status is `declared-not-yet-active` until Phase 9 activates.

## Test strategy

No automated tests. Manual verification:
- `cat research/registry.jsonl | tail -3` shows new entry cleanly.
- `jq` parses without error.
- RESEARCH-STATE.md renders readable.

## Rollback

Remove the appended registry line + delete the two new doc files.

## Notes

This phase is deliberately light on code. Its purpose is research-discipline: the epic's technical substance must be accompanied by research-log artifacts so that the livestream-as-research-instrument principle holds.
