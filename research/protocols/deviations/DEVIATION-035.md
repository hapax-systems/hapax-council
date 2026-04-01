# DEVIATION-035: Activation Score Telemetry + Stale Comment Removal

**Date:** 2026-03-31
**Phase:** A (baseline)
**Path:** agents/hapax_daimonion/conversation_pipeline.py
**Zone:** Middle (behavioral freeze)

## Changes

### 1. Activation score telemetry (3 lines added)
Add 3 `hapax_score()` calls after salience router returns, logging:
- `novelty` (float, 0-1)
- `concern_overlap` (float, 0-1)
- `dialog_feature_score` (float, 0-1)

### 2. Stale comment removal (5 lines removed)
Remove misleading comments at lines 993-995 ("Tools disabled for voice pacing")
and lines 1189-1190 ("TODO: re-enable with tight per-tool timeouts"). Both
contradict the actual code which passes tools and calls the handler.

## Justification

### Telemetry
Observability-only. These calls log numeric scores to Langfuse traces.
They do not alter model input, model output, model selection, or any
behavioral parameter. The salience router already computes these values
every turn. This change makes them visible in Langfuse for Sprint 1
correlation analysis (Measure 7.2).

### Comments
Non-functional change. Removes 5 comment lines that describe dead behavior.
No code logic affected.

## Impact on experiment validity

None. Scores are written after the turn completes. No feedback loop.
Comment removal has zero runtime effect.
