"""Tests for the world-language materializer (keystone split 2/3)."""

from __future__ import annotations

from unittest import mock

from shared.direction import Direction, PhysicalDirection
from shared.materialize_world_language import materialize
from shared.sheaf_health import compute_consistency_radius


class TestMaterialize:
    def test_emits_nodes_from_the_real_wcs(self):
        m = materialize(write=False)
        assert m["node_count"] > 0
        assert m["schema_version"] == 1

    def test_every_node_has_non_null_generated_from(self):
        m = materialize(write=False)
        for node in m["nodes"]:
            gf = node["generated_from"]
            assert gf and gf["ssot"] and gf["key"] and gf["content_hash"]

    def test_only_observation_actuation_sampling(self):
        m = materialize(write=False)
        allowed = {"Observation", "Actuation", "Sampling"}
        assert {n["sosa_class"] for n in m["nodes"]} <= allowed

    def test_deterministic_content_hash(self):
        a = materialize(write=False)
        b = materialize(write=False)
        assert a["content_hash"] == b["content_hash"]
        assert a["nodes"] == b["nodes"]  # stable ordering

    def test_drift_gate_reuses_sheaf_radius(self):
        m = materialize(write=False)
        # with the real registry fully projecting, residuals are all 0 → radius 0
        assert m["drift_radius"] == round(compute_consistency_radius([0.0] * m["node_count"]), 4)
        assert m["coverage_shortfall"] is False

    def test_boot_safe_when_source_fails(self):
        # a missing/broken source must degrade coverage, never raise (service-load safety)
        with mock.patch(
            "shared.world_capability_surface.load_world_capability_registry",
            side_effect=RuntimeError("registry unreadable"),
        ):
            m = materialize(write=False)
        assert m["node_count"] == 0
        assert m["coverage_shortfall"] is True  # H¹ obstruction surfaced as information
        assert m["drift_radius"] > 0.0

    def test_projection_maps_are_structural_not_referent_tables(self):
        # The declarative maps are enum→enum/str STRUCTURAL projections (the Ashby
        # homomorphism), never a symbol→referent (meaning) lookup table — meaning is
        # bound at use-time by the affordance pipeline (split 3).
        import shared.materialize_world_language as mod

        assert all(isinstance(k, Direction) for k in mod._PHYSICAL_FOR_DIRECTION)
        assert all(isinstance(v, PhysicalDirection) for v in mod._PHYSICAL_FOR_DIRECTION.values())
