from __future__ import annotations

import json
import math
import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(path: str) -> dict:
    return runpy.run_path(str(REPO_ROOT / path), run_name="__test__")


def _comment_block(content: str, marker: str) -> str:
    start = content.index(marker)
    end = content.find("\n// ", start + 1)
    return content[start:] if end == -1 else content[start:end]


def test_screwm_map_spatializes_only_functional_wards_as_geometric_instruments() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    content = module["generate_map"](module["MODE_PRESETS"]["rnd"])

    assert len(module["WARD_ANCHORS"]) == 36
    assert module["WARD_ATLAS_VISIBLE_INDICES"] == frozenset(set(range(1, 37)) - {18, 19})
    assert module["ACTIVE_WARD_INDICES"] == frozenset(set(range(1, 37)) - {18, 19})
    assert module["WARD_ATLAS_MOUNT"]["texture"] == "ward_atlas"
    assert module["WARD_ATLAS_MOUNT"]["active_visible_indices"] == sorted(
        set(range(1, 37)) - {18, 19}
    )
    assert module["WARD_ATLAS_MOUNT"]["activation_policy"] == ("all-wards-live-34-of-36")
    assert module["STATIC_WARD_MOUNT_PROFILE"] == "state-ward-instrument"
    assert content.count("// ward-anchor ") == 0
    assert content.count("// ward-depth-plate ") == 0
    assert content.count("// ward-frame ") == 0
    assert content.count("// ward-glow ") == 0
    assert content.count("// ward-light ") == 0
    assert content.count("// review-fill-light ") == 8
    assert content.count("// ward-garden-light ") == len(module["ACTIVE_WARD_INDICES"])
    rectangular_ward_indices = {
        idx
        for idx in module["ACTIVE_WARD_INDICES"]
        if module["ward_mount_is_inherently_rectangular"](
            module["ward_live_mount_contract"](idx, module["WARD_ANCHORS"][idx - 1])
        )
    }
    glyph_ward_indices = module["ACTIVE_WARD_INDICES"] - rectangular_ward_indices
    receiver_w, receiver_h, _u_scale, _v_scale, thickness = module[
        "ward_homage_receiver_metrics"
    ](*module["ward_pane_dimensions"](2))
    assert receiver_w >= module["WARD_PURPOSE_RECEIVER_MIN_WIDTH"] >= 180
    assert receiver_h >= module["WARD_PURPOSE_RECEIVER_MIN_HEIGHT"] >= 96
    assert thickness >= 18
    assert module["WARD_PURPOSE_RECEIVER_THICKNESS_RATIO"] >= 0.18
    assert content.count("// ward-garden-pane ") == len(rectangular_ward_indices)
    assert all(f"// ward-homage-glyph {idx:02d}." in content for idx in glyph_ward_indices)
    assert all(
        module["ward_live_mount_contract"](idx, module["WARD_ANCHORS"][idx - 1])["texture"]
        in _comment_block(
            content, f"// ward-homage-glyph {idx:02d}.1"
        )
        for idx in glyph_ward_indices
    )
    assert all(f"// ward-homage-accent {idx:02d}." in content for idx in glyph_ward_indices)
    assert all(
        module["DOMAIN_GLOW_TEX"][module["ward_domain"](idx)] in _comment_block(
            content, f"// ward-homage-accent {idx:02d}.1"
        )
        for idx in glyph_ward_indices
    )
    assert content.count("// ward-garden-pane-frame ") == 0
    assert content.count("// ward-state-lamp ") == 0
    assert content.count("// ward-garden-pane-mount-") == 0
    assert content.count("// ward-garden-drift-stone ") == 0
    assert content.count("// ward-review-pane ") == 0
    assert content.count("// ward-review-frame ") == 0
    assert "legacy-sierpinski" not in content
    assert content.count("// aoa-payload-pane ") == 0
    assert content.count("// aoa-payload-pane-frame ") == 0
    assert content.count("// aoa-payload-tether ") == 0
    assert content.count("// aoa-payload-light ") == 0
    assert content.count("// aoa-attendant-sphere ") == module["AOA_SPHERE_STRIP_COUNT"]
    assert content.count("// aoa-attendant-sphere-frame ") == 0
    assert content.count("// aoa-attendant-sphere-cross ") == 0
    assert content.count("// aoa-attendant-sphere-cross-frame ") == 0
    assert content.count("// aoa-attendant-sphere-ring ") == 0
    assert content.count("// aoa-attendant-sphere-light ") == 1
    assert content.count("// scroom-scene-hls ") == 0
    assert content.count("// scroom-scene-ir ") == 0
    assert content.count("// scroom-scene-ward-shelf ") == 0
    assert content.count("// scroom-scene-mid-band ") == 0
    assert content.count("// scroom-scene-far-band ") == 0
    assert content.count("// scroom-scene-rail ") == 0
    assert content.count("// scroom-scene-light ") == 0
    assert content.count("// scroom-light-marker ") == 0
    assert content.count("// scroom-room-floor-grid-x ") == 0
    assert content.count("// scroom-room-floor-grid-y ") == 0
    assert content.count("// scroom-room-ceiling-grid-x ") == 0
    assert content.count("// scroom-room-ceiling-grid-y ") == 0
    assert content.count("// scroom-room-floor-truss ") == 0
    assert content.count("// scroom-room-ceiling-truss ") == 0
    assert content.count("// scroom-room-side-grid-v ") == 0
    assert content.count("// scroom-room-side-grid-h ") == 0
    assert content.count("// scroom-room-end-grid-v ") == 0
    assert content.count("// scroom-room-end-grid-h ") == 0
    assert content.count("// scroom-volumetric-beam ") == 0
    assert content.count("// scroom-material-grid ") == 0
    assert content.count("// scroom-garden-path-stone ") == 0
    assert content.count("// scroom-garden-island ") == 0
    assert content.count("// scroom-garden-lantern ") == 0
    assert content.count("// scroom-garden-lantern-cap ") == 0
    assert content.count("// scroom-local-effect-lens ") == 0
    assert content.count("// scroom-local-effect-lens-frame ") == 0
    assert content.count("// scroom-local-effect-tether ") == 0
    assert content.count("// scroom-local-effect-light ") == 0
    assert content.count("// ward-rail row") == 0
    assert content.count("// ward-spine col") == 0
    assert content.count("// ward-drift ") == 0
    assert "w01" not in content
    assert "// ward-garden-pane 09: grounding_provenance_ticker w09" in content
    assert "// ward-garden-pane 22: precedent_ticker w22" in content
    assert "// ward-garden-pane 27: chronicle_ticker w27" in content
    assert "w35" not in content
    assert "// ward-homage-glyph 02.1: album music slash-pair ward_atlas" in content
    assert "// ward-garden-pane 02: album ward_atlas" not in content
    assert "// ward-homage-glyph 01.1: token_pole token spine ward_atlas" in content
    assert "// ward-homage-glyph 35.1: m8_oscilloscope music slash-pair ward_atlas" in content
    before_receivers, receiver_tail = content.split("// section: scroom-drift-receiver-strips")
    _receivers, after_receivers = receiver_tail.split("// section: scroom-local-effect-lenses")
    non_receiver_content = before_receivers + after_receivers
    assert "// drift-receiver-strip:" not in non_receiver_content
    assert "// section: ward-garden-clumps" in content
    assert "// section: ward-garden-drift-stones" in content
    assert "// section: legacy-sierpinski-scrim" not in content
    assert "// section: aoa-payload-panes" in content
    assert "// section: scroom-scene-graph-bands" in content
    assert "// section: scroom-material-field" in content
    assert "// section: scroom-local-effect-lenses" in content
    assert "// section: ward-depth-echo-planes" in content
    assert "slot_sierp" not in content
    assert "slot_album" not in content
    assert "slot_rev" not in content
    assert "slot_voice" not in content
    assert "aoa_root" not in content
    assert "aoa_gate" not in content
    assert "cam_cov" in content
    assert "// section: speech-waveform" in content
    assert "// speech-waveform 01: hapax-speech speech_wave" in content
    assert "// speech-waveform-light 01: hapax-speech" in content
    assert module["ward_review_position"](1) == (-900, -2360, 130)
    assert module["ward_review_position"](5) == (-700, -1120, 260)
    assert module["ward_review_position"](36) == (-1180, -600, 330)
    assert abs(module["ward_review_position"](1)[0]) >= 600
    assert module["MEDIA_RECEIVER_EDGE_TEX"] == "scroom"
    assert module["SYNTHWAVE_TICKER_WARDS"] == {9, 22, 27}
    assert module["ward_pane_dimensions"](9) == (768, 101)
    assert module["ward_pane_dimensions"](22) == (768, 101)
    assert module["ward_pane_dimensions"](27) == (768, 101)
    assert module["ward_live_mount_contract"](2, "album")["texture"] == "ward_atlas"
    assert module["ward_live_mount_contract"](2, "album")["atlas_cell"] == [1, 0]
    assert module["ward_live_mount_contract"](5, "reverie")["texture"] == "w05"
    assert module["ward_garden_facing"](5) == "y"
    assert module["ward_live_mount_contract"](8, "gem")["texture"] == "ward_atlas"
    assert module["ward_atlas_cell"](1) == (0, 0)
    assert module["ward_atlas_cell"](9) == (0, 2)
    assert module["ward_atlas_texture_transform"](9)["v_offset_px"] == 512
    assert module["static_ward_surface_texture"]("cognition") == "scroom"
    assert (
        module["static_ward_mount_contract"](1, "token_pole", "drift_c")["material_profile"]
        == "state-ward-instrument"
    )
    assert module["ward_review_drift_midpoint"](1, 9) == (-1240, -2110, 175)
    assert module["inward_x_normal"](-1180) == 1
    assert module["inward_x_normal"](1180) == -1
    assert module["inward_y_normal"](-2360) == 1
    assert module["inward_y_normal"](980) == -1
    assert module["offset_span"](-1180, 1, 4, 8) == (-1176, -1172)
    assert module["offset_span"](1180, -1, 4, 8) == (1172, 1176)
    assert module["pane_light_origin"](-1180, -1780, 150, "x", 18) == (-1162, -1780, 150)
    assert module["pane_light_origin"](1180, -1780, 315, "x", 18) == (1162, -1780, 315)
    assert module["pane_light_origin"](0, -2360, 130, "y", 18) == (0, -2342, 130)
    assert module["pane_light_origin"](-1040, 980, 300, "y", 18) == (-1040, 962, 300)
    assert "aoa-attendant-sphere 01: yt-media-face-strip yt_sphere" not in content
    assert "aoa-attendant-sphere-cross 01: yt-media-face-side yt_sphere" not in content
    assert '"origin" "0 -555 224"' in content


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
    assert content.count("r_ground") == 0
    assert content.count("ground1_6") == 0
    assert content.count("sky4") == 0
    assert content.count("city4_2") == 0
    assert content.count("void_floor") == 0
    assert content.count("void_ceil") == 0
    assert content.count("void_wall") == 0
    assert content.count("skip 0 0 0 16 16") > 1
    assert content.count("cmp_wall") == 0
    assert "cmp_floor" not in content
    assert "cmp_ceil" not in content


