# Query Agents Design — System Operations & Knowledge Context

**Date:** 2026-03-10
**Status:** Approved
**Builds on:** cockpit-insight (query dispatch, SSE streaming, Insight page)

## Context

Logos query engine currently has one registered agent: Development Archaeology (dev_story), which queries a SQLite database of git/session data. This design adds two more agents to cover the remaining data surfaces: operational infrastructure and semantic knowledge.

## Agent 1: System Operations

### Purpose

Answer questions about system health, infrastructure state, Docker services, drift detection, LLM costs, and operational analytics.

### Data Access Pattern: Hybrid

**SQLite (historical time-series from JSONL/JSON):**

| Table | Source File | Key Columns |
|-------|-----------|-------------|
| `health_runs` | health-history.jsonl (~595 entries) | timestamp, status, healthy, degraded, failed, duration_ms, failed_checks (JSON array) |
| `drift_items` | drift-report.json | severity, category, doc_file, doc_claim, reality, suggestion |
| `drift_runs` | drift-history.jsonl | timestamp, drift_count, docs_analyzed, summary |
| `digest_runs` | digest-history.jsonl (~410 entries) | timestamp, hours, headline, summary, new_documents |
| `knowledge_maint` | knowledge-maint-history.jsonl (~96 entries) | timestamp, pruned_count, merged_count, duration_ms |

**Live tools (real-time HTTP/file reads):**

| Tool | Source | Returns |
|------|--------|---------|
| `get_infra_snapshot` | profiles/infra-snapshot.json (15-min updates) | Containers, timers, GPU state, cycle mode |
| `get_manifest_section(section)` | profiles/manifest.json (weekly, 26 KB) | Docker, systemd, qdrant, ollama, gpu, disk, ports, creds |
| `query_langfuse_cost(days)` | Langfuse API via shared/langfuse_client.py | Per-model cost breakdown, total spend, trace counts |
| `query_qdrant_stats` | Qdrant API via shared/config.get_qdrant() | Collection names, point counts, dimensions |

### Tools (6 total)

1. `run_sql(query)` — Execute SQL against the ops SQLite DB
2. `get_table_schemas()` — Return all table DDL for LLM introspection
3. `get_infra_snapshot()` — Current containers, timers, GPU, cycle mode
4. `get_manifest_section(section)` — Deep infrastructure detail by section
5. `query_langfuse_cost(days)` — LLM cost analytics from Langfuse
6. `query_qdrant_stats()` — Vector DB collection health

### System Prompt

Embeds full SQL table schemas. Explains the two-paradigm split: SQL for "over time" questions (trends, aggregates, history), live tools for "right now" questions (current state, loaded models, running containers). Includes mermaid diagram instructions (inherited from dev-story pattern).

### Registration

```python
_AGENTS["system_ops"] = {
    "name": "System Operations",
    "description": "Query infrastructure health, Docker services, costs, drift, and operational state",
    "keywords": [
        "health", "docker", "container", "service", "timer", "systemd",
        "gpu", "vram", "ollama", "model", "cost", "spend", "langfuse",
        "drift", "uptime", "degraded", "failed", "qdrant", "collection",
        "infrastructure", "disk", "port", "running", "status",
    ],
}
```

## Agent 2: Knowledge & Context

### Purpose

Answer questions by searching across Qdrant vector collections (documents, profile facts, memory) and structured knowledge artifacts (briefings, digests, scout reports, goals).

### Data Access Pattern: Semantic Search + Artifact Reads

**Qdrant collections:**

| Collection | Content | Key Filters |
|-----------|---------|-------------|
| `documents` | RAG chunks from 9 sync agents | source_service, content_type, modality_tags, ingested_at, people |
| `profile-facts` | 11 operator dimensions (5 trait + 6 behavioral) | dimension, confidence |
| `claude-memory` | Multi-session conversation context | — |
| `axiom-precedents` | Governance decisions | — |

**source_service values:** gdrive, gcalendar, gmail, youtube, claude-code, obsidian, chrome, ambient-audio, takeout, proton

**File artifacts:**

| File | Content | Update Frequency |
|------|---------|-----------------|
| briefing.json | Daily briefing with action items, stats | Daily 07:00 |
| digest.json | Knowledge digest, notable items | Daily 06:45 |
| scout-report.json | Technology recommendations (tier/effort/confidence) | Weekly Wed |
| operator.json | Active goals, constraints, patterns | On profile update |

### Tools (8 total)

1. `search_documents(query, source_service?, content_type?, days_back?, limit)` — Vector search on `documents` with optional filters
2. `search_profile(query, dimension?, limit)` — Vector search on `profile-facts` via ProfileStore
3. `search_memory(query, limit)` — Vector search on `claude-memory`
4. `read_briefing()` — Latest briefing.json
5. `read_digest()` — Latest digest.json
6. `read_scout_report()` — Latest scout-report.json
7. `get_operator_goals()` — Active goals from operator.json
8. `get_collection_stats()` — Point counts and metadata for all collections

### System Prompt

Explains collection contents and what each source_service covers. Documents available filter fields. Instructs on evidence citation (source file, confidence scores, timestamps). Includes mermaid diagram instructions. Guides the LLM on filter selection: "what did my email say about X" → source_service=gmail, "find that Obsidian note" → source_service=obsidian.

### Registration

```python
_AGENTS["knowledge"] = {
    "name": "Knowledge & Context",
    "description": "Search documents, profile facts, briefings, digests, and operator context",
    "keywords": [
        "document", "search", "find", "briefing", "digest", "scout",
        "goal", "profile", "memory", "knowledge", "obsidian", "drive",
        "email", "gmail", "youtube", "chrome", "calendar", "note",
        "vault", "rag", "context", "recommendation", "fact",
    ],
}
```

## Shared Patterns

Both agents follow the established dev-story pattern:
- `agents/<name>/query.py` — Agent definition, system prompt, tools
- Factory function registered in `cockpit/query_dispatch.py` via `_AGENT_FACTORY_NAMES`
- Keyword classification routes queries (3 agents means scoring matters now)
- SSE streaming via existing `/api/query/run` endpoint
- Mermaid diagram support in system prompts
- `@dataclass QueryDeps` for dependency injection
- Full test coverage with mocked LLM calls

## Sequencing

1. **System Operations first** — self-contained (file reads + HTTP), no vector search complexity, battle-tests multi-agent dispatch
2. **Knowledge & Context second** — depends on semantic search tuning, benefits from dispatch infrastructure proven with 2 agents

## Classification Update

With 3 agents, keyword scoring becomes meaningful. The `classify_query` function already handles multi-agent scoring via keyword overlap. Keywords are chosen to be distinctive per agent with minimal overlap.
