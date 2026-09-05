from __future__ import annotations

import json
import os
import re
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
    drop_phase12_env: bool = False,
    signature_mode: str = "canonical",
    existing_b2: bool = False,
    nas_mode: str = "existing",
    supplied_nas_password: bool = False,
    restore_snapshot: str = "",
    snapshot_mode: str = "mixed",
    fail_privileged: str = "",
    github_mode: str = "available",
    council_bundle: str = "absent",
    activation_mode: str = "valid",
    unit_target_mode: str = "valid",
    omit_restored_home: str = "",
    archived_unit: bool = False,
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
    # Explicit source inventory: activation must never invent units from the restore arrays.
    activation_tree = tmp_path / "activation-tree"
    (activation_tree / ".git").mkdir(parents=True)
    (activation_tree / "scripts").mkdir()
    source_units = activation_tree / "systemd/units"
    source_units.mkdir(parents=True)
    service_names = [
        "hapax-secrets",
        "logos-api",
        "officium-api",
        "hapax-daimonion",
        "hapax-watch-receiver",
        "studio-compositor",
        "studio-fx-output",
        "visual-layer-aggregator",
        "audio-recorder",
        "rag-ingest",
        "keychron-keepalive",
        "ydotool",
        "llm-stack",
        "llm-stack-analytics",
    ]
    timer_names = [
        "hapax-backup-local",
        "hapax-backup-remote",
        "hapax-backup-watchdog",
        "health-monitor",
        "stack-maintenance",
        "daily-briefing",
        "digest",
        "profile-update",
        "audio-processor",
        "av-correlator",
        "drift-detector",
        "knowledge-maint",
        "scout",
        "llm-backup",
        "llm-cost-alert",
        "log-anomaly-alert",
        "manifest-snapshot",
        "chrome-sync",
        "claude-code-sync",
        "gcalendar-sync",
        "gdrive-sync",
        "gmail-sync",
        "git-sync",
        "langfuse-sync",
        "stimmung-sync",
        "weather-sync",
        "health-connect-parse",
        "obsidian-sync",
        "youtube-sync",
        "cache-cleanup",
        "dev-story-index",
        "disk-space-check",
        "flow-journal",
        "gpg-keyboxd-watchdog",
        "mixer-keepalive",
        "screen-context",
        "storage-arbiter",
        "tmp-monitor",
        "video-processor",
        "video-retention",
        "vram-watchdog",
    ]
    active = home / ".cache/hapax/source-activation/worktree"
    for name in service_names + timer_names:
        _write_executable(activation_tree / "scripts" / name, "#!/bin/sh\nexit 0\n")
        (source_units / f"{name}.service").write_text(
            f"[Service]\nWorkingDirectory={active}\nExecStart={active}/scripts/{name}\n"
        )
    for name in timer_names:
        (source_units / f"{name}.timer").write_text(f"[Timer]\nUnit={name}.service\n")
    if unit_target_mode == "missing-unit":
        (source_units / "hapax-backup-remote.service").unlink()
    if unit_target_mode == "missing-script":
        (source_units / "hapax-backup-remote.service").write_text(
            f"[Service]\nExecStart=/bin/bash {active}/scripts/missing-backup\n"
        )
    home.mkdir()
    for identity in (".gnupg", ".ssh"):
        (home / identity).mkdir()
        (home / identity / "original").write_text("original identity fixture\n")
    snapshots = [
        {
            "id": "abcdef0123456789",
            "hostname": "hapax-podium",
            "tags": ["tier2-remote"],
            "time": "2026-09-01T00:00:00Z",
        },
        {
            "id": "2" * 64,
            "hostname": "hapax-podium",
            "tags": ["tier2-remote"],
            "time": "2026-09-02T00:00:00Z",
        },
        {
            "id": "f" * 64,
            "hostname": "hapax-monocle",
            "tags": ["monocle-daily"],
            "time": "2026-09-04T00:00:00Z",
        },
        {
            "id": "e" * 64,
            "hostname": "hapax-podium",
            "tags": ["other"],
            "time": "2026-09-03T00:00:00Z",
        },
    ]
    if snapshot_mode == "foreign-only":
        snapshots = snapshots[2:]
    if snapshot_mode == "invalid-time":
        snapshots[1]["time"] = "unknown"
    snapshot_file = tmp_path / "snapshots.json"
    snapshot_file.write_text(json.dumps(snapshots))
    if omit_env_file == ".env" or omit_stack:
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
    nas_entry = pass_state / "backups" / "restic-password"
    nas_entry.parent.mkdir(parents=True)
    if nas_mode != "absent":
        nas_entry.write_text("nas-fixture\n")  # pragma: allowlist secret
    if existing_b2:
        b2_entry = pass_state / "backblaze" / "restic-password"
        b2_entry.parent.mkdir(parents=True)
        b2_entry.write_text("b2-recovered-fixture\n")  # pragma: allowlist secret
    # Model pass's encrypted-entry existence separately from decryption success.
    password_store = home / ".password-store"
    password_store.mkdir()
    for entry in pass_state.rglob("*"):
        if entry.is_file():
            marker = password_store / (str(entry.relative_to(pass_state)) + ".gpg")
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()

    _write_executable(
        fake_bin / "restic",
        """#!/bin/sh
set -eu
printf 'restic %s\n' "$*" >> "$COMMAND_LOG"
if [ "${1:-}" = -r ]; then
    if [ "$RESTIC_PASSWORD" = "$(cat "$PASS_STATE/backups/restic-password")" ] &&
       [ "$RESTIC_PASSWORD" = nas-fixture ]; then
        printf '%s\n' 'NAS credential matched' >> "$COMMAND_LOG"
    else
        printf '%s\n' 'NAS credential mismatch' >> "$COMMAND_LOG"
        exit 19
    fi
fi
if [ "${1:-}" = snapshots ]; then
    host= tag=
    while [ "$#" -gt 0 ]; do
        case "$1" in --host) host=$2; shift ;; --tag) tag=$2; shift ;; esac
        shift
    done
    if [ -n "$host" ]; then
        [ "$SNAPSHOT_MODE" != unreadable ] || exit 17
        if [ "$SNAPSHOT_MODE" = invalid-json ]; then printf '%s\n' '{'; exit 0; fi
    fi
    jq --arg host "$host" --arg tag "$tag" '[.[] | select(($host == "" or .hostname == $host) and ($tag == "" or (.tags | index($tag))))]' "$SNAPSHOT_FILE"
    exit 0
fi
if [ "${1:-}" = restore ]; then
    selected=$2
    if [ "$selected" = latest ]; then selected=$(jq -r 'max_by(.time).id' "$SNAPSHOT_FILE"); fi
    printf 'selected snapshot %s\n' "$selected" >> "$COMMAND_LOG"
    target=
    while [ "$#" -gt 0 ]; do
        if [ "$1" = --target ]; then
            target=$2
            break
        fi
        shift
    done
    if [ "$OMIT_RESTORED_HOME" = absent ]; then exit 0; fi
    if [ "$OMIT_RESTORED_HOME" = empty ]; then mkdir -p "$target/home"; exit 0; fi
    home_seg=home
    backed_up_rclone="$target/${home_seg}/backup-user/.config/rclone/rclone.conf"
    mkdir -p "$target/${home_seg}/backup-user/llm-stack" "$(dirname "$backed_up_rclone")"
    for identity in .gnupg .ssh; do
        mkdir -p "$target/${home_seg}/backup-user/$identity"
        printf '%s\n' 'replacement identity fixture' > "$target/${home_seg}/backup-user/$identity/replacement"
    done
    restored_home="$target/${home_seg}/backup-user"
    active="$HOME/.cache/hapax/source-activation/worktree"
    mkdir -p "$restored_home/.config/systemd/user" "$restored_home/.local/bin"
    ln -s "$active/systemd/units/hapax-backup-local.service" "$restored_home/.config/systemd/user/hapax-backup-local.service"
    ln -s "$active/systemd/units/hapax-backup-local.timer" "$restored_home/.config/systemd/user/hapax-backup-local.timer"
    ln -s "$active/scripts/hapax-backup-local" "$restored_home/.local/bin/hapax-backup-local"
    if [ "$ARCHIVED_UNIT" = 1 ]; then
        rm "$restored_home/.config/systemd/user/hapax-backup-local.service"
        printf '[Service]\nExecStart=/bin/bash %s/projects/distro-work/scripts/hapax-backup-local\nWorkingDirectory=%s/projects/distro-work\n' "$HOME" "$HOME" > "$restored_home/.config/systemd/user/hapax-backup-local.service"
        printf '[Service]\nExecStart=/bin/bash %s/projects/distro-work/scripts/hapax-backup-remote\n' "$HOME" > "$restored_home/.config/systemd/user/hapax-backup-remote.service"
    fi
    stack="$target/${home_seg}/backup-user/llm-stack"
    printf '%s\n' 'services: {}' > "$stack/docker-compose.yml"
    printf '%s\n' '# restored environment fixture' > "$stack/.env"
    printf '%s\n' '# restored direnv fixture' > "$stack/.envrc"
    if [ -n "$OMIT_ENV_FILE" ]; then rm "$stack/$OMIT_ENV_FILE"; fi
    if [ "$OMIT_STACK" = 1 ]; then rm -rf "$stack"; fi
    printf '%s\n' 'stale-b2-config' > "$backed_up_rclone"
    if [ "${OMIT_RESTORE_DUMP:-0}" != 1 ] && [ "$selected" != ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff ]; then
        dump="$target/store/llm-data/backup-dumps-remote"
        mkdir -p "$dump/qdrant" "$dump/git-bundles"
        printf '%s\n' 'SELECT 1;' > "$dump/postgres-all.sql"
        printf '%s\n' '{}' > "$dump/n8n-workflows.json"
        printf '%s\n' 'snapshot' > "$dump/qdrant/restore-test.snapshot"
        printf '%s\n' 'bundle' > "$dump/git-bundles/obsidian-hapax.bundle"
        if [ "$COUNCIL_BUNDLE" != absent ]; then
            printf '%s\n' "$COUNCIL_BUNDLE" > "$dump/git-bundles/hapax-council.bundle"
        fi
    fi
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "sudo",
        """#!/bin/sh
set -eu
printf 'sudo %s\n' "$*" >> "$COMMAND_LOG"
if [ "$FAIL_PRIVILEGED" = store-mkdir ] && [ "$*" = "mkdir -p -- $STORE_ROOT_FIXTURE" ]; then exit 17; fi
if [ -n "$FAIL_PRIVILEGED" ]; then
    case " $* " in *" $FAIL_PRIVILEGED "*) exit 17 ;; esac
