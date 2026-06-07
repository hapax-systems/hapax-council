# CCTV Platform Routing and Cache Policy

Status: operational runbook
Last verified: 2026-06-04
Authority: CASE-DELIBERATIVE-COUNCIL-20260515, CASE-CAPACITY-ROUTING-001

This runbook covers CCTV deliberative-council runs, including intake,
research assessment, disconfirmation, audit, rubric validation, and benchmark
ablation.

## Route Freshness

CCTV code must default to `CouncilConfig` model aliases and must not pin
provider model IDs inside runner scripts. The canonical source route set is:

| CCTV alias | LiteLLM route | Provider family | Current cache policy |
| --- | --- | --- | --- |
| `opus` | `claude-opus` | Anthropic | `cache_control` breakpoint |
| `balanced` | `claude-sonnet` | Anthropic | `cache_control` breakpoint |
| `gemini-3-pro` | `gemini-pro` | Google | `cache_control` breakpoint via LiteLLM |
| `local-fast` | `local-fast` | local/OpenAI-compatible | no provider prompt-cache marker |
| `web-research` | `web-research` | Perplexity | no provider prompt-cache marker |
| `mistral-large` | `mistral-large` | Mistral | no provider prompt-cache marker |

Live provider model IDs are route evidence in
`/home/hapax/llm-stack/litellm-config.yaml`, not CCTV source constants. Before
high-spend or benchmark CCTV runs, inspect that file and compare cloud route
targets against current provider docs. If a route is stale, create a governed
runtime/provider-spend cc-task before changing the gateway.

## Critical SDLC Availability

CCTV is critical SDLC infrastructure. It must not be degraded solely because a
Claude Code subscription lane is quota-dry. Claude Code subscription quota is a
lane-dispatch capacity signal, not evidence that Anthropic/Google API routes or
LiteLLM gateway aliases are unavailable.

The only quota/capacity blockers that may degrade or hold CCTV are actual paid
API budget exhaustion, provider-side quota/rate-limit evidence for the selected
API route, or gateway health/config evidence that the route is not dispatchable.
When provider auto-reload is enabled, provider quota interruptions should
normally be recorded as transient hold/retry evidence, then retried on the
frontier API route. Do not silently substitute a lower-capability model family
for CCTV unless the cc-task's quality floor and route evidence explicitly permit
that degradation.

2026-06-04 audit note: Google Gemini API docs list Gemini 3.1 Pro Preview and
Gemini 3.5 Flash Stable in the current Gemini 3 line, and list Gemini 3 Pro
Preview under previous/shut-down models. The live gateway still mapped
`gemini-pro` to `gemini/gemini-3-pro-preview` and `gemini-flash`/`fast` to
`gemini/gemini-3-flash-preview`. The follow-up task
`litellm-gemini-current-route-refresh-20260604` records the required refresh,
but dispatcher policy refused both `runtime` and `provider_spend` mutation
surfaces for every registered platform route, so the live config was not
changed in the CCTV source PR.

2026-06-04 gateway refresh note: after provider-gateway route evidence and the
quota/spend ledger were accepted, `litellm-gemini-current-route-refresh-20260604`
updated live LiteLLM routes so `gemini-pro` targets
`gemini/gemini-3.1-pro-preview`, while `gemini-flash` and `fast` target
`gemini/gemini-3.5-flash`. Validation: YAML parse passed, `docker compose
--profile core config --quiet` accepted the stack, LiteLLM restarted with
readiness HTTP 200, `/v1/models` exposed `gemini-pro`, `gemini-flash`, and
`fast`, and bounded smoke calls returned HTTP 200 with `gemini-flash` producing
`ok.` and `gemini-pro` producing `ok` with visible reasoning-token usage.

2026-06-04 Anthropic audit note: Claude model docs list Claude Opus 4.8,
Claude Sonnet 4.6, and Claude Haiku 4.5 as the current main Claude model line.
The live gateway already maps `claude-sonnet`/`balanced` to
`anthropic/claude-sonnet-4-6` and `claude-haiku` to
`anthropic/claude-haiku-4-5-20251001`, but still maps `claude-opus` to
`anthropic/claude-opus-4-7`. The follow-up task
`litellm-anthropic-current-route-refresh-20260604` records the required Opus
route refresh. Do not update the live gateway under this CCTV source PR.

