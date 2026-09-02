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
    qdrant_mode: str,
    n8n_mode: str = "success",
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
    printf '%s\n' 'stub PostgreSQL dump'
elif [ "${1:-}" = exec ] && [ "${2:-}" = n8n ]; then
    if [ "$N8N_MODE" = export-fail ]; then
        exit 9
    fi
elif [ "${1:-}" = cp ] && [ "${2:-}" = n8n:/tmp/n8n-workflows.json ]; then
    if [ "$N8N_MODE" = copy-fail ]; then
        exit 10
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
    printf '%s\n' '-- PostgreSQL database cluster dump complete'
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
    printf '%s\n' 1000000000
else
    /usr/bin/stat "$@"
fi
""",
    )
    _write_stub(
        fake_bin,
        "jq",
        """
payload=$(cat)
case "$payload" in
    *\"collections\"*) printf '%s\n' test-collection ;;
    *\"name\"*) printf '%s\n' test.snapshot ;;
    *) exit 1 ;;
esac
""",
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
        printf '%s\n' '{"result":{"name":"test.snapshot"}}'
        ;;
    *"127.0.0.1:6333/collections"*)
        if [ "$QDRANT_MODE" = list-fail ]; then
            exit 22
        fi
        printf '%s\n' '{"result":{"collections":[{"name":"test-collection"}]}}'
        ;;
    *) exit 0 ;;
esac
""",
    )
    _write_stub(
        fake_bin,
        "restic",
        'printf \'restic %s\\n\' "$*" >> "$COMMAND_LOG"',
    )
    _write_stub(
        fake_bin,
        "rclone",
        'printf \'rclone %s\\n\' "$*" >> "$COMMAND_LOG"',
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
