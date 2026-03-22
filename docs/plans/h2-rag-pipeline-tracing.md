# H2: RAG Pipeline Tracing — Implementation Plan

**Date:** 2026-03-12
**Status:** Ready for implementation
**Goal:** Instrument embed/search operations so every RAG query is visible in Langfuse with latency, vector count, and result quality.

---

## 1. Call Graph

```
                        ┌─────────────────────────────┐
                        │         Agent Layer          │
                        │                              │
                        │  knowledge/query.py          │
                        │  hapax_voice/tools.py        │
                        │  cockpit/chat_agent.py       │
                        │  demo_pipeline/research.py   │
                        │  demo_pipeline/dossier.py    │
                        │  demo_pipeline/sufficiency.py│
                        │  briefing.py, digest.py      │
                        │  research.py, scout.py       │
                        │  axiom_precedents.py         │
                        │  scripts/sdlc_plan.py        │
                        └──────────┬──────────────────┘
                                   │
                    ┌──────────────┼──────────────────┐
                    │              │                   │
                    ▼              ▼                   ▼
        ┌───────────────┐  ┌─────────────┐  ┌────────────────┐
        │knowledge_search│  │profile_store│  │axiom_precedents│
        │               │  │             │  │                │
        │search_documents│  │.search()   │  │.search()       │
        │search_memory  │  │.index()     │  │.record()       │
        │search_profile │  │             │  │                │
        └───────┬───────┘  └──────┬──────┘  └───────┬────────┘
                │                 │                  │
                └─────────┬───────┘──────────────────┘
                          │
                          ▼
               ┌─────────────────────┐
               │    shared/config.py │
               │                     │
               │  embed()            │──► Ollama /api/embed
               │  embed_batch()      │──► Ollama /api/embed (list)
               │  get_qdrant()       │──► QdrantClient singleton
               └─────────────────────┘
                          │
                          ▼
               ┌─────────────────────┐
               │   External Services │
               │                     │
               │  Ollama (embedding) │
               │  Qdrant (vector DB) │
               └─────────────────────┘
```

### Direct callers (bypass knowledge_search, call embed/get_qdrant directly)

Council:
- `cockpit/chat_agent.py` — inline search_documents tool
- `agents/hapax_voice/tools.py` — handle_search_documents, workspace context
- `agents/demo_pipeline/research.py` — 5 tool functions with direct embed+qdrant
- `agents/demo_pipeline/dossier.py` — profile embedding + qdrant upsert
- `agents/demo_pipeline/sufficiency.py` — coverage check via embed+qdrant
- `agents/briefing.py` — qdrant collection reads
- `agents/digest.py` — qdrant collection reads
- `agents/research.py` — direct qdrant usage via Deps
- `agents/health_monitor.py` — qdrant health check
- `agents/knowledge_maint.py` — 6 qdrant operations (cleanup, dedup, stats)
- `agents/ingest.py` — own embed() + get_qdrant() (standalone, does NOT use shared/config)
- `scripts/sdlc_plan.py` — precedent search

Officium:
- `agents/demo_pipeline/research.py` — 2 tool functions with direct embed+qdrant
- `agents/demo_pipeline/sufficiency.py` — coverage check
- `agents/digest.py` — qdrant reads
- `agents/knowledge_maint.py` — 6 qdrant operations
- `scripts/sdlc_plan.py` — precedent search
- `scripts/index-docs.py` — bulk indexing with embed_batch+qdrant

---

## 2. Function Inventory

### shared/config.py (IDENTICAL interface in both repos)

| Function | Signature | Purpose |
|---|---|---|
| `embed` | `(text: str, model: str \| None = None, prefix: str = "search_query") -> list[float]` | Single-text embedding via Ollama |
| `embed_batch` | `(texts: list[str], model: str \| None = None, prefix: str = "search_document") -> list[list[float]]` | Batch embedding via Ollama |
| `get_qdrant` | `() -> QdrantClient` | Singleton Qdrant client |
| `validate_embed_dimensions` | `() -> None` | Startup dimension check (calls embed internally) |

### shared/knowledge_search.py

**Council** (full implementation):

