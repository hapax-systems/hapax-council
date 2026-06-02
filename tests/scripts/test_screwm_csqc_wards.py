from __future__ import annotations

import runpy
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CSQC_DIR = REPO_ROOT / "assets" / "quake" / "csqc"
QC_DIR = REPO_ROOT / "assets" / "quake" / "qc"
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install-darkplaces-screwm-assets.sh"
AUTOEXEC = REPO_ROOT / "assets" / "quake" / "config" / "autoexec.cfg"


def _load_script(path: str) -> dict:
    return runpy.run_path(str(REPO_ROOT / path), run_name="__test__")


def test_csqc_sources_define_all_legacy_ward_labels() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert "CSQC_UpdateView" in body
    assert "cs_project" in body
    assert "adddynamiclight" in body
    assert 'cvar("screwm_csqc_overlay") > 0' in body
    assert body.count("screwm_draw_ward_label(") == 36
    assert body.count("screwm_draw_ward_detail(") == 36
    for ordinal in range(1, 37):
        assert f'"{ordinal:02d}"' in body
        assert f"data/ward-{ordinal:02d}.txt" in body
        assert f"screwm_w{ordinal:02d}" in body


def test_csqc_text_overlay_is_not_the_default_ward_surface() -> None:
    autoexec = AUTOEXEC.read_text(encoding="utf-8")
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert "set screwm_csqc_overlay 0" in autoexec
    assert "set screwm_csqc_lightfield 1" in autoexec
    assert "set screwm_csqc_diagnostic_lightfield 0" in autoexec
    assert "set screwm_csqc_effect_lightfield 1" in autoexec
    assert "set screwm_review_fill_light 1" in autoexec
    assert "set screwm_csqc_material_field 1" in autoexec
    assert "set screwm_csqc_theatre_spots 0" in autoexec
    assert "set screwm_csqc_surface_grid_overlay 0" in autoexec
    assert "set screwm_csqc_roaming_surface_pulses 0" in autoexec
    assert "r_ambient 8" in autoexec
    assert "r_fullbright_directed 1" in autoexec
    assert "r_shadow_realtime_dlightshadows 1" in autoexec
    assert "set screwm_csqc_full_expression_field 1" in autoexec
    assert "set screwm_csqc_shadow_budget 1" in autoexec
    assert "Ward identity belongs to the scroom geometry" in autoexec
    assert "screwm_effect_lightfield_enabled" in body
    assert "screwm_shadow_budget_enabled" in body
    assert 'cvar("screwm_csqc_effect_lightfield") > 0' in body
    assert 'cvar("screwm_review_fill_light") > 0' in body
    assert "adddynamiclight('0 -555 250'" in body
    assert "92 + screwm_energy * 34" in body
    assert "screwm_add_ward_light('-900 -2360 130'" in body
    assert "screwm_add_ward_light('-1180 -600 330'" in body


def test_aoa_entities_can_participate_in_shadowed_lightfield() -> None:
    body = (QC_DIR / "world.qc").read_text(encoding="utf-8")

    assert "EF_DYNAMICMODELLIGHT" in body
    assert "ent.effects = EF_DOUBLESIDED + EF_DYNAMICMODELLIGHT;" in body
    assert "EF_FULLBRIGHT +" not in body
    assert "EF_NOSHADOW" not in body


def test_csqc_dynamic_lights_cover_all_physical_ward_panes() -> None:
    map_module = _load_script("scripts/generate-screwm-map.py")
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert body.count("screwm_add_ward_light('") == 36
    assert body.count('screwm_read_norm("data/ward-active-') == 36
    assert body.count('screwm_read_norm("data/ward-presence-') == 36
    assert "active * 118" in body
    assert "presence * 96" in body
    assert "activity = screwm_clamp(active + presence * 0.70" in body
    assert "screwm_clamp(radius, 28, 158)" in body
    assert 'screwm_read_norm("data/audio-rms.txt")' in body
    assert "screwm_audio_onset * 26" in body
    assert 'screwm_read_norm("data/homage-quake-active.txt")' in body
    assert "homage_boost = screwm_homage_quake" in body
    assert 'cvar("screwm_csqc_lightfield") < 0' in body
    assert 'screwm_read_norm("data/ward-property-depth-pressure.txt")' in body
    assert "screwm_add_ward_property_field_lights" in body
    assert "screwm_ward_property_depth_pressure * 82" in body
    assert "screwm_ward_property_drift_pressure * 106" in body

    for idx in range(1, 37):
        x, y, z = map_module["ward_review_position"](idx)
        assert f"screwm_add_ward_light('{x} {y} {z}'" in body
        assert f"screwm_active_{idx:02d}" in body
        assert f"screwm_presence_{idx:02d}" in body


def test_csqc_dynamic_lights_cover_physical_drift_graph() -> None:
    map_module = _load_script("scripts/generate-screwm-map.py")
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")
    color_vars = {
        "drift_c": "screwm_cyan",
        "drift_a": "screwm_amber",
        "drift_r": "screwm_rose",
        "drift_g": "screwm_green",
    }

    assert body.count("screwm_add_drift_light('") == len(map_module["DRIFT_LINKS"])
    assert "activity * 58" in body
    assert "screwm_audio_onset * 34" in body
    assert "screwm_homage_transition * 26" in body

    for idx, (src, dst, texture) in enumerate(map_module["DRIFT_LINKS"], start=1):
        x, y, z = map_module["ward_review_drift_midpoint"](src, dst)
        assert (
            f"screwm_add_drift_light('{x} {y} {z}', {idx}, {color_vars[texture]}, "
            f"screwm_active_{src:02d}, screwm_active_{dst:02d});"
        ) in body