def test_screwm_map_embeds_hex_alignment_substrate_without_filled_receiver_strips() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    content = module["generate_map"](module["MODE_PRESETS"]["rnd"])

    assert "// section: scroom-hex-alignment-substrate" in content
    assert module["HEX_GRID_RADIUS"] == 384
    assert module["HEX_GRID_LINE_WIDTH"] <= 6
    assert module["WALL_GRID_LINE_WIDTH"] <= 4
    assert module["clip_segment_to_scroom_bounds"](
        -9999,
        module["AOA_Y"],
        9999,
        module["AOA_Y"],
    ) == (
        module["SCROOM_GRID_BOUNDS"][0],
        module["AOA_Y"],
        module["SCROOM_GRID_BOUNDS"][1],
        module["AOA_Y"],
    )
    assert content.count("// scroom-hex-floor-line ") > 20
    assert content.count("// scroom-hex-floor-line ") == content.count("// scroom-hex-ceiling-line ")
    assert content.count("// scroom-stipple-floor-dot ") > 20
    assert content.count("// scroom-stipple-floor-dot ") == content.count(
        "// scroom-stipple-ceiling-dot "
    )
    assert content.count("// scroom-wall-beam-") == 0
    assert content.count("// scroom-wall-grid-") > 20
    assert content.count("// scroom-wall-stipple-") > 20
    assert "// scroom-hex-floor-line 001" in content
    assert "// scroom-hex-ceiling-line 001" in content
    assert "hex_floor 0 0 0 8 8" in content
    assert "hex_ceil 0 0 0 8 8" in content
    assert "hex_wall 0 0 0 8 8" in content
    assert "stipple_floor 0 0 0 8 8" in content
    assert "stipple_ceil 0 0 0 8 8" in content
    assert "stipple_wall 0 0 0 8 8" in content
    assert "// section: scroom-drift-receiver-strips" in content
    assert content.count("// drift-receiver-strip:") == 0
    assert "entry-floor-center" not in content
    assert "entry-ceiling-center" not in content
    hex_section = content.split("// section: scroom-hex-alignment-substrate", 1)[1]
    hex_section = hex_section.split("// section: scroom-drift-receiver-strips", 1)[0]
    assert "hex_floor 0 0 0 8 8" in hex_section
    assert "hex_ceil 0 0 0 8 8" in hex_section
    assert "hex_wall 0 0 0 8 8" in hex_section
    assert "stipple_floor 0 0 0 8 8" in hex_section
    assert "stipple_ceil 0 0 0 8 8" in hex_section
    assert "stipple_wall 0 0 0 8 8" in hex_section
    assert "// scroom-wall-grid-left-h " in hex_section
    assert "// scroom-wall-grid-right-v " in hex_section
    assert "// scroom-wall-stipple-entry " in hex_section
    assert "drift_a" not in hex_section
    assert "drift_c" not in hex_section
    assert "drift_g" not in hex_section
    assert "drift_r" not in hex_section


