# Query Agents Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add System Operations and Knowledge & Context query agents to the cockpit query dispatch system, with shared data-access modules reusable by voice daemon and future consumers.

**Architecture:** Each agent follows the established dev-story pattern (factory in query_dispatch.py, pydantic-ai agent with tools, SSE streaming). Data-access functions live in `shared/` modules (not agent internals), so voice and other consumers can call them directly. System Operations uses a hybrid SQLite-for-history + live-HTTP-tools pattern. Knowledge & Context uses Qdrant semantic search + file artifact reads.

**Tech Stack:** pydantic-ai 1.63.0, SQLite, Qdrant (via shared.config), Langfuse (via shared.langfuse_client), FastAPI SSE (existing)

**Spec:** `docs/superpowers/specs/2026-03-10-query-agents-design.md`

---

## Chunk 1: Shared Data-Access Modules

These modules contain the pure data-fetching logic. No pydantic-ai dependency. Reusable by query agents, voice tools, cockpit collectors, or any future consumer.

### Task 1: shared/ops_db.py — Operations SQLite Builder

**Files:**
- Create: `shared/ops_db.py`
- Test: `tests/test_ops_db.py`

This module builds a temporary in-memory SQLite database from the JSONL/JSON files in profiles/. It is called once at agent startup, and the connection is passed to the agent's tools.

- [ ] **Step 1: Write failing tests for build_ops_db**

```python
# tests/test_ops_db.py
"""Tests for shared.ops_db — operations SQLite builder."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from shared.ops_db import build_ops_db, get_table_schemas, run_sql


class TestBuildOpsDb:
    def test_creates_all_tables(self, tmp_path):
        """An empty profiles dir still creates all 5 tables."""
        conn = build_ops_db(tmp_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [r[0] for r in cursor.fetchall()]
        assert tables == [
            "digest_runs",
            "drift_items",
            "drift_runs",
            "health_runs",
            "knowledge_maint",
        ]
        conn.close()

    def test_loads_health_history(self, tmp_path):
        """JSONL entries are loaded into health_runs."""
        history = tmp_path / "health-history.jsonl"
        history.write_text(
            json.dumps({
                "timestamp": "2026-03-10T10:00:00+00:00",
                "status": "healthy",
                "healthy": 44,
                "degraded": 0,
                "failed": 0,
                "duration_ms": 2500,
                "failed_checks": [],
            })
            + "\n"
            + json.dumps({
                "timestamp": "2026-03-10T10:15:00+00:00",
                "status": "degraded",
                "healthy": 42,
                "degraded": 2,
                "failed": 0,
                "duration_ms": 3100,
                "failed_checks": ["docker_ollama", "gpu_vram"],
            })
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        rows = conn.execute("SELECT COUNT(*) FROM health_runs").fetchone()[0]
        assert rows == 2

        degraded = conn.execute(
            "SELECT failed_checks FROM health_runs WHERE status = 'degraded'"
        ).fetchone()[0]
        assert "docker_ollama" in degraded
        conn.close()

    def test_loads_drift_report(self, tmp_path):
        """drift-report.json items are loaded into drift_items."""
        report = tmp_path / "drift-report.json"
        report.write_text(json.dumps({
            "drift_items": [
                {
                    "severity": "high",
                    "category": "missing_service",
                    "doc_file": "CLAUDE.md",
                    "doc_claim": "16 services",
                    "reality": "18 services",
                    "suggestion": "Update count",
                },
            ],
            "docs_analyzed": ["CLAUDE.md"],
            "summary": "1 drift item found",
        }))
        conn = build_ops_db(tmp_path)
        rows = conn.execute("SELECT COUNT(*) FROM drift_items").fetchone()[0]
        assert rows == 1
        row = conn.execute("SELECT severity, category FROM drift_items").fetchone()
        assert row == ("high", "missing_service")
        conn.close()

    def test_loads_drift_history(self, tmp_path):
        """JSONL entries are loaded into drift_runs."""
        history = tmp_path / "drift-history.jsonl"
        history.write_text(
            json.dumps({
                "timestamp": "2026-03-09T17:05:02Z",
                "drift_count": 25,
                "docs_analyzed": 18,
                "summary": "1 cross-project boundary drift",
            })
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        rows = conn.execute("SELECT COUNT(*) FROM drift_runs").fetchone()[0]
        assert rows == 1
        conn.close()

    def test_loads_digest_history(self, tmp_path):
        """JSONL entries are loaded into digest_runs."""
        history = tmp_path / "digest-history.jsonl"
        history.write_text(
            json.dumps({
                "timestamp": "2026-03-10T06:45:00Z",
                "hours": 24,
                "headline": "Test headline",
                "summary": "Test summary",
                "new_documents": 15,
            })
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        row = conn.execute("SELECT headline FROM digest_runs").fetchone()
        assert row[0] == "Test headline"
        conn.close()

    def test_loads_knowledge_maint_history(self, tmp_path):
        """JSONL entries are loaded into knowledge_maint."""
        history = tmp_path / "knowledge-maint-history.jsonl"
        history.write_text(
            json.dumps({
                "timestamp": "2026-03-09T09:39:00Z",
                "pruned_count": 12,
                "merged_count": 3,
                "duration_ms": 4500,
            })
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        row = conn.execute(
            "SELECT pruned_count, merged_count FROM knowledge_maint"
        ).fetchone()
        assert row == (12, 3)
        conn.close()

    def test_skips_malformed_jsonl_lines(self, tmp_path):
        """Malformed lines are skipped without crashing."""
        history = tmp_path / "health-history.jsonl"
        history.write_text(
            "not valid json\n"
            + json.dumps({
                "timestamp": "2026-03-10T10:00:00+00:00",
                "status": "healthy",
                "healthy": 44,
                "degraded": 0,
                "failed": 0,
                "duration_ms": 2500,
                "failed_checks": [],
            })
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        rows = conn.execute("SELECT COUNT(*) FROM health_runs").fetchone()[0]
        assert rows == 1
        conn.close()


class TestRunSql:
    def test_select_returns_formatted_table(self, tmp_path):
        """SELECT queries return formatted table output."""
        history = tmp_path / "health-history.jsonl"
        history.write_text(
            json.dumps({
                "timestamp": "2026-03-10T10:00:00+00:00",
                "status": "healthy",
                "healthy": 44,
                "degraded": 0,
                "failed": 0,
                "duration_ms": 2500,
                "failed_checks": [],
            })
            + "\n"
        )
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "SELECT status, healthy FROM health_runs")
        assert "healthy" in result
        assert "44" in result
        conn.close()

    def test_rejects_non_select(self, tmp_path):
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "DROP TABLE health_runs")
        assert "error" in result.lower()
        conn.close()

    def test_limits_output_rows(self, tmp_path):
        history = tmp_path / "health-history.jsonl"
        lines = []
        for i in range(150):
            lines.append(json.dumps({
                "timestamp": f"2026-03-10T{i:02d}:00:00+00:00",
                "status": "healthy",
                "healthy": 44,
                "degraded": 0,
                "failed": 0,
                "duration_ms": 2500,
                "failed_checks": [],
            }))
        history.write_text("\n".join(lines) + "\n")
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "SELECT * FROM health_runs")
        assert "150 total rows" in result
        assert "showing first 100" in result
        conn.close()

    def test_handles_sql_errors(self, tmp_path):
        conn = build_ops_db(tmp_path)
        result = run_sql(conn, "SELECT * FROM nonexistent_table")
        assert "SQL error" in result
        conn.close()


class TestGetTableSchemas:
    def test_returns_all_create_statements(self, tmp_path):
        """get_table_schemas returns DDL for all 5 tables."""
        conn = build_ops_db(tmp_path)
        schemas = get_table_schemas(conn)
        assert "health_runs" in schemas
        assert "drift_items" in schemas
        assert "drift_runs" in schemas
        assert "digest_runs" in schemas
        assert "knowledge_maint" in schemas
        assert "CREATE TABLE" in schemas
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ops_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.ops_db'`

- [ ] **Step 3: Implement shared/ops_db.py**