def test_csqc_source_anchors_carry_live_camera_scalars() -> None:
    map_module = _load_script("scripts/generate-screwm-map.py")
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert body.count('screwm_read_norm("data/source-priority-') == 6
    assert body.count('screwm_read_norm("data/source-fresh-') == 6
    assert body.count("screwm_add_source_light('") == 6
    assert "fresh * 84" in body

    for idx, source in enumerate(map_module["SOURCE_ANCHORS"], start=1):
        x, y, z = source["pos"]
        assert f"screwm_add_source_light('{x} {y} {z}'" in body
        assert f"screwm_source_priority_{idx:02d}" in body
        assert f"screwm_source_fresh_{idx:02d}" in body


def test_csqc_content_source_manifests_live_on_source_planes() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert 'screwm_read_norm("data/content-source-count.txt")' in body
    for ordinal in range(1, 7):
        assert f'screwm_read_norm("data/content-source-fresh-{ordinal:02d}.txt")' in body
        assert f'screwm_read_norm("data/content-source-opacity-{ordinal:02d}.txt")' in body
        assert f'screwm_read_norm("data/content-source-area-{ordinal:02d}.txt")' in body
        assert f"screwm_content_fresh_{ordinal:02d}" in body
        assert f"screwm_content_opacity_{ordinal:02d}" in body
        assert f"screwm_content_area_{ordinal:02d}" in body

    assert (
        "void(vector org, float idx, vector color, float fresh, float opacity, float area) screwm_add_content_source_light"
        in body
    )
    assert "fresh * 78 + opacity * 46 + area * 42" in body
    assert "screwm_content_source_count * 16" in body
    assert "void() screwm_add_media_source_signal_lights" in body
    assert "screwm_add_content_source_light('-1580 -2140 290', 1" in body
    assert "screwm_add_content_source_light('1580 -500 300', 6" in body


def test_csqc_aoa_panes_and_scroom_scene_graph_carry_live_lightfields() -> None:
    map_module = _load_script("scripts/generate-screwm-map.py")
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert body.count('screwm_read_norm("data/aoa-pane-signal-') == 10
    assert body.count("screwm_add_aoa_pane_light('") == len(map_module["AOA_PAYLOAD_PANES"])
    assert "void() screwm_add_aoa_pane_signal_lights" in body
    assert body.count("screwm_add_aoa_pane_signal_lights();") == 2
    assert "signal * 92" in body
    assert "screwm_homage_transition * 20" in body

    for idx, (_name, _tex, _frame_tex, dx, dz, _opacity) in enumerate(
        map_module["AOA_PAYLOAD_PANES"], start=1
    ):
        x = map_module["AOA_X"] + dx
        y = map_module["AOA_Y"] - 42
        z = map_module["AOA_Z"] + dz
        assert f"screwm_add_aoa_pane_light('{x} {y} {z}', {idx}" in body
        assert f"screwm_aoa_pane_{idx:02d}" in body

    assert body.count("screwm_add_scene_graph_light('") == len(
        map_module["SCROOM_SCENE_GRAPH_PANES"]
    )
    assert "signal * 64 + fresh * 52" in body

    for idx, (_band, _name, _tex, _frame_tex, x, y, z, _w, _h) in enumerate(
        map_module["SCROOM_SCENE_GRAPH_PANES"], start=1
    ):
        assert f"screwm_add_scene_graph_light('{x} {y - 30} {z}', {idx}" in body


def test_csqc_homage_package_lives_in_scroom_lightfield() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert 'screwm_read_norm("data/homage-transition-energy.txt")' in body
    assert 'screwm_read_norm("data/homage-signature-intensity.txt")' in body
    assert "void() screwm_add_homage_lights" in body
    assert "if (screwm_homage_quake <= 0)" in body
    assert "adddynamiclight('0 -372 172'" in body
    assert "screwm_add_homage_lights();" in body


def test_csqc_reverie_material_fields_live_on_scroom_geometry() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert 'screwm_read_norm("data/reverie-temporal.txt")' in body
    assert 'screwm_read_norm("data/reverie-spectral.txt")' in body
    assert 'screwm_read_norm("data/reverie-material.txt")' in body
    assert 'screwm_read_norm("data/reverie-thermal.txt")' in body
    assert "void() screwm_add_material_field_lights" in body
    assert "material_field = screwm_reverie_material" in body
    assert "spectral_field = screwm_reverie_spectral" in body
    assert "temporal_field = screwm_reverie_temporal" in body
    assert "thermal_field = screwm_reverie_thermal" in body
    assert 'cvar("screwm_csqc_material_field") <= 0' in body
    assert "adddynamiclight('0 -620 326'" in body
    assert "adddynamiclight('0 -588 252'" in body
    assert "adddynamiclight('-180 -595 300'" in body
    assert "adddynamiclight('180 -595 260'" in body
    assert "adddynamiclight('-120 -650 104'" in body
    assert "screwm_add_material_field_lights();" in body


