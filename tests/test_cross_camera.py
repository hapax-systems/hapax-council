"""Tests for cross-camera trajectory stitching."""

from __future__ import annotations

import numpy as np

from agents.models.cross_camera import CrossCameraStitcher


class TestCrossCameraStitcher:
    def test_temporal_match_on_adjacent_cameras(self):
        st = CrossCameraStitcher(temporal_window_s=5.0)
        st.report_disappeared("p1", "brio-operator", "person")
        suggestions = st.report_appeared("p2", "c920-hardware", "person")
        # brio-operator and c920-hardware are adjacent
        assert len(suggestions) >= 1
        assert suggestions[0].entity_a == "p1"
        assert suggestions[0].entity_b == "p2"

    def test_no_match_on_non_adjacent_cameras(self):
        st = CrossCameraStitcher(temporal_window_s=5.0)
        st.report_disappeared("p1", "brio-operator", "person")
        # c920-aux is not adjacent to brio-operator
        suggestions = st.report_appeared("p2", "c920-aux", "person")
        assert len(suggestions) == 0

    def test_face_embedding_boosts_confidence(self):
        st = CrossCameraStitcher(temporal_window_s=5.0, face_threshold=0.5)
        emb = np.random.randn(512).astype(np.float32)
        emb /= np.linalg.norm(emb)
        st.report_disappeared("p1", "brio-operator", "person", face_embedding=emb)
        # Same embedding → high similarity
        suggestions = st.report_appeared("p2", "c920-hardware", "person", face_embedding=emb)
        assert len(suggestions) >= 1
        assert suggestions[0].confidence > 0.5
        assert suggestions[0].reason == "both"

    def test_different_labels_dont_match(self):
        st = CrossCameraStitcher(temporal_window_s=5.0)
        st.report_disappeared("p1", "brio-operator", "person")
        suggestions = st.report_appeared("c1", "c920-hardware", "chair")
        assert len(suggestions) == 0

    def test_reset_clears_state(self):
        st = CrossCameraStitcher()
        st.report_disappeared("p1", "brio-operator", "person")
        st.reset()
        suggestions = st.report_appeared("p2", "c920-hardware", "person")
        assert len(suggestions) == 0
