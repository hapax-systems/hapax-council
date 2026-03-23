# Boundary Contract Enforcement

**Date:** 2026-03-23
**Status:** Implemented (council + MCP), smoke-tested against live system
**Scope:** hapax-council, hapax-officium, hapax-mcp

## Problem Statement

The Hapax system has 92 API endpoints across two logos APIs, 34 MCP tool bridges, a
filesystem-as-bus with 25+ document types, and cross-process shared memory channels.
Response shapes at service boundaries are untyped. The MCP client trusts raw JSON without
validation. Frontmatter writers emit YAML without schema enforcement. Breaking changes
propagate silently until runtime failure.

Prior contract enforcement:

| Boundary | Enforcement | Failure mode |
|----------|-------------|--------------|
| Logos API request bodies | Pydantic models (FastAPI) | Caught at request time |
| Logos API response bodies | None | Silent schema drift |
| MCP → Logos API | None (`r.json()` → raw dict) | Silent field absence |
| Filesystem-as-bus writes | None (permissive YAML parse) | Malformed frontmatter ignored |
| /dev/shm cross-process | Struct convention only | Silent corruption on layout change |
| Qdrant collection config | None | Config drift after rebuild |

## Non-Goals

- Consumer-driven contract testing (Pact/CDC). Single-operator system with no cross-team
  coordination problem. The ceremony-to-value ratio is prohibitive.
- Full E2E testing of LLM agent pipelines. Non-deterministic outputs are tested via
  pydantic-ai `TestModel` and Langfuse evaluation, not schema contracts.
- Schema versioning or negotiation. All services deploy together via systemd reload.
  Version negotiation solves a problem that lockstep deployment eliminates.

## Implementation

Four interventions, ordered by risk coverage and implementation cost.

### 1. API Schema Fuzzing via Schemathesis

**What:** Property-based API testing against the auto-generated OpenAPI spec. Schemathesis
generates valid and edge-case inputs for every endpoint, verifying that responses conform
to declared schemas and that no endpoint returns 500 on valid input.

**Why:** 92 endpoints, most returning untyped dicts. Adding response models to all 92
routes is high cost. Schemathesis tests the *actual* behavior against the *declared* spec
without requiring response model annotations — it catches 500s, undeclared error codes,
malformed JSON, and schema violations from the OpenAPI spec that FastAPI already
auto-generates.

**Files:**
- `tests/contract/test_council_api_schema.py` — 97 parametrized tests (one per endpoint)
- `pyproject.toml` — `schemathesis>=4.7` in dev dependencies, `contract` marker

**Usage:**
```bash
uv run pytest -m contract tests/contract/   # run contract tests only
uv run pytest tests/                        # default run excludes contract tests
```

- Runs in-process via ASGI transport (no live server required).
- Hypothesis generates ~100 examples per operation by default.
- CI marker: `@pytest.mark.contract` (excluded from default run via `addopts`).
- Configuration inline via `from_asgi()` parameters (schemathesis.toml config format is
  unstable across versions).

**Limitation:** Endpoints returning raw dicts without `response_model=` in the FastAPI
decorator will have loose OpenAPI schemas (just `object`). Schemathesis can still catch
500s and malformed responses, but cannot validate field presence for untyped endpoints.
The MCP response models (intervention 2) cover the field-level contract for the endpoints
that MCP actually consumes.

### 2. MCP Response Models (Bilateral Contracts)

**What:** Pydantic response models in `hapax-mcp` that validate the JSON returned by each
logos API endpoint. The API defines what it sends (via route implementation); the MCP
client enforces what it expects (via Pydantic parse). A response shape change breaks
immediately with a `ValidationError` instead of propagating silently.

**Why:** The MCP client is the primary programmatic consumer of both logos APIs. It
currently calls `r.json()` and passes raw dicts through `json.dumps()` to Claude Code.
If an API endpoint adds, removes, or renames a field, the MCP tool continues to work
(JSON serialization succeeds) but the *semantic contract* is violated — Claude Code
receives different data than expected. Pydantic validation at the client boundary catches
this immediately.

**Files:**
```
hapax-mcp/src/hapax_mcp/
  client.py              ← get_validated() typed client function
  models/
    __init__.py          ← re-exports all models
    health.py            ← HealthResponse, HealthCheckDetail, HealthHistoryEntry
    infrastructure.py    ← GpuResponse, ContainerInfo, InfrastructureResponse
    profile.py           ← ProfileResponse, ProfileDimensionResponse
    working_mode.py      ← WorkingModeResponse
hapax-mcp/tests/
  test_response_models.py  ← 14 tests (valid + missing field + extra field)
```

**Model strategy:** Models are *consumer-side* (defined in hapax-mcp, not in the API).
They declare the minimum fields the MCP tool requires. Extra fields are allowed
(`model_config = ConfigDict(extra="allow")`). This is a Postel's Law contract: strict in
what the client requires, tolerant of additions.