```python
# shared/ops_db.py
"""shared/ops_db.py — Build in-memory SQLite from operational JSONL/JSON files.

Reusable by query agents, voice tools, cockpit collectors, or any consumer
needing SQL access to operational history data.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

log = logging.getLogger("shared.ops_db")

# ── Schema ───────────────────────────────────────────────────────────────────

_TABLES = {
    "health_runs": """
        CREATE TABLE health_runs (
            timestamp TEXT NOT NULL,
            status TEXT NOT NULL,
            healthy INTEGER NOT NULL DEFAULT 0,
            degraded INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            failed_checks TEXT NOT NULL DEFAULT '[]'
        )
    """,
    "drift_items": """
        CREATE TABLE drift_items (
            severity TEXT NOT NULL,
            category TEXT NOT NULL,
            doc_file TEXT NOT NULL DEFAULT '',
            doc_claim TEXT NOT NULL DEFAULT '',
            reality TEXT NOT NULL DEFAULT '',
            suggestion TEXT NOT NULL DEFAULT ''
        )
    """,
    "drift_runs": """
        CREATE TABLE drift_runs (
            timestamp TEXT NOT NULL,
            drift_count INTEGER NOT NULL DEFAULT 0,
            docs_analyzed INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT ''
        )
    """,
    "digest_runs": """
        CREATE TABLE digest_runs (
            timestamp TEXT NOT NULL,
            hours INTEGER NOT NULL DEFAULT 0,
            headline TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            new_documents INTEGER NOT NULL DEFAULT 0
        )
    """,
    "knowledge_maint": """
        CREATE TABLE knowledge_maint (
            timestamp TEXT NOT NULL,
            pruned_count INTEGER NOT NULL DEFAULT 0,
            merged_count INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0
        )
    """,
}

_INDEXES = [
    "CREATE INDEX idx_health_timestamp ON health_runs(timestamp)",
    "CREATE INDEX idx_health_status ON health_runs(status)",
    "CREATE INDEX idx_drift_items_severity ON drift_items(severity)",
    "CREATE INDEX idx_drift_runs_timestamp ON drift_runs(timestamp)",
    "CREATE INDEX idx_digest_timestamp ON digest_runs(timestamp)",
    "CREATE INDEX idx_maint_timestamp ON knowledge_maint(timestamp)",
]


# ── Loaders ──────────────────────────────────────────────────────────────────

def _load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file, skipping malformed lines."""
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            log.debug("Skipping malformed JSONL line in %s", path.name)
    return entries


def _load_json(path: Path) -> dict | None:
    """Load a JSON file, returning None if missing or invalid."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        log.debug("Failed to load %s", path.name)
        return None


def _insert_health_runs(conn: sqlite3.Connection, profiles_dir: Path) -> int:
    entries = _load_jsonl(profiles_dir / "health-history.jsonl")
    for e in entries:
        conn.execute(
            "INSERT INTO health_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                e.get("timestamp", ""),
                e.get("status", "unknown"),
                e.get("healthy", 0),
                e.get("degraded", 0),
                e.get("failed", 0),
                e.get("duration_ms", 0),
                json.dumps(e.get("failed_checks", [])),
            ),
        )
    return len(entries)


def _insert_drift_items(conn: sqlite3.Connection, profiles_dir: Path) -> int:
    report = _load_json(profiles_dir / "drift-report.json")
    if not report:
        return 0
    items = report.get("drift_items", [])
    for item in items:
        conn.execute(
            "INSERT INTO drift_items VALUES (?, ?, ?, ?, ?, ?)",
            (
                item.get("severity", ""),
                item.get("category", ""),
                item.get("doc_file", ""),
                item.get("doc_claim", ""),
                item.get("reality", ""),
                item.get("suggestion", ""),
            ),
        )
    return len(items)


def _insert_drift_runs(conn: sqlite3.Connection, profiles_dir: Path) -> int:
    entries = _load_jsonl(profiles_dir / "drift-history.jsonl")
    for e in entries:
        conn.execute(
            "INSERT INTO drift_runs VALUES (?, ?, ?, ?)",
            (
                e.get("timestamp", ""),
                e.get("drift_count", 0),
                e.get("docs_analyzed", 0),
                e.get("summary", ""),
            ),
        )
    return len(entries)


def _insert_digest_runs(conn: sqlite3.Connection, profiles_dir: Path) -> int:
    entries = _load_jsonl(profiles_dir / "digest-history.jsonl")
    for e in entries:
        conn.execute(
            "INSERT INTO digest_runs VALUES (?, ?, ?, ?, ?)",
            (
                e.get("timestamp", ""),
                e.get("hours", 0),
                e.get("headline", ""),
                e.get("summary", ""),
                e.get("new_documents", 0),
            ),
        )
    return len(entries)


def _insert_knowledge_maint(conn: sqlite3.Connection, profiles_dir: Path) -> int:
    entries = _load_jsonl(profiles_dir / "knowledge-maint-history.jsonl")
    for e in entries:
        conn.execute(
            "INSERT INTO knowledge_maint VALUES (?, ?, ?, ?)",
            (
                e.get("timestamp", ""),
                e.get("pruned_count", 0),
                e.get("merged_count", 0),
                e.get("duration_ms", 0),
            ),
        )
    return len(entries)


# ── Public API ───────────────────────────────────────────────────────────────

def build_ops_db(profiles_dir: Path) -> sqlite3.Connection:
    """Build an in-memory SQLite database from operational data files.

    Args:
        profiles_dir: Path to the profiles/ directory containing JSONL/JSON files.

    Returns:
        sqlite3.Connection to the populated in-memory database.
    """
    conn = sqlite3.connect(":memory:")

    for ddl in _TABLES.values():
        conn.execute(ddl)
    for idx in _INDEXES:
        conn.execute(idx)

    counts = {
        "health_runs": _insert_health_runs(conn, profiles_dir),
        "drift_items": _insert_drift_items(conn, profiles_dir),
        "drift_runs": _insert_drift_runs(conn, profiles_dir),
        "digest_runs": _insert_digest_runs(conn, profiles_dir),
        "knowledge_maint": _insert_knowledge_maint(conn, profiles_dir),
    }
    conn.commit()

    log.info("Built ops DB: %s", ", ".join(f"{k}={v}" for k, v in counts.items()))
    return conn


def get_table_schemas(conn: sqlite3.Connection) -> str:
    """Return DDL for all tables in the database."""
    cursor = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    return "\n\n".join(row[0] for row in cursor.fetchall() if row[0])


def run_sql(conn: sqlite3.Connection, query: str) -> str:
    """Execute a read-only SQL query and return formatted results.

    Reusable by any consumer — not tied to pydantic-ai.
    """
    read_only_prefixes = ("select", "with", "explain", "pragma")
    stripped = query.strip().lower()
    if not any(stripped.startswith(p) for p in read_only_prefixes):
        return "Error: Only SELECT/WITH/EXPLAIN/PRAGMA queries are allowed."

    try:
        cursor = conn.execute(query)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()

        if not rows:
            return "No results."

        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows[:100]:
            lines.append(" | ".join(str(v) for v in row))

        if len(rows) > 100:
            lines.append(f"... ({len(rows)} total rows, showing first 100)")

        return "\n".join(lines)
    except Exception as e:
        return f"SQL error: {e}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ops_db.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add shared/ops_db.py tests/test_ops_db.py
git commit -m "feat: add shared ops_db module for operational SQLite builder"
```

---

### Task 2: shared/ops_live.py — Live Infrastructure Queries

**Files:**
- Create: `shared/ops_live.py`
- Test: `tests/test_ops_live.py`

