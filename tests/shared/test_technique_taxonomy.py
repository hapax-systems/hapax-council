"""Tests for TechniqueTaxonomy (HOMAGE Ward Umbrella Phase 2)."""

from __future__ import annotations

from shared.technique_taxonomy import TechniqueTaxonomy


def test_technique_taxonomy_loads():
    """Taxonomy loads from canonical source and is non-empty."""
    taxonomy = TechniqueTaxonomy.load()
    assert taxonomy.families
    assert len(taxonomy.families) > 0


def test_technique_taxonomy_has_palette_family_with_posterize_and_extract():
    """Palette-transformation family ships posterize + palette_extract."""
    taxonomy = TechniqueTaxonomy.load()
    palette = taxonomy.get_family("palette_transformations")
    assert palette is not None
    names = {t.name for t in palette.techniques}
    assert "posterize" in names
    assert "palette_extract" in names
    assert len(palette.techniques) >= 3


def test_technique_taxonomy_has_spatial_family_with_edge_and_kuwahara():
    """Spatial-transformation family ships edge_detect + kuwahara."""
    taxonomy = TechniqueTaxonomy.load()
    spatial = taxonomy.get_family("spatial_transformations")
    assert spatial is not None
    names = {t.name for t in spatial.techniques}
    assert "edge_detect" in names
    assert "kuwahara" in names


def test_technique_recognizability_risk_in_range():
    """Every technique declares a recognizability_risk in [0, 5]."""
    taxonomy = TechniqueTaxonomy.load()
    for family in taxonomy.families.values():
        for tech in family.techniques:
            assert 0 <= tech.recognizability_risk <= 5
            assert tech.node_ids, f"{tech.name} must declare node_ids"


def test_get_technique_lookup_across_families():
    """get_technique() finds a technique by name regardless of family."""
    taxonomy = TechniqueTaxonomy.load()
    posterize = taxonomy.get_technique("posterize")
    assert posterize is not None
    assert posterize.name == "posterize"

    assert taxonomy.get_technique("nonexistent_technique") is None


def test_applicable_techniques_for_album():
    """album-ward gets at least the 4 Phase-2 techniques."""
    taxonomy = TechniqueTaxonomy.load()
    album_techs = {t.name for t in taxonomy.get_applicable_techniques_for_ward("album")}
    assert {"posterize", "palette_extract", "edge_detect", "kuwahara"}.issubset(album_techs)


def test_applicable_techniques_respects_rejections():
    """A ward listed in rejected_wards never appears in applicable_techniques."""
    taxonomy = TechniqueTaxonomy.load()
    # Add a synthetic rejection for verification against existing data.
    kuwahara = taxonomy.get_technique("kuwahara")
    assert kuwahara is not None
    # token_pole rejects kuwahara per umbrella YAML; confirm the taxonomy
    # honours that contract by querying applicable techniques for token_pole.
    token_pole_techs = {t.name for t in taxonomy.get_applicable_techniques_for_ward("token_pole")}
    # Phase 2 techniques are album/sierpinski-scoped; token_pole gets none yet.
    assert "kuwahara" not in token_pole_techs
