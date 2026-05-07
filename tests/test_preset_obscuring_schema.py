"""Obscuring-schema gate for compositor presets.

Every broadcast preset must include at least one node whose type is in
the obscuring-grade set — transforms that meaningfully distance the
output from the raw camera. Light presets (colorgrade-only,
vignette-only, scanlines-only) preserve too much legibility; they must
be paired with a heavier transform.

This test loads every ``presets/*.json`` file and asserts the rule.
Configuration files (no ``nodes`` key, e.g. ``_default_modulations``,
``shader_intensity_bounds``) are excluded.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRESETS_DIR = REPO_ROOT / "presets"

# Obscuring-grade node types — transforms that meaningfully distance the
# output from the raw camera.
OBSCURING_NODE_TYPES: frozenset[str] = frozenset(
    {
        # Pixel-level discretization
        "posterize",
        "threshold",
        "dither",
        "halftone",
        "ascii",
        "color_map",
        "palette_remap",
        "palette_extract",
        # Spatial distortion / reorganization
        "displacement_map",
        "warp",
        "slitscan",
        "pixsort",
        "scramble",
        "fluid_sim",
        "reaction_diffusion",
        "syrup",
        # Tonal / chromatic transforms
        "chromatic_aberration",
        "rutt_etra",
        "thermal",
        "invert",
        "kuwahara",
        "sharpen",
        # Geometric / mirror-class
        "mirror",
        "kaleidoscope",
        "fisheye",
        "tunnel",
        "droste",
        "circular_mask",
        # Edge / structure
        "emboss",
        "edge_detect",
        # Glitch / temporal
        "glitch_block",
        "glitch",
        "vhs",
        "scanlines",
        "stutter",
        # Texture / overlay
        "noise_overlay",
        "voronoi_overlay",
        "particle_system",
        # Keying
        "chroma_key",
        "luma_key",
    }
)

NON_PRESET_FILES: frozenset[str] = frozenset(
    {
        "_default_modulations.json",
        "shader_intensity_bounds.json",
    }
)


def _list_presets() -> list[Path]:
    return sorted(p for p in PRESETS_DIR.glob("*.json") if p.name not in NON_PRESET_FILES)


def _preset_node_types(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = data.get("nodes") or {}
    return {(nv.get("type", nk) if isinstance(nv, dict) else nk) for nk, nv in nodes.items()}


def test_every_preset_includes_obscuring_node() -> None:
    violators: list[tuple[str, list[str]]] = []
    for path in _list_presets():
        types = _preset_node_types(path)
        if not types:
            continue
        if not (types & OBSCURING_NODE_TYPES):
            violators.append((path.name, sorted(types)))
    if violators:
        lines = ["Presets missing obscuring-grade transforms:"]
        for name, types in violators:
            lines.append(f"  {name}: nodes={types}")
        lines.append("")
        lines.append(
            "Every broadcast preset must include at least one node from "
            "OBSCURING_NODE_TYPES. If a preset is intentionally light, add "
            "an obscuring layer (posterize, halftone, displacement_map, "
            "chromatic_aberration, etc.) per the never-remove directive "
            "— do not delete the preset."
        )
        import pytest

        pytest.fail("\n".join(lines))


def test_obscuring_types_are_real() -> None:
    used_types: set[str] = set()
    for path in _list_presets():
        used_types |= _preset_node_types(path)
    allowed_unused: frozenset[str] = frozenset(
        {
            "scramble",
            "ascii",
            "rutt_etra",
            "palette_extract",
            "color_map",
            "kuwahara",
            "sharpen",
            "chroma_key",
            "luma_key",
            "circular_mask",
            "particle_system",
            "voronoi_overlay",
            "fluid_sim",
            "reaction_diffusion",
            "syrup",
            "thermal",
            "invert",
            "fisheye",
            "tunnel",
            "droste",
            "displacement_map",
            "vhs",
            "glitch_block",
            "pixsort",
            "stutter",
            "edge_detect",
            "emboss",
            "halftone",
            "dither",
            "threshold",
            "palette_remap",
            "slitscan",
            "warp",
            "noise_overlay",
            "mirror",
            "kaleidoscope",
            "chromatic_aberration",
            "scanlines",
            "posterize",
            "glitch",
        }
    )
    unknown = OBSCURING_NODE_TYPES - used_types - allowed_unused
    assert not unknown, (
        f"OBSCURING_NODE_TYPES contains type names not seen in any preset and "
        f"not in the allow-list: {sorted(unknown)}. Possible typo or stale "
        f"entry; either rename, remove, or add to allowed_unused."
    )
