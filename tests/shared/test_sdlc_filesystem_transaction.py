from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import pytest

from shared import sdlc_filesystem_transaction as transaction
from shared.sdlc_filesystem_transaction import (
    FileMutation,
    FilesystemTransactionError,
    execute_filesystem_transaction,
    recover_filesystem_transaction,
    task_note_transaction_context,
)


def _load_manifest(journal_path: Path) -> tuple[str, list[transaction.TransactionEntry]]:
    record = transaction._load_journal(journal_path)
    return record.state, record.entries


def _target_nfs_rename(
    original: Callable[[Path, Path, int], None],
    target: Path,
) -> Callable[[Path, Path, int], None]:
    def rename(source: Path, destination: Path, flags: int) -> None:
        if (
            target in {source, destination}
            or source.parent.name == ".hapax-transactions"
            or destination.parent.name == ".hapax-transactions"
        ):
            raise OSError(errno.EINVAL, "target NFS rejects rename flags")
        original(source, destination, flags)

    return rename


def test_execute_commits_all_postimages_and_removes_journal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = root / "first"
    second = root / "second"
    first.write_bytes(b"before")
    journal = root / "journal.json"

    execute_filesystem_transaction(
        journal,
        (
            FileMutation(first, b"after", mode=0o640),
            FileMutation(second, b"created", mode=0o600, expected_exists=False),
        ),
        allowed_roots=(root,),
    )

    assert first.read_bytes() == b"after"
    assert second.read_bytes() == b"created"
    assert not journal.exists()
    assert len(list(root.glob(".journal.json.history-*-committed"))) == 1


def test_execute_canonicalizes_symlinked_journal_root_before_locking(tmp_path: Path) -> None:
    physical_cache = tmp_path / "physical-cache"
    physical_cache.mkdir()
    cache_alias = tmp_path / "home" / ".cache" / "hapax"
    cache_alias.parent.mkdir(parents=True)
    cache_alias.symlink_to(physical_cache, target_is_directory=True)
    target = cache_alias / "cc-active-task-cx-test"
    journal = cache_alias / "cc-ownership-txn.json"
    code = """
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from shared.sdlc_filesystem_transaction import FileMutation, execute_filesystem_transaction

journal = Path(sys.argv[2])
target = Path(sys.argv[3])
cache = Path(sys.argv[4])
execute_filesystem_transaction(
    journal,
    (FileMutation(target, b"task-x\\n", mode=0o600, expected_exists=False),),
    allowed_roots=(cache,),
)
"""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(Path(__file__).resolve().parents[2]),
            str(journal),
            str(target),
            str(cache_alias),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == b"task-x\n"
    assert not journal.exists()


@pytest.mark.parametrize(
    ("first_vault_name", "second_vault_name"),
    [
        ("hapax-requests", "hapax-cc-tasks"),
        ("hapax-cc-tasks", "hapax-requests"),
    ],
)
def test_stable_ownership_journal_recovers_across_governance_vaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_vault_name: str,
    second_vault_name: str,
) -> None:
    projects = tmp_path / "20-projects"
    first_vault = projects / first_vault_name
    second_vault = projects / second_vault_name
    for vault in (first_vault, second_vault):
        (vault / "active").mkdir(parents=True)
        (vault / "closed").mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    journal = cache / "cc-ownership-txn.json"
    first_target = first_vault / "active" / "first.md"
    first_guard = first_vault / "closed" / "first.md"
    second_target = second_vault / "active" / "second.md"
    original_archive = transaction._archive_journal
    interrupted = False

    def interrupt_first_commit(
        path: Path,
        record: transaction._JournalRecord,
        *,
        outcome: str,
    ) -> Path:
        nonlocal interrupted
        if not interrupted and outcome == "committed":
            interrupted = True
            raise RuntimeError("simulated crash before journal archive")
        return original_archive(path, record, outcome=outcome)

    monkeypatch.setattr(transaction, "_archive_journal", interrupt_first_commit)

    with pytest.raises(RuntimeError, match="simulated crash"):
        execute_filesystem_transaction(
            journal,
            (
                FileMutation(first_target, b"first", mode=0o644, expected_exists=False),
                FileMutation(first_guard, None, expected_exists=False),
            ),
            allowed_roots=(cache, first_vault),
        )

    assert journal.exists()
    assert first_target.read_bytes() == b"first"
    execute_filesystem_transaction(
        journal,
        (FileMutation(second_target, b"second", mode=0o644, expected_exists=False),),
        allowed_roots=(cache, second_vault),
    )

    assert not journal.exists()
    assert first_target.read_bytes() == b"first"
    assert second_target.read_bytes() == b"second"


def test_canonical_request_vault_uses_shared_ownership_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("HAPAX_CC_OWNERSHIP_CACHE_DIR", raising=False)
    request_vault = tmp_path / "Documents/Personal/20-projects/hapax-requests"
    path = request_vault / "active" / "REQ-test.md"

    resolved_vault, cache_dir = task_note_transaction_context(
        path,
        vault_root=request_vault,
    )

    assert resolved_vault == request_vault
    assert cache_dir == tmp_path / ".cache/hapax"


