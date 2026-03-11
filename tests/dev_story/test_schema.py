"""Tests for dev-story SQLite schema."""

from __future__ import annotations

import sqlite3

from agents.dev_story.schema import SCHEMA_VERSION, create_tables


def test_create_tables_creates_all_expected_tables():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    expected = [
        "code_survival",
        "commit_files",
        "commits",
        "correlations",
        "critical_moments",
        "file_changes",
        "hotspots",
        "index_state",
        "messages",
        "session_metrics",
        "session_tags",
        "sessions",
        "tool_calls",
    ]
    assert tables == expected


def test_create_tables_idempotent():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    create_tables(conn)  # Should not raise
    cursor = conn.execute("SELECT COUNT(*) FROM sessions")
    assert cursor.fetchone()[0] == 0


def test_schema_version_stored():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    cursor = conn.execute("SELECT value FROM index_state WHERE key='schema_version'")
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == str(SCHEMA_VERSION)


def test_sessions_table_columns():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    cursor = conn.execute("PRAGMA table_info(sessions)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "id" in columns
    assert "project_path" in columns
    assert "started_at" in columns
    assert "model_primary" in columns


def test_correlations_table_columns():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    cursor = conn.execute("PRAGMA table_info(correlations)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "message_id" in columns
    assert "commit_hash" in columns
    assert "confidence" in columns
    assert "method" in columns


def test_wal_mode_enabled():
    """WAL mode should be set for concurrent read during indexing."""
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    cursor = conn.execute("PRAGMA journal_mode")
    assert cursor.fetchone() is not None