Pure data-fetching functions for live infrastructure state. No pydantic-ai dependency. Each function returns a formatted string suitable for LLM consumption.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ops_live.py
"""Tests for shared.ops_live — live infrastructure queries."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from shared.ops_live import (
    get_infra_snapshot,
    get_manifest_section,
    query_langfuse_cost,
    query_qdrant_stats,
)


class TestGetInfraSnapshot:
    def test_reads_snapshot_file(self, tmp_path):
        snapshot = tmp_path / "infra-snapshot.json"
        snapshot.write_text(json.dumps({
            "timestamp": "2026-03-11T01:33:38Z",
            "cycle_mode": "prod",
            "containers": [
                {"service": "qdrant", "name": "qdrant", "state": "running", "health": "healthy"},
            ],
            "timers": [
                {"unit": "health-monitor.timer", "type": "systemd", "status": "active"},
            ],
            "gpu": {"used_mb": 5842, "total_mb": 24576, "free_mb": 18734, "loaded_models": ["nomic-embed-text"]},
        }))
        result = get_infra_snapshot(tmp_path)
        assert "qdrant" in result
        assert "running" in result
        assert "prod" in result
        assert "5842" in result

    def test_missing_file_returns_message(self, tmp_path):
        result = get_infra_snapshot(tmp_path)
        assert "not available" in result.lower() or "not found" in result.lower()


class TestGetManifestSection:
    def test_reads_docker_section(self, tmp_path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({
            "docker": {"containers": [{"service": "qdrant", "status": "running"}]},
            "gpu": {"name": "RTX 3090", "vram_total_mb": 24576},
        }))
        result = get_manifest_section(tmp_path, "docker")
        assert "qdrant" in result

    def test_unknown_section_returns_available(self, tmp_path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"docker": {}, "gpu": {}}))
        result = get_manifest_section(tmp_path, "nonexistent")
        assert "docker" in result.lower() or "available" in result.lower()

    def test_missing_file_returns_message(self, tmp_path):
        result = get_manifest_section(tmp_path, "docker")
        assert "not available" in result.lower() or "not found" in result.lower()


class TestQueryLangfuseCost:
    @patch("shared.langfuse_client.langfuse_get")
    def test_returns_cost_breakdown(self, mock_get):
        mock_get.return_value = {
            "data": [
                {"model": "claude-sonnet", "calculatedTotalCost": 0.05, "startTime": "2026-03-10T10:00:00Z"},
                {"model": "claude-haiku", "calculatedTotalCost": 0.01, "startTime": "2026-03-10T11:00:00Z"},
            ],
            "meta": {"totalItems": 2},
        }
        result = query_langfuse_cost(days=7)
        assert "claude-sonnet" in result
        assert "0.05" in result or "0.06" in result  # total or per-model

    @patch("shared.ops_live.langfuse_get", return_value={})
    def test_unavailable_returns_message(self, mock_get):
        result = query_langfuse_cost(days=7)
        assert "not available" in result.lower() or "no data" in result.lower()


class TestQueryQdrantStats:
    @patch("shared.ops_live.get_qdrant")
    def test_returns_collection_stats(self, mock_qdrant):
        mock_collection = MagicMock()
        mock_collection.name = "documents"
        mock_qdrant.return_value.get_collections.return_value.collections = [mock_collection]
        mock_qdrant.return_value.count.return_value.count = 1500
        result = query_qdrant_stats()
        assert "documents" in result
        assert "1500" in result

    @patch("shared.ops_live.get_qdrant", side_effect=Exception("Connection refused"))
    def test_unavailable_returns_message(self, mock_qdrant):
        result = query_qdrant_stats()
        assert "not available" in result.lower() or "error" in result.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ops_live.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.ops_live'`

- [ ] **Step 3: Implement shared/ops_live.py**

```python
# shared/ops_live.py
"""shared/ops_live.py — Live infrastructure queries.

Reusable functions for fetching current infrastructure state from
files and HTTP endpoints. Returns formatted strings for LLM consumption.
No pydantic-ai dependency.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.ops_db import _load_json

log = logging.getLogger("shared.ops_live")


def get_infra_snapshot(profiles_dir: Path) -> str:
    """Read the current infrastructure snapshot.

    Returns formatted text describing containers, timers, GPU state.
    """
    data = _load_json(profiles_dir / "infra-snapshot.json")
    if not data:
        return "Infrastructure snapshot not found. The health monitor may not have run yet."

    lines = [f"Infrastructure Snapshot ({data.get('timestamp', 'unknown')})"]
    lines.append(f"Cycle mode: {data.get('cycle_mode', 'unknown')}")
    lines.append("")

    containers = data.get("containers", [])
    if containers:
        lines.append("Containers:")
        for c in containers:
            health = f" ({c['health']})" if c.get("health") else ""
            lines.append(f"  {c['service']:20s} {c['state']}{health}")
        lines.append("")

    timers = data.get("timers", [])
    if timers:
        lines.append("Timers:")
        for t in timers:
            lines.append(f"  {t['unit']:35s} {t.get('status', 'unknown'):10s} {t.get('type', '')}")
        lines.append("")

    gpu = data.get("gpu", {})
    if gpu:
        lines.append(f"GPU: {gpu.get('used_mb', '?')}MiB / {gpu.get('total_mb', '?')}MiB used")
        models = gpu.get("loaded_models", [])
        if models:
            lines.append(f"  Loaded models: {', '.join(models)}")

    return "\n".join(lines)


def get_manifest_section(profiles_dir: Path, section: str) -> str:
    """Read a specific section from the full infrastructure manifest.

    Valid sections: docker, systemd, qdrant, ollama, gpu, disk, ports, creds,
    litellm_routes, profile_files, listening_ports.
    """
    data = _load_json(profiles_dir / "manifest.json")
    if not data:
        return "Infrastructure manifest not found. Run `uv run python -m agents.introspect --save` to generate it."

    if section not in data:
        available = ", ".join(sorted(data.keys()))
        return f"Section '{section}' not found. Available sections: {available}"

    return json.dumps(data[section], indent=2, default=str)


def query_langfuse_cost(days: int = 7) -> str:
    """Query Langfuse for LLM cost data over the given window.

    Returns a formatted cost breakdown by model.
    """
    from shared.langfuse_client import langfuse_get, LANGFUSE_PK  # noqa: PLC0415

    if not LANGFUSE_PK:
        return "Langfuse not available (no credentials configured)."

    now = datetime.now(timezone.utc)
    from_time = (now - timedelta(days=days)).isoformat()

    model_costs: dict[str, dict] = {}
    page = 1
    total_cost = 0.0
    total_generations = 0

    while True:
        resp = langfuse_get(
            "/observations",
            {"type": "GENERATION", "fromStartTime": from_time, "limit": 100, "page": page},
            timeout=15,
        )
        if not resp:
            if page == 1:
                return "Langfuse not available or no data in the requested window."
            break

        data = resp.get("data", [])
        for obs in data:
            cost = obs.get("calculatedTotalCost") or 0.0
            model = obs.get("model") or "unknown"
            tokens_in = obs.get("promptTokens") or obs.get("usage", {}).get("input", 0) or 0
            tokens_out = obs.get("completionTokens") or obs.get("usage", {}).get("output", 0) or 0

            if model not in model_costs:
                model_costs[model] = {"cost": 0.0, "calls": 0, "tokens_in": 0, "tokens_out": 0}
            model_costs[model]["cost"] += cost
            model_costs[model]["calls"] += 1
            model_costs[model]["tokens_in"] += tokens_in
            model_costs[model]["tokens_out"] += tokens_out
            total_cost += cost
            total_generations += 1

        total_items = resp.get("meta", {}).get("totalItems", 0)
        if page * 100 >= total_items:
            break
        page += 1

    if not model_costs:
        return f"No LLM generations found in the last {days} days."

    lines = [f"LLM Cost Summary (last {days} days)"]
    lines.append(f"Total: ${total_cost:.4f} across {total_generations} generations")
    lines.append("")
    lines.append(f"{'Model':35s} {'Calls':>6s} {'Cost':>10s} {'Tokens In':>12s} {'Tokens Out':>12s}")
    lines.append("-" * 80)
    for model, stats in sorted(model_costs.items(), key=lambda x: -x[1]["cost"]):
        lines.append(
            f"{model:35s} {stats['calls']:6d} ${stats['cost']:9.4f} "
            f"{stats['tokens_in']:12,d} {stats['tokens_out']:12,d}"
        )

    return "\n".join(lines)


def query_qdrant_stats() -> str:
    """Query Qdrant for collection statistics.

    Returns a formatted table of collection names, point counts, and dimensions.
    """
    try:
        from shared.config import get_qdrant
        client = get_qdrant()
        collections = client.get_collections().collections
    except Exception as e:
        return f"Qdrant not available: {e}"

    if not collections:
        return "No Qdrant collections found."

    lines = ["Qdrant Collections:"]
    lines.append(f"{'Collection':25s} {'Points':>10s}")
    lines.append("-" * 40)
    for coll in sorted(collections, key=lambda c: c.name):
        try:
            count = client.count(coll.name).count
        except Exception:
            count = "error"
        lines.append(f"{coll.name:25s} {str(count):>10s}")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ops_live.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add shared/ops_live.py tests/test_ops_live.py