def test_recovery_domain_expands_only_the_named_stable_ownership_journal(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "20-projects"
    task_vault = projects / "hapax-cc-tasks"
    request_vault = projects / "hapax-requests"
    cache = tmp_path / "cache"

    stable_roots = transaction.ownership_transaction_allowed_roots(
        cache / "cc-ownership-txn.json",
        (cache, task_vault),
    )
    unrelated_roots = transaction.ownership_transaction_allowed_roots(
        cache / "other-journal.json",
        (cache, task_vault),
    )

    assert stable_roots == (cache, task_vault, request_vault)
    assert unrelated_roots == (cache, task_vault)


def test_prepared_journal_rolls_back_partial_postimages(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = root / "first"
    second = root / "second"
    first.write_bytes(b"first-before")
    second.write_bytes(b"second-before")
    journal = root / "journal.json"
    entries = [
        {
            "path": str(first),
            "pre_content": transaction._encoded(b"first-before"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"first-after"),
            "post_mode": 0o600,
        },
        {
            "path": str(second),
            "pre_content": transaction._encoded(b"second-before"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"second-after"),
            "post_mode": 0o600,
        },
    ]
    transaction._write_manifest(journal, state="prepared", entries=entries)
    _state, prepared = _load_manifest(journal)
    transaction._apply(
        prepared[:1],
        image="post",
        accepted_current_images=("pre",),
        allowed_roots=(root,),
    )

    assert recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert first.read_bytes() == b"first-before"
    assert second.read_bytes() == b"second-before"
    assert not journal.exists()


def test_committed_journal_rolls_forward_partial_postimages(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = root / "first"
    second = root / "second"
    first.write_bytes(b"first-before")
    second.write_bytes(b"second-before")
    journal = root / "journal.json"
    entries = [
        {
            "path": str(first),
            "pre_content": transaction._encoded(b"first-before"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"first-after"),
            "post_mode": 0o600,
        },
        {
            "path": str(second),
            "pre_content": transaction._encoded(b"second-before"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"second-after"),
            "post_mode": 0o600,
        },
    ]
    transaction._write_manifest(journal, state="committed", entries=entries)
    _state, prepared = _load_manifest(journal)
    transaction._apply(
        prepared[:1],
        image="post",
        accepted_current_images=("pre",),
        allowed_roots=(root,),
    )

    assert recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert first.read_bytes() == b"first-after"
    assert second.read_bytes() == b"second-after"
    assert not journal.exists()


def test_corrupt_journal_fails_closed_without_touching_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"before")
    journal = root / "journal.json"
    journal.mkdir(mode=0o700)
    (journal / "manifest.json").write_text(
        json.dumps(
            {
                "schema": transaction.TRANSACTION_SCHEMA,
                "transaction_id": "a" * 32,
                "entries": [],
                "manifest_sha256": "0" * 64,
            }
        ),
        encoding="ascii",
    )

    with pytest.raises(FilesystemTransactionError, match="journal hash mismatch"):
        recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert target.read_bytes() == b"before"
    assert journal.exists()


def test_expected_preimage_blocks_lost_update_before_journal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"unexpected")
    journal = root / "journal.json"

    with pytest.raises(FilesystemTransactionError, match="preimage changed"):
        execute_filesystem_transaction(
            journal,
            (FileMutation(target, b"after", expected_sha256="0" * 64),),
            allowed_roots=(root,),
        )

    assert target.read_bytes() == b"unexpected"
    assert not journal.exists()


@pytest.mark.parametrize("state", ["prepared", "committed"])
def test_recovery_refuses_unrecorded_third_image_without_touching_any_file(
    tmp_path: Path,
    state: Literal["prepared", "committed"],
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = root / "first"
    second = root / "second"
    first.write_bytes(b"first-before")
    second.write_bytes(b"second-before")
    journal = root / "journal.json"
    entries = [
        {
            "path": str(first),
            "pre_content": transaction._encoded(b"first-before"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"first-after"),
            "post_mode": 0o644,
        },
        {
            "path": str(second),
            "pre_content": transaction._encoded(b"second-before"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"second-after"),
            "post_mode": 0o644,
        },
    ]
    transaction._write_manifest(journal, state=state, entries=entries)
    _loaded_state, prepared = _load_manifest(journal)
    transaction._apply(
        prepared[:1],
        image="post",
        accepted_current_images=("pre",),
        allowed_roots=(root,),
    )
    second.write_bytes(b"operator-third-image")
    before = (first.read_bytes(), second.read_bytes())

    with pytest.raises(FilesystemTransactionError, match="third-image conflict"):
        recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert (first.read_bytes(), second.read_bytes()) == before
    assert journal.is_dir()


def test_exchange_race_preserves_displaced_third_image_and_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    original = transaction._renameat2
    injected = False

    def race(source: Path, destination: Path, flags: int) -> None:
        nonlocal injected
        if not injected and flags == transaction._RENAME_EXCHANGE and source == target:
            injected = True
            target.write_bytes(b"operator-third-image")
        original(source, destination, flags)

    monkeypatch.setattr(transaction, "_renameat2", race)

    with pytest.raises(FilesystemTransactionError, match="third-image conflict"):
        execute_filesystem_transaction(
            journal,
            (FileMutation(target, b"post"),),
            allowed_roots=(root,),
        )

    assert injected
    assert journal.is_dir()
    _state, entries = _load_manifest(journal)
    stage = Path(str(entries[0]["stage_path"]))
    assert {target.read_bytes(), stage.read_bytes()} == {b"post", b"operator-third-image"}


@pytest.mark.parametrize("operation", ["create", "delete"])
def test_noreplace_race_preserves_every_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    mutation: FileMutation
    if operation == "create":
        mutation = FileMutation(target, b"post", expected_exists=False)
    else:
        target.write_bytes(b"pre")
        mutation = FileMutation(target, None, expected_exists=True)
    journal = root / "journal.json"
    original = transaction._renameat2
    injected = False

    def race(source: Path, destination: Path, flags: int) -> None:
        nonlocal injected
        if (
            not injected
            and flags == transaction._RENAME_NOREPLACE
            and target
            in {
                source,
                destination,
            }
        ):
            injected = True
            target.write_bytes(b"operator-third-image")
        original(source, destination, flags)

    monkeypatch.setattr(transaction, "_renameat2", race)

    with pytest.raises(FilesystemTransactionError, match="third-image conflict"):
        execute_filesystem_transaction(journal, (mutation,), allowed_roots=(root,))

    assert injected
    assert journal.is_dir()
    _state, entries = _load_manifest(journal)
    stage = Path(str(entries[0]["stage_path"]))
    preserved = [path.read_bytes() for path in (target, stage) if path.is_file()]
    assert b"operator-third-image" in preserved
    if operation == "create":
        assert b"post" in preserved
    else:
        manifest = (journal / "manifest.json").read_bytes()
        assert transaction._encoded(b"pre").encode() in manifest


@pytest.mark.parametrize("state", ["prepared", "committed"])
def test_recovery_syscall_race_preserves_third_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: Literal["prepared", "committed"],
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    transaction._write_manifest(journal, state=state, entries=entries)
    _loaded_state, prepared = _load_manifest(journal)
    if state == "prepared":
        transaction._apply(
            prepared,
            image="post",
            accepted_current_images=("pre",),
            allowed_roots=(root,),
        )
    original = transaction._renameat2
    injected = False

    def race(source: Path, destination: Path, flags: int) -> None:
        nonlocal injected
        if not injected and flags == transaction._RENAME_EXCHANGE:
            injected = True
            target.write_bytes(b"operator-third-image")
        original(source, destination, flags)

    monkeypatch.setattr(transaction, "_renameat2", race)

    with pytest.raises(FilesystemTransactionError, match="third-image conflict"):
        recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert injected
    stage = Path(str(prepared[0]["stage_path"]))
    assert b"operator-third-image" in {target.read_bytes(), stage.read_bytes()}
    assert journal.is_dir()


def test_journal_archive_race_preserves_original_and_intruder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    displaced_journal = root / "operator-preserved-original-journal"
    original = transaction._renameat2
    injected = False

    def race(source: Path, destination: Path, flags: int) -> None:
        nonlocal injected
        if not injected and source == journal and flags == transaction._RENAME_NOREPLACE:
            injected = True
            source.rename(displaced_journal)
            source.mkdir()
            (source / "operator-third-image").write_bytes(b"preserve-me")
        original(source, destination, flags)

    monkeypatch.setattr(transaction, "_renameat2", race)

    with pytest.raises(FilesystemTransactionError, match="journal third-image conflict"):
        execute_filesystem_transaction(
            journal,
            (FileMutation(target, b"post"),),
            allowed_roots=(root,),
        )

    assert injected
    assert target.read_bytes() == b"post"
    assert displaced_journal.is_dir()
    intruder_archives = list(root.glob(".journal.json.history-*-committed"))
    assert len(intruder_archives) == 1
    assert (intruder_archives[0] / "operator-third-image").read_bytes() == b"preserve-me"


def test_stage_directory_accepts_server_mapped_new_entry_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    monkeypatch.setattr(transaction.os, "geteuid", lambda: 2**31 - 1)

    execute_filesystem_transaction(
        root / "journal",
        (FileMutation(target, b"post"),),
        allowed_roots=(root,),
    )

    stage = root / ".hapax-transactions"
    assert stage.is_dir()
    assert stage.stat().st_uid != transaction.os.geteuid()
    assert target.read_bytes() == b"post"


def test_filesystem_without_unnamed_owner_probe_refuses_before_target_or_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    original_open = transaction.os.open

    def refuse_tmpfile(path: object, flags: int, mode: int = 0o777) -> int:
        temporary_flag = getattr(os, "O_TMPFILE", 0)
        if temporary_flag and flags & temporary_flag == temporary_flag:
            raise OSError(errno.EOPNOTSUPP, "unnamed files unsupported")
        return original_open(path, flags, mode)

    monkeypatch.setattr(transaction.os, "open", refuse_tmpfile)

    with pytest.raises(FilesystemTransactionError, match="lacks unnamed ownership probes"):
        execute_filesystem_transaction(
            journal,
            (FileMutation(target, b"post"),),
            allowed_roots=(root,),
        )

    assert target.read_bytes() == b"pre"
    assert not journal.exists()
    assert not (root / ".hapax-owner-probe").exists()


def test_nfs_without_no_replace_support_refuses_before_journal_or_target_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"

    original_rename = transaction._renameat2
    monkeypatch.setattr(transaction, "_renameat2", _target_nfs_rename(original_rename, target))

    with pytest.raises(FilesystemTransactionError, match="atomic no-replace support"):
        execute_filesystem_transaction(
            journal,
            (
                FileMutation(
                    target,
                    b"post",
                    expected_sha256=hashlib.sha256(b"pre").hexdigest(),
                ),
            ),
            allowed_roots=(root,),
        )

    assert target.read_bytes() == b"pre"
    assert not journal.exists()
    assert not list((root / ".hapax-transactions").glob("*.stage"))


def test_nfs_create_refuses_before_publishing_live_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    journal = root / "journal.json"

    original_rename = transaction._renameat2
    monkeypatch.setattr(transaction, "_renameat2", _target_nfs_rename(original_rename, target))

    with pytest.raises(FilesystemTransactionError, match="no authoritative image was moved"):
        execute_filesystem_transaction(
            journal,
            (FileMutation(target, b"post", expected_exists=False),),
            allowed_roots=(root,),
        )

    assert not target.exists()
    assert not journal.exists()


def test_nfs_noop_prepared_recovery_refuses_before_journal_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    transaction._write_manifest(journal, state="prepared", entries=entries)
    _state, prepared = _load_manifest(journal)

    original_rename = transaction._renameat2
    monkeypatch.setattr(transaction, "_renameat2", _target_nfs_rename(original_rename, target))
    with pytest.raises(FilesystemTransactionError, match="atomic no-replace support"):
        transaction._transition_entry(prepared[0], image="post", allowed_roots=(root,))

    with pytest.raises(FilesystemTransactionError, match="atomic no-replace support"):
        recover_filesystem_transaction(journal, allowed_roots=(root,))
    assert target.read_bytes() == b"pre"
    assert journal.exists()
    assert not list(root.glob(".journal.json.history-*-recovered-pre"))


def test_noop_recovery_probes_distinct_target_filesystem_before_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal_root = tmp_path / "journal-root"
    target_root = tmp_path / "target-root"
    journal_root.mkdir()
    target_root.mkdir()
    target = target_root / "target"
    target.write_bytes(b"pre")
    journal = journal_root / "journal.json"
    transaction._write_manifest(
        journal,
        state="prepared",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(b"pre"),
                "pre_mode": 0o644,
                "post_content": transaction._encoded(b"post"),
                "post_mode": 0o644,
            }
        ],
    )
    original_rename = transaction._renameat2

    def unsupported_target(source: Path, destination: Path, flags: int) -> None:
        if source.is_relative_to(target_root) or destination.is_relative_to(target_root):
            raise OSError(errno.EINVAL, "target filesystem rejects rename flags")
        original_rename(source, destination, flags)

    monkeypatch.setattr(transaction, "_renameat2", unsupported_target)

    with pytest.raises(FilesystemTransactionError, match="atomic no-replace support"):
        recover_filesystem_transaction(
            journal,
            allowed_roots=(journal_root, target_root),
        )

    assert journal.is_dir()
    assert target.read_bytes() == b"pre"
    assert not list(journal_root.glob(".journal.json.history-*"))