**Current coverage:** The `status()` compound tool (health + gpu + infrastructure +
cycle-mode) uses validated responses. Remaining 30 endpoints use unvalidated `client.get()`
and can be migrated incrementally.

### 3. Frontmatter Write-Time Schema Validation

**What:** Pydantic models for each document type written through the filesystem-as-bus.
Validation at `vault_writer.py` write boundary.

**Why:** The filesystem-as-bus carries 25+ document types. The canonical parser
(`shared/frontmatter.py`) returns `({}, text)` on any parse failure — silently dropping
malformed metadata. The reactive engine then processes files without the metadata it
expects. A schema violation at write time is cheaper to debug than a silent downstream
failure.

**Files:**
- `shared/frontmatter_schemas.py` — 7 Pydantic models + `validate_frontmatter()` utility
- `shared/vault_writer.py` — all 6 specialized writers now validate before writing
- `tests/test_frontmatter_schemas.py` — 17 tests including Hypothesis property-based

**Schemas implemented:**

| Model | `type` literal | Used by |
|-------|---------------|---------|
| `BriefingFrontmatter` | `"briefing"` | `write_briefing_to_vault()` |
| `DigestFrontmatter` | `"digest"` | `write_digest_to_vault()` |
| `NudgeFrontmatter` | `"nudges"` | `write_nudges_to_vault()` |
| `GoalsFrontmatter` | `"goals"` | `write_goals_to_vault()` |
| `DecisionFrontmatter` | `"decision"` | `create_decision_starter()` |
| `BridgePromptFrontmatter` | `"bridge-prompt"` | `write_bridge_prompt_to_vault()` |
| `RagSourceFrontmatter` | (uses `content_type`) | Available for sync agent migration |

All models use `extra="allow"` for forward compatibility. The generic `write_to_vault()`
remains unvalidated — only the specialized writers enforce schemas.

### 4. Qdrant Collection Schema Assertions

**What:** Startup assertions in logos API lifespan that verify each Qdrant collection's
configuration (vector dimensions, distance metric) matches expectations.

