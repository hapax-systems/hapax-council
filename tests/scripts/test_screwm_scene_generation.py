from __future__ import annotations

import json
import runpy
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(path: str) -> dict:
    return runpy.run_path(str(REPO_ROOT / path), run_name="__test__")


def test_screwm_map_sourceizes_all_legacy_ward_anchors() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    content = module["generate_map"](module["MODE_PRESETS"]["rnd"])

    assert len(module["WARD_ANCHORS"]) == 36
    assert content.count("// ward-anchor ") == 36
    assert content.count("// ward-glow ") == 36
    assert content.count("// ward-light ") == 36
    assert content.count("// ward-rail row") == 6
    assert content.count("// ward-spine col") == 7
    assert content.count("// ward-drift ") >= 13
    assert "w01" in content
    assert "w35" in content
    assert "drift_c" in content
    assert "drift_r" in content
    assert "// ward-anchor 05: reverie domain=perception" in content
    assert "// ward-anchor 34: segment_content" in content
    assert "// ward-anchor 36: cbip_dual_ir_displacement domain=perception" in content
    assert "pos=-222,62,280" in content
    assert "pos=222,-82,64" in content
    assert "pos=0,-118,28" in content
    assert "ward-glow 01: token_pole drift_c" in content
    assert "ward-glow 02: album drift_r" in content
    assert "ward-glow 03: stream_overlay drift_g" in content


def test_screwm_map_inventory_matches_default_non_darkplaces_sources() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    default_layout = json.loads(
        (REPO_ROOT / "config" / "compositor-layouts" / "default.json").read_text(encoding="utf-8")
    )
    default_sources = {source["id"] for source in default_layout["sources"]} - {"darkplaces"}

    assert set(module["WARD_ANCHORS"]) == default_sources
    assert set(module["WARD_DOMAINS"]) == default_sources
    assert set(module["WARD_DOMAINS"].values()) == {
        "communication",
        "presence",
        "token",
        "music",
        "cognition",
        "director",
        "perception",
    }


def test_screwm_wad_defines_all_ward_panel_textures() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    ward_textures = [name for name in textures if name.startswith("w") and name[1:].isdigit()]
    assert len(ward_textures) == 36
    assert textures["w01"]["pattern"] == "ward_panel"
    assert textures["w01"]["code"] == "TOKEN"
    assert len(module["WARD_ACCENT_INDICES"]) >= 4
    assert textures["w35"]["label"] == 35
    assert textures["w35"]["code"] == "SCOPE"
    assert textures["w36"]["label"] == 36
    assert textures["w36"]["code"] == "IRDUAL"
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