def test_no_replace_capability_probe_preserves_raced_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"

    raced_destination: Path | None = None

    def unsupported(_source: Path, destination: Path, _flags: int) -> None:
        nonlocal raced_destination
        destination.write_bytes(b"operator-third-image")
        raced_destination = destination
        raise OSError(errno.EINVAL, "NFS rejects rename flags")

    monkeypatch.setattr(transaction, "_renameat2", unsupported)

    with pytest.raises(FilesystemTransactionError, match="no authoritative image was moved"):
        execute_filesystem_transaction(
            journal,
            (FileMutation(target, b"post"),),
            allowed_roots=(root,),
        )

    assert raced_destination is not None
    assert raced_destination.read_bytes() == b"operator-third-image"
    assert target.read_bytes() == b"pre"
    assert not journal.exists()


def test_no_replace_capability_probe_requires_eexist_and_preserves_probe_identities(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    stage = transaction._ensure_stage_directory(target)

    transaction._require_atomic_no_replace_support((target,))
    source = stage / ".hapax-noreplace-probe-source"
    destination = stage / ".hapax-noreplace-probe-destination"
    before = (transaction._path_identity(source), transaction._path_identity(destination))

    transaction._require_atomic_no_replace_support((target,))

    assert transaction._path_identity(source) == before[0]
    assert transaction._path_identity(destination) == before[1]


def test_no_replace_capability_probe_refuses_ignored_flag_without_unbounded_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    original = transaction._renameat2

    def ignore_noreplace(source: Path, destination: Path, flags: int) -> None:
        if source.name == ".hapax-noreplace-probe-source":
            assert flags == transaction._RENAME_NOREPLACE
            os.replace(source, destination)
            return
        original(source, destination, flags)

    monkeypatch.setattr(transaction, "_renameat2", ignore_noreplace)

    for _attempt in range(2):
        with pytest.raises(FilesystemTransactionError, match="replaced an existing no-replace"):
            execute_filesystem_transaction(
                journal,
                (FileMutation(target, b"post"),),
                allowed_roots=(root,),
            )

    probes = list((root / ".hapax-transactions").glob(".hapax-noreplace-probe-*"))
    assert len(probes) <= 2
    assert target.read_bytes() == b"pre"
    assert not journal.exists()


def test_capability_probe_never_unlinks_shared_probe_pathnames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    transaction._ensure_stage_directory(target)
    original_unlink = Path.unlink

    def reject_probe_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.name.startswith((".hapax-noreplace-probe-", ".hapax-owner-probe")):
            raise AssertionError(f"probe pathname was unlinked: {path}")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", reject_probe_unlink)

    transaction._require_atomic_no_replace_support((target,))


def test_archive_without_no_replace_support_preserves_active_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    transaction._write_manifest(
        journal,
        state="committed",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(b"pre"),
                "pre_mode": 0o644,
                "post_content": transaction._encoded(b"post"),
                "post_mode": 0o644,
            }
        ],
    )
    original_rename = transaction._renameat2

    def unsupported_archive(source: Path, destination: Path, flags: int) -> None:
        if source == journal:
            raise OSError(errno.EINVAL, "journal filesystem rejects rename flags")
        original_rename(source, destination, flags)

    monkeypatch.setattr(transaction, "_renameat2", unsupported_archive)

    with pytest.raises(FilesystemTransactionError, match="requires atomic no-replace"):
        recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert target.read_bytes() == b"post"
    assert journal.is_dir()
    assert (journal / "intent.json").is_file()
    assert not list(root.glob(".journal.json.history-*-recovered-post"))