def test_screwm_room_textures_are_information_surfaces_not_identifiable_materials() -> None:
    wad_module = _load_script("scripts/generate-screwm-wad.py")
    surface_contracts = json.loads(
        (REPO_ROOT / "config" / "screwm-quake-surface-contracts.json").read_text(encoding="utf-8")
    )
    info_contract = surface_contracts["information_surface_contract"]

    forbidden_patterns = {
        "stone_blocks",
        "worn_stone",
        "dark_ceiling",
        "brushed_metal",
        "carved_stone",
        "metal_grate",
        "dark_ornate",
        "polished_stone",
    }
    room_texture_names = {
        "city4_2",
        "ground1_6",
        "sky4",
        "metal5_2",
        "scroom",
        "void_floor",
        "void_ceil",
        "void_wall",
        "skip",
        "geom_mark",
        "hex_floor",
        "hex_ceil",
        "hex_wall",
        "stipple_floor",
        "stipple_ceil",
        "stipple_wall",
        "r_percep",
        "r_cognit",
        "r_comm",
        "r_express",
        "r_ground",
        "s_percep",
        "s_cognit",
        "s_comm",
        "s_express",
        "s_ground",
    }
    room_textures = {name: wad_module["TEXTURES"][name] for name in room_texture_names}

    assert not {params["pattern"] for params in room_textures.values()} & forbidden_patterns
    assert {params.get("palette") for params in room_textures.values()} == {"scroom"}
    assert all(int(params.get("size", 0)) >= 128 for params in room_textures.values())
    assert "cmp_floor" not in wad_module["TEXTURES"]
    assert "cmp_ceil" not in wad_module["TEXTURES"]
    assert room_textures["void_floor"]["pattern"] == "hidden_void_shell"
    assert room_textures["void_ceil"]["pattern"] == "hidden_void_shell"
    assert room_textures["void_wall"]["pattern"] == "hidden_void_shell"
    assert room_textures["skip"]["pattern"] == "hidden_void_shell"
    assert room_textures["geom_mark"]["pattern"] == "geometry_signal_mark"
    assert room_textures["hex_floor"]["pattern"] == "geometry_signal_mark"
    assert room_textures["hex_ceil"]["pattern"] == "geometry_signal_mark"
    assert room_textures["hex_wall"]["pattern"] == "geometry_signal_mark"
    assert room_textures["stipple_floor"]["pattern"] == "geometry_signal_mark"
    assert room_textures["stipple_ceil"]["pattern"] == "geometry_signal_mark"
    assert room_textures["stipple_wall"]["pattern"] == "geometry_signal_mark"
    assert wad_module["build_scroom_palette"]()[:3] == b"\x00\x00\x00"
    hidden_pixels, _palette = wad_module["generate_pixel_data"](
        (0, 0, 0),
        0,
        128,
        128,
        seed=7,
        pattern="hidden_void_shell",
        palette_mode="scroom",
    )
    assert set(hidden_pixels) == {0}
    mark_pixels, _palette = wad_module["generate_pixel_data"](
        (4, 4, 6),
        0,
        128,
        128,
        seed=7,
        pattern="geometry_signal_mark",
        palette_mode="scroom",
    )
    mark_set = set(mark_pixels)
    assert len(mark_set) > 3
    assert 214 in mark_set
    assert 245 not in mark_set
    pixels, _palette = wad_module["generate_pixel_data"](
        (4, 4, 6),
        0,
        256,
        256,
        seed=7,
        pattern="hidden_void_shell",
        palette_mode="scroom",
    )
    assert set(pixels) == {0}
    assert "clean_room_homage_chrome" in info_contract["admissible_texture_types"]
    assert "quake_scenic_material" in info_contract["forbidden_material_semantics"]
    assert "A room texture can be named as a real-world material" in " ".join(
        info_contract["failure_predicates"]
    )
    for surface in surface_contracts["surfaces"]:
        assert surface["texture"] == "skip"
        assert surface["collision_texture"] == "skip"
        assert len(surface["visible_substrate_textures"]) == 2
        assert all(tex.startswith(("hex_", "stipple_")) for tex in surface["visible_substrate_textures"])
        assert min(surface["texture_scale"]) >= 3
        assert "material" not in surface["surface_kind"]