| Function | Signature | Calls |
|---|---|---|
| `search_documents` | `(query: str, *, source_service: str \| None, content_type: str \| None, days_back: int \| None, limit: int = 10) -> str` | embed + get_qdrant + query_points("documents") |
| `search_profile` | `(query: str, *, dimension: str \| None, limit: int = 5) -> str` | ProfileStore.search (embed + query_points("profile-facts")) |
| `search_memory` | `(query: str, *, limit: int = 5) -> str` | embed + get_qdrant + query_points("claude-memory") |
| `get_collection_stats` | `() -> str` | delegates to ops_live |

**Officium** (minimal — only search_profile):

| Function | Signature | Calls |
|---|---|---|
| `search_profile` | `(query: str, *, dimension: str \| None, limit: int = 5) -> str` | ProfileStore.search |

### shared/profile_store.py (IDENTICAL interface in both repos)

| Method | Signature | Calls |
|---|---|---|
| `ProfileStore.search` | `(query: str, *, dimension: str \| None, limit: int = 5) -> list[dict]` | embed + query_points("profile-facts") |
| `ProfileStore.index_profile` | `(profile) -> int` | embed_batch + upsert |

### shared/axiom_precedents.py (IDENTICAL interface in both repos)

| Method | Signature | Calls |
|---|---|---|
| `PrecedentStore.search` | `(axiom_id: str, situation: str, *, limit: int = 5) -> list[Precedent]` | embed + query_points("axiom-precedents") |
| `PrecedentStore.record` | `(precedent: Precedent) -> str` | embed + upsert |

### agents/ingest.py (council only — standalone embed/qdrant)

Has its own `get_qdrant()` and inline `ollama.embed()` calls. Does NOT use shared/config.

---

## 3. Interface Comparison: Council vs Officium

| Aspect | Council | Officium |
|---|---|---|
| `shared/config.py` | Identical signatures | Identical signatures |
| Ollama client | `Client(timeout=120)` | `Client(host=OLLAMA_URL, timeout=120)` |
| Default LiteLLM port | 4000 | 4100 |
| Default Qdrant port | 6333 | 6433 |
| `knowledge_search.py` | Full: search_documents, search_profile, search_memory, artifacts | Minimal: search_profile only |
| `profile_store.py` | Identical | Identical |
| `axiom_precedents.py` | Identical | Identical |
| `langfuse_config.py` | service.name=hapax-council, Basic auth | service.name=hapax-officium, header-key auth |
| OTel TracerProvider | Yes (via langfuse_config.py) | Yes (via langfuse_config.py) |
| HTTPX auto-instrumentation | Yes | Yes |
| Voice tracing (Langfuse SDK) | Yes (VoiceTracer) | N/A |
| Direct embed+qdrant callers | ~12 files | ~6 files |

**Key finding:** The shared function interfaces are identical. The instrumentation can be implemented once and applied to both repos via the same patch to `shared/config.py`.

---

## 4. Span Placement Decision

### Decision: Decorate shared functions in `shared/config.py`

**Rationale:**

1. **Coverage breadth.** Every call path — knowledge_search, profile_store, axiom_precedents, direct agent callers, scripts — flows through `embed()`, `embed_batch()`, and `get_qdrant().query_points()`. Instrumenting at the shared layer covers all current and future callers automatically.

2. **Minimal diff.** Three function decorators in config.py vs 18+ call-site patches across two repos. Lower merge conflict risk, easier to review.

3. **OTel is already bootstrapped.** Both repos have `langfuse_config.py` setting up a TracerProvider + HTTPX auto-instrumentation. The httpx instrumentation already captures raw HTTP calls to Ollama and Qdrant, but those spans lack semantic RAG attributes. Adding OTel spans inside embed/search functions creates meaningful parent spans that the httpx child spans will nest under.

4. **No new dependencies.** `opentelemetry-api` is already in both repos (via langfuse_config.py). The spans use `trace.get_tracer()` which returns no-op spans when the provider is not configured — zero overhead in tests.

### Supplementary: Optional search-level spans in knowledge_search.py

Add thin wrapper spans in `search_documents`, `search_memory`, `search_profile` to capture the full search lifecycle (embed + filter construction + qdrant query + result formatting) as one named span. These parent the config-level embed/qdrant spans and add search-specific attributes (collection, filter predicates, result count, top score).

