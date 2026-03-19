# Claim 5: Salience Activation Correlates with Response Properties

## Prior
Normal(0.3, 0.15) — centered on the predicted effect size with moderate
uncertainty. If the true correlation is near zero, the prior will be
updated toward the null.

## Prediction
Higher `activation_score` from the salience router correlates positively
(r ≥ 0.3) with response length and `context_anchor_success`.

## ROPE
[-0.1, 0.1] for r — correlations within this range are practically zero.

## Metric
- Primary: Pearson r between activation_score and response token count
- Secondary: Pearson r between activation_score and context_anchor_success

## Sequential Stopping Rule
Stop after 50+ turns with valid activation scores, or when Bayes Factor > 10.
Run via `eval_grounding.py` after sufficient data collection.

## Design
Correlation analysis across sessions. No component flag needed — salience
routing is always active when the salience router is configured. The
analysis compares turns with varying activation levels within the same
condition.

## Pre-Registration Date
2026-03-19
