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
    assert content.count("// ward-depth-plate ") == 36
    assert content.count("// ward-frame ") == 108
    assert content.count("// ward-glow ") == 36
    assert content.count("// ward-light ") == 36
    assert content.count("// review-fill-light ") == 3
    assert content.count("// ward-rail row") == 6
    assert content.count("// ward-spine col") == 7
    assert content.count("// ward-drift ") >= 25
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
    assert "ward-frame 01: token_pole top drift_c" in content
    assert "ward-frame 04: sierpinski left drift_g" in content
    assert "ward-depth-plate 36: cbip_dual_ir_displacement" in content
    assert '"origin" "0 -144 176"' in content


def test_screwm_drift_graph_physically_touches_every_ward_anchor() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    content = module["generate_map"](module["MODE_PRESETS"]["rnd"])

    covered = {ward for link in module["DRIFT_LINKS"] for ward in link[:2]}

    assert covered == set(range(1, 37))
    assert len(module["DRIFT_LINKS"]) >= 27
    assert "// section: ward-drift-paths" in content


def test_screwm_map_keeps_foundational_tower_geometry_in_regenerated_bsp() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    content = module["generate_map"](module["MODE_PRESETS"]["rnd"])

    assert "// section: tower-pillar-columns" in content
    assert "// section: tower-level-ledges" in content
    assert "// section: central-aoa-lattice" in content
    assert "// section: tower-ramp-shelves" in content
    assert "// section: central-aoa-pedestal" in content
    assert content.count("r_percep") > 1
    assert content.count("r_ground") > 1


def test_screwm_review_geometry_keeps_wards_primary_not_architecture() -> None:
    source = (REPO_ROOT / "scripts" / "generate-screwm-map.py").read_text(encoding="utf-8")

    assert "ledge_depth = 18" in source
    assert "ledge_height = 6" in source
    assert "WARD_FRAME_PAD = 6" in source
    assert "WARD_FRAME_T = 4" in source
    assert "inner = 78" in source
    assert "ring_height = 4" in source
    assert "rod_half = 3" in source
    assert "ramp_w = 52" in source
    assert "ramp_d = 22" in source
    assert 'base = int(preset.get("wall_light", 100) * 0.72)' in source


def test_screwm_map_embeds_camera_source_constellation() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    content = module["generate_map"](module["MODE_PRESETS"]["rnd"])

    roles = [source["role"] for source in module["SOURCE_ANCHORS"]]
    assert roles == [
        "brio-operator",
        "brio-room",
        "brio-synths",
        "c920-desk",
        "c920-room",
        "c920-overhead",
    ]
    assert content.count("// source-anchor ") == 6
    assert content.count("// source-glow ") == 6
    assert content.count("// source-tether ") == 6
    assert content.count("// source-light ") == 6
    assert "// section: source-camera-constellation" in content
    assert "// source-anchor 01: brio-operator class=brio domain=presence" in content
    assert "// source-anchor 03: brio-synths class=brio domain=music" in content
    assert "// source-anchor 06: c920-overhead class=c920 domain=perception" in content
    assert "cam_bop" in content
    assert "cam_cov" in content


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


def test_screwm_wad_defines_camera_source_anchor_textures() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    source_names = [name for name, _code, _accent in module["CAMERA_SOURCE_TEXTURES"]]
    assert source_names == ["cam_bop", "cam_brm", "cam_bsy", "cam_cdk", "cam_crm", "cam_cov"]
    assert all(textures[name]["pattern"] == "source_portal" for name in source_names)
    assert textures["cam_bop"]["code"] == "BRIOOP"
    assert textures["cam_bsy"]["accent"] == 186
    assert textures["cam_cov"]["code"] == "C920OVH"


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


def test_source_portal_texture_has_legible_camera_code() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    pixels, _palette = module["generate_pixel_data"](
        (74, 88, 84),
        0,
        module["TEX_SIZE"],
        module["TEX_SIZE"],
        pattern="source_portal",
        code="C920OVH",
        accent=214,
    )

    assert max(pixels) >= 232
    assert min(pixels) <= 34
    assert pixels.count(214) > 25