git commit -m "feat: add shared ops_live module for live infrastructure queries"
```

---

### Task 3: shared/knowledge_search.py — Qdrant Search & Artifact Reads

**Files:**
- Create: `shared/knowledge_search.py`
- Test: `tests/test_knowledge_search.py`

Reusable semantic search and artifact read functions. No pydantic-ai dependency.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_knowledge_search.py
"""Tests for shared.knowledge_search — Qdrant search & artifact reads."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from shared.knowledge_search import (
    search_documents,
    search_profile,
    search_memory,
    read_briefing,
    read_digest,
    read_scout_report,
    get_operator_goals,
    get_collection_stats,
)


class TestSearchDocuments:
    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed")
    def test_returns_formatted_results(self, mock_embed, mock_qdrant):
        mock_embed.return_value = [0.1] * 768
        mock_point = MagicMock()
        mock_point.payload = {
            "text": "Meeting notes from Monday",
            "source": "/path/to/file.md",
            "source_service": "obsidian",
            "ingested_at": 1710000000.0,
        }
        mock_point.score = 0.92
        mock_qdrant.return_value.query_points.return_value.points = [mock_point]

        result = search_documents("meeting notes")
        assert "Meeting notes from Monday" in result
        assert "obsidian" in result
        assert "0.92" in result

    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed")
    def test_source_service_filter(self, mock_embed, mock_qdrant):
        mock_embed.return_value = [0.1] * 768
        mock_qdrant.return_value.query_points.return_value.points = []

        search_documents("test", source_service="gmail")
        call_kwargs = mock_qdrant.return_value.query_points.call_args
        query_filter = call_kwargs.kwargs.get("query_filter") or call_kwargs[1].get("query_filter")
        assert query_filter is not None

    @patch("shared.knowledge_search.get_qdrant", side_effect=Exception("Connection refused"))
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_unavailable_returns_message(self, mock_embed, mock_qdrant):
        result = search_documents("test")
        assert "error" in result.lower() or "not available" in result.lower()


class TestSearchProfile:
    @patch("shared.knowledge_search.ProfileStore")
    def test_returns_formatted_facts(self, mock_store_cls):
        mock_store = mock_store_cls.return_value
        mock_store.search.return_value = [
            {"dimension": "tool_usage", "key": "preferred_editor", "value": "Claude Code", "confidence": 0.9, "score": 0.88},
        ]
        result = search_profile("tool preferences")
        assert "tool_usage" in result
        assert "Claude Code" in result
        assert "0.9" in result

    @patch("shared.knowledge_search.ProfileStore")
    def test_dimension_filter_passed(self, mock_store_cls):
        mock_store = mock_store_cls.return_value
        mock_store.search.return_value = []
        search_profile("test", dimension="work_patterns")
        mock_store.search.assert_called_once_with("test", dimension="work_patterns", limit=5)

    @patch("shared.knowledge_search.ProfileStore", side_effect=Exception("Connection refused"))
    def test_unavailable_returns_message(self, mock_store_cls):
        result = search_profile("test")
        assert "error" in result.lower()


class TestSearchMemory:
    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed")
    def test_searches_claude_memory_collection(self, mock_embed, mock_qdrant):
        mock_embed.return_value = [0.1] * 768
        mock_qdrant.return_value.query_points.return_value.points = []
        search_memory("test query")
        call_args = mock_qdrant.return_value.query_points.call_args
        assert call_args[0][0] == "claude-memory" or call_args.kwargs.get("collection_name") == "claude-memory"


class TestReadBriefing:
    def test_reads_briefing_file(self, tmp_path):
        briefing = tmp_path / "briefing.json"
        briefing.write_text(json.dumps({
            "generated_at": "2026-03-10T07:00:00Z",
            "headline": "All systems nominal",
            "action_items": [{"priority": "high", "action": "Review drift"}],
        }))
        result = read_briefing(tmp_path)
        assert "All systems nominal" in result
        assert "Review drift" in result

    def test_missing_file(self, tmp_path):
        result = read_briefing(tmp_path)
        assert "not available" in result.lower() or "not found" in result.lower()


class TestReadDigest:
    def test_reads_digest_file(self, tmp_path):
        digest = tmp_path / "digest.json"
        digest.write_text(json.dumps({
            "generated_at": "2026-03-10T06:45:00Z",
            "headline": "5 new documents ingested",
            "notable_items": [{"title": "API design doc", "source": "gdrive"}],
        }))
        result = read_digest(tmp_path)
        assert "5 new documents" in result
        assert "API design doc" in result

    def test_missing_file(self, tmp_path):
        result = read_digest(tmp_path)
        assert "not available" in result.lower() or "not found" in result.lower()


class TestReadScoutReport:
    def test_reads_scout_file(self, tmp_path):
        scout = tmp_path / "scout-report.json"
        scout.write_text(json.dumps({
            "generated_at": "2026-03-05T10:00:00Z",
            "recommendations": [
                {"component": "embeddings", "tier": "evaluate", "summary": "Try new model"}
            ],
        }))
        result = read_scout_report(tmp_path)
        assert "embeddings" in result
        assert "evaluate" in result

    def test_missing_file(self, tmp_path):
        result = read_scout_report(tmp_path)
        assert "not available" in result.lower() or "not found" in result.lower()


class TestGetOperatorGoals:
    def test_reads_goals_from_operator(self, tmp_path):
        operator = tmp_path / "operator.json"
        operator.write_text(json.dumps({
            "goals": {
                "primary": [
                    {"id": "g1", "name": "Ship cockpit", "status": "active"},
                ],
                "secondary": [
                    {"id": "g2", "name": "Voice daemon stability", "status": "active"},
                ],
            },
        }))
        result = get_operator_goals(tmp_path)
        assert "Ship cockpit" in result
        assert "Voice daemon" in result

    def test_missing_file(self, tmp_path):
        result = get_operator_goals(tmp_path)
        assert "not available" in result.lower() or "not found" in result.lower()


class TestGetCollectionStats:
    @patch("shared.knowledge_search.get_qdrant")
    def test_returns_all_collections(self, mock_qdrant):
        coll1 = MagicMock()
        coll1.name = "documents"
        coll2 = MagicMock()
        coll2.name = "profile-facts"
        mock_qdrant.return_value.get_collections.return_value.collections = [coll1, coll2]
        mock_qdrant.return_value.count.return_value.count = 500
        result = get_collection_stats()
        assert "documents" in result
        assert "profile-facts" in result
        assert "500" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_knowledge_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shared.knowledge_search'`

- [ ] **Step 3: Implement shared/knowledge_search.py**

