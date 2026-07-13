"""Crash-recoverable, preserving multi-file transactions for SDLC ownership state."""

from __future__ import annotations

import base64
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import stat
import uuid
from collections.abc import Sequence
from contextlib import contextmanager, nullcontext
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
    expected_mode: int | None = None


@dataclass(frozen=True)
class _JournalRecord:
    state: Literal["prepared", "committed"]
    transaction_id: str
    manifest_sha256: str
    entries: list[TransactionEntry]
    device: int
    inode: int


@dataclass(frozen=True)
class _V1JournalRecord:
    state: Literal["prepared", "committed"]
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
    """Publish one complete durable file without exposing a partial final name."""

    temporary = path.parent / f".hapax-write-{uuid.uuid4().hex}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        fd = os.open(temporary, flags, mode)
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction temporary create failed: {temporary}"
        ) from exc
    try:
        os.fchmod(fd, mode)
        offset = 0
        while offset < len(content):
            written = os.write(fd, content[offset:])
            if written <= 0:
                raise OSError(errno.EIO, "transaction temporary write made no progress")
            offset += written
        os.fsync(fd)
    except BaseException:
        # A failed temporary is retained for diagnosis. The authoritative final
        # pathname was never published and therefore cannot be mistaken as valid.
        raise
    finally:
        os.close(fd)
    _fsync_directory(temporary.parent)
    try:
        _renameat2(temporary, path, _RENAME_NOREPLACE)
    except OSError as exc:
        if exc.errno not in {errno.ENOSYS, errno.EINVAL, errno.EXDEV, errno.EOPNOTSUPP}:
            raise FilesystemTransactionError(
                f"transaction final publication failed without replacement: {path}"
            ) from exc
        try:
            os.link(temporary, path, follow_symlinks=False)
        except OSError as fallback_exc:
            raise FilesystemTransactionError(
                f"transaction final link publication failed without replacement: {path}"
            ) from fallback_exc
        # Portable publication deliberately retains the complete temporary
        # hardlink. POSIX has no compare-and-unlink primitive, so deleting it
        # would reopen the no-clobber race this fallback exists to avoid.
    _fsync_directory(path.parent)


def _preserve_pathname_removal(
    path: Path,
    expected_identity: tuple[int, int],
    *,
    quarantine_parent: Path | None = None,
) -> Path:
    """Remove a visible name by moving its occupant into a private quarantine."""

    quarantine_root = quarantine_parent or path.parent
    if quarantine_root.stat().st_dev != path.parent.stat().st_dev:
        raise FilesystemTransactionError(
            f"transaction preservation directory is on another filesystem: {quarantine_root}"
        )
    quarantine = quarantine_root / f".hapax-preserved-{uuid.uuid4().hex}"
    try:
        quarantine.mkdir(mode=0o700)
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction preservation directory create failed: {quarantine}"
        ) from exc
    _fsync_directory(quarantine.parent)
    preserved = quarantine / "image"
    try:
        _renameat2(path, preserved, _RENAME_NOREPLACE)
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction preserving move requires atomic no-replace support: {path}"
        ) from exc
    _fsync_directory(quarantine)
    _fsync_directory(path.parent)
    if quarantine.parent != path.parent:
        _fsync_directory(quarantine.parent)
    if _path_identity(preserved) != expected_identity:
        raise FilesystemTransactionError(
            f"transaction source identity changed during preserving move: {path}; "
            f"the competing image is preserved at {preserved}"
        )
    return preserved


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