def test_csqc_visual_layer_state_lives_in_scroom_lightfield() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    for ordinal in range(1, 9):
        assert f'screwm_read_norm("data/visual-zone-{ordinal:02d}.txt")' in body
        assert f"screwm_visual_zone_{ordinal:02d}" in body

    assert 'screwm_read_norm("data/visual-display-state.txt")' in body
    assert 'screwm_read_norm("data/visual-stance.txt")' in body
    assert 'screwm_read_norm("data/visual-ambient-turbulence.txt")' in body
    assert 'screwm_read_norm("data/stimmung-health.txt")' in body
    assert 'screwm_read_norm("data/stimmung-resource.txt")' in body
    assert 'screwm_read_norm("data/stimmung-error.txt")' in body
    assert (
        "void(vector org, float idx, vector color, float signal) screwm_add_visual_zone_light"
        in body
    )
    assert "void() screwm_add_visual_layer_lights" in body
    assert "signal * 84 + screwm_visual_display * 28" in body
    assert "screwm_visual_stance * 90" in body
    assert "screwm_stimmung_error * 86" in body
    assert "screwm_add_visual_zone_light('-300 -548 340', 1" in body
    assert "screwm_add_visual_zone_light('300 -548 340', 8" in body
    assert "screwm_add_visual_layer_lights();" in body


def test_csqc_visual_chain_and_effect_drift_live_in_scroom_lightfield() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    for ordinal in range(1, 10):
        assert f'screwm_read_norm("data/visual-chain-{ordinal:02d}.txt")' in body
        assert f"screwm_chain_{ordinal:02d}" in body

    for name in (
        "noise",
        "drift",
        "color",
        "feedback",
        "aperture",
        "param-pressure",
    ):
        assert f"data/visual-chain-{name}.txt" in body
    for name in (
        "pass-count",
        "active-ratio",
        "max-delta",
        "region-count",
        "tonal",
        "atmospheric",
        "temporal",
        "texture",
        "edge",
        "compositing",
        "density",
        "density-currency",
    ):
        assert f"data/effect-drift-{name}.txt" in body
    for name in (
        "mode-tonal",
        "mode-atmospheric",
        "mode-temporal",
        "mode-texture",
        "mode-edge",
        "mode-compositing",
    ):
        assert f"data/effect-drift-{name}.txt" in body

    assert (
        "void(vector org, float idx, vector color, float signal) screwm_add_visual_chain_light"
        in body
    )
    assert "void() screwm_add_visual_chain_lights" in body
    assert "signal * 96 + screwm_chain_param_pressure * 24" in body
    assert "screwm_effect_drift_active_ratio * 22" in body
    assert "screwm_chain_drift * 104 + screwm_effect_drift_atmospheric * 56" in body
    assert "screwm_effect_drift_region_count * 34" in body
    assert "screwm_effect_drift_compositing * 104" in body
    assert "void() screwm_add_expression_surface_lights" in body
    assert "screwm_effect_drift_density_currency * 0.32" in body
    assert "screwm_add_expression_surface_lights();" in body
    assert "screwm_add_visual_chain_light('-300 -526 74', 1" in body
    assert "screwm_add_visual_chain_light('300 -526 74', 9" in body
    assert "screwm_add_visual_chain_lights();" in body


def test_csqc_imagination_fragment_intent_lives_in_scroom_lightfield() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert 'screwm_read_norm("data/imagination-salience.txt")' in body
    assert 'screwm_read_norm("data/imagination-continuation.txt")' in body
    assert 'screwm_read_norm("data/imagination-material.txt")' in body
    for ordinal in range(1, 10):
        assert f'screwm_read_norm("data/imagination-dim-{ordinal:02d}.txt")' in body
        assert f"screwm_imagination_dim_{ordinal:02d}" in body

    assert "float(float target) screwm_imagination_material_weight" in body
    assert (
        "void(vector org, float idx, vector color, float signal) screwm_add_imagination_dim_light"
        in body
    )
    assert "void() screwm_add_imagination_intent_lights" in body
    assert "screwm_imagination_salience * 118" in body
    assert "screwm_imagination_continuation * 34" in body
    assert "screwm_imagination_material_weight(0.25)" in body
    assert "screwm_add_imagination_dim_light('-132 -602 284', 1" in body
    assert "screwm_add_imagination_dim_light('0 -602 238', 9" in body
    assert "screwm_add_imagination_intent_lights();" in body


def test_csqc_scene_quad_local_effects_live_on_scroom_lenses() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    for ordinal in range(1, 12):
        assert f'screwm_read_norm("data/local-effect-{ordinal:02d}.txt")' in body
        assert f"screwm_effect_{ordinal:02d}" in body

    assert (
        "void(vector org, float idx, vector color, float signal) screwm_add_local_effect_light"
        in body
    )
    assert "void() screwm_add_local_effect_lights" in body
    assert "screwm_reverie_temporal * 20" in body
    assert "screwm_reverie_material * 24" in body
    assert "void() screwm_add_shadow_budget_lights" in body
    assert "screwm_add_shadow_budget_lights();" in body
    shadow_body = body[body.index("void() screwm_add_shadow_budget_lights") :]
    shadow_body = shadow_body[: shadow_body.index("void() screwm_add_shader_plan_lights")]
    assert "screwm_add_scroom_baseline_lights();" in shadow_body
    assert "screwm_add_hex_grid_drift_lights();" in shadow_body
    assert "screwm_add_entry_substrate_drift_lights();" in shadow_body
    assert "screwm_add_expression_surface_lights();" in shadow_body
    assert "screwm_add_shadow_budget_edge_lights();" in shadow_body
    assert "screwm_add_aoa_drift_lights();" in shadow_body
    assert "screwm_add_world_edge_lattice_lights();" not in shadow_body
    assert "screwm_add_local_effect_lights();" not in shadow_body
    assert 'screwm_read_norm("data/shader-plan-pass-count.txt")' in body
    assert "void() screwm_add_shader_plan_lights" in body
    assert "screwm_shader_plan_pass_count * 78" in body
    assert "screwm_shader_plan_feedback * 112" in body
    assert "screwm_shader_plan_temporal_ratio * 126" in body
    assert "screwm_add_local_effect_light('-980 -1780 214', 1, screwm_cyan, screwm_effect_01)" in body
    assert "screwm_add_local_effect_light('0 -1320 512', 2, screwm_rose, screwm_effect_02)" in body
    assert "screwm_add_local_effect_light('1040 -1420 64', 6, screwm_rose, screwm_effect_06)" in body
    assert (
        "screwm_add_local_effect_light('760 720 148', 11, screwm_amber, screwm_effect_11)" in body
    )
    assert "screwm_add_local_effect_lights();" in body
    assert "screwm_add_shader_plan_lights();" in body


