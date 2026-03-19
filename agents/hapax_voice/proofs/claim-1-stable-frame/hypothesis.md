# Claim 1: Stable Frame Improves Context Anchoring

## Prior
Skeptical: Beta(2, 2) — no prior evidence that thread injection helps voice
context anchoring. Equal weight to improvement and no-improvement.

## Prediction
The conversation thread injected into the system prompt will increase
`context_anchor_success` scores from baseline by ≥0.15 on sessions with
5+ turns.

## ROPE
[-0.05, 0.05] — differences within 5% of baseline are practically equivalent.

## Metric
- Primary: `context_anchor_success` (Langfuse, per-turn, float 0-1)
- Secondary: operator acceptance rate (ACCEPT/CLARIFY/IGNORE/REJECT)
- Success metric: frustration composite (`frustration_rolling_avg`)

## Sequential Stopping Rule
Stop when Bayes Factor > 10 (decisive evidence for or against), or after
30 sessions, whichever comes first. Minimum 5 turns per session.

## Design
SCED A-B-A with component flags:
- Phase A (baseline): `stable_frame: false` in experiment JSON
- Phase B (intervention): `stable_frame: true`
- Phase A' (reversal): `stable_frame: false`

Feature flag: `components.stable_frame` in `~/.cache/hapax/voice-experiment.json`.

## Pre-Registration Date
2026-03-19
