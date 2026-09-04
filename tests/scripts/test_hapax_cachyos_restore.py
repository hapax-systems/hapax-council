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


def test_postgres_import_filters_only_preexisting_superuser_from_pg_dumpall(
    tmp_path: Path,
) -> None:
    dump_dir = tmp_path / "dump"
    dump_dir.mkdir()
    postgres_dump = dump_dir / "postgres-all.sql"
    postgres_dump.write_text(
        """--
-- PostgreSQL database cluster dump
--

SET default_transaction_read_only = off;

--
-- Roles
--

CREATE ROLE hapax;
ALTER ROLE hapax WITH SUPERUSER INHERIT CREATEROLE CREATEDB LOGIN;
CREATE ROLE app_reader;
ALTER ROLE app_reader WITH NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB NOLOGIN;

--
-- Database creation
--

CREATE DATABASE hapax WITH TEMPLATE = template0 OWNER = hapax;
ALTER DATABASE hapax OWNER TO hapax;
\\connect hapax
CREATE TABLE public.restore_probe (id integer);
CREATE DATABASE app WITH TEMPLATE = template0 OWNER = hapax;

-- PostgreSQL database cluster dump complete
""",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "sudo.log"
    psql_input = tmp_path / "psql-input.sql"
    sudo = fake_bin / "sudo"
    sudo.write_text(
        """#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$COMMAND_LOG"
case "$*" in
    *" pg_isready "*) exit 0 ;;
    *" psql "*)
        cat > "$PSQL_INPUT"
        if grep -Fxq 'CREATE ROLE hapax;' "$PSQL_INPUT" \
            || grep -Eq '^CREATE DATABASE hapax([ ;])' "$PSQL_INPUT"; then
            printf '%s\n' 'ERROR: bootstrap role or database already exists' >&2
            exit 7
        fi
        grep -Fq 'CREATE DATABASE app' "$PSQL_INPUT"
        exit 0
        ;;
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
    env.update(
        {
            "COMMAND_LOG": str(command_log),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "PSQL_INPUT": str(psql_input),
        }
    )

    result = subprocess.run(
        [str(probe), str(RESTORE_SCRIPT), str(dump_dir)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    restored_sql = psql_input.read_text(encoding="utf-8")
    assert "CREATE ROLE hapax;" not in restored_sql
    assert "ALTER ROLE hapax WITH SUPERUSER" in restored_sql
    assert "CREATE DATABASE hapax" not in restored_sql
    assert "ALTER DATABASE hapax OWNER TO hapax" in restored_sql
    assert "\\connect hapax" in restored_sql
    assert "CREATE ROLE app_reader;" in restored_sql
    assert "CREATE DATABASE app" in restored_sql
    assert command_log.read_text(encoding="utf-8").splitlines() == [
        "docker exec postgres pg_isready -U hapax",
        "docker exec -i postgres psql -U hapax -v ON_ERROR_STOP=1",
    ]


def _ensure_storage_roots(
    tmp_path: Path,
    *,
    fail_root: str = "",
) -> tuple[subprocess.CompletedProcess[str], Path, list[str]]:
    fake_root = tmp_path / "fake-root"
    fake_bin = tmp_path / "bin"
    command_log = tmp_path / "mount-commands.log"
    fake_bin.mkdir()
    sudo = fake_bin / "sudo"
    sudo.write_text(
        """#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$COMMAND_LOG"
case "${1:-}" in
    mkdir) shift; exec /usr/bin/mkdir "$@" ;;
    mount)
        target=$2
        if [ -n "$MOUNT_FAIL_ROOT" ]; then
            case "$target" in
                *"$MOUNT_FAIL_ROOT") exit 32 ;;
            esac
        fi
        : > "$target/.mounted"
        ;;
esac
""",
        encoding="utf-8",
    )
    sudo.chmod(0o755)
    mountpoint = fake_bin / "mountpoint"
    mountpoint.write_text(
        """#!/bin/sh
set -eu
[ "${1:-}" = -q ]
[ -f "$2/.mounted" ]
""",
        encoding="utf-8",
    )
    mountpoint.chmod(0o755)
    probe = tmp_path / "storage-roots.sh"
    probe.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
source "$1"
load_backup_storage_roots "$2"
ensure_backup_storage_roots "$3"
""",
        encoding="utf-8",
    )
    probe.chmod(0o755)
    registry = RESTORE_SCRIPT.parents[1] / "config/infrastructure/host-storage-registry.json"
    env = os.environ.copy()
    env.update(
        {
            "COMMAND_LOG": str(command_log),
            "MOUNT_FAIL_ROOT": fail_root,
            "PATH": f"{fake_bin}:/usr/bin:/bin",
        }
    )
    result = subprocess.run(
        [str(probe), str(RESTORE_SCRIPT), str(registry), str(fake_root)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    commands = command_log.read_text(encoding="utf-8").splitlines()
    return result, fake_root, commands


def test_restore_creates_and_mounts_registry_storage_roots_under_fake_root(
    tmp_path: Path,
) -> None:
    result, fake_root, commands = _ensure_storage_roots(tmp_path)

    assert result.returncode == 0, result.stderr
    assert (fake_root / "store/.mounted").is_file()
    assert (fake_root / "mnt/nas/.mounted").is_file()
    assert not (fake_root / "data").exists()
    assert f"mount {fake_root}/store" in commands
    assert f"mount {fake_root}/mnt/nas" in commands
    restore_text = RESTORE_SCRIPT.read_text(encoding="utf-8")
    assert "/data/backups/restic" not in restore_text
    assert 'LOCAL_RESTIC_REPO="$TIER1_STORAGE_ROOT/backups/restic"' in restore_text


def test_restore_fails_loudly_naming_unmountable_registry_root(tmp_path: Path) -> None:
    result, _fake_root, _commands = _ensure_storage_roots(tmp_path, fail_root="/mnt/nas")

    assert result.returncode != 0
    assert "Required backup storage root /mnt/nas could not be mounted" in result.stderr


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


def test_phase_12_orchestration_fails_when_compose_configuration_is_missing(
    tmp_path: Path,
) -> None:
    restore_root = tmp_path / "restore"
    (restore_root / DUMP_PATHS[0]).mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    missing_compose = home / "llm-stack/docker-compose.yml"
    probe = tmp_path / "phase-12.sh"
    probe.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
source "$1"
restore_database_services "$2"
""",
        encoding="utf-8",
    )
    probe.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(home)

    result = subprocess.run(
        [str(probe), str(RESTORE_SCRIPT), str(restore_root)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Using database dumps" in result.stdout
    assert f"Required Docker Compose configuration is missing: {missing_compose}" in result.stderr
    assert "restore llm-stack/docker-compose.yml" in result.stderr
    assert 'restore_database_services "$RESTORE_ROOT"' in RESTORE_SCRIPT.read_text(encoding="utf-8")


def test_restore_reports_the_canonical_dr_object_name() -> None:
    result = subprocess.run(
        [str(RESTORE_SCRIPT), "--print-dr-object-name"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )

    assert result.stdout.strip() == "hapax-cachyos-restore.sh"