def test_csqc_effect_drift_targets_all_shell_geometry_and_edges() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert (
        "void(vector org, float idx, vector color, float signal, vector axis) screwm_add_world_edge_light"
        in body
    )
    assert "void() screwm_add_world_edge_lattice_lights" in body
    assert "void() screwm_add_shadow_budget_edge_lights" in body
    assert "screwm_effect_drift_edge * 1.20" in body
    assert "screwm_effect_mode_edge * 0.70" in body
    assert "screwm_effect_drift_density_currency * 0.55" in body
    assert "pulse * (86 + signal * 78" in body
    assert body.count("screwm_add_world_edge_light('") == 22
    assert "screwm_add_world_edge_lattice_lights();" in body
    assert "screwm_add_shadow_budget_edge_lights();" in body

    for anchor in (
        "screwm_add_world_edge_light('0 -2230 42'",
        "screwm_add_world_edge_light('-1620 -2450 58'",
        "screwm_add_world_edge_light('1620 -2450 58'",
        "screwm_add_world_edge_light('-1988 -1780 92'",
        "screwm_add_world_edge_light('1988 -1780 92'",
        "screwm_add_world_edge_light('0 -2070 1710'",
        "screwm_add_world_edge_light('-1560 -2220 1710'",
        "screwm_add_world_edge_light('1560 -2220 1710'",
        "screwm_add_world_edge_light('-1988 -1480 1710'",
        "screwm_add_world_edge_light('1988 -1480 1710'",
        "screwm_add_world_edge_light('-1990 -760 420'",
        "screwm_add_world_edge_light('1990 -760 420'",
        "screwm_add_world_edge_light('0 -2520 420'",
        "screwm_add_world_edge_light('0 1330 420'",
        "screwm_add_world_edge_light('-1420 1330 1710'",
        "screwm_add_world_edge_light('1420 1330 92'",
        "screwm_add_world_edge_light('-760 -590 124'",
        "screwm_add_world_edge_light('760 -590 124'",
        "screwm_add_world_edge_light('0 -590 446'",
        "screwm_add_world_edge_light('0 -590 70'",
        "screwm_add_world_edge_light('-1100 580 330'",
        "screwm_add_world_edge_light('1100 580 330'",
    ):
        assert anchor in body


def test_csqc_entry_substrate_drift_targets_floor_ceiling_entity_and_negative_space() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert "void() screwm_add_entry_substrate_drift_lights" in body
    assert "screwm_effect_drift_active_ratio <= 0.01" in body
    assert "screwm_effect_drift_active_ratio * 0.86" in body
    assert "screwm_effect_drift_active_effect_ratio * 0.56" in body
    assert "screwm_effect_drift_edge * 0.82" in body
    assert "screwm_effect_drift_texture * 0.48" in body
    assert "screwm_effect_drift_temporal * 0.42" in body
    assert "adddynamiclight('0 -2240 34'" in body
    assert "adddynamiclight('0 -2140 1718'" in body
    assert "adddynamiclight('0 -590 224'" in body
    assert "adddynamiclight('-1480 -2290 1614'" in body
    assert body.count("screwm_add_entry_substrate_drift_lights();") == 2
    assert "adddynamiclight('0 -2380 52'" in body
    assert "adddynamiclight('0 -2380 1710'" in body
    assert "adddynamiclight('920 -1020 1692'" in body
    assert body.index("screwm_add_entry_substrate_drift_lights();") < body.index(
        "screwm_add_aoa_drift_lights();"
    )
    assert body.rindex("screwm_add_entry_substrate_drift_lights();") < body.index(
        "screwm_add_world_edge_lattice_lights();"
    )