```python
# shared/knowledge_search.py
"""shared/knowledge_search.py — Qdrant semantic search & knowledge artifact reads.

Reusable by query agents, voice tools, or any consumer needing
semantic search over Qdrant collections and access to knowledge artifacts.
No pydantic-ai dependency.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shared.ops_db import _load_json

log = logging.getLogger("shared.knowledge_search")


# ── Qdrant Search ────────────────────────────────────────────────────────────

def search_documents(
    query: str,
    *,
    source_service: str | None = None,
    content_type: str | None = None,
    days_back: int | None = None,
    limit: int = 10,
) -> str:
    """Semantic search over the documents collection.

    Args:
        query: Natural language search query.
        source_service: Filter by source (gdrive, gmail, obsidian, etc.).
        content_type: Filter by content type (document, email_metadata, etc.).
        days_back: Only include documents ingested in the last N days.
        limit: Maximum results to return.

    Returns:
        Formatted text with search results and scores.
    """
    try:
        from shared.config import get_qdrant, embed
        from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

        query_vec = embed(query, prefix="search_query")
        client = get_qdrant()

        conditions = []
        if source_service:
            conditions.append(
                FieldCondition(key="source_service", match=MatchValue(value=source_service))
            )
        if content_type:
            conditions.append(
                FieldCondition(key="content_type", match=MatchValue(value=content_type))
            )
        if days_back:
            since_ts = (datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp()
            conditions.append(
                FieldCondition(key="ingested_at", range=Range(gte=since_ts))
            )

        query_filter = Filter(must=conditions) if conditions else None

        results = client.query_points(
            "documents",
            query=query_vec,
            query_filter=query_filter,
            limit=limit,
        )
    except Exception as e:
        return f"Document search error: {e}"

    if not results.points:
        filters = []
        if source_service:
            filters.append(f"source_service={source_service}")
        if content_type:
            filters.append(f"content_type={content_type}")
        if days_back:
            filters.append(f"last {days_back} days")
        filter_desc = f" (filters: {', '.join(filters)})" if filters else ""
        return f"No documents found matching '{query}'{filter_desc}."

    lines = [f"Found {len(results.points)} results for '{query}':", ""]
    for i, pt in enumerate(results.points, 1):
        p = pt.payload
        text = p.get("text", "")[:300]
        source = p.get("source", "unknown")
        service = p.get("source_service", "unknown")
        lines.append(f"**Result {i}** (score: {pt.score:.2f}, source: {service})")
        lines.append(f"  File: {source}")
        lines.append(f"  {text}")
        lines.append("")

    return "\n".join(lines)


def search_profile(
    query: str,
    *,
    dimension: str | None = None,
    limit: int = 5,
) -> str:
    """Semantic search over operator profile facts.

    Args:
        query: Natural language search query.
        dimension: Filter by dimension (e.g., "work_patterns", "tool_usage").
        limit: Maximum results to return.

    Returns:
        Formatted text with matching profile facts.
    """
    try:
        from shared.profile_store import ProfileStore
        store = ProfileStore()
        results = store.search(query, dimension=dimension, limit=limit)
    except Exception as e:
        return f"Profile search error: {e}"

    if not results:
        dim_note = f" in dimension '{dimension}'" if dimension else ""
        return f"No profile facts found matching '{query}'{dim_note}."

    lines = [f"Found {len(results)} profile facts:", ""]
    for r in results:
        lines.append(
            f"- [{r['dimension']}/{r['key']}] {r['value']} "
            f"(confidence: {r['confidence']:.2f}, score: {r['score']:.2f})"
        )

    return "\n".join(lines)


def search_memory(query: str, *, limit: int = 5) -> str:
    """Semantic search over the claude-memory collection.

    Args:
        query: Natural language search query.
        limit: Maximum results to return.

    Returns:
        Formatted text with matching memory entries.
    """
    try:
        from shared.config import get_qdrant, embed
        query_vec = embed(query, prefix="search_query")
        client = get_qdrant()
        results = client.query_points("claude-memory", query=query_vec, limit=limit)
    except Exception as e:
        return f"Memory search error: {e}"

    if not results.points:
        return f"No memory entries found matching '{query}'."

    lines = [f"Found {len(results.points)} memory entries:", ""]
    for i, pt in enumerate(results.points, 1):
        text = pt.payload.get("text", pt.payload.get("content", ""))[:300]
        lines.append(f"**Entry {i}** (score: {pt.score:.2f})")
        lines.append(f"  {text}")
        lines.append("")

    return "\n".join(lines)


# ── Artifact Reads ───────────────────────────────────────────────────────────

def read_briefing(profiles_dir: Path) -> str:
    """Read the latest daily briefing."""
    data = _load_json(profiles_dir / "briefing.json")
    if not data:
        return "Daily briefing not available. It may not have run yet today."

    lines = [f"Daily Briefing ({data.get('generated_at', 'unknown')})"]
    lines.append(f"Headline: {data.get('headline', 'none')}")
    lines.append("")

    body = data.get("body", "")
    if body:
        lines.append(body[:2000])
        lines.append("")

    actions = data.get("action_items", [])
    if actions:
        lines.append("Action Items:")
        for a in actions:
            priority = a.get("priority", "medium")
            lines.append(f"  [{priority}] {a.get('action', '')}")
            if a.get("reason"):
                lines.append(f"    Reason: {a['reason']}")
        lines.append("")

    stats = data.get("stats", {})
    if stats:
        lines.append("Stats:")
        for k, v in stats.items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


def read_digest(profiles_dir: Path) -> str:
    """Read the latest knowledge digest."""
    data = _load_json(profiles_dir / "digest.json")
    if not data:
        return "Knowledge digest not available. It may not have run yet today."

    lines = [f"Knowledge Digest ({data.get('generated_at', 'unknown')})"]
    lines.append(f"Headline: {data.get('headline', 'none')}")
    lines.append("")

    summary = data.get("summary", "")
    if summary:
        lines.append(summary[:1000])
        lines.append("")

    items = data.get("notable_items", [])
    if items:
        lines.append("Notable Items:")
        for item in items:
            lines.append(f"  - {item.get('title', '')} (source: {item.get('source', 'unknown')})")
            if item.get("relevance"):
                lines.append(f"    {item['relevance']}")
        lines.append("")

    actions = data.get("suggested_actions", [])
    if actions:
        lines.append("Suggested Actions:")
        for a in actions:
            lines.append(f"  - {a}")

    return "\n".join(lines)


def read_scout_report(profiles_dir: Path) -> str:
    """Read the latest scout (horizon scan) report."""
    data = _load_json(profiles_dir / "scout-report.json")
    if not data:
        return "Scout report not available. The scout agent runs weekly."

    lines = [f"Scout Report ({data.get('generated_at', 'unknown')})"]
    lines.append(f"Components scanned: {data.get('components_scanned', '?')}")
    lines.append("")

    recs = data.get("recommendations", [])
    if recs:
        lines.append("Recommendations:")
        for r in recs:
            lines.append(
                f"  [{r.get('tier', '?')}] {r.get('component', '?')}: "
                f"{r.get('summary', '')}"
            )
            if r.get("migration_effort"):
                lines.append(f"    Effort: {r['migration_effort']}, Confidence: {r.get('confidence', '?')}")
            for f in r.get("findings", []):
                lines.append(f"    - {f.get('name', '')}: {f.get('description', '')}")
        lines.append("")

    errors = data.get("errors", [])
    if errors:
        lines.append(f"Errors: {', '.join(errors)}")

    return "\n".join(lines)


def get_operator_goals(profiles_dir: Path) -> str:
    """Read active operator goals from the operator manifest."""
    data = _load_json(profiles_dir / "operator.json")
    if not data:
        return "Operator manifest not available."

    goals = data.get("goals", {})
    lines = ["Operator Goals:", ""]

    for tier in ("primary", "secondary"):
        tier_goals = goals.get(tier, [])
        if tier_goals:
            lines.append(f"{tier.title()}:")
            for g in tier_goals:
                status = g.get("status", "unknown")
                lines.append(f"  - [{status}] {g.get('name', '?')}: {g.get('description', '')}")
                if g.get("last_activity_at"):
                    lines.append(f"    Last activity: {g['last_activity_at']}")
            lines.append("")

    if len(lines) <= 2:
        return "No goals defined in operator manifest."

    return "\n".join(lines)


def get_collection_stats() -> str:
    """Get point counts for all Qdrant collections.

    Delegates to shared.ops_live.query_qdrant_stats to avoid duplication.
    """
    from shared.ops_live import query_qdrant_stats  # noqa: PLC0415
    return query_qdrant_stats()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_knowledge_search.py -v`
Expected: All 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add shared/knowledge_search.py tests/test_knowledge_search.py
git commit -m "feat: add shared knowledge_search module for Qdrant search and artifact reads"
```

---

## Chunk 2: System Operations Query Agent

### Task 4: agents/system_ops/query.py — Agent Definition

**Files:**
- Create: `agents/system_ops/__init__.py`
- Create: `agents/system_ops/query.py`
- Test: `tests/test_system_ops_query.py`

The pydantic-ai agent that wires shared data-access functions as tools.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_system_ops_query.py
"""Tests for agents.system_ops.query — system operations query agent."""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.system_ops.query import (
    SystemOpsDeps,
    build_system_prompt,
    create_agent,
)


class TestBuildSystemPrompt:
    def test_includes_table_schemas(self):
        prompt = build_system_prompt()
        assert "health_runs" in prompt
        assert "drift_items" in prompt
        assert "drift_runs" in prompt
        assert "digest_runs" in prompt
        assert "knowledge_maint" in prompt

    def test_includes_paradigm_guidance(self):
        prompt = build_system_prompt()
        assert "sql" in prompt.lower() or "SQL" in prompt
        assert "live" in prompt.lower()

    def test_includes_mermaid_instructions(self):
        prompt = build_system_prompt()
        assert "mermaid" in prompt.lower()
        assert "```mermaid" in prompt


class TestCreateAgent:
    def test_creates_agent_with_deps_type(self):
        agent = create_agent()
        assert agent.deps_type is SystemOpsDeps

    def test_agent_has_expected_tools(self):
        agent = create_agent()
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        assert "sql_query" in tool_names
        assert "table_schemas" in tool_names
        assert "infra_snapshot" in tool_names
        assert "manifest_section" in tool_names
        assert "langfuse_cost" in tool_names
        assert "qdrant_stats" in tool_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_system_ops_query.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.system_ops'`

- [ ] **Step 3: Create agents/system_ops/__init__.py**

```python
# agents/system_ops/__init__.py
"""System Operations — infrastructure health and operational analytics agent."""
```

- [ ] **Step 4: Implement agents/system_ops/query.py**