def test_torn_temporary_write_never_publishes_authoritative_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    original_write = os.write
    injected = False

    def tear(descriptor: int, content: bytes) -> int:
        nonlocal injected
        if not injected and len(content) > 1:
            injected = True
            original_write(descriptor, content[: len(content) // 2])
            raise OSError(errno.ENOSPC, "simulated torn write")
        return original_write(descriptor, content)

    monkeypatch.setattr(transaction.os, "write", tear)

    with pytest.raises(OSError, match="simulated torn write"):
        execute_filesystem_transaction(
            journal,
            (FileMutation(target, b"post"),),
            allowed_roots=(root,),
        )

    assert injected
    assert target.read_bytes() == b"pre"
    assert not journal.exists()
    assert not transaction._intent_path(journal).exists()
    assert list(root.glob(".hapax-write-*")), "the non-authoritative torn temp is preserved"


def test_portable_displacement_never_clobbers_raced_quarantine_occupant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    original_renameat2 = transaction._renameat2
    raced_destination: Path | None = None

    def race(source: Path, destination: Path, flags: int) -> None:
        nonlocal raced_destination
        if raced_destination is None and source == target and destination.name == "image":
            destination.write_bytes(b"operator-quarantine-occupant")
            raced_destination = destination
            raise OSError(errno.EINVAL, "target NFS rejects rename flags")
        original_renameat2(source, destination, flags)

    monkeypatch.setattr(transaction, "_renameat2", race)

    with pytest.raises(FilesystemTransactionError, match="atomic no-replace support"):
        transaction._preserve_pathname_removal(target, transaction._path_identity(target))

    assert raced_destination is not None
    assert raced_destination.read_bytes() == b"operator-quarantine-occupant"
    assert target.read_bytes() == b"pre"


def test_journal_substitution_while_waiting_for_target_locks_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    transaction._write_manifest(
        journal,
        state="committed",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(b"pre"),
                "pre_mode": 0o644,
                "post_content": transaction._encoded(b"post"),
                "post_mode": 0o644,
            }
        ],
    )
    displaced = root / "operator-preserved-journal"
    original_target_locks = transaction._target_locks

    @contextmanager
    def substitute(paths: list[Path]):
        with original_target_locks(paths):
            journal.rename(displaced)
            shutil.copytree(displaced, journal)
            yield

    monkeypatch.setattr(transaction, "_target_locks", substitute)

    with pytest.raises(FilesystemTransactionError, match="acquiring target locks"):
        recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert target.read_bytes() == b"pre"
    assert displaced.is_dir()
    assert journal.is_dir()


