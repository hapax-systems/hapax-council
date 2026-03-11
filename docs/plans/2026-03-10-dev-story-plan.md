# Dev Story Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a development archaeology agent that correlates Claude Code conversation logs with git history to answer analytical questions about development patterns, efficiency, and critical moments.

**Architecture:** Offline SQLite indexer parses session transcripts + git history into a normalized database with message-level correlation. Pydantic-ai query agent translates natural language into SQL + content retrieval, returning narrative answers with evidence. Multi-file agent module at `agents/dev_story/`.

**Tech Stack:** Python 3.12+, sqlite3 (stdlib), pydantic-ai via shared.config.get_model(), subprocess for git, streaming JSONL parsing.

**Spec:** `docs/plans/2026-03-10-dev-story-design.md`

---

## File Structure

```
agents/dev_story/
  __init__.py          # Docstring only
  __main__.py          # CLI entry point: argparse, dispatches to index/query
  models.py            # Pydantic models for all data structures
  schema.py            # SQLite schema DDL + create_tables() + migrations
  parser.py            # Streaming JSONL session transcript parser
  git_extractor.py     # Git log/diff/blame extraction via subprocess
  correlator.py        # File + timestamp correlation engine
  indexer.py           # Orchestrates full index pipeline
  phase_detector.py    # Tool sequence → phase classification
  classifier.py        # Session dimension tagging
  critical_moments.py  # Churn, wrong-path, cascade detection
  survival.py          # Code survival computation
  query.py             # Pydantic-ai query agent with SQL + content tools

tests/dev_story/
  __init__.py
  test_models.py
  test_schema.py
  test_parser.py
  test_git_extractor.py
  test_correlator.py
  test_indexer.py
  test_phase_detector.py
  test_classifier.py
  test_critical_moments.py
  test_survival.py
  test_query.py
```

---

## Chunk 1: Foundation (Models, Schema, Parser)

### Task 1: Pydantic Models

**Files:**
- Create: `agents/dev_story/__init__.py`
- Create: `agents/dev_story/models.py`
- Test: `tests/dev_story/__init__.py`
- Test: `tests/dev_story/test_models.py`

- [ ] **Step 1: Create module init**

```python
# agents/dev_story/__init__.py
"""Dev Story — development archaeology agent."""
```

```python
# tests/dev_story/__init__.py
```

- [ ] **Step 2: Write failing tests for models**

```python
# tests/dev_story/test_models.py
"""Tests for dev_story data models."""
from __future__ import annotations

from agents.dev_story.models import (
    Session,
    Message,
    ToolCall,
    FileChange,
    Commit,
    CommitFile,
    Correlation,
    SessionMetrics,
    SessionTag,
    CriticalMoment,
    HotspotEntry,
    CodeSurvivalEntry,
)


def test_session_defaults():
    s = Session(
        id="abc-123",
        project_path="/home/user/projects/foo",
        project_name="foo",
        started_at="2026-03-10T10:00:00Z",
    )
    assert s.git_branch is None
    assert s.message_count == 0
    assert s.total_tokens_in == 0
    assert s.total_tokens_out == 0
    assert s.total_cost_estimate == 0.0
    assert s.model_primary is None
    assert s.ended_at is None


def test_message_fields():
    m = Message(
        id="msg-1",
        session_id="abc-123",
        role="assistant",
        timestamp="2026-03-10T10:00:01Z",
        content_text="Hello",
    )
    assert m.parent_id is None
    assert m.model is None
    assert m.tokens_in == 0
    assert m.tokens_out == 0


def test_tool_call_fields():
    tc = ToolCall(
        message_id="msg-1",
        tool_name="Edit",
        sequence_position=0,
    )
    assert tc.arguments_summary is None
    assert tc.duration_ms is None
    assert tc.success is True


def test_file_change_fields():
    fc = FileChange(
        message_id="msg-1",
        file_path="shared/config.py",
        version=2,
        change_type="modified",
        timestamp="2026-03-10T10:00:02Z",
    )
    assert fc.file_path == "shared/config.py"


def test_commit_fields():
    c = Commit(
        hash="abc123def",
        author_date="2026-03-10 10:05:00 -0500",
        message="feat: add something",
    )
    assert c.branch is None
    assert c.files_changed == 0
    assert c.insertions == 0
    assert c.deletions == 0


def test_commit_file_fields():
    cf = CommitFile(
        commit_hash="abc123def",
        file_path="shared/config.py",
        operation="M",
    )
    assert cf.operation == "M"


def test_correlation_confidence_range():
    c = Correlation(
        message_id="msg-1",
        commit_hash="abc123def",
        confidence=0.85,
        method="file_and_timestamp",
    )
    assert 0.0 <= c.confidence <= 1.0


def test_session_metrics_defaults():
    sm = SessionMetrics(session_id="abc-123")
    assert sm.tool_call_count == 0
    assert sm.tool_diversity == 0
    assert sm.edit_count == 0
    assert sm.bash_count == 0
    assert sm.agent_dispatch_count == 0
    assert sm.user_steering_ratio == 0.0
    assert sm.phase_sequence is None


def test_session_tag():
    t = SessionTag(
        session_id="abc-123",
        dimension="work_type",
        value="feature",
        confidence=0.9,
    )
    assert t.dimension == "work_type"


def test_critical_moment():
    cm = CriticalMoment(
        moment_type="churn",
        severity=0.8,
        session_id="abc-123",
        description="Code rewritten within 2 days",
    )
    assert cm.message_id is None
    assert cm.commit_hash is None
    assert cm.evidence is None


def test_hotspot_entry():
    h = HotspotEntry(
        file_path="shared/config.py",
        change_frequency=31,
        session_count=12,
        churn_rate=0.15,
    )
    assert h.change_frequency == 31


def test_code_survival_entry():
    cs = CodeSurvivalEntry(
        file_path="shared/config.py",
        introduced_by_commit="abc123",
        survived_days=5.5,
    )
    assert cs.introduced_by_session is None
    assert cs.replacement_commit is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/dev_story/test_models.py -v`
Expected: ImportError — models module doesn't exist yet

- [ ] **Step 4: Implement models**

```python
# agents/dev_story/models.py
"""Pydantic models for the dev-story data layer."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Session(BaseModel):
    id: str
    project_path: str
    project_name: str
    started_at: str
    ended_at: str | None = None
    git_branch: str | None = None
    message_count: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_estimate: float = 0.0
    model_primary: str | None = None


class Message(BaseModel):
    id: str
    session_id: str
    role: str  # user | assistant
    timestamp: str
    content_text: str
    parent_id: str | None = None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0


class ToolCall(BaseModel):
    message_id: str
    tool_name: str
    sequence_position: int
    arguments_summary: str | None = None
    duration_ms: int | None = None
    success: bool = True


class FileChange(BaseModel):
    message_id: str
    file_path: str
    version: int
    change_type: str  # created | modified | deleted
    timestamp: str


class Commit(BaseModel):
    hash: str
    author_date: str
    message: str
    branch: str | None = None
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


class CommitFile(BaseModel):
    commit_hash: str
    file_path: str
    operation: str  # A | M | D


class Correlation(BaseModel):
    message_id: str
    commit_hash: str
    confidence: float = Field(ge=0.0, le=1.0)
    method: str  # timestamp_window | file_match | file_and_timestamp | content_match


class SessionMetrics(BaseModel):
    session_id: str
    tool_call_count: int = 0
    tool_diversity: int = 0
    edit_count: int = 0
    bash_count: int = 0
    agent_dispatch_count: int = 0
    avg_response_time_ms: float = 0.0
    user_steering_ratio: float = 0.0
    phase_sequence: str | None = None


class SessionTag(BaseModel):
    session_id: str
    dimension: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)


class CriticalMoment(BaseModel):
    moment_type: str  # churn | wrong_path | cascade | efficient | unblocking
    severity: float = Field(ge=0.0, le=1.0)
    session_id: str
    description: str
    message_id: str | None = None
    commit_hash: str | None = None
    evidence: str | None = None  # JSON string


class HotspotEntry(BaseModel):
    file_path: str
    change_frequency: int
    session_count: int
    churn_rate: float


class CodeSurvivalEntry(BaseModel):
    file_path: str
    introduced_by_commit: str
    survived_days: float
    introduced_by_session: str | None = None
    replacement_commit: str | None = None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/dev_story/test_models.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add agents/dev_story/__init__.py agents/dev_story/models.py tests/dev_story/__init__.py tests/dev_story/test_models.py
git commit -m "feat(dev-story): add pydantic data models"
```

---

### Task 2: SQLite Schema

**Files:**
- Create: `agents/dev_story/schema.py`
- Test: `tests/dev_story/test_schema.py`

- [ ] **Step 1: Write failing tests for schema**

```python
# tests/dev_story/test_schema.py
"""Tests for dev-story SQLite schema."""
from __future__ import annotations

import sqlite3

from agents.dev_story.schema import create_tables, SCHEMA_VERSION


def test_create_tables_creates_all_expected_tables():
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
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
    # WAL only works on file-based DBs, but pragma should not fail on :memory:
    cursor = conn.execute("PRAGMA journal_mode")
    # :memory: uses "memory" journal mode, not WAL — just verify no error
    assert cursor.fetchone() is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dev_story/test_schema.py -v`
Expected: ImportError

- [ ] **Step 3: Implement schema**