def _path_identity(path: Path) -> tuple[int, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction image identity unavailable: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FilesystemTransactionError(f"transaction path is not a regular file: {path}")
    return metadata.st_dev, metadata.st_ino


def _link_then_preserve(source: Path, destination: Path) -> None:
    """Move a regular file without ever replacing the destination name."""

    source_identity = _path_identity(source)
    try:
        os.link(source, destination, follow_symlinks=False)
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction no-clobber link failed: {source} -> {destination}"
        ) from exc
    _fsync_directory(destination.parent)
    if _path_identity(destination) != source_identity:
        raise FilesystemTransactionError(
            f"transaction destination identity changed before preserving move: {destination}"
        )
    quarantine_parent = (
        source.parent if source.parent.name == ".hapax-transactions" else destination.parent
    )
    _preserve_pathname_removal(
        source,
        source_identity,
        quarantine_parent=quarantine_parent,
    )


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
            identity = _path_identity(auxiliary)
            _preserve_pathname_removal(auxiliary, identity)
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
        _link_then_preserve(destination, displaced)
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
        auxiliary_image = _snapshot(auxiliary)
        if auxiliary_image[0] is not None:
            if (
                sum(
                    _snapshot(candidate) == auxiliary_image
                    for candidate in (path, stage, hold, move)
                )
                < 2
            ):
                raise FilesystemTransactionError(
                    f"transaction auxiliary image is not duplicated: {auxiliary}"
                )
            identity = _path_identity(auxiliary)
            _preserve_pathname_removal(auxiliary, identity)
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
    if stage.parent != path.parent:
        _fsync_directory(stage.parent)
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


def _intent_path(journal_path: Path) -> Path:
    return journal_path.with_name(f".{journal_path.name}.intent")


@contextmanager
def _transaction_lock(journal_path: Path):
    lock_path = journal_path.with_name(f".{journal_path.name}.lock")
    try:
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction lock unavailable: {lock_path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise FilesystemTransactionError(f"transaction lock is unsafe: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            raise FilesystemTransactionError(
                f"transaction lock acquisition failed: {lock_path}"
            ) from exc
        yield
    finally:
        os.close(descriptor)


@contextmanager
def _target_locks(paths: Sequence[Path]):
    """Serialize governed writers on every target filesystem, including NFS."""

    stage_directories = sorted({_ensure_stage_directory(path) for path in paths})
    descriptors: list[int] = []
    try:
        for stage_directory in stage_directories:
            lock_path = stage_directory / ".hapax-transaction.lock"
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                    0o600,
                )
            except OSError as exc:
                raise FilesystemTransactionError(
                    f"transaction target lock unavailable: {lock_path}"
                ) from exc
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
                raise FilesystemTransactionError(f"transaction target lock is unsafe: {lock_path}")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except OSError as exc:
                raise FilesystemTransactionError(
                    f"transaction target lock acquisition failed: {lock_path}"
                ) from exc
        yield
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


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
        prepared.append(prepared_entry)

    body = _manifest_body(transaction_id=transaction_id, entries=prepared)
    manifest_sha256 = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    record = {**body, "manifest_sha256": manifest_sha256}
    manifest_bytes = _canonical_bytes(record) + b"\n"
    intent = _intent_path(journal_path)
    _write_exclusive(intent, manifest_bytes, 0o600)
    try:
        journal_path.mkdir(mode=0o700)
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal create failed without replacement: {journal_path}"
        ) from exc
    _fsync_directory(journal_path.parent)
    try:
        os.link(intent, _manifest_path(journal_path), follow_symlinks=False)
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction manifest publication failed without replacement: {journal_path}"
        ) from exc
    _fsync_directory(journal_path)
    metadata = journal_path.lstat()
    journal_record = _JournalRecord(
        state="prepared",
        transaction_id=transaction_id,
        manifest_sha256=manifest_sha256,
        entries=prepared,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )
    _materialize_missing_stages(journal_record, allowed_roots=allowed_roots)
    _validate_current_images(prepared, accepted_images=("pre",), allowed_roots=allowed_roots)
    return journal_record