fi
case "${1:-}" in
    mkdir)
        shift
        exec /usr/bin/mkdir "$@"
        ;;
    blkid)
        if [ "$DROP_PHASE12_ENV" = 1 ]; then rm -f "$HOME/llm-stack/.env"; fi
        if [ "${2:-}" = -U ]; then
            if [ "$SIGNATURE_MODE" = uuid-failure ]; then exit 17; fi
            if [ "$SIGNATURE_MODE" = uuid-empty ]; then exit 0; fi
            if [ "$SIGNATURE_MODE" != canonical ]; then exit 2; fi
        fi
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
if [ "${2:-}" = show ]; then
    unit=$3
    case "$*" in
        *Triggers*) printf '%s\n' "${unit%.timer}.service" ;;
        *LoadState*) [ -f "$HOME/.config/systemd/user/$unit" ] && printf '%s\n' loaded || printf '%s\n' not-found ;;
        *WorkingDirectory*) sed -n 's/^WorkingDirectory=//p' "$HOME/.config/systemd/user/$unit" ;;
        *ExecStart*)
            target=$(sed -n 's/^ExecStart=//p' "$HOME/.config/systemd/user/$unit")
            printf '{ path=%s ; argv[]=%s ; }\n' "${target%% *}" "$target"
            ;;
    esac