```python
# agents/dev_story/schema.py
"""SQLite schema definition for the dev-story database."""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    project_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    git_branch TEXT,
    message_count INTEGER DEFAULT 0,
    total_tokens_in INTEGER DEFAULT 0,
    total_tokens_out INTEGER DEFAULT 0,
    total_cost_estimate REAL DEFAULT 0.0,
    model_primary TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    parent_id TEXT,
    role TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    content_text TEXT NOT NULL,
    model TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL REFERENCES messages(id),
    tool_name TEXT NOT NULL,
    arguments_summary TEXT,
    duration_ms INTEGER,
    success INTEGER DEFAULT 1,
    sequence_position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS file_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL REFERENCES messages(id),
    file_path TEXT NOT NULL,
    version INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commits (
    hash TEXT PRIMARY KEY,
    author_date TEXT NOT NULL,
    message TEXT NOT NULL,
    branch TEXT,
    files_changed INTEGER DEFAULT 0,
    insertions INTEGER DEFAULT 0,
    deletions INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS commit_files (
    commit_hash TEXT NOT NULL REFERENCES commits(hash),
    file_path TEXT NOT NULL,
    operation TEXT NOT NULL,
    PRIMARY KEY (commit_hash, file_path)
);

CREATE TABLE IF NOT EXISTS correlations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL REFERENCES messages(id),
    commit_hash TEXT NOT NULL REFERENCES commits(hash),
    confidence REAL NOT NULL,
    method TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_metrics (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id),
    tool_call_count INTEGER DEFAULT 0,
    tool_diversity INTEGER DEFAULT 0,
    edit_count INTEGER DEFAULT 0,
    bash_count INTEGER DEFAULT 0,
    agent_dispatch_count INTEGER DEFAULT 0,
    avg_response_time_ms REAL DEFAULT 0.0,
    user_steering_ratio REAL DEFAULT 0.0,
    phase_sequence TEXT
);

CREATE TABLE IF NOT EXISTS session_tags (
    session_id TEXT NOT NULL REFERENCES sessions(id),
    dimension TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (session_id, dimension, value)
);

CREATE TABLE IF NOT EXISTS critical_moments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    moment_type TEXT NOT NULL,
    severity REAL NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    message_id TEXT REFERENCES messages(id),
    commit_hash TEXT REFERENCES commits(hash),
    description TEXT NOT NULL,
    evidence TEXT
);

CREATE TABLE IF NOT EXISTS hotspots (
    file_path TEXT PRIMARY KEY,
    change_frequency INTEGER NOT NULL,
    session_count INTEGER NOT NULL,
    churn_rate REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS code_survival (
    file_path TEXT NOT NULL,
    introduced_by_commit TEXT NOT NULL REFERENCES commits(hash),
    introduced_by_session TEXT REFERENCES sessions(id),
    survived_days REAL NOT NULL,
    replacement_commit TEXT REFERENCES commits(hash),
    PRIMARY KEY (file_path, introduced_by_commit)
);

CREATE TABLE IF NOT EXISTS index_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_tool_calls_message ON tool_calls(message_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_name ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_file_changes_message ON file_changes(message_id);
CREATE INDEX IF NOT EXISTS idx_file_changes_path ON file_changes(file_path);
CREATE INDEX IF NOT EXISTS idx_commit_files_path ON commit_files(file_path);
CREATE INDEX IF NOT EXISTS idx_correlations_message ON correlations(message_id);
CREATE INDEX IF NOT EXISTS idx_correlations_commit ON correlations(commit_hash);
CREATE INDEX IF NOT EXISTS idx_session_tags_dimension ON session_tags(dimension);
CREATE INDEX IF NOT EXISTS idx_critical_moments_type ON critical_moments(moment_type);
"""


def create_tables(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes. Idempotent."""
    conn.executescript(_DDL)
    conn.execute(
        "INSERT OR REPLACE INTO index_state (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def open_db(path: str) -> sqlite3.Connection:
    """Open or create the dev-story database with WAL mode."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/dev_story/test_schema.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/dev_story/schema.py tests/dev_story/test_schema.py
git commit -m "feat(dev-story): add SQLite schema with indexes and state tracking"
```

---

### Task 3: Session Transcript Parser

**Files:**
- Create: `agents/dev_story/parser.py`
- Test: `tests/dev_story/test_parser.py`

- [ ] **Step 1: Write failing tests for parser**

```python
# tests/dev_story/test_parser.py
"""Tests for JSONL session transcript parser."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agents.dev_story.parser import (
    parse_session,
    extract_project_path,
    ParsedSession,
)


def _write_jsonl(lines: list[dict], path: Path) -> None:
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def test_extract_project_path_from_encoded_dirname():
    assert extract_project_path("-home-user-projects-foo") == "/home/user/projects/foo"


def test_extract_project_path_preserves_simple():
    assert extract_project_path("-home-user-myproject") == "/home/user/myproject"


def test_parse_session_empty_file():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w") as f:
        f.write("")
        f.flush()
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert result.messages == []
    assert result.tool_calls == []
    assert result.file_changes == []


def test_parse_session_extracts_user_message():
    lines = [
        {
            "type": "user",
            "uuid": "u1",
            "parentUuid": None,
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:00:00.000Z",
            "message": {"role": "user", "content": "hello world"},
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert len(result.messages) == 1
    assert result.messages[0].role == "user"
    assert result.messages[0].content_text == "hello world"
    assert result.messages[0].id == "u1"


def test_parse_session_extracts_assistant_message_strips_tool_use():
    lines = [
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:00:01.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-5-20250514",
                "content": [
                    {"type": "text", "text": "Let me check that."},
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/foo.py"}},
                ],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert len(result.messages) == 1
    msg = result.messages[0]
    assert msg.content_text == "Let me check that."
    assert msg.model == "claude-sonnet-4-5-20250514"
    assert msg.tokens_in == 100
    assert msg.tokens_out == 50


def test_parse_session_extracts_tool_calls():
    lines = [
        {
            "type": "assistant",
            "uuid": "a1",
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:00:01.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/foo.py"}},
                    {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": "/tmp/foo.py", "old_string": "a", "new_string": "b"}},
                ],
            },
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0].tool_name == "Read"
    assert result.tool_calls[0].sequence_position == 0
    assert result.tool_calls[0].arguments_summary == "/tmp/foo.py"
    assert result.tool_calls[1].tool_name == "Edit"
    assert result.tool_calls[1].sequence_position == 1


def test_parse_session_extracts_file_history_snapshot():
    lines = [
        {
            "type": "file-history-snapshot",
            "messageId": "m1",
            "snapshot": {
                "trackedFileBackups": {
                    "shared/config.py": {
                        "backupFileName": "abc123@v2",
                        "version": 2,
                        "backupTime": "2026-03-10T10:00:02.000Z",
                    },
                    "agents/foo.py": {
                        "backupFileName": "def456@v1",
                        "version": 1,
                        "backupTime": "2026-03-10T10:00:01.000Z",
                    },
                },
                "timestamp": "2026-03-10T10:00:03.000Z",
            },
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert len(result.file_changes) == 2
    paths = {fc.file_path for fc in result.file_changes}
    assert "shared/config.py" in paths
    assert "agents/foo.py" in paths


def test_parse_session_computes_session_metadata():
    lines = [
        {
            "type": "user",
            "uuid": "u1",
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:00:00.000Z",
            "gitBranch": "main",
            "message": {"role": "user", "content": "start"},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:05:00.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-sonnet-4-5-20250514",
                "content": [{"type": "text", "text": "done"}],
                "usage": {"input_tokens": 200, "output_tokens": 100},
            },
        },
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert result.session.id == "sess-1"
    assert result.session.started_at == "2026-03-10T10:00:00.000Z"
    assert result.session.ended_at == "2026-03-10T10:05:00.000Z"
    assert result.session.message_count == 2
    assert result.session.git_branch == "main"
    assert result.session.total_tokens_in == 200
    assert result.session.total_tokens_out == 100


def test_parse_session_handles_malformed_lines():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        f.write("not valid json\n")
        f.write(json.dumps({"type": "user", "uuid": "u1", "sessionId": "s1",
                            "timestamp": "2026-03-10T10:00:00Z",
                            "message": {"role": "user", "content": "ok"}}) + "\n")
        f.flush()
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert len(result.messages) == 1


def test_parse_session_content_list_with_text_blocks():
    """User messages can have content as list of blocks."""
    lines = [
        {
            "type": "user",
            "uuid": "u1",
            "sessionId": "sess-1",
            "timestamp": "2026-03-10T10:00:00.000Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "part one "},
                    {"type": "text", "text": "part two"},
                ],
            },
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        _write_jsonl(lines, Path(f.name))
        result = parse_session(Path(f.name), project_path="/tmp/test")
    assert result.messages[0].content_text == "part one part two"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dev_story/test_parser.py -v`
Expected: ImportError

- [ ] **Step 3: Implement parser**

