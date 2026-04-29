# Content Candidate Discovery Daemon - Design Spec

**Status:** runnable producer seed for `content-candidate-discovery-daemon`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/content-candidate-discovery-daemon.md`
**Date:** 2026-04-29
**Scope:** source-observation ingestion, freshness/provenance/quota checks, trend/current-event gate integration, and auditable `ContentOpportunity` candidate emission.
**Non-scope:** programme scheduling, public fanout, YouTube writes, media scraping, supporter requests, or runner execution.

## Purpose

Hapax needs autonomous content-programming candidates without turning the
operator into the recurring topic source. The discovery daemon is the first
producer in that chain. It consumes registered source observations and emits
scored, blocked, held, or dry-run `ContentOpportunity` candidates.

The daemon must never schedule shows directly. Scheduling remains the job of
`content-programme-scheduler-policy`, after run-store, rights, public-event,
monetization, egress, and world-surface gates have had a chance to evaluate the
candidate.

## Runtime Contract

The runnable entry point is:

- `python -m agents.content_candidate_discovery --once`

The default systemd units are:

- `systemd/units/hapax-content-candidate-discovery.service`
- `systemd/units/hapax-content-candidate-discovery.timer`

The timer is enabled in `systemd/user-preset.d/hapax.preset`. The first shipped
runtime is a safe producer: it reads JSONL observations from `/dev/shm`, appends
candidate decisions to `/dev/shm`, writes health, and reports malformed source
rows to an audit log. A missing source-observation file is healthy zero-work,
not a disabled feature.

## Policy And Deployment Config

The policy config lives at:

- `config/content-candidate-discovery-daemon.json`

The config is pinned by:

- `schemas/content-candidate-discovery-daemon.schema.json`

The policy is enabled by default and declares:

- single operator only,
- no direct programme scheduling,
- no supporter request queues,
- no trend-as-truth,
- missing freshness blocks public claims,
- private/dry-run as the uncertain-source default,
- source-class public-mode ceilings,
- output, audit, and health paths.

## Source Observation Contract

The daemon consumes `ContentSourceObservation` rows. Required source facts:

| Field | Meaning |
|---|---|
| `observation_id` | Stable idempotency seed for the candidate decision. |
| `source_class` | One of the registered source classes from the input-source registry. |
| `source_id` | Registry/source identifier. |
| `format_id` | Candidate format such as tier list, review, claim audit, or refusal. |
| `subject` / `subject_cluster` | Bounded candidate object and cluster for posterior learning. |
| `retrieved_at` / `freshness_ttl_s` | Timestamp and TTL used before any public claim. |
| `public_mode` | Desired mode before gates downgrade or hold it. |
| `rights_state` / `rights_hints` | Rights posture and hints for the downstream rights ledger. |
| `substrate_refs` / `evidence_refs` / `provenance_refs` | Evidence carried downstream. |
| `source_priors` | Source-prior hints for the Bayesian opportunity model. |
| `grounding_question` | The question the content format can test. |

Trend and current-event observations also carry primary/official/corroborating
source counts, recency labels, uncertainty-copy flags, sensitivity state,
trend-decay score, and source-bias score.

## Candidate Output Contract

Each output row is a `ContentDiscoveryDecision` with:

- `status`: `emitted`, `held`, or `blocked`,
- `scheduler_action`: `emit_candidate`, `hold_for_refresh`, or `block`,
- `scheduled_show_created`: always `false`,
- the canonical `ContentOpportunity` tuple,
- freshness, quota, provenance, and trend/current-event gate records,
- blocked reasons,
- audit refs to the source registry, Bayesian model, and trend gate contracts.

The opportunity tuple preserves:

`format + input_source + subject + time_window + substrates + public_mode + rights_state`

The daemon emits candidates, not verdicts. Engagement, trend, revenue, or source
popularity never become scientific warrant.

## Gate Behavior

Freshness:

- Missing TTL or stale source holds the candidate and blocks public selection.
- Health still records the held candidate so the system can see why discovery is dry.

Quota and provenance:

- Quota/rate-limit failure holds the candidate.
- Incomplete provenance holds the candidate.

Supporter and request boundaries:

- Supporter-controlled programming and per-person request queues hard-block the candidate.

Trend and current events:

- `trend_sources`, `public_web_references`, and explicit current-event claims route through `shared.trend_current_event_gate`.
- Under-24h definitive rankings downgrade to watch/audit/refusal shapes.
- Sensitive events force refusal/audit posture and cannot monetize.
- Trend/currentness may route attention but may not become a truth warrant.

## Downstream Boundaries

The daemon feeds:

- Bayesian opportunity model,
- source-pool rights ledger,
- scheduler policy,
- run store,
- public-event adapters,
- feedback ledger.

Downstream systems must consume the persisted candidate decision. They must not
silently re-score a hidden copy of the source observation.

## Verification

Local verification should include:

- `python -m json.tool config/content-candidate-discovery-daemon.json`
- `python -m json.tool schemas/content-candidate-discovery-daemon.schema.json`
- focused docs, shared-model, and agent CLI tests
- ruff and pyright on the new shared/agent modules
- `git diff --check`