```python
# agents/system_ops/query.py
"""Pydantic-ai query agent for system operations and infrastructure."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent

from shared.config import get_model
from shared.ops_db import build_ops_db, get_table_schemas as _get_table_schemas, run_sql

log = logging.getLogger(__name__)


def build_system_prompt() -> str:
    """Build the system prompt for the system operations agent."""
    return """You are a system operations analyst. You answer questions about infrastructure
health, Docker services, systemd timers, GPU state, documentation drift, LLM costs,
and operational analytics. You are precise and evidence-driven.

## Data Access — Two Paradigms

### SQL (historical data)
Use the `sql_query` tool for time-series and aggregate questions: trends, uptime
calculations, recurring failures, cost over time. Call `table_schemas` first to see
available columns.

**Tables:**

- **health_runs**: Per-run health check results (every 15 minutes).
  Columns: timestamp (ISO 8601), status (healthy/degraded/failed), healthy (int),
  degraded (int), failed (int), duration_ms (int), failed_checks (JSON array of strings).
  Use `json_each(failed_checks)` to unnest failed check names.

- **drift_items**: Current documentation drift findings.
  Columns: severity (high/medium/low), category, doc_file, doc_claim, reality, suggestion.

- **drift_runs**: Historical drift detection runs.
  Columns: timestamp, drift_count, docs_analyzed, summary.

- **digest_runs**: Daily knowledge digest history.
  Columns: timestamp, hours, headline, summary, new_documents.

- **knowledge_maint**: Qdrant maintenance run history.
  Columns: timestamp, pruned_count, merged_count, duration_ms.

**SQL tips:**
- Timestamps are ISO 8601 strings. Use `substr(timestamp, 1, 10)` for date grouping.
- Use `json_each(failed_checks)` to analyze which checks fail most often.
- Only SELECT/WITH/EXPLAIN/PRAGMA queries are allowed.

### Live tools (current state)
Use `infra_snapshot`, `manifest_section`, `langfuse_cost`, and `qdrant_stats` for
"right now" questions: current container status, loaded GPU models, today's costs.

## How to Answer

1. Determine if the question is about history/trends (→ SQL) or current state (→ live tools).
2. For mixed questions, use both — e.g., "is health improving?" needs SQL for the trend
   and infra_snapshot for the current state.
3. Show your data: include query results or tool output before narrative.
4. All counts must come from actual data, never estimated.
5. Begin with a content heading (#). No narration of your process.
6. When evidence is thin, say so rather than speculating.

## Diagram generation
When your answer involves relationships, flows, timelines, or architecture,
include Mermaid diagrams using fenced code blocks:

    ```mermaid
    graph TD
      A[HealthMonitor] --> B[health-history.jsonl]
      C[DriftDetector] --> D[drift-report.json]
    ```

Useful diagram types:
- Service dependencies: graph TD or graph LR
- Health timelines: gantt
- Container topology: flowchart

Keep diagrams focused — max 15-20 nodes.
"""


@dataclass
class SystemOpsDeps:
    """Runtime dependencies for the system operations agent."""

    profiles_dir: Path
    db: sqlite3.Connection


def create_agent() -> Agent:
    """Create the system operations query agent."""
    agent = Agent(
        get_model("balanced"),
        system_prompt=build_system_prompt(),
        deps_type=SystemOpsDeps,
        model_settings={"max_tokens": 8192},
    )

    @agent.tool
    async def sql_query(ctx, query: str) -> str:
        """Execute read-only SQL against the operations database.

        Tables: health_runs, drift_items, drift_runs, digest_runs, knowledge_maint.
        Use for historical trends and aggregations.
        """
        return run_sql(ctx.deps.db, query)

    @agent.tool
    async def table_schemas(ctx) -> str:
        """Return the SQL CREATE TABLE statements for all tables."""
        return _get_table_schemas(ctx.deps.db)

    @agent.tool
    async def infra_snapshot(ctx) -> str:
        """Get the current infrastructure state: containers, timers, GPU, cycle mode.

        Updated every 15 minutes by the health monitor.
        """
        from shared.ops_live import get_infra_snapshot
        return get_infra_snapshot(ctx.deps.profiles_dir)

    @agent.tool
    async def manifest_section(ctx, section: str) -> str:
        """Read a section from the full infrastructure manifest.

        Valid sections: docker, systemd, qdrant_collections, ollama, gpu,
        disk, listening_ports, pass_entries, litellm_routes, profile_files.
        """
        from shared.ops_live import get_manifest_section
        return get_manifest_section(ctx.deps.profiles_dir, section)

    @agent.tool
    async def langfuse_cost(ctx, days: int = 7) -> str:
        """Query LLM usage costs from Langfuse for the given time window.

        Returns per-model cost breakdown with token counts.
        """
        from shared.ops_live import query_langfuse_cost
        return query_langfuse_cost(days=days)

    @agent.tool
    async def qdrant_stats(ctx) -> str:
        """Get current Qdrant collection statistics: names and point counts."""
        from shared.ops_live import query_qdrant_stats
        return query_qdrant_stats()

    return agent
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_system_ops_query.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add agents/system_ops/__init__.py agents/system_ops/query.py tests/test_system_ops_query.py
git commit -m "feat: add system operations query agent"
```

---

### Task 5: Register system_ops in query_dispatch.py

**Files:**
- Modify: `cockpit/query_dispatch.py`
- Modify: `tests/test_query_dispatch.py`

- [ ] **Step 1: Write failing tests for new agent registration**

Add to `tests/test_query_dispatch.py`:

```python
# Add these test classes to tests/test_query_dispatch.py

class TestClassifyQueryMultiAgent:
    """Classification tests with multiple agents registered."""

    def test_health_query_routes_to_system_ops(self):
        result = classify_query("what is the system health status?")
        assert result == "system_ops"

    def test_docker_query_routes_to_system_ops(self):
        result = classify_query("which docker containers are running?")
        assert result == "system_ops"

    def test_cost_query_routes_to_system_ops(self):
        result = classify_query("how much did we spend on LLM costs?")
        assert result == "system_ops"

    def test_commit_query_still_routes_to_dev_story(self):
        result = classify_query("show me commit history and session patterns")
        assert result == "dev_story"

    def test_drift_routes_to_system_ops(self):
        result = classify_query("what infrastructure has drifted from docs?")
        assert result == "system_ops"


class TestGetAgentListMultiAgent:
    def test_includes_system_ops(self):
        agents = get_agent_list()
        types = {a.agent_type for a in agents}
        assert "system_ops" in types
        assert "dev_story" in types


class TestRunQuerySystemOps:
    @patch("cockpit.query_dispatch.extract_full_output", return_value="## Health\nAll good")
    @patch("cockpit.query_dispatch._call_factory")
    async def test_run_system_ops_query(self, mock_factory, mock_extract):
        mock_result = MagicMock()
        mock_result.usage.return_value = MagicMock(
            input_tokens=800, output_tokens=400
        )
        mock_agent = AsyncMock()
        mock_agent.run.return_value = mock_result
        mock_factory.return_value = (mock_agent, MagicMock())

        result = await run_query("system_ops", "what is the health status?")

        assert result.markdown == "## Health\nAll good"
        assert result.agent_type == "system_ops"
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `uv run pytest tests/test_query_dispatch.py -v`
Expected: New classification tests FAIL (system_ops not registered yet)

- [ ] **Step 3: Update cockpit/query_dispatch.py**

Add system_ops to the `_AGENTS` registry after the dev_story entry:

```python
# In _AGENTS dict, add after the dev_story entry:
    "system_ops": {
        "name": "System Operations",
        "description": "Query infrastructure health, Docker services, costs, drift, and operational state",
        "keywords": [
            "health", "docker", "container", "service", "timer", "systemd",
            "gpu", "vram", "ollama", "model", "cost", "spend", "langfuse",
            "drift", "uptime", "degraded", "failed", "qdrant", "collection",
            "infrastructure", "disk", "port", "running", "status",
        ],
    },
```

Add the factory function after `_create_dev_story_agent`:

```python
def _create_system_ops_agent():
    """Create the system-ops query agent and its deps."""
    from agents.system_ops.query import SystemOpsDeps, create_agent as create_system_ops_agent
    from shared.ops_db import build_ops_db

    db = build_ops_db(PROFILES_DIR)
    agent = create_system_ops_agent()
    deps = SystemOpsDeps(profiles_dir=PROFILES_DIR, db=db)
    return agent, deps
