# Claim 4: Sentinel Fact Survives System Prompt Rebuilds

## Prior
Optimistic: Beta(9, 1) — sentinel is now injected in `_update_system_context()`
rather than appended once at `start()`, so it should survive all rebuilds.

## Prediction
A sentinel number injected at session start will be correctly retrieved
when the operator asks a probe question ("what's my favorite number?")
at any point during the session, with ≥90% accuracy.

## ROPE
[0.85, 1.0] — retrieval below 85% indicates the sentinel is being lost.

## Metric
- Primary: `sentinel_retrieval` (Langfuse, per-probe, binary 0/1)

## Sequential Stopping Rule
Stop when Bayes Factor > 10 (decisive evidence for or against), or after
15 probe questions across sessions.

## Design
Probe questions at turns 2, 5, and 10+ across sessions:
- `sentinel: false` → baseline (no sentinel injected)
- `sentinel: true` → intervention (sentinel in system prompt)

Feature flag: `components.sentinel` in `~/.cache/hapax/voice-experiment.json`.

## Pre-Registration Date
2026-03-19
