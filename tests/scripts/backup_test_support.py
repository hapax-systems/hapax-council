from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


def _write_stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\nset -eu\n{body}\n")
    path.chmod(0o755)


def run_backup(
    tmp_path: Path,
    lane: str,
    *,
    qdrant_mode: str = "success",
    n8n_mode: str = "success",
    postgres_mode: str = "success",
    restic_mode: str = "success",
    rclone_mode: str = "success",
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fake_bin = tmp_path / "bin"
    fake_home = tmp_path / "home"
    dump_dir = tmp_path / "dump"
    command_log = tmp_path / "commands.log"
    fake_bin.mkdir()
    fake_home.mkdir()

    _write_stub(fake_bin, "pass", "printf '%s\\n' test-password")
    _write_stub(
        fake_bin,
        "docker",
        """
printf 'docker %s\n' "$*" >> "$COMMAND_LOG"
if [ "${1:-}" = exec ] && [ "${2:-}" = postgres ] && [ "${3:-}" = pg_dumpall ]; then
    if [ "$POSTGRES_MODE" = exit-fail ]; then
        printf '%s\n' 'simulated pg_dumpall failure' >&2
        exit 8
    fi
    printf '%s\n' 'stub PostgreSQL dump'
elif [ "${1:-}" = exec ] && [ "${2:-}" = n8n ]; then
    if [ "$N8N_MODE" = export-fail ]; then
        exit 9
    fi
elif [ "${1:-}" = cp ] && [ "${2:-}" = n8n:/tmp/n8n-workflows.json ]; then
    if [ "$N8N_MODE" = copy-fail ]; then
        exit 10
    fi
    if [ "$N8N_MODE" = empty-output ]; then
        : > "$3"
        exit 0
    fi
    printf '%s\n' '[{"id":"test-workflow"}]' > "$3"
fi
exit 0
""",
    )
    _write_stub(
        fake_bin,
        "tail",
        """
if [ "${1:-}" = -c ]; then
    if [ "$POSTGRES_MODE" = missing-terminator ]; then
        printf '%s\n' '-- truncated PostgreSQL dump'
    else
        printf '%s\n' '-- PostgreSQL database cluster dump complete'
    fi
else
    /usr/bin/tail "$@"
fi
""",
    )
    _write_stub(
        fake_bin,
        "stat",
        """
if [ "${1:-}" = -c%s ]; then
    if [ "$POSTGRES_MODE" = too-small ]; then
        printf '%s\n' 999999999
    else
        printf '%s\n' 1000000000
    fi
else
    /usr/bin/stat "$@"
fi
""",
    )
    _write_stub(
        fake_bin,
        "jq",
        'exec /usr/bin/jq "$@"',
    )
    _write_stub(
        fake_bin,
        "curl",
        """
args="$*"
case "$args" in
    *"/snapshots/test.snapshot"*)
        if [ "$QDRANT_MODE" = download-fail ]; then
            exit 22
        fi
        while [ "$#" -gt 0 ]; do
            if [ "$1" = -o ]; then
                shift
                printf '%s\n' snapshot > "$1"
                exit 0
            fi
            shift
        done
        printf '%s\n' snapshot
        ;;
    *"-X POST"*"/collections/test-collection/snapshots"*)
        if [ "$QDRANT_MODE" = snapshot-fail ]; then
            exit 22
        elif [ "$QDRANT_MODE" = invalid-snapshot ]; then
            printf '%s\n' '{"result":{}}'
        else
            printf '%s\n' '{"result":{"name":"test.snapshot"}}'
        fi
        ;;
    *"127.0.0.1:6333/collections"*)
        if [ "$QDRANT_MODE" = list-fail ]; then
            exit 22
        elif [ "$QDRANT_MODE" = empty-list ]; then
            printf '%s\n' '{"result":{"collections":[]}}'
        elif [ "$QDRANT_MODE" = invalid-list ]; then
            printf '%s\n' '{"unexpected":true}'
        else
            printf '%s\n' '{"result":{"collections":[{"name":"test-collection"}]}}'
        fi
        ;;
    *) exit 0 ;;
esac
""",
    )
    _write_stub(
        fake_bin,
        "restic",
        """
printf 'restic %s\n' "$*" >> "$COMMAND_LOG"
case "${1:-}:$RESTIC_MODE" in
    backup:backup-fail) exit 12 ;;
    forget:retention-fail) exit 13 ;;
esac
exit 0
""",
    )
    _write_stub(
        fake_bin,
        "rclone",
        """
printf 'rclone %s\n' "$*" >> "$COMMAND_LOG"
case "$RCLONE_MODE:$*" in
    upload-fail:*hapax-cachyos-restore.sh) exit 14 ;;
    registry-upload-fail:*host-storage-registry.json) exit 15 ;;
esac
exit 0
""",
    )
    _write_stub(fake_bin, "lsblk", "printf '%s\\n' 'NAME SIZE TYPE FSTYPE MOUNTPOINT'")
    for command in (
        "pacman",
        "flatpak",
        "git",
        "notify-send",
        "systemctl",
        "crontab",
    ):
        _write_stub(fake_bin, command, "exit 0")

    env = os.environ.copy()
    env.update(
        {
            "COMMAND_LOG": str(command_log),
            "HAPAX_BACKUP_DUMP_DIR": str(dump_dir),
            "HOME": str(fake_home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "QDRANT_MODE": qdrant_mode,
            "N8N_MODE": n8n_mode,
            "POSTGRES_MODE": postgres_mode,
            "RESTIC_MODE": restic_mode,
            "RCLONE_MODE": rclone_mode,
        }
    )
    result = subprocess.run(
        [str(SCRIPTS / f"hapax-backup-{lane}")],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    commands = command_log.read_text().splitlines() if command_log.exists() else []
    return result, commands
