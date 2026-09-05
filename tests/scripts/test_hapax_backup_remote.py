from __future__ import annotations

from pathlib import Path

import pytest

from tests.scripts.backup_test_support import REPO, run_backup


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
def test_remote_backup_fails_closed_on_qdrant_errors(
    tmp_path: Path,
    mode: str,
    message: str,
) -> None:
    result, commands = run_backup(tmp_path, "remote", qdrant_mode=mode)

    assert result.returncode != 0
    assert message in result.stdout
    assert not any(command.startswith("restic backup") for command in commands)


@pytest.mark.parametrize("mode", ["export-fail", "copy-fail", "empty-output"])
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


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("exit-fail", "pg_dumpall exited non-zero"),
        ("missing-terminator", "dump lacks completion terminator"),
        ("too-small", "dump implausibly small"),
    ],
)
def test_remote_backup_fails_before_restic_on_postgres_errors(
    tmp_path: Path,
    mode: str,
    message: str,
) -> None:
    result, commands = run_backup(tmp_path, "remote", postgres_mode=mode)

    assert result.returncode != 0
    assert message in result.stdout
    assert not any(command.startswith("restic backup") for command in commands)


@pytest.mark.parametrize(
    ("mode", "forbidden_command"),
    [
        ("backup-fail", "restic forget"),
        ("retention-fail", "rclone copyto"),
    ],
)
def test_remote_backup_propagates_restic_failures(
    tmp_path: Path,
    mode: str,
    forbidden_command: str,
) -> None:
    result, commands = run_backup(tmp_path, "remote", restic_mode=mode)

    assert result.returncode != 0
    assert not any(command.startswith(forbidden_command) for command in commands)


def test_remote_backup_copyto_uses_recovery_instruction_object_name(tmp_path: Path) -> None:
    result, commands = run_backup(tmp_path, "remote", qdrant_mode="success")

    assert result.returncode == 0, result.stderr
    assert (
        f"rclone copyto {REPO}/scripts/hapax-cachyos-restore "
        "b2:hapax-backups/dr-scripts/hapax-cachyos-restore.sh"
    ) in commands
    assert (
        f"rclone copyto {REPO}/config/infrastructure/host-storage-registry.json "
        "b2:hapax-backups/dr-scripts/host-storage-registry.json"
    ) in commands
    assert not any(command.startswith("rclone copy ") for command in commands)


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("upload-fail", "DR script upload failed"),
        ("registry-upload-fail", "host storage registry upload failed"),
    ],
)
def test_remote_backup_propagates_recovery_object_upload_failures(
    tmp_path: Path,
    mode: str,
    message: str,
) -> None:
    result, _commands = run_backup(tmp_path, "remote", rclone_mode=mode)

    assert result.returncode != 0
    assert message in result.stdout


@pytest.mark.parametrize("lane", ["local", "remote"])
@pytest.mark.parametrize("missing_mounts", [("/store",), ("/mnt/nas",), ("/store", "/mnt/nas")])
def test_backup_mount_refusal_names_lane_and_skipped_steps(
    tmp_path: Path, lane: str, missing_mounts: tuple[str, ...]
) -> None:
    result, commands = run_backup(tmp_path, lane, missing_mounts=missing_mounts)
    if lane == "remote" and missing_mounts == ("/mnt/nas",):
        assert result.returncode == 0, result.stderr
        return
    assert result.returncode != 0
    receipt = next(line for line in result.stdout.splitlines() if "BACKUP RECEIPT" in line)
    assert f"lane={'tier1-local' if lane == 'local' else 'tier2-remote'} status=failed" in receipt
    assert "step=mounts snapshot=skipped git-bundles=skipped dr-publication=skipped" in receipt
    for mount in missing_mounts:
        if lane == "local" or mount == "/store":
            assert mount in receipt
    assert not any(
        command.startswith(("restic ", "docker ", "pass ", "rclone ")) for command in commands
    )
    assert not (tmp_path / "dump").exists()


@pytest.mark.parametrize("lane", ["local", "remote"])
@pytest.mark.parametrize("credential_mode", ["failure", "empty"])
def test_backup_credentials_fail_with_receipt_before_restic(
    tmp_path: Path, lane: str, credential_mode: str
) -> None:
    result, commands = run_backup(tmp_path, lane, credential_mode=credential_mode)
    assert result.returncode != 0
    assert "status=failed step=credentials snapshot=skipped" in result.stdout
    entry = "backups/restic-password" if lane == "local" else "backblaze/restic-password"
    assert f"cannot read non-empty pass entry {entry}" in result.stdout
    assert not any(command.startswith(("restic ", "docker ")) for command in commands)


@pytest.mark.parametrize("bundle_mode", ["invalid-repo", "invalid-worktree"])
def test_remote_bundle_failures_name_every_repository_and_refuse_green(
    tmp_path: Path, bundle_mode: str
) -> None:
    result, commands = run_backup(tmp_path, "remote", bundle_mode=bundle_mode)
    assert result.returncode != 0
    receipt = next(line for line in result.stdout.splitlines() if "BACKUP RECEIPT" in line)
    assert "lane=tier2-remote status=failed step=git-bundles" in receipt
    assert "snapshot=skipped git-bundles=failed dr-publication=skipped" in receipt
    for name in ("local-only-one", "local-only-two"):
        repo = tmp_path / "home" / "projects" / name
        assert str(repo) in receipt
        assert any(f"git -C {repo}/ bundle create" in command for command in commands)
    assert not any(
        command.startswith(("restic backup", "restic forget", "rclone ")) for command in commands
    )
    assert "Tier 2 backup complete" not in result.stdout


@pytest.mark.parametrize("bundle_mode, outcome", [("success", "success"), ("none", "skipped")])
def test_remote_receipt_names_bundle_success_or_skip(
    tmp_path: Path, bundle_mode: str, outcome: str
) -> None:
    result, _ = run_backup(tmp_path, "remote", bundle_mode=bundle_mode)
    assert result.returncode == 0, result.stderr
    assert f"snapshot=success git-bundles={outcome} dr-publication=success" in result.stdout
    assert "lane=tier2-remote status=success step=complete" in result.stdout


@pytest.mark.parametrize("lane, tag", [("local", "tier1-local"), ("remote", "tier2-remote")])
def test_backup_retention_filters_only_the_exact_podium_producer(
    tmp_path: Path, lane: str, tag: str
) -> None:
    result, commands = run_backup(tmp_path, lane)
    assert result.returncode == 0, result.stderr
    for verb in ("backup", "forget"):
        args = next(
            command.split() for command in commands if command.startswith(f"restic {verb} ")
        )
        assert args.count("--host") == args.count("--tag") == 1
        assert args[args.index("--host") + 1] == "hapax-podium"
        assert args[args.index("--tag") + 1] == tag
    forget = next(command for command in commands if command.startswith("restic forget "))
    assert "--group-by host,tags" in forget
