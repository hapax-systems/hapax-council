"""Integration tests for knowledge query agent against real data."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.knowledge_search import (
    get_operator_goals,
    read_briefing,
    read_digest,
    read_scout_report,
    search_documents,
    search_profile,
)
from tests.query_integration._helpers import (
    EMPTY_PROFILES,
    POPULATED_PROFILES,
    skip_if_missing,
)

# ── Populated state — File reads ─────────────────────────────────────────────


class TestKnowledgeFileReads:
    def setup_method(self):
        skip_if_missing(POPULATED_PROFILES)

    def test_briefing_has_content(self):
        result = read_briefing(POPULATED_PROFILES)
        # Either has content or says not available
        assert len(result) > 20

    def test_briefing_structure(self):
        result = read_briefing(POPULATED_PROFILES)
        if "not available" not in result.lower():
            assert "Briefing" in result or "Headline" in result

    def test_digest_has_content(self):
        result = read_digest(POPULATED_PROFILES)
        assert len(result) > 20

    def test_scout_report_has_content(self):
        result = read_scout_report(POPULATED_PROFILES)
        assert len(result) > 20

    def test_operator_goals_has_content(self):
        result = get_operator_goals(POPULATED_PROFILES)
        assert len(result) > 20


# ── Populated state — Search (mocked at Qdrant client level) ─────────────────


class TestKnowledgeSearchFilters:
    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_source_service_filter_construction(self, mock_embed, mock_qdrant):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.points = []
        mock_client.query_points.return_value = mock_result
        mock_qdrant.return_value = mock_client

        search_documents("test", source_service="gmail")

        call_args = mock_client.query_points.call_args
        query_filter = call_args.kwargs.get("query_filter") or call_args[1].get("query_filter")
        assert query_filter is not None
        # Filter should contain gmail condition
        conditions = query_filter.must
        assert any("gmail" in str(c) for c in conditions)

    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_days_back_filter_construction(self, mock_embed, mock_qdrant):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.points = []
        mock_client.query_points.return_value = mock_result
        mock_qdrant.return_value = mock_client

        search_documents("test", days_back=7)

        call_args = mock_client.query_points.call_args
        query_filter = call_args.kwargs.get("query_filter") or call_args[1].get("query_filter")
        assert query_filter is not None
        # Should have a range condition on ingested_at
        conditions = query_filter.must
        assert len(conditions) == 1

    @patch("shared.knowledge_search.ProfileStore")
    def test_profile_dimension_filter(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.search.return_value = []
        mock_store_cls.return_value = mock_store

        search_profile("work habits", dimension="work_patterns")

        mock_store.search.assert_called_once_with("work habits", dimension="work_patterns", limit=5)


# ── Empty state ──────────────────────────────────────────────────────────────


class TestKnowledgeEmptyState:
    def setup_method(self):
        skip_if_missing(EMPTY_PROFILES, allow_empty=True)

    def test_briefing_missing_includes_schedule(self):
        result = read_briefing(EMPTY_PROFILES)
        assert "not available" in result.lower()
        assert "07:00" in result or "daily" in result.lower()

    def test_digest_missing_includes_schedule(self):
        result = read_digest(EMPTY_PROFILES)
        assert "not available" in result.lower()
        assert "06:45" in result or "daily" in result.lower()

    def test_scout_missing_includes_schedule(self):
        result = read_scout_report(EMPTY_PROFILES)
        assert "not available" in result.lower()
        assert "weekly" in result.lower()

    def test_goals_missing_includes_explanation(self):
        result = get_operator_goals(EMPTY_PROFILES)
        assert "not available" in result.lower()


class TestKnowledgeQdrantErrors:
    @patch("shared.knowledge_search.get_qdrant", side_effect=ConnectionError("Connection refused"))
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_qdrant_down_returns_error_message(self, mock_embed, mock_qdrant):
        result = search_documents("test query")
        assert "error" in result.lower()
        assert "Connection refused" in result
