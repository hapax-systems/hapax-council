from __future__ import annotations

import os
import shlex
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "notify-failure@.service"
INSTALLER = REPO_ROOT / "scripts" / "hapax-recovery-plane-install"


def _write_fake_bin(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def test_notify_failure_routes_through_p0_intake():
    text = UNIT.read_text(encoding="utf-8")

    assert (
        "ExecStart=%h/.local/lib/hapax-recovery/council/scripts/"
        "hapax-p0-incident-intake service-failed %i"
    ) in text
    assert ".cache/hapax/source-activation/worktree" not in text
    assert "/data/cache/hapax/scratch" not in text
    assert "/usr/bin/notify-send" not in text


def test_notify_failure_execstart_runs_intake_cli(tmp_path):
    home = tmp_path / "home"
    recovery_dest = home / ".local" / "lib" / "hapax-recovery" / "council"
    install = subprocess.run(
        [str(INSTALLER), "--source", str(REPO_ROOT), "--dest", str(recovery_dest)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    notify_log = tmp_path / "notify.log"
    _write_fake_bin(
        fake_bin / "gdbus",
        """
        #!/usr/bin/env bash
        printf '%s\n' "$@" >> "$HAPAX_NOTIFY_CAPTURE"
        """,
    )
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "HAPAX_NOTIFY_CAPTURE": str(notify_log),
        }
    )
    exec_start = next(
        line.removeprefix("ExecStart=").strip()
        for line in UNIT.read_text(encoding="utf-8").splitlines()
        if line.startswith("ExecStart=")
    )
    command = shlex.split(exec_start.replace("%h", str(home)).replace("%i", "demo.service"))

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    task_glob = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    assert list(task_glob.glob("p0-incident-systemd-service-failed-demo-service-*.md"))
    assert not notify_log.exists(), "P0 intake should consume failures without desktop echo"