```python
# agents/dev_story/parser.py
"""Streaming JSONL parser for Claude Code session transcripts."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from agents.dev_story.models import (
    FileChange,
    Message,
    Session,
    ToolCall,
)

log = logging.getLogger(__name__)


@dataclass
class ParsedSession:
    """Result of parsing a single session JSONL file."""

    session: Session
    messages: list[Message] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    file_changes: list[FileChange] = field(default_factory=list)


def extract_project_path(encoded: str) -> str:
    """Decode Claude Code's project directory encoding.

    Claude encodes /home/user/projects/foo as -home-user-projects-foo.
    """
    return "/" + encoded.lstrip("-").replace("-", "/")


def _extract_content_text(content) -> str:
    """Extract plain text from message content (string or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


def _extract_tool_calls(message_id: str, content) -> list[ToolCall]:
    """Extract tool_use blocks from assistant message content."""
    if not isinstance(content, list):
        return []
    calls = []
    for i, block in enumerate(content):
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name", "unknown")
            inp = block.get("input", {})
            # Summarize arguments: file_path for file tools, command for Bash, pattern for Grep
            summary = inp.get("file_path") or inp.get("command") or inp.get("pattern")
            calls.append(
                ToolCall(
                    message_id=message_id,
                    tool_name=name,
                    arguments_summary=summary,
                    sequence_position=i,
                )
            )
    return calls


def _extract_file_changes(entry: dict) -> list[FileChange]:
    """Extract file changes from a file-history-snapshot entry."""
    snapshot = entry.get("snapshot", {})
    message_id = entry.get("messageId", "")
    backups = snapshot.get("trackedFileBackups", {})
    changes = []
    for file_path, info in backups.items():
        version = info.get("version", 0)
        backup_time = info.get("backupTime", snapshot.get("timestamp", ""))
        change_type = "created" if version <= 1 else "modified"
        changes.append(
            FileChange(
                message_id=message_id,
                file_path=file_path,
                version=version,
                change_type=change_type,
                timestamp=backup_time,
            )
        )
    return changes


def parse_session(path: Path, project_path: str) -> ParsedSession:
    """Parse a session JSONL file into structured data.

    Streams line-by-line to handle large files (some are 27MB+).
    """
    messages: list[Message] = []
    tool_calls: list[ToolCall] = []
    file_changes: list[FileChange] = []

    session_id: str | None = None
    git_branch: str | None = None
    first_ts: str | None = None
    last_ts: str | None = None
    total_tokens_in = 0
    total_tokens_out = 0
    model_counts: dict[str, int] = {}

    with open(path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                log.debug("Skipping malformed line %d in %s", line_num, path.name)
                continue

            entry_type = entry.get("type")
            ts = entry.get("timestamp")

            if ts:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts

            if session_id is None:
                session_id = entry.get("sessionId")
            if git_branch is None:
                git_branch = entry.get("gitBranch")

            if entry_type in ("user", "assistant"):
                msg_data = entry.get("message", {})
                uuid = entry.get("uuid", f"line-{line_num}")
                content = msg_data.get("content", "")
                content_text = _extract_content_text(content)

                usage = msg_data.get("usage", {})
                t_in = usage.get("input_tokens", 0) or 0
                t_out = usage.get("output_tokens", 0) or 0
                model = msg_data.get("model")

                if model:
                    model_counts[model] = model_counts.get(model, 0) + 1

                messages.append(
                    Message(
                        id=uuid,
                        session_id=session_id or path.stem,
                        parent_id=entry.get("parentUuid"),
                        role=msg_data.get("role", entry_type),
                        timestamp=ts or "",
                        content_text=content_text,
                        model=model,
                        tokens_in=t_in,
                        tokens_out=t_out,
                    )
                )

                total_tokens_in += t_in
                total_tokens_out += t_out

                # Extract tool calls from assistant messages
                if entry_type == "assistant":
                    tool_calls.extend(_extract_tool_calls(uuid, content))

            elif entry_type == "file-history-snapshot":
                file_changes.extend(_extract_file_changes(entry))

    # Determine primary model
    model_primary = None
    if model_counts:
        model_primary = max(model_counts, key=model_counts.get)

    project_name = Path(project_path).name if project_path else path.parent.name

    session = Session(
        id=session_id or path.stem,
        project_path=project_path,
        project_name=project_name,
        started_at=first_ts or "",
        ended_at=last_ts,
        git_branch=git_branch,
        message_count=len(messages),
        total_tokens_in=total_tokens_in,
        total_tokens_out=total_tokens_out,
        model_primary=model_primary,
    )

    return ParsedSession(
        session=session,
        messages=messages,
        tool_calls=tool_calls,
        file_changes=file_changes,
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/dev_story/test_parser.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/dev_story/parser.py tests/dev_story/test_parser.py
git commit -m "feat(dev-story): add streaming JSONL session transcript parser"
```

---

## Chunk 2: Git Extraction & Correlation

### Task 4: Git Extractor

**Files:**
- Create: `agents/dev_story/git_extractor.py`
- Test: `tests/dev_story/test_git_extractor.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/dev_story/test_git_extractor.py
"""Tests for git history extraction."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from agents.dev_story.git_extractor import (
    parse_log_line,
    parse_numstat_line,
    extract_commits,
)
from agents.dev_story.models import Commit, CommitFile


def test_parse_log_line_standard():
    line = "abc123|2026-03-10 10:00:00 -0500|feat: add something"
    commit = parse_log_line(line)
    assert commit is not None
    assert commit.hash == "abc123"
    assert commit.author_date == "2026-03-10 10:00:00 -0500"
    assert commit.message == "feat: add something"


def test_parse_log_line_with_pipe_in_message():
    line = "abc123|2026-03-10 10:00:00 -0500|feat: add x | y support"
    commit = parse_log_line(line)
    assert commit.message == "feat: add x | y support"


def test_parse_log_line_malformed():
    assert parse_log_line("not a valid line") is None
    assert parse_log_line("") is None


def test_parse_numstat_line_standard():
    line = "15\t3\tshared/config.py"
    result = parse_numstat_line(line)
    assert result is not None
    insertions, deletions, path = result
    assert insertions == 15
    assert deletions == 3
    assert path == "shared/config.py"


def test_parse_numstat_line_binary():
    line = "-\t-\timage.png"
    result = parse_numstat_line(line)
    assert result is not None
    insertions, deletions, path = result
    assert insertions == 0
    assert deletions == 0


def test_parse_numstat_line_empty():
    assert parse_numstat_line("") is None
    assert parse_numstat_line("\n") is None


@patch("agents.dev_story.git_extractor.subprocess.run")
def test_extract_commits_parses_output(mock_run):
    mock_run.return_value = MagicMock(
        stdout=(
            "abc123|2026-03-10 10:00:00 -0500|feat: add something\n"
            "5\t2\tshared/config.py\n"
            "10\t0\tagents/foo.py\n"
            "\n"
            "def456|2026-03-10 10:05:00 -0500|fix: broken thing\n"
            "3\t1\tagents/foo.py\n"
            "\n"
        ),
        returncode=0,
    )
    commits, files = extract_commits("/tmp/repo")
    assert len(commits) == 2
    assert commits[0].hash == "abc123"
    assert commits[0].files_changed == 2
    assert commits[0].insertions == 15
    assert commits[0].deletions == 2
    assert len(files) == 3
    assert files[0].file_path == "shared/config.py"
    assert files[0].operation == "M"


@patch("agents.dev_story.git_extractor.subprocess.run")
def test_extract_commits_with_since(mock_run):
    mock_run.return_value = MagicMock(stdout="", returncode=0)
    extract_commits("/tmp/repo", since="2026-03-01")
    cmd = mock_run.call_args[0][0]
    assert "--since=2026-03-01" in cmd


@patch("agents.dev_story.git_extractor.subprocess.run")
def test_extract_commits_handles_empty_output(mock_run):
    mock_run.return_value = MagicMock(stdout="", returncode=0)
    commits, files = extract_commits("/tmp/repo")
    assert commits == []
    assert files == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dev_story/test_git_extractor.py -v`
Expected: ImportError

- [ ] **Step 3: Implement git extractor**

```python
# agents/dev_story/git_extractor.py
"""Git history extraction via subprocess."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from agents.dev_story.models import Commit, CommitFile

log = logging.getLogger(__name__)


def parse_log_line(line: str) -> Commit | None:
    """Parse a git log line in format: hash|date|message."""
    parts = line.split("|", 2)
    if len(parts) < 3:
        return None
    return Commit(
        hash=parts[0].strip(),
        author_date=parts[1].strip(),
        message=parts[2].strip(),
    )


def parse_numstat_line(line: str) -> tuple[int, int, str] | None:
    """Parse a git numstat line: insertions\\tdeletions\\tpath."""
    line = line.strip()
    if not line:
        return None
    parts = line.split("\t", 2)
    if len(parts) < 3:
        return None
    ins_str, del_str, path = parts
    insertions = int(ins_str) if ins_str != "-" else 0
    deletions = int(del_str) if del_str != "-" else 0
    return insertions, deletions, path


def extract_commits(
    repo_path: str,
    since: str | None = None,
    after_hash: str | None = None,
) -> tuple[list[Commit], list[CommitFile]]:
    """Extract commits and per-file stats from a git repository.

    Args:
        repo_path: Absolute path to the repository root.
        since: Only commits after this date (ISO 8601 or relative).
        after_hash: Only commits after this hash (exclusive).

    Returns:
        Tuple of (commits, commit_files).
    """
    cmd = [
        "git", "-C", repo_path,
        "log", "--format=%H|%ai|%s", "--numstat",
    ]
    if since:
        cmd.append(f"--since={since}")
    if after_hash:
        cmd.append(f"{after_hash}..HEAD")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log.warning("git log failed in %s: %s", repo_path, result.stderr[:200])
        return [], []

    commits: list[Commit] = []
    commit_files: list[CommitFile] = []
    current_commit: Commit | None = None
    current_insertions = 0
    current_deletions = 0
    current_file_count = 0

    for line in result.stdout.splitlines():
        line = line.rstrip()

        # Empty line separates commits
        if not line:
            if current_commit:
                current_commit.files_changed = current_file_count
                current_commit.insertions = current_insertions
                current_commit.deletions = current_deletions
                commits.append(current_commit)
                current_commit = None
                current_insertions = 0
                current_deletions = 0
                current_file_count = 0
            continue

        # Try as commit header
        parsed = parse_log_line(line)
        if parsed and len(parsed.hash) >= 7:
            if current_commit:
                current_commit.files_changed = current_file_count
                current_commit.insertions = current_insertions
                current_commit.deletions = current_deletions
                commits.append(current_commit)
                current_insertions = 0
                current_deletions = 0
                current_file_count = 0
            current_commit = parsed
            continue

        # Try as numstat
        numstat = parse_numstat_line(line)
        if numstat and current_commit:
            ins, dels, path = numstat
            current_insertions += ins
            current_deletions += dels
            current_file_count += 1
            # Infer operation from numstat
            operation = "A" if dels == 0 and ins > 0 else "M"
            commit_files.append(
                CommitFile(
                    commit_hash=current_commit.hash,
                    file_path=path,
                    operation=operation,
                )
            )

    # Flush last commit
    if current_commit:
        current_commit.files_changed = current_file_count
        current_commit.insertions = current_insertions
        current_commit.deletions = current_deletions
        commits.append(current_commit)

    return commits, commit_files
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/dev_story/test_git_extractor.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/dev_story/git_extractor.py tests/dev_story/test_git_extractor.py
git commit -m "feat(dev-story): add git history extractor"
```

---

### Task 5: Correlator