def test_v1_journal_substitution_while_waiting_for_target_locks_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"post")
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "prepared", "entries": entries}
    journal_record = {
        **body,
        "manifest_sha256": hashlib.sha256(transaction._canonical_bytes(body)).hexdigest(),
    }
    journal = root / "journal.json"
    journal.write_bytes(transaction._canonical_bytes(journal_record) + b"\n")
    journal.chmod(0o600)
    displaced = root / "operator-preserved-v1-journal"
    original_target_locks = transaction._target_locks

    @contextmanager
    def substitute(paths: list[Path]):
        with original_target_locks(paths):
            journal.rename(displaced)
            shutil.copy2(displaced, journal)
            yield

    monkeypatch.setattr(transaction, "_target_locks", substitute)

    with pytest.raises(FilesystemTransactionError, match="v1 journal identity changed"):
        recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert target.read_bytes() == b"post"
    assert displaced.is_file()
    assert journal.is_file()


def test_legacy_prepared_journal_is_retired_after_later_committed_image(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "cc-active-task-cx-test"
    legacy = root / "cc-ownership-txn-a.json"
    transaction._write_manifest(
        legacy,
        state="prepared",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(None),
                "pre_mode": None,
                "post_content": transaction._encoded(b"task-a\n"),
                "post_mode": 0o600,
            }
        ],
    )
    legacy_record = transaction._load_journal(legacy)
    transaction._apply(
        legacy_record.entries,
        image="post",
        accepted_current_images=("pre",),
        allowed_roots=(root,),
    )

    # A later task-keyed transaction committed before global serialization and
    # left A's prepared journal behind. Its bytes are intentionally neither of
    # A's images.
    target.write_bytes(b"task-b\n")
    stable = root / "cc-ownership-txn.json"

    transaction.migrate_legacy_filesystem_transactions(
        stable,
        (legacy,),
        allowed_roots=(root,),
    )

    assert target.read_bytes() == b"task-b\n"
    assert not legacy.exists()
    assert (
        len(list(root.glob(".cc-ownership-txn-a.json.history-*-legacy-superseded-third-image")))
        == 1
    )


def test_legacy_v3_supersession_probes_target_before_archiving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    legacy = root / "cc-ownership-txn-a.json"
    transaction._write_manifest(
        legacy,
        state="prepared",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(b"pre"),
                "pre_mode": 0o644,
                "post_content": transaction._encoded(b"post"),
                "post_mode": 0o644,
            }
        ],
    )
    target.write_bytes(b"operator-third-image")
    probes: list[tuple[Path, ...]] = []

    def refuse_target(paths: list[Path] | tuple[Path, ...]) -> None:
        probe = tuple(paths)
        probes.append(probe)
        if target in probe:
            raise FilesystemTransactionError("atomic no-replace support unavailable")

    monkeypatch.setattr(transaction, "_require_atomic_no_replace_support", refuse_target)

    with pytest.raises(FilesystemTransactionError, match="atomic no-replace support"):
        transaction.migrate_legacy_filesystem_transactions(
            root / "cc-ownership-txn.json",
            (legacy,),
            allowed_roots=(root,),
        )

    assert any(legacy in probe and target in probe for probe in probes)
    assert target.read_bytes() == b"operator-third-image"
    assert legacy.is_dir()
    assert not list(root.glob(".cc-ownership-txn-a.json.history-*-legacy-superseded*"))


def test_stable_prepared_journal_recovers_before_legacy_classification(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "cc-active-task-cx-test"
    legacy = root / "cc-ownership-txn-a.json"
    transaction._write_manifest(
        legacy,
        state="prepared",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(None),
                "pre_mode": None,
                "post_content": transaction._encoded(b"task-a\n"),
                "post_mode": 0o600,
            }
        ],
    )
    legacy_record = transaction._load_journal(legacy)
    transaction._apply(
        legacy_record.entries,
        image="post",
        accepted_current_images=("pre",),
        allowed_roots=(root,),
    )

    stable = root / "cc-ownership-txn.json"
    transaction._write_manifest(
        stable,
        state="prepared",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(b"task-a\n"),
                "pre_mode": 0o600,
                "post_content": transaction._encoded(b"task-b\n"),
                "post_mode": 0o600,
            }
        ],
    )
    stable_record = transaction._load_journal(stable)
    transaction._apply(
        stable_record.entries,
        image="post",
        accepted_current_images=("pre",),
        allowed_roots=(root,),
    )

    transaction.migrate_legacy_filesystem_transactions(
        stable,
        (legacy,),
        allowed_roots=(root,),
    )

    assert not target.exists()
    assert not stable.exists()
    assert not legacy.exists()
    assert list(root.glob(".cc-ownership-txn.json.history-*-recovered-pre"))
    assert list(root.glob(".cc-ownership-txn-a.json.history-*-recovered-pre"))


