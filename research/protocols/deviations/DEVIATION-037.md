# Deviation Record: DEVIATION-037

**Date:** 2026-04-17
**Phase at time of change:** baseline (Phase A accumulation under `cond-phase-a-persona-doc-qwen-001`)
**Author:** alpha (volitional-grounded-director epic, PR #1017)

## What Changed

The studio-compositor director's data path and behavior were materially extended. Concretely:

- **Output signature.** `agents/studio_compositor/director_loop.py::_parse_intent_from_llm` now funnels the LLM response through `shared/director_intent.py::DirectorIntent` — adds `stance` (shared.stimmung.Stance enum), `grounding_provenance: list[str]`, `compositional_impingements: list[CompositionalImpingement]`, and extends the activity vocabulary from 6 → 13 labels (HSEA Phase 2). Legacy `{activity, react}` LLM responses still parse into a minimal DirectorIntent (stance=NOMINAL, empty provenance, empty impingements) — behavior is backward-compatible.
- **Input context.** `_build_unified_prompt` now embeds `shared/perceptual_field.py::PerceptualField.model_dump_json(exclude_none=True)` inside a `<Perceptual Field>` block. Every existing classifier/detector (Pi NoIR YOLOv8n, studio RGB YOLO, SCRFD, SigLIP2, cross-modal `detected_action`, `overhead_hand_zones`, CLAP, contact mic DSP, MIDI clock, stimmung 12-dim, album identifier, chat aggregate) is now first-class typed JSON in the prompt. No new sensors.
- **Artifacts.** Each director tick now also writes:
  - `~/hapax-state/stream-experiment/director-intent.jsonl` — append, one line per tick, condition-tagged.
  - `/dev/shm/hapax-director/narrative-state.json` — atomic, carries stance + activity + condition_id for downstream twitch-director consumption.
  - Prometheus counters/histograms per `shared/director_observability.py` (condition-labelled).
- **Compositional catalog** (`shared/compositional_affordances.py`): 26 CapabilityRecords across 6 families (camera.hero, fx.family, overlay, youtube, attention.winner, stream.mode.transition) ready for AffordancePipeline recruitment. Consumer in `agents/studio_compositor/compositional_consumer.py` dispatches recruited names to atomic SHM files the compositor layer reads.
- **Legibility** (Phase 4): 4 new CairoSource classes (ActivityHeaderCairoSource, StanceIndicatorCairoSource, ChatKeywordLegendCairoSource, GroundingProvenanceTickerCairoSource) registered for layout declarability. Layout assignment is operator-owned.
- **Rollback flag** `HAPAX_DIRECTOR_MODEL_LEGACY=1` reverts to pre-epic `{activity, react}` behavior + skips new artifact emission.

Full design: `docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md`. Per-phase plans under `docs/superpowers/plans/2026-04-17-phase-*.md`.

Frozen-files discipline respected: `grounding_ledger.py`, `grounding_evaluator.py`, `stats.py`, `experiment_runner.py`, `eval_grounding.py`, `proofs/`, `conversation_pipeline.py`, `persona.py`, `conversational_policy.py` are untouched.

## Why

Operator directive 2026-04-17: "the whole thing should be OBVIOUSLY HOSTED AND RUN AND DIRECTOR by Hapax. Volitional on Hapax's part, making USE of all these options in a GROUNDED way. Highly active. Even while OTHER things are being highlighted (music)."

Pre-existing gap (three independent research agents confirmed 2026-04-17):
- Director emitted only `{activity, react}` labels; three independent shufflers (random_mode preset, YouTube `random.choice`, hardcoded `objective_hero_switcher`) made compositional decisions without supervision.
- The system's ~15 classification/detection pipelines (Pi NoIR YOLO, studio RGB YOLO, SCRFD, SigLIP2, CLAP, contact mic DSP, MIDI clock, cross-modal `detected_action`, `overhead_hand_zones`, stimmung) reached `presence_engine` and `visual_layer_aggregator` — but not the director's prompt. The director could not ground its moves in specific perceptual evidence.
- `set_header` was a no-op; captions source registered but not in any layout; attention bids silent. The director's internal activity was invisible on-frame.

Closing this gap while preserving:
- Unified Semantic Recruitment (all expression goes through AffordancePipeline; director emits *impingements* not direct capability invocations).
- Imagination produces intent, not implementation.
- Director-grounding-critical axiom (`feedback_director_grounding.md`) + grounding-exhaustive axiom (`feedback_grounding_exhaustive.md`) + single-grounded-model rule.
- LRR Phase 7 persona/posture/role data model (existing Stance enum; posture vocabulary glossary-only).
- All five constitutional/domain axioms (single_user, executive_function, management_governance, interpersonal_transparency + it-irreversible-broadcast, corporate_boundary).

## Impact on Experiment Validity

**Moderate.** The director's observable behavior changes substantially within Phase A sample accumulation. Running a mixed Phase-A sample across old and new director behavior would confound the RIFTS clarifying-question-rate signal and the MCMC BEST grounding-rate posterior.

Mitigation — a new condition is declared (see below) so the sample stratifies cleanly.

## Mitigation

1. **New condition:** `cond-phase-a-volitional-director-001` declared concurrently with this deviation. Pre-deviation sessions remain valid under `cond-phase-a-persona-doc-qwen-001`. Post-activation sessions are analyzed under the new condition. MCMC BEST treats as separate strata.

2. **Activation gate:** the new condition activates only after Phase 9's 30-minute private rehearsal passes (see `docs/superpowers/plans/2026-04-17-phase-9-rehearsal.md`) — gate criteria on activity distribution (±10% of prediction), persona coherence (no posture-vocabulary leakage), overlay visual audit, TTS quality over music, zero stacktraces.

3. **Runtime rollback:** `HAPAX_DIRECTOR_MODEL_LEGACY=1` (+ optional `HAPAX_COMPOSITOR_LAYOUT=default-legacy.json`) reverts director behavior to pre-epic. In the rollback case, `cond-phase-a-persona-doc-qwen-001` resumes, and the new-condition sessions are marked invalid.

4. **Hypotheses tied to the new condition** (for clean post-hoc analysis):
   - H1: grounding_provenance coverage ≥3 signals per narrative tick on average (parent baseline: 0–1 under stimmung-prose collapse).
   - H2: palette_coverage_ratio (10-min window) ≥ 0.5 across the 6 compositional families.
   - H3: stance/activity transition rate increases without Langfuse latency regression.
   - H4: RIFTS clarifying-question rate does NOT worsen vs parent baseline (non-inferiority bound).

5. **Audit trail:** every DirectorIntent is logged to `~/hapax-state/stream-experiment/director-intent.jsonl` with condition_id; Prometheus counters are condition-labelled; Langfuse spans carry the condition tag (existing mechanism).

6. **Frozen-files protection:** None of the condition-frozen files (`grounding_ledger.py`, `grounding_evaluator.py`, `stats.py`, `experiment_runner.py`, `eval_grounding.py`, `proofs/`, `conversation_pipeline.py`, `persona.py`, `conversational_policy.py`) is modified by this epic. Verified by git diff review during self-audit.
