from __future__ import annotations

import runpy
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(path: str) -> dict:
    return runpy.run_path(str(REPO_ROOT / path), run_name="__test__")


def test_screwm_map_sourceizes_all_legacy_ward_anchors() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    content = module["generate_map"](module["MODE_PRESETS"]["rnd"])

    assert len(module["WARD_ANCHORS"]) == 35
    assert content.count("// ward-anchor ") == 35
    assert "w01" in content
    assert "w35" in content
    assert "// ward-anchor 05: reverie" in content
    assert "// ward-anchor 34: segment_content" in content


def test_screwm_wad_defines_all_ward_panel_textures() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    ward_textures = [name for name in textures if name.startswith("w") and name[1:].isdigit()]
    assert len(ward_textures) == 35
    assert textures["w01"]["pattern"] == "ward_panel"
    assert textures["w35"]["label"] == 35


def test_ward_panel_texture_has_legible_number_contrast() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    pixels, _palette = module["generate_pixel_data"](
        (120, 105, 70),
        0,
        module["TEX_SIZE"],
        module["TEX_SIZE"],
        pattern="ward_panel",
        label=17,
    )

    assert max(pixels) >= 232
    assert min(pixels) <= 34
    assert pixels.count(max(pixels)) > 120
