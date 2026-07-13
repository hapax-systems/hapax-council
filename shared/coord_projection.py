"""Canonical coordination projection + typed event emitters.

Coordination reform Phase 4 (CASE-SDLC-REFORM-001): the daemon-owned coord event
log (``shared/coord_event_log``) is the SSOT for SDLC stage and the no-go
authorization booleans. This module is the ONLY sanctioned way to:

* emit a typed :class:`CoordEvent` for a stage transition, a no-go-boolean flip,
  an evidence append, or a migration annotation — so "a typed ledger append is
  the only way to flip a no-go boolean" (master design §4.3) is realized in code;
* fold the replayed log back into a per-task projection (stage + no-go vector)
  that vault frontmatter and dashboards are diffed against for drift.

Two emit disciplines:

* **strict** (:func:`emit_stage_transition` / :func:`emit_authorization_flip` /
  :func:`emit_stage_transition_intent`): the transition is authoritative, so the
  append must succeed. Only :class:`DuplicateEventError` is swallowed (an
  idempotent retry of the same event); every other error propagates so the caller
  ABORTS rather than leave the vault projecting state the ledger does not back.
* **best-effort** (:func:`emit_evidence_appended` / :func:`emit_migration_annotated`):
  an observability mirror that is off by default, never raises, and is
  load-bearing for no invariant.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import struct
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from hapax.context_canon import (
    CoordEventRecord,
    CoordReplaySnapshot,
    LifecycleDefinition,
    build_coord_replay_snapshot,
)

from shared.coord_event_log import (
    AppendReceipt,
    CoordEvent,
    CoordEventLog,
    CoordWriter,
    DuplicateEventError,
    coord_base_dir,
    default_event_log,
)

if TYPE_CHECKING:
    from shared.coord_event_log import CoordEventLog, ReplayResult

# --- canonical coord event types ---------------------------------------------
CANON_STAGE_TRANSITION = "sdlc.stage_transition"
CANON_AUTHZ_FLIP = "sdlc.authorization_flip"
CANON_EVIDENCE_APPENDED = "evidence.appended"
CANON_MIGRATION_ANNOTATED = "migration.annotated"
CANON_TRANSITION_PREPARED = "sdlc.transition_prepared"
CANON_TRANSITION_APPLIED = "sdlc.transition_applied"
CANON_TRANSITION_ABORTED = "sdlc.transition_aborted"
TRANSITION_TRANSACTION_SCHEMA_V1 = "hapax.sdlc-transition-transaction.v1"
TRANSITION_TRANSACTION_SCHEMA_V2 = "hapax.sdlc-transition-transaction.v2"
TRANSITION_TRANSACTION_SCHEMA = TRANSITION_TRANSACTION_SCHEMA_V2
LIFECYCLE_DEFINITION_BINDING_SCHEMA = "hapax.sdlc-lifecycle-definition-binding.v2"
LIFECYCLE_DEFINITION_COMPILER_REF = "hapax.lifecycle-definition-compiler@v1"
SUPPORTED_LIFECYCLE_DEFINITION_COMPILER_REFS = frozenset({LIFECYCLE_DEFINITION_COMPILER_REF})
LIFECYCLE_DERIVATION_MODE = "write_time_append_attestation"
_LIFECYCLE_EFFECT_ACTIVATION = False
PHASE_APPEND_PROJECTION_SCHEMA = "hapax.sdlc-transition-phase-append-projection.v1"
MATERIALIZATION_PLAN_SCHEMA = "hapax.sdlc-transition-materialization-plan.v1"
LIFECYCLE_INSPECTION_SCHEMA = "hapax.sdlc-lifecycle-inspection.v1"
_MAX_LIFECYCLE_TRANSACTIONS = 4096
_MAX_LIFECYCLE_JOURNAL_CHILDREN = 64
_MAX_LIFECYCLE_TOTAL_CHILDREN = 16384
_MAX_LIFECYCLE_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_LIFECYCLE_BLOB_BYTES = 32 * 1024 * 1024
_MAX_LIFECYCLE_PHASE_BYTES = 1024 * 1024
_MAX_LIFECYCLE_JOURNAL_BYTES = 128 * 1024 * 1024
_MAX_LIFECYCLE_REASON_CODE_BYTES = 256
_MAX_LIFECYCLE_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES = 192 * 1024 * 1024
_LIFECYCLE_SOURCE_BLOB = "lifecycle-source.yaml"
_LIFECYCLE_DEFINITION_BLOB = "lifecycle-definition.json"
_RENAME_NOREPLACE = 1
_RENAME_EXCHANGE = 2

#: Opt-in env var: when set (and no event_log is injected) the best-effort
#: evidence mirror writes to the default coord log instead of no-op'ing.
EVIDENCE_MIRROR_ENV = "HAPAX_COORD_EVIDENCE_MIRROR"

#: The no-go authorization booleans a typed flip event may carry. Every consumer
#: across the stack (policy_decide, cc-task-repair, cc-task-backfill-nogo,
#: cc-stage-advance, case_migration) draws its fields from this set.
NO_GO_BOOLEANS = frozenset(
    {
        "implementation_authorized",
        "source_mutation_authorized",
        "docs_mutation_authorized",
        "runtime_mutation_authorized",
        "vault_mutation_authorized",
        "release_authorized",
        "public_current",
        "axiom_mutation_authorized",
    }
)

#: Vault cc-task store (the stage projection is diffed against its frontmatter).
DEFAULT_VAULT_TASKS = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_lifecycle_effect_activation() -> None:
    if _LIFECYCLE_EFFECT_ACTIVATION is not True:
        raise LifecycleTransitionError(
            "transition_effect_activation_unavailable",
            "activate lifecycle effects only with the admitted spine lockstep release",
        )


def _digest(*parts: object) -> str:
    payload = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _domain_hash(domain: str, value: object) -> str:
    return _sha256(domain.encode("ascii") + b"\0" + _canonical_json_bytes(value))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


# --- deterministic event-id builders -----------------------------------------
# Same load-bearing inputs -> same id, so an idempotent retry collapses to one
# durable event; a changed field (e.g. a different to_stage) yields a new id.
def stage_transition_event_id(
    *,
    task_id: str,
    authority_case: str | None,
    from_stage: str,
    to_stage: str,
    timestamp: str,
) -> str:
    return f"sdlc-stage-{_digest(task_id, authority_case, from_stage, to_stage, timestamp)}"


def authorization_flip_event_id(
    *, task_id: str, field: str, old: object, new: object, timestamp: str
) -> str:
    return f"authz-flip-{_digest(task_id, field, old, new, timestamp)}"


def evidence_appended_event_id(*, evidence_id: str) -> str:
    return f"evidence-{_digest(evidence_id)}"


def migration_annotated_event_id(*, task_id: str, stage: str, risk_tier: str, decision: str) -> str:
    return f"migration-{_digest(task_id, stage, risk_tier, decision)}"


# --- strict append discipline ------------------------------------------------
def _strict_append(event_log: CoordEventLog, event: CoordEvent) -> AppendReceipt:
    """Append authoritatively. Swallow ONLY a duplicate (idempotent success)."""
    try:
        return event_log.append(event, writer=CoordWriter.daemon())
    except DuplicateEventError:
        return AppendReceipt(
            event_id=event.event_id,
            appended=True,
            spooled=False,
            sequence=None,
            db_path=event_log.db_path,
            jsonl_path=event_log.jsonl_path,
        )


class LifecycleTransitionError(RuntimeError):
    """Typed refusal or recovery failure for a lifecycle transaction."""

    def __init__(self, reason_code: str, repair_action: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
        message = f"{reason_code}: {repair_action}"
        if detail:
            message += f" ({detail})"
        super().__init__(message)


class ReadOnlySnapshotError(RuntimeError):
    """Typed refusal from the zero-write filesystem snapshot boundary."""

    def __init__(self, reason_code: str, repair_action: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
        message = f"{reason_code}: {repair_action}"
        if detail:
            message += f" ({detail})"
        super().__init__(message)


@dataclass(frozen=True)
class FsStamp:
    device: int
    inode: int
    uid: int
    gid: int
    mode: int
    nlink: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, metadata: os.stat_result) -> FsStamp:
        return cls(
            device=metadata.st_dev,
            inode=metadata.st_ino,
            uid=metadata.st_uid,
            gid=metadata.st_gid,
            mode=metadata.st_mode,
            nlink=metadata.st_nlink,
            size=metadata.st_size,
            mtime_ns=metadata.st_mtime_ns,
            ctime_ns=metadata.st_ctime_ns,
        )

    def to_record(self) -> dict[str, int]:
        return {
            "ctime_ns": self.ctime_ns,
            "device": self.device,
            "gid": self.gid,
            "inode": self.inode,
            "mode": self.mode,
            "mtime_ns": self.mtime_ns,
            "nlink": self.nlink,
            "size": self.size,
            "uid": self.uid,
        }


@dataclass(frozen=True)
class PinnedDirectory:
    path: Path
    stamp: FsStamp
    observation_sha256: str
    _fd: int = field(repr=False, compare=False)
    _owner_token: object = field(repr=False, compare=False)
    _private: bool = field(repr=False, compare=False)
    _parent_fd: int | None = field(default=None, repr=False, compare=False)
    _name: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class CapturedFile:
    path: Path
    content: bytes
    content_sha256: str
    stamp: FsStamp
    observation_sha256: str


@dataclass(frozen=True)
class FileObservation:
    path: Path
    present: bool
    captured: CapturedFile | None
    observation_sha256: str


@dataclass(frozen=True)
class FsSnapshotSeal:
    directory_observations: tuple[str, ...]
    file_observations: tuple[str, ...]
    listing_observations: tuple[str, ...]
    absence_observations: tuple[str, ...]
    seal_ref: str
    seal_hash: str
    change_scope: Literal["estate", "observed_paths"] = "estate"
    may_authorize: Literal[False] = False
    schema: str = "hapax.read-only-fs-snapshot.v1"

    def __post_init__(self) -> None:
        expected_schema = (
            "hapax.read-only-fs-snapshot.v1"
            if self.change_scope == "estate"
            else "hapax.read-only-fs-snapshot.v2"
        )
        if self.may_authorize is not False or self.schema != expected_schema:
            raise ValueError("filesystem snapshot seal scope/schema mismatch")
        body = {
            "absence_observations": self.absence_observations,
            "directory_observations": self.directory_observations,
            "file_observations": self.file_observations,
            "listing_observations": self.listing_observations,
            "may_authorize": False,
            "schema": self.schema,
        }
        if self.schema == "hapax.read-only-fs-snapshot.v2":
            body["change_scope"] = self.change_scope
        digest = _domain_hash(self.schema, body)
        if self.seal_hash != digest or self.seal_ref != f"read-only-fs-snapshot@sha256:{digest}":
            raise ValueError("filesystem snapshot seal identity mismatch")


@dataclass
class _PinnedFileHandle:
    parent: PinnedDirectory
    name: str
    fd: int
    captured: CapturedFile


_IN_MODIFY = 0x00000002
_IN_ATTRIB = 0x00000004
_IN_CLOSE_WRITE = 0x00000008
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_UNMOUNT = 0x00002000
_IN_Q_OVERFLOW = 0x00004000
_IN_IGNORED = 0x00008000
_SNAPSHOT_INOTIFY_MASK = (
    _IN_MODIFY
    | _IN_ATTRIB
    | _IN_CLOSE_WRITE
    | _IN_MOVED_FROM
    | _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE
    | _IN_DELETE_SELF
    | _IN_MOVE_SELF
    | _IN_UNMOUNT
    | _IN_Q_OVERFLOW
    | _IN_IGNORED
)
_INOTIFY_EVENT_HEADER = struct.Struct("=iIII")
_SNAPSHOT_DIRECTORY_SELF_MASK = _IN_DELETE_SELF | _IN_MOVE_SELF | _IN_UNMOUNT | _IN_IGNORED


class ReadOnlyFsSnapshot:
    """FD-pinned, bounded, zero-write filesystem observation capability."""

    def __init__(
        self,
        *,
        max_total_bytes: int = 512 * 1024 * 1024,
        change_scope: Literal["estate", "observed_paths"] = "estate",
    ) -> None:
        if max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        if change_scope not in {"estate", "observed_paths"}:
            raise ValueError("change_scope must be estate or observed_paths")
        self._max_total_bytes = max_total_bytes
        self._change_scope = change_scope
        self._captured_bytes = 0
        self._owner_token = object()
        self._directories: list[PinnedDirectory] = []
        self._directory_handles: set[int] = set()
        self._files: list[_PinnedFileHandle] = []
        self._listings: dict[int, tuple[str, ...]] = {}
        self._listing_observations: dict[int, str] = {}
        self._absence_observations: list[str] = []
        self._directory_watch_descriptors: dict[int, int] = {}
        self._watch_kinds: dict[int, set[Literal["directory", "file"]]] = {}
        self._estate_watch_descriptors: set[int] = set()
        self._relevant_child_names: dict[int, set[bytes]] = {}
        self._closed = False
        self._sealed = False
        self._libc = ctypes.CDLL(None, use_errno=True)
        init = getattr(self._libc, "inotify_init1", None)
        add_watch = getattr(self._libc, "inotify_add_watch", None)
        if init is None or add_watch is None:
            raise ReadOnlySnapshotError(
                "fs_snapshot_guard_unavailable",
                "run strict observation on Linux with inotify support",
            )
        init.argtypes = [ctypes.c_int]
        init.restype = ctypes.c_int
        add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        add_watch.restype = ctypes.c_int
        self._inotify_add_watch = add_watch
        self._inotify_fd = init(os.O_CLOEXEC | os.O_NONBLOCK)
        if self._inotify_fd < 0:
            value = ctypes.get_errno()
            raise ReadOnlySnapshotError(
                "fs_snapshot_guard_unavailable",
                "restore inotify capacity before strict observation",
                os.strerror(value),
            )

    def __enter__(self) -> ReadOnlyFsSnapshot:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed or self._sealed:
            raise ReadOnlySnapshotError(
                "fs_snapshot_lifecycle_invalid",
                "use each snapshot capability only while open and before seal",
            )

    def _require_owned(self, directory: PinnedDirectory) -> None:
        self._require_open()
        if (
            directory._owner_token is not self._owner_token
            or id(directory) not in self._directory_handles
        ):
            raise ReadOnlySnapshotError(
                "fs_snapshot_handle_foreign",
                "use only directory handles minted by this open snapshot",
                str(directory.path),
            )

    @staticmethod
    def _stamp_address(kind: str, path: Path, stamp: FsStamp) -> str:
        return _domain_hash(
            "hapax.read-only-fs-snapshot.object.v1",
            {"kind": kind, "path": str(path), "stamp": stamp.to_record()},
        )

    @staticmethod
    def _validate_component(name: str) -> None:
        if name in {"", ".", ".."} or "/" in name or "\0" in name:
            raise ReadOnlySnapshotError(
                "fs_snapshot_name_unsafe",
                "use one literal child name without traversal",
                name,
            )

    def _watch_fd(
        self,
        fd: int,
        path: Path,
        *,
        kind: Literal["directory", "file"],
    ) -> int:
        watch_path = f"/proc/self/fd/{fd}".encode("ascii")
        watch_descriptor = self._inotify_add_watch(
            self._inotify_fd,
            watch_path,
            _SNAPSHOT_INOTIFY_MASK,
        )
        if watch_descriptor < 0:
            value = ctypes.get_errno()
            raise ReadOnlySnapshotError(
                "fs_snapshot_guard_unavailable",
                "restore inotify watch capacity before strict observation",
                f"{path}:{os.strerror(value)}",
            )
        self._watch_kinds.setdefault(watch_descriptor, set()).add(kind)
        return watch_descriptor

    def _register_child_name(self, directory: PinnedDirectory, name: str) -> None:
        if self._change_scope != "observed_paths":
            return
        watch_descriptor = self._directory_watch_descriptors.get(directory._fd)
        if watch_descriptor is None:
            raise ReadOnlySnapshotError(
                "fs_snapshot_guard_unavailable",
                "restore the directory watch before observing a child",
                str(directory.path / name),
            )
        self._relevant_child_names.setdefault(watch_descriptor, set()).add(os.fsencode(name))

    @staticmethod
    def _require_directory(
        metadata: os.stat_result,
        path: Path,
        *,
        private: bool,
    ) -> FsStamp:
        if not stat.S_ISDIR(metadata.st_mode):
            raise ReadOnlySnapshotError(
                "fs_snapshot_directory_unsafe",
                "restore the path as one real directory",
                str(path),
            )
        if private and (metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700):
            raise ReadOnlySnapshotError(
                "fs_snapshot_private_directory_unsafe",
                "use one euid-owned mode-0700 real directory",
                str(path),
            )
        return FsStamp.from_stat(metadata)

    @staticmethod
    def _require_file(
        metadata: os.stat_result,
        path: Path,
        *,
        private: bool,
    ) -> FsStamp:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or (private and stat.S_IMODE(metadata.st_mode) != 0o600)
        ):
            raise ReadOnlySnapshotError(
                "fs_snapshot_file_unsafe",
                "use one euid-owned single-link regular file"
                + (" with mode 0600" if private else ""),
                str(path),
            )
        return FsStamp.from_stat(metadata)

    def _record_directory(
        self,
        fd: int,
        path: Path,
        *,
        private: bool,
        parent_fd: int | None = None,
        name: str | None = None,
    ) -> PinnedDirectory:
        stamp = self._require_directory(os.fstat(fd), path, private=private)
        watch_descriptor = self._watch_fd(fd, path, kind="directory")
        self._directory_watch_descriptors[fd] = watch_descriptor
        self._relevant_child_names.setdefault(watch_descriptor, set())
        pinned = PinnedDirectory(
            path=path,
            stamp=stamp,
            observation_sha256=self._stamp_address("directory", path, stamp),
            _fd=fd,
            _owner_token=self._owner_token,
            _private=private,
            _parent_fd=parent_fd,
            _name=name,
        )
        self._directories.append(pinned)
        self._directory_handles.add(id(pinned))
        return pinned

    @staticmethod
    def _noatime_directory_fd(fd: int, path: Path) -> int:
        metadata = os.fstat(fd)
        if metadata.st_uid != os.geteuid():
            raise ReadOnlySnapshotError(
                "fs_snapshot_noatime_unavailable",
                "observe absence only below an euid-owned directory",
                str(path),
            )
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NOATIME
        try:
            replacement = os.open(".", flags, dir_fd=fd)
        except OSError as exc:
            raise ReadOnlySnapshotError(
                "fs_snapshot_noatime_unavailable",
                "restore O_NOATIME support before strict absence observation",
                str(path),
            ) from exc
        os.close(fd)
        return replacement

    def pin_absolute_dir(
        self,
        path: Path,
        *,
        private_final: bool,
        allow_missing: bool = False,
    ) -> PinnedDirectory | None:
        self._require_open()
        normalized = _normalized_path(path)
        if normalized == Path("/"):
            raise ReadOnlySnapshotError(
                "fs_snapshot_root_observation_forbidden",
                "observe one bounded directory below the filesystem root",
                str(normalized),
            )
        base_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        fd = os.open("/", base_flags)
        fd_owned = False
        current_path = Path("/")
        try:
            components = normalized.parts[1:]
            for index, component in enumerate(components):
                final = index == len(components) - 1
                flags = base_flags | (os.O_NOATIME if final else 0)
                try:
                    next_fd = os.open(component, flags, dir_fd=fd)
                except FileNotFoundError:
                    if allow_missing:
                        fd = self._noatime_directory_fd(fd, current_path)
                        parent = self._record_directory(
                            fd,
                            current_path,
                            private=False,
                        )
                        fd_owned = True
                        names = self.list_names(parent)
                        digest = _domain_hash(
                            "hapax.read-only-fs-snapshot.directory-absence.v1",
                            {
                                "missing_component": component,
                                "names": names,
                                "parent_observation": parent.observation_sha256,
                                "path": str(normalized),
                                "present": False,
                            },
                        )
                        self._absence_observations.append(digest)
                        return None
                    raise
                os.close(fd)
                fd = next_fd
                current_path /= component
            return self._record_directory(
                fd,
                normalized,
                private=private_final,
            )
        except FileNotFoundError as exc:
            if not fd_owned:
                os.close(fd)
            raise ReadOnlySnapshotError(
                "fs_snapshot_directory_missing",
                "restore the required observation directory",
                str(normalized),
            ) from exc
        except OSError as exc:
            if not fd_owned:
                os.close(fd)
            raise ReadOnlySnapshotError(
                "fs_snapshot_directory_unsafe",
                "restore every path component as a real non-symlink directory",
                str(normalized),
            ) from exc
        except Exception:
            if not fd_owned:
                os.close(fd)
            raise

    def pin_dir_at(
        self,
        parent: PinnedDirectory,
        name: str,
        *,
        private: bool,
    ) -> PinnedDirectory:
        self._require_owned(parent)
        self._validate_component(name)
        self._register_child_name(parent, name)
        path = parent.path / name
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NOATIME
        try:
            fd = os.open(name, flags, dir_fd=parent._fd)
        except OSError as exc:
            raise ReadOnlySnapshotError(
                "fs_snapshot_directory_unsafe",
                "restore the child as one real non-symlink directory",
                str(path),
            ) from exc
        try:
            return self._record_directory(
                fd,
                path,
                private=private,
                parent_fd=parent._fd,
                name=name,
            )
        except Exception:
            os.close(fd)
            raise

    def list_names(self, directory: PinnedDirectory) -> tuple[str, ...]:
        self._require_owned(directory)
        watch_descriptor = self._directory_watch_descriptors.get(directory._fd)
        if watch_descriptor is not None:
            self._estate_watch_descriptors.add(watch_descriptor)
        try:
            names = tuple(sorted(os.listdir(directory._fd)))
        except OSError as exc:
            raise ReadOnlySnapshotError(
                "fs_snapshot_directory_unreadable",
                "restore a readable stable observation directory",
                str(directory.path),
            ) from exc
        prior = self._listings.setdefault(directory._fd, names)
        if prior != names:
            raise ReadOnlySnapshotError(
                "fs_snapshot_listing_changed",
                "retry after the observation directory stabilizes",
                str(directory.path),
            )
        self._listing_observations[directory._fd] = _domain_hash(
            "hapax.read-only-fs-snapshot.listing.v1",
            {
                "directory_observation": directory.observation_sha256,
                "names": names,
                "path": str(directory.path),
            },
        )
        return names

    def observe_file_at(
        self,
        parent: PinnedDirectory,
        name: str,
        *,
        private: bool,
        max_bytes: int,
    ) -> FileObservation:
        self._require_owned(parent)
        self._validate_component(name)
        self._register_child_name(parent, name)
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        path = parent.path / name
        flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NOATIME
        try:
            fd = os.open(name, flags, dir_fd=parent._fd)
        except FileNotFoundError:
            digest = _domain_hash(
                "hapax.read-only-fs-snapshot.file.v1",
                {"path": str(path), "present": False},
            )
            self._absence_observations.append(digest)
            return FileObservation(path, False, None, digest)
        except OSError as exc:
            raise ReadOnlySnapshotError(
                "fs_snapshot_file_unsafe",
                "restore the entry as an absent path or regular non-symlink file",
                str(path),
            ) from exc
        try:
            before = self._require_file(os.fstat(fd), path, private=private)
            if (
                before.size > max_bytes
                or self._captured_bytes + before.size > self._max_total_bytes
            ):
                raise ReadOnlySnapshotError(
                    "fs_snapshot_size_limit",
                    "narrow the observation or raise an explicitly governed byte limit",
                    f"{path}:{before.size}",
                )
            self._watch_fd(fd, path, kind="file")
            chunks: list[bytes] = []
            offset = 0
            while offset < before.size:
                chunk = os.pread(fd, min(1024 * 1024, before.size - offset), offset)
                if not chunk:
                    break
                chunks.append(chunk)
                offset += len(chunk)
            content = b"".join(chunks)
            after = FsStamp.from_stat(os.fstat(fd))
            if before != after or len(content) != before.size:
                raise ReadOnlySnapshotError(
                    "fs_snapshot_file_changed",
                    "retry after the observed file stabilizes",
                    str(path),
                )
            content_sha256 = _sha256(content)
            observation_sha256 = _domain_hash(
                "hapax.read-only-fs-snapshot.file.v1",
                {
                    "content_sha256": content_sha256,
                    "path": str(path),
                    "present": True,
                    "stamp": before.to_record(),
                },
            )
            captured = CapturedFile(
                path=path,
                content=content,
                content_sha256=content_sha256,
                stamp=before,
                observation_sha256=observation_sha256,
            )
            self._captured_bytes += len(content)
            self._files.append(_PinnedFileHandle(parent, name, fd, captured))
            return FileObservation(path, True, captured, observation_sha256)
        except Exception:
            os.close(fd)
            raise

    @staticmethod
    def _same_named_inode(
        parent_fd: int,
        name: str,
        stamp: FsStamp,
    ) -> bool:
        try:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError:
            return False
        return current.st_dev == stamp.device and current.st_ino == stamp.inode

    def _reopen_absolute(self, directory: PinnedDirectory) -> bool:
        base_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        fd = os.open("/", base_flags)
        try:
            components = directory.path.parts[1:]
            for index, component in enumerate(components):
                flags = base_flags | (os.O_NOATIME if index == len(components) - 1 else 0)
                next_fd = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            current = FsStamp.from_stat(os.fstat(fd))
            return self._directory_stamp_matches(current, directory.stamp)
        except OSError:
            return False
        finally:
            os.close(fd)

    def _directory_stamp_matches(self, current: FsStamp, observed: FsStamp) -> bool:
        if self._change_scope == "estate":
            return current == observed
        return (
            current.device,
            current.inode,
            current.uid,
            current.gid,
            current.mode,
        ) == (
            observed.device,
            observed.inode,
            observed.uid,
            observed.gid,
            observed.mode,
        )

    def _guard_events_present(self) -> bool:
        while True:
            try:
                chunk = os.read(self._inotify_fd, 64 * 1024)
            except BlockingIOError:
                return False
            if not chunk:
                return False
            if self._change_scope == "estate":
                return True
            offset = 0
            while offset < len(chunk):
                if len(chunk) - offset < _INOTIFY_EVENT_HEADER.size:
                    return True
                watch_descriptor, mask, _cookie, name_length = _INOTIFY_EVENT_HEADER.unpack_from(
                    chunk, offset
                )
                offset += _INOTIFY_EVENT_HEADER.size
                end = offset + name_length
                if end > len(chunk):
                    return True
                raw_name = chunk[offset:end]
                offset = end
                name = raw_name.split(b"\0", 1)[0] if raw_name else b""
                if mask & _IN_Q_OVERFLOW:
                    return True
                kinds = self._watch_kinds.get(watch_descriptor)
                if kinds is None:
                    return True
                if "file" in kinds:
                    return True
                if watch_descriptor in self._estate_watch_descriptors:
                    return True
                if "directory" not in kinds:
                    return True
                if mask & _SNAPSHOT_DIRECTORY_SELF_MASK or not name:
                    return True
                if name in self._relevant_child_names[watch_descriptor]:
                    return True

    def seal(self) -> FsSnapshotSeal:
        self._require_open()
        # A seal attempt consumes the capability. A failed attempt cannot be
        # retried after change evidence or inotify events have been observed.
        self._sealed = True
        for handle in self._files:
            current = FsStamp.from_stat(os.fstat(handle.fd))
            if current != handle.captured.stamp or not self._same_named_inode(
                handle.parent._fd, handle.name, handle.captured.stamp
            ):
                raise ReadOnlySnapshotError(
                    "fs_snapshot_file_changed",
                    "retry after the observed file stabilizes",
                    str(handle.captured.path),
                )
            content = b"".join(
                os.pread(
                    handle.fd,
                    min(1024 * 1024, current.size - offset),
                    offset,
                )
                for offset in range(0, current.size, 1024 * 1024)
            )
            if content != handle.captured.content:
                raise ReadOnlySnapshotError(
                    "fs_snapshot_file_changed",
                    "retry after the observed file stabilizes",
                    str(handle.captured.path),
                )
        for directory in self._directories:
            current = FsStamp.from_stat(os.fstat(directory._fd))
            if not self._directory_stamp_matches(current, directory.stamp):
                raise ReadOnlySnapshotError(
                    "fs_snapshot_directory_changed",
                    "retry after the observation directory stabilizes",
                    str(directory.path),
                )
            if directory._parent_fd is None:
                named = self._reopen_absolute(directory)
            else:
                assert directory._name is not None
                named = self._same_named_inode(
                    directory._parent_fd, directory._name, directory.stamp
                )
            if not named:
                raise ReadOnlySnapshotError(
                    "fs_snapshot_directory_changed",
                    "retry after the lexical observation path stabilizes",
                    str(directory.path),
                )
            if directory._fd in self._listings:
                try:
                    names = tuple(sorted(os.listdir(directory._fd)))
                except OSError as exc:
                    raise ReadOnlySnapshotError(
                        "fs_snapshot_directory_unreadable",
                        "restore a readable stable observation directory",
                        str(directory.path),
                    ) from exc
                if names != self._listings[directory._fd]:
                    raise ReadOnlySnapshotError(
                        "fs_snapshot_listing_changed",
                        "retry with a new snapshot after the directory stabilizes",
                        str(directory.path),
                    )
        if self._guard_events_present():
            raise ReadOnlySnapshotError(
                "fs_snapshot_concurrent_change",
                "retry after every watched filesystem object stabilizes",
            )
        directory_observations = tuple(
            sorted(item.observation_sha256 for item in self._directories)
        )
        file_observations = tuple(sorted(item.captured.observation_sha256 for item in self._files))
        listing_observations = tuple(sorted(self._listing_observations.values()))
        absence_observations = tuple(sorted(self._absence_observations))
        schema = (
            "hapax.read-only-fs-snapshot.v1"
            if self._change_scope == "estate"
            else "hapax.read-only-fs-snapshot.v2"
        )
        body = {
            "absence_observations": absence_observations,
            "directory_observations": directory_observations,
            "file_observations": file_observations,
            "listing_observations": listing_observations,
            "may_authorize": False,
            "schema": schema,
        }
        if schema == "hapax.read-only-fs-snapshot.v2":
            body["change_scope"] = self._change_scope
        digest = _domain_hash(schema, body)
        return FsSnapshotSeal(
            directory_observations=directory_observations,
            file_observations=file_observations,
            listing_observations=listing_observations,
            absence_observations=absence_observations,
            seal_ref=f"read-only-fs-snapshot@sha256:{digest}",
            seal_hash=digest,
            change_scope=self._change_scope,
            schema=schema,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handle in self._files:
            try:
                os.close(handle.fd)
            except OSError:
                pass
        for directory in self._directories:
            try:
                os.close(directory._fd)
            except OSError:
                pass
        os.close(self._inotify_fd)


def _rebuild_lifecycle_definition(
    source_content: bytes,
    *,
    compiler_ref: str = LIFECYCLE_DEFINITION_COMPILER_REF,
) -> LifecycleDefinition:
    from shared.sdlc_lifecycle import parse_sdlc_stage_metadata
    from shared.session_context_canon import build_lifecycle_definition

    if compiler_ref != LIFECYCLE_DEFINITION_COMPILER_REF:
        raise LifecycleTransitionError(
            "transition_lifecycle_compiler_unsupported",
            "restore the versioned lifecycle compiler named by the journal",
            compiler_ref,
        )
    try:
        catalog = parse_sdlc_stage_metadata(
            source_content.decode("utf-8"),
            source_label="docs/formal/sdlc-stage-metadata.yaml",
        )
        return build_lifecycle_definition(catalog, source_hash=_sha256(source_content))
    except (UnicodeError, ValueError) as exc:
        raise LifecycleTransitionError(
            "transition_lifecycle_definition_malformed",
            "restore source bytes that rebuild the accepted lifecycle definition",
            type(exc).__name__,
        ) from exc


@dataclass(frozen=True)
class LifecycleDefinitionBinding:
    """Exact historical lifecycle source, generic definition, and selected edge."""

    source_label: str
    source_blob: str
    source_sha256: str
    definition_blob: str
    definition_ref: str
    definition_hash: str
    compiler_ref: str
    derivation_mode: str
    derivation_ref: str
    derivation_hash: str
    from_stage: str
    to_stage: str
    edge_class: str
    projection_role: str
    authority_capability: str
    guards: tuple[str, ...]
    actions: tuple[str, ...]
    enforcement: str
    enforcement_ref: str | None
    binding_ref: str
    binding_hash: str
    may_authorize: Literal[False] = False
    schema: str = LIFECYCLE_DEFINITION_BINDING_SCHEMA

    def body(self) -> dict[str, Any]:
        return {
            "actions": list(self.actions),
            "authority_capability": self.authority_capability,
            "definition_blob": self.definition_blob,
            "definition_hash": self.definition_hash,
            "definition_ref": self.definition_ref,
            "compiler_ref": self.compiler_ref,
            "derivation_hash": self.derivation_hash,
            "derivation_mode": self.derivation_mode,
            "derivation_ref": self.derivation_ref,
            "edge_class": self.edge_class,
            "enforcement": self.enforcement,
            "enforcement_ref": self.enforcement_ref,
            "from_stage": self.from_stage,
            "guards": list(self.guards),
            "may_authorize": False,
            "projection_role": self.projection_role,
            "schema": LIFECYCLE_DEFINITION_BINDING_SCHEMA,
            "source_blob": self.source_blob,
            "source_label": self.source_label,
            "source_sha256": self.source_sha256,
            "to_stage": self.to_stage,
        }

    def to_record(self) -> dict[str, Any]:
        return {
            **self.body(),
            "binding_hash": self.binding_hash,
            "binding_ref": self.binding_ref,
        }

    def __post_init__(self) -> None:
        if (
            self.schema != LIFECYCLE_DEFINITION_BINDING_SCHEMA
            or self.may_authorize is not False
            or self.source_label != "docs/formal/sdlc-stage-metadata.yaml"
            or self.source_blob != _LIFECYCLE_SOURCE_BLOB
            or self.definition_blob != _LIFECYCLE_DEFINITION_BLOB
            or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None
            or re.fullmatch(r"[0-9a-f]{64}", self.definition_hash) is None
            or self.definition_ref != f"lifecycle-definition@sha256:{self.definition_hash}"
            or self.compiler_ref not in SUPPORTED_LIFECYCLE_DEFINITION_COMPILER_REFS
            or self.derivation_mode != LIFECYCLE_DERIVATION_MODE
            or re.fullmatch(r"[0-9a-f]{64}", self.derivation_hash) is None
            or self.derivation_ref
            != f"lifecycle-definition-derivation@sha256:{self.derivation_hash}"
            or self.edge_class not in {"next", "fall"}
            or self.projection_role not in {"advance", "branch", "repair"}
            or self.enforcement not in {"declared", "enforced"}
            or (self.enforcement == "enforced") != (self.enforcement_ref is not None)
            or not self.guards
            or not self.actions
            or self.guards != tuple(sorted(set(self.guards)))
            or self.actions != tuple(sorted(set(self.actions)))
        ):
            raise ValueError("lifecycle definition binding shape is invalid")
        derivation_hash = _domain_hash(
            "hapax.sdlc-lifecycle-definition-derivation.v1",
            {
                "compiler_ref": self.compiler_ref,
                "definition_hash": self.definition_hash,
                "definition_ref": self.definition_ref,
                "derivation_mode": self.derivation_mode,
                "source_label": self.source_label,
                "source_sha256": self.source_sha256,
            },
        )
        if self.derivation_hash != derivation_hash:
            raise ValueError("lifecycle definition derivation identity mismatch")
        digest = _domain_hash(LIFECYCLE_DEFINITION_BINDING_SCHEMA, self.body())
        if self.binding_hash != digest or self.binding_ref != (
            f"lifecycle-definition-binding@sha256:{digest}"
        ):
            raise ValueError("lifecycle definition binding identity mismatch")

    @classmethod
    def create(
        cls,
        definition: LifecycleDefinition,
        source_content: bytes,
        *,
        from_stage: str,
        to_stage: str,
        edge_class: str,
    ) -> LifecycleDefinitionBinding:
        checked = LifecycleDefinition.model_validate(
            definition.model_dump(mode="json", by_alias=True)
        )
        rebuilt = _rebuild_lifecycle_definition(source_content)
        source_hash = _sha256(source_content)
        if (
            checked.source_ref != "docs/formal/sdlc-stage-metadata.yaml"
            or checked.source_hash != source_hash
            or checked != rebuilt
        ):
            raise LifecycleTransitionError(
                "transition_lifecycle_source_mismatch",
                "use the exact definition rebuilt from the captured lifecycle source",
                checked.definition_ref,
            )
        return cls.from_attested_definition(
            checked,
            source_content,
            compiler_ref=LIFECYCLE_DEFINITION_COMPILER_REF,
            from_stage=from_stage,
            to_stage=to_stage,
            edge_class=edge_class,
        )

    @classmethod
    def from_attested_definition(
        cls,
        definition: LifecycleDefinition,
        source_content: bytes,
        *,
        compiler_ref: str,
        from_stage: str,
        to_stage: str,
        edge_class: str,
    ) -> LifecycleDefinitionBinding:
        """Bind a captured accepted definition without replaying its old compiler."""

        checked = LifecycleDefinition.model_validate(
            definition.model_dump(mode="json", by_alias=True)
        )
        source_hash = _sha256(source_content)
        if compiler_ref not in SUPPORTED_LIFECYCLE_DEFINITION_COMPILER_REFS:
            raise LifecycleTransitionError(
                "transition_lifecycle_compiler_unsupported",
                "restore a supported append-bound lifecycle derivation attestation",
                compiler_ref,
            )
        if (
            checked.source_ref != "docs/formal/sdlc-stage-metadata.yaml"
            or checked.source_hash != source_hash
        ):
            raise LifecycleTransitionError(
                "transition_lifecycle_source_mismatch",
                "restore the source bytes bound by the accepted definition",
                checked.definition_ref,
            )
        source = _definition_stage_token(checked, from_stage)
        target = _definition_stage_token(checked, to_stage)
        stage = next(item for item in checked.stages if item.token == source)
        matching = tuple(
            (name, edge)
            for name, edges in (("next", stage.next), ("fall", stage.fall))
            for edge in edges
            if edge.to == target
        )
        if edge_class == "auto":
            if len(matching) > 1:
                raise LifecycleTransitionError(
                    "transition_edge_class_ambiguous",
                    "pass --edge-class next or --edge-class fall",
                    f"{source}->{target}",
                )
            selected = matching[0] if matching else None
        elif edge_class in {"next", "fall"}:
            selected = next((item for item in matching if item[0] == edge_class), None)
        else:
            raise LifecycleTransitionError(
                "transition_edge_class_invalid",
                "use auto, next, or fall",
                edge_class,
            )
        if selected is None:
            raise LifecycleTransitionError(
                "transition_edge_illegal",
                "choose an exact Next or Fall edge from the checked lifecycle definition",
                f"{source}->{target}:{edge_class}",
            )
        selected_class, selected_edge = selected
        derivation_body = {
            "compiler_ref": compiler_ref,
            "definition_hash": checked.definition_hash,
            "definition_ref": checked.definition_ref,
            "derivation_mode": LIFECYCLE_DERIVATION_MODE,
            "source_label": checked.source_ref,
            "source_sha256": source_hash,
        }
        derivation_hash = _domain_hash(
            "hapax.sdlc-lifecycle-definition-derivation.v1",
            derivation_body,
        )
        body: dict[str, Any] = {
            "actions": list(selected_edge.actions),
            "authority_capability": selected_edge.authority_capability,
            "definition_blob": _LIFECYCLE_DEFINITION_BLOB,
            "definition_hash": checked.definition_hash,
            "definition_ref": checked.definition_ref,
            "compiler_ref": compiler_ref,
            "derivation_hash": derivation_hash,
            "derivation_mode": LIFECYCLE_DERIVATION_MODE,
            "derivation_ref": (f"lifecycle-definition-derivation@sha256:{derivation_hash}"),
            "edge_class": selected_class,
            "enforcement": selected_edge.enforcement,
            "enforcement_ref": selected_edge.enforcement_ref,
            "from_stage": source,
            "guards": list(selected_edge.guards),
            "may_authorize": False,
            "projection_role": selected_edge.projection_role,
            "schema": LIFECYCLE_DEFINITION_BINDING_SCHEMA,
            "source_blob": _LIFECYCLE_SOURCE_BLOB,
            "source_label": checked.source_ref,
            "source_sha256": source_hash,
            "to_stage": target,
        }
        digest = _domain_hash(LIFECYCLE_DEFINITION_BINDING_SCHEMA, body)
        return cls(
            source_label=checked.source_ref,
            source_blob=_LIFECYCLE_SOURCE_BLOB,
            source_sha256=source_hash,
            definition_blob=_LIFECYCLE_DEFINITION_BLOB,
            definition_ref=checked.definition_ref,
            definition_hash=checked.definition_hash,
            compiler_ref=compiler_ref,
            derivation_mode=LIFECYCLE_DERIVATION_MODE,
            derivation_ref=(f"lifecycle-definition-derivation@sha256:{derivation_hash}"),
            derivation_hash=derivation_hash,
            from_stage=source,
            to_stage=target,
            edge_class=selected_class,
            projection_role=selected_edge.projection_role,
            authority_capability=selected_edge.authority_capability,
            guards=selected_edge.guards,
            actions=selected_edge.actions,
            enforcement=selected_edge.enforcement,
            enforcement_ref=selected_edge.enforcement_ref,
            binding_ref=f"lifecycle-definition-binding@sha256:{digest}",
            binding_hash=digest,
        )

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> LifecycleDefinitionBinding:
        exact = {
            "actions",
            "authority_capability",
            "binding_hash",
            "binding_ref",
            "definition_blob",
            "definition_hash",
            "definition_ref",
            "compiler_ref",
            "derivation_hash",
            "derivation_mode",
            "derivation_ref",
            "edge_class",
            "enforcement",
            "enforcement_ref",
            "from_stage",
            "guards",
            "may_authorize",
            "projection_role",
            "schema",
            "source_blob",
            "source_label",
            "source_sha256",
            "to_stage",
        }
        if set(value) != exact or value.get("may_authorize") is not False:
            raise ValueError("lifecycle definition binding record is malformed")
        checked = cls(
            source_label=str(value["source_label"]),
            source_blob=str(value["source_blob"]),
            source_sha256=str(value["source_sha256"]),
            definition_blob=str(value["definition_blob"]),
            definition_ref=str(value["definition_ref"]),
            definition_hash=str(value["definition_hash"]),
            compiler_ref=str(value["compiler_ref"]),
            derivation_mode=str(value["derivation_mode"]),
            derivation_ref=str(value["derivation_ref"]),
            derivation_hash=str(value["derivation_hash"]),
            from_stage=str(value["from_stage"]),
            to_stage=str(value["to_stage"]),
            edge_class=str(value["edge_class"]),
            projection_role=str(value["projection_role"]),
            authority_capability=str(value["authority_capability"]),
            guards=tuple(str(item) for item in value["guards"]),
            actions=tuple(str(item) for item in value["actions"]),
            enforcement=str(value["enforcement"]),
            enforcement_ref=_optional_str(value.get("enforcement_ref")),
            binding_ref=str(value["binding_ref"]),
            binding_hash=str(value["binding_hash"]),
        )
        if checked.to_record() != dict(value):
            raise ValueError("lifecycle definition binding record is noncanonical")
        return checked


def _definition_stage_token(definition: LifecycleDefinition, raw: str) -> str:
    if not raw.strip():
        raise LifecycleTransitionError(
            "stage_blank",
            "provide a canonical stage token or declared alias",
        )
    if raw != raw.strip():
        raise LifecycleTransitionError(
            "stage_whitespace_drift",
            "remove leading or trailing whitespace",
            raw,
        )
    aliases = {
        alias: stage.token
        for stage in definition.stages
        for alias in (
            stage.token,
            stage.display_alias,
            *stage.aliases,
            *stage.deprecated_aliases,
        )
    }
    resolved = aliases.get(raw)
    if resolved is not None:
        return resolved
    folded = {alias.casefold(): alias for alias in aliases}
    if raw.casefold() in folded:
        canonical = folded[raw.casefold()]
        raise LifecycleTransitionError(
            "stage_case_drift",
            f"use exact case: {canonical}",
            raw,
        )
    raise LifecycleTransitionError(
        "stage_alias_unknown",
        "use a token or alias declared by the bound lifecycle definition",
        raw,
    )


def _capture_current_lifecycle_definition() -> tuple[LifecycleDefinition, bytes]:
    from shared.sdlc_lifecycle import SDLC_STAGE_METADATA_PATH

    with ReadOnlyFsSnapshot(max_total_bytes=_MAX_LIFECYCLE_MANIFEST_BYTES) as snapshot:
        parent = snapshot.pin_absolute_dir(
            SDLC_STAGE_METADATA_PATH.parent,
            private_final=False,
        )
        assert parent is not None
        observation = snapshot.observe_file_at(
            parent,
            SDLC_STAGE_METADATA_PATH.name,
            private=False,
            max_bytes=_MAX_LIFECYCLE_MANIFEST_BYTES,
        )
        if observation.captured is None:
            raise LifecycleTransitionError(
                "transition_lifecycle_definition_missing",
                "restore the exact lifecycle source before constructing an intent",
            )
        source = observation.captured.content
        snapshot.seal()
    return _rebuild_lifecycle_definition(source), source


@dataclass(frozen=True)
class LifecycleTransitionIntent:
    """One canonical, non-authorizing request to traverse a declared FSM edge."""

    task_id: str
    from_stage: str
    to_stage: str
    edge_class: str
    edge_projection_role: str
    edge_authority_capability: str
    authority_case: str
    actor: str
    no_go_snapshot: Mapping[str, bool]
    guard_evidence: Mapping[str, tuple[str, ...]]
    lifecycle_definition_binding: LifecycleDefinitionBinding
    lifecycle_definition: LifecycleDefinition = field(repr=False)
    lifecycle_source: bytes = field(repr=False)
    parent_spec: str | None = None
    predecessor_position_ref: str | None = None
    echo_receipt_ref: str | None = None
    evidence_type: str | None = None
    evidence_summary: str | None = None
    origin: str = "cli"

    def __post_init__(self) -> None:
        checked_definition = LifecycleDefinition.model_validate(
            self.lifecycle_definition.model_dump(mode="json", by_alias=True)
        )
        if (
            any(
                not isinstance(value, str) or not value or value != value.strip()
                for value in (
                    self.task_id,
                    self.from_stage,
                    self.to_stage,
                    self.edge_class,
                    self.edge_projection_role,
                    self.edge_authority_capability,
                    self.authority_case,
                    self.actor,
                    self.origin,
                )
            )
            or type(self.lifecycle_source) is not bytes
            or self.from_stage != self.lifecycle_definition_binding.from_stage
            or self.to_stage != self.lifecycle_definition_binding.to_stage
            or self.edge_class != self.lifecycle_definition_binding.edge_class
            or self.edge_projection_role != self.lifecycle_definition_binding.projection_role
            or self.edge_authority_capability
            != self.lifecycle_definition_binding.authority_capability
            or checked_definition.source_ref != self.lifecycle_definition_binding.source_label
            or checked_definition.source_hash != _sha256(self.lifecycle_source)
            or checked_definition.definition_ref != self.lifecycle_definition_binding.definition_ref
            or set(self.no_go_snapshot) != set(NO_GO_BOOLEANS)
            or any(type(value) is not bool for value in self.no_go_snapshot.values())
            or set(self.guard_evidence) != set(self.lifecycle_definition_binding.guards)
            or any(
                not isinstance(refs, tuple)
                or not refs
                or any(not isinstance(ref, str) or not ref or ref != ref.strip() for ref in refs)
                for refs in self.guard_evidence.values()
            )
            or any(
                value is not None and not isinstance(value, str)
                for value in (
                    self.parent_spec,
                    self.predecessor_position_ref,
                    self.echo_receipt_ref,
                    self.evidence_type,
                    self.evidence_summary,
                )
            )
        ):
            raise LifecycleTransitionError(
                "transition_intent_shape_malformed",
                "construct one canonical immutable lifecycle intent",
                self.task_id if isinstance(self.task_id, str) else None,
            )
        object.__setattr__(self, "lifecycle_definition", checked_definition)
        object.__setattr__(
            self,
            "no_go_snapshot",
            MappingProxyType(
                {key: self.no_go_snapshot[key] for key in sorted(self.no_go_snapshot)}
            ),
        )
        object.__setattr__(
            self,
            "guard_evidence",
            MappingProxyType(
                {key: tuple(self.guard_evidence[key]) for key in sorted(self.guard_evidence)}
            ),
        )

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        from_stage: str,
        to_stage: str,
        edge_class: str = "auto",
        authority_case: str,
        actor: str,
        no_go_snapshot: Mapping[str, bool],
        guard_evidence: Mapping[str, Sequence[str]],
        parent_spec: str | None = None,
        predecessor_position_ref: str | None = None,
        echo_receipt_ref: str | None = None,
        evidence_type: str | None = None,
        evidence_summary: str | None = None,
        origin: str = "cli",
        lifecycle_definition: LifecycleDefinition | None = None,
        lifecycle_source: bytes | None = None,
        definition_binding: LifecycleDefinitionBinding | None = None,
    ) -> LifecycleTransitionIntent:
        if (lifecycle_definition is None) != (lifecycle_source is None):
            raise LifecycleTransitionError(
                "transition_lifecycle_capture_incomplete",
                "supply both the exact lifecycle definition and its source bytes",
            )
        if lifecycle_definition is None:
            lifecycle_definition, lifecycle_source = _capture_current_lifecycle_definition()
        assert lifecycle_source is not None
        checked_definition = LifecycleDefinition.model_validate(
            lifecycle_definition.model_dump(mode="json", by_alias=True)
        )
        if definition_binding is None:
            selected_binding = LifecycleDefinitionBinding.create(
                checked_definition,
                lifecycle_source,
                from_stage=from_stage,
                to_stage=to_stage,
                edge_class=edge_class,
            )
        else:
            selected_binding = LifecycleDefinitionBinding.from_attested_definition(
                checked_definition,
                lifecycle_source,
                compiler_ref=definition_binding.compiler_ref,
                from_stage=from_stage,
                to_stage=to_stage,
                edge_class=edge_class,
            )
            if selected_binding != definition_binding:
                raise LifecycleTransitionError(
                    "transition_lifecycle_binding_mismatch",
                    "bind the intent to the exact stored lifecycle definition and edge",
                    selected_binding.binding_ref,
                )
        if not task_id.strip() or not authority_case.strip() or not actor.strip():
            raise LifecycleTransitionError(
                "transition_identity_missing",
                "bind task_id, authority_case, and actor before preparing a transition",
            )
        snapshot = dict(no_go_snapshot)
        if set(snapshot) != set(NO_GO_BOOLEANS) or any(
            not isinstance(value, bool) for value in snapshot.values()
        ):
            raise LifecycleTransitionError(
                "transition_no_go_snapshot_malformed",
                "record the exact canonical no-go key set with boolean values",
            )
        evidence: dict[str, tuple[str, ...]] = {}
        for key, value in guard_evidence.items():
            if isinstance(value, (str, bytes)):
                raise LifecycleTransitionError(
                    "transition_guard_evidence_malformed",
                    "record every guard's evidence as a sequence of durable refs",
                    str(key),
                )
            evidence[str(key)] = tuple(value)
        if set(evidence) != set(selected_binding.guards) or any(
            not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs)
            for refs in evidence.values()
        ):
            raise LifecycleTransitionError(
                "transition_guard_evidence_incomplete",
                "bind at least one durable evidence ref to every exact edge guard and no others",
                ",".join(selected_binding.guards),
            )
        return cls(
            task_id=task_id,
            from_stage=selected_binding.from_stage,
            to_stage=selected_binding.to_stage,
            edge_class=selected_binding.edge_class,
            edge_projection_role=selected_binding.projection_role,
            edge_authority_capability=selected_binding.authority_capability,
            authority_case=authority_case,
            actor=actor,
            no_go_snapshot={key: snapshot[key] for key in sorted(snapshot)},
            guard_evidence={key: evidence[key] for key in sorted(evidence)},
            lifecycle_definition_binding=selected_binding,
            lifecycle_definition=checked_definition,
            lifecycle_source=lifecycle_source,
            parent_spec=parent_spec,
            predecessor_position_ref=predecessor_position_ref,
            echo_receipt_ref=echo_receipt_ref,
            evidence_type=evidence_type,
            evidence_summary=evidence_summary,
            origin=origin,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "authority_case": self.authority_case,
            "echo_receipt_ref": self.echo_receipt_ref,
            "edge_authority_capability": self.edge_authority_capability,
            "edge_class": self.edge_class,
            "edge_projection_role": self.edge_projection_role,
            "evidence_summary": self.evidence_summary,
            "evidence_type": self.evidence_type,
            "from_stage": self.from_stage,
            "guard_evidence": {
                key: list(self.guard_evidence[key]) for key in sorted(self.guard_evidence)
            },
            "lifecycle_definition_binding": self.lifecycle_definition_binding.to_record(),
            "no_go_snapshot": dict(self.no_go_snapshot),
            "origin": self.origin,
            "parent_spec": self.parent_spec,
            "predecessor_position_ref": self.predecessor_position_ref,
            "task_id": self.task_id,
            "to_stage": self.to_stage,
        }

    @classmethod
    def from_record(
        cls,
        value: Mapping[str, Any],
        *,
        lifecycle_definition: LifecycleDefinition,
        lifecycle_source: bytes,
    ) -> LifecycleTransitionIntent:
        exact_keys = {
            "actor",
            "authority_case",
            "echo_receipt_ref",
            "edge_authority_capability",
            "edge_class",
            "edge_projection_role",
            "evidence_summary",
            "evidence_type",
            "from_stage",
            "guard_evidence",
            "lifecycle_definition_binding",
            "no_go_snapshot",
            "origin",
            "parent_spec",
            "predecessor_position_ref",
            "task_id",
            "to_stage",
        }
        if set(value) != exact_keys or not isinstance(
            value.get("lifecycle_definition_binding"), Mapping
        ):
            raise LifecycleTransitionError(
                "transition_intent_record_malformed",
                "restore the exact v2 lifecycle transition intent record",
            )
        binding = LifecycleDefinitionBinding.from_record(value["lifecycle_definition_binding"])
        intent = cls.create(
            task_id=str(value["task_id"]),
            from_stage=str(value["from_stage"]),
            to_stage=str(value["to_stage"]),
            edge_class=str(value["edge_class"]),
            authority_case=str(value["authority_case"]),
            actor=str(value["actor"]),
            no_go_snapshot=dict(value.get("no_go_snapshot") or {}),
            guard_evidence={
                str(key): tuple(str(item) for item in refs)
                for key, refs in dict(value.get("guard_evidence") or {}).items()
            },
            parent_spec=_optional_str(value.get("parent_spec")),
            predecessor_position_ref=_optional_str(value.get("predecessor_position_ref")),
            echo_receipt_ref=_optional_str(value.get("echo_receipt_ref")),
            evidence_type=_optional_str(value.get("evidence_type")),
            evidence_summary=_optional_str(value.get("evidence_summary")),
            origin=str(value.get("origin") or "cli"),
            lifecycle_definition=lifecycle_definition,
            lifecycle_source=lifecycle_source,
            definition_binding=binding,
        )
        if (
            value.get("edge_projection_role") != intent.edge_projection_role
            or value.get("edge_authority_capability") != intent.edge_authority_capability
        ):
            raise LifecycleTransitionError(
                "transition_edge_metadata_mismatch",
                "restore the intent bound to the checked lifecycle edge metadata",
                f"{intent.from_stage}->{intent.to_stage}:{intent.edge_class}",
            )
        if intent.to_record() != dict(value):
            raise LifecycleTransitionError(
                "transition_intent_record_malformed",
                "restore the canonical intent bound to its lifecycle definition",
                intent.task_id,
            )
        return intent


@dataclass(frozen=True)
class _EntryState:
    content: bytes
    mode: int
    uid: int
    nlink: int
    device: int
    inode: int


def _normalized_path(path: Path) -> Path:
    expanded = os.path.expanduser(os.fspath(path))
    return Path(os.path.abspath(expanded))


@contextmanager
def _open_parent_dir(path: Path):
    normalized = _normalized_path(path)
    if normalized.name in {"", ".", ".."}:
        raise LifecycleTransitionError(
            "transition_projection_path_unsafe",
            "project one named entry below an absolute non-symlink directory",
            str(path),
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for component in normalized.parent.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd, normalized.name
    except OSError as exc:
        raise LifecycleTransitionError(
            "transition_projection_parent_unsafe",
            "restore every projection parent as a real non-symlink directory",
            str(normalized.parent),
        ) from exc
    finally:
        os.close(fd)


def _entry_state_at(
    dir_fd: int,
    name: str,
    *,
    max_bytes: int,
) -> _EntryState | None:
    try:
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NOATIME,
            dir_fd=dir_fd,
        )
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LifecycleTransitionError(
            "transition_projection_path_unsafe",
            "project only absent paths or regular non-symlink files",
            name,
        ) from exc
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
        ):
            raise LifecycleTransitionError(
                "transition_projection_path_unsafe",
                "project only absent paths or euid-owned single-link regular files",
                name,
            )
        if metadata.st_size > max_bytes:
            raise LifecycleTransitionError(
                "transition_file_bound_exceeded",
                "restore a bounded lifecycle projection or journal artifact",
                f"{name}:{metadata.st_size}>{max_bytes}",
            )
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while True:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
            if remaining == 0:
                raise LifecycleTransitionError(
                    "transition_file_bound_exceeded",
                    "restore a bounded lifecycle projection or journal artifact",
                    f"{name}:>{max_bytes}",
                )
        final_metadata = os.fstat(fd)
        content = b"".join(chunks)
        if (
            final_metadata.st_dev != metadata.st_dev
            or final_metadata.st_ino != metadata.st_ino
            or final_metadata.st_size != len(content)
            or final_metadata.st_size != metadata.st_size
        ):
            raise LifecycleTransitionError(
                "transition_file_changed_during_read",
                "retry after the lifecycle file identity and size stabilize",
                name,
            )
        return _EntryState(
            content=content,
            mode=metadata.st_mode & 0o777,
            uid=metadata.st_uid,
            nlink=metadata.st_nlink,
            device=metadata.st_dev,
            inode=metadata.st_ino,
        )
    finally:
        os.close(fd)


def _file_state(path: Path) -> tuple[bytes | None, int | None]:
    with _open_parent_dir(path) as (dir_fd, name):
        state = _entry_state_at(
            dir_fd,
            name,
            max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
        )
    return (None, None) if state is None else (state.content, state.mode)


def _private_file_state(path: Path, *, max_bytes: int) -> _EntryState | None:
    with _open_parent_dir(path) as (dir_fd, name):
        state = _entry_state_at(dir_fd, name, max_bytes=max_bytes)
    if state is None:
        return None
    if state.uid != os.geteuid() or state.nlink != 1 or state.mode != 0o600:
        raise LifecycleTransitionError(
            "transition_private_file_unsafe",
            "use one euid-owned single-link mode-0600 transaction file",
            str(path),
        )
    return state


def _load_private_manifest_payload(
    path: Path,
    *,
    content: bytes | None = None,
) -> dict[str, Any]:
    def unique_pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in values:
            if key in output:
                raise LifecycleTransitionError(
                    "transition_manifest_duplicate_key",
                    "remove duplicate JSON keys from the transaction manifest",
                    f"{path}:{key}",
                )
            output[key] = value
        return output

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        if content is None:
            state = _private_file_state(
                path,
                max_bytes=_MAX_LIFECYCLE_MANIFEST_BYTES,
            )
            if state is None:
                raise FileNotFoundError(path)
            payload_bytes = state.content
        else:
            payload_bytes = content
        text = payload_bytes.decode("ascii")
        payload = json.loads(
            text,
            object_pairs_hook=unique_pairs,
            parse_constant=reject_constant,
        )
    except LifecycleTransitionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise LifecycleTransitionError(
            "transition_manifest_malformed",
            "restore or quarantine the malformed durable transaction manifest",
            str(path),
        ) from exc
    if not isinstance(payload, dict):
        raise LifecycleTransitionError(
            "transition_manifest_malformed",
            "restore the transaction manifest as one canonical JSON object",
            str(path),
        )
    try:
        canonical = _canonical_json_bytes(payload) + b"\n"
    except (TypeError, ValueError) as exc:
        raise LifecycleTransitionError(
            "transition_manifest_malformed",
            "restore the transaction manifest as one canonical JSON object",
            str(path),
        ) from exc
    if payload_bytes != canonical:
        raise LifecycleTransitionError(
            "transition_manifest_noncanonical",
            "restore the exact canonical transaction manifest bytes",
            str(path),
        )
    return payload


@dataclass(frozen=True)
class FileProjection:
    """Exact preimage/postimage pair for one filesystem projection."""

    path: Path
    before: bytes | None
    after: bytes | None
    before_mode: int | None
    after_mode: int | None

    def __post_init__(self) -> None:
        normalized = _normalized_path(self.path)
        object.__setattr__(self, "path", normalized)
        for label, payload, mode in (
            ("before", self.before, self.before_mode),
            ("after", self.after, self.after_mode),
        ):
            if (
                payload is not None
                and type(payload) is not bytes
                or (payload is None) != (mode is None)
                or (mode is not None and (type(mode) is not int or not 0 <= mode <= 0o777))
            ):
                raise LifecycleTransitionError(
                    "transition_projection_shape_malformed",
                    "bind presence and a valid permission mode consistently",
                    f"{self.path}:{label}",
                )

    @classmethod
    def capture(
        cls,
        path: Path,
        *,
        after: bytes | None,
        after_mode: int | None = None,
    ) -> FileProjection:
        resolved = _normalized_path(path)
        before, before_mode = _file_state(resolved)
        if after is not None and after_mode is None:
            after_mode = before_mode if before_mode is not None else 0o644
        if after is None:
            after_mode = None
        return cls(
            path=resolved,
            before=before,
            after=after,
            before_mode=before_mode,
            after_mode=after_mode,
        )

    @classmethod
    def from_snapshot(
        cls,
        path: Path,
        *,
        before: bytes | None,
        before_mode: int | None,
        after: bytes | None,
        after_mode: int | None = None,
    ) -> FileProjection:
        """Construct from caller-held exact bytes without rereading the path."""

        if after is not None and after_mode is None:
            after_mode = before_mode if before_mode is not None else 0o644
        return cls(
            path=_normalized_path(path),
            before=before,
            after=after,
            before_mode=before_mode,
            after_mode=after_mode,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "after_mode": self.after_mode,
            "after_present": self.after is not None,
            "after_sha256": _sha256(self.after) if self.after is not None else None,
            "before_mode": self.before_mode,
            "before_present": self.before is not None,
            "before_sha256": _sha256(self.before) if self.before is not None else None,
            "path": str(self.path),
        }


@dataclass(frozen=True)
class LifecycleTransitionReceipt:
    operation_id: str
    attempt_no: int
    transaction_id: str
    prepared_event_id: str
    applied_event_id: str
    prepared_sequence: int | None
    applied_sequence: int | None
    manifest_path: Path
    replayed: bool = False


@dataclass(frozen=True)
class LifecycleRecoveryResult:
    transaction_id: str
    state: str
    reason_code: str | None = None


@dataclass(frozen=True)
class LifecycleMaterializationPlan:
    """Single-file, self-hashed source for resuming initial journal assembly."""

    transaction_id: str
    artifacts: tuple[tuple[str, bytes], ...]
    plan_ref: str
    plan_hash: str
    may_authorize: Literal[False] = False
    schema: str = MATERIALIZATION_PLAN_SCHEMA

    def body(self) -> dict[str, Any]:
        return {
            "artifacts": [
                {
                    "content_base64": base64.b64encode(content).decode("ascii"),
                    "name": name,
                    "sha256": _sha256(content),
                    "size": len(content),
                }
                for name, content in self.artifacts
            ],
            "may_authorize": False,
            "schema": MATERIALIZATION_PLAN_SCHEMA,
            "transaction_id": self.transaction_id,
        }

    def to_record(self) -> dict[str, Any]:
        return {**self.body(), "plan_hash": self.plan_hash, "plan_ref": self.plan_ref}

    def payload(self) -> bytes:
        payload = _canonical_json_bytes(self.to_record()) + b"\n"
        if len(payload) > _MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES:
            raise LifecycleTransitionError(
                "transition_materialization_plan_bound_exceeded",
                "decompose the transition before creating its recovery plan",
                self.transaction_id,
            )
        return payload

    def artifact(self, name: str) -> bytes:
        try:
            return dict(self.artifacts)[name]
        except KeyError as exc:
            raise LifecycleTransitionError(
                "transition_materialization_plan_artifact_missing",
                "restore every artifact named by the recovery plan",
                f"{self.transaction_id}:{name}",
            ) from exc

    def __post_init__(self) -> None:
        names = tuple(name for name, _content in self.artifacts)
        artifacts = dict(self.artifacts)
        required = {
            "manifest.json",
            _LIFECYCLE_SOURCE_BLOB,
            _LIFECYCLE_DEFINITION_BLOB,
        }
        if (
            self.schema != MATERIALIZATION_PLAN_SCHEMA
            or self.may_authorize is not False
            or _TRANSACTION_DIRECTORY_RE.fullmatch(self.transaction_id) is None
            or names != tuple(sorted(names))
            or len(names) != len(set(names))
            or not required.issubset(names)
            or any(
                name not in required and _TRANSACTION_BLOB_RE.fullmatch(name) is None
                for name in names
            )
            or len(names) + 2 > _MAX_LIFECYCLE_JOURNAL_CHILDREN
            or len(artifacts.get("manifest.json", b"")) > _MAX_LIFECYCLE_MANIFEST_BYTES
            or any(
                len(content) > _MAX_LIFECYCLE_BLOB_BYTES
                for name, content in self.artifacts
                if name != "manifest.json"
            )
            or sum(len(content) for _name, content in self.artifacts)
            + 2 * _MAX_LIFECYCLE_PHASE_BYTES
            > _MAX_LIFECYCLE_JOURNAL_BYTES
        ):
            raise ValueError("lifecycle materialization plan shape is invalid")
        digest = _domain_hash(MATERIALIZATION_PLAN_SCHEMA, self.body())
        if self.plan_hash != digest or self.plan_ref != (
            f"lifecycle-materialization-plan@sha256:{digest}"
        ):
            raise ValueError("lifecycle materialization plan identity mismatch")

    @classmethod
    def create(
        cls,
        transaction_id: str,
        artifacts: Mapping[str, bytes],
    ) -> LifecycleMaterializationPlan:
        checked = tuple(sorted(artifacts.items()))
        body = {
            "artifacts": [
                {
                    "content_base64": base64.b64encode(content).decode("ascii"),
                    "name": name,
                    "sha256": _sha256(content),
                    "size": len(content),
                }
                for name, content in checked
            ],
            "may_authorize": False,
            "schema": MATERIALIZATION_PLAN_SCHEMA,
            "transaction_id": transaction_id,
        }
        digest = _domain_hash(MATERIALIZATION_PLAN_SCHEMA, body)
        plan = cls(
            transaction_id=transaction_id,
            artifacts=checked,
            plan_ref=f"lifecycle-materialization-plan@sha256:{digest}",
            plan_hash=digest,
        )
        plan.payload()
        return plan

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> LifecycleMaterializationPlan:
        exact = {
            "artifacts",
            "may_authorize",
            "plan_hash",
            "plan_ref",
            "schema",
            "transaction_id",
        }
        raw_artifacts = value.get("artifacts")
        if (
            set(value) != exact
            or value.get("schema") != MATERIALIZATION_PLAN_SCHEMA
            or value.get("may_authorize") is not False
            or not isinstance(value.get("transaction_id"), str)
            or not isinstance(value.get("plan_ref"), str)
            or not isinstance(value.get("plan_hash"), str)
            or not isinstance(raw_artifacts, list)
        ):
            raise ValueError("lifecycle materialization plan record is malformed")
        artifacts: list[tuple[str, bytes]] = []
        for item in raw_artifacts:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"content_base64", "name", "sha256", "size"}
                or not isinstance(item.get("name"), str)
                or not isinstance(item.get("content_base64"), str)
                or not isinstance(item.get("sha256"), str)
                or type(item.get("size")) is not int
            ):
                raise ValueError("materialization artifact record is malformed")
            try:
                content = base64.b64decode(item["content_base64"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("materialization artifact base64 is invalid") from exc
            if len(content) != item["size"] or _sha256(content) != item["sha256"]:
                raise ValueError("materialization artifact identity mismatch")
            artifacts.append((item["name"], content))
        checked = cls(
            transaction_id=value["transaction_id"],
            artifacts=tuple(artifacts),
            plan_ref=value["plan_ref"],
            plan_hash=value["plan_hash"],
        )
        if checked.to_record() != dict(value):
            raise ValueError("lifecycle materialization plan record is noncanonical")
        checked.payload()
        return checked


def _load_materialization_plan(
    path: Path,
    *,
    content: bytes | None = None,
) -> LifecycleMaterializationPlan:
    if content is None:
        state = _private_file_state(
            path,
            max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
        )
        if state is None:
            raise LifecycleTransitionError(
                "transition_materialization_plan_missing",
                "restore the self-contained materialization recovery plan",
                str(path),
            )
        content = state.content
    try:
        payload = _load_private_manifest_payload(path, content=content)
        plan = LifecycleMaterializationPlan.from_record(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise LifecycleTransitionError(
            "transition_materialization_plan_malformed",
            "restore the exact canonical self-hashed recovery plan",
            str(path),
        ) from exc
    if plan.payload() != content:
        raise LifecycleTransitionError(
            "transition_materialization_plan_noncanonical",
            "restore the canonical recovery plan bytes",
            str(path),
        )
    return plan


@dataclass(frozen=True)
class LifecycleReceiptFrontierEntry:
    """One immutable, non-authorizing phase receipt in the inspected frontier."""

    transaction_id: str
    phase: Literal["prepared", "applied", "aborted"]
    event_id: str
    event_sha256: str
    ledger_path: str
    sequence: int
    projection_ref: str

    def __post_init__(self) -> None:
        if (
            not self.transaction_id
            or self.event_id != f"{self.transaction_id}.{self.phase}"
            or re.fullmatch(r"[0-9a-f]{64}", self.event_sha256) is None
            or not Path(self.ledger_path).is_absolute()
            or self.sequence <= 0
            or re.fullmatch(
                r"lifecycle-phase-append@sha256:[0-9a-f]{64}",
                self.projection_ref,
            )
            is None
        ):
            raise ValueError("lifecycle receipt frontier entry is invalid")

    def to_record(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_sha256": self.event_sha256,
            "ledger_path": self.ledger_path,
            "phase": self.phase,
            "projection_ref": self.projection_ref,
            "sequence": self.sequence,
            "transaction_id": self.transaction_id,
        }

    @classmethod
    def from_projection(
        cls,
        projection: LifecyclePhaseAppendProjection,
    ) -> LifecycleReceiptFrontierEntry:
        return cls(
            transaction_id=projection.transaction_id,
            phase=projection.phase,
            event_id=projection.event.event_id,
            event_sha256=_sha256(_canonical_json_bytes(projection.event.to_record())),
            ledger_path=projection.ledger_path,
            sequence=projection.sequence,
            projection_ref=projection.projection_ref,
        )


@dataclass(frozen=True)
class LifecycleTransactionInspection:
    """Self-hashed read-only classification of one captured journal."""

    transaction_id: str
    task_id: str | None
    operation_id: str | None
    manifest_schema: str | None
    manifest_sha256: str | None
    lifecycle_definition_ref: str | None
    state: Literal["applied", "aborted", "not_started", "prepared", "hold"]
    recovery_required: bool
    reason_codes: tuple[str, ...]
    phase_frontier: tuple[LifecycleReceiptFrontierEntry, ...]
    inspection_ref: str
    inspection_hash: str
    may_authorize: Literal[False] = False
    schema: str = "hapax.sdlc-lifecycle-transaction-inspection.v1"

    def body(self) -> dict[str, Any]:
        return {
            "lifecycle_definition_ref": self.lifecycle_definition_ref,
            "manifest_schema": self.manifest_schema,
            "manifest_sha256": self.manifest_sha256,
            "may_authorize": False,
            "operation_id": self.operation_id,
            "phase_frontier": [item.to_record() for item in self.phase_frontier],
            "reason_codes": list(self.reason_codes),
            "recovery_required": self.recovery_required,
            "schema": self.schema,
            "state": self.state,
            "task_id": self.task_id,
            "transaction_id": self.transaction_id,
        }

    def to_record(self) -> dict[str, Any]:
        return {
            **self.body(),
            "inspection_hash": self.inspection_hash,
            "inspection_ref": self.inspection_ref,
        }

    def __post_init__(self) -> None:
        if (
            self.schema != "hapax.sdlc-lifecycle-transaction-inspection.v1"
            or self.may_authorize is not False
            or not self.transaction_id
            or (
                self.operation_id is not None
                and re.fullmatch(r"sdlc-txn-[0-9a-f]{64}", self.operation_id) is None
            )
            or (
                self.manifest_sha256 is not None
                and re.fullmatch(r"[0-9a-f]{64}", self.manifest_sha256) is None
            )
            or (
                self.lifecycle_definition_ref is not None
                and re.fullmatch(
                    r"lifecycle-definition@sha256:[0-9a-f]{64}",
                    self.lifecycle_definition_ref,
                )
                is None
            )
            or self.reason_codes != tuple(sorted(set(self.reason_codes)))
            or (self.recovery_required and not self.reason_codes)
            or any(item.transaction_id != self.transaction_id for item in self.phase_frontier)
            or tuple(
                sorted(
                    self.phase_frontier,
                    key=lambda item: (item.ledger_path, item.sequence, item.event_id),
                )
            )
            != self.phase_frontier
            or (self.state in {"hold", "not_started", "prepared"} and not self.recovery_required)
        ):
            raise ValueError("lifecycle transaction inspection shape is invalid")
        digest = _domain_hash(self.schema, self.body())
        if self.inspection_hash != digest or self.inspection_ref != (
            f"lifecycle-transaction-inspection@sha256:{digest}"
        ):
            raise ValueError("lifecycle transaction inspection identity mismatch")

    @classmethod
    def create(
        cls,
        *,
        transaction_id: str,
        task_id: str | None,
        operation_id: str | None,
        manifest_schema: str | None,
        manifest_sha256: str | None,
        lifecycle_definition_ref: str | None,
        state: Literal["applied", "aborted", "not_started", "prepared", "hold"],
        recovery_required: bool,
        reason_codes: Sequence[str] = (),
        phase_frontier: Sequence[LifecycleReceiptFrontierEntry] = (),
    ) -> LifecycleTransactionInspection:
        checked_reasons = tuple(sorted(set(reason_codes)))
        checked_frontier = tuple(
            sorted(
                phase_frontier,
                key=lambda item: (item.ledger_path, item.sequence, item.event_id),
            )
        )
        body = {
            "lifecycle_definition_ref": lifecycle_definition_ref,
            "manifest_schema": manifest_schema,
            "manifest_sha256": manifest_sha256,
            "may_authorize": False,
            "operation_id": operation_id,
            "phase_frontier": [item.to_record() for item in checked_frontier],
            "reason_codes": list(checked_reasons),
            "recovery_required": recovery_required,
            "schema": "hapax.sdlc-lifecycle-transaction-inspection.v1",
            "state": state,
            "task_id": task_id,
            "transaction_id": transaction_id,
        }
        digest = _domain_hash(body["schema"], body)
        return cls(
            transaction_id=transaction_id,
            task_id=task_id,
            operation_id=operation_id,
            manifest_schema=manifest_schema,
            manifest_sha256=manifest_sha256,
            lifecycle_definition_ref=lifecycle_definition_ref,
            state=state,
            recovery_required=recovery_required,
            reason_codes=checked_reasons,
            phase_frontier=checked_frontier,
            inspection_ref=f"lifecycle-transaction-inspection@sha256:{digest}",
            inspection_hash=digest,
        )


@dataclass(frozen=True)
class LifecycleInspectionEnvelope:
    """Sealed estate inspection; evidence only and never action authority."""

    task_id: str | None
    transactions: tuple[LifecycleTransactionInspection, ...]
    estate_transaction_refs: tuple[str, ...]
    scope_transaction_refs: tuple[str, ...]
    receipt_frontier: tuple[LifecycleReceiptFrontierEntry, ...]
    fs_seal_ref: str | None
    fs_seal_hash: str | None
    event_plane_snapshot_ref: str | None
    event_plane_snapshot_hash: str | None
    event_plane_frontier_ref: str | None
    observed_at: str
    complete: bool
    estate_complete: bool
    scope_complete: bool
    reason_codes: tuple[str, ...]
    envelope_ref: str
    envelope_hash: str
    may_authorize: Literal[False] = False
    schema: str = LIFECYCLE_INSPECTION_SCHEMA

    def body(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "estate_complete": self.estate_complete,
            "estate_transaction_refs": list(self.estate_transaction_refs),
            "event_plane_frontier_ref": self.event_plane_frontier_ref,
            "event_plane_snapshot_hash": self.event_plane_snapshot_hash,
            "event_plane_snapshot_ref": self.event_plane_snapshot_ref,
            "fs_seal_hash": self.fs_seal_hash,
            "fs_seal_ref": self.fs_seal_ref,
            "may_authorize": False,
            "observed_at": self.observed_at,
            "reason_codes": list(self.reason_codes),
            "receipt_frontier": [item.to_record() for item in self.receipt_frontier],
            "schema": LIFECYCLE_INSPECTION_SCHEMA,
            "scope_complete": self.scope_complete,
            "scope_transaction_refs": list(self.scope_transaction_refs),
            "task_id": self.task_id,
            "transactions": [item.to_record() for item in self.transactions],
        }

    def to_record(self) -> dict[str, Any]:
        return {
            **self.body(),
            "envelope_hash": self.envelope_hash,
            "envelope_ref": self.envelope_ref,
        }

    def __post_init__(self) -> None:
        transaction_ids = tuple(item.transaction_id for item in self.transactions)
        exact_estate_refs = tuple(sorted(item.inspection_ref for item in self.transactions))
        exact_scope_refs = tuple(
            sorted(
                item.inspection_ref
                for item in self.transactions
                if self.task_id is None or item.task_id == self.task_id or item.task_id is None
            )
        )
        exact_frontier = tuple(
            sorted(
                (
                    frontier
                    for transaction in self.transactions
                    for frontier in transaction.phase_frontier
                ),
                key=lambda item: (item.ledger_path, item.sequence, item.event_id),
            )
        )
        if (
            self.schema != LIFECYCLE_INSPECTION_SCHEMA
            or self.may_authorize is not False
            or type(self.complete) is not bool
            or type(self.estate_complete) is not bool
            or type(self.scope_complete) is not bool
            or self.transactions
            != tuple(sorted(self.transactions, key=lambda item: item.transaction_id))
            or len(set(transaction_ids)) != len(transaction_ids)
            or self.estate_transaction_refs != exact_estate_refs
            or self.scope_transaction_refs != exact_scope_refs
            or self.receipt_frontier != exact_frontier
            or self.reason_codes != tuple(sorted(set(self.reason_codes)))
            or self.complete != self.scope_complete
            or (self.task_id is None and self.estate_complete != self.scope_complete)
            or (self.estate_complete and any(item.recovery_required for item in self.transactions))
            or (self.fs_seal_ref is None) != (self.fs_seal_hash is None)
            or (
                self.fs_seal_hash is not None
                and (
                    re.fullmatch(r"[0-9a-f]{64}", self.fs_seal_hash) is None
                    or self.fs_seal_ref != f"read-only-fs-snapshot@sha256:{self.fs_seal_hash}"
                )
            )
            or ((self.event_plane_snapshot_ref is None) != (self.event_plane_snapshot_hash is None))
            or (
                self.event_plane_snapshot_hash is None and self.event_plane_frontier_ref is not None
            )
            or (
                self.event_plane_snapshot_hash is not None
                and (
                    re.fullmatch(r"[0-9a-f]{64}", self.event_plane_snapshot_hash) is None
                    or self.event_plane_snapshot_ref
                    != "coord-replay-snapshot@sha256:" + self.event_plane_snapshot_hash
                    or self.event_plane_frontier_ref is None
                    or re.fullmatch(
                        r"coord-event-frontier@sha256:[0-9a-f]{64}",
                        self.event_plane_frontier_ref,
                    )
                    is None
                )
            )
            or (
                self.scope_complete
                and any(
                    item.recovery_required
                    for item in self.transactions
                    if self.task_id is None or item.task_id == self.task_id or item.task_id is None
                )
            )
            or (self.complete and self.event_plane_snapshot_ref is None)
        ):
            raise ValueError("lifecycle inspection envelope shape is invalid")
        digest = _domain_hash(LIFECYCLE_INSPECTION_SCHEMA, self.body())
        if self.envelope_hash != digest or self.envelope_ref != (
            f"lifecycle-inspection@sha256:{digest}"
        ):
            raise ValueError("lifecycle inspection envelope identity mismatch")

    @classmethod
    def create(
        cls,
        *,
        task_id: str | None,
        transactions: Sequence[LifecycleTransactionInspection],
        estate_transaction_refs: Sequence[str],
        receipt_frontier: Sequence[LifecycleReceiptFrontierEntry],
        fs_seal: FsSnapshotSeal | None,
        event_plane_snapshot: CoordReplaySnapshot | None,
        estate_complete: bool,
        scope_complete: bool,
        reason_codes: Sequence[str] = (),
        observed_at: str | None = None,
    ) -> LifecycleInspectionEnvelope:
        checked_transactions = tuple(sorted(transactions, key=lambda item: item.transaction_id))
        checked_estate_refs = tuple(sorted(set(estate_transaction_refs)))
        checked_scope_refs = tuple(
            sorted(
                item.inspection_ref
                for item in checked_transactions
                if task_id is None or item.task_id == task_id or item.task_id is None
            )
        )
        checked_frontier = tuple(
            sorted(
                receipt_frontier,
                key=lambda item: (item.ledger_path, item.sequence, item.event_id),
            )
        )
        checked_reasons = tuple(sorted(set(reason_codes)))
        timestamp = observed_at or _now_iso()
        body = {
            "complete": scope_complete,
            "estate_complete": estate_complete,
            "estate_transaction_refs": list(checked_estate_refs),
            "event_plane_frontier_ref": (
                None if event_plane_snapshot is None else event_plane_snapshot.frontier_ref
            ),
            "event_plane_snapshot_hash": (
                None if event_plane_snapshot is None else event_plane_snapshot.snapshot_hash
            ),
            "event_plane_snapshot_ref": (
                None if event_plane_snapshot is None else event_plane_snapshot.snapshot_ref
            ),
            "fs_seal_hash": None if fs_seal is None else fs_seal.seal_hash,
            "fs_seal_ref": None if fs_seal is None else fs_seal.seal_ref,
            "may_authorize": False,
            "observed_at": timestamp,
            "reason_codes": list(checked_reasons),
            "receipt_frontier": [item.to_record() for item in checked_frontier],
            "schema": LIFECYCLE_INSPECTION_SCHEMA,
            "scope_complete": scope_complete,
            "scope_transaction_refs": list(checked_scope_refs),
            "task_id": task_id,
            "transactions": [item.to_record() for item in checked_transactions],
        }
        digest = _domain_hash(LIFECYCLE_INSPECTION_SCHEMA, body)
        return cls(
            task_id=task_id,
            transactions=checked_transactions,
            estate_transaction_refs=checked_estate_refs,
            scope_transaction_refs=checked_scope_refs,
            receipt_frontier=checked_frontier,
            fs_seal_ref=None if fs_seal is None else fs_seal.seal_ref,
            fs_seal_hash=None if fs_seal is None else fs_seal.seal_hash,
            event_plane_snapshot_ref=(
                None if event_plane_snapshot is None else event_plane_snapshot.snapshot_ref
            ),
            event_plane_snapshot_hash=(
                None if event_plane_snapshot is None else event_plane_snapshot.snapshot_hash
            ),
            event_plane_frontier_ref=(
                None if event_plane_snapshot is None else event_plane_snapshot.frontier_ref
            ),
            observed_at=timestamp,
            complete=scope_complete,
            estate_complete=estate_complete,
            scope_complete=scope_complete,
            reason_codes=checked_reasons,
            envelope_ref=f"lifecycle-inspection@sha256:{digest}",
            envelope_hash=digest,
        )


@dataclass(frozen=True)
class LifecyclePhaseAppendProjection:
    """Immutable source-local projection of one canonical phase append receipt."""

    operation_id: str
    transaction_id: str
    attempt_no: int
    phase: Literal["prepared", "applied", "aborted"]
    event: CoordEvent
    ledger_path: str
    sequence: int
    prior_projection_ref: str | None
    projection_ref: str
    projection_hash: str
    may_authorize: Literal[False] = False
    schema: str = PHASE_APPEND_PROJECTION_SCHEMA
    transaction_schema: str = TRANSITION_TRANSACTION_SCHEMA_V2

    def body(self) -> dict[str, Any]:
        return {
            "append_receipt": {
                "appended": True,
                "ledger_path": self.ledger_path,
                "sequence": self.sequence,
                "spooled": False,
            },
            "attempt_no": self.attempt_no,
            "event": self.event.to_record(),
            "may_authorize": False,
            "operation_id": self.operation_id,
            "phase": self.phase,
            "prior_projection_ref": self.prior_projection_ref,
            "schema": PHASE_APPEND_PROJECTION_SCHEMA,
            "transaction_id": self.transaction_id,
            "transaction_schema": TRANSITION_TRANSACTION_SCHEMA_V2,
        }

    def to_record(self) -> dict[str, Any]:
        return {
            **self.body(),
            "projection_hash": self.projection_hash,
            "projection_ref": self.projection_ref,
        }

    def __post_init__(self) -> None:
        expected_prior = self.phase != "prepared"
        if (
            self.schema != PHASE_APPEND_PROJECTION_SCHEMA
            or self.transaction_schema != TRANSITION_TRANSACTION_SCHEMA_V2
            or self.may_authorize is not False
            or self.attempt_no < 0
            or self.sequence <= 0
            or self.event.sequence != self.sequence
            or self.event.event_id != f"{self.transaction_id}.{self.phase}"
            or self.event.payload.get("operation_id") != self.operation_id
            or self.event.payload.get("transaction_id") != self.transaction_id
            or self.event.payload.get("attempt_no") != self.attempt_no
            or self.event.payload.get("phase") != self.phase
            or self.event.payload.get("schema") != TRANSITION_TRANSACTION_SCHEMA_V2
            or self.event.event_type != _PHASE_EVENT_TYPES[self.phase]
            or (self.prior_projection_ref is not None) != expected_prior
            or (
                self.prior_projection_ref is not None
                and re.fullmatch(
                    r"lifecycle-phase-append@sha256:[0-9a-f]{64}",
                    self.prior_projection_ref,
                )
                is None
            )
            or not Path(self.ledger_path).is_absolute()
        ):
            raise ValueError("lifecycle phase append projection shape is invalid")
        digest = _domain_hash(PHASE_APPEND_PROJECTION_SCHEMA, self.body())
        if self.projection_hash != digest or self.projection_ref != (
            f"lifecycle-phase-append@sha256:{digest}"
        ):
            raise ValueError("lifecycle phase append projection identity mismatch")

    @classmethod
    def create(
        cls,
        *,
        event: CoordEvent,
        receipt: AppendReceipt,
        prior_projection_ref: str | None,
    ) -> LifecyclePhaseAppendProjection:
        payload = event.payload
        phase = payload.get("phase")
        if phase not in {"prepared", "applied", "aborted"}:
            raise LifecycleTransitionError(
                "transition_phase_projection_event_invalid",
                "project only one exact lifecycle phase event",
                event.event_id,
            )
        if (
            not receipt.appended
            or receipt.spooled
            or receipt.sequence is None
            or receipt.sequence <= 0
            or receipt.event_id != event.event_id
        ):
            raise LifecycleTransitionError(
                "transition_phase_projection_receipt_invalid",
                "project only a positive canonical append receipt",
                event.event_id,
            )
        committed = event.with_sequence(receipt.sequence)
        values: dict[str, Any] = {
            "append_receipt": {
                "appended": True,
                "ledger_path": str(_normalized_path(receipt.db_path)),
                "sequence": receipt.sequence,
                "spooled": False,
            },
            "attempt_no": payload.get("attempt_no"),
            "event": committed.to_record(),
            "may_authorize": False,
            "operation_id": payload.get("operation_id"),
            "phase": phase,
            "prior_projection_ref": prior_projection_ref,
            "schema": PHASE_APPEND_PROJECTION_SCHEMA,
            "transaction_id": payload.get("transaction_id"),
            "transaction_schema": TRANSITION_TRANSACTION_SCHEMA_V2,
        }
        digest = _domain_hash(PHASE_APPEND_PROJECTION_SCHEMA, values)
        return cls(
            operation_id=str(payload.get("operation_id")),
            transaction_id=str(payload.get("transaction_id")),
            attempt_no=int(payload.get("attempt_no")),
            phase=phase,
            event=committed,
            ledger_path=str(_normalized_path(receipt.db_path)),
            sequence=receipt.sequence,
            prior_projection_ref=prior_projection_ref,
            projection_ref=f"lifecycle-phase-append@sha256:{digest}",
            projection_hash=digest,
        )

    @classmethod
    def from_record(cls, value: Mapping[str, Any]) -> LifecyclePhaseAppendProjection:
        exact = {
            "append_receipt",
            "attempt_no",
            "event",
            "may_authorize",
            "operation_id",
            "phase",
            "prior_projection_ref",
            "projection_hash",
            "projection_ref",
            "schema",
            "transaction_id",
            "transaction_schema",
        }
        append = value.get("append_receipt")
        event = value.get("event")
        if (
            set(value) != exact
            or not isinstance(append, Mapping)
            or set(append) != {"appended", "ledger_path", "sequence", "spooled"}
            or append.get("appended") is not True
            or append.get("spooled") is not False
            or not isinstance(event, Mapping)
            or value.get("may_authorize") is not False
        ):
            raise ValueError("lifecycle phase append projection record is malformed")
        phase = value.get("phase")
        if phase not in {"prepared", "applied", "aborted"}:
            raise ValueError("lifecycle phase append projection phase is invalid")
        checked = cls(
            operation_id=str(value["operation_id"]),
            transaction_id=str(value["transaction_id"]),
            attempt_no=int(value["attempt_no"]),
            phase=phase,
            event=CoordEvent.from_record(event),
            ledger_path=str(append["ledger_path"]),
            sequence=int(append["sequence"]),
            prior_projection_ref=_optional_str(value.get("prior_projection_ref")),
            projection_ref=str(value["projection_ref"]),
            projection_hash=str(value["projection_hash"]),
        )
        if checked.to_record() != dict(value):
            raise ValueError("lifecycle phase append projection record is noncanonical")
        return checked


def _phase_projection_name(phase: str) -> str:
    if phase not in {"prepared", "applied", "aborted"}:
        raise LifecycleTransitionError(
            "transition_phase_projection_name_invalid",
            "use prepared, applied, or aborted",
            phase,
        )
    return f"phase-{phase}.append.json"


def _project_phase_append_receipt(
    directory: Path,
    event: CoordEvent,
    receipt: AppendReceipt,
    *,
    prior: LifecyclePhaseAppendProjection | None,
) -> LifecyclePhaseAppendProjection:
    phase = str(event.payload.get("phase") or "")
    if (phase == "prepared") != (prior is None):
        raise LifecycleTransitionError(
            "transition_phase_projection_chain_invalid",
            "chain each terminal phase projection to prepared",
            phase,
        )
    if prior is not None and (
        prior.phase != "prepared"
        or prior.transaction_id != event.payload.get("transaction_id")
        or prior.operation_id != event.payload.get("operation_id")
        or prior.attempt_no != event.payload.get("attempt_no")
        or prior.ledger_path != str(_normalized_path(receipt.db_path))
        or receipt.sequence is None
        or prior.sequence >= receipt.sequence
    ):
        raise LifecycleTransitionError(
            "transition_phase_projection_chain_invalid",
            "chain the terminal append after this transaction's prepared append",
            event.event_id,
        )
    projection = LifecyclePhaseAppendProjection.create(
        event=event,
        receipt=receipt,
        prior_projection_ref=None if prior is None else prior.projection_ref,
    )
    path = directory / _phase_projection_name(phase)
    payload = _canonical_json_bytes(projection.to_record()) + b"\n"
    if len(payload) > _MAX_LIFECYCLE_PHASE_BYTES:
        raise LifecycleTransitionError(
            "transition_phase_projection_inspection_bound_exceeded",
            "decompose the transition before writing an uninspectable phase projection",
            event.event_id,
        )
    existing = _private_file_state(path, max_bytes=_MAX_LIFECYCLE_PHASE_BYTES)
    if existing is not None:
        if existing.mode != 0o600 or existing.content != payload:
            raise LifecycleTransitionError(
                "transition_phase_projection_collision",
                "preserve the first immutable append projection and reconcile",
                str(path),
            )
        return projection
    _atomic_install(path, payload, 0o600, None)
    return projection


@dataclass(frozen=True)
class _ProjectionScratch:
    path: Path
    kind: str


def lifecycle_transition_id(
    intent: LifecycleTransitionIntent, projections: Sequence[FileProjection]
) -> str:
    body = {
        "intent": intent.to_record(),
        "projections": [projection.to_record() for projection in projections],
        "schema": TRANSITION_TRANSACTION_SCHEMA,
    }
    return f"sdlc-txn-{_domain_hash(TRANSITION_TRANSACTION_SCHEMA_V2, body)}"


def lifecycle_transition_intent_ref(intent: LifecycleTransitionIntent) -> str:
    return f"transition-intent@sha256:{_sha256(_canonical_json_bytes(intent.to_record()))}"


def _validate_terminal_close_admission(
    intent: LifecycleTransitionIntent,
    admission: Mapping[str, Any] | None,
) -> None:
    is_terminal_close = intent.from_stage == "S10" and intent.to_stage == "S11"
    if not is_terminal_close:
        if admission is not None:
            raise LifecycleTransitionError(
                "transition_terminal_admission_unexpected",
                "bind terminal close admission only to the canonical S10 -> S11 edge",
            )
        return
    if admission is None:
        raise LifecycleTransitionError(
            "transition_terminal_admission_missing",
            "enter S11 only through the governed cc-close admission",
        )
    exact_keys = {
        "actor",
        "admission_ref",
        "authority_case",
        "claim_publication_proof",
        "claim_vector",
        "echo_message_id",
        "final_status",
        "gate_evidence",
        "gate_refs",
        "may_authorize",
        "note_mode",
        "note_path",
        "note_sha256",
        "position_ref",
        "receipt_mode",
        "receipt_path",
        "receipt_sha256",
        "relay_vector",
        "schema",
        "session_id",
        "task_id",
    }
    body = {key: value for key, value in admission.items() if key != "admission_ref"}
    admission_ref = f"terminal-close-admission@sha256:{_sha256(_canonical_json_bytes(body))}"
    gate_evidence = admission.get("gate_evidence")
    checked_gate_evidence: list[dict[str, Any]] = (
        [item for item in gate_evidence if isinstance(item, dict)]
        if isinstance(gate_evidence, list)
        else []
    )
    valid_gate_evidence = (
        isinstance(gate_evidence, list)
        and bool(gate_evidence)
        and len(checked_gate_evidence) == len(gate_evidence)
    )
    expected_gate_refs = (
        [
            f"terminal-close-gate@sha256:{_sha256(_canonical_json_bytes(item))}"
            for item in checked_gate_evidence
        ]
        if valid_gate_evidence
        else []
    )
    claim_vector = admission.get("claim_vector")
    claim_publication_proof = admission.get("claim_publication_proof")
    claim_keys = {
        "binding_mode",
        "binding_path",
        "binding_sha256",
        "claim_key",
        "claim_mode",
        "claim_path",
        "claim_sha256",
        "epoch_mode",
        "epoch_path",
        "epoch_sha256",
    }
    relay_keys = {"relay_mode", "relay_path", "relay_sha256"}
    proof_keys = {"kind", "mode", "path", "sha256"}
    relay_vector = admission.get("relay_vector")
    gate_keys = {
        "authority_case",
        "command",
        "final_status",
        "gate",
        "may_authorize",
        "note_sha256",
        "observed_at",
        "outcome",
        "returncode",
        "schema",
        "stderr_sha256",
        "stdout_sha256",
        "task_id",
    }
    if (
        set(admission) != exact_keys
        or admission.get("schema") != "hapax.terminal-close-admission.v2"
        or admission.get("may_authorize") is not False
        or admission.get("admission_ref") != admission_ref
        or admission.get("task_id") != intent.task_id
        or admission.get("authority_case") != intent.authority_case
        or admission.get("actor") != intent.actor
        or admission.get("position_ref") != intent.predecessor_position_ref
        or f"mq:{admission.get('echo_message_id')}" != intent.echo_receipt_ref
        or intent.evidence_type != "terminal_close_admission"
        or intent.evidence_summary != admission_ref
        or admission.get("final_status") not in {"done", "withdrawn", "superseded"}
        or not isinstance(admission.get("session_id"), str)
        or not admission.get("session_id")
        or not isinstance(claim_vector, list)
        or not claim_vector
        or any(not isinstance(item, dict) or set(item) != claim_keys for item in claim_vector)
        or not isinstance(claim_publication_proof, list)
        or len(claim_publication_proof) != 2
        or any(
            not isinstance(item, dict)
            or set(item) != proof_keys
            or item.get("kind") not in {"manifest", "receipt"}
            or not isinstance(item.get("path"), str)
            or not Path(str(item.get("path"))).is_absolute()
            or type(item.get("mode")) is not int
            or re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256"))) is None
            for item in claim_publication_proof
        )
        or {str(item.get("kind")) for item in claim_publication_proof} != {"manifest", "receipt"}
        or not isinstance(relay_vector, list)
        or not relay_vector
        or any(not isinstance(item, dict) or set(item) != relay_keys for item in relay_vector)
        or not valid_gate_evidence
        or admission.get("gate_refs") != expected_gate_refs
        or any(
            item.get("schema") != "hapax.terminal-close-gate-evidence.v1"
            or set(item) != gate_keys
            or item.get("may_authorize") is not False
            or item.get("task_id") != intent.task_id
            or item.get("authority_case") != intent.authority_case
            or item.get("final_status") != admission.get("final_status")
            or item.get("note_sha256") != admission.get("note_sha256")
            or item.get("outcome") not in {"pass", "not_applicable"}
            for item in checked_gate_evidence
        )
        or not isinstance(admission.get("note_path"), str)
        or not Path(str(admission.get("note_path"))).is_absolute()
        or not isinstance(admission.get("note_mode"), int)
        or any(
            not isinstance(item.get("relay_path"), str)
            or not Path(str(item.get("relay_path"))).is_absolute()
            or not isinstance(item.get("relay_mode"), int)
            or re.fullmatch(r"[0-9a-f]{64}", str(item.get("relay_sha256"))) is None
            for item in relay_vector
        )
        or ((admission.get("receipt_path") is None) != (admission.get("receipt_sha256") is None))
        or ((admission.get("receipt_mode") is None) != (admission.get("receipt_sha256") is None))
    ):
        raise LifecycleTransitionError(
            "transition_terminal_admission_mismatch",
            "bind the exact self-hashed claim, Echo, and gate admission from cc-close",
            intent.task_id,
        )


def _projected_terminal_close_admission(
    intent: LifecycleTransitionIntent,
    projections: Sequence[FileProjection],
) -> dict[str, Any] | None:
    if intent.from_stage != "S10" or intent.to_stage != "S11":
        return None

    def unique_pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in values:
            if key in output:
                raise LifecycleTransitionError(
                    "transition_terminal_admission_projection_malformed",
                    "restore the unique-key canonical terminal admission projection",
                    key,
                )
            output[key] = value
        return output

    matches: list[dict[str, Any]] = []
    for projection in projections:
        if projection.after is None:
            continue
        try:
            permissive = json.loads(projection.after.decode("ascii"))
        except (UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(permissive, dict) or permissive.get("schema") != (
            "hapax.terminal-close-admission.v2"
        ):
            continue
        try:
            record = json.loads(
                projection.after.decode("ascii"),
                object_pairs_hook=unique_pairs,
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LifecycleTransitionError(
                "transition_terminal_admission_projection_malformed",
                "restore the unique-key canonical terminal admission projection",
                str(projection.path),
            ) from exc
        if (
            not isinstance(record, dict)
            or projection.after != _canonical_json_bytes(record) + b"\n"
            or not isinstance(record.get("receipt_hash"), str)
            or projection.before is not None
            or projection.before_mode is not None
            or projection.after_mode != 0o600
        ):
            raise LifecycleTransitionError(
                "transition_terminal_admission_projection_not_canonical",
                "restore the exact canonical terminal admission receipt bytes",
                str(projection.path),
            )
        admission = {key: value for key, value in record.items() if key != "receipt_hash"}
        if record["receipt_hash"] != _sha256(_canonical_json_bytes(admission)):
            raise LifecycleTransitionError(
                "transition_terminal_admission_projection_hash_mismatch",
                "restore the terminal admission receipt bound to its exact body",
                str(projection.path),
            )
        _validate_terminal_close_admission(intent, admission)
        matches.append(admission)
    if len(matches) != 1:
        raise LifecycleTransitionError(
            "transition_terminal_admission_projection_missing",
            "commit exactly one canonical terminal admission receipt in the close transaction",
            intent.task_id,
        )
    return matches[0]


def _validate_terminal_admission_projection_bindings(
    admission: Mapping[str, Any] | None,
    projections: Sequence[FileProjection],
) -> None:
    if admission is None:
        return
    records = [projection.to_record() for projection in projections]

    def require_bound(
        *,
        path: object,
        mode: object,
        sha256: object,
        after_present: bool,
        label: str,
    ) -> None:
        expected = {
            "path": path,
            "before_mode": mode,
            "before_present": True,
            "before_sha256": sha256,
        }
        matches = [
            item
            for item in records
            if all(item.get(key) == value for key, value in expected.items())
            and item.get("after_present") is after_present
        ]
        if len(matches) != 1:
            raise LifecycleTransitionError(
                "transition_terminal_admission_surface_unbound",
                "bind every admitted close surface to one exact transaction projection",
                label,
            )

    require_bound(
        path=admission.get("note_path"),
        mode=admission.get("note_mode"),
        sha256=admission.get("note_sha256"),
        after_present=False,
        label="note",
    )
    if admission.get("receipt_path") is not None:
        require_bound(
            path=admission.get("receipt_path"),
            mode=admission.get("receipt_mode"),
            sha256=admission.get("receipt_sha256"),
            after_present=False,
            label="acceptance_receipt",
        )
    for index, item in enumerate(admission.get("claim_vector") or []):
        for prefix in ("claim", "epoch", "binding"):
            require_bound(
                path=item.get(f"{prefix}_path"),
                mode=item.get(f"{prefix}_mode"),
                sha256=item.get(f"{prefix}_sha256"),
                after_present=False,
                label=f"claim_vector[{index}].{prefix}",
            )
    for item in admission.get("claim_publication_proof") or []:
        require_bound(
            path=item.get("path"),
            mode=item.get("mode"),
            sha256=item.get("sha256"),
            after_present=True,
            label=f"claim_publication_proof.{item.get('kind')}",
        )
        matches = [
            record
            for record in records
            if record.get("path") == item.get("path")
            and record.get("after_mode") == item.get("mode")
            and record.get("after_sha256") == item.get("sha256")
        ]
        if len(matches) != 1:
            raise LifecycleTransitionError(
                "transition_terminal_admission_surface_unbound",
                "preserve every applied claim-publication proof as one no-op projection",
                str(item.get("kind")),
            )
    for index, item in enumerate(admission.get("relay_vector") or []):
        require_bound(
            path=item.get("relay_path"),
            mode=item.get("relay_mode"),
            sha256=item.get("relay_sha256"),
            after_present=True,
            label=f"relay_vector[{index}]",
        )


def _attempt_transaction_id(operation_id: str, attempt_no: int) -> str:
    return f"{operation_id}.attempt-{attempt_no:04d}"


def _event_without_sequence(event: CoordEvent) -> dict[str, Any]:
    record = event.to_record()
    record.pop("sequence", None)
    return record


def _find_exact_event(event_log: CoordEventLog, event: CoordEvent) -> CoordEvent | None:
    replay = event_log.replay(fail_open=False)
    if replay.degraded or replay.source != "sqlite":
        raise LifecycleTransitionError(
            "transition_receipt_replay_degraded",
            "restore the canonical SQLite coordination ledger before transition",
        )
    existing = next((item for item in replay.events if item.event_id == event.event_id), None)
    if existing is None:
        return None
    if _event_without_sequence(existing) != _event_without_sequence(event):
        raise LifecycleTransitionError(
            "transition_idempotency_collision",
            "preserve the first exact receipt and investigate the conflicting payload",
            event.event_id,
        )
    return existing


def _strict_append_exact(event_log: CoordEventLog, event: CoordEvent) -> AppendReceipt:
    try:
        receipt = event_log.append(event, writer=CoordWriter.daemon())
    except DuplicateEventError as exc:
        existing = _find_exact_event(event_log, event)
        if existing is None:
            raise LifecycleTransitionError(
                "transition_duplicate_receipt_missing",
                "restore the canonical receipt indexed by its duplicate event id",
                event.event_id,
            ) from exc
        return AppendReceipt(
            event_id=event.event_id,
            appended=True,
            spooled=False,
            sequence=existing.sequence,
            db_path=event_log.db_path,
            jsonl_path=event_log.jsonl_path,
        )
    if not receipt.appended or receipt.spooled or receipt.sequence is None:
        raise LifecycleTransitionError(
            "transition_receipt_not_canonical",
            "append the transition receipt to the canonical SQLite ledger without spooling",
            event.event_id,
        )
    # CoordEventLog.append returns only after the canonical SQLite commit. Its
    # sequence is therefore the commit receipt; a subsequent replay outage must
    # not turn a committed applied event into a rollback.
    return receipt


def _projection_vector(projections: Sequence[FileProjection], *, after: bool) -> str:
    records = []
    for projection in projections:
        payload = projection.after if after else projection.before
        mode = projection.after_mode if after else projection.before_mode
        records.append(
            {
                "mode": mode,
                "path": str(projection.path),
                "present": payload is not None,
                "sha256": _sha256(payload) if payload is not None else None,
            }
        )
    return _domain_hash("hapax.sdlc-projection-vector.v1", records)


def _transaction_event(
    *,
    event_type: str,
    phase: str,
    transaction_id: str,
    operation_id: str,
    attempt_no: int,
    intent: LifecycleTransitionIntent,
    projections: Sequence[FileProjection],
    timestamp: str,
    reason_code: str | None = None,
) -> CoordEvent:
    if reason_code is not None and (
        not reason_code or len(reason_code) > _MAX_LIFECYCLE_REASON_CODE_BYTES
    ):
        raise LifecycleTransitionError(
            "transition_reason_code_invalid",
            "use one bounded non-empty lifecycle reason code",
            transaction_id,
        )
    payload: dict[str, Any] = {
        "intent": intent.to_record(),
        "attempt_no": attempt_no,
        "operation_id": operation_id,
        "phase": phase,
        "preimage_vector_sha256": _projection_vector(projections, after=False),
        "projections": [projection.to_record() for projection in projections],
        "schema": TRANSITION_TRANSACTION_SCHEMA,
        "transaction_id": transaction_id,
    }
    if phase == "applied":
        payload["postimage_vector_sha256"] = _projection_vector(projections, after=True)
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return CoordEvent(
        event_id=f"{transaction_id}.{phase}",
        timestamp=timestamp,
        event_type=event_type,
        actor=intent.actor,
        subject=intent.task_id,
        authority_case=intent.authority_case,
        parent_spec=intent.parent_spec,
        payload=payload,
    )


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


_UNSAFE_RECOVERY_ENTRY = object()


def _recovery_entry_state_at(
    directory_fd: int,
    name: str,
    *,
    max_bytes: int,
) -> _EntryState | None | object:
    """Observe a post-rename entry without letting a special-file race escape recovery."""

    try:
        return _entry_state_at(directory_fd, name, max_bytes=max_bytes)
    except LifecycleTransitionError:
        return _UNSAFE_RECOVERY_ENTRY


def _atomic_install(
    path: Path,
    payload: bytes | None,
    mode: int | None,
    expected: _EntryState | None,
) -> _EntryState | None:
    """CAS one private journal entry without discarding raced bytes."""

    with _open_parent_dir(path) as (directory_fd, name):
        current = _entry_state_at(
            directory_fd,
            name,
            max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
        )
        if current != expected:
            raise LifecycleTransitionError(
                "transition_private_install_precondition_changed",
                "preserve the raced journal entry and retry from a fresh snapshot",
                str(path),
            )

        for _ in range(32):
            candidate = f".{name}.{secrets.token_hex(16)}.transition-tmp"
            if payload is None:
                if expected is None:
                    return None
                try:
                    _renameat2(
                        directory_fd,
                        name,
                        directory_fd,
                        candidate,
                        _RENAME_NOREPLACE,
                    )
                except OSError as exc:
                    raise LifecycleTransitionError(
                        "transition_private_install_precondition_changed",
                        "preserve the raced journal entry and retry from a fresh snapshot",
                        str(path),
                    ) from exc
                os.fsync(directory_fd)
                displaced = _recovery_entry_state_at(
                    directory_fd,
                    candidate,
                    max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
                )
                if displaced != expected:
                    try:
                        if (
                            _recovery_entry_state_at(
                                directory_fd,
                                name,
                                max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
                            )
                            is None
                        ):
                            _renameat2(
                                directory_fd,
                                candidate,
                                directory_fd,
                                name,
                                _RENAME_NOREPLACE,
                            )
                            os.fsync(directory_fd)
                    except Exception as restore_exc:
                        raise LifecycleTransitionError(
                            "transition_private_install_recovery_required",
                            "preserve both journal entries and reconcile the failed delete",
                            str(path),
                        ) from restore_exc
                    if displaced is _UNSAFE_RECOVERY_ENTRY:
                        raise LifecycleTransitionError(
                            "transition_private_install_recovery_required",
                            "preserve every raced entry and reconcile the failed delete",
                            str(path),
                        )
                    raise LifecycleTransitionError(
                        "transition_private_install_precondition_changed",
                        "preserve the restored raced journal entry and retry",
                        str(path),
                    )
                _unlink_exact_entry(
                    directory_fd,
                    candidate,
                    expected,
                    max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
                )
                return None

            assert mode is not None
            try:
                fd = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                    mode,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            replacement: _EntryState | None = None
            candidate_contains_replacement = True
            try:
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                os.fchmod(fd, mode)
                os.fsync(fd)
                metadata = os.fstat(fd)
                replacement = _EntryState(
                    content=payload,
                    mode=metadata.st_mode & 0o777,
                    uid=metadata.st_uid,
                    nlink=metadata.st_nlink,
                    device=metadata.st_dev,
                    inode=metadata.st_ino,
                )
                os.close(fd)
                fd = -1

                if expected is None:
                    try:
                        _renameat2(
                            directory_fd,
                            candidate,
                            directory_fd,
                            name,
                            _RENAME_NOREPLACE,
                        )
                    except OSError as exc:
                        raise LifecycleTransitionError(
                            "transition_private_install_precondition_changed",
                            "preserve the raced journal entry and retry from a fresh snapshot",
                            str(path),
                        ) from exc
                    candidate_contains_replacement = False
                    os.fsync(directory_fd)
                    installed = _recovery_entry_state_at(
                        directory_fd,
                        name,
                        max_bytes=len(payload),
                    )
                    if installed != replacement:
                        raise LifecycleTransitionError(
                            "transition_private_install_recovery_required",
                            "preserve the unexpected installed journal entry for reconciliation",
                            str(path),
                        )
                    return installed

                _renameat2(
                    directory_fd,
                    candidate,
                    directory_fd,
                    name,
                    _RENAME_EXCHANGE,
                )
                candidate_contains_replacement = False
                os.fsync(directory_fd)
                installed = _recovery_entry_state_at(
                    directory_fd,
                    name,
                    max_bytes=len(payload),
                )
                displaced = _recovery_entry_state_at(
                    directory_fd,
                    candidate,
                    max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
                )
                if installed != replacement or displaced != expected:
                    try:
                        if installed == replacement and displaced is not None:
                            _renameat2(
                                directory_fd,
                                name,
                                directory_fd,
                                candidate,
                                _RENAME_EXCHANGE,
                            )
                            candidate_contains_replacement = True
                            os.fsync(directory_fd)
                    except Exception as restore_exc:
                        raise LifecycleTransitionError(
                            "transition_private_install_recovery_required",
                            "preserve both exchanged journal entries for reconciliation",
                            str(path),
                        ) from restore_exc
                    if installed is _UNSAFE_RECOVERY_ENTRY or displaced is _UNSAFE_RECOVERY_ENTRY:
                        raise LifecycleTransitionError(
                            "transition_private_install_recovery_required",
                            "preserve every raced exchange entry for reconciliation",
                            str(path),
                        )
                    raise LifecycleTransitionError(
                        "transition_private_install_precondition_changed",
                        "preserve the restored raced journal entry and retry",
                        str(path),
                    )
                _unlink_exact_entry(
                    directory_fd,
                    candidate,
                    expected,
                    max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
                )
                return installed
            finally:
                if fd >= 0:
                    os.close(fd)
                if candidate_contains_replacement and replacement is not None:
                    candidate_state = _recovery_entry_state_at(
                        directory_fd,
                        candidate,
                        max_bytes=len(payload),
                    )
                    if candidate_state == replacement:
                        _unlink_exact_entry(
                            directory_fd,
                            candidate,
                            replacement,
                            max_bytes=len(payload),
                        )
        raise LifecycleTransitionError(
            "transition_projection_temp_exhausted",
            "clear stale transition temp files and retry",
            str(path),
        )


def _state_matches(path: Path, payload: bytes | None, mode: int | None) -> bool:
    try:
        observed, observed_mode = _file_state(path)
    except LifecycleTransitionError:
        return False
    return observed == payload and observed_mode == mode


def _entry_matches(state: _EntryState | None, payload: bytes | None, mode: int | None) -> bool:
    if state is None:
        return payload is None and mode is None
    return state.content == payload and state.mode == mode


def _renameat2(
    src_dir_fd: int,
    src_name: str,
    dst_dir_fd: int,
    dst_name: str,
    flags: int,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameat2", None)
    if function is None:
        raise LifecycleTransitionError(
            "transition_atomic_cas_unavailable",
            "run lifecycle projection only on Linux with renameat2 support",
        )
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    result = function(
        src_dir_fd,
        os.fsencode(src_name),
        dst_dir_fd,
        os.fsencode(dst_name),
        flags,
    )
    if result != 0:
        value = ctypes.get_errno()
        raise OSError(value, os.strerror(value), f"{src_name}->{dst_name}")


def _write_scratch(dir_fd: int, name: str, payload: bytes, mode: int) -> _EntryState:
    try:
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            mode,
            dir_fd=dir_fd,
        )
    except FileExistsError as exc:
        raise LifecycleTransitionError(
            "transition_projection_scratch_exists",
            "recover or quarantine the prior exact transaction scratch before retrying",
            name,
        ) from exc
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fchmod(fd, mode)
        os.fsync(fd)
        metadata = os.fstat(fd)
        expected = _EntryState(
            content=payload,
            mode=metadata.st_mode & 0o777,
            uid=metadata.st_uid,
            nlink=metadata.st_nlink,
            device=metadata.st_dev,
            inode=metadata.st_ino,
        )
    finally:
        os.close(fd)
    os.fsync(dir_fd)
    if (
        _entry_state_at(
            dir_fd,
            name,
            max_bytes=len(payload),
        )
        != expected
    ):
        raise LifecycleTransitionError(
            "transition_projection_scratch_identity_mismatch",
            "hold the transaction and preserve the unexpected scratch entry",
            name,
        )
    return expected


def _unlink_exact_entry(
    dir_fd: int,
    name: str,
    expected: _EntryState,
    *,
    max_bytes: int = _MAX_LIFECYCLE_BLOB_BYTES,
) -> None:
    if (
        _entry_state_at(
            dir_fd,
            name,
            max_bytes=max_bytes,
        )
        != expected
    ):
        raise LifecycleTransitionError(
            "transition_projection_scratch_identity_mismatch",
            "hold the transaction and preserve the unexpected scratch entry",
            name,
        )
    os.unlink(name, dir_fd=dir_fd)
    os.fsync(dir_fd)
    if (
        _entry_state_at(
            dir_fd,
            name,
            max_bytes=max_bytes,
        )
        is not None
    ):
        raise LifecycleTransitionError(
            "transition_projection_scratch_cleanup_failed",
            "hold the transaction until the exact scratch entry is absent",
            name,
        )


def _scratch_for(projection: FileProjection, transaction_id: str, index: int) -> _ProjectionScratch:
    if projection.before is None and projection.after is None:
        kind = "noop"
    elif projection.before is None:
        kind = "create"
    elif projection.after is None:
        kind = "delete"
    elif projection.before == projection.after and projection.before_mode == projection.after_mode:
        kind = "noop"
    else:
        kind = "update"
    suffix = _sha256(f"{transaction_id}:{index}:{projection.path}".encode())[:24]
    return _ProjectionScratch(
        path=projection.path.parent / f".{projection.path.name}.{suffix}.transition-scratch",
        kind=kind,
    )


def _cas_project(projection: FileProjection, scratch: _ProjectionScratch) -> None:
    with _open_parent_dir(projection.path) as (dir_fd, name):
        scratch_name = scratch.path.name
        current = _entry_state_at(
            dir_fd,
            name,
            max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
        )
        if not _entry_matches(current, projection.before, projection.before_mode):
            raise LifecycleTransitionError(
                "transition_precondition_changed",
                "reload the current position and prepare a new transition without spending echo repair",
                str(projection.path),
            )
        if scratch.kind == "noop":
            return
        if (
            _entry_state_at(
                dir_fd,
                scratch_name,
                max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
            )
            is not None
        ):
            raise LifecycleTransitionError(
                "transition_projection_scratch_exists",
                "recover or quarantine the prior exact transaction scratch before retrying",
                str(scratch.path),
            )
        if scratch.kind == "create":
            assert projection.after is not None and projection.after_mode is not None
            replacement = _write_scratch(
                dir_fd, scratch_name, projection.after, projection.after_mode
            )
            try:
                _renameat2(dir_fd, scratch_name, dir_fd, name, _RENAME_NOREPLACE)
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    raise LifecycleTransitionError(
                        "transition_precondition_changed",
                        "preserve the racing create and prepare a new transition",
                        str(projection.path),
                    ) from exc
                raise
            os.fsync(dir_fd)
            if (
                _entry_state_at(
                    dir_fd,
                    name,
                    max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
                )
                != replacement
            ):
                raise LifecycleTransitionError(
                    "transition_projection_readback_mismatch",
                    "hold the transaction and preserve the unexpected created entry",
                    str(projection.path),
                )
        elif scratch.kind == "delete":
            try:
                _renameat2(dir_fd, name, dir_fd, scratch_name, _RENAME_NOREPLACE)
            except OSError as exc:
                raise LifecycleTransitionError(
                    "transition_projection_exchange_failed",
                    "hold the transaction and recover its exact displaced entry",
                    str(projection.path),
                ) from exc
            os.fsync(dir_fd)
            displaced = _entry_state_at(
                dir_fd,
                scratch_name,
                max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
            )
            if displaced != current:
                try:
                    _renameat2(dir_fd, scratch_name, dir_fd, name, _RENAME_NOREPLACE)
                    os.fsync(dir_fd)
                except OSError as exc:
                    raise LifecycleTransitionError(
                        "transition_projection_recovery_required",
                        "preserve both racing entries and reconcile the delete manually",
                        str(projection.path),
                    ) from exc
                raise LifecycleTransitionError(
                    "transition_precondition_changed",
                    "preserve the racing replacement and prepare a new transition",
                    str(projection.path),
                )
        else:
            assert projection.after is not None and projection.after_mode is not None
            replacement = _write_scratch(
                dir_fd, scratch_name, projection.after, projection.after_mode
            )
            try:
                _renameat2(dir_fd, scratch_name, dir_fd, name, _RENAME_EXCHANGE)
            except OSError as exc:
                raise LifecycleTransitionError(
                    "transition_projection_exchange_failed",
                    "hold the transaction and recover its exact exchanged entries",
                    str(projection.path),
                ) from exc
            os.fsync(dir_fd)
            displaced = _entry_state_at(
                dir_fd,
                scratch_name,
                max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
            )
            if displaced != current:
                if not _entry_matches(
                    _entry_state_at(
                        dir_fd,
                        name,
                        max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
                    ),
                    projection.after,
                    projection.after_mode,
                ):
                    raise LifecycleTransitionError(
                        "transition_projection_recovery_required",
                        "preserve both exchanged entries and reconcile the racing update",
                        str(projection.path),
                    )
                _renameat2(dir_fd, scratch_name, dir_fd, name, _RENAME_EXCHANGE)
                os.fsync(dir_fd)
                restored = _entry_state_at(
                    dir_fd,
                    name,
                    max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
                )
                if displaced is None or restored != displaced:
                    raise LifecycleTransitionError(
                        "transition_projection_recovery_required",
                        "preserve both exchanged entries and reconcile the racing update",
                        str(projection.path),
                    )
                raise LifecycleTransitionError(
                    "transition_precondition_changed",
                    "preserve the racing replacement and prepare a new transition",
                    str(projection.path),
                )
            if (
                _entry_state_at(
                    dir_fd,
                    name,
                    max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
                )
                != replacement
            ):
                raise LifecycleTransitionError(
                    "transition_projection_readback_mismatch",
                    "hold the transaction and preserve the unexpected updated entry",
                    str(projection.path),
                )
        if not _entry_matches(
            _entry_state_at(
                dir_fd,
                name,
                max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
            ),
            projection.after,
            projection.after_mode,
        ):
            raise LifecycleTransitionError(
                "transition_projection_readback_mismatch",
                "hold the transaction and recover its exact projection scratch",
                str(projection.path),
            )


def _finalize_applied_scratches(
    projections: Sequence[FileProjection], scratches: Sequence[_ProjectionScratch]
) -> None:
    for projection, scratch in zip(projections, scratches, strict=True):
        with _open_parent_dir(projection.path) as (dir_fd, _name):
            state = _entry_state_at(
                dir_fd,
                scratch.path.name,
                max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
            )
            if state is None:
                continue
            if scratch.kind not in {"delete", "update"} or not _entry_matches(
                state, projection.before, projection.before_mode
            ):
                raise LifecycleTransitionError(
                    "transition_projection_scratch_terminal_mismatch",
                    "hold the transaction and preserve the unexpected terminal scratch",
                    str(scratch.path),
                )
            _unlink_exact_entry(dir_fd, scratch.path.name, state)


def _finalize_rolled_back_scratch(
    projection: FileProjection, scratch: _ProjectionScratch, dir_fd: int
) -> bool:
    state = _entry_state_at(
        dir_fd,
        scratch.path.name,
        max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
    )
    if state is None:
        return True
    if scratch.kind not in {"create", "update"} or not _entry_matches(
        state, projection.after, projection.after_mode
    ):
        return False
    try:
        _unlink_exact_entry(dir_fd, scratch.path.name, state)
    except LifecycleTransitionError:
        return False
    return True


def _cas_rollback(projection: FileProjection, scratch: _ProjectionScratch) -> bool:
    with _open_parent_dir(projection.path) as (dir_fd, name):
        current = _entry_state_at(
            dir_fd,
            name,
            max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
        )
        if _entry_matches(current, projection.before, projection.before_mode):
            return True
        if not _entry_matches(current, projection.after, projection.after_mode):
            return False
        scratch_state = _entry_state_at(
            dir_fd,
            scratch.path.name,
            max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
        )
        try:
            if scratch.kind == "create":
                if scratch_state is not None:
                    return False
                _renameat2(dir_fd, name, dir_fd, scratch.path.name, _RENAME_NOREPLACE)
            elif scratch.kind == "delete":
                if scratch_state is None:
                    assert projection.before is not None and projection.before_mode is not None
                    scratch_state = _write_scratch(
                        dir_fd,
                        scratch.path.name,
                        projection.before,
                        projection.before_mode,
                    )
                if not _entry_matches(scratch_state, projection.before, projection.before_mode):
                    return False
                _renameat2(dir_fd, scratch.path.name, dir_fd, name, _RENAME_NOREPLACE)
            elif scratch.kind == "update":
                if scratch_state is None:
                    assert projection.before is not None and projection.before_mode is not None
                    scratch_state = _write_scratch(
                        dir_fd,
                        scratch.path.name,
                        projection.before,
                        projection.before_mode,
                    )
                if not _entry_matches(scratch_state, projection.before, projection.before_mode):
                    return False
                _renameat2(dir_fd, scratch.path.name, dir_fd, name, _RENAME_EXCHANGE)
            else:
                return True
        except OSError:
            return False
        os.fsync(dir_fd)
        return _entry_matches(
            _entry_state_at(
                dir_fd,
                name,
                max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
            ),
            projection.before,
            projection.before_mode,
        ) and _finalize_rolled_back_scratch(projection, scratch, dir_fd)


def _assert_preimages(projections: Sequence[FileProjection]) -> None:
    drifted = [
        str(item.path)
        for item in projections
        if not _state_matches(item.path, item.before, item.before_mode)
    ]
    if drifted:
        raise LifecycleTransitionError(
            "transition_precondition_changed",
            "reload the current position and prepare a new transition without spending echo repair",
            ",".join(drifted),
        )


def _apply_projections(
    projections: Sequence[FileProjection],
    scratches: Sequence[_ProjectionScratch],
    failure_hook: Callable[[str, int | None], None] | None,
) -> None:
    for index, (projection, scratch) in enumerate(zip(projections, scratches, strict=True)):
        if failure_hook is not None:
            failure_hook("before_projection", index)
        _cas_project(projection, scratch)
        if not _state_matches(projection.path, projection.after, projection.after_mode):
            raise LifecycleTransitionError(
                "transition_projection_readback_mismatch",
                "hold the transaction and restore its exact preimage",
                str(projection.path),
            )
        if failure_hook is not None:
            failure_hook("after_projection", index)


def _rollback_projections(
    projections: Sequence[FileProjection], scratches: Sequence[_ProjectionScratch]
) -> tuple[str, ...]:
    conflicts: list[str] = []
    pairs = tuple(zip(projections, scratches, strict=True))
    for projection, scratch in reversed(pairs):
        if not _cas_rollback(projection, scratch):
            conflicts.append(str(projection.path))
    return tuple(reversed(conflicts))


def _manifest_root(path: Path | None) -> Path:
    return path or coord_base_dir() / "transition-transactions"


def _materialization_root(root: Path) -> Path:
    return root.parent / f".{root.name}.materializing"


def _lock_root(path: Path | None) -> Path:
    return path or coord_base_dir() / "task-locks"


def _ensure_private_directory_fd(path: Path) -> int:
    normalized = _normalized_path(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for component in normalized.parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component, flags, dir_fd=fd)
                os.fsync(fd)
            os.close(fd)
            fd = next_fd
        metadata = os.fstat(fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != 0o700
        ):
            raise LifecycleTransitionError(
                "transition_private_directory_unsafe",
                "use one euid-owned mode-0700 real transaction directory",
                str(normalized),
            )
        return fd
    except OSError as exc:
        os.close(fd)
        raise LifecycleTransitionError(
            "transition_private_directory_unsafe",
            "use one euid-owned mode-0700 real transaction directory",
            str(normalized),
        ) from exc
    except Exception:
        os.close(fd)
        raise


def _open_existing_private_directory_fd(path: Path) -> int | None:
    normalized = _normalized_path(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for component in normalized.parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                os.close(fd)
                return None
            except OSError as exc:
                raise LifecycleTransitionError(
                    "transition_private_directory_unsafe",
                    "use one euid-owned mode-0700 real transaction directory",
                    str(normalized),
                ) from exc
            os.close(fd)
            fd = next_fd
        metadata = os.fstat(fd)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != 0o700
        ):
            raise LifecycleTransitionError(
                "transition_private_directory_unsafe",
                "use one euid-owned mode-0700 real transaction directory",
                str(normalized),
            )
        return fd
    except Exception:
        os.close(fd)
        raise


_TRANSACTION_DIRECTORY_RE = re.compile(r"^sdlc-txn-[0-9a-f]{64}\.attempt-[0-9]{4,}$")
_TRANSACTION_BLOB_RE = re.compile(r"^[0-9]{4}\.(?:before|after)$")
_TRANSACTION_PHASE_PROJECTION_RE = re.compile(r"^phase-(?:prepared|applied|aborted)\.append\.json$")
_MATERIALIZATION_PLAN_RE = re.compile(r"^(sdlc-txn-[0-9a-f]{64}\.attempt-[0-9]{4,})\.plan\.json$")


def _transaction_child_max_bytes(name: str) -> int:
    if name == "manifest.json":
        return _MAX_LIFECYCLE_MANIFEST_BYTES
    if _MATERIALIZATION_PLAN_RE.fullmatch(name) is not None:
        return _MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES
    if _TRANSACTION_PHASE_PROJECTION_RE.fullmatch(name) is not None:
        return _MAX_LIFECYCLE_PHASE_BYTES
    return _MAX_LIFECYCLE_BLOB_BYTES


def _materialization_plan_name(transaction_id: str) -> str:
    if _TRANSACTION_DIRECTORY_RE.fullmatch(transaction_id) is None:
        raise LifecycleTransitionError(
            "transition_materialization_identity_invalid",
            "use one exact transaction identity for its recovery plan",
            transaction_id,
        )
    return f"{transaction_id}.plan.json"


def _known_transaction_child(name: str) -> bool:
    return (
        name in {"manifest.json", _LIFECYCLE_SOURCE_BLOB, _LIFECYCLE_DEFINITION_BLOB}
        or _TRANSACTION_BLOB_RE.fullmatch(name) is not None
        or _TRANSACTION_PHASE_PROJECTION_RE.fullmatch(name) is not None
    )


def _transaction_manifest_paths(
    root: Path,
    *,
    allow_materialization_plans: bool = False,
) -> tuple[Path, ...]:
    root_fd = _open_existing_private_directory_fd(root)
    if root_fd is None:
        return ()
    paths: list[Path] = []
    try:
        for name in sorted(os.listdir(root_fd)):
            if allow_materialization_plans and _MATERIALIZATION_PLAN_RE.fullmatch(name):
                continue
            if _TRANSACTION_DIRECTORY_RE.fullmatch(name) is None:
                raise LifecycleTransitionError(
                    "transition_manifest_root_entry_unknown",
                    "quarantine every entry outside the exact transaction-directory grammar",
                    str(root / name),
                )
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
            try:
                directory_fd = os.open(name, flags, dir_fd=root_fd)
            except OSError as exc:
                raise LifecycleTransitionError(
                    "transition_manifest_directory_unsafe",
                    "restore the transaction entry as one private real directory",
                    str(root / name),
                ) from exc
            try:
                metadata = os.fstat(directory_fd)
                if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o777 != 0o700:
                    raise LifecycleTransitionError(
                        "transition_manifest_directory_unsafe",
                        "use one euid-owned mode-0700 transaction directory",
                        str(root / name),
                    )
            finally:
                os.close(directory_fd)
            paths.append(root / name / "manifest.json")
    finally:
        os.close(root_fd)
    return tuple(paths)


def _materialization_plan_paths(root: Path) -> tuple[Path, ...]:
    root_fd = _open_existing_private_directory_fd(root)
    if root_fd is None:
        return ()
    paths: list[Path] = []
    try:
        for name in sorted(os.listdir(root_fd)):
            match = _MATERIALIZATION_PLAN_RE.fullmatch(name)
            if match is not None:
                state = _private_file_state(
                    root / name,
                    max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
                )
                if state is None or len(state.content) > (
                    _MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES
                ):
                    raise LifecycleTransitionError(
                        "transition_materialization_plan_bound_exceeded",
                        "restore one bounded private materialization plan",
                        str(root / name),
                    )
                paths.append(root / name)
                continue
            if _TRANSACTION_DIRECTORY_RE.fullmatch(name) is None:
                raise LifecycleTransitionError(
                    "transition_materialization_root_entry_unknown",
                    "quarantine entries outside plan or staged-journal grammar",
                    str(root / name),
                )
    finally:
        os.close(root_fd)
    return tuple(paths)


def _rehydrate_materialization_plan(
    *,
    event_log: CoordEventLog,
    root: Path,
    plan_path: Path,
    lock_root: Path,
    task_id: str | None,
) -> tuple[str, bool] | None:
    """Validate, lock, rehydrate, and promote one pre-append journal plan."""

    initial_state = _private_file_state(
        plan_path,
        max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
    )
    if initial_state is None:
        raise LifecycleTransitionError(
            "transition_materialization_plan_missing",
            "restore the self-contained materialization recovery plan",
            str(plan_path),
        )
    initial_plan = _load_materialization_plan(
        plan_path,
        content=initial_state.content,
    )
    initial_transaction = _validated_materialization_plan_transaction(
        initial_plan,
        plan_path,
    )
    intent = initial_transaction[4]
    projections = initial_transaction[5]
    if task_id is not None and intent.task_id != task_id:
        return None

    with (
        _transition_locks(
            intent.task_id,
            [projection.path for projection in projections],
            lock_root,
        ),
        _lifecycle_estate_lock(root),
    ):
        locked_state = _private_file_state(
            plan_path,
            max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
        )
        if locked_state is None or locked_state.content != initial_state.content:
            raise LifecycleTransitionError(
                "transition_materialization_plan_changed",
                "retry after the recovery plan identity stabilizes under lock",
                str(plan_path),
            )
        plan = _load_materialization_plan(plan_path, content=locked_state.content)
        transaction = _validated_materialization_plan_transaction(plan, plan_path)
        if transaction != initial_transaction:
            raise LifecycleTransitionError(
                "transition_materialization_plan_changed",
                "retry after the validated recovery transaction stabilizes under lock",
                plan.transaction_id,
            )

        materialization_root = _materialization_root(root)
        stage = materialization_root / plan.transaction_id
        final_directory = root / plan.transaction_id
        stage_fd = _open_existing_private_directory_fd(stage)
        final_fd = _open_existing_private_directory_fd(final_directory)
        stage_exists = stage_fd is not None
        final_exists = final_fd is not None
        if stage_fd is not None:
            os.close(stage_fd)
        if final_fd is not None:
            os.close(final_fd)
        if stage_exists and final_exists:
            raise LifecycleTransitionError(
                "transition_materialization_identity_collision",
                "reconcile the staged and promoted copies before continuing",
                plan.transaction_id,
            )

        receipts = _transaction_receipt_census(event_log)
        if final_exists:
            final_transaction = _load_transaction_manifest(final_directory / "manifest.json")
            if final_transaction[:7] != transaction[:7]:
                raise LifecycleTransitionError(
                    "transition_materialization_plan_collision",
                    "reconcile the residual plan against the exact promoted journal",
                    plan.transaction_id,
                )
            planned_manifest = _load_private_manifest_payload(
                stage / "manifest.json",
                content=plan.artifact("manifest.json"),
            )
            final_manifest = _load_private_manifest_payload(final_directory / "manifest.json")
            static_keys = set(planned_manifest) - {"reason_code", "state"}
            if set(final_manifest) != set(planned_manifest) or {
                key: final_manifest[key] for key in static_keys
            } != {key: planned_manifest[key] for key in static_keys}:
                raise LifecycleTransitionError(
                    "transition_materialization_plan_collision",
                    "preserve one exact immutable identity across plan and journal",
                    plan.transaction_id,
                )
            for name, content in plan.artifacts:
                if name == "manifest.json":
                    continue
                observed = _private_file_state(
                    final_directory / name,
                    max_bytes=_transaction_child_max_bytes(name),
                )
                if observed is None or observed.content != content:
                    raise LifecycleTransitionError(
                        "transition_materialization_plan_collision",
                        "restore every immutable artifact committed by the residual plan",
                        f"{plan.transaction_id}:{name}",
                    )
            _atomic_install(plan_path, None, None, locked_state)
            return plan.transaction_id, False

        if plan.transaction_id in receipts:
            raise LifecycleTransitionError(
                "transition_materialization_receipt_present",
                "restore the promoted journal before accepting any phase receipt",
                plan.transaction_id,
            )
        estate_journals, estate_children, estate_bytes = _lifecycle_estate_usage(
            root,
            materialization_root,
        )
        if (
            estate_journals > _MAX_LIFECYCLE_TRANSACTIONS
            or estate_children > _MAX_LIFECYCLE_TOTAL_CHILDREN
            or estate_bytes > _MAX_LIFECYCLE_TOTAL_BYTES
        ):
            raise LifecycleTransitionError(
                "transition_journal_estate_capacity_exceeded",
                "archive through a governed content-addressed frontier before recovery",
                plan.transaction_id,
            )

        if not stage_exists:
            stage_fd = _ensure_private_directory_fd(stage)
            os.close(stage_fd)
        expected = dict(plan.artifacts)
        observed_fd = _open_existing_private_directory_fd(stage)
        assert observed_fd is not None
        try:
            observed_names = set(os.listdir(observed_fd))
        finally:
            os.close(observed_fd)
        if not observed_names.issubset(expected):
            raise LifecycleTransitionError(
                "transition_materialization_artifact_unknown",
                "preserve and reconcile staged entries outside the recovery plan",
                plan.transaction_id,
            )
        for name, content in plan.artifacts:
            path = stage / name
            observed = _private_file_state(
                path,
                max_bytes=_transaction_child_max_bytes(name),
            )
            if observed is not None and observed.content != content:
                raise LifecycleTransitionError(
                    "transition_materialization_artifact_collision",
                    "preserve the first staged artifact and reconcile its bytes",
                    f"{plan.transaction_id}:{name}",
                )
            if observed is None:
                _atomic_install(path, content, 0o600, None)
        _fsync_directory(stage)
        staged_transaction = _load_transaction_manifest(stage / "manifest.json")
        if staged_transaction != transaction:
            raise LifecycleTransitionError(
                "transition_materialization_plan_collision",
                "promote only the exact fully rehydrated recovery transaction",
                plan.transaction_id,
            )

        source_fd = _open_existing_private_directory_fd(materialization_root)
        destination_fd = _open_existing_private_directory_fd(root)
        assert source_fd is not None and destination_fd is not None
        try:
            _renameat2(
                source_fd,
                plan.transaction_id,
                destination_fd,
                plan.transaction_id,
                _RENAME_NOREPLACE,
            )
            os.fsync(source_fd)
            os.fsync(destination_fd)
        finally:
            os.close(source_fd)
            os.close(destination_fd)
        _atomic_install(plan_path, None, None, locked_state)
        return plan.transaction_id, True


def _lifecycle_estate_usage(*roots: Path) -> tuple[int, int, int]:
    journals = 0
    children = 0
    total_bytes = 0
    final_transaction_ids: set[str] = set()
    if roots:
        final_fd = _open_existing_private_directory_fd(roots[0])
        if final_fd is not None:
            try:
                final_transaction_ids = {
                    name
                    for name in os.listdir(final_fd)
                    if _TRANSACTION_DIRECTORY_RE.fullmatch(name) is not None
                }
            finally:
                os.close(final_fd)
    for root_index, root in enumerate(roots):
        root_fd = _open_existing_private_directory_fd(root)
        if root_fd is None:
            continue
        try:
            root_names = tuple(sorted(os.listdir(root_fd)))
            plans: dict[str, tuple[LifecycleMaterializationPlan, int]] = {}
            if root_index > 0:
                for name in root_names:
                    match = _MATERIALIZATION_PLAN_RE.fullmatch(name)
                    if match is None:
                        continue
                    plan_path = root / name
                    state = _private_file_state(
                        plan_path,
                        max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
                    )
                    if state is None:
                        raise LifecycleTransitionError(
                            "transition_materialization_plan_missing",
                            "restore the private materialization plan",
                            str(plan_path),
                        )
                    plan = _load_materialization_plan(
                        plan_path,
                        content=state.content,
                    )
                    _validated_materialization_plan_transaction(plan, plan_path)
                    plans[plan.transaction_id] = (plan, len(state.content))
                    children += 1
                    total_bytes += len(state.content)
                    if plan.transaction_id not in final_transaction_ids:
                        journals += 1
                        children += len(plan.artifacts) + 2
                        total_bytes += (
                            sum(len(content) for _name, content in plan.artifacts)
                            + 2 * _MAX_LIFECYCLE_PHASE_BYTES
                        )
            for name in root_names:
                if root_index > 0 and _MATERIALIZATION_PLAN_RE.fullmatch(name):
                    continue
                if _TRANSACTION_DIRECTORY_RE.fullmatch(name) is None:
                    raise LifecycleTransitionError(
                        "transition_manifest_root_entry_unknown",
                        "quarantine entries outside the transaction grammar",
                        str(root / name),
                    )
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
                directory_fd = os.open(name, flags, dir_fd=root_fd)
                try:
                    metadata = os.fstat(directory_fd)
                    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
                        raise LifecycleTransitionError(
                            "transition_manifest_directory_unsafe",
                            "restore every journal as one private owned directory",
                            str(root / name),
                        )
                    names = tuple(sorted(os.listdir(directory_fd)))
                    planned = plans.get(name)
                    if root_index > 0 and planned is not None:
                        if name in final_transaction_ids:
                            raise LifecycleTransitionError(
                                "transition_materialization_identity_collision",
                                "reconcile the staged and promoted copies before continuing",
                                name,
                            )
                        expected = dict(planned[0].artifacts)
                        if not set(names).issubset(expected):
                            raise LifecycleTransitionError(
                                "transition_materialization_artifact_unknown",
                                "preserve and reconcile entries outside the recovery plan",
                                name,
                            )
                        for child in names:
                            state = _private_file_state(
                                root / name / child,
                                max_bytes=_transaction_child_max_bytes(child),
                            )
                            if state is None or state.content != expected[child]:
                                raise LifecycleTransitionError(
                                    "transition_materialization_artifact_collision",
                                    "preserve the first staged artifact and reconcile its bytes",
                                    f"{name}:{child}",
                                )
                        continue
                    journals += 1
                    children += len(names)
                    phase_count = sum(
                        _TRANSACTION_PHASE_PROJECTION_RE.fullmatch(child) is not None
                        for child in names
                    )
                    missing_phase_count = max(0, 2 - phase_count)
                    children += missing_phase_count
                    total_bytes += missing_phase_count * _MAX_LIFECYCLE_PHASE_BYTES
                    for child in names:
                        item = os.stat(
                            child,
                            dir_fd=directory_fd,
                            follow_symlinks=False,
                        )
                        if (
                            not stat.S_ISREG(item.st_mode)
                            or item.st_uid != os.geteuid()
                            or item.st_nlink != 1
                            or stat.S_IMODE(item.st_mode) != 0o600
                        ):
                            raise LifecycleTransitionError(
                                "transition_private_file_unsafe",
                                "restore every journal artifact as one private regular file",
                                str(root / name / child),
                            )
                        total_bytes += item.st_size
                finally:
                    os.close(directory_fd)
        finally:
            os.close(root_fd)
    return journals, children, total_bytes


@contextmanager
def _lifecycle_estate_lock(root: Path):
    """Serialize capacity and journal materialization on the canonical estate."""

    handle = _ensure_private_directory_fd(root)
    locked = False
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        locked = True
        metadata = os.fstat(handle)
        named = os.stat(root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(named.st_mode)
            or metadata.st_dev != named.st_dev
            or metadata.st_ino != named.st_ino
        ):
            raise LifecycleTransitionError(
                "transition_estate_lock_identity_changed",
                "hold until the canonical transaction root names the locked estate",
                str(root),
            )
        yield
    finally:
        if locked:
            fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


@contextmanager
def _transition_locks(task_id: str, paths: Sequence[Path], root: Path):
    keys = {f"task:{task_id}", *(f"path:{_normalized_path(path)}" for path in paths)}
    root_fd = _ensure_private_directory_fd(root)
    root_locked = False
    try:
        fcntl.flock(root_fd, fcntl.LOCK_EX)
        root_locked = True
        handles: list[tuple[str, int]] = []
        try:
            for key in sorted(keys):
                name = f"{_sha256(key.encode('utf-8'))}.lock"
                handle = os.open(
                    name,
                    os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=root_fd,
                )
                try:
                    metadata = os.fstat(handle)
                    if (
                        not stat.S_ISREG(metadata.st_mode)
                        or metadata.st_uid != os.geteuid()
                        or metadata.st_nlink != 1
                        or metadata.st_mode & 0o777 != 0o600
                        or metadata.st_size != 0
                    ):
                        raise LifecycleTransitionError(
                            "transition_lock_file_unsafe",
                            "use one euid-owned single-link empty mode-0600 lock file",
                            str(root / name),
                        )
                    fcntl.flock(handle, fcntl.LOCK_EX)
                    locked_metadata = os.fstat(handle)
                    named_metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                    if (
                        locked_metadata.st_nlink != 1
                        or locked_metadata.st_dev != named_metadata.st_dev
                        or locked_metadata.st_ino != named_metadata.st_ino
                    ):
                        raise LifecycleTransitionError(
                            "transition_lock_identity_changed",
                            "hold until the canonical lock pathname names the inode under flock",
                            str(root / name),
                        )
                except Exception:
                    os.close(handle)
                    raise
                handles.append((name, handle))
            for name, handle in handles:
                metadata = os.fstat(handle)
                named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                if (
                    metadata.st_nlink != 1
                    or metadata.st_dev != named.st_dev
                    or metadata.st_ino != named.st_ino
                ):
                    raise LifecycleTransitionError(
                        "transition_lock_identity_changed",
                        "hold until every canonical lock pathname names its inode under flock",
                        str(root / name),
                    )
            yield tuple(str(root / name) for name, _handle in handles)
        finally:
            for _name, handle in reversed(handles):
                try:
                    fcntl.flock(handle, fcntl.LOCK_UN)
                    os.close(handle)
                except OSError:
                    pass
    finally:
        if root_locked:
            fcntl.flock(root_fd, fcntl.LOCK_UN)
        os.close(root_fd)


def _write_manifest(
    root: Path,
    operation_id: str,
    attempt_no: int,
    transaction_id: str,
    intent: LifecycleTransitionIntent,
    projections: Sequence[FileProjection],
    scratches: Sequence[_ProjectionScratch],
    *,
    timestamp: str,
    state: str,
    reason_code: str | None = None,
) -> Path:
    directory = root / transaction_id
    definition_payload = (
        _canonical_json_bytes(intent.lifecycle_definition.model_dump(mode="json", by_alias=True))
        + b"\n"
    )
    immutable_artifacts: dict[str, bytes] = {
        _LIFECYCLE_SOURCE_BLOB: intent.lifecycle_source,
        _LIFECYCLE_DEFINITION_BLOB: definition_payload,
    }
    records: list[dict[str, Any]] = []
    for index, (projection, scratch) in enumerate(zip(projections, scratches, strict=True)):
        record = projection.to_record()
        record["scratch_kind"] = scratch.kind
        record["scratch_name"] = scratch.path.name
        for label, payload in (
            ("before", projection.before),
            ("after", projection.after),
        ):
            if payload is None:
                record[f"{label}_blob"] = None
                continue
            blob_name = f"{index:04d}.{label}"
            immutable_artifacts[blob_name] = payload
            record[f"{label}_blob"] = blob_name
        records.append(record)
    manifest_path = directory / "manifest.json"
    static = {
        "attempt_no": attempt_no,
        "created_at": timestamp,
        "intent": intent.to_record(),
        "lifecycle_definition": intent.lifecycle_definition_binding.to_record(),
        "operation_id": operation_id,
        "projections": records,
        "schema": TRANSITION_TRANSACTION_SCHEMA,
        "transaction_id": transaction_id,
    }
    if (state in {"aborted", "recovery_required"}) != (reason_code is not None):
        raise LifecycleTransitionError(
            "transition_manifest_reason_state_mismatch",
            "bind a reason exactly to aborted or recovery-required state",
            state,
        )
    body = {**static, "reason_code": reason_code, "state": state}
    manifest_payload = _canonical_json_bytes(body) + b"\n"
    if (
        len(immutable_artifacts) + 3 > _MAX_LIFECYCLE_JOURNAL_CHILDREN
        or len(manifest_payload) > _MAX_LIFECYCLE_MANIFEST_BYTES
        or any(len(payload) > _MAX_LIFECYCLE_BLOB_BYTES for payload in immutable_artifacts.values())
        or sum(len(payload) for payload in immutable_artifacts.values())
        + len(manifest_payload)
        + 2 * _MAX_LIFECYCLE_PHASE_BYTES
        > _MAX_LIFECYCLE_JOURNAL_BYTES
    ):
        raise LifecycleTransitionError(
            "transition_manifest_inspection_bound_exceeded",
            "decompose the transition before writing an uninspectable journal",
            transaction_id,
        )
    materialization_plan = (
        LifecycleMaterializationPlan.create(
            transaction_id,
            {**immutable_artifacts, "manifest.json": manifest_payload},
        )
        if state == "created"
        else None
    )
    materialization_plan_payload = (
        materialization_plan.payload() if materialization_plan is not None else None
    )
    materialization_root = _materialization_root(root)

    def existing_directory(path: Path) -> bool:
        handle = _open_existing_private_directory_fd(path)
        if handle is None:
            return False
        os.close(handle)
        return True

    final_exists = existing_directory(directory)
    staged_exists = existing_directory(materialization_root / transaction_id)
    if final_exists and staged_exists:
        raise LifecycleTransitionError(
            "transition_materialization_identity_collision",
            "reconcile the staged and promoted copies before continuing",
            transaction_id,
        )
    plan_path = materialization_root / _materialization_plan_name(transaction_id)
    materialization_root_exists = existing_directory(materialization_root)
    plan_state = (
        _private_file_state(
            plan_path,
            max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
        )
        if materialization_root_exists
        else None
    )
    if final_exists and plan_state is not None:
        residual_plan = _load_materialization_plan(
            plan_path,
            content=plan_state.content,
        )
        planned_manifest = _load_private_manifest_payload(
            directory / "manifest.json",
            content=residual_plan.artifact("manifest.json"),
        )
        if {key: planned_manifest.get(key) for key in static} != static:
            raise LifecycleTransitionError(
                "transition_materialization_plan_collision",
                "reconcile the residual plan against the promoted journal",
                transaction_id,
            )
    if not final_exists:
        assert materialization_plan_payload is not None
        if plan_state is not None and plan_state.content != materialization_plan_payload:
            raise LifecycleTransitionError(
                "transition_materialization_plan_collision",
                "preserve the first recovery plan and reconcile its identity",
                transaction_id,
            )
        if staged_exists and plan_state is None:
            raise LifecycleTransitionError(
                "transition_materialization_plan_missing",
                "restore the self-contained recovery plan for the staged journal",
                transaction_id,
            )
        if staged_exists:
            expected_stage = {
                **immutable_artifacts,
                "manifest.json": manifest_payload,
            }
            stage_fd = _open_existing_private_directory_fd(materialization_root / transaction_id)
            assert stage_fd is not None
            try:
                stage_names = tuple(sorted(os.listdir(stage_fd)))
            finally:
                os.close(stage_fd)
            if not set(stage_names).issubset(expected_stage):
                raise LifecycleTransitionError(
                    "transition_materialization_artifact_unknown",
                    "preserve and reconcile entries outside the recovery plan",
                    transaction_id,
                )
            for name in stage_names:
                state_entry = _private_file_state(
                    materialization_root / transaction_id / name,
                    max_bytes=_transaction_child_max_bytes(name),
                )
                if state_entry is None or state_entry.content != expected_stage[name]:
                    raise LifecycleTransitionError(
                        "transition_materialization_artifact_collision",
                        "preserve the first staged artifact and reconcile its bytes",
                        f"{transaction_id}:{name}",
                    )
    estate_journals, estate_children, estate_bytes = _lifecycle_estate_usage(
        root,
        materialization_root,
    )
    if not final_exists and plan_state is None:
        assert materialization_plan_payload is not None
        expected_children = len(immutable_artifacts) + 4
        expected_bytes = (
            len(materialization_plan_payload)
            + sum(len(payload) for payload in immutable_artifacts.values())
            + len(manifest_payload)
            + 2 * _MAX_LIFECYCLE_PHASE_BYTES
        )
        estate_journals += 1
        estate_children += expected_children
        estate_bytes += expected_bytes
    if (
        estate_journals > _MAX_LIFECYCLE_TRANSACTIONS
        or estate_children > _MAX_LIFECYCLE_TOTAL_CHILDREN
        or estate_bytes > _MAX_LIFECYCLE_TOTAL_BYTES
    ):
        raise LifecycleTransitionError(
            "transition_journal_estate_capacity_exceeded",
            "archive through a governed content-addressed frontier before writing",
            transaction_id,
        )
    root_fd = _ensure_private_directory_fd(root)
    os.close(root_fd)
    final_directory = directory
    directory_fd = _open_existing_private_directory_fd(final_directory)
    materializing = directory_fd is None
    if materializing:
        if state != "created":
            raise LifecycleTransitionError(
                "transition_materialization_manifest_missing",
                "recover the initial created journal before advancing its state",
                transaction_id,
            )
        materialization_root_fd = _ensure_private_directory_fd(materialization_root)
        os.close(materialization_root_fd)
        assert materialization_plan_payload is not None
        if plan_state is None:
            plan_state = _atomic_install(
                plan_path,
                materialization_plan_payload,
                0o600,
                None,
            )
        directory = materialization_root / transaction_id
        directory_fd = _open_existing_private_directory_fd(directory)
    if directory_fd is None:
        directory_fd = _ensure_private_directory_fd(directory)
    os.close(directory_fd)
    manifest_path = directory / "manifest.json"
    manifest_state = _private_file_state(
        manifest_path,
        max_bytes=_MAX_LIFECYCLE_MANIFEST_BYTES,
    )
    if manifest_state is not None:
        current = _load_private_manifest_payload(manifest_path)
        if set(current) != {
            "attempt_no",
            "created_at",
            "intent",
            "lifecycle_definition",
            "operation_id",
            "projections",
            "reason_code",
            "schema",
            "state",
            "transaction_id",
        }:
            raise LifecycleTransitionError(
                "transition_manifest_schema_unknown",
                "use the checked lifecycle transaction manifest schema",
                str(manifest_path),
            )
        observed_static = {key: current.get(key) for key in static}
        if observed_static != static:
            raise LifecycleTransitionError(
                "transition_manifest_collision",
                "preserve the first transaction manifest and investigate conflicting intent",
                transaction_id,
            )
        current_state = str(current.get("state") or "")
        allowed = {
            "created": {
                "created",
                "prepared",
                "projecting",
                "postimage_complete",
                "aborted",
                "recovery_required",
            },
            "prepared": {
                "prepared",
                "projecting",
                "postimage_complete",
                "applied",
                "aborted",
                "recovery_required",
            },
            "projecting": {
                "projecting",
                "postimage_complete",
                "applied",
                "aborted",
                "recovery_required",
            },
            "postimage_complete": {
                "postimage_complete",
                "applied",
                "aborted",
                "recovery_required",
            },
            "applied": {"applied"},
            "aborted": {"aborted"},
            "recovery_required": {"recovery_required", "applied", "aborted"},
        }
        if state not in allowed.get(current_state, set()):
            raise LifecycleTransitionError(
                "transition_manifest_state_regression",
                "preserve the monotonic transaction journal state",
                f"{current_state}->{state}",
            )
    for name, payload in immutable_artifacts.items():
        artifact_path = directory / name
        artifact_state = _private_file_state(
            artifact_path,
            max_bytes=_transaction_child_max_bytes(name),
        )
        if artifact_state is not None and artifact_state.content != payload:
            raise LifecycleTransitionError(
                "transition_manifest_blob_collision",
                "preserve the first immutable journal artifact and reconcile",
                str(artifact_path),
            )
        if artifact_state is None:
            _atomic_install(artifact_path, payload, 0o600, None)
    _atomic_install(
        manifest_path,
        manifest_payload,
        0o600,
        manifest_state,
    )
    if not materializing:
        if plan_state is not None:
            _atomic_install(plan_path, None, None, plan_state)
        return manifest_path
    source_parent_fd = _open_existing_private_directory_fd(directory.parent)
    destination_parent_fd = _open_existing_private_directory_fd(root)
    assert source_parent_fd is not None and destination_parent_fd is not None
    try:
        _renameat2(
            source_parent_fd,
            transaction_id,
            destination_parent_fd,
            transaction_id,
            _RENAME_NOREPLACE,
        )
        os.fsync(source_parent_fd)
        os.fsync(destination_parent_fd)
    except OSError as exc:
        raise LifecycleTransitionError(
            "transition_materialization_promotion_failed",
            "preserve the staged journal and reconcile its final identity",
            transaction_id,
        ) from exc
    finally:
        os.close(source_parent_fd)
        os.close(destination_parent_fd)
    assert plan_state is not None
    _atomic_install(plan_path, None, None, plan_state)
    return final_directory / "manifest.json"


_PHASE_EVENT_TYPES = {
    "prepared": CANON_TRANSITION_PREPARED,
    "applied": CANON_TRANSITION_APPLIED,
    "aborted": CANON_TRANSITION_ABORTED,
}


def _events_for_operation(
    event_log: CoordEventLog,
    operation_id: str,
    *,
    replay_events: Sequence[CoordEvent] | None = None,
) -> dict[int, dict[str, CoordEvent]]:
    if replay_events is None:
        replay = event_log.replay(fail_open=False)
        if replay.degraded or replay.source != "sqlite":
            raise LifecycleTransitionError(
                "transition_receipt_replay_degraded",
                "restore the canonical SQLite coordination ledger before transition",
            )
        replay_events = replay.events
    attempts: dict[int, dict[str, CoordEvent]] = {}
    for event in replay_events:
        payload = event.payload
        if payload.get("schema") == TRANSITION_TRANSACTION_SCHEMA_V1:
            continue
        if payload.get("operation_id") != operation_id:
            continue
        phase = payload.get("phase")
        attempt_no = payload.get("attempt_no")
        transaction_id = payload.get("transaction_id")
        if (
            payload.get("schema") != TRANSITION_TRANSACTION_SCHEMA
            or phase not in _PHASE_EVENT_TYPES
            or not isinstance(attempt_no, int)
            or attempt_no < 0
            or transaction_id != _attempt_transaction_id(operation_id, attempt_no)
            or event.event_id != f"{transaction_id}.{phase}"
            or event.event_type != _PHASE_EVENT_TYPES[phase]
        ):
            raise LifecycleTransitionError(
                "transition_phase_receipt_malformed",
                "restore only exact typed phase receipts for this operation",
                event.event_id,
            )
        phases = attempts.setdefault(attempt_no, {})
        if phase in phases:
            raise LifecycleTransitionError(
                "transition_phase_receipt_duplicate",
                "retain one exact phase receipt per operation attempt",
                event.event_id,
            )
        phases[str(phase)] = event
    for attempt_no, phases in attempts.items():
        if "applied" in phases and "aborted" in phases:
            raise LifecycleTransitionError(
                "transition_phase_receipt_contradiction",
                "hold the operation and reconcile its applied and aborted receipts",
                _attempt_transaction_id(operation_id, attempt_no),
            )
    return attempts


def _transaction_receipt_census(
    event_log: CoordEventLog,
    *,
    replay: ReplayResult | None = None,
) -> dict[str, tuple[str, str, dict[str, CoordEvent]]]:
    replay = replay if replay is not None else event_log.replay(fail_open=False)
    if replay.degraded or replay.source != "sqlite":
        raise LifecycleTransitionError(
            "transition_receipt_replay_degraded",
            "restore the canonical SQLite coordination ledger before transition recovery",
        )
    operation_ids: set[str] = set()
    for event in replay.events:
        payload = event.payload
        schema = payload.get("schema")
        if schema == TRANSITION_TRANSACTION_SCHEMA_V1:
            continue
        if event.event_type not in _PHASE_EVENT_TYPES.values() and schema != (
            TRANSITION_TRANSACTION_SCHEMA_V2
        ):
            continue
        if schema != TRANSITION_TRANSACTION_SCHEMA_V2:
            raise LifecycleTransitionError(
                "transition_phase_receipt_malformed",
                "restore every current phase event under the v2 transaction schema",
                event.event_id,
            )
        operation_id = payload.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise LifecycleTransitionError(
                "transition_phase_receipt_malformed",
                "restore every transition phase receipt with one operation identity",
                event.event_id,
            )
        operation_ids.add(operation_id)
    census: dict[str, tuple[str, str, dict[str, CoordEvent]]] = {}
    for operation_id in sorted(operation_ids):
        attempts = _events_for_operation(
            event_log,
            operation_id,
            replay_events=replay.events,
        )
        for attempt_no, phases in attempts.items():
            transaction_id = _attempt_transaction_id(operation_id, attempt_no)
            subjects = {event.subject for event in phases.values()}
            if len(subjects) != 1:
                raise LifecycleTransitionError(
                    "transition_phase_receipt_subject_mismatch",
                    "restore every phase receipt against one exact task subject",
                    transaction_id,
                )
            if transaction_id in census:
                raise LifecycleTransitionError(
                    "transition_phase_receipt_transaction_duplicate",
                    "retain one phase lineage per transaction identity",
                    transaction_id,
                )
            census[transaction_id] = (operation_id, next(iter(subjects)), phases)
    return census


def _manifest_headers(root: Path, operation_id: str) -> dict[int, dict[str, Any]]:
    headers: dict[int, dict[str, Any]] = {}
    final_paths = _transaction_manifest_paths(root)
    materialized_paths = _transaction_manifest_paths(
        _materialization_root(root),
        allow_materialization_plans=True,
    )
    for path in (*final_paths, *materialized_paths):
        if not path.parent.name.startswith(f"{operation_id}.attempt-"):
            continue
        if (
            path in materialized_paths
            and _private_file_state(
                path,
                max_bytes=_MAX_LIFECYCLE_MANIFEST_BYTES,
            )
            is None
        ):
            continue
        (
            observed_operation_id,
            attempt_no,
            transaction_id,
            created_at,
            _intent,
            _projections,
            _scratches,
            state,
        ) = _load_transaction_manifest(path)
        if (
            observed_operation_id != operation_id
            or transaction_id != _attempt_transaction_id(operation_id, attempt_no)
            or path.parent.name != transaction_id
        ):
            raise LifecycleTransitionError(
                "transition_manifest_identity_mismatch",
                "restore the manifest bound to its operation and attempt identity",
                str(path),
            )
        if attempt_no in headers:
            raise LifecycleTransitionError(
                "transition_manifest_attempt_duplicate",
                "retain one durable manifest per operation attempt",
                str(path),
            )
        headers[attempt_no] = {"created_at": created_at, "state": state}
    return headers


def _select_attempt(
    event_log: CoordEventLog, root: Path, operation_id: str
) -> tuple[int, str, str, dict[str, CoordEvent]]:
    attempts = _events_for_operation(event_log, operation_id)
    headers = _manifest_headers(root, operation_id)
    for number, phases in attempts.items():
        if "aborted" not in phases:
            continue
        header = headers.get(number)
        if header is None or header.get("state") != "aborted":
            raise LifecycleTransitionError(
                "transition_aborted_projection_unreconciled",
                "reconcile the aborted append projection and terminal manifest before retrying",
                _attempt_transaction_id(operation_id, number),
            )
    applied = [(number, phases) for number, phases in attempts.items() if "applied" in phases]
    if len(applied) > 1:
        raise LifecycleTransitionError(
            "transition_operation_applied_multiple",
            "reconcile the operation that has more than one applied attempt",
            operation_id,
        )
    if applied:
        number, phases = applied[0]
        timestamp = phases.get("prepared", phases["applied"]).timestamp
        return number, timestamp, "applied", phases
    unresolved = [
        (number, phases)
        for number, phases in attempts.items()
        if "prepared" in phases and "aborted" not in phases
    ]
    if len(unresolved) > 1:
        raise LifecycleTransitionError(
            "transition_operation_prepared_multiple",
            "recover the earlier prepared attempt before selecting another",
            operation_id,
        )
    if unresolved:
        number, phases = unresolved[0]
        return number, phases["prepared"].timestamp, "prepared", phases
    created = [
        (number, header)
        for number, header in headers.items()
        if number not in attempts and header.get("state") == "created"
    ]
    uncertain = [
        number for number, header in headers.items() if header.get("state") == "recovery_required"
    ]
    if uncertain:
        raise LifecycleTransitionError(
            "transition_prior_recovery_required",
            "recover the uncertain attempt before constructing another",
            _attempt_transaction_id(operation_id, max(uncertain)),
        )
    if len(created) > 1:
        raise LifecycleTransitionError(
            "transition_operation_created_multiple",
            "recover the earlier not-started attempt before selecting another",
            operation_id,
        )
    if created:
        number, header = created[0]
        return number, str(header["created_at"]), "created", {}
    highest = max({*attempts, *headers}, default=-1)
    number = highest + 1
    return number, "", "new", {}


def _canonical_execution_inputs(
    intent: LifecycleTransitionIntent,
    projections: Sequence[FileProjection],
) -> tuple[LifecycleTransitionIntent, tuple[FileProjection, ...]]:
    """Detach and revalidate every caller-owned value before acquiring locks."""

    if type(intent) is not LifecycleTransitionIntent:
        raise LifecycleTransitionError(
            "transition_intent_shape_malformed",
            "supply one exact canonical lifecycle intent",
        )
    try:
        intent_record = json.loads(_canonical_json_bytes(intent.to_record()))
        checked_intent = LifecycleTransitionIntent.from_record(
            intent_record,
            lifecycle_definition=intent.lifecycle_definition,
            lifecycle_source=bytes(intent.lifecycle_source),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LifecycleTransitionError(
            "transition_intent_shape_malformed",
            "supply one exact canonical immutable lifecycle intent",
            type(exc).__name__,
        ) from exc
    if checked_intent.to_record() != intent_record:
        raise LifecycleTransitionError(
            "transition_intent_shape_malformed",
            "supply the canonical lifecycle intent wire image",
            intent.task_id,
        )

    detached: list[FileProjection] = []
    try:
        for projection in tuple(projections):
            if type(projection) is not FileProjection:
                raise TypeError("projection is not an exact FileProjection")
            checked = FileProjection.from_snapshot(
                projection.path,
                before=projection.before,
                before_mode=projection.before_mode,
                after=projection.after,
                after_mode=projection.after_mode,
            )
            if checked.to_record() != projection.to_record():
                raise ValueError("projection wire image is noncanonical")
            detached.append(checked)
    except (TypeError, ValueError) as exc:
        raise LifecycleTransitionError(
            "transition_projection_shape_malformed",
            "supply exact immutable file projections",
            type(exc).__name__,
        ) from exc
    return checked_intent, tuple(detached)


def _execute_lifecycle_transition(
    *,
    event_log: CoordEventLog,
    intent: LifecycleTransitionIntent,
    projections: Sequence[FileProjection],
    transaction_root: Path | None = None,
    lock_root: Path | None = None,
    timestamp: str | None = None,
    failure_hook: Callable[[str, int | None], None] | None = None,
    terminal_close_admission: Mapping[str, Any] | None = None,
    locked_preflight: Callable[[], None] | None = None,
) -> LifecycleTransitionReceipt:
    """Apply one exact lifecycle transition with strict receipts and CAS rollback."""

    _require_lifecycle_effect_activation()
    intent, ordered = _canonical_execution_inputs(intent, projections)
    _validate_terminal_close_admission(intent, terminal_close_admission)
    if intent.from_stage == "S10" and intent.to_stage == "S11" and locked_preflight is None:
        raise LifecycleTransitionError(
            "transition_terminal_locked_preflight_missing",
            "revalidate the exact close position under the transaction lock",
        )
    if not ordered:
        raise LifecycleTransitionError(
            "transition_projection_empty",
            "declare at least one exact state projection",
        )
    projected_admission = _projected_terminal_close_admission(intent, ordered)
    if projected_admission != (
        dict(terminal_close_admission) if terminal_close_admission is not None else None
    ):
        raise LifecycleTransitionError(
            "transition_terminal_admission_projection_mismatch",
            "bind the executor admission to the exact admission receipt projection",
            intent.task_id,
        )
    _validate_terminal_admission_projection_bindings(projected_admission, ordered)
    paths = [item.path for item in ordered]
    if len(paths) != len(set(paths)):
        raise LifecycleTransitionError(
            "transition_projection_path_duplicate",
            "project each path exactly once per transaction",
        )
    projection_payloads = tuple(
        payload
        for projection in ordered
        for payload in (projection.before, projection.after)
        if payload is not None
    )
    if len(projection_payloads) + 5 > _MAX_LIFECYCLE_JOURNAL_CHILDREN or any(
        len(payload) > _MAX_LIFECYCLE_BLOB_BYTES for payload in projection_payloads
    ):
        raise LifecycleTransitionError(
            "transition_manifest_inspection_bound_exceeded",
            "decompose the transition before writing an uninspectable journal",
        )
    operation_id = lifecycle_transition_id(intent, ordered)
    manifest_root = _manifest_root(transaction_root)
    lock_directory = _lock_root(lock_root)
    with (
        _transition_locks(intent.task_id, paths, lock_directory),
        _lifecycle_estate_lock(manifest_root),
    ):
        attempt_no, prior_timestamp, attempt_state, existing = _select_attempt(
            event_log, manifest_root, operation_id
        )
        transaction_id = _attempt_transaction_id(operation_id, attempt_no)
        created_at = prior_timestamp or timestamp or _now_iso()
        scratches = tuple(
            _scratch_for(projection, transaction_id, index)
            for index, projection in enumerate(ordered)
        )

        def phase_event(phase: str, *, reason_code: str | None = None) -> CoordEvent:
            return _transaction_event(
                event_type=_PHASE_EVENT_TYPES[phase],
                phase=phase,
                transaction_id=transaction_id,
                operation_id=operation_id,
                attempt_no=attempt_no,
                intent=intent,
                projections=ordered,
                timestamp=created_at,
                reason_code=reason_code,
            )

        def replay_receipt(event: CoordEvent) -> AppendReceipt:
            if event.sequence is None:
                raise LifecycleTransitionError(
                    "transition_phase_projection_sequence_missing",
                    "restore the positive canonical sequence before projection",
                    event.event_id,
                )
            return AppendReceipt(
                event_id=event.event_id,
                appended=True,
                spooled=False,
                sequence=event.sequence,
                db_path=event_log.db_path,
                jsonl_path=event_log.jsonl_path,
            )

        def project_terminal_phase(
            event: CoordEvent,
            receipt: AppendReceipt,
            prior: LifecyclePhaseAppendProjection,
            *,
            mark_failure: bool = True,
        ) -> LifecyclePhaseAppendProjection:
            try:
                return _project_phase_append_receipt(
                    manifest_root / transaction_id,
                    event,
                    receipt,
                    prior=prior,
                )
            except Exception as exc:
                reason = "transition_terminal_phase_projection_persistence_failed"
                if mark_failure:
                    try:
                        _write_manifest(
                            manifest_root,
                            operation_id,
                            attempt_no,
                            transaction_id,
                            intent,
                            ordered,
                            scratches,
                            timestamp=created_at,
                            state="recovery_required",
                            reason_code=reason,
                        )
                    except Exception as journal_exc:
                        raise LifecycleTransitionError(
                            "transition_terminal_phase_projection_persistence_unknown",
                            "hold the attempt until its terminal append and journal are reconciled",
                            transaction_id,
                        ) from journal_exc
                raise LifecycleTransitionError(
                    reason,
                    "hold the attempt until its terminal append projection is durable",
                    transaction_id,
                ) from exc

        prepared_event = phase_event("prepared")
        applied_event = phase_event("applied")

        def assert_phase_projection_bounds() -> None:
            maximum_sequence = (1 << 53) - 1

            def receipt(event: CoordEvent, sequence: int) -> AppendReceipt:
                return AppendReceipt(
                    event_id=event.event_id,
                    appended=True,
                    spooled=False,
                    sequence=sequence,
                    db_path=event_log.db_path,
                    jsonl_path=event_log.jsonl_path,
                )

            prepared_bound = LifecyclePhaseAppendProjection.create(
                event=prepared_event,
                receipt=receipt(prepared_event, maximum_sequence - 1),
                prior_projection_ref=None,
            )
            terminal_events = (
                applied_event,
                phase_event(
                    "aborted",
                    reason_code="x" * _MAX_LIFECYCLE_REASON_CODE_BYTES,
                ),
            )
            payloads = (
                _canonical_json_bytes(prepared_bound.to_record()) + b"\n",
                *(
                    _canonical_json_bytes(
                        LifecyclePhaseAppendProjection.create(
                            event=event,
                            receipt=receipt(event, maximum_sequence),
                            prior_projection_ref=prepared_bound.projection_ref,
                        ).to_record()
                    )
                    + b"\n"
                    for event in terminal_events
                ),
            )
            if any(len(payload) > _MAX_LIFECYCLE_PHASE_BYTES for payload in payloads):
                raise LifecycleTransitionError(
                    "transition_phase_projection_inspection_bound_exceeded",
                    "decompose the transition before any canonical phase append",
                    transaction_id,
                )

        assert_phase_projection_bounds()

        if attempt_state == "applied":
            applied_existing = _find_exact_event(event_log, applied_event)
            if applied_existing is None:
                raise LifecycleTransitionError(
                    "transition_applied_receipt_missing",
                    "restore the exact applied receipt selected for this operation",
                    transaction_id,
                )
            prepared_existing = existing.get("prepared")
            if prepared_existing is None:
                raise LifecycleTransitionError(
                    "transition_prepared_receipt_missing",
                    "restore prepared before the applied lifecycle receipt",
                    transaction_id,
                )
            prepared_existing = _find_exact_event(event_log, prepared_event)
            assert prepared_existing is not None
            prepared_projection = _project_phase_append_receipt(
                manifest_root / transaction_id,
                prepared_event,
                replay_receipt(prepared_existing),
                prior=None,
            )
            project_terminal_phase(
                applied_event,
                replay_receipt(applied_existing),
                prepared_projection,
                mark_failure=False,
            )
            if any(not _state_matches(item.path, item.after, item.after_mode) for item in ordered):
                raise LifecycleTransitionError(
                    "transition_applied_postimage_drift",
                    "restore the exact applied projection before replaying its receipt",
                    transaction_id,
                )
            _finalize_applied_scratches(ordered, scratches)
            manifest_path = _write_manifest(
                manifest_root,
                operation_id,
                attempt_no,
                transaction_id,
                intent,
                ordered,
                scratches,
                timestamp=created_at,
                state="applied",
            )
            return LifecycleTransitionReceipt(
                operation_id=operation_id,
                attempt_no=attempt_no,
                transaction_id=transaction_id,
                prepared_event_id=prepared_event.event_id,
                applied_event_id=applied_event.event_id,
                prepared_sequence=prepared_existing.sequence,
                applied_sequence=applied_existing.sequence,
                manifest_path=manifest_path,
                replayed=True,
            )

        if attempt_state == "prepared":
            prepared_existing = _find_exact_event(event_log, prepared_event)
            if prepared_existing is None:
                raise LifecycleTransitionError(
                    "transition_prepared_receipt_missing",
                    "restore the exact prepared receipt selected for this operation",
                    transaction_id,
                )
            prepared_projection = _project_phase_append_receipt(
                manifest_root / transaction_id,
                prepared_event,
                replay_receipt(prepared_existing),
                prior=None,
            )
            if all(_state_matches(item.path, item.after, item.after_mode) for item in ordered):
                _finalize_applied_scratches(ordered, scratches)
                applied = _strict_append_exact(event_log, applied_event)
                project_terminal_phase(
                    applied_event,
                    applied,
                    prepared_projection,
                )
                manifest_path = _write_manifest(
                    manifest_root,
                    operation_id,
                    attempt_no,
                    transaction_id,
                    intent,
                    ordered,
                    scratches,
                    timestamp=created_at,
                    state="applied",
                )
                return LifecycleTransitionReceipt(
                    operation_id=operation_id,
                    attempt_no=attempt_no,
                    transaction_id=transaction_id,
                    prepared_event_id=prepared_event.event_id,
                    applied_event_id=applied_event.event_id,
                    prepared_sequence=prepared_existing.sequence,
                    applied_sequence=applied.sequence,
                    manifest_path=manifest_path,
                    replayed=True,
                )
            conflicts = _rollback_projections(ordered, scratches)
            reason_code = (
                "transition_projection_recovery_required"
                if conflicts
                else "transition_interrupted_projection_rolled_back"
            )
            aborted_event = phase_event("aborted", reason_code=reason_code)
            if not conflicts:
                aborted = _strict_append_exact(event_log, aborted_event)
                project_terminal_phase(
                    aborted_event,
                    aborted,
                    prepared_projection,
                )
            _write_manifest(
                manifest_root,
                operation_id,
                attempt_no,
                transaction_id,
                intent,
                ordered,
                scratches,
                timestamp=created_at,
                state="recovery_required" if conflicts else "aborted",
                reason_code=reason_code,
            )
            raise LifecycleTransitionError(
                reason_code,
                "reload the recovered current position before retrying",
                ",".join(conflicts) if conflicts else transaction_id,
            )

        _assert_preimages(ordered)
        if locked_preflight is not None:
            locked_preflight()
            _assert_preimages(ordered)
        manifest_path = _write_manifest(
            manifest_root,
            operation_id,
            attempt_no,
            transaction_id,
            intent,
            ordered,
            scratches,
            timestamp=created_at,
            state="created",
        )
        if failure_hook is not None:
            failure_hook("before_prepared", None)
        try:
            prepared = _strict_append_exact(event_log, prepared_event)
        except Exception:
            try:
                committed = _find_exact_event(event_log, prepared_event)
            except Exception as probe_exc:
                _write_manifest(
                    manifest_root,
                    operation_id,
                    attempt_no,
                    transaction_id,
                    intent,
                    ordered,
                    scratches,
                    timestamp=created_at,
                    state="recovery_required",
                    reason_code="transition_prepared_commit_unknown",
                )
                raise LifecycleTransitionError(
                    "transition_prepared_commit_unknown",
                    "restore canonical ledger readback before projecting any state",
                    transaction_id,
                ) from probe_exc
            if committed is None:
                raise
            prepared = AppendReceipt(
                event_id=prepared_event.event_id,
                appended=True,
                spooled=False,
                sequence=committed.sequence,
                db_path=event_log.db_path,
                jsonl_path=event_log.jsonl_path,
            )
        prepared_projection = _project_phase_append_receipt(
            manifest_root / transaction_id,
            prepared_event,
            prepared,
            prior=None,
        )
        _write_manifest(
            manifest_root,
            operation_id,
            attempt_no,
            transaction_id,
            intent,
            ordered,
            scratches,
            timestamp=created_at,
            state="prepared",
        )
        try:
            if failure_hook is not None:
                failure_hook("after_prepared", None)
            _write_manifest(
                manifest_root,
                operation_id,
                attempt_no,
                transaction_id,
                intent,
                ordered,
                scratches,
                timestamp=created_at,
                state="projecting",
            )
            _apply_projections(ordered, scratches, failure_hook)
            _finalize_applied_scratches(ordered, scratches)
            _write_manifest(
                manifest_root,
                operation_id,
                attempt_no,
                transaction_id,
                intent,
                ordered,
                scratches,
                timestamp=created_at,
                state="postimage_complete",
            )
            if failure_hook is not None:
                failure_hook("before_applied", None)
        except Exception as exc:
            conflicts = _rollback_projections(ordered, scratches)
            if (
                isinstance(exc, LifecycleTransitionError)
                and exc.reason_code == "transition_precondition_changed"
                and exc.detail is not None
            ):
                conflicts = tuple(path for path in conflicts if path != exc.detail)
            reason_code = (
                "transition_projection_recovery_required"
                if conflicts
                else getattr(exc, "reason_code", "transition_application_failed")
            )
            if not conflicts:
                aborted_event = phase_event("aborted", reason_code=reason_code)
                aborted = _strict_append_exact(event_log, aborted_event)
                project_terminal_phase(
                    aborted_event,
                    aborted,
                    prepared_projection,
                )
            _write_manifest(
                manifest_root,
                operation_id,
                attempt_no,
                transaction_id,
                intent,
                ordered,
                scratches,
                timestamp=created_at,
                state="recovery_required" if conflicts else "aborted",
                reason_code=reason_code,
            )
            if conflicts:
                raise LifecycleTransitionError(
                    reason_code,
                    "preserve every unrecognized byte and reconcile the transaction manually",
                    ",".join(conflicts),
                ) from exc
            raise

        try:
            applied = _strict_append_exact(event_log, applied_event)
        except Exception as exc:
            try:
                committed = _find_exact_event(event_log, applied_event)
            except Exception as probe_exc:
                _write_manifest(
                    manifest_root,
                    operation_id,
                    attempt_no,
                    transaction_id,
                    intent,
                    ordered,
                    scratches,
                    timestamp=created_at,
                    state="recovery_required",
                    reason_code="transition_applied_commit_unknown",
                )
                raise LifecycleTransitionError(
                    "transition_applied_commit_unknown",
                    "preserve the postimage until canonical ledger readback is restored",
                    transaction_id,
                ) from probe_exc
            if committed is None:
                conflicts = _rollback_projections(ordered, scratches)
                reason_code = (
                    "transition_projection_recovery_required"
                    if conflicts
                    else "transition_applied_receipt_absent"
                )
                if not conflicts:
                    aborted_event = phase_event("aborted", reason_code=reason_code)
                    aborted = _strict_append_exact(event_log, aborted_event)
                    project_terminal_phase(
                        aborted_event,
                        aborted,
                        prepared_projection,
                    )
                _write_manifest(
                    manifest_root,
                    operation_id,
                    attempt_no,
                    transaction_id,
                    intent,
                    ordered,
                    scratches,
                    timestamp=created_at,
                    state="recovery_required" if conflicts else "aborted",
                    reason_code=reason_code,
                )
                if conflicts:
                    raise LifecycleTransitionError(
                        reason_code,
                        "preserve every unrecognized byte and reconcile manually",
                        ",".join(conflicts),
                    ) from exc
                raise
            applied = AppendReceipt(
                event_id=applied_event.event_id,
                appended=True,
                spooled=False,
                sequence=committed.sequence,
                db_path=event_log.db_path,
                jsonl_path=event_log.jsonl_path,
            )
        project_terminal_phase(
            applied_event,
            applied,
            prepared_projection,
        )
        _write_manifest(
            manifest_root,
            operation_id,
            attempt_no,
            transaction_id,
            intent,
            ordered,
            scratches,
            timestamp=created_at,
            state="applied",
        )
        return LifecycleTransitionReceipt(
            operation_id=operation_id,
            attempt_no=attempt_no,
            transaction_id=transaction_id,
            prepared_event_id=prepared_event.event_id,
            applied_event_id=applied_event.event_id,
            prepared_sequence=prepared.sequence,
            applied_sequence=applied.sequence,
            manifest_path=manifest_path,
        )


def execute_lifecycle_transition(
    *,
    event_log: CoordEventLog,
    intent: LifecycleTransitionIntent,
    projections: Sequence[FileProjection],
    transaction_root: Path | None = None,
    lock_root: Path | None = None,
    timestamp: str | None = None,
    failure_hook: Callable[[str, int | None], None] | None = None,
    terminal_close_admission: Mapping[str, Any] | None = None,
    locked_preflight: Callable[[], None] | None = None,
) -> LifecycleTransitionReceipt:
    """Execute a nonterminal FSM projection; S10 -> S11 belongs only to cc-close."""

    if intent.from_stage == "S10" and intent.to_stage == "S11":
        raise LifecycleTransitionError(
            "transition_terminal_executor_required",
            "enter S11 only through the private governed cc-close executor",
            intent.task_id,
        )
    return _execute_lifecycle_transition(
        event_log=event_log,
        intent=intent,
        projections=projections,
        transaction_root=transaction_root,
        lock_root=lock_root,
        timestamp=timestamp,
        failure_hook=failure_hook,
        terminal_close_admission=terminal_close_admission,
        locked_preflight=locked_preflight,
    )


def _execute_terminal_close_transition(
    *,
    event_log: CoordEventLog,
    intent: LifecycleTransitionIntent,
    projections: Sequence[FileProjection],
    timestamp: str,
    terminal_close_admission: Mapping[str, Any],
    locked_preflight: Callable[[], None],
    failure_hook: Callable[[str, int | None], None] | None = None,
    transaction_root: Path | None = None,
    lock_root: Path | None = None,
) -> LifecycleTransitionReceipt:
    """Private terminal entry used by the claim-bound cc-close implementation."""

    if intent.from_stage != "S10" or intent.to_stage != "S11":
        raise LifecycleTransitionError(
            "transition_terminal_edge_required",
            "use the terminal executor only for the canonical S10 -> S11 edge",
            intent.task_id,
        )
    return _execute_lifecycle_transition(
        event_log=event_log,
        intent=intent,
        projections=projections,
        transaction_root=transaction_root,
        lock_root=lock_root,
        timestamp=timestamp,
        failure_hook=failure_hook,
        terminal_close_admission=terminal_close_admission,
        locked_preflight=locked_preflight,
    )


def _load_legacy_transaction_manifest(
    path: Path,
    *,
    manifest_content: bytes | None = None,
    captured_blobs: Mapping[str, tuple[bytes, int]] | None = None,
    captured_inventory: frozenset[str] | None = None,
    lifecycle_definition_content: bytes | None = None,
    lifecycle_catalog: object | None = None,
) -> tuple[
    str,
    int,
    str,
    str,
    LifecycleTransitionIntent,
    tuple[FileProjection, ...],
    tuple[_ProjectionScratch, ...],
    str,
]:
    payload = _load_private_manifest_payload(path, content=manifest_content)
    exact_keys = {
        "attempt_no",
        "created_at",
        "intent",
        "lifecycle_definition_sha256",
        "operation_id",
        "projections",
        "reason_code",
        "schema",
        "state",
        "transaction_id",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != exact_keys
        or payload.get("schema") != TRANSITION_TRANSACTION_SCHEMA
    ):
        raise LifecycleTransitionError(
            "transition_manifest_schema_unknown",
            "use the checked lifecycle transaction manifest schema",
            str(path),
        )
    transaction_id = payload.get("transaction_id")
    operation_id = payload.get("operation_id")
    attempt_no = payload.get("attempt_no")
    created_at = payload.get("created_at")
    state = payload.get("state")
    reason_code = payload.get("reason_code")
    intent_payload = payload.get("intent")
    records = payload.get("projections")
    if (
        not isinstance(transaction_id, str)
        or not transaction_id
        or not isinstance(operation_id, str)
        or not operation_id
        or type(attempt_no) is not int
        or attempt_no < 0
        or not isinstance(created_at, str)
        or not created_at
        or state
        not in {
            "created",
            "prepared",
            "projecting",
            "postimage_complete",
            "applied",
            "aborted",
            "recovery_required",
        }
        or not isinstance(intent_payload, dict)
        or not isinstance(records, list)
        or not records
        or (reason_code is not None and (not isinstance(reason_code, str) or not reason_code))
        or (state in {"aborted", "recovery_required"}) != (reason_code is not None)
    ):
        raise LifecycleTransitionError(
            "transition_manifest_shape_malformed",
            "restore the exact intent, timestamp, and projection records",
            str(path),
        )
    from shared.sdlc_lifecycle import SDLC_STAGE_METADATA_PATH

    lifecycle_bytes = (
        SDLC_STAGE_METADATA_PATH.read_bytes()
        if lifecycle_definition_content is None
        else lifecycle_definition_content
    )
    if payload.get("lifecycle_definition_sha256") != _sha256(lifecycle_bytes):
        raise LifecycleTransitionError(
            "transition_manifest_lifecycle_drift",
            "recover under the exact lifecycle definition that prepared the transaction",
            transaction_id,
        )
    projections: list[FileProjection] = []
    expected_record_keys = {
        "after_blob",
        "after_mode",
        "after_present",
        "after_sha256",
        "before_blob",
        "before_mode",
        "before_present",
        "before_sha256",
        "path",
        "scratch_kind",
        "scratch_name",
    }
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != expected_record_keys:
            raise LifecycleTransitionError(
                "transition_manifest_projection_malformed",
                "restore every projection record as an exact mapping",
                str(path),
            )

        def blob(label: str) -> bytes | None:
            name = record.get(f"{label}_blob")
            if name is None:
                if record.get(f"{label}_present") is not False:
                    raise LifecycleTransitionError(
                        "transition_manifest_projection_malformed",
                        "bind absent projection content without a blob or hash",
                        f"{path}:{index}:{label}",
                    )
                return None
            if name != f"{index:04d}.{label}":
                raise LifecycleTransitionError(
                    "transition_manifest_blob_name_unsafe",
                    "use the deterministic local blob name for every projection",
                    str(name),
                )
            blob_name = str(name)
            candidate = path.parent / blob_name
            if captured_blobs is None:
                candidate_state = _private_file_state(
                    candidate,
                    max_bytes=_MAX_LIFECYCLE_BLOB_BYTES,
                )
                if candidate_state is None:
                    raise LifecycleTransitionError(
                        "transition_manifest_blob_missing",
                        "restore the content-addressed transaction blob beside its manifest",
                        str(candidate),
                    )
                content = candidate_state.content
            else:
                captured = captured_blobs.get(blob_name)
                if captured is None:
                    raise LifecycleTransitionError(
                        "transition_manifest_blob_missing",
                        "restore the content-addressed captured transaction blob",
                        str(candidate),
                    )
                content, mode = captured
                if mode != 0o600:
                    raise LifecycleTransitionError(
                        "transition_private_file_unsafe",
                        "restore every captured journal blob to mode 0600",
                        str(candidate),
                    )
            if _sha256(content) != record.get(f"{label}_sha256"):
                raise LifecycleTransitionError(
                    "transition_manifest_blob_hash_mismatch",
                    "restore the exact transaction blob committed by the manifest",
                    str(candidate),
                )
            if record.get(f"{label}_present") is not True:
                raise LifecycleTransitionError(
                    "transition_manifest_projection_malformed",
                    "bind present projection content to its exact blob and hash",
                    f"{path}:{index}:{label}",
                )
            return content

        raw_path = record.get("path")
        if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
            raise LifecycleTransitionError(
                "transition_manifest_projection_path_invalid",
                "bind every projection to one normalized absolute path",
                str(raw_path),
            )
        projection = FileProjection(
            path=Path(raw_path),
            before=blob("before"),
            after=blob("after"),
            before_mode=record.get("before_mode"),
            after_mode=record.get("after_mode"),
        )
        if str(projection.path) != raw_path:
            raise LifecycleTransitionError(
                "transition_manifest_projection_path_invalid",
                "bind every projection to one normalized absolute path",
                raw_path,
            )
        projections.append(projection)
    if len({item.path for item in projections}) != len(projections):
        raise LifecycleTransitionError(
            "transition_manifest_projection_path_duplicate",
            "bind each normalized projection path exactly once",
            transaction_id,
        )
    try:
        intent = LifecycleTransitionIntent.from_record(
            intent_payload,
            catalog=lifecycle_catalog,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LifecycleTransitionError(
            "transition_manifest_intent_malformed",
            "restore the exact typed transition intent",
            transaction_id,
        ) from exc
    if intent.to_record() != intent_payload:
        raise LifecycleTransitionError(
            "transition_manifest_intent_malformed",
            "restore the exact typed transition intent without coercion or extra fields",
            transaction_id,
        )
    if (
        lifecycle_transition_id(intent, projections) != operation_id
        or transaction_id != _attempt_transaction_id(operation_id, attempt_no)
        or path.parent.name != transaction_id
    ):
        raise LifecycleTransitionError(
            "transition_manifest_identity_mismatch",
            "restore the manifest whose identity binds its intent and projections",
            transaction_id,
        )
    scratches = tuple(
        _scratch_for(projection, transaction_id, index)
        for index, projection in enumerate(projections)
    )
    for record, scratch in zip(records, scratches, strict=True):
        if (
            record.get("scratch_kind") != scratch.kind
            or record.get("scratch_name") != scratch.path.name
        ):
            raise LifecycleTransitionError(
                "transition_manifest_scratch_identity_mismatch",
                "restore the deterministic projection scratch binding",
                str(scratch.path),
            )
    if captured_inventory is None:
        directory_fd = _open_existing_private_directory_fd(path.parent)
        if directory_fd is None:
            raise LifecycleTransitionError(
                "transition_manifest_directory_missing",
                "restore the exact private transaction directory",
                str(path.parent),
            )
        try:
            observed_entries = set(os.listdir(directory_fd))
        finally:
            os.close(directory_fd)
    else:
        observed_entries = set(captured_inventory)
    expected_entries = {"manifest.json"}
    for record in records:
        for label in ("before", "after"):
            blob_name = record.get(f"{label}_blob")
            if isinstance(blob_name, str):
                expected_entries.add(blob_name)
    if observed_entries != expected_entries:
        raise LifecycleTransitionError(
            "transition_manifest_directory_inventory_mismatch",
            "restore exactly the manifest and its declared preimage/postimage blobs",
            str(path.parent),
        )
    return (
        operation_id,
        attempt_no,
        transaction_id,
        created_at,
        intent,
        tuple(projections),
        scratches,
        str(state),
    )


def _load_transaction_manifest(
    path: Path,
    *,
    manifest_content: bytes | None = None,
    captured_blobs: Mapping[str, tuple[bytes, int]] | None = None,
    captured_inventory: frozenset[str] | None = None,
) -> tuple[
    str,
    int,
    str,
    str,
    LifecycleTransitionIntent,
    tuple[FileProjection, ...],
    tuple[_ProjectionScratch, ...],
    str,
]:
    """Load one v2 journal from either live private files or captured bytes."""

    if (
        manifest_content is None
        and _private_file_state(
            path,
            max_bytes=_MAX_LIFECYCLE_MANIFEST_BYTES,
        )
        is None
    ):
        raise LifecycleTransitionError(
            "transition_manifest_missing",
            "restore the exact private transaction manifest",
            str(path),
        )
    payload = _load_private_manifest_payload(path, content=manifest_content)
    schema = payload.get("schema")
    if schema == TRANSITION_TRANSACTION_SCHEMA_V1:
        raise LifecycleTransitionError(
            "transition_v1_self_containment_absent",
            "preserve the legacy journal and recover it only through an explicit migration",
            str(path),
        )
    exact_keys = {
        "attempt_no",
        "created_at",
        "intent",
        "lifecycle_definition",
        "operation_id",
        "projections",
        "reason_code",
        "schema",
        "state",
        "transaction_id",
    }
    if set(payload) != exact_keys or schema != TRANSITION_TRANSACTION_SCHEMA_V2:
        raise LifecycleTransitionError(
            "transition_manifest_schema_unknown",
            "use the checked self-contained lifecycle transaction schema",
            str(path),
        )
    transaction_id = payload.get("transaction_id")
    operation_id = payload.get("operation_id")
    attempt_no = payload.get("attempt_no")
    created_at = payload.get("created_at")
    state = payload.get("state")
    reason_code = payload.get("reason_code")
    intent_payload = payload.get("intent")
    binding_payload = payload.get("lifecycle_definition")
    records = payload.get("projections")
    if (
        not isinstance(transaction_id, str)
        or not transaction_id
        or not isinstance(operation_id, str)
        or not operation_id
        or type(attempt_no) is not int
        or attempt_no < 0
        or not isinstance(created_at, str)
        or not created_at
        or state
        not in {
            "created",
            "prepared",
            "projecting",
            "postimage_complete",
            "applied",
            "aborted",
            "recovery_required",
        }
        or not isinstance(intent_payload, Mapping)
        or not isinstance(binding_payload, Mapping)
        or not isinstance(records, list)
        or not records
        or (reason_code is not None and (not isinstance(reason_code, str) or not reason_code))
        or (state in {"aborted", "recovery_required"}) != (reason_code is not None)
    ):
        raise LifecycleTransitionError(
            "transition_manifest_shape_malformed",
            "restore the exact intent, timestamp, lifecycle binding, and projections",
            str(path),
        )

    def private_content(name: str) -> bytes:
        candidate = path.parent / name
        if captured_blobs is None:
            candidate_state = _private_file_state(
                candidate,
                max_bytes=_transaction_child_max_bytes(name),
            )
            if candidate_state is None:
                raise LifecycleTransitionError(
                    "transition_manifest_blob_missing",
                    "restore every immutable journal artifact beside its manifest",
                    str(candidate),
                )
            return candidate_state.content
        captured = captured_blobs.get(name)
        if captured is None:
            raise LifecycleTransitionError(
                "transition_manifest_blob_missing",
                "restore every immutable artifact in the captured journal",
                str(candidate),
            )
        content, mode = captured
        if mode != 0o600:
            raise LifecycleTransitionError(
                "transition_private_file_unsafe",
                "restore every captured journal artifact to mode 0600",
                str(candidate),
            )
        return content

    source_content = private_content(_LIFECYCLE_SOURCE_BLOB)
    definition_content = private_content(_LIFECYCLE_DEFINITION_BLOB)
    try:
        definition_payload = _load_private_manifest_payload(
            path.parent / _LIFECYCLE_DEFINITION_BLOB,
            content=definition_content,
        )
        definition = LifecycleDefinition.model_validate(definition_payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise LifecycleTransitionError(
            "transition_lifecycle_definition_malformed",
            "restore the exact accepted lifecycle definition blob",
            transaction_id,
        ) from exc
    expected_definition_content = (
        _canonical_json_bytes(definition.model_dump(mode="json", by_alias=True)) + b"\n"
    )
    if expected_definition_content != definition_content:
        raise LifecycleTransitionError(
            "transition_lifecycle_definition_noncanonical",
            "restore the canonical accepted lifecycle definition bytes",
            transaction_id,
        )
    compiler_ref = binding_payload.get("compiler_ref")
    if compiler_ref not in SUPPORTED_LIFECYCLE_DEFINITION_COMPILER_REFS:
        raise LifecycleTransitionError(
            "transition_lifecycle_compiler_unsupported",
            "restore a supported append-bound lifecycle derivation attestation",
            str(compiler_ref),
        )
    try:
        binding = LifecycleDefinitionBinding.from_record(binding_payload)
        expected_binding = LifecycleDefinitionBinding.from_attested_definition(
            definition,
            source_content,
            compiler_ref=binding.compiler_ref,
            from_stage=binding.from_stage,
            to_stage=binding.to_stage,
            edge_class=binding.edge_class,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LifecycleTransitionError(
            "transition_lifecycle_binding_malformed",
            "restore the exact definition-derived lifecycle edge binding",
            transaction_id,
        ) from exc
    if binding != expected_binding:
        raise LifecycleTransitionError(
            "transition_lifecycle_binding_mismatch",
            "restore the definition-derived lifecycle edge binding",
            transaction_id,
        )
    try:
        intent = LifecycleTransitionIntent.from_record(
            intent_payload,
            lifecycle_definition=definition,
            lifecycle_source=source_content,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LifecycleTransitionError(
            "transition_manifest_intent_malformed",
            "restore the exact typed transition intent",
            transaction_id,
        ) from exc
    if intent.lifecycle_definition_binding != binding or intent.to_record() != dict(intent_payload):
        raise LifecycleTransitionError(
            "transition_manifest_intent_malformed",
            "restore one exact lifecycle binding across manifest and intent",
            transaction_id,
        )

    expected_record_keys = {
        "after_blob",
        "after_mode",
        "after_present",
        "after_sha256",
        "before_blob",
        "before_mode",
        "before_present",
        "before_sha256",
        "path",
        "scratch_kind",
        "scratch_name",
    }
    projections: list[FileProjection] = []
    declared_blobs: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping) or set(record) != expected_record_keys:
            raise LifecycleTransitionError(
                "transition_manifest_projection_malformed",
                "restore every projection record as an exact mapping",
                f"{path}:{index}",
            )

        def projection_blob(label: str) -> bytes | None:
            name = record.get(f"{label}_blob")
            present = record.get(f"{label}_present")
            digest = record.get(f"{label}_sha256")
            if name is None:
                if present is not False or digest is not None:
                    raise LifecycleTransitionError(
                        "transition_manifest_projection_malformed",
                        "bind absent projection content without a blob or hash",
                        f"{path}:{index}:{label}",
                    )
                return None
            expected_name = f"{index:04d}.{label}"
            if name != expected_name or digest is None:
                raise LifecycleTransitionError(
                    "transition_manifest_blob_name_unsafe",
                    "use the deterministic local projection blob name",
                    str(name),
                )
            declared_blobs.add(expected_name)
            content = private_content(expected_name)
            if present is not True or _sha256(content) != digest:
                raise LifecycleTransitionError(
                    "transition_manifest_blob_hash_mismatch",
                    "restore the exact projection blob committed by the manifest",
                    str(path.parent / expected_name),
                )
            return content

        raw_path = record.get("path")
        if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
            raise LifecycleTransitionError(
                "transition_manifest_projection_path_invalid",
                "bind every projection to one normalized absolute path",
                str(raw_path),
            )
        projection = FileProjection(
            path=Path(raw_path),
            before=projection_blob("before"),
            after=projection_blob("after"),
            before_mode=record.get("before_mode"),
            after_mode=record.get("after_mode"),
        )
        if str(projection.path) != raw_path:
            raise LifecycleTransitionError(
                "transition_manifest_projection_path_invalid",
                "bind every projection to one normalized absolute path",
                raw_path,
            )
        projections.append(projection)
    if len({item.path for item in projections}) != len(projections):
        raise LifecycleTransitionError(
            "transition_manifest_projection_path_duplicate",
            "bind each normalized projection path exactly once",
            transaction_id,
        )
    if (
        lifecycle_transition_id(intent, projections) != operation_id
        or transaction_id != _attempt_transaction_id(operation_id, attempt_no)
        or path.parent.name != transaction_id
    ):
        raise LifecycleTransitionError(
            "transition_manifest_identity_mismatch",
            "restore the manifest whose identity binds its intent and projections",
            transaction_id,
        )
    scratches = tuple(
        _scratch_for(projection, transaction_id, index)
        for index, projection in enumerate(projections)
    )
    for record, scratch in zip(records, scratches, strict=True):
        if (
            record.get("scratch_kind") != scratch.kind
            or record.get("scratch_name") != scratch.path.name
        ):
            raise LifecycleTransitionError(
                "transition_manifest_scratch_identity_mismatch",
                "restore the deterministic projection scratch binding",
                str(scratch.path),
            )
    if captured_inventory is None:
        directory_fd = _open_existing_private_directory_fd(path.parent)
        if directory_fd is None:
            raise LifecycleTransitionError(
                "transition_manifest_directory_missing",
                "restore the exact private transaction directory",
                str(path.parent),
            )
        try:
            observed_entries = set(os.listdir(directory_fd))
        finally:
            os.close(directory_fd)
    else:
        observed_entries = set(captured_inventory)
    required_entries = {
        "manifest.json",
        _LIFECYCLE_SOURCE_BLOB,
        _LIFECYCLE_DEFINITION_BLOB,
        *declared_blobs,
    }
    allowed_entries = {
        *required_entries,
        *(_phase_projection_name(phase) for phase in _PHASE_EVENT_TYPES),
    }
    unknown_entries = observed_entries - allowed_entries
    if unknown_entries:
        raise LifecycleTransitionError(
            "transition_manifest_directory_entry_unknown",
            "remove entries outside the deterministic transaction inventory",
            f"{path.parent}:{','.join(sorted(unknown_entries))}",
        )
    if not required_entries.issubset(observed_entries):
        raise LifecycleTransitionError(
            "transition_manifest_directory_inventory_mismatch",
            "restore exactly the declared blobs and immutable phase projections",
            str(path.parent),
        )
    return (
        operation_id,
        attempt_no,
        transaction_id,
        created_at,
        intent,
        tuple(projections),
        scratches,
        str(state),
    )


def _validated_materialization_plan_transaction(
    plan: LifecycleMaterializationPlan,
    plan_path: Path,
) -> tuple[
    str,
    int,
    str,
    str,
    LifecycleTransitionIntent,
    tuple[FileProjection, ...],
    tuple[_ProjectionScratch, ...],
    str,
]:
    """Validate a recovery plan as the exact complete journal it will install."""

    if plan_path.name != _materialization_plan_name(plan.transaction_id):
        raise LifecycleTransitionError(
            "transition_materialization_plan_identity_mismatch",
            "restore the plan at its transaction-derived path",
            str(plan_path),
        )
    artifacts = dict(plan.artifacts)
    transaction = _load_transaction_manifest(
        plan_path.parent / plan.transaction_id / "manifest.json",
        manifest_content=artifacts["manifest.json"],
        captured_blobs={
            name: (content, 0o600) for name, content in plan.artifacts if name != "manifest.json"
        },
        captured_inventory=frozenset(artifacts),
    )
    if transaction[2] != plan.transaction_id or transaction[7] != "created":
        raise LifecycleTransitionError(
            "transition_materialization_state_invalid",
            "recover only the exact pre-append created transaction",
            plan.transaction_id,
        )
    return transaction


@dataclass(frozen=True)
class _CapturedLifecycleJournal:
    transaction_id: str
    manifest_path: Path
    manifest: CapturedFile
    blobs: tuple[tuple[str, CapturedFile], ...]
    inventory: frozenset[str]
    materializing: bool = False


@dataclass(frozen=True)
class _CapturedLifecycleMaterializationPlan:
    transaction_id: str
    path: Path
    captured: CapturedFile


def _capture_lifecycle_journals(
    snapshot: ReadOnlyFsSnapshot,
    root: Path,
    *,
    materializing: bool = False,
) -> tuple[
    _CapturedLifecycleJournal | _CapturedLifecycleMaterializationPlan | LifecycleRecoveryResult,
    ...,
]:
    directory = snapshot.pin_absolute_dir(root, private_final=True, allow_missing=True)
    if directory is None:
        return ()
    names = snapshot.list_names(directory)
    entry_limit = _MAX_LIFECYCLE_TRANSACTIONS * (2 if materializing else 1)
    if len(names) > entry_limit:
        return (
            LifecycleRecoveryResult(
                "transition-root",
                "recovery_required",
                "transition_manifest_count_limit",
            ),
        )
    captured: list[
        _CapturedLifecycleJournal | _CapturedLifecycleMaterializationPlan | LifecycleRecoveryResult
    ] = []
    total_children = 0
    for name in names:
        plan_match = _MATERIALIZATION_PLAN_RE.fullmatch(name)
        if materializing and plan_match is not None:
            try:
                observed = snapshot.observe_file_at(
                    directory,
                    name,
                    private=True,
                    max_bytes=_MAX_LIFECYCLE_MATERIALIZATION_PLAN_BYTES,
                )
                assert observed.captured is not None
                captured.append(
                    _CapturedLifecycleMaterializationPlan(
                        transaction_id=plan_match.group(1),
                        path=directory.path / name,
                        captured=observed.captured,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - corrupt plan is isolated.
                captured.append(
                    LifecycleRecoveryResult(
                        plan_match.group(1),
                        "recovery_required",
                        getattr(
                            exc,
                            "reason_code",
                            "transition_materialization_plan_inspection_failed",
                        ),
                    )
                )
            continue
        if _TRANSACTION_DIRECTORY_RE.fullmatch(name) is None:
            captured.append(
                LifecycleRecoveryResult(
                    name,
                    "recovery_required",
                    "transition_manifest_root_entry_unknown",
                )
            )
            continue
        try:
            transaction = snapshot.pin_dir_at(directory, name, private=True)
            children = snapshot.list_names(transaction)
            total_children += len(children)
            if total_children > _MAX_LIFECYCLE_TOTAL_CHILDREN:
                raise LifecycleTransitionError(
                    "transition_manifest_total_entry_limit",
                    "narrow or compact the governed journal estate before inspection",
                    f"{root}:{total_children}",
                )
            if len(children) > _MAX_LIFECYCLE_JOURNAL_CHILDREN:
                raise LifecycleTransitionError(
                    "transition_manifest_entry_limit",
                    "restore the bounded deterministic transaction inventory",
                    f"{transaction.path}:{len(children)}",
                )
            if "manifest.json" not in children:
                raise LifecycleTransitionError(
                    "transition_manifest_missing",
                    "restore the exact private transaction manifest",
                    str(transaction.path),
                )
            unknown = tuple(child for child in children if not _known_transaction_child(child))
            if unknown:
                raise LifecycleTransitionError(
                    "transition_manifest_directory_entry_unknown",
                    "remove entries outside the deterministic transaction inventory",
                    f"{transaction.path}:{','.join(unknown)}",
                )
            manifest = snapshot.observe_file_at(
                transaction,
                "manifest.json",
                private=True,
                max_bytes=_MAX_LIFECYCLE_MANIFEST_BYTES,
            )
            assert manifest.captured is not None
            blobs: list[tuple[str, CapturedFile]] = []
            for child in children:
                if child == "manifest.json":
                    continue
                observed = snapshot.observe_file_at(
                    transaction,
                    child,
                    private=True,
                    max_bytes=_transaction_child_max_bytes(child),
                )
                assert observed.captured is not None
                blobs.append((child, observed.captured))
            captured.append(
                _CapturedLifecycleJournal(
                    transaction_id=name,
                    manifest_path=transaction.path / "manifest.json",
                    manifest=manifest.captured,
                    blobs=tuple(blobs),
                    inventory=frozenset(children),
                    materializing=materializing,
                )
            )
        except Exception as exc:  # noqa: BLE001 - each corrupt journal is isolated.
            reason_code = getattr(
                exc,
                "reason_code",
                "transition_inspection_failed",
            )
            if materializing:
                reason_code = "transition_materialization_incomplete"
            captured.append(
                LifecycleRecoveryResult(
                    name,
                    "recovery_required",
                    reason_code,
                )
            )
    return tuple(captured)


def _captured_lifecycle_estate_usage(
    entries: Sequence[
        _CapturedLifecycleJournal | _CapturedLifecycleMaterializationPlan | LifecycleRecoveryResult
    ],
) -> tuple[int, int]:
    """Return reserved child/byte usage from one sealed two-root capture."""

    journals = tuple(entry for entry in entries if isinstance(entry, _CapturedLifecycleJournal))
    final_ids = {entry.transaction_id for entry in journals if not entry.materializing}
    plan_entries = {
        entry.transaction_id: entry
        for entry in entries
        if isinstance(entry, _CapturedLifecycleMaterializationPlan)
    }
    children = 0
    total_bytes = 0

    for entry in plan_entries.values():
        children += 1
        total_bytes += len(entry.captured.content)
        if entry.transaction_id in final_ids:
            continue
        try:
            plan = _load_materialization_plan(
                entry.path,
                content=entry.captured.content,
            )
        except Exception:  # noqa: BLE001 - reserve the maximum for an opaque plan.
            children += _MAX_LIFECYCLE_JOURNAL_CHILDREN
            total_bytes += _MAX_LIFECYCLE_JOURNAL_BYTES
            continue
        children += len(plan.artifacts) + 2
        total_bytes += (
            sum(len(content) for _name, content in plan.artifacts) + 2 * _MAX_LIFECYCLE_PHASE_BYTES
        )

    for entry in journals:
        plan_entry = plan_entries.get(entry.transaction_id)
        if entry.materializing and plan_entry is not None and entry.transaction_id not in final_ids:
            try:
                planned_names = set(
                    dict(
                        _load_materialization_plan(
                            plan_entry.path,
                            content=plan_entry.captured.content,
                        ).artifacts
                    )
                )
            except Exception:  # noqa: BLE001 - opaque plan was reserved at maximum.
                planned_names = set(entry.inventory)
            extras = entry.inventory - planned_names
            children += len(extras)
            total_bytes += sum(
                len(captured.content) for name, captured in entry.blobs if name in extras
            )
            if "manifest.json" in extras:
                total_bytes += len(entry.manifest.content)
            continue
        phase_count = sum(
            _TRANSACTION_PHASE_PROJECTION_RE.fullmatch(name) is not None for name in entry.inventory
        )
        missing_phase_count = max(0, 2 - phase_count)
        children += len(entry.inventory) + missing_phase_count
        total_bytes += (
            len(entry.manifest.content)
            + sum(len(captured.content) for _name, captured in entry.blobs)
            + missing_phase_count * _MAX_LIFECYCLE_PHASE_BYTES
        )
    return children, total_bytes


def _exact_lifecycle_phase_receipts(
    *,
    phases: Mapping[str, CoordEvent],
    intent: LifecycleTransitionIntent,
    projections: Sequence[FileProjection],
    transaction_id: str,
    operation_id: str,
    attempt_no: int,
    created_at: str,
    abort_reason: str | None,
) -> None:
    for phase, observed in phases.items():
        expected = _transaction_event(
            event_type=_PHASE_EVENT_TYPES[phase],
            phase=phase,
            transaction_id=transaction_id,
            operation_id=operation_id,
            attempt_no=attempt_no,
            intent=intent,
            projections=projections,
            timestamp=created_at,
            reason_code=abort_reason if phase == "aborted" else None,
        )
        if _event_without_sequence(observed) != _event_without_sequence(expected):
            raise LifecycleTransitionError(
                "transition_phase_receipt_payload_mismatch",
                "restore the exact receipt reconstructed from the captured journal",
                observed.event_id,
            )
    prepared = phases.get("prepared")
    terminal = phases.get("applied") or phases.get("aborted")
    if terminal is not None and (
        prepared is None
        or prepared.sequence is None
        or terminal.sequence is None
        or prepared.sequence >= terminal.sequence
    ):
        raise LifecycleTransitionError(
            "transition_phase_receipt_order_invalid",
            "restore prepared before exactly one terminal phase receipt",
            transaction_id,
        )


def _inspect_lifecycle_transactions_legacy(
    *,
    event_log: CoordEventLog,
    transaction_root: Path | None = None,
    task_id: str | None = None,
) -> tuple[LifecycleRecoveryResult, ...]:
    """Disabled pre-v2 inspector retained only as an explicit refusal boundary."""

    raise LifecycleTransitionError(
        "transition_legacy_inspector_disabled",
        "use the sealed self-contained lifecycle inspection envelope",
    )

    root = _manifest_root(transaction_root)
    try:
        replay_before = event_log.replay(fail_open=False)
        receipts = _transaction_receipt_census(event_log, replay=replay_before)
    except Exception as exc:  # noqa: BLE001 - ledger defects are global HOLDs.
        return (
            LifecycleRecoveryResult(
                "transition-ledger",
                "recovery_required",
                getattr(exc, "reason_code", "transition_inspection_failed"),
            ),
        )
    try:
        from shared.sdlc_lifecycle import (
            SDLC_STAGE_METADATA_PATH,
            parse_sdlc_stage_metadata,
        )

        with ReadOnlyFsSnapshot() as snapshot:
            metadata_parent = snapshot.pin_absolute_dir(
                SDLC_STAGE_METADATA_PATH.parent,
                private_final=False,
            )
            assert metadata_parent is not None
            metadata_observation = snapshot.observe_file_at(
                metadata_parent,
                SDLC_STAGE_METADATA_PATH.name,
                private=False,
                max_bytes=_MAX_LIFECYCLE_MANIFEST_BYTES,
            )
            if metadata_observation.captured is None:
                raise LifecycleTransitionError(
                    "transition_lifecycle_definition_missing",
                    "restore the exact captured lifecycle definition",
                    str(SDLC_STAGE_METADATA_PATH),
                )
            lifecycle_content = metadata_observation.captured.content
            try:
                lifecycle_catalog = parse_sdlc_stage_metadata(
                    lifecycle_content.decode("utf-8"),
                    source_label=str(SDLC_STAGE_METADATA_PATH),
                )
            except (UnicodeError, ValueError) as exc:
                raise LifecycleTransitionError(
                    "transition_lifecycle_definition_malformed",
                    "restore the exact valid lifecycle metadata snapshot",
                    type(exc).__name__,
                ) from exc
            entries = _capture_lifecycle_journals(snapshot, root)
            results: list[LifecycleRecoveryResult] = []
            observed_journal_ids = {
                entry.transaction_id
                for entry in entries
                if _TRANSACTION_DIRECTORY_RE.fullmatch(entry.transaction_id) is not None
            }
            journal_census_complete = not any(
                isinstance(entry, LifecycleRecoveryResult)
                and entry.transaction_id == "transition-root"
                for entry in entries
            )
            if journal_census_complete:
                for transaction_id, (
                    _operation_id,
                    subject,
                    _phases,
                ) in receipts.items():
                    if transaction_id in observed_journal_ids or (
                        task_id is not None and subject != task_id
                    ):
                        continue
                    results.append(
                        LifecycleRecoveryResult(
                            transaction_id,
                            "recovery_required",
                            "transition_receipt_manifest_missing",
                        )
                    )
            for entry in entries:
                if isinstance(entry, LifecycleRecoveryResult):
                    results.append(entry)
                    continue
                try:
                    manifest_record = _load_private_manifest_payload(
                        entry.manifest_path,
                        content=entry.manifest.content,
                    )
                    abort_reason = manifest_record.get("reason_code")
                    if abort_reason is not None and not isinstance(abort_reason, str):
                        raise LifecycleTransitionError(
                            "transition_manifest_shape_malformed",
                            "restore one optional string reason code",
                            entry.transaction_id,
                        )
                    blobs = {
                        name: (captured.content, stat.S_IMODE(captured.stamp.mode))
                        for name, captured in entry.blobs
                    }
                    (
                        operation_id,
                        attempt_no,
                        transaction_id,
                        created_at,
                        intent,
                        projections,
                        _scratches,
                        state,
                    ) = _load_transaction_manifest(
                        entry.manifest_path,
                        manifest_content=entry.manifest.content,
                        captured_blobs=blobs,
                        captured_inventory=entry.inventory,
                        lifecycle_definition_content=lifecycle_content,
                        lifecycle_catalog=lifecycle_catalog,
                    )
                    terminal_admission = _projected_terminal_close_admission(
                        intent,
                        projections,
                    )
                    _validate_terminal_close_admission(intent, terminal_admission)
                    _validate_terminal_admission_projection_bindings(
                        terminal_admission,
                        projections,
                    )
                    if task_id is not None and intent.task_id != task_id:
                        continue
                    receipt_entry = receipts.get(transaction_id)
                    if receipt_entry is not None and (
                        receipt_entry[0] != operation_id or receipt_entry[1] != intent.task_id
                    ):
                        raise LifecycleTransitionError(
                            "transition_receipt_manifest_identity_mismatch",
                            "restore one identity across ledger and manifest",
                            transaction_id,
                        )
                    phases = receipt_entry[2] if receipt_entry is not None else {}
                    _exact_lifecycle_phase_receipts(
                        phases=phases,
                        intent=intent,
                        projections=projections,
                        transaction_id=transaction_id,
                        operation_id=operation_id,
                        attempt_no=attempt_no,
                        created_at=created_at,
                        abort_reason=abort_reason,
                    )
                    if state == "applied" and set(phases) == {"prepared", "applied"}:
                        results.append(LifecycleRecoveryResult(transaction_id, "applied"))
                    elif state == "aborted" and set(phases) == {"prepared", "aborted"}:
                        results.append(LifecycleRecoveryResult(transaction_id, "aborted"))
                    else:
                        reason = (
                            str(abort_reason)
                            if state == "recovery_required" and abort_reason
                            else "transition_interrupted_before_prepare"
                            if state == "created" and not phases
                            else "transition_reconciliation_required"
                        )
                        results.append(
                            LifecycleRecoveryResult(
                                transaction_id,
                                "recovery_required",
                                reason,
                            )
                        )
                except Exception as exc:  # noqa: BLE001 - malformed entry is HOLD.
                    results.append(
                        LifecycleRecoveryResult(
                            entry.transaction_id,
                            "recovery_required",
                            getattr(exc, "reason_code", "transition_inspection_failed"),
                        )
                    )
            snapshot.seal()
            replay_after = event_log.replay(fail_open=False)
            if replay_after != replay_before:
                raise LifecycleTransitionError(
                    "transition_receipt_frontier_changed",
                    "retry after the canonical coordination event frontier stabilizes",
                )
    except Exception as exc:  # noqa: BLE001 - no unsealed classification escapes.
        return (
            LifecycleRecoveryResult(
                "transition-root",
                "recovery_required",
                getattr(exc, "reason_code", "transition_inspection_failed"),
            ),
        )
    return tuple(results)


def _hold_lifecycle_inspection(
    *,
    transaction_id: str,
    reason_code: str,
    manifest_schema: str | None = None,
    manifest_sha256: str | None = None,
    task_id: str | None = None,
    operation_id: str | None = None,
    lifecycle_definition_ref: str | None = None,
    phase_frontier: Sequence[LifecycleReceiptFrontierEntry] = (),
) -> LifecycleTransactionInspection:
    return LifecycleTransactionInspection.create(
        transaction_id=transaction_id,
        task_id=task_id,
        operation_id=operation_id,
        manifest_schema=manifest_schema,
        manifest_sha256=manifest_sha256,
        lifecycle_definition_ref=lifecycle_definition_ref,
        state="hold",
        recovery_required=True,
        reason_codes=(reason_code,),
        phase_frontier=phase_frontier,
    )


def _inspect_materialization_plan(
    entry: _CapturedLifecycleMaterializationPlan,
) -> LifecycleTransactionInspection:
    try:
        plan = _load_materialization_plan(
            entry.path,
            content=entry.captured.content,
        )
        (
            operation_id,
            _attempt_no,
            transaction_id,
            _created_at,
            intent,
            _projections,
            _scratches,
            _state,
        ) = _validated_materialization_plan_transaction(plan, entry.path)
        manifest_content = plan.artifact("manifest.json")
        manifest = _load_private_manifest_payload(
            entry.path.parent / entry.transaction_id / "manifest.json",
            content=manifest_content,
        )
        if (
            manifest.get("transaction_id") != entry.transaction_id
            or plan.transaction_id != entry.transaction_id
            or transaction_id != entry.transaction_id
        ):
            raise LifecycleTransitionError(
                "transition_materialization_plan_identity_mismatch",
                "restore one transaction identity across plan and manifest",
                entry.transaction_id,
            )
        return _hold_lifecycle_inspection(
            transaction_id=entry.transaction_id,
            reason_code="transition_materialization_plan_unpromoted",
            manifest_schema=(
                str(manifest.get("schema")) if isinstance(manifest.get("schema"), str) else None
            ),
            manifest_sha256=_sha256(manifest_content),
            task_id=intent.task_id,
            operation_id=operation_id,
            lifecycle_definition_ref=(intent.lifecycle_definition_binding.definition_ref),
        )
    except Exception as exc:  # noqa: BLE001 - corrupt plan remains a HOLD.
        return _hold_lifecycle_inspection(
            transaction_id=entry.transaction_id,
            reason_code=getattr(
                exc,
                "reason_code",
                "transition_materialization_plan_inspection_failed",
            ),
        )


def _inspect_captured_lifecycle_journal(
    entry: _CapturedLifecycleJournal,
) -> tuple[LifecycleTransactionInspection, bool]:
    """Purely classify one already-captured journal and its local receipts."""

    manifest_sha256 = _sha256(entry.manifest.content)
    raw: dict[str, Any] | None = None
    frontier: list[LifecycleReceiptFrontierEntry] = []
    try:
        raw = _load_private_manifest_payload(
            entry.manifest_path,
            content=entry.manifest.content,
        )
        schema = raw.get("schema")
        raw_intent = raw.get("intent")
        task_id = (
            str(raw_intent.get("task_id"))
            if isinstance(raw_intent, Mapping)
            and isinstance(raw_intent.get("task_id"), str)
            and raw_intent.get("task_id")
            else None
        )
        operation_id = (
            str(raw.get("operation_id"))
            if isinstance(raw.get("operation_id"), str)
            and re.fullmatch(
                r"sdlc-txn-[0-9a-f]{64}",
                str(raw.get("operation_id")),
            )
            else None
        )
        if schema == TRANSITION_TRANSACTION_SCHEMA_V1:
            return (
                _hold_lifecycle_inspection(
                    transaction_id=entry.transaction_id,
                    reason_code="transition_v1_self_containment_absent",
                    manifest_schema=TRANSITION_TRANSACTION_SCHEMA_V1,
                    manifest_sha256=manifest_sha256,
                    task_id=task_id,
                    operation_id=operation_id,
                ),
                False,
            )
        if schema != TRANSITION_TRANSACTION_SCHEMA_V2:
            return (
                _hold_lifecycle_inspection(
                    transaction_id=entry.transaction_id,
                    reason_code="transition_manifest_schema_unknown",
                    manifest_schema=str(schema) if isinstance(schema, str) else None,
                    manifest_sha256=manifest_sha256,
                    task_id=task_id,
                    operation_id=operation_id,
                ),
                False,
            )
        blobs = {
            name: (captured.content, stat.S_IMODE(captured.stamp.mode))
            for name, captured in entry.blobs
        }
        (
            operation_id,
            attempt_no,
            transaction_id,
            created_at,
            intent,
            projections,
            _scratches,
            manifest_state,
        ) = _load_transaction_manifest(
            entry.manifest_path,
            manifest_content=entry.manifest.content,
            captured_blobs=blobs,
            captured_inventory=entry.inventory,
        )
        terminal_admission = _projected_terminal_close_admission(intent, projections)
        _validate_terminal_close_admission(intent, terminal_admission)
        _validate_terminal_admission_projection_bindings(
            terminal_admission,
            projections,
        )
        phases: dict[str, CoordEvent] = {}
        phase_projections: dict[str, LifecyclePhaseAppendProjection] = {}
        for name, captured in entry.blobs:
            if _TRANSACTION_PHASE_PROJECTION_RE.fullmatch(name) is None:
                continue
            try:
                record = _load_private_manifest_payload(
                    entry.manifest_path.parent / name,
                    content=captured.content,
                )
                projection = LifecyclePhaseAppendProjection.from_record(record)
            except (KeyError, TypeError, ValueError) as exc:
                raise LifecycleTransitionError(
                    "transition_phase_projection_malformed",
                    "restore the exact self-hashed phase append projection",
                    f"{transaction_id}:{name}",
                ) from exc
            if _canonical_json_bytes(record) + b"\n" != captured.content:
                raise LifecycleTransitionError(
                    "transition_phase_projection_noncanonical",
                    "restore the canonical phase append projection bytes",
                    f"{transaction_id}:{name}",
                )
            if (
                name != _phase_projection_name(projection.phase)
                or projection.transaction_id != transaction_id
                or projection.operation_id != operation_id
                or projection.attempt_no != attempt_no
                or projection.phase in phase_projections
            ):
                raise LifecycleTransitionError(
                    "transition_phase_projection_identity_mismatch",
                    "restore one exact phase projection for this transaction",
                    f"{transaction_id}:{name}",
                )
            phase_projections[projection.phase] = projection
            phases[projection.phase] = projection.event
            frontier.append(LifecycleReceiptFrontierEntry.from_projection(projection))
        prepared_projection = phase_projections.get("prepared")
        terminal_projection = phase_projections.get("applied") or phase_projections.get("aborted")
        if "applied" in phase_projections and "aborted" in phase_projections:
            raise LifecycleTransitionError(
                "transition_phase_receipt_contradiction",
                "retain exactly one terminal phase projection",
                transaction_id,
            )
        if terminal_projection is not None and (
            prepared_projection is None
            or terminal_projection.prior_projection_ref != prepared_projection.projection_ref
        ):
            raise LifecycleTransitionError(
                "transition_phase_projection_chain_invalid",
                "chain the terminal projection to this transaction's prepared projection",
                transaction_id,
            )
        if len({item.ledger_path for item in phase_projections.values()}) > 1:
            raise LifecycleTransitionError(
                "transition_phase_projection_ledger_mismatch",
                "bind every phase projection to one canonical ledger path",
                transaction_id,
            )
        manifest_reason = raw.get("reason_code")
        projected_abort_reason = (
            phases["aborted"].payload.get("reason_code") if "aborted" in phases else None
        )
        if projected_abort_reason is not None and not isinstance(projected_abort_reason, str):
            raise LifecycleTransitionError(
                "transition_phase_receipt_payload_mismatch",
                "restore one exact string abort reason",
                transaction_id,
            )
        if (
            manifest_reason is not None
            and projected_abort_reason is not None
            and manifest_reason != projected_abort_reason
        ):
            raise LifecycleTransitionError(
                "transition_phase_receipt_payload_mismatch",
                "restore one abort reason across manifest and append projection",
                transaction_id,
            )
        _exact_lifecycle_phase_receipts(
            phases=phases,
            intent=intent,
            projections=projections,
            transaction_id=transaction_id,
            operation_id=operation_id,
            attempt_no=attempt_no,
            created_at=created_at,
            abort_reason=(
                str(projected_abort_reason) if projected_abort_reason is not None else None
            ),
        )
        definition_ref = intent.lifecycle_definition_binding.definition_ref
        checked_frontier = tuple(frontier)
        if "applied" in phases:
            if manifest_state == "aborted":
                raise LifecycleTransitionError(
                    "transition_terminal_state_contradiction",
                    "reconcile the applied projection and aborted manifest",
                    transaction_id,
                )
            lagged = manifest_state != "applied"
            return (
                LifecycleTransactionInspection.create(
                    transaction_id=transaction_id,
                    task_id=intent.task_id,
                    operation_id=operation_id,
                    manifest_schema=TRANSITION_TRANSACTION_SCHEMA_V2,
                    manifest_sha256=manifest_sha256,
                    lifecycle_definition_ref=definition_ref,
                    state="applied",
                    recovery_required=lagged,
                    reason_codes=("transition_manifest_state_lag",) if lagged else (),
                    phase_frontier=checked_frontier,
                ),
                True,
            )
        if "aborted" in phases:
            if manifest_state == "applied":
                raise LifecycleTransitionError(
                    "transition_terminal_state_contradiction",
                    "reconcile the aborted projection and applied manifest",
                    transaction_id,
                )
            lagged = manifest_state != "aborted"
            return (
                LifecycleTransactionInspection.create(
                    transaction_id=transaction_id,
                    task_id=intent.task_id,
                    operation_id=operation_id,
                    manifest_schema=TRANSITION_TRANSACTION_SCHEMA_V2,
                    manifest_sha256=manifest_sha256,
                    lifecycle_definition_ref=definition_ref,
                    state="aborted",
                    recovery_required=lagged,
                    reason_codes=("transition_manifest_state_lag",) if lagged else (),
                    phase_frontier=checked_frontier,
                ),
                True,
            )
        if "prepared" in phases:
            if manifest_state in {"applied", "aborted"}:
                raise LifecycleTransitionError(
                    "transition_terminal_manifest_receipt_missing",
                    "restore the terminal append projection required by the manifest",
                    transaction_id,
                )
            if manifest_state == "recovery_required":
                return (
                    _hold_lifecycle_inspection(
                        transaction_id=transaction_id,
                        reason_code=str(manifest_reason),
                        manifest_schema=TRANSITION_TRANSACTION_SCHEMA_V2,
                        manifest_sha256=manifest_sha256,
                        task_id=intent.task_id,
                        operation_id=operation_id,
                        lifecycle_definition_ref=definition_ref,
                        phase_frontier=checked_frontier,
                    ),
                    True,
                )
            reason = (
                "transition_manifest_state_lag"
                if manifest_state == "created"
                else "transition_reconciliation_required"
            )
            return (
                LifecycleTransactionInspection.create(
                    transaction_id=transaction_id,
                    task_id=intent.task_id,
                    operation_id=operation_id,
                    manifest_schema=TRANSITION_TRANSACTION_SCHEMA_V2,
                    manifest_sha256=manifest_sha256,
                    lifecycle_definition_ref=definition_ref,
                    state="prepared",
                    recovery_required=True,
                    reason_codes=(reason,),
                    phase_frontier=checked_frontier,
                ),
                True,
            )
        if manifest_state == "created":
            return (
                LifecycleTransactionInspection.create(
                    transaction_id=transaction_id,
                    task_id=intent.task_id,
                    operation_id=operation_id,
                    manifest_schema=TRANSITION_TRANSACTION_SCHEMA_V2,
                    manifest_sha256=manifest_sha256,
                    lifecycle_definition_ref=definition_ref,
                    state="not_started",
                    recovery_required=True,
                    reason_codes=("transition_interrupted_before_prepare",),
                    phase_frontier=(),
                ),
                True,
            )
        raise LifecycleTransitionError(
            "transition_manifest_phase_receipt_missing",
            "restore the immutable phase append projection required by the manifest",
            transaction_id,
        )
    except Exception as exc:  # noqa: BLE001 - one corrupt journal becomes one HOLD.
        schema = raw.get("schema") if isinstance(raw, dict) else None
        raw_intent = raw.get("intent") if isinstance(raw, dict) else None
        task_id = (
            str(raw_intent.get("task_id"))
            if isinstance(raw_intent, Mapping)
            and isinstance(raw_intent.get("task_id"), str)
            and raw_intent.get("task_id")
            else None
        )
        operation_id = (
            str(raw.get("operation_id"))
            if isinstance(raw, dict)
            and isinstance(raw.get("operation_id"), str)
            and re.fullmatch(
                r"sdlc-txn-[0-9a-f]{64}",
                str(raw.get("operation_id")),
            )
            else None
        )
        return (
            _hold_lifecycle_inspection(
                transaction_id=entry.transaction_id,
                reason_code=getattr(
                    exc,
                    "reason_code",
                    "transition_inspection_failed",
                ),
                manifest_schema=str(schema) if isinstance(schema, str) else None,
                manifest_sha256=manifest_sha256,
                task_id=task_id,
                operation_id=operation_id,
                phase_frontier=frontier,
            ),
            False,
        )


def _validate_event_plane_lifecycle_coverage(
    snapshot: CoordReplaySnapshot,
    inspections: Sequence[LifecycleTransactionInspection],
) -> tuple[tuple[LifecycleTransactionInspection, ...], bool, tuple[str, ...]]:
    """Reconcile local phase projections with one caller-supplied event frontier."""

    checked = list(inspections)
    reasons: set[str] = set()
    complete = snapshot.coverage_complete
    if not complete:
        reasons.add("transition_event_plane_snapshot_degraded")

    def mark_hold(
        transaction_id: str,
        reason_code: str,
        *,
        task_id: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        for index, inspection in enumerate(checked):
            if inspection.transaction_id != transaction_id:
                continue
            checked[index] = LifecycleTransactionInspection.create(
                transaction_id=inspection.transaction_id,
                task_id=inspection.task_id,
                operation_id=inspection.operation_id,
                manifest_schema=inspection.manifest_schema,
                manifest_sha256=inspection.manifest_sha256,
                lifecycle_definition_ref=inspection.lifecycle_definition_ref,
                state="hold",
                recovery_required=True,
                reason_codes=(*inspection.reason_codes, reason_code),
                phase_frontier=inspection.phase_frontier,
            )
            return
        checked.append(
            _hold_lifecycle_inspection(
                transaction_id=transaction_id,
                reason_code=reason_code,
                task_id=task_id,
                operation_id=operation_id,
            )
        )

    local_by_event: dict[str, LifecycleReceiptFrontierEntry] = {}
    for inspection in checked:
        for frontier in inspection.phase_frontier:
            if frontier.event_id in local_by_event:
                complete = False
                reasons.add("transition_phase_projection_event_duplicate")
                mark_hold(
                    frontier.transaction_id,
                    "transition_phase_projection_event_duplicate",
                )
            local_by_event[frontier.event_id] = frontier

    plane_by_event: dict[str, CoordEventRecord] = {}
    for event in snapshot.events:
        payload = event.payload
        schema = payload.get("schema")
        is_phase_type = event.event_type in _PHASE_EVENT_TYPES.values()
        if not is_phase_type:
            if (
                schema
                in {
                    TRANSITION_TRANSACTION_SCHEMA_V1,
                    TRANSITION_TRANSACTION_SCHEMA_V2,
                }
                and payload.get("phase") is not None
            ):
                complete = False
                reasons.add("transition_event_plane_phase_event_malformed")
            continue
        if schema == TRANSITION_TRANSACTION_SCHEMA_V1:
            complete = False
            reasons.add("transition_v1_event_plane_history_opaque")
            legacy_operation = payload.get("operation_id")
            legacy_attempt = payload.get("attempt_no")
            legacy_transaction = payload.get("transaction_id")
            if (
                isinstance(legacy_operation, str)
                and re.fullmatch(r"sdlc-txn-[0-9a-f]{64}", legacy_operation)
                and type(legacy_attempt) is int
                and legacy_attempt >= 0
                and legacy_transaction == _attempt_transaction_id(legacy_operation, legacy_attempt)
            ):
                mark_hold(
                    str(legacy_transaction),
                    "transition_v1_self_containment_absent",
                    task_id=event.subject,
                    operation_id=legacy_operation,
                )
            else:
                reasons.add("transition_event_plane_phase_event_malformed")
            continue
        phase = payload.get("phase")
        operation_id = payload.get("operation_id")
        attempt_no = payload.get("attempt_no")
        transaction_id = payload.get("transaction_id")
        if (
            schema != TRANSITION_TRANSACTION_SCHEMA_V2
            or phase not in _PHASE_EVENT_TYPES
            or event.event_type != _PHASE_EVENT_TYPES[phase]
            or not isinstance(operation_id, str)
            or re.fullmatch(r"sdlc-txn-[0-9a-f]{64}", operation_id) is None
            or type(attempt_no) is not int
            or attempt_no < 0
            or transaction_id != _attempt_transaction_id(operation_id, attempt_no)
            or event.event_id != f"{transaction_id}.{phase}"
        ):
            complete = False
            reasons.add("transition_event_plane_phase_event_malformed")
            continue
        plane_by_event[event.event_id] = event

    for event_id, frontier in local_by_event.items():
        event = plane_by_event.get(event_id)
        if event is None:
            complete = False
            reason = "transition_phase_projection_event_plane_missing"
            reasons.add(reason)
            mark_hold(frontier.transaction_id, reason)
            continue
        if (
            frontier.ledger_path != snapshot.ledger_path
            or frontier.sequence != event.sequence
            or frontier.event_sha256
            != _sha256(_canonical_json_bytes(event.model_dump(mode="json")))
        ):
            complete = False
            reason = "transition_phase_projection_event_plane_mismatch"
            reasons.add(reason)
            mark_hold(frontier.transaction_id, reason)

    for event_id, event in plane_by_event.items():
        if event_id in local_by_event:
            continue
        complete = False
        reason = "transition_receipt_manifest_or_projection_missing"
        reasons.add(reason)
        payload = event.payload
        transaction_id = str(payload["transaction_id"])
        operation_id = str(payload["operation_id"])
        mark_hold(
            transaction_id,
            reason,
            task_id=event.subject,
            operation_id=operation_id,
        )
    return tuple(checked), complete, tuple(sorted(reasons))


def _validate_lifecycle_operation_lineage(
    inspections: Sequence[LifecycleTransactionInspection],
) -> tuple[tuple[LifecycleTransactionInspection, ...], bool, tuple[str, ...]]:
    """Reject cross-attempt contradictions hidden by per-journal validity."""

    checked = list(inspections)
    groups: dict[str, list[tuple[int, LifecycleTransactionInspection]]] = {}
    reasons: set[str] = set()
    for inspection in inspections:
        if inspection.operation_id is None:
            continue
        match = re.fullmatch(
            rf"{re.escape(inspection.operation_id)}\.attempt-([0-9]{{4,}})",
            inspection.transaction_id,
        )
        if match is None:
            reasons.add("transition_operation_attempt_identity_mismatch")
            continue
        groups.setdefault(inspection.operation_id, []).append((int(match.group(1)), inspection))

    def hold_group(
        operation_id: str,
        reason_code: str,
    ) -> None:
        reasons.add(reason_code)
        for index, inspection in enumerate(checked):
            if inspection.operation_id != operation_id:
                continue
            checked[index] = LifecycleTransactionInspection.create(
                transaction_id=inspection.transaction_id,
                task_id=inspection.task_id,
                operation_id=inspection.operation_id,
                manifest_schema=inspection.manifest_schema,
                manifest_sha256=inspection.manifest_sha256,
                lifecycle_definition_ref=inspection.lifecycle_definition_ref,
                state="hold",
                recovery_required=True,
                reason_codes=(*inspection.reason_codes, reason_code),
                phase_frontier=inspection.phase_frontier,
            )

    for operation_id, attempts in groups.items():
        ordered = sorted(attempts, key=lambda item: item[0])
        numbers = [number for number, _inspection in ordered]
        task_ids = {
            inspection.task_id for _number, inspection in ordered if inspection.task_id is not None
        }
        if len(numbers) != len(set(numbers)) or len(task_ids) > 1:
            hold_group(operation_id, "transition_operation_attempt_identity_mismatch")
            continue
        if numbers != list(range(len(numbers))):
            hold_group(operation_id, "transition_operation_attempt_gap")
            continue
        applied = [item for item in ordered if item[1].state == "applied"]
        prepared = [item for item in ordered if item[1].state == "prepared"]
        created = [item for item in ordered if item[1].state == "not_started"]
        if len(applied) > 1:
            hold_group(operation_id, "transition_operation_applied_multiple")
            continue
        if len(prepared) > 1:
            hold_group(operation_id, "transition_operation_prepared_multiple")
            continue
        if len(created) > 1:
            hold_group(operation_id, "transition_operation_created_multiple")
            continue
        if applied:
            applied_number = applied[0][0]
            if any(number > applied_number for number, _inspection in ordered):
                hold_group(operation_id, "transition_operation_continued_after_applied")
                continue
        sequenced = [
            (
                number,
                min(item.sequence for item in inspection.phase_frontier),
                max(item.sequence for item in inspection.phase_frontier),
            )
            for number, inspection in ordered
            if inspection.phase_frontier
        ]
        if any(
            left_max >= right_min
            for (_left_number, _left_min, left_max), (
                _right_number,
                right_min,
                _right_max,
            ) in zip(
                sequenced,
                sequenced[1:],
                strict=False,
            )
        ):
            hold_group(operation_id, "transition_operation_receipt_order_invalid")
    return tuple(checked), not reasons, tuple(sorted(reasons))


def capture_coord_replay_snapshot(event_log: CoordEventLog) -> CoordReplaySnapshot:
    """Capture one read-only, support-only event-plane replay frontier."""

    ledger_path = Path(event_log.db_path).expanduser()
    if not ledger_path.is_file():
        return build_coord_replay_snapshot(
            (),
            ledger_path=ledger_path,
            source="sqlite",
            degraded=True,
            errors=("coord_event_log_absent",),
        )
    try:
        replay = event_log.replay(fail_open=True)
    except Exception as exc:  # noqa: BLE001 - an unreadable owner becomes typed degraded input.
        return build_coord_replay_snapshot(
            (),
            ledger_path=ledger_path,
            source="sqlite",
            degraded=True,
            errors=(f"coord_event_log_replay_failed:{type(exc).__name__}",),
        )
    return build_coord_replay_snapshot(
        tuple(event.to_record() for event in replay.events),
        ledger_path=ledger_path,
        source=replay.source,
        degraded=replay.degraded,
        errors=replay.errors,
    )


def inspect_lifecycle_transactions(
    *,
    transaction_root: Path | None = None,
    task_id: str | None = None,
    event_log: object | None = None,
    event_plane_snapshot: CoordReplaySnapshot | None = None,
    observed_at: str | None = None,
) -> LifecycleInspectionEnvelope:
    """Inspect one journal estate without ledger access, locks, writes, or repair."""

    del event_log  # Compatibility input; deliberately never dereferenced.
    root = _manifest_root(transaction_root)
    try:
        with ReadOnlyFsSnapshot() as snapshot:
            entries = (
                *_capture_lifecycle_journals(snapshot, root),
                *_capture_lifecycle_journals(
                    snapshot,
                    _materialization_root(root),
                    materializing=True,
                ),
            )
            transaction_identities = {
                entry.transaction_id
                for entry in entries
                if _TRANSACTION_DIRECTORY_RE.fullmatch(entry.transaction_id) is not None
            }
            if len(transaction_identities) > _MAX_LIFECYCLE_TRANSACTIONS:
                entries = (
                    *entries,
                    LifecycleRecoveryResult(
                        "transition-root",
                        "recovery_required",
                        "transition_manifest_count_limit",
                    ),
                )
            estate_children, estate_bytes = _captured_lifecycle_estate_usage(entries)
            if estate_children > _MAX_LIFECYCLE_TOTAL_CHILDREN:
                entries = (
                    *entries,
                    LifecycleRecoveryResult(
                        "transition-root",
                        "recovery_required",
                        "transition_manifest_total_entry_limit",
                    ),
                )
            if estate_bytes > _MAX_LIFECYCLE_TOTAL_BYTES:
                entries = (
                    *entries,
                    LifecycleRecoveryResult(
                        "transition-root",
                        "recovery_required",
                        "transition_manifest_total_byte_limit",
                    ),
                )
            all_inspections: list[LifecycleTransactionInspection] = []
            semantic_complete = True
            for entry in entries:
                if isinstance(entry, _CapturedLifecycleMaterializationPlan):
                    all_inspections.append(_inspect_materialization_plan(entry))
                    semantic_complete = False
                    continue
                if isinstance(entry, LifecycleRecoveryResult):
                    all_inspections.append(
                        _hold_lifecycle_inspection(
                            transaction_id=entry.transaction_id,
                            reason_code=entry.reason_code or "transition_inspection_failed",
                        )
                    )
                    semantic_complete = False
                    continue
                inspected, complete = _inspect_captured_lifecycle_journal(entry)
                if entry.materializing:
                    inspected = LifecycleTransactionInspection.create(
                        transaction_id=inspected.transaction_id,
                        task_id=inspected.task_id,
                        operation_id=inspected.operation_id,
                        manifest_schema=inspected.manifest_schema,
                        manifest_sha256=inspected.manifest_sha256,
                        lifecycle_definition_ref=inspected.lifecycle_definition_ref,
                        state="hold",
                        recovery_required=True,
                        reason_codes=(
                            *inspected.reason_codes,
                            "transition_materialization_unpromoted",
                        ),
                        phase_frontier=inspected.phase_frontier,
                    )
                    complete = False
                all_inspections.append(inspected)
                semantic_complete = semantic_complete and complete
            merged_inspections: dict[str, LifecycleTransactionInspection] = {}
            for inspection in all_inspections:
                prior = merged_inspections.get(inspection.transaction_id)
                if prior is None:
                    merged_inspections[inspection.transaction_id] = inspection
                    continue
                identity_conflict = (
                    prior.task_id is not None
                    and inspection.task_id is not None
                    and prior.task_id != inspection.task_id
                    or prior.operation_id is not None
                    and inspection.operation_id is not None
                    and prior.operation_id != inspection.operation_id
                    or prior.manifest_sha256 is not None
                    and inspection.manifest_sha256 is not None
                    and prior.manifest_sha256 != inspection.manifest_sha256
                )
                merged_inspections[inspection.transaction_id] = (
                    LifecycleTransactionInspection.create(
                        transaction_id=inspection.transaction_id,
                        task_id=prior.task_id or inspection.task_id,
                        operation_id=prior.operation_id or inspection.operation_id,
                        manifest_schema=(prior.manifest_schema or inspection.manifest_schema),
                        manifest_sha256=(prior.manifest_sha256 or inspection.manifest_sha256),
                        lifecycle_definition_ref=(
                            prior.lifecycle_definition_ref or inspection.lifecycle_definition_ref
                        ),
                        state="hold",
                        recovery_required=True,
                        reason_codes=(
                            *prior.reason_codes,
                            *inspection.reason_codes,
                            (
                                "transition_materialization_identity_collision"
                                if identity_conflict
                                else "transition_materialization_plan_residual"
                            ),
                        ),
                        phase_frontier=(
                            *prior.phase_frontier,
                            *inspection.phase_frontier,
                        ),
                    )
                )
            all_inspections = list(merged_inspections.values())
            seal = snapshot.seal()
        coverage_reasons: tuple[str, ...]
        coverage_source_complete = False
        if event_plane_snapshot is None:
            semantic_complete = False
            coverage_reasons = ("transition_event_plane_coverage_absent",)
        elif not isinstance(event_plane_snapshot, CoordReplaySnapshot):
            semantic_complete = False
            coverage_reasons = ("transition_event_plane_snapshot_malformed",)
            event_plane_snapshot = None
        else:
            try:
                snapshot_record = json.loads(
                    _canonical_json_bytes(
                        event_plane_snapshot.model_dump(mode="json", by_alias=True)
                    )
                )
                checked_snapshot = CoordReplaySnapshot.model_validate(snapshot_record)
                if checked_snapshot.model_dump(mode="json", by_alias=True) != snapshot_record:
                    raise ValueError("coord replay snapshot record is noncanonical")
                event_plane_snapshot = checked_snapshot
            except (KeyError, TypeError, ValueError):
                semantic_complete = False
                coverage_reasons = ("transition_event_plane_snapshot_malformed",)
                event_plane_snapshot = None
            else:
                coverage_source_complete = event_plane_snapshot.coverage_complete
                (
                    reconciled,
                    coverage_complete,
                    coverage_reasons,
                ) = _validate_event_plane_lifecycle_coverage(
                    event_plane_snapshot,
                    all_inspections,
                )
                all_inspections = list(reconciled)
                semantic_complete = semantic_complete and coverage_complete
        (
            lineage_checked,
            lineage_complete,
            lineage_reasons,
        ) = _validate_lifecycle_operation_lineage(all_inspections)
        all_inspections = list(lineage_checked)
        semantic_complete = semantic_complete and lineage_complete
        full_frontier = tuple(
            item for inspection in all_inspections for item in inspection.phase_frontier
        )
        seen_sequences: dict[tuple[str, int], str] = {}
        duplicate_frontier = False
        for item in full_frontier:
            key = (item.ledger_path, item.sequence)
            if key in seen_sequences:
                duplicate_frontier = True
            else:
                seen_sequences[key] = item.event_id
        if duplicate_frontier:
            semantic_complete = False
        incomplete_reasons = {
            reason
            for inspection in all_inspections
            if inspection.recovery_required
            or inspection.manifest_schema != TRANSITION_TRANSACTION_SCHEMA_V2
            for reason in inspection.reason_codes
        }
        incomplete_reasons.update(coverage_reasons)
        incomplete_reasons.update(lineage_reasons)
        if duplicate_frontier:
            incomplete_reasons.add("transition_receipt_frontier_sequence_duplicate")
        global_blocking_reasons = {
            "transition_event_plane_coverage_absent",
            "transition_event_plane_snapshot_degraded",
            "transition_event_plane_snapshot_malformed",
            "transition_event_plane_phase_event_malformed",
            "transition_operation_attempt_identity_mismatch",
            "transition_phase_projection_event_duplicate",
            "transition_receipt_frontier_sequence_duplicate",
        }.intersection(incomplete_reasons)
        estate_complete = (
            coverage_source_complete
            and not global_blocking_reasons
            and not any(inspection.recovery_required for inspection in all_inspections)
        )
        scope_inspections = tuple(
            inspection
            for inspection in all_inspections
            if task_id is None or inspection.task_id == task_id or inspection.task_id is None
        )
        scope_complete = (
            coverage_source_complete
            and not global_blocking_reasons
            and not any(inspection.recovery_required for inspection in scope_inspections)
        )
        if task_id is None:
            scope_complete = estate_complete
        return LifecycleInspectionEnvelope.create(
            task_id=task_id,
            transactions=all_inspections,
            estate_transaction_refs=(inspection.inspection_ref for inspection in all_inspections),
            receipt_frontier=full_frontier,
            fs_seal=seal,
            event_plane_snapshot=event_plane_snapshot,
            estate_complete=estate_complete,
            scope_complete=scope_complete,
            reason_codes=tuple(incomplete_reasons),
            observed_at=observed_at,
        )
    except Exception as exc:  # noqa: BLE001 - no unsealed classification escapes.
        root_hold = _hold_lifecycle_inspection(
            transaction_id="transition-root",
            reason_code=getattr(
                exc,
                "reason_code",
                "transition_inspection_failed",
            ),
        )
        return LifecycleInspectionEnvelope.create(
            task_id=task_id,
            transactions=(root_hold,),
            estate_transaction_refs=(root_hold.inspection_ref,),
            receipt_frontier=(),
            fs_seal=None,
            event_plane_snapshot=(
                event_plane_snapshot
                if isinstance(event_plane_snapshot, CoordReplaySnapshot)
                else None
            ),
            estate_complete=False,
            scope_complete=False,
            reason_codes=(getattr(exc, "reason_code", "transition_inspection_failed"),),
            observed_at=observed_at,
        )


def recover_lifecycle_transactions(
    *,
    event_log: CoordEventLog,
    transaction_root: Path | None = None,
    lock_root: Path | None = None,
    task_id: str | None = None,
) -> tuple[LifecycleRecoveryResult, ...]:
    """Reconcile crash-left manifests without overwriting unrecognized bytes."""

    _require_lifecycle_effect_activation()
    root = _manifest_root(transaction_root)
    results: list[LifecycleRecoveryResult] = []
    try:
        receipts = _transaction_receipt_census(event_log)
    except Exception as exc:  # noqa: BLE001 - return a typed global recovery HOLD.
        return (
            LifecycleRecoveryResult(
                "transition-ledger",
                "recovery_required",
                getattr(exc, "reason_code", f"transition_recovery_{type(exc).__name__}"),
            ),
        )
    materialization_root = _materialization_root(root)
    try:
        plan_paths = _materialization_plan_paths(materialization_root)
    except Exception as exc:  # noqa: BLE001 - materialization root is isolated.
        return (
            LifecycleRecoveryResult(
                "transition-materialization-root",
                "recovery_required",
                getattr(exc, "reason_code", f"transition_recovery_{type(exc).__name__}"),
            ),
        )
    promoted_ids: set[str] = set()
    plan_ids: set[str] = set()
    result_ids: set[str] = set()
    for plan_path in plan_paths:
        match = _MATERIALIZATION_PLAN_RE.fullmatch(plan_path.name)
        plan_identity = match.group(1) if match is not None else plan_path.name
        plan_ids.add(plan_identity)
        try:
            outcome = _rehydrate_materialization_plan(
                event_log=event_log,
                root=root,
                plan_path=plan_path,
                lock_root=_lock_root(lock_root),
                task_id=task_id,
            )
            if outcome is not None and outcome[1]:
                promoted_ids.add(outcome[0])
        except Exception as exc:  # noqa: BLE001 - isolate recovery plans.
            results.append(
                LifecycleRecoveryResult(
                    plan_identity,
                    "recovery_required",
                    getattr(
                        exc,
                        "reason_code",
                        f"transition_recovery_{type(exc).__name__}",
                    ),
                )
            )
            result_ids.add(plan_identity)
    try:
        materialized_paths = _transaction_manifest_paths(
            materialization_root,
            allow_materialization_plans=True,
        )
    except Exception as exc:  # noqa: BLE001 - return a typed root recovery HOLD.
        return (
            LifecycleRecoveryResult(
                "transition-materialization-root",
                "recovery_required",
                getattr(exc, "reason_code", f"transition_recovery_{type(exc).__name__}"),
            ),
        )
    for staged_manifest in materialized_paths:
        transaction_id = staged_manifest.parent.name
        if transaction_id in result_ids:
            continue
        try:
            (
                _operation_id,
                _attempt_no,
                transaction_id,
                _created_at,
                intent,
                projections,
                _scratches,
                state,
            ) = _load_transaction_manifest(staged_manifest)
            if task_id is not None and intent.task_id != task_id:
                continue
            raise LifecycleTransitionError(
                "transition_materialization_plan_missing",
                "restore the validated self-contained plan before staged recovery",
                transaction_id,
            )
        except Exception as exc:  # noqa: BLE001 - isolate staged journals.
            results.append(
                LifecycleRecoveryResult(
                    transaction_id,
                    "recovery_required",
                    getattr(
                        exc,
                        "reason_code",
                        f"transition_recovery_{type(exc).__name__}",
                    ),
                )
            )
            result_ids.add(transaction_id)
    try:
        manifest_paths = _transaction_manifest_paths(root)
    except Exception as exc:  # noqa: BLE001 - return a typed root recovery HOLD.
        return (
            *results,
            LifecycleRecoveryResult(
                "transition-root",
                "recovery_required",
                getattr(exc, "reason_code", f"transition_recovery_{type(exc).__name__}"),
            ),
        )
    manifest_ids = {path.parent.name for path in manifest_paths}
    for transaction_id, (_operation_id, subject, _phases) in receipts.items():
        if (
            transaction_id in manifest_ids
            or transaction_id in result_ids
            or (task_id is not None and subject != task_id)
        ):
            continue
        results.append(
            LifecycleRecoveryResult(
                transaction_id,
                "recovery_required",
                "transition_receipt_manifest_missing",
            )
        )
    for manifest_path in manifest_paths:
        if manifest_path.parent.name in result_ids:
            continue
        try:
            (
                operation_id,
                attempt_no,
                transaction_id,
                created_at,
                intent,
                projections,
                _scratches,
                state,
            ) = _load_transaction_manifest(manifest_path)
            if task_id is not None and intent.task_id != task_id:
                continue
            receipt_entry = receipts.get(transaction_id)
            if receipt_entry is not None and (
                receipt_entry[0] != operation_id or receipt_entry[1] != intent.task_id
            ):
                raise LifecycleTransitionError(
                    "transition_receipt_manifest_identity_mismatch",
                    "restore one task and operation identity across ledger and manifest",
                    transaction_id,
                )
            phases = receipt_entry[2] if receipt_entry is not None else {}
            if "aborted" in phases:
                prepared_event = phases.get("prepared")
                aborted_event = phases["aborted"]
                abort_reason = aborted_event.payload.get("reason_code")
                if prepared_event is None or not isinstance(abort_reason, str):
                    raise LifecycleTransitionError(
                        "transition_terminal_manifest_receipt_missing",
                        "restore prepared and one reasoned aborted receipt",
                        transaction_id,
                    )
                _exact_lifecycle_phase_receipts(
                    phases=phases,
                    intent=intent,
                    projections=projections,
                    transaction_id=transaction_id,
                    operation_id=operation_id,
                    attempt_no=attempt_no,
                    created_at=created_at,
                    abort_reason=abort_reason,
                )
                if prepared_event.sequence is None or aborted_event.sequence is None:
                    raise LifecycleTransitionError(
                        "transition_phase_projection_sequence_missing",
                        "restore positive canonical sequences before recovery",
                        transaction_id,
                    )
                with _transition_locks(
                    intent.task_id,
                    [projection.path for projection in projections],
                    _lock_root(lock_root),
                ):
                    if any(
                        not _state_matches(
                            projection.path,
                            projection.before,
                            projection.before_mode,
                        )
                        for projection in projections
                    ):
                        raise LifecycleTransitionError(
                            "transition_aborted_preimage_drift",
                            "restore the exact rolled-back preimage before reconciling abort",
                            transaction_id,
                        )
                    prepared_projection = _project_phase_append_receipt(
                        manifest_path.parent,
                        prepared_event,
                        AppendReceipt(
                            event_id=prepared_event.event_id,
                            appended=True,
                            spooled=False,
                            sequence=prepared_event.sequence,
                            db_path=event_log.db_path,
                            jsonl_path=event_log.jsonl_path,
                        ),
                        prior=None,
                    )
                    _project_phase_append_receipt(
                        manifest_path.parent,
                        aborted_event,
                        AppendReceipt(
                            event_id=aborted_event.event_id,
                            appended=True,
                            spooled=False,
                            sequence=aborted_event.sequence,
                            db_path=event_log.db_path,
                            jsonl_path=event_log.jsonl_path,
                        ),
                        prior=prepared_projection,
                    )
                    _write_manifest(
                        root,
                        operation_id,
                        attempt_no,
                        transaction_id,
                        intent,
                        projections,
                        tuple(
                            _scratch_for(projection, transaction_id, index)
                            for index, projection in enumerate(projections)
                        ),
                        timestamp=created_at,
                        state="aborted",
                        reason_code=abort_reason,
                    )
                results.append(
                    LifecycleRecoveryResult(
                        transaction_id,
                        "aborted",
                        ("transition_reconciled_aborted_receipt" if state != "aborted" else None),
                    )
                )
                continue
            if state == "recovery_required" and "applied" not in phases:
                results.append(
                    LifecycleRecoveryResult(
                        transaction_id,
                        "recovery_required",
                        "transition_manifest_recovery_required",
                    )
                )
                continue
            if not phases:
                if state != "created":
                    raise LifecycleTransitionError(
                        "transition_manifest_phase_receipt_missing",
                        "restore the phase receipt required by the durable manifest state",
                        transaction_id,
                    )
                results.append(
                    LifecycleRecoveryResult(
                        transaction_id,
                        "not_started",
                        (
                            "transition_materialization_promoted"
                            if transaction_id in promoted_ids
                            else "transition_interrupted_before_prepare"
                        ),
                    )
                )
                continue
            if state == "applied" and not {"prepared", "applied"}.issubset(phases):
                raise LifecycleTransitionError(
                    "transition_terminal_manifest_receipt_missing",
                    "restore the exact applied receipt for the terminal manifest",
                    transaction_id,
                )
            terminal_admission = _projected_terminal_close_admission(intent, projections)
            receipt = _execute_lifecycle_transition(
                event_log=event_log,
                intent=intent,
                projections=projections,
                transaction_root=root,
                lock_root=lock_root,
                timestamp=created_at,
                terminal_close_admission=terminal_admission,
                locked_preflight=(lambda: None) if terminal_admission is not None else None,
            )
            results.append(
                LifecycleRecoveryResult(
                    transaction_id,
                    "applied",
                    "transition_recovered_from_prepared" if receipt.replayed else None,
                )
            )
        except Exception as exc:  # noqa: BLE001 - isolate malformed manifests.
            results.append(
                LifecycleRecoveryResult(
                    manifest_path.parent.name,
                    "recovery_required",
                    getattr(exc, "reason_code", f"transition_recovery_{type(exc).__name__}"),
                )
            )
    return tuple(results)


def emit_stage_transition(
    *,
    event_log: CoordEventLog,
    task_id: str,
    from_stage: str,
    to_stage: str,
    authority_case: str | None,
    actor: str,
    no_go_snapshot: Mapping[str, bool],
    parent_spec: str | None = None,
    timestamp: str | None = None,
    evidence_type: str | None = None,
    evidence_summary: str | None = None,
    origin: str = "cli",
) -> AppendReceipt:
    """Record an authoritative S-stage transition in the coord SSOT log."""
    ts = timestamp or _now_iso()
    payload: dict[str, Any] = {
        "from_stage": from_stage,
        "to_stage": to_stage,
        "no_go_snapshot": dict(no_go_snapshot),
        "origin": origin,
    }
    if evidence_type is not None:
        payload["evidence_type"] = evidence_type
    if evidence_summary is not None:
        payload["evidence_summary"] = evidence_summary
    event = CoordEvent(
        event_id=stage_transition_event_id(
            task_id=task_id,
            authority_case=authority_case,
            from_stage=from_stage,
            to_stage=to_stage,
            timestamp=ts,
        ),
        timestamp=ts,
        event_type=CANON_STAGE_TRANSITION,
        actor=actor,
        subject=task_id,
        authority_case=authority_case,
        parent_spec=parent_spec,
        payload=payload,
    )
    return _strict_append(event_log, event)


def emit_authorization_flip(
    *,
    event_log: CoordEventLog,
    task_id: str,
    field: str,
    old: object,
    new: object,
    authority_case: str | None,
    actor: str,
    reason: str = "",
    timestamp: str | None = None,
) -> AppendReceipt:
    """Record an authoritative no-go-boolean flip — the keystone SSOT write."""
    if field not in NO_GO_BOOLEANS:
        raise ValueError(f"{field!r} is not a no-go boolean (one of {sorted(NO_GO_BOOLEANS)})")
    ts = timestamp or _now_iso()
    event = CoordEvent(
        event_id=authorization_flip_event_id(
            task_id=task_id, field=field, old=old, new=new, timestamp=ts
        ),
        timestamp=ts,
        event_type=CANON_AUTHZ_FLIP,
        actor=actor,
        subject=task_id,
        authority_case=authority_case,
        payload={
            "field": field,
            "old": old,
            "new": new,
            "reason": reason,
            "actor": actor,
        },
    )
    return _strict_append(event_log, event)


def emit_stage_transition_intent(
    *,
    event_log: CoordEventLog,
    task_id: str,
    from_stage: str,
    to_stage: str,
    authority_case: str | None,
    actor: str,
    no_go_snapshot: Mapping[str, bool],
    timestamp: str | None = None,
    reason: str = "daemon_down",
) -> AppendReceipt:
    """Spool a stage transition for boot reconciliation (daemon-down shim path).

    The shim cannot reach the daemon to append the canonical log, so it writes a
    fail-open spool intent the daemon ingests on boot. Nothing canonical is
    written here — the receipt is ``spooled``, not ``appended``.
    """
    ts = timestamp or _now_iso()
    event = CoordEvent(
        event_id=stage_transition_event_id(
            task_id=task_id,
            authority_case=authority_case,
            from_stage=from_stage,
            to_stage=to_stage,
            timestamp=ts,
        ),
        timestamp=ts,
        event_type=CANON_STAGE_TRANSITION,
        actor=actor,
        subject=task_id,
        authority_case=authority_case,
        payload={
            "from_stage": from_stage,
            "to_stage": to_stage,
            "no_go_snapshot": dict(no_go_snapshot),
            "origin": "shim-intent",
        },
    )
    return event_log.spool_fail_open(event, writer=CoordWriter.shim(name=actor), reason=reason)


# --- best-effort observability mirrors ---------------------------------------
def emit_evidence_appended(
    entry: object, *, event_log: CoordEventLog | None = None
) -> AppendReceipt | None:
    """Mirror an evidence-ledger append into the coord log (best-effort).

    No-op unless an ``event_log`` is injected or ``HAPAX_COORD_EVIDENCE_MIRROR``
    is set; never raises (a malformed entry is silently skipped) — the evidence
    JSONL append is the authoritative surface, this mirror is observability only.
    """
    if event_log is None and not os.environ.get(EVIDENCE_MIRROR_ENV):
        return None
    try:
        log = event_log or default_event_log()
        case_id = str(entry.case_id)  # type: ignore[attr-defined]
        evidence_id = str(entry.evidence_id)  # type: ignore[attr-defined]
        event = CoordEvent(
            event_id=evidence_appended_event_id(evidence_id=evidence_id),
            timestamp=_epoch_to_iso(getattr(entry, "timestamp_utc", None)),
            event_type=CANON_EVIDENCE_APPENDED,
            actor=str(getattr(entry, "producer", "") or "evidence-ledger"),
            subject=case_id,
            authority_case=case_id if case_id.startswith("CASE-") else None,
            payload={
                "evidence_id": evidence_id,
                "kind": getattr(entry, "kind", None),
                "valence": getattr(entry, "valence", None),
                "claim": getattr(entry, "claim", None),
                "risk_tier": getattr(entry, "risk_tier", None),
            },
        )
        return _best_effort_append(log, event)
    except Exception:
        return None


def emit_migration_annotated(
    *,
    task_id: str,
    stage: str,
    risk_tier: str,
    decision: str,
    seeded_fields: list[str] | None = None,
    event_log: CoordEventLog | None = None,
) -> AppendReceipt | None:
    """Mirror a migration stub annotation into the coord log (best-effort).

    No-op unless an ``event_log`` is injected; never raises.
    """
    if event_log is None:
        return None
    try:
        event = CoordEvent(
            event_id=migration_annotated_event_id(
                task_id=task_id, stage=stage, risk_tier=risk_tier, decision=decision
            ),
            timestamp=_now_iso(),
            event_type=CANON_MIGRATION_ANNOTATED,
            actor="case-migration",
            subject=task_id,
            payload={
                "stage": stage,
                "risk_tier": risk_tier,
                "decision": decision,
                "seeded_fields": list(seeded_fields or []),
            },
        )
        return _best_effort_append(event_log, event)
    except Exception:
        return None


def _best_effort_append(event_log: CoordEventLog, event: CoordEvent) -> AppendReceipt | None:
    try:
        return event_log.append(event, writer=CoordWriter.daemon())
    except DuplicateEventError:
        return AppendReceipt(
            event_id=event.event_id,
            appended=True,
            spooled=False,
            sequence=None,
            db_path=event_log.db_path,
            jsonl_path=event_log.jsonl_path,
        )
    except Exception:
        return None


def _epoch_to_iso(value: object) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _now_iso()


# --- the projection fold -----------------------------------------------------
@dataclass
class TaskState:
    """Folded coordination state for one cc-task (subject), latest-write-wins."""

    task_id: str
    stage: str | None = None
    authority_case: str | None = None
    no_go: dict[str, bool] = field(default_factory=dict)
    last_transition_id: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "stage": self.stage,
            "authority_case": self.authority_case,
            "last_transition_id": self.last_transition_id,
            "no_go": dict(self.no_go),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> TaskState:
        no_go = record.get("no_go") or {}
        return cls(
            task_id=str(record["task_id"]),
            stage=_optional_str(record.get("stage")),
            authority_case=_optional_str(record.get("authority_case")),
            last_transition_id=_optional_str(record.get("last_transition_id")),
            no_go={str(k): bool(v) for k, v in dict(no_go).items()},
        )


@dataclass
class CoordProjection:
    """The cc-task/AuthorityCase projection derived by replaying the coord log."""

    tasks: dict[str, TaskState] = field(default_factory=dict)

    @classmethod
    def from_replay(cls, replay: ReplayResult) -> CoordProjection:
        projection = cls()
        for event in replay.events:
            projection.fold_event(event)
        return projection

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> CoordProjection:
        """Restore a projection from its serialized checkpoint (see :meth:`to_record`)."""
        projection = cls()
        tasks = record.get("tasks") or {}
        for task_id, task_record in dict(tasks).items():
            projection.tasks[str(task_id)] = TaskState.from_record(task_record)
        return projection

    def to_record(self) -> dict[str, Any]:
        """Canonical, lossless serialization of the fold — the snapshot ``state_json``.

        Keys are stable and per-task records are plain JSON, so
        ``_canonical_json(to_record())`` is byte-identical for equal folds regardless
        of task insertion order (the snapshot-vs-full-replay equality rests on this).
        """
        return {"tasks": {task_id: state.to_record() for task_id, state in self.tasks.items()}}

    def fold_event(self, event: CoordEvent) -> None:
        """Fold one event into the projection in place (latest-write-wins per field).

        The public incremental fold the snapshot tail-replay seeds from: folding the
        stream one event at a time is identical to :meth:`from_replay`.
        """
        if event.event_type == CANON_STAGE_TRANSITION:
            state = self.tasks.setdefault(event.subject, TaskState(task_id=event.subject))
            to_stage = event.payload.get("to_stage")
            if to_stage is not None:
                state.stage = str(to_stage)
            if event.authority_case:
                state.authority_case = event.authority_case
            snapshot = event.payload.get("no_go_snapshot")
            if isinstance(snapshot, dict):
                state.no_go.update({str(k): bool(v) for k, v in snapshot.items()})
        elif event.event_type == CANON_AUTHZ_FLIP:
            state = self.tasks.setdefault(event.subject, TaskState(task_id=event.subject))
            field_name = event.payload.get("field")
            if field_name is not None:
                state.no_go[str(field_name)] = bool(event.payload.get("new"))
            if event.authority_case:
                state.authority_case = event.authority_case
        elif event.event_type == CANON_TRANSITION_APPLIED:
            intent = event.payload.get("intent")
            if not isinstance(intent, dict):
                return
            from_stage = intent.get("from_stage")
            to_stage = intent.get("to_stage")
            if not isinstance(from_stage, str) or not isinstance(to_stage, str):
                return
            state = self.tasks.setdefault(event.subject, TaskState(task_id=event.subject))
            if state.stage is not None:
                try:
                    from shared.sdlc_lifecycle import stage_token

                    if stage_token(state.stage) != from_stage:
                        return
                except ValueError:
                    return
            state.stage = to_stage
            if event.authority_case:
                state.authority_case = event.authority_case
            snapshot = intent.get("no_go_snapshot")
            if isinstance(snapshot, dict) and all(
                isinstance(value, bool) for value in snapshot.values()
            ):
                state.no_go.update({str(key): value for key, value in snapshot.items()})
            transaction_id = event.payload.get("transaction_id")
            if isinstance(transaction_id, str):
                state.last_transition_id = transaction_id


# --- projection <-> vault drift ----------------------------------------------
@dataclass(frozen=True)
class StageDrift:
    """A divergence between the ledger projection and the vault frontmatter."""

    task_id: str
    ledger_stage: str | None
    vault_stage: str | None


def diff_projection_vs_vault(
    projection: CoordProjection, vault_stages: Mapping[str, str]
) -> list[StageDrift]:
    """Return per-task stage divergences between the ledger projection and vault."""
    drifts: list[StageDrift] = []
    for task_id in sorted(set(projection.tasks) | set(vault_stages)):
        ledger_stage = projection.tasks[task_id].stage if task_id in projection.tasks else None
        vault_stage = vault_stages.get(task_id)
        if ledger_stage != vault_stage:
            drifts.append(
                StageDrift(task_id=task_id, ledger_stage=ledger_stage, vault_stage=vault_stage)
            )
    return drifts


def load_vault_task_stages(vault_tasks: Path | None = None) -> dict[str, str]:
    """Read ``task_id``/``stage`` frontmatter for every cc-task note in the vault."""
    base = vault_tasks or DEFAULT_VAULT_TASKS
    stages: dict[str, str] = {}
    for sub in ("active", "closed"):
        directory = base / sub
        if not directory.is_dir():
            continue
        for note in directory.glob("*.md"):
            task_id, stage = _read_task_id_and_stage(note)
            if task_id and stage:
                stages[task_id] = stage
    return stages


def _read_task_id_and_stage(note: Path) -> tuple[str | None, str | None]:
    try:
        lines = note.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    if not lines or lines[0].strip() != "---":
        return None, None
    task_id: str | None = None
    stage: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("task_id:"):
            task_id = _scalar(line.split(":", 1)[1])
        elif line.startswith("stage:"):
            stage = _scalar(line.split(":", 1)[1])
    return task_id, stage


def _scalar(raw: str) -> str:
    return raw.strip().strip('"').strip("'")


__all__ = [
    "CANON_AUTHZ_FLIP",
    "CANON_EVIDENCE_APPENDED",
    "CANON_MIGRATION_ANNOTATED",
    "CANON_STAGE_TRANSITION",
    "CANON_TRANSITION_ABORTED",
    "CANON_TRANSITION_APPLIED",
    "CANON_TRANSITION_PREPARED",
    "EVIDENCE_MIRROR_ENV",
    "NO_GO_BOOLEANS",
    "CoordProjection",
    "CapturedFile",
    "FileProjection",
    "FileObservation",
    "FsSnapshotSeal",
    "FsStamp",
    "LifecycleRecoveryResult",
    "LifecycleTransitionError",
    "LifecycleTransitionIntent",
    "LifecycleTransitionReceipt",
    "PinnedDirectory",
    "ReadOnlyFsSnapshot",
    "ReadOnlySnapshotError",
    "StageDrift",
    "TaskState",
    "authorization_flip_event_id",
    "capture_coord_replay_snapshot",
    "diff_projection_vs_vault",
    "emit_authorization_flip",
    "emit_evidence_appended",
    "emit_migration_annotated",
    "emit_stage_transition",
    "emit_stage_transition_intent",
    "evidence_appended_event_id",
    "load_vault_task_stages",
    "lifecycle_transition_id",
    "inspect_lifecycle_transactions",
    "migration_annotated_event_id",
    "stage_transition_event_id",
    "execute_lifecycle_transition",
    "recover_lifecycle_transactions",
]

# CoordProjection.from_replay is consumed by scripts/coord-drift-check — an
# extensionless CLI the unused-function scanner does not parse — so reference it
# here to mark it used (mirrors shared/coord_event_log.py's _DYNAMIC_ENTRYPOINTS).
# The snapshot (de)serializers are consumed cross-module by CoordEventLog.snapshot /
# replay_projection via the Foldable protocol, which the scanner also cannot trace.
_DYNAMIC_ENTRYPOINTS = (
    CoordProjection.from_replay,
    CoordProjection.from_record,
    CoordProjection.to_record,
    CoordProjection.fold_event,
    TaskState.from_record,
    TaskState.to_record,
)