def test_stable_execute_drains_committed_legacy_close_before_current_writer(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    active = root / "active"
    closed = root / "closed"
    active.mkdir(parents=True)
    closed.mkdir()
    active_note = active / "task.md"
    closed_note = closed / "task.md"
    active_note.write_bytes(b"in-progress")
    legacy = root / "cc-ownership-txn-task.json"
    transaction._write_manifest(
        legacy,
        state="committed",
        entries=[
            {
                "path": str(active_note),
                "pre_content": transaction._encoded(b"in-progress"),
                "pre_mode": 0o644,
                "post_content": transaction._encoded(None),
                "post_mode": None,
            },
            {
                "path": str(closed_note),
                "pre_content": transaction._encoded(None),
                "pre_mode": None,
                "post_content": transaction._encoded(b"done"),
                "post_mode": 0o644,
            },
        ],
    )

    with pytest.raises(FilesystemTransactionError, match="preimage changed"):
        execute_filesystem_transaction(
            root / "cc-ownership-txn.json",
            (
                FileMutation(
                    active_note,
                    b"release-armed",
                    expected_sha256=hashlib.sha256(b"in-progress").hexdigest(),
                ),
            ),
            allowed_roots=(root,),
            legacy_journals=(legacy,),
        )

    assert not active_note.exists()
    assert closed_note.read_bytes() == b"done"
    assert not legacy.exists()
    assert list(root.glob(".cc-ownership-txn-task.json.history-*-recovered-post"))


def test_legacy_auxiliary_third_image_is_not_classified_as_supersession(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    legacy = root / "cc-ownership-txn-a.json"
    transaction._write_manifest(
        legacy,
        state="prepared",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(b"pre"),
                "pre_mode": 0o644,
                "post_content": transaction._encoded(b"post"),
                "post_mode": 0o644,
            }
        ],
    )
    record = transaction._load_journal(legacy)
    hold, _move = transaction._entry_auxiliary_paths(record.entries[0], (root,))
    hold.write_bytes(b"operator-third-image")

    with pytest.raises(FilesystemTransactionError, match="auxiliary third-image conflict"):
        transaction.migrate_legacy_filesystem_transactions(
            root / "cc-ownership-txn.json",
            (legacy,),
            allowed_roots=(root,),
        )

    assert target.read_bytes() == b"pre"
    assert hold.read_bytes() == b"operator-third-image"
    assert legacy.is_dir()
    assert not list(root.glob(".cc-ownership-txn-a.json.history-*-legacy-superseded*"))


def test_v1_conversion_rejects_mode_only_third_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"same-bytes")
    target.chmod(0o600)
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"same-bytes"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"same-bytes"),
            "post_mode": 0o600,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "prepared", "entries": entries}
    record = {
        **body,
        "manifest_sha256": hashlib.sha256(transaction._canonical_bytes(body)).hexdigest(),
    }
    journal = root / "journal.json"
    journal.write_bytes(transaction._canonical_bytes(record) + b"\n")
    journal.chmod(0o600)
    original_execute = transaction._execute_filesystem_transaction_unlocked

    def change_mode_before_conversion(
        compatibility_journal: Path,
        mutations: tuple[FileMutation, ...] | list[FileMutation],
        *,
        allowed_roots: tuple[Path, ...],
    ) -> None:
        target.chmod(0o640)
        original_execute(
            compatibility_journal,
            mutations,
            allowed_roots=allowed_roots,
        )

    monkeypatch.setattr(
        transaction, "_execute_filesystem_transaction_unlocked", change_mode_before_conversion
    )

    with pytest.raises(FilesystemTransactionError, match="mode precondition changed"):
        recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert journal.is_file()


@pytest.mark.parametrize("interrupt_at", ["intent", "manifest"])
def test_preparation_interrupt_is_recovered_from_durable_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt_at: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    intent = root / ".journal.json.intent"
    injected = False

    if interrupt_at == "intent":
        original_write = transaction._write_exclusive

        def interrupt_write(path: Path, content: bytes, mode: int) -> None:
            nonlocal injected
            original_write(path, content, mode)
            if not injected and path == intent:
                injected = True
                raise KeyboardInterrupt

        monkeypatch.setattr(transaction, "_write_exclusive", interrupt_write)
    else:
        original_link = transaction.os.link

        def interrupt_link(source: Path, destination: Path, **kwargs: object) -> None:
            nonlocal injected
            if not injected and destination == journal / "manifest.json":
                injected = True
                raise KeyboardInterrupt
            original_link(source, destination, **kwargs)

        monkeypatch.setattr(transaction.os, "link", interrupt_link)

    with pytest.raises(KeyboardInterrupt):
        execute_filesystem_transaction(
            journal,
            (FileMutation(target, b"post"),),
            allowed_roots=(root,),
        )

    assert injected
    assert target.read_bytes() == b"pre"
    assert not journal.exists()
    assert not intent.exists()
    assert len(list(root.glob(".journal.json.history-*-recovered-pre"))) == 1


def test_journal_substitution_is_rejected_before_entries_can_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"
    transaction._write_manifest(
        journal,
        state="prepared",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(b"pre"),
                "pre_mode": 0o644,
                "post_content": transaction._encoded(b"post"),
                "post_mode": 0o644,
            }
        ],
    )
    displaced = root / "operator-preserved-journal"
    original_load = transaction._load_json_unique_at
    injected = False

    def substitute(directory_fd: int, name: str, path: Path) -> object:
        nonlocal injected
        if not injected and name == "manifest.json":
            injected = True
            journal.rename(displaced)
            journal.mkdir()
            (journal / "operator-third-image").write_bytes(b"preserve-me")
        return original_load(directory_fd, name, path)

    monkeypatch.setattr(transaction, "_load_json_unique_at", substitute)

    with pytest.raises(FilesystemTransactionError, match="identity changed while loading"):
        transaction._load_journal(journal)

    assert injected
    assert target.read_bytes() == b"pre"
    assert displaced.is_dir()
    assert (journal / "operator-third-image").read_bytes() == b"preserve-me"


def test_cross_directory_transition_fsyncs_target_and_stage_parents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    observed: list[Path] = []
    original_fsync = transaction._fsync_directory

    def record(path: Path) -> None:
        observed.append(path)
        original_fsync(path)

    monkeypatch.setattr(transaction, "_fsync_directory", record)
    execute_filesystem_transaction(
        root / "journal.json",
        (FileMutation(target, b"post"),),
        allowed_roots=(root,),
    )

    assert root in observed
    assert root / ".hapax-transactions" in observed


