from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "install-p0-oom-containment"


def test_p0_oom_containment_source_check_passes() -> None:
    result = subprocess.run(
        [str(INSTALLER), "--check"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "p0 oom containment install/check complete" in result.stdout


def test_p0_oom_containment_install_and_verify_live_against_temp_destinations(
    tmp_path: Path,
) -> None:
    system_dir = tmp_path / "systemd-system"
    user_dir = tmp_path / "systemd-user"
    user_control_dir = tmp_path / "systemd-user-control"
    stale_control = user_control_dir / "app.slice.d" / "50-MemoryHigh.conf"
    stale_control.parent.mkdir(parents=True)
    stale_control.write_text("[Slice]\nMemoryHigh=1G\n", encoding="utf-8")
    earlyoom_dest = tmp_path / "earlyoom"
    systemctl_calls = tmp_path / "systemctl-calls.txt"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> {systemctl_calls!s}\nexit 0\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o755)

    result = subprocess.run(
        [str(INSTALLER), "--install", "--verify-live", "--no-runtime"],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "HAPAX_OOM_SYSTEMD_SYSTEM_DIR": str(system_dir),
            "HAPAX_OOM_SYSTEMD_USER_DIR": str(user_dir),
            "HAPAX_OOM_SYSTEMD_USER_CONTROL_DIR": str(user_control_dir),
            "HAPAX_OOM_EARLYOOM_DEST": str(earlyoom_dest),
            "HAPAX_OOM_SYSTEMCTL": str(fake_systemctl),
            "HAPAX_OOM_INSTALL_SUDO": "",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (
        (system_dir / "user@1000.service.d" / "oom.conf")
        .read_text(encoding="utf-8")
        .strip()
        .endswith("OOMScoreAdjust=100")
    )
    app_dropin = user_dir / "app.slice.d" / "oom-containment.conf"
    assert app_dropin.is_file()
    assert not app_dropin.is_symlink()
    assert "MemorySwapMax=8G" in app_dropin.read_text(encoding="utf-8")
    assert earlyoom_dest.read_text(encoding="utf-8").startswith("EARLYOOM_ARGS=")
    assert not stale_control.exists()
    calls = systemctl_calls.read_text(encoding="utf-8")
    assert "daemon-reload" in calls
