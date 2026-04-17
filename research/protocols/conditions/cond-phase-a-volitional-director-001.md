# Condition: cond-phase-a-volitional-director-001

**Declared:** 2026-04-17
**Parent condition:** cond-phase-a-persona-doc-qwen-001
**Status:** declared-not-yet-active (activation pending Phase 9 rehearsal)
**Declarer:** alpha (volitional-grounded-director epic, PR #1017)
**Related DEVIATION:** DEVIATION-037
**Design spec:** `docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md`

## Delta description (vs parent)

Enumerated concrete changes relative to `cond-phase-a-persona-doc-qwen-001`:

1. **Director output shape.** Parent emitted `{activity, react}` (6-label vocabulary). This condition emits `DirectorIntent`: stance (Stance enum), 13-label activity vocabulary (HSEA Phase 2 extension), `grounding_provenance: list[str]`, `compositional_impingements: list[CompositionalImpingement]`.

2. **Director input context.** Parent used `phenomenal_context.render(tier="FAST")` prose. This condition emits `PerceptualField.model_dump_json(exclude_none=True)` — structured JSON of every classifier/detector output (Pi NoIR YOLOv8n, studio RGB YOLO, SCRFD, SigLIP2, CLAP, contact mic DSP, MIDI clock, cross-modal detected_action, overhead_hand_zones, stimmung 12-dim, album, chat aggregate).

3. **Compositional recruitment.** Parent had three independent shufflers (random_mode preset, YouTube `random.choice`, hardcoded `objective_hero_switcher`) with no director supervision. This condition declares the compositional capability catalog (26 capabilities across camera.hero.*, fx.family.*, overlay.*, youtube.*, attention.winner.*, stream.mode.*.transition) and the consumer that dispatches recruited names to SHM state files. Director-side impingement emission to AffordancePipeline lands in Phase 3c (pending).

4. **Legibility surfaces.** Parent had no on-frame activity/stance indicator (set_header was a no-op; captions registered but not laid out). This condition adds 4 new CairoSource subclasses (ActivityHeader, StanceIndicator, ChatKeywordLegend, GroundingProvenanceTicker) registered for Layout-JSON declarability.

5. **Multi-rate directorial hierarchy.** Parent had single 8-second director tick. This condition plans twitch (4-5 s deterministic Python) + narrative (15-30 s grounded-LLM, slowed from 8 s) + structural (150 s grounded-LLM) — Phase 5 of the epic (pending).

6. **Consent live-egress gate.** Parent enforced consent at recording valve + Qdrant writes only; live video egress was unprotected. This condition closes that gap (Phase 6, pending) — compose-safe fallback layout on guest detection without active contract.

7. **Research observability.** Parent emitted Langfuse span + existing Prometheus metrics. This condition adds `~/hapax-state/stream-experiment/director-intent.jsonl`, condition-labelled Prometheus counters for grounding signals + compositional impingements + twitch moves + structural intents, and histograms for per-tier LLM latency.

## Measurable hypotheses

- **H1: grounding_provenance coverage.** Mean provenance signals per narrative tick ≥ 3 over a 30-minute sample (parent baseline: 0–1 under stimmung-prose collapse).
- **H2: palette coverage.** 10-minute-window palette_coverage_ratio ≥ 0.5 across the 6 compositional families (unachievable under parent — only preset.bias was ever exercised by random_mode).
- **H3: activity/stance transition rate.** Increases vs parent without regression in p95 narrative-tick LLM latency.
- **H4: RIFTS clarifying-question rate (non-inferiority).** Does NOT worsen vs parent (parent is `cond-phase-a-persona-doc-qwen-001` 8.2% ambiguous / 3.9% non-ambiguous — see `docs/research/2026-04-15-rifts-qwen3.5-9b-baseline.md`). Acceptance bound: +1% absolute.

## Activation criteria

All of:

- Phases 0–7 of the volitional-director epic merged to main (Phase 3c and 3b wiring land at or before Phase 9 gate).
- Phase 9 rehearsal passes — 30-minute private rehearsal per `docs/research/2026-04-17-expected-behavior-at-launch.md §4`:
  - Activity distribution within prediction ±10%.
  - Persona coherence (no posture-vocabulary leakage into narrative prose).
  - Overlay visual audit at 1920×1080 clean.
  - TTS quality over music (ducker works).
  - No stacktraces in the 30-minute window.
- `scripts/research-registry.py open cond-phase-a-volitional-director-001` invoked; `/dev/shm/hapax-compositor/research-marker.json` carries the new id.
- Operator sign-off on DEVIATION-037 (pre-authorized per 2026-04-17 directive "execute without intervention, we can always adjust later").

## Rollback criteria

- RIFTS clarifying-question rate regresses > +1% vs parent baseline (H4 violated).
- ≥ 5 director parse failures per 10 minutes sustained.
- Palette-coverage ratio stays below 0.3 after 20 minutes of active use (H2 inverted — the catalog isn't being recruited because impingements aren't landing).
- Operator override.

Rollback procedure: set `HAPAX_DIRECTOR_MODEL_LEGACY=1` (+ optional `HAPAX_COMPOSITOR_LAYOUT=default-legacy.json`) in systemd drop-in, daemon-reload, restart compositor. Mark this condition as closed with failure note; parent condition resumes.

## Sample-size target

≥ 8 post-activation sessions before MCMC BEST analysis, matching parent's ongoing sample target. Aims for 2026-05-10 at current session cadence.

## Data-path notes for analysts

- Condition ID in `~/hapax-state/stream-experiment/director-intent.jsonl` under `condition_id` per line.
- Langfuse tag `stream-experiment` with `condition_id` metadata.
- Prometheus metrics labelled `condition_id=<id>`.
- `scripts/director-intent-replay.py` (Phase 7 follow-up) replays a session's JSONL for offline analysis.
