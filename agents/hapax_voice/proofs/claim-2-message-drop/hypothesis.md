# Claim 2: Simple Message Drop Maintains Reference Accuracy

## Prior
Optimistic: Beta(8, 2) — conversation thread is designed to compensate for
dropped messages. Prior belief that reference_accuracy stays high.

## Prediction
Replacing LLMLingua-2 lossy compression with simple message dropping
(keep system + last 5 user exchanges) will maintain `reference_accuracy` ≥0.8
on sessions with 10+ turns, while the conversation thread compensates
for dropped context.

## ROPE
[-0.1, 0.1] — 10% degradation from baseline is acceptable given the
simplicity gain.

## Metric
- Primary: `reference_accuracy` (Langfuse, per-turn, float 0-1)
- Secondary: operator clarification requests (CLARIFY acceptance type)
- Success metric: frustration composite (`frustration_rolling_avg`)

## Sequential Stopping Rule
Stop when Bayes Factor > 10 (decisive evidence for or against), or after
20 sessions exceeding 10 turns each.

## Design
SCED A-B with component flags:
- Phase A (baseline): `message_drop: false` in experiment JSON (no dropping)
- Phase B (intervention): `message_drop: true` (5-exchange window active)

Feature flag: `components.message_drop` in `~/.cache/hapax/voice-experiment.json`.

## Pre-Registration Date
2026-03-19
