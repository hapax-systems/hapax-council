from __future__ import annotations

import os
import shlex
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "notify-failure@.service"
INTAKE = "%h/.local/lib/hapax-recovery/council/current/scripts/hapax-p0-incident-intake"
FORBIDDEN_EXECSTART_ROOTS = (
    "source-activation/worktree",
    "scratch/vocab-export",
    "/data/cache",
)


def _write_fake_bin(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def test_notify_failure_routes_through_p0_intake():
    text = UNIT.read_text(encoding="utf-8")

    assert f"ConditionPathExists={INTAKE}" in text
    assert f"ExecStart={INTAKE} service-failed %i" in text
    assert "/usr/bin/notify-send" not in text


def test_notify_failure_execstart_avoids_reapable_d2_roots() -> None:
    exec_lines = [
        line
        for line in UNIT.read_text(encoding="utf-8").splitlines()
        if line.startswith("ExecStart=")
    ]

    assert exec_lines
    for root in FORBIDDEN_EXECSTART_ROOTS:
        assert all(root not in line for line in exec_lines)


def test_notify_failure_execstart_runs_intake_cli(tmp_path):
    home = tmp_path / "home"
    recovery_bundle = home / ".local" / "lib" / "hapax-recovery" / "council"
    recovery_bundle.mkdir(parents=True)
    (recovery_bundle / "current").symlink_to(REPO_ROOT, target_is_directory=True)

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