fi
case " $* " in
    *" enable $FAIL_ENABLE_UNIT ") exit 7 ;;
    *" is-enabled $FAIL_VERIFY_UNIT ") exit 8 ;;
    *" is-enabled $REPORT_STATE_UNIT ") printf '%s\n' "$REPORTED_STATE" ;;
    *" is-enabled "*) printf '%s\n' enabled ;;
    *" --user enable "*)
        unit=$3
        service=${unit%.timer}.service
        if [ "$unit" = "${unit%.timer}" ]; then service=$unit; fi
        target=$(sed -n 's/^ExecStart=//p' "$HOME/.config/systemd/user/$service")
        target=${target%% *}
        [ -f "$target" ] && [ -x "$target" ] || exit 20
        printf 'verified ExecStart %s\n' "$service" >> "$COMMAND_LOG"
        ;;
esac
exit 0
""",
    )
    _write_executable(
        fake_bin / "git",
        """#!/bin/sh
set -eu
printf 'git %s\n' "$*" >> "$COMMAND_LOG"
case " $* " in
    *" rev-parse "*) printf '%s\n' aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa ;;
    *" fsck "*) [ "$COUNCIL_BUNDLE" != disconnected ] || exit 22 ;;
esac
if [ "${1:-}" = clone ]; then
    case "$2" in
        *hapax-council*)
            case "$2" in
                *.bundle) [ "$(cat "$2")" = valid ] || [ "$(cat "$2")" = disconnected ] || exit 21 ;;
                *) [ "$FAIL_COUNCIL_CLONES" != 1 ] && [ "$GITHUB_MODE" = available ] || exit 7 ;;
            esac
            if [ "$EMPTY_COUNCIL_CHECKOUT" = 1 ]; then exit 0; fi
            mkdir -p "$3/systemd/units" "$3/scripts"
            cp "$COMPOSE_CONTRACT_FIXTURE" "$3/systemd/units/llm-stack.service"
            if [ "$ACTIVATION_MODE" != missing-entry ]; then
                cp "$RESTORE_FAKE_BIN/activate" "$3/scripts/hapax-source-activate"
            fi
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
[ "$GITHUB_MODE" != missing ] || exit 127
[ "$GITHUB_MODE" != unauthenticated ] || exit 4
if [ "${1:-}" = repo ] && [ "${2:-}" = clone ] && [ "$3" = hapax-systems/hapax-council ]; then
    [ "$FAIL_COUNCIL_CLONES" != 1 ] || exit 8
    exec "$RESTORE_FAKE_BIN/git" clone "$3" "$4"
fi
""",
    )
    _write_executable(
        fake_bin / "activate",
        r"""#!/usr/bin/python3
import json, os, shutil, sys
from pathlib import Path
home = Path(os.environ['HOME'])
active = home / '.cache/hapax/source-activation/worktree'
mode = os.environ['ACTIVATION_MODE']
with open(os.environ['COMMAND_LOG'], 'a') as log:
    log.write('activate ' + ' '.join(sys.argv[1:]) + '\n')
if mode == 'failed': sys.exit(17)
if mode == 'held': sys.exit(0)
active.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(os.environ['ACTIVATION_TREE'], active)
(active.parent / 'current.json').write_text(json.dumps(dict(status='completed_skip_deploy', active_source_head='a'*40, origin_main_sha='a'*40, active_source_path=str(active))))
# --skip-deploy publishes the supplied source tree and launchers, never unit files.
broken = active / 'scripts/hapax-backup-remote'
target_mode = os.environ['UNIT_TARGET_MODE']
if target_mode in ('missing', 'dangling'):
    broken.unlink()
    if target_mode == 'dangling': broken.symlink_to(active / 'absent')
if target_mode == 'nonexecutable': broken.chmod(0o644)
if mode == 'missing-backup': (active / 'scripts/hapax-backup-local').unlink()
""",
    )
    _write_executable(
        fake_bin / "docker",
        """#!/bin/sh