def test_csqc_surface_drift_is_geometry_lit_not_post_render_projected() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert "void() screwm_add_scroom_baseline_lights" in body
    assert "void() screwm_add_aoa_drift_lights" in body
    assert "void() screwm_add_hex_grid_drift_lights" in body
    assert "screwm_add_surface_drift_receivers" not in body
    assert "screwm_draw_surface_drift_edges" not in body
    assert "screwm_draw_surface_edge_line" not in body
    assert "drawfill(p + '-20 -11 0'" not in body
    assert "drawfill(p + '-34 8 0'" not in body
    assert 'R_BeginPolygon("textures/screwm/ground1_6", DRAWFLAG_ADDITIVE, 0);' not in body
    assert "drawline(width, pa, pb, color" not in body
    assert "void() screwm_draw_geometry_edge_pulses" in body
    assert "void() screwm_draw_hex_alignment_light_grid" in body
    assert "void(float z, float phase, float width, float alpha, float phase_bias) screwm_draw_hex_light_grid_plane" in body
    assert "void(float phase, float width, float alpha) screwm_draw_wall_light_grid_planes" in body
    assert "void() screwm_draw_media_receiver_drift_fields" in body
    assert "void() screwm_draw_substrate_drift_pulses" in body
    assert "void() screwm_draw_entry_threshold_substrate_pulses" in body
    assert 'R_BeginPolygon("geom_mark", DRAWFLAG_ADDITIVE, 0);' in body
    assert 'R_BeginPolygon("drift_c", DRAWFLAG_ADDITIVE, 0);' in body
    assert 'precache_pic("geom_mark");' in body
    assert 'precache_pic("drift_c");' in body
    assert 'precache_pic("textures/screwm/ground1_6");' not in body
    assert "void(float y, float cx, float cz, float length, float width, float angle, vector color, float alpha) screwm_draw_yz_wall_ribbon" in body
    pulse_body = body[
        body.index("void(vector a, vector b, vector c, vector d, vector color, float alpha) screwm_draw_geometry_quad")
        : body.index("void() screwm_add_shader_plan_lights")
    ]
    assert "cs_project" not in pulse_body
    assert "drawfill" not in pulse_body
    assert "drawline" not in pulse_body
    assert body.count("screwm_add_scroom_baseline_lights();") == 2
    assert body.count("screwm_add_aoa_drift_lights();") == 2
    assert body.count("screwm_add_hex_grid_drift_lights();") == 2
    assert body.count("screwm_add_entry_substrate_drift_lights();") == 2
    assert body.count("screwm_add_expression_surface_lights();") == 2
    assert body.count("screwm_add_shadow_budget_edge_lights();") == 1
    assert body.count("screwm_add_media_source_signal_lights();") == 2
    assert body.count("screwm_draw_hex_alignment_light_grid();") == 1
    assert body.count("screwm_draw_media_receiver_drift_fields();") == 1
    assert "screwm_roaming_surface_pulses_enabled" in body
    assert "screwm_surface_grid_overlay_enabled" in body
    assert 'cvar("screwm_csqc_surface_grid_overlay") > 0' in body
    assert 'cvar("screwm_csqc_roaming_surface_pulses") > 0' in body
    assert "adddynamiclight('0 -555 42'" in body
    assert "adddynamiclight('0 -555 1716'" in body
    assert "adddynamiclight('-1980 -555 430'" in body
    assert "adddynamiclight('1980 -555 430'" in body
    assert "adddynamiclight('0 -590 224'" in body
    assert "screwm_effect_drift_edge * 0.90" in body
    assert body.index("screwm_add_dynamic_lights();") < body.index("renderscene();")
    assert body.index("screwm_draw_hex_alignment_light_grid();") < body.index("renderscene();")
    update_view = body[body.index("void(float vid_width"): body.index('if (cvar("screwm_csqc_overlay")')]
    assert "if (screwm_roaming_surface_pulses_enabled())" in update_view
    assert update_view.index("screwm_draw_hex_alignment_light_grid();") < update_view.index(
        "if (screwm_roaming_surface_pulses_enabled())"
    )
    assert update_view.index("screwm_draw_hex_alignment_light_grid();") > update_view.index(
        "if (screwm_surface_grid_overlay_enabled())"
    )
    assert update_view.index("screwm_draw_media_receiver_drift_fields();") > update_view.index(
        "if (screwm_roaming_surface_pulses_enabled())"
    )
    assert update_view.index("screwm_draw_geometry_edge_pulses();") > update_view.index(
        "if (screwm_roaming_surface_pulses_enabled())"
    )
    assert update_view.index("screwm_draw_substrate_drift_pulses();") > update_view.index(
        "if (screwm_roaming_surface_pulses_enabled())"
    )
    assert "screwm_draw_xy_ribbon(0, -2260, -52" in body
    assert "screwm_draw_xy_ribbon(0, -2260, 1754" in body
    assert "ceiling_trace_width = screwm_clamp(18 + screwm_effect_drift_edge * 14" in body
    assert "ceiling_stipple_alpha = screwm_clamp(0.74 + pulse_b * 0.26" in body
    assert "ceiling_z = 1758;" in body
    assert "kinetic_alpha = screwm_clamp(0.82 + pulse_c * 0.18" in body
    assert "ceiling_knot_alpha = screwm_clamp(0.90 + pulse_a * 0.10" in body
    assert "ceiling_knot_width = screwm_clamp(34 + screwm_effect_drift_edge * 12" in body
    assert "right_wall_alpha = screwm_clamp(0.78 + pulse_a * 0.22" in body
    assert "right_wall_width = screwm_clamp(24 + screwm_effect_drift_edge * 10" in body
    assert "screwm_draw_drift_xy_ribbon(0, -2380, ceiling_z" in body
    assert "screwm_draw_drift_xy_ribbon(sin(phase * 0.31) * 120, -2300, ceiling_z - 1" in body
    assert "screwm_draw_drift_xy_ribbon(cos(phase * 0.33) * 120, -2240, ceiling_z - 2" in body
    assert "screwm_draw_drift_xy_ribbon(sin(phase * 0.91) * 420, -2620, ceiling_z" in body
    assert "screwm_draw_drift_xy_ribbon(-1760 + sin(phase * 1.03) * 260, -2480, ceiling_z" in body
    assert "screwm_draw_drift_xy_ribbon(1760 + cos(phase * 1.01) * 260, -2480, ceiling_z" in body
    assert "screwm_draw_drift_xy_ribbon(-1120 + sin(phase * 1.23) * 220" in body
    assert "screwm_draw_drift_xy_ribbon(0 + sin(phase * 1.31) * 240" in body
    assert "screwm_draw_drift_xy_ribbon(1480 + sin(phase * 1.11) * 260" in body
    assert "screwm_draw_xy_ribbon(sin(phase * 1.09) * 520, -2500, ceiling_z" in body
    assert "screwm_draw_xy_ribbon(cos(phase * 1.03) * 520, -2260, ceiling_z" in body
    assert "screwm_draw_drift_xy_ribbon(-1180 + sin(phase * 1.53) * 180" in body
    assert "screwm_draw_drift_xy_ribbon(-220 + sin(phase * 1.61) * 190" in body
    assert "screwm_draw_drift_xy_ribbon(0 + sin(phase * 1.71) * 210" in body
    assert "screwm_draw_xy_ribbon(1180 + sin(phase * 1.75) * 150" in body
    assert "screwm_draw_drift_xy_ribbon(-1260 + sin(phase * 2.11) * 130" in body
    assert "screwm_draw_drift_xy_ribbon(80 + cos(phase * 2.23) * 142" in body
    assert "screwm_draw_xy_ribbon(1040 + sin(phase * 2.33) * 118" in body
    assert "screwm_draw_xy_ribbon(sin(phase * 1.12) * 520, -2380, -49" in body
    assert "screwm_draw_yz_wall_ribbon(1422, sin(phase * 1.21) * 1280" in body
    assert "screwm_draw_drift_xz_wall_ribbon(2050, -1320 + sin(phase * 1.45) * 220" in body
    assert "screwm_draw_drift_xz_wall_ribbon(2048, -1640 + sin(phase * 1.51) * 240" in body
    assert "screwm_draw_xz_wall_ribbon(2051, -1210 + cos(phase * 1.59) * 200" in body
    assert "screwm_draw_drift_xy_ribbon(-1660 + sin(phase * 0.41) * 120, -2320, 1718" in body
    assert "screwm_draw_drift_xy_ribbon(0, -2330, 1718" in body
    assert "screwm_draw_drift_xy_ribbon(1480 + cos(phase * 0.43) * 120, -2310, 1718" in body
    assert "screwm_draw_xy_ribbon(-1320 + sin(phase * 0.93) * 260, -2300, 1754" in body
    assert "screwm_draw_xy_ribbon(1320 + cos(phase * 0.89) * 260, -2300, 1754" in body
    assert "screwm_draw_xz_wall_ribbon(2054, -1720, 420" in body
    assert "screwm_draw_xz_wall_ribbon(2051, -2260 + sin(phase * 0.83) * 260" in body
    assert "screwm_draw_drift_xz_wall_ribbon(1988, -2260, 540" in body
    assert "screwm_draw_drift_yz_wall_ribbon(1418, 0, 760" in body
    assert "screwm_draw_drift_yz_wall_ribbon(1418, 1480 + cos(phase * 0.39) * 120, 720" in body
    assert "signal = screwm_clamp(\n        0.56 + pressure * 1.02" in body
    assert "width = screwm_clamp(5 + screwm_effect_drift_edge * 6" in body
    assert "alpha = screwm_clamp(0.10 + signal * 0.035" in body
    assert "screwm_draw_wall_light_grid_planes(phase, width, alpha * 0.96);" in body
    assert "screwm_draw_drift_xz_wall_ribbon(-1580, -1320 + sin(phase * 1.21) * 86" in body
    assert "screwm_draw_drift_xz_wall_ribbon(1580, -1320 + cos(phase * 1.19) * 86" in body
    assert "flash_a = 0.50 + 0.50 * sin(phase * 2.37" in body
    assert "source_alpha = screwm_clamp(0.26 + signal * 0.12 + flash_a * 0.54" in body
    assert "screwm_draw_xz_wall_ribbon(-1578, -1320 + cos(phase * 1.89) * 260" in body
    assert "screwm_draw_xz_wall_ribbon(1578, -1320 + sin(phase * 1.87) * 260" in body
    assert "screwm_draw_drift_xy_ribbon(-1040 + sin(phase * 0.59) * 120, -1480, -48" in body
    assert "screwm_draw_xy_ribbon(-1040 + sin(phase * 1.93) * 560" in body
    assert "screwm_draw_xy_ribbon(1040 + cos(phase * 1.91) * 560" in body
    assert "screwm_draw_xy_ribbon(-1120 + cos(phase * 1.83) * 580" in body
    assert "screwm_draw_xy_ribbon(1120 + sin(phase * 1.81) * 580" in body
    assert "screwm_draw_drift_xy_ribbon(0, -555 + sin(phase * 0.47) * 96, -47" in body
    assert "screwm_draw_drift_yz_wall_ribbon(-596, sin(phase * 0.73) * 180" in body
    assert "screwm_draw_xz_wall_ribbon(-2054, -1720, 420" in body
    assert "screwm_draw_yz_wall_ribbon(1422, 0, 430" in body
    assert body.index("renderscene();") < body.index('if (cvar("screwm_csqc_overlay")')