def test_screwm_review_geometry_keeps_wards_primary_not_architecture() -> None:
    source = (REPO_ROOT / "scripts" / "generate-screwm-map.py").read_text(encoding="utf-8")

    assert "No free-standing columns in the reviewable scroom baseline" in source
    assert "Wall bands are deferred" in source
    assert "The duplicate deep ward lattice is disabled" in source
    assert "REVIEW_ALCOVE_Y_MIN" in source
    assert "WARD_GARDEN_LAYOUT" in source
    assert "AOA_Y = -555" in source
    assert "AOA_HEIGHT_M = 7.0" in source
    assert "AOA_RUNTIME_SCALE = 1.0" in source
    assert "TOWER_CEIL_M = TOWER_FLOOR_M + (BASE_TOWER_CEIL_M - TOWER_FLOOR_M) * 2.0" in source
    assert "REVIEW_DRIFT_Y = AOA_Y - 45" in source
    assert "WARD_FRAME_PAD = 6" in source
    assert "WARD_FRAME_T = 4" in source
    assert "WARD_DEPTH_PLANES" in source
    assert "Deferred while establishing the clean live-media Scroom baseline" in source
    assert "aoa_payload_panes" in source
    assert "scroom_scene_graph_bands" in source
    assert "scroom_material_field" in source
    assert "scroom_local_effect_lenses" in source
    assert "scroom_room_grid" in source
    assert "scroom_hex_grid_and_stipple" in source
    assert "scroom_drift_receiver_strips" in source
    assert "Disabled: drift receiver evidence must be carried by the shell/grid geometry" in source
    assert "inward_x_normal" in source
    assert "inward_y_normal" in source
    assert "offset_span" in source
    assert "pane_light_origin" in source
    assert 'vis_cmd.insert(1, "-fast")' in source
    assert "--full-vis" in source
    assert "SCROOM_PATH_STONES" in source
    assert "SCROOM_GARDEN_LANTERNS" in source
    assert "AOA_SPHERE_FACE_SIZE" in source
    assert "AOA_SPHERE_STRIP_COUNT = 0" in source
    assert '"_minlight" "16"' in source
    assert '"_minlight_color" "0.12 0.14 0.18"' in source
    assert "scene_quad.wgsl" in source
    assert "No diagnostic floor crosshair" in source
    assert "No physical drift graph stones" in source
    assert "Do not instantiate diagnostic path stones" in source
    assert 'base = int(preset.get("wall_light", 100) * 1.25)' in source


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
    assert module["BASELINE_SOURCE_ROLES"] == set(roles)
    assert content.count("// source-garden-anchor ") == 6
    assert content.count("// speech-waveform ") == 1
    assert content.count("// source-garden-anchor-frame ") == 0
    assert content.count("// speech-waveform-frame ") == 0
    assert content.count("// source-garden-anchor-mount-") == 0
    assert content.count("// speech-waveform-mount-") == 0
    assert content.count("// source-anchor ") == 0
    assert content.count("// source-glow ") == 0
    assert content.count("// source-tether ") == 0
    assert content.count("// source-light ") == 6
    assert content.count("// speech-waveform-light ") == 1
    assert "// section: source-camera-constellation" in content
    assert "// section: speech-waveform" in content
    assert "// source-garden-anchor 06: c920-overhead cam_cov" in content
    assert "// speech-waveform 01: hapax-speech speech_wave" in content
    assert "cam_bop" in content
    assert "cam_cov" in content
    assert "speech_wave" in content
    assert "cam_bop 5990 1085 0 0.4 0.4" in content
    assert module["SOURCE_ANCHORS"][0]["w"] == 512
    assert module["SOURCE_ANCHORS"][0]["h"] == 288
    assert module["SOURCE_ANCHORS"][3]["w"] == 512
    assert module["SOURCE_ANCHORS"][3]["h"] == 288
    assert module["SOURCE_ANCHORS"][0]["texture_size"] == (1280, 720)
    assert module["SOURCE_ANCHORS"][0]["texture_transform"] == {
        "u_sign": 1,
        "v_sign": 1,
        "rotation": 0,
        "surface_local": True,
        "reason": "Left-wall x-facing inward BSP face must use surface-local UV origin; otherwise world-space coordinates wrap the live camera frame",
    }
    assert module["SOURCE_ANCHORS"][3]["texture_transform"] == {
        "u_sign": -1,
        "v_sign": 1,
        "rotation": 0,
        "surface_local": True,
        "reason": "Right-wall x-facing inward BSP face mirrors camera handedness; surface-local u flip preserves the source orientation",
    }
    assert {pane[0] for pane in module["SCROOM_SCENE_GRAPH_PANES"]} >= {"camera-source"}
    assert "hls" not in {pane[0] for pane in module["SCROOM_SCENE_GRAPH_PANES"]}
    assert module["MEDIA_MOUNT_CONTRACTS"]["version"] == "screwm-quake-media-mounts-v1"
    assert module["WARD_ATLAS_MOUNT"]["texture"] == "ward_atlas"
    assert module["SPEECH_WAVE_MOUNT"]["texture"] == "speech_wave"
    assert module["SPEECH_WAVE_ANCHOR"]["w"] == 384
    assert module["SPEECH_WAVE_ANCHOR"]["h"] == 96
    assert module["SPEECH_WAVE_ANCHOR"]["pos"] == (-80, -555, 104)
    assert module["SPEECH_WAVE_ANCHOR"]["texture_size"] == (512, 128)
    assert module["SPEECH_WAVE_ANCHOR"]["texture_transform"] == {
        "u_sign": 1,
        "v_sign": 1,
        "rotation": 0,
        "surface_local": True,
        "reason": "OARB-depth y-facing waveform uses surface-local mapping so the live oscilloscope spans the receiver once without world-space tiling",
    }
    assert module["MEDIA_MOUNTS_BY_ID"]["grounding-provenance-ticker"]["texture"] == "w09"
    assert module["MEDIA_MOUNTS_BY_ID"]["grounding-provenance-ticker"]["texture_transform"] == {
        "u_sign": 1,
        "v_sign": 1,
        "rotation": 180,
        "surface_local": True,
        "reason": "Quake y-facing BSP text basis requires surface-local origin plus 180-degree rotation; vertical precompensation belongs to the producer",
    }
    assert module["MEDIA_MOUNTS_BY_ID"]["grounding-provenance-ticker"]["producer_pretransform"] == {
        "flip_y": True,
        "reason": "Mount-space ticker pixels are vertically preflipped so the stable DarkPlaces BSP mapping reads upright",
    }
    assert module["MEDIA_MOUNTS_BY_ID"]["precedent-ticker"]["texture"] == "w22"
    assert module["MEDIA_MOUNTS_BY_ID"]["chronicle-ticker"]["texture"] == "w27"


