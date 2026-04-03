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

## Architectural State Snapshot (2026-04-03)

The Unified Semantic Recruitment (USR) architecture deployed on 2026-04-03
(Total Affordance Field epic, PRs #573–#579) is the mechanism this claim
tests. Documenting the current state for Phase A baseline reconstruction:

**Pipeline mechanism:** `AffordancePipeline` in `shared/affordance_pipeline.py`.
Scoring: `0.50×cosine_similarity + 0.20×base_level + 0.10×context_boost
+ 0.20×thompson_sample`. SEEKING stance halves threshold (0.05 → 0.025).
Thompson prior: Beta(2,1) optimistic. Decay: gamma=0.99.

**Tool recruitment:** `ToolRecruitmentGate` in `agents/hapax_daimonion/tool_recruitment.py`.
Converts utterance → Impingement(source="operator.utterance", strength=1.0),
calls pipeline.select(), filters to tool names. 31 tools registered with
Gibson-verb descriptions in `agents/hapax_daimonion/tool_affordances.py`.

**Shared registry:** `shared/affordance_registry.py` — 87 affordances across
9 domains (env, body, studio, space, digital, knowledge, social, system,
world) + 12 shader nodes + 2 content + 3 legacy. All indexed in both
Reverie and Daimonion pipeline instances.

**Feature flag:** World domain routing gated by file existence at
`~/.cache/hapax/world-routing-enabled` (hot-toggleable). Tool recruitment
gate in `conversation_pipeline.py:995-1009` fires only when `self.tools`
is populated (empty during experiment sessions).

**Experiment isolation:** DEVIATION-040 confirms volatile_lockdown gate
prevents all affordance content from reaching experiment sessions. The
Phase A condition ("monolithic tools re-enabled, all tools, all turns")
can be reconstructed by: (1) setting `self.tools` to the full tool list,
(2) bypassing the ToolRecruitmentGate, (3) disabling world routing flag.
This is equivalent to setting `components.bayesian_tools=false` in the
experiment JSON.

**Phase A reconstruction path:** When this claim begins, Phase A will use
`components.bayesian_tools=false` which disables `ToolRecruitmentGate`
and presents all 31 tools on every turn (monolithic mode). Phase B will
use `components.bayesian_tools=true` which enables the gate, letting the
AffordancePipeline select tools per-utterance via cosine similarity +
Thompson sampling.

**Git reference:** Total Affordance Field epic commit range: `f5dcb4b1`
(Phase 1 start) through `3b2e365f` (gap closure complete). Full spec at
`docs/superpowers/specs/2026-04-03-total-affordance-field-design.md`.
