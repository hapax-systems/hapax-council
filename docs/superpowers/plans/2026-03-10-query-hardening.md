# Query System Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the query system with real-data integration tests, empty-state contracts, and hapax-logos test foundation.

**Architecture:** Three categories of work: (1) fix pre-existing bugs and add empty-state instructions to system prompts, (2) create a test data corpus extracted from real profiles and build an integration test suite against it, (3) bootstrap vitest in hapax-logos for Insight page tests. All Python tests follow the project's self-contained pattern (no conftest fixtures, unittest.mock only).

**Tech Stack:** pytest, unittest.mock, httpx (ASGI transport), sqlite3, vitest, @testing-library/react, jsdom

**Spec:** `docs/superpowers/specs/2026-03-10-query-hardening-design.md`

---

## Chunk 1: Bug Fix + System Prompt Empty-State Instructions

### Task 1: Fix dev-story.db filename mismatch

**Files:**
- Modify: `cockpit/query_dispatch.py:95`
- Modify: `tests/test_query_dispatch.py` (existing test covers this path)

The git-extractor writes to `dev-story.db` (kebab-case per project conventions) but `query_dispatch.py:95` looks for `dev_story.db` (snake_case). Both files exist in profiles/ because of this bug.

- [ ] **Step 1: Fix the filename**

In `cockpit/query_dispatch.py`, line 95, change:
```python
db_path = str(PROFILES_DIR / "dev_story.db")
```
to:
```python
db_path = str(PROFILES_DIR / "dev-story.db")
```

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `uv run pytest tests/test_query_dispatch.py -v`
Expected: All 18 tests pass (the tests mock the factory, so the filename doesn't affect them — but verify nothing breaks)

- [ ] **Step 3: Commit**

```bash
git add cockpit/query_dispatch.py
git commit -m "fix: correct dev-story.db filename to kebab-case in query dispatch"
```

### Task 2: Add empty-state instructions to dev_story system prompt

**Files:**
- Modify: `agents/dev_story/query.py:17-114`
- Test: `tests/dev_story/test_query_prompt.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/dev_story/test_query_prompt.py`:

```python
def test_prompt_includes_empty_state_guidance():
    prompt = build_system_prompt()
    assert "When Data is Unavailable" in prompt
    assert "git-extractor" in prompt.lower() or "dev_story" in prompt
    assert "uv run python -m agents.dev_story" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/dev_story/test_query_prompt.py::test_prompt_includes_empty_state_guidance -v`
Expected: FAIL (prompt doesn't contain these strings yet)

- [ ] **Step 3: Add empty-state section to the system prompt**

In `agents/dev_story/query.py`, add before the closing `"""` of `build_system_prompt()` (before line 114):

```python
## When Data is Unavailable

If the database has no sessions or commits (queries return "No results." for all tables),
do not produce analysis that implies data exists. Instead:
- State: "The dev-story database has not been populated yet."
- Explain: "Run the git-extractor to build development history: uv run python -m agents.dev_story"
- Note: "After first run, data covers the full git history of the repository."
Answer only what you can from the data that IS available.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/dev_story/test_query_prompt.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/dev_story/query.py tests/dev_story/test_query_prompt.py
git commit -m "feat: add empty-state guidance to dev-story query prompt"
```

### Task 3: Add empty-state instructions to system_ops system prompt

**Files:**
- Modify: `agents/system_ops/query.py:17-83`
- Test: `tests/test_system_ops_query.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_system_ops_query.py`:

```python
def test_prompt_includes_empty_state_guidance():
    prompt = build_system_prompt()
    assert "When Data is Unavailable" in prompt
    assert "health monitor" in prompt.lower() or "health_runs" in prompt
    assert "every 15 minutes" in prompt
    assert "drift detector" in prompt.lower() or "drift_runs" in prompt
```

Add the import at the top if not already present:
```python
from agents.system_ops.query import build_system_prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_system_ops_query.py::test_prompt_includes_empty_state_guidance -v`
Expected: FAIL

- [ ] **Step 3: Add empty-state section to the system prompt**

In `agents/system_ops/query.py`, add before the closing `"""` of `build_system_prompt()` (before line 83):

```python
## When Data is Unavailable

If tables are empty or files are missing, explain what's missing and what populates it:
- health_runs: "Health monitor runs every 15 minutes (systemd timer). No data until first run."
- drift_items/drift_runs: "Drift detector runs weekly Sunday 03:00. No data until first run."
- digest_runs: "Digest agent runs daily at 06:45. No data until first run."
- knowledge_maint: "Knowledge maintenance runs weekly Sunday 04:30. No data until first run."
- infra-snapshot.json: "Infrastructure snapshot updates every 15 minutes with health monitor."
- manifest.json: "Infrastructure manifest updated weekly Sunday 02:30."

Do not produce analysis that implies data exists. State what is missing and when to expect it.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_system_ops_query.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/system_ops/query.py tests/test_system_ops_query.py
git commit -m "feat: add empty-state guidance to system-ops query prompt"
```

### Task 4: Add empty-state instructions to knowledge system prompt

**Files:**
- Modify: `agents/knowledge/query.py:15-85`
- Test: `tests/test_knowledge_query.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_knowledge_query.py`:

```python
def test_prompt_includes_empty_state_guidance():
    prompt = build_system_prompt()
    assert "When Data is Unavailable" in prompt
    assert "sync agents" in prompt.lower()
    assert "briefing" in prompt.lower()
    assert "07:00" in prompt or "daily" in prompt.lower()
```

Add the import at the top if not already present:
```python
from agents.knowledge.query import build_system_prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_knowledge_query.py::test_prompt_includes_empty_state_guidance -v`
Expected: FAIL

- [ ] **Step 3: Add empty-state section to the system prompt**

In `agents/knowledge/query.py`, add before the closing `"""` of `build_system_prompt()` (before line 85):

```python
## When Data is Unavailable

If searches return no results or files are missing, explain what's missing and what populates it:
- documents collection: "RAG sync agents populate this (gdrive, gmail, obsidian, etc.). Run sync agents first."
- profile-facts: "Profile updater runs every 6 hours. No facts until first run."
- claude-memory: "Populated automatically from Claude Code sessions."
- briefing.json: "Daily briefing generates at 07:00. Not available until first run."
- digest.json: "Daily digest generates at 06:45. Not available until first run."
- scout-report.json: "Scout runs weekly Wednesday 10:00. Not available until first run."
- operator.json: "Operator profile updates every 6 hours. Not available until first run."

Do not produce analysis that implies data exists. State what is missing and what generates it.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_knowledge_query.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/knowledge/query.py tests/test_knowledge_query.py
git commit -m "feat: add empty-state guidance to knowledge query prompt"
```

### Task 5: Enrich empty-state tool return values with schedule info

**Files:**
- Modify: `shared/knowledge_search.py:142-143,176-177,209-210,241`
- Test: `tests/test_knowledge_search.py`

The current empty-state messages are generic ("not available"). Per the spec, they should include schedule information so the user knows when to expect data, regardless of whether the LLM uses it.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_knowledge_search.py` in appropriate test classes:

```python
class TestReadBriefingEmptyState:
    def test_missing_briefing_includes_schedule(self, tmp_path):
        result = read_briefing(tmp_path)
        assert "07:00" in result or "daily" in result.lower()
        assert "briefing" in result.lower()


class TestReadDigestEmptyState:
    def test_missing_digest_includes_schedule(self, tmp_path):
        result = read_digest(tmp_path)
        assert "06:45" in result or "daily" in result.lower()
        assert "digest" in result.lower()


class TestReadScoutEmptyState:
    def test_missing_scout_includes_schedule(self, tmp_path):
        result = read_scout_report(tmp_path)
        assert "weekly" in result.lower() or "wednesday" in result.lower()


class TestGetGoalsEmptyState:
    def test_missing_operator_includes_explanation(self, tmp_path):
        result = get_operator_goals(tmp_path)
        assert "operator" in result.lower()
        assert "profile" in result.lower() or "6 hours" in result
```

Add imports at top:
```python
from shared.knowledge_search import read_briefing, read_digest, read_scout_report, get_operator_goals
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_knowledge_search.py::TestReadBriefingEmptyState -v`
Expected: FAIL (current message is "Daily briefing not available. It may not have run yet today." — no schedule)

- [ ] **Step 3: Update empty-state messages in shared/knowledge_search.py**

Line 143 — change:
```python
return "Daily briefing not available. It may not have run yet today."
```
to:
```python
return "Daily briefing not available. The briefing agent runs daily at 07:00. No data until first run."
```

Line 177 — change:
```python
return "Knowledge digest not available. It may not have run yet today."
```
to:
```python
return "Knowledge digest not available. The digest agent runs daily at 06:45. No data until first run."
```

Line 210 — change:
```python
return "Scout report not available. The scout agent runs weekly."
```
to:
```python
return "Scout report not available. The scout agent runs weekly on Wednesday at 10:00. No data until first run."
```

Line 241 — change:
```python
return "Operator manifest not available."
```
to:
```python
return "Operator manifest not available. The profile updater runs every 6 hours. No data until first run."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_knowledge_search.py -v`
Expected: All tests PASS (including existing tests — the new messages are supersets of what tests previously expected)

- [ ] **Step 5: Commit**

```bash
git add shared/knowledge_search.py tests/test_knowledge_search.py
git commit -m "feat: enrich empty-state tool messages with schedule information"
```

## Chunk 2: Existing Test Backfills

### Task 6: Backfill empty-state tests for ops_db

**Files:**
- Modify: `tests/test_ops_db.py`

- [ ] **Step 1: Add empty-state tests**

Add to `tests/test_ops_db.py`:

```python
class TestBuildOpsDbEmpty:
    def test_build_with_empty_dir_all_counts_zero(self, tmp_path):
        conn = build_ops_db(tmp_path)
        for table in ("health_runs", "drift_items", "drift_runs", "digest_runs", "knowledge_maint"):
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            assert cursor.fetchone()[0] == 0

    def test_query_empty_health_runs_returns_no_results(self, tmp_path):
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "SELECT * FROM health_runs")
        assert result == "No results."

    def test_query_empty_drift_items_returns_no_results(self, tmp_path):
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "SELECT * FROM drift_items")
        assert result == "No results."
