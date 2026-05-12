from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-camera-loopback-setup"


def _run(*args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_setup_prints_merged_modprobe_command() -> None:
    result = _run("--print-modprobe")

    assert result.returncode == 0
    assert "modprobe v4l2loopback" in result.stdout
    assert "devices=14" in result.stdout
    assert (
        "video_nr=10\\,42\\,50\\,51\\,52\\,60\\,61\\,62\\,70\\,71\\,72\\,73\\,74\\,75"
        in result.stdout
    )
    assert "exclusive_caps=1\\,0\\,0\\,0\\,0\\,1\\,1\\,1\\,0\\,0\\,0\\,0\\,0\\,0" in result.stdout
    assert "Hapax\\ BRIO\\ Operator" in result.stdout


def test_setup_check_reports_missing_per_camera_devices(tmp_path: Path) -> None:
    result = _run("--check", extra_env={"HAPAX_CAMERA_LOOPBACK_DEV_ROOT": str(tmp_path)})

    assert result.returncode == 1
    assert "missing per-camera loopback device" in result.stdout
    assert str(tmp_path / "video70") in result.stdout
    assert str(tmp_path / "video75") in result.stdout
