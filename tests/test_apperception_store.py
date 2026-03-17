"""Tests for ApperceptionStore and concern graph anchors — Batch 4.

Store tests mock Qdrant/embedding to avoid infrastructure dependencies.
Anchor tests verify self-band integration into the concern graph.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from shared.apperception import Apperception, ApperceptionStore


def _make_apperception(
    source: str = "correction",
    text: str = "test trigger",
    observation: str = "I notice correction: test",
    valence: float = -0.3,
    valence_target: str = "accuracy",
    cascade_depth: int = 7,
    action: str = "",
    reflection: str = "",
) -> Apperception:
    return Apperception(
        source=source,  # type: ignore[arg-type]
        trigger_text=text,
        cascade_depth=cascade_depth,
        observation=observation,
        valence=valence,
        valence_target=valence_target,
        action=action,
        reflection=reflection,
    )


class TestApperceptionStore:
    def test_add_and_pending_count(self):
        store = ApperceptionStore()
        assert store.pending_count == 0
        store.add(_make_apperception())
        assert store.pending_count == 1
        store.add(_make_apperception(text="another"))
        assert store.pending_count == 2

    def test_flush_clears_pending(self):
        """Flush clears pending list even when embedding fails."""
        store = ApperceptionStore()
        store.add(_make_apperception())
        store.add(_make_apperception(text="second"))

        with patch("shared.config.embed_batch_safe", return_value=None):
            flushed = store.flush()

        assert flushed == 0
        assert store.pending_count == 0

    def test_flush_empty_returns_zero(self):
        store = ApperceptionStore()
        assert store.flush() == 0

    def test_flush_with_vectors(self):
        """Flush upserts to Qdrant when embeddings succeed."""
        store = ApperceptionStore()
        store.add(_make_apperception())

        mock_qdrant = MagicMock()
        fake_vectors = [[0.1] * 768]

        with (
            patch("shared.config.embed_batch_safe", return_value=fake_vectors),
            patch("shared.config.get_qdrant", return_value=mock_qdrant),
        ):
            flushed = store.flush()

        assert flushed == 1
        mock_qdrant.upsert.assert_called_once()
        call_args = mock_qdrant.upsert.call_args
        assert call_args.kwargs["collection_name"] == "hapax-apperceptions"
        points = call_args.kwargs["points"]
        assert len(points) == 1
        assert points[0].payload["source"] == "correction"
        assert points[0].payload["valence"] == -0.3

    def test_flush_multiple_apperceptions(self):
        """Batch flush handles multiple apperceptions."""
        store = ApperceptionStore()
        for i in range(3):
            store.add(_make_apperception(text=f"trigger_{i}"))

        mock_qdrant = MagicMock()
        fake_vectors = [[0.1] * 768 for _ in range(3)]

        with (
            patch("shared.config.embed_batch_safe", return_value=fake_vectors),
            patch("shared.config.get_qdrant", return_value=mock_qdrant),
        ):
            flushed = store.flush()

        assert flushed == 3

    def test_flush_qdrant_error_returns_zero(self):
        """Qdrant failure returns 0, doesn't raise."""
        store = ApperceptionStore()
        store.add(_make_apperception())

        mock_qdrant = MagicMock()
        mock_qdrant.upsert.side_effect = Exception("connection refused")
        fake_vectors = [[0.1] * 768]

        with (
            patch("shared.config.embed_batch_safe", return_value=fake_vectors),
            patch("shared.config.get_qdrant", return_value=mock_qdrant),
        ):
            flushed = store.flush()

        assert flushed == 0

    def test_search_returns_payloads(self):
        """Search returns payload dicts from Qdrant results."""
        store = ApperceptionStore()

        mock_result = MagicMock()
        mock_result.payload = {"observation": "I notice correction", "valence": -0.3}

        mock_qdrant = MagicMock()
        mock_qdrant.search.return_value = [mock_result]

        with (
            patch("shared.config.embed_safe", return_value=[0.1] * 768),
            patch("shared.config.get_qdrant", return_value=mock_qdrant),
        ):
            results = store.search("accuracy issues")

        assert len(results) == 1
        assert results[0]["observation"] == "I notice correction"

    def test_search_embedding_failure_returns_empty(self):
        """Search returns empty list when embedding fails."""
        store = ApperceptionStore()
        with patch("shared.config.embed_safe", return_value=None):
            results = store.search("anything")
        assert results == []

    def test_ensure_collection_creates_when_missing(self):
        """ensure_collection creates collection when it doesn't exist."""
        mock_qdrant = MagicMock()
        mock_collection = MagicMock()
        mock_collection.name = "other-collection"
        mock_qdrant.get_collections.return_value.collections = [mock_collection]

        with patch("shared.config.get_qdrant", return_value=mock_qdrant):
            store = ApperceptionStore()
            store.ensure_collection()

        mock_qdrant.create_collection.assert_called_once()

    def test_ensure_collection_skips_when_exists(self):
        """ensure_collection is idempotent — skips if collection exists."""
        mock_qdrant = MagicMock()
        mock_collection = MagicMock()
        mock_collection.name = "hapax-apperceptions"
        mock_qdrant.get_collections.return_value.collections = [mock_collection]

        with patch("shared.config.get_qdrant", return_value=mock_qdrant):
            store = ApperceptionStore()
            store.ensure_collection()

        mock_qdrant.create_collection.assert_not_called()