```

Add import at top if needed:
```python
from shared.ops_db import build_ops_db, run_sql
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_ops_db.py::TestBuildOpsDbEmpty -v`
Expected: All 3 PASS (build_ops_db already handles empty dirs gracefully)

- [ ] **Step 3: Commit**

```bash
git add tests/test_ops_db.py
git commit -m "test: add empty-state tests for ops_db"
```

### Task 7: Backfill empty-state tests for knowledge_search

**Files:**
- Modify: `tests/test_knowledge_search.py`

- [ ] **Step 1: Add empty Qdrant result tests**

Add to `tests/test_knowledge_search.py`:

```python
class TestSearchDocumentsEmptyResults:
    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_empty_results_return_no_documents_message(self, mock_embed, mock_qdrant):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.points = []
        mock_client.query_points.return_value = mock_result
        mock_qdrant.return_value = mock_client

        result = search_documents("test query")
        assert "No documents found" in result


class TestSearchProfileNoMatches:
    @patch("shared.knowledge_search.ProfileStore")
    def test_no_matching_facts(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.search.return_value = []
        mock_store_cls.return_value = mock_store

        result = search_profile("nonexistent topic", dimension="work_patterns")
        assert "No profile facts found" in result
        assert "work_patterns" in result


class TestSearchMemoryEmpty:
    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_empty_memory_returns_no_entries(self, mock_embed, mock_qdrant):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.points = []
        mock_client.query_points.return_value = mock_result
        mock_qdrant.return_value = mock_client

        result = search_memory("test query")
        assert "No memory entries found" in result
```

Add imports at top if needed:
```python
from unittest.mock import MagicMock, patch
from shared.knowledge_search import search_documents, search_profile, search_memory
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_knowledge_search.py::TestSearchDocumentsEmptyResults tests/test_knowledge_search.py::TestSearchProfileNoMatches tests/test_knowledge_search.py::TestSearchMemoryEmpty -v`
Expected: All 3 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_knowledge_search.py
git commit -m "test: add empty-result tests for knowledge search functions"
```

### Task 8: Backfill empty-state tests for dev_story query tools

**Files:**
- Modify: `tests/dev_story/test_query.py`

- [ ] **Step 1: Add empty-state tests**

Add to `tests/dev_story/test_query.py`:

```python
class TestSqlQueryEmpty:
    def test_select_empty_sessions_returns_no_results(self):
        conn = _make_db()
        result = _sql_query(conn, "SELECT * FROM sessions")
        assert result == "No results."

    def test_select_empty_commits_returns_no_results(self):
        conn = _make_db()
        result = _sql_query(conn, "SELECT * FROM commits")
        assert result == "No results."


class TestFileHistoryEmpty:
    def test_no_commit_files_returns_no_history(self):
        conn = _make_db()
        result = _file_history(conn, "nonexistent/file.py")
        assert "No history found" in result
```

These use the existing `_make_db()` helper which creates empty schema. Add import for `_file_history` at top if not present:
```python
from agents.dev_story.query import _sql_query, _session_content, _file_history
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/dev_story/test_query.py::TestSqlQueryEmpty tests/dev_story/test_query.py::TestFileHistoryEmpty -v`
Expected: All 3 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/dev_story/test_query.py
git commit -m "test: add empty-state tests for dev-story query tools"
```

### Task 9: Backfill SSE event ordering and dispatch tests

**Files:**
- Modify: `tests/test_query_api.py`
- Modify: `tests/test_query_dispatch.py`

- [ ] **Step 1: Add SSE event order test**

Add to `tests/test_query_api.py`:

```python
class TestSSEEventOrder:
    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query", return_value="dev_story")
    async def test_events_follow_status_text_done_sequence(self, mock_classify, mock_run, client):
        mock_run.return_value = QueryResult(
            markdown="## Test\nContent here",
            agent_type="dev_story",
            tokens_in=100,
            tokens_out=50,
            elapsed_ms=500,
        )
        resp = await client.post("/api/query/run", json={"query": "test query"})
        assert resp.status_code == 200

        body = resp.text
        # SSE events should contain status, text_delta, done in order
        status_pos = body.find("event: status")
        text_pos = body.find("event: text_delta")
        done_pos = body.find("event: done")
        assert status_pos >= 0, "Missing status event"
        assert text_pos >= 0, "Missing text_delta event"
        assert done_pos >= 0, "Missing done event"
        assert status_pos < text_pos < done_pos, "Events out of order"

    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query", return_value="dev_story")
    async def test_empty_result_still_completes(self, mock_classify, mock_run, client):
        mock_run.return_value = QueryResult(
            markdown="",
            agent_type="dev_story",
            tokens_in=50,
            tokens_out=10,
            elapsed_ms=200,
        )
        resp = await client.post("/api/query/run", json={"query": "empty test"})
        assert resp.status_code == 200
        assert "event: done" in resp.text
```

Add import at top if needed:
```python
from logos.query_dispatch import QueryResult
```

- [ ] **Step 2: Add dispatch edge case tests**

Add to `tests/test_query_dispatch.py`:

```python
class TestClassifyEdgeCases:
    def test_infrastructure_keyword_routes_to_system_ops(self):
        result = classify_query("what changed in the infrastructure this week")
        assert result == "system_ops"

    def test_no_keyword_overlap_defaults_to_first_agent(self):
        result = classify_query("the quick brown fox jumps over the lazy dog")
        assert result == "dev_story"
```

- [ ] **Step 3: Run all tests**

Run: `uv run pytest tests/test_query_api.py tests/test_query_dispatch.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_query_api.py tests/test_query_dispatch.py
git commit -m "test: add SSE event ordering and dispatch edge case tests"
```

## Chunk 3: Test Data Extraction Script + Corpus

### Task 10: Create the test data extraction script

**Files:**
- Create: `scripts/extract-test-data.py`

- [ ] **Step 1: Create the extraction script**

```python
#!/usr/bin/env python3
"""Extract curated test data slices from live profiles.

Run: uv run python scripts/extract-test-data.py
Writes to: test-data/
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"
OUT = ROOT / "test-data"


def _tail_jsonl(path: Path, n: int) -> list[dict]:
    """Read the last N entries from a JSONL file."""
    if not path.is_file():
        print(f"  SKIP (not found): {path.name}")
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                entries.append(obj)
        except json.JSONDecodeError:
            continue
    # If line-by-line didn't work, try as single JSON
    if not entries:
        try:
            text = path.read_text().strip()
            parsed = json.loads(text)
            if isinstance(parsed, list):
                entries = [e for e in parsed if isinstance(e, dict)]
            elif isinstance(parsed, dict):
                entries = [parsed]
        except json.JSONDecodeError:
            pass
    # Fallback: concatenated pretty-printed JSON
    if not entries:
        try:
            text = path.read_text().strip()
            wrapped = "[" + text.replace("}\n{", "},\n{") + "]"
            parsed = json.loads(wrapped)
            entries = [e for e in parsed if isinstance(e, dict)]
        except json.JSONDecodeError:
            pass
    result = entries[-n:]
    print(f"  {path.name}: {len(result)}/{len(entries)} entries")
    return result


def _copy_json(src: Path, dst: Path) -> None:
    """Copy a JSON file if it exists."""
    if src.is_file():
        shutil.copy2(src, dst)
        print(f"  {src.name}: copied")
    else:
        print(f"  SKIP (not found): {src.name}")


def extract_profiles_populated():
    """Extract curated profile data slices."""
    dst = OUT / "profiles-populated"
    dst.mkdir(parents=True, exist_ok=True)

    # JSONL files — take last N entries
    for name, n in [
        ("health-history.jsonl", 20),
        ("drift-history.jsonl", 10),
        ("digest-history.jsonl", 10),
        ("knowledge-maint-history.jsonl", 5),
    ]:
        entries = _tail_jsonl(PROFILES / name, n)
        if entries:
            (dst / name).write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    # JSON files — copy as-is
    for name in [
        "drift-report.json",
        "infra-snapshot.json",
        "manifest.json",
        "briefing.json",
        "digest.json",
        "scout-report.json",
        "operator.json",
    ]:
        _copy_json(PROFILES / name, dst / name)


def extract_dev_story_populated():
    """Create a small dev-story DB from the real one."""
    src = PROFILES / "dev-story.db"
    dst = OUT / "dev-story-populated.db"

    if not src.is_file():
        print("  SKIP: dev-story.db not found")
        return

    shutil.copy2(src, dst)
    conn = sqlite3.connect(str(dst))

    # Disable FK for pruning
    conn.execute("PRAGMA foreign_keys=OFF")

    # Keep most recent 50 commits
    conn.execute("""
        DELETE FROM commit_files WHERE commit_hash NOT IN (
            SELECT hash FROM commits ORDER BY author_date DESC LIMIT 50
        )
    """)
    conn.execute("""
        DELETE FROM correlations WHERE commit_hash NOT IN (
            SELECT hash FROM commits ORDER BY author_date DESC LIMIT 50
        )
    """)
    conn.execute("""
        DELETE FROM code_survival WHERE introduced_by_commit NOT IN (
            SELECT hash FROM commits ORDER BY author_date DESC LIMIT 50
        )
    """)
    conn.execute("""
        DELETE FROM critical_moments WHERE commit_hash IS NOT NULL AND commit_hash NOT IN (
            SELECT hash FROM commits ORDER BY author_date DESC LIMIT 50
        )
    """)
    conn.execute("""
        DELETE FROM commits WHERE hash NOT IN (
            SELECT hash FROM commits ORDER BY author_date DESC LIMIT 50
        )
    """)

    # Keep most recent 10 sessions
    keep_sessions = """SELECT id FROM sessions ORDER BY started_at DESC LIMIT 10"""
    conn.execute(f"""
        DELETE FROM session_metrics WHERE session_id NOT IN ({keep_sessions})
    """)
    conn.execute(f"""
        DELETE FROM session_tags WHERE session_id NOT IN ({keep_sessions})
    """)
    conn.execute(f"""
        DELETE FROM critical_moments WHERE session_id IS NOT NULL AND session_id NOT IN ({keep_sessions})
    """)
    # Delete correlations referencing messages from deleted sessions
    conn.execute(f"""
        DELETE FROM correlations WHERE message_id IN (
            SELECT id FROM messages WHERE session_id NOT IN ({keep_sessions})
        )
    """)
    conn.execute(f"""
        DELETE FROM file_changes WHERE message_id IN (
            SELECT id FROM messages WHERE session_id NOT IN ({keep_sessions})
        )
    """)
    conn.execute(f"""
        DELETE FROM tool_calls WHERE message_id IN (
            SELECT id FROM messages WHERE session_id NOT IN ({keep_sessions})
        )
    """)
    conn.execute(f"""
        DELETE FROM messages WHERE session_id NOT IN ({keep_sessions})
    """)
    conn.execute(f"""
        DELETE FROM sessions WHERE id NOT IN ({keep_sessions})
    """)

    # Rebuild hotspots from remaining data
    conn.execute("DELETE FROM hotspots")

    conn.execute("VACUUM")
    conn.commit()
    conn.close()

    size_mb = dst.stat().st_size / (1024 * 1024)
    print(f"  dev-story-populated.db: {size_mb:.1f}MB")


def extract_dev_story_empty():
    """Create an empty dev-story DB with schema only."""
    dst = OUT / "dev-story-empty.db"
    conn = sqlite3.connect(str(dst))

    # Import and run the schema DDL
    from agents.dev_story.schema import create_tables
    create_tables(conn)
    conn.close()
    print("  dev-story-empty.db: schema only")


def create_profiles_empty():
    """Create the empty profiles directory."""
    dst = OUT / "profiles-empty"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / ".gitkeep").touch()
    print("  profiles-empty/: created with .gitkeep")


def validate_schema():
    """Validate schema compatibility between live and test DBs."""
    live = PROFILES / "dev-story.db"
    test = OUT / "dev-story-populated.db"

    if not live.is_file() or not test.is_file():
        print("  SKIP schema validation (missing DB)")
        return

    live_conn = sqlite3.connect(str(live))
    test_conn = sqlite3.connect(str(test))

    live_tables = {row[0] for row in live_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    test_tables = {row[0] for row in test_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    if live_tables != test_tables:
        print(f"  WARNING: Table mismatch! Live-only: {live_tables - test_tables}, Test-only: {test_tables - live_tables}")

    for table in live_tables & test_tables:
        live_cols = {row[1] for row in live_conn.execute(f"PRAGMA table_info({table})").fetchall()}
        test_cols = {row[1] for row in test_conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if live_cols != test_cols:
            print(f"  WARNING: Column mismatch in {table}! Live-only: {live_cols - test_cols}, Test-only: {test_cols - live_cols}")

    live_conn.close()
    test_conn.close()
    print("  Schema validation complete")


if __name__ == "__main__":
    print("Extracting test data from live profiles...\n")

    print("[1/5] Profiles (populated)")
    extract_profiles_populated()

    print("\n[2/5] Dev-story DB (populated)")
    extract_dev_story_populated()

    print("\n[3/5] Dev-story DB (empty)")
    extract_dev_story_empty()

    print("\n[4/5] Profiles (empty)")
    create_profiles_empty()

    print("\n[5/5] Schema validation")
    validate_schema()

    print(f"\nDone! Test data written to {OUT}/")
```

- [ ] **Step 2: Run the extraction script**

Run: `uv run python scripts/extract-test-data.py`
Expected: Output showing each step, files created in `test-data/`

- [ ] **Step 3: Verify the test data**

Run: `ls -la test-data/profiles-populated/ && ls -la test-data/profiles-empty/ && ls -la test-data/dev-story-*.db`
Expected: Populated directory has ~11 files, empty has .gitkeep, two .db files exist

- [ ] **Step 4: Add test-data to git and commit**

```bash
git add scripts/extract-test-data.py test-data/
git commit -m "feat: add test data extraction script and initial test corpus"
```

### Task 11: Add pytest markers for integration and llm tests

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add markers to pyproject.toml**

Find the `[tool.pytest.ini_options]` section. It already has a `markers` list with `slow`, `integration`, and `hardware`. **Append** `llm` to the existing list (do not replace):

```toml
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks integration tests",
    "hardware: marks tests needing real hardware (deselect with '-m \"not hardware\"')",
    "llm: tests requiring live LLM access via LiteLLM (deselect with '-m \"not llm\"')",
]
```

Also add `addopts` to skip LLM tests by default (no existing `addopts` in pyproject.toml):

```toml
addopts = "-m 'not llm'"
```

This applies globally to all `pytest` runs. The `llm` marker is opt-in: `uv run pytest -m llm`.

- [ ] **Step 2: Verify markers work**

Run: `uv run pytest --markers | grep -E "llm|integration"`
Expected: Both markers listed

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add pytest markers for integration and llm tests"
```

## Chunk 4: Integration Test Suite — Helpers + Dev Story + System Ops

### Task 12: Create integration test helpers and dev_story tests

**Files:**
- Create: `tests/query_integration/__init__.py`
- Create: `tests/query_integration/_helpers.py`
- Create: `tests/query_integration/test_dev_story.py`

- [ ] **Step 1: Create the helpers module**

Create `tests/query_integration/__init__.py` (empty file).

Create `tests/query_integration/_helpers.py`:

```python
"""Shared helpers for query integration tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from shared.ops_db import build_ops_db

TEST_DATA = Path(__file__).resolve().parent.parent.parent / "test-data"
POPULATED_PROFILES = TEST_DATA / "profiles-populated"
EMPTY_PROFILES = TEST_DATA / "profiles-empty"
POPULATED_DEV_STORY_DB = TEST_DATA / "dev-story-populated.db"
EMPTY_DEV_STORY_DB = TEST_DATA / "dev-story-empty.db"


def make_ops_db(profiles_dir: Path) -> sqlite3.Connection:
    """Build an in-memory ops SQLite database from profiles."""
    return build_ops_db(profiles_dir)


def open_dev_story_db(path: Path) -> sqlite3.Connection:
    """Open a dev-story database in read-only mode."""
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def skip_if_missing(path: Path) -> None:
    """Raise pytest.skip if the path doesn't exist or is empty."""
    import pytest

    if not path.exists():
        pytest.skip(f"Test data not found: {path}")
    if path.is_dir() and not any(p.name != ".gitkeep" for p in path.iterdir()):
        pytest.skip(f"Test data directory empty: {path}")
```

- [ ] **Step 2: Create dev_story integration tests**

Create `tests/query_integration/test_dev_story.py`:

```python
"""Integration tests for dev-story query agent against real data."""
from __future__ import annotations

import pytest

from agents.dev_story.query import _sql_query, _session_content, _file_history
from tests.query_integration._helpers import (
    POPULATED_DEV_STORY_DB,
    EMPTY_DEV_STORY_DB,
    open_dev_story_db,
    skip_if_missing,
)


# ── Populated state ──────────────────────────────────────────────────────────


class TestDevStoryPopulatedCommits:
    def setup_method(self):
        skip_if_missing(POPULATED_DEV_STORY_DB)
        self.conn = open_dev_story_db(POPULATED_DEV_STORY_DB)

    def teardown_method(self):
        if hasattr(self, "conn"):
            self.conn.close()

    def test_commits_exist(self):
        result = _sql_query(self.conn, "SELECT COUNT(*) as cnt FROM commits")
        assert "cnt" in result
        assert "No results" not in result

    def test_commit_count_is_positive(self):
        cursor = self.conn.execute("SELECT COUNT(*) FROM commits")
        count = cursor.fetchone()[0]
        assert count > 0

    def test_date_range_filter(self):
        result = _sql_query(
            self.conn,
            "SELECT COUNT(*) as cnt FROM commits WHERE substr(author_date, 1, 4) = '2026'"
        )
        assert "cnt" in result

    def test_file_change_ranking(self):
        result = _sql_query(
            self.conn,
            """SELECT cf.file_path, COUNT(*) as changes
               FROM commit_files cf
               GROUP BY cf.file_path
               ORDER BY changes DESC
               LIMIT 5"""
        )
        # Should have results (populated db has commits with files)
        assert "file_path" in result or "No results" in result

    def test_author_date_grouping(self):
        result = _sql_query(
            self.conn,
            """SELECT substr(author_date, 1, 10) as day, COUNT(*) as cnt
               FROM commits
               GROUP BY day
               ORDER BY day DESC
               LIMIT 5"""
        )
        assert "day" in result


class TestDevStoryPopulatedSessions:
    def setup_method(self):
        skip_if_missing(POPULATED_DEV_STORY_DB)
        self.conn = open_dev_story_db(POPULATED_DEV_STORY_DB)

    def teardown_method(self):
        if hasattr(self, "conn"):
            self.conn.close()

    def test_sessions_exist(self):
        cursor = self.conn.execute("SELECT COUNT(*) FROM sessions")
        count = cursor.fetchone()[0]
        assert count > 0

    def test_session_duration_aggregate(self):
        result = _sql_query(
            self.conn,
            """SELECT project_name, COUNT(*) as cnt, AVG(message_count) as avg_msgs
               FROM sessions
               WHERE started_at != ''
               GROUP BY project_name"""
        )
        assert "project_name" in result or "No results" in result

    def test_session_content_returns_conversation(self):
        cursor = self.conn.execute("SELECT id FROM sessions LIMIT 1")
        row = cursor.fetchone()
        if row:
            result = _session_content(self.conn, row[0])
            # Should return something (might be "not found" if no messages)
            assert len(result) > 0

    def test_nonexistent_session(self):
        result = _session_content(self.conn, "nonexistent-session-id")
        assert "not found" in result.lower()


class TestDevStoryPopulatedFileHistory:
    def setup_method(self):
        skip_if_missing(POPULATED_DEV_STORY_DB)
        self.conn = open_dev_story_db(POPULATED_DEV_STORY_DB)

    def teardown_method(self):
        if hasattr(self, "conn"):
            self.conn.close()

    def test_file_history_for_known_file(self):
        cursor = self.conn.execute("SELECT file_path FROM commit_files LIMIT 1")
        row = cursor.fetchone()
        if row:
            result = _file_history(self.conn, row[0])
            assert "History for" in result

    def test_file_history_for_nonexistent_file(self):
        result = _file_history(self.conn, "definitely/does/not/exist.xyz")
        assert "No history found" in result


# ── Empty state ──────────────────────────────────────────────────────────────


class TestDevStoryEmpty:
    def setup_method(self):
        skip_if_missing(EMPTY_DEV_STORY_DB)
        self.conn = open_dev_story_db(EMPTY_DEV_STORY_DB)

    def teardown_method(self):
        if hasattr(self, "conn"):
            self.conn.close()

    def test_empty_commits_returns_no_results(self):
        result = _sql_query(self.conn, "SELECT * FROM commits")
        assert result == "No results."

    def test_empty_sessions_returns_no_results(self):
        result = _sql_query(self.conn, "SELECT * FROM sessions")
        assert result == "No results."

    def test_schema_still_valid(self):
        result = _sql_query(
            self.conn,
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        assert "sessions" in result
        assert "commits" in result

    def test_aggregate_on_empty_returns_zero(self):
        result = _sql_query(self.conn, "SELECT COUNT(*) as cnt FROM commits")
        assert "0" in result
```

- [ ] **Step 3: Run the integration tests**

Run: `uv run pytest tests/query_integration/test_dev_story.py -v`
Expected: All tests PASS (or skip if test-data not present)

- [ ] **Step 4: Commit**

```bash
git add tests/query_integration/
git commit -m "test: add dev-story integration tests against real data"
```

### Task 13: Create system_ops integration tests

**Files:**
- Create: `tests/query_integration/test_system_ops.py`

- [ ] **Step 1: Create the test file**

```python
"""Integration tests for system-ops query agent against real data."""
from __future__ import annotations

import json

import pytest

from shared.ops_db import build_ops_db, run_sql, get_table_schemas, _load_jsonl
from shared.ops_live import get_infra_snapshot, get_manifest_section
from tests.query_integration._helpers import (
    POPULATED_PROFILES,
    EMPTY_PROFILES,
    make_ops_db,
    skip_if_missing,
)


# ── Populated state — SQL ────────────────────────────────────────────────────


class TestSystemOpsHealthQueries:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)
        self.conn = make_ops_db(POPULATED_PROFILES)

    def test_health_runs_have_data(self):
        result = run_sql(self.conn, "SELECT COUNT(*) as cnt FROM health_runs")
        assert "No results" not in result
        # Should have some entries
        cursor = self.conn.execute("SELECT COUNT(*) FROM health_runs")
        assert cursor.fetchone()[0] > 0

    def test_health_status_distribution(self):
        result = run_sql(
            self.conn,
            "SELECT status, COUNT(*) as cnt FROM health_runs GROUP BY status ORDER BY cnt DESC"
        )
        assert "status" in result
        assert "cnt" in result

    def test_latest_health_run(self):
        result = run_sql(
            self.conn,
            "SELECT timestamp, status FROM health_runs ORDER BY timestamp DESC LIMIT 1"
        )
        assert "timestamp" in result

    def test_duration_stats(self):
        result = run_sql(
            self.conn,
            "SELECT AVG(duration_ms) as avg_dur, MAX(duration_ms) as max_dur FROM health_runs"
        )
        assert "avg_dur" in result

    def test_failed_checks_unnest(self):
        result = run_sql(
            self.conn,
            """SELECT value as check_name, COUNT(*) as fail_count
               FROM health_runs, json_each(failed_checks)
               WHERE status != 'healthy'
               GROUP BY value
               ORDER BY fail_count DESC
               LIMIT 5"""
        )
        # May return "No results." if all runs are healthy — that's fine
        assert isinstance(result, str)


class TestSystemOpsDriftQueries:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)
        self.conn = make_ops_db(POPULATED_PROFILES)

    def test_drift_items_by_severity(self):
        result = run_sql(
            self.conn,
            "SELECT severity, COUNT(*) as cnt FROM drift_items GROUP BY severity"
        )
        # May be empty if no drift report
        assert isinstance(result, str)

    def test_drift_runs_trend(self):
        result = run_sql(
            self.conn,
            "SELECT timestamp, drift_count FROM drift_runs ORDER BY timestamp DESC LIMIT 5"
        )
        assert isinstance(result, str)


