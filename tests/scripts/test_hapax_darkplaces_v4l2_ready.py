from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-darkplaces-v4l2-ready"


def _write_stub(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\n{textwrap.dedent(body).strip()}\n", encoding="utf-8")
    path.chmod(0o755)


def _env_with_stubs(tmp_path: Path, v4l2_body: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "v4l2-ctl", v4l2_body)
    _write_stub(
        bin_dir / "timeout",
        """
        shift
        exec "$@"
        """,
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env


def test_darkplaces_v4l2_ready_accepts_capture_device_with_expected_format(tmp_path: Path) -> None:
    device = tmp_path / "video52"
    device.write_bytes(b"")
    env = _env_with_stubs(
        tmp_path,
        """
        case "$*" in
          *--info*)
            printf 'Capabilities:\\n\\tVideo Capture\\n\\tStreaming\\n'
            ;;
          *--get-fmt-video*)
            printf "Width/Height      : 1280/720\\nPixel Format      : 'YUYV'\\n"
            ;;
        esac
        exit 0
        """,
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "--device",
            str(device),
            "--timeout-seconds",
            "1",
            "--poll-interval",
            "0",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
    assert str(device) in result.stdout


def test_darkplaces_v4l2_ready_waits_for_capture_capability(tmp_path: Path) -> None:
    device = tmp_path / "video52"
    device.write_bytes(b"")
    state = tmp_path / "seen-info"
    env = _env_with_stubs(
        tmp_path,
        f"""
        case "$*" in
          *--info*)
            if [[ -f {state} ]]; then
              printf 'Capabilities:\\n\\tVideo Capture\\n\\tStreaming\\n'
            else
              touch {state}
              printf 'Capabilities:\\n\\tVideo Output\\n\\tStreaming\\n'
            fi
            ;;
          *--get-fmt-video*)
            printf "Width/Height      : 1280/720\\nPixel Format      : 'YUYV'\\n"
            ;;
        esac
        exit 0
        """,
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "--device",
            str(device),
            "--timeout-seconds",
            "2",
            "--poll-interval",
            "0",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert state.exists()


def test_darkplaces_v4l2_ready_fails_on_wrong_format(tmp_path: Path) -> None:
    device = tmp_path / "video52"
    device.write_bytes(b"")
    env = _env_with_stubs(
        tmp_path,
        """
        case "$*" in
          *--info*)
            printf 'Capabilities:\\n\\tVideo Capture\\n\\tStreaming\\n'
            ;;
          *--get-fmt-video*)
            printf "Width/Height      : 640/480\\nPixel Format      : 'BGR4'\\n"
            ;;
        esac
        exit 0
        """,
    )

    result = subprocess.run(
        [
            str(SCRIPT),
            "--device",
            str(device),
            "--timeout-seconds",
            "0",
            "--poll-interval",
            "0",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "expected 1280x720" in result.stderr
