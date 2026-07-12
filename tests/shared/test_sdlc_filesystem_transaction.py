from __future__ import annotations

import errno
import hashlib
import json
from pathlib import Path
from typing import Literal

import pytest

from shared import sdlc_filesystem_transaction as transaction
from shared.sdlc_filesystem_transaction import (
    FileMutation,
    FilesystemTransactionError,
    execute_filesystem_transaction,
    recover_filesystem_transaction,
)


def _load_manifest(journal_path: Path) -> tuple[str, list[transaction.TransactionEntry]]:
    record = transaction._load_journal(journal_path)
    return record.state, record.entries


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
        if not injected and flags == transaction._RENAME_NOREPLACE:
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


def test_nfs_fallback_updates_existing_file_and_archives_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"pre")
    journal = root / "journal.json"

    def unsupported(_source: Path, _destination: Path, _flags: int) -> None:
        raise OSError(errno.EINVAL, "NFS rejects rename flags")

    monkeypatch.setattr(transaction, "_renameat2", unsupported)

    execute_filesystem_transaction(
        journal,
        (FileMutation(target, b"post", expected_sha256=hashlib.sha256(b"pre").hexdigest()),),
        allowed_roots=(root,),
    )

    assert target.read_bytes() == b"post"
    assert not journal.exists()
    assert len(list(root.glob(".journal.json.history-*-committed"))) == 1
    assert not list((root / ".hapax-transactions").glob("*.hold"))
    assert not list((root / ".hapax-transactions").glob("*.move"))


def test_nfs_fallback_recovers_interrupted_portable_transition(
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

    def unsupported(_source: Path, _destination: Path, _flags: int) -> None:
        raise OSError(errno.EINVAL, "NFS rejects rename flags")

    monkeypatch.setattr(transaction, "_renameat2", unsupported)
    original_link = transaction.os.link
    calls = 0

    def interrupt(source: Path, destination: Path, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        original_link(source, destination, **kwargs)

    monkeypatch.setattr(transaction.os, "link", interrupt)
    with pytest.raises(KeyboardInterrupt):
        transaction._transition_entry(prepared[0], image="post", allowed_roots=(root,))

    monkeypatch.setattr(transaction.os, "link", original_link)
    assert recover_filesystem_transaction(journal, allowed_roots=(root,))
    assert target.read_bytes() == b"pre"
    assert not journal.exists()


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