**Files:**
- Create: `agents/dev_story/correlator.py`
- Test: `tests/dev_story/test_correlator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/dev_story/test_correlator.py
"""Tests for the correlation engine."""
from __future__ import annotations

from agents.dev_story.correlator import (
    correlate,
    _parse_iso_timestamp,
    _time_diff_minutes,
)
from agents.dev_story.models import FileChange, CommitFile, Correlation


def test_parse_iso_timestamp_utc():
    result = _parse_iso_timestamp("2026-03-10T10:00:00.000Z")
    assert result is not None


def test_parse_iso_timestamp_with_offset():
    result = _parse_iso_timestamp("2026-03-10 10:00:00 -0500")
    assert result is not None


def test_parse_iso_timestamp_invalid():
    assert _parse_iso_timestamp("not a date") is None


def test_time_diff_minutes_same_time():
    assert _time_diff_minutes("2026-03-10T10:00:00Z", "2026-03-10T10:00:00Z") == 0.0


def test_time_diff_minutes_30_min():
    diff = _time_diff_minutes("2026-03-10T10:00:00Z", "2026-03-10T10:30:00Z")
    assert abs(diff - 30.0) < 0.1


def test_time_diff_minutes_cross_timezone():
    # UTC 15:00 == CDT 10:00
    diff = _time_diff_minutes("2026-03-10T15:00:00Z", "2026-03-10 10:00:00 -0500")
    assert abs(diff) < 0.1


def test_correlate_file_and_timestamp_match():
    file_changes = [
        FileChange(
            message_id="msg-1",
            file_path="shared/config.py",
            version=2,
            change_type="modified",
            timestamp="2026-03-10T15:00:00Z",
        )
    ]
    commit_files = [
        CommitFile(
            commit_hash="abc123",
            file_path="shared/config.py",
            operation="M",
        )
    ]
    commit_dates = {"abc123": "2026-03-10 10:05:00 -0500"}  # 15:05 UTC

    results = correlate(file_changes, commit_files, commit_dates)
    assert len(results) == 1
    assert results[0].confidence >= 0.8
    assert results[0].method == "file_and_timestamp"


def test_correlate_file_match_only_distant_time():
    file_changes = [
        FileChange(
            message_id="msg-1",
            file_path="shared/config.py",
            version=2,
            change_type="modified",
            timestamp="2026-03-10T10:00:00Z",
        )
    ]
    commit_files = [
        CommitFile(
            commit_hash="abc123",
            file_path="shared/config.py",
            operation="M",
        )
    ]
    commit_dates = {"abc123": "2026-03-10 16:00:00 -0500"}  # 6 hours later

    results = correlate(file_changes, commit_files, commit_dates)
    assert len(results) == 1
    assert results[0].confidence < 0.8
    assert results[0].method == "file_match"


def test_correlate_no_match():
    file_changes = [
        FileChange(
            message_id="msg-1",
            file_path="shared/config.py",
            version=2,
            change_type="modified",
            timestamp="2026-03-10T10:00:00Z",
        )
    ]
    commit_files = [
        CommitFile(
            commit_hash="abc123",
            file_path="agents/foo.py",
            operation="M",
        )
    ]
    commit_dates = {"abc123": "2026-03-10 10:05:00 -0500"}

    results = correlate(file_changes, commit_files, commit_dates)
    assert len(results) == 0


def test_correlate_deduplicates():
    """Same message+commit pair should produce one correlation, not multiple."""
    file_changes = [
        FileChange(message_id="msg-1", file_path="a.py", version=1,
                   change_type="modified", timestamp="2026-03-10T10:00:00Z"),
        FileChange(message_id="msg-1", file_path="b.py", version=1,
                   change_type="modified", timestamp="2026-03-10T10:00:00Z"),
    ]
    commit_files = [
        CommitFile(commit_hash="abc123", file_path="a.py", operation="M"),
        CommitFile(commit_hash="abc123", file_path="b.py", operation="M"),
    ]
    commit_dates = {"abc123": "2026-03-10 10:05:00 +0000"}

    results = correlate(file_changes, commit_files, commit_dates)
    # Should be one correlation with boosted confidence, not two
    pairs = {(r.message_id, r.commit_hash) for r in results}
    assert len(pairs) == 1
    assert results[0].confidence >= 0.9  # Multiple file matches boost confidence
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dev_story/test_correlator.py -v`
Expected: ImportError

- [ ] **Step 3: Implement correlator**

```python
# agents/dev_story/correlator.py
"""Correlation engine — joins conversation file changes to git commits."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from agents.dev_story.models import Correlation, FileChange, CommitFile

log = logging.getLogger(__name__)

# Maximum time difference (minutes) for timestamp-based correlation
_TIMESTAMP_WINDOW = 30.0
# Maximum time for file-only match (hours)
_FILE_ONLY_MAX_HOURS = 12.0


def _parse_iso_timestamp(ts: str) -> datetime | None:
    """Parse various timestamp formats to timezone-aware datetime."""
    if not ts:
        return None
    # Strip trailing Z and add UTC
    ts = ts.strip()
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        # Handle "2026-03-10 10:00:00 -0500" format
        if " -" in ts or " +" in ts:
            # Python's fromisoformat handles this in 3.11+
            return datetime.fromisoformat(ts.replace(" -", "-").replace(" +", "+"))
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _time_diff_minutes(ts1: str, ts2: str) -> float | None:
    """Compute absolute time difference in minutes between two timestamps."""
    dt1 = _parse_iso_timestamp(ts1)
    dt2 = _parse_iso_timestamp(ts2)
    if dt1 is None or dt2 is None:
        return None
    # Ensure both are UTC for comparison
    if dt1.tzinfo is None:
        dt1 = dt1.replace(tzinfo=timezone.utc)
    if dt2.tzinfo is None:
        dt2 = dt2.replace(tzinfo=timezone.utc)
    return abs((dt2 - dt1).total_seconds()) / 60.0


def correlate(
    file_changes: list[FileChange],
    commit_files: list[CommitFile],
    commit_dates: dict[str, str],
) -> list[Correlation]:
    """Correlate file changes from sessions with git commits.

    Args:
        file_changes: File changes extracted from session transcripts.
        commit_files: Files changed per commit from git log.
        commit_dates: Mapping of commit hash -> author_date string.

    Returns:
        List of correlations with confidence scores.
    """
    # Build index: file_path -> list of commit_files
    commit_file_index: dict[str, list[CommitFile]] = {}
    for cf in commit_files:
        commit_file_index.setdefault(cf.file_path, []).append(cf)

    # Track best correlation per (message_id, commit_hash) pair
    best: dict[tuple[str, str], Correlation] = {}

    for fc in file_changes:
        matching_commits = commit_file_index.get(fc.file_path, [])
        for cf in matching_commits:
            pair = (fc.message_id, cf.commit_hash)
            commit_date = commit_dates.get(cf.commit_hash, "")
            diff = _time_diff_minutes(fc.timestamp, commit_date)

            if diff is not None and diff <= _TIMESTAMP_WINDOW:
                # Close in time AND same file — highest confidence
                confidence = 0.95 - (diff / _TIMESTAMP_WINDOW) * 0.1  # 0.85-0.95
                method = "file_and_timestamp"
            elif diff is not None and diff <= _FILE_ONLY_MAX_HOURS * 60:
                # Same file but farther in time
                confidence = 0.7 - (diff / (_FILE_ONLY_MAX_HOURS * 60)) * 0.2  # 0.5-0.7
                method = "file_match"
            else:
                continue  # Too far apart or unparseable

            # Keep best confidence per pair, boost if multiple files match
            existing = best.get(pair)
            if existing:
                # Multiple file matches — boost confidence
                boosted = min(existing.confidence + 0.05, 1.0)
                if boosted > existing.confidence:
                    best[pair] = Correlation(
                        message_id=pair[0],
                        commit_hash=pair[1],
                        confidence=boosted,
                        method=existing.method,
                    )
            else:
                best[pair] = Correlation(
                    message_id=pair[0],
                    commit_hash=pair[1],
                    confidence=confidence,
                    method=method,
                )

    return list(best.values())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/dev_story/test_correlator.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/dev_story/correlator.py tests/dev_story/test_correlator.py
git commit -m "feat(dev-story): add file+timestamp correlation engine"
```

---

### Task 6: Indexer Orchestrator

**Files:**
- Create: `agents/dev_story/indexer.py`
- Test: `tests/dev_story/test_indexer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/dev_story/test_indexer.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/dev_story/test_indexer.py -v`
Expected: ImportError

- [ ] **Step 3: Implement indexer**

