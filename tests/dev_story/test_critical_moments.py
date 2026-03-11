"""Tests for critical moment detection."""
from __future__ import annotations

import sqlite3

from agents.dev_story.critical_moments import (
    detect_churn_moments,
    detect_high_token_sessions,
    detect_wrong_path_moments,
)
from agents.dev_story.schema import create_tables


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _seed_churn_data(conn: sqlite3.Connection) -> None:
    """Seed DB with a file that was introduced then rewritten 4 times quickly."""
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', '/tmp', 'test', '2026-03-01T10:00:00Z', '2026-03-01T11:00:00Z', 'main', 10, 0, 0, 0, NULL)"
    )
    conn.execute(
        "INSERT INTO messages VALUES ('m1', 's1', NULL, 'assistant', '2026-03-01T10:30:00Z', 'wrote code', NULL, 0, 0)"
    )
    # 5 commits touching widget.py — enough to trigger the >= 3 rewrite threshold
    for i in range(5):
        hash_val = f"c{i}"
        date = f"2026-03-0{i+1} 10:00:00 -0500"
        msg = "feat: add widget" if i == 0 else f"fix: rewrite widget v{i}"
        dels = 0 if i == 0 else 30
        conn.execute(
            "INSERT INTO commits VALUES (?, ?, ?, 'main', 1, 50, ?)",
            (hash_val, date, msg, dels),
        )
        op = "A" if i == 0 else "M"
        conn.execute("INSERT INTO commit_files VALUES (?, 'widget.py', ?)", (hash_val, op))
    conn.execute("INSERT INTO correlations VALUES (1, 'm1', 'c0', 0.9, 'file_and_timestamp')")
    conn.commit()


def test_detect_churn_moments_finds_quick_rewrite():
    conn = _make_db()
    _seed_churn_data(conn)
    moments = detect_churn_moments(conn, max_survived_days=7)
    assert len(moments) >= 1
    assert moments[0].moment_type == "churn"
    assert "widget.py" in moments[0].description
    # Should report the rewrite count
    assert "rewrite" in moments[0].description.lower()


def test_detect_churn_severity_scales_with_count():
    conn = _make_db()
    _seed_churn_data(conn)
    moments = detect_churn_moments(conn, max_survived_days=7)
    assert len(moments) >= 1
    # 4 rewrites (commits c1-c4 rewrite c0's file) → severity ~0.24
    assert moments[0].severity > 0.1
    assert moments[0].severity < 0.95


def test_detect_churn_moments_empty_db():
    conn = _make_db()
    moments = detect_churn_moments(conn, max_survived_days=7)
    assert moments == []


def _seed_wrong_path_data(conn: sqlite3.Connection) -> None:
    """Seed DB with Edit→Bash debugging cycles on the same file."""
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', '/tmp', 'test', '2026-03-01T10:00:00Z', '2026-03-01T11:00:00Z', 'main', 20, 0, 0, 0, NULL)"
    )
    # 4 Edit→Bash cycles on the same file
    for i in range(8):
        msg_id = f"m{i}"
        conn.execute(
            "INSERT INTO messages VALUES (?, 's1', NULL, 'assistant', ?, 'trying again', NULL, 0, 0)",
            (msg_id, f"2026-03-01T10:{i:02d}:00Z"),
        )
        tool = "Edit" if i % 2 == 0 else "Bash"
        arg = "agents/foo.py" if tool == "Edit" else "pytest tests/test_foo.py"
        conn.execute(
            "INSERT INTO tool_calls VALUES (NULL, ?, ?, ?, NULL, 1, 0)",
            (msg_id, tool, arg),
        )
    conn.commit()


def test_detect_wrong_path_edit_bash_cycles():
    conn = _make_db()
    _seed_wrong_path_data(conn)
    moments = detect_wrong_path_moments(conn)
    assert len(moments) >= 1
    assert moments[0].moment_type == "wrong_path"
    assert "Edit-test loop" in moments[0].description


def test_detect_wrong_path_empty_db():
    conn = _make_db()
    moments = detect_wrong_path_moments(conn)
    assert moments == []


def _seed_token_waste_data(conn: sqlite3.Connection) -> None:
    """Seed DB with a high-token session that produced no commits."""
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', '/tmp', 'test', '2026-03-01T10:00:00Z', '2026-03-01T14:00:00Z', 'main', 500, 200000, 100000, 0, 'claude-sonnet')"
    )
    conn.execute(
        "INSERT INTO messages VALUES ('m1', 's1', NULL, 'user', '2026-03-01T10:00:00Z', 'hello', NULL, 0, 0)"
    )
    conn.commit()


def test_detect_high_token_sessions():
    conn = _make_db()
    _seed_token_waste_data(conn)
    moments = detect_high_token_sessions(conn)
    assert len(moments) >= 1
    assert moments[0].moment_type == "token_waste"
    assert "300,000" in moments[0].description


def test_detect_high_token_sessions_empty_db():
    conn = _make_db()
    moments = detect_high_token_sessions(conn)
    assert moments == []
