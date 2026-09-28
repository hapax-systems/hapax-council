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

# The DR script is podium's ~/projects/distro-work/hapax-cachyos-restore.sh at 4e0087f (git blob 53b4137e6, whose own
# sha256 is fa0dafc7…), changed in exactly six hunks by the seat's exceptions (2026-09-27 10:29Z, 12:03Z, 12:12Z,
# 12:24Z, 12:33Z): the bootstrap clone (lines 22–23), Phase 2's restore selecting --tag tier2-remote (110), Phase 3's
# FileStore restore (after line 153), Phase 12's dump search (613ff), Phase 13's council remote (684) and the
# manual-steps checklist (829–830: the activator from the council checkout, unit reinstall, first backup). The
# move itself (#4820) carries two more granted hunks: RESTORE_DIR under /var/tmp (105) and Phase 14 initializing
# nothing, only warning with the NAS tier-1 target (seat rulings 2026-09-28).
# DR_SCRIPT_SHA256 below is the digest of that result, not of the live blob. The seat grants no further exception;
# any other change belongs to the follow-up row, never to a silent edit.
DR_SCRIPT_SHA256 = "ea3fe913343ef890c0056f377d5b67e2fe82582bf6be61c4a0847940781bc108"


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


def _run_dr_upload(tmp_path: Path, *, with_dr_script: bool, rclone_exit: int) -> tuple:
    """Run the remote script's own DR-upload section, cut from the script, beside a fake rclone. The full script
    cannot reach it cheaply (the pg_dumpall gate needs a real 1 GB dump), so the section runs as it is written."""

    text = (SCRIPTS / "hapax-backup-remote").read_text(encoding="utf-8")
    start = text.index('DR_SCRIPT="${_hapax_self%/*}/hapax-cachyos-restore.sh"')
    end = text.index("\n", text.index('ok "DR script uploaded'))
    here = tmp_path / "scripts"
    here.mkdir()
    if with_dr_script:
        (here / "hapax-cachyos-restore.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
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
        'log() { echo "$1"; }\nok() { echo "OK: $1"; }\n'
        f'_hapax_self="{here}/hapax-backup-remote"\n' + text[start:end] + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(probe)],
        env=dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result, (calls.read_text(encoding="utf-8") if calls.exists() else ""), here


def test_dr_upload_sends_the_in_repo_script_to_its_old_object(tmp_path: Path) -> None:
    result, calls, here = _run_dr_upload(tmp_path, with_dr_script=True, rclone_exit=0)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.strip() == f"copy {here}/hapax-cachyos-restore.sh b2:hapax-backups/dr-scripts/"
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


