from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.scripts.backup_test_support import SCRIPTS

RESTORE_SCRIPT = SCRIPTS / "hapax-cachyos-restore"
DUMP_PATHS = (
    "store/llm-data/backup-dumps-remote",
    "store/llm-data/backup-dumps-local",
)


@pytest.mark.parametrize("relative_path", DUMP_PATHS)
def test_restore_resolves_each_producer_dump_path(tmp_path: Path, relative_path: str) -> None:
    expected = tmp_path / relative_path
    expected.mkdir(parents=True)

    result = subprocess.run(
        [str(RESTORE_SCRIPT), "--resolve-dump-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == str(expected)


def test_restore_dump_lookup_fails_loudly_with_every_searched_path(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(RESTORE_SCRIPT), "--resolve-dump-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "No database dump directory found" in result.stderr
    for relative_path in DUMP_PATHS:
        assert str(tmp_path / relative_path) in result.stderr


def test_restored_dump_survives_tmpfs_mount_step_in_documented_order(
    tmp_path: Path,
) -> None:
    fake_root = tmp_path / "fake-root"
    restore_root = fake_root / "var/tmp/hapax-restore"
    expected_dump = restore_root / DUMP_PATHS[0]
    probe = tmp_path / "restore-sequence.sh"
    probe.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
source "$1"
restore_root="$2/var/tmp/hapax-restore"
prepare_restore_root "$restore_root"
mkdir -p "$restore_root/store/llm-data/backup-dumps-remote"
mkdir -p "$2/tmp/restored-tree-that-mount-must-hide"
current_filesystem_type() { printf '%s\n' btrfs; }
record_tmpfs_mount() { :; }
mount_tmpfs_at() { rm -rf -- "$1"; mkdir -p -- "$1"; }
ensure_tmpfs_tmp "$2/tmp" "$2/etc/fstab"
find_restore_dump_dir "$restore_root"
""",
        encoding="utf-8",
    )
    probe.chmod(0o755)
    env = os.environ.copy()

    result = subprocess.run(
        [str(probe), str(RESTORE_SCRIPT), str(fake_root)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == str(expected_dump)
    assert not (fake_root / "tmp/restored-tree-that-mount-must-hide").exists()
    assert expected_dump.is_dir()
    assert 'RESTORE_ROOT="/var/tmp/hapax-restore"' in RESTORE_SCRIPT.read_text(encoding="utf-8")


def _n8n_import(
    tmp_path: Path,
    dump_dir: Path,
    *,
    fail_import: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fake_bin = tmp_path / "bin"
    command_log = tmp_path / "sudo.log"
    fake_bin.mkdir(exist_ok=True)
    sudo = fake_bin / "sudo"
    sudo.write_text(
        """#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$COMMAND_LOG"
if [ "${N8N_IMPORT_FAIL:-0}" = 1 ] && echo "$*" | grep -q 'import:workflow'; then
    exit 7
fi
"""
    )
    sudo.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "COMMAND_LOG": str(command_log),
            "N8N_IMPORT_FAIL": "1" if fail_import else "0",
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        }
    )
    result = subprocess.run(
        [str(RESTORE_SCRIPT), "--import-n8n-workflows", str(dump_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    commands = command_log.read_text().splitlines() if command_log.exists() else []
    return result, commands


def test_n8n_import_runs_only_when_export_exists_and_fails_closed(tmp_path: Path) -> None:
    dump_dir = tmp_path / "dump"
    dump_dir.mkdir()

    missing_result, missing_commands = _n8n_import(tmp_path, dump_dir)
    assert missing_result.returncode != 0
    assert missing_commands == []
    assert str(dump_dir / "n8n-workflows.json") in missing_result.stderr

    workflow_dump = dump_dir / "n8n-workflows.json"
    workflow_dump.write_text("{}")
    success_result, success_commands = _n8n_import(tmp_path, dump_dir)
    assert success_result.returncode == 0
    assert success_commands == [
        f"docker cp {workflow_dump} n8n:/tmp/n8n-workflows.json",
        "docker exec n8n n8n import:workflow --input=/tmp/n8n-workflows.json",
    ]

    failed_result, _ = _n8n_import(tmp_path, dump_dir, fail_import=True)
    assert failed_result.returncode != 0
    assert "n8n workflow import failed" in failed_result.stderr


def test_postgres_import_uses_hapax_role_and_fails_closed(tmp_path: Path) -> None:
    dump_dir = tmp_path / "dump"
    dump_dir.mkdir()
    (dump_dir / "postgres-all.sql").write_text("SELECT 1;\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "sudo.log"
    sudo = fake_bin / "sudo"
    sudo.write_text(
        """#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$COMMAND_LOG"
case "$*" in
    *" psql "*) exit 7 ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    probe = tmp_path / "postgres-restore.sh"
    probe.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
source "$1"
wait_for_postgresql
restore_postgresql "$2"
""",
        encoding="utf-8",
    )
    probe.chmod(0o755)
    env = os.environ.copy()
    env.update({"COMMAND_LOG": str(command_log), "PATH": f"{fake_bin}:/usr/bin:/bin"})

    result = subprocess.run(
        [str(probe), str(RESTORE_SCRIPT), str(dump_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode != 0
    assert "PostgreSQL import failed" in result.stderr
    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "docker exec postgres pg_isready -U hapax",
        "docker exec -i postgres psql -U hapax -v ON_ERROR_STOP=1",
    ]


def test_qdrant_upload_failure_is_fatal_and_names_collection(tmp_path: Path) -> None:
    dump_dir = tmp_path / "dump"
    qdrant_dir = dump_dir / "qdrant"
    qdrant_dir.mkdir(parents=True)
    (qdrant_dir / "test-collection.snapshot").write_text("snapshot", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text("#!/bin/sh\nexit 22\n", encoding="utf-8")
    curl.chmod(0o755)
    probe = tmp_path / "qdrant-restore.sh"
    probe.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
source "$1"
restore_qdrant_snapshots "$2"
""",
        encoding="utf-8",
    )
    probe.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:/usr/bin:/bin"

    result = subprocess.run(
        [str(probe), str(RESTORE_SCRIPT), str(dump_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Qdrant snapshot upload failed for collection test-collection" in result.stderr


def test_restore_reports_the_canonical_dr_object_name() -> None:
    result = subprocess.run(
        [str(RESTORE_SCRIPT), "--print-dr-object-name"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )

    assert result.stdout.strip() == "hapax-cachyos-restore.sh"
