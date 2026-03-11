"""Integration tests for dev-story query agent against real data."""

from __future__ import annotations

from agents.dev_story.query import _file_history, _session_content, _sql_query
from tests.query_integration._helpers import (
    EMPTY_DEV_STORY_DB,
    POPULATED_DEV_STORY_DB,
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
            "SELECT COUNT(*) as cnt FROM commits WHERE substr(author_date, 1, 4) = '2026'",
        )
        assert "cnt" in result

    def test_file_change_ranking(self):
        result = _sql_query(
            self.conn,
            """SELECT cf.file_path, COUNT(*) as changes
               FROM commit_files cf
               GROUP BY cf.file_path
               ORDER BY changes DESC
               LIMIT 5""",
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
               LIMIT 5""",
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
               GROUP BY project_name""",
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
            self.conn, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        assert "sessions" in result
        assert "commits" in result

    def test_aggregate_on_empty_returns_zero(self):
        result = _sql_query(self.conn, "SELECT COUNT(*) as cnt FROM commits")
        assert "0" in result