def _phase12_dump(tmp_path: Path, present: list[str]) -> subprocess.CompletedProcess:
    """Run the DR script's own Phase 12 dump search (from its header to the Docker stack start) against a fixture
    restore tree holding ``present`` (paths relative to RESTORE_DIR), and print the DUMP it chose."""

    text = (SCRIPTS / "hapax-cachyos-restore.sh").read_text(encoding="utf-8")
    start = text.index("# ─── Phase 12")
    end = text.index("if [[ -f ~/llm-stack/docker-compose.yml ]]", start)
    restore = tmp_path / "restore"
    for rel in present:
        (restore / rel).mkdir(parents=True)
        (restore / rel / "postgres-all.sql").write_text("-- dump\n", encoding="utf-8")
    probe = tmp_path / "phase12.sh"
    probe.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'log() { echo "$1"; }\nok() { echo "$1"; }\nwarn() { echo "$1"; }\nfail() { echo "$1"; }\n'
        f'RESTORE_DIR="{restore}"\n' + text[start:end] + 'echo "DUMP=$DUMP"\n',
        encoding="utf-8",
    )
    return subprocess.run(["bash", str(probe)], capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize(
    "present",
    [
        ["store/llm-data/backup-dumps-remote"],  # a B2 snapshot since ca32d43 (2026-09-02)
        ["store/llm-data/backup-dumps-local"],  # a NAS snapshot since ca32d43
        ["tmp/hapax-backup-dumps-remote"],  # a snapshot from before 09-02
        ["tmp/hapax-backup-dumps"],
    ],
)
def test_dr_phase12_finds_the_dumps_where_the_producers_write_them(
    tmp_path: Path, present: list[str]
) -> None:
    result = _phase12_dump(tmp_path, present)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"DUMP={tmp_path / 'restore' / present[0]}\n" in result.stdout


def test_dr_phase12_prefers_the_current_dump_location(tmp_path: Path) -> None:
    result = _phase12_dump(
        tmp_path, ["tmp/hapax-backup-dumps-remote", "store/llm-data/backup-dumps-remote"]
    )
    assert f"DUMP={tmp_path / 'restore' / 'store/llm-data/backup-dumps-remote'}\n" in result.stdout


def test_dr_phase12_requires_the_dump_file_not_just_its_directory(tmp_path: Path) -> None:
    """An empty dump directory is not a dump (#4813 review round 2 critical): skip it for a later candidate that
    holds postgres-all.sql, and refuse when none does."""

    empty = tmp_path / "a" / "restore" / "store/llm-data/backup-dumps-remote"
    empty.mkdir(parents=True)
    fallback = _phase12_dump(tmp_path / "a", ["tmp/hapax-backup-dumps-remote"])
    assert (
        f"DUMP={tmp_path / 'a' / 'restore' / 'tmp/hapax-backup-dumps-remote'}\n" in fallback.stdout
    )

    only_empty = tmp_path / "b" / "restore" / "store/llm-data/backup-dumps-local"
    only_empty.mkdir(parents=True)
    refused = _phase12_dump(tmp_path / "b", [])
    assert refused.returncode != 0
    assert "DUMP=" not in refused.stdout
    assert "postgres-all.sql" in refused.stdout


def test_dr_phase12_refuses_loudly_when_no_dump_exists(tmp_path: Path) -> None:
    """Never a silent skip of PostgreSQL and Qdrant that still reports completion (#4813 review critical)."""

    result = _phase12_dump(tmp_path, [])
    assert result.returncode != 0
    assert "DUMP=" not in result.stdout
    for rel in (
        "store/llm-data/backup-dumps-remote",
        "store/llm-data/backup-dumps-local",
        "tmp/hapax-backup-dumps-remote",
        "tmp/hapax-backup-dumps",
    ):
        assert rel in result.stdout + result.stderr


_SENTINEL = "SENTINEL-NOT-A-REAL-SECRET"


def _filestore_section() -> str:
    text = (SCRIPTS / "hapax-cachyos-restore.sh").read_text(encoding="utf-8")
    start = text.index("# ─── FileStore (")
    return text[start : text.index("# ─── end FileStore", start)]


def _restore_filestore(tmp_path: Path, blobs: list[str] | None) -> tuple:
    """Run the DR script's own Phase 3 FileStore section against a fixture restored home. ``blobs`` are the .bin
    names in the snapshot's FileStore (None: the snapshot holds no FileStore). Each blob holds a sentinel value."""

    rhome = tmp_path / "restore" / "home" / "hapax"
    rhome.mkdir(parents=True)
    if blobs is not None:
        store = rhome / ".config" / "reins" / "secrets"
        store.mkdir(parents=True)
        (store / ".key").write_text(_SENTINEL + "-key", encoding="utf-8")
        for name in blobs:
            (store / name).write_text(f"{_SENTINEL}-{name}", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    probe = tmp_path / "filestore.sh"
    probe.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'log() { echo "$1"; }\nok() { echo "OK $1"; }\nwarn() { echo "WARN $1"; }\nfail() { echo "FAIL $1"; }\n'
        f'RHOME="{rhome}"\n' + _filestore_section(),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(probe)],
        env=dict(os.environ, HOME=str(home)),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result, home / ".config" / "reins" / "secrets"


def test_dr_restores_the_filestore_with_its_modes_and_verifies_the_entry_names(
    tmp_path: Path,
) -> None:
    result, store = _restore_filestore(
        tmp_path,
        ["backups-restic-password.bin", "backblaze-restic-password.bin", "other-entry.bin"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (store / ".key").is_file() and (store / "other-entry.bin").is_file()
    assert oct(store.stat().st_mode & 0o777) == "0o700"
    assert {oct(p.stat().st_mode & 0o777) for p in store.iterdir()} == {"0o600"}
    assert "OK FileStore entry present: backups/restic-password" in result.stdout
    assert "OK FileStore entry present: backblaze/restic-password" in result.stdout
    assert _SENTINEL not in result.stdout + result.stderr  # no secret value is ever printed


def test_dr_names_a_missing_filestore_entry(tmp_path: Path) -> None:
    result, _ = _restore_filestore(tmp_path, ["backups-restic-password.bin"])
    assert result.returncode == 0
    assert "WARN FileStore entry missing: backblaze/restic-password" in result.stdout
    assert "hapax-secret backblaze/restic-password" in result.stdout
    assert _SENTINEL not in result.stdout + result.stderr


def test_dr_warns_with_the_next_action_when_the_snapshot_has_no_filestore(tmp_path: Path) -> None:
    result, store = _restore_filestore(tmp_path, None)
    assert result.returncode == 0  # an older snapshot must still restore
    assert "WARN The snapshot holds no FileStore" in result.stdout
    assert "hapax-secret" in result.stdout and not store.exists()


def test_dr_filestore_section_reads_no_secret_value() -> None:
    """The section copies the store and tests names with -f; nothing in it opens a blob's content."""

    section = _filestore_section()
    code = "\n".join(line for line in section.splitlines() if not line.lstrip().startswith("#"))
    code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)  # messages are text, not commands
    readers = re.findall(
        r"(?:^|[\s;&|(`])(cat|head|tail|read|less|more|strings|xxd|od|hapax-secret)(?=\s)",
        code,
        re.M,
    )
    assert readers == [], readers
    assert not re.search(r"(?<![<])<(?![<(])\s*\S", code), "an input redirect reads a file"


def _manual_steps() -> list[str]:
    text = (SCRIPTS / "hapax-cachyos-restore.sh").read_text(encoding="utf-8")
    block = text[text.index('log "Manual steps:"') : text.index('log "Verification:"')]
    return re.findall(r'^echo "\s*\d+\. (.*)"$', block, re.M)


def test_dr_final_step_starts_the_backup_service() -> None:
    text = (SCRIPTS / "hapax-cachyos-restore.sh").read_text(encoding="utf-8")
    assert "First local backup: systemctl --user start hapax-backup-local.service" in text
    assert "~/.local/bin/hapax-backup-local.sh" not in text


def test_dr_steps_build_the_activation_worktree_and_verify_it_before_any_start() -> None:
    """The migrated units run from the activation worktree, which .cache exclusion leaves out of every snapshot;
    hapax-source-activate builds it from ~/projects/hapax-council (#4813 round 5, seat exception 12:12Z)."""

    steps = _manual_steps()
    activate = next(i for i, s in enumerate(steps) if "hapax-source-activate" in s)
    assert (
        "test -x ~/.cache/hapax/source-activation/worktree/scripts/hapax-backup-local"
        in steps[activate]
    )
    sync = next(i for i, s in enumerate(steps) if "uv sync" in s)
    starts = [i for i, s in enumerate(steps) if "systemctl --user start" in s]
    assert sync < activate < min(starts)


def test_dr_steps_run_the_activator_from_the_council_checkout() -> None:
    """A restored ~/.local/bin/hapax-source-activate may be a symlink into the activation worktree, which no snapshot
    holds; the checkout's own copy always exists after the clone (seat exception 6, 2026-09-27 12:24Z)."""

    steps = _manual_steps()
    activate = next(s for s in steps if "hapax-source-activate" in s)
    assert "~/projects/hapax-council/scripts/hapax-source-activate &&" in activate
    assert "~/.local/bin/hapax-source-activate" not in activate
    assert (
        SCRIPTS / "hapax-source-activate"
    ).is_file()  # the path the step names exists in council


def test_dr_restore_selects_the_tier2_snapshot_by_tag() -> None:
    """Exception 8 (seat 2026-09-27 12:33Z): a bare `latest` is the newest snapshot of any tag, the #4803 class. B2's
    only writer tags tier2-remote, so this is a guard, not a behaviour change."""

    text = (SCRIPTS / "hapax-cachyos-restore.sh").read_text(encoding="utf-8")
    restores = re.findall(r"^restic restore .*$", text, re.M)
    assert restores == [
        'restic restore latest --tag tier2-remote --target "$RESTORE_DIR" --no-lock --verbose 2>&1 | tail -3'
    ]


def test_dr_phase13_clones_council_from_hapax_systems() -> None:
    """Seat exception 7: the repository map clones council from its current owner, as the bootstrap does."""

    text = (SCRIPTS / "hapax-cachyos-restore.sh").read_text(encoding="utf-8")
    assert '    [hapax-council]="hapax-systems/hapax-council"\n' in text
    assert '[hapax-council]="ryanklee/hapax-council"' not in text


def test_dr_steps_reinstall_the_backup_units_from_council_before_the_first_backup() -> None:
    """Units restored from an older snapshot's ~/.config/systemd/user still run distro-work."""

    steps = _manual_steps()
    reinstall = next(i for i, s in enumerate(steps) if "install -m 644" in s)
    assert (
        "~/projects/hapax-council/systemd/units/hapax-backup-{local,remote}.service ~/.config/systemd/user/"
        in steps[reinstall]
    )
    assert "systemctl --user daemon-reload" in steps[reinstall]
    first_backup = next(
        i for i, s in enumerate(steps) if "hapax-backup-local.service" in s and "start" in s
    )
    activate = next(i for i, s in enumerate(steps) if "hapax-source-activate" in s)
    assert activate < reinstall < first_backup


def test_dr_bootstrap_clones_council_not_the_archived_repository() -> None:
    header = (
        (SCRIPTS / "hapax-cachyos-restore.sh")
        .read_text(encoding="utf-8")
        .split("# YOU NEED TO KNOW")[0]
    )
    assert "gh repo clone hapax-systems/hapax-council" in header
    assert "./hapax-council/scripts/hapax-cachyos-restore.sh" in header
    assert "gh repo clone ryanklee/distro-work" not in header


def test_dr_upload_failure_names_a_next_action(tmp_path: Path) -> None:
    result, _, _ = _run_dr_upload(tmp_path, with_dr_script=True, rclone_exit=1)
    assert "rclone lsd b2:hapax-backups" in result.stdout and "rerun" in result.stdout


def test_the_dr_script_is_the_live_one_plus_the_two_granted_hunks() -> None:
    digest = hashlib.sha256((SCRIPTS / "hapax-cachyos-restore.sh").read_bytes()).hexdigest()
    assert digest == DR_SCRIPT_SHA256


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
