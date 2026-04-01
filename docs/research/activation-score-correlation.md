# Activation Score Correlation Analysis (Measure 7.2)

**Date:** 2026-03-31
**Sprint:** 0, Day 2

## Summary

**Data gap: N = 0.** No `activation_score` entries exist in Langfuse. Correlation analysis cannot proceed.

## Query results

- **Langfuse reachable:** Yes (v3.157.0 at localhost:3000)
- **Scores named `activation_score`:** 0
- **Scores named `context_anchor_success`:** Not checked (moot given N=0)
- **N (turns with both scores):** 0
- **Threshold (N >= 50):** Not met

## Root cause

The `hapax_score()` calls that log `activation_score` to Langfuse are in `conversation_pipeline.py` — which is in the experiment freeze zone (measure 7.1 requires DEVIATION-025 to add the logging). Until DEVIATION-025 is filed and the 3 score calls are added, no activation data flows to Langfuse.

## Sprint 0 gate check

The schedule says: "If 7.2 shows r < 0.1, STOP and rescope salience measures." Since N = 0, we cannot compute r. This is not a gate failure — it is a prerequisite gap. The gate cannot be evaluated until data collection begins.

## Collection plan

1. File DEVIATION-025 (measure 7.1) — adds 3 `hapax_score()` calls to `conversation_pipeline.py`
2. Run at least 50 voice sessions with the instrumented pipeline
3. At ~5 sessions/evening, estimate 10 evenings to reach N = 50
4. Re-run 7.2 correlation analysis after collection

## Conclusion

7.2 is blocked on 7.1 (DEVIATION-025). No data exists yet. This is expected — the schedule anticipated 7.1 as a Day 1 prerequisite. Collection plan documented above.
