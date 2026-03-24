# Ingestion Pipeline Audit: Design Document

**Date:** 2026-03-23
**Scope:** All ingestion paths, data sinks, and consumer surfaces across hapax-council and hapax-officium
**Method:** Automated multi-agent codebase exploration with manual verification of findings

---

## 1. System Inventory

### 1.1 Ingestion Sources (10 external entry points)

| Source | Protocol | Receiver | Sink |
|--------|----------|----------|------|
| Pixel Watch 4 | HTTP POST `:8042` | `agents/watch_receiver.py` | `~/hapax-state/watch/*.json` |
| PipeWire audio | PCM 16kHz callback | `agents/hapax_voice/audio_input.py` | In-memory → ConversationPipeline |
| 6 USB cameras | v4l2src GStreamer CUDA | `agents/studio_compositor.py` | `/dev/video42`, HLS, `~/video-recording/` |
| Google Drive | OAuth 2.0 Changes API | `agents/gdrive_sync.py` | `~/documents/rag-sources/gdrive/` |
| Gmail, Calendar, YouTube, Chrome | OAuth / local | Respective sync agents | `~/documents/rag-sources/{service}/` |
| Obsidian vault | File sync | `agents/obsidian_sync.py` | `~/documents/rag-sources/obsidian/` |
| Phone (KDE Connect) | Bluetooth | Perception backends | `perception-state.json` |
| Screen capture | grim + ImageMagick | `agents/hapax_voice/screen_capturer.py` | Base64 in perception state |
| Keyboard/mouse | evdev / Hyprland | `agents/hapax_voice/backends/input_activity.py` | `perception-state.json` |
| RAG source files | inotify | `agents/ingest.py` (Docling) | Qdrant `documents` |

### 1.2 Data Sinks

#### Qdrant Vector DB (9 collections, 2 dead)

| Collection | Dim | Embedding | Writer | Status |
|------------|-----|-----------|--------|--------|
| `documents` | 768 | nomic | `agents/ingest.py` | LIVE |
| `profile-facts` | 768 | nomic | `shared/profile_store.py` | LIVE |
| `axiom-precedents` | 768 | nomic | `shared/axiom_precedents.py` | LIVE |
| `operator-corrections` | 768 | nomic | `shared/correction_memory.py` | LIVE |
| `operator-episodes` | 768 | nomic | `shared/episodic_memory.py` | LIVE |
| `operator-patterns` | 768 | nomic | `shared/pattern_consolidation.py` | LIVE |
| `studio-moments` | 512 | CLAP | `agents/av_correlator.py` | LIVE |
| `hapax-apperceptions` | 768 | nomic | `shared/apperception.py` | LIVE |
| `samples` | 768 | nomic | **None** | DEAD |
| `claude-memory` | 768 | nomic | **None** | DEAD |

#### Filesystem

- **JSONL audit logs** (12+ files under `profiles/`): health-history, drift-history, enforcement-audit, sdlc-events, capacity-history, deliberation-eval, tool-usage, engine-audit, etc.
- **Obsidian vault** (`~/Documents/Work/30-system/`): briefings, digests, nudges, goals
- **RAG sources** (`~/documents/rag-sources/`): sync agent output, consumed by ingest pipeline
- **Cache state** (`~/.cache/hapax*/`): dedup tracker, retry queue, perception state, working mode

#### Shared Memory (`/dev/shm/`)

- `hapax-stimmung/state.json` — system mood (60s writes)
- `hapax-temporal/bands.json` — temporal context
- `hapax-apperception/self-band.json` — self-model state
- `hapax-compositor/` — visual layer state, snapshots, HLS, watershed events, consent audit

#### Docker Infrastructure (all actively used)

- **PostgreSQL** `:5432` — LiteLLM config + Langfuse metadata + n8n workflows
- **Redis** `:6379` — Langfuse job queue
- **ClickHouse** `:8123` — Langfuse OLAP analytics
- **MinIO** `:9001` — Langfuse media/event storage

### 1.3 Consumer Surfaces

| Consumer | Method | Cadence |
|----------|--------|---------|
| React/Tauri SPA | HTTP + SSE (40 council, 20 officium endpoints) | 30s fast / 5min slow |
| Claude Code (hapax-mcp) | 34 HTTP tools | On-demand |
| Grafana | Prometheus scrape `/metrics` | 30s |
| ntfy | HTTP POST `:8090` | Event-triggered |
| Reactive engine | inotify on `profiles/`, `rag-sources/` | Event-driven |