set -eu
printf 'docker %s\n' "$*" >> "$COMMAND_LOG"
if [ "${1:-}" = compose ]; then
    [ "$*" = "compose -f $HOME/llm-stack/docker-compose.yml --profile $COMPOSE_PROFILE up -d" ] || exit 10
    [ -f "$HOME/llm-stack/.env" ] || exit 11
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
    _write_executable(
        fake_bin / "lsblk",
        """#!/bin/sh
set -eu
printf 'lsblk %s\n' "$*" >> "$COMMAND_LOG"
case "$*" in
    *"-dno TYPE"*)
        printf '%s\n' disk
        if [ "$SIGNATURE_MODE" = type-failure ]; then exit 17; fi
        ;;
    *"-no FSTYPE,PTTYPE"*)
        case "$SIGNATURE_MODE" in
            failure) printf '%s\n' 'simulated signature inspection failure' >&2; exit 17 ;;
            failure-empty) exit 17 ;;
            existing) printf '%s\n' ext4 ;;
        esac
        ;;
esac
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
        if [ "$entry" = backups/restic-password ] && [ "$NAS_MODE" = unreadable ]; then exit 18; fi
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
        'command() { if [[ "$*" == "-v gh" && "$GITHUB_MODE" == missing ]]; then return 1; fi; builtin command "$@"; }\n'
        + "\n".join(
            f'{command}() {{ "$RESTORE_FAKE_BIN/{command}" "$@"; }}'
            for command in (
                *passthrough_commands,
                "curl",
                "cp",
                "docker",
                "findmnt",
                "gh",
                "git",
                "lsblk",
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

    nas_fixture_password = (
        "nas-fixture" if supplied_nas_password else ""
    )  # pragma: allowlist secret
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
            "HAPAX_RESTORE_SNAPSHOT": restore_snapshot,
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
            "SIGNATURE_MODE": signature_mode,
            "FAIL_PRIVILEGED": fail_privileged,
            "STORE_ROOT_FIXTURE": str(store_root),
            "SNAPSHOT_MODE": snapshot_mode,
            "SNAPSHOT_FILE": str(snapshot_file),
            "GITHUB_MODE": github_mode,
            "COUNCIL_BUNDLE": council_bundle,
            "ACTIVATION_MODE": activation_mode,
            "UNIT_TARGET_MODE": unit_target_mode,
            "ACTIVATION_TREE": str(activation_tree),
            "ARCHIVED_UNIT": "1" if archived_unit else "0",
            "OMIT_RESTORED_HOME": omit_restored_home,
            "DROP_PHASE12_ENV": "1" if drop_phase12_env else "0",
            "RESTORE_STORE_DEVICE": str(tmp_path / "replacement-disk"),
            "NAS_MODE": nas_mode,
            "RESTORE_NAS_RESTIC_PASSWORD": nas_fixture_password,
            "PASSWORD_STORE_DIR": str(password_store),
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
        f"docker compose -f {tmp_path / 'home' / 'llm-stack' / 'docker-compose.yml'}"
        " --profile full up -d"
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
    ):
        assert f"pass insert -e {entry}" in commands
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
            {"mismatch_pass_show_entry": "backblaze/restic-password"},
            "Backup credential backblaze/restic-password did not match after pass insert",
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
        f"docker compose -f {tmp_path / 'home' / 'llm-stack' / 'docker-compose.yml'}"
        f" --profile {profile} up -d" in commands
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


@pytest.mark.parametrize("env_file", [".env"])
def test_full_restore_refuses_missing_secret_environment(tmp_path: Path, env_file: str) -> None:
    result, commands, root = _run_full_restore(tmp_path, omit_env_file=env_file)
    assert result.returncode != 0
    assert "/".join((str(root), "home", "backup-user", "llm-stack", env_file)) in result.stderr
    assert "Phase 5" not in result.stdout
    assert not any(command.startswith("docker compose ") for command in commands)
    assert "CachyOS Restore Complete" not in result.stdout


def test_full_restore_verifies_environment_after_copy(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path, drop_copied_env=True)
    assert result.returncode != 0
    missing_env = tmp_path / "home" / "llm-stack" / ".env"
    assert f"environment file was not restored: {missing_env}" in result.stderr
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


@pytest.mark.parametrize(
    "mode",
    ["failure", "failure-empty", "type-failure", "uuid-failure", "uuid-empty", "existing", "empty"],
)
def test_round4_signature_inspection_gates_every_destructive_step(
    tmp_path: Path, mode: str
) -> None:
    result, commands, _ = _run_full_restore(tmp_path, signature_mode=mode)
    destructive = [
        c
        for c in commands
        if any(
            word in c.split() for word in ("mklabel", "mkpart", "mkfs.ext4", "wipefs", "luksFormat")
        )
    ]
    if mode == "empty":
        assert result.returncode == 0, result.stderr
        assert len(destructive) == 3
    else:
        assert not destructive, "unproved disk was formatted"
        assert result.returncode != 0
        if mode.startswith("uuid-"):
            assert (
                "could not inspect canonical filesystem UUID=restore-test-uuid: blkid exit"
                in result.stderr
            )
            assert "nothing was formatted" in result.stderr
        elif mode == "type-failure":
            assert "could not inspect" in result.stderr
            assert "disk type: lsblk exit 17" in result.stderr
            assert "nothing was formatted" in result.stderr
        elif mode.startswith("failure"):
            assert f"could not inspect {tmp_path / 'replacement-disk'} signatures" in result.stderr
            assert "lsblk exit 17" in result.stderr
            assert "nothing was formatted" in result.stderr
        else:
            assert "already carries a filesystem or partition table" in result.stderr


def test_round4_envrc_is_optional_in_both_restore_phases(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path, omit_env_file=".envrc")
    assert result.returncode == 0, "complete stack without optional .envrc was refused"
    assert "Optional llm-stack .envrc is absent" in result.stdout
    assert "Phase 12: verified required llm-stack .env" in result.stdout
    assert not (tmp_path / "home/llm-stack/.envrc").exists()
    assert "Optional llm-stack .envrc is absent; Compose requires .env only" in result.stdout
    assert "CachyOS Restore Complete" in result.stdout
    assert any(c.startswith("docker compose ") for c in commands)


@pytest.mark.parametrize("existing_b2", [False, True])
def test_round4_repository_credentials_remain_independent(
    tmp_path: Path, existing_b2: bool
) -> None:
    result, commands, _ = _run_full_restore(tmp_path, existing_b2=existing_b2)
    assert result.returncode == 0, "restore failed with independent repository passwords"
    assert (tmp_path / "pass-state/backups/restic-password").read_text() == "nas-fixture\n"
    assert "NAS credential matched" in commands
    assert not any(
        c.startswith("pass insert") and c.endswith("backups/restic-password") for c in commands
    )
    b2_inserts = [
        c
        for c in commands
        if c.startswith("pass insert") and c.endswith("backblaze/restic-password")
    ]
    assert len(b2_inserts) == (0 if existing_b2 else 1)
    if existing_b2:
        assert (
            tmp_path / "pass-state/backblaze/restic-password"
        ).read_text() == "b2-recovered-fixture\n"


@pytest.mark.parametrize("mode", ["absent", "unreadable"])
def test_round4_unproved_nas_credential_is_never_replaced(tmp_path: Path, mode: str) -> None:
    result, commands, _ = _run_full_restore(tmp_path, nas_mode=mode)
    assert result.returncode != 0
    assert "backups/restic-password" in result.stderr
    assert not any(
        c.startswith("pass insert") and c.endswith("backups/restic-password") for c in commands
    )
    assert "Phase 14" not in result.stdout


def test_round4_absent_nas_credential_requires_its_own_input(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path, nas_mode="absent", supplied_nas_password=True)
    assert result.returncode == 0, "separately supplied NAS password was not used"
    assert "pass insert -e backups/restic-password" in commands
    assert "NAS credential matched" in commands


def test_round4_missing_dump_names_producer_and_recovery_action(tmp_path: Path) -> None:
    result, _, _ = _run_full_restore(tmp_path, omit_restore_dump=True)
    assert result.returncode != 0
    assert "select a complete hapax-podium/tier2-remote snapshot" in result.stderr
    assert "restic snapshots --host hapax-podium --tag tier2-remote" in result.stderr
    assert "rerun from Phase 2" in result.stderr


def test_round4_phase12_still_refuses_missing_env(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path, drop_phase12_env=True)
    assert result.returncode != 0
    missing = tmp_path / "home" / "llm-stack" / ".env"
    assert f"Required llm-stack environment file is missing: {missing}" in result.stderr
    assert "Phase 12:" in result.stdout
    assert not any(c.startswith("docker compose ") for c in commands)


def test_round4_dump_remedy_can_select_complete_snapshot(tmp_path: Path) -> None:
    result, commands, root = _run_full_restore(tmp_path, restore_snapshot="abcdef0123456789")
    assert result.returncode == 0
    assert f"restic restore abcdef0123456789 --target {root} --no-lock --verbose" in commands


def test_round5_restore_selects_newest_podium_snapshot(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "selected snapshot " + "2" * 64 in commands
    assert any("--host hapax-podium --tag tier2-remote" in c for c in commands)


@pytest.mark.parametrize("selection", ["", "f" * 64, "e" * 64, "deadbeef", "latest"])
def test_round5_restore_refuses_unproved_producer_before_identity(
    tmp_path: Path, selection: str
) -> None:
    result, commands, _ = _run_full_restore(
        tmp_path, snapshot_mode="foreign-only", restore_snapshot=selection
    )
    assert result.returncode != 0
    assert "hapax-podium/tier2-remote" in result.stderr
    assert "restic snapshots --host hapax-podium --tag tier2-remote" in result.stderr
    assert not any(c.startswith("restic restore ") for c in commands)
    for identity in (".gnupg", ".ssh"):
        assert (tmp_path / "home" / identity / "original").is_file()


def test_round5_dump_validation_precedes_identity_replacement(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path, omit_restore_dump=True)
    assert result.returncode != 0
    assert "No database dump directory" in result.stderr
    for identity in (".gnupg", ".ssh"):
        assert (tmp_path / "home" / identity / "original").is_file(), (
            "identity changed before dump validation"
        )
        assert not (tmp_path / "home" / identity / "replacement").exists()
    assert not any(c.startswith("pass ") for c in commands)


@pytest.mark.parametrize(
    "operation,next_operation",
    [
        ("mklabel gpt", "mkpart"),
        ("mkpart store ext4 1MiB 100%", "udevadm"),
        ("udevadm settle", "mkfs.ext4"),
        ("mkfs.ext4 -L store", "blkid -s UUID"),
        ("blkid -s UUID -o value", "tee -a /etc/fstab"),
    ],
)
def test_round5_phase11_stops_after_privileged_failure(
    tmp_path: Path, operation: str, next_operation: str
) -> None:
    result, commands, _ = _run_full_restore(
        tmp_path,
        restore_snapshot="abcdef0123456789",
        signature_mode="empty",
        fail_privileged=operation,
    )
    assert result.returncode != 0, "Phase 11 continued after privileged exit 17"
    failed_index = next(
        i for i, c in enumerate(commands) if c.startswith("sudo ") and operation in c
    )
    assert not any(next_operation in c for c in commands[failed_index + 1 :]), (
        "later privileged operation ran"
    )
    assert "Phase 12:" not in result.stdout
    assert "Replacement disk provisioned" not in result.stdout
    assert "Phase 11" in result.stderr and "inspect" in result.stderr


@pytest.mark.parametrize("mode", ["missing", "unauthenticated", "clone-failed"])
def test_round5_council_bundle_recovers_github_failure(tmp_path: Path, mode: str) -> None:
    result, commands, root = _run_full_restore(
        tmp_path, restore_snapshot="abcdef0123456789", github_mode=mode, council_bundle="valid"
    )
    assert result.returncode == 0, result.stderr
    assert "hapax-council bundle fallback" in result.stdout
    assert "CachyOS Restore Complete" in result.stdout
    assert any(
        c.startswith(f"git clone {root}/{DUMP_PATHS[0]}/git-bundles/hapax-council.bundle ")
        for c in commands
    )
    assert any("fsck --connectivity-only" in c for c in commands)
    if mode == "missing":
        assert "gh is unavailable" in result.stdout
    elif mode == "unauthenticated":
        assert "gh auth status failed" in result.stdout


@pytest.mark.parametrize("bundle", ["absent", "invalid"])
def test_round5_council_bundle_failure_is_named(tmp_path: Path, bundle: str) -> None:
    result, commands, _ = _run_full_restore(
        tmp_path,
        restore_snapshot="abcdef0123456789",
        github_mode="clone-failed",
        council_bundle=bundle,
    )
    assert result.returncode != 0
    assert "hapax-council.bundle" in result.stderr
    assert "rerun" in result.stderr
    assert "Phase 4:" not in result.stdout
    assert not any(c.startswith("docker compose ") for c in commands)


def test_round5_bootstrap_installs_phase_dependencies(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path, restore_snapshot="abcdef0123456789")
    assert result.returncode == 0
    bootstrap = next(c for c in commands if c.startswith("sudo pacman -Syu "))
    assert {
        "restic",
        "rclone",
        "gnupg",
        "pass",
        "curl",
        "wget",
        "git",
        "github-cli",
        "jq",
        "base-devel",
        "python",
        "parted",
        "e2fsprogs",
        "util-linux",
    } <= set(bootstrap.split())
    assert commands.index(bootstrap) < next(
        i for i, c in enumerate(commands) if c.startswith("gh ")
    )


def test_round5_activation_precedes_all_unit_enables(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path, restore_snapshot="abcdef0123456789")
    assert result.returncode == 0, result.stderr
    assert "activate --skip-deploy" in commands
    assert commands.index("activate --skip-deploy") < next(
        i for i, c in enumerate(commands) if " enable " in c
    )
    launcher = tmp_path / "home/.local/bin/hapax-backup-local"
    assert launcher.is_symlink() and launcher.is_file() and os.access(launcher, os.X_OK)
    for command in commands:
        if command.startswith("--user enable "):
            unit = command.split()[-1].replace(".timer", ".service")
            text = (tmp_path / "home/.config/systemd/user" / unit).read_text()
            target = Path(text.split("ExecStart=", 1)[1].strip())
            assert target.is_file() and os.access(target, os.X_OK), command
            assert f"verified ExecStart {unit}" in commands


@pytest.mark.parametrize("mode", ["missing-entry", "failed", "held", "missing-backup"])
def test_round5_unproved_activation_refuses_before_any_enable(tmp_path: Path, mode: str) -> None:
    result, commands, _ = _run_full_restore(
        tmp_path, restore_snapshot="abcdef0123456789", activation_mode=mode
    )
    assert result.returncode != 0
    assert "activation" in result.stderr and "rerun" in result.stderr
    assert not any(" enable " in c for c in commands)
    assert "CachyOS Restore Complete" not in result.stdout


@pytest.mark.parametrize("mode", ["missing", "dangling", "nonexecutable", "missing-unit"])
def test_round5_user_targets_verified_before_any_user_enable(tmp_path: Path, mode: str) -> None:
    result, commands, _ = _run_full_restore(
        tmp_path, restore_snapshot="abcdef0123456789", unit_target_mode=mode
    )
    assert result.returncode != 0
    assert "hapax-backup-remote.service" in result.stderr
    assert "rerun Phase 15" in result.stderr
    assert not any(c.startswith("--user enable ") for c in commands)
    assert "CachyOS Restore Complete" not in result.stdout


@pytest.mark.parametrize("mode", ["unreadable", "invalid-json", "invalid-time"])
def test_round5_unreadable_snapshot_metadata_refuses_before_restore(
    tmp_path: Path, mode: str
) -> None:
    result, commands, _ = _run_full_restore(tmp_path, snapshot_mode=mode)
    assert result.returncode != 0
    assert "hapax-podium/tier2-remote" in result.stderr
    assert "rerun Phase 2" in result.stderr
    assert not any(c.startswith("restic restore ") for c in commands)
    assert (tmp_path / "home/.gnupg/original").is_file()


def test_round5_snapshot_prefix_resolves_to_immutable_id(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path, restore_snapshot="22222222")
    assert result.returncode == 0
    assert "selected snapshot " + "2" * 64 in commands


def test_round5_bundle_connectivity_failure_refuses(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(
        tmp_path, github_mode="clone-failed", council_bundle="disconnected"
    )
    assert result.returncode != 0
    assert "bundle fallback failed connectivity verification" in result.stderr
    assert "rerun Phase 3" in result.stderr
    assert "Phase 4:" not in result.stdout
    assert not any("activate " in c for c in commands)


@pytest.mark.parametrize("operation", ["store-mkdir", "tee -a /etc/fstab"])
def test_round5_phase11_publication_failure_has_no_success_receipt(
    tmp_path: Path, operation: str
) -> None:
    result, commands, _ = _run_full_restore(
        tmp_path, signature_mode="empty", fail_privileged=operation
    )
    assert result.returncode != 0
    assert "Replacement disk provisioned" not in result.stdout
    assert "Phase 12:" not in result.stdout
    assert "inspect" in result.stderr and "rerun Phase 11" in result.stderr
    if operation == "store-mkdir":
        assert not any("tee -a /etc/fstab" in c for c in commands)


@pytest.mark.parametrize("payload_kind", ["copy", "function", "nested-tags"])
def test_round6_postgres_payload_is_byte_identical(tmp_path: Path, payload_kind: str) -> None:
    payloads = {
        "copy": b"COPY public.probe (value) FROM stdin;\r\nCREATE ROLE hapax;\r\nCREATE DATABASE hapax;\r\nplain row\r\n\\.\r\n",
        "function": b"CREATE FUNCTION probe() RETURNS text AS $$\nCREATE ROLE hapax;\nCREATE DATABASE hapax;\n$$ LANGUAGE sql;\n",
        "nested-tags": b"CREATE FUNCTION probe() RETURNS text AS $outer$\nSELECT $inner$\nCREATE ROLE hapax;\nCREATE DATABASE hapax;\n$inner$;\nSELECT $$nested$$;\n$outer$ LANGUAGE sql;\n",
    }
    payload = payloads[payload_kind]
    dump = tmp_path / "dump"
    dump.mkdir()
    tail = b"ALTER ROLE hapax WITH LOGIN;\nCREATE ROLE app_reader;\nSELECT 1;"
    (dump / "postgres-all.sql").write_bytes(
        b"CREATE ROLE hapax;\nCREATE DATABASE hapax WITH TEMPLATE = template0;\n"
        + payload
        + b"CREATE ROLE hapax;\nCREATE DATABASE hapax;\n"
        + tail
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    psql_input = tmp_path / "psql-input.sql"
    _write_executable(fake_bin / "sudo", '#!/bin/sh\ncat > "$PSQL_INPUT"\n')
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; restore_postgresql "$2"',
            "restore",
            str(RESTORE_SCRIPT),
            str(dump),
        ],
        env={**os.environ, "PATH": f"{fake_bin}:/usr/bin:/bin", "PSQL_INPUT": str(psql_input)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    restored = psql_input.read_bytes()
    assert payload in restored, "COPY rows/function body changed during successful import"
    assert restored.strip() == (payload + b"\n\n" + tail).strip()


def test_round6_reconciles_archived_unit_with_activation_source(tmp_path: Path) -> None:
    result, commands, root = _run_full_restore(tmp_path, archived_unit=True)
    assert result.returncode == 0, result.stderr
    units = tmp_path / "home/.config/systemd/user"
    active = tmp_path / "home/.cache/hapax/source-activation/worktree"
    unit = "hapax-backup-local.service"
    assert (units / unit).read_bytes() == (active / "systemd/units" / unit).read_bytes()
    assert (units / (unit + ".restored")).read_bytes() == (
        root / "home/backup-user/.config/systemd/user" / unit
    ).read_bytes()
    assert "--user enable hapax-backup-local.timer" in commands
    assert not any(" enable " in c and ".restored" in c for c in commands)


def test_round6_missing_activation_unit_refuses_archived_fallback(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(
        tmp_path, archived_unit=True, unit_target_mode="missing-unit"
    )
    assert result.returncode != 0
    missing = (
        tmp_path
        / "home/.cache/hapax/source-activation/worktree/systemd/units/hapax-backup-remote.service"
    )
    assert str(missing) in result.stderr
    assert "rerun Phase 15" in result.stderr
    assert not any(c.startswith("--user enable ") for c in commands)


def test_round6_interpreter_with_missing_script_refuses_enable(tmp_path: Path) -> None:
    result, commands, _ = _run_full_restore(tmp_path, unit_target_mode="missing-script")
    assert result.returncode != 0
    missing = tmp_path / "home/.cache/hapax/source-activation/worktree/scripts/missing-backup"
    assert "hapax-backup-remote.service" in result.stderr
    assert str(missing) in result.stderr
    assert "rerun Phase 15" in result.stderr
    assert not any(c.startswith("--user enable ") for c in commands)


@pytest.mark.parametrize("mode", ["empty", "absent"])
def test_round6_missing_home_names_snapshot_inspection_and_retry(tmp_path: Path, mode: str) -> None:
    result, commands, _ = _run_full_restore(tmp_path, omit_restored_home=mode)
    identity = "2" * 64
    assert result.returncode != 0
    assert f"No home directory found in backup snapshot {identity}" in result.stderr
    assert f"restic ls {identity} --host hapax-podium --tag tier2-remote /home" in result.stderr
    assert "HAPAX_RESTORE_SNAPSHOT=<id>" in result.stderr
    assert "rerun Phase 2" in result.stderr
    assert not any(" enable " in c for c in commands)


def test_round6_runbook_has_no_direct_watchdog_invocation() -> None:
    # Extend the existing consistency checks without editing the out-of-scope suites.
    from tests.systemd.test_llm_backup_reconciliation import (
        test_reconciliation_runbook_documents_restore_path,
    )

    test_reconciliation_runbook_documents_restore_path()
    text = (SCRIPTS.parent / "docs/runbooks/llm-stack-backup-reconciliation.md").read_text()
    assert not re.search(r"`(?:\./)?scripts/hapax-backup-watchdog(?:`|\s)", text)
    assert not re.search(r"(?m)^\s*(?:\./)?scripts/hapax-backup-watchdog(?:$|\s)", text)
    restore_steps = text.split("## Restore Path", 1)[1].split("For bare-metal", 1)[0]
    assert "systemctl --user start hapax-backup-watchdog.service" in restore_steps


@pytest.mark.parametrize(
    "mode",
    [
        "missing-script",
        "dangling-script",
        "unreadable-script",
        "outside-root",
        "missing-interpreter",
    ],
)
def test_round6_resolved_interpreter_and_script_are_both_required(
    tmp_path: Path, mode: str
) -> None:
    result, target = _verify_interpreter_target(tmp_path, mode)
    assert result.returncode != 0, "interpreter-only verification accepted an unusable script"
    assert "fixture.service" in result.stderr
    assert str(target) in result.stderr
    assert "rerun Phase 15" in result.stderr


@pytest.mark.parametrize("mode", ["readable-script", "relative-script", "quoted-script"])
def test_round6_readable_activation_script_passes(tmp_path: Path, mode: str) -> None:
    result, _ = _verify_interpreter_target(tmp_path, mode)
    assert result.returncode == 0, result.stderr


def _verify_interpreter_target(
    tmp_path: Path, mode: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    import shlex

    home = tmp_path / "home"
    active = home / ".cache/hapax/source-activation/worktree"
    active.mkdir(parents=True)
    script = active / ("backup script" if mode == "quoted-script" else "backup")
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o644)  # An interpreter only needs its script to be readable.
    interpreter = Path("/bin/bash")
    if mode == "missing-script":
        script.unlink()
    if mode == "dangling-script":
        script.unlink()
        script.symlink_to(active / "absent")
    if mode == "unreadable-script":
        script.chmod(0o000)
    if mode == "outside-root":
        script = home / "archived-script"
        script.write_text("exit 0\n")
    if mode == "missing-interpreter":
        interpreter = active / "absent-bash"
    argument = script.name if mode == "relative-script" else str(script)
    starts = f"{{ path={interpreter} ; argv[]={interpreter} -eu -- {shlex.quote(argument)} ; }}"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "systemctl",
        """#!/bin/sh
case "$*" in
    *LoadState*) echo loaded ;;
    *ExecStart*) printf '%s\n' "$FIXTURE_EXEC_START" ;;
    *WorkingDirectory*) printf '%s\n' "$FIXTURE_WORKING_DIRECTORY" ;;
