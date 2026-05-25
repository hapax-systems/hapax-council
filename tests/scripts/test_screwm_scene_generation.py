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
    assert content.count("// ward-anchor ") == 0
    assert content.count("// ward-depth-plate ") == sum(
        module["WARD_DEPTH_STYLES"][module["ward_depth_plane"](idx)]["layers"]
        for idx in range(1, 37)
    )
    assert content.count("// ward-frame ") == 0
    assert content.count("// ward-glow ") == 0
    assert content.count("// ward-light ") == 36
    assert content.count("// review-fill-light ") == 4
    assert content.count("// ward-review-light ") == 36
    assert content.count("// ward-review-pane ") == 36
    assert content.count("// ward-review-frame ") == 144
    assert content.count("// ward-review-drift ") >= 25
    assert content.count("// legacy-sierpinski-edge ") == len(module["legacy_sierpinski_edges"]())
    assert content.count("// legacy-sierpinski-slot ") == 4
    assert content.count("// legacy-sierpinski-slot-frame ") == 16
    assert content.count("// legacy-sierpinski-light ") == 4
    assert content.count("// ward-rail row") == 0
    assert content.count("// ward-spine col") == 0
    assert content.count("// ward-drift ") == 0
    assert "w01" in content
    assert "w35" in content
    assert "drift_c" in content
    assert "drift_r" in content
    assert "// section: ward-review-plane" in content
    assert "// section: ward-review-drift-paths" in content
    assert "// section: legacy-sierpinski-scrim" in content
    assert "// section: ward-depth-echo-planes" in content
    assert "slot_sierp" in content
    assert "slot_album" in content
    assert "slot_rev" in content
    assert "slot_voice" in content
    assert "// ward-review-pane 01: token_pole" in content
    assert "// ward-depth-plate 01: token_pole hero-presence layer=1" in content
    assert "// ward-depth-plate 02: album beyond-scrim layer=3" in content
    assert "// ward-depth-plate 10: impingement_cascade near-surface layer=1" in content
    assert "// ward-review-frame 36: cbip_dual_ir_displacement" in content
    assert module["ward_review_position"](1) == (-222, -360, 280)
    assert module["ward_review_position"](36) == (0, -360, 28)
    assert module["ward_review_drift_midpoint"](1, 9) == (-185, -378, 253)
    assert "ward-review-frame 01: token_pole top drift_c" in content
    assert "ward-review-frame 04: sierpinski left drift_g" in content
    assert '"origin" "0 -455 176"' in content


def test_screwm_drift_graph_physically_touches_every_ward_anchor() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    content = module["generate_map"](module["MODE_PRESETS"]["rnd"])

    covered = {ward for link in module["DRIFT_LINKS"] for ward in link[:2]}

    assert covered == set(range(1, 37))
    assert len(module["DRIFT_LINKS"]) >= 27
    assert "// section: ward-drift-paths" in content


def test_screwm_map_keeps_open_scroom_geometry_in_regenerated_bsp() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    content = module["generate_map"](module["MODE_PRESETS"]["rnd"])

    assert "// section: tower-pillar-columns" in content
    assert "// section: tower-level-ledges" in content
    assert "// section: central-aoa-lattice" in content
    assert "// section: tower-ramp-shelves" in content
    assert "// section: central-aoa-pedestal" in content
    assert content.count("r_percep") == 0
    assert content.count("r_ground") > 1


def test_screwm_review_geometry_keeps_wards_primary_not_architecture() -> None:
    source = (REPO_ROOT / "scripts" / "generate-screwm-map.py").read_text(encoding="utf-8")

    assert "No free-standing columns in the reviewable scroom baseline" in source
    assert "Wall bands are deferred" in source
    assert "The duplicate deep ward lattice is disabled" in source
    assert "REVIEW_ALCOVE_Y_MIN" in source
    assert "REVIEW_WARD_Y = -360" in source
    assert "AOA_Y = -455" in source
    assert "REVIEW_DRIFT_Y = REVIEW_WARD_Y - 18" in source
    assert "t = 1" in source
    assert "WARD_FRAME_PAD = 5" in source
    assert "WARD_FRAME_T = 4" in source
    assert "WARD_DEPTH_PLANES" in source
    assert "ward_depth_echo_panes" in source
    assert "Low, non-obstructing AoA floor mark" in source
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
    assert len(module["WARD_TEXTURE_TYPES"]) == 36
    assert textures["w01"]["pattern"] == "ward_panel"
    assert textures["w01"]["code"] == "TOKEN"
    assert textures["w01"]["ward_type"] == "token_path"
    assert textures["w04"]["ward_type"] == "sierpinski"
    assert textures["w13"]["ward_type"] == "pressure_bar"
    assert len(module["WARD_ACCENT_INDICES"]) >= 4
    assert textures["w35"]["label"] == 35
    assert textures["w35"]["code"] == "SCOPE"
    assert textures["w35"]["ward_type"] == "scope_wave"
    assert textures["w36"]["label"] == 36
    assert textures["w36"]["code"] == "IRDUAL"
    assert textures["w36"]["ward_type"] == "ir_dual"
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


def test_screwm_wad_defines_legacy_sierpinski_slot_textures() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    slot_names = [name for name, _code, _accent in module["LEGACY_SLOT_TEXTURES"]]
    assert slot_names == ["slot_sierp", "slot_album", "slot_rev", "slot_voice"]
    assert all(textures[name]["pattern"] == "legacy_slot" for name in slot_names)
    assert textures["slot_sierp"]["code"] == "SIERP"
    assert textures["slot_album"]["accent"] == 186
    assert textures["slot_voice"]["code"] == "VOICE"


def test_ward_panel_texture_has_semantic_glyph_contrast() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    pixels, _palette = module["generate_pixel_data"](
        (120, 105, 70),
        0,
        module["TEX_SIZE"],
        module["TEX_SIZE"],
        pattern="ward_panel",
        label=13,
        code="PRESS",
        ward_type="pressure_bar",
    )

    assert max(pixels) >= 232
    assert min(pixels) <= 34
    accent = module["WARD_ACCENT_INDICES"][(13 - 1) % len(module["WARD_ACCENT_INDICES"])]
    assert pixels.count(accent) > 180

    scope_pixels, _palette = module["generate_pixel_data"](
        (120, 105, 70),
        0,
        module["TEX_SIZE"],
        module["TEX_SIZE"],
        pattern="ward_panel",
        label=35,
        code="SCOPE",
        ward_type="scope_wave",
    )
    scope_accent = module["WARD_ACCENT_INDICES"][(35 - 1) % len(module["WARD_ACCENT_INDICES"])]
    assert scope_pixels.count(scope_accent) > 100


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


def test_legacy_sierpinski_slot_texture_has_legible_code() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    pixels, _palette = module["generate_pixel_data"](
        (62, 76, 72),
        0,
        module["TEX_SIZE"],
        module["TEX_SIZE"],
        pattern="legacy_slot",
        code="REVERIE",
        accent=202,
    )

    assert max(pixels) >= 232
    assert min(pixels) <= 34
    assert pixels.count(202) > 20
