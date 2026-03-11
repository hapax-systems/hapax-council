"""Tests for git bundle and archived conversation support."""

from __future__ import annotations

import sqlite3
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.dev_story.git_extractor import (
    discover_bundles,
    extract_commits_from_bundle,
)
from agents.dev_story.indexer import (
    _discover_archived_session_files,
    index_bundles,
)
from agents.dev_story.parser import discover_archived_sessions
from agents.dev_story.schema import SCHEMA_VERSION, _migrate_v1_to_v2, create_tables

# --- discover_bundles ---


def test_discover_bundles_finds_bundle_files():
    with tempfile.TemporaryDirectory() as tmp:
        bundles_dir = Path(tmp)
        (bundles_dir / "ai-agents-history.bundle").write_bytes(b"")
        (bundles_dir / "hapaxromana-history.bundle").write_bytes(b"")
        (bundles_dir / "notes.txt").write_text("not a bundle")

        results = discover_bundles(bundles_dir)
        assert len(results) == 2
        paths = [r[0].name for r in results]
        names = [r[1] for r in results]
        assert "ai-agents-history.bundle" in paths
        assert "hapaxromana-history.bundle" in paths
        assert "ai-agents" in names
        assert "hapaxromana" in names


def test_discover_bundles_strips_history_suffix():
    with tempfile.TemporaryDirectory() as tmp:
        bundles_dir = Path(tmp)
        (bundles_dir / "hapax-mgmt-history.bundle").write_bytes(b"")
        results = discover_bundles(bundles_dir)
        assert results[0][1] == "hapax-mgmt"


def test_discover_bundles_no_history_suffix():
    with tempfile.TemporaryDirectory() as tmp:
        bundles_dir = Path(tmp)
        (bundles_dir / "my-repo.bundle").write_bytes(b"")
        results = discover_bundles(bundles_dir)
        assert results[0][1] == "my-repo"


def test_discover_bundles_nonexistent_dir():
    results = discover_bundles(Path("/nonexistent/dir"))
    assert results == []


def test_discover_bundles_empty_dir():
    with tempfile.TemporaryDirectory() as tmp:
        results = discover_bundles(Path(tmp))
        assert results == []


# --- extract_commits_from_bundle ---