@pytest.mark.parametrize("state", ["prepared", "committed"])
def test_v1_flat_journal_is_recovered_and_archived(
    tmp_path: Path,
    state: Literal["prepared", "committed"],
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"post")
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {
        "schema": transaction.TRANSACTION_SCHEMA_V1,
        "state": state,
        "entries": entries,
    }
    record = {
        **body,
        "manifest_sha256": hashlib.sha256(transaction._canonical_bytes(body)).hexdigest(),
    }
    journal = root / "journal.json"
    journal.write_bytes(transaction._canonical_bytes(record) + b"\n")
    journal.chmod(0o600)

    assert recover_filesystem_transaction(journal, allowed_roots=(root,))

    expected = b"pre" if state == "prepared" else b"post"
    assert target.read_bytes() == expected
    assert not journal.exists()
    assert (
        len(
            list(
                root.glob(
                    f".journal.json.history-v1-*-recovered-{'pre' if state == 'prepared' else 'post'}"
                )
            )
        )
        == 1
    )


def test_v1_recovery_refuses_concurrent_third_image_without_replacing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"post")
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "prepared", "entries": entries}
    record = {
        **body,
        "manifest_sha256": hashlib.sha256(transaction._canonical_bytes(body)).hexdigest(),
    }
    journal = root / "journal.json"
    journal.write_bytes(transaction._canonical_bytes(record) + b"\n")
    journal.chmod(0o600)
    original_execute = transaction._execute_filesystem_transaction_unlocked
    injected = False

    def race(
        conversion_journal: Path,
        mutations: tuple[FileMutation, ...] | list[FileMutation],
        *,
        allowed_roots: tuple[Path, ...],
    ) -> None:
        nonlocal injected
        injected = True
        target.write_bytes(b"operator-third-image")
        original_execute(conversion_journal, mutations, allowed_roots=allowed_roots)

    monkeypatch.setattr(transaction, "_execute_filesystem_transaction_unlocked", race)

    with pytest.raises(FilesystemTransactionError, match="preimage changed"):
        recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert injected
    assert target.read_bytes() == b"operator-third-image"
    assert journal.is_file()


def test_v1_retry_always_drains_interrupted_compatibility_journal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"post")
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "prepared", "entries": entries}
    digest = hashlib.sha256(transaction._canonical_bytes(body)).hexdigest()
    journal = root / "journal.json"
    journal.write_bytes(transaction._canonical_bytes({**body, "manifest_sha256": digest}) + b"\n")
    journal.chmod(0o600)

    compatibility = root / f".journal.json.v1-conversion-{digest[:16]}"
    transaction._write_manifest(
        compatibility,
        state="prepared",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(b"post"),
                "pre_mode": 0o644,
                "post_content": transaction._encoded(b"pre"),
                "post_mode": 0o644,
            }
        ],
    )
    compatibility_record = transaction._load_journal(compatibility)
    transaction._apply(
        compatibility_record.entries,
        image="post",
        accepted_current_images=("pre",),
        allowed_roots=(root,),
    )
    assert target.read_bytes() == b"pre"

    assert recover_filesystem_transaction(journal, allowed_roots=(root,))

    assert target.read_bytes() == b"pre"
    assert not journal.exists()
    assert not compatibility.exists()
    assert list(root.glob("..journal.json.v1-conversion-*.history-*-recovered-pre"))
    assert list(root.glob("..journal.json.v1-conversion-*.history-*-committed"))


def test_v1_recovery_locks_compatibility_before_target_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"post")
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "prepared", "entries": entries}
    digest = hashlib.sha256(transaction._canonical_bytes(body)).hexdigest()
    journal = root / "journal.json"
    journal.write_bytes(transaction._canonical_bytes({**body, "manifest_sha256": digest}) + b"\n")
    journal.chmod(0o600)
    compatibility = root / f".{journal.name}.v1-conversion-{digest[:16]}"
    original_transaction_lock = transaction._transaction_lock
    original_target_locks = transaction._target_locks
    held_transactions: list[Path] = []

    @contextmanager
    def track_transaction(path: Path):
        with original_transaction_lock(path):
            held_transactions.append(path)
            try:
                yield
            finally:
                held_transactions.remove(path)

    @contextmanager
    def require_compatibility_first(paths: list[Path] | tuple[Path, ...]):
        assert compatibility in held_transactions
        with original_target_locks(paths):
            yield

    monkeypatch.setattr(transaction, "_transaction_lock", track_transaction)
    monkeypatch.setattr(transaction, "_target_locks", require_compatibility_first)

    assert recover_filesystem_transaction(journal, allowed_roots=(root,))


def test_legacy_v1_supersession_retires_active_compatibility_journal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"post")
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "prepared", "entries": entries}
    digest = hashlib.sha256(transaction._canonical_bytes(body)).hexdigest()
    legacy = root / "cc-ownership-txn-task.json"
    legacy.write_bytes(transaction._canonical_bytes({**body, "manifest_sha256": digest}) + b"\n")
    legacy.chmod(0o600)
    compatibility = root / f".{legacy.name}.v1-conversion-{digest[:16]}"
    transaction._write_manifest(
        compatibility,
        state="prepared",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(b"post"),
                "pre_mode": 0o644,
                "post_content": transaction._encoded(b"pre"),
                "post_mode": 0o644,
            }
        ],
    )
    target.write_bytes(b"operator-third-image")

    transaction.migrate_legacy_filesystem_transactions(
        root / "cc-ownership-txn.json",
        (legacy,),
        allowed_roots=(root,),
    )

    assert target.read_bytes() == b"operator-third-image"
    assert not legacy.exists()
    assert not compatibility.exists()
    assert list(root.glob(f".{compatibility.name}.history-*-legacy-parent-superseded"))
    assert list(root.glob(f".{legacy.name}.history-v1-*-legacy-superseded-third-image"))