def _materialize_missing_stages(
    record: _JournalRecord,
    *,
    allowed_roots: Sequence[Path],
) -> None:
    """Finish durable stage preparation after an interrupted journal publish."""

    for entry in record.entries:
        path = _entry_path(entry, allowed_roots)
        stage = _entry_stage_path(entry, allowed_roots)
        hold, move = _entry_auxiliary_paths(entry, allowed_roots)
        post_content, post_mode = _entry_image(entry, "post")
        if post_content is None or _snapshot(stage)[0] is not None:
            continue
        if _snapshot(path) != _entry_image(entry, "pre"):
            continue
        if any(_snapshot(auxiliary)[0] is not None for auxiliary in (hold, move)):
            continue
        assert post_mode is not None
        _write_exclusive(stage, post_content, post_mode)


def _restore_journal_from_intent(journal_path: Path) -> bool:
    """Publish a complete manifest from the durable sibling intent if needed."""

    intent = _intent_path(journal_path)
    try:
        intent_metadata = intent.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction intent unavailable: {intent}") from exc
    expected_uid, expected_gid = _new_entry_identity(journal_path.parent)
    if (
        stat.S_ISLNK(intent_metadata.st_mode)
        or not stat.S_ISREG(intent_metadata.st_mode)
        or (intent_metadata.st_uid, intent_metadata.st_gid) != (expected_uid, expected_gid)
        or stat.S_IMODE(intent_metadata.st_mode) & 0o077
    ):
        raise FilesystemTransactionError(f"transaction intent path is unsafe: {intent}")

    try:
        journal_metadata = journal_path.lstat()
    except FileNotFoundError:
        try:
            journal_path.mkdir(mode=0o700)
        except OSError as exc:
            raise FilesystemTransactionError(
                f"transaction journal restore failed: {journal_path}"
            ) from exc
        _fsync_directory(journal_path.parent)
        journal_metadata = journal_path.lstat()
    if stat.S_ISLNK(journal_metadata.st_mode) or not stat.S_ISDIR(journal_metadata.st_mode):
        raise FilesystemTransactionError(
            f"transaction intent conflicts with journal path: {journal_path}"
        )

    manifest = _manifest_path(journal_path)
    try:
        manifest_metadata = manifest.lstat()
    except FileNotFoundError:
        try:
            os.link(intent, manifest, follow_symlinks=False)
        except OSError as exc:
            raise FilesystemTransactionError(
                f"transaction manifest restore failed: {manifest}"
            ) from exc
        _fsync_directory(journal_path)
        manifest_metadata = manifest.lstat()
    if (manifest_metadata.st_dev, manifest_metadata.st_ino) != (
        intent_metadata.st_dev,
        intent_metadata.st_ino,
    ):
        raise FilesystemTransactionError(
            f"transaction intent and manifest identities disagree: {journal_path}"
        )
    return True


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


def _decode_json_unique(raw: bytes, path: Path) -> object:
    def unique_pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in values:
            if key in output:
                raise FilesystemTransactionError(f"transaction journal duplicate key: {key}")
            output[key] = value
        return output

    try:
        return json.loads(raw.decode("ascii"), object_pairs_hook=unique_pairs)
    except FilesystemTransactionError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FilesystemTransactionError(f"transaction journal malformed: {path}") from exc


def _load_json_unique(path: Path) -> object:
    raw, _mode = _snapshot(path)
    if raw is None:
        raise FilesystemTransactionError(f"transaction journal member disappeared: {path}")
    return _decode_json_unique(raw, path)