def _create_test_bundle(tmp_dir: str) -> Path:
    """Create a minimal git bundle for testing.

    Creates a repo with 2 commits, bundles it, returns the bundle path.
    """
    repo_path = Path(tmp_dir) / "source-repo"
    repo_path.mkdir()
    bundle_path = Path(tmp_dir) / "test-history.bundle"

    subprocess.run(["git", "init", str(repo_path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.name", "Test"],
        capture_output=True,
        check=True,
    )

    # First commit
    (repo_path / "file1.py").write_text("print('hello')\n")
    subprocess.run(["git", "-C", str(repo_path), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", "feat: initial commit"],
        capture_output=True,
        check=True,
    )

    # Second commit
    (repo_path / "file2.py").write_text("print('world')\n")
    subprocess.run(["git", "-C", str(repo_path), "add", "."], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", "feat: add file2"],
        capture_output=True,
        check=True,
    )

    # Create bundle
    subprocess.run(
        ["git", "-C", str(repo_path), "bundle", "create", str(bundle_path), "--all"],
        capture_output=True,
        check=True,
    )

    return bundle_path


def test_extract_commits_from_bundle():
    with tempfile.TemporaryDirectory() as tmp:
        bundle_path = _create_test_bundle(tmp)
        commits, commit_files = extract_commits_from_bundle(bundle_path, "test-repo")

        assert len(commits) == 2
        assert all(c.source_repo == "test-repo" for c in commits)
        assert all(cf.source_repo == "test-repo" for cf in commit_files)

        # Check commit messages are present
        messages = {c.message for c in commits}
        assert "feat: initial commit" in messages
        assert "feat: add file2" in messages


def test_extract_commits_from_bundle_invalid_path():
    commits, commit_files = extract_commits_from_bundle(
        Path("/nonexistent/bundle.bundle"), "bad-repo"
    )
    assert commits == []
    assert commit_files == []


@patch("agents.dev_story.git_extractor.subprocess.run")
def test_extract_commits_from_bundle_clone_failure(mock_run):
    """If git clone fails, return empty lists."""
    mock_run.return_value = MagicMock(returncode=128, stderr="fatal: not a bundle")
    with tempfile.TemporaryDirectory() as tmp:
        bundle_path = Path(tmp) / "bad.bundle"
        bundle_path.write_bytes(b"not a real bundle")
        commits, commit_files = extract_commits_from_bundle(bundle_path, "bad-repo")
        assert commits == []
        assert commit_files == []


# --- discover_archived_sessions ---


def test_discover_archived_sessions_finds_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = Path(tmp)
        # Create conversation directories
        ai_dir = archive_dir / "ai-agents-conversations"
        ai_dir.mkdir()
        (ai_dir / "session1.jsonl").write_text('{"type": "user"}\n')
        (ai_dir / "session2.jsonl").write_text('{"type": "user"}\n')

        hr_dir = archive_dir / "hapaxromana-conversations"
        hr_dir.mkdir()
        (hr_dir / "session3.jsonl").write_text('{"type": "user"}\n')

        results = discover_archived_sessions(archive_dir)
        assert len(results) == 3
        stems = {p.stem for p in results}
        assert stems == {"session1", "session2", "session3"}


def test_discover_archived_sessions_skips_non_jsonl():
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = Path(tmp)
        subdir = archive_dir / "conversations"
        subdir.mkdir()
        (subdir / "INDEX.md").write_text("# index\n")
        (subdir / "notes.txt").write_text("notes\n")

        results = discover_archived_sessions(archive_dir)
        assert results == []


def test_discover_archived_sessions_nonexistent_dir():
    results = discover_archived_sessions(Path("/nonexistent/archive"))
    assert results == []


def test_discover_archived_sessions_skips_files_at_top_level():
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = Path(tmp)
        (archive_dir / "INDEX.md").write_text("# index\n")
        (archive_dir / "stray.jsonl").write_text('{"type": "user"}\n')

        results = discover_archived_sessions(archive_dir)
        # stray.jsonl is at top level, not in a subdirectory
        assert results == []


# --- _discover_archived_session_files ---


def test_discover_archived_session_files_creates_session_files():
    with tempfile.TemporaryDirectory() as tmp:
        archive_dir = Path(tmp)
        ai_dir = archive_dir / "ai-agents-conversations"
        ai_dir.mkdir()
        (ai_dir / "sess-abc.jsonl").write_text('{"type": "user"}\n')

        with patch("agents.dev_story.indexer.CONVERSATIONS_ARCHIVE_DIR", archive_dir):
            results = _discover_archived_session_files(archive_dir)

        assert len(results) == 1
        sf = results[0]
        assert sf.session_id == "sess-abc"
        assert sf.project_path == "(archived)/ai-agents"
        assert sf.project_encoded == "ai-agents-conversations"


# --- schema migration ---


def test_schema_version_is_2():
    assert SCHEMA_VERSION == 2


def test_migration_adds_source_repo_columns():
    """Simulate a v1 database and verify migration adds source_repo."""
    conn = sqlite3.connect(":memory:")

    # Create v1 schema (without source_repo columns)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS index_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO index_state (key, value) VALUES ('schema_version', '1');
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
            commit_hash TEXT NOT NULL,
            file_path TEXT NOT NULL,
            operation TEXT NOT NULL,
            PRIMARY KEY (commit_hash, file_path)
        );
    """)

    # Run migration
    _migrate_v1_to_v2(conn)

    # Verify source_repo columns exist
    cursor = conn.execute("PRAGMA table_info(commits)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "source_repo" in columns

    cursor = conn.execute("PRAGMA table_info(commit_files)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "source_repo" in columns


def test_migration_is_idempotent():
    """Running migration twice should not raise."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS index_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO index_state (key, value) VALUES ('schema_version', '1');
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
            commit_hash TEXT NOT NULL,
            file_path TEXT NOT NULL,
            operation TEXT NOT NULL,
            PRIMARY KEY (commit_hash, file_path)
        );
    """)
    _migrate_v1_to_v2(conn)
    _migrate_v1_to_v2(conn)  # Should not raise

    cursor = conn.execute("PRAGMA table_info(commits)")
    source_repo_count = sum(1 for row in cursor.fetchall() if row[1] == "source_repo")
    assert source_repo_count == 1


def test_create_tables_fresh_includes_source_repo():
    """A fresh database should have source_repo columns."""
    conn = sqlite3.connect(":memory:")
    create_tables(conn)

    cursor = conn.execute("PRAGMA table_info(commits)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "source_repo" in columns

    cursor = conn.execute("PRAGMA table_info(commit_files)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "source_repo" in columns


# --- index_bundles ---


@patch("agents.dev_story.indexer.discover_bundles")
@patch("agents.dev_story.indexer.extract_commits_from_bundle")
def test_index_bundles_inserts_with_source_repo(mock_extract, mock_discover):
    from agents.dev_story.models import Commit, CommitFile

    mock_discover.return_value = [
        (Path("/tmp/ai-agents-history.bundle"), "ai-agents"),
    ]
    mock_extract.return_value = (
        [
            Commit(
                hash="aaa111",
                author_date="2026-01-01 10:00:00 -0500",
                message="feat: agent init",
                source_repo="ai-agents",
            ),
        ],
        [
            CommitFile(
                commit_hash="aaa111",
                file_path="agents/foo.py",
                operation="A",
                source_repo="ai-agents",
            ),
        ],
    )

    conn = sqlite3.connect(":memory:")
    create_tables(conn)

    total = index_bundles(conn, Path("/tmp/bundles"))
    assert total == 1

    cursor = conn.execute("SELECT hash, source_repo FROM commits")
    row = cursor.fetchone()
    assert row[0] == "aaa111"
    assert row[1] == "ai-agents"

    cursor = conn.execute("SELECT source_repo FROM commit_files")
    assert cursor.fetchone()[0] == "ai-agents"


@patch("agents.dev_story.indexer.discover_bundles")
def test_index_bundles_no_bundles(mock_discover):
    mock_discover.return_value = []
    conn = sqlite3.connect(":memory:")
    create_tables(conn)
    total = index_bundles(conn, Path("/tmp/empty"))
    assert total == 0
