# Autonomous Content Programming Format Registry - Design Spec

**Status:** schema seed for `autonomous-content-programming-format-registry`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/autonomous-content-programming-format-registry.md`
**Date:** 2026-04-29
**Depends on:** `grounding-commitment-no-expert-system-gate`, `autonomous-grounding-value-stream-research`
**Scope:** `ContentProgrammeFormat` schema, initial recognizable format rows, grounding attempt semantics, no-expert-system fields, Bayesian selection fields, rights/consent fail-closed posture, public output mapping, revenue posture, and no-recurring-operator-labor constraints.
**Non-scope:** content runner implementation, Bayesian opportunity model implementation, media acquisition, platform API writes, YouTube uploads, live cuepoint insertion, or public fanout execution.

## Purpose

Autonomous content programming treats familiar formats as scientific grounding
attempts.

Tier lists, react/commentary, rankings, comparisons, reviews, watch-alongs,
explainers, rundowns, debates, brackets, "what is this?" segments, refusal
breakdowns, and evidence audits are not entertainment wrappers around Hapax.
They are bounded protocols for testing what Hapax can perceive, classify,
compare, rank, explain, refuse, correct, and legitimately claim.

The registry defines those protocols before a runner or scheduler can execute
them. A format row says what question it grounds, what evidence it needs, which
substrates it may consume, which public claims it may emit, how the
no-expert-system gate constrains it, how Bayesian selection may learn from it,
and how it may become public outputs without inventing publication, revenue, or
rights facts.

## `ContentProgrammeFormat` Schema Seed

The machine-readable seed lives at:

- `schemas/content-programme-format.schema.json`

Required top-level fields:

| Field | Meaning |
|---|---|
| `schema_version` | Format schema version. Initial value is `1`. |
| `format_id` | Stable format id from the initial registry vocabulary. |
| `display_name` | Operator-facing and archive-facing format name. |
| `traditional_content_analogue` | The recognizable public format shape. |
| `grounding_question` | The exact question a run of this format tries to ground. |
| `grounding_attempt_types` | What counts as the grounding attempt. |
| `input_substrates` | Allowed substrate ids or substrate classes this format can consume. |
| `allowed_media_classes` | Media classes allowed for private, public, archive, and monetized use. |
| `director_verbs` | Verbs the director may use while staging the format. |
| `permitted_claim_shape` | Allowed claim kind, authority ceiling, verbs, uncertainty, and confidence policy. |
| `evidence_requirement` | Required evidence classes, freshness, citations, rights, provenance, and minimum evidence count. |
| `no_expert_system_policy` | Machine-readable assertion that the format gates attempts but does not produce hidden expertise. |
| `rights_posture` | Rights, consent, privacy, and third-party media fail-closed policy. |
| `public_claim_policy` | Public-live, archive, metadata, caption, chapter, Shorts, monetization, and refusal/correction permissions. |
| `public_output_mapping` | How the format may become title, description, chapter, caption, Shorts, archive/replay, and public-event outputs. |
| `archive_outputs` | Archive, replay, artifact, dataset, and correction outputs the format can produce. |
| `monetization_posture` | Platform-native, support, artifact, replay, edition, grant/demo, and refusal-artifact revenue posture. |
| `bayesian_policy` | Format priors, source compatibility, rewards, exploration eligibility, and cooldown. |
| `metrics` | Grounding, artifact, revenue, safety, labor, and outcome metrics. |
| `grounding_infraction_behavior` | How each forbidden infraction downgrades, blocks, refuses, or corrects the run. |
| `operator_labor_policy` | Guarantees that the format does not create recurring operator labor or supporter obligations. |
| `boundary_event_types` | Programme boundary events this format may emit. |
| `status` | Registry lifecycle state: proposed, dry-run-ready, private-ready, public-eligible, paused, or retired. |

Example row:

```json
{
  "schema_version": 1,
  "format_id": "tier_list",
  "display_name": "Evidence tier list",
  "traditional_content_analogue": "Tier list or ranking video",
  "grounding_question": "Which candidate model routes are best supported by current grounding evidence?",
  "grounding_attempt_types": ["classification", "ranking", "comparison", "uncertainty", "claim_confidence_update"],
  "input_substrates": ["research_cards", "terminal_tiles", "programme_cuepoints"],
  "allowed_media_classes": ["operator_original", "operator_controlled", "text_reference", "metadata_only"],
  "director_verbs": ["stage", "foreground", "compare", "rank", "mark boundary", "refuse", "correct"],
  "permitted_claim_shape": {
    "claim_kind": "ranking",
    "authority_ceiling": "evidence_bound",
    "allowed_verbs": ["observed", "compared", "ranked", "downgraded", "refused", "corrected"],
    "forbidden_verbs": ["proved", "certified", "guaranteed", "diagnosed"],
    "confidence_policy": "posterior_required",
    "uncertainty_language": "Name missing evidence, freshness, and scope limits in every public or archive claim.",
    "scope_limit": "Ranks only the candidate set and evidence window declared by the run."
  },
  "evidence_requirement": {
    "required_evidence_classes": ["source_ref", "criterion", "comparison_trace", "grounding_gate_ref"],
    "minimum_evidence_refs": 2,
    "freshness_ttl_s": 86400,
    "requires_primary_or_official_source": false,
    "requires_rights_provenance": true,
    "requires_grounding_gate": true,
    "requires_public_event_mapping": true
  },
  "no_expert_system_policy": {
    "rules_may_gate_and_structure_attempts": true,
    "authoritative_verdict_allowed": false,
    "trend_as_truth_allowed": false,
    "hidden_expertise_allowed": false,
    "must_emit_uncertainty": true
  },
  "rights_posture": {
    "default_public_mode": "dry_run",
    "third_party_media_policy": "metadata_or_link_only",
    "consent_required_media_allowed": false,
    "uncleared_media_allowed_publicly": false,
    "monetization_requires_rights_clearance": true,
    "fail_closed_reasons": ["rights_blocked", "privacy_blocked", "missing_grounding_gate"]
  },
  "public_claim_policy": {
    "public_live_allowed": false,
    "public_archive_allowed": true,
    "metadata_allowed": true,
    "captions_allowed": true,
    "chapters_allowed": true,
    "shorts_allowed": false,
    "monetization_allowed": false,
    "refusal_artifact_allowed": true,
    "correction_artifact_required_on_public_error": true
  },
  "public_output_mapping": {
    "title_policy": "May name the bounded ranking only after gate pass or dry-run label.",
    "description_policy": "Must include evidence window, uncertainty, and denied surfaces.",
    "chapter_policy": "May create VOD chapter markers from rank or criterion boundaries.",
    "caption_policy": "May caption only evidence-bound summaries and uncertainty.",
    "shorts_policy": "Disabled unless owned/cleared visuals and public claim gate pass.",
    "archive_replay_policy": "Archive run card stores criteria, evidence refs, ranks, refusals, and corrections.",
    "public_event_policy": "Emits programme.boundary, chapter.marker, refusal, and correction events only through ResearchVehiclePublicEvent.",
    "false_claim_controls": ["no_live_claim_without_egress", "no_monetization_claim_without_ledger", "no_rights_claim_without_provenance"]
  },
  "archive_outputs": ["run_card", "rank_table", "criteria_sheet", "refusal_artifact", "correction_artifact"],
  "monetization_posture": {
    "revenue_routes": ["platform_native", "support_prompt", "artifact", "replay", "grant_demo_evidence"],
    "support_prompt_allowed": true,
    "artifact_allowed": true,
    "edition_allowed": false,
    "grant_demo_allowed": true,
    "paid_promotion_allowed": false,
    "monetization_blockers": ["dry_run_mode", "rights_blocked", "monetization_blocked"]
  },
  "bayesian_policy": {
    "format_prior": {"grounding_value": 0.75, "audience_value": 0.6, "artifact_value": 0.65, "revenue_value": 0.45, "risk": 0.2},
    "source_compatibility": ["official_docs", "operator_owned_archive", "public_metadata", "open_data"],
    "grounding_reward_dimensions": ["evidence_yield", "ranking_stability", "uncertainty_quality", "correction_value"],
    "artifact_revenue_reward_dimensions": ["chapter_value", "replay_value", "support_prompt_value", "grant_demo_value"],
    "exploration_eligibility": "eligible_private_first",
    "cooldown_policy": {"minimum_interval_s": 3600, "repeat_penalty": 0.2, "risk_reset_requires": ["new_evidence", "rights_pass"]}
  },
  "metrics": ["grounding_success", "evidence_count", "uncertainty_quality", "refusal_count", "correction_count", "archive_conversion", "revenue_route_attempted", "operator_touch_count"],
  "grounding_infraction_behavior": {
    "unsupported_claim": "block_claim_emit_refusal",
    "hidden_expertise": "block_public_claim",
    "unlabelled_uncertainty": "downgrade_to_private",
    "stale_source_claim": "refresh_or_dry_run",
    "rights_provenance_bypass": "block_public_and_monetized",
    "trend_as_truth": "rewrite_as_trend_observation",
    "false_public_live_claim": "emit_correction",
    "false_monetization_claim": "block_monetization",
    "missing_grounding_question": "block_runner",
    "missing_permitted_claim_shape": "block_runner",
    "expert_verdict_without_evidence": "block_claim_emit_refusal"
  },
  "operator_labor_policy": {
    "recurring_operator_labor_allowed": false,
    "community_obligation_allowed": false,
    "request_queue_allowed": false,
    "personalized_supporter_treatment_allowed": false,
    "manual_exception_allowed_only_for": ["bootstrap", "credentials", "legal_attestation", "guarded_approval", "refusal_boundary"]
  },
  "boundary_event_types": ["programme.started", "criterion.declared", "claim.made", "rank.assigned", "uncertainty.marked", "refusal.issued", "correction.made", "chapter.boundary", "programme.ended"],
  "status": "dry-run-ready"
}
```

## Initial Format Registry

Initial `format_id` values are:

| Format id | Traditional analogue | Grounding attempt types | Default public posture | Revenue mapping |
|---|---|---|---|---|
| `tier_list` | Tier list or ranked list | classification, comparison, ranking, uncertainty, claim-confidence update | Archive/chapter first; live only after gate pass. | Platform-native, support prompt, replay, grant/demo evidence. |
| `react_commentary` | React/commentary video | perception, explanation, refusal, uncertainty, correction | Metadata/link-only by default; no third-party rebroadcast. | Platform-native only for owned/cleared sources; refusal artifact otherwise. |
| `ranking` | Top-N or ordered ranking | classification, ranking, comparison, claim-confidence update | Archive/chapter safe when evidence-bound. | Platform-native, artifact, replay. |
| `comparison` | A vs B comparison | comparison, explanation, uncertainty, correction | Public only with symmetric evidence and scope limit. | Platform-native, support prompt, grant/demo evidence. |
| `review` | Product/tool/media review | perception, classification, comparison, explanation, refusal | Public if rights/provenance and sponsorship/compensation gates are clear. | Platform-native, artifact, support prompt; no paid promotion by default. |
| `watch_along` | Watch-along or companion commentary | perception, timed attention, explanation, uncertainty, refusal | Link-along or owned/cleared media only; third-party AV blocked. | Replay and support prompt only until rights clearance. |
| `explainer` | Explainer or tutorial | explanation, classification, claim-confidence update, uncertainty | Public/archive eligible with citations and freshness. | Platform-native, artifact, grant/demo evidence. |
| `rundown` | News/state rundown | classification, explanation, uncertainty, correction | Dry-run for current events until freshness/sensitivity gates pass. | Platform-native and support prompt only when public-safe. |
| `debate` | Internal debate/adversarial segment | comparison, explanation, uncertainty, correction | Archive-first; final claim must remain evidence-bound. | Replay, artifact, grant/demo evidence. |
| `bracket` | Tournament bracket | pairwise comparison, ranking, inconsistency testing | Archive/chapter safe when criteria and decisions are logged. | Platform-native, replay, artifact. |
| `what_is_this` | Mystery object/interface/media segment | perception, classification, uncertainty, correction | Public only if media and privacy are safe; uncertainty is the point. | Platform-native, Shorts only for owned/cleared visuals, replay. |
| `refusal_breakdown` | Why this cannot be made/published | refusal, explanation, correction, uncertainty | Public-safe refusal artifact when it does not expose private or unsafe material. | Refusal artifact, grant/demo evidence, support prompt. |
| `evidence_audit` | Claim audit or failure autopsy | evidence validation, correction, uncertainty, claim-confidence update | Public/archive eligible when sources and correction path are safe. | Artifact, replay, grant/demo evidence. |

These rows are enough for the Bayesian opportunity model to start with
recognizable public formats while staying inside evidence, rights, and labor
constraints.

## Grounding Attempt Semantics

Every format must explicitly name what counts as a successful or failed
grounding attempt. Valid initial attempt types are:

- `perception`
- `classification`
- `comparison`
- `ranking`
- `explanation`
- `refusal`
- `uncertainty`
- `correction`
- `claim_confidence_update`
- `timed_attention`
- `evidence_validation`
- `inconsistency_testing`

Each attempt emits `ProgrammeBoundaryEvent` records. A run that cannot emit at
least one boundary is not a content programme run. It is private scratch work.

`claim_confidence_update` never means a truth guarantee. It means an evidence
bound posterior or qualitative confidence update attached to a claim, refusal,
or correction.

## No-Expert-System And Evidence Fields

The registry consumes the grounding gate rather than replacing it. Each format
must declare:

- `grounding_question`
- `permitted_claim_shape.claim_kind`
- `permitted_claim_shape.authority_ceiling`
- `permitted_claim_shape.confidence_policy`
- `permitted_claim_shape.uncertainty_language`
- `evidence_requirement.required_evidence_classes`
- `evidence_requirement.minimum_evidence_refs`
- `evidence_requirement.freshness_ttl_s`
- `evidence_requirement.requires_rights_provenance`
- `evidence_requirement.requires_grounding_gate`
- `grounding_infraction_behavior`

The no-expert-system policy is strict:

Hapax cannot act as a hidden rule engine that emits expert-like verdicts.

- rules may structure attempts, score candidate evidence, and block outputs,
- rules may not become a hidden domain authority,
- trend/currentness is input evidence, not truth,
- popularity is not scientific warrant,
- public entertainment value cannot hide uncertainty,
- no format may convert a blocked infraction into public content except as an
  explicit refusal, correction, or failure artifact.

## Rights And Consent Fail-Closed Policy

Third-party media is unsafe by default.

Allowed default media classes:

- `operator_original`
- `operator_controlled`
- `public_domain`
- `creative_commons_compatible`
- `explicitly_licensed`
- `text_reference`
- `metadata_only`
- `link_along`
- `open_data`

Blocked or private-by-default classes:

- `third_party_uncleared`
- `fair_use_candidate`
- `synthetic_realistic_media`
- `identifiable_person_media`
- `sensitive_current_event_media`
- `consent_required`
- `unknown`

React/commentary and watch-along formats must default to metadata, citation,
link-along, or owned/cleared sources. They may not autonomously rebroadcast
third-party audio/video, rip streams, cache unauthorized media, compile source
media as the product, or publish Shorts from uncleared material.

Unknown means unavailable, not safe. Consent-required material remains private
unless a current consent contract or row-specific policy exists.

## Public Output Mapping

A format may produce public outputs only through declared mappings and upstream
truth. The output mapping must cover:

- YouTube title policy
- YouTube description policy
- VOD chapter policy
- caption policy
- Shorts policy
- archive/replay policy
- `ResearchVehiclePublicEvent` policy
- false-claim controls

Required false-claim controls:

- `no_live_claim_without_egress`
- `no_archive_claim_without_archive_ref`
- `no_monetization_claim_without_ledger`
- `no_rights_claim_without_provenance`
- `no_source_claim_without_evidence_refs`
- `no_short_without_owned_or_cleared_media`

Titles, descriptions, chapters, captions, Shorts, archive cards, replay cards,
and public events must inherit the format's gate result.
Dry-run outputs must say they are dry-run or remain private.
Public-safe refusal and correction artifacts are allowed; laundering the
blocked claim is not.

## Bayesian Selection And Rewards

The format registry supplies the priors and dimensions consumed by the later
opportunity model. It does not execute selection itself.

Each format must declare:

- `bayesian_policy.format_prior.grounding_value`
- `bayesian_policy.format_prior.audience_value`
- `bayesian_policy.format_prior.artifact_value`
- `bayesian_policy.format_prior.revenue_value`
- `bayesian_policy.format_prior.risk`
- `bayesian_policy.source_compatibility`
- `bayesian_policy.grounding_reward_dimensions`
- `bayesian_policy.artifact_revenue_reward_dimensions`
- `bayesian_policy.exploration_eligibility`
- `bayesian_policy.cooldown_policy`

Valid grounding reward dimensions include `evidence_yield`,
`classification_quality`, `ranking_stability`, `comparison_quality`,
`explanation_quality`, `uncertainty_quality`, `refusal_quality`,
`correction_value`, `posterior_update`, and `inconsistency_discovery`.

Valid artifact/revenue dimensions include `chapter_value`, `caption_value`,
`shorts_value`, `replay_value`, `artifact_value`, `support_prompt_value`,
`grant_demo_value`, `platform_native_value`, and `refusal_artifact_value`.

Risky formats start `eligible_private_first` or `dry_run_only` until rights,
egress, source freshness, and monetization gates pass.

## Revenue And Artifact Mapping

Revenue mapping is allowed only as posture, not as a promise.

Valid routes:

- `platform_native`
- `support_prompt`
- `artifact`
- `replay`
- `edition`
- `grant_demo_evidence`
- `refusal_artifact`

Each route is gated by the format row and by downstream ledgers. The registry
cannot claim YPP state, RPM, support receipts, sponsorship, affiliate status,
paid promotion, channel monetization, or artifact sales. It can say whether a
format is structurally eligible for a route after the relevant readiness gates
pass.

Paid promotion, affiliate, free-product review compensation, sponsor reads,
supporter-controlled topics, perk ladders, community moderation, request queues,
customer service, and personalized supporter treatment are refused by default.

## Operator Labor Constraint

Every format row must carry `operator_labor_policy` with all recurring
obligation booleans false:

- `recurring_operator_labor_allowed`
- `community_obligation_allowed`
- `request_queue_allowed`
- `personalized_supporter_treatment_allowed`

Manual exceptions are limited to:

- `bootstrap`
- `credentials`
- `legal_attestation`
- `guarded_approval`
- `refusal_boundary`

If a format requires recurring operator authorship, moderation, fulfillment,
supporter relationship management, or custom service delivery, the scheduler
must refuse it or keep it private.

## Downstream Unblockers

This registry unblocks:

- `bayesian-content-opportunity-model`
- `content-opportunity-input-source-registry`
- `content-format-source-pool-rights-ledger`
- `rights-safe-media-reference-gate`
- `format-grounding-evaluator`
- `content-programme-run-store-event-surface`
- `format-to-public-event-adapter`
- `content-programme-feedback-ledger`
- `content-programme-scheduler-policy`
- `youtube-content-programming-packaging-compiler`
- `content-programming-grounding-runner`

Those downstream packets consume this registry. They must not redefine format
semantics, rights posture, no-expert-system behavior, or no-recurring-labor
policy in parallel.

## Acceptance Pin

This spec is complete only if:

- the schema names all required `ContentProgrammeFormat` fields,
- all initial format ids are present in the schema and spec,
- every format has explicit grounding attempt semantics,
- no-expert-system and evidence fields are machine-readable,
- Bayesian prior/reward/cooldown fields are machine-readable,
- public output mapping covers title, description, chapters, captions, Shorts,
  archive/replay, and public events without false public claims,
- rights and consent rules fail closed for third-party media,
- revenue mapping is structural posture, not a revenue claim,
- recurring operator labor, community obligations, request queues, and
  personalized supporter treatment are forbidden.
