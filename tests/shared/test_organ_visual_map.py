"""Tests for the system organ to visual representation mapping."""

from shared.organ_visual_map import (
    load_organ_visual_map,
    organ_by_id,
    organ_ids,
    organs_using_technique,
    shader_node_ids,
    visual_techniques_for_organ,
    ward_ids,
)


class TestMapLoading:
    def test_loads_without_error(self):
        data = load_organ_visual_map()
        assert data["schema_version"] == 1

    def test_has_organs(self):
        assert len(organ_ids()) >= 10

    def test_has_visual_techniques(self):
        data = load_organ_visual_map()
        assert len(data["visual_techniques"]) >= 4


class TestOrganAccessors:
    def test_organ_by_id_found(self):
        organ = organ_by_id("daimonion")
        assert organ is not None
        assert organ["name"] == "Hapax Daimonion"

    def test_organ_by_id_not_found(self):
        assert organ_by_id("nonexistent") is None

    def test_every_organ_has_visual_representation(self):
        for oid in organ_ids():
            techniques = visual_techniques_for_organ(oid)
            assert len(techniques) >= 1, f"{oid} has no visual representations"

    def test_every_organ_has_tier(self):
        data = load_organ_visual_map()
        for o in data["organs"]:
            assert o.get("tier") in ("T1", "T2", "T3"), f"{o['id']} missing valid tier"


class TestTechniqueQueries:
    def test_cairo_ward_users(self):
        users = organs_using_technique("cairo_ward")
        assert "daimonion" in users
        assert "compositor" in users

    def test_shader_node_users(self):
        users = organs_using_technique("shader_node")
        assert "compositor" in users
        assert "imagination" in users

    def test_stimmung_users(self):
        users = organs_using_technique("stimmung_tint")
        assert "daimonion" in users
        assert "health_monitor" in users

    def test_ward_ids_non_empty(self):
        wards = ward_ids()
        assert len(wards) >= 3
        assert "voice-state" in wards

    def test_shader_node_ids_non_empty(self):
        nodes = shader_node_ids()
        assert len(nodes) >= 6
        assert "noise" in nodes