```python
# agents/dev_story/indexer.py
"""Index orchestrator — builds the dev-story SQLite database."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from agents.dev_story.correlator import correlate
from agents.dev_story.git_extractor import extract_commits
from agents.dev_story.models import CommitFile, FileChange
from agents.dev_story.parser import extract_project_path, parse_session

log = logging.getLogger(__name__)


@dataclass
class SessionFile:
    """A discovered session JSONL file."""

    path: Path
    session_id: str
    project_path: str
    project_encoded: str


def discover_sessions(projects_dir: Path) -> list[SessionFile]:
    """Scan Claude Code projects directory for session JSONL files."""
    results: list[SessionFile] = []
    if not projects_dir.is_dir():
        log.warning("Projects directory not found: %s", projects_dir)
        return results

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        project_encoded = project_dir.name
        project_path = extract_project_path(project_encoded)
        for jsonl_file in sorted(project_dir.glob("*.jsonl")):
            session_id = jsonl_file.stem
            results.append(
                SessionFile(
                    path=jsonl_file,
                    session_id=session_id,
                    project_path=project_path,
                    project_encoded=project_encoded,
                )
            )
    return results


def index_session(conn: sqlite3.Connection, sf: SessionFile) -> None:
    """Parse and insert a single session into the database."""
    parsed = parse_session(sf.path, sf.project_path)
    s = parsed.session

    conn.execute(
        """INSERT OR REPLACE INTO sessions
           (id, project_path, project_name, started_at, ended_at, git_branch,
            message_count, total_tokens_in, total_tokens_out, total_cost_estimate,
            model_primary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (s.id, s.project_path, s.project_name, s.started_at, s.ended_at,
         s.git_branch, s.message_count, s.total_tokens_in, s.total_tokens_out,
         s.total_cost_estimate, s.model_primary),
    )

    # Clear existing data for this session (for re-indexing)
    conn.execute("DELETE FROM messages WHERE session_id = ?", (s.id,))
    conn.execute(
        "DELETE FROM tool_calls WHERE message_id IN (SELECT id FROM messages WHERE session_id = ?)",
        (s.id,),
    )

    for msg in parsed.messages:
        conn.execute(
            """INSERT OR REPLACE INTO messages
               (id, session_id, parent_id, role, timestamp, content_text, model,
                tokens_in, tokens_out)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (msg.id, msg.session_id, msg.parent_id, msg.role, msg.timestamp,
             msg.content_text, msg.model, msg.tokens_in, msg.tokens_out),
        )

    for tc in parsed.tool_calls:
        conn.execute(
            """INSERT INTO tool_calls
               (message_id, tool_name, arguments_summary, duration_ms, success,
                sequence_position)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (tc.message_id, tc.tool_name, tc.arguments_summary, tc.duration_ms,
             1 if tc.success else 0, tc.sequence_position),
        )

    for fc in parsed.file_changes:
        conn.execute(
            """INSERT INTO file_changes
               (message_id, file_path, version, change_type, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (fc.message_id, fc.file_path, fc.version, fc.change_type, fc.timestamp),
        )

    conn.commit()


def index_git(conn: sqlite3.Connection, repo_path: str, since: str | None = None) -> None:
    """Extract and insert git history for a repository."""
    commits, commit_files = extract_commits(repo_path, since=since)

    for c in commits:
        conn.execute(
            """INSERT OR IGNORE INTO commits
               (hash, author_date, message, branch, files_changed, insertions, deletions)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (c.hash, c.author_date, c.message, c.branch, c.files_changed,
             c.insertions, c.deletions),
        )

    for cf in commit_files:
        conn.execute(
            "INSERT OR IGNORE INTO commit_files (commit_hash, file_path, operation) VALUES (?, ?, ?)",
            (cf.commit_hash, cf.file_path, cf.operation),
        )

    conn.commit()
    log.info("Indexed %d commits, %d file records from %s", len(commits), len(commit_files), repo_path)


def run_correlations(conn: sqlite3.Connection) -> int:
    """Compute correlations between file changes and commits."""
    # Clear existing correlations
    conn.execute("DELETE FROM correlations")

    # Load file changes
    cursor = conn.execute("SELECT message_id, file_path, version, change_type, timestamp FROM file_changes")
    file_changes = [
        FileChange(message_id=r[0], file_path=r[1], version=r[2], change_type=r[3], timestamp=r[4])
        for r in cursor.fetchall()
    ]

    # Load commit files
    cursor = conn.execute("SELECT commit_hash, file_path, operation FROM commit_files")
    commit_files_list = [
        CommitFile(commit_hash=r[0], file_path=r[1], operation=r[2])
        for r in cursor.fetchall()
    ]

    # Load commit dates
    cursor = conn.execute("SELECT hash, author_date FROM commits")
    commit_dates = {r[0]: r[1] for r in cursor.fetchall()}

    # Run correlation
    correlations = correlate(file_changes, commit_files_list, commit_dates)

    for cor in correlations:
        conn.execute(
            "INSERT INTO correlations (message_id, commit_hash, confidence, method) VALUES (?, ?, ?, ?)",
            (cor.message_id, cor.commit_hash, cor.confidence, cor.method),
        )

    conn.commit()
    log.info("Created %d correlations", len(correlations))
    return len(correlations)


def full_index(db_path: str, claude_projects_dir: Path) -> dict:
    """Run the full indexing pipeline.

    Returns:
        Dict with stats: sessions_indexed, commits_indexed, correlations_created.
    """
    from agents.dev_story.schema import open_db

    conn = open_db(db_path)
    stats = {"sessions_indexed": 0, "commits_indexed": 0, "correlations_created": 0}

    # 1. Discover and index sessions
    session_files = discover_sessions(claude_projects_dir)
    log.info("Discovered %d session files", len(session_files))

    # Track unique project paths for git extraction
    project_paths: set[str] = set()

    for sf in session_files:
        try:
            index_session(conn, sf)
            stats["sessions_indexed"] += 1
            project_paths.add(sf.project_path)
        except Exception:
            log.exception("Failed to index session %s", sf.session_id)

    # 2. Index git history for each project
    for project_path in sorted(project_paths):
        if Path(project_path).is_dir() and (Path(project_path) / ".git").exists():
            try:
                index_git(conn, project_path)
                cursor = conn.execute("SELECT COUNT(*) FROM commits")
                stats["commits_indexed"] = cursor.fetchone()[0]
            except Exception:
                log.exception("Failed to index git for %s", project_path)

    # 3. Run correlations
    stats["correlations_created"] = run_correlations(conn)

    # Store index timestamp
    from datetime import datetime, timezone
    conn.execute(
        "INSERT OR REPLACE INTO index_state (key, value) VALUES ('last_indexed', ?)",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    conn.close()

    return stats
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/dev_story/test_indexer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add agents/dev_story/indexer.py tests/dev_story/test_indexer.py
git commit -m "feat(dev-story): add index orchestrator with session/git/correlation pipeline"
```

---

## Chunk 3: Analysis (Phase Detection, Classification, Critical Moments)

### Task 7: Phase Detector

**Files:**
- Create: `agents/dev_story/phase_detector.py`
- Test: `tests/dev_story/test_phase_detector.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/dev_story/test_phase_detector.py
"""Tests for tool sequence phase detection."""
from __future__ import annotations

from agents.dev_story.phase_detector import detect_phases, detect_phase_sequence


def test_detect_phases_explore():
    tools = ["Read", "Grep", "Glob", "Read", "Grep", "Read"]
    phases = detect_phases(tools)
    assert phases == ["explore"]


def test_detect_phases_implement():
    tools = ["Read", "Edit", "Write", "Edit", "Edit", "Bash"]
    phases = detect_phases(tools)
    assert "implement" in phases


def test_detect_phases_test():
    tools = ["Bash:pytest tests/ -v", "Bash:uv run pytest", "Bash:pytest"]
    phases = detect_phases(tools)
    assert "test" in phases


def test_detect_phases_debug_cycle():
    tools = ["Read", "Edit", "Bash:pytest", "Read", "Edit", "Bash:pytest", "Read", "Edit", "Bash:pytest"]
    phases = detect_phases(tools)
    assert "debug" in phases


def test_detect_phases_design():
    tools = ["Agent", "Agent", "Agent"]
    phases = detect_phases(tools)
    assert "design" in phases


def test_detect_phase_sequence():
    tools = [
        "Grep", "Read", "Glob", "Read",  # explore
        "Edit", "Write", "Edit",           # implement
        "Bash:pytest tests/ -v",           # test
    ]
    seq = detect_phase_sequence(tools)
    assert seq == "explore>implement>test"


def test_detect_phase_sequence_empty():
    assert detect_phase_sequence([]) == ""


def test_detect_phase_sequence_single():
    tools = ["Read", "Read", "Grep"]
    seq = detect_phase_sequence(tools)
    assert seq == "explore"
```

- [ ] **Step 2: Run tests to verify fail, then implement**

```python
# agents/dev_story/phase_detector.py
"""Detect development phases from tool call sequences."""
from __future__ import annotations

_EXPLORE_TOOLS = {"Read", "Grep", "Glob", "LS"}
_IMPLEMENT_TOOLS = {"Edit", "Write", "MultiEdit"}
_AGENT_TOOLS = {"Agent"}
_WINDOW_SIZE = 6


def _classify_window(tools: list[str]) -> str | None:
    """Classify a window of tool calls into a phase."""
    if not tools:
        return None

    names = [t.split(":")[0] for t in tools]
    bash_args = [t.split(":", 1)[1] if ":" in t else "" for t in tools]

    explore_ratio = sum(1 for n in names if n in _EXPLORE_TOOLS) / len(names)
    implement_ratio = sum(1 for n in names if n in _IMPLEMENT_TOOLS) / len(names)
    bash_count = sum(1 for n in names if n == "Bash")
    agent_count = sum(1 for n in names if n in _AGENT_TOOLS)
    test_indicators = sum(
        1 for a in bash_args if any(k in a.lower() for k in ("pytest", "test", "uv run"))
    )

    # Debug: detect edit→bash(fail)→read→edit cycles
    if implement_ratio > 0.2 and bash_count >= 2:
        # Check for repetitive patterns on same operation
        edit_bash_cycles = 0
        for i in range(len(names) - 1):
            if names[i] in _IMPLEMENT_TOOLS and names[i + 1] == "Bash":
                edit_bash_cycles += 1
        if edit_bash_cycles >= 2:
            return "debug"

    if test_indicators >= 1 and bash_count >= 1:
        return "test"
    if agent_count >= len(names) * 0.4:
        return "design"
    if implement_ratio >= 0.4:
        return "implement"
    if explore_ratio >= 0.5:
        return "explore"
    if sum(1 for n in names if n == "Read") >= len(names) * 0.7:
        return "review"

    return None


def detect_phases(tools: list[str]) -> list[str]:
    """Detect all phases present in a tool sequence."""
    phases: set[str] = set()
    for i in range(0, len(tools), _WINDOW_SIZE // 2):
        window = tools[i:i + _WINDOW_SIZE]
        if not window:
            break
        phase = _classify_window(window)
        if phase:
            phases.add(phase)
    return sorted(phases)


def detect_phase_sequence(tools: list[str]) -> str:
    """Detect the ordered sequence of phases in a tool call list.

    Returns a string like 'explore>implement>test>debug'.
    """
    if not tools:
        return ""

    sequence: list[str] = []
    prev_phase: str | None = None

    for i in range(0, len(tools), _WINDOW_SIZE // 2):
        window = tools[i:i + _WINDOW_SIZE]
        if not window:
            break
        phase = _classify_window(window)
        if phase and phase != prev_phase:
            sequence.append(phase)
            prev_phase = phase

    return ">".join(sequence)
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/dev_story/test_phase_detector.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add agents/dev_story/phase_detector.py tests/dev_story/test_phase_detector.py
git commit -m "feat(dev-story): add tool sequence phase detection"
```

