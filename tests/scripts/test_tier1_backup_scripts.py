"""The tier-1 (NAS) and tier-2 (B2) backup scripts, moved from the archived distro-work repository into council.

Row tier1-backup-scripts-into-council-reland-r2-20260927 (option A, seat ruling 2026-09-27 10:13Z): a faithful move
of what podium ran at distro-work 4e0087f, with FileStore secrets, and the FileStore itself backed up (seat exception
11:55Z). The never-prune rule for tier1-transcripts is pinned by tests/test_transcript_custody.py's tree-wide forget
scan, which now covers these scripts. The DR restore script stays where it lives today; moving it is its own PR (seat
ruling 12:41Z).
"""

from __future__ import annotations

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
LIVE_DR_SCRIPT = '"$HOME/projects/distro-work/hapax-cachyos-restore.sh"'


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


@pytest.mark.parametrize("script", BACKUP_SCRIPTS)
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


def test_remote_uploads_the_dr_script_from_where_it_lives_today() -> None:
    """Faithful to live: the DR script is not moved by this PR (seat ruling 2026-09-27 12:41Z)."""

    text = (SCRIPTS / "hapax-backup-remote").read_text(encoding="utf-8")
    assert f"DR_SCRIPT={LIVE_DR_SCRIPT}\n" in text
    assert 'rclone copy "$DR_SCRIPT" b2:hapax-backups/dr-scripts/' in text
    assert not (SCRIPTS / "hapax-cachyos-restore.sh").exists()


def _run_dr_upload(tmp_path: Path, *, with_dr_script: bool, rclone_exit: int) -> tuple:
    """Run the remote script's own DR-upload section, cut from the script, beside a fake rclone. The full script
    cannot reach it cheaply (the pg_dumpall gate needs a real 1 GB dump), so the section runs as it is written."""

    text = (SCRIPTS / "hapax-backup-remote").read_text(encoding="utf-8")
    start = text.index(f"DR_SCRIPT={LIVE_DR_SCRIPT}")
    end = text.index("\n", text.index('ok "DR script uploaded'))
    home = tmp_path / "home"
    dr_dir = home / "projects" / "distro-work"
    dr_dir.mkdir(parents=True)
    if with_dr_script:
        (dr_dir / "hapax-cachyos-restore.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "rclone.log"
    (bin_dir / "rclone").write_text(
        f'#!/usr/bin/env bash\necho "$*" >> "{calls}"\nexit {rclone_exit}\n', encoding="utf-8"
    )
    (bin_dir / "rclone").chmod(0o755)
    probe = tmp_path / "probe.sh"
    probe.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'log() { echo "$1"; }\nok() { echo "OK: $1"; }\n' + text[start:end] + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(probe)],
        env=dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin", HOME=str(home)),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result, (calls.read_text(encoding="utf-8") if calls.exists() else ""), dr_dir


def test_dr_upload_sends_the_script_to_its_object(tmp_path: Path) -> None:
    result, calls, dr_dir = _run_dr_upload(tmp_path, with_dr_script=True, rclone_exit=0)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.strip() == f"copy {dr_dir}/hapax-cachyos-restore.sh b2:hapax-backups/dr-scripts/"
    assert "OK: DR script uploaded: hapax-cachyos-restore.sh" in result.stdout


def test_dr_upload_fails_loudly_when_the_script_is_missing(tmp_path: Path) -> None:
    result, calls, _ = _run_dr_upload(tmp_path, with_dr_script=False, rclone_exit=0)
    assert result.returncode == 1
    assert "FATAL: DR script missing at" in result.stdout
    assert calls == ""  # nothing uploaded


def test_dr_upload_fails_loudly_when_rclone_fails(tmp_path: Path) -> None:
    result, _, _ = _run_dr_upload(tmp_path, with_dr_script=True, rclone_exit=1)
    assert result.returncode == 1
    assert "FATAL: DR script upload failed" in result.stdout


def test_the_forget_scan_covers_the_moved_scripts() -> None:
    """The never-prune rule for tier1-transcripts is pinned by the tree-wide scan; it must actually see these."""

    from tests import test_transcript_custody as custody

    found = {where.split(":")[0]: args for where, args in custody._forget_invocations()}
    for script in BACKUP_SCRIPTS:
        assert f"scripts/{script}" in found, sorted(found)
        assert custody.tc.forget_protects_transcripts(found[f"scripts/{script}"])


def _restic_backup_paths(script: str) -> list[str]:
    """The quoted path arguments of the script's `restic backup` command (continuation lines joined)."""

    text = (SCRIPTS / script).read_text(encoding="utf-8")
    start = text.index("restic backup \\")
    end = text.index("\n\n", start)
    return re.findall(r'^\s*"([^"]+)" \\$', text[start:end], re.M)


@pytest.mark.parametrize("script", BACKUP_SCRIPTS)
def test_the_filestore_is_backed_up_with_the_other_secret_stores(script: str) -> None:
    """The FileStore holds the estate's secrets since the 09-16 migration, including the restic passwords these
    scripts read; it was in no backup (seat exception 2026-09-27 11:55Z). It travels inside the encrypted repository,
    beside ~/.password-store/ and ~/.gnupg/."""

    paths = _restic_backup_paths(script)
    assert "$HOME/.config/reins/secrets/" in paths
    assert "$HOME/.password-store/" in paths and "$HOME/.gnupg/" in paths


def test_remote_unit_carries_the_live_memory_policy() -> None:
    unit = (UNITS / "hapax-backup-remote.service").read_text(encoding="utf-8")
    for line in ("MemoryMax=8G", "MemoryHigh=6G", "Environment=GOMEMLIMIT=6GiB"):
        assert f"{line}\n" in unit
    assert "MemoryMax=2G" not in unit