def _load_json_unique_at(directory_fd: int, name: str, path: Path) -> object:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction journal member unavailable: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise FilesystemTransactionError(f"transaction journal member is unsafe: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return _decode_json_unique(b"".join(chunks), path)
    finally:
        os.close(descriptor)


def _load_v1_journal(
    journal_path: Path,
) -> _V1JournalRecord:
    try:
        descriptor = os.open(journal_path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal unavailable: {journal_path}"
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        expected_uid, expected_gid = _new_entry_identity(journal_path.parent)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or (metadata.st_uid, metadata.st_gid) != (expected_uid, expected_gid)
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise FilesystemTransactionError(f"transaction journal path is unsafe: {journal_path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    value = _decode_json_unique(b"".join(chunks), journal_path)
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
    try:
        current_metadata = journal_path.lstat()
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal identity changed while loading: {journal_path}"
        ) from exc
    if (current_metadata.st_dev, current_metadata.st_ino) != (
        metadata.st_dev,
        metadata.st_ino,
    ):
        raise FilesystemTransactionError(
            f"transaction journal identity changed while loading: {journal_path}"
        )
    return _V1JournalRecord(
        state=state,
        manifest_sha256=manifest_sha256,
        entries=entries,
        device=metadata.st_dev,
        inode=metadata.st_ino,
    )


def _same_v1_journal(left: _V1JournalRecord, right: _V1JournalRecord) -> bool:
    return (
        left.state == right.state
        and left.manifest_sha256 == right.manifest_sha256
        and left.device == right.device
        and left.inode == right.inode
    )


def _archive_v1_journal(
    journal_path: Path,
    record: _V1JournalRecord,
    *,
    outcome: str,
) -> Path:
    archive = journal_path.with_name(
        f".{journal_path.name}.history-v1-{record.manifest_sha256[:16]}-{outcome}"
    )
    try:
        current_metadata = journal_path.lstat()
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction v1 journal unavailable before archive: {journal_path}"
        ) from exc
    if (current_metadata.st_dev, current_metadata.st_ino) != (record.device, record.inode):
        raise FilesystemTransactionError(
            f"transaction v1 journal identity changed before archive: {journal_path}"
        )
    try:
        _renameat2(journal_path, archive, _RENAME_NOREPLACE)
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise FilesystemTransactionError(
                f"transaction v1 journal archive failed without replacement: {journal_path}"
            ) from exc
        archive_metadata = archive.lstat()
        if (archive_metadata.st_dev, archive_metadata.st_ino) != (
            record.device,
            record.inode,
        ):
            raise FilesystemTransactionError(
                f"transaction v1 archive third-image conflict: {archive}"
            ) from exc
        duplicate = archive.with_name(f"{archive.name}.duplicate-{uuid.uuid4().hex}")
        try:
            _renameat2(journal_path, duplicate, _RENAME_NOREPLACE)
        except OSError as duplicate_exc:
            raise FilesystemTransactionError(
                f"transaction v1 duplicate archive failed without replacement: {journal_path}"
            ) from duplicate_exc
    _fsync_directory(journal_path.parent)
    archive_metadata = archive.lstat()
    if (archive_metadata.st_dev, archive_metadata.st_ino) != (record.device, record.inode):
        raise FilesystemTransactionError(
            f"transaction v1 journal identity changed; all images were preserved: {archive}"
        )
    archived = _load_v1_journal(archive)
    if not _same_v1_journal(archived, record):
        raise FilesystemTransactionError(
            f"transaction v1 archived journal identity mismatch: {archive}"
        )
    return archive


def _recover_v1_journal(
    journal_path: Path,
    *,
    allowed_roots: Sequence[Path],
    target_locks_held: bool = False,
) -> None:
    record = _load_v1_journal(journal_path)
    target_paths: list[Path] = []
    seen: set[Path] = set()
    for entry in record.entries:
        raw_path = entry["path"]
        if not isinstance(raw_path, str) or not raw_path:
            raise FilesystemTransactionError("transaction entry path malformed")
        path = _allowed(Path(raw_path), allowed_roots)
        if path in seen:
            raise FilesystemTransactionError(f"duplicate transaction path: {path}")
        seen.add(path)
        target_paths.append(path)
    lock_context = nullcontext() if target_locks_held else _target_locks(target_paths)
    with lock_context:
        locked_record = _load_v1_journal(journal_path)
        if not _same_v1_journal(locked_record, record):
            raise FilesystemTransactionError(
                f"transaction v1 journal identity changed while acquiring target locks: {journal_path}"
            )
        record = locked_record
        image: ImageName = "post" if record.state == "committed" else "pre"
        mutations: list[FileMutation] = []
        for path, entry in zip(target_paths, record.entries, strict=True):
            actual = _snapshot(path)
            if actual not in {_entry_image(entry, "pre"), _entry_image(entry, "post")}:
                raise FilesystemTransactionError(
                    f"transaction third-image conflict; v1 journal and image were preserved: {path}"
                )
            content, mode = _entry_image(entry, image)
            if actual != (content, mode):
                expected_content, expected_mode = actual
                mutations.append(
                    FileMutation(
                        path=path,
                        content=content,
                        mode=mode,
                        expected_exists=expected_content is not None,
                        expected_sha256=(
                            hashlib.sha256(expected_content).hexdigest()
                            if expected_content is not None
                            else None
                        ),
                        expected_mode=expected_mode,
                    )
                )
        if mutations:
            compatibility_journal = journal_path.with_name(
                f".{journal_path.name}.v1-conversion-{record.manifest_sha256[:16]}"
            )
            with _transaction_lock(compatibility_journal):
                _recover_filesystem_transaction_unlocked(
                    compatibility_journal,
                    allowed_roots=allowed_roots,
                    target_locks_held=True,
                )
                _execute_filesystem_transaction_unlocked(
                    compatibility_journal,
                    mutations,
                    allowed_roots=allowed_roots,
                )
        _archive_v1_journal(journal_path, record, outcome=f"recovered-{image}")


def _load_journal(journal_path: Path) -> _JournalRecord:
    try:
        directory_fd = os.open(
            journal_path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal unavailable: {journal_path}"
        ) from exc
    try:
        metadata = os.fstat(directory_fd)
        expected_uid, expected_gid = _new_entry_identity(journal_path.parent)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_uid, metadata.st_gid) != (expected_uid, expected_gid)
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise FilesystemTransactionError(f"transaction journal path is unsafe: {journal_path}")
        value = _load_json_unique_at(
            directory_fd,
            "manifest.json",
            _manifest_path(journal_path),
        )
        commit_present = False
        try:
            commit_metadata = os.stat(
                "committed.json",
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise FilesystemTransactionError(
                f"transaction commit marker unavailable: {journal_path}"
            ) from exc
        else:
            if stat.S_ISLNK(commit_metadata.st_mode) or not stat.S_ISREG(commit_metadata.st_mode):
                raise FilesystemTransactionError(
                    f"transaction commit marker is unsafe: {journal_path}"
                )
            commit_present = True
            marker = _load_json_unique_at(
                directory_fd,
                "committed.json",
                _commit_path(journal_path),
            )
    finally:
        os.close(directory_fd)
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
    if commit_present:
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
    try:
        current_metadata = journal_path.lstat()
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal identity changed while loading: {journal_path}"
        ) from exc
    if (current_metadata.st_dev, current_metadata.st_ino) != (metadata.st_dev, metadata.st_ino):
        raise FilesystemTransactionError(
            f"transaction journal identity changed while loading: {journal_path}"
        )
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
        current_metadata = journal_path.lstat()
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal unavailable before archive: {journal_path}"
        ) from exc
    if (current_metadata.st_dev, current_metadata.st_ino) != (record.device, record.inode):
        raise FilesystemTransactionError(
            f"transaction journal identity changed before archive: {journal_path}"
        )
    intent = _intent_path(journal_path)
    try:
        intent_metadata = intent.lstat()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise FilesystemTransactionError(f"transaction intent unavailable: {intent}") from exc
    else:
        manifest_metadata = _manifest_path(journal_path).lstat()
        if (intent_metadata.st_dev, intent_metadata.st_ino) != (
            manifest_metadata.st_dev,
            manifest_metadata.st_ino,
        ):
            raise FilesystemTransactionError(
                f"transaction intent identity changed before archive: {intent}"
            )
        try:
            _renameat2(intent, journal_path / "intent.json", _RENAME_NOREPLACE)
        except OSError as exc:
            raise FilesystemTransactionError(
                f"transaction intent preservation failed without replacement: {intent}"
            ) from exc
        _fsync_directory(journal_path)
        _fsync_directory(intent.parent)
    try:
        _renameat2(journal_path, archive, _RENAME_NOREPLACE)
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal archive requires atomic no-replace support: {journal_path}"
        ) from exc
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


