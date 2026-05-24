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
    assert "screwm_draw_ward_detail(" in body
    for ordinal in range(1, 37):
        assert f'"{ordinal:02d}"' in body
    for ordinal in ("01", "02", "07", "09", "12", "13", "21", "28", "34"):
        assert f"data/ward-{ordinal}.txt" in body


def test_csqc_text_overlay_is_not_the_default_ward_surface() -> None:
    autoexec = AUTOEXEC.read_text(encoding="utf-8")
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert "screwm_csqc_overlay 0" in autoexec
    assert "screwm_csqc_lightfield 1" in autoexec
    assert "Ward identity belongs to the scroom geometry" in autoexec
    assert "screwm_add_ward_light('-222 62 280'" in body
    assert "screwm_add_ward_light('148 -82 64'" in body


def test_csqc_dynamic_lights_cover_all_physical_ward_panes() -> None:
    map_module = _load_script("scripts/generate-screwm-map.py")
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert body.count("screwm_add_ward_light('") == 36
    assert body.count('screwm_read_norm("data/ward-active-') == 36
    assert "active * 74" in body
    assert 'cvar("screwm_csqc_lightfield") < 0' in body

    for idx in range(1, 37):
        x, y, z = map_module["ward_anchor_position"](idx)
        assert f"screwm_add_ward_light('{x} {y} {z}'" in body
        assert f"screwm_active_{idx:02d}" in body


def test_darkplaces_review_camera_is_locked_by_default() -> None:
    autoexec = AUTOEXEC.read_text(encoding="utf-8")
    camera = (REPO_ROOT / "assets" / "quake" / "qc" / "camera.qc").read_text(encoding="utf-8")

    assert "screwm_camera_orbit 0" in autoexec
    assert "cl_bob 0" in autoexec
    assert "cl_rollangle 0" in autoexec
    assert "fov 90" in autoexec
    assert "screwm_camera_file_control 1" in autoexec
    assert 'cvar("screwm_camera_orbit") > 0' in camera
    assert "CAMERA_REVIEW_POS" in camera


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
