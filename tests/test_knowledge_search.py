"""Tests for shared.knowledge_search — Qdrant search & artifact reads."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from shared.knowledge_search import (
    get_collection_stats,
    get_operator_goals,
    read_briefing,
    read_digest,
    read_scout_report,
    search_documents,
    search_profile,
)


class TestSearchDocuments:
    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed")
    def test_returns_formatted_results(self, mock_embed, mock_qdrant):
        mock_embed.return_value = [0.1] * 768
        mock_point = MagicMock()
        mock_point.payload = {
            "text": "Meeting notes from Monday",
            "source": "/path/to/file.md",
            "source_service": "obsidian",
            "ingested_at": 1710000000.0,
        }
        mock_point.score = 0.92
        mock_qdrant.return_value.query_points.return_value.points = [mock_point]

        result = search_documents("meeting notes")
        assert "Meeting notes from Monday" in result
        assert "obsidian" in result
        assert "0.92" in result

    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed")
    def test_source_service_filter(self, mock_embed, mock_qdrant):
        mock_embed.return_value = [0.1] * 768
        mock_qdrant.return_value.query_points.return_value.points = []

        search_documents("test", source_service="gmail")
        call_kwargs = mock_qdrant.return_value.query_points.call_args
        query_filter = call_kwargs.kwargs.get("query_filter") or call_kwargs[1].get("query_filter")
        assert query_filter is not None

    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed")
    def test_excludes_retrieval_ineligible_by_default(self, mock_embed, mock_qdrant):
        mock_embed.return_value = [0.1] * 768
        mock_qdrant.return_value.query_points.return_value.points = []

        search_documents("test")
        call_kwargs = mock_qdrant.return_value.query_points.call_args
        query_filter = call_kwargs.kwargs.get("query_filter") or call_kwargs[1].get("query_filter")

        assert query_filter is not None
        assert query_filter.must_not
        exclusion = query_filter.must_not[0]
        assert exclusion.key == "retrieval_eligible"
        assert exclusion.match.value is False

    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed")
    def test_inventory_search_can_include_retrieval_ineligible(self, mock_embed, mock_qdrant):
        mock_embed.return_value = [0.1] * 768
        mock_qdrant.return_value.query_points.return_value.points = []

        search_documents("test", include_inventory=True)
        call_kwargs = mock_qdrant.return_value.query_points.call_args
        query_filter = call_kwargs.kwargs.get("query_filter") or call_kwargs[1].get("query_filter")

        assert query_filter is None

    @patch("shared.knowledge_search.get_qdrant", side_effect=Exception("Connection refused"))
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_unavailable_returns_message(self, mock_embed, mock_qdrant):
        result = search_documents("test")
        assert "error" in result.lower() or "not available" in result.lower()


class TestSearchProfile:
    @patch("shared.knowledge_search.ProfileStore")
    def test_returns_formatted_facts(self, mock_store_cls):
        mock_store = mock_store_cls.return_value
        mock_store.search.return_value = [
            {
                "dimension": "tool_usage",
                "key": "preferred_editor",
                "value": "Claude Code",
                "confidence": 0.9,
                "score": 0.88,
            },
        ]
        result = search_profile("tool preferences")
        assert "tool_usage" in result
        assert "Claude Code" in result
        assert "0.9" in result

    @patch("shared.knowledge_search.ProfileStore")
    def test_dimension_filter_passed(self, mock_store_cls):
        mock_store = mock_store_cls.return_value
        mock_store.search.return_value = []
        search_profile("test", dimension="work_patterns")
        mock_store.search.assert_called_once_with("test", dimension="work_patterns", limit=5)

    @patch("shared.knowledge_search.ProfileStore", side_effect=Exception("Connection refused"))
    def test_unavailable_returns_message(self, mock_store_cls):
        result = search_profile("test")
        assert "error" in result.lower()


class TestReadBriefing:
    def test_reads_briefing_file(self, tmp_path):
        briefing = tmp_path / "briefing.json"
        briefing.write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-10T07:00:00Z",
                    "headline": "All systems nominal",
                    "action_items": [{"priority": "high", "action": "Review drift"}],
                }
            )
        )
        result = read_briefing(tmp_path)
        assert "All systems nominal" in result
        assert "Review drift" in result

    def test_missing_file(self, tmp_path):
        result = read_briefing(tmp_path)
        assert "not available" in result.lower() or "not found" in result.lower()


class TestReadDigest:
    def test_reads_digest_file(self, tmp_path):
        digest = tmp_path / "digest.json"
        digest.write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-10T06:45:00Z",
                    "headline": "5 new documents ingested",
                    "notable_items": [{"title": "API design doc", "source": "gdrive"}],
                }
            )
        )
        result = read_digest(tmp_path)
        assert "5 new documents" in result
        assert "API design doc" in result

    def test_missing_file(self, tmp_path):
        result = read_digest(tmp_path)
        assert "not available" in result.lower() or "not found" in result.lower()


class TestReadScoutReport:
    def test_reads_scout_file(self, tmp_path):
        scout = tmp_path / "scout-report.json"
        scout.write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-05T10:00:00Z",
                    "recommendations": [
                        {"component": "embeddings", "tier": "evaluate", "summary": "Try new model"}
                    ],
                }
            )
        )
        result = read_scout_report(tmp_path)
        assert "embeddings" in result
        assert "evaluate" in result

    def test_missing_file(self, tmp_path):
        result = read_scout_report(tmp_path)
        assert "not available" in result.lower() or "not found" in result.lower()


class TestGetOperatorGoals:
    def test_reads_goals_from_operator(self, tmp_path):
        operator = tmp_path / "operator.json"
        operator.write_text(
            json.dumps(
                {
                    "goals": {
                        "primary": [
                            {"id": "g1", "name": "Ship cockpit", "status": "active"},
                        ],
                        "secondary": [
                            {"id": "g2", "name": "Voice daemon stability", "status": "active"},
                        ],
                    },
                }
            )
        )
        result = get_operator_goals(tmp_path)
        assert "Ship cockpit" in result
        assert "Voice daemon" in result

    def test_missing_file(self, tmp_path):
        result = get_operator_goals(tmp_path)
        assert "not available" in result.lower() or "not found" in result.lower()


class TestGetCollectionStats:
    @patch("shared.ops_live.get_qdrant")
    def test_returns_all_collections(self, mock_qdrant):
        coll1 = MagicMock()
        coll1.name = "documents"
        coll2 = MagicMock()
        coll2.name = "profile-facts"
        mock_qdrant.return_value.get_collections.return_value.collections = [coll1, coll2]
        mock_qdrant.return_value.count.return_value.count = 500
        result = get_collection_stats()
        assert "documents" in result
        assert "profile-facts" in result
        assert "500" in result


class TestReadBriefingEmptyState:
    def test_missing_briefing_includes_schedule(self, tmp_path):
        result = read_briefing(tmp_path)
        assert "07:00" in result or "daily" in result.lower()
        assert "briefing" in result.lower()


class TestReadDigestEmptyState:
    def test_missing_digest_includes_schedule(self, tmp_path):
        result = read_digest(tmp_path)
        assert "06:45" in result or "daily" in result.lower()
        assert "digest" in result.lower()


class TestReadScoutEmptyState:
    def test_missing_scout_includes_schedule(self, tmp_path):
        result = read_scout_report(tmp_path)
        assert "weekly" in result.lower() or "wednesday" in result.lower()


class TestGetGoalsEmptyState:
    def test_missing_operator_includes_explanation(self, tmp_path):
        result = get_operator_goals(tmp_path)
        assert "operator" in result.lower()
        assert "profile" in result.lower() or "6 hours" in result


class TestSearchDocumentsEmptyResults:
    @patch("shared.knowledge_search.get_qdrant")
    @patch("shared.knowledge_search.embed", return_value=[0.1] * 768)
    def test_empty_results_return_no_documents_message(self, mock_embed, mock_qdrant):
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.points = []
        mock_client.query_points.return_value = mock_result
        mock_qdrant.return_value = mock_client

        result = search_documents("test query")
        assert "No documents found" in result


class TestSearchProfileNoMatches:
    @patch("shared.knowledge_search.ProfileStore")
    def test_no_matching_facts(self, mock_store_cls):
        mock_store = MagicMock()
        mock_store.search.return_value = []
        mock_store_cls.return_value = mock_store

        result = search_profile("nonexistent topic", dimension="work_patterns")
        assert "No profile facts found" in result
        assert "work_patterns" in result
