"""Regression tests: cc-claim dispatch-residue archive across device boundaries.

Pins the 2026-09-22 host-appendix incident: archiving terminal dispatch-only
claim residue with ``Path.replace`` raised ``OSError: [Errno 18] Invalid
cross-device link`` across the ``~/.cache/hapax`` <-> vault mount boundary,
crashing ``cc-claim`` mid-claim, and ``mkdir(exist_ok=False)`` aborted retries
that landed on the half-applied lineage directory. The archive logic lives in
``shared.sdlc_claim.archive_dispatch_only_claim_residue``; these tests pin the
cross-device move, the idempotent retry, and the end-to-end claim path across a
real device boundary.
"""

from __future__ import annotations

import errno
import os
import shutil
import uuid
from pathlib import Path

import pytest

from shared.sdlc_claim import (
    ClaimResidueArchiveHold,
    archive_dispatch_only_claim_residue,
)
from shared.sdlc_task_store import (
    ClaimDispatchBinding,
    write_claim_dispatch_binding,
)
from tests.scripts.test_cc_claim import (
    _SESSION_ID,
    _claim,
    _task_root,
    _write_task,
)

RESIDUE_TASK = "residue-closed-task"
FRESH_TASK = "fresh-after-residue"
CLAIM_KEY = "cx-test"
OBSERVED_AT = "20260922T062821Z"
LINEAGE_DIR_NAME = f"closed-claim-dispatch-residue-{OBSERVED_AT}-{CLAIM_KEY}"


