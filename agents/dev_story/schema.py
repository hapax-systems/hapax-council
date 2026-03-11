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
    session_id TEXT REFERENCES sessions(id),
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