---

### Task 8: Session Classifier

**Files:**
- Create: `agents/dev_story/classifier.py`
- Test: `tests/dev_story/test_classifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/dev_story/test_classifier.py
"""Tests for session dimension classification."""
from __future__ import annotations

from agents.dev_story.classifier import (
    classify_work_type,
    classify_interaction_mode,
    classify_env_topology,
    classify_session_scale,
)


def test_classify_work_type_feature():
    commit_messages = ["feat: add widget", "feat: wire up API"]
    result = classify_work_type(commit_messages)
    assert result.value == "feature"
    assert result.confidence > 0.5


def test_classify_work_type_bugfix():
    commit_messages = ["fix: broken query", "fix: null check"]
    result = classify_work_type(commit_messages)
    assert result.value == "bugfix"


def test_classify_work_type_mixed():
    commit_messages = ["feat: add X", "fix: Y", "feat: Z"]
    result = classify_work_type(commit_messages)
    assert result.value == "feature"  # Majority wins


def test_classify_work_type_empty():
    result = classify_work_type([])
    assert result.value == "unknown"


def test_classify_interaction_mode_high_steering():
    user_msg_lengths = [5, 3, 2, 8, 4, 3, 2, 1, 6, 3]  # All short
    result = classify_interaction_mode(user_msg_lengths, parallel=False)
    assert result.value == "high-steering"


def test_classify_interaction_mode_autonomous():
    user_msg_lengths = [150, 200, 180, 250]  # All long
    result = classify_interaction_mode(user_msg_lengths, parallel=False)
    assert result.value == "autonomous"


def test_classify_interaction_mode_parallel():
    user_msg_lengths = [50, 60, 70]
    result = classify_interaction_mode(user_msg_lengths, parallel=True)
    assert "parallel" in result.value


def test_classify_env_topology_containerized():
    file_paths = ["Dockerfile.api", "docker-compose.yml", "agents/foo.py"]
    result = classify_env_topology(file_paths)
    assert result.value == "containerized"


def test_classify_env_topology_host():
    file_paths = ["systemd/units/foo.service", "agents/bar.py"]
    result = classify_env_topology(file_paths)
    assert result.value == "host-side"


def test_classify_env_topology_single_repo():
    file_paths = ["agents/foo.py", "shared/config.py", "tests/test_foo.py"]
    result = classify_env_topology(file_paths)
    assert result.value == "single-repo"


def test_classify_session_scale_single_file():
    file_paths = ["agents/foo.py"]
    result = classify_session_scale(file_paths)
    assert result.value == "single-file"


def test_classify_session_scale_cross_module():
    file_paths = ["agents/foo.py", "shared/config.py", "cockpit/api/routes/data.py"]
    result = classify_session_scale(file_paths)
    assert result.value == "cross-module"
```

- [ ] **Step 2: Run tests to verify fail, then implement**

```python
# agents/dev_story/classifier.py
"""Session classification across development dimensions."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TagResult:
    """Result of a classification."""
    dimension: str
    value: str
    confidence: float


def classify_work_type(commit_messages: list[str]) -> TagResult:
    """Classify session work type from correlated commit messages."""
    if not commit_messages:
        return TagResult(dimension="work_type", value="unknown", confidence=0.0)

    counts = {"feature": 0, "bugfix": 0, "refactor": 0, "docs": 0, "test": 0, "chore": 0}
    for msg in commit_messages:
        lower = msg.lower().strip()
        if lower.startswith("feat"):
            counts["feature"] += 1
        elif lower.startswith("fix"):
            counts["bugfix"] += 1
        elif lower.startswith("refactor"):
            counts["refactor"] += 1
        elif lower.startswith("doc"):
            counts["docs"] += 1
        elif lower.startswith("test"):
            counts["test"] += 1
        elif lower.startswith("chore"):
            counts["chore"] += 1

    total = sum(counts.values())
    if total == 0:
        return TagResult(dimension="work_type", value="unknown", confidence=0.3)

    winner = max(counts, key=counts.get)
    confidence = counts[winner] / total
    return TagResult(dimension="work_type", value=winner, confidence=confidence)


def classify_interaction_mode(
    user_msg_lengths: list[int],
    parallel: bool = False,
) -> TagResult:
    """Classify interaction mode from user message lengths."""
    if not user_msg_lengths:
        return TagResult(dimension="interaction_mode", value="unknown", confidence=0.0)

    avg_length = sum(user_msg_lengths) / len(user_msg_lengths)
    short_ratio = sum(1 for l in user_msg_lengths if l < 20) / len(user_msg_lengths)

    if parallel:
        base = "parallel-"
    else:
        base = ""

    if short_ratio > 0.7:
        return TagResult(
            dimension="interaction_mode",
            value=f"{base}high-steering",
            confidence=min(short_ratio, 0.95),
        )
    elif avg_length > 100:
        return TagResult(
            dimension="interaction_mode",
            value=f"{base}autonomous",
            confidence=min(avg_length / 200, 0.95),
        )
    else:
        return TagResult(
            dimension="interaction_mode",
            value=f"{base}mixed",
            confidence=0.6,
        )


def classify_env_topology(file_paths: list[str]) -> TagResult:
    """Classify environment topology from file paths touched."""
    if not file_paths:
        return TagResult(dimension="env_topology", value="unknown", confidence=0.0)

    docker_files = sum(1 for p in file_paths if "docker" in p.lower() or "Dockerfile" in p)
    systemd_files = sum(1 for p in file_paths if "systemd/" in p)
    # Cross-project: multiple top-level directories or project references
    top_dirs = {p.split("/")[0] for p in file_paths if "/" in p}

    if docker_files > 0:
        return TagResult(dimension="env_topology", value="containerized", confidence=0.8)
    if systemd_files > 0:
        return TagResult(dimension="env_topology", value="host-side", confidence=0.7)
    return TagResult(dimension="env_topology", value="single-repo", confidence=0.6)


def classify_session_scale(file_paths: list[str]) -> TagResult:
    """Classify session scale from file paths."""
    if not file_paths:
        return TagResult(dimension="session_scale", value="unknown", confidence=0.0)

    if len(file_paths) == 1:
        return TagResult(dimension="session_scale", value="single-file", confidence=0.95)

    # Count distinct top-level modules
    modules = set()
    for p in file_paths:
        parts = p.split("/")
        if len(parts) >= 2:
            modules.add(parts[0])
        else:
            modules.add(p)

    if len(modules) >= 3:
        return TagResult(dimension="session_scale", value="cross-module", confidence=0.8)
    elif len(modules) == 2:
        return TagResult(dimension="session_scale", value="multi-module", confidence=0.7)
    else:
        return TagResult(dimension="session_scale", value="single-module", confidence=0.7)
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/dev_story/test_classifier.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add agents/dev_story/classifier.py tests/dev_story/test_classifier.py
git commit -m "feat(dev-story): add session dimension classification"
```

---

### Task 9: Critical Moments (Tiers A & B)

**Files:**
- Create: `agents/dev_story/critical_moments.py`
- Test: `tests/dev_story/test_critical_moments.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/dev_story/test_critical_moments.py
"""Tests for critical moment detection."""
from __future__ import annotations

import sqlite3

from agents.dev_story.critical_moments import (
    detect_churn_moments,
    detect_wrong_path_moments,
)
from agents.dev_story.schema import create_tables


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_tables(conn)
    return conn


def _seed_churn_data(conn: sqlite3.Connection) -> None:
    """Seed DB with a file that was introduced then replaced quickly."""
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', '/tmp', 'test', '2026-03-01T10:00:00Z', '2026-03-01T11:00:00Z', 'main', 10, 0, 0, 0, NULL)"
    )
    conn.execute(
        "INSERT INTO messages VALUES ('m1', 's1', NULL, 'assistant', '2026-03-01T10:30:00Z', 'wrote code', NULL, 0, 0)"
    )
    conn.execute(
        "INSERT INTO commits VALUES ('c1', '2026-03-01 10:35:00 -0500', 'feat: add widget', 'main', 1, 50, 0)"
    )
    conn.execute(
        "INSERT INTO commits VALUES ('c2', '2026-03-02 10:00:00 -0500', 'fix: rewrite widget', 'main', 1, 40, 45)"
    )
    conn.execute("INSERT INTO commit_files VALUES ('c1', 'widget.py', 'A')")
    conn.execute("INSERT INTO commit_files VALUES ('c2', 'widget.py', 'M')")
    conn.execute("INSERT INTO correlations VALUES (1, 'm1', 'c1', 0.9, 'file_and_timestamp')")
    conn.commit()


def test_detect_churn_moments_finds_quick_rewrite():
    conn = _make_db()
    _seed_churn_data(conn)
    moments = detect_churn_moments(conn, max_survived_days=7)
    assert len(moments) >= 1
    assert moments[0].moment_type == "churn"
    assert "widget.py" in moments[0].description


def test_detect_churn_moments_empty_db():
    conn = _make_db()
    moments = detect_churn_moments(conn, max_survived_days=7)
    assert moments == []


def _seed_wrong_path_data(conn: sqlite3.Connection) -> None:
    """Seed DB with retry loop pattern."""
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', '/tmp', 'test', '2026-03-01T10:00:00Z', '2026-03-01T11:00:00Z', 'main', 20, 0, 0, 0, NULL)"
    )
    for i in range(6):
        msg_id = f"m{i}"
        conn.execute(
            "INSERT INTO messages VALUES (?, 's1', NULL, 'assistant', ?, 'trying again', NULL, 0, 0)",
            (msg_id, f"2026-03-01T10:{i:02d}:00Z"),
        )
        # Alternating Edit → Bash pattern
        tool = "Edit" if i % 2 == 0 else "Bash"
        arg = "agents/foo.py" if tool == "Edit" else "pytest tests/test_foo.py"
        conn.execute(
            "INSERT INTO tool_calls VALUES (NULL, ?, ?, ?, NULL, ?, 0)",
            (msg_id, tool, arg, 0 if tool == "Bash" else 1),
        )
    conn.commit()


def test_detect_wrong_path_retry_loops():
    conn = _make_db()
    _seed_wrong_path_data(conn)
    moments = detect_wrong_path_moments(conn)
    assert len(moments) >= 1
    assert moments[0].moment_type == "wrong_path"


def test_detect_wrong_path_empty_db():
    conn = _make_db()
    moments = detect_wrong_path_moments(conn)
    assert moments == []
```