def _recover_filesystem_transaction_unlocked(
    journal_path: Path,
    *,
    allowed_roots: Sequence[Path],
    target_locks_held: bool = False,
) -> bool:
    """Recover a prior interrupted transaction without deleting any image."""

    _allowed(journal_path, allowed_roots)
    _restore_journal_from_intent(journal_path)
    try:
        metadata = journal_path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise FilesystemTransactionError(
            f"transaction journal unavailable: {journal_path}"
        ) from exc
    if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        _recover_v1_journal(
            journal_path,
            allowed_roots=allowed_roots,
            target_locks_held=target_locks_held,
        )
        return True
    record = _load_journal(journal_path)
    target_paths = [_entry_path(entry, allowed_roots) for entry in record.entries]
    lock_context = nullcontext() if target_locks_held else _target_locks(target_paths)
    with lock_context:
        locked_record = _load_journal(journal_path)
        if (
            locked_record.transaction_id != record.transaction_id
            or locked_record.manifest_sha256 != record.manifest_sha256
            or locked_record.state != record.state
            or locked_record.device != record.device
            or locked_record.inode != record.inode
        ):
            raise FilesystemTransactionError(
                f"transaction journal identity changed while acquiring target locks: {journal_path}"
            )
        record = locked_record
        _materialize_missing_stages(record, allowed_roots=allowed_roots)
        image: ImageName = "post" if record.state == "committed" else "pre"
        _apply(
            record.entries,
            image=image,
            accepted_current_images=("pre", "post"),
            allowed_roots=allowed_roots,
        )
        _archive_journal(journal_path, record, outcome=f"recovered-{image}")
    return True


