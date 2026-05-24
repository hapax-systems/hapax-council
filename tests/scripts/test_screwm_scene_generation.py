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
    assert content.count("// ward-glow ") == 35
    assert content.count("// ward-light ") == 35
    assert content.count("// ward-rail row") == 5
    assert content.count("// ward-spine col") == 7
    assert content.count("// ward-drift ") >= 13
    assert "w01" in content
    assert "w35" in content
    assert "drift_c" in content
    assert "drift_r" in content
    assert "// ward-anchor 05: reverie" in content
    assert "// ward-anchor 34: segment_content" in content
    assert "pos=-222,62,280" in content
    assert "pos=222,-82,64" in content


def test_screwm_wad_defines_all_ward_panel_textures() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    ward_textures = [name for name in textures if name.startswith("w") and name[1:].isdigit()]
    assert len(ward_textures) == 35
    assert textures["w01"]["pattern"] == "ward_panel"
    assert textures["w01"]["code"] == "TOKEN"
    assert len(module["WARD_ACCENT_INDICES"]) >= 4
    assert textures["w35"]["label"] == 35
    assert textures["w35"]["code"] == "SCOPE"
    assert textures["drift_c"]["pattern"] == "drift_line"
    assert textures["drift_r"]["drift"] == 186


def test_ward_panel_texture_has_legible_number_contrast() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    pixels, _palette = module["generate_pixel_data"](
        (120, 105, 70),
        0,
        module["TEX_SIZE"],
        module["TEX_SIZE"],
        pattern="ward_panel",
        label=17,
        code="CODE",
    )

    assert max(pixels) >= 232
    assert min(pixels) <= 34
    assert pixels.count(max(pixels)) > 120
    accent = module["WARD_ACCENT_INDICES"][(17 - 1) % len(module["WARD_ACCENT_INDICES"])]
    assert pixels.count(accent) > 10
