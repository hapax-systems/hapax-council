# LiteLLM config vs shared/config.py drift audit

**Date:** 2026-04-15
**Author:** alpha (AWB mode, queue/ item #113)
**Scope:** Cross-check `shared/config.py` MODELS dict + `EMBEDDING_MODEL` against the running LiteLLM proxy configuration. Verify route alignment for council (:4000) and officium (:4100 per workspace CLAUDE.md).
**Register:** scientific, neutral

## 1. Headline

**3 drift findings, 1 structural anomaly.** No blocking issues.

| # | Severity | Finding | Owner |
|---|---|---|---|
| D1 | MEDIUM | `LITELLM_BASE` default in `hapax-officium/shared/config.py` points to `http://localhost:4100`, which is not listening. Only the council LiteLLM container on :4000 is running. | officium |
| D2 | LOW | `EMBEDDING_MODEL = "nomic-embed-cpu"` duplicated in 3 files: `shared/config.py:102`, `agents/_config.py:91`, `agents/ingest.py:29`. Single source of truth would eliminate future drift risk. | council |
| D3 | LOW | LiteLLM routes `nomic-embed-text` + `nomic-embed` exist but no code calls them. All embeds use `ollama.Client` directly. These routes are dead config. | council |
| A1 | anomaly | `long-context` alias in `MODELS` dict resolves to `gemini-flash` (LiteLLM route), not a dedicated Gemini 1M-context route. | council |

MODELS dict ↔ LiteLLM route alignment for all active inference routes (`fast`, `balanced`, `local-fast`, `coding`, `reasoning`) is clean. TabbyAPI wiring is correct. No stale Ollama inference references anywhere in Python.

## 2. Method

```bash
# Council LiteLLM actual config
docker exec litellm cat /app/config.yaml > /tmp/litellm-council.yaml
grep -E "^  - model_name:" /tmp/litellm-council.yaml

# shared/config.py MODELS dict
grep -n "MODELS\|EMBEDDING_MODEL" shared/config.py

# Cross-reference
diff <(MODELS dict aliases) <(LiteLLM route names)

# Port listening check
ss -tln | grep -E "4000|4100"
curl -s http://localhost:4100/health
```

## 3. Council LiteLLM actual routes

LiteLLM container `litellm` on `127.0.0.1:4000` has **14 routes** in `/app/config.yaml`:

| # | Route name | Backend | Notes |
|---|---|---|---|
| 1 | `claude-sonnet-4-20250514` | anthropic/claude-sonnet-4-20250514 | Direct model ID |
| 2 | `claude-opus-4-20250514` | anthropic/claude-opus-4-20250514 | Direct model ID |
| 3 | `claude-haiku` | anthropic/claude-haiku-4-5-20251001 | Haiku 4.5 |
| 4 | `balanced` | anthropic/claude-sonnet-4-20250514 | Primary alias |
| 5 | `fast` | gemini/gemini-2.5-flash | Primary alias |
| 6 | `claude-sonnet` | anthropic/claude-sonnet-4-20250514 | Alias |
| 7 | `claude-opus` | anthropic/claude-opus-4-20250514 | Alias |
| 8 | `gemini-pro` | gemini/gemini-2.5-pro | Alias |
| 9 | `gemini-flash` | gemini/gemini-2.5-flash | Alias |
| 10 | `local-fast` | openai/Qwen3.5-9B-exl3-5.00bpw @ 172.18.0.1:5000 | TabbyAPI |
| 11 | `coding` | openai/Qwen3.5-9B-exl3-5.00bpw @ 172.18.0.1:5000 | TabbyAPI |
| 12 | `reasoning` | openai/Qwen3.5-9B-exl3-5.00bpw @ 172.18.0.1:5000 | TabbyAPI |
| 13 | `nomic-embed-text` | ollama/nomic-embed-cpu @ host.docker.internal:11434 | Ollama embed |
| 14 | `nomic-embed` | ollama/nomic-embed-cpu @ host.docker.internal:11434 | Ollama embed |

### 3.1 Fallback chains (per config)

```yaml
fallbacks:
  - claude-opus: [claude-sonnet, gemini-pro]
  - claude-sonnet: [gemini-pro]
  - claude-haiku: [gemini-flash]
  - reasoning: [claude-sonnet, claude-opus, gemini-pro]
  - local-fast: [gemini-flash, claude-haiku]
  - coding: [claude-sonnet, claude-opus]
```

Note the policy shift documented in the config file: `local-fast/coding/reasoning` had a `qwen3:8b` Ollama fallback, REMOVED because "Ollama qwen3:8b on CPU creates a death spiral: 900% CPU → system overload → more timeouts → more fallbacks. Agents handle TabbyAPI failures gracefully." This aligns with workspace CLAUDE.md § Shared Infrastructure: "No local model fallback chains — TabbyAPI failures degrade gracefully."

## 4. shared/config.py MODELS dict

```python
# shared/config.py:93-100
MODELS: dict[str, str] = {
    "fast": "gemini-flash",
    "balanced": "claude-sonnet",
    "long-context": "gemini-flash",  # 1M context, for prompts that exceed 200K
    "reasoning": "reasoning",
    "coding": "coding",
    "local-fast": "local-fast",
}

EMBEDDING_MODEL: str = "nomic-embed-cpu"
```

| Python alias | Resolves to | Valid LiteLLM route? |
|---|---|---|
| `fast` | `gemini-flash` | ✓ route 9 |
| `balanced` | `claude-sonnet` | ✓ route 6 |
| `long-context` | `gemini-flash` | ✓ route 9 (see A1 below) |
| `reasoning` | `reasoning` | ✓ route 12 |
| `coding` | `coding` | ✓ route 11 |
| `local-fast` | `local-fast` | ✓ route 10 |

**6/6 aliases resolve to valid LiteLLM routes.** Zero drift.

## 5. Drift finding D1 — officium LiteLLM :4100 dead

`hapax-officium/shared/config.py:17`:

```python
LITELLM_BASE: str = os.environ.get(
    "LITELLM_BASE",
    os.environ.get("LITELLM_BASE_URL", "http://localhost:4100"),
)
```

```
$ ss -tln | grep -E "4000|4100"
LISTEN 0  4096  127.0.0.1:4000  0.0.0.0:*

$ curl -s http://localhost:4100/health
(connection refused)
```

**Only :4000 is listening.** Officium's default fallback `http://localhost:4100` points to a port with no listener. The officium-api systemd service is running but has no `LITELLM_BASE` environment override in its unit (`systemctl show officium-api.service -p Environment` shows only `PATH` + `HOME`). Either:

1. Officium-api never makes LLM calls (it runs successfully without hitting LiteLLM)
2. Officium-api crashes on LLM calls at runtime
3. A runtime-set env var overrides the default (not visible from systemd unit inspection)

**Workspace CLAUDE.md states:** "LiteLLM — API gateway (:4000 council, :4100 officium), routes to Claude/Gemini/TabbyAPI." This contradicts observed runtime state. Either the CLAUDE.md is stale or the :4100 container was intentionally merged into :4000.

**Remediation options:**
- (a) Update officium's `shared/config.py` default to `http://localhost:4000` (single shared LiteLLM)
- (b) Spin up a separate `litellm-officium` container on :4100 (restores two-gateway model)
- (c) Document the single-gateway model in workspace CLAUDE.md + officium CLAUDE.md

Alpha recommends (a) + (c) — consolidating onto one LiteLLM is simpler, avoids duplicate budget/cost tracking, and matches the actual running state.

## 6. Drift finding D2 — EMBEDDING_MODEL duplicated in 3 files

```
shared/config.py:102:       EMBEDDING_MODEL: str = "nomic-embed-cpu"
agents/_config.py:91:       EMBEDDING_MODEL: str = "nomic-embed-cpu"
agents/ingest.py:29:        EMBEDDING_MODEL = "nomic-embed-cpu"
```

Three separate module-level constants, all with the same value. If any consumer changes theirs without updating the others, the agent graph will embed with inconsistent models → corrupt Qdrant collections (since embedding dims + semantic space are model-dependent).

**Recommended fix:** import `EMBEDDING_MODEL` from `shared/config` everywhere; delete the duplicates in `agents/_config.py` and `agents/ingest.py`. Small patch, high future-proofing value.

## 7. Drift finding D3 — LiteLLM embed routes are dead config

LiteLLM routes `nomic-embed-text` (route 13) and `nomic-embed` (route 14) both proxy to `ollama/nomic-embed-cpu`. **No Python code calls either of these routes via LiteLLM.**

```bash
$ grep -rn "nomic-embed\b\|nomic-embed-text" --include="*.py" .
agents/hapax_daimonion/grounding_evaluator.py:258:    # Uses nomic-embed (768-dim) cosine similarity. (comment only)
agents/health_monitor/constants.py:70:    "nomic-embed-cpu",  # health check string
agents/studio_compositor/chat_queues.py:18:    # comment only
agents/_episodic_memory.py:17:   # comment only
agents/scout.py:434:    "nomic-embed",  # This one — but it is a fact-key, not a LiteLLM call
scripts/chat-monitor.py:116:  # "Get embedding from nomic-embed via Ollama on localhost." (comment)
```

All embed calls use `ollama.Client()` directly (e.g., `agents/query.py:26`, `shared/config.py:240-273`). The LiteLLM routes were likely added for symmetry or future parity but are currently unused.

**Remediation options:**
- (a) Remove routes 13-14 from LiteLLM config (dead code cleanup)
- (b) Migrate agent embed calls to go through LiteLLM for unified observability + Langfuse tracing
- (c) Keep as-is (optionality for future migration)

Alpha recommends (a) unless there is an imminent plan to unify through LiteLLM. Workspace CLAUDE.md explicitly says "Ollama is GPU-isolated... used only for CPU embedding... never for inference" — which suggests direct Ollama is the intended model, so the LiteLLM routes are redundant.

## 8. Anomaly A1 — `long-context` alias resolves to `gemini-flash`

```python
"long-context": "gemini-flash",  # 1M context, for prompts that exceed 200K
```

The alias name promises 1M-context routing, and Gemini 2.5 Flash supports 1M context, so the mapping is technically correct. But `gemini-flash` is also where `fast` points:

```python
"fast": "gemini-flash",
"long-context": "gemini-flash",  # same backend
```

Both aliases hit the same route + same max_parallel_requests limit. Callers who pick `long-context` specifically to get 1M context windowing share the same queue as `fast` callers. This is not drift — it is working as designed — but it is worth documenting that `long-context` is a semantic alias, not a separate LiteLLM route. No dedicated `gemini-1m` or `long-context` route exists in the LiteLLM config.

## 9. Positive findings (things that are correct)

1. **No stale Ollama inference refs in `shared/config.py` MODELS dict.** Workspace CLAUDE.md mandate "MODELS dict must use LiteLLM route names... never Ollama model names directly" is respected.
2. **`qwen3:8b` fully excised from Python.** `grep -rn "qwen3:8b" shared/ agents/` returns empty.
3. **TabbyAPI wiring is correct.** All three local routes (`local-fast`, `coding`, `reasoning`) point to `openai/Qwen3.5-9B-exl3-5.00bpw` at `172.18.0.1:5000/v1` via OpenAI-compatible API. Matches workspace CLAUDE.md § "Host services".
4. **Fallback chains are sane.** The removed `qwen3:8b` fallback + the comment explaining the death-spiral reasoning is well-documented in the LiteLLM config itself.
5. **Haiku 4.5 route correctly wired.** `claude-haiku` → `anthropic/claude-haiku-4-5-20251001` matches workspace env description: "claude-haiku-4-5-20251001".

## 10. Remediation queue items (proposed)

```yaml
id: "139"  # or next
title: "Officium LITELLM_BASE default → :4000 (D1)"
description: |
  Per queue #113 audit D1. Officium default LITELLM_BASE points to
  :4100 which is not listening. Update hapax-officium/shared/config.py
  default to http://localhost:4000 OR document the single-gateway model
  in workspace CLAUDE.md.
priority: low

id: "140"  # or next
title: "De-duplicate EMBEDDING_MODEL constant (D2)"
description: |
  Per queue #113 audit D2. EMBEDDING_MODEL defined in 3 files. Import
  from shared/config everywhere; delete duplicates in agents/_config.py
  + agents/ingest.py. Small 2-file patch.
priority: low

id: "141"  # or next
title: "Remove dead LiteLLM embed routes (D3)"
description: |
  Per queue #113 audit D3. Routes nomic-embed-text + nomic-embed in
  LiteLLM config are unused (all embeds go through ollama.Client
  directly). Delete the routes from the litellm container config.
priority: low
```

None are urgent. All three are safe single-file (or single-container-restart) changes.

## 11. Closing

LiteLLM config + shared/config.py MODELS dict are aligned for all inference routes. Three low-severity drift findings + one documentation anomaly (workspace CLAUDE.md describes a :4100 container that does not exist). No blocking issues.

Branch-only commit per queue item #113 acceptance criteria.

## 12. Cross-references

- Workspace CLAUDE.md § "Shared Infrastructure" — describes intended LiteLLM topology
- hapax-council CLAUDE.md § "Key Modules" — references `shared/config.py` MODELS dict
- `/tmp/litellm-council.yaml` — frozen snapshot of live litellm container config
- `shared/config.py:93-102` — MODELS + EMBEDDING_MODEL definitions
- `hapax-officium/shared/config.py:17` — LITELLM_BASE default

— alpha, 2026-04-15T18:18Z