def test_csqc_gem_recruitment_mural_lives_in_scroom_lightfield() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert 'screwm_read_norm("data/gem-recruitment-score.txt")' in body
    assert 'screwm_read_norm("data/gem-recruitment-fresh.txt")' in body
    assert 'screwm_read_norm("data/gem-frame-count.txt")' in body
    assert 'screwm_read_norm("data/gem-layer-density.txt")' in body
    assert 'screwm_read_norm("data/gem-layer-opacity.txt")' in body
    assert 'screwm_read_norm("data/gem-narrative-pressure.txt")' in body
    assert "void() screwm_add_gem_mural_lights" in body
    assert "screwm_gem_recruitment_score * 92" in body
    assert "screwm_gem_layer_density * 96" in body
    assert "screwm_gem_narrative_pressure * 102" in body
    assert "adddynamiclight('-222 -360 226'" in body
    assert "adddynamiclight('250 -518 226'" in body
    assert "screwm_add_gem_mural_lights();" in body


def test_csqc_impingement_recruitment_field_lives_in_scroom_lightfield() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert 'screwm_read_norm("data/impingement-count.txt")' in body
    assert 'screwm_read_norm("data/impingement-strength.txt")' in body
    assert 'screwm_read_norm("data/impingement-reverie-alert.txt")' in body
    assert 'screwm_read_norm("data/recruitment-family-count.txt")' in body
    assert 'screwm_read_norm("data/recruitment-transition-pressure.txt")' in body
    assert 'screwm_read_norm("data/recruitment-studio-pressure.txt")' in body
    assert "void() screwm_add_impingement_recruitment_lights" in body
    assert "screwm_impingement_strength * 82" in body
    assert "screwm_recruitment_transition_pressure * 98" in body
    assert "adddynamiclight('-74 -360 226'" in body
    assert "adddynamiclight('120 -532 276'" in body
    assert "screwm_add_impingement_recruitment_lights();" in body


