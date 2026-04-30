# Content Programme Run Store Event Surface - Design Spec

**Status:** schema seed for `content-programme-run-store-event-surface`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/content-programme-run-store-event-surface.md`
**Date:** 2026-04-29
**Depends on:** content programme format registry, Bayesian content opportunity model, input source registry, programme boundary event surface, format grounding evaluator, and WCS planning packets.
**Scope:** canonical `ContentProgrammeRunEnvelope`, append-only `ContentProgrammeRunStoreEvent`, fixture catalog, WCS refs, boundary refs, execution/witness separation, and adapter-facing state.
**Non-scope:** scheduler implementation, runner implementation, public-event adapter writes, YouTube writes, feedback-ledger persistence, or conversion broker implementation.

## Purpose

The content programme run store is the durable audit spine for autonomous
content programming attempts.

A run starts from a selected `ContentOpportunity` decision and a
`ContentProgrammeFormat` row. It then records the world surfaces, evidence,
director plan, gates, boundary refs, claims, refusals, corrections, scores,
conversion candidates, and final status that downstream systems need. The run
store must not re-score hidden copies of the opportunity or infer public
eligibility from public-looking content.

The machine-readable schema lives at:

- `schemas/content-programme-run-store-event-surface.schema.json`

Typed helper models live at:

- `shared/content_programme_run_store.py`

## Run Envelope

`ContentProgrammeRunEnvelope` is a projection over append-only events. It is
not the audit trail itself.

Required fields:

| Field | Meaning |
|---|---|
| `schema_version` | Envelope schema version. Initial value is `1`. |
| `run_id` | Stable run id. |
| `programme_id` | Programme arc id. |
| `opportunity_decision_id` | Persisted Bayesian decision id that selected the opportunity. |
| `format_id` | Selected content programme format id. |
| `condition_id` | Active condition id when the run was selected. |
| `selected_at` | UTC selection timestamp. |
| `selected_by` | Component that selected the run, usually `content_opportunity_model`. |
| `grounding_question` | Exact bounded question the run attempts to ground. |
| `requested_public_private_mode` | Requested private, dry-run, public-live, public-archive, or public-monetizable mode. |
| `public_private_mode` | Effective mode after rights, privacy, public-event, WCS, and monetization gates. |
| `rights_privacy_public_mode` | Effective posture and unavailable reasons. |
| `selected_opportunity` | Refs to the selected `ContentOpportunity` decision, tuple, reward vector, and posterior samples. |
| `selected_format` | Refs to the format registry row and grounding attempt vocabulary. |
| `broadcast_refs` | Broadcast/live refs, when available. |
| `archive_refs` | Archive, replay, or sidecar refs. |
| `selected_input_refs` | Source/input refs selected for this run. |
| `substrate_refs` | Content substrate refs from the opportunity and WCS. |
| `semantic_capability_refs` | Capability refs recruited or required by the run. |
| `director_plan` | Director snapshot, plan, move, and condition refs. |
| `gate_refs` | Grounding, rights, privacy, monetization, and public-event gate refs. |
| `wcs` | WCS binding block. |
| `events` | Projection refs to run-store events. |
| `boundary_event_refs` | Refs to `ProgrammeBoundaryEvent` records. |
| `claims` | Evidence-envelope backed claim refs. |
| `uncertainties` | Explicit uncertainty refs. |
| `refusals` | Refusal refs. |
| `corrections` | Correction refs. |
| `scores` | Format grounding evaluator refs. |
| `conversion_candidates` | Archive, chapter, cuepoint, Shorts, artifact, support, grant, or monetization candidates. |
| `nested_outcomes` | Stage-level outcome refs for observation, claim/gate, artifact, public event, conversion, refusal, and correction. |
| `command_execution` | Selected, commanded, executed, and witnessed outcome split. |
| `witnessed_outcomes` | Witnessed outcomes visible at top level for feedback and health consumers. |
| `adapter_exposure` | Stable adapter-facing state refs. |
| `separation_policy` | Grounding, engagement, revenue, support, and witness separation constants. |
| `operator_labor_policy` | Single-operator and no-request-queue guarantees. |
| `final_status` | Selected, running, blocked, refused, corrected, conversion-held, completed, or aborted. |

## Append-Only Run Store Event

`ContentProgrammeRunStoreEvent` is the audit trail. Events are append-only and
immutable; corrections, refusals, retries, and state changes add a new event.
They do not rewrite earlier records.

Required event fields:

- `schema_version`
- `event_id`
- `run_id`
- `sequence`
- `event_type`
- `occurred_at`
- `idempotency_key`
- `producer`
- `payload_refs`
- `evidence_refs`
- `boundary_event_refs`
- `public_event_refs`
- `capability_outcome_refs`
- `append_only`
- `mutation_policy`

Initial `event_type` values:

- `selected`
- `started`
- `transitioned`
- `blocked`
- `evidence_attached`
- `gate_evaluated`
- `boundary_emitted`
- `claim_recorded`
- `outcome_recorded`
- `refusal_issued`
- `correction_made`
- `artifact_candidate`
- `conversion_held`
- `public_event_linked`
- `completed`
- `aborted`

The envelope may cache refs to these events for adapter efficiency, but the
event stream remains the source of audit history.

## Opportunity And Format Refs

The run store persists the selected opportunity decision and format row:

- `selected_opportunity.decision_id`
- `selected_opportunity.decision_ref`
- `selected_opportunity.content_opportunity_tuple_ref`
- `selected_opportunity.posterior_sample_refs`
- `selected_opportunity.reward_vector_ref`
- `selected_opportunity.rescore_hidden_copy_allowed = false`
- `selected_format.registry_ref`
- `selected_format.row_ref`
- `selected_format.grounding_question`
- `selected_format.grounding_attempt_types`

Downstream scheduler, runner, and adapter code must consume the persisted
decision. They may add evidence, refuse, correct, hold, or convert the run, but
they must not silently re-score a hidden copy of the opportunity.

## WCS Binding

Every run persists WCS refs instead of prompt-implied capability:

- `semantic_substrate_refs`
- `grounding_contract_refs`
- `evidence_envelope_refs`
- `witness_requirements`
- `capability_outcome_refs`
- `health_state`
- `unavailable_reasons`
- `public_private_posture`

Unknown, missing, stale, blocked, unsafe, or candidate WCS state fails closed.
Missing evidence becomes dry-run, refusal, blocked, or conversion-held state.
It never becomes public eligibility.

## Boundary Event Refs

`ProgrammeBoundaryEvent` owns boundary semantics. The run envelope stores only
refs and adapter-critical keys:

- `boundary_id`
- `sequence`
- `boundary_type`
- `duplicate_key`
- `cuepoint_chapter_distinction`
- `public_event_mapping_ref`
- `mapping_state`
- `unavailable_reasons`

The envelope does not duplicate boundary summaries, claim shapes, evidence
payloads, or public-event mapping payloads. It preserves enough to keep
sequence numbers, duplicate suppression, cuepoint/chapter distinction, and
unavailable reasons stable across adapters.

## Execution Versus Witnessed Outcomes

The run store separates:

- selected opportunity,
- commanded action,
- executed or accepted command,
- witnessed outcome.

Selected, commanded, and executed records always have
`posterior_update_allowed = false`. They are useful execution facts but not
world proof.

Only witnessed outcomes with `witness_state = witness_verified`, evidence
envelope refs, and capability outcome refs may update grounding, opportunity,
or capability-success posteriors. Inferred context, command acceptance, legacy
public events, and engagement metrics do not satisfy witnesses.

Programme runs also expose `nested_outcomes[]` so consumers can preserve the
stage that produced each outcome. A run must carry observation, claim/gate,
artifact, public-event, conversion, refusal, and correction outcome slots. A
conversion outcome can be marked successful only when it cites an accepted
public-event ref; refusal and correction outcomes may be successful learning
events but must keep `validates_refused_claim=false`.

## Public Conversion Path

Public adapters must consume the canonical path:

`ContentProgrammeRunEnvelope` -> `ProgrammeBoundaryEvent` ->
`ResearchVehiclePublicEvent` -> surface adapter

Direct publication from the run envelope is not allowed.

Conversion candidates record whether `ResearchVehiclePublicEvent` is required
and whether one is linked. Public conversion is held when the RVPE ref is
missing. Shorts candidates require owned or cleared audio/video refs.
Monetization candidates require monetization readiness evidence.

## Rights Privacy Public Modes

The contract preserves requested and effective posture separately.

Examples:

- A requested `public_live` run may become effective `dry_run` when egress,
  audio, public-event, or witness evidence is missing.
- A requested `public_monetizable` run may become effective `public_archive`
  when monetization readiness is missing.
- A private run remains useful and auditable without implying public
  eligibility.
- A dry-run tier list can preserve criteria, ranking, uncertainty, and boundary
  refs without becoming public content.
- React/commentary and watch-along runs over third-party audio/video block
  public and monetized media unless rights evidence is explicit.

## Evaluator Scores And Engagement Separation

Format grounding evaluator outputs are evidence-bearing outcomes. They are not
expert-system verdicts.

Every score ref names evaluator evidence. `verdict_authority_allowed` is
always `false`, and `engagement_metric_source_allowed` is always `false`.

Engagement and revenue observations remain separate from grounding quality:

- `engagement_can_override_grounding = false`
- `revenue_can_override_grounding = false`
- `engagement_metrics_stored_separately = true`
- `support_data_public_state_aggregate_only = true`
- `public_payer_identity_allowed = false`

Support data that reaches public or adapter state is aggregate-only. The run
store does not expose payer identity, handles, message text, or per-payer
history.

## Fixture Catalog

Initial fixtures are pinned in schema and helper tests:

- `private_run`
- `dry_run`
- `public_archive_run`
- `public_live_blocked_run`
- `monetization_blocked_run`
- `refusal_run`
- `correction_run`
- `conversion_held_run`
- `dry_run_tier_list`
- `public_safe_evidence_audit`
- `rights_blocked_react_commentary`
- `world_surface_blocked_run`

These fixtures cover missing evidence fail-closed behavior, third-party media
blocks, ranking criteria/rank/uncertainty boundaries, RVPE-required public
conversion, Shorts owned/cleared audio/video checks, monetization readiness
checks, public-safe refusal/correction outputs, and WCS health blockers.

## Adapter Exposure

The run envelope exposes state to:

- public-event adapters,
- scheduler policy,
- feedback ledger,
- archive/replay systems,
- YouTube packaging/adapters,
- metrics dashboards.

Adapters receive refs and blocked reasons. They do not infer truth from format
ids, public-looking text, or engagement.

## Operator Doctrine

The contract is single-operator only.

`operator_labor_policy` pins:

- `single_operator_only = true`
- `request_queue_allowed = false`
- `manual_content_calendar_allowed = false`
- `supporter_controlled_programming_allowed = false`
- `personalized_supporter_treatment_allowed = false`

Autonomous programming may discover and select opportunities. It must not turn
supporters into controllers, create per-person queues, or require a recurring
manual calendar.

## Example Envelope

```json
{
  "schema_version": 1,
  "run_id": "run_public_archive_evidence_audit_20260429",
  "programme_id": "programme_content_grounding_20260429",
  "opportunity_decision_id": "cod_20260429_evidence_audit_a",
  "format_id": "evidence_audit",
  "condition_id": "condition_content_programming_20260429",
  "selected_at": "2026-04-29T04:40:00Z",
  "selected_by": "content_opportunity_model",
  "grounding_question": "Which claim can this evidence audit support inside the declared source window?",
  "requested_public_private_mode": "public_archive",
  "public_private_mode": "public_archive",
  "rights_privacy_public_mode": {
    "requested_mode": "public_archive",
    "effective_mode": "public_archive",
    "rights_state": "cleared",
    "privacy_state": "public_safe",
    "public_event_policy_state": "linked",
    "monetization_state": "not_requested",
    "unavailable_reasons": []
  },
  "selected_opportunity": {
    "decision_id": "cod_20260429_evidence_audit_a",
    "decision_ref": "content-opportunity-model:cod_20260429_evidence_audit_a",
    "opportunity_id": "opp_20260429_evidence_audit_a",
    "content_opportunity_tuple_ref": "tuple:opp_20260429_evidence_audit_a",
    "posterior_sample_refs": ["posterior:format_prior:evidence_audit"],
    "reward_vector_ref": "reward:opp_20260429_evidence_audit_a",
    "rescore_hidden_copy_allowed": false
  },
  "selected_format": {
    "format_id": "evidence_audit",
    "registry_ref": "schemas/content-programme-format.schema.json",
    "row_ref": "schemas/content-programme-format.schema.json#evidence_audit",
    "grounding_question": "Which claim can this evidence audit support?",
    "grounding_attempt_types": ["evidence_validation", "correction", "uncertainty"]
  },
  "broadcast_refs": [],
  "archive_refs": ["archive:run_public_archive_evidence_audit_20260429"],
  "selected_input_refs": ["input:source_bundle_a"],
  "substrate_refs": ["substrate:research_cards"],
  "semantic_capability_refs": ["capability:content_programme.evidence_audit"],
  "director_plan": {
    "director_snapshot_ref": "director-snapshot:20260429t044000z",
    "director_plan_ref": "director-plan:evidence_audit_a",
    "director_move_refs": ["director-move:foreground_evidence"],
    "condition_id": "condition_content_programming_20260429"
  },
  "gate_refs": {
    "grounding_gate_refs": ["grounding-gate:evidence_audit_a"],
    "rights_gate_refs": ["rights-gate:evidence_audit_a"],
    "privacy_gate_refs": ["privacy-gate:evidence_audit_a"],
    "monetization_gate_refs": [],
    "public_event_gate_refs": ["public-event-gate:evidence_audit_a"]
  },
  "wcs": {
    "semantic_substrate_refs": ["semantic-substrate:research_cards"],
    "grounding_contract_refs": ["grounding-contract:evidence_audit"],
    "evidence_envelope_refs": ["ee:evidence_audit_a"],
    "witness_requirements": [
      {
        "requirement_id": "witness-required:evidence_audit_a",
        "substrate_ref": "semantic-substrate:research_cards",
        "required_witness_refs": ["witness:archive_sidecar_hash"],
        "missing_witness_refs": []
      }
    ],
    "capability_outcome_refs": ["coe:evidence_audit_a"],
    "health_state": "healthy",
    "unavailable_reasons": [],
    "public_private_posture": {
      "requested_mode": "public_archive",
      "effective_mode": "public_archive",
      "rights_state": "cleared",
      "privacy_state": "public_safe",
      "public_event_policy_state": "linked",
      "monetization_state": "not_requested",
      "unavailable_reasons": []
    }
  },
  "events": [
    {"event_id": "event:evidence_audit_a:selected", "sequence": 0, "event_type": "selected"},
    {"event_id": "event:evidence_audit_a:started", "sequence": 1, "event_type": "started"},
    {"event_id": "event:evidence_audit_a:boundary", "sequence": 2, "event_type": "boundary_emitted"}
  ],
  "boundary_event_refs": [
    {
      "boundary_id": "pbe_evidence_audit_a_001",
      "sequence": 1,
      "boundary_type": "claim.made",
      "duplicate_key": "programme_content_grounding_20260429:run_public_archive_evidence_audit_20260429:claim.made:001",
      "cuepoint_chapter_distinction": "none",
      "public_event_mapping_ref": "rvpe:evidence_audit_a",
      "mapping_state": "research_vehicle_linked",
      "unavailable_reasons": []
    }
  ],
  "claims": [
    {
      "claim_id": "claim:evidence_audit_a",
      "evidence_refs": ["source:primary_doc_a", "gate:grounding"],
      "evidence_envelope_refs": ["ee:evidence_audit_a"],
      "uncertainty_ref": "uncertainty:evidence_audit_a",
      "posterior_state_ref": "posterior-state:evidence_audit_a"
    }
  ],
  "uncertainties": [
    {
      "state_id": "uncertainty:evidence_audit_a",
      "reason": "Scope is limited to the declared source window.",
      "evidence_refs": ["source:primary_doc_a"]
    }
  ],
  "refusals": [],
  "corrections": [],
  "scores": [
    {
      "evaluation_id": "fge:evidence_audit_a",
      "dimension": "uncertainty",
      "score_ref": "score:evidence_audit_a:uncertainty",
      "evidence_refs": ["ee:evidence_audit_a"],
      "verdict_authority_allowed": false,
      "engagement_metric_source_allowed": false
    }
  ],
  "conversion_candidates": [
    {
      "candidate_id": "conversion:evidence_audit_archive",
      "conversion_type": "archive_replay",
      "state": "linked",
      "requires_research_vehicle_public_event": true,
      "research_vehicle_public_event_ref": "rvpe:evidence_audit_a",
      "owned_cleared_av_ref": null,
      "monetization_readiness_ref": null,
      "unavailable_reasons": []
    }
  ],
  "nested_outcomes": [
    {
      "outcome_id": "nested:run_public_archive_evidence_audit_20260429:observation",
      "kind": "observation",
      "state": "verified",
      "parent_outcome_refs": [],
      "capability_outcome_refs": ["coe:evidence_audit_a"],
      "evidence_envelope_refs": ["ee:evidence_audit_a"],
      "witness_refs": ["witness:archive_sidecar_hash"],
      "boundary_event_refs": ["pbe_evidence_audit_a_001"],
      "public_event_refs": [],
      "conversion_candidate_refs": [],
      "refusal_or_correction_refs": [],
      "blocked_reasons": [],
      "learning_update_allowed": true,
      "claim_posterior_update_allowed": false,
      "public_conversion_success": false,
      "validates_refused_claim": false
    },
    {
      "outcome_id": "nested:run_public_archive_evidence_audit_20260429:claim-gate",
      "kind": "claim_gate",
      "state": "accepted",
      "parent_outcome_refs": ["nested:run_public_archive_evidence_audit_20260429:observation"],
      "capability_outcome_refs": ["coe:evidence_audit_a"],
      "evidence_envelope_refs": ["ee:evidence_audit_a"],
      "witness_refs": [],
      "boundary_event_refs": ["pbe_evidence_audit_a_001"],
      "public_event_refs": [],
      "conversion_candidate_refs": [],
      "refusal_or_correction_refs": [],
      "blocked_reasons": [],
      "learning_update_allowed": true,
      "claim_posterior_update_allowed": true,
      "public_conversion_success": false,
      "validates_refused_claim": false
    },
    {
      "outcome_id": "nested:run_public_archive_evidence_audit_20260429:artifact",
      "kind": "artifact",
      "state": "emitted",
      "parent_outcome_refs": ["nested:run_public_archive_evidence_audit_20260429:claim-gate"],
      "capability_outcome_refs": [],
      "evidence_envelope_refs": ["ee:evidence_audit_a"],
      "witness_refs": [],
      "boundary_event_refs": ["pbe_evidence_audit_a_001"],
      "public_event_refs": ["rvpe:evidence_audit_a"],
      "conversion_candidate_refs": ["conversion:evidence_audit_archive"],
      "refusal_or_correction_refs": [],
      "blocked_reasons": [],
      "learning_update_allowed": true,
      "claim_posterior_update_allowed": false,
      "public_conversion_success": false,
      "validates_refused_claim": false
    },
    {
      "outcome_id": "nested:run_public_archive_evidence_audit_20260429:public-event",
      "kind": "public_event",
      "state": "accepted",
      "parent_outcome_refs": ["nested:run_public_archive_evidence_audit_20260429:artifact"],
      "capability_outcome_refs": [],
      "evidence_envelope_refs": ["ee:evidence_audit_a"],
      "witness_refs": [],
      "boundary_event_refs": ["pbe_evidence_audit_a_001"],
      "public_event_refs": ["rvpe:evidence_audit_a"],
      "conversion_candidate_refs": [],
      "refusal_or_correction_refs": [],
      "blocked_reasons": [],
      "learning_update_allowed": true,
      "claim_posterior_update_allowed": false,
      "public_conversion_success": false,
      "validates_refused_claim": false
    },
    {
      "outcome_id": "nested:run_public_archive_evidence_audit_20260429:conversion",
      "kind": "conversion",
      "state": "linked",
      "parent_outcome_refs": ["nested:run_public_archive_evidence_audit_20260429:public-event"],
      "capability_outcome_refs": [],
      "evidence_envelope_refs": ["ee:evidence_audit_a"],
      "witness_refs": [],
      "boundary_event_refs": [],
      "public_event_refs": ["rvpe:evidence_audit_a"],
      "conversion_candidate_refs": ["conversion:evidence_audit_archive"],
      "refusal_or_correction_refs": [],
      "blocked_reasons": [],
      "learning_update_allowed": true,
      "claim_posterior_update_allowed": false,
      "public_conversion_success": true,
      "validates_refused_claim": false
    },
    {
      "outcome_id": "nested:run_public_archive_evidence_audit_20260429:refusal",
      "kind": "refusal",
      "state": "not_applicable",
      "parent_outcome_refs": ["nested:run_public_archive_evidence_audit_20260429:claim-gate"],
      "capability_outcome_refs": [],
      "evidence_envelope_refs": [],
      "witness_refs": [],
      "boundary_event_refs": [],
      "public_event_refs": [],
      "conversion_candidate_refs": [],
      "refusal_or_correction_refs": [],
      "blocked_reasons": [],
      "learning_update_allowed": false,
      "claim_posterior_update_allowed": false,
      "public_conversion_success": false,
      "validates_refused_claim": false
    },
    {
      "outcome_id": "nested:run_public_archive_evidence_audit_20260429:correction",
      "kind": "correction",
      "state": "not_applicable",
      "parent_outcome_refs": ["nested:run_public_archive_evidence_audit_20260429:claim-gate"],
      "capability_outcome_refs": [],
      "evidence_envelope_refs": [],
      "witness_refs": [],
      "boundary_event_refs": [],
      "public_event_refs": [],
      "conversion_candidate_refs": [],
      "refusal_or_correction_refs": [],
      "blocked_reasons": [],
      "learning_update_allowed": false,
      "claim_posterior_update_allowed": false,
      "public_conversion_success": false,
      "validates_refused_claim": false
    }
  ],
  "command_execution": {
    "selected": {
      "record_id": "selected:evidence_audit_a",
      "state": "selected",
      "occurred_at": "2026-04-29T04:40:00Z",
      "refs": ["cod_20260429_evidence_audit_a"],
      "posterior_update_allowed": false
    },
    "commanded_states": [
      {
        "record_id": "commanded:evidence_audit_a",
        "state": "accepted",
        "occurred_at": "2026-04-29T04:40:01Z",
        "refs": ["director-plan:evidence_audit_a"],
        "posterior_update_allowed": false
      }
    ],
    "executed_states": [
      {
        "record_id": "executed:evidence_audit_a",
        "state": "applied",
        "occurred_at": "2026-04-29T04:40:02Z",
        "refs": ["archive:run_public_archive_evidence_audit_20260429"],
        "posterior_update_allowed": false
      }
    ],
    "witnessed_outcomes": [
      {
        "outcome_id": "outcome:evidence_audit_a",
        "witness_state": "witness_verified",
        "evidence_envelope_refs": ["ee:evidence_audit_a"],
        "capability_outcome_ref": "coe:evidence_audit_a",
        "posterior_update_allowed": true
      }
    ]
  },
  "witnessed_outcomes": [
    {
      "outcome_id": "outcome:evidence_audit_a",
      "witness_state": "witness_verified",
      "evidence_envelope_refs": ["ee:evidence_audit_a"],
      "capability_outcome_ref": "coe:evidence_audit_a",
      "posterior_update_allowed": true
    }
  ],
  "adapter_exposure": {
    "adapters": ["public_event", "scheduler", "feedback", "archive", "youtube", "metrics"],
    "ref": "adapter-exposure:evidence_audit_a",
    "stale_or_missing_state_blocks_public": true
  },
  "separation_policy": {
    "selected_commanded_executed_are_not_witnessed": true,
    "witnessed_outcomes_only_update_posteriors": true,
    "evaluator_outputs_are_evidence_outcomes": true,
    "engagement_can_override_grounding": false,
    "revenue_can_override_grounding": false,
    "engagement_metrics_stored_separately": true,
    "support_data_public_state_aggregate_only": true,
    "public_payer_identity_allowed": false
  },
  "operator_labor_policy": {
    "single_operator_only": true,
    "request_queue_allowed": false,
    "manual_content_calendar_allowed": false,
    "supporter_controlled_programming_allowed": false,
    "personalized_supporter_treatment_allowed": false
  },
  "final_status": "completed"
}
```

## Acceptance Pins

This contract is complete only if:

- the schema names every required envelope field,
- the schema defines the append-only `ContentProgrammeRunStoreEvent` event stream,
- event types include selected, started, transitioned, blocked, evidence, gate,
  boundary, claim, outcome, refusal, correction, artifact, conversion, public
  event, completed, and aborted states,
- selected opportunity and format registry refs are persisted,
- WCS refs include substrates, contracts, evidence envelopes, witnesses,
  capability outcomes, health, unavailable reasons, and public/private posture,
- boundary events are refs, not duplicated semantics,
- public conversion requires `ResearchVehiclePublicEvent`,
- private and dry-run runs do not imply public eligibility,
- missing evidence fails closed,
- selected, commanded, and executed states cannot update posteriors,
- only witnessed outcomes can update posteriors,
- evaluator outputs remain evidence-bearing outcomes rather than expert-system
  verdicts,
- engagement and revenue are separate from grounding quality,
- support data is aggregate-only,
- no request queues, no manual content calendar, and no supporter-controlled
  programming are introduced.