This gives a two-tier span tree:
```
search_documents (knowledge_search)         ← search context
  └─ embed (config)                         ← embedding latency
  └─ qdrant.query_points (httpx auto-inst)  ← vector search latency
```

---

## 5. Attribute Schema

### Span: `rag.embed`
| Attribute | Type | Source |
|---|---|---|
| `rag.embed.model` | string | model param or EMBEDDING_MODEL |
| `rag.embed.prefix` | string | "search_query" or "search_document" |
| `rag.embed.text_length` | int | len(text) |
| `rag.embed.dimensions` | int | len(result vector) |
| `rag.embed.latency_ms` | float | measured in span |

### Span: `rag.embed_batch`
| Attribute | Type | Source |
|---|---|---|
| `rag.embed_batch.model` | string | model param or EMBEDDING_MODEL |
| `rag.embed_batch.prefix` | string | prefix param |
| `rag.embed_batch.count` | int | len(texts) |
| `rag.embed_batch.total_chars` | int | sum of text lengths |
| `rag.embed_batch.dimensions` | int | len(result vectors[0]) |
| `rag.embed_batch.latency_ms` | float | measured in span |

### Span: `rag.search` (knowledge_search-level)
| Attribute | Type | Source |
|---|---|---|
| `rag.query` | string | query text (truncated to 200 chars) |
| `rag.collection` | string | "documents", "claude-memory", "profile-facts", "axiom-precedents" |
| `rag.top_k` | int | limit param |
| `rag.result_count` | int | len(results.points) |
| `rag.top_score` | float | results.points[0].score if any |
| `rag.min_score` | float | results.points[-1].score if any |
| `rag.latency_ms` | float | full search including embed+query |
| `rag.filters` | string | JSON of applied filters (optional) |
| `rag.error` | string | exception message if failed |

---

## 6. Implementation Approach

### Phase 1: Config-level instrumentation (shared/config.py)

Add a module-level tracer and wrap `embed()` and `embed_batch()`:

```python
from opentelemetry import trace

_tracer = trace.get_tracer("hapax.rag")

def embed(text: str, model: str | None = None, prefix: str = "search_query") -> list[float]:
    model_name = model or EMBEDDING_MODEL
    with _tracer.start_as_current_span("rag.embed") as span:
        span.set_attribute("rag.embed.model", model_name)
        span.set_attribute("rag.embed.prefix", prefix)
        span.set_attribute("rag.embed.text_length", len(text))
        # ... existing logic ...
        span.set_attribute("rag.embed.dimensions", len(vec))
        return vec
```

Same pattern for `embed_batch()`. The OTel import is safe — `trace.get_tracer()` returns a no-op tracer when no provider is set, so tests and scripts that skip langfuse_config.py see zero overhead.

### Phase 2: Search-level instrumentation (shared/knowledge_search.py)

Wrap each search function:

```python
from opentelemetry import trace

_tracer = trace.get_tracer("hapax.rag")

def search_documents(query, *, source_service=None, content_type=None, days_back=None, limit=10):
    with _tracer.start_as_current_span("rag.search") as span:
        span.set_attribute("rag.query", query[:200])
        span.set_attribute("rag.collection", "documents")
        span.set_attribute("rag.top_k", limit)
        # ... existing logic ...
        span.set_attribute("rag.result_count", len(results.points))
        if results.points:
            span.set_attribute("rag.top_score", results.points[0].score)
```

### Phase 3: Store-level instrumentation (profile_store.py, axiom_precedents.py)

Add spans to `ProfileStore.search()`, `ProfileStore.index_profile()`, `PrecedentStore.search()`, `PrecedentStore.record()`. These follow the same pattern — get tracer, start span, set attributes.

### Phase 4: Direct-caller audit

Review all direct callers listed in section 1. Most will automatically gain visibility because they call `embed()` and `get_qdrant()`. The ones that need attention:

- **`agents/ingest.py` (council):** Has its own `get_qdrant()` and raw `ollama.embed()`. Either refactor to use `shared/config.embed` or add standalone spans.
- **`cockpit/chat_agent.py`:** Calls embed+query_points inline. Config-level spans cover embed; consider adding a `rag.search` span wrapper or refactoring to use `search_documents` from knowledge_search.

### Implementation order

