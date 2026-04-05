"""Tests for satellite node recruitment in Reverie mixer."""

import json
from pathlib import Path

from agents.reverie._graph_builder import NODE_LAYERS, build_graph
from agents.reverie._satellites import (
    RECRUITMENT_THRESHOLD,
    SatelliteManager,
)


def _core_vocab() -> dict:
    """Load the actual reverie vocabulary."""
    path = Path(__file__).resolve().parents[1] / "presets" / "reverie_vocabulary.json"
    return json.loads(path.read_text())


class TestLayerClassification:
    def test_generation_before_color(self):
        assert NODE_LAYERS["noise_gen"] < NODE_LAYERS["colorgrade"]

    def test_color_before_spatial(self):
        assert NODE_LAYERS["colorgrade"] < NODE_LAYERS["drift"]

    def test_spatial_before_temporal(self):
        assert NODE_LAYERS["drift"] < NODE_LAYERS["feedback"]

    def test_temporal_before_content(self):
        assert NODE_LAYERS["feedback"] < NODE_LAYERS["content_layer"]

    def test_content_before_effects(self):
        assert NODE_LAYERS["content_layer"] < NODE_LAYERS["bloom"]

    def test_effects_before_post(self):
        assert NODE_LAYERS["bloom"] < NODE_LAYERS["postprocess"]


class TestGraphBuilder:
    def test_core_only_produces_8_passes(self):
        vocab = _core_vocab()
        graph = build_graph(vocab, {})
        assert len(graph.edges) == 8  # 9 nodes, 8 edges

    def test_recruiting_bloom_adds_one_pass(self):
        vocab = _core_vocab()
        graph = build_graph(vocab, {"bloom": 0.5})
        assert len(graph.edges) == 9  # 10 nodes, 9 edges

    def test_recruited_node_at_correct_layer(self):
        vocab = _core_vocab()
        graph = build_graph(vocab, {"bloom": 0.5})
        node_ids = [e[0] for e in graph.edges] + [graph.edges[-1][1]]
        # bloom (layer 6) should be after content_layer (layer 5) and before postprocess (layer 8)
        bloom_idx = node_ids.index("sat_bloom")
        content_idx = node_ids.index("content")
        post_idx = node_ids.index("post")
        assert content_idx < bloom_idx < post_idx

    def test_multiple_satellites_sorted_by_layer(self):
        vocab = _core_vocab()
        graph = build_graph(vocab, {"bloom": 0.5, "warp": 0.4, "trail": 0.6})
        node_ids = [e[0] for e in graph.edges] + [graph.edges[-1][1]]
        warp_idx = node_ids.index("sat_warp")
        trail_idx = node_ids.index("sat_trail")
        bloom_idx = node_ids.index("sat_bloom")
        # warp (layer 3) < trail (layer 4) < bloom (layer 6)
        assert warp_idx < trail_idx < bloom_idx

    def test_core_node_type_not_duplicated(self):
        vocab = _core_vocab()
        # noise_gen is already in core — should not be added again
        graph = build_graph(vocab, {"noise_gen": 0.5})
        node_ids = list(graph.nodes.keys())
        noise_ids = [nid for nid in node_ids if "noise" in nid]
        assert len(noise_ids) == 1  # only the core "noise", no "sat_noise_gen"

    def test_unknown_node_type_skipped(self):
        vocab = _core_vocab()
        graph = build_graph(vocab, {"nonexistent_shader_xyz": 0.5})
        assert len(graph.edges) == 8  # unchanged


class TestSatelliteManager:
    def test_recruit_above_threshold(self):
        mgr = SatelliteManager(_core_vocab())
        mgr.begin_tick()
        mgr.recruit("bloom", 0.5)
        assert "bloom" in mgr.recruited

    def test_recruit_below_threshold_ignored(self):
        mgr = SatelliteManager(_core_vocab())
        mgr.begin_tick()
        mgr.recruit("bloom", 0.1)
        assert "bloom" not in mgr.recruited

    def test_decay_dismisses(self):
        mgr = SatelliteManager(_core_vocab())
        mgr.begin_tick()
        mgr.recruit("bloom", RECRUITMENT_THRESHOLD + 0.01)
        # Decay enough to dismiss
        mgr.decay(dt=100.0)
        assert "bloom" not in mgr.recruited

    def test_active_count(self):
        mgr = SatelliteManager(_core_vocab())
        mgr.begin_tick()
        mgr.recruit("bloom", 0.5)
        mgr.recruit("warp", 0.4)
        assert mgr.active_count == 2

    def test_maybe_rebuild_writes_plan(self, tmp_path):
        """Recruiting a satellite and calling maybe_rebuild should write a new plan.json."""
        from unittest.mock import patch

        mgr = SatelliteManager(_core_vocab())
        mgr.begin_tick()
        mgr.recruit("bloom", 0.5)
        with patch("agents.reverie._satellites.write_wgsl_pipeline") as mock_write:
            rebuilt = mgr.maybe_rebuild()
            assert rebuilt is True
            assert mock_write.called

    def test_maybe_rebuild_error_recovery(self):
        """Graph rebuild failure should not crash — returns False."""
        from unittest.mock import patch

        mgr = SatelliteManager(_core_vocab())
        mgr.begin_tick()
        mgr.recruit("bloom", 0.5)
        with patch(
            "agents.reverie._satellites.compile_to_wgsl_plan", side_effect=RuntimeError("boom")
        ):
            rebuilt = mgr.maybe_rebuild()
            assert rebuilt is False
            assert mgr.active_count == 1  # satellite still tracked
