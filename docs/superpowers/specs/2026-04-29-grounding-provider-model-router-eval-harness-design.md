# Grounding Provider Model Router And Eval Harness - Design Spec

**Status:** first implementation seed for `grounding-provider-model-router-eval-harness`
**Task:** `obsidian-task:grounding-provider-model-router-eval-harness`
**Date:** 2026-04-29
**Scope:** provider registry, routing policy, evidence envelope, eval-suite registry, replayable eval artifact shell, and deterministic validators.
**Non-scope:** live API calls, account entitlement checks, prompt optimization, director model replacement, public runner enablement, or cost-controller implementation.

## Purpose

Hapax needs grounding routes, not a new hidden expert system.

The local director can remain Command-R because the current evidence selects it
for source-conditioned director grounding. Open-world factual claims, current
events, model/vendor comparisons, rights/provenance claims, and public
content-programming assertions need source-acquiring providers that emit
auditable evidence. The router defined here separates those roles.

## Provider Registry

The machine-readable registry lives at:

- `config/grounding-providers.json`
- `schemas/grounding-provider-router.schema.json`

Required provider adapters:

- `local_supplied_evidence_command_r`
- `openai_web_search`
- `anthropic_web_search`
- `gemini_google_search`
- `gemini_deep_research`
- `perplexity_search_or_sonar`

Provider kinds:

| Kind | Meaning |
|---|---|
| `source_acquiring` | Provider can retrieve/search external sources and return citation/provenance material. |
| `source_conditioned` | Provider can ground output in supplied sources but must not discover open-world facts by itself. |
| `general_reasoning` | Provider may reason or generate, but does not satisfy grounding without an evidence envelope. |

## Evidence Envelope

Every accepted provider route must normalize output into these fields:

- `provider_id`
- `model_id`
- `tool_id`
- `input_claim_request`
- `retrieval_events`
- `source_items`
- `claim_items`
- `citations`
- `confidence_or_posterior`
- `source_quality`
- `freshness`
- `refusal_or_uncertainty`
- `tool_errors`
- `raw_source_hashes`
- `retrieved_at`

Missing evidence fields are blockers. Citations without source hashes or
retrieval events are not replayable enough for public claims.

## Routing Policy

The registry pins these policy constants:

- `open_world_claims_require_grounding: true`
- `latest_cloud_model_default: true`
- `older_model_exception_required: true`
- `command_r_source_supplied_only: true`
- `privacy_egress_preflight_required_for_cloud: true`
- `director_model_swap_requires_eval_pass: true`

Grounding is required for:

- `open_world_factual_claim`
- `current_event_claim`
- `knowledge_recruitment_guidance_request`
- `model_vendor_comparison`
- `rights_provenance_claim`
- `public_content_programming_assertion`

The local Command-R route is allowed only for supplied-evidence local/private
grounding and the current director substrate. It may not satisfy open-world
claims by itself.

When Hapax detects thin internal know-how in any domain, the
`knowledge_recruitment_guidance_request` claim type requires grounded guidance
recruitment before the system treats outside input as a usable prior. That
guidance remains evaluated evidence pressure only: it cannot authorize script
playback, static/default layout success, public claims, or runtime actions
without the existing downstream grounding and readback gates.

Cloud routes must require privacy/egress preflight. Older, cheaper, or
lower-intelligence cloud routes require an exception record with route scope,
reason, evidence, owner, and expiry. The local Command-R exception is documented
as `local_director_grounding_evidence`, not as a general license to downgrade
cloud research routes.

## Current Provider Facts

Current official-source checks recorded for this seed:

- OpenAI web search returns search-call actions plus URL citations; Responses
  web search supports domain filtering and `gpt-5.5` examples.
- Anthropic release notes deprecate legacy Sonnet 4 / Opus 4 API model IDs and
  recommend Sonnet 4.6 / Opus 4.7.