def test_screwm_live_media_panes_have_one_truth_bearing_face_without_visible_backing() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    content = module["generate_map"](module["MODE_PRESETS"]["rnd"])

    for idx, source in enumerate(module["SOURCE_ANCHORS"], start=1):
        role = source["role"]
        tex = source["texture"]
        source_pane = _comment_block(content, f"// source-garden-anchor {idx:02d}: {role} {tex}")

        assert source_pane.count(tex) == 2
        assert source_pane.count(module["MEDIA_RECEIVER_EDGE_TEX"]) == 5

    speech_pane = _comment_block(content, "// speech-waveform 01: hapax-speech speech_wave")
    assert speech_pane.count("speech_wave") == 2
    assert speech_pane.count(module["MEDIA_RECEIVER_EDGE_TEX"]) == 5

    for idx, tex in ((9, "w09"), (22, "w22"), (27, "w27")):
        name = module["WARD_ANCHORS"][idx - 1]
        ticker_pane = _comment_block(content, f"// ward-garden-pane {idx:02d}: {name} {tex}")

        assert ticker_pane.count(tex) == 2
        assert ticker_pane.count(module["MEDIA_RECEIVER_EDGE_TEX"]) == 5

    assert content.count("// ward-garden-pane-mount-") == 0
    assert content.count("// source-garden-anchor-mount-") == 0
    assert content.count("// speech-waveform-mount-") == 0
    assert "status-spine" not in content
    assert "standoff-" not in content


