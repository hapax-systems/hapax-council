# Deviation Record: DEVIATION-025

**Date:** 2026-03-30
**Phase at time of change:** baseline (Cycle 2 Phase A)
**Author:** Claude (alpha session)

## What Changed

`agents/hapax_daimonion/conversation_pipeline.py` line 1162 (after existing `activation_score` scoring):

```python
hapax_score(_utt_trace, "novelty", _bd.novelty)
hapax_score(_utt_trace, "concern_overlap", _bd.concern_overlap)
hapax_score(_utt_trace, "dialog_feature_score", _bd.dialog_feature_score)
```

Three `hapax_score()` calls added inside the existing `if _bd is not None:` block at the end of `_process_utterance()`. These write Langfuse scores only — no change to any variable, model input, model output, or control flow.

## Why

Bayesian validation measure 7.1 requires logging salience signal components to Langfuse for correlation analysis (measure 7.2). The `activation_score` (composite) is already logged but its three constituent signals are not, making it impossible to determine which component predicts grounding success.

## Impact on Experiment Validity

**None.** The change is observability-only:
- No model input modified (prompt, messages, system prompt unchanged)
- No model output modified (response generation path untouched)
- No control flow modified (no conditionals, no early returns)
- No state modified (hapax_score writes to Langfuse, not to pipeline state)
- The three values already exist in memory (`_bd` is computed before this point) — this merely persists them to the trace

## Mitigation

- Existing tests run before commit to verify no behavioral change
- Values sourced from `ActivationBreakdown` dataclass fields that are already computed and used elsewhere in the pipeline
- Change is 3 lines of pure logging, additive only
