from __future__ import annotations

import json
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
    assert 'RESTORE_ROOT="${HAPAX_RESTORE_ROOT:-/var/tmp/hapax-restore}"' in (
        RESTORE_SCRIPT.read_text(encoding="utf-8")
    )


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
DUMP=$(find_restore_dump_dir "$2")
restore_database_services "$DUMP"
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
    script = RESTORE_SCRIPT.read_text(encoding="utf-8")
    assert 'DUMP=$(find_restore_dump_dir "$RESTORE_ROOT")' in script
    assert 'restore_database_services "$DUMP"' in script


def test_restore_reports_the_canonical_dr_object_name() -> None:
    result = subprocess.run(
        [str(RESTORE_SCRIPT), "--print-dr-object-name"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )

    assert result.stdout.strip() == "hapax-cachyos-restore.sh"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _run_full_restore(
    tmp_path: Path,
    *,
    fail_enable_unit: str = "",
    fail_pass_insert_entry: str = "",
    fail_pass_list: bool = False,
    fail_verify_unit: str = "",
    mismatch_pass_show_entry: str = "",
    omit_restore_dump: bool = False,
    report_state_unit: str = "",
    reported_state: str = "enabled",
    compose_profile: str | None = "full",
    omit_env_file: str = "",
    omit_stack: bool = False,
    fail_council_clones: bool = False,
    empty_council_checkout: bool = False,
    fail_compose: bool = False,
    drop_copied_env: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[str], Path]:
    home = tmp_path / "home"
    restore_root = tmp_path / "restore-root"
    store_root = tmp_path / "store"
    tier1_root = tmp_path / "nas"
    fake_bin = tmp_path / "bin"
    bash_env = tmp_path / "bash-env"
    command_log = tmp_path / "commands.log"
    pass_state = tmp_path / "pass-state"
    registry = tmp_path / "host-storage-registry.json"
    compose_contract = tmp_path / "llm-stack.service"
    contract_text = (SCRIPTS.parent / "systemd/units/llm-stack.service").read_text()
    contract_text = contract_text.replace(
        "--profile full", "" if compose_profile is None else f"--profile {compose_profile}"
    )
    compose_contract.write_text(contract_text)
    home.mkdir()
    if omit_env_file or omit_stack:
        # A pre-existing destination must not hide missing recovery inputs.
        (home / "llm-stack").mkdir()
        for env_file in (".env", ".envrc"):
            (home / "llm-stack" / env_file).write_text("# stale destination fixture\n")
    fake_bin.mkdir()
    registry.write_text(
        json.dumps(
            {
                "backup_policies": [
                    {
                        "store_id": "local-nas-restic",
                        "target_host": "restore-host",
                        "required_mount_roots": [str(store_root), str(tier1_root)],
                    },
                    {
                        "store_id": "b2-restic-offsite",
                        "target_host": "restore-host",
                        "required_mount_roots": [str(store_root)],
                    },
                ],
                "mounts": [
                    {
                        "target_host": "restore-host",
                        "mountpoints": [str(store_root)],
                        "uuid": "restore-test-uuid",
                        "device_ref": {"serial": "restore-test-serial"},
                    }
                ],
                "devices": [
                    {
                        "target_host": "restore-host",
                        "serial": "restore-test-serial",
                        "by_id": ["/dev/disk/by-id/restore-test-disk"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rclone_config = home / ".config" / "rclone" / "rclone.conf"
    rclone_config.parent.mkdir(parents=True)
    rclone_config.write_text("active-b2-config\n", encoding="utf-8")
    stale_pass_entry = pass_state / "backups" / "restic-password"
    stale_pass_entry.parent.mkdir(parents=True)
    stale_pass_entry.write_text("stale\n", encoding="utf-8")  # pragma: allowlist secret

    _write_executable(
        fake_bin / "restic",
        """#!/bin/sh
set -eu
if [ "${1:-}" = restore ]; then
    target=
    while [ "$#" -gt 0 ]; do
        if [ "$1" = --target ]; then
            target=$2
            break
        fi
        shift
    done
    home_seg=home
    backed_up_rclone="$target/${home_seg}/backup-user/.config/rclone/rclone.conf"
    mkdir -p "$target/${home_seg}/backup-user/llm-stack" "$(dirname "$backed_up_rclone")"
    stack="$target/${home_seg}/backup-user/llm-stack"
    printf '%s\n' 'services: {}' > "$stack/docker-compose.yml"
    printf '%s\n' '# restored environment fixture' > "$stack/.env"
    printf '%s\n' '# restored direnv fixture' > "$stack/.envrc"
    if [ -n "$OMIT_ENV_FILE" ]; then rm "$stack/$OMIT_ENV_FILE"; fi
    if [ "$OMIT_STACK" = 1 ]; then rm -rf "$stack"; fi
    printf '%s\n' 'stale-b2-config' > "$backed_up_rclone"
    if [ "${OMIT_RESTORE_DUMP:-0}" != 1 ]; then
        dump="$target/store/llm-data/backup-dumps-remote"
        mkdir -p "$dump/qdrant" "$dump/git-bundles"
        printf '%s\n' 'SELECT 1;' > "$dump/postgres-all.sql"
        printf '%s\n' '{}' > "$dump/n8n-workflows.json"
        printf '%s\n' 'snapshot' > "$dump/qdrant/restore-test.snapshot"
        printf '%s\n' 'bundle' > "$dump/git-bundles/obsidian-hapax.bundle"
    fi
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "sudo",
        """#!/bin/sh
set -eu
case "${1:-}" in
    mkdir)
        shift
        exec /usr/bin/mkdir "$@"
        ;;
    blkid)
        printf '%s\n' /dev/restore-test
        ;;
    docker)
        shift
        exec "$RESTORE_FAKE_BIN/docker" "$@"
        ;;
    tee)
        cat > /dev/null
        ;;
esac
exit 0
""",
    )
    _write_executable(
        fake_bin / "systemctl",
        """#!/bin/sh
set -eu
printf '%s\n' "$*" >> "$COMMAND_LOG"
case " $* " in
    *" enable $FAIL_ENABLE_UNIT ") exit 7 ;;
    *" is-enabled $FAIL_VERIFY_UNIT ") exit 8 ;;
    *" is-enabled $REPORT_STATE_UNIT ") printf '%s\n' "$REPORTED_STATE" ;;
    *" is-enabled "*) printf '%s\n' enabled ;;