def test_live_media_textures_are_self_lit_information_surfaces() -> None:
    shader = (REPO_ROOT / "assets/quake/scripts/hapax_live_media.shader").read_text()
    live_names = [
        "w05",
        "ward_atlas",
        "w09",
        "w22",
        "w27",
        "cam_bop",
        "cam_brm",
        "cam_bsy",
        "cam_cdk",
        "cam_crm",
        "cam_cov",
        "speech_wave",
    ]
    for name in live_names:
        block_start = shader.index(f"{name}\n{{")
        next_block = min(
            [
                idx
                for idx in (
                    shader.find(f"\n{candidate}\n{{", block_start + 1) for candidate in live_names
                )
                if idx != -1
            ]
            or [len(shader)]
        )
        block = shader[block_start:next_block]
        assert "surfaceparm nolightmap" in block
        assert "surfaceparm nomarks" in block
        assert "surfaceparm nonsolid" in block
        assert "dpnoshadow" in block
        assert f"map {name}" in block
        assert "rgbgen const" in block


def test_spatiotemporal_framework_makes_media_ethics_operational() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    framework = module["SPATIOTEMPORAL_FRAMEWORK"]
    media = framework["media_constraints"]
    media_theory = framework["media_theory_constraints"]
    anti = framework["anti_parasocial_constraints"]

    for field in ("freshness", "consent_or_license", "purpose"):
        assert field in media["required_mount_fields"]
    for field in ("mount_kind", "substrate", "surface", "hybrid_contract"):
        assert field in media["required_mount_fields"]
    assert "drift_interaction" in media["required_mount_fields"]
    for field in (
        "visible_border",
        "visible_backing_panel",
        "visible_grid_background",
        "physical_chrome",
        "edge_faces",
        "stale_texture_style",
        "size_policy",
    ):
        assert field in media["required_flat_mount_fields"]
    assert set(media["required_hybrid_contract_fields"]) == {
        "quake_binding",
        "producer_binding",
        "memory_format",
        "update_semantics",
        "aspect_policy",
        "compositor_role",
    }
    assert media_theory["screens_are_spatial_objects_not_windows"] is True
    assert media_theory["remediation_contract_required"] is True
    assert media_theory["homage_technology_must_remain_swappable"] is True
    assert media_theory["material_profile_binding_required"] is True
    assert media_theory["drift_interaction_required_for_entity_substance"] is True
    assert anti["spatialized_presence_required"] is True
    assert anti["object_of_attention_discipline_required"] is True
    assert anti["viewer_agency_targets_space_or_object_not_personality"] is True
    assert anti["max_face_dominant_camera_wards_per_pause_view"] == 1

    for mount in module["MEDIA_MOUNT_CONTRACTS"]["mounts"]:
        assert mount["drift_interaction"]["owner"]
        for field in anti["required_source_context"]:
            assert field in mount
        if mount["projection"].startswith("flat"):
            assert mount["visible_border"] is False
            assert mount["visible_backing_panel"] is False
            assert mount["visible_grid_background"] is False
            assert mount["physical_chrome"] == "forbidden"
            assert mount["edge_faces"] == "hidden_or_zero_contrast"
            assert mount["stale_texture_style"] == "borderless_quiet_void"
            assert "legibility" in mount["size_policy"]


def test_aoa_model_transform_stands_pyramid_upright_and_centers_media_front() -> None:
    module = _load_script("scripts/generate-aoa-mdl.py")

    transformed_root = module["transform_vertices"](module["AOA_ROOT_MODEL_VERTICES"])
    base_z = [vertex[2] for vertex in transformed_root[:3]]
    apex_z = transformed_root[3][2]
    center = module["tetrahedron_incenter"](transformed_root)

    assert max(base_z) - min(base_z) < 0.000001
    assert apex_z > base_z[0]
    assert max(abs(component) for component in center) < 0.000001

    faces = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]
    root_inradius = min(
        abs(
            sum(
                module["face_normal"](
                    transformed_root[face[0]],
                    transformed_root[face[1]],
                    transformed_root[face[2]],
                )[axis]
                * transformed_root[face[0]][axis]
                for axis in range(3)
            )
        )
        for face in faces
    )
    inner_void_inradius = module["aoa_inner_void_inradius"]()
    derived_scale = module["derived_aoa_model_scale"]()
    edge_lengths = [
        math.dist(transformed_root[i], transformed_root[j])
        for i in range(4)
        for j in range(i + 1, 4)
    ]
    assert max(edge_lengths) - min(edge_lengths) < 0.000001
    assert module["DEPTH"] == 4
    assert module["AOA_LEAF_FACE_EDGE_UNITS"] == 48
    assert module["SCALE"] == 768
    assert module["aoa_face_count"]() == 1024

    parts = module["compose_aoa_parts"](module["DEPTH"])
    surface_verts, surface_faces, surface_uvs = module["flatten_aoa_surface_mesh"](parts)
    assert len(parts) == 4**module["DEPTH"]
    assert len(surface_faces) == module["aoa_face_count"]()
    assert len(surface_verts) == len(surface_uvs) == module["aoa_face_count"]() * 3
    assert module["AOA_SKIN_W"] == module["AOA_SKIN_H"] == 2048

    # The OARB is a perfect insphere of the first central octahedral void.
    world_inradius = inner_void_inradius * module["SCALE"] * derived_scale
    world_sphere_radius = (
        module["ATTENDANT_SPHERE_RADIUS"] * module["SCALE"] * module["AOA_SPHERE_MODEL_SCALE"]
    )
    assert derived_scale == 1.0
    assert abs(world_inradius - world_sphere_radius) < 0.001
    assert module["ATTENDANT_SPHERE_CLEARANCE_RATIO"] == 1.0
    assert inner_void_inradius <= root_inradius

    sphere_vertices, _sphere_faces, sphere_uvs = module["media_sphere_mesh"](1.0, 4, 4)
    center_index = 2 * (4 + 1) + 2
    front = sphere_vertices[center_index]

    assert sphere_uvs[center_index] == (0.5, 0.5)
    assert abs(front[0]) < 0.000001
    assert front[1] < -0.999999
    assert abs(front[2]) < 0.000001


