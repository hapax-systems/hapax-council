"""Dedicated empty-state assertions across all query agents."""

from __future__ import annotations

from agents.dev_story.query import _sql_query
from agents.dev_story.query import build_system_prompt as dev_story_prompt
from agents.knowledge.query import build_system_prompt as knowledge_prompt
from agents.system_ops.query import build_system_prompt as system_ops_prompt
from shared.knowledge_search import (
    get_operator_goals,
    read_briefing,
    read_digest,
    read_scout_report,
)
from shared.ops_db import build_ops_db, run_sql
from shared.ops_live import get_infra_snapshot, get_manifest_section
from tests.query_integration._helpers import (
    EMPTY_DEV_STORY_DB,
    EMPTY_PROFILES,
    open_dev_story_db,
    skip_if_missing,
)


class TestDevStoryEmptyStateContract:
    """Verify dev-story handles fresh deployment gracefully."""

    def test_prompt_has_empty_state_guidance(self):
        prompt = dev_story_prompt()
        assert "When Data is Unavailable" in prompt

    def test_empty_db_all_tables_queryable(self):
        skip_if_missing(EMPTY_DEV_STORY_DB)
        conn = open_dev_story_db(EMPTY_DEV_STORY_DB)
        for table in ("sessions", "commits", "messages", "correlations"):
            result = _sql_query(conn, f"SELECT COUNT(*) FROM {table}")
            assert "0" in result
        conn.close()


class TestSystemOpsEmptyStateContract:
    """Verify system-ops handles fresh deployment gracefully."""

    def test_prompt_has_empty_state_guidance(self):
        prompt = system_ops_prompt()
        assert "When Data is Unavailable" in prompt

    def test_empty_ops_db_no_crashes(self):
        skip_if_missing(EMPTY_PROFILES, allow_empty=True)
        conn = build_ops_db(EMPTY_PROFILES)
        for table in ("health_runs", "drift_items", "drift_runs", "digest_runs", "knowledge_maint"):
            result = run_sql(conn, f"SELECT * FROM {table}")
            assert result == "No results."

    def test_infra_snapshot_missing_gracefully(self):
        skip_if_missing(EMPTY_PROFILES, allow_empty=True)
        result = get_infra_snapshot(EMPTY_PROFILES)
        assert "not" in result.lower()  # "not found" or "not available"

    def test_manifest_missing_gracefully(self):
        skip_if_missing(EMPTY_PROFILES, allow_empty=True)
        result = get_manifest_section(EMPTY_PROFILES, "docker")
        assert "not found" in result.lower()


class TestKnowledgeEmptyStateContract:
    """Verify knowledge handles fresh deployment gracefully."""

    def test_prompt_has_empty_state_guidance(self):
        prompt = knowledge_prompt()
        assert "When Data is Unavailable" in prompt

    def test_all_artifact_reads_graceful(self):
        skip_if_missing(EMPTY_PROFILES, allow_empty=True)
        for fn, name in [
            (read_briefing, "briefing"),
            (read_digest, "digest"),
            (read_scout_report, "scout"),
            (get_operator_goals, "goals"),
        ]:
            result = fn(EMPTY_PROFILES)
            assert "not available" in result.lower(), f"{name} should say 'not available'"
            assert len(result) > 30, (
                f"{name} empty message too short — should include schedule info"
            )
