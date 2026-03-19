# Conversational Continuity Proofs

Pre-registered hypotheses and validation artifacts for the conversational
continuity design (DESIGN-conversational-continuity.md).

## Structure

Each claim gets a directory:
```
claim-N/
  hypothesis.md    — prediction, null, metric, design, date
  design.md        — detailed experiment design (after baseline)
  data/            — raw Langfuse exports and session logs
  analysis/        — scripts and results
```

## Claims

| # | Claim | Status |
|---|-------|--------|
| 1 | Stable frame improves context_anchor_success | pre-registered |
| 2 | Simple message drop maintains reference_accuracy | pre-registered |
| 3 | Cross-session memory enables recall of prior sessions | pre-registered |
| 4 | Sentinel fact survives system prompt rebuilds | pre-registered |
| 5 | Salience activation correlates with response depth | pre-registered |

## Methodology

Bayesian SCED with sequential stopping and per-component feature flags.

Each claim specifies:
- **Prior** — Beta or Normal distribution encoding pre-experiment belief
- **ROPE** — Region of Practical Equivalence (null zone)
- **Sequential Stopping Rule** — BF > 10 or max sessions
- **Component flag** — individual feature toggle for A-B-A phases

Primary success metric across all claims: **frustration composite**
(`frustration_rolling_avg` from `FrustrationDetector`), adapted from
Datadog RUM frustration signals + COLING 2025 dialogue breakdown research.

Use `~/.cache/hapax/voice-experiment.json` to set condition:
```json
{
  "name": "continuity-v1",
  "condition": "A",
  "phase": "baseline",
  "components": {
    "stable_frame": false,
    "message_drop": false,
    "cross_session": false,
    "sentinel": false
  }
}
```

No experiment JSON = all components ON (production default).