def test_csqc_programme_segment_field_lives_in_scroom_lightfield() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert 'screwm_read_norm("data/programme-role.txt")' in body
    assert 'screwm_read_norm("data/programme-beat-progress.txt")' in body
    assert 'screwm_read_norm("data/programme-source-pressure.txt")' in body
    assert 'screwm_read_norm("data/programme-asset-pressure.txt")' in body
    assert 'screwm_read_norm("data/programme-cue-hold.txt")' in body
    assert "void() screwm_add_programme_segment_lights" in body
    assert "screwm_programme_role * 72" in body
    assert "screwm_programme_beat_progress * 96" in body
    assert "screwm_programme_source_pressure * 78" in body
    assert "adddynamiclight('222 -360 172'" in body
    assert "adddynamiclight('148 -360 64'" in body
    assert "screwm_add_programme_segment_lights();" in body


def test_csqc_live_context_field_lives_in_scroom_lightfield() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert 'screwm_read_norm("data/live-token-pressure.txt")' in body
    assert 'screwm_read_norm("data/live-viewer-pressure.txt")' in body
    assert 'screwm_read_norm("data/live-album-confidence.txt")' in body
    assert 'screwm_read_norm("data/live-album-risk.txt")' in body
    assert 'screwm_read_norm("data/live-voice-active.txt")' in body
    assert "void() screwm_add_live_context_lights" in body
    assert "screwm_live_token_pressure * 88" in body
    assert "screwm_live_album_confidence * 82" in body
    assert "screwm_live_voice_active * 104" in body
    assert "adddynamiclight('-222 -360 280'" in body
    assert "adddynamiclight('-148 -360 280'" in body
    assert "screwm_add_live_context_lights();" in body


def test_csqc_governance_health_field_lives_in_scroom_lightfield() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert 'screwm_read_norm("data/governance-consent-allowed.txt")' in body
    assert 'screwm_read_norm("data/governance-persistence-allowed.txt")' in body
    assert 'screwm_read_norm("data/governance-health-error.txt")' in body
    assert 'screwm_read_norm("data/governance-follow-confidence.txt")' in body
    assert "void() screwm_add_governance_health_lights" in body
    assert "screwm_governance_consent_allowed * 82" in body
    assert "screwm_governance_health_error * 112" in body
    assert "screwm_governance_follow_confidence * 64" in body
    assert "adddynamiclight('-300 -548 460'" in body
    assert "screwm_add_governance_health_lights();" in body


def test_darkplaces_review_camera_is_locked_by_default() -> None:
    autoexec = AUTOEXEC.read_text(encoding="utf-8")
    camera = (REPO_ROOT / "assets" / "quake" / "qc" / "camera.qc").read_text(encoding="utf-8")

    assert "set screwm_camera_orbit 0" in autoexec
    assert "cl_bob 0" in autoexec
    assert "cl_rollangle 0" in autoexec
    assert "fov 90" in autoexec
    assert "set screwm_camera_file_control 1" in autoexec
    assert "set screwm_player_noclip_control 1" in autoexec
    assert "set screwm_csqc_review_camera 1" in autoexec
    assert "set screwm_csqc_review_path 1" in autoexec
    assert "set screwm_csqc_manual_camera 1" in autoexec
    assert "set screwm_csqc_native_controller 0" in autoexec
    assert "joy_enable 1" in autoexec
    assert "joy_index 1" in autoexec
    assert "joy_axisforward 1" in autoexec
    assert "joy_axisyaw 3" in autoexec
    assert "joy_axispitch 4" in autoexec
    assert "joy_x360_axisforward 1" in autoexec
    assert "joy_x360_axisyaw 2" in autoexec
    assert "joy_x360_axispitch 3" in autoexec
    assert "joyadvancedupdate" in autoexec
    assert "bind JOY5 +movedown" in autoexec
    assert "bind JOY6 +moveup" in autoexec
    assert 'cvar("screwm_camera_orbit") > 0' in camera
    assert "CAMERA_REVIEW_POS" in camera


