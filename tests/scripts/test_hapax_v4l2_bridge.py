from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-v4l2-bridge"


def test_bridge_exits_cleanly_when_disabled(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HAPAX_V4L2_BRIDGE_ENABLED"] = "0"

    result = subprocess.run(
        [
            str(SCRIPT),
            "--device",
            str(tmp_path / "missing-device"),
            "--socket",
            str(tmp_path / "missing.sock"),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert "disabled by HAPAX_V4L2_BRIDGE_ENABLED=0" in result.stdout


def test_bridge_exits_cleanly_when_compositor_selects_direct_egress(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$2" = "show" ] && [ "$3" = "studio-compositor.service" ]; then\n'
        "  echo 'HAPAX_V4L2_BRIDGE_ENABLED=0 HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT=0'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    systemctl.chmod(0o755)
    env = os.environ.copy()
    env["HAPAX_V4L2_BRIDGE_ENABLED"] = "1"
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        [
            str(SCRIPT),
            "--device",
            str(tmp_path / "missing-device"),
            "--socket",
            str(tmp_path / "missing.sock"),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert "disabled by studio-compositor HAPAX_V4L2_BRIDGE_ENABLED=0" in result.stdout


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


def test_check_rejects_stale_socket_file_that_is_not_listening(tmp_path: Path) -> None:
    socket_path = tmp_path / "stale.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(socket_path))
    stale.close()

    result = subprocess.run(
        [
            str(SCRIPT),
            "--check",
            "--device",
            str(tmp_path / "not-a-real-device"),
            "--socket",
            str(socket_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "not listening" in result.stdout


def test_bridge_execs_python_appsink_writer(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "gst-args.txt"
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$2" = "show" ] && [ "$3" = "studio-compositor.service" ]; then\n'
        "  echo 'HAPAX_V4L2_BRIDGE_ENABLED=1 HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT=0'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    systemctl.chmod(0o755)
    python = bin_dir / "python"
    python.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > {args_file}\nexit 0\n")
    python.chmod(0o755)
    guard = bin_dir / "format-guard"
    guard.write_text("#!/usr/bin/env bash\nexit 0\n")
    guard.chmod(0o755)

    socket_path = tmp_path / "bridge.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    try:
        env = os.environ.copy()
        env.update(
            {
                "HAPAX_V4L2_BRIDGE_ENABLED": "1",
                "HAPAX_V4L2_FORMAT_GUARD_SCRIPT": str(guard),
                "PATH": f"{bin_dir}:{env['PATH']}",
            }
        )
        result = subprocess.run(
            [
                str(SCRIPT),
                "--device",
                str(tmp_path / "video42"),
                "--socket",
                str(socket_path),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
    finally:
        listener.close()

    assert result.returncode == 0
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert args[:3] == ["-m", "agents.studio_compositor.v4l2_shm_bridge", "--device"]
    assert str(tmp_path / "video42") in args
    assert "--socket" in args
    assert str(socket_path) in args
    assert "--wait-seconds" in args
