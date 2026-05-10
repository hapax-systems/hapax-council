from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-v4l2-video42-format-guard"


def _write_stub(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{textwrap.dedent(body).strip()}\n", encoding="utf-8")
    path.chmod(0o755)


def _format_stub(record: Path) -> str:
    return f"""
    printf '%s\\n' "$*" >> {record}
    case "$*" in
      *--get-fmt-video-out*|*--get-fmt-video*)
        cat <<'EOF'
    Format Video Capture:
            Width/Height      : 1280/720
            Pixel Format      : 'NV12'
    EOF
        ;;
      *--get-ctrl\\ keep_format*)
        printf 'keep_format: 1\\n'
        ;;
      *--get-parm*)
        printf 'Frames per second: 30.000 (30/1)\\n'
        ;;
    esac
    exit 0
    """


def test_video42_format_guard_sets_format_before_keep_format_and_verifies(
    tmp_path: Path,
) -> None:
    device = tmp_path / "video42"
    device.write_bytes(b"")
    record = tmp_path / "v4l2-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "v4l2-ctl", _format_stub(record))

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    result = subprocess.run(
        [str(SCRIPT), "--device", str(device)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    calls = record.read_text(encoding="utf-8").splitlines()
    assert calls[:4] == [
        f"-d {device} --set-fmt-video-out=width=1280,height=720,pixelformat=NV12",
        f"-d {device} --set-fmt-video=width=1280,height=720,pixelformat=NV12",
        f"-d {device} --set-parm=30",
        f"-d {device} -c keep_format=1",
    ]
    assert any("--get-fmt-video-out" in call for call in calls)
    assert any("--get-fmt-video" in call for call in calls)
    assert any("--get-ctrl keep_format" in call for call in calls)


def test_video42_format_guard_verify_only_does_not_mutate_device(tmp_path: Path) -> None:
    device = tmp_path / "video42"
    device.write_bytes(b"")
    record = tmp_path / "v4l2-calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "v4l2-ctl", _format_stub(record))

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    result = subprocess.run(
        [str(SCRIPT), "--verify-only", "--device", str(device)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    calls = record.read_text(encoding="utf-8").splitlines()
    assert not any("--set-fmt" in call for call in calls)
    assert not any("--set-parm" in call for call in calls)
    assert not any(" -p " in f" {call} " for call in calls)
    assert not any("-c keep_format=1" in call for call in calls)


def test_video42_format_guard_fails_closed_on_wrong_format(tmp_path: Path) -> None:
    device = tmp_path / "video42"
    device.write_bytes(b"")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(
        bin_dir / "v4l2-ctl",
        """
        case "$*" in
          *--get-fmt-video-out*|*--get-fmt-video*)
            printf "Width/Height      : 640/480\\nPixel Format      : 'NV12'\\n"
            ;;
          *--get-ctrl\\ keep_format*)
            printf 'keep_format: 1\\n'
            ;;
          *--get-parm*)
            printf 'Frames per second: 30.000 (30/1)\\n'
            ;;
        esac
        exit 0
        """,
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    result = subprocess.run(
        [str(SCRIPT), "--verify-only", "--device", str(device)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "expected both capture/output 1280x720" in result.stderr


def test_video42_format_guard_rejects_missing_option_value(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(SCRIPT), "--device"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--device requires a value" in result.stderr


def test_video42_format_guard_rejects_malformed_expected_values(tmp_path: Path) -> None:
    device = tmp_path / "video42"
    device.write_bytes(b"")

    result = subprocess.run(
        [str(SCRIPT), "--device", str(device), "--width", "1280|720"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "invalid width" in result.stderr