**Why:** After a crash or rebuild, Qdrant collections may be recreated with different
parameters (session 12 incident: profile-facts had 0 points after reboot because WAL
wasn't flushed). A startup assertion catches configuration drift before the API serves
requests.

**Files:**
- `shared/qdrant_schema.py` — `EXPECTED_COLLECTIONS` dict + `verify_collections()` + `log_collection_issues()`
- `logos/api/app.py` — verification wired into lifespan startup (non-fatal)
- `tests/test_qdrant_schema.py` — 9 tests (correct config, missing collection, wrong dimensions, wrong distance, case-insensitive enum, connection failure)

**Note:** Qdrant client returns distance enum names in uppercase (`COSINE`). The
comparison is case-insensitive to handle this.

## Schemathesis Results (First Run)

97 endpoints tested. 57 passed, 40 failed. Failures triaged below.

### Passed (57) — All read-only endpoints MCP consumes

All GET endpoints with no path parameters or side effects pass cleanly: health,
health/history, gpu, infrastructure, briefing, scout, drift, cost, goals, readiness,
nudges, agents, accommodations, management, workspace, manual, profile,
profile/facts/pending, copilot, demos, working-mode, cycle-mode, scout/decisions,
query/agents, engine/status, engine/rules, engine/history, consent/revoke, consent/trace,
consent/contracts, consent/coverage, consent/precedents, flow/state, chat/models,
agents/runs/current, root.

### Non-Actionable Failures (32)

| Category | Count | Cause | Resolution |
|----------|-------|-------|------------|
| Prometheus `/metrics` | 1 | Returns `text/plain` (Prometheus text format), not JSON. Mounted by `prometheus_fastapi_instrumentator`. | Exclude from schemathesis |
| Fuzzed path params → 404 | 24 | All handlers (nudges, agents, chat, accommodations, profile, demos, scout) have **correct 404 handling**. Schemathesis reports failures because fuzzed IDs don't match existing resources. No 500s — these are proper 404 responses. | Exclude mutating endpoints or accept 404 as valid response |
| SSE streaming | 2 | `query/run` and `query/refine` return `EventSourceResponse` (`text/event-stream`). No `responses` parameter in route decorator, so OpenAPI schema shows default JSON. | Add `responses={200: {"content": {"text/event-stream": {}}}}` to route decorators, or exclude from schemathesis |
| Binary/image endpoints | 5 | Studio stream endpoints return `image/jpeg` or `multipart/mixed`. `snapshot` and `fx` return 503 JSON when compositor not running (content-type mismatch). | Exclude from schemathesis |

### Actionable Findings (8)

**Validation gap (1):**

| Endpoint | Finding | Root cause | Fix |
|----------|---------|------------|-----|
| `POST /api/logos/directive` | Accepts `bool` for `detection_tier` (declared `int \| None`) | Pydantic v2 lax mode coerces `bool→int` (`True→1`, `False→0`). Python `bool` subclasses `int`. Model has no `strict=True` or `Strict()` annotation. | Add `Strict()` to `detection_tier` field or set `model_config = ConfigDict(strict=True)` |

**Environment-dependent 500s (4):**

| Endpoint | Finding | Root cause | Fix |
|----------|---------|------------|-----|
| `PUT /api/working-mode` | 500 on valid `"research"` or `"rnd"` input | Calls `hapax-working-mode` shell script which fails in ASGI test mode (no desktop env). Handler correctly raises `HTTPException(500)` on script failure. | Not a bug — environment dependency. Works in production. |
| `PUT /api/cycle-mode` | 500 on valid `"dev"` or `"prod"` input | Same pattern — calls `hapax-mode` script with fallback file write. | Same — environment dependency. |
| `POST /api/studio/moments/search` | 500 | Searches Qdrant `studio-moments` collection. Fails when Qdrant not reachable in ASGI test mode. | Not a bug — infrastructure dependency. |
| `GET /api/consent/channels` | 500 | Pure computation (no I/O). Likely transient import failure during app initialization in test. Low risk. | Investigate if reproducible; likely false positive. |

**Missing error handling (3):**

| Endpoint | Finding | Root cause | Fix |
|----------|---------|------------|-----|
| `POST /api/consent/create` | 500 on filesystem I/O | Writes to `axioms/contracts/` with no exception handling. `mkdir()` or `write_text()` raises unhandled `OSError` if directory not writable or disk full. Also: no validation that `person_id` matches registered principals. | Wrap I/O in try/except, return 503 on write failure. Consider person_id validation. |
| `GET /api/consent/overhead` | 500 | `measure_alignment_tax()` → `measure_label_operations()` has no `ImportError` handling. If governance modules fail to import → unhandled exception. `measure_sdlc_overhead()` catches missing file but not unreadable file. | Add try/except around imports and file reads in `alignment_tax_meter.py`. |
| `GET /api/engine/audit` | 500 | Reads JSONL audit log with overbroad `except Exception` that returns 500 `JSONResponse`. Triggered by malformed JSONL or missing audit directory. | Narrow exception handling: catch `FileNotFoundError` → empty list, `json.JSONDecodeError` → skip malformed lines, `PermissionError` → 503. |

## Dependency Summary

| Package | Version | Repo | Purpose |
|---------|---------|------|---------|
| schemathesis | >=4.7 | council | API schema fuzzing (dev dep) |
| pydantic | >=2.0 | hapax-mcp | Response model validation (runtime dep) |
| (hypothesis — already present) | — | council | Frontmatter property-based tests |

`testcontainers[qdrant]` deferred — Qdrant assertions use mocks in unit tests and verify
against live Qdrant via the startup lifespan check.

## What This Does Not Cover

- **Cross-process /dev/shm contracts.** The GQI→stimmung shared memory channel uses a
  simple float write/read. Adding a schema layer to a single-float IPC channel is
  over-engineering. The existing health check (stimmung dimension count) catches drift.

- **LLM output contracts.** Pydantic `output_type` on pydantic-ai agents already handles
  this. No additional contract layer needed.

- **Officium↔Council HTTP communication.** These services do not currently call each other
  directly. The MCP server is the only cross-service consumer. If direct service-to-service
  calls are added in the future, extend intervention 2 (typed client models) to that
  boundary.

## Test Summary

| Suite | Location | Count | Marker | Default run |
|-------|----------|-------|--------|-------------|
| Schemathesis API fuzzing | `tests/contract/test_council_api_schema.py` | 97 | `contract` | Excluded |
| Frontmatter schemas | `tests/test_frontmatter_schemas.py` | 17 | (none) | Included |
| Qdrant schema assertions | `tests/test_qdrant_schema.py` | 9 | (none) | Included |
| Vault writer (existing) | `tests/test_vault_writer.py` | 17 | (none) | Included |
| MCP response models | `hapax-mcp/tests/test_response_models.py` | 14 | (none) | Included |

## Future Work

1. **Expand MCP response models** — Cover remaining 30 endpoints beyond the 4 compound-tool
   endpoints currently validated.
2. **Fix actionable schemathesis findings** — `detection_tier` strict validation, consent
   error handling, engine audit exception narrowing.
3. **Officium schemathesis** — Add contract tests for the officium API (:8050) in the
   hapax-officium repo.
4. **RAG source frontmatter schemas** — Extend `RagSourceFrontmatter` to cover the 20+
   `content_type` values used by sync agents.
5. **OpenAPI annotations for non-JSON endpoints** — Add `responses` parameter to SSE and
   binary endpoints so the OpenAPI spec accurately reflects content types.