def test_legacy_v1_supersession_without_child_probes_all_filesystems(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"operator-third-image")
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "prepared", "entries": entries}
    digest = hashlib.sha256(transaction._canonical_bytes(body)).hexdigest()
    legacy = root / "cc-ownership-txn-task.json"
    legacy.write_bytes(transaction._canonical_bytes({**body, "manifest_sha256": digest}) + b"\n")
    legacy.chmod(0o600)
    compatibility = root / f".{legacy.name}.v1-conversion-{digest[:16]}"
    probes: list[tuple[Path, ...]] = []

    def refuse_target(paths: list[Path] | tuple[Path, ...]) -> None:
        probe = tuple(paths)
        probes.append(probe)
        if target in probe:
            raise FilesystemTransactionError("atomic no-replace support unavailable")

    monkeypatch.setattr(transaction, "_require_atomic_no_replace_support", refuse_target)

    with pytest.raises(FilesystemTransactionError, match="atomic no-replace support"):
        transaction.migrate_legacy_filesystem_transactions(
            root / "cc-ownership-txn.json",
            (legacy,),
            allowed_roots=(root,),
        )

    assert any(legacy in probe and compatibility in probe and target in probe for probe in probes)
    assert target.read_bytes() == b"operator-third-image"
    assert legacy.is_file()
    assert not compatibility.exists()
    assert not list(root.glob(f".{legacy.name}.history-v1-*-legacy-superseded*"))


def test_legacy_v1_supersession_holds_on_compatibility_auxiliary_third_image(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"post")
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "prepared", "entries": entries}
    digest = hashlib.sha256(transaction._canonical_bytes(body)).hexdigest()
    legacy = root / "cc-ownership-txn-task.json"
    legacy.write_bytes(transaction._canonical_bytes({**body, "manifest_sha256": digest}) + b"\n")
    legacy.chmod(0o600)
    compatibility = root / f".{legacy.name}.v1-conversion-{digest[:16]}"
    transaction._write_manifest(
        compatibility,
        state="prepared",
        entries=[
            {
                "path": str(target),
                "pre_content": transaction._encoded(b"post"),
                "pre_mode": 0o644,
                "post_content": transaction._encoded(b"pre"),
                "post_mode": 0o644,
            }
        ],
    )
    child = transaction._load_journal(compatibility)
    hold, _move = transaction._entry_auxiliary_paths(child.entries[0], (root,))
    hold.write_bytes(b"operator-child-auxiliary")
    target.write_bytes(b"operator-target-third-image")

    with pytest.raises(FilesystemTransactionError, match="auxiliary third-image conflict"):
        transaction.migrate_legacy_filesystem_transactions(
            root / "cc-ownership-txn.json",
            (legacy,),
            allowed_roots=(root,),
        )

    assert target.read_bytes() == b"operator-target-third-image"
    assert hold.read_bytes() == b"operator-child-auxiliary"
    assert legacy.is_file()
    assert compatibility.is_dir()


def test_legacy_v1_missing_target_holds_instead_of_evidencing_supersession(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "prepared", "entries": entries}
    digest = hashlib.sha256(transaction._canonical_bytes(body)).hexdigest()
    legacy = root / "cc-ownership-txn-task.json"
    legacy.write_bytes(transaction._canonical_bytes({**body, "manifest_sha256": digest}) + b"\n")
    legacy.chmod(0o600)

    with pytest.raises(FilesystemTransactionError, match="target image is missing"):
        transaction.migrate_legacy_filesystem_transactions(
            root / "cc-ownership-txn.json",
            (legacy,),
            allowed_roots=(root,),
        )

    assert legacy.is_file()
    assert not list(root.glob(f".{legacy.name}.history-v1-*-legacy-superseded*"))


def test_legacy_v1_checks_all_missing_targets_before_retiring_on_third_image(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = root / "first"
    second = root / "second"
    first.write_bytes(b"operator-third-image")
    entries = [
        {
            "path": str(first),
            "pre_content": transaction._encoded(b"first-pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"first-post"),
            "post_mode": 0o644,
        },
        {
            "path": str(second),
            "pre_content": transaction._encoded(b"second-pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"second-post"),
            "post_mode": 0o644,
        },
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "prepared", "entries": entries}
    digest = hashlib.sha256(transaction._canonical_bytes(body)).hexdigest()
    legacy = root / "cc-ownership-txn-task.json"
    legacy.write_bytes(transaction._canonical_bytes({**body, "manifest_sha256": digest}) + b"\n")
    legacy.chmod(0o600)

    with pytest.raises(FilesystemTransactionError, match="target image is missing"):
        transaction.migrate_legacy_filesystem_transactions(
            root / "cc-ownership-txn.json",
            (legacy,),
            allowed_roots=(root,),
        )

    assert first.read_bytes() == b"operator-third-image"
    assert not second.exists()
    assert legacy.is_file()
    assert not list(root.glob(f".{legacy.name}.history-v1-*-legacy-superseded*"))


def test_v1_archive_retry_accepts_existing_link_to_same_journal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"post")
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "committed", "entries": entries}
    digest = hashlib.sha256(transaction._canonical_bytes(body)).hexdigest()
    record = {**body, "manifest_sha256": digest}
    journal = root / "journal.json"
    journal.write_bytes(transaction._canonical_bytes(record) + b"\n")
    journal.chmod(0o600)
    archive = root / f".journal.json.history-v1-{digest[:16]}-recovered-post"
    archive.hardlink_to(journal)

    assert recover_filesystem_transaction(journal, allowed_roots=(root,))
    assert not journal.exists()
    assert archive.is_file()
    assert target.read_bytes() == b"post"


def test_v1_archive_preserves_successive_identical_journals(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"post")
    entries = [
        {
            "path": str(target),
            "pre_content": transaction._encoded(b"pre"),
            "pre_mode": 0o644,
            "post_content": transaction._encoded(b"post"),
            "post_mode": 0o644,
        }
    ]
    body = {"schema": transaction.TRANSACTION_SCHEMA_V1, "state": "committed", "entries": entries}
    digest = hashlib.sha256(transaction._canonical_bytes(body)).hexdigest()
    payload = transaction._canonical_bytes({**body, "manifest_sha256": digest}) + b"\n"
    journal = root / "journal.json"

    for _index in range(2):
        journal.write_bytes(payload)
        journal.chmod(0o600)
        assert recover_filesystem_transaction(journal, allowed_roots=(root,))

    archive = root / f".journal.json.history-v1-{digest[:16]}-recovered-post"
    assert archive.is_file()
    assert len(list(root.glob(f"{archive.name}.duplicate-*"))) == 1
    assert not journal.exists()
    assert target.read_bytes() == b"post"
