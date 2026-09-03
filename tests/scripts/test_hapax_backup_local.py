from __future__ import annotations

from pathlib import Path

import pytest

from tests.scripts.backup_test_support import run_backup


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("list-fail", "failed to list Qdrant collections"),
        ("empty-list", "collection list was empty or invalid"),
        ("invalid-list", "collection list was empty or invalid"),
        ("snapshot-fail", "failed to create Qdrant snapshot for test-collection"),
        ("invalid-snapshot", "returned no snapshot name for test-collection"),
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


@pytest.mark.parametrize("mode", ["export-fail", "copy-fail", "empty-output"])
def test_local_backup_fails_before_restic_when_n8n_export_is_incomplete(
    tmp_path: Path,
    mode: str,
) -> None:
    result, commands = run_backup(
        tmp_path,
        "local",
        qdrant_mode="success",
        n8n_mode=mode,
    )

    assert result.returncode != 0
    assert "FATAL:" in result.stdout
    assert "n8n workflow" in result.stdout
    assert not any(command.startswith("restic backup") for command in commands)


def test_local_backup_uses_shared_postgres_superuser_contract(tmp_path: Path) -> None:
    result, commands = run_backup(tmp_path, "local", qdrant_mode="success")

    assert result.returncode == 0, result.stderr
    assert "docker exec postgres pg_dumpall -U hapax" in commands


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("exit-fail", "pg_dumpall exited non-zero"),
        ("missing-terminator", "dump lacks completion terminator"),
        ("too-small", "dump implausibly small"),
    ],
)
def test_local_backup_fails_before_restic_on_postgres_errors(
    tmp_path: Path,
    mode: str,
    message: str,
) -> None:
    result, commands = run_backup(tmp_path, "local", postgres_mode=mode)

    assert result.returncode != 0
    assert message in result.stdout
    assert not any(command.startswith("restic backup") for command in commands)


@pytest.mark.parametrize(
    ("mode", "forbidden_command"),
    [
        ("backup-fail", "restic forget"),
        ("retention-fail", "restic snapshots"),
    ],
)
def test_local_backup_propagates_restic_failures(
    tmp_path: Path,
    mode: str,
    forbidden_command: str,
) -> None:
    result, commands = run_backup(tmp_path, "local", restic_mode=mode)

    assert result.returncode != 0
    assert not any(command.startswith(forbidden_command) for command in commands)