```

Add to `_AGENT_FACTORY_NAMES`:

```python
_AGENT_FACTORY_NAMES: dict[str, str] = {
    "dev_story": "_create_dev_story_agent",
    "system_ops": "_create_system_ops_agent",
}
```

Also update `classify_query` — remove the early-return for single agent since we now have 2+:

```python
def classify_query(query: str) -> str:
    """Classify a natural language query to select the best agent."""
    query_lower = query.lower()
    best_agent = next(iter(_AGENTS))
    best_score = 0

    for agent_type, info in _AGENTS.items():
        score = sum(1 for kw in info["keywords"] if kw in query_lower)
        if score > best_score:
            best_score = score
            best_agent = agent_type

    return best_agent
```

- [ ] **Step 4: Run all dispatch tests**

Run: `uv run pytest tests/test_query_dispatch.py -v`
Expected: All tests PASS (old + new)

- [ ] **Step 5: Commit**

```bash
git add cockpit/query_dispatch.py tests/test_query_dispatch.py
git commit -m "feat: register system_ops agent in query dispatch"
```

---

## Chunk 3: Knowledge & Context Query Agent

### Task 6: agents/knowledge/query.py — Agent Definition

**Files:**
- Create: `agents/knowledge/__init__.py`
- Create: `agents/knowledge/query.py`
- Test: `tests/test_knowledge_query.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_knowledge_query.py
"""Tests for agents.knowledge.query — knowledge & context query agent."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from agents.knowledge.query import (
    KnowledgeDeps,
    build_system_prompt,
    create_agent,
)


class TestBuildSystemPrompt:
    def test_includes_collection_descriptions(self):
        prompt = build_system_prompt()
        assert "documents" in prompt
        assert "profile-facts" in prompt
        assert "claude-memory" in prompt

    def test_includes_source_service_guide(self):
        prompt = build_system_prompt()
        assert "gdrive" in prompt
        assert "gmail" in prompt
        assert "obsidian" in prompt

    def test_includes_mermaid_instructions(self):
        prompt = build_system_prompt()
        assert "mermaid" in prompt.lower()
        assert "```mermaid" in prompt


class TestCreateAgent:
    def test_creates_agent_with_deps_type(self):
        agent = create_agent()
        assert agent.deps_type is KnowledgeDeps

    def test_agent_has_expected_tools(self):
        agent = create_agent()
        tool_names = {t.name for t in agent._function_toolset.tools.values()}
        assert "search_docs" in tool_names
        assert "search_profile_facts" in tool_names
        assert "search_conv_memory" in tool_names
        assert "briefing" in tool_names
        assert "digest" in tool_names
        assert "scout_report" in tool_names
        assert "operator_goals" in tool_names
        assert "collection_stats" in tool_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_knowledge_query.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.knowledge'`

- [ ] **Step 3: Create agents/knowledge/__init__.py**

```python
# agents/knowledge/__init__.py
"""Knowledge & Context — semantic search and knowledge artifact query agent."""
```

- [ ] **Step 4: Implement agents/knowledge/query.py**

```python
# agents/knowledge/query.py
"""Pydantic-ai query agent for knowledge and context search."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai import Agent

from shared.config import get_model

log = logging.getLogger(__name__)


def build_system_prompt() -> str:
    """Build the system prompt for the knowledge & context agent."""
    return """You are a knowledge and context analyst. You answer questions by searching
across the operator's document corpus, profile facts, conversation memory, and
structured knowledge artifacts (briefings, digests, scout reports).

## Data Sources

### Qdrant Collections (semantic search)

**documents** — RAG chunks from 10 sync agents. This is the primary knowledge base.
Filter by `source_service` to narrow searches:
- `gdrive` — Google Drive documents (reports, specs, notes)
- `gcalendar` — Google Calendar events (meetings, schedules)
- `gmail` — Email metadata (subject, sender, labels — body for starred/important)
- `youtube` — YouTube subscriptions and liked videos
- `claude-code` — Claude Code session transcripts (development conversations)
- `obsidian` — Obsidian vault notes (personal knowledge base)
- `chrome` — Browser history and bookmarks
- `ambient-audio` — Transcribed ambient audio segments
- `takeout` — Google Takeout data
- `proton` — ProtonMail data

Filter by `content_type`: document, email_metadata, spreadsheet, presentation, etc.
Filter by `days_back` to restrict to recent documents.

**profile-facts** — Operator behavioral and trait profile.
11 dimensions: identity, neurocognitive, values, communication_style, relationships
(trait), work_patterns, energy_and_attention, information_seeking, creative_process,
tool_usage, communication_patterns (behavioral). Filter by `dimension`.

**claude-memory** — Persistent conversation memory across Claude Code sessions.

### Structured Artifacts (file reads)

- **Daily briefing** — Morning briefing with headline, action items, stats
- **Knowledge digest** — Daily digest of newly ingested documents
- **Scout report** — Weekly technology horizon scan with recommendations
- **Operator goals** — Active primary and secondary goals with status

## How to Answer

1. Determine which data source(s) are relevant:
   - "What did my email say about X?" → search_docs with source_service="gmail"
   - "Find that Obsidian note about Y" → search_docs with source_service="obsidian"
   - "What are my work patterns?" → search_profile_facts with dimension="work_patterns"
   - "What did the briefing say?" → briefing tool
   - "What technology should I evaluate?" → scout_report tool
   - General knowledge questions → search_docs without filters

2. For broad questions, search multiple sources. Start with the most likely source,
   then broaden if results are sparse.

3. Cite evidence: include source file paths, confidence scores, and relevance scores.

4. Begin with a content heading (#). No narration of your process.

5. When results are sparse, say so rather than speculating.

## Diagram generation
When your answer involves relationships, knowledge maps, or information flows,
include Mermaid diagrams:

    ```mermaid
    graph LR
      A[Obsidian Vault] --> B[documents collection]
      C[Google Drive] --> B
      D[Gmail] --> B
    ```

Keep diagrams focused — max 15-20 nodes.
"""


@dataclass
class KnowledgeDeps:
    """Runtime dependencies for the knowledge & context agent."""

    profiles_dir: Path


def create_agent() -> Agent:
    """Create the knowledge & context query agent."""
    agent = Agent(
        get_model("balanced"),
        system_prompt=build_system_prompt(),
        deps_type=KnowledgeDeps,
        model_settings={"max_tokens": 8192},
    )

    @agent.tool
    async def search_docs(
        ctx,
        query: str,
        source_service: str = "",
        content_type: str = "",
        days_back: int = 0,
        limit: int = 10,
    ) -> str:
        """Search the documents collection via semantic similarity.

        Args:
            query: Natural language search query.
            source_service: Filter by source (gdrive, gmail, obsidian, chrome, youtube,
                gcalendar, claude-code, ambient-audio, takeout, proton). Empty = all.
            content_type: Filter by type (document, email_metadata, etc.). Empty = all.
            days_back: Restrict to documents ingested in the last N days. 0 = all time.
            limit: Maximum results (default 10).
        """
        from shared.knowledge_search import search_documents
        return search_documents(
            query,
            source_service=source_service or None,
            content_type=content_type or None,
            days_back=days_back or None,
            limit=limit,
        )

    @agent.tool
    async def search_profile_facts(
        ctx, query: str, dimension: str = "", limit: int = 5
    ) -> str:
        """Search operator profile facts via semantic similarity.

        Args:
            query: Natural language search query.
            dimension: Filter by dimension (identity, neurocognitive, values,
                communication_style, relationships, work_patterns, energy_and_attention,
                information_seeking, creative_process, tool_usage, communication_patterns).
                Empty = all dimensions.
            limit: Maximum results (default 5).
        """
        from shared.knowledge_search import search_profile
        return search_profile(query, dimension=dimension or None, limit=limit)

    @agent.tool
    async def search_conv_memory(ctx, query: str, limit: int = 5) -> str:
        """Search persistent conversation memory from Claude Code sessions.

        Args:
            query: Natural language search query.
            limit: Maximum results (default 5).
        """
        from shared.knowledge_search import search_memory
        return search_memory(query, limit=limit)

    @agent.tool
    async def briefing(ctx) -> str:
        """Read the latest daily briefing (headline, action items, stats)."""
        from shared.knowledge_search import read_briefing
        return read_briefing(ctx.deps.profiles_dir)

    @agent.tool
    async def digest(ctx) -> str:
        """Read the latest knowledge digest (new documents, notable items)."""
        from shared.knowledge_search import read_digest
        return read_digest(ctx.deps.profiles_dir)

    @agent.tool
    async def scout_report(ctx) -> str:
        """Read the latest scout report (technology recommendations, horizon scan)."""
        from shared.knowledge_search import read_scout_report
        return read_scout_report(ctx.deps.profiles_dir)

    @agent.tool
    async def operator_goals(ctx) -> str:
        """Read the operator's active goals (primary and secondary)."""
        from shared.knowledge_search import get_operator_goals
        return get_operator_goals(ctx.deps.profiles_dir)

    @agent.tool
    async def collection_stats(ctx) -> str:
        """Get point counts for all Qdrant collections."""
        from shared.knowledge_search import get_collection_stats
        return get_collection_stats()

    return agent
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_knowledge_query.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add agents/knowledge/__init__.py agents/knowledge/query.py tests/test_knowledge_query.py
git commit -m "feat: add knowledge and context query agent"
```

---

### Task 7: Register knowledge in query_dispatch.py

**Files:**
- Modify: `cockpit/query_dispatch.py`
- Modify: `tests/test_query_dispatch.py`

- [ ] **Step 1: Write failing tests for knowledge agent**

Add to `tests/test_query_dispatch.py`:

```python
class TestClassifyQueryKnowledge:
    def test_document_search_routes_to_knowledge(self):
        result = classify_query("search for that document about API design")
        assert result == "knowledge"

    def test_briefing_routes_to_knowledge(self):
        result = classify_query("what did the briefing say today?")
        assert result == "knowledge"

    def test_email_routes_to_knowledge(self):
        result = classify_query("find emails from last week about the project")
        assert result == "knowledge"

    def test_obsidian_routes_to_knowledge(self):
        result = classify_query("search my obsidian notes for meeting prep")
        assert result == "knowledge"

    def test_goal_routes_to_knowledge(self):
        result = classify_query("what are my current goals?")
        assert result == "knowledge"


