"""The tier-1 (NAS) and tier-2 (B2) backup scripts, moved from the archived distro-work repository into council.

Row tier1-backup-scripts-into-council-reland-r2-20260927 (option A, seat ruling 2026-09-27 10:13Z): a faithful move
of what podium ran at distro-work 4e0087f, with two changes, FileStore secrets and the DR script's new location. The
never-prune rule for tier1-transcripts is pinned by tests/test_transcript_custody.py's tree-wide forget scan, which
now covers these scripts.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
UNITS = REPO / "systemd" / "units"
BACKUP_SCRIPTS = ("hapax-backup-local", "hapax-backup-remote")
ACTIVATION_ROOT = "%h/.cache/hapax/source-activation/worktree"

# sha256 of podium's ~/projects/distro-work/hapax-cachyos-restore.sh at 4e0087f (git blob 53b4137e6). The DR script
# moved unchanged; a change to it belongs to the follow-up row, not to a silent edit here.
LIVE_DR_SCRIPT_SHA256 = "fa0dafc78244daae304028fb980b53efb0ff36362f773325d0b4f7d7806e30cc"


@pytest.mark.parametrize("name", ["hapax-backup-local.service", "hapax-backup-remote.service"])
def test_backup_units_run_the_activation_worktree_never_a_checkout(name: str) -> None:
    unit = (UNITS / name).read_text(encoding="utf-8")
    exec_lines = [
        line for line in unit.splitlines() if line.startswith(("ExecStart=", "WorkingDirectory="))
    ]
    assert exec_lines, f"{name} has no ExecStart"
    for line in exec_lines:
        assert ACTIVATION_ROOT in line, line
        assert "projects/" not in line and "distro-work" not in line, line
    script = name.removesuffix(".service")
    assert f"ExecStart={ACTIVATION_ROOT}/scripts/{script}\n" in unit


@pytest.mark.parametrize("script", [*BACKUP_SCRIPTS, "hapax-cachyos-restore.sh"])
def test_scripts_parse(script: str) -> None:
    subprocess.run(["bash", "-n", str(SCRIPTS / script)], check=True, timeout=30)


@pytest.mark.parametrize("script", BACKUP_SCRIPTS)
def test_backup_scripts_read_the_filestore_never_pass(script: str) -> None:
    text = (SCRIPTS / script).read_text(encoding="utf-8")
    assert not re.search(r"\bpass\s+(show|ls|insert)\b", text)
    assert '. "${_hapax_self%/*}/lib/secret.sh"' in text
    assert 'RESTIC_PASSWORD="$(hapax_secret_read "$PASSWORD_ENTRY")"' in text


def _fake_bin(tmp_path: Path, secret_body: str) -> tuple[dict[str, str], Path]:
    """PATH with a fake hapax-secret and recording fakes for every command the scripts run before the dump."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    (bin_dir / "hapax-secret").write_text("#!/usr/bin/env bash\n" + secret_body, encoding="utf-8")
    recorder = (
        "#!/usr/bin/env bash\n"
        'echo "$(basename "$0") $* password-set=$([ -n "${RESTIC_PASSWORD:-}" ] && echo yes || echo no)" '
        f'>> "{calls}"\n'
        # docker fails, so the scripts stop at the pg_dumpall gate before any real work.
        '[ "$(basename "$0")" = docker ] && exit 1\n'
        "exit 0\n"
    )
    for tool in ("restic", "docker", "curl", "jq", "rclone", "notify-send"):
        (bin_dir / tool).write_text(recorder, encoding="utf-8")
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:/usr/bin:/bin",
        HOME=str(tmp_path / "home"),
        HAPAX_BACKUP_DUMP_DIR=str(tmp_path / "dump"),
    )
    return env, calls


@pytest.mark.parametrize("script", BACKUP_SCRIPTS)
@pytest.mark.parametrize(
    ("secret_body", "reason"),
    [("exit 1\n", "cannot read the restic password"), ("printf ''\n", "is empty")],
)
def test_an_unreadable_or_empty_password_stops_before_restic(
    tmp_path: Path, script: str, secret_body: str, reason: str
) -> None:
    env, calls = _fake_bin(tmp_path, secret_body)
    result = subprocess.run(
        [str(SCRIPTS / script)], env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 1
    assert reason in result.stderr and "hapax-secret" in result.stderr
    assert not calls.exists(), "restic or docker ran without a password"


@pytest.mark.parametrize("script", BACKUP_SCRIPTS)
def test_the_filestore_password_reaches_restic(tmp_path: Path, script: str) -> None:
    env, calls = _fake_bin(tmp_path, "printf 'not-a-real-secret\\n'\n")
    result = subprocess.run(
        [str(SCRIPTS / script)], env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 1  # the fake docker fails the pg_dumpall gate, by design
    assert "FATAL: pg_dumpall exited non-zero" in result.stdout
    log = calls.read_text(encoding="utf-8")
    assert "restic unlock password-set=yes" in log
    assert "not-a-real-secret" not in log  # the value is never echoed


def test_remote_uploads_the_in_repo_dr_script_under_its_old_object_name() -> None:
    text = (SCRIPTS / "hapax-backup-remote").read_text(encoding="utf-8")
    assert 'DR_SCRIPT="${_hapax_self%/*}/hapax-cachyos-restore.sh"' in text
    assert (
        'rclone copy "$DR_SCRIPT" b2:hapax-backups/dr-scripts/' in text
    )  # basename: hapax-cachyos-restore.sh
    assert (SCRIPTS / "hapax-cachyos-restore.sh").is_file()


def test_the_dr_script_moved_unchanged() -> None:
    digest = hashlib.sha256((SCRIPTS / "hapax-cachyos-restore.sh").read_bytes()).hexdigest()
    assert digest == LIVE_DR_SCRIPT_SHA256


def test_remote_unit_carries_the_live_memory_policy() -> None:
    unit = (UNITS / "hapax-backup-remote.service").read_text(encoding="utf-8")
    for line in ("MemoryMax=8G", "MemoryHigh=6G", "Environment=GOMEMLIMIT=6GiB"):
        assert f"{line}\n" in unit
    assert "MemoryMax=2G" not in unit
