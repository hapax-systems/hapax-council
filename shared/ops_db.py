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


def _load_json(path: Path) -> dict | None:
    """Load a JSON file, returning None if missing or invalid."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        log.debug("Failed to load %s", path.name)
        return None


def _load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file, skipping malformed lines.

    Handles both true JSONL (one JSON object per line) and files with
    pretty-printed multi-line JSON objects concatenated together.
    """
    if not path.is_file():
        return []

    text = path.read_text().strip()
    if not text:
        return []

    entries = []

    # Try line-by-line first (true JSONL)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                entries.append(obj)
        except json.JSONDecodeError:
            continue

    if entries:
        return entries

    # Fallback: try parsing as a single JSON array or concatenated objects
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [e for e in parsed if isinstance(e, dict)]
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    # Last resort: try splitting on "}\n{" for concatenated pretty-printed JSON
    try:
        # Wrap in array brackets and add commas between objects
        wrapped = "[" + text.replace("}\n{", "},\n{") + "]"
        parsed = json.loads(wrapped)
        return [e for e in parsed if isinstance(e, dict)]
    except json.JSONDecodeError:
        log.debug("Could not parse %s as JSONL or concatenated JSON", path.name)
        return []


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


def build_ops_db(profiles_dir: Path) -> sqlite3.Connection:
    """Build an in-memory SQLite database from operational data files."""
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
    """Execute a read-only SQL query and return formatted results."""
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
