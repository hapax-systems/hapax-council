"""Tests for world-language use-time binding in the affordance pipeline (split 3/3)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

from shared.affordance import SelectionCandidate
from shared.affordance_pipeline import AffordancePipeline


def _cand(name: str, payload: dict | None = None) -> SelectionCandidate:
    return SelectionCandidate(capability_name=name, payload=payload or {})


class TestUseTimeBinding:
    def test_no_op_when_manifest_absent_is_byte_identical(self):
        p = AffordancePipeline()
        with mock.patch.object(p, "_world_language_manifest", return_value={}):
            cands = [_cand("a"), _cand("b", {"existing": 1})]
            out = p._bind_interpretants(cands)
        assert out is cands  # same list object — selection untouched while inert
        assert all("world_language_node" not in c.payload for c in out)

    def test_attaches_interpretant_when_manifest_present(self):
        p = AffordancePipeline()
        node = {"node_id": "cap.x", "sosa_class": "Observation"}
        with mock.patch.object(p, "_world_language_manifest", return_value={"cap.x": node}):
            out = p._bind_interpretants([_cand("cap.x", {"k": 1}), _cand("cap.y")])
        assert out[0].payload["world_language_node"] == node
        assert out[0].payload["k"] == 1  # existing payload preserved
        assert "world_language_node" not in out[1].payload  # no match → unchanged

    def test_select_wrapper_binds_posterior_winner(self):
        # the interpretant follows the POSTERIOR selection (whatever _select_candidates
        # returns), not a static symbol→referent table.
        p = AffordancePipeline()
        node = {"node_id": "cap.win"}
        with (
            mock.patch.object(p, "_select_candidates", return_value=[_cand("cap.win")]),
            mock.patch.object(p, "_world_language_manifest", return_value={"cap.win": node}),
        ):
            out = p.select(impingement=mock.MagicMock(), top_k=5)
        assert out[0].payload["world_language_node"] == node

    def test_manifest_loads_and_indexes_by_node_id(self):
        p = AffordancePipeline()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"nodes": [{"node_id": "cap.x", "sosa_class": "Actuation"}]}, fh)
            path = Path(fh.name)
        try:
            with mock.patch("shared.affordance_pipeline._WL_MANIFEST_PATH", path):
                m = p._world_language_manifest()
        finally:
            path.unlink()
        assert m == {"cap.x": {"node_id": "cap.x", "sosa_class": "Actuation"}}

    def test_manifest_absent_returns_empty(self):
        p = AffordancePipeline()
        with mock.patch(
            "shared.affordance_pipeline._WL_MANIFEST_PATH", Path("/nonexistent/hapax/wl.json")
        ):
            assert p._world_language_manifest() == {}