---

## 2. Findings

### 2.1 HIGH Severity

#### H1: Dedup tracker non-atomic write

**Location:** `agents/ingest.py:465-468`
**Problem:** `_save_dedup_tracker()` uses `Path.write_text()` directly. No tmp+rename pattern. A crash mid-write corrupts `~/.cache/rag-ingest/processed.json`, causing the tracker to return `{}` on reload, which triggers full re-ingestion of all files.
**Fix:** Atomic write via tmp file + `os.rename()`. Add file locking via `fcntl.flock()` to prevent concurrent writers.

#### H2: Orphan Qdrant collections in maintenance lists

**Location:** `agents/knowledge_maint.py:51`, `agents/digest.py:78`, `agents/health_monitor.py:128-134`
**Problem:** `COLLECTIONS` lists include `samples` and `claude-memory` which have zero writers in the codebase. Health monitor expects them to exist. Maintenance agent wastes cycles on empty collections. `search_memory()` in `shared/knowledge_search.py:153-181` queries a permanently empty collection.
**Fix:** Remove both from all `COLLECTIONS` lists and `REQUIRED_QDRANT_COLLECTIONS`. Remove `search_memory()` from knowledge_search.py. Delete the collections from Qdrant. Update `shared/spec_audit.py` if needed.

#### H3: Cross-project null-safety gap

**Location:** `shared/axiom_precedents.py:104` (council), `shared/profile_store.py` (council)
**Problem:** Council's `_from_payload()` accepts `payload: dict` but Qdrant can return `None` payloads. Officium has defensive `if payload is None: payload = {}` checks that council lacks. Council will crash on None payloads.
**Fix:** Port officium's null-safety pattern to council's `axiom_precedents.py` and `profile_store.py`.

### 2.2 MEDIUM Severity

#### M1: Silent retry discard (no dead-letter queue)

**Location:** `agents/ingest.py:191-231`, `agents/ingest.py:312-315`
**Problem:** After 5 retries (max 1h backoff), failed files are logged and discarded. No alert, no persistent dead-letter file, no mechanism to resurface them.
**Fix:** Write permanently-failed entries to `~/.cache/rag-ingest/dead-letter.jsonl`. Send ntfy alert on permanent failure. Add `--retry-dead-letter` CLI flag to re-attempt dead-lettered files.

#### M2: Qdrant health check lacks depth

**Location:** `agents/health_monitor.py:715-811`
**Problem:** Checks HTTP reachability and collection existence with point count, but never validates vector dimensions, runs a test query, or detects corruption. A collection with wrong dimensions passes health checks.
**Fix:** Add dimension validation check per collection (compare `vectors_config.size` against `EXPECTED_EMBED_DIMENSIONS`). Add a canary query check on `documents` collection.

#### M3: Perception state error silently swallowed

**Location:** `agents/hapax_voice/_perception_state_writer.py:420-421`
**Problem:** `except OSError` catches disk-full, permission-denied, etc. and logs at DEBUG level only. Stale perception state goes undetected by all consumers.
**Fix:** Promote to WARNING. Track consecutive failures. After 5 consecutive failures, emit ntfy alert.

#### M4: Watch receiver input validation gaps

**Location:** `agents/watch_receiver.py:73-78`
**Problem:** Device ID whitelist exists (good), but: `readings` list is unbounded (memory DoS), `ts` has no upper bound (accepts year 5000), `bpm` accepts 0-infinity. No rate limiting.
**Fix:** Add `max_length=500` to `readings` field. Add `le=` bounds on `ts` (now + 1 day), `bpm` (0-300). Add simple per-device rate limit (1 req/s).

#### M5: Officium hardcodes embedding dimensions

**Location:** `hapax-officium/shared/axiom_precedents.py`, `hapax-officium/shared/profile_store.py`
**Problem:** Officium hardcodes `VECTOR_DIM = 768` instead of importing `EXPECTED_EMBED_DIMENSIONS` from config.py. If embedding model changes, council auto-follows but officium silently breaks.
**Fix:** Replace hardcoded `768` with `from shared.config import EXPECTED_EMBED_DIMENSIONS` in both files.

