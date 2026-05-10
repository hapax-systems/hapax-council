from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-v4l2-bridge"


def test_check_requires_socket_by_default(tmp_path: Path) -> None:
    device = tmp_path / "not-a-real-device"
    env = os.environ.copy()
    result = subprocess.run(
        [
            str(SCRIPT),
            "--check",
            "--device",
            str(device),
            "--socket",
            str(tmp_path / "missing.sock"),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "FAIL: socket" in result.stdout


def test_check_can_allow_missing_socket_for_precreation_waits(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(SCRIPT),
            "--check",
            "--allow-missing-socket",
            "--device",
            str(tmp_path / "not-a-real-device"),
            "--socket",
            str(tmp_path / "missing.sock"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "allowed by --allow-missing-socket" in result.stdout
