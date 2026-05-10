from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "install-compositor-layouts.sh"

REQUIRED_LAYOUTS = (
    "config/compositor-layouts/default.json",
    "config/compositor-layouts/consent-safe.json",
    "config/compositor-layouts/segment-chat.json",
    "config/compositor-layouts/segment-compare.json",
    "config/compositor-layouts/segment-detail.json",
    "config/compositor-layouts/segment-list.json",
    "config/compositor-layouts/segment-poll.json",
    "config/compositor-layouts/segment-programme-context.json",
    "config/compositor-layouts/segment-receipt.json",
    "config/compositor-layouts/segment-tier.json",
    "config/layouts/garage-door.json",
)


def _stage_script_fixture(tmp_path: Path, *, missing: str | None = None) -> Path:
    fixture = tmp_path / "repo"
    (fixture / "scripts").mkdir(parents=True)
    staged_script = fixture / "scripts" / "install-compositor-layouts.sh"
    shutil.copy2(SCRIPT, staged_script)

    for relative in REQUIRED_LAYOUTS:
        if relative == missing:
            continue
        path = fixture / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    return staged_script


def test_install_compositor_layouts_fails_fast_when_required_layout_is_missing(
    tmp_path: Path,
) -> None:
    staged_script = _stage_script_fixture(
        tmp_path, missing="config/compositor-layouts/default.json"
    )
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config-home")

    result = subprocess.run(
        [str(staged_script)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "ERROR: required source layout not found" in result.stderr
    assert not (
        tmp_path / "config-home" / "hapax-compositor" / "layouts" / "consent-safe.json"
    ).exists()


def test_install_compositor_layouts_installs_complete_required_set(tmp_path: Path) -> None:
    staged_script = _stage_script_fixture(tmp_path)
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config-home")

    result = subprocess.run(
        [str(staged_script)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    dest = tmp_path / "config-home" / "hapax-compositor" / "layouts"
    assert (dest / "default.json").exists()
    assert (dest / "garage-door.json").exists()
