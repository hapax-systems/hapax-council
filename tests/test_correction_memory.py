"""Tests for correction memory (WS3 Level 1)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from shared.correction_memory import (
    COLLECTION,
    Correction,
    CorrectionMatch,
    CorrectionStore,
    check_for_corrections,
)


def _mock_qdrant() -> MagicMock:
    """Create a mock Qdrant client with basic collection support."""
    client = MagicMock()
    client.get_collections.return_value = SimpleNamespace(
        collections=[SimpleNamespace(name=COLLECTION)]
    )
    return client


def _mock_embed(text: str, prefix: str = "search_query") -> list[float]:
    """Deterministic fake embedding for testing."""
    # Simple hash-based fake embedding
    h = hash(text) % 1000
    return [float(h % (i + 1)) / (i + 1) for i in range(768)]


class TestCorrectionModel:
    def test_correction_text(self):
        c = Correction(
            dimension="activity",
            original_value="coding",
            corrected_value="writing",
            context="was in Obsidian",
            activity="coding",
        )
        text = c.correction_text
        assert "activity" in text
        assert "coding → writing" in text
        assert "Obsidian" in text
        assert "during: coding" in text

    def test_correction_text_minimal(self):
        c = Correction(
            dimension="flow",
            original_value="active",
            corrected_value="idle",
        )
        text = c.correction_text
        assert "flow: active → idle" in text

    def test_correction_id_auto_generated(self):
        c = Correction(dimension="activity", original_value="a", corrected_value="b")
        assert c.id == ""  # not yet generated

    def test_correction_match(self):
        c = Correction(dimension="activity", original_value="a", corrected_value="b")
        m = CorrectionMatch(correction=c, score=0.85)
        assert m.score == 0.85


class TestCorrectionStore:
    def test_ensure_collection_creates_when_missing(self):
        client = MagicMock()
        client.get_collections.return_value = SimpleNamespace(collections=[])
        store = CorrectionStore(client=client)
        store.ensure_collection()
        client.create_collection.assert_called_once()

    def test_ensure_collection_skips_when_exists(self):
        client = _mock_qdrant()
        store = CorrectionStore(client=client)
        store.ensure_collection()
        client.create_collection.assert_not_called()

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_record_returns_id(self, mock_embed):
        client = _mock_qdrant()
        store = CorrectionStore(client=client)
        correction = Correction(
            dimension="activity",
            original_value="coding",
            corrected_value="writing",
        )
        cid = store.record(correction)
        assert cid.startswith("corr-")
        client.upsert.assert_called_once()
        # Verify the upsert was called with correct collection
        call_args = client.upsert.call_args
        assert call_args[0][0] == COLLECTION

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_record_sets_timestamp(self, mock_embed):
        client = _mock_qdrant()
        store = CorrectionStore(client=client)
        correction = Correction(
            dimension="flow",
            original_value="active",
            corrected_value="idle",
        )
        store.record(correction)
        assert correction.timestamp > 0

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_record_preserves_existing_id(self, mock_embed):
        client = _mock_qdrant()
        store = CorrectionStore(client=client)
        correction = Correction(
            id="my-custom-id",
            dimension="activity",
            original_value="a",
            corrected_value="b",
        )
        cid = store.record(correction)
        assert cid == "my-custom-id"

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_returns_matches(self, mock_embed):
        client = _mock_qdrant()
        # Mock query_points response
        mock_point = SimpleNamespace(
            payload={
                "dimension": "activity",
                "original_value": "coding",
                "corrected_value": "writing",
                "context": "was in Obsidian",
                "timestamp": time.time(),
                "id": "corr-abc123",
                "flow_score": 0.0,
                "activity": "coding",
                "hour": 14,
                "applied_count": 0,
                "last_applied": 0.0,
            },
            score=0.85,
        )
        client.query_points.return_value = SimpleNamespace(points=[mock_point])
        store = CorrectionStore(client=client)
        matches = store.search("activity when using Obsidian")
        assert len(matches) == 1
        assert matches[0].score == 0.85
        assert matches[0].correction.corrected_value == "writing"

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_filters_low_score(self, mock_embed):
        client = _mock_qdrant()
        mock_point = SimpleNamespace(
            payload={
                "dimension": "activity",
                "original_value": "a",
                "corrected_value": "b",
                "timestamp": 0,
                "id": "",
                "context": "",
                "flow_score": 0.0,
                "activity": "",
                "hour": 0,
                "applied_count": 0,
                "last_applied": 0.0,
            },
            score=0.15,
        )
        client.query_points.return_value = SimpleNamespace(points=[mock_point])
        store = CorrectionStore(client=client)
        matches = store.search("anything", min_score=0.3)
        assert len(matches) == 0

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_with_dimension_filter(self, mock_embed):
        client = _mock_qdrant()
        client.query_points.return_value = SimpleNamespace(points=[])
        store = CorrectionStore(client=client)
        store.search("test", dimension="flow")
        # Verify filter was passed
        call_args = client.query_points.call_args
        assert call_args.kwargs.get("query_filter") is not None or (len(call_args[1]) > 0)

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_search_for_dimension(self, mock_embed):
        client = _mock_qdrant()
        client.query_points.return_value = SimpleNamespace(points=[])
        store = CorrectionStore(client=client)
        store.search_for_dimension("activity", "coding", context="in VS Code")
        client.query_points.assert_called_once()

    def test_get_all(self):
        client = _mock_qdrant()
        mock_point = SimpleNamespace(
            payload={
                "dimension": "activity",
                "original_value": "a",
                "corrected_value": "b",
                "timestamp": 0,
                "id": "c1",
                "context": "",
                "flow_score": 0.0,
                "activity": "",
                "hour": 0,
                "applied_count": 0,
                "last_applied": 0.0,
            }
        )
        client.scroll.return_value = ([mock_point], None)
        store = CorrectionStore(client=client)
        all_corrections = store.get_all()
        assert len(all_corrections) == 1

    def test_count(self):
        client = _mock_qdrant()
        client.get_collection.return_value = SimpleNamespace(points_count=42)
        store = CorrectionStore(client=client)
        assert store.count() == 42


class TestCheckForCorrections:
    def test_no_file_returns_none(self):
        client = _mock_qdrant()
        store = CorrectionStore(client=client)
        with patch("shared.correction_memory.CORRECTION_INTAKE_PATH", Path("/nonexistent")):
            result = check_for_corrections(store, {"production_activity": "coding"})
        assert result is None

    @patch("shared.config.embed", side_effect=_mock_embed)
    def test_correction_recorded(self, mock_embed, tmp_path: Path):
        client = _mock_qdrant()
        store = CorrectionStore(client=client)

        correction_file = tmp_path / "correction.json"
        correction_file.write_text(
            json.dumps(
                {
                    "label": "writing",
                    "detail": "in Obsidian",
                    "timestamp": time.time(),
                    "ttl_s": 1800,
                }
            )
        )

        with patch("shared.correction_memory.CORRECTION_INTAKE_PATH", correction_file):
            result = check_for_corrections(
                store, {"production_activity": "coding", "flow_score": 0.3, "hour": 14}
            )
        assert result is not None
        assert result.corrected_value == "writing"
        assert result.original_value == "coding"
        client.upsert.assert_called_once()

    def test_same_label_returns_none(self, tmp_path: Path):
        client = _mock_qdrant()
        store = CorrectionStore(client=client)

        correction_file = tmp_path / "correction.json"
        correction_file.write_text(json.dumps({"label": "coding", "timestamp": time.time()}))

        with patch("shared.correction_memory.CORRECTION_INTAKE_PATH", correction_file):
            result = check_for_corrections(store, {"production_activity": "coding"})
        assert result is None

    def test_stale_correction_ignored(self, tmp_path: Path):
        client = _mock_qdrant()
        store = CorrectionStore(client=client)

        correction_file = tmp_path / "correction.json"
        correction_file.write_text(
            json.dumps({"label": "writing", "timestamp": time.time() - 600})  # 10 min old
        )

        with patch("shared.correction_memory.CORRECTION_INTAKE_PATH", correction_file):
            result = check_for_corrections(store, {"production_activity": "coding"})
        assert result is None

    @pytest.mark.parametrize(
        "payload",
        ["[]", "null", '"string"', "42", "true"],
    )
    def test_non_dict_root_returns_none(self, tmp_path: Path, payload: str):
        """Same defensive pattern as the broader non-dict-root campaign —
        a correction intake file containing a JSON list/string/null/
        number/bool would have crashed `data.get("label", "")` with
        AttributeError before this hardening."""
        client = _mock_qdrant()
        store = CorrectionStore(client=client)

        correction_file = tmp_path / "correction.json"
        correction_file.write_text(payload)

        with patch("shared.correction_memory.CORRECTION_INTAKE_PATH", correction_file):
            result = check_for_corrections(store, {"production_activity": "coding"})
        assert result is None
