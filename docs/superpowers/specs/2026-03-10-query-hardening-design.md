# Query System Hardening — Design Spec

**Date:** 2026-03-10
**Status:** Approved
**Builds on:** cockpit-insight, query-agents

## Context

The query system now has 3 agents (dev_story, system_ops, knowledge), keyword dispatch, SSE streaming, and a hapax-logos Insight page. All 76 existing query tests use mocked/synthetic data and assume data always exists. No tests exercise real data patterns, empty-state behavior, or the full dispatch-to-rendering pipeline. hapax-logos has zero test infrastructure.

## Goals

1. Prove the system works end-to-end with real data patterns
2. Prove the system handles fresh deployment gracefully (empty state surfaced, not hidden)
3. Harden existing tests where empty-state gaps were found
4. Establish hapax-logos test foundation for the Insight page

## Non-Goals

- LLM output quality scoring (promptfoo evals — separate effort)
- Performance benchmarking
- Voice/perception layer testing
- Expanding hapax-logos test coverage beyond Insight page

## Data Partition: Real vs Demo

Real operational data and demo/seed data are categorically different. Tests must never conflate them.

**Real data** (from the actual running system):
- `dev-story.db` — built from real git history and Claude Code sessions
- `health-history.jsonl` — real health monitor runs
- `drift-report.json`, `drift-history.jsonl` — real drift detection output
- `digest-history.jsonl` — real digest agent runs
- `knowledge-maint-history.jsonl` — real maintenance runs
- `infra-snapshot.json`, `manifest.json` — real infrastructure state
- `briefing.json`, `digest.json`, `scout-report.json`, `operator.json` — real agent outputs
- Qdrant collections — real document embeddings

**Demo data** (synthetic, for hapax-mgmt demo system only):
- Never referenced by integration tests
- Never used to validate query agent behavior

**Test corpus approach:** Curated slices extracted from real profile data via a script, committed to `test-data/`. Not invented fiction.

## Empty-State Contract

When the system has just been deployed and no agents have run yet, every query agent must:

1. State clearly what data is missing
2. Explain what generates that data (which agent or timer, what schedule)
3. Tell the user when to expect it
4. Answer what it can from whatever data IS available

This contract is enforced at three levels:
- **Tool return values** include schedule/source information in empty-state messages (deterministic enforcement of requirements 1-3). For example, `read_briefing()` returns "Daily briefing not available. The briefing agent runs daily at 07:00." rather than just "not available."
- **System prompts** include explicit empty-state instruction blocks with per-data-source availability metadata (LLM-level guidance for composing multi-source answers)
- **Tests** assert that empty-state queries produce responses surfacing limitations, not hollow analysis

### Qdrant Empty State

Qdrant collections may not exist at all on fresh deployment (not just empty). The knowledge agent must distinguish:
- **Collection missing** — explain that sync agents haven't run yet, which ones populate which collections
- **Collection empty** — explain that the collection exists but no documents have been ingested
- **Connection refused** — explain that Qdrant is not running

Each case gets a specific, helpful message rather than a raw error string.

## Category 1: Integration Test Suite

### Test Data Corpus

Two profile directories, both checked into git under `test-data/`:

**`test-data/profiles-populated/`** — Curated slices of real data, extracted from the live system:

| File | Size Target | Content |
|------|-------------|---------|
| `health-history.jsonl` | ~20 entries | Spans healthy, degraded, failed states |
| `drift-report.json` | 3-4 items | High, medium, low severity |
| `drift-history.jsonl` | ~10 entries | Drift count trends over time |
| `digest-history.jsonl` | ~10 entries | Includes multi-line pretty-printed JSON |
| `knowledge-maint-history.jsonl` | ~5 entries | Pruned/merged counts |
| `infra-snapshot.json` | 1 snapshot | Full container, timer, GPU state |
| `manifest.json` | 1 manifest | All sections (docker, systemd, qdrant, etc.) |
| `briefing.json` | 1 briefing | With action items and stats |
| `digest.json` | 1 digest | With notable items |
| `scout-report.json` | 1 report | With recommendations |
| `operator.json` | 1 operator | With active goals |

**`test-data/profiles-empty/`** — Fresh deployment state. Directory exists with only a `.gitkeep` file (git cannot track empty directories).

**`test-data/dev-story-populated.db`** — Small SQLite built from real git history of this repo (~50 commits, ~10 sessions, correlations).

**`test-data/dev-story-empty.db`** — Schema only, zero rows. Created by running the git-extractor schema DDL with no data.

**Extraction script:** `scripts/extract-test-data.py` reads live `profiles/` and `profiles/dev-story.db`, trims to target sizes, writes to `test-data/`. Run manually when test data needs refreshing. The committed output is the test corpus, not the live data.

### Test Suite Structure