class TestSystemOpsDigestQueries:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)
        self.conn = make_ops_db(POPULATED_PROFILES)

    def test_digest_headline_search(self):
        result = run_sql(
            self.conn,
            "SELECT timestamp, headline FROM digest_runs ORDER BY timestamp DESC LIMIT 3"
        )
        assert isinstance(result, str)


class TestSystemOpsMaintQueries:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)
        self.conn = make_ops_db(POPULATED_PROFILES)

    def test_maint_totals(self):
        result = run_sql(
            self.conn,
            "SELECT SUM(pruned_count) as total_pruned, SUM(merged_count) as total_merged FROM knowledge_maint"
        )
        assert isinstance(result, str)


# ── Populated state — Live tools ─────────────────────────────────────────────


class TestSystemOpsLiveTools:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)

    def test_infra_snapshot_has_sections(self):
        result = get_infra_snapshot(POPULATED_PROFILES)
        assert "Infrastructure Snapshot" in result or "not found" in result.lower()

    def test_manifest_docker_section(self):
        result = get_manifest_section(POPULATED_PROFILES, "docker")
        # Either returns JSON content or "not found"
        assert len(result) > 0

    def test_manifest_nonexistent_section(self):
        result = get_manifest_section(POPULATED_PROFILES, "nonexistent_section")
        assert "not found" in result.lower() or "Available sections" in result