esac
exit 0
""",
    )
    _write_executable(
        fake_bin / "git",
        """#!/bin/sh
set -eu
printf 'git %s\n' "$*" >> "$COMMAND_LOG"
if [ "${1:-}" = clone ]; then
    case "$2" in
        *hapax-council*)
            [ "$FAIL_COUNCIL_CLONES" != 1 ] || exit 7
            if [ "$EMPTY_COUNCIL_CHECKOUT" = 1 ]; then exit 0; fi
            mkdir -p "$3/systemd/units"
            cp "$COMPOSE_CONTRACT_FIXTURE" "$3/systemd/units/llm-stack.service"
            ;;
    esac
    mkdir -p "$3/.git"
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "gh",
        """#!/bin/sh
set -eu
printf 'gh %s\n' "$*" >> "$COMMAND_LOG"
if [ "${1:-}" = repo ] && [ "${2:-}" = clone ] && [ "$3" = hapax-systems/hapax-council ]; then
    [ "$FAIL_COUNCIL_CLONES" != 1 ] || exit 8
    exec "$RESTORE_FAKE_BIN/git" clone "$3" "$4"
fi
""",
    )
    _write_executable(
        fake_bin / "docker",
        """#!/bin/sh
set -eu
printf 'docker %s\n' "$*" >> "$COMMAND_LOG"
if [ "${1:-}" = compose ]; then
    [ "$*" = "compose -f $HOME/llm-stack/docker-compose.yml --profile $COMPOSE_PROFILE up -d" ] || exit 10
    [ -f "$HOME/llm-stack/.env" ] && [ -f "$HOME/llm-stack/.envrc" ] || exit 11
    [ "$FAIL_COMPOSE" != 1 ] || exit 12
    : > "$HOME/stack-started"
elif [ "${1:-}" = exec ]; then
    [ -f "$HOME/stack-started" ] || exit 13
    case " $* " in
        *" psql "*) cat > "$HOME/restored-postgres.sql" ;;
    esac
elif [ "${1:-}" = cp ]; then
    [ -s "$2" ] || exit 14
fi
""",
    )
    _write_executable(
        fake_bin / "cp",
        """#!/bin/sh
set -eu
/usr/bin/cp "$@"
if [ "$DROP_COPIED_ENV" = 1 ]; then
    rm -f "$HOME/llm-stack/.env"
fi
""",
    )
    _write_executable(fake_bin / "mountpoint", "#!/bin/sh\nexit 0\n")
    _write_executable(fake_bin / "findmnt", "#!/bin/sh\nprintf '%s\\n' tmpfs\n")
    _write_executable(fake_bin / "curl", "#!/bin/sh\nexit 0\n")
    _write_executable(fake_bin / "pacman", "#!/bin/sh\nexit 1\n")
    _write_executable(fake_bin / "rclone", "#!/bin/sh\nprintf '%s\\n' 'b2:'\n")
    _write_executable(fake_bin / "rustup", "#!/bin/sh\nprintf '%s\\n' stable\n")
    _write_executable(
        fake_bin / "pass",
        """#!/bin/sh
set -eu
printf 'pass %s\n' "$*" >> "$COMMAND_LOG"
case "${1:-}" in
    ls)
        [ "${FAIL_PASS_LIST:-0}" != 1 ]
        ;;
    insert)
        entry=
        force=0
        for argument in "$@"; do
            [ "$argument" != -f ] || force=1
            entry=$argument
        done
        [ "$entry" != "${FAIL_PASS_INSERT_ENTRY:-}" ] || exit 9
        destination="$PASS_STATE/$entry"
        if [ -e "$destination" ] && [ "$force" != 1 ]; then exit 10; fi
        mkdir -p "$(dirname "$destination")"
        cat > "$destination"
        ;;
    show)
        entry=${2:-}
        if [ "$entry" = "${MISMATCH_PASS_SHOW_ENTRY:-}" ]; then
            printf '%s\n' stale # pragma: allowlist secret
        else
            cat "$PASS_STATE/$entry"
        fi
        ;;
esac
""",
    )
    passthrough_commands = (
        "aichat",
        "claude",
        "fabric",
        "fc-cache",
        "fish",
        "flatpak",
        "fnm",
        "go",
        "mods",
        "ollama",
        "paru",
        "pipx",
        "pnpm",
        "sleep",
        "uv",
        "wpctl",
    )
    for command in passthrough_commands:
        _write_executable(fake_bin / command, "#!/bin/sh\nexit 0\n")
    bash_env.write_text(
        "\n".join(
            f'{command}() {{ "$RESTORE_FAKE_BIN/{command}" "$@"; }}'
            for command in (
                *passthrough_commands,
                "curl",
                "cp",
                "docker",
                "findmnt",
                "gh",
                "git",
                "mountpoint",
                "pacman",
                "pass",
                "rclone",
                "restic",
                "rustup",
                "sudo",
                "systemctl",
            )
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "B2_APP_KEY": "restore-test-app-key",  # pragma: allowlist secret
            "B2_KEY_ID": "restore-test-key-id",  # pragma: allowlist secret
            "BASH_ENV": str(bash_env),
            "COMMAND_LOG": str(command_log),
            "FAIL_ENABLE_UNIT": fail_enable_unit,
            "FAIL_PASS_INSERT_ENTRY": fail_pass_insert_entry,
            "FAIL_PASS_LIST": "1" if fail_pass_list else "0",
            "FAIL_VERIFY_UNIT": fail_verify_unit,
            "HAPAX_HOST_STORAGE_REGISTRY": str(registry),
            "HAPAX_RESTORE_ROOT": str(restore_root),
            "HOME": str(home),
            "MISMATCH_PASS_SHOW_ENTRY": mismatch_pass_show_entry,
            "OMIT_RESTORE_DUMP": "1" if omit_restore_dump else "0",
            "COMPOSE_CONTRACT_FIXTURE": str(compose_contract),
            "COMPOSE_PROFILE": compose_profile or "",
            "OMIT_ENV_FILE": omit_env_file,
            "OMIT_STACK": "1" if omit_stack else "0",
            "FAIL_COUNCIL_CLONES": "1" if fail_council_clones else "0",
            "EMPTY_COUNCIL_CHECKOUT": "1" if empty_council_checkout else "0",
            "FAIL_COMPOSE": "1" if fail_compose else "0",
            "DROP_COPIED_ENV": "1" if drop_copied_env else "0",
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "PASS_STATE": str(pass_state),
            "RESTIC_PASSWORD": "restore-test-password",  # pragma: allowlist secret
            "RESTORE_FAKE_BIN": str(fake_bin),
            "REPORT_STATE_UNIT": report_state_unit,
            "REPORTED_STATE": reported_state,
            "SHELL": "/bin/bash",
            "USER": "restore-test-user",
        }
    )
    result = subprocess.run(
        [str(RESTORE_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )
    commands = command_log.read_text(encoding="utf-8").splitlines() if command_log.exists() else []
    return result, commands, restore_root


def test_full_restore_carries_resolved_artifacts_through_phase_16(tmp_path: Path) -> None:
    result, commands, restore_root = _run_full_restore(tmp_path)
    dump = restore_root / DUMP_PATHS[0]

    assert result.returncode == 0, result.stderr
    phase_positions = [result.stdout.index(f"=== Phase {phase}:") for phase in range(17)]
    assert phase_positions == sorted(phase_positions)
    compose_command = (
        f"docker compose -f {tmp_path}/home/llm-stack/docker-compose.yml --profile full up -d"
    )
    assert compose_command in commands
    assert commands.index(compose_command) < commands.index(
        "docker exec postgres pg_isready -U hapax"
    )
    assert (tmp_path / "home/restored-postgres.sql").read_text() == "SELECT 1;\n"
    assert (tmp_path / "home/projects/hapax-council/.git").is_dir()
    for env_file in (".env", ".envrc"):
        source = restore_root / "home/backup-user/llm-stack" / env_file
        assert (tmp_path / "home/llm-stack" / env_file).read_bytes() == source.read_bytes()
    assert "CachyOS Restore Complete" in result.stdout
    assert any(
        command == f"git clone {dump}/git-bundles/obsidian-hapax.bundle "
        f"{tmp_path}/{'home'}/projects/obsidian-hapax"
        for command in commands
    )
    for unit in (
        "hapax-secrets.service",
        "hapax-backup-local.timer",
        "hapax-backup-remote.timer",
        "hapax-backup-watchdog.timer",
    ):
        assert f"--user enable {unit}" in commands
        assert f"--user is-enabled {unit}" in commands
    assert not any("rclone-gdrive-drop.timer" in command for command in commands)
    home_segment = "home"
    restored_rclone_config = tmp_path / home_segment / ".config" / "rclone" / "rclone.conf"
    assert restored_rclone_config.read_text(encoding="utf-8") == "active-b2-config\n"
    for entry in (
        "backblaze/key-id",
        "backblaze/app-key",
        "backblaze/restic-password",
        "backups/restic-password",
    ):
        assert f"pass insert -f -e {entry}" in commands
        assert f"pass show {entry}" in commands


def test_full_restore_fails_with_named_paths_when_dump_inputs_are_missing(
    tmp_path: Path,
) -> None:
    result, _commands, restore_root = _run_full_restore(tmp_path, omit_restore_dump=True)

    assert result.returncode != 0
    assert "No database dump directory found. Searched:" in result.stderr
    for relative_path in DUMP_PATHS:
        assert str(restore_root / relative_path) in result.stderr
    assert "Phase 13" not in result.stdout
    assert "CachyOS Restore Complete" not in result.stdout


@pytest.mark.parametrize(
    ("failure_options", "message"),
    [
        pytest.param(
            {"fail_pass_list": True},
            "Password store is unavailable",
            id="unavailable-store",
        ),
        pytest.param(
            {"fail_pass_insert_entry": "backblaze/app-key"},
            "Could not store backup credential backblaze/app-key",
            id="insert-failure",
        ),
        pytest.param(
            {"mismatch_pass_show_entry": "backups/restic-password"},
            "Backup credential backups/restic-password did not match after pass insert",
            id="readback-mismatch",
        ),
    ],
)
def test_full_restore_refuses_success_without_witnessed_credentials(
    tmp_path: Path,
    failure_options: dict[str, object],
    message: str,
) -> None:
    result, _commands, _restore_root = _run_full_restore(tmp_path, **failure_options)

    assert result.returncode != 0
    assert message in result.stderr
    assert "Backup credentials stored and verified in pass" not in result.stdout
    assert "CachyOS Restore Complete" not in result.stdout


@pytest.mark.parametrize(
    ("failed_unit", "unit_kind"),
    [
        pytest.param("hapax-secrets.service", "service", id="service"),
        pytest.param("hapax-backup-remote.timer", "timer", id="backup-timer"),
        pytest.param("hapax-backup-watchdog.timer", "timer", id="watchdog-timer"),
    ],
)
def test_full_restore_refuses_completion_when_user_unit_enable_fails(
    tmp_path: Path,
    failed_unit: str,
    unit_kind: str,
) -> None:
    result, commands, _restore_root = _run_full_restore(
        tmp_path,
        fail_enable_unit=failed_unit,
    )

    assert result.returncode != 0
    assert f"Could not enable systemd user {unit_kind} {failed_unit}" in result.stderr
    assert f"--user enable {failed_unit}" in commands
    assert f"--user is-enabled {failed_unit}" not in commands
    assert "CachyOS Restore Complete" not in result.stdout


def test_full_restore_refuses_completion_when_backup_timer_state_is_unknown(
    tmp_path: Path,
) -> None:
    unconfirmed_unit = "hapax-backup-remote.timer"
    result, commands, _restore_root = _run_full_restore(
        tmp_path,
        fail_verify_unit=unconfirmed_unit,
    )

    assert result.returncode != 0
    assert f"could not determine whether user timer {unconfirmed_unit} is enabled" in result.stderr
    assert f"--user enable {unconfirmed_unit}" in commands
    assert f"--user is-enabled {unconfirmed_unit}" in commands
    assert "CachyOS Restore Complete" not in result.stdout


def test_full_restore_refuses_completion_without_persistent_timer_install_link(
    tmp_path: Path,
) -> None:
    unit = "hapax-backup-remote.timer"
    result, commands, _restore_root = _run_full_restore(
        tmp_path,
        report_state_unit=unit,
        reported_state="static",
    )

    assert result.returncode != 0
    assert f"reports user timer {unit} as static, not enabled" in result.stderr
    assert f"--user enable {unit}" in commands
    assert "CachyOS Restore Complete" not in result.stdout


@pytest.mark.parametrize("profile", ["full", "recovery-fixture"])
def test_full_restore_uses_the_tracked_compose_profile(tmp_path: Path, profile: str) -> None:
    result, commands, _ = _run_full_restore(tmp_path, compose_profile=profile)
    assert result.returncode == 0, result.stderr
    assert (
        f"docker compose -f {tmp_path}/home/llm-stack/docker-compose.yml --profile {profile} up -d"
        in commands
    )
    assert "CachyOS Restore Complete" in result.stdout


@pytest.mark.parametrize("profile", [None, "", "full extra"])
def test_full_restore_refuses_missing_or_invalid_compose_profile(
    tmp_path: Path, profile: str | None
) -> None:
    result, commands, _ = _run_full_restore(tmp_path, compose_profile=profile)
    assert result.returncode != 0
    assert "Required Docker Compose profile is absent or invalid" in result.stderr
    assert not any(command.startswith("docker compose ") for command in commands)
    assert "Phase 13" not in result.stdout
    assert "CachyOS Restore Complete" not in result.stdout


@pytest.mark.parametrize("env_file", [".env", ".envrc"])
def test_full_restore_refuses_missing_secret_environment(tmp_path: Path, env_file: str) -> None:
    result, commands, root = _run_full_restore(tmp_path, omit_env_file=env_file)
    assert result.returncode != 0
    assert f"{root}/home/backup-user/llm-stack/{env_file}" in result.stderr
    assert "Phase 5" not in result.stdout
    assert not any(command.startswith("docker compose ") for command in commands)
    assert "CachyOS Restore Complete" not in result.stdout


def test_full_restore_verifies_environment_after_copy(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path, drop_copied_env=True)
    assert result.returncode != 0
    assert f"environment file was not restored: {tmp_path}/home/llm-stack/.env" in result.stderr
    assert "Phase 5" not in result.stdout
    assert not any(command.startswith("docker compose ") for command in commands)
    assert "CachyOS Restore Complete" not in result.stdout


def test_full_restore_refuses_missing_stack_inputs(tmp_path: Path) -> None:
    result, _, _ = _run_full_restore(tmp_path, omit_stack=True)
    assert result.returncode != 0
    assert "Required llm-stack environment file is missing" in result.stderr
    assert "Phase 5" not in result.stdout
    assert "CachyOS Restore Complete" not in result.stdout


def test_full_restore_double_council_clone_failure_stops_with_recovery_remedy(
    tmp_path: Path,
) -> None:
    result, commands, root = _run_full_restore(tmp_path, fail_council_clones=True)
    assert result.returncode != 0
    council = tmp_path / "home/projects/hapax-council"
    assert f"git clone git@github.com:hapax-systems/hapax-council.git {council}" in commands
    assert f"gh repo clone hapax-systems/hapax-council {council}" in commands
    assert "Failed to clone hapax-council" in result.stderr
    assert "git@github.com:hapax-systems/hapax-council.git" in result.stderr
    assert (
        f"git clone '{root}/{DUMP_PATHS[0]}/git-bundles/hapax-council.bundle' '{council}'"
        in result.stderr
    )
    assert "Phase 4" not in result.stdout
    assert not any(command.startswith("docker compose ") for command in commands)
    assert "CachyOS Restore Complete" not in result.stdout


def test_full_restore_refuses_clone_success_without_council_checkout(tmp_path: Path) -> None:
    result, _, _ = _run_full_restore(tmp_path, empty_council_checkout=True)
    assert result.returncode != 0
    assert "Required council checkout is invalid" in result.stderr
    assert "Phase 4" not in result.stdout
    assert "CachyOS Restore Complete" not in result.stdout


def test_full_restore_compose_failure_stops_database_import_and_later_phases(
    tmp_path: Path,
) -> None:
    result, commands, _ = _run_full_restore(tmp_path, fail_compose=True)
    assert result.returncode != 0
    assert not any("pg_isready" in command or "psql" in command for command in commands)
    assert "Phase 13" not in result.stdout
    assert "CachyOS Restore Complete" not in result.stdout