- [ ] **Step 2: Run tests to verify fail, then implement**

```python
# agents/dev_story/critical_moments.py
"""Critical moment detection — churn, wrong paths, cascades."""
from __future__ import annotations

import logging
import sqlite3

from agents.dev_story.models import CriticalMoment

log = logging.getLogger(__name__)


def detect_churn_moments(
    conn: sqlite3.Connection,
    max_survived_days: int = 7,
) -> list[CriticalMoment]:
    """Detect code that was introduced and significantly rewritten quickly.

    Finds files where a commit added/modified code, then another commit
    changed the same file within max_survived_days.
    """
    cursor = conn.execute(
        """
        SELECT
            cf1.file_path,
            c1.hash AS intro_hash,
            c1.author_date AS intro_date,
            c1.message AS intro_msg,
            c2.hash AS replace_hash,
            c2.author_date AS replace_date,
            c2.message AS replace_msg,
            cor.message_id,
            cor.confidence
        FROM commit_files cf1
        JOIN commits c1 ON c1.hash = cf1.commit_hash
        JOIN commit_files cf2 ON cf2.file_path = cf1.file_path AND cf2.commit_hash != cf1.commit_hash
        JOIN commits c2 ON c2.hash = cf2.commit_hash AND c2.author_date > c1.author_date
        LEFT JOIN correlations cor ON cor.commit_hash = c1.hash
        WHERE julianday(c2.author_date) - julianday(c1.author_date) <= ?
          AND c2.deletions > 0
        ORDER BY julianday(c2.author_date) - julianday(c1.author_date) ASC
        LIMIT 100
        """
    , (max_survived_days,))

    moments: list[CriticalMoment] = []
    seen: set[tuple[str, str]] = set()

    for row in cursor.fetchall():
        file_path, intro_hash, intro_date, intro_msg, replace_hash, replace_date, replace_msg, message_id, confidence = row
        key = (intro_hash, replace_hash)
        if key in seen:
            continue
        seen.add(key)

        moments.append(
            CriticalMoment(
                moment_type="churn",
                severity=min((confidence or 0.5) * 0.8, 1.0),
                session_id=_session_for_message(conn, message_id) or "",
                message_id=message_id,
                commit_hash=intro_hash,
                description=f"{file_path} introduced in '{intro_msg}' ({intro_date}), rewritten in '{replace_msg}' ({replace_date})",
                evidence=f'{{"file": "{file_path}", "intro": "{intro_hash}", "replace": "{replace_hash}"}}',
            )
        )

    return moments


def detect_wrong_path_moments(conn: sqlite3.Connection) -> list[CriticalMoment]:
    """Detect wrong-path patterns from tool call sequences.

    Looks for retry loops: same tool on same file executed 3+ times
    with failures between.
    """
    # Find sessions with high edit→bash failure cycles
    cursor = conn.execute(
        """
        SELECT
            m.session_id,
            tc.tool_name,
            tc.arguments_summary,
            tc.success,
            m.id AS message_id,
            m.timestamp
        FROM tool_calls tc
        JOIN messages m ON m.id = tc.message_id
        ORDER BY m.session_id, m.timestamp, tc.sequence_position
        """
    )

    rows = cursor.fetchall()
    if not rows:
        return []

    moments: list[CriticalMoment] = []
    current_session: str | None = None
    consecutive_failures = 0
    failure_target: str | None = None
    first_message_id: str | None = None

    for row in rows:
        session_id, tool_name, args, success, message_id, timestamp = row

        if session_id != current_session:
            current_session = session_id
            consecutive_failures = 0
            failure_target = None
            first_message_id = None

        if tool_name == "Bash" and not success:
            if failure_target is None:
                failure_target = args
                first_message_id = message_id
            consecutive_failures += 1
        elif tool_name == "Bash" and success and consecutive_failures >= 3:
            # Resolved after retries — this was a wrong path
            moments.append(
                CriticalMoment(
                    moment_type="wrong_path",
                    severity=min(consecutive_failures * 0.15, 1.0),
                    session_id=session_id,
                    message_id=first_message_id,
                    description=f"Retry loop: {consecutive_failures} consecutive failures on '{failure_target or 'unknown'}'",
                )
            )
            consecutive_failures = 0
            failure_target = None
        elif tool_name in ("Edit", "Write"):
            # Edit between failures continues the cycle
            pass
        else:
            if consecutive_failures >= 3:
                moments.append(
                    CriticalMoment(
                        moment_type="wrong_path",
                        severity=min(consecutive_failures * 0.15, 1.0),
                        session_id=session_id,
                        message_id=first_message_id,
                        description=f"Retry loop: {consecutive_failures} failures before giving up on '{failure_target or 'unknown'}'",
                    )
                )
            consecutive_failures = 0
            failure_target = None

    return moments


def _session_for_message(conn: sqlite3.Connection, message_id: str | None) -> str | None:
    """Look up session_id for a message."""
    if not message_id:
        return None
    cursor = conn.execute("SELECT session_id FROM messages WHERE id = ?", (message_id,))
    row = cursor.fetchone()
    return row[0] if row else None
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/dev_story/test_critical_moments.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add agents/dev_story/critical_moments.py tests/dev_story/test_critical_moments.py
git commit -m "feat(dev-story): add critical moment detection (churn + wrong-path)"
```

---

## Chunk 4: Query Agent & CLI

### Task 10: Query Agent

**Files:**
- Create: `agents/dev_story/query.py`
- Test: `tests/dev_story/test_query.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/dev_story/test_query.py
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
```

- [ ] **Step 2: Run tests to verify fail, then implement**

```python
# agents/dev_story/query.py
"""Pydantic-ai query agent for the dev-story database."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from pydantic_ai import Agent

from shared.config import get_model

log = logging.getLogger(__name__)

_READ_ONLY_PREFIXES = ("select", "with", "explain", "pragma")


def build_system_prompt() -> str:
    """Build the system prompt describing the schema and query patterns."""
    return """You are a development archaeology analyst. You have access to a SQLite database
that correlates Claude Code conversation logs with git history.

## Schema

### Core Tables
- sessions(id, project_path, project_name, started_at, ended_at, git_branch, message_count, total_tokens_in, total_tokens_out, total_cost_estimate, model_primary)
- messages(id, session_id, parent_id, role, timestamp, content_text, model, tokens_in, tokens_out)
- tool_calls(id, message_id, tool_name, arguments_summary, duration_ms, success, sequence_position)
- file_changes(id, message_id, file_path, version, change_type, timestamp)
- commits(hash, author_date, message, branch, files_changed, insertions, deletions)
- commit_files(commit_hash, file_path, operation)
- correlations(id, message_id, commit_hash, confidence, method)

### Derived Tables
- session_metrics(session_id, tool_call_count, tool_diversity, edit_count, bash_count, agent_dispatch_count, avg_response_time_ms, user_steering_ratio, phase_sequence)
- session_tags(session_id, dimension, value, confidence)
- critical_moments(id, moment_type, severity, session_id, message_id, commit_hash, description, evidence)
- hotspots(file_path, change_frequency, session_count, churn_rate)
- code_survival(file_path, introduced_by_commit, introduced_by_session, survived_days, replacement_commit)

## How to Answer

- **Story questions**: Find correlated sessions + commits, narrate chronologically with conversation excerpts
- **Pattern questions**: Use SQL aggregations, GROUP BY session dimensions
- **Critical moment questions**: Query critical_moments, retrieve conversation context
- **Efficiency questions**: Compare token spend, time-to-commit, tool patterns across dimensions

Always cite evidence: session IDs, commit hashes, timestamps, confidence scores.
When showing conversation excerpts, use session_content tool for context around key messages.
"""


@dataclass
class QueryDeps:
    """Runtime dependencies for the query agent."""

    db_path: str


def _sql_query(conn: sqlite3.Connection, query: str) -> str:
    """Execute a read-only SQL query and return formatted results."""
    stripped = query.strip().lower()
    if not any(stripped.startswith(p) for p in _READ_ONLY_PREFIXES):
        return "Error: Only SELECT/WITH/EXPLAIN/PRAGMA queries are allowed."

    try:
        cursor = conn.execute(query)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()

        if not rows:
            return "No results."

        # Format as table
        lines = [" | ".join(columns)]
        lines.append("-" * len(lines[0]))
        for row in rows[:100]:  # Limit output
            lines.append(" | ".join(str(v) for v in row))

        if len(rows) > 100:
            lines.append(f"... ({len(rows)} total rows, showing first 100)")

        return "\n".join(lines)
    except Exception as e:
        return f"SQL error: {e}"


def _session_content(
    conn: sqlite3.Connection,
    session_id: str,
    around_message_id: str | None = None,
) -> str:
    """Retrieve conversation text from a session."""
    if around_message_id:
        # Get ±10 messages around the target
        cursor = conn.execute(
            """
            SELECT role, timestamp, content_text FROM messages
            WHERE session_id = ?
            ORDER BY timestamp
            """,
            (session_id,),
        )
        rows = cursor.fetchall()
        target_idx = None
        for i, row in enumerate(rows):
            # Find closest message by checking all messages in session
            pass

        if not rows:
            return f"Session {session_id} not found."

        # Find the target message index
        msg_ids_cursor = conn.execute(
            "SELECT id FROM messages WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
        msg_ids = [r[0] for r in msg_ids_cursor.fetchall()]
        try:
            target_idx = msg_ids.index(around_message_id)
        except ValueError:
            target_idx = len(rows) // 2

        start = max(0, target_idx - 10)
        end = min(len(rows), target_idx + 11)
        rows = rows[start:end]
    else:
        cursor = conn.execute(
            """
            SELECT role, timestamp, content_text FROM messages
            WHERE session_id = ?
            ORDER BY timestamp
            LIMIT 40
            """,
            (session_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        return f"Session {session_id} not found."

    lines = []
    for role, ts, text in rows:
        # Truncate long messages
        preview = text[:500] + "..." if len(text) > 500 else text
        lines.append(f"## {role.title()} ({ts})\n{preview}\n")

    return "\n".join(lines)


def _file_history(conn: sqlite3.Connection, file_path: str, since: str | None = None) -> str:
    """Show commit + session history for a file."""
    query = """
        SELECT
            c.hash, c.author_date, c.message, c.insertions, c.deletions,
            cor.confidence, cor.method,
            s.id AS session_id, s.project_name
        FROM commit_files cf
        JOIN commits c ON c.hash = cf.commit_hash
        LEFT JOIN correlations cor ON cor.commit_hash = c.hash
        LEFT JOIN messages m ON m.id = cor.message_id
        LEFT JOIN sessions s ON s.id = m.session_id
        WHERE cf.file_path = ?
        ORDER BY c.author_date DESC
        LIMIT 50
    """
    cursor = conn.execute(query, (file_path,))
    rows = cursor.fetchall()

    if not rows:
        return f"No history found for {file_path}"

    lines = [f"History for {file_path}:\n"]
    for hash, date, msg, ins, dels, conf, method, sess_id, proj in rows:
        line = f"- {hash[:8]} ({date}) {msg} [+{ins}/-{dels}]"
        if sess_id:
            line += f" <- session {sess_id[:8]} ({proj}, confidence={conf:.2f})"
        lines.append(line)

    return "\n".join(lines)


def create_agent() -> Agent:
    """Create the dev-story query agent."""
    agent = Agent(
        get_model("balanced"),
        system_prompt=build_system_prompt(),
        deps_type=QueryDeps,
    )

    @agent.tool
    async def sql_query(ctx, query: str) -> str:
        """Execute read-only SQL against the dev-story database."""
        conn = sqlite3.connect(ctx.deps.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return _sql_query(conn, query)
        finally:
            conn.close()

    @agent.tool
    async def session_content(ctx, session_id: str, around_message_id: str = "") -> str:
        """Retrieve conversation text from a session. Optionally center around a specific message."""
        conn = sqlite3.connect(ctx.deps.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return _session_content(conn, session_id, around_message_id or None)
        finally:
            conn.close()

    @agent.tool
    async def file_history(ctx, file_path: str) -> str:
        """Show commit and session history for a specific file."""
        conn = sqlite3.connect(ctx.deps.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return _file_history(conn, file_path)
        finally:
            conn.close()

    @agent.tool
    async def git_diff(ctx, commit_hash: str) -> str:
        """Show the actual diff for a git commit."""
        import subprocess
        # Find the repo path from the commit
        conn = sqlite3.connect(ctx.deps.db_path)
        cursor = conn.execute(
            """SELECT DISTINCT s.project_path FROM correlations cor
               JOIN messages m ON m.id = cor.message_id
               JOIN sessions s ON s.id = m.session_id
               WHERE cor.commit_hash = ? LIMIT 1""",
            (commit_hash,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return f"No project path found for commit {commit_hash}"

        result = subprocess.run(
            ["git", "-C", row[0], "show", "--stat", commit_hash],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout[:3000] if result.returncode == 0 else f"git show failed: {result.stderr[:200]}"

    return agent
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/dev_story/test_query.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add agents/dev_story/query.py tests/dev_story/test_query.py
git commit -m "feat(dev-story): add pydantic-ai query agent with SQL and content tools"
```