def _write_residue(
    vault_root: Path,
    cache_dir: Path,
    *,
    session_id: str = "0f9f9f9f-1111-2222-3333-444455556666",
) -> bytes:
    (vault_root / "closed").mkdir(parents=True, exist_ok=True)
    (vault_root / "active").mkdir(parents=True, exist_ok=True)
    (vault_root / "closed" / f"{RESIDUE_TASK}.md").write_text(
        f"---\ntype: cc-task\ntask_id: {RESIDUE_TASK}\nstatus: done\n---\n",
        encoding="utf-8",
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    binding = ClaimDispatchBinding.create(
        task_id=RESIDUE_TASK,
        lane=CLAIM_KEY,
        session_id=session_id,
        claim_epoch=1,
        dispatch_message_id=f"dispatch-{RESIDUE_TASK}",
        platform="codex",
        mode="headless",
        profile="ultra",
        authority_case="CASE-TEST-001",
        binding_hash="a" * 64,
    )
    dispatch_path = write_claim_dispatch_binding(cache_dir, CLAIM_KEY, binding)
    return dispatch_path.read_bytes()


def _archive(
    vault_root: Path,
    cache_dir: Path,
    *,
    current_task_id: str = FRESH_TASK,
) -> list[Path]:
    return archive_dispatch_only_claim_residue(
        vault_root=vault_root,
        cache_dir=cache_dir,
        role=CLAIM_KEY,
        session_id=_SESSION_ID,
        current_task_id=current_task_id,
        observed_at=OBSERVED_AT,
    )


def _destination(vault_root: Path) -> Path:
    return (
        vault_root
        / "_lineage"
        / RESIDUE_TASK
        / LINEAGE_DIR_NAME
        / f"cc-claim-dispatch-{CLAIM_KEY}.json"
    )


def test_residue_archive_survives_cross_device_rename_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    cache_dir = tmp_path / "cache"
    residue_bytes = _write_residue(vault_root, cache_dir)

    def raise_exdev(src: str, dst: str) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link", src, None, dst)

    monkeypatch.setattr(os, "rename", raise_exdev)
    monkeypatch.setattr(os, "replace", raise_exdev)

    archived = _archive(vault_root, cache_dir)

    destination = _destination(vault_root)
    assert archived == [destination]
    assert destination.read_bytes() == residue_bytes
    assert not (cache_dir / f"cc-claim-dispatch-{CLAIM_KEY}.json").exists()
    readme = destination.parent / "README.md"
    assert f"archived_at: {OBSERVED_AT}" in readme.read_text(encoding="utf-8")


def test_residue_archive_tolerates_dir_from_prior_crash(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    cache_dir = tmp_path / "cache"
    residue_bytes = _write_residue(vault_root, cache_dir)

    lineage_dir = vault_root / "_lineage" / RESIDUE_TASK / LINEAGE_DIR_NAME
    lineage_dir.mkdir(parents=True)

    archived = _archive(vault_root, cache_dir)

    destination = _destination(vault_root)
    assert archived == [destination]
    assert destination.read_bytes() == residue_bytes
    assert (destination.parent / "README.md").is_file()


def test_residue_archive_completes_when_dispatch_already_moved(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    cache_dir = tmp_path / "cache"
    residue_bytes = _write_residue(vault_root, cache_dir)

    destination = _destination(vault_root)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(residue_bytes)

    archived = _archive(vault_root, cache_dir)

    assert archived == [destination]
    assert destination.read_bytes() == residue_bytes
    readme = destination.parent / "README.md"
    assert f"claim_key: {CLAIM_KEY}" in readme.read_text(encoding="utf-8")


def test_residue_archive_holds_when_residue_is_current_task(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    cache_dir = tmp_path / "cache"
    _write_residue(vault_root, cache_dir)

    with pytest.raises(
        ClaimResidueArchiveHold,
        match="current task has dispatch-only claim residue",
    ):
        _archive(vault_root, cache_dir, current_task_id=RESIDUE_TASK)


_DEV_SHM = Path("/dev/shm")


@pytest.mark.skipif(not _DEV_SHM.is_dir(), reason="/dev/shm unavailable")
def test_claim_archives_residue_across_real_device_boundary(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    shm_root = _DEV_SHM / f"cc-claim-exdev-{os.getpid()}-{uuid.uuid4().hex}"
    shm_root.mkdir(mode=0o700)
    try:
        first_note = _write_task(home, "active", "exdev-closed")
        first = _claim(home, "exdev-closed")
        assert first.returncode == 0, first.stderr

        task_root = _task_root(home)
        closed_note = task_root / "closed" / first_note.name
        closed_note.write_text(
            first_note.read_text(encoding="utf-8").replace("status: claimed", "status: done", 1),
            encoding="utf-8",
        )
        first_note.unlink()
        cache = home / ".cache" / "hapax"
        residue_paths = [
            cache / "cc-claim-dispatch-cx-test.json",
            cache / f"cc-claim-dispatch-cx-test-{_SESSION_ID}.json",
        ]
        assert all(path.is_file() for path in residue_paths)
        residue_bytes = {path.name: path.read_bytes() for path in residue_paths}
        for key in ("cx-test", f"cx-test-{_SESSION_ID}"):
            (cache / f"cc-active-task-{key}").unlink()
            (cache / f"cc-claim-epoch-{key}").unlink()

        # The device boundary sits between the claim cache (real directory on
        # tmp_path) and the lineage archive (symlinked into /dev/shm tmpfs):
        # the residue move must cross it exactly as it does on hosts where
        # ~/.cache/hapax and the vault live on different mounts.
        lineage_shm = shm_root / "lineage"
        lineage_shm.mkdir()
        if os.stat(lineage_shm).st_dev == os.stat(task_root).st_dev:
            pytest.skip("no real device boundary between /dev/shm and tmp_path")
        os.symlink(lineage_shm, task_root / "_lineage")

        second_note = _write_task(home, "active", "exdev-after-close")
        second = _claim(home, "exdev-after-close")

        assert second.returncode == 0, second.stderr
        assert "archived terminal dispatch-only claim residue" in second.stderr
        assert "status: claimed" in second_note.read_text(encoding="utf-8")
        archived = sorted(lineage_shm.glob("exdev-closed/closed-claim-dispatch-residue-*/*.json"))
        assert sorted(path.name for path in archived) == sorted(residue_bytes)
        for path in archived:
            assert path.read_bytes() == residue_bytes[path.name]
    finally:
        shutil.rmtree(shm_root, ignore_errors=True)
