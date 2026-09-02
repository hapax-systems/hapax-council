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
    assert missing_result.returncode == 0
    assert missing_commands == []

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


def test_restore_reports_the_canonical_dr_object_name() -> None:
    result = subprocess.run(
        [str(RESTORE_SCRIPT), "--print-dr-object-name"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )

    assert result.stdout.strip() == "hapax-cachyos-restore.sh"
