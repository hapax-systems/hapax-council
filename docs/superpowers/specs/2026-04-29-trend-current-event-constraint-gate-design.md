# Trend And Current-Event Constraint Gate - Design Spec

**Status:** implementation seed for `trend-current-event-constraint-gate`
**Task:** `obsidian-task:trend-current-event-constraint-gate`
**Date:** 2026-04-29
**Depends on:** `bayesian-content-opportunity-model`, `content-opportunity-input-source-registry`, `grounding-commitment-no-expert-system-gate`, `grounding-provider-model-router-eval-harness`
**Blocks:** `content-candidate-discovery-daemon`
**Scope:** deterministic public-claim gating for trend and current-event candidates before content opportunity selection, metadata, captions, chapters, public events, or monetization consume them.
**Non-scope:** web crawling, Tavily implementation, YouTube writes, model-provider routing, public-event fanout, or legal/domain expert adjudication.

## Purpose

Trend and current-event inputs may route attention. They may not become
authority.

The gate defined here prevents candidate discovery from converting popularity,
freshness, urgency, or public attention into a truth warrant. It forces every
trend/current-event candidate through timestamped freshness, primary or official
corroboration, sensitivity, uncertainty-copy, trend-decay, and source-bias
checks before any public claim can leave private/dry-run space.

## Machine-Readable Contract

The implementation seed lives in:

- `config/trend-current-event-constraint-gate.json`
- `schemas/trend-current-event-constraint-gate.schema.json`
- `shared/trend_current_event_gate.py`

Required top-level policy fields:

| Field | Meaning |
|---|---|
| `global_policy` | Hard constants: no trend-as-truth, source/freshness/uncertainty required, under-24h definitive ranking disallowed, sensitive-event monetization disallowed. |
| `freshness_policy` | Timestamped retrieval, recency labels, public TTLs, and stale-source behavior. |
| `corroboration_policy` | Minimum official/primary source and corroborating source counts. |
| `event_age_policy` | Under-24h events default to watching, audit, refusal, correction, or claim-audit formats. |
| `sensitivity_policy` | Sensitive categories, refusal/audit-only handling, EDSA-context requirement, and monetization denial. |
| `uncertainty_policy` | Required uncertainty language in both title and description. |
| `scoring_features` | Trend decay and source bias are scoring features only, never truth warrants. |
| `actions` | `allow_public_claim`, `downgrade_to_watch`, `force_refusal_format`, `block_public_claim`. |
| `downstream_contract` | Fields the candidate discovery daemon and public adapters must preserve. |

## Gate Inputs

The deterministic helper consumes a `TrendCurrentEventCandidate` with:

- candidate id, claim type, proposed format, and public/private mode,
- source age and TTL,
- event age,
- primary/official/corroborating source counts,
- recency-label state,
- title and description uncertainty markers,
- sensitivity categories and EDSA-context state,
- monetization intent,
- whether trend/currentness is being used as truth,
- `trend_decay_score`,
- `source_bias_score`.

The candidate may be produced by `trend_sources`, `public_web_references`,
curated watchlists, or grounding-provider routes, but the gate output shape is
source-neutral.

## Freshness And Corroboration

Public claims require timestamped freshness and corroboration:

- retrieval time is mandatory,
- published time is mandatory when available,
- public copies must show a recency label,
- trend-source public TTL is short (`1800` seconds),
- current-event public TTL is `3600` seconds,
- default public-source TTL is no more than `86400` seconds,
- at least one primary or official source is required,
- at least two corroborating source observations are required.

Missing or stale freshness emits `missing_freshness` or `stale_source` and
selects `block_public_claim`. Missing primary/official corroboration emits
`missing_primary_or_official_source` and also blocks public claims.

## Under-24H Policy

Events younger than 24 hours default to watching, audit, refusal, correction, or
claim-audit formats. They do not become definitive rankings, tier lists,
predictions, best-of lists, or final reviews.

If an under-24h candidate proposes a definitive format, the gate emits
`under_24h_definitive_format`, selects `downgrade_to_watch`, and sets the
required format family to `watching_or_audit`.

This is a default, not a permanent ban on discussing current events. A later
candidate can become public when source freshness, corroboration, uncertainty,
sensitivity, and public-surface gates pass.

## Sensitive Events

Sensitive current-event treatment includes politics, elections, allegations,
health, finance, violence, tragedy, identifiable persons, legal, and public
safety surfaces.

Sensitive candidates must be refusal, audit, correction, or claim-audit
artifacts with EDSA-style context. They may not be monetized. If a sensitive
candidate proposes ranking, reaction, definitive review, prediction, or
monetized treatment, the gate emits `sensitive_event_exploitation`, selects
`force_refusal_format`, denies monetization, and denies public claims until the
format is reframed.

## Uncertainty Copy

Current candidates must carry uncertainty in public-facing titles and
descriptions. Required public-copy fields are:

- `recency_label`,
- `freshness_checked_at`,
- `uncertainty_language`.

Valid uncertainty markers include "current evidence", "early signal",
"unverified", "watching", "needs corroboration", and "as of". Missing
uncertainty emits `missing_uncertainty_language` and selects
`downgrade_to_watch` unless a stronger blocker already selected
`block_public_claim` or `force_refusal_format`.

## Trend Decay And Source Bias

Trend decay and source bias are mandatory scoring features:

- `trend_decay_score` updates the `trend_decay` posterior in the Bayesian
  content opportunity model.
- `source_bias_score` updates source priors and risk/cost penalties.

Neither field is a truth warrant. A candidate with high trend strength but weak
freshness, missing corroboration, sensitive-event exploitation, missing
uncertainty, or untracked source bias remains blocked or downgraded.

## Gate Actions

| Action | Public claim | Meaning |
|---|---:|---|
| `allow_public_claim` | yes | Every freshness, corroboration, sensitivity, uncertainty, trend-decay, and source-bias constraint passes. |
| `downgrade_to_watch` | no | Candidate may remain private/dry-run or become watching/audit/refusal/correction. |
| `force_refusal_format` | no | Candidate must become refusal, audit, correction, or claim-audit before public treatment. |
| `block_public_claim` | no | Candidate lacks required evidence or commits a hard grounding infraction. |

The helper returns `TrendCurrentEventGateResult` with action, blockers,
infractions, required copy fields, required format family, monetization state,
and scoring features.

## Downstream Contract

`content-candidate-discovery-daemon` must run this gate before publishing,
scheduling public-live, building YouTube metadata, producing captions/chapters,
or updating monetization state for trend/current-event opportunities.

Downstream systems must preserve:

- `gate_id`,
- `candidate_id`,
- `action`,
- `infractions`,
- `blockers`,
- `required_copy_fields`,
- `trend_decay_score`,
- `source_bias_score`,
- `freshness_checked_at`,
- `recency_label`,
- `primary_or_official_source_refs`.

The gate feeds `content-opportunity-model`, `format-grounding-evaluator`,
`grounding-commitment-gate`, and `research-vehicle-public-event-contract`.

## Verification

The acceptance pins are:

- schema/config parse and require no trend-as-truth,
- source freshness and primary/official corroboration block public claims when missing,
- events under 24 hours downgrade definitive formats to watching/audit/refusal,
- sensitive-event treatment forces refusal/audit and denies monetization unless EDSA-context framing is present,
- uncertainty language is required in title and description,
- trend decay and source bias survive as scoring features and are not truth warrants,
- config and spec do not embed operator home paths.
