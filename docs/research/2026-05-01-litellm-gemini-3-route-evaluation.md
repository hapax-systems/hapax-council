---
type: research-evaluation
title: LiteLLM Gemini 3 Route Evaluation
date: 2026-05-01
status: recommendation-ready
owner: gamma
train: codex-gemini-sidecar-2026-04-29
parent_audit: ~/Documents/Personal/20-projects/hapax-research/audits/2026-04-29-codex-gemini-cli-sidecar-policy.md
sources:
  - https://ai.google.dev/gemini-api/docs/models
  - https://ai.google.dev/gemini-api/docs/gemini-3
  - https://ai.google.dev/pricing
  - shared/config.py (MODELS dict)
---

# LiteLLM Gemini 3 Route Evaluation

Closes the recommendation half of cc-task `litellm-gemini-3-route-evaluation`.
Smoke verification is a separate operator-action — see §6.

## 1. Question

Should the Hapax runtime LiteLLM `MODELS` dict (`shared/config.py:93-101`)
add or migrate to any of the Gemini 3 family aliases —
`gemini-3-flash-preview`, `gemini-3.1-flash-lite-preview`,
`gemini-3.1-pro-preview` — separately from the Codex Gemini CLI sidecar
policy already shipped under
`docs/governance/cross-agent-audit.md`?

## 2. Current state

`shared/config.py:93-101`:

```python
MODELS: dict[str, str] = {
    "fast": "gemini-flash",
    "balanced": "claude-sonnet",
    "long-context": "gemini-flash",
    "reasoning": "reasoning",
    "coding": "coding",
    "local-fast": "local-fast",
    "local-research-instruct": "local-research-instruct",
}
```

`gemini-flash` resolves through the council LiteLLM proxy (port 4000) to
gemini-2.5-flash on the Google AI Studio API key path. `reasoning` and
`coding` resolve to the local TabbyAPI Command-R 35B EXL3.

## 3. Gemini 3 family availability (2026-04-29 currentness)

Per the parent audit's official-doc citations:

| Model ID | Context | Free API tier | Notes |
| --- | --- | --- | --- |
| `gemini-3.1-pro-preview` | 1M / 64k | NO | Currently rolling out; check via Gemini CLI `/model`. |
| `gemini-3-flash-preview` | 1M / 64k | YES | Latest Flash generation. |
| `gemini-3.1-flash-lite-preview` | 1M / 64k | YES | Cheapest tier; designed for high-volume extraction. |
| `gemini-3-pro-preview` | — | — | Shut down on 2026-03-09. Do not target. |

The Gemini 3 family thus offers two free-tier candidates
(`gemini-3-flash-preview` and `gemini-3.1-flash-lite-preview`) and one
paid-only candidate (`gemini-3.1-pro-preview`).

## 4. Quota & billing surface (per role)

The Gemini CLI quota-and-pricing docs distinguish four quota surfaces
that the audit pinned:

- **Google AI Pro / Ultra** — subscription-tier quotas attached to the
  CLI; not API-key-driven; not visible to LiteLLM.
- **Code Assist** — OAuth-flow CLI quota; also not LiteLLM-visible.
- **API key (Google AI Studio)** — what LiteLLM uses when a
  `GEMINI_API_KEY` is configured; this is the path Hapax runtime LLM
  calls go through.
- **Vertex AI** — Google Cloud route; LiteLLM can target via
  `vertex_ai/<model>` provider prefix; requires a billing-enabled GCP
  project + service-account credentials.

For Hapax, the relevant quota is **API key (Google AI Studio)**:

- Gemini 2.5 Flash + 2.0 Flash + the two Gemini 3 free-tier models
  share the same free-tier RPM/TPM/RPD allocation.
- `gemini-3.1-pro-preview` has no free tier; calling it via the API key
  path requires a billing-enabled paid tier and incurs charges per the
  ai.google.dev/pricing page.

CLI Ultra/Pro quotas do not transfer; running through LiteLLM is the
API-key-billing path regardless of how many CLI quotas the operator's
account has.

## 5. Recommendations (per role)

### `fast` — primary recommendation: ADD `gemini-3-flash-preview` as alternate alias `fast-3`; defer migration

- Current: `gemini-flash` (gemini-2.5-flash on API-key tier).
- New `MODELS["fast-3"] = "gemini-3-flash-preview"` lets adoption be
  opt-in per call site.
- **Do not migrate `MODELS["fast"]` until smoke + 14-day observability
  shows 3-flash latency p95 ≤ current 2.5-flash p95** under the same
  prompt mix.
- Rationale: Gemini 3 Flash is in *preview* per official docs; preview
  models can be deprecated faster than GA models. Keeping `fast`
  pointing at the GA route reduces availability risk for the
  reactive engine and stimmung modulation paths that route through
  `get_model("fast")`.

### `long-context` — primary recommendation: ADD `long-context-3`; defer migration

- Current: `gemini-flash` (gemini-2.5-flash; 1M context).
- Both Gemini 3 Flash and 3.1 Flash-Lite carry 1M context.
- Same conservative posture as `fast`: add the alternate alias, defer
  migration until smoke + observability prove parity.

### NEW `extraction` and `scouting` roles — ADD pointing at `gemini-3.1-flash-lite-preview`

- The parent audit explicitly recommends Flash-Lite for *"lower-risk
  extraction and scouting"*.
