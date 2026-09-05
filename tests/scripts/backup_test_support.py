from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
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
    missing_mounts: tuple[str, ...] = (),
    credential_mode: str = "success",
    bundle_mode: str = "none",
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fake_bin = tmp_path / "bin"
    fake_home = tmp_path / "home"
    dump_dir = tmp_path / "dump"
    command_log = tmp_path / "commands.log"
    fake_bin.mkdir()
    fake_home.mkdir()

    _write_stub(
        fake_bin,
        "pass",
        """
printf 'pass %s\n' "$*" >> "$COMMAND_LOG"
case "$CREDENTIAL_MODE" in
    failure) exit 9 ;;
    empty) exit 0 ;;
esac
printf '%s\n' test-password # pragma: allowlist secret
""",
    )
    _write_stub(
        fake_bin,
        "mountpoint",
        """
printf 'mountpoint %s\n' "$*" >> "$COMMAND_LOG"
case " $MISSING_MOUNTS " in
    *" $2 "*) exit 1 ;;
esac
exit 0
""",
    )
    if bundle_mode != "none":
        for name in ("local-only-one", "local-only-two"):
            repo = fake_home / "projects" / name
            repo.mkdir(parents=True)
            if bundle_mode == "invalid-worktree":
                (repo / ".git").write_text(f"gitdir: {tmp_path}/missing-git-dir\n")
            else:
                (repo / ".git").mkdir()
    _write_stub(
        fake_bin,
        "git",
        """
printf 'git %s\n' "$*" >> "$COMMAND_LOG"
if [ "${3:-}" = bundle ]; then
    if [ "$BUNDLE_MODE" = invalid-repo ] || [ "$BUNDLE_MODE" = invalid-worktree ]; then
        # Read-only git validation proves these fixture repositories cannot be bundled.
        exec /usr/bin/git -C "$2" rev-parse --verify HEAD
    fi
    printf '%s\n' bundle > "$5"
fi
exit 0
""",
    )
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
            "MISSING_MOUNTS": " ".join(missing_mounts),
            "CREDENTIAL_MODE": credential_mode,
            "BUNDLE_MODE": bundle_mode,
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


