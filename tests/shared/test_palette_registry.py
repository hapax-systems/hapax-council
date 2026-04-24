"""Tests for the palette registry loader + lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.palette_registry import (
    DEFAULT_REGISTRY_PATH,
    PaletteRegistry,
    RegistryLoadError,
)


class TestRegistryLoadDefault:
    """Smoke checks against the real registry.yaml shipped in-tree."""

    def test_default_registry_parses(self):
        reg = PaletteRegistry.load()
        assert reg is not None

    def test_default_registry_has_dozen_plus_palettes(self):
        # Operator directive: at least a dozen palette instances.
        reg = PaletteRegistry.load()
        assert len(reg.palette_ids()) >= 12

    def test_default_registry_has_expected_families(self):
        reg = PaletteRegistry.load()
        ids = reg.palette_ids()
        # Spot-check one from each family.
        assert "amber-glow" in ids  # warm
        assert "cool-mist" in ids  # cool
        assert "monochrome" in ids  # neutral

    def test_default_registry_chains_load(self):
        reg = PaletteRegistry.load()
        assert len(reg.chain_ids()) >= 1
        # All chain steps reference real palettes (invariant validated at load).
        for chain in reg.all_chains():
            for step in chain.steps:
                assert reg.find_palette(step.palette_id) is not None

    def test_default_registry_curves_validate(self):
        reg = PaletteRegistry.load()
        # Every palette has a curve; every curve's mode is one of the
        # documented Literal values (would have raised on load otherwise).
        for p in reg.all_palettes():
            assert p.curve is not None
            assert p.curve.mode in (
                "identity",
                "lab_shift",
                "duotone",
                "gradient_map",
                "hue_rotate",
                "channel_mix",
            )


class TestRegistryLoadErrors:
    """Error paths — malformed YAML, duplicates, bad references."""

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(RegistryLoadError, match="read failed"):
            PaletteRegistry.load(tmp_path / "nonexistent.yaml")

    def test_malformed_yaml_root(self, tmp_path: Path):
        bad = tmp_path / "r.yaml"
        bad.write_text("- just a list", encoding="utf-8")
        with pytest.raises(RegistryLoadError, match="must be a mapping"):
            PaletteRegistry.load(bad)

    def test_duplicate_palette_id(self, tmp_path: Path):
        content = """\
palettes:
  - id: x
    display_name: X
  - id: x
    display_name: X2
"""
        bad = tmp_path / "r.yaml"
        bad.write_text(content, encoding="utf-8")
        with pytest.raises(RegistryLoadError, match="duplicate palette"):
            PaletteRegistry.load(bad)

    def test_chain_references_unknown_palette(self, tmp_path: Path):
        content = """\
palettes:
  - id: known
    display_name: Known
chains:
  - id: c
    display_name: C
    steps:
      - palette_id: known
        dwell_s: 10.0
      - palette_id: missing
        dwell_s: 10.0
"""
        bad = tmp_path / "r.yaml"
        bad.write_text(content, encoding="utf-8")
        with pytest.raises(RegistryLoadError, match="unknown palette"):
            PaletteRegistry.load(bad)

    def test_palette_validation_error(self, tmp_path: Path):
        # warmth_axis > 1.0 violates the model's Field(le=1.0).
        content = """\
palettes:
  - id: bad
    display_name: Bad
    warmth_axis: 2.0
"""
        bad = tmp_path / "r.yaml"
        bad.write_text(content, encoding="utf-8")
        with pytest.raises(RegistryLoadError, match="failed validation"):
            PaletteRegistry.load(bad)


class TestRegistryLookup:
    @pytest.fixture
    def reg(self) -> PaletteRegistry:
        return PaletteRegistry.load()

    def test_get_palette_hit(self, reg):
        p = reg.get_palette("amber-glow")
        assert p.id == "amber-glow"

    def test_get_palette_miss_raises(self, reg):
        with pytest.raises(KeyError):
            reg.get_palette("does-not-exist")

    def test_find_palette_miss_returns_none(self, reg):
        assert reg.find_palette("does-not-exist") is None

    def test_get_chain_hit(self, reg):
        chain = reg.get_chain("day-arc")
        assert chain.id == "day-arc"

    def test_find_chain_miss_returns_none(self, reg):
        assert reg.find_chain("does-not-exist") is None


class TestRegistryRecruitment:
    @pytest.fixture
    def reg(self) -> PaletteRegistry:
        return PaletteRegistry.load()

    def test_recruit_empty_tags_returns_all(self, reg):
        matches = reg.recruit_by_tags(())
        assert len(matches) == len(reg.palette_ids())

    def test_recruit_single_tag(self, reg):
        warm = reg.recruit_by_tags(("warm",))
        # At least a few palettes carry the warm tag.
        assert len(warm) >= 3
        assert all("warm" in p.semantic_tags for p in warm)

    def test_recruit_and_semantics(self, reg):
        # Both tags must be present — AND.
        deep_cool = reg.recruit_by_tags(("cool", "deep"))
        for p in deep_cool:
            assert "cool" in p.semantic_tags
            assert "deep" in p.semantic_tags

    def test_recruit_no_matches_returns_empty(self, reg):
        assert reg.recruit_by_tags(("this-tag-does-not-exist",)) == ()

    def test_filter_by_affinity_research(self, reg):
        matches = reg.filter_by_affinity("research")
        # Every match has research or any in its affinity.
        for p in matches:
            assert "research" in p.working_mode_affinity or "any" in p.working_mode_affinity

    def test_filter_by_affinity_rnd(self, reg):
        matches = reg.filter_by_affinity("rnd")
        for p in matches:
            assert "rnd" in p.working_mode_affinity or "any" in p.working_mode_affinity

    def test_any_affinity_palettes_present(self, reg):
        # At least one palette has broad affinity.
        any_palettes = [p for p in reg.all_palettes() if "any" in p.working_mode_affinity]
        assert any_palettes


class TestRegistryContents:
    """Spot-checks on specific well-known palettes — pin their shape."""

    @pytest.fixture
    def reg(self) -> PaletteRegistry:
        return PaletteRegistry.load()

    def test_monochrome_is_zero_chroma(self, reg):
        p = reg.get_palette("monochrome")
        assert p.saturation_axis == 0.0
        assert p.warmth_axis == 0.0
        assert p.dominant_lab[1] == 0.0  # a*
        assert p.dominant_lab[2] == 0.0  # b*
        assert p.curve.preserve_luminance is True

    def test_candle_tongue_is_pulsing(self, reg):
        p = reg.get_palette("candle-tongue")
        assert p.temporal_profile == "pulsing"
        assert p.temporal_rate_hz > 0.0

    def test_cool_mist_carries_a6_tag(self, reg):
        p = reg.get_palette("cool-mist")
        assert "a6" in p.semantic_tags

    def test_day_arc_is_looping(self, reg):
        chain = reg.get_chain("day-arc")
        assert chain.loop is True

    def test_electric_study_is_one_shot(self, reg):
        chain = reg.get_chain("electric-study")
        assert chain.loop is False

    def test_default_registry_path_exists(self):
        assert DEFAULT_REGISTRY_PATH.exists()
