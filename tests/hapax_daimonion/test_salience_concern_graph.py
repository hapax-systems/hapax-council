"""Tests for the salience concern graph."""

from __future__ import annotations

import numpy as np

from agents.hapax_daimonion.salience.concern_graph import ConcernAnchor, ConcernGraph


class TestConcernGraph:
    def _make_graph(self, dim: int = 256) -> ConcernGraph:
        return ConcernGraph(dim=dim)

    def test_refresh_with_anchors(self) -> None:
        graph = self._make_graph()
        anchors = [
            ConcernAnchor(text="coding", source="workspace", weight=1.0),
            ConcernAnchor(text="meeting", source="calendar", weight=0.8),
            ConcernAnchor(text="lunch", source="temporal", weight=0.5),
        ]
        embeddings = np.random.randn(3, 256).astype(np.float32)
        graph.refresh(anchors, embeddings)
        assert graph.anchor_count == 3

    def test_query_returns_float_in_range(self) -> None:
        graph = self._make_graph()
        anchors = [ConcernAnchor(text="test", source="test", weight=1.0)]
        embeddings = np.random.randn(1, 256).astype(np.float32)
        graph.refresh(anchors, embeddings)
        result = graph.query(np.random.randn(256).astype(np.float32))
        assert 0.0 <= result <= 1.0

    def test_query_empty_graph(self) -> None:
        graph = self._make_graph()
        result = graph.query(np.random.randn(256).astype(np.float32))
        assert result == 0.0

    def test_novelty_returns_float_in_range(self) -> None:
        graph = self._make_graph()
        result = graph.novelty(np.random.randn(256).astype(np.float32))
        assert 0.0 <= result <= 1.0

    def test_novelty_zero_vector(self) -> None:
        graph = self._make_graph()
        result = graph.novelty(np.zeros(256, dtype=np.float32))
        assert result == 0.5

    def test_refresh_empty_clears_anchors(self) -> None:
        graph = self._make_graph()
        anchors = [ConcernAnchor(text="test", source="test", weight=1.0)]
        embeddings = np.random.randn(1, 256).astype(np.float32)
        graph.refresh(anchors, embeddings)
        assert graph.anchor_count == 1

        graph.refresh([], np.zeros((0, 256), dtype=np.float32))
        assert graph.anchor_count == 0

    def test_add_recent_utterance(self) -> None:
        graph = self._make_graph()
        vec = np.random.randn(256).astype(np.float32)
        graph.add_recent_utterance(vec)
        assert len(graph._recent_utterances) == 1

    def test_get_anchor_texts(self) -> None:
        graph = self._make_graph()
        anchors = [
            ConcernAnchor(text="coding", source="workspace"),
            ConcernAnchor(text="music", source="studio"),
        ]
        embeddings = np.random.randn(2, 256).astype(np.float32)
        graph.refresh(anchors, embeddings)
        assert graph.get_anchor_texts() == ["coding", "music"]