- Gemini Google Search returns structured grounding metadata, including search
  queries, grounding chunks, and grounding supports. Gemini 3 routes are listed
  as supported for Google Search grounding.
- Gemini Deep Research uses background interactions that can be polled or
  streamed and resumed with interaction/event ids.
- Perplexity Sonar is a web-grounded API surface with OpenAI-compatible client
  use.

These facts justify provider adapters. They do not justify public claims until
live smoke tests capture replayable artifacts.

## Eval Suite

The machine-readable eval suite lives at:

- `config/grounding-eval-suite.json`
- `schemas/grounding-eval-suite.schema.json`

The suite contains 35 items. Required categories:

- `global_competence_gap_guidance`
- `current_model_release_scouting`
- `content_opportunity_discovery`
- `tier_list_react_video_evidence_packets`
- `local_only_obsidian_facts`
- `contradicted_sources`
- `stale_documentation`
- `public_rights_provenance_claims`
- `refusal_required_prompts`
- `tool_error_surfacing`

Each eval item declares prompt, category, provider-kind eligibility, fixtures,
expected behaviors, failure modes, public-claim mode, and scoring weights.
Weights must sum to 1.

## Scoring Dimensions

Initial eval items score:

- `source_recall`
- `citation_faithfulness`
- `claim_alignment`
- `uncertainty_refusal`
- `replay_completeness`

Downstream implementations may add cost, latency, source-quality calibration,
privacy/egress pass rate, and provider-specific tool reliability, but they may
not drop the replay and refusal dimensions.

## Artifact Contract

`shared/grounding_provider_router.py` provides:

- typed provider registry loading,
- routing eligibility checks,
- provider registry validation,
- eval suite validation,
- deterministic eval artifact shell generation,
- privacy/egress preflight artifact generation for cloud routes.

`build_eval_artifact()` creates a replayable shell with:

- provider id,
- eval id,
- eval category,
- expected behaviors,
- observed fields,
- score placeholders,
- pass placeholder,
- blockers,
- deterministic `raw_hash`.

The shell is intentionally not a score oracle. Provider adoption still requires
live runs, human-readable review when needed, and downstream gating before any
public runner consumes results.

`build_privacy_egress_preflight()` is the first hook point for OpenAI Privacy
Filter or an equivalent local redaction model. Cloud routes fail closed unless a
redaction/privacy pass is recorded. Local Command-R supplied-evidence routes do
not require cloud egress preflight, but they still remain private unless another
gate promotes their artifacts.

## Downstream Contract

This harness unblocks downstream tasks only when they consume the registry and
eval artifacts conservatively:

- `trend-current-event-constraint-gate` can use source-acquiring routes for
  currentness but must still enforce freshness and sensitivity gates.
- `format-grounding-evaluator` can score citation and refusal behavior without
  treating engagement as truth.
- `content-candidate-discovery-daemon` can scout current sources, but public
  candidates remain blocked without evidence, rights, privacy, and freshness.
- `content-programming-grounding-runner` must not use cloud routes without
  egress preflight and replayable artifacts.

## Verification

Focused verification:

- JSON parse for both schemas and both configs.
- Contract tests for required provider adapters, evidence fields, routing
  policy, latest-model aliases, Command-R limitations, and eval coverage.
- Unit tests for validator behavior, routing eligibility, and deterministic eval
  artifact generation.

## Sources

- OpenAI web search docs: https://developers.openai.com/api/docs/guides/tools-web-search
- OpenAI GPT-5.5 announcement: https://openai.com/index/introducing-gpt-5-5/
- Anthropic web search docs: https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
- Anthropic release notes: https://platform.claude.com/docs/en/release-notes/overview
- Gemini Google Search grounding docs: https://ai.google.dev/gemini-api/docs/google-search
- Gemini Deep Research docs: https://ai.google.dev/gemini-api/docs/deep-research
- Perplexity Sonar docs: https://docs.perplexity.ai/docs/sonar/quickstart
