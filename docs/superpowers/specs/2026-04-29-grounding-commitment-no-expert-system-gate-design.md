# Grounding Commitment And No-Expert-System Gate - Design Spec

**Status:** schema seed for `grounding-commitment-no-expert-system-gate`
**Task:** `/home/hapax/Documents/Personal/20-projects/hapax-cc-tasks/active/grounding-commitment-no-expert-system-gate.md`
**Date:** 2026-04-29
**Scope:** machine-readable grounding gate results for content programming formats, programme runs, public events, captions, chapters, metadata, monetization, refusal artifacts, and correction artifacts.
**Non-scope:** domain expert adjudication, model-router implementation, content runner implementation, public fanout implementation, or YouTube writes.

## Purpose

Hapax runs grounding attempts, not expert-system verdicts.

Autonomous content programming can rank, compare, classify, react, refuse,
correct, and explain only as bounded evidence-bearing attempts. The gate defined
here is the shared contract every downstream content surface consumes before it
turns a programme move into a claim, caption, chapter, public event, metadata
line, monetization candidate, or artifact.

The gate is conservative. It may structure, block, downgrade, route, and record
a grounding attempt. It may not emit hidden expertise or authoritative domain
judgments. In other words, authoritative domain judgments are outside the gate's
authority. A rule can say "this claim lacks fresh evidence"; it cannot say "this
topic is definitively true" unless that exact claim is bound to evidence,
uncertainty, freshness, scope, and a correction path.

## Machine-Readable Contract

The schema seed lives at:

- `schemas/grounding-commitment-gate.schema.json`

Required top-level fields:

| Field | Meaning |
|---|---|
| `schema_version` | Gate schema version. Initial value is `1`. |
| `gate_id` | Stable idempotency key for this gate evaluation. |
| `evaluated_at` | UTC timestamp when the gate decision was made. |
| `producer` | Component that evaluated the gate. |
| `programme_id` | Programme arc id, or `null`. |
| `format_id` | Content programme format id, or `null`. |
| `run_id` | Content programme run id, or `null`. |
| `public_private_mode` | Whether the attempt is private, dry-run, public-live, public-archive, or public-monetizable. |
| `grounding_question` | The explicit question the programme is trying to ground. |
| `permitted_claim_shape` | The allowed claim kind, scope, verbs, and authority ceiling. |
| `claim` | Evidence-bound claim envelope with provenance, confidence/posterior, uncertainty, scope limit, freshness, and correction path. |
| `infractions` | Forbidden grounding infractions observed in the attempt. |
| `gate_state` | Final gate state: pass, fail, dry-run, private-only, refusal, or correction-required. |
| `gate_result` | Machine-readable downstream decisions for claim/publication/refusal/correction. |
| `no_expert_system_policy` | Explicit assertion that rules gate attempts but do not emit authority. |
| `downstream` | Surface-ready booleans and refs for format registry, opportunity model, evaluator, runner, public events, captions, chapters, metadata, and monetization. |

Example result:

```json
{
  "schema_version": 1,
  "gate_id": "grounding_gate_20260429t013000z_tierlist_a",
  "evaluated_at": "2026-04-29T01:30:00Z",
  "producer": "content_programming_grounding_gate",
  "programme_id": "programme_tierlist_models_20260429",
  "format_id": "tier_list",
  "run_id": "run_20260429_models_a",
  "public_private_mode": "dry_run",
  "grounding_question": "Which model routes can Hapax currently justify for source-acquiring grounding work?",
  "permitted_claim_shape": {
    "claim_kind": "ranking",
    "authority_ceiling": "evidence_bound",
    "allowed_verbs": ["observed", "ranked", "compared", "refused", "corrected"],
    "forbidden_verbs": ["proved", "certified", "diagnosed", "guaranteed"],
    "scope_limit": "Ranks only currently observed provider evidence and local route configuration."
  },
  "claim": {
    "claim_text": "OpenAI, Anthropic, Gemini, and Perplexity are source-acquiring provider candidates; Command-R is local supplied-evidence grounding.",
    "evidence_refs": [
      "source:openai_web_search_docs",
      "source:anthropic_web_search_docs",
      "source:gemini_google_search_docs",
      "local:/home/hapax/llm-stack/litellm-config.yaml"
    ],
    "provenance": {
      "producer": "cx-amber",
      "source_refs": ["openai_web_search_docs", "anthropic_web_search_docs", "gemini_google_search_docs"],
      "model_id": "claude-sonnet-4-6",
      "tool_id": "manual_research",
      "retrieved_at": "2026-04-29T01:20:00Z"
    },
    "confidence": {
      "kind": "posterior",
      "value": 0.78,
      "label": "medium_high"
    },
    "uncertainty": "Provider availability and exact account entitlements still require live smoke tests.",
    "scope_limit": "This is a routing recommendation, not a truth guarantee.",
    "freshness": {
      "status": "fresh",
      "checked_at": "2026-04-29T01:20:00Z",
      "age_s": 600,
      "ttl_s": 86400
    },
    "rights_state": "operator_original",
    "privacy_state": "public_safe",
    "public_private_mode": "dry_run",
    "refusal_correction_path": {
      "refusal_reason": null,
      "correction_event_ref": null,
      "artifact_ref": "grounding_gate_20260429t013000z_tierlist_a"
    }
  },
  "infractions": [],
  "gate_state": "dry_run",
  "gate_result": {
    "may_emit_claim": true,
    "may_publish_live": false,
    "may_publish_archive": true,
    "may_monetize": false,
    "must_emit_refusal_artifact": false,
    "must_emit_correction_artifact": false,
    "blockers": ["dry_run_until_provider_smoke"],
    "unavailable_reasons": ["live_provider_smoke_missing"]
  },
  "no_expert_system_policy": {
    "rules_may_gate_and_structure_attempts": true,
    "authoritative_verdict_allowed": false,
    "verdict_requires_evidence_bound_claim": true,
    "latest_intelligence_default": true,
    "older_model_exception_requires_grounding_evidence": true
  },
  "downstream": {
    "format_registry_ready": true,
    "opportunity_model_ready": true,
    "format_evaluator_ready": true,
    "runner_ready": false,
    "public_event_ready": false,
    "caption_ready": false,
    "chapter_ready": true,
    "metadata_ready": false,
    "monetization_ready": false,
    "event_refs": []
  }
}
```

## Forbidden Grounding Infractions

Every gate implementation must detect these infractions by name:

| Infraction | Meaning | Required behavior |
|---|---|---|
| `unsupported_claim` | Claim has no evidence refs or source/chunk binding. | Fail or downgrade to refusal/correction artifact. |
| `hidden_expertise` | Output implies domain expertise not carried by evidence. | Fail public claim; emit no-expert-system blocker. |
| `unlabelled_uncertainty` | Claim lacks uncertainty/confidence/posterior. | Fail unless output is explicitly private draft. |
| `stale_source_claim` | Claim depends on expired source freshness. | Downgrade to dry-run or refresh sources. |
| `rights_provenance_bypass` | Claim/publication lacks rights, provenance, or attribution basis. | Block public/monetized surfaces. |
| `trend_as_truth` | Trend/popularity/currentness is treated as truth warrant. | Fail or rewrite as trend observation. |
| `false_public_live_claim` | Output says live/public surface exists or is safe when egress evidence does not support it. | Block live claim and emit correction if public copy existed. |
| `false_monetization_claim` | Output implies revenue/monetization readiness without ledger evidence. | Block monetization and emit unavailable reason. |
| `missing_grounding_question` | Format or run does not declare what is being grounded. | Block runner execution. |
| `missing_permitted_claim_shape` | Format or run does not declare allowed claim type and authority ceiling. | Block runner execution. |
| `expert_verdict_without_evidence` | System emits a final domain verdict not narrowed to evidence. | Fail and emit refusal/correction artifact. |

## Required Claim Fields

Any claim that leaves private scratch space must carry:

- `evidence_refs`: URLs, local file refs, source ids, chunk ids, public event ids, or gate refs.
- `provenance`: producer, source refs, model id, tool id, and retrieval/evaluation time.
- `confidence`: posterior or qualitative confidence label.
- `uncertainty`: explicit uncertainty or limitation text.
- `scope_limit`: what the claim does and does not cover.
- `freshness`: status, checked time, age, and TTL where applicable.
- `rights_state`: rights posture used for public/archive/monetization decisions.
- `privacy_state`: privacy posture and consent/public-safety classification.
- `refusal_correction_path`: where a blocked, corrected, or retracted claim goes.
- `public_private_mode`: private, dry-run, public-live, public-archive, or public-monetizable.

If a field is not applicable, the claim must say why. Omission is not a valid
shortcut.

## No-Expert-System Policy

Rules may:

- require evidence,
- route to source-acquiring providers,
- compare candidate evidence,
- score confidence or posterior state,
- block unsupported publication,
- force private/dry-run mode,
- emit refusal/correction artifacts,
- update downstream Bayesian priors from observed outcomes.

Rules may not:

- become a hidden domain authority,
- emit unbounded expert verdicts,
- convert popularity, trend, or currentness into truth,
- claim monetization or public-live state without source evidence,
- bypass rights, provenance, privacy, consent, or freshness checks,
- hide uncertainty because the format would be more entertaining without it.

## Programme Format And Run Requirements

Every `ContentProgrammeFormat` and `ContentProgrammeRun` must declare:

1. `grounding_question`
2. `permitted_claim_shape.claim_kind`
3. `permitted_claim_shape.authority_ceiling`
4. required evidence classes
5. public/private mode
6. rights and provenance requirements
7. confidence/posterior output shape
8. refusal/correction behavior

Recognizable formats remain allowed and encouraged. Tier lists, brackets,
reviews, react/commentary, watch-alongs, explainers, rundowns, rankings, claim
audits, refusal breakdowns, and failure autopsies become scientific attempts
only when their allowed claim shape is explicit.

## Refusal And Correction Artifacts

Blocked attempts are not silent skips. When public-safe, the gate should emit a
refusal, correction, or failure artifact with:

- gate id,
- blocked claim text or claim summary,
- infraction names,
- missing evidence,
- public/private mode,
- correction path,
- downstream surfaces denied,
- replay/archive eligibility.

If public emission is unsafe, the artifact remains private but still updates the
run store, evaluator, opportunity model, and audit trail.

## Latest-Model Policy

Intelligence is premium in this system.

For cloud routes, the latest/highest-intelligence generally available model is
the default. Older, cheaper, or lower-intelligence models require a
grounding-network exception record with:

- route id,
- older model id,
- latest model id considered,
- reason for exception,
- evidence that the exception improves the route,
- scope,
- expiry,
- owner.

Valid exception reasons include latency, reliability, privacy/locality, cost
containment under a declared budget, or a demonstrated grounding-quality
regression. The exception must be evidence-bearing. Habit, stale config, and
"good enough" are not reasons.

The current local Command-R director route is an exception because prior
grounding evidence selected it for grounded output behavior over raw G-IQ. That
exception remains scoped to local supplied-evidence/director work and must be
re-evaluated by the grounding-provider eval harness before any broader use.

## Downstream Machine-Readable Outputs

The gate result must be consumable by:

- content format registry,
- Bayesian opportunity model,
- input source registry,
- format grounding evaluator,
- content programme runner,
- programme boundary events,
- `ResearchVehiclePublicEvent`,
- captions,
- chapters,
- YouTube metadata,
- archive/replay,
- monetization readiness,
- conversion broker.

Downstream systems consume the gate result; they do not re-invent the policy.
If the gate says private-only, dry-run, refusal, or correction-required, public
adapters must carry that state forward instead of silently dropping it.

## Acceptance Pin

This spec is complete only if:

- all forbidden infractions are named in the schema and spec,
- every required claim field is present in the schema,
- no-expert-system policy is explicit,
- programme formats/runs require grounding questions and permitted claim shape,
- refusal/correction artifacts are specified,
- downstream surfaces are machine-readable,
- latest-model default and grounded exceptions are pinned.