2026-06-04 Anthropic gateway refresh note:
`litellm-anthropic-current-route-refresh-20260604` updated live LiteLLM routes
so `claude-opus` and the new full-name `claude-opus-4-8` route target
`anthropic/claude-opus-4-8`. The legacy full-name `claude-opus-4-7` route is
retained as an explicit compatibility alias that also targets current Opus 4.8.
Validation: YAML parse passed, `docker compose --profile core config --quiet`
accepted the stack, LiteLLM restarted with readiness HTTP 200, `/v1/models`
exposed `claude-opus`, `claude-opus-4-8`, and `claude-opus-4-7`, and a bounded
`claude-opus` smoke call returned HTTP 200 with `ok`.

## Prompt Caching

CCTV prompts must put stable instructions, rubric text, and stable examples at
the beginning of the prompt. Per-claim text, source references, and fresh
research findings must remain after the cache breakpoint.

Provider behavior:

- Anthropic Claude: use an ephemeral `cache_control` breakpoint on the final
  stable content block. Supported TTL settings are `5m` and `1h`; default CCTV
  TTL is `5m` via `HAPAX_CCTV_PROMPT_CACHE_TTL`.
- Google Gemini through LiteLLM: use the same OpenAI-compatible content-block
  `cache_control` shape for Gemini routes, but emit Gemini TTLs in seconds
  (`300s` for the `5m` CCTV setting and `3600s` for `1h`). Gemini also has
  native explicit cached-content resources outside this Pydantic AI/LiteLLM
  path.
- OpenAI API routes, if added to CCTV: pass `openai_prompt_cache_key` and
  `openai_prompt_cache_retention` through Pydantic AI model settings. OpenAI
  API prompt caching is prefix-based and automatic for supported recent models;
  `prompt_cache_key`/retention improve routing and retention, not block-level
  cache placement.
- Codex CLI/app: current Codex product documentation exposes cached input token
  accounting and several local/container/web caches, but no user-tunable
  prompt-cache control equivalent to API `prompt_cache_key` or Claude
  `cache_control`. Do not invent a Codex prompt-cache setting for CCTV.
- Local, Perplexity, and Mistral routes: do not attach provider prompt-cache
  controls unless current provider docs and the gateway path prove support.

CCTV receipts should expose each alias' cache policy so future route additions
make unknown cache semantics visible in tests and run artifacts.

## Ultracode Escalation

Claude Code ultracode is a workflow, not a source-level API in this repository.
Use it as CCTV's default escalation pattern when the question is systemic,
high-ambiguity, or cross-surface enough that a single lane is likely to produce
an incomplete patch.

Trigger ultracode for:

- SDLC, dispatch, clog, migration, provider-routing, quota, or lane-recovery
  work where the failure may span multiple subsystems.
- CCTV findings that identify possible false completion, stale evidence,
  broken route authority, or contradictory live/runtime state.
- Any CCTV research question whose answer will drive provider spend, runtime
  mutation, or governance-policy change.

The expected ultracode shape is read-only multi-agent diagnosis, root-cause
synthesis, adversarial verification, then governed cc-tasks for any mutation.
Do not let ultracode output directly mutate source or runtime state. It is
intake and evidence; implementation still goes through task authority,
dispatch, claim, quality gates, and PR/runtime release gates.

## References

- Anthropic Claude prompt caching:
  https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Anthropic Claude models:
  https://platform.claude.com/docs/en/docs/about-claude/models
- OpenAI API prompt caching:
  https://developers.openai.com/api/docs/guides/prompt-caching
- Gemini API models and context caching:
  https://ai.google.dev/gemini-api/docs/models
  https://ai.google.dev/gemini-api/docs/caching
- LiteLLM prompt caching:
  https://docs.litellm.ai/docs/completion/prompt_caching
- Local ultracode precedent:
  `/home/hapax/Documents/Personal/30-areas/hapax/baseline-recovery-plan-2026-06-03.md`
