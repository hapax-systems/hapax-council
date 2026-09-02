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


def test_remote_backup_copyto_uses_recovery_instruction_object_name(tmp_path: Path) -> None:
    result, commands = run_backup(tmp_path, "remote", qdrant_mode="success")

    assert result.returncode == 0, result.stderr
    assert (
        f"rclone copyto {REPO}/scripts/hapax-cachyos-restore "
        "b2:hapax-backups/dr-scripts/hapax-cachyos-restore.sh"
    ) in commands
    assert not any(command.startswith("rclone copy ") for command in commands)
