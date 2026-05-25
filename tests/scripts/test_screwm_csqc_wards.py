from __future__ import annotations

import runpy
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CSQC_DIR = REPO_ROOT / "assets" / "quake" / "csqc"
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
    assert "set screwm_review_fill_light 1" in autoexec
    assert "Ward identity belongs to the scroom geometry" in autoexec
    assert 'cvar("screwm_review_fill_light") > 0' in body
    assert "adddynamiclight('0 -332 184'" in body
    assert "220 + screwm_energy * 80" in body
    assert "screwm_add_ward_light('-222 -360 280'" in body
    assert "screwm_add_ward_light('148 -360 64'" in body


def test_csqc_dynamic_lights_cover_all_physical_ward_panes() -> None:
    map_module = _load_script("scripts/generate-screwm-map.py")
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert body.count("screwm_add_ward_light('") == 36
    assert body.count('screwm_read_norm("data/ward-active-') == 36
    assert "active * 74" in body
    assert 'screwm_read_norm("data/audio-rms.txt")' in body
    assert "screwm_audio_onset * 20" in body
    assert 'screwm_read_norm("data/homage-quake-active.txt")' in body
    assert "homage_boost = screwm_homage_quake" in body
    assert 'cvar("screwm_csqc_lightfield") < 0' in body

    for idx in range(1, 37):
        x, y, z = map_module["ward_review_position"](idx)
        assert f"screwm_add_ward_light('{x} {y} {z}'" in body
        assert f"screwm_active_{idx:02d}" in body


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


def test_csqc_homage_package_lives_in_scroom_lightfield() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert 'screwm_read_norm("data/homage-transition-energy.txt")' in body
    assert 'screwm_read_norm("data/homage-signature-intensity.txt")' in body
    assert "void() screwm_add_homage_lights" in body
    assert "if (screwm_homage_quake <= 0)" in body
    assert "adddynamiclight('0 -372 172'" in body
    assert "screwm_add_homage_lights();" in body


def test_darkplaces_review_camera_is_locked_by_default() -> None:
    autoexec = AUTOEXEC.read_text(encoding="utf-8")
    camera = (REPO_ROOT / "assets" / "quake" / "qc" / "camera.qc").read_text(encoding="utf-8")

    assert "set screwm_camera_orbit 0" in autoexec
    assert "cl_bob 0" in autoexec
    assert "cl_rollangle 0" in autoexec
    assert "fov 78" in autoexec
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
    assert "phase = time * screwm_review_camera_two_pi / screwm_review_camera_period;" in body
    assert "screwm_review_camera_origin_x = sin(phase) * 84;" in body
    assert "screwm_review_camera_origin_y = -650 + cos(phase) * 20;" in body
    assert (
        "screwm_review_camera_angles = vectoangles('0 -405 176' - screwm_review_camera_origin);"
        in body
    )
    assert "setproperty(VF_ORIGIN, screwm_review_camera_origin);" in body
    assert "setproperty(VF_ANGLES, screwm_review_camera_angles);" in body
    assert "setproperty(VF_CL_VIEWANGLES, screwm_review_camera_angles);" in body
    assert "setproperty(VF_FOV, screwm_review_camera_fov);" in body
    assert "screwm_review_camera_origin = '0 -650 190';" in body
    assert (
        "screwm_review_camera_angles = vectoangles('0 -405 176' - screwm_review_camera_origin);"
        in body
    )
    assert "screwm_review_camera_fov = '78 49 0';" in body
    assert "screwm_review_camera_period = 110.0;" in body


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


def test_darkplaces_asset_installer_deploys_csqc_dat() -> None:
    body = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "assets/quake/csqc/csprogs.dat" in body
    assert '"$GAME_DIR/csprogs.dat"' in body
