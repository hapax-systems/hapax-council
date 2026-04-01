# Signal Availability Audit — Bayesian Tool Selection (Measure 8.1)

**Date:** 2026-03-31
**Sprint:** 0, Day 2

## Summary

11/16 signals exist at runtime. 3 are derivable (stimmung SHM, trivial integration). 1 has a naming mismatch (`turn_depth` → `turn_count`). 1 needs a name-to-implementation mapping decision.

The spec's claim that "all 16 signals already available at 2.5s perception tick" is overstated. The 3 stimmung-derived signals live in a separate SHM file and are not part of the unified perception tick. Integration is trivial but requires an explicit secondary read.

## Signal inventory

| Signal | Status | Location | Notes |
|--------|--------|----------|-------|
| `activation_score` | EXISTS | `conversation_pipeline.py:924` | Computed per-turn by `SalienceRouter.route()`, stored as `final_activation` |
| `novelty` | EXISTS | `salience_router.py:193` | `ConcernGraph.novelty()` from utterance embedding distance |
| `concern_overlap` | EXISTS | `salience_router.py:192` | `ConcernGraph.query()`, field on `ActivationBreakdown` |
| `dialog_feature_score` | EXISTS | `salience_router.py:196` | `_dialog_feature_score()` from `UtteranceFeatures` |
| `conversation_temperature` | EXISTS | `conversational_model.py:28` | Updated per-turn, exposed via `CognitiveLoop` |
| `presence_probability` | EXISTS | `presence_engine.py:171` | Bayesian posterior from `PresenceEngine` |
| `interruptibility_score` | EXISTS | `_perception_state_writer.py:358` | From perception backend |
| `activity_mode` | EXISTS | `_perception_state_writer.py:357` | Rich coverage (65 files) |
| `flow_state` | EXISTS | `_perception_state_writer.py:335` | Derived from flow_state_score float |
| `heart_rate` | EXISTS | `_perception_state_writer.py:377` | As `heart_rate_bpm` — minor naming mismatch |
| `active_window` | EXISTS | `perception.py:190` | `PerceptionState.active_window: WindowInfo`, via Hyprland IPC |
| `stimmung_stance` | DERIVABLE | `/dev/shm/hapax-stimmung/state.json` | Not in perception tick; requires explicit SHM read |
| `resource_pressure` | DERIVABLE | `/dev/shm/hapax-stimmung/state.json` | Same gap as stimmung_stance |
| `cost_pressure` | DERIVABLE | `/dev/shm/hapax-stimmung/state.json` | Named `llm_cost_pressure` in codebase |
| `BOCPD_change_points` | DERIVABLE | `aggregator.py:1044` | Computed by `MultiSignalBOCPD`, in `VisualLayerState.recent_change_points`. Not surfaced in per-turn snapshot. |
| `turn_depth` | MISSING | n/a | Concept exists as `turn_count` in `voice_session` block. Name absent. |

## Status counts

- **EXISTS:** 11 (including `heart_rate` with minor naming mismatch)
- **DERIVABLE:** 4 (3 stimmung SHM + BOCPD in VLS)
- **MISSING:** 1 (`turn_depth` naming only)

## Integration work required

1. **Stimmung signals (3):** Add explicit `/dev/shm/hapax-stimmung/state.json` read to ModeSelector. Access pattern documented at `conversation_helpers.py:197-203`.
2. **BOCPD:** Surface `VisualLayerState.recent_change_points` in perception snapshot or read VLS directly from ModeSelector.
3. **turn_depth:** Map to `voice_session.turn_count` (already available in perception state). Decision: rename spec signal or add alias.
4. **cost_pressure:** Reconcile naming — spec says `cost_pressure`, codebase uses `llm_cost_pressure`.

## Conclusion

No fundamental gaps. All 16 signals are either available or trivially derivable from existing runtime data. The integration work is mechanical (4 explicit reads + 2 naming reconciliations).
