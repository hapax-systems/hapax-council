# Claim 6: Bayesian Mode/Tool Selection Improves Tool-Assisted Grounding

## Prior
Uninformative: Beta(1, 1) — no prior evidence that Bayesian mode
selection improves grounding over monolithic tool access. The system
has never had mode-aware tool composition. Equal weight to all outcomes.

## Prediction
Bayesian mode/tool selection — where a posterior probability over
operational modes determines a composed tool palette and knowledge
context per turn — will improve `context_anchor_success` on tool-invoked
turns by ≥0.20 compared to monolithic tool access (all 20+ tools
available on every turn).

## ROPE
[-0.1, 0.1] — differences within 10% are practically equivalent.
Wider than claim 1 ROPE because tool-invoked turns have higher
variance (tool results inject external data that may or may not
anchor to conversation context).

## Metric
- Primary: `context_anchor_success` on turns where tools were invoked
  (filtered to tool-active turns only)
- Secondary: `tool_fitness_hit_rate` — proportion of tool calls that
  passed fitness gating AND improved the next turn's anchor score
- Tertiary: `mode_stability` — mode transitions per session
  (too stable = unresponsive, too unstable = thrashing)
- Success metric: frustration composite on tool-invoked turns

## Sequential Stopping Rule
Stop when Bayes Factor > 10 (decisive evidence for or against), or
after 30 sessions with ≥3 tool-invoked turns each.

## Design
SCED A-B with component flags:
- Phase A (control): monolithic tools re-enabled (all tools, all turns)
- Phase B (intervention): Bayesian mode selection with atomic primitives

Feature flag: `components.bayesian_tools` in experiment JSON.

Note: Phase A for this claim uses monolithic tools, NOT the tools-disabled
state from claims 1-5. The comparison is mode-selected tools vs all-tools,
not tools vs no-tools.

## Dependencies
- Claim 1 must be completed (Phase B + Phase A' reversal)
- Atomic tool primitives must be implemented
- Mode selector must be implemented with experiment flag gating
- Tool fitness scoring must be added to Langfuse instrumentation

## Pre-Registration Date
Not yet pre-registered. Document prepared 2026-03-20 during claim 1
Phase B data collection. Will be formally pre-registered after claim 1
cycle completes and results are reported.
