---
Status: ready-for-implementation-dispatch
Task: obsidian-task:perplexity-litellm-wiring
Date: 2026-05-15
Scope: LiteLLM route configuration, shared/config.py model aliases, grounding-providers.json model expansion, grounding adapter implementation, research agent web search tools, cost tracking, Claude Code delegation rules
Non-scope: pplx-embed embeddings (nomic-embed-cpu sufficient), Agent API presets (redundant with direct model routing), Perplexity Pro subscription management, director model swap to Perplexity, MCP tool exposure (deferred to later spec)
---

# Perplexity API Integration

## Purpose

Wire Perplexity's search-grounded LLM API into the Hapax stack as a first-class
grounding provider, filling the research agent's web search gap and enabling
citation-backed evidence envelopes for CHI 2027 publication work.

## Inputs Consumed

- [Grounding Provider Model Router Eval Harness Design](2026-04-29-grounding-provider-model-router-eval-harness-design.md)
- [LiteLLM Gemini 3 Route Evaluation](../research/2026-05-01-litellm-gemini-3-route-evaluation.md)
- [LiteLLM Config Audit](../research/2026-04-14-litellm-config-audit.md)
- [Perplexity API docs](https://docs.perplexity.ai)
- Existing provider registry: `config/grounding-providers.json`
- Existing router: `shared/grounding_provider_router.py`

## Design

### Provider Positioning

Perplexity occupies a distinct niche among the 6 declared grounding providers:

| Provider | Best For | Limitation |
|---|---|---|
| Command-R (local) | Source-conditioned private drafts | Cannot acquire sources |
| OpenAI web_search | In-session GPT grounding | Tied to OpenAI models |
| Anthropic web_search | In-session Claude grounding | Tied to Claude models |
| Gemini Google Search | Google-specific grounding | Google index only |
| Gemini Deep Research | Long async background research | Slow turnaround |
| **Perplexity (sonar)** | **Provider-neutral web search, fast scouting, citation-heavy research** | **Cloud-only, no image/video perception** |

Perplexity is the only provider that combines dedicated search infrastructure
with model-agnostic web grounding and per-response cost transparency.

### Model Routes

Four models, each mapped to a semantic alias in `shared/config.py`:

| Alias | Perplexity Model | Context | In/Out $/1M | Role |
|---|---|---|---|---|
| `web-scout` | `sonar` | 128K | $1/$1 | Fast factual lookups, current-event claims, scouting |
| `web-research` | `sonar-pro` | 200K | $3/$15 | Multi-source investigation, large-context synthesis |
| `web-reason` | `sonar-reasoning-pro` | 128K | $2/$8 | Chain-of-thought + search, claim cross-verification |
| `web-deep` | `sonar-deep-research` | 128K | $2/$8+extras | Multi-step exhaustive research, systematic reviews |

Not adopted: pplx-embed (nomic-embed-cpu handles local embedding), Agent API
presets (we route our own models and don't need Perplexity to orchestrate
GPT/Claude on our behalf).

### LiteLLM Route Configuration

LiteLLM supports Perplexity natively via the `perplexity/` model prefix and
OpenAI-compatible endpoint at `https://api.perplexity.ai`.

```yaml
# litellm-config.yaml additions
- model_name: web-scout
  litellm_params:
    model: perplexity/sonar
    api_key: os.environ/PERPLEXITY_API_KEY

- model_name: web-research
  litellm_params:
    model: perplexity/sonar-pro
    api_key: os.environ/PERPLEXITY_API_KEY

- model_name: web-reason
  litellm_params:
    model: perplexity/sonar-reasoning-pro
    api_key: os.environ/PERPLEXITY_API_KEY

- model_name: web-deep
  litellm_params:
    model: perplexity/sonar-deep-research
    api_key: os.environ/PERPLEXITY_API_KEY
```

### Degradation Paths

Under stimmung cost/resource pressure, Perplexity aliases degrade:

```
web-deep   → web-research → web-scout → balanced (Claude fallback)
web-reason → web-scout    → balanced
web-research → web-scout  → balanced
web-scout  → balanced     → fast (Gemini Flash)
```

This follows the existing `get_model_adaptive()` pattern in `shared/config.py`.

### Secrets Wiring

API key path: `pass perplexity/api-key` → `.envrc` export → LiteLLM container
environment variable `PERPLEXITY_API_KEY`.

```bash
# .envrc addition
export PERPLEXITY_API_KEY=$(pass perplexity/api-key)
```

LiteLLM container picks up the key via `os.environ/PERPLEXITY_API_KEY` in the
model route config (same pattern as `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`).

### Provider Registry Expansion

The existing `perplexity_search_or_sonar` entry in `grounding-providers.json`
covers only `sonar`. Expand to reflect full model coverage:

- Update `model_id` to reflect the primary routing model (`sonar` for scouting)
- Add `available_models` field listing all 4 models with their semantic roles
- Add `search_parameters` documenting `search_domain_filter`,
  `search_recency_filter`, `return_citations`, `search_context_size`
- Capabilities list gains: `search_domain_filtering`, `search_recency_filtering`,
  `per_response_cost_transparency`, `deep_multi_step_research`

### Grounding Adapter

New file: `shared/grounding_adapters/perplexity.py`

Responsibilities:
1. Accept a claim request + search parameters (domains, recency, context size)
2. Route to appropriate Perplexity model via LiteLLM
3. Normalize the response into the evidence envelope:
   - `citations` ← Perplexity `citations` array (URL list)
   - `source_items` ← constructed from citation URLs + response text
   - `raw_source_hashes` ← SHA-256 of each citation URL + retrieved content
   - `freshness` ← derived from `search_recency_filter` + response timestamp
   - `retrieved_at` ← response timestamp (ISO 8601)
   - `confidence_or_posterior` ← model's stated confidence or 0.5 default
   - `refusal_or_uncertainty` ← detected from response content
   - `tool_errors` ← HTTP errors, rate limits, empty results
4. Extract `request_cost` and `total_cost` from response metadata → feed to
   cost tracking
5. Privacy egress preflight (already required per registry)

### Research Agent Web Search Tools

Two new tools for `agents/research.py`:

**`search_web(ctx, query: str, recency: str | None, domains: list[str] | None) → str`**
- Routes to `web-scout` via LiteLLM
- Passes `search_domain_filter` and `search_recency_filter` as extra params
- Returns grounded answer with inline citations
- Injects `return_citations: true` on every call

**`deep_research(ctx, question: str, domains: list[str] | None) → str`**
- Routes to `web-deep` via LiteLLM
- Returns comprehensive multi-source report with full citation list
- Higher cost — gated behind working mode check (skip in `fortress`)

### Claude Code Delegation Rules

Addition to workspace CLAUDE.md:

```
## Perplexity Delegation

Use Perplexity (via `web-scout`/`web-research` LiteLLM aliases) when:
- Real-time web search for current-event grounding
- Literature scouting for CHI 2027 or other publications
- Citation-backed fact-checking with URL sources
- Technology/model/vendor comparison requiring current data
- Content opportunity discovery across diverse web sources

Use Gemini instead when:
- Long-doc / image / video perception (Perplexity has no multimodal)
- Google-specific search grounding
- OCR / scanned document parsing

Mandatory: after every Perplexity call, check response for 429/rate-limit
signals. Surface immediately to operator if hit.
```

### Cost Tracking

Perplexity returns `total_cost` in every API response. Integration points:

1. LiteLLM Langfuse callback already captures response metadata — verify
   Perplexity cost fields flow through
2. Prometheus metrics: add `perplexity_request_cost_total` counter
3. `/cost` logos API endpoint: aggregate Perplexity spend alongside existing
   providers
4. Daily briefing: include Perplexity spend line item

Estimated cost at research-mode usage (~50 queries/day):
- 40× sonar: ~$0.08/day
- 8× sonar-pro: ~$0.16/day
- 2× sonar-deep: ~$0.20/day
- Total: ~$0.44/day, ~$13/month (well within $50/30d budget cap)

### Axiom Compliance

| Axiom | Weight | Assessment |
|---|---|---|
| `single_user` | 100 | ✅ No multi-user concerns. Single API key, single operator. |
| `executive_function` | 95 | ✅ Zero-config after wiring. Errors include next actions via tool_errors field. |
| `corporate_boundary` | 90 | ✅ Research data only — no employer data transits. Egress preflight required. |
| `interpersonal_transparency` | 88 | ✅ No person data sent to Perplexity. Consent gate at egress preflight. |
| `management_governance` | 85 | ✅ Perplexity outputs are grounding material, not decisions. LLMs prepare. |

### Error Semantics

Following the LiteLLM Gemini 3 evaluation pattern:

| Error | Behavior |
|---|---|
| 429 (rate limit) | Auto-retry with backoff (LiteLLM handles). Surface to operator if persistent. |
| 401 (auth failure) | Bubble up. API key invalid or expired. |
| 404 (model not found) | Bubble up. No silent retry on wrong model ID. |
| Empty citations | Treat as low-confidence result. Set `source_quality: "none"`. |
| Timeout | Degrade to next model in chain. Log tool_error. |

## Downstream Contracts

- `agents/research.py` consumes `search_web` and `deep_research` tools
  conservatively — results are evidence, not truth
- Grounding eval harness consumes evidence envelopes for scoring
- `/cost` endpoint consumes per-response cost data
- `get_model_adaptive()` consumes degradation paths under stimmung pressure
- SWH attribution pipeline consumes Perplexity citation URLs for deposit

## Verification Plan

1. Smoke test: `curl` to LiteLLM with `web-scout` model, verify grounded response
2. Evidence envelope: adapter produces valid 17-field envelope from Perplexity response
3. Cost tracking: `total_cost` from response appears in Langfuse trace
4. Degradation: simulate stimmung pressure, verify `web-deep → web-scout → balanced`
5. Domain filtering: `search_domain_filter: ["arxiv.org"]` restricts sources
6. Recency filtering: `search_recency_filter: "week"` returns only recent sources
7. Privacy egress: preflight blocks when redaction fails
