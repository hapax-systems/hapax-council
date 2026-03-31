"""Tests for affordance pipeline retrieval and keyword fallback."""

from unittest.mock import MagicMock, patch

from shared.affordance_pipeline import AffordancePipeline
from shared.impingement import Impingement, ImpingementType


def _make_impingement(**kwargs) -> Impingement:
    defaults = {
        "timestamp": 1.0,
        "source": "test",
        "type": ImpingementType.ABSOLUTE_THRESHOLD,
        "strength": 0.8,
        "content": {"metric": "test_metric"},
    }
    defaults.update(kwargs)
    return Impingement(**defaults)


class TestFallbackKeywordMatch:
    def test_exact_name_match(self):
        pipeline = AffordancePipeline()
        imp = _make_impingement(content={"metric": "fortress_governance"})
        mock_point = MagicMock()
        mock_point.payload = {
            "capability_name": "fortress_governance",
            "description": "Fortress governance capability",
            "available": True,
        }
        with patch("shared.config.get_qdrant") as mock_qdrant:
            mock_client = MagicMock()
            mock_client.scroll.return_value = ([mock_point], None)
            mock_qdrant.return_value = mock_client
            result = pipeline._fallback_keyword_match(imp)
        assert len(result) >= 1
        assert result[0].capability_name == "fortress_governance"

    def test_no_match_returns_empty(self):
        pipeline = AffordancePipeline()
        imp = _make_impingement(content={"metric": "nonexistent_xyz"})
        mock_point = MagicMock()
        mock_point.payload = {
            "capability_name": "something_else",
            "description": "Unrelated capability",
            "available": True,
        }
        with patch("shared.config.get_qdrant") as mock_qdrant:
            mock_client = MagicMock()
            mock_client.scroll.return_value = ([mock_point], None)
            mock_qdrant.return_value = mock_client
            result = pipeline._fallback_keyword_match(imp)
        assert len(result) == 0

    def test_qdrant_down_returns_empty(self):
        pipeline = AffordancePipeline()
        imp = _make_impingement()
        with patch("shared.config.get_qdrant", side_effect=Exception("refused")):
            result = pipeline._fallback_keyword_match(imp)
        assert result == []


class TestRetrieve:
    def test_happy_path(self):
        pipeline = AffordancePipeline()
        embedding = [0.1] * 768
        mock_hit = MagicMock()
        mock_hit.score = 0.9
        mock_hit.payload = {"capability_name": "speech_production", "available": True}
        mock_result = MagicMock()
        mock_result.points = [mock_hit]
        with patch("shared.config.get_qdrant") as mock_qdrant:
            mock_client = MagicMock()
            mock_client.query_points.return_value = mock_result
            mock_qdrant.return_value = mock_client
            result = pipeline._retrieve(embedding, top_k=5)
        assert len(result) == 1
        assert result[0].capability_name == "speech_production"

    def test_qdrant_timeout_returns_empty(self):
        pipeline = AffordancePipeline()
        embedding = [0.1] * 768
        with patch("shared.config.get_qdrant") as mock_qdrant:
            mock_client = MagicMock()
            mock_client.query_points.side_effect = Exception("Timeout")
            mock_qdrant.return_value = mock_client
            result = pipeline._retrieve(embedding, top_k=5)
        assert result == []

    def test_empty_collection(self):
        pipeline = AffordancePipeline()
        embedding = [0.1] * 768
        mock_result = MagicMock()
        mock_result.points = []
        with patch("shared.config.get_qdrant") as mock_qdrant:
            mock_client = MagicMock()
            mock_client.query_points.return_value = mock_result
            mock_qdrant.return_value = mock_client
            result = pipeline._retrieve(embedding, top_k=5)
        assert result == []


class TestSelectEndToEnd:
    def test_interrupt_token_bypasses_retrieval(self):
        pipeline = AffordancePipeline()
        pipeline.register_interrupt("population_critical", "fortress_governance", "fortress")
        imp = _make_impingement(interrupt_token="population_critical")
        candidates = pipeline.select(imp)
        assert any(c.capability_name == "fortress_governance" for c in candidates)