class TestGetAgentListAll:
    def test_includes_all_three_agents(self):
        agents = get_agent_list()
        types = {a.agent_type for a in agents}
        assert types == {"dev_story", "system_ops", "knowledge"}
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `uv run pytest tests/test_query_dispatch.py::TestClassifyQueryKnowledge -v`
Expected: FAIL (knowledge not registered)

- [ ] **Step 3: Update cockpit/query_dispatch.py**

Add to `_AGENTS` dict:

```python
    "knowledge": {
        "name": "Knowledge & Context",
        "description": "Search documents, profile facts, briefings, digests, and operator context",
        "keywords": [
            "document", "search", "find", "briefing", "digest", "scout",
            "goal", "profile", "memory", "knowledge", "obsidian", "drive",
            "email", "gmail", "youtube", "chrome", "calendar", "note",
            "vault", "rag", "context", "recommendation", "fact",
        ],
    },
```

Add factory function:

```python
def _create_knowledge_agent():
    """Create the knowledge & context query agent and its deps."""
    from agents.knowledge.query import KnowledgeDeps, create_agent as create_knowledge_agent

    agent = create_knowledge_agent()
    deps = KnowledgeDeps(profiles_dir=PROFILES_DIR)
    return agent, deps
```

Add to `_AGENT_FACTORY_NAMES`:

```python
_AGENT_FACTORY_NAMES: dict[str, str] = {
    "dev_story": "_create_dev_story_agent",
    "system_ops": "_create_system_ops_agent",
    "knowledge": "_create_knowledge_agent",
}
```

- [ ] **Step 4: Run all dispatch tests**

Run: `uv run pytest tests/test_query_dispatch.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add cockpit/query_dispatch.py tests/test_query_dispatch.py
git commit -m "feat: register knowledge agent in query dispatch"
```

---

## Chunk 4: Integration Testing & Smoke Test

### Task 8: Full Test Suite + Regression Check

**Files:**
- No new files

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass (existing + new). Two known pre-existing failures are acceptable: `test_no_path_home_in_shared`, `test_no_path_home_in_agents`.

- [ ] **Step 2: Verify imports from shared modules work**

Run: `uv run python -c "from shared.ops_db import build_ops_db; from shared.ops_live import get_infra_snapshot; from shared.knowledge_search import search_documents; print('All imports OK')"`
Expected: "All imports OK"

- [ ] **Step 3: Verify agent creation works**

Run: `uv run python -c "from agents.system_ops.query import create_agent; a = create_agent(); print(f'system_ops: {len(a._function_tools)} tools')" && uv run python -c "from agents.knowledge.query import create_agent; a = create_agent(); print(f'knowledge: {len(a._function_tools)} tools')"`
Expected: `system_ops: 6 tools` and `knowledge: 8 tools`

- [ ] **Step 4: Verify query dispatch lists all 3 agents**

Run: `uv run python -c "from cockpit.query_dispatch import get_agent_list; agents = get_agent_list(); print([(a.agent_type, a.name) for a in agents])"`
Expected: List containing all three agent types: dev_story, system_ops, knowledge

- [ ] **Step 5: Verify classification routes correctly**

Run: `uv run python -c "from cockpit.query_dispatch import classify_query; tests = [('show commit history', 'dev_story'), ('system health status', 'system_ops'), ('search my documents', 'knowledge')]; [print(f'{q!r} -> {classify_query(q)} (expected {e})') for q, e in tests]"`
Expected: All three queries route to the correct agent

- [ ] **Step 6: Commit any fixes if needed, then tag completion**

If all checks pass, no commit needed. If fixes were required, commit them.

---

### Task 9: Smoke Test Against Live System (host, not container)

**Files:**
- No new files

This task requires Langfuse and Qdrant to be running. Run on host with `eval "$(<.envrc)"` loaded.

- [ ] **Step 1: Test system_ops agent end-to-end**

Run (on host with .envrc loaded):
```bash
cd ~/projects/hapax-council && eval "$(<.envrc)"
uv run python -c "
import asyncio
from cockpit.query_dispatch import run_query

async def main():
    result = await run_query('system_ops', 'What is the current system health status? Show uptime for the last 24 hours.')
    print(f'Agent: {result.agent_type}')
    print(f'Tokens: {result.tokens_in} in / {result.tokens_out} out')
    print(f'Time: {result.elapsed_ms}ms')
    print(f'---')
    print(result.markdown[:500])

asyncio.run(main())
"
```
Expected: Markdown response with health data, no errors

- [ ] **Step 2: Test knowledge agent end-to-end**

Run (on host with .envrc loaded):
```bash
uv run python -c "
import asyncio
from cockpit.query_dispatch import run_query

async def main():
    result = await run_query('knowledge', 'What are my current active goals?')
    print(f'Agent: {result.agent_type}')
    print(f'Tokens: {result.tokens_in} in / {result.tokens_out} out')
    print(f'Time: {result.elapsed_ms}ms')
    print(f'---')
    print(result.markdown[:500])

asyncio.run(main())
"
```
Expected: Markdown response with goal data, no errors

- [ ] **Step 3: Test SSE streaming via curl**

Run (with cockpit-api running on host or container):
```bash
curl -N -X POST http://localhost:8051/api/query/run \
  -H 'Content-Type: application/json' \
  -d '{"query": "what docker containers are currently running?"}' \
  2>/dev/null | head -20
```
Expected: SSE events with `event: status`, `event: text_delta`, `event: done`

- [ ] **Step 4: Rebuild and test container**

```bash
cd ~/projects/hapax-council && eval "$(<.envrc)"
docker compose build cockpit-api
docker compose up -d cockpit-api
sleep 5
curl -s http://localhost:8051/api/query/agents | python3 -m json.tool
```
Expected: JSON array with 3 agents listed

- [ ] **Step 5: Commit and merge**

```bash
git add -A
git status  # Verify only expected files
git commit -m "feat: add system operations and knowledge query agents

Two new query agents registered in cockpit dispatch:
- system_ops: hybrid SQLite + live HTTP for infrastructure health,
  drift, costs, and operational analytics
- knowledge: Qdrant semantic search + artifact reads for documents,
  profile facts, briefings, digests, and goals

Shared data-access modules (shared/ops_db.py, shared/ops_live.py,
shared/knowledge_search.py) are reusable by voice daemon and
future consumers."
```

Then merge to main if on feature branch, or confirm with user.

---

## Future Integration Notes

**Voice daemon convergence:** The shared modules (`shared/ops_live.py`, `shared/knowledge_search.py`) are designed for direct use by voice tools. When ready, the voice daemon's `search_documents`, `search_emails`, and `system_status` tools can be replaced with calls to these shared functions. The voice tools become thin wrappers: call the shared function, truncate for TTS length, return.

**Demo pipeline integration:** The demo pipeline's `gather_research()` currently makes 20+ hardcoded source fetches. These can be replaced with query agent calls: `run_query("system_ops", "infrastructure overview")` and `run_query("knowledge", "recent project activity")`.
