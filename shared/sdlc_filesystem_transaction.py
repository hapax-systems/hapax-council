"""Crash-recoverable, preserving multi-file transactions for SDLC ownership state."""

from __future__ import annotations

import base64
import ctypes
import errno
import hashlib
import json
import os
import stat
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TRANSACTION_SCHEMA_V1 = "hapax.sdlc-filesystem-transaction.v1"
TRANSACTION_SCHEMA_V2 = "hapax.sdlc-filesystem-transaction.v2"
TRANSACTION_SCHEMA = "hapax.sdlc-filesystem-transaction.v3"
COMMIT_MARKER_SCHEMA = "hapax.sdlc-filesystem-transaction-commit.v1"
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2

ImageName = Literal["pre", "post"]
TransactionEntry = dict[str, object]


class FilesystemTransactionError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileMutation:
    path: Path
    content: bytes | None
    mode: int | None = None
    expected_sha256: str | None = None
    expected_exists: bool | None = None


@dataclass(frozen=True)
class _JournalRecord:
    state: Literal["prepared", "committed"]
    transaction_id: str
    manifest_sha256: str
    entries: list[TransactionEntry]
    device: int
    inode: int


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_exclusive(path: Path, content: bytes, mode: int) -> None:
    """Create one durable file without replacing any pathname occupant."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, mode)
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction exclusive create failed: {path}") from exc
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # The path is deliberately retained on failure. Removing it could erase
        # a non-cooperating writer that replaced it after creation.
        raise
    _fsync_directory(path.parent)


def _renameat2(source: Path, destination: Path, flags: int) -> None:
    """Perform one preserving Linux rename transition or fail closed."""

    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as exc:
        raise OSError(errno.ENOSYS, "renameat2 is unavailable") from exc
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        flags,
    )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(source), str(destination))


def _allowed(path: Path, roots: Sequence[Path]) -> Path:
    absolute = path.expanduser().absolute()
    try:
        parent = absolute.parent.resolve(strict=True)
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction parent unavailable: {path}") from exc
    for root in roots:
        try:
            resolved_root = root.expanduser().resolve(strict=True)
        except OSError as exc:
            raise FilesystemTransactionError(f"transaction root unavailable: {root}") from exc
        if parent == resolved_root or parent.is_relative_to(resolved_root):
            return parent / absolute.name
    raise FilesystemTransactionError(f"transaction path outside allowed roots: {path}")


def _snapshot(path: Path) -> tuple[bytes | None, int | None]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction image unreadable: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FilesystemTransactionError(f"transaction path is not a regular file: {path}")
    try:
        return path.read_bytes(), stat.S_IMODE(metadata.st_mode)
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction image unreadable: {path}") from exc


def _encoded(content: bytes | None) -> str | None:
    return base64.b64encode(content).decode("ascii") if content is not None else None


def _decoded(content: object, *, field: str) -> bytes | None:
    if content is None:
        return None
    if not isinstance(content, str):
        raise FilesystemTransactionError(f"transaction {field} is malformed")
    try:
        return base64.b64decode(content, validate=True)
    except (ValueError, TypeError) as exc:
        raise FilesystemTransactionError(f"transaction {field} is malformed") from exc


def _entry_path(entry: TransactionEntry, allowed_roots: Sequence[Path]) -> Path:
    if set(entry) != {
        "path",
        "stage_path",
        "hold_path",
        "move_path",
        "pre_content",
        "pre_mode",
        "post_content",
        "post_mode",
    }:
        raise FilesystemTransactionError("transaction entry schema mismatch")
    raw_path = entry["path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise FilesystemTransactionError("transaction entry path malformed")
    return _allowed(Path(raw_path), allowed_roots)


def _entry_stage_path(entry: TransactionEntry, allowed_roots: Sequence[Path]) -> Path:
    raw_path = entry["stage_path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise FilesystemTransactionError("transaction stage path malformed")
    return _allowed(Path(raw_path), allowed_roots)


def _entry_auxiliary_paths(
    entry: TransactionEntry,
    allowed_roots: Sequence[Path],
) -> tuple[Path, Path]:
    output: list[Path] = []
    for field in ("hold_path", "move_path"):
        raw_path = entry[field]
        if not isinstance(raw_path, str) or not raw_path:
            raise FilesystemTransactionError(f"transaction {field} malformed")
        output.append(_allowed(Path(raw_path), allowed_roots))
    return output[0], output[1]


def _entry_image(entry: TransactionEntry, image: ImageName) -> tuple[bytes | None, int | None]:
    content = _decoded(entry[f"{image}_content"], field=f"{image}_content")
    mode_value = entry[f"{image}_mode"]
    if content is None:
        if mode_value is not None:
            raise FilesystemTransactionError("absent transaction image has a mode")
        return None, None
    if not isinstance(mode_value, int) or isinstance(mode_value, bool):
        raise FilesystemTransactionError("transaction mode malformed")
    return content, mode_value


def _pair_state(
    entry: TransactionEntry,
    *,
    allowed_roots: Sequence[Path],
) -> Literal["pre", "post", "both"]:
    path = _entry_path(entry, allowed_roots)
    stage = _entry_stage_path(entry, allowed_roots)
    auxiliaries = _entry_auxiliary_paths(entry, allowed_roots)
    if not (
        path.parent == stage.parent.parent
        and stage.parent.name == ".hapax-transactions"
        and path.parent.stat().st_dev == stage.parent.stat().st_dev
        and all(auxiliary.parent == stage.parent for auxiliary in auxiliaries)
        and len({path, stage, *auxiliaries}) == 4
    ):
        raise FilesystemTransactionError("transaction stage is not on the target filesystem")
    if any(_snapshot(auxiliary)[0] is not None for auxiliary in auxiliaries):
        raise FilesystemTransactionError("transaction has an interrupted portable transition")
    actual = (_snapshot(path), _snapshot(stage))
    pre = _entry_image(entry, "pre")
    post = _entry_image(entry, "post")
    pre_pair = (pre, post)
    post_pair = (post, pre)
    matches_pre = actual == pre_pair
    matches_post = actual == post_pair
    if matches_pre and matches_post:
        return "both"
    if matches_pre:
        return "pre"
    if matches_post:
        return "post"
    raise FilesystemTransactionError(
        "transaction third-image conflict; all images and journal were preserved: "
        f"{path} stage={stage}"
    )


def _portable_paths(
    entry: TransactionEntry,
    allowed_roots: Sequence[Path],
) -> tuple[Path, Path, Path, Path]:
    path = _entry_path(entry, allowed_roots)
    stage = _entry_stage_path(entry, allowed_roots)
    hold, move = _entry_auxiliary_paths(entry, allowed_roots)
    if not (
        path.parent == stage.parent.parent
        and stage.parent.name == ".hapax-transactions"
        and all(auxiliary.parent == stage.parent for auxiliary in (hold, move))
        and path.parent.stat().st_dev == stage.parent.stat().st_dev
        and len({path, stage, hold, move}) == 4
    ):
        raise FilesystemTransactionError("transaction stage is not on the target filesystem")
    return path, stage, hold, move


def _portable_states(
    entry: TransactionEntry,
    *,
    allowed_roots: Sequence[Path],
) -> dict[Path, ImageName | Literal["absent"]]:
    pre = _entry_image(entry, "pre")
    post = _entry_image(entry, "post")
    states: dict[Path, ImageName | Literal["absent"]] = {}
    for candidate in _portable_paths(entry, allowed_roots):
        actual = _snapshot(candidate)
        if actual == (None, None):
            states[candidate] = "absent"
        elif actual == pre:
            states[candidate] = "pre"
        elif actual == post:
            states[candidate] = "post"
        else:
            raise FilesystemTransactionError(
                "transaction third-image conflict; all images and journal were preserved: "
                f"{candidate}"
            )
    for image, expected in (("pre", pre), ("post", post)):
        if expected[0] is not None and image not in states.values():
            raise FilesystemTransactionError(
                f"transaction recorded {image} image disappeared; journal was preserved"
            )
    return states


def _portable_free_auxiliary(
    entry: TransactionEntry,
    *,
    allowed_roots: Sequence[Path],
) -> Path:
    states = _portable_states(entry, allowed_roots=allowed_roots)
    _path, _stage, hold, move = _portable_paths(entry, allowed_roots)
    for auxiliary in (hold, move):
        if states[auxiliary] == "absent":
            return auxiliary
    for auxiliary in (hold, move):
        image = states[auxiliary]
        if image != "absent" and sum(value == image for value in states.values()) > 1:
            auxiliary.unlink()
            _fsync_directory(auxiliary.parent)
            if _snapshot(auxiliary) != (None, None):
                raise FilesystemTransactionError(
                    f"transaction auxiliary cleanup incomplete: {auxiliary}"
                )
            return auxiliary
    raise FilesystemTransactionError(
        "transaction portable transition has no safe spare pathname; all images were preserved"
    )


def _portable_set_path(
    entry: TransactionEntry,
    destination: Path,
    desired: ImageName | Literal["absent"],
    *,
    allowed_roots: Sequence[Path],
) -> None:
    states = _portable_states(entry, allowed_roots=allowed_roots)
    if states[destination] == desired:
        return
    if states[destination] != "absent":
        displaced = _portable_free_auxiliary(entry, allowed_roots=allowed_roots)
        before = _snapshot(destination)
        try:
            os.rename(destination, displaced)
        except OSError as exc:
            raise FilesystemTransactionError(
                f"transaction portable displacement failed: {destination}"
            ) from exc
        _fsync_directory(destination.parent)
        if displaced.parent != destination.parent:
            _fsync_directory(displaced.parent)
        if _snapshot(displaced) != before:
            raise FilesystemTransactionError(
                "transaction third-image conflict during portable displacement; "
                f"all images were preserved: {displaced}"
            )
        states = _portable_states(entry, allowed_roots=allowed_roots)
        if states[destination] != "absent":
            raise FilesystemTransactionError(
                f"transaction portable destination was concurrently occupied: {destination}"
            )
    if desired == "absent":
        return
    states = _portable_states(entry, allowed_roots=allowed_roots)
    source = next(
        (candidate for candidate, state in states.items() if state == desired),
        None,
    )
    if source is None:
        raise FilesystemTransactionError(
            f"transaction portable source image disappeared: {desired}"
        )
    try:
        os.link(source, destination, follow_symlinks=False)
    except OSError as exc:
        try:
            _portable_states(entry, allowed_roots=allowed_roots)
        except FilesystemTransactionError:
            raise
        raise FilesystemTransactionError(
            f"transaction portable no-clobber install failed: {destination}"
        ) from exc
    _fsync_directory(destination.parent)
    if _portable_states(entry, allowed_roots=allowed_roots)[destination] != desired:
        raise FilesystemTransactionError(f"transaction portable install incomplete: {destination}")


def _portable_transition_entry(
    entry: TransactionEntry,
    *,
    image: ImageName,
    allowed_roots: Sequence[Path],
) -> None:
    path, stage, hold, move = _portable_paths(entry, allowed_roots)
    opposite: ImageName = "post" if image == "pre" else "pre"
    desired_path: ImageName | Literal["absent"] = (
        image if _entry_image(entry, image)[0] is not None else "absent"
    )
    desired_stage: ImageName | Literal["absent"] = (
        opposite if _entry_image(entry, opposite)[0] is not None else "absent"
    )
    _portable_states(entry, allowed_roots=allowed_roots)
    _portable_set_path(entry, path, desired_path, allowed_roots=allowed_roots)
    _portable_set_path(entry, stage, desired_stage, allowed_roots=allowed_roots)
    states = _portable_states(entry, allowed_roots=allowed_roots)
    if states[path] != desired_path or states[stage] != desired_stage:
        raise FilesystemTransactionError(f"transaction portable transition incomplete: {path}")
    for auxiliary in (hold, move):
        if _snapshot(auxiliary)[0] is not None:
            auxiliary.unlink()
            _fsync_directory(auxiliary.parent)
    observed = _pair_state(entry, allowed_roots=allowed_roots)
    if observed not in {image, "both"}:
        raise FilesystemTransactionError(f"transaction portable transition incomplete: {path}")


def _validate_current_images(
    entries: list[TransactionEntry],
    *,
    accepted_images: Sequence[ImageName],
    allowed_roots: Sequence[Path],
    allow_portable_intermediate: bool = False,
) -> None:
    seen: set[Path] = set()
    for entry in entries:
        path = _entry_path(entry, allowed_roots)
        stage = _entry_stage_path(entry, allowed_roots)
        if path in seen or stage in seen or path == stage:
            raise FilesystemTransactionError(f"duplicate transaction path: {path}")
        auxiliaries = _entry_auxiliary_paths(entry, allowed_roots)
        if any(candidate in seen for candidate in auxiliaries):
            raise FilesystemTransactionError(f"duplicate transaction path: {path}")
        seen.update((path, stage, *auxiliaries))
        try:
            state = _pair_state(entry, allowed_roots=allowed_roots)
        except FilesystemTransactionError as exc:
            if not allow_portable_intermediate:
                raise
            _portable_states(entry, allowed_roots=allowed_roots)
            if set(accepted_images) != {"pre", "post"}:
                raise exc
            continue
        if state != "both" and state not in accepted_images:
            raise FilesystemTransactionError(
                f"transaction image state {state} is not accepted for {path}"
            )


def _transition_entry(
    entry: TransactionEntry,
    *,
    image: ImageName,
    allowed_roots: Sequence[Path],
) -> None:
    try:
        state = _pair_state(entry, allowed_roots=allowed_roots)
    except FilesystemTransactionError:
        _portable_transition_entry(entry, image=image, allowed_roots=allowed_roots)
        return
    if state in {image, "both"}:
        return
    path = _entry_path(entry, allowed_roots)
    stage = _entry_stage_path(entry, allowed_roots)
    pre = _entry_image(entry, "pre")
    post = _entry_image(entry, "post")
    try:
        if pre[0] is not None and post[0] is not None:
            _renameat2(path, stage, _RENAME_EXCHANGE)
        elif image == "post":
            source, destination = (stage, path) if post[0] is not None else (path, stage)
            _renameat2(source, destination, _RENAME_NOREPLACE)
        else:
            source, destination = (stage, path) if pre[0] is not None else (path, stage)
            _renameat2(source, destination, _RENAME_NOREPLACE)
    except OSError as exc:
        if exc.errno in {errno.ENOSYS, errno.EINVAL, errno.EXDEV, errno.EOPNOTSUPP}:
            _portable_transition_entry(entry, image=image, allowed_roots=allowed_roots)
            return
        # A competing writer may have completed the same transition. Re-read the
        # preserving pair before deciding; no fallback replace/unlink is allowed.
        try:
            observed = _pair_state(entry, allowed_roots=allowed_roots)
        except FilesystemTransactionError:
            raise
        if observed not in {image, "both"}:
            raise FilesystemTransactionError(
                f"preserving rename transition failed: {path}"
            ) from exc
    _fsync_directory(path.parent)
    observed = _pair_state(entry, allowed_roots=allowed_roots)
    if observed not in {image, "both"}:
        raise FilesystemTransactionError(f"transaction transition incomplete: {path}")


def _apply(
    entries: list[TransactionEntry],
    *,
    image: ImageName,
    accepted_current_images: Sequence[ImageName],
    allowed_roots: Sequence[Path],
) -> None:
    # Validate the whole set before the first transition, then use preserving
    # rename primitives whose displaced image remains at the recorded stage path.
    _validate_current_images(
        entries,
        accepted_images=accepted_current_images,
        allowed_roots=allowed_roots,
        allow_portable_intermediate=set(accepted_current_images) == {"pre", "post"},
    )
    for entry in entries:
        _transition_entry(entry, image=image, allowed_roots=allowed_roots)
    _validate_current_images(entries, accepted_images=(image,), allowed_roots=allowed_roots)


def _manifest_body(
    *,
    transaction_id: str,
    entries: list[TransactionEntry],
    schema: str = TRANSACTION_SCHEMA,
) -> dict[str, object]:
    return {
        "schema": schema,
        "transaction_id": transaction_id,
        "entries": entries,
    }


def _manifest_path(journal_path: Path) -> Path:
    return journal_path / "manifest.json"


def _commit_path(journal_path: Path) -> Path:
    return journal_path / "committed.json"


def _new_entry_identity(parent: Path) -> tuple[int, int]:
    """Observe server-side ownership assigned to a new private entry."""

    probe = parent / f".hapax-owner-probe-{uuid.uuid4().hex}"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            probe,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise FilesystemTransactionError(f"transaction ownership probe is unsafe: {probe}")
        return metadata.st_uid, metadata.st_gid
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction ownership probe failed: {parent}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
            try:
                probe.unlink()
            except OSError as exc:
                raise FilesystemTransactionError(
                    f"transaction ownership probe cleanup failed: {probe}"
                ) from exc
            _fsync_directory(parent)


def _ensure_stage_directory(path: Path) -> Path:
    stage_directory = path.parent / ".hapax-transactions"
    try:
        stage_directory.mkdir(mode=0o700)
        _fsync_directory(path.parent)
    except FileExistsError:
        pass
    try:
        metadata = stage_directory.lstat()
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction stage directory unavailable: {stage_directory}"
        ) from exc
    expected_uid, expected_gid = _new_entry_identity(path.parent)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != (expected_uid, expected_gid)
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise FilesystemTransactionError(
            f"transaction stage directory is unsafe: {stage_directory}"
        )
    return stage_directory


def _prepare_journal(
    journal_path: Path,
    entries: list[TransactionEntry],
    *,
    allowed_roots: Sequence[Path],
    transaction_id: str | None = None,
) -> _JournalRecord:
    transaction_id = transaction_id or uuid.uuid4().hex
    if len(transaction_id) != 32 or any(char not in "0123456789abcdef" for char in transaction_id):
        raise FilesystemTransactionError("transaction id malformed")
    prepared: list[TransactionEntry] = []
    seen: set[Path] = set()
    for index, entry in enumerate(entries):
        raw_path = entry.get("path")
        if not isinstance(raw_path, str):
            raise FilesystemTransactionError("transaction entry path malformed")
        path = _allowed(Path(raw_path), allowed_roots)
        if path in seen:
            raise FilesystemTransactionError(f"duplicate transaction path: {path}")
        seen.add(path)
        stage_directory = _ensure_stage_directory(path)
        stage = _allowed(stage_directory / f"{transaction_id}-{index}.stage", allowed_roots)
        hold = _allowed(stage_directory / f"{transaction_id}-{index}.hold", allowed_roots)
        move = _allowed(stage_directory / f"{transaction_id}-{index}.move", allowed_roots)
        for auxiliary in (stage, hold, move):
            if auxiliary in seen or auxiliary.exists() or auxiliary.is_symlink():
                raise FilesystemTransactionError(
                    f"transaction stage path already exists: {auxiliary}"
                )
            seen.add(auxiliary)
        prepared_entry = dict(entry)
        prepared_entry["stage_path"] = str(stage)
        prepared_entry["hold_path"] = str(hold)
        prepared_entry["move_path"] = str(move)
        _entry_path(prepared_entry, allowed_roots)
        _entry_stage_path(prepared_entry, allowed_roots)
        post_content, post_mode = _entry_image(prepared_entry, "post")
        if post_content is not None:
            assert post_mode is not None
            _write_exclusive(stage, post_content, post_mode)
        prepared.append(prepared_entry)

    try:
        journal_path.mkdir(mode=0o700)
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal create failed without replacement: {journal_path}"
        ) from exc
    _fsync_directory(journal_path.parent)
    body = _manifest_body(transaction_id=transaction_id, entries=prepared)
    manifest_sha256 = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    record = {**body, "manifest_sha256": manifest_sha256}
    _write_exclusive(_manifest_path(journal_path), _canonical_bytes(record) + b"\n", 0o600)
    metadata = journal_path.lstat()
    journal_record = _JournalRecord(
        state="prepared",
        transaction_id=transaction_id,
        manifest_sha256=manifest_sha256,
        entries=prepared,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )
    _validate_current_images(prepared, accepted_images=("pre",), allowed_roots=allowed_roots)
    return journal_record


def _commit_marker_bytes(record: _JournalRecord) -> bytes:
    return (
        _canonical_bytes(
            {
                "schema": COMMIT_MARKER_SCHEMA,
                "transaction_id": record.transaction_id,
                "manifest_sha256": record.manifest_sha256,
            }
        )
        + b"\n"
    )


def _mark_committed(journal_path: Path, record: _JournalRecord) -> None:
    _write_exclusive(_commit_path(journal_path), _commit_marker_bytes(record), 0o600)
    _fsync_directory(journal_path)


def _load_json_unique(path: Path) -> object:
    def unique_pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in values:
            if key in output:
                raise FilesystemTransactionError(f"transaction journal duplicate key: {key}")
            output[key] = value
        return output

    raw, _mode = _snapshot(path)
    if raw is None:
        raise FilesystemTransactionError(f"transaction journal member disappeared: {path}")
    try:
        return json.loads(raw.decode("ascii"), object_pairs_hook=unique_pairs)
    except FilesystemTransactionError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FilesystemTransactionError(f"transaction journal malformed: {path}") from exc


def _load_v1_journal(
    journal_path: Path,
) -> tuple[Literal["prepared", "committed"], list[TransactionEntry], str]:
    value = _load_json_unique(journal_path)
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "state",
        "entries",
        "manifest_sha256",
    }:
        raise FilesystemTransactionError(f"transaction journal schema mismatch: {journal_path}")
    state = value["state"]
    entries = value["entries"]
    if (
        value["schema"] != TRANSACTION_SCHEMA_V1
        or state not in {"prepared", "committed"}
        or not isinstance(entries, list)
        or not all(isinstance(entry, dict) for entry in entries)
    ):
        raise FilesystemTransactionError(f"transaction journal schema mismatch: {journal_path}")
    for entry in entries:
        if set(entry) != {
            "path",
            "pre_content",
            "pre_mode",
            "post_content",
            "post_mode",
        }:
            raise FilesystemTransactionError(f"transaction journal schema mismatch: {journal_path}")
        _entry_image(entry, "pre")
        _entry_image(entry, "post")
    body = {"schema": TRANSACTION_SCHEMA_V1, "state": state, "entries": entries}
    manifest_sha256 = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    if value["manifest_sha256"] != manifest_sha256:
        raise FilesystemTransactionError(f"transaction journal hash mismatch: {journal_path}")
    return state, entries, manifest_sha256


def _replace_compatibility_image(
    path: Path,
    content: bytes | None,
    mode: int | None,
) -> None:
    if content is None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        _fsync_directory(path.parent)
        return
    assert mode is not None
    temporary = path.parent / f".{path.name}.v1-recovery-{uuid.uuid4().hex}"
    _write_exclusive(temporary, content, mode)
    try:
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        # Retain the temporary image on failure; recovery can safely be retried.
        raise


def _recover_v1_journal(
    journal_path: Path,
    *,
    allowed_roots: Sequence[Path],
) -> None:
    metadata = journal_path.lstat()
    expected_uid, expected_gid = _new_entry_identity(journal_path.parent)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != (expected_uid, expected_gid)
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise FilesystemTransactionError(f"transaction journal path is unsafe: {journal_path}")
    state, entries, manifest_sha256 = _load_v1_journal(journal_path)
    image: ImageName = "post" if state == "committed" else "pre"
    resolved: list[tuple[Path, TransactionEntry]] = []
    seen: set[Path] = set()
    for entry in entries:
        raw_path = entry["path"]
        if not isinstance(raw_path, str) or not raw_path:
            raise FilesystemTransactionError("transaction entry path malformed")
        path = _allowed(Path(raw_path), allowed_roots)
        if path in seen:
            raise FilesystemTransactionError(f"duplicate transaction path: {path}")
        seen.add(path)
        actual = _snapshot(path)
        if actual not in {_entry_image(entry, "pre"), _entry_image(entry, "post")}:
            raise FilesystemTransactionError(
                f"transaction third-image conflict; v1 journal and image were preserved: {path}"
            )
        resolved.append((path, entry))
    for path, entry in resolved:
        actual = _snapshot(path)
        if actual not in {_entry_image(entry, "pre"), _entry_image(entry, "post")}:
            raise FilesystemTransactionError(
                f"transaction third-image conflict; v1 journal and image were preserved: {path}"
            )
        content, mode = _entry_image(entry, image)
        if actual != (content, mode):
            _replace_compatibility_image(path, content, mode)
    archive = journal_path.with_name(
        f".{journal_path.name}.history-v1-{manifest_sha256[:16]}-recovered-{image}"
    )
    try:
        os.link(journal_path, archive, follow_symlinks=False)
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction v1 journal archive failed without replacement: {journal_path}"
        ) from exc
    _fsync_directory(journal_path.parent)
    source_metadata = journal_path.lstat()
    archive_metadata = archive.lstat()
    if (
        source_metadata.st_dev != metadata.st_dev
        or source_metadata.st_ino != metadata.st_ino
        or archive_metadata.st_dev != metadata.st_dev
        or archive_metadata.st_ino != metadata.st_ino
    ):
        raise FilesystemTransactionError(
            f"transaction v1 journal identity changed; all images were preserved: {journal_path}"
        )
    journal_path.unlink()
    _fsync_directory(journal_path.parent)


def _load_journal(journal_path: Path) -> _JournalRecord:
    try:
        metadata = journal_path.lstat()
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal unavailable: {journal_path}"
        ) from exc
    expected_uid, expected_gid = _new_entry_identity(journal_path.parent)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_uid, metadata.st_gid) != (expected_uid, expected_gid)
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise FilesystemTransactionError(f"transaction journal path is unsafe: {journal_path}")
    value = _load_json_unique(_manifest_path(journal_path))
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "transaction_id",
        "entries",
        "manifest_sha256",
    }:
        raise FilesystemTransactionError(f"transaction journal schema mismatch: {journal_path}")
    schema = value["schema"]
    transaction_id = value["transaction_id"]
    entries = value["entries"]
    if (
        schema not in {TRANSACTION_SCHEMA_V2, TRANSACTION_SCHEMA}
        or not isinstance(transaction_id, str)
        or len(transaction_id) != 32
        or any(char not in "0123456789abcdef" for char in transaction_id)
        or not isinstance(entries, list)
        or not all(isinstance(entry, dict) for entry in entries)
    ):
        raise FilesystemTransactionError(f"transaction journal schema mismatch: {journal_path}")
    body = _manifest_body(transaction_id=transaction_id, entries=entries, schema=str(schema))
    manifest_sha256 = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    if value["manifest_sha256"] != manifest_sha256:
        raise FilesystemTransactionError(f"transaction journal hash mismatch: {journal_path}")
    state: Literal["prepared", "committed"] = "prepared"
    commit = _commit_path(journal_path)
    if commit.exists() or commit.is_symlink():
        marker = _load_json_unique(commit)
        expected = {
            "schema": COMMIT_MARKER_SCHEMA,
            "transaction_id": transaction_id,
            "manifest_sha256": manifest_sha256,
        }
        if marker != expected:
            raise FilesystemTransactionError(f"transaction commit marker mismatch: {journal_path}")
        state = "committed"
    normalized_entries: list[TransactionEntry] = []
    for index, raw_entry in enumerate(entries):
        normalized = dict(raw_entry)
        if schema == TRANSACTION_SCHEMA_V2:
            if set(normalized) != {
                "path",
                "stage_path",
                "pre_content",
                "pre_mode",
                "post_content",
                "post_mode",
            }:
                raise FilesystemTransactionError(
                    f"transaction journal schema mismatch: {journal_path}"
                )
            stage = Path(str(normalized["stage_path"]))
            normalized["hold_path"] = str(stage.with_name(f"{transaction_id}-{index}.hold"))
            normalized["move_path"] = str(stage.with_name(f"{transaction_id}-{index}.move"))
        normalized_entries.append(normalized)
    return _JournalRecord(
        state=state,
        transaction_id=transaction_id,
        manifest_sha256=manifest_sha256,
        entries=normalized_entries,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _archive_journal(journal_path: Path, record: _JournalRecord, *, outcome: str) -> Path:
    archive = journal_path.with_name(
        f".{journal_path.name}.history-{record.transaction_id}-{outcome}"
    )
    try:
        _renameat2(journal_path, archive, _RENAME_NOREPLACE)
    except OSError as exc:
        if exc.errno not in {errno.ENOSYS, errno.EINVAL, errno.EXDEV, errno.EOPNOTSUPP}:
            raise FilesystemTransactionError(
                f"transaction journal archive failed without replacement: {journal_path}"
            ) from exc
        if archive.exists() or archive.is_symlink():
            raise FilesystemTransactionError(
                f"transaction journal archive already exists: {archive}"
            ) from exc
        try:
            os.rename(journal_path, archive)
        except OSError as fallback_exc:
            raise FilesystemTransactionError(
                f"transaction journal portable archive failed: {journal_path}"
            ) from fallback_exc
    _fsync_directory(journal_path.parent)
    try:
        metadata = archive.lstat()
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction archive disappeared: {archive}") from exc
    if metadata.st_dev != record.device or metadata.st_ino != record.inode:
        raise FilesystemTransactionError(
            f"transaction journal third-image conflict preserved at {archive}"
        )
    archived = _load_journal(archive)
    if (
        archived.transaction_id != record.transaction_id
        or archived.manifest_sha256 != record.manifest_sha256
        or archived.state != record.state
    ):
        raise FilesystemTransactionError(
            f"transaction archived journal identity mismatch preserved at {archive}"
        )
    return archive


def _write_manifest(
    journal_path: Path,
    *,
    state: Literal["prepared", "committed"],
    entries: list[TransactionEntry],
) -> None:
    roots = tuple(
        dict.fromkeys(
            [journal_path.parent, *(Path(str(entry["path"])).parent for entry in entries)]
        )
    )
    record = _prepare_journal(journal_path, entries, allowed_roots=roots)
    if state == "committed":
        _mark_committed(journal_path, record)


def recover_filesystem_transaction(
    journal_path: Path,
    *,
    allowed_roots: Sequence[Path],
) -> bool:
    """Recover a prior interrupted transaction without deleting any image."""

    try:
        metadata = journal_path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal unavailable: {journal_path}"
        ) from exc
    _allowed(journal_path, allowed_roots)
    if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        _recover_v1_journal(journal_path, allowed_roots=allowed_roots)
        return True
    record = _load_journal(journal_path)
    image: ImageName = "post" if record.state == "committed" else "pre"
    _apply(
        record.entries,
        image=image,
        accepted_current_images=("pre", "post"),
        allowed_roots=allowed_roots,
    )
    _archive_journal(journal_path, record, outcome=f"recovered-{image}")
    return True


def execute_filesystem_transaction(
    journal_path: Path,
    mutations: Sequence[FileMutation],
    *,
    allowed_roots: Sequence[Path],
) -> None:
    """Apply exact postimages while preserving every displaced pathname image."""

    if not mutations:
        raise FilesystemTransactionError("transaction requires at least one mutation")
    recover_filesystem_transaction(journal_path, allowed_roots=allowed_roots)
    _allowed(journal_path, allowed_roots)

    entries: list[TransactionEntry] = []
    seen: set[Path] = set()
    for mutation in mutations:
        path = _allowed(mutation.path, allowed_roots)
        if path in seen:
            raise FilesystemTransactionError(f"duplicate transaction path: {path}")
        seen.add(path)
        pre_content, pre_mode = _snapshot(path)
        if mutation.expected_exists is not None and (pre_content is not None) != (
            mutation.expected_exists
        ):
            raise FilesystemTransactionError(f"transaction existence precondition changed: {path}")
        if mutation.expected_sha256 is not None and (
            pre_content is None
            or hashlib.sha256(pre_content).hexdigest() != mutation.expected_sha256
        ):
            raise FilesystemTransactionError(f"transaction preimage changed: {path}")
        post_mode = mutation.mode
        if mutation.content is not None and post_mode is None:
            post_mode = pre_mode if pre_mode is not None else 0o600
        if mutation.content is None:
            post_mode = None
        entries.append(
            {
                "path": str(path),
                "pre_content": _encoded(pre_content),
                "pre_mode": pre_mode,
                "post_content": _encoded(mutation.content),
                "post_mode": post_mode,
            }
        )

    record = _prepare_journal(journal_path, entries, allowed_roots=allowed_roots)
    try:
        _apply(
            record.entries,
            image="post",
            accepted_current_images=("pre",),
            allowed_roots=allowed_roots,
        )
    except BaseException:
        recover_filesystem_transaction(journal_path, allowed_roots=allowed_roots)
        raise
    try:
        _mark_committed(journal_path, record)
    except BaseException:
        recover_filesystem_transaction(journal_path, allowed_roots=allowed_roots)
        raise
    committed = _load_journal(journal_path)
    _archive_journal(journal_path, committed, outcome="committed")