1. `shared/config.py` — both repos (identical patch except import line)
2. `shared/knowledge_search.py` — council only (officium's is too minimal)
3. `shared/profile_store.py` — both repos (identical patch)
4. `shared/axiom_precedents.py` — both repos (identical patch)
5. `agents/ingest.py` — council only (refactor to shared/config or add spans)

---

## 7. What NOT to instrument

- **`get_qdrant()`** — singleton factory, called once. Not useful to trace.
- **`validate_embed_dimensions()`** — startup-only, calls embed() which will be traced.
- **`read_briefing`, `read_digest`, `read_scout_report`** — file reads, not RAG operations.
- **`get_collection_stats`, `ops_live.query_qdrant_stats`** — admin queries, not search paths.
- **knowledge_maint.py operations** — maintenance (dedup, cleanup, stats). Could add later but low priority.

---

## 8. Avoiding Double-Counting

HTTPX auto-instrumentation (already active) traces raw HTTP calls to Ollama and Qdrant. With config-level spans added, the trace tree becomes:

```
rag.search (knowledge_search)           ← NEW: search context
  ├─ rag.embed (config)                 ← NEW: embed semantics
  │   └─ HTTP POST ollama/api/embed     ← EXISTING: httpx auto
  └─ HTTP POST qdrant/collections/...   ← EXISTING: httpx auto
```

This is the desired outcome — the httpx spans provide raw latency/status, the new spans add RAG semantics. No double-counting because they are parent-child, not siblings.

---

## 9. Fail-Open Guarantee

All spans use `trace.get_tracer("hapax.rag")` which returns a no-op tracer when no TracerProvider is configured. This means:

- **Tests:** No tracing overhead, no mock needed.
- **Scripts without langfuse_config:** Silently no-op.
- **Langfuse down:** OTel BatchSpanProcessor drops spans after buffer fills; no backpressure on the application.

The existing `langfuse_config.py` pattern already demonstrates this — no try/except needed around span creation.

---

## 10. Verification Checklist

### Pre-implementation
- [ ] Confirm `opentelemetry-api` is in both repos' dependencies (pyproject.toml)
- [ ] Confirm langfuse_config.py is imported by all target agent entrypoints
- [ ] Run existing test suites to establish green baseline

### Implementation
- [ ] Add `_tracer = trace.get_tracer("hapax.rag")` to shared/config.py (both repos)
- [ ] Wrap embed() with rag.embed span + attributes
- [ ] Wrap embed_batch() with rag.embed_batch span + attributes
- [ ] Add rag.search spans to knowledge_search.py search_documents (council)
- [ ] Add rag.search spans to knowledge_search.py search_memory (council)
- [ ] Add rag.search spans to knowledge_search.py search_profile (both repos)
- [ ] Add rag.search spans to ProfileStore.search (both repos)
- [ ] Add rag.index spans to ProfileStore.index_profile (both repos)
- [ ] Add rag.search spans to PrecedentStore.search (both repos)
- [ ] Add rag.index spans to PrecedentStore.record (both repos)
- [ ] Audit agents/ingest.py — refactor or add standalone spans

### Post-implementation
- [ ] Run full test suite — confirm no regressions (spans are no-op without provider)
- [ ] Start Langfuse + Ollama + Qdrant locally
- [ ] Trigger a search_documents query via cockpit chat or voice
- [ ] Verify in Langfuse: trace appears with rag.search parent span
- [ ] Verify: rag.embed child span shows model, prefix, text_length, dimensions
- [ ] Verify: httpx child spans show raw HTTP calls to Ollama and Qdrant
- [ ] Verify: rag.result_count and rag.top_score attributes populated
- [ ] Trigger embed_batch via profile indexing — verify rag.embed_batch span
- [ ] Trigger axiom precedent search — verify rag.search with collection=axiom-precedents
- [ ] Check Langfuse dashboard: latency distribution visible, filterable by collection
- [ ] Confirm no performance regression (embed latency within normal range)

### Langfuse dashboard queries to validate
- Filter by span name `rag.embed` — should show all embed calls with latency
- Filter by `rag.collection=documents` — should show document searches
- Group by `rag.embed.model` — should show only nomic-embed-text-v2-moe
- Sort by `rag.latency_ms` desc — identify slow searches
- Filter `rag.result_count=0` — find queries returning no results (quality signal)
