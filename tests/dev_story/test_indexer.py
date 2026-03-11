"""Tests for the index orchestrator."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from agents.dev_story.indexer import (
    discover_sessions,
    index_session,
    index_git,
    run_correlations,
    full_index,
    SessionFile,
)
from agents.dev_story.schema import create_tables


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    return conn


def _make_session_dir(base: Path, project_encoded: str, sessions: dict[str, list[dict]]) -> Path:
    """Create a mock Claude session directory structure."""
    project_dir = base / project_encoded
    project_dir.mkdir(parents=True, exist_ok=True)
    for session_id, lines in sessions.items():
        path = project_dir / f"{session_id}.jsonl"
        with open(path, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")
    return project_dir


def test_discover_sessions_finds_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "projects"
        _make_session_dir(base, "-home-user-projects-foo", {
            "sess-1": [{"type": "user", "uuid": "u1", "sessionId": "sess-1",
                        "timestamp": "2026-03-10T10:00:00Z",
                        "message": {"role": "user", "content": "hi"}}],
        })
        results = discover_sessions(base)
        assert len(results) == 1
        assert results[0].session_id == "sess-1"
        assert results[0].project_path == "/home/user/projects/foo"


def test_discover_sessions_skips_non_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "projects"
        project_dir = base / "-home-user-projects-foo"
        project_dir.mkdir(parents=True)
        (project_dir / "notes.txt").write_text("not a session")
        results = discover_sessions(base)
        assert len(results) == 0


def test_index_session_inserts_into_db():
    conn = _make_db()
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        lines = [
            {"type": "user", "uuid": "u1", "sessionId": "sess-1",
             "timestamp": "2026-03-10T10:00:00Z",
             "message": {"role": "user", "content": "hello"}},
            {"type": "assistant", "uuid": "a1", "sessionId": "sess-1",
             "timestamp": "2026-03-10T10:00:05Z",
             "message": {"role": "assistant", "content": [
                 {"type": "text", "text": "hi there"},
                 {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/x"}},
             ], "usage": {"input_tokens": 10, "output_tokens": 5}}},
        ]
        for line in lines:
            f.write(json.dumps(line) + "\n")
        f.flush()
        sf = SessionFile(path=Path(f.name), session_id="sess-1",
                         project_path="/tmp/test", project_encoded="test")
        index_session(conn, sf)

    # Check session row
    cursor = conn.execute("SELECT id, message_count FROM sessions")
    row = cursor.fetchone()
    assert row[0] == "sess-1"
    assert row[1] == 2

    # Check messages
    cursor = conn.execute("SELECT COUNT(*) FROM messages")
    assert cursor.fetchone()[0] == 2

    # Check tool calls
    cursor = conn.execute("SELECT tool_name FROM tool_calls")
    assert cursor.fetchone()[0] == "Read"


@patch("agents.dev_story.indexer.extract_commits")
def test_index_git_inserts_commits(mock_extract):
    conn = _make_db()
    mock_extract.return_value = (
        [MagicMock(hash="abc", author_date="2026-03-10 10:00:00 -0500",
                   message="feat: test", branch=None, files_changed=1,
                   insertions=5, deletions=0)],
        [MagicMock(commit_hash="abc", file_path="foo.py", operation="A")],
    )
    index_git(conn, "/tmp/repo")

    cursor = conn.execute("SELECT hash, message FROM commits")
    row = cursor.fetchone()
    assert row[0] == "abc"
    assert row[1] == "feat: test"

    cursor = conn.execute("SELECT file_path FROM commit_files")
    assert cursor.fetchone()[0] == "foo.py"