def test_screwm_map_inventory_matches_default_non_darkplaces_sources() -> None:
    module = _load_script("scripts/generate-screwm-map.py")
    default_layout = json.loads(
        (REPO_ROOT / "config" / "compositor-layouts" / "default.json").read_text(encoding="utf-8")
    )
    default_sources = {source["id"] for source in default_layout["sources"]} - {"darkplaces"}
    default_sources.discard("sierpinski")
    default_sources.add("aoa_oarb_state")

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


def test_screwm_wad_defines_only_declared_live_ward_receiver_textures() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    ward_textures = [name for name in textures if name.startswith("w") and name[1:].isdigit()]
    assert ward_textures == ["w05", "w09", "w22", "w27"]
    assert module["ACTIVE_WARD_TEXTURES"] == {"w05", "w09", "w22", "w27"}
    assert module["generate_pixel_data"].__defaults__[1] == "void_substrate"
    assert textures["ward_atlas"]["pattern"] == "live_media"
    assert textures["ward_atlas"]["width"] == 2048
    assert textures["ward_atlas"]["height"] == 2304
    assert len(module["WARD_TEXTURE_TYPES"]) == 36
    assert textures["w09"]["pattern"] == "live_media"
    assert textures["w09"]["width"] == 1344
    assert textures["w09"]["height"] == 176
    assert textures["w09"]["code"] == "GROUND"
    assert textures["w05"]["pattern"] == "live_media"
    assert textures["w05"]["width"] == 960
    assert textures["w05"]["height"] == 540
    assert textures["w05"]["code"] == "REV"
    assert textures["w22"]["pattern"] == "live_media"
    assert textures["w22"]["width"] == 1344
    assert textures["w22"]["height"] == 176
    assert textures["w22"]["code"] == "PRECED"
    assert textures["w27"]["pattern"] == "live_media"
    assert textures["w27"]["width"] == 1344
    assert textures["w27"]["height"] == 176
    assert textures["w27"]["code"] == "CHRON"
    assert textures["speech_wave"]["pattern"] == "live_media"
    assert textures["speech_wave"]["width"] == 512
    assert textures["speech_wave"]["height"] == 128
    assert textures["speech_wave"]["code"] == "VOICE"
    assert len(module["WARD_ACCENT_INDICES"]) >= 4
    assert textures["drift_c"]["pattern"] == "drift_line"
    assert textures["drift_r"]["drift"] == 186
    assert "cmp_floor" not in textures
    assert "cmp_ceil" not in textures
    assert textures["void_floor"]["pattern"] == "hidden_void_shell"
    assert textures["void_ceil"]["pattern"] == "hidden_void_shell"
    assert textures["void_wall"]["pattern"] == "hidden_void_shell"
    assert textures["skip"]["pattern"] == "hidden_void_shell"
    assert textures["geom_mark"]["pattern"] == "geometry_signal_mark"
    assert textures["hex_floor"]["pattern"] == "geometry_signal_mark"
    assert textures["hex_ceil"]["pattern"] == "geometry_signal_mark"
    assert textures["hex_wall"]["pattern"] == "geometry_signal_mark"
    assert textures["stipple_floor"]["pattern"] == "geometry_signal_mark"
    assert textures["stipple_ceil"]["pattern"] == "geometry_signal_mark"
    assert textures["stipple_wall"]["pattern"] == "geometry_signal_mark"
    assert textures["void_floor"]["size"] == 128
    assert textures["void_ceil"]["size"] == 128
    assert textures["void_wall"]["size"] == 128
    assert textures["skip"]["size"] == 128
    assert textures["geom_mark"]["size"] == 128
    assert textures["hex_floor"]["size"] == 128
    assert textures["hex_ceil"]["size"] == 128
    assert textures["hex_wall"]["size"] == 128
    assert textures["stipple_floor"]["size"] == 128
    assert textures["stipple_ceil"]["size"] == 128
    assert textures["stipple_wall"]["size"] == 128
    assert textures["void_floor"]["palette"] == "scroom"
    assert textures["void_ceil"]["palette"] == "scroom"
    assert textures["void_wall"]["palette"] == "scroom"
    assert textures["skip"]["palette"] == "scroom"
    assert textures["geom_mark"]["palette"] == "scroom"
    assert textures["hex_floor"]["palette"] == "scroom"
    assert textures["hex_ceil"]["palette"] == "scroom"
    assert textures["hex_wall"]["palette"] == "scroom"
    assert textures["stipple_floor"]["palette"] == "scroom"
    assert textures["stipple_ceil"]["palette"] == "scroom"
    assert textures["stipple_wall"]["palette"] == "scroom"
    identifiable_material_patterns = {
        "stone_blocks",
        "worn_stone",
        "dark_ceiling",
        "brushed_metal",
        "carved_stone",
        "metal_grate",
        "dark_ornate",
        "polished_stone",
    }
    default_surface_textures = {
        "city4_2",
        "ground1_6",
        "sky4",
        "metal5_2",
        "scroom",
        "void_floor",
        "void_ceil",
        "void_wall",
        "skip",
        "geom_mark",
        "hex_floor",
        "hex_ceil",
        "hex_wall",
        "stipple_floor",
        "stipple_ceil",
        "stipple_wall",
        "r_percep",
        "r_cognit",
        "r_comm",
        "r_express",
        "r_ground",
        "s_percep",
        "s_cognit",
        "s_comm",
        "s_express",
        "s_ground",
    }
    assert {textures[name]["pattern"] for name in default_surface_textures}.isdisjoint(
        identifiable_material_patterns
    )


