# Content Programme Feedback Ledger - Design Spec

**Status:** schema/config/helper seed for `content-programme-feedback-ledger`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/content-programme-feedback-ledger.md`
**Date:** 2026-04-29
**Depends on:** Bayesian content opportunity model, content programme run store event surface, and format grounding evaluator.
**Scope:** append-only feedback events, run-state learning records, evaluator and witnessed-outcome consumption, aggregate-only audience/revenue observations, posterior update proposals, exploration regret, novelty distance, and safety/refusal metrics.
**Non-scope:** scheduler policy, runner execution, public adapter writes, raw audience ingestion, monetization decisions, or posterior-store mutation.

## Purpose

The feedback ledger is the learning handoff for autonomous content programming.
It consumes completed or blocked run-store state, witnessed capability outcomes,
and format-grounding evaluator outputs, then records the posterior update
proposals that the Bayesian opportunity model may consume.

The ledger must learn from the whole lifecycle, including selected, blocked,
dry-run, public-run, completed, aborted, refused, corrected, and private-only
runs. A blocked or refused run is still a learning event. It is not a public
truth event.

The machine-readable contract lives at:

- `schemas/content-programme-feedback-ledger.schema.json`
- `config/content-programme-feedback-ledger.json`

Typed helper models live at:

- `shared/content_programme_feedback_ledger.py`

## Feedback Event Contract

`ContentProgrammeFeedbackEvent` is append-only. It records one learning event
for a programme run without rewriting the run store or evaluator outputs.

Required fields:

| Field | Meaning |
|---|---|
| `ledger_event_id` | Stable feedback event id. |
| `run_id` | Content programme run id. |
| `programme_id` | Programme arc id. |
| `opportunity_decision_id` | Bayesian decision selected or held by the run. |
| `format_id` | Content programme format id. |
| `input_source_id` | Source-pool or input-source registry id. |
| `subject_cluster` | Subject cluster arm used by the sampler. |
| `occurred_at` | UTC event timestamp. |
| `event_kind` | Run selected, blocked, dry-run, public-run, completed, aborted, refused, corrected, private-only, or posterior proposal event. |
| `programme_state` | Lifecycle state being learned from. |
| `public_private_mode` | Effective run mode from the run store. |
| `run_store_ref` | Canonical `ContentProgrammeRunEnvelope` or run-store event ref. |
| `selected_state_refs` | Selected decision or selected command refs. |
| `commanded_state_refs` | Commanded, accepted, queued, or executed command refs. |
| `gate_outcomes` | Truth, rights, consent, monetization, egress, WCS, public-event, and safety gate outcomes. |
| `grounding_outputs` | Format-grounding evaluator refs and update eligibility. |
| `artifact_outputs` | Replay, chapter, short, dataset, zine, refusal, correction, or support artifact outputs. |
| `audience_outcome` | Aggregate-only audience observations. |
| `revenue_proxies` | Aggregate-only revenue/support observations and readiness proxies. |
| `safety_metrics` | Refusal, correction, privacy, rights, egress, witness, and unsupported-claim counts. |
| `witnessed_capability_outcomes` | Witnessed `CapabilityOutcomeEnvelope` refs, separate from selected/commanded states. |
| `nested_programme_outcome_refs` | Run-envelope nested outcome refs consumed for observation, claim/gate, artifact, public-event, conversion, refusal, and correction stage learning. |
| `posterior_updates` | Evidence-bound posterior update proposals. |
| `exploration` | Exploration regret, novelty distance, and budget refs. |
| `separation_policy` | Machine-readable anti-substitution rules. |
| `learning_policy` | Blocked/refused/corrected/private-only learning rules. |
| `append_only` | Always true. |
| `idempotency_key` | Duplicate-suppression key for the feedback event. |

## Lifecycle Coverage

The ledger recognizes exactly these programme outcome states:

- `selected`
- `blocked`
- `dry_run`
- `public_run`
- `completed`
- `aborted`
- `refused`
- `corrected`
- `private_only`
- `conversion_held`

The seeded ledger includes representative records for selected, blocked,
dry-run, public-run, completed, aborted, refused, corrected, and private-only
runs. `conversion_held` is accepted by the schema because conversion brokers
must learn from public-event or rights gaps without treating the held artifact
as a public success.

## Gate And Grounding Inputs

Gate outcomes are evidence-bearing facts, not scalar opinions. Each gate
outcome records:

- `gate_name`
- `state`
- `gate_ref`
- `evidence_refs`
- `unavailable_reasons`
- `blocks_public_claim`
- `posterior_update_allowed`

Format-grounding evaluator outputs are consumed through
`grounding_outputs[]`. The ledger records evaluator refs, grounding score,
infractions, evidence refs, and whether the evaluator allowed an update. It
does not re-score the run and does not grant expert-system verdict authority.

Missing evidence, unsupported claims, hidden expertise, or engagement metric
substitution force `posterior_update_allowed=false` for grounding-quality
updates. The event may still be archived and may still update refusal/safety
rates.

## Witnessed Outcomes Versus Commands

Selected, commanded, accepted, queued, and executed states are execution facts.
They are not witnessed outcomes.

The ledger consumes witnessed `CapabilityOutcomeEnvelope` refs only through
`witnessed_capability_outcomes[]`. A witnessed outcome may update posteriors
only when it has:

- `witness_state = witness_verified`,
- evidence envelope refs,
- a capability outcome envelope ref,
- `posterior_update_allowed=true`.

Selected and commanded state refs are preserved for audit and regret analysis,
but `selected_commanded_states_update_posteriors=false` is pinned in every
event.

## Posterior Update Families

The feedback ledger keeps posterior update families separate:

- `grounding_quality`
- `audience_response`
- `artifact_conversion`
- `revenue_support_response`
- `rights_pass_probability`
- `safety_refusal_rate`
- `format_prior`
- `source_prior`

Each posterior update proposal records:

- `posterior_family`
- `target_ref`
- `source_signal`
- `value`
- `confidence`
- `prior_ref`
- `evidence_refs`
- `update_allowed`
- `blocked_reason`

The ledger proposes updates. It does not mutate Bayesian posterior storage.
The Bayesian opportunity model remains the consumer that decides how to apply
posterior movement.

## Aggregate Audience And Revenue Policy

Audience data is aggregate-only. The ledger may store views, watch time,
retention, click-through, aggregate comment signal, rewatch, follow-through,
or support-intent metrics. It must not store handles, payer identities, raw
comment text, personalized supporter state, or per-person history.

Revenue and support observations are also aggregate-only. The ledger records
proxy signals such as platform revenue readiness, support count bucket, grant
lead signal, license interest, artifact conversion intent, or product interest.
These proxies may update `revenue_support_response`; they may not update
grounding quality.

Pinned rules:

- `audience_data_aggregate_only = true`
- `per_person_audience_state_allowed = false`
- `public_payer_identity_allowed = false`
- `raw_comment_text_allowed = false`
- `engagement_can_override_grounding = false`
- `revenue_can_override_grounding = false`

## Exploration And Novelty

Every feedback event records exploration learning:

- `exploration_budget_ref`
- `exploration_regret`
- `novelty_distance`
- `cooldown_effect_ref`
- `evidence_refs`

Exploration regret and novelty distance help tune format/source/subject
selection. They do not override eligibility gates and do not convert unsafe or
unsupported public claims into truth.

## Safety And Refusal Learning

Blocked, refused, corrected, private-only, and aborted runs are learning
events. They preserve:

- gate blockers,
- refusal/correction refs,
- unsupported or overbroad claim counts,
- rights/privacy/egress/monetization blockers,
- witness missing or stale counts,
- safety/refusal posterior proposals.

These events may update `safety_refusal_rate`, `rights_pass_probability`,
`source_prior`, or `format_prior` when evidence exists. They must keep
`public_truth_claim_allowed=false`.

## Downstream Contract

Downstream consumers:

- `content_opportunity_model`
- `programme_scheduler_policy`
- `content_programme_run_store`
- `format_grounding_evaluator`
- `conversion_broker`
- `metrics_dashboard`

Consumers must preserve event ids, run refs, evaluator refs, witnessed outcome
refs, nested programme outcome refs, aggregate-only audience/revenue policy,
posterior update family, evidence refs, blocked reasons, exploration signals,
and separation policy. They must
not infer truth from engagement, revenue, selected state, command acceptance,
or public-looking artifacts.

## Example Feedback Event

```json
{
  "schema_version": 1,
  "ledger_event_id": "feedback:completed:evidence_audit:20260429",
  "run_id": "run_public_archive_evidence_audit_20260429",
  "programme_id": "programme_content_grounding_20260429",
  "opportunity_decision_id": "cod_20260429_evidence_audit_a",
  "format_id": "evidence_audit",
  "input_source_id": "operator_owned_archive_segments",
  "subject_cluster": "evidence_audit",
  "occurred_at": "2026-04-29T12:45:00Z",
  "event_kind": "run_completed",
  "programme_state": "completed",
  "public_private_mode": "public_archive",
  "run_store_ref": "run-store:run_public_archive_evidence_audit_20260429",
  "selected_state_refs": ["command:selected:evidence_audit"],
  "commanded_state_refs": ["command:accepted:evidence_audit"],
  "gate_outcomes": [
    {
      "gate_name": "truth_gate",
      "state": "pass",
      "gate_ref": "grounding_gate:evidence_audit",
      "evidence_refs": ["ee:evidence_audit"],
      "unavailable_reasons": [],
      "blocks_public_claim": false,
      "posterior_update_allowed": true
    },
    {
      "gate_name": "rights_gate",
      "state": "pass",
      "gate_ref": "rights:operator_owned_archive_segments",
      "evidence_refs": ["rights:owned"],
      "unavailable_reasons": [],
      "blocks_public_claim": false,
      "posterior_update_allowed": true
    }
  ],
  "grounding_outputs": [
    {
      "evaluation_id": "fge:evidence_audit",
      "event_kind": "format_grounding_evaluation",
      "grounding_quality_score": 0.82,
      "update_allowed": true,
      "infraction_refs": [],
      "evidence_refs": ["ee:evidence_audit"],
      "posterior_refs": ["grounding_yield_probability"]
    }
  ],
  "artifact_outputs": [
    {
      "artifact_id": "artifact:evidence_audit_card",
      "artifact_type": "archive_card",
      "state": "emitted",
      "public_event_ref": "rvpe:evidence_audit",
      "evidence_refs": ["artifact:evidence_audit_card"]
    }
  ],
  "audience_outcome": {
    "aggregate_only": true,
    "per_person_identity_allowed": false,
    "raw_comment_text_allowed": false,
    "public_payer_identity_allowed": false,
    "metrics": [
      {
        "metric_name": "watch_time",
        "value": 0.58,
        "sample_size": 12,
        "identity_scope": "aggregate",
        "aggregate_ref": "audience:aggregate:evidence_audit",
        "evidence_refs": ["youtube:analytics:aggregate:evidence_audit"]
      }
    ],
    "evidence_refs": ["youtube:analytics:aggregate:evidence_audit"]
  },
  "revenue_proxies": [
    {
      "proxy_name": "support_intent",
      "value": 0.2,
      "aggregate_only": true,
      "public_payer_identity_allowed": false,
      "evidence_refs": ["support:aggregate:evidence_audit"]
    }
  ],
  "safety_metrics": [
    {
      "metric_name": "unsupported_claim_count",
      "count": 0,
      "evidence_refs": ["fge:evidence_audit"]
    }
  ],
  "witnessed_capability_outcomes": [
    {
      "capability_outcome_ref": "coe:evidence_audit",
      "capability_outcome_envelope_ref": "CapabilityOutcomeEnvelope:coe:evidence_audit",
      "witness_state": "witness_verified",
      "evidence_envelope_refs": ["ee:evidence_audit"],
      "posterior_update_allowed": true
    }
  ],
  "nested_programme_outcome_refs": [
    "nested:run_public_archive_evidence_audit_20260429:observation",
    "nested:run_public_archive_evidence_audit_20260429:claim-gate",
    "nested:run_public_archive_evidence_audit_20260429:artifact",
    "nested:run_public_archive_evidence_audit_20260429:public-event",
    "nested:run_public_archive_evidence_audit_20260429:conversion",
    "nested:run_public_archive_evidence_audit_20260429:refusal",
    "nested:run_public_archive_evidence_audit_20260429:correction"
  ],
  "posterior_updates": [
    {
      "update_id": "posterior:grounding:evidence_audit",
      "posterior_family": "grounding_quality",
      "target_ref": "content-opportunity-model.posterior_state.grounding_yield_probability",
      "source_signal": "format_grounding_evaluation",
      "value": 0.82,
      "confidence": 0.74,
      "prior_ref": "posterior:grounding:evidence_audit:prior",
      "evidence_refs": ["fge:evidence_audit", "ee:evidence_audit"],
      "update_allowed": true,
      "blocked_reason": null
    },
    {
      "update_id": "posterior:audience:evidence_audit",
      "posterior_family": "audience_response",
      "target_ref": "content-opportunity-model.posterior_state.audience_response",
      "source_signal": "audience_aggregate",
      "value": 0.58,
      "confidence": 0.5,
      "prior_ref": "posterior:audience:evidence_audit:prior",
      "evidence_refs": ["youtube:analytics:aggregate:evidence_audit"],
      "update_allowed": true,
      "blocked_reason": null
    }
  ],
  "exploration": {
    "exploration_budget_ref": "exploration:daily:20260429",
    "exploration_regret": 0.08,
    "novelty_distance": 0.42,
    "cooldown_effect_ref": "cooldown:format:evidence_audit",
    "evidence_refs": ["sampler:cod_20260429_evidence_audit_a"]
  },
  "separation_policy": {
    "selected_commanded_states_update_posteriors": false,
    "witnessed_capability_outcomes_update_grounding": true,
    "format_grounding_evaluations_update_grounding": true,
    "engagement_can_override_grounding": false,
    "revenue_can_override_grounding": false,
    "audience_data_aggregate_only": true,
    "per_person_audience_state_allowed": false,
    "public_payer_identity_allowed": false,
    "blocked_claims_become_public_truth": false
  },
  "learning_policy": {
    "blocked_refused_corrected_private_only_are_learning_events": true,
    "public_truth_claim_allowed": true,
    "posterior_store_mutation_allowed": false
  },
  "append_only": true,
  "idempotency_key": "run_public_archive_evidence_audit_20260429:completed"
}
```

## Acceptance Pin

This packet is complete only if:

- selected, blocked, dry-run, public-run, completed, and aborted states are
  first-class feedback states,
- blocked, refused, corrected, and private-only runs are learning events but
  never public truth events,
- gate outcomes, grounding outputs, artifact outputs, audience outcomes,
  revenue proxies, posterior updates, exploration regret, novelty distance,
  and safety metrics are machine-readable,
- audience and support/revenue data are aggregate-only,
- selected/commanded states are separate from witnessed
  `CapabilityOutcomeEnvelope` refs,
- format-grounding evaluator outputs are consumed separately from witnessed
  capability outcomes,
- posterior updates remain separated across grounding quality, audience
  response, artifact conversion, revenue/support response, rights pass, and
  safety/refusal rates,
- engagement and revenue observations cannot override grounding quality,
- the ledger proposes posterior updates without mutating Bayesian posterior
  storage.
