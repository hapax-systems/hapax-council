# Format Grounding Evaluator - Design Spec

**Status:** schema seed for `format-grounding-evaluator`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/format-grounding-evaluator.md`
**Date:** 2026-04-29
**Depends on:** `grounding-commitment-no-expert-system-gate`, `autonomous-content-programming-format-registry`, `bayesian-content-opportunity-model`
**Scope:** evaluator output schema, per-format dimensions, claim evidence rules, confidence/posterior movement, grounding infractions, reward-vector inputs, feedback-ledger handoff, and engagement separation.
**Non-scope:** runner execution, scheduler policy, content uploads, public-event adapter writes, feedback-ledger storage implementation, or model-router implementation.

## Purpose

The format grounding evaluator scores a content programme run as a grounding
attempt. It does not decide domain truth, certify expertise, or optimize for
engagement as a proxy for scientific quality.

The evaluator consumes:

- a `ContentProgrammeFormat` row,
- a `GroundingCommitmentGateResult`,
- a `ContentOpportunityModelDecision`,
- the run's evidence refs, boundary events, claims, refusals, and corrections.

It emits an evidence-bound `FormatGroundingEvaluation` that downstream ledgers
can replay. Every score must remain attached to evidence, uncertainty, and
posterior movement.

## Evaluation Contract

The machine-readable schema lives at:

- `schemas/format-grounding-evaluator.schema.json`

Required top-level fields:

| Field | Meaning |
|---|---|
| `schema_version` | Evaluator schema version. Initial value is `1`. |
| `evaluation_id` | Stable evaluation id. |
| `evaluated_at` | Evaluation timestamp. |
| `producer` | Component that emitted the evaluation. |
| `run_ref` | Programme, run, format, opportunity, source, subject cluster, and public/private mode. |
| `format_evaluator_profile` | Per-format weights and grounding attempt types inherited from the format registry. |
| `gate_refs` | Grounding gate, opportunity decision, and format registry refs. |
| `grounding_question` | The exact question being grounded. |
| `dimension_scores` | Required scores for every evaluator dimension. |
| `scored_claims` | Every evaluated claim, refusal, or correction with evidence and posterior state. |
| `infractions` | Unsupported, overbroad, missing-evidence, or metric-substitution failures. |
| `evaluator_result` | Overall grounding quality, pass state, and public/refusal/correction outcome. |
| `no_expert_system_policy` | Machine-readable limits on evaluator authority. |
| `reward_vector_inputs` | Bayesian feedback inputs, with grounding and engagement separated. |
| `feedback_ledger_interface` | Event kind and update constraints for the later feedback ledger. |
| `separation_policy` | Hard rule that engagement cannot override grounding quality. |
| `audit` | Evidence, decision trace, and generated artifact refs. |

The evaluator is append-friendly: a later correction emits a new evaluation
rather than mutating away the previous result.

## Per-Format Dimension Profiles

Every evaluation includes the same dimension vocabulary so that formats can be
compared without hiding format-specific weights.

Required evaluator dimensions:

- `perception`
- `classification`
- `comparison`
- `ranking`
- `explanation`
- `refusal`
- `uncertainty`
- `correction`
- `claim_confidence_movement`

The format profile assigns each dimension a non-negative weight. A format may
set a dimension weight to `0` when the dimension is not applicable, but the
dimension still appears in the evaluation with `applicable=false`, a null
score, and an explicit reward signal of `not_applicable`.

Dimensions are not hidden rules. They score whether a run actually produced
the evidence, classification, comparison, ranking, explanation, refusal,
uncertainty, correction, or confidence movement promised by the registered
format. They may block, refuse, downgrade, or request correction.
They may not declare an authoritative domain verdict.

## Claim Evidence And Confidence Requirements

Every scored claim must carry:

- `claim_id`
- `claim_text`
- `claim_kind`
- `dimension_refs`
- `evidence_refs`
- `confidence`
- `posterior_state`
- `claim_confidence_movement`
- `support_state`
- `scope_limit`
- `public_eligible`
- `correction_ref`
- `infraction_refs`

Evidence refs are mandatory even when the claim is a refusal. A refusal's
evidence may be the missing gate, blocked rights state, stale source, or
unsupported claim trace that caused the refusal.

Posterior state is mandatory for every scored claim. A qualitative-only
format still records a qualitative posterior family, prior, likelihood signal,
posterior, delta, timestamp, and evidence refs.
Confidence without evidence is recorded as `confidence_without_evidence`.

`claim_confidence_movement` is a movement record, not a truth guarantee. It
captures whether the run raised, lowered, or left flat confidence in the
bounded claim under the declared evidence window.

## Grounding Infractions

The evaluator records forbidden failures as machine-readable infractions.

Required infraction vocabulary:

- `unsupported_claim`
- `overbroad_claim`
- `hidden_expertise`
- `unlabelled_uncertainty`
- `stale_source_claim`
- `missing_evidence_ref`
- `missing_posterior_state`
- `confidence_without_evidence`
- `trend_as_truth`
- `expert_verdict_without_evidence`
- `engagement_metric_substituted_for_grounding`
- `missing_reward_vector_input`

Unsupported and overbroad claims are not soft notes. They must appear in both
the top-level `infractions` list and in each affected `scored_claim.infraction_refs`.

Unsupported means the claim lacks evidence, the cited evidence does not support
the claim, or the run cannot trace the claim back to the declared evidence
window.

Overbroad means the claim exceeds the candidate set, time window, source scope,
rights posture, uncertainty language, or authority ceiling declared by the
format, gate, or opportunity decision.

## Reward Vector Inputs

The evaluator emits inputs for the Bayesian feedback ledger. It does not
directly rewrite posterior state.

Grounding reward inputs:

- `evidence_yield`
- `classification_quality`
- `comparison_quality`
- `ranking_stability`
- `explanation_quality`
- `uncertainty_quality`
- `refusal_quality`
- `correction_value`
- `posterior_update`
- `inconsistency_discovery`

Artifact reward inputs:

- `chapter_value`
- `caption_value`
- `replay_value`
- `artifact_value`

Revenue reward inputs:

- `structural_revenue_signal`
- `monetization_gate_signal`

Posterior update targets are limited to the posterior families already named
by the opportunity model: `format_prior`, `source_prior`,
`grounding_yield_probability`, `artifact_conversion_probability`,
`audience_response`, and `revenue_support_response`.

Each reward input carries a value, confidence, evidence refs, and posterior
refs. Missing evidence is a grounding infraction, not a zero-value success.

## Engagement Separation Policy

Engagement metrics are useful observations. They are not evidence that a claim
was scientifically grounded.

The evaluator keeps these separate:

- grounding quality: dimension scores, scored claims, infractions, grounding
  gate state, corrections, and refusals,
- engagement observations: views, watch time, retention, click-through rate,
  aggregate comment signal, support intent, and replay request.

`engagement_can_override_grounding` is always false.
`engagement_metrics_stored_separately` is always true.

If an implementation uses engagement as a substitute for grounding quality, it
must emit `engagement_metric_substituted_for_grounding` and block public claim
promotion until a corrected evaluation exists.

## Feedback Ledger Interface

The later feedback ledger consumes evaluator events with:

- `event_kind = format_grounding_evaluation`
- `ledger_payload_ref`
- `update_allowed`
- `only_if_evidence_bound = true`

When `update_allowed=false`, the ledger may still archive the evaluation but
must not update Bayesian posteriors. Typical blockers are unsupported claims,
missing posterior state, missing evidence refs, hidden expertise, or metric
substitution.

## Example Evaluation

```json
{
  "schema_version": 1,
  "evaluation_id": "fge_20260429t023000z_tierlist_models_a",
  "evaluated_at": "2026-04-29T02:30:00Z",
  "producer": "format_grounding_evaluator",
  "run_ref": {
    "programme_id": "programme_20260429_model_grounding",
    "run_id": "run_20260429t022500z_tierlist_models_a",
    "format_id": "tier_list",
    "opportunity_id": "opp_20260429t021000z_model_routes_tierlist",
    "input_source_id": "local_model_grounding_scout",
    "subject_cluster": "model_routing_grounding",
    "public_private_mode": "dry_run"
  },
  "format_evaluator_profile": {
    "format_id": "tier_list",
    "format_contract_ref": "schemas/content-programme-format.schema.json#tier_list",
    "grounding_attempt_types": ["classification", "ranking", "comparison", "uncertainty", "claim_confidence_update"],
    "dimension_weights": {
      "perception": 0.1,
      "classification": 0.2,
      "comparison": 0.2,
      "ranking": 0.2,
      "explanation": 0.05,
      "refusal": 0.05,
      "uncertainty": 0.1,
      "correction": 0.0,
      "claim_confidence_movement": 0.1
    },
    "minimum_passing_score": 0.7
  },
  "gate_refs": {
    "grounding_gate_ref": "grounding_gate_20260429t013000z_tierlist_a",
    "opportunity_decision_ref": "cod_20260429t021000z_tierlist_models_a",
    "format_registry_ref": "schemas/content-programme-format.schema.json"
  },
  "grounding_question": "Which model-route candidates can Hapax justify from current evidence?",
  "dimension_scores": {
    "perception": {
      "dimension_name": "perception",
      "applicable": true,
      "weight": 0.1,
      "score": 0.74,
      "evidence_refs": ["local:research_brief:model_routes"],
      "confidence": {"kind": "posterior", "value": 0.67, "uncertainty": 0.16, "calibration": "dry-run sample"},
      "posterior_state": {"family": "beta", "prior": 0.55, "likelihood_signal": 0.74, "posterior": 0.67, "delta": 0.12, "updated_at": "2026-04-29T02:30:00Z", "evidence_refs": ["local:research_brief:model_routes"]},
      "failure_modes": [],
      "reward_signal": "evidence_yield"
    },
    "classification": {
      "dimension_name": "classification",
      "applicable": true,
      "weight": 0.2,
      "score": 0.72,
      "evidence_refs": ["claim:route_classification_table"],
      "confidence": {"kind": "posterior", "value": 0.66, "uncertainty": 0.14, "calibration": "criterion matched"},
      "posterior_state": {"family": "beta", "prior": 0.54, "likelihood_signal": 0.72, "posterior": 0.66, "delta": 0.12, "updated_at": "2026-04-29T02:30:00Z", "evidence_refs": ["claim:route_classification_table"]},
      "failure_modes": [],
      "reward_signal": "classification_quality"
    },
    "comparison": {
      "dimension_name": "comparison",
      "applicable": true,
      "weight": 0.2,
      "score": 0.69,
      "evidence_refs": ["trace:model_route_pairwise_compare"],
      "confidence": {"kind": "posterior", "value": 0.61, "uncertainty": 0.18, "calibration": "pairwise dry-run"},
      "posterior_state": {"family": "beta", "prior": 0.5, "likelihood_signal": 0.69, "posterior": 0.61, "delta": 0.11, "updated_at": "2026-04-29T02:30:00Z", "evidence_refs": ["trace:model_route_pairwise_compare"]},
      "failure_modes": [],
      "reward_signal": "comparison_quality"
    },
    "ranking": {
      "dimension_name": "ranking",
      "applicable": true,
      "weight": 0.2,
      "score": 0.71,
      "evidence_refs": ["rank:model_routes"],
      "confidence": {"kind": "posterior", "value": 0.63, "uncertainty": 0.17, "calibration": "ranking trace exists"},
      "posterior_state": {"family": "beta", "prior": 0.5, "likelihood_signal": 0.71, "posterior": 0.63, "delta": 0.13, "updated_at": "2026-04-29T02:30:00Z", "evidence_refs": ["rank:model_routes"]},
      "failure_modes": [],
      "reward_signal": "ranking_stability"
    },
    "explanation": {
      "dimension_name": "explanation",
      "applicable": true,
      "weight": 0.05,
      "score": 0.65,
      "evidence_refs": ["narrative:bounded_explanation"],
      "confidence": {"kind": "posterior", "value": 0.58, "uncertainty": 0.2, "calibration": "dry-run explanation"},
      "posterior_state": {"family": "beta", "prior": 0.5, "likelihood_signal": 0.65, "posterior": 0.58, "delta": 0.08, "updated_at": "2026-04-29T02:30:00Z", "evidence_refs": ["narrative:bounded_explanation"]},
      "failure_modes": [],
      "reward_signal": "explanation_quality"
    },
    "refusal": {
      "dimension_name": "refusal",
      "applicable": true,
      "weight": 0.05,
      "score": 1.0,
      "evidence_refs": ["gate:public_live_egress_blocked"],
      "confidence": {"kind": "refused", "value": 1.0, "uncertainty": 0.0, "calibration": "egress gate fail"},
      "posterior_state": {"family": "qualitative", "prior": 1.0, "likelihood_signal": 1.0, "posterior": 1.0, "delta": 0.0, "updated_at": "2026-04-29T02:30:00Z", "evidence_refs": ["gate:public_live_egress_blocked"]},
      "failure_modes": [],
      "reward_signal": "refusal_quality"
    },
    "uncertainty": {
      "dimension_name": "uncertainty",
      "applicable": true,
      "weight": 0.1,
      "score": 0.79,
      "evidence_refs": ["caption:uncertainty_markers"],
      "confidence": {"kind": "posterior", "value": 0.7, "uncertainty": 0.12, "calibration": "uncertainty named"},
      "posterior_state": {"family": "beta", "prior": 0.55, "likelihood_signal": 0.79, "posterior": 0.7, "delta": 0.15, "updated_at": "2026-04-29T02:30:00Z", "evidence_refs": ["caption:uncertainty_markers"]},
      "failure_modes": [],
      "reward_signal": "uncertainty_quality"
    },
    "correction": {
      "dimension_name": "correction",
      "applicable": false,
      "weight": 0.0,
      "score": null,
      "evidence_refs": [],
      "confidence": {"kind": "qualitative", "value": 0.0, "uncertainty": 0.0, "calibration": "not applicable"},
      "posterior_state": {"family": "qualitative", "prior": 0.0, "likelihood_signal": 0.0, "posterior": 0.0, "delta": 0.0, "updated_at": "2026-04-29T02:30:00Z", "evidence_refs": ["profile:dimension_not_applicable"]},
      "failure_modes": [],
      "reward_signal": "not_applicable"
    },
    "claim_confidence_movement": {
      "dimension_name": "claim_confidence_movement",
      "applicable": true,
      "weight": 0.1,
      "score": 0.68,
      "evidence_refs": ["claim:route_a_confidence_delta"],
      "confidence": {"kind": "posterior", "value": 0.62, "uncertainty": 0.16, "calibration": "claim posterior moved"},
      "posterior_state": {"family": "beta", "prior": 0.52, "likelihood_signal": 0.68, "posterior": 0.62, "delta": 0.1, "updated_at": "2026-04-29T02:30:00Z", "evidence_refs": ["claim:route_a_confidence_delta"]},
      "failure_modes": [],
      "reward_signal": "posterior_update"
    }
  },
  "scored_claims": [
    {
      "claim_id": "claim_route_a_rank_1",
      "claim_text": "Route A is the best-supported candidate in the declared evidence window.",
      "claim_kind": "ranking",
      "dimension_refs": ["ranking", "comparison", "claim_confidence_movement"],
      "evidence_refs": ["rank:model_routes", "trace:model_route_pairwise_compare"],
      "confidence": {"kind": "posterior", "value": 0.62, "uncertainty": 0.16, "calibration": "dry-run posterior"},
      "posterior_state": {"family": "beta", "prior": 0.52, "likelihood_signal": 0.68, "posterior": 0.62, "delta": 0.1, "updated_at": "2026-04-29T02:30:00Z", "evidence_refs": ["rank:model_routes", "trace:model_route_pairwise_compare"]},
      "claim_confidence_movement": {"prior": 0.52, "posterior": 0.62, "delta": 0.1, "direction": "up"},
      "support_state": "supported",
      "scope_limit": "Only ranks the declared model-route candidate set and evidence window.",
      "public_eligible": false,
      "correction_ref": null,
      "infraction_refs": []
    }
  ],
  "infractions": [],
  "evaluator_result": {
    "grounding_quality_score": 0.72,
    "pass_state": "warn",
    "public_claim_allowed": false,
    "correction_required": false,
    "refusal_required": true,
    "unsupported_claim_count": 0,
    "overbroad_claim_count": 0
  },
  "no_expert_system_policy": {
    "rules_may_score_attempt_quality": true,
    "authoritative_verdict_allowed": false,
    "domain_truth_adjudication_allowed": false,
    "score_requires_evidence_bound_claim": true,
    "score_may_block_or_refuse": true
  },
  "reward_vector_inputs": {
    "grounding_reward_inputs": {
      "evidence_yield": {"value": 0.74, "confidence": 0.67, "evidence_refs": ["local:research_brief:model_routes"], "posterior_refs": ["grounding_yield_probability"]},
      "classification_quality": {"value": 0.72, "confidence": 0.66, "evidence_refs": ["claim:route_classification_table"], "posterior_refs": ["format_prior"]},
      "comparison_quality": {"value": 0.69, "confidence": 0.61, "evidence_refs": ["trace:model_route_pairwise_compare"], "posterior_refs": ["format_prior"]},
      "ranking_stability": {"value": 0.71, "confidence": 0.63, "evidence_refs": ["rank:model_routes"], "posterior_refs": ["format_prior"]},
      "explanation_quality": {"value": 0.65, "confidence": 0.58, "evidence_refs": ["narrative:bounded_explanation"], "posterior_refs": ["format_prior"]},
      "uncertainty_quality": {"value": 0.79, "confidence": 0.7, "evidence_refs": ["caption:uncertainty_markers"], "posterior_refs": ["grounding_yield_probability"]},
      "refusal_quality": {"value": 1.0, "confidence": 1.0, "evidence_refs": ["gate:public_live_egress_blocked"], "posterior_refs": ["grounding_yield_probability"]},
      "correction_value": {"value": 0.0, "confidence": 0.0, "evidence_refs": ["profile:dimension_not_applicable"], "posterior_refs": []},
      "posterior_update": {"value": 0.1, "confidence": 0.62, "evidence_refs": ["claim:route_a_confidence_delta"], "posterior_refs": ["grounding_yield_probability"]},
      "inconsistency_discovery": {"value": 0.0, "confidence": 0.0, "evidence_refs": ["trace:no_inconsistency_found"], "posterior_refs": []}
    },
    "artifact_reward_inputs": {
      "chapter_value": {"value": 0.4, "confidence": 0.5, "evidence_refs": ["boundary:rank_assigned"], "posterior_refs": ["artifact_conversion_probability"]},
      "caption_value": {"value": 0.5, "confidence": 0.5, "evidence_refs": ["caption:uncertainty_markers"], "posterior_refs": ["artifact_conversion_probability"]},
      "replay_value": {"value": 0.45, "confidence": 0.5, "evidence_refs": ["replay:dry_run_card"], "posterior_refs": ["artifact_conversion_probability"]},
      "artifact_value": {"value": 0.45, "confidence": 0.5, "evidence_refs": ["artifact:rank_table"], "posterior_refs": ["artifact_conversion_probability"]}
    },
    "revenue_reward_inputs": {
      "structural_revenue_signal": {"value": 0.0, "confidence": 1.0, "evidence_refs": ["gate:monetization_blocked"], "posterior_refs": ["revenue_support_response"]},
      "monetization_gate_signal": {"value": -1.0, "confidence": 1.0, "evidence_refs": ["gate:monetization_blocked"], "posterior_refs": ["revenue_support_response"]}
    },
    "engagement_observations": {
      "kept_separate": true,
      "may_override_grounding": false,
      "metrics": [],
      "evidence_refs": []
    },
    "posterior_update_targets": ["format_prior", "grounding_yield_probability", "artifact_conversion_probability", "revenue_support_response"]
  },
  "feedback_ledger_interface": {
    "event_kind": "format_grounding_evaluation",
    "ledger_payload_ref": null,
    "update_allowed": true,
    "only_if_evidence_bound": true
  },
  "separation_policy": {
    "engagement_can_override_grounding": false,
    "engagement_metrics_stored_separately": true,
    "grounding_score_sources": ["dimension_scores", "scored_claims", "infractions", "grounding_gate", "refusals"],
    "engagement_score_sources": [],
    "substitution_infraction": "engagement_metric_substituted_for_grounding"
  },
  "audit": {
    "evidence_refs": ["local:research_brief:model_routes", "grounding_gate_20260429t013000z_tierlist_a"],
    "decision_trace_refs": ["cod_20260429t021000z_tierlist_models_a"],
    "generated_artifact_refs": ["artifact:rank_table", "replay:dry_run_card"]
  }
}
```

## Acceptance Pin

This spec is complete only if:

- every evaluation carries a per-format profile and all required dimensions,
- every scored claim carries evidence refs, confidence, posterior state, and
  claim-confidence movement,
- unsupported and overbroad claims are machine-readable infractions,
- missing evidence and missing posterior state are machine-readable
  infractions,
- reward-vector inputs map to the Bayesian feedback ledger without directly
  mutating posterior state,
- engagement metrics are stored separately and cannot override grounding
  quality,
- the evaluator can refuse, correct, or block a run without acting as an expert-system verdict engine.