def test_screwm_wad_defines_camera_source_anchor_textures() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    source_names = [name for name, _code, _accent in module["CAMERA_SOURCE_TEXTURES"]]
    assert source_names == ["cam_bop", "cam_brm", "cam_bsy", "cam_cdk", "cam_crm", "cam_cov"]
    assert all(textures[name]["pattern"] == "source_portal" for name in source_names)
    assert textures["cam_bop"]["code"] == "BRIOOP"
    assert textures["cam_bop"]["width"] == 1280
    assert textures["cam_bop"]["height"] == 720
    assert textures["cam_bsy"]["accent"] == 186
    assert textures["cam_cov"]["code"] == "C920OVH"


def test_screwm_wad_defines_speech_waveform_texture() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    speech_names = [name for name, _code, _accent in module["SPEECH_WAVE_TEXTURES"]]
    assert speech_names == ["speech_wave"]
    assert textures["speech_wave"]["pattern"] == "live_media"
    assert textures["speech_wave"]["code"] == "VOICE"
    assert textures["speech_wave"]["width"] == 512
    assert textures["speech_wave"]["height"] == 128


def test_screwm_wad_defines_aoa_oarb_slot_textures() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    slot_names = [name for name, _code, _accent in module["LEGACY_SLOT_TEXTURES"]]
    assert slot_names == ["slot_aoa", "slot_album", "slot_rev", "slot_voice"]
    assert all(textures[name]["pattern"] == "legacy_slot" for name in slot_names)
    assert textures["slot_aoa"]["code"] == "OARB"
    assert textures["slot_album"]["accent"] == 186
    assert textures["slot_voice"]["code"] == "VOICE"


def test_screwm_wad_defines_current_aoa_payload_pane_textures() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    pane_names = [name for name, _code, _accent in module["AOA_PANE_TEXTURES"]]
    assert pane_names == [
        "aoa_root",
        "aoa_tri",
        "aoa_data",
        "aoa_glyph",
        "aoa_edge",
        "aoa_lod",
        "aoa_priv",
        "aoa_src",
        "aoa_comp",
        "aoa_gate",
    ]
    assert all(textures[name]["pattern"] == "aoa_pane" for name in pane_names)
    assert textures["aoa_root"]["code"] == "ROOT"
    assert textures["aoa_data"]["accent"] == 198
    assert textures["aoa_gate"]["code"] == "GATE"
    assert [name for name, _code, _accent in module["AOA_SPHERE_TEXTURES"]] == ["aoa_media_sphere"]
    assert textures["aoa_media_sphere"]["pattern"] == "aoa_sphere"
    assert textures["aoa_media_sphere"]["code"] == "MEDIA"
    assert textures["aoa_media_sphere"]["accent"] == 236
    assert textures["aoa_media_sphere"]["width"] == 2048
    assert textures["aoa_media_sphere"]["height"] == 1024


def test_screwm_wad_defines_scene_quad_effect_lens_textures() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    textures = module["TEXTURES"]

    effect_names = [name for name, _code, _accent, _effect in module["LOCAL_EFFECT_TEXTURES"]]
    assert effect_names == [
        "fx_mirr",
        "fx_kale",
        "fx_warp",
        "fx_fish",
        "fx_xfrm",
        "fx_disp",
        "fx_dros",
        "fx_tunn",
        "fx_tile",
        "fx_drif",
        "fx_brea",
    ]
    assert all(textures[name]["pattern"] == "effect_lens" for name in effect_names)
    assert textures["fx_mirr"]["effect"] == "mirror"
    assert textures["fx_kale"]["effect"] == "kaleidoscope"
    assert textures["fx_brea"]["code"] == "BRETH"


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


def test_source_portal_texture_is_borderless_quiet_fallback() -> None:
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

    width = module["TEX_SIZE"]
    assert pixels[0] <= 1
    assert pixels[width - 1] <= 1
    assert pixels[-width] <= 1
    assert pixels[-1] <= 1
    assert max(pixels) < 214
    assert min(pixels) == 0
    assert pixels.count(214) == 0
    assert sum(1 for pixel in pixels if pixel > 40) > 0


def test_aoa_oarb_slot_texture_has_legible_code() -> None:
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


def test_current_aoa_payload_pane_texture_has_pane_local_triangle() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    pixels, _palette = module["generate_pixel_data"](
        (56, 70, 74),
        0,
        module["TEX_SIZE"],
        module["TEX_SIZE"],
        pattern="aoa_pane",
        code="GATE",
        accent=202,
    )

    assert max(pixels) >= 232
    assert min(pixels) <= 34
    assert pixels.count(202) > 90


def test_aoa_attendant_sphere_texture_has_media_face_signal() -> None:
    module = _load_script("scripts/generate-screwm-wad.py")
    pixels, _palette = module["generate_pixel_data"](
        (56, 70, 74),
        0,
        module["TEX_SIZE"],
        module["TEX_SIZE"],
        pattern="aoa_sphere",
        code="YT",
        accent=214,
    )

    assert max(pixels) >= 232
    assert min(pixels) <= 12
    assert pixels.count(214) > 120