def test_csqc_review_camera_overrides_render_view_for_obs_feedback() -> None:
    defs = (CSQC_DIR / "defs.qc").read_text(encoding="utf-8")
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert "const float VF_ORIGIN = 11;" in defs
    assert "const float VF_ANGLES = 15;" in defs
    assert "const float VF_CL_VIEWANGLES = 33;" in defs
    assert "R_BeginPolygon = #306;" in defs
    assert "R_PolygonVertex = #307;" in defs
    assert "R_EndPolygon = #308;" in defs
    assert "precache_pic = #317;" in defs
    assert "void(vector ang) makevectors = #1;" in defs
    assert "vector(vector v) vectoangles = #51;" in defs
    assert "void() screwm_apply_review_camera" in body
    assert 'cvar("screwm_csqc_review_camera") <= 0' in body
    assert 'cvar("screwm_csqc_native_controller") > 0' in body
    assert "screwm_review_camera_manual_until = time + native_hold;" in body
    assert "makevectors(screwm_review_camera_angles);" in body
    assert "v_forward * input_movevalues_x * frametime * native_speed" in body
    assert 'cvar("screwm_csqc_manual_camera") > 0 && manual > 0' in body
    assert 'screwm_read_float("data/camera-origin-x.txt"' in body
    assert 'screwm_read_float("data/camera-pitch.txt"' in body
    assert 'screwm_read_float("data/camera-yaw.txt"' in body
    assert "screwm_review_camera_fov_y = fov * 0.625;" in body
    assert 'cvar("screwm_csqc_review_path") > 0' in body
    assert 'screwm_read_float("data/camera-period.txt", screwm_review_camera_period)' in body
    assert "active_period = screwm_clamp(active_period, 24, 720);" in body
    assert "cycle = time * 800 / active_period;" in body
    assert "while (cycle >= 800)" in body
    assert "origin_a = '0 -2360 190';" in body
    assert "origin_b = '-240 -2200 204';" in body
    assert "origin_b = '-560 -1880 218';" in body
    assert "origin_b = '-720 -1460 230';" in body
    assert "origin_b = '520 -1120 224';" in body
    assert "origin_b = '720 -1460 230';" in body
    assert "origin_b = '560 -1880 218';" in body
    assert "origin_b = '0 -2360 190';" in body
    assert "target_a = '0 -555 254';" in body
    assert "target_b = '-420 -1160 230';" not in body
    assert "target_b = '-1180 -1320 245';" not in body
    assert "target_b = '1180 -1320 245';" not in body
    assert "target_b = '420 -1160 230';" not in body
    assert "target_b = '0 -555 262';" in body
    assert "screwm_review_camera_fov = '92 57.5 0';" in body
    assert "s = u * u * (3 - 2 * u);" in body
    assert "phase = time * screwm_review_camera_two_pi / active_period;" in body
    assert "screwm_review_camera_origin = origin_a + (origin_b - origin_a) * s;" in body
    assert "target = target_a + (target_b - target_a) * s;" in body
    assert (
        "screwm_review_camera_angles = vectoangles(target - screwm_review_camera_origin);" in body
    )
    assert "setproperty(VF_ORIGIN, screwm_review_camera_origin);" in body
    assert "setproperty(VF_ANGLES, screwm_review_camera_angles);" in body
    assert "setproperty(VF_CL_VIEWANGLES, screwm_review_camera_angles);" in body
    assert "setproperty(VF_FOV, screwm_review_camera_fov);" in body
    assert "screwm_review_camera_origin = '0 -2360 190';" in body
    assert (
        "screwm_review_camera_angles = vectoangles('0 -555 254' - screwm_review_camera_origin);"
        in body
    )
    assert "screwm_review_camera_fov = '92 57.5 0';" in body
    assert "screwm_review_camera_period = 360.0;" in body


def test_darkplaces_review_camera_is_noclip_not_player_physics() -> None:
    defs = (REPO_ROOT / "assets" / "quake" / "qc" / "defs.qc").read_text(encoding="utf-8")
    world = (REPO_ROOT / "assets" / "quake" / "qc" / "world.qc").read_text(encoding="utf-8")

    assert "MOVETYPE_NOCLIP = 8" in defs
    assert ".vector velocity;" in defs
    assert "void(entity view) screwm_free_view_body" in world
    assert "void(entity view) screwm_player_noclip_body" in world
    assert "view.movetype = MOVETYPE_NOCLIP;" in world
    assert "view.solid = SOLID_NOT;" in world
    assert "view.velocity = '0 0 0';" in world
    assert "screwm_free_view_body(self);" in world
    assert "screwm_player_noclip_body(self);" in world
    assert "self.movetype = MOVETYPE_NONE;" not in world


def test_csqc_compiles_in_temporary_directory(tmp_path: Path) -> None:
    if not shutil.which("fteqcc"):
        pytest.skip("fteqcc is not installed")

    work = tmp_path / "csqc"
    shutil.copytree(CSQC_DIR, work)
    (work / "csprogs.dat").unlink(missing_ok=True)

    result = subprocess.run(
        ["fteqcc", "-Tdp"],
        cwd=work,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (work / "csprogs.dat").exists()
    assert "DP-specific CSQC module" in result.stdout + result.stderr


def test_server_qc_compiles_in_temporary_directory(tmp_path: Path) -> None:
    if not shutil.which("fteqcc"):
        pytest.skip("fteqcc is not installed")

    work = tmp_path / "qc"
    shutil.copytree(QC_DIR, work)
    (work / "progs.dat").unlink(missing_ok=True)

    result = subprocess.run(
        ["fteqcc", "-Tdp"],
        cwd=work,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (work / "progs.dat").exists()
    assert "Writing progs.dat" in result.stdout + result.stderr


def test_darkplaces_asset_installer_deploys_csqc_dat() -> None:
    body = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "assets/quake/csqc/csprogs.dat" in body
    assert '"$GAME_DIR/csprogs.dat"' in body
