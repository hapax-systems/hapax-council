# Protention Accuracy Validation (Measure 3.2)

**Date:** 2026-03-31
**Sprint:** 0, Day 2

## Summary

**Data gap blocks validation.** The activity classifier produces `idle` for all 8,045 perception-minutes entries. Activity Markov chain and flow timing sub-models have zero learned transitions. Only the circadian model has data (394,688 observations).

Protention prediction snapshots are not persisted — only aggregate counts go to Langfuse. No replay validation is possible until both gaps are closed.

## ProtentionEngine location

`agents/protention_engine.py` — three sub-models:
- **Activity Markov chain** — transition probabilities between activities
- **FlowTimingModel** — flow session duration predictions
- **CircadianModel** — time-of-day activity patterns

## Data state

| Sub-model | State | Observations |
|-----------|-------|-------------|
| Circadian | Populated | 394,688 observations, all 24 hours covered |
| Activity Markov | EMPTY | 0 transitions — all entries are `activity='idle'` |
| Flow timing | EMPTY | 0 flow sessions — `flow_state='idle'` throughout |

**Root cause:** `production_activity` field is empty/idle in all perception data fed to `VLA._protention.observe()`. The `llm_activity` fallback path at `aggregator.py:384` may not be exercising.

## Persistence gap

- **Model state:** Persisted to `~/.cache/hapax-daimonion/protention-state.json` (flushed every 300s). Present and current.
- **Individual predictions:** NOT persisted. `trace_prediction_tick` logs count + cache hit rate to Langfuse, but not the predictions themselves.

## Test harness

`tests/test_protention_validation.py` — 12 passed, 1 skipped (correctly):
- `TestProtentionDataGapAudit` — documents gaps, prints instrumentation guidance
- `TestProtentionReplayValidation` — replay precision/recall/lead-time (skips until non-idle data exists)
- `TestProtentionSyntheticBaseline` — synthetic coding→browsing pattern validates harness; synthetic precision=1.0

## Instrumentation needed

1. Verify `production_activity` is non-empty during active work in `perception-state.json`
2. Confirm VLA feeds correct field (check `llm_activity` fallback path)
3. Add prediction-snapshot JSONL log alongside `perception-minutes.jsonl` for replay
4. Log flow session start/end events to `~/.cache/hapax-daimonion/flow-sessions.jsonl`

## Edge case found

`FlowTimingModel.predict_remaining` can return `0.0`, producing `expected_in_s=0.0` in flow-ending predictions. Documented in test.

## Conclusion

Cannot compute precision/recall/lead-time-error until activity classifier produces non-idle labels. The circadian model alone has sufficient data but makes coarser predictions (hour-level, not minute-level). Instrumentation work is prerequisite to validation.