def _same_journal(left: _JournalRecord, right: _JournalRecord) -> bool:
    return (
        left.transaction_id == right.transaction_id
        and left.manifest_sha256 == right.manifest_sha256
        and left.state == right.state
        and left.device == right.device
        and left.inode == right.inode
    )


def _entries_have_third_image(
    entries: list[TransactionEntry],
    *,
    allowed_roots: Sequence[Path],
) -> bool:
    for entry in entries:
        pre = _entry_image(entry, "pre")
        post = _entry_image(entry, "post")
        for candidate in _portable_paths(entry, allowed_roots):
            actual = _snapshot(candidate)
            if actual not in {(None, None), pre, post}:
                return True
    return False


def _recover_legacy_filesystem_transaction_unlocked(
    journal_path: Path,
    *,
    allowed_roots: Sequence[Path],
) -> bool:
    """Recover or preserve-retire one journal created before global serialization."""

    _allowed(journal_path, allowed_roots)
    _restore_journal_from_intent(journal_path)
    try:
        metadata = journal_path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise FilesystemTransactionError(
            f"legacy transaction journal unavailable: {journal_path}"
        ) from exc

    if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        record = _load_v1_journal(journal_path)
        target_paths = [
            _allowed(Path(str(entry["path"])), allowed_roots) for entry in record.entries
        ]
        with _target_locks(target_paths):
            locked_record = _load_v1_journal(journal_path)
            if not _same_v1_journal(locked_record, record):
                raise FilesystemTransactionError(
                    "legacy v1 transaction journal identity changed while acquiring "
                    f"target locks: {journal_path}"
                )
            for path, entry in zip(target_paths, locked_record.entries, strict=True):
                actual = _snapshot(path)
                if actual not in {_entry_image(entry, "pre"), _entry_image(entry, "post")}:
                    _archive_v1_journal(
                        journal_path,
                        locked_record,
                        outcome="legacy-superseded-third-image",
                    )
                    return True
            _recover_v1_journal(
                journal_path,
                allowed_roots=allowed_roots,
                target_locks_held=True,
            )
            return True

    record = _load_journal(journal_path)
    target_paths = [_entry_path(entry, allowed_roots) for entry in record.entries]
    with _target_locks(target_paths):
        locked_record = _load_journal(journal_path)
        if not _same_journal(locked_record, record):
            raise FilesystemTransactionError(
                "legacy transaction journal identity changed while acquiring target locks: "
                f"{journal_path}"
            )
        _materialize_missing_stages(locked_record, allowed_roots=allowed_roots)
        if _entries_have_third_image(locked_record.entries, allowed_roots=allowed_roots):
            _archive_journal(
                journal_path,
                locked_record,
                outcome="legacy-superseded-third-image",
            )
            return True
        return _recover_filesystem_transaction_unlocked(
            journal_path,
            allowed_roots=allowed_roots,
            target_locks_held=True,
        )