```
tests/query_integration/
    __init__.py
    _helpers.py              # shared path constants and builder functions
    test_dev_story.py        # dev-story data pipeline (populated + empty)
    test_system_ops.py       # system-ops data pipeline (populated + empty)
    test_knowledge.py        # knowledge reads + search (populated + empty)
    test_dispatch.py         # classification accuracy (30+ curated queries)
    test_empty_state.py      # dedicated empty-state assertions across all agents
    test_sse_streaming.py    # API SSE event contract
    test_llm_spot.py         # Layer 2: live LLM spot checks (@pytest.mark.llm)
```

### Shared Test Helpers

A helper module `tests/query_integration/_helpers.py` provides path constants and builder functions (not conftest fixtures, consistent with the project's "each test file is self-contained" convention):

```python
"""Shared helpers for query integration tests."""
from pathlib import Path
import sqlite3
from shared.ops_db import build_ops_db

TEST_DATA = Path(__file__).resolve().parent.parent.parent / "test-data"
POPULATED_PROFILES = TEST_DATA / "profiles-populated"
EMPTY_PROFILES = TEST_DATA / "profiles-empty"
POPULATED_DEV_STORY_DB = TEST_DATA / "dev-story-populated.db"
EMPTY_DEV_STORY_DB = TEST_DATA / "dev-story-empty.db"

def make_ops_db(profiles_dir: Path) -> sqlite3.Connection:
    return build_ops_db(profiles_dir)

def open_dev_story_db(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
```

Each test file imports what it needs from `_helpers`. No conftest.py, no global fixtures.

### test_dev_story.py (~15 tests)

Populated state:
- Commit count query returns known count
- Date range filter narrows results correctly
- File change ranking returns expected top files
- Session duration aggregate matches known values
- Author filter works
- Query for nonexistent branch returns empty result set

Empty state:
- All queries against empty db return "No results." not exceptions
- `get_table_schemas()` returns valid DDL even with no data

### test_system_ops.py (~20 tests)

Populated state — SQL queries:
- Health status count by status matches known distribution
- Latest failed run timestamp is correct
- Duration stats (avg, max) are reasonable
- Drift item count by severity matches known values
- Digest headline search finds known entries
- Knowledge maint total pruned/merged matches

Populated state — live tools:
- `get_infra_snapshot()` returns structured text with container/timer/GPU sections
- `get_manifest_section("docker")` returns docker-specific content
- `get_manifest_section("nonexistent")` returns available sections list

Empty state:
- `build_ops_db()` with empty dir creates tables, all queries return "No results."
- All file-based live tools return meaningful "not available" messages when files missing
- `langfuse_cost()` with connection refused returns service-unavailable message (not raw exception)
- `qdrant_stats()` with connection refused returns service-unavailable message

Error paths:
- Malformed JSONL entry in health-history (test `_load_jsonl` skip behavior)
- Truncated/partial JSON in digest-history (test concatenated-object fallback parser)

### test_knowledge.py (~10 tests)

Populated state — file reads:
- `read_briefing()` returns string containing expected sections (action items, stats)
- `read_digest()` returns string with notable items
- `read_scout_report()` returns string with recommendations
- `get_operator_goals()` returns string with active goals

Populated state — search (mocked at Qdrant client level):
- `search_documents()` constructs correct filter payload for source_service
- `search_documents()` constructs correct date filter for days_back
- `search_profile()` passes dimension filter to ProfileStore

Empty state:
- All file read functions return "not available" message with schedule info when files missing
- Search against empty collection returns "No results found" with explanation of what populates the collection
- Search against missing collection returns message explaining which sync agent creates it
- Search with Qdrant connection refused returns service-unavailable message

### test_dispatch.py (~30 queries)

10 curated queries per agent:

Dev Story queries:
- "show me commit history for logos module"
- "what files changed most in the last week"
- "how many sessions were there yesterday"
- "what's the average session duration"
- "show git activity by author"
- "what branches were worked on recently"
- "correlate commits with session length"
- "what was the longest coding session"
- "show me the development timeline"
- "how has the codebase grown over time"

System Ops queries:
- "what is the current health status"
- "which docker containers are running"
- "how much did we spend on LLM costs this week"
- "are there any drift items with high severity"
- "show me the health trend over the last day"
- "what GPU memory is being used"
- "which systemd timers are active"
- "how many qdrant collections exist"
- "what's the infrastructure manifest say about ports"
- "show me degraded health checks"

Knowledge queries:
- "search for documents about API design"
- "what did the briefing say today"
- "find emails from last week about the project"
- "search my obsidian notes for meeting prep"
- "what are my current goals"
- "show me the latest digest"
- "what did the scout report recommend"
- "search my conversation memory for voice pipeline"
- "find documents from google drive about architecture"
- "what does my profile say about communication style"

Ambiguous/edge cases:
- "" (empty) → dev_story (default)
- "tell me everything" → dev_story (default, no keywords)
- "what changed in the infrastructure this week" → system_ops ("infrastructure" keyword match)
- "search commit history in documents" → knowledge ("search" + "document" = 2 hits vs dev_story "commit" + "history" = 2 hits — tests tiebreaker behavior)

### test_empty_state.py (~12 tests)

Dedicated empty-state assertions across all agents. For each agent:

- Build agent with empty profiles dir / empty db
- Call each tool function
- Assert: no exceptions, returns meaningful empty response
- For system prompts: assert empty-state instruction block exists

### test_sse_streaming.py (~5 tests)

Uses httpx ASGI transport against the FastAPI app:

- POST `/api/query/run` with valid query → response is `text/event-stream`
- SSE events follow sequence: `status` event first, then `text_delta` events, then `done` event
- `done` event contains metadata (tokens, elapsed_ms)
- POST with empty query → rejected before streaming (422/400)
- First SSE `status` event has `phase: "querying"` and includes the `agent` type string

### test_llm_spot.py (~8 tests, @pytest.mark.llm)

Skipped by default. Run with `pytest -m llm`. Requires LiteLLM at localhost:4000.

Populated state (2-3 per agent):
- Dev Story: "what files changed most recently" → non-empty markdown, contains file paths
- System Ops: "what's the health trend" → non-empty markdown, contains status words
- Knowledge: "what did the briefing say" → non-empty markdown, contains briefing content

Empty state (2-3 total):
- Dev Story against empty db → markdown explicitly mentions no data / no sessions
- System Ops against empty profiles → markdown explicitly mentions no health data / fresh deployment
- Knowledge against empty profiles → markdown explicitly mentions no briefing available

## Category 2: Existing Test Fixes

### System Prompt Changes (3 agents)

Each agent gets an empty-state instruction block added to its system prompt:

**agents/dev_story/query.py:**
```
## When Data is Unavailable

If the database has no sessions or commits, explain:
- "The dev-story database has not been populated yet"
- "Run the git-extractor agent to build development history: uv run python -m agents.dev_story"
- "After first run, data covers the full git history of the repository"
Do not produce analysis that implies data exists. State what is missing and what generates it.
```

**agents/system_ops/query.py:**
```
## When Data is Unavailable

If tables are empty or files are missing, explain what's missing and what populates it:
- health_runs: "Health monitor runs every 15 minutes (systemd timer). No data until first run."
- drift_items/drift_runs: "Drift detector runs weekly Sunday 03:00. No data until first run."
- digest_runs: "Digest agent runs daily at 06:45. No data until first run."
- knowledge_maint: "Knowledge maintenance runs weekly Sunday 04:30. No data until first run."
- infra-snapshot.json: "Manifest snapshot runs weekly. No snapshot until first run."
- manifest.json: "Infrastructure manifest updated weekly Sunday 02:30."
Do not produce analysis that implies data exists. State what is missing and when to expect it.
```

**agents/knowledge/query.py:**
```
## When Data is Unavailable

If searches return no results or files are missing, explain what's missing:
- documents collection: "RAG sync agents populate this. Run sync agents first (gdrive, gmail, obsidian, etc.)"
- profile-facts: "Profile updater runs every 6 hours. No facts until first run."
- briefing.json: "Daily briefing generates at 07:00. Not available until first run."
- digest.json: "Daily digest generates at 06:45. Not available until first run."
- scout-report.json: "Scout runs weekly Wednesday 10:00. Not available until first run."
- operator.json: "Operator profile updates every 6 hours. Not available until first run."
Do not produce analysis that implies data exists. State what is missing and what generates it.
```

### Existing Test File Backfills

**test_ops_db.py** (3 new tests):
- `test_query_empty_health_runs` — SELECT against empty health_runs returns "No results."
- `test_query_empty_drift_items` — SELECT against empty drift_items returns "No results."
- `test_build_ops_db_counts_zero_when_empty` — verify all counts are 0 with empty profiles dir

**test_knowledge_search.py** (3 new tests):
- `test_search_documents_empty_results` — empty result from Qdrant returns "No results found" message
- `test_search_profile_no_matches` — dimension exists but no matching facts
- `test_search_memory_empty_collection` — empty claude-memory returns "No results found"

**test_knowledge_query.py** (1 new test):
- `test_prompt_includes_empty_state_guidance` — verify system prompt contains "When Data is Unavailable"

**test_system_ops_query.py** (1 new test):
- `test_prompt_includes_empty_state_guidance` — verify system prompt contains "When Data is Unavailable"

**tests/dev_story/test_query.py** (2 new tests):
- `test_sql_query_empty_sessions` — SELECT on empty sessions table
- `test_file_history_no_data` — file_history with empty correlations table

**tests/dev_story/test_query_prompt.py** (1 new test):
- `test_prompt_includes_empty_state_guidance` — verify prompt contains empty-database instruction

**test_query_api.py** (3 new tests):
- `test_run_returns_sse_events_in_order` — parse actual SSE stream, verify status→text_delta→done sequence
- `test_run_empty_result_still_streams` — agent returns empty markdown, SSE still completes with done event
- `test_refine_empty_state` — refinement with empty prior_result and agent that has no data

**test_query_dispatch.py** (2 new tests):
- `test_classify_ambiguous_infrastructure_query` — "what changed in infrastructure" routes to system_ops
- `test_classify_no_match_defaults_to_dev_story` — queries with zero keyword overlap

### Bug Fix: dev-story.db Filename Mismatch

Pre-existing bug discovered during audit: `cockpit/query_dispatch.py:95` looks for `dev_story.db` (snake_case) but the git-extractor writes to `dev-story.db` (kebab-case, matching project naming conventions). Fix: change line 95 to `PROFILES_DIR / "dev-story.db"`. This is a prerequisite for integration tests to work against real data.

## Category 3: hapax-logos Test Foundation

### Setup

Install vitest + testing-library + jsdom in hapax-logos:

```bash
pnpm add -D vitest @testing-library/react @testing-library/jest-dom jsdom @testing-library/user-event
```

Add to `vite.config.ts`:
```typescript
test: {
  environment: 'jsdom',
  setupFiles: './src/test-setup.ts',
}
```

Add `"test": "vitest"` to package.json scripts.

### Test Files

```
hapax-logos/src/
    test-setup.ts                              # jsdom + testing-library setup
    pages/__tests__/InsightPage.test.tsx        # page-level tests
    components/insight/__tests__/
        QueryResult.test.tsx                    # result rendering
        QueryInput.test.tsx                     # input behavior
    api/__tests__/sse.test.ts                   # SSE client unit tests
```

### InsightPage.test.tsx (~8 tests)

- Renders placeholder when no results exist
- Renders query input
- Submitting a query shows loading state
- Receiving SSE text_delta events builds up result markdown
- Receiving done event stops loading, shows result
- Receiving error event shows error message
- Multiple queries accumulate in result list
- Empty markdown from agent still renders (no crash)

### QueryResult.test.tsx (~5 tests)

- Renders markdown content
- Renders mermaid blocks (code block with mermaid language tag present)
- Renders agent type badge
- Renders token/timing metadata
- Handles empty markdown string (no crash, meaningful display)

### QueryInput.test.tsx (~4 tests)

- Submits on Enter key
- Submit button disabled when input empty
- Submit button disabled during loading
- Input clears after submit

### sse.test.ts (~4 tests)

- `connectSSE` calls fetch with correct URL and body
- Parses SSE events correctly (event: type, data: json)
- Calls onEvent for each parsed event
- Calls onDone when stream ends

## Extraction Script

`scripts/extract-test-data.py`:

```python
"""Extract curated test data slices from live profiles."""
# Reads profiles/health-history.jsonl → takes last 20 entries
# Reads profiles/drift-report.json → copies as-is (small)
# Reads profiles/drift-history.jsonl → takes last 10 entries
# Reads profiles/digest-history.jsonl → takes last 10 entries
# Reads profiles/knowledge-maint-history.jsonl → takes last 5 entries
# Copies infra-snapshot.json, manifest.json, briefing.json, digest.json,
#   scout-report.json, operator.json as-is
# Creates dev-story-populated.db: copies profiles/dev-story.db,
#   then prunes with PRAGMA foreign_keys=OFF, deletes in dependency order
#   (correlations → session_metrics → session_tags → critical_moments →
#    messages → tool_calls → file_changes → sessions), keeping most recent
#   50 commits and 10 sessions, then VACUUM to reclaim space
# Creates dev-story-empty.db: schema only from git_extractor DDL
# Creates profiles-empty/ with .gitkeep
# Validates schema compatibility: runs PRAGMA table_info on each table in
#   both live and test DBs, warns if columns differ (catches schema drift)
```

## Test Markers

```ini
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "llm: tests that require live LLM access via LiteLLM (deselect with '-m not llm')",
    "integration: integration tests using real data patterns (test-data/)",
]
```

Default `pytest` runs everything except `llm`. `pytest -m llm` runs live LLM spot checks.

## Sequencing

1. Bug fix: dev-story.db filename mismatch in query_dispatch.py
2. Extraction script + test data corpus (foundation)
3. System prompt empty-state instructions (3 agents) + tool return value enrichment
4. Existing test backfills (8 files, ~16 new tests)
5. Integration test suite (7 files, ~95 new tests)
6. hapax-logos test foundation (setup + 4 files, ~21 tests)
7. LLM spot checks (last, depends on everything else)
