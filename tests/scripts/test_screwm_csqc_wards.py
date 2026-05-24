from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CSQC_DIR = REPO_ROOT / "assets" / "quake" / "csqc"
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install-darkplaces-screwm-assets.sh"


def test_csqc_sources_define_all_legacy_ward_labels() -> None:
    body = (CSQC_DIR / "wards.qc").read_text(encoding="utf-8")

    assert "CSQC_UpdateView" in body
    assert "cs_project" in body
    assert "adddynamiclight" in body
    assert body.count("screwm_draw_ward_label(") == 35
    for ordinal in range(1, 36):
        assert f'"{ordinal:02d}"' in body


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
