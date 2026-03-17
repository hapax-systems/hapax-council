"""Tests for pattern consolidation (WS3 Level 3)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from shared.pattern_consolidation import (
    COLLECTION,
    ConsolidationResult,
    ExtractedPattern,
    Pattern,
    PatternStore,
    run_consolidation,
)


def _mock_qdrant() -> MagicMock:
    client = MagicMock()
    client.get_collections.return_value = SimpleNamespace(
        collections=[SimpleNamespace(name=COLLECTION)]
    )
    return client


def _mock_embed(text: str, prefix: str = "search_query") -> list[float]:
    h = hash(text) % 1000
    return [float(h % (i + 1)) / (i + 1) for i in range(768)]


# ── Pattern Model Tests ──────────────────────────────────────────────────────


class TestPattern:
    def test_pattern_text(self):
        p = Pattern(condition="coding AND flow falling", prediction="break within 5 min")
        assert p.pattern_text == "IF coding AND flow falling THEN break within 5 min"

    def test_evidence_ratio_no_data(self):
        p = Pattern(condition="a", prediction="b")
        assert p.evidence_ratio == 0.5

    def test_evidence_ratio_all_supporting(self):
        p = Pattern(condition="a", prediction="b", supporting_episodes=10, contradicting_episodes=0)
        assert p.evidence_ratio == 1.0

    def test_evidence_ratio_mixed(self):
        p = Pattern(condition="a", prediction="b", supporting_episodes=3, contradicting_episodes=1)
        assert p.evidence_ratio == 0.75

    def test_confirm_increases_confidence(self):
        p = Pattern(condition="a", prediction="b", confidence=0.5)
        p.confirm()
        assert p.confidence == 0.52
        assert p.supporting_episodes == 1

    def test_confirm_capped_at_095(self):
        p = Pattern(condition="a", prediction="b", confidence=0.95)
        p.confirm()
        assert p.confidence == 0.95

    def test_contradict_decreases_confidence(self):
        p = Pattern(condition="a", prediction="b", confidence=0.5)
        p.contradict()
        assert p.confidence == 0.45
        assert p.contradicting_episodes == 1

    def test_contradict_floored_at_005(self):
        p = Pattern(condition="a", prediction="b", confidence=0.05)
        p.contradict()
        assert p.confidence == 0.05

    def test_decay_no_effect_recent(self):
        p = Pattern(condition="a", prediction="b", confidence=0.8)
        p.decay(days_since_confirmed=10)
        assert p.confidence == 0.8
        assert p.active is True

    def test_decay_reduces_confidence_after_30d(self):
        p = Pattern(condition="a", prediction="b", confidence=0.8)
        p.decay(days_since_confirmed=35)
        assert p.confidence < 0.8
        assert p.active is True

    def test_decay_deactivates_after_60d_low_confidence(self):
        p = Pattern(condition="a", prediction="b", confidence=0.08)
        p.decay(days_since_confirmed=65)
        assert p.active is False


# ── Pattern Store Tests ──────────────────────────────────────────────────────


class TestPatternStore:
    def test_ensure_collection_creates_when_missing(self):
        client = MagicMock()
        client.get_collections.return_value = SimpleNamespace(collections=[])
        store = PatternStore(client=client)
        store.ensure_collection()
        client.create_collection.assert_called_once()

    def test_ensure_collection_skips_when_exists(self):
        client = _mock_qdrant()
        store = PatternStore(client=client)
        store.ensure_collection()
        client.create_collection.assert_not_called()

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_record_returns_id(self, mock_embed):
        client = _mock_qdrant()
        store = PatternStore(client=client)
        p = Pattern(condition="coding", prediction="flow likely")
        pid = store.record(p)
        assert pid.startswith("pat-")
        client.upsert.assert_called_once()

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_record_sets_timestamps(self, mock_embed):
        client = _mock_qdrant()
        store = PatternStore(client=client)
        p = Pattern(condition="a", prediction="b")
        store.record(p)
        assert p.created_at > 0
        assert p.updated_at > 0

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_returns_matches(self, mock_embed):
        client = _mock_qdrant()
        mock_point = SimpleNamespace(
            payload=Pattern(
                condition="coding AND evening",
                prediction="flow likely",
                confidence=0.7,
                active=True,
            ).model_dump(),
            score=0.85,
        )
        client.query_points.return_value = SimpleNamespace(points=[mock_point])
        store = PatternStore(client=client)
        matches = store.search("coding at night")
        assert len(matches) == 1
        assert matches[0].score == 0.85
        assert matches[0].pattern.condition == "coding AND evening"

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_filters_low_score(self, mock_embed):
        client = _mock_qdrant()
        mock_point = SimpleNamespace(
            payload=Pattern(condition="a", prediction="b").model_dump(),
            score=0.15,
        )
        client.query_points.return_value = SimpleNamespace(points=[mock_point])
        store = PatternStore(client=client)
        assert len(store.search("anything", min_score=0.3)) == 0

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_with_dimension_filter(self, mock_embed):
        client = _mock_qdrant()
        client.query_points.return_value = SimpleNamespace(points=[])
        store = PatternStore(client=client)
        store.search("test", dimension="activity")
        call_kwargs = client.query_points.call_args
        assert call_kwargs.kwargs.get("query_filter") is not None

    def test_get_active(self):
        client = _mock_qdrant()
        mock_point = SimpleNamespace(
            payload=Pattern(
                condition="a", prediction="b", active=True
            ).model_dump()
        )
        client.scroll.return_value = ([mock_point], None)
        store = PatternStore(client=client)
        patterns = store.get_active()
        assert len(patterns) == 1

    def test_count(self):
        client = _mock_qdrant()
        client.get_collection.return_value = SimpleNamespace(points_count=7)
        store = PatternStore(client=client)
        assert store.count() == 7


# ── Consolidation Runner Tests ───────────────────────────────────────────────


class TestConsolidationRunner:
    @pytest.mark.asyncio
    @patch("shared.config.embed", side_effect=_mock_embed)
    @patch("shared.pattern_consolidation.extract_patterns")
    async def test_run_consolidation_stores_patterns(self, mock_extract, mock_embed):
        """Consolidation stores extracted patterns."""
        mock_extract.return_value = ConsolidationResult(
            patterns=[
                ExtractedPattern(
                    condition="coding AND hour >= 22",
                    prediction="flow state likely active",
                    dimension="flow",
                    confidence=0.7,
                )
            ],
            summary="Found 1 pattern",
        )

        # Mock stores
        episode_store = MagicMock()
        episode_store.get_all.return_value = []

        correction_store = MagicMock()
        correction_store.get_all.return_value = []

        client = _mock_qdrant()
        client.scroll.return_value = ([], None)
        client.get_collection.return_value = SimpleNamespace(points_count=1)
        pattern_store = PatternStore(client=client)

        result = await run_consolidation(episode_store, correction_store, pattern_store)
        assert len(result.patterns) == 1
        assert result.patterns[0].condition == "coding AND hour >= 22"
        # Pattern should have been stored
        client.upsert.assert_called()

    @pytest.mark.asyncio
    @patch("shared.config.embed", side_effect=_mock_embed)
    @patch("shared.pattern_consolidation.extract_patterns")
    async def test_run_consolidation_empty(self, mock_extract, mock_embed):
        """No patterns extracted → nothing stored."""
        mock_extract.return_value = ConsolidationResult(patterns=[], summary="No patterns")

        episode_store = MagicMock()
        episode_store.get_all.return_value = []

        correction_store = MagicMock()
        correction_store.get_all.return_value = []

        client = _mock_qdrant()
        client.scroll.return_value = ([], None)
        client.get_collection.return_value = SimpleNamespace(points_count=0)
        pattern_store = PatternStore(client=client)

        result = await run_consolidation(episode_store, correction_store, pattern_store)
        assert len(result.patterns) == 0


# ── Extracted Pattern Model ──────────────────────────────────────────────────


class TestExtractedPattern:
    def test_basic(self):
        ep = ExtractedPattern(
            condition="coding at night",
            prediction="flow likely",
            dimension="flow",
            confidence=0.7,
            reasoning="seen in 5 episodes",
        )
        assert ep.confidence == 0.7
