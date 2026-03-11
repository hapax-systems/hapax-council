"""Tests for the dev-story query agent."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from agents.dev_story.query import (
    _sql_query,
    _session_content,
    _file_history,
    build_system_prompt,
)
from agents.dev_story.schema import create_tables


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _seed_basic_data(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', '/home/user/projects/foo', 'foo', '2026-03-01T10:00:00Z', '2026-03-01T11:00:00Z', 'main', 5, 500, 200, 0.01, 'claude-sonnet')"
    )
    conn.execute(
        "INSERT INTO messages VALUES ('m1', 's1', NULL, 'user', '2026-03-01T10:00:00Z', 'build a widget', NULL, 0, 0)"
    )
    conn.execute(
        "INSERT INTO messages VALUES ('m2', 's1', 'm1', 'assistant', '2026-03-01T10:00:05Z', 'I will build the widget.', 'claude-sonnet', 500, 200)"
    )
    conn.commit()


def test_sql_query_select():
    conn = _make_db()
    _seed_basic_data(conn)
    result = _sql_query(conn, "SELECT id, project_name FROM sessions")
    assert "s1" in result
    assert "foo" in result


def test_sql_query_rejects_write():
    conn = _make_db()
    result = _sql_query(conn, "DROP TABLE sessions")
    assert "error" in result.lower() or "not allowed" in result.lower()


def test_sql_query_rejects_insert():
    conn = _make_db()
    result = _sql_query(conn, "INSERT INTO sessions VALUES ('x','x','x','x','x','x',0,0,0,0,'x')")
    assert "error" in result.lower() or "not allowed" in result.lower()


def test_session_content_returns_messages():
    conn = _make_db()
    _seed_basic_data(conn)
    result = _session_content(conn, "s1")
    assert "build a widget" in result
    assert "I will build the widget" in result


def test_session_content_missing_session():
    conn = _make_db()
    result = _session_content(conn, "nonexistent")
    assert "not found" in result.lower() or result == ""


def test_file_history():
    conn = _make_db()
    _seed_basic_data(conn)
    conn.execute("INSERT INTO commits VALUES ('c1', '2026-03-01 10:05:00 -0500', 'feat: widget', 'main', 1, 50, 0)")
    conn.execute("INSERT INTO commit_files VALUES ('c1', 'widget.py', 'A')")
    conn.execute("INSERT INTO correlations VALUES (1, 'm2', 'c1', 0.9, 'file_and_timestamp')")
    conn.commit()

    result = _file_history(conn, "widget.py")
    assert "c1" in result or "widget" in result


def test_build_system_prompt_contains_schema():
    prompt = build_system_prompt()
    assert "sessions" in prompt
    assert "correlations" in prompt
    assert "tool_calls" in prompt


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
