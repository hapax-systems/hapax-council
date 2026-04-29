# Bayesian Content Opportunity Model - Design Spec

**Status:** schema seed for `bayesian-content-opportunity-model`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/bayesian-content-opportunity-model.md`
**Date:** 2026-04-29
**Depends on:** `grounding-commitment-no-expert-system-gate`
**Scope:** `ContentOpportunity` shape, eligibility gates, reward vector, posterior state, hierarchical Thompson sampling policy, cold-start priors, persistence, refusal, audit, and replay contract.
**Non-scope:** candidate discovery daemon, input source registry implementation, programme scheduler implementation, feedback ledger implementation, model-router implementation, or public adapter writes.

## Purpose

Hapax should discover and rank content opportunities without waiting for the
operator to nominate topics.

The model defined here is not an expert system and not an entertainment-only
optimizer. It is a gated contextual bandit for selecting recognizable content
formats as grounding attempts. Every selected opportunity remains provisional,
evidence-bound, reversible, and subordinate to truth, rights, privacy, consent,
monetization, substrate freshness, egress, and no-expert-system gates.

## ContentOpportunity Contract

The canonical opportunity tuple is:

`ContentOpportunity = format + input_source + subject + time_window + substrates + public_mode + rights_state`

Machine-readable decisions use:

- `format_id`: content programme format, such as tier list, review, bracket, or
  refusal breakdown.
- `input_source_id`: source registry id for the candidate stream or object.
- `subject`: the bounded topic, candidate set, asset, event, artifact, or
  question being grounded.
- `time_window`: start/end timestamps plus freshness TTL for trend-sensitive or
  source-sensitive candidates.
- `substrate_refs`: mounted content substrates needed to observe, explain,
  archive, or publish the opportunity.
- `public_mode`: private, dry-run, public-live, public-archive, or
  public-monetizable.
- `rights_state`: rights posture used before any public, archive, or
  monetized surface consumes the decision.
- `grounding_question`: the explicit question this opportunity can test.
- `evidence_refs`: local files, source ids, gate ids, event ids, citations, or
  substrate refs used by the decision.

The schema seed lives at:

- `schemas/content-opportunity-model.schema.json`

## Eligibility Gates

An opportunity is scoreable only after the gate envelope has been evaluated.
It is selectable for public mode only when every applicable public gate passes.

Required gates:

| Gate | Required evidence | Fail-closed behavior |
|---|---|---|
| `truth_gate` | Source evidence, freshness, claim shape, uncertainty, and correction path. | Block public claim or route to refusal/correction. |
| `rights_gate` | Rights class, provenance token, attribution, license, and media-use posture. | Force private/dry-run or refusal; never monetize. |
| `consent_gate` | Privacy class, aggregate-only status, consent contract, or public-safe basis. | Block person-identifying or consent-required public output. |
| `monetization_gate` | Monetization readiness, advertiser suitability, support/artifact policy, and no-perk surface state. | Set `may_monetize=false` and preserve unavailable reason. |
| `substrate_freshness_gate` | Fresh substrate/event/source observations under declared TTL. | Downgrade to refresh-needed or private-only. |
| `egress_gate` | Live/archive/public aperture evidence, audio safety, and surface readiness. | Deny live/public claims; archive only when archive evidence is fresh. |
| `no_expert_system_gate` | `GroundingCommitmentGateResult` ref, infractions, permitted claim shape, and authority ceiling. | Deny unsupported verdicts; emit refusal/correction artifact. |

The model may still record and learn from failed candidates. Blocked candidates
become a refusal, correction, or failure artifact when safe; they do not
disappear from the audit trail.

## Reward Vector

The scalar scoring equation is:

`score = E[grounding_value] + E[audience_value] + E[artifact_value] + E[revenue_value] + novelty_bonus - cost_penalty - risk_penalty`

Each reward component must carry a mean, uncertainty, evidence refs, and the
posterior ids that produced it.

| Component | Meaning |
|---|---|
| `grounding_value` | Expected evidence, classification, comparison, explanation, refusal, correction, or claim-confidence learning. |
| `audience_value` | Expected legibility, retention, usefulness, and public interest without treating popularity as truth. |
| `artifact_value` | Expected replay, dataset, zine, clip, chapter, archive card, citation, or public artifact yield. |
| `revenue_value` | Expected support, grant, platform, licensing, artifact, or product response, gated by monetization evidence. |
| `novelty_bonus` | Exploration value for under-sampled safe formats, sources, and subject clusters. |
| `cost_penalty` | Expected compute, quota, latency, operator overhead, coordination cost, and opportunity cost. |
| `risk_penalty` | Rights, privacy, consent, truth, egress, monetization, platform-policy, and reputational risk. |

Risk and cost are penalties, not hidden vetoes. Hard policy failures remain in
eligibility gates; soft risk shapes ranking and public/private mode.

## Posterior Families

The model maintains separate posterior state for:

| Posterior | Initial family | Update signal |
|---|---|---|
| `format_prior` | Categorical/Dirichlet or per-format Beta arms. | Format run outcomes, grounding yield, audience response, artifact conversion. |
| `source_prior` | Source-cluster Beta arms. | Source freshness, rights pass, yield, refusal rate, evidence quality. |
| `rights_pass_probability` | Beta. | Rights gate pass/fail and downstream attribution corrections. |
| `grounding_yield_probability` | Beta. | Evidence-bound claims, refusals, corrections, and evaluator scores. |
| `artifact_conversion_probability` | Beta. | Replay, chapter, zine, dataset, clip, archive, or publication artifact creation. |
| `audience_response` | Normal or Beta by metric. | Retention, CTR, comments aggregate, support intent, rewatch, or follow-through. |
| `revenue_support_response` | Log-normal, Gamma, or hurdle model. | Platform revenue, support, grant, artifact, license, or product conversion evidence. |
| `trend_decay` | Exponential half-life or time-to-stale posterior. | Source age, trend source updates, current-event sensitivity, and stale-source failures. |

Every posterior entry includes the family, parameters, mean, sampled value,
update count, last update time, and evidence refs. A posterior without evidence
must be marked `cold_start=true`.

## Hierarchical Thompson Sampling

Selection uses hierarchical Thompson sampling across three levels:

1. `format`
2. `source`
3. `subject_cluster`

The sampler draws posterior samples at each level, composes them with the
reward vector, then applies eligibility, cooldown, and exploration-budget
constraints.

Required policy fields:

- `hierarchy`: exactly `["format", "source", "subject_cluster"]`.
- `exploration_budget`: bounded per day/run window, with remaining budget,
  private-first mode, and max risk tier for exploration.
- `cooldowns`: format, source, subject-cluster, public-mode, and refusal
  cooldowns so one promising shape cannot monopolize programming.
- `risk_ceiling`: max allowed risk tier for public, archive, and monetized
  selections.
- `decision_reason`: why this candidate was selected, held, refused, or routed
  to private/dry-run.

Exploration is allowed only inside the declared budget. Public exploration must
pass all public gates. Risky or evidence-poor exploration starts private or
dry-run.

## Cold-Start Priors

Cold start favors low-rights/high-grounding opportunities:

- operator-original and operator-controlled material,
- public-domain or CC-compatible sources with attribution evidence,
- metadata-first reviews and explainers,
- refusal breakdowns and claim audits,
- local Obsidian/task/chronicle/programme-state candidates,
- archive-only or dry-run modes before public-live mode,
- formats with explicit grounding questions and low media-rights exposure.

Cold start deprioritizes:

- third-party audio/video,
- sensitive current events,
- identifiable-person commentary,
- full or near-full watch-alongs,
- supporter-controlled topics,
- monetized public claims without ledger evidence,
- candidates whose value depends on trend popularity rather than grounding
  evidence.

The cold-start prior is not permanent. It decays as observed outcomes update
format, source, rights, grounding, artifact, audience, revenue, and trend
posteriors.

## Persistence And Audit

Every model decision persists enough state for audit, replay, posterior update,
and refusal:

- `opportunity_id`
- full `ContentOpportunity` tuple
- gate states, blockers, unavailable reasons, and gate refs
- reward vector components and posterior refs
- posterior samples used for the decision
- sampler hierarchy, exploration-budget state, cooldown state, and random seed
- selected/held/refused decision and public/private route
- audit log ref and replay key
- posterior update ref or feedback-ledger placeholder
- refusal/correction/failure artifact ref when blocked
- idempotency key

State persistence must be append-friendly. Replaying a decision should explain
why it was selected or refused with the same evidence and posterior samples that
were available at the time.

## Downstream Interfaces

The model is consumed by:

- content programme format registry,
- content opportunity input source registry,
- rights/source pool ledger,
- format grounding evaluator,
- programme scheduler policy,
- content programme run store,
- programme boundary events,
- feedback ledger,
- conversion broker,
- YouTube/archive/artifact adapters.

Downstream systems do not re-score hidden copies of the candidate. They consume
the persisted decision and either add evidence or emit a refusal/correction
event.

## Example Decision

```json
{
  "schema_version": 1,
  "decision_id": "cod_20260429t021000z_tierlist_models_a",
  "evaluated_at": "2026-04-29T02:10:00Z",
  "producer": "content_opportunity_model",
  "opportunity": {
    "opportunity_id": "opp_20260429t021000z_model_routes_tierlist",
    "format_id": "tier_list",
    "input_source_id": "local_model_grounding_scout",
    "subject": "source-acquiring model route candidates for grounded content programming",
    "subject_cluster": "model_routing_grounding",
    "time_window": {
      "starts_at": "2026-04-29T00:00:00Z",
      "ends_at": "2026-04-30T00:00:00Z",
      "freshness_ttl_s": 86400
    },
    "substrate_refs": ["programme_cuepoints", "research_brief"],
    "public_mode": "dry_run",
    "rights_state": "operator_original",
    "grounding_question": "Which model-route candidates can Hapax justify from current evidence?",
    "evidence_refs": [
      "local:/home/hapax/Documents/Personal/20-projects/hapax-research/audits/2026-04-29-model-developments-grounding-scout.md",
      "grounding_gate_20260429t013000z_tierlist_a"
    ]
  },
  "eligibility": {
    "eligible": true,
    "public_selectable": false,
    "monetizable": false,
    "truth_gate": {
      "state": "pass",
      "gate_ref": "grounding_gate_20260429t013000z_tierlist_a",
      "evidence_refs": ["grounding_gate_20260429t013000z_tierlist_a"],
      "blockers": [],
      "unavailable_reasons": []
    },
    "rights_gate": {
      "state": "pass",
      "gate_ref": null,
      "evidence_refs": ["rights:operator_original"],
      "blockers": [],
      "unavailable_reasons": []
    },
    "consent_gate": {
      "state": "pass",
      "gate_ref": null,
      "evidence_refs": ["privacy:public_safe"],
      "blockers": [],
      "unavailable_reasons": []
    },
    "monetization_gate": {
      "state": "fail",
      "gate_ref": "monetization_readiness_missing",
      "evidence_refs": [],
      "blockers": ["monetization_ledger_missing"],
      "unavailable_reasons": ["monetization_blocked"]
    },
    "substrate_freshness_gate": {
      "state": "pass",
      "gate_ref": "substrate:research_brief",
      "evidence_refs": ["research_brief.age_s"],
      "blockers": [],
      "unavailable_reasons": []
    },
    "egress_gate": {
      "state": "fail",
      "gate_ref": "livestream_egress_state",
      "evidence_refs": ["LivestreamEgressState.public_claim_allowed=false"],
      "blockers": ["public_live_egress_blocked"],
      "unavailable_reasons": ["egress_blocked"]
    },
    "no_expert_system_gate": {
      "state": "pass",
      "gate_ref": "grounding_gate_20260429t013000z_tierlist_a",
      "evidence_refs": ["GroundingCommitmentGateResult.gate_state=dry_run"],
      "blockers": [],
      "unavailable_reasons": []
    }
  },
  "reward_vector": {
    "grounding_value": {"mean": 0.82, "uncertainty": 0.12, "posterior_refs": ["grounding_yield:model_routing"], "evidence_refs": ["grounding_gate_20260429t013000z_tierlist_a"]},
    "audience_value": {"mean": 0.48, "uncertainty": 0.25, "posterior_refs": ["audience_response:tier_list"], "evidence_refs": []},
    "artifact_value": {"mean": 0.7, "uncertainty": 0.18, "posterior_refs": ["artifact_conversion:tier_list"], "evidence_refs": ["archive:research_brief"]},
    "revenue_value": {"mean": 0.1, "uncertainty": 0.3, "posterior_refs": ["revenue_support_response:cold_start"], "evidence_refs": []},
    "novelty_bonus": {"mean": 0.16, "uncertainty": 0.05, "posterior_refs": ["format_prior:tier_list"], "evidence_refs": []},
    "cost_penalty": {"mean": 0.18, "uncertainty": 0.04, "posterior_refs": ["cost:dry_run"], "evidence_refs": ["quota:none"]},
    "risk_penalty": {"mean": 0.2, "uncertainty": 0.07, "posterior_refs": ["rights_pass_probability:operator_original"], "evidence_refs": ["rights:operator_original"]},
    "expected_total": 1.88
  },
  "posterior_state": {
    "format_prior": {"family": "beta", "alpha": 2.0, "beta": 1.0, "mean": 0.67, "sample": 0.74, "update_count": 0, "cold_start": true, "updated_at": null, "evidence_refs": []},
    "source_prior": {"family": "beta", "alpha": 2.0, "beta": 1.0, "mean": 0.67, "sample": 0.7, "update_count": 0, "cold_start": true, "updated_at": null, "evidence_refs": []},
    "rights_pass_probability": {"family": "beta", "alpha": 4.0, "beta": 1.0, "mean": 0.8, "sample": 0.82, "update_count": 1, "cold_start": false, "updated_at": "2026-04-29T02:00:00Z", "evidence_refs": ["rights:operator_original"]},
    "grounding_yield_probability": {"family": "beta", "alpha": 3.0, "beta": 1.0, "mean": 0.75, "sample": 0.79, "update_count": 1, "cold_start": false, "updated_at": "2026-04-29T02:00:00Z", "evidence_refs": ["grounding_gate_20260429t013000z_tierlist_a"]},
    "artifact_conversion_probability": {"family": "beta", "alpha": 2.0, "beta": 1.0, "mean": 0.67, "sample": 0.69, "update_count": 0, "cold_start": true, "updated_at": null, "evidence_refs": []},
    "audience_response": {"family": "normal", "alpha": null, "beta": null, "mean": 0.48, "sample": 0.5, "update_count": 0, "cold_start": true, "updated_at": null, "evidence_refs": []},
    "revenue_support_response": {"family": "lognormal", "alpha": null, "beta": null, "mean": 0.1, "sample": 0.08, "update_count": 0, "cold_start": true, "updated_at": null, "evidence_refs": []},
    "trend_decay": {"family": "exponential_decay", "alpha": null, "beta": null, "mean": 0.92, "sample": 0.9, "update_count": 0, "cold_start": true, "updated_at": null, "evidence_refs": []}
  },
  "sampler_policy": {
    "hierarchy": ["format", "source", "subject_cluster"],
    "exploration_budget": {
      "budget_window": "daily",
      "max_exploration_fraction": 0.2,
      "used_fraction": 0.05,
      "remaining_fraction": 0.15,
      "private_first": true,
      "max_public_risk_tier": "low"
    },
    "cooldowns": {
      "format_cooldown_s": 3600,
      "source_cooldown_s": 1800,
      "subject_cluster_cooldown_s": 7200,
      "public_mode_cooldown_s": 3600,
      "refusal_cooldown_s": 900
    },
    "risk_ceiling": {
      "private": "medium",
      "dry_run": "medium",
      "public_live": "low",
      "public_archive": "low",
      "public_monetizable": "minimal"
    },
    "random_seed_ref": "sampler_seed:20260429:cx-blue"
  },
  "sampler_decision": {
    "decision": "select_dry_run",
    "decision_reason": "High grounding and artifact value; public live and monetization gates unavailable.",
    "selected_for": ["private_rehearsal", "archive_candidate"],
    "held_reasons": ["egress_blocked", "monetization_blocked"],
    "refusal_required": false
  },
  "cold_start_priors": {
    "low_rights_high_grounding_bias": true,
    "preferred_rights_states": ["operator_original", "operator_controlled", "public_domain", "cc_compatible"],
    "preferred_formats": ["claim_audit", "refusal_breakdown", "explainer", "tier_list", "review"],
    "deprioritized_risks": ["third_party_audio_video", "sensitive_current_events", "identifiable_person_commentary", "supporter_controlled_topics"]
  },
  "persistence": {
    "audit_log_ref": "content_opportunity_decisions.jsonl#cod_20260429t021000z_tierlist_models_a",
    "replay_key": "opp_20260429t021000z_model_routes_tierlist:2026-04-29T02:10:00Z",
    "posterior_update_ref": "feedback_ledger:pending",
    "refusal_artifact_ref": null,
    "decision_trace_refs": ["sampler_seed:20260429:cx-blue"],
    "state_store_ref": "content_opportunity_model_state.json",
    "idempotency_key": "opp_20260429t021000z_model_routes_tierlist:dry_run"
  }
}
```

## Acceptance Pin

This spec is complete only if:

- the `ContentOpportunity` tuple is explicit in spec and schema,
- truth, rights, consent, monetization, substrate freshness, egress, and
  no-expert-system gates are machine-readable,
- the reward vector names grounding, audience, artifact, revenue, novelty,
  cost, and risk,
- posteriors are split for format, source, rights pass, grounding yield,
  artifact conversion, audience response, revenue/support response, and trend
  decay,
- hierarchical Thompson sampling covers format, source, and subject cluster,
- exploration budget and cooldowns are bounded,
- cold-start priors favor low-rights/high-grounding formats,
- persistence supports audit, replay, posterior update, and refusal artifacts.
