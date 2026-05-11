from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-camera-loopback-sidecar"


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


def test_sidecar_exits_cleanly_when_disabled() -> None:
    result = _run(extra_env={"HAPAX_CAMERA_LOOPBACK_ENABLED": "0"})

    assert result.returncode == 0
    assert "disabled" in result.stdout


def test_sidecar_prints_ffmpeg_command_from_flags() -> None:
    result = _run(
        "--print-command",
        "--role",
        "brio-operator",
        "--source",
        "/dev/video60",
        "--device",
        "/dev/video70",
        "--width",
        "1280",
        "--height",
        "720",
        "--fps",
        "30",
    )

    assert result.returncode == 0
    assert result.stdout.startswith("ffmpeg ")
    assert "-f v4l2" in result.stdout
    assert "-input_format mjpeg" in result.stdout
    assert "-video_size 1280x720" in result.stdout
    assert "/dev/video60" in result.stdout
    assert "/dev/video70" in result.stdout
    assert "-pix_fmt yuyv422" in result.stdout


def test_sidecar_loads_repo_env_file() -> None:
    env_file = REPO_ROOT / "config" / "camera-loopbacks" / "brio-synths.env"

    result = _run("--env-file", str(env_file), "--print-command")

    assert result.returncode == 0
    assert "/dev/video75" in result.stdout
    assert "-video_size 640x480" in result.stdout
    assert "-framerate 15" in result.stdout


def test_sidecar_check_reports_missing_devices(tmp_path: Path) -> None:
    result = _run(
        "--check",
        "--role",
        "c920-desk",
        "--source",
        str(tmp_path / "missing-source"),
        "--device",
        str(tmp_path / "missing-loopback"),
    )

    assert result.returncode == 1
    assert "source device missing" in result.stderr
    assert "loopback device missing" in result.stderr