#### M6: hapax-sdlc version skew

**Location:** `hapax-council/pyproject.toml:31`, `hapax-officium/pyproject.toml:40`
**Problem:** Council tracks main branch (unpinned). Officium pinned to commit `cbdf204` (stale). API changes in hapax-sdlc could break council while officium stays frozen.
**Fix:** Pin both to same commit hash. Update together as part of sdlc releases.

### 2.3 LOW Severity

#### L1: Officium lacks OTel tracing in shared modules

**Location:** `hapax-officium/shared/axiom_precedents.py`, `hapax-officium/shared/profile_store.py`
**Problem:** Council wraps Qdrant operations in `_rag_tracer.start_as_current_span()`. Officium has no tracing. RAG performance issues in officium are invisible in Langfuse.
**Status:** Deferred. Officium is lower-traffic and less latency-sensitive.

#### L2: knowledge_search.py gutted in officium

**Location:** `hapax-officium/shared/knowledge_search.py` (42 lines vs council's 320)
**Problem:** Only `search_profile()` remains. `search_documents()`, `search_memory()`, artifact reads all removed.
**Status:** Intentional scoping. Officium doesn't need document search. Not a bug.

#### L3: Council agent flag validation weaker than officium

**Location:** `hapax-council/logos/api/routes/agents.py:26-27`
**Problem:** Council has basic regex validation for agent CLI flags. Officium adds a blocklist (`--exec`, `--command`, `--shell`) and rate limiting.
**Fix:** Port officium's `_validate_flags()` and `_BLOCKED_FLAG_PREFIXES` to council.

---

## 3. Scope Exclusions

The following were investigated and found to be **not issues**:

- **PostgreSQL, Redis, ClickHouse, MinIO** — All actively used by Langfuse/LiteLLM Docker stack. No application-code writes needed.
- **Model alias divergence** (council vs officium) — Intentional. Different workloads, different routing.
- **Axiom naming divergence** — Versioned evolution. Officium's v3 supersedes council's. Both registries active by design.
- **Profile dimension count** (11 council vs 6 officium) — Intentional scoping. Officium only needs management dimensions.
- **MCP write-back** — By design, Claude Code doesn't write to the knowledge base. Write tools are limited to nudge actions, profile corrections, scout decisions.

---

## 4. Implementation Batches

### Batch A: Data Integrity (H1, M1, M3)
Atomicity, dead-letter queue, error visibility. All in `agents/ingest.py` and `agents/hapax_voice/_perception_state_writer.py`.

### Batch B: Collection Hygiene (H2, M2)
Remove orphan collections from all references. Add dimension validation to health monitor.

### Batch C: Cross-Project Safety (H3, M5, M4, L3)
Null-safety, hardcoded dimensions, input validation. Changes in `shared/` modules across both projects.

### Batch D: Dependency Alignment (M6)
Pin hapax-sdlc to same commit in both projects.

---

## 5. Files Affected

### Batch A
- `hapax-council/agents/ingest.py` (dedup tracker atomic write, dead-letter queue)
- `hapax-council/agents/hapax_voice/_perception_state_writer.py` (error escalation)
- `hapax-council/shared/notify.py` (new alert paths)

### Batch B
- `hapax-council/agents/knowledge_maint.py` (remove samples, claude-memory)
- `hapax-council/agents/digest.py` (remove samples, claude-memory)
- `hapax-council/agents/health_monitor.py` (remove from REQUIRED, add dimension check)
- `hapax-council/shared/knowledge_search.py` (remove search_memory)

### Batch C
- `hapax-council/shared/axiom_precedents.py` (null-safety)
- `hapax-council/shared/profile_store.py` (null-safety)
- `hapax-officium/shared/axiom_precedents.py` (import EXPECTED_EMBED_DIMENSIONS)
- `hapax-officium/shared/profile_store.py` (import EXPECTED_EMBED_DIMENSIONS)
- `hapax-council/agents/watch_receiver.py` (input bounds)
- `hapax-council/logos/api/routes/agents.py` (flag validation)

### Batch D
- `hapax-council/pyproject.toml` (pin hapax-sdlc)
- `hapax-officium/pyproject.toml` (update hapax-sdlc pin)
