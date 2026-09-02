from __future__ import annotations

from pathlib import Path

import pytest

from tests.scripts.backup_test_support import run_backup


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("list-fail", "failed to list Qdrant collections"),
        ("download-fail", "failed to download Qdrant snapshot for test-collection"),
    ],
)
def test_local_backup_fails_closed_on_qdrant_errors(
    tmp_path: Path,
    mode: str,
    message: str,
) -> None:
    result, commands = run_backup(tmp_path, "local", qdrant_mode=mode)

    assert result.returncode != 0
    assert message in result.stdout
    assert not any(command.startswith("restic backup") for command in commands)