esac
""",
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; verify_systemd_user_target fixture.service',
            "restore",
            str(RESTORE_SCRIPT),
        ],
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "FIXTURE_EXEC_START": starts,
            "FIXTURE_WORKING_DIRECTORY": str(active),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result, interpreter if mode == "missing-interpreter" else script


@pytest.mark.parametrize(
    "payload",
    [
        b"/* outer\n/* inner */\nCREATE ROLE hapax;\nCREATE DATABASE hapax;\n*/\n",
        b"SELECT 'quoted\nCREATE ROLE hapax;\nCREATE DATABASE hapax;\n''tail';\n",
        b"SELECT E'escaped\\\"quote\nCREATE ROLE hapax;\nCREATE DATABASE hapax;\n';\n",
        b'CREATE ROLE hapax_reader; CREATE DATABASE hapax_extra; CREATE ROLE "Hapax";\n',
        b'CREATE ROLE "name with spaces"; SELECT 1;\n',
        b"-- CREATE ROLE hapax;\nSELECT 1; CREATE ROLE app; -- trailing comment\n",
    ],
    ids=["nested-comments", "string", "escape-string", "similar-names", "quoted-name", "same-line"],
)
def test_round6_postgres_unrelated_sql_passes_verbatim(tmp_path: Path, payload: bytes) -> None:
    dump = tmp_path / "postgres-all.sql"
    dump.write_bytes(payload)
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; filter_postgresql_bootstrap "$2"',
            "restore",
            str(RESTORE_SCRIPT),
            str(dump),
        ],
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == payload


def test_round6_reconciliation_preserves_dropins_and_previous_archives(tmp_path: Path) -> None:
    home = tmp_path / "home"
    active = home / ".cache/hapax/source-activation/worktree/systemd/units"
    active.mkdir(parents=True)
    source = active / "fixture.service"
    source.write_bytes(b"[Service]\nExecStart=/bin/true\n")
    units = home / ".config/systemd/user"
    units.mkdir(parents=True)
    installed = units / source.name
    installed.write_bytes(b"archived unit\r\n")
    previous = units / "fixture.service.restored"
    previous.write_bytes(b"previous archived unit\n")
    dropins = units / "fixture.service.d"
    dropins.mkdir()
    (dropins / "override.conf").write_bytes(b"archived override\r\n")
    for _ in range(2):
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; reconcile_systemd_user_unit fixture.service',
                "restore",
                str(RESTORE_SCRIPT),
            ],
            env={**os.environ, "HOME": str(home)},
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, result.stderr
    assert installed.resolve() == source
    assert installed.read_bytes() == source.read_bytes()
    assert previous.read_bytes() == b"previous archived unit\n"
    assert (units / "fixture.service.restored.1").read_bytes() == b"archived unit\r\n"
    assert not dropins.exists()
    assert (
        units / "fixture.service.d.restored/override.conf"
    ).read_bytes() == b"archived override\r\n"


def test_round6_only_exact_top_level_bootstrap_statements_are_removed(tmp_path: Path) -> None:
    dump = tmp_path / "postgres-all.sql"
    dump.write_bytes(
        b'-- prefix\nCREATE ROLE "hapax"; CREATE ROLE "Hapax";\n'
        b'CREATE\nDATABASE "hapax" WITH TEMPLATE = template0; SELECT 2;\n'
        b"\\connect hapax\nCREATE ROLE hapax; ALTER ROLE hapax WITH LOGIN;"
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; filter_postgresql_bootstrap "$2"',
            "restore",
            str(RESTORE_SCRIPT),
            str(dump),
        ],
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        b'-- prefix\n CREATE ROLE "Hapax";\n SELECT 2;\n'
        b"\\connect hapax\n ALTER ROLE hapax WITH LOGIN;"
    )