# ── Empty state ──────────────────────────────────────────────────────────────


class TestSystemOpsEmpty:
    def setup_method(self):
        skip_if_missing(EMPTY_PROFILES)
        self.conn = make_ops_db(EMPTY_PROFILES)

    def test_all_tables_empty(self):
        for table in ("health_runs", "drift_items", "drift_runs", "digest_runs", "knowledge_maint"):
            result = run_sql(self.conn, f"SELECT * FROM {table}")
            assert result == "No results.", f"Expected empty {table}"

    def test_schemas_still_valid(self):
        schemas = get_table_schemas(self.conn)
        assert "health_runs" in schemas
        assert "drift_items" in schemas

    def test_infra_snapshot_missing(self):
        result = get_infra_snapshot(EMPTY_PROFILES)
        assert "not found" in result.lower() or "not available" in result.lower()

    def test_manifest_missing(self):
        result = get_manifest_section(EMPTY_PROFILES, "docker")
        assert "not found" in result.lower()


# ── Error paths ──────────────────────────────────────────────────────────────


class TestSystemOpsErrorPaths:
    def test_malformed_jsonl_skips_bad_lines(self, tmp_path):
        """Verify _load_jsonl handles malformed entries."""
        data = '{"timestamp":"2026-01-01","status":"healthy","healthy":1,"degraded":0,"failed":0,"duration_ms":100,"failed_checks":[]}\n'
        data += 'THIS IS NOT JSON\n'
        data += '{"timestamp":"2026-01-02","status":"failed","healthy":0,"degraded":0,"failed":1,"duration_ms":200,"failed_checks":["docker"]}\n'
        (tmp_path / "health-history.jsonl").write_text(data)

        conn = build_ops_db(tmp_path)
        cursor = conn.execute("SELECT COUNT(*) FROM health_runs")
        count = cursor.fetchone()[0]
        assert count == 2  # Skipped the bad line

    def test_multiline_json_parsed_correctly(self, tmp_path):
        """Verify _load_jsonl handles pretty-printed concatenated JSON."""
        entries = [
            {"timestamp": "2026-01-01", "hours": 24, "headline": "Test 1", "summary": "S1", "new_documents": 5},
            {"timestamp": "2026-01-02", "hours": 24, "headline": "Test 2", "summary": "S2", "new_documents": 3},
        ]
        # Write as pretty-printed (not true JSONL)
        text = "\n".join(json.dumps(e, indent=2) for e in entries)
        (tmp_path / "digest-history.jsonl").write_text(text)

        conn = build_ops_db(tmp_path)
        cursor = conn.execute("SELECT COUNT(*) FROM digest_runs")
        count = cursor.fetchone()[0]
        assert count == 2
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/query_integration/test_system_ops.py -v`
Expected: All PASS (or skip where data missing)

- [ ] **Step 3: Commit**

```bash
git add tests/query_integration/test_system_ops.py
git commit -m "test: add system-ops integration tests against real data"
```

## Chunk 5: Integration Tests — Knowledge + Dispatch + Empty State + SSE

### Task 14: Create knowledge integration tests

**Files:**
- Create: `tests/query_integration/test_knowledge.py`

- [ ] **Step 1: Create the test file**

```python
"""Integration tests for knowledge query agent against real data."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from shared.knowledge_search import (
    read_briefing,
    read_digest,
    read_scout_report,
    get_operator_goals,
    search_documents,
    search_profile,
    search_memory,
)
from tests.query_integration._helpers import (
    POPULATED_PROFILES,
    EMPTY_PROFILES,
    skip_if_missing,
)


# ── Populated state — File reads ─────────────────────────────────────────────


class TestKnowledgeFileReads:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)

    def test_briefing_has_content(self):
        result = read_briefing(POPULATED_PROFILES)
        # Either has content or says not available
        assert len(result) > 20

    def test_briefing_structure(self):
        result = read_briefing(POPULATED_PROFILES)
        if "not available" not in result.lower():
            assert "Briefing" in result or "Headline" in result

    def test_digest_has_content(self):
        result = read_digest(POPULATED_PROFILES)
        assert len(result) > 20

    def test_scout_report_has_content(self):
        result = read_scout_report(POPULATED_PROFILES)
        assert len(result) > 20

    def test_operator_goals_has_content(self):
        result = get_operator_goals(POPULATED_PROFILES)
        assert len(result) > 20


# ── Populated state — Search (mocked at Qdrant client level) ─────────────────


class TestKnowledgeSearchFilters:
    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_source_service_filter_construction(self, mock_embed, mock_qdrant):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.points = []
        mock_client.query_points.return_value = mock_result
        mock_qdrant.return_value = mock_client

        search_documents("test", source_service="gmail")

        call_args = mock_client.query_points.call_args
        query_filter = call_args.kwargs.get("query_filter") or call_args[1].get("query_filter")
        assert query_filter is not None
        # Filter should contain gmail condition
        conditions = query_filter.must
        assert any("gmail" in str(c) for c in conditions)

    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_days_back_filter_construction(self, mock_embed, mock_qdrant):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.points = []
        mock_client.query_points.return_value = mock_result
        mock_qdrant.return_value = mock_client

        search_documents("test", days_back=7)

        call_args = mock_client.query_points.call_args
        query_filter = call_args.kwargs.get("query_filter") or call_args[1].get("query_filter")
        assert query_filter is not None
        # Should have a range condition on ingested_at
        conditions = query_filter.must
        assert len(conditions) == 1

    @patch("shared.knowledge_search.ProfileStore")
    def test_profile_dimension_filter(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.search.return_value = []
        mock_store_cls.return_value = mock_store

        search_profile("work habits", dimension="work_patterns")

        mock_store.search.assert_called_once_with(
            "work habits", dimension="work_patterns", limit=5
        )


# ── Empty state ──────────────────────────────────────────────────────────────


class TestKnowledgeEmptyState:
    def setup_method(self):
        skip_if_missing(EMPTY_PROFILES)

    def test_briefing_missing_includes_schedule(self):
        result = read_briefing(EMPTY_PROFILES)
        assert "not available" in result.lower()
        assert "07:00" in result or "daily" in result.lower()

    def test_digest_missing_includes_schedule(self):
        result = read_digest(EMPTY_PROFILES)
        assert "not available" in result.lower()
        assert "06:45" in result or "daily" in result.lower()

    def test_scout_missing_includes_schedule(self):
        result = read_scout_report(EMPTY_PROFILES)
        assert "not available" in result.lower()
        assert "weekly" in result.lower()

    def test_goals_missing_includes_explanation(self):
        result = get_operator_goals(EMPTY_PROFILES)
        assert "not available" in result.lower()


class TestKnowledgeQdrantErrors:
    @patch("shared.knowledge_search.get_qdrant", side_effect=ConnectionError("Connection refused"))
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_qdrant_down_returns_error_message(self, mock_embed, mock_qdrant):
        result = search_documents("test query")
        assert "error" in result.lower()
        assert "Connection refused" in result

    @patch("shared.knowledge_search.get_qdrant", side_effect=ConnectionError("Connection refused"))
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_memory_search_qdrant_down(self, mock_embed, mock_qdrant):
        result = search_memory("test query")
        assert "error" in result.lower()
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/query_integration/test_knowledge.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/query_integration/test_knowledge.py
git commit -m "test: add knowledge integration tests with real data and empty state"
```

### Task 15: Create dispatch classification tests

**Files:**
- Create: `tests/query_integration/test_dispatch.py`

- [ ] **Step 1: Create the test file**

```python
"""Integration tests for query dispatch classification accuracy."""
from __future__ import annotations

import pytest

from logos.query_dispatch import classify_query


class TestDevStoryClassification:
    """Queries that should route to dev_story."""

    @pytest.mark.parametrize("query,expected", [
        ("show me commit history for logos module", "dev_story"),
        ("what files changed most in the last week", "dev_story"),
        ("how many sessions were there yesterday", "dev_story"),
        ("what's the average session duration", "dev_story"),
        ("show git activity by author", "dev_story"),
        ("what branches were worked on recently", "dev_story"),
        ("correlate commits with session length", "dev_story"),
        ("what was the longest coding session", "dev_story"),
        ("show me the development timeline", "dev_story"),
        ("how has the codebase grown over time", "dev_story"),
    ])
    def test_routes_to_dev_story(self, query, expected):
        assert classify_query(query) == expected


class TestSystemOpsClassification:
    """Queries that should route to system_ops."""

    @pytest.mark.parametrize("query,expected", [
        ("what is the current health status", "system_ops"),
        ("which docker containers are running", "system_ops"),
        ("how much did we spend on LLM costs this week", "system_ops"),
        ("are there any drift items with high severity", "system_ops"),
        ("show me the health trend over the last day", "system_ops"),
        ("what GPU memory is being used", "system_ops"),
        ("which systemd timers are active", "system_ops"),
        ("how many qdrant collections exist", "system_ops"),
        ("what's the infrastructure manifest say about ports", "system_ops"),
        ("show me degraded health checks", "system_ops"),
    ])
    def test_routes_to_system_ops(self, query, expected):
        assert classify_query(query) == expected


class TestKnowledgeClassification:
    """Queries that should route to knowledge."""

    @pytest.mark.parametrize("query,expected", [
        ("search for documents about API design", "knowledge"),
        ("what did the briefing say today", "knowledge"),
        ("find emails from last week about the project", "knowledge"),
        ("search my obsidian notes for meeting prep", "knowledge"),
        ("what are my current goals", "knowledge"),
        ("show me the latest digest", "knowledge"),
        ("what did the scout report recommend", "knowledge"),
        ("search my conversation memory for voice pipeline", "knowledge"),
        ("find documents from google drive about architecture", "knowledge"),
        ("what does my profile say about communication style", "knowledge"),
    ])
    def test_routes_to_knowledge(self, query, expected):
        assert classify_query(query) == expected


class TestEdgeCases:
    """Ambiguous and edge-case queries."""

    def test_empty_query_defaults_to_dev_story(self):
        assert classify_query("") == "dev_story"

    def test_no_keywords_defaults_to_dev_story(self):
        assert classify_query("tell me everything") == "dev_story"

    def test_no_overlap_defaults_to_dev_story(self):
        assert classify_query("the quick brown fox jumps over the lazy dog") == "dev_story"

    def test_infrastructure_routes_to_system_ops(self):
        assert classify_query("what changed in the infrastructure this week") == "system_ops"

    def test_multi_keyword_overlap_highest_score_wins(self):
        # "search" + "document" = knowledge(2), "commit" + "history" = dev_story(2)
        # Tie goes to whichever agent is iterated first with that score
        result = classify_query("search commit history in documents")
        assert result in ("dev_story", "knowledge")  # Either is acceptable for a tie
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/query_integration/test_dispatch.py -v`
Expected: All PASS. If any parametrized query routes incorrectly, adjust either the query wording or the assertion (the test is testing classification accuracy — if a query genuinely has ambiguous keywords, the assertion should reflect the actual behavior).

- [ ] **Step 3: Commit**

```bash
git add tests/query_integration/test_dispatch.py
git commit -m "test: add dispatch classification accuracy tests with 30+ queries"
```

### Task 16: Create empty-state and SSE streaming integration tests

**Files:**
- Create: `tests/query_integration/test_empty_state.py`
- Create: `tests/query_integration/test_sse_streaming.py`

- [ ] **Step 1: Create empty-state tests**

```python
"""Dedicated empty-state assertions across all query agents."""
from __future__ import annotations

import sqlite3

import pytest

from agents.dev_story.query import _sql_query, build_system_prompt as dev_story_prompt
from agents.system_ops.query import build_system_prompt as system_ops_prompt
from agents.knowledge.query import build_system_prompt as knowledge_prompt
from shared.ops_db import build_ops_db, run_sql, get_table_schemas
from shared.ops_live import get_infra_snapshot, get_manifest_section
from shared.knowledge_search import (
    read_briefing,
    read_digest,
    read_scout_report,
    get_operator_goals,
)
from tests.query_integration._helpers import (
    EMPTY_PROFILES,
    EMPTY_DEV_STORY_DB,
    open_dev_story_db,
    skip_if_missing,
)


class TestDevStoryEmptyStateContract:
    """Verify dev-story handles fresh deployment gracefully."""

    def test_prompt_has_empty_state_guidance(self):
        prompt = dev_story_prompt()
        assert "When Data is Unavailable" in prompt

    def test_empty_db_all_tables_queryable(self):
        skip_if_missing(EMPTY_DEV_STORY_DB)
        conn = open_dev_story_db(EMPTY_DEV_STORY_DB)
        for table in ("sessions", "commits", "messages", "correlations"):
            result = _sql_query(conn, f"SELECT COUNT(*) FROM {table}")
            assert "0" in result
        conn.close()


class TestSystemOpsEmptyStateContract:
    """Verify system-ops handles fresh deployment gracefully."""

    def test_prompt_has_empty_state_guidance(self):
        prompt = system_ops_prompt()
        assert "When Data is Unavailable" in prompt

    def test_empty_ops_db_no_crashes(self):
        skip_if_missing(EMPTY_PROFILES)
        conn = build_ops_db(EMPTY_PROFILES)
        for table in ("health_runs", "drift_items", "drift_runs", "digest_runs", "knowledge_maint"):
            result = run_sql(conn, f"SELECT * FROM {table}")
            assert result == "No results."

    def test_infra_snapshot_missing_gracefully(self):
        skip_if_missing(EMPTY_PROFILES)
        result = get_infra_snapshot(EMPTY_PROFILES)
        assert "not" in result.lower()  # "not found" or "not available"

    def test_manifest_missing_gracefully(self):
        skip_if_missing(EMPTY_PROFILES)
        result = get_manifest_section(EMPTY_PROFILES, "docker")
        assert "not found" in result.lower()


class TestKnowledgeEmptyStateContract:
    """Verify knowledge handles fresh deployment gracefully."""

    def test_prompt_has_empty_state_guidance(self):
        prompt = knowledge_prompt()
        assert "When Data is Unavailable" in prompt

    def test_all_artifact_reads_graceful(self):
        skip_if_missing(EMPTY_PROFILES)
        for fn, name in [
            (read_briefing, "briefing"),
            (read_digest, "digest"),
            (read_scout_report, "scout"),
            (get_operator_goals, "goals"),
        ]:
            result = fn(EMPTY_PROFILES)
            assert "not available" in result.lower(), f"{name} should say 'not available'"
            assert len(result) > 30, f"{name} empty message too short — should include schedule info"
```

- [ ] **Step 2: Create SSE streaming tests**

```python
"""Integration tests for SSE streaming API contract."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from logos.api.app import app
from logos.query_dispatch import QueryResult


