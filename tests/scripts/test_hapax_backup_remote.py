from __future__ import annotations

from pathlib import Path

import pytest

from tests.scripts.backup_test_support import REPO, run_backup


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("list-fail", "failed to list Qdrant collections"),
        ("download-fail", "failed to download Qdrant snapshot for test-collection"),
    ],
)
def test_remote_backup_fails_closed_on_qdrant_errors(
    tmp_path: Path,
    mode: str,
    message: str,
) -> None:
    result, commands = run_backup(tmp_path, "remote", qdrant_mode=mode)

    assert result.returncode != 0
    assert message in result.stdout
    assert not any(command.startswith("restic backup") for command in commands)


@pytest.mark.parametrize("mode", ["export-fail", "copy-fail"])
def test_remote_backup_fails_before_restic_when_n8n_export_is_incomplete(
    tmp_path: Path,
    mode: str,
) -> None:
    result, commands = run_backup(
        tmp_path,
        "remote",
        qdrant_mode="success",
        n8n_mode=mode,
    )

    assert result.returncode != 0
    assert "FATAL:" in result.stdout
    assert "n8n workflow" in result.stdout
    assert not any(command.startswith("restic backup") for command in commands)


def test_remote_backup_uses_shared_postgres_superuser_contract(tmp_path: Path) -> None:
    result, commands = run_backup(tmp_path, "remote", qdrant_mode="success")

    assert result.returncode == 0, result.stderr
    assert "docker exec postgres pg_dumpall -U hapax" in commands


def test_remote_backup_copyto_uses_recovery_instruction_object_name(tmp_path: Path) -> None:
    result, commands = run_backup(tmp_path, "remote", qdrant_mode="success")

    assert result.returncode == 0, result.stderr
    assert (
        f"rclone copyto {REPO}/scripts/hapax-cachyos-restore "
        "b2:hapax-backups/dr-scripts/hapax-cachyos-restore.sh"
    ) in commands
    assert not any(command.startswith("rclone copy ") for command in commands)