---

### Task 11: CLI Entry Point

**Files:**
- Create: `agents/dev_story/__main__.py`
- Test: Manual verification (CLI entry points are integration-tested)

- [ ] **Step 1: Implement CLI**

```python
# agents/dev_story/__main__.py
"""CLI entry point for the dev-story agent."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from shared.config import PROFILES_DIR, CLAUDE_CONFIG_DIR

DB_PATH = str(PROFILES_DIR / "dev-story.db")
CLAUDE_PROJECTS_DIR = CLAUDE_CONFIG_DIR / "projects"


async def cmd_index(incremental: bool = False) -> None:
    """Run the indexing pipeline."""
    from agents.dev_story.indexer import full_index

    print(f"Indexing sessions from {CLAUDE_PROJECTS_DIR}")
    print(f"Database: {DB_PATH}")
    stats = full_index(DB_PATH, CLAUDE_PROJECTS_DIR)
    print(f"\nIndex complete:")
    print(f"  Sessions: {stats['sessions_indexed']}")
    print(f"  Commits:  {stats['commits_indexed']}")
    print(f"  Correlations: {stats['correlations_created']}")


async def cmd_stats() -> None:
    """Show index statistics."""
    from agents.dev_story.schema import open_db

    conn = open_db(DB_PATH)
    tables = ["sessions", "messages", "tool_calls", "file_changes",
              "commits", "commit_files", "correlations", "session_metrics",
              "session_tags", "critical_moments", "hotspots"]
    print("Dev Story Index Statistics\n")
    for table in tables:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        if count > 0:
            print(f"  {table:20s} {count:>8,}")

    cursor = conn.execute("SELECT value FROM index_state WHERE key='last_indexed'")
    row = cursor.fetchone()
    if row:
        print(f"\n  Last indexed: {row[0]}")
    conn.close()


async def cmd_query(prompt: str) -> None:
    """Run a single query."""
    from agents.dev_story.query import create_agent, QueryDeps

    agent = create_agent()
    result = await agent.run(prompt, deps=QueryDeps(db_path=DB_PATH))
    print(result.output)


async def cmd_interactive() -> None:
    """Interactive query REPL."""
    from agents.dev_story.query import create_agent, QueryDeps

    agent = create_agent()
    deps = QueryDeps(db_path=DB_PATH)
    print("Dev Story — Interactive Mode")
    print("Type your questions. Ctrl+D to exit.\n")

    while True:
        try:
            prompt = input("? ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not prompt.strip():
            continue
        result = await agent.run(prompt, deps=deps)
        print(f"\n{result.output}\n")


async def cmd_hotspots() -> None:
    """Show top hotspot files."""
    from agents.dev_story.schema import open_db

    conn = open_db(DB_PATH)
    cursor = conn.execute(
        "SELECT file_path, change_frequency, session_count, churn_rate FROM hotspots ORDER BY change_frequency DESC LIMIT 20"
    )
    rows = cursor.fetchall()
    if not rows:
        print("No hotspot data. Run --index first.")
        return
    print(f"{'File':<50} {'Changes':>8} {'Sessions':>9} {'Churn':>6}")
    print("-" * 75)
    for path, freq, sess, churn in rows:
        print(f"{path:<50} {freq:>8} {sess:>9} {churn:>6.2f}")
    conn.close()


async def cmd_correlations() -> None:
    """Show correlation quality stats."""
    from agents.dev_story.schema import open_db

    conn = open_db(DB_PATH)
    cursor = conn.execute(
        """SELECT method, COUNT(*), AVG(confidence), MIN(confidence), MAX(confidence)
           FROM correlations GROUP BY method ORDER BY COUNT(*) DESC"""
    )
    rows = cursor.fetchall()
    if not rows:
        print("No correlations. Run --index first.")
        return
    print(f"{'Method':<25} {'Count':>6} {'Avg Conf':>9} {'Min':>6} {'Max':>6}")
    print("-" * 55)
    for method, count, avg, mn, mx in rows:
        print(f"{method:<25} {count:>6} {avg:>9.3f} {mn:>6.3f} {mx:>6.3f}")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dev Story — development archaeology agent",
        prog="python -m agents.dev_story",
    )
    parser.add_argument("query", nargs="?", help="Natural language query")
    parser.add_argument("--index", action="store_true", help="Run the indexing pipeline")
    parser.add_argument("--incremental", action="store_true", help="Only index new/changed data")
    parser.add_argument("--interactive", action="store_true", help="Interactive query REPL")
    parser.add_argument("--stats", action="store_true", help="Show index statistics")
    parser.add_argument("--hotspots", action="store_true", help="Show top hotspot files")
    parser.add_argument("--correlations", action="store_true", help="Show correlation quality")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.index:
        asyncio.run(cmd_index(incremental=args.incremental))
    elif args.stats:
        asyncio.run(cmd_stats())
    elif args.hotspots:
        asyncio.run(cmd_hotspots())
    elif args.correlations:
        asyncio.run(cmd_correlations())
    elif args.interactive:
        asyncio.run(cmd_interactive())
    elif args.query:
        asyncio.run(cmd_query(args.query))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify CLI help works**

Run: `uv run python -m agents.dev_story --help`
Expected: Shows help with all flags

- [ ] **Step 3: Commit**

```bash
git add agents/dev_story/__main__.py
git commit -m "feat(dev-story): add CLI entry point with index/query/stats commands"
```

---

### Task 12: Integration Test — Full Pipeline

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/dev_story/ -v`
Expected: All tests pass

- [ ] **Step 2: Run indexer against real data**

Run: `uv run python -m agents.dev_story --index`
Expected: Indexes sessions and git history, prints stats

- [ ] **Step 3: Check stats**

Run: `uv run python -m agents.dev_story --stats`
Expected: Shows non-zero counts for sessions, messages, commits, correlations

- [ ] **Step 4: Check correlations quality**

Run: `uv run python -m agents.dev_story --correlations`
Expected: Shows correlation methods with confidence ranges

- [ ] **Step 5: Test a query**

Run: `uv run python -m agents.dev_story "what sessions produced the most commits?"`
Expected: Narrative answer referencing session IDs and commit data

- [ ] **Step 6: Commit any fixes from integration testing**

```bash
git add -u
git commit -m "fix(dev-story): integration test fixes"
```

---

## Chunk 5: Derived Analytics (deferred)

Tasks 13-15 (survival.py, hotspot computation, session_metrics aggregation, Tier C cascade detection) are deferred until the core pipeline proves out with real data. The schema and models are already in place — these tasks add computation during indexing and populate the derived tables.

This is intentional: run the MVP, see what correlations look like, then add the expensive analytics.