def run_watchdog(
    tmp_path: Path,
    *,
    ages: dict[str, int | None] | None = None,
    listing_mode: str = "present",
    check_mode: str = "success",
    fail_entries: tuple[str, ...] = (),
    empty_entries: tuple[str, ...] = (),
    monocle_threshold: str | None = "36",
    snapshot_mode: str = "valid",
) -> tuple[subprocess.CompletedProcess[str], list[dict], str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    qdrant = tmp_path / "qdrant"
    for index in range(5):
        (qdrant / str(index)).mkdir(parents=True)
    identities = [
        ("nas", "hapax-podium", "tier1-local"),
        ("b2", "hapax-podium", "tier2-remote"),
        ("b2", "hapax-monocle", "monocle-daily"),
        ("gdrive", "hapax-podium", "gdrive-critical"),
        ("b2", "foreign", "tier2-remote"),
        ("b2", "hapax-podium", "foreign-tag"),
    ]
    now = datetime.now(UTC)
    snapshots = []
    for index, (repo, host, tag) in enumerate(identities, 1):
        age = (ages or {}).get(tag if host != "foreign" else "foreign-host", 1)
        if age is not None:
            snapshots.append(
                dict(
                    repo=repo,
                    hostname=host,
                    tags=[tag],
                    id=f"{index:064x}",
                    time=(now - timedelta(hours=age)).isoformat(),
                )
            )
    snapshot_file = tmp_path / "snapshots.json"
    snapshot_file.write_text(json.dumps(snapshots))
    commands = tmp_path / "commands.jsonl"
    receipt = tmp_path / "receipt"
    _write_stub(
        fake_bin,
        "pass",
        """
case " $FAIL_ENTRIES " in *" $2 "*) exit 9 ;; esac
case " $EMPTY_ENTRIES " in *" $2 "*) exit 0 ;; esac
printf '%s\n' watchdog-fixture-password # pragma: allowlist secret
""",
    )
    restic = fake_bin / "restic"
    restic.write_text(r"""#!/usr/bin/python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
repo = os.environ['RESTIC_REPOSITORY']
with open(os.environ['COMMAND_LOG'], 'a') as stream:
    stream.write(json.dumps(dict(repo=repo, args=args)) + '\n')
snapshots = [s for s in json.loads(Path(os.environ['SNAPSHOTS']).read_text()) if s['repo'] == repo]
for flag, key in [('--host', 'hostname'), ('--tag', 'tags')]:
    if flag in args:
        value = args[args.index(flag) + 1]
        snapshots = [s for s in snapshots if (value in s[key] if key == 'tags' else value == s[key])]
if args[0] == 'snapshots':
    mode = os.environ['SNAPSHOT_MODE'] if repo == 'b2' and '--tag' in args and args[args.index('--tag') + 1] == 'tier2-remote' else 'valid'
    if mode == 'invalid-json':
        print('{')
    elif mode == 'invalid-metadata':
        print('{}')
    else:
        if mode == 'invalid-id': snapshots[0]['id'] = 'invalid'
        if mode == 'invalid-time': snapshots[0]['time'] = 'unknown'
        print(json.dumps(snapshots))
elif args[0] == 'check' and repo == 'nas':
    mode = os.environ['CHECK_MODE']
    if mode.startswith('locked'):
        print('unable to create lock: repository is already locked exclusively by PID 123', file=sys.stderr)
        sys.exit(11 if mode == 'locked' else 1)
    if mode == 'corrupt':
        print('pack checksum mismatch', file=sys.stderr)
        sys.exit(1)
elif args[0] == 'ls':
    mode = os.environ['LISTING_MODE'] if repo == 'b2' else 'present'
    if mode == 'failed':
        print('simulated listing denied ' + os.environ['RESTIC_PASSWORD'], file=sys.stderr)
        sys.exit(23)
    if mode == 'absent':
        print('-rw-r--r-- 0 0 1000 date time /dump/postgres-all.sql.old')
    elif mode in ('small', 'invalid-size'):
        size = '1' if mode == 'small' else 'unknown'
        print(f'-rw-r--r-- 0 0 {size} date time /dump/postgres-all.sql')
    elif mode == 'foreign-only' and f'{2:064x}' in args:
        pass
    else:
        print('-rw-r--r-- 0 0 1000 date time /dump/postgres-all.sql')
""")
    restic.chmod(0o755)
    _write_stub(
        fake_bin,
        "curl",
        """
while [ "$#" -gt 0 ]; do
    if [ "$1" = -d ]; then printf '%s' "$2" > "$RECEIPT.ntfy"; exit 0; fi
    shift
done
""",
    )
    _write_stub(fake_bin, "hapax-alert", """printf '%s' "$3" > "$RECEIPT" """)
    _write_stub(fake_bin, "notify-send", """printf '%s\n' "$*" > "$RECEIPT" """)
    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("HAPAX_MONOCLE_MAX_AGE_HOURS", None)
    env.update(
        {
            "HOME": str(fake_home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "HAPAX_ALERT_BIN": str(fake_bin / "hapax-alert"),
            "HAPAX_QDRANT_SNAP_DIR": str(qdrant),
            "HAPAX_TIER1_REPO": "nas",
            "HAPAX_TIER2_B2_REPO": "b2",
            "HAPAX_GDRIVE_CRITICAL_REPO": "gdrive",
            "HAPAX_TIER1_RESTIC_PASSWORD_ENTRY": "nas-password",  # pragma: allowlist secret
            "HAPAX_TIER2_B2_RESTIC_PASSWORD_ENTRY": "b2-password",  # pragma: allowlist secret
            "HAPAX_GDRIVE_CRITICAL_RESTIC_PASSWORD_ENTRY": "gdrive-password",  # pragma: allowlist secret
            "HAPAX_POSTGRES_DUMP_MIN_BYTES": "100",
            "SNAPSHOTS": str(snapshot_file),
            "SNAPSHOT_MODE": snapshot_mode,
            "COMMAND_LOG": str(commands),
            "RECEIPT": str(receipt),
            "LISTING_MODE": listing_mode,
            "CHECK_MODE": check_mode,
            "FAIL_ENTRIES": " ".join(fail_entries),
            "EMPTY_ENTRIES": " ".join(empty_entries),
            "TMPDIR": str(tmp_path),
        }
    )
    if monocle_threshold is not None:
        env["HAPAX_MONOCLE_MAX_AGE_HOURS"] = monocle_threshold
    result = subprocess.run(
        [str(SCRIPTS / "hapax-backup-watchdog")],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    rows = (
        [json.loads(line) for line in commands.read_text().splitlines()]
        if commands.exists()
        else []
    )
    report = receipt.read_text() if receipt.exists() else ""
    if receipt.with_suffix(".ntfy").exists():
        assert report == receipt.with_suffix(".ntfy").read_text()
    assert "watchdog-fixture-password" not in result.stdout + result.stderr + report
    return result, rows, report