class TestApperceptionAnchors:
    """Test concern graph anchors from self-band state."""

    def test_pending_actions_become_anchors(self, tmp_path):
        """Pending actions from cascade become high-weight concern anchors."""
        from agents.hapax_voice.salience.anchor_builder import _read_apperception_anchors

        data = {
            "self_model": {"dimensions": {}, "recent_observations": [], "coherence": 0.7},
            "pending_actions": ["Consider adjusting approach to temporal_prediction"],
            "timestamp": time.time(),
        }

        with patch(
            "agents.hapax_voice.salience.anchor_builder._APPERCEPTION_PATH",
            tmp_path / "self-band.json",
        ):
            (tmp_path / "self-band.json").write_text(json.dumps(data))
            anchors = _read_apperception_anchors()

        assert len(anchors) == 1
        assert anchors[0].source == "self"
        assert anchors[0].weight == 1.3
        assert "temporal_prediction" in anchors[0].text

    def test_low_confidence_dimensions_become_anchors(self, tmp_path):
        """Dimensions with confidence < 0.3 become concern anchors."""
        from agents.hapax_voice.salience.anchor_builder import _read_apperception_anchors

        data = {
            "self_model": {
                "dimensions": {
                    "accuracy": {
                        "name": "accuracy",
                        "confidence": 0.2,
                    },
                    "temporal_prediction": {
                        "name": "temporal_prediction",
                        "confidence": 0.7,
                    },
                },
                "recent_observations": [],
                "coherence": 0.5,
            },
            "pending_actions": [],
            "timestamp": time.time(),
        }

        with patch(
            "agents.hapax_voice.salience.anchor_builder._APPERCEPTION_PATH",
            tmp_path / "self-band.json",
        ):
            (tmp_path / "self-band.json").write_text(json.dumps(data))
            anchors = _read_apperception_anchors()

        assert len(anchors) == 1
        assert "accuracy" in anchors[0].text
        assert anchors[0].source == "self"

    def test_stale_data_returns_empty(self, tmp_path):
        """Stale apperception data (> 30s) returns no anchors."""
        from agents.hapax_voice.salience.anchor_builder import _read_apperception_anchors

        data = {
            "self_model": {"dimensions": {}},
            "pending_actions": ["something"],
            "timestamp": time.time() - 60,
        }

        with patch(
            "agents.hapax_voice.salience.anchor_builder._APPERCEPTION_PATH",
            tmp_path / "self-band.json",
        ):
            (tmp_path / "self-band.json").write_text(json.dumps(data))
            anchors = _read_apperception_anchors()

        assert len(anchors) == 0

    def test_missing_file_returns_empty(self):
        """Missing self-band file returns empty (graceful degradation)."""
        from agents.hapax_voice.salience.anchor_builder import _read_apperception_anchors

        with patch(
            "agents.hapax_voice.salience.anchor_builder._APPERCEPTION_PATH",
            Path("/nonexistent/path/self-band.json"),
        ):
            anchors = _read_apperception_anchors()

        assert len(anchors) == 0

    def test_build_anchors_includes_self(self, tmp_path):
        """build_anchors() includes self-band anchors when available."""
        from agents.hapax_voice.salience.anchor_builder import build_anchors

        data = {
            "self_model": {
                "dimensions": {
                    "accuracy": {"name": "accuracy", "confidence": 0.1},
                },
            },
            "pending_actions": ["adjust accuracy approach"],
            "timestamp": time.time(),
        }

        with (
            patch(
                "agents.hapax_voice.salience.anchor_builder._APPERCEPTION_PATH",
                tmp_path / "self-band.json",
            ),
            patch(
                "agents.hapax_voice.salience.anchor_builder._TEMPORAL_PATH",
                Path("/nonexistent/temporal"),
            ),
        ):
            (tmp_path / "self-band.json").write_text(json.dumps(data))
            anchors = build_anchors()

        self_anchors = [a for a in anchors if a.source == "self"]
        assert len(self_anchors) == 2  # 1 pending action + 1 low-confidence dimension