def migrate_legacy_filesystem_transactions(
    stable_journal: Path,
    legacy_journals: Sequence[Path],
    *,
    allowed_roots: Sequence[Path],
) -> None:
    """Drain pre-global journals while one stable ownership lock excludes new writers."""

    _allowed(stable_journal, allowed_roots)
    with _transaction_lock(stable_journal):
        for journal_path in sorted(set(legacy_journals)):
            if journal_path == stable_journal:
                continue
            with _transaction_lock(journal_path):
                _recover_legacy_filesystem_transaction_unlocked(
                    journal_path,
                    allowed_roots=allowed_roots,
                )
        _recover_filesystem_transaction_unlocked(
            stable_journal,
            allowed_roots=allowed_roots,
        )


def recover_filesystem_transaction(
    journal_path: Path,
    *,
    allowed_roots: Sequence[Path],
) -> bool:
    """Recover one transaction while excluding cooperating writers."""

    _allowed(journal_path, allowed_roots)
    with _transaction_lock(journal_path):
        return _recover_filesystem_transaction_unlocked(
            journal_path,
            allowed_roots=allowed_roots,
        )


def _execute_filesystem_transaction_unlocked(
    journal_path: Path,
    mutations: Sequence[FileMutation],
    *,
    allowed_roots: Sequence[Path],
) -> None:
    """Apply exact postimages while preserving every displaced pathname image."""

    if not mutations:
        raise FilesystemTransactionError("transaction requires at least one mutation")
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
        if mutation.expected_mode is not None and pre_mode != mutation.expected_mode:
            raise FilesystemTransactionError(f"transaction mode precondition changed: {path}")
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

    try:
        record = _prepare_journal(journal_path, entries, allowed_roots=allowed_roots)
    except BaseException:
        if journal_path.exists() or _intent_path(journal_path).exists():
            _recover_filesystem_transaction_unlocked(
                journal_path,
                allowed_roots=allowed_roots,
                target_locks_held=True,
            )
        raise
    try:
        _apply(
            record.entries,
            image="post",
            accepted_current_images=("pre",),
            allowed_roots=allowed_roots,
        )
    except BaseException:
        _recover_filesystem_transaction_unlocked(
            journal_path,
            allowed_roots=allowed_roots,
            target_locks_held=True,
        )
        raise
    try:
        _mark_committed(journal_path, record)
    except BaseException:
        _recover_filesystem_transaction_unlocked(
            journal_path,
            allowed_roots=allowed_roots,
            target_locks_held=True,
        )
        raise
    committed = _load_journal(journal_path)
    _archive_journal(journal_path, committed, outcome="committed")


def execute_filesystem_transaction(
    journal_path: Path,
    mutations: Sequence[FileMutation],
    *,
    allowed_roots: Sequence[Path],
) -> None:
    """Apply one transaction while excluding cooperating writers."""

    _allowed(journal_path, allowed_roots)
    with _transaction_lock(journal_path):
        _recover_filesystem_transaction_unlocked(journal_path, allowed_roots=allowed_roots)
        target_paths = [_allowed(mutation.path, allowed_roots) for mutation in mutations]
        with _target_locks(target_paths):
            _execute_filesystem_transaction_unlocked(
                journal_path,
                mutations,
                allowed_roots=allowed_roots,
            )
