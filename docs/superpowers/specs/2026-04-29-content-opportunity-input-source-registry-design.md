# Content Opportunity Input Source Registry - Design Spec

**Status:** schema seed for `content-opportunity-input-source-registry`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/content-opportunity-input-source-registry.md`
**Date:** 2026-04-29
**Scope:** source classes, freshness, provenance, quota/rate limits, rights assumptions, privacy posture, source priors, and public-claim constraints for `ContentOpportunity` discovery.
**Non-scope:** crawler implementation, Tavily adapter implementation, YouTube writes, public-event adapters, scheduler policy, or programme runner implementation.

## Purpose

Hapax should discover content-programming opportunities without waiting for the
operator to nominate them, but discovery is not permission to publish.

The registry below defines which source classes may propose `ContentOpportunity`
candidates. Every candidate must carry freshness, provenance, quota/rate-limit
state, rights assumptions, privacy posture, and source priors before the
Bayesian selector or any public surface consumes it.

## Machine-Readable Registry

The schema seed lives at:

- `schemas/content-opportunity-input-source-registry.schema.json`

Required top-level fields:

| Field | Meaning |
|---|---|
| `schema_version` | Registry schema version. Initial value is `1`. |
| `registry_id` | Stable registry id. |
| `declared_at` | UTC timestamp for this registry declaration. |
| `producer` | Component or session that produced the registry. |
| `global_policy` | Cross-source policy: single operator, aggregate-only audience signals, no supporter control, no request queues, current-source requirements. |
| `source_classes` | Source class records that can propose opportunities. |

Example registry:

```json
{
  "schema_version": 1,
  "registry_id": "content_opportunity_input_source_registry_20260429",
  "declared_at": "2026-04-29T02:20:00Z",
  "producer": "cx-red",
  "global_policy": {
    "single_operator_only": true,
    "supporter_controlled_programming_allowed": false,
    "per_person_request_queues_allowed": false,
    "aggregate_audience_only": true,
    "trend_as_truth_allowed": false,
    "official_current_source_required_for_current_event": true,
    "missing_freshness_blocks_public_claim": true,
    "private_dry_run_default_for_uncertain_sources": true,
    "forbidden_uses": [
      "per_person_request_queue",
      "supporter_controlled_programming",
      "supporter_priority_queue",
      "personalized_supporter_perk_content",
      "trend_as_truth_warrant",
      "uncleared_media_rebroadcast",
      "stale_current_event_claim",
      "private_analytics_disclosure",
      "identifiable_person_audience_targeting"
    ]
  },
  "source_classes": [
    {
      "source_class": "local_state",
      "description": "Obsidian goals, plans, active task state, chronicle summaries, programme outcomes, refusals, and corrections.",
      "freshness": {
        "default_ttl_s": 3600,
        "public_claim_ttl_s": 900,
        "stale_behavior": "downgrade_to_dry_run",
        "watermark_required": true
      },
      "provenance_requirements": [
        "local file or chronicle event ref",
        "producer id",
        "retrieved_at timestamp",
        "redaction or public-event mapping ref for public claims"
      ],
      "quota_rate_limits": {
        "quota_owner": "local_filesystem",
        "rate_limit_ref": "no external quota; bounded by scan budget",
        "failure_mode": "hold_candidate"
      },
      "rights_assumptions": "operator_controlled",
      "privacy_posture": "operator_private",
      "source_prior_fields": [
        {
          "field_name": "grounding_yield_prior",
          "meaning": "Probability that local state produces a grounded programme candidate.",
          "initial_value": 0.74,
          "update_signal": "accepted programme outcomes and refusal density"
        },
        {
          "field_name": "privacy_pass_probability",
          "meaning": "Probability the local-state reference can be made public after redaction and event mapping.",
          "initial_value": 0.35,
          "update_signal": "public-event gate pass/fail history"
        }
      ],
      "allowed_public_private_modes": [
        "private",
        "dry_run",
        "public_archive"
      ],
      "private_dry_run_only": false,
      "public_claim_requirements": [
        "redaction complete",
        "public-event source mapping present",
        "no private operator state exposed",
        "freshness watermark within public TTL"
      ],
      "official_current_source_policy": {
        "required": false,
        "applies_to": [],
        "primary_source_required": false,
        "max_source_age_s": null,
        "recency_label_required": false,
        "sensitivity_gate_required": false
      }
    },
    {
      "source_class": "owned_media",
      "description": "Operator-owned VOD, archive segments, generated visuals, operator-owned music/assets, and prior public events.",
      "freshness": {
        "default_ttl_s": 86400,
        "public_claim_ttl_s": 86400,
        "stale_behavior": "block_public_claim",
        "watermark_required": true
      },
      "provenance_requirements": [
        "asset path or archive sidecar ref",
        "rights owner declaration",
        "capture or generation timestamp",
        "public event id where available"
      ],
      "quota_rate_limits": {
        "quota_owner": "local_archive",
        "rate_limit_ref": "archive scan budget and storage pressure",
        "failure_mode": "hold_candidate"
      },
      "rights_assumptions": "owned_or_licensed_only",
      "privacy_posture": "public_safe_when_sanitized",
      "source_prior_fields": [
        {
          "field_name": "rights_pass_probability",
          "meaning": "Probability the media can be used without third-party clearance.",
          "initial_value": 0.86,
          "update_signal": "rights-ledger pass/fail events"
        },
        {
          "field_name": "artifact_conversion_prior",
          "meaning": "Probability the source produces a replay, clip, archive, or artifact candidate.",
          "initial_value": 0.68,
          "update_signal": "archive and conversion broker outcomes"
        }
      ],
      "allowed_public_private_modes": [
        "private",
        "dry_run",
        "public_live",
        "public_archive",
        "public_monetizable"
      ],
      "private_dry_run_only": false,
      "public_claim_requirements": [
        "rights ledger pass",
        "privacy scan pass",
        "archive sidecar fresh",
        "audio and visual safety gates pass"
      ],
      "official_current_source_policy": {
        "required": false,
        "applies_to": [],
        "primary_source_required": false,
        "max_source_age_s": null,
        "recency_label_required": false,
        "sensitivity_gate_required": false
      }
    },
    {
      "source_class": "platform_native_state",
      "description": "YouTube analytics, VOD/comment/chat aggregates, known video ids, cuepoints, publication state, and platform status.",
      "freshness": {
        "default_ttl_s": 21600,
        "public_claim_ttl_s": 3600,
        "stale_behavior": "downgrade_to_dry_run",
        "watermark_required": true
      },
      "provenance_requirements": [
        "platform API endpoint or export ref",
        "account/channel id",
        "retrieved_at timestamp",
        "aggregation window"
      ],
      "quota_rate_limits": {
        "quota_owner": "youtube_api",
        "rate_limit_ref": "YouTube Data API quota and local caller budget",
        "failure_mode": "downgrade_to_dry_run"
      },
      "rights_assumptions": "public_metadata_only",
      "privacy_posture": "aggregate_only",
      "source_prior_fields": [
        {
          "field_name": "audience_signal_prior",
          "meaning": "Probability that aggregate platform response predicts useful programming.",
          "initial_value": 0.52,
          "update_signal": "aggregate retention, view, replay, and conversion outcomes"
        },
        {
          "field_name": "quota_cost_prior",
          "meaning": "Expected quota cost for refreshing platform state.",
          "initial_value": 0.45,
          "update_signal": "API quota usage and rate-limit events"
        }
      ],
      "allowed_public_private_modes": [
        "private",
        "dry_run",
        "public_archive"
      ],
      "private_dry_run_only": false,
      "public_claim_requirements": [
        "aggregate-only disclosure",
        "no private analytics values unless explicitly cleared",
        "platform source timestamp present",
        "quota state recorded"
      ],
      "official_current_source_policy": {
        "required": false,
        "applies_to": [],
        "primary_source_required": false,
        "max_source_age_s": null,
        "recency_label_required": false,
        "sensitivity_gate_required": false
      }
    },
    {
      "source_class": "trend_sources",
      "description": "Official releases, RSS, Wikipedia current events, Google Trends API, allowed public charts, and similar currentness signals.",
      "freshness": {
        "default_ttl_s": 3600,
        "public_claim_ttl_s": 1800,
        "stale_behavior": "refresh_required",
        "watermark_required": true
      },
      "provenance_requirements": [
        "canonical URL or API result id",
        "publisher or provider id",
        "retrieved_at timestamp",
        "published_at timestamp where available",
        "recency label"
      ],
      "quota_rate_limits": {
        "quota_owner": "external_provider",
        "rate_limit_ref": "provider terms, robots policy, and local research budget",
        "failure_mode": "deny_public_claim"
      },
      "rights_assumptions": "official_primary_sources_only",
      "privacy_posture": "public_reference",
      "source_prior_fields": [
        {
          "field_name": "source_reliability_prior",
          "meaning": "Probability that this trend provider supplies accurate metadata for the narrow claim.",
          "initial_value": 0.6,
          "update_signal": "claim audit and correction outcomes"
        },
        {
          "field_name": "trend_decay_prior",
          "meaning": "Expected decay rate of public relevance for the trend candidate.",
          "initial_value": 0.7,
          "update_signal": "freshness misses and outcome half-life"
        }
      ],
      "allowed_public_private_modes": [
        "private",
        "dry_run",
        "public_live",
        "public_archive"
      ],
      "private_dry_run_only": false,
      "public_claim_requirements": [
        "official or primary source present for current-event claim",
        "recency label shown",
        "trend not treated as truth warrant",
        "sensitivity gate pass"
      ],
      "official_current_source_policy": {
        "required": true,
        "applies_to": [
          "trend_candidate",
          "current_event_claim",
          "public_claim",
          "sensitive_topic"
        ],
        "primary_source_required": true,
        "max_source_age_s": 86400,
        "recency_label_required": true,
        "sensitivity_gate_required": true
      }
    },
    {
      "source_class": "curated_watchlists",
      "description": "Bootstrapped lists that Hapax may consume autonomously after setup, including topics, channels, docs, datasets, and assets.",
      "freshness": {
        "default_ttl_s": 604800,
        "public_claim_ttl_s": 86400,
        "stale_behavior": "downgrade_to_dry_run",
        "watermark_required": true
      },
      "provenance_requirements": [
        "watchlist id",
        "curation owner or source",
        "last reviewed timestamp",
        "inclusion rationale"
      ],
      "quota_rate_limits": {
        "quota_owner": "watchlist_owner",
        "rate_limit_ref": "watchlist scan cadence and downstream provider quotas",
        "failure_mode": "hold_candidate"
      },
      "rights_assumptions": "unknown_blocks_public",
      "privacy_posture": "public_safe_when_sanitized",
      "source_prior_fields": [
        {
          "field_name": "source_reliability_prior",
          "meaning": "Probability that a curated item still points at an intended useful source.",
          "initial_value": 0.58,
          "update_signal": "dead-link, stale-item, and accepted-candidate history"
        },
        {
          "field_name": "grounding_yield_prior",
          "meaning": "Probability that the watchlist item produces a grounded format run.",
          "initial_value": 0.62,
          "update_signal": "programme acceptance and evaluator outcomes"
        }
      ],
      "allowed_public_private_modes": [
        "private",
        "dry_run",
        "public_archive"
      ],
      "private_dry_run_only": false,
      "public_claim_requirements": [
        "source ref refreshed",
        "rights state resolved",
        "privacy review pass",
        "watchlist rationale preserved"
      ],
      "official_current_source_policy": {
        "required": false,
        "applies_to": [
          "current_event_claim"
        ],
        "primary_source_required": true,
        "max_source_age_s": 86400,
        "recency_label_required": true,
        "sensitivity_gate_required": true
      }
    },
    {
      "source_class": "public_web_references",
      "description": "Official docs, primary sources, publisher pages, open data, and public pages used as reference material.",
      "freshness": {
        "default_ttl_s": 86400,
        "public_claim_ttl_s": 86400,
        "stale_behavior": "refresh_required",
        "watermark_required": true
      },
      "provenance_requirements": [
        "canonical URL",
        "retrieved_at timestamp",
        "publisher identity",
        "source type",
        "quoted or summarized claim binding"
      ],
      "quota_rate_limits": {
        "quota_owner": "web_research_provider",
        "rate_limit_ref": "Tavily/web provider monthly budget and domain-specific policies",
        "failure_mode": "deny_public_claim"
      },
      "rights_assumptions": "official_primary_sources_only",
      "privacy_posture": "public_reference",
      "source_prior_fields": [
        {
          "field_name": "source_reliability_prior",
          "meaning": "Probability that the public reference is authoritative for the narrow claim.",
          "initial_value": 0.7,
          "update_signal": "claim audit outcomes and correction events"
        },
        {
          "field_name": "freshness_decay_prior",
          "meaning": "Probability that the reference remains adequate without refresh.",
          "initial_value": 0.5,
          "update_signal": "source age, page update cadence, and stale-claim incidents"
        }
      ],
      "allowed_public_private_modes": [
        "private",
        "dry_run",
        "public_live",
        "public_archive",
        "public_monetizable"
      ],
      "private_dry_run_only": false,
      "public_claim_requirements": [
        "canonical URL stored",
        "publisher identity present",
        "current-event claim uses official or primary source",
        "quote/citation limits respected"
      ],
      "official_current_source_policy": {
        "required": true,
        "applies_to": [
          "current_event_claim",
          "public_claim",
          "sensitive_topic"
        ],
        "primary_source_required": true,
        "max_source_age_s": 86400,
        "recency_label_required": true,
        "sensitivity_gate_required": true
      }
    },
    {
      "source_class": "ambient_aggregate_audience",
      "description": "Aggregate audience signals such as counts, rates, retention, chat volume, and anonymized response summaries.",
      "freshness": {
        "default_ttl_s": 300,
        "public_claim_ttl_s": 120,
        "stale_behavior": "private_only",
        "watermark_required": true
      },
      "provenance_requirements": [
        "aggregate window",
        "metric producer id",
        "minimum aggregation threshold",
        "retrieved_at timestamp"
      ],
      "quota_rate_limits": {
        "quota_owner": "platform_or_local_metric",
        "rate_limit_ref": "analytics quota and local metric cadence",
        "failure_mode": "private_only"
      },
      "rights_assumptions": "aggregate_metadata_only",
      "privacy_posture": "aggregate_only",
      "source_prior_fields": [
        {
          "field_name": "audience_signal_prior",
          "meaning": "Probability that aggregate audience response is a useful programming signal.",
          "initial_value": 0.42,
          "update_signal": "subsequent watch, replay, support, and artifact outcomes"
        },
        {
          "field_name": "privacy_pass_probability",
          "meaning": "Probability that the aggregate is safe to reference without identifying a person.",
          "initial_value": 0.3,
          "update_signal": "aggregation threshold and privacy gate outcomes"
        }
      ],
      "allowed_public_private_modes": [
        "private",
        "dry_run"
      ],
      "private_dry_run_only": true,
      "public_claim_requirements": [
        "no per-person queue",
        "no supporter priority",
        "minimum aggregation threshold met",
        "no individual or handle exposed"
      ],
      "official_current_source_policy": {
        "required": false,
        "applies_to": [],
        "primary_source_required": false,
        "max_source_age_s": null,
        "recency_label_required": false,
        "sensitivity_gate_required": false
      }
    },
    {
      "source_class": "internal_anomalies",
      "description": "Errors, strange visual states, failed grounding attempts, substrate transitions, refusals, and correction events.",
      "freshness": {
        "default_ttl_s": 900,
        "public_claim_ttl_s": 300,
        "stale_behavior": "private_only",
        "watermark_required": true
      },
      "provenance_requirements": [
        "event id",
        "producer id",
        "detected_at timestamp",
        "affected substrate",
        "failure or refusal artifact ref"
      ],
      "quota_rate_limits": {
        "quota_owner": "local_event_stream",
        "rate_limit_ref": "anomaly summarizer cadence and alert budget",
        "failure_mode": "private_only"
      },
      "rights_assumptions": "operator_controlled",
      "privacy_posture": "private_or_dry_run_only",
      "source_prior_fields": [
        {
          "field_name": "anomaly_yield_prior",
          "meaning": "Probability that an anomaly produces a useful failure autopsy or refusal breakdown.",
          "initial_value": 0.66,
          "update_signal": "accepted failure-autopsy outcomes and correction artifact reuse"
        },
        {
          "field_name": "privacy_pass_probability",
          "meaning": "Probability the anomaly can be shown without leaking private state.",
          "initial_value": 0.25,
          "update_signal": "public-event, redaction, and egress gate outcomes"
        }
      ],
      "allowed_public_private_modes": [
        "private",
        "dry_run"
      ],
      "private_dry_run_only": true,
      "public_claim_requirements": [
        "refusal or correction artifact created",
        "private paths and secrets redacted",
        "public-event adapter explicitly promotes the anomaly",
        "affected substrate state remains fresh"
      ],
      "official_current_source_policy": {
        "required": false,
        "applies_to": [],
        "primary_source_required": false,
        "max_source_age_s": null,
        "recency_label_required": false,
        "sensitivity_gate_required": false
      }
    }
  ]
}
```

## Source Class Registry

The required source classes are:

| Source class | Candidate role | Default public posture |
|---|---|---|
| `local_state` | Turns Obsidian plans, goals, active tasks, chronicle state, outcomes, refusals, and corrections into candidate subjects. | Private/dry-run by default; archive/public only after redaction and public-event mapping. |
| `owned_media` | Finds replay, review, clip, artifact, and archive candidates from material Hapax controls. | Public-capable only after rights, privacy, archive, audio, and visual gates pass. |
| `platform_native_state` | Uses YouTube and platform-native aggregate state to find follow-on topics and packaging opportunities. | Aggregate-only. Exact private analytics stay private unless separately cleared. |
| `trend_sources` | Identifies currentness and timing opportunities from allowed public trend surfaces. | Public claims require official or primary sources and recency labels. Trend is not truth. |
| `curated_watchlists` | Lets Hapax consume bootstrapped topic/source lists without operator nomination. | Public only after source refresh, rights resolution, and privacy review. |
| `public_web_references` | Supplies official docs, primary sources, publisher pages, and open data. | Public-capable with canonical URL, retrieval time, publisher identity, and citation limits. |
| `ambient_aggregate_audience` | Provides aggregate audience response as a scheduling and selection signal. | Private/dry-run only. No individual requests or supporter control. |
| `internal_anomalies` | Converts failures, substrate transitions, strange states, refusals, and corrections into candidate autopsies or refusal breakdowns. | Private/dry-run only until a later public-event adapter promotes a safe artifact. |

## Source Freshness And Provenance

Every source class must declare:

- `freshness.default_ttl_s`
- `freshness.public_claim_ttl_s`
- `freshness.stale_behavior`
- `freshness.watermark_required`
- `provenance_requirements`
- `quota_rate_limits`

Freshness is a public-claim gate, not a display nicety. A stale source can still
inform private scheduling or dry-run exploration, but it cannot justify a public
current claim. Missing freshness blocks public claims.

Provenance must be replayable enough for a later correction pass. At minimum,
each candidate needs a source ref, producer/tool identity, retrieval or
observation time, and the narrow claim or signal extracted from the source.

## Rights Privacy And Dry-Run Defaults

The registry separates candidate discovery from public eligibility.

`ambient_aggregate_audience` and `internal_anomalies` are private/dry-run-only
sources. They may affect scoring, scheduling, refusal artifacts, and follow-on
work, but they cannot directly create public-live, public-archive, or
public-monetizable opportunities.

Other sources can become public only when their class-specific requirements pass
and the downstream rights, privacy, grounding, egress, audio, visual, and
monetization gates agree.

## No Request Queues Or Supporter Control

The registry forbids:

- `per_person_request_queue`
- `supporter_controlled_programming`
- `supporter_priority_queue`
- `personalized_supporter_perk_content`
- `identifiable_person_audience_targeting`

Audience signals are aggregate only. Support can fund the system, but it cannot
control the programme queue, create customer-service obligations, create
per-person topic queues, or buy personalized content.

## Trend And Current Event Policy

Trend and current-event candidates require official or primary sources before
they can support public claims. For `trend_sources` and current-event
`public_web_references`:

- recency label required,
- primary or official source required,
- source age must be within `max_source_age_s`,
- sensitivity gate required for politics, elections, allegations, health,
  finance, violence, tragedy, identifiable persons, and similar high-risk
  surfaces,
- trend/currentness may route attention but may not become a truth warrant.

If those fields are missing, the candidate is private/dry-run only or refused.

## Source Priors

Each source class contributes priors for the Bayesian selector. The initial
fields are:

- `source_reliability_prior`
- `freshness_decay_prior`
- `rights_pass_probability`
- `privacy_pass_probability`
- `grounding_yield_prior`
- `audience_signal_prior`
- `artifact_conversion_prior`
- `quota_cost_prior`
- `trend_decay_prior`
- `anomaly_yield_prior`

These are priors, not authority. They are updated from observed programme
outcomes, rights/privacy gates, claim audits, correction events, quota failures,
and conversion outcomes.

## Candidate Output Contract

Any source that emits a `ContentOpportunity` candidate must include:

- source class,
- source ref,
- extracted subject,
- proposed format ids,
- freshness status and TTL,
- provenance refs,
- rights assumption,
- privacy posture,
- source prior fields,
- public/private mode ceiling,
- dry-run/private-only reason where applicable,
- official/current-source evidence for trend or current-event claims,
- forbidden-use check results.

Downstream systems may narrow this envelope, but they may not silently drop the
freshness, provenance, rights, privacy, or source-prior fields.
