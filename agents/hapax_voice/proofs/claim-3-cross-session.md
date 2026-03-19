# Claim 3: Cross-Session Memory Enables Recall

## Prior
Uninformative: Beta(1, 1) — one-sided test. Baseline is zero recall (no
memory injection), so any improvement is meaningful.

## Prediction
With session digests persisted to episodic memory (with real `start_ts`)
and loaded via scroll at session start, the model will correctly reference
prior session content when asked "What were we talking about last time?"
in ≥80% of test cases.

## ROPE
[0, 0.2] one-sided — recall below 20% is practically equivalent to no recall.

## Metric
- Primary: manual probe question success rate (binary: correct/incorrect)
- Secondary: `context_anchor_success` on first 2 turns of new sessions

## Sequential Stopping Rule
Stop when Bayes Factor > 10 (decisive evidence for or against), or after
10 paired sessions.

## Design
Paired sessions with component flags:
- Session A: 5+ turn conversation (any condition)
- Gap: ≥5 minutes
- Session B: probe question "What were we talking about last time?"
- `cross_session: false` → baseline (no memory loaded)
- `cross_session: true` → intervention (scroll-based memory loaded)

Feature flag: `components.cross_session` in `~/.cache/hapax/voice-experiment.json`.

## Pre-Registration Date
2026-03-19