- Add two new aliases:
  - `MODELS["extraction"] = "gemini-3.1-flash-lite-preview"` for
    structured-output extraction across vault notes, RAG ingest, etc.
  - `MODELS["scouting"] = "gemini-3.1-flash-lite-preview"` for
    web-currentness scouting (typically routed through Gemini CLI
    sidecar today, but a LiteLLM path lets agents call it
    programmatically).
- Both roles are NEW — they do not displace any existing route.

### Pro / `reasoning` / `balanced` — NO CHANGE

- `gemini-3.1-pro-preview` is paid-only; the Codex sidecar already
  uses it via the CLI under that audit's policy. Adding a LiteLLM
  route would create a parallel paid path that bypasses the sidecar's
  read-only guardrails. Out of scope for this evaluation.
- `balanced` (Claude Sonnet), `reasoning`/`coding` (local TabbyAPI
  Command-R) are unaffected by this change.

### Fallback semantics for the new aliases

Adopting the new aliases requires `get_model_adaptive` to know how to
degrade them under stimmung pressure. Recommended additions to the
existing degradation map (`shared/config.py:156-167`):

```python
# Stimmung resource-pressure degradation:
downgraded = {
    "balanced": "fast",
    "fast": "local-fast",
    "fast-3": "fast",                 # NEW
    "long-context-3": "long-context", # NEW
    "extraction": "fast-3",           # NEW
    "scouting": "fast-3",             # NEW
    "reasoning": "local-fast",
}
```

Error semantics:

- **Capacity / rate limit (429)**: LiteLLM already retries with
  exponential backoff; the agent-side path falls through to the
  degradation map.
- **Model-not-found (404)**: bubble up to caller. Do NOT silently
  retry on a different alias — that would mask deprecation events.
- **Auth failure (401)**: bubble up; this indicates a misconfigured
  `GEMINI_API_KEY` or expired billing tier and the operator must fix
  it.

## 6. Verification plan (operator action)

Smoke script: `scripts/smoke-litellm-gemini-3.py`. Operator runs:

```bash
LITELLM_API_KEY=$(pass show hapax/litellm-api-key) \
  uv run python scripts/smoke-litellm-gemini-3.py
```

Expected output (success):

```
gemini-3-flash-preview: OK (latency=NNNms)
gemini-3.1-flash-lite-preview: OK (latency=NNNms)
gemini-3.1-pro-preview: OK (latency=NNNms)  # only if paid tier active
```

Expected output (failure modes):

```
gemini-3-flash-preview: ERR <status> <body-snippet>
```

The script never prints the API key. It uses the standard LiteLLM
client through `shared.config.get_model(...)` so it exercises the same
provider path the runtime uses.

## 7. Cost / quota implications

| Alias change | Free-tier impact | Paid impact |
| --- | --- | --- |
| ADD `fast-3` | Shares the API-key free tier with existing 2.5-flash. | None; same free quota pool. |
| ADD `long-context-3` | Same as above (Gemini 3 Flash). | None. |
| ADD `extraction`/`scouting` | Pulls from the same Flash-Lite free quota pool. | None. |
| MIGRATE `fast` → 3-flash-preview (DEFERRED) | Same pool. | None — until preview deprecates and forces migration. |
| ADD any Pro alias | N/A — not free-tier. | Pay-per-token at ai.google.dev/pricing. **Out of scope.** |

The free-tier RPM/TPM ceilings are shared across the Gemini 2 + 3 API
key path; adding the new routes does not unlock additional quota.

## 8. Decision summary

**Adopted (Phase A — substrate, this PR):**

- ADD `MODELS["fast-3"] = "gemini-3-flash-preview"`.
- ADD `MODELS["long-context-3"] = "gemini-3-flash-preview"`.
- ADD `MODELS["extraction"] = "gemini-3.1-flash-lite-preview"`.
- ADD `MODELS["scouting"] = "gemini-3.1-flash-lite-preview"`.
- Add the four new aliases to the `get_model_adaptive` degradation
  map.
- Ship `scripts/smoke-litellm-gemini-3.py` for operator verification.

**Deferred (Phase B — operator action + observability):**

- Operator runs the smoke script to confirm availability.
- Operator runs the four new aliases through one tick of representative
  agents (sync_agent, frontmatter_extractor, scouting tools).
- After 14 days of observability with no preview-deprecation events, a
  follow-up PR migrates `MODELS["fast"]` and `MODELS["long-context"]`
  to the Gemini 3 Flash route.

**Not adopted:**

- No `MODELS["pro-3"]` or any Gemini 3.1 Pro route. The Codex sidecar
  policy is the canonical surface for Pro-tier use.
- No migration of `reasoning` / `coding` / `local-fast` / `balanced`
  routes. The audit explicitly says do not disturb Command-R / local
  routes unless evidence says they should move; this evaluation
  produced no such evidence.

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| Preview-tier deprecation faster than GA | Phase A only ADDs aliases, doesn't migrate. Migration path is gated on observed parity. |
| Free-tier quota exhaustion when 4 new aliases share the pool | Existing `get_model_adaptive` degrades to local Command-R at high resource pressure. |
| Vertex AI route divergence | Out of scope; the API-key path is the LiteLLM truth. Vertex would require a separate evaluation + service-account credential bootstrap. |
| Paid Pro charges via accidental alias use | Phase A intentionally does not add a Pro alias. The Codex sidecar boundary remains the only paid Pro surface. |

## 10. Closure evidence

- Recommendation document: this file.
- Smoke script: `scripts/smoke-litellm-gemini-3.py`.
- Smoke-script tests: `tests/scripts/test_smoke_litellm_gemini_3.py`.
- `shared/config.py` MODELS additions + degradation-map updates.
