"""Tests for cross-modal expression coordination."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from shared.expression import (
    FRAGMENT_TO_SHADER,
    MATERIAL_TO_UNIFORM,
    ExpressionCoordinator,
    map_fragment_to_material_uniform,
    map_fragment_to_visual,
)


class TestExpressionCoordinator(unittest.TestCase):
    def _mock_cap(self, medium_value=None, category_value="expression"):
        from shared.capability import CapabilityCategory

        cap = MagicMock()
        cap.category = CapabilityCategory.EXPRESSION
        cap.operational.medium = medium_value
        cap.medium = medium_value
        return cap

    def test_coordinate_distributes_fragment(self):
        coord = ExpressionCoordinator()
        content = {"fragment": {"narrative": "A field of stars", "material": "air"}}
        recruited = [
            ("speech_production", self._mock_cap("speech_production")),
            ("shader_graph", self._mock_cap("shader_graph")),
        ]
        activations = coord.coordinate(content, recruited)
        assert len(activations) == 2
        assert activations[0]["fragment"]["narrative"] == "A field of stars"
        assert activations[1]["fragment"]["narrative"] == "A field of stars"

    def test_coordinate_infers_modality(self):
        coord = ExpressionCoordinator()
        content = {"fragment": {"narrative": "test"}}
        recruited = [
            ("speech_production", self._mock_cap(medium_value="speech")),
            ("shader_graph", self._mock_cap(medium_value="visual")),
        ]
        activations = coord.coordinate(content, recruited)
        modalities = {a["modality"] for a in activations}
        assert "speech" in modalities
        assert "visual" in modalities

    def test_coordinate_no_fragment_returns_empty(self):
        coord = ExpressionCoordinator()
        content = {"metric": "some_metric"}
        recruited = [("speech_production", self._mock_cap("speech"))]
        activations = coord.coordinate(content, recruited)
        assert activations == []

    def test_coordinate_narrative_string(self):
        coord = ExpressionCoordinator()
        content = {"narrative": "Direct narrative text"}
        recruited = [("speech_production", self._mock_cap("speech"))]
        activations = coord.coordinate(content, recruited)
        assert len(activations) == 1
        assert activations[0]["fragment"]["narrative"] == "Direct narrative text"

    def test_last_fragment_tracked(self):
        coord = ExpressionCoordinator()
        content = {"fragment": {"narrative": "tracked"}}
        coord.coordinate(content, [("x", self._mock_cap("x"))])
        assert coord.last_fragment["narrative"] == "tracked"

    def test_empty_recruited_returns_empty(self):
        coord = ExpressionCoordinator()
        content = {"fragment": {"narrative": "test"}}
        activations = coord.coordinate(content, [])
        assert activations == []


class TestFragmentToVisual(unittest.TestCase):
    def test_maps_dimensions(self):
        fragment = {"dimensions": {"intensity": 0.8, "diffusion": 0.5}}
        result = map_fragment_to_visual(fragment)
        assert result["noise.amplitude"] == 0.8
        assert result["physarum.sensor_dist"] == 0.5

    def test_missing_dimensions_skipped(self):
        fragment = {"dimensions": {"intensity": 0.8}}
        result = map_fragment_to_visual(fragment)
        assert "physarum.sensor_dist" not in result

    def test_no_dimensions_returns_empty(self):
        assert map_fragment_to_visual({}) == {}

    def test_all_mappings_covered(self):
        dims = {k: 0.5 for k in FRAGMENT_TO_SHADER}
        result = map_fragment_to_visual({"dimensions": dims})
        assert len(result) == len(FRAGMENT_TO_SHADER)


class TestFragmentToMaterialUniform(unittest.TestCase):
    def test_water_maps(self):
        assert map_fragment_to_material_uniform({"material": "water"}) == 0.0

    def test_fire_maps(self):
        assert map_fragment_to_material_uniform({"material": "fire"}) == 1.0

    def test_unknown_returns_zero(self):
        assert map_fragment_to_material_uniform({"material": "plasma"}) == 0.0

    def test_no_material_defaults_water(self):
        assert map_fragment_to_material_uniform({}) == 0.0

    def test_case_insensitive(self):
        assert map_fragment_to_material_uniform({"material": "EARTH"}) == 2.0

    def test_all_materials_mapped(self):
        for material, value in MATERIAL_TO_UNIFORM.items():
            assert map_fragment_to_material_uniform({"material": material}) == value