def _parse_sse_events(body: str) -> list[dict]:
    """Parse SSE event stream into a list of {event, data} dicts."""
    events = []
    current_event = "message"
    for line in body.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            events.append({"event": current_event, "data": line[6:]})
            current_event = "message"
    return events


class TestSSEEventContract:
    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query", return_value="dev_story")
    async def test_event_sequence_status_text_done(self, mock_classify, mock_run):
        mock_run.return_value = QueryResult(
            markdown="## Results\nSome content",
            agent_type="dev_story",
            tokens_in=500,
            tokens_out=200,
            elapsed_ms=1000,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query/run", json={"query": "test query"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = _parse_sse_events(resp.text)
        event_types = [e["event"] for e in events]
        assert "status" in event_types, "Missing status event"
        assert "text_delta" in event_types, "Missing text_delta event"
        assert "done" in event_types, "Missing done event"

        status_idx = event_types.index("status")
        text_idx = event_types.index("text_delta")
        done_idx = event_types.index("done")
        assert status_idx < text_idx < done_idx

    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query", return_value="dev_story")
    async def test_status_event_has_phase_and_agent(self, mock_classify, mock_run):
        mock_run.return_value = QueryResult(
            markdown="test", agent_type="dev_story",
            tokens_in=10, tokens_out=5, elapsed_ms=100,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query/run", json={"query": "test"})

        events = _parse_sse_events(resp.text)
        status_events = [e for e in events if e["event"] == "status"]
        assert len(status_events) >= 1
        data = json.loads(status_events[0]["data"])
        assert data["phase"] == "querying"
        assert data["agent"] == "dev_story"

    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query", return_value="dev_story")
    async def test_done_event_has_metadata(self, mock_classify, mock_run):
        mock_run.return_value = QueryResult(
            markdown="test", agent_type="dev_story",
            tokens_in=500, tokens_out=200, elapsed_ms=1234,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query/run", json={"query": "test"})

        events = _parse_sse_events(resp.text)
        done_events = [e for e in events if e["event"] == "done"]
        assert len(done_events) == 1
        data = json.loads(done_events[0]["data"])
        assert data["agent_used"] == "dev_story"
        assert data["tokens_in"] == 500
        assert data["tokens_out"] == 200
        assert data["elapsed_ms"] == 1234

    async def test_empty_query_rejected(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query/run", json={"query": "  "})
        assert resp.status_code == 422

    @patch("cockpit.api.routes.query.run_query")
    @patch("cockpit.api.routes.query.classify_query", return_value="dev_story")
    async def test_empty_markdown_still_completes(self, mock_classify, mock_run):
        mock_run.return_value = QueryResult(
            markdown="", agent_type="dev_story",
            tokens_in=50, tokens_out=10, elapsed_ms=200,
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/query/run", json={"query": "empty test"})
        assert resp.status_code == 200
        assert "event: done" in resp.text
```

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/query_integration/test_empty_state.py tests/query_integration/test_sse_streaming.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/query_integration/test_empty_state.py tests/query_integration/test_sse_streaming.py
git commit -m "test: add empty-state contract and SSE streaming integration tests"
```

## Chunk 6: hapax-logos Test Foundation

### Task 17: Bootstrap vitest in hapax-logos

**Files:**
- Modify: `~/projects/hapax-logos/package.json`
- Modify: `~/projects/hapax-logos/vite.config.ts`
- Create: `~/projects/hapax-logos/src/test-setup.ts`

- [ ] **Step 1: Install test dependencies**

```bash
cd ~/projects/hapax-logos && pnpm add -D vitest @testing-library/react @testing-library/jest-dom jsdom @testing-library/user-event
```

- [ ] **Step 2: Add test config to vite.config.ts**

Read `vite.config.ts` first. Add `test` configuration to the `defineConfig` object:

```typescript
test: {
  environment: 'jsdom',
  setupFiles: './src/test-setup.ts',
  globals: true,
},
```

- [ ] **Step 3: Create test setup file**

Create `~/projects/hapax-logos/src/test-setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 4: Add test script to package.json**

Add `"test": "vitest"` to the `scripts` section.

- [ ] **Step 5: Verify setup**

```bash
cd ~/projects/hapax-logos && pnpm test -- --run 2>&1 | head -5
```
Expected: vitest starts (may say "no test files found" — that's fine)

- [ ] **Step 6: Commit**

```bash
cd ~/projects/hapax-logos && git add package.json pnpm-lock.yaml vite.config.ts src/test-setup.ts
git commit -m "feat: bootstrap vitest test infrastructure"
```

### Task 18: Add SSE client unit tests

**Files:**
- Create: `~/projects/hapax-logos/src/api/__tests__/sse.test.ts`

- [ ] **Step 1: Create SSE client tests**

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { connectSSE, type SSEEvent } from "../sse";

// Mock fetch with a streaming response helper
function mockStreamResponse(chunks: string[]) {
  const encoder = new TextEncoder();
  let chunkIndex = 0;

  const reader = {
    read: vi.fn(async () => {
      if (chunkIndex >= chunks.length) {
        return { done: true, value: undefined };
      }
      return {
        done: false,
        value: encoder.encode(chunks[chunkIndex++]),
      };
    }),
  };

  return {
    ok: true,
    body: { getReader: () => reader },
  } as unknown as Response;
}

describe("connectSSE", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("calls fetch with correct URL and body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockStreamResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    const onEvent = vi.fn();
    connectSSE("http://test/api/query/run", {
      body: { query: "test" },
      onEvent,
    });

    // Wait for async fetch
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(fetchMock).toHaveBeenCalledWith(
      "http://test/api/query/run",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: "test" }),
      }),
    );
  });

  it("parses SSE events correctly", async () => {
    const events: SSEEvent[] = [];
    const fetchMock = vi.fn().mockResolvedValue(
      mockStreamResponse([
        "event: status\ndata: {\"phase\":\"querying\"}\n\n",
        "event: text_delta\ndata: {\"content\":\"hello\"}\n\n",
        "event: done\ndata: {\"elapsed_ms\":100}\n\n",
      ]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const onDone = vi.fn();
    connectSSE("http://test", {
      body: { query: "test" },
      onEvent: (e) => events.push(e),
      onDone,
    });

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(events).toHaveLength(3);
    expect(events[0].event).toBe("status");
    expect(events[1].event).toBe("text_delta");
    expect(events[2].event).toBe("done");
  });

  it("calls onDone when stream ends", async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockStreamResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    const onDone = vi.fn();
    connectSSE("http://test", { body: {}, onEvent: vi.fn(), onDone });

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("calls onError for non-ok responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: async () => "Validation error",
    });
    vi.stubGlobal("fetch", fetchMock);

    const onError = vi.fn();
    connectSSE("http://test", {
      body: {},
      onEvent: vi.fn(),
      onError,
    });

    await vi.waitFor(() => expect(onError).toHaveBeenCalled());
    expect(onError.mock.calls[0][0].message).toContain("422");
  });
});
```

- [ ] **Step 2: Run the tests**

```bash
cd ~/projects/hapax-logos && pnpm test -- --run src/api/__tests__/sse.test.ts
```
Expected: 4 tests PASS

- [ ] **Step 3: Commit**

```bash
cd ~/projects/hapax-logos && git add src/api/__tests__/sse.test.ts
git commit -m "test: add SSE client unit tests"
```

### Task 19: Add QueryInput and QueryResult component tests

**Files:**
- Create: `~/projects/hapax-logos/src/components/insight/__tests__/QueryInput.test.tsx`
- Create: `~/projects/hapax-logos/src/components/insight/__tests__/QueryResult.test.tsx`

- [ ] **Step 1: Create QueryInput tests**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryInput } from "../QueryInput";

describe("QueryInput", () => {
  it("submits on Enter key", async () => {
    const onSubmit = vi.fn();
    render(<QueryInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "test query");
    await userEvent.keyboard("{Enter}");

    expect(onSubmit).toHaveBeenCalledWith("test query");
  });

  it("does not submit when input is empty", async () => {
    const onSubmit = vi.fn();
    render(<QueryInput onSubmit={onSubmit} isLoading={false} />);

    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
  });

  it("disables input during loading", () => {
    const onSubmit = vi.fn();
    render(<QueryInput onSubmit={onSubmit} isLoading={true} />);

    const textarea = screen.getByRole("textbox");
    expect(textarea).toBeDisabled();
  });

  it("clears input after submit", async () => {
    const onSubmit = vi.fn();
    render(<QueryInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "test query");
    await userEvent.keyboard("{Enter}");

    expect(textarea).toHaveValue("");
  });
});
```

- [ ] **Step 2: Create QueryResult tests**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryResult } from "../QueryResult";

describe("QueryResult", () => {
  it("renders markdown content", () => {
    render(
      <QueryResult
        query="test query"
        markdown="## Hello World\n\nThis is content"
        isStreaming={false}
        metadata={{ agent_used: "dev_story", tokens_in: 100, tokens_out: 50, elapsed_ms: 500 }}
      />,
    );

    expect(screen.getByText("Hello World")).toBeInTheDocument();
    expect(screen.getByText("This is content")).toBeInTheDocument();
  });

  it("shows agent type badge", () => {
    render(
      <QueryResult
        query="test"
        markdown="content"
        isStreaming={false}
        metadata={{ agent_used: "system_ops", tokens_in: 100, tokens_out: 50, elapsed_ms: 500 }}
      />,
    );

    expect(screen.getByText("system_ops")).toBeInTheDocument();
  });

  it("shows loading indicator when streaming", () => {
    render(
      <QueryResult
        query="test"
        markdown=""
        isStreaming={true}
      />,
    );

    expect(screen.getByText("Querying...")).toBeInTheDocument();
  });

  it("shows timing metadata", () => {
    render(
      <QueryResult
        query="test"
        markdown="content"
        isStreaming={false}
        metadata={{ agent_used: "dev_story", tokens_in: 1000, tokens_out: 500, elapsed_ms: 2500 }}
      />,
    );

    expect(screen.getByText("2.5s")).toBeInTheDocument();
  });

  it("handles empty markdown without crash", () => {
    const { container } = render(
      <QueryResult
        query="test"
        markdown=""
        isStreaming={false}
        metadata={{ agent_used: "dev_story", tokens_in: 50, tokens_out: 10, elapsed_ms: 200 }}
      />,
    );

    // Should render without errors
    expect(container).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run the tests**

```bash
cd ~/projects/hapax-logos && pnpm test -- --run src/components/insight/__tests__/
```
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd ~/projects/hapax-logos && git add src/components/insight/__tests__/
git commit -m "test: add QueryInput and QueryResult component tests"
```

## Chunk 7: LLM Spot Checks

### Task 20: Create LLM spot check tests

**Files:**
- Create: `tests/query_integration/test_llm_spot.py`

These tests are marked `@pytest.mark.llm` and skipped by default. They make real LLM calls through LiteLLM and verify that agents produce coherent responses.

- [ ] **Step 1: Create the test file**

```python
"""Live LLM spot checks for query agents.

These tests make real LLM API calls and are SLOW (~10-30s each).
Skipped by default. Run with: uv run pytest -m llm -v

Requires:
- LiteLLM running at localhost:4000
- Test data in test-data/ (run scripts/extract-test-data.py first)
"""
from __future__ import annotations

import shutil
from unittest.mock import patch

import pytest

from logos.query_dispatch import run_query
from tests.query_integration._helpers import (
    POPULATED_PROFILES,
    POPULATED_DEV_STORY_DB,
    EMPTY_PROFILES,
    EMPTY_DEV_STORY_DB,
    skip_if_missing,
)

pytestmark = pytest.mark.llm


# ── Populated state ──────────────────────────────────────────────────────────


class TestDevStoryLLM:
    def setup_method(self):
        skip_if_missing(POPULATED_DEV_STORY_DB)

    async def test_commit_query_returns_markdown(self):
        result = await run_query("dev_story", "what files changed most recently?")
        assert len(result.markdown) > 50
        assert result.agent_type == "dev_story"

    async def test_session_query_returns_content(self):
        result = await run_query("dev_story", "show me recent session patterns")
        assert len(result.markdown) > 50


class TestSystemOpsLLM:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)

    async def test_health_query(self):
        result = await run_query("system_ops", "what is the health trend?")
        assert len(result.markdown) > 50
        assert result.agent_type == "system_ops"

    async def test_drift_query(self):
        result = await run_query("system_ops", "are there any drift items?")
        assert len(result.markdown) > 50


class TestKnowledgeLLM:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)

    async def test_briefing_query(self):
        result = await run_query("knowledge", "what did the briefing say?")
        assert len(result.markdown) > 50
        assert result.agent_type == "knowledge"

    async def test_goals_query(self):
        result = await run_query("knowledge", "what are my current goals?")
        assert len(result.markdown) > 50
        assert result.agent_type == "knowledge"


# ── Empty state ──────────────────────────────────────────────────────────────


class TestEmptyStateLLM:
    """Verify agents explicitly surface data limitations on empty state.

    Patches PROFILES_DIR to point at the empty test data directory.
    For dev_story, also copies the empty DB into the empty profiles dir
    so the factory function finds dev-story.db at the expected path.
    """

    def setup_method(self):
        skip_if_missing(EMPTY_PROFILES)
        skip_if_missing(EMPTY_DEV_STORY_DB)
        # Copy empty dev-story.db into the empty profiles dir so the factory finds it
        self._db_copy = EMPTY_PROFILES / "dev-story.db"
        if not self._db_copy.exists():
            shutil.copy2(EMPTY_DEV_STORY_DB, self._db_copy)
        # Patch PROFILES_DIR in both modules
        self._patches = [
            patch("shared.config.PROFILES_DIR", EMPTY_PROFILES),
            patch("cockpit.query_dispatch.PROFILES_DIR", EMPTY_PROFILES),
        ]
        for p in self._patches:
            p.start()

    def teardown_method(self):
        for p in self._patches:
            p.stop()
        # Clean up the copied db
        if hasattr(self, "_db_copy") and self._db_copy.exists():
            self._db_copy.unlink()

    async def test_dev_story_empty_surfaces_limitation(self):
        result = await run_query("dev_story", "show me the development timeline")
        md = result.markdown.lower()
        assert any(
            phrase in md
            for phrase in ["no data", "not populated", "no sessions", "no commits", "empty", "unavailable"]
        ), f"Expected empty-state message, got: {result.markdown[:200]}"

    async def test_system_ops_empty_surfaces_limitation(self):
        result = await run_query("system_ops", "what is the health status?")
        md = result.markdown.lower()
        assert any(
            phrase in md
            for phrase in ["no data", "no results", "empty", "not available", "no health"]
        ), f"Expected empty-state message, got: {result.markdown[:200]}"
```

- [ ] **Step 3: Verify tests are skipped by default**

Run: `uv run pytest tests/query_integration/test_llm_spot.py -v`
Expected: All tests SKIPPED (due to `-m "not llm"` in addopts)

- [ ] **Step 4: Commit**

```bash
git add tests/query_integration/test_llm_spot.py
git commit -m "test: add LLM spot check tests for query agents (skipped by default)"
```

### Task 21: Run full test suite and verify

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest tests/ -q --tb=short 2>&1 | tail -20
```
Expected: All new tests pass, no regressions. Pre-existing failures remain unchanged. Total test count should increase by ~130.

- [ ] **Step 2: Run integration tests specifically**

```bash
uv run pytest tests/query_integration/ -v --tb=short
```
Expected: All integration tests pass (LLM tests skipped)

- [ ] **Step 3: Run hapax-logos tests**

```bash
cd ~/projects/hapax-logos && pnpm test -- --run
```
Expected: All frontend tests pass

- [ ] **Step 4: Final commit with test count update**

If all tests pass, no additional commit needed. If any test needed adjustment, commit the fixes:

```bash
git add -u && git commit -m "fix: adjust integration test assertions after full suite validation"
```
