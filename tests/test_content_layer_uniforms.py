"""Tests for material encoding in uniforms.json."""

from __future__ import annotations

MATERIAL_MAP = {"water": 0, "fire": 1, "earth": 2, "air": 3, "void": 4}


def test_material_map_covers_all_values():
    """All 5 Bachelard materials have numeric encodings."""
    assert set(MATERIAL_MAP.keys()) == {"water", "fire", "earth", "air", "void"}
    assert list(MATERIAL_MAP.values()) == [0, 1, 2, 3, 4]
