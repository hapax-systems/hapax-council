"""Strict task-note resolution and exact byte snapshots for SDLC writers."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal

from shared.frontmatter import parse_frontmatter_with_diagnostics

TaskState = Literal["active", "closed", "refused"]
_TASK_STATES: tuple[TaskState, ...] = ("active", "closed", "refused")
CLAIM_DISPATCH_BINDING_SCHEMA = "hapax.claim-dispatch-binding.v1"
_CLAIM_KEY_FRAGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{3,127}")
_RENAME_NOREPLACE = 1


class TaskStoreError(RuntimeError):
    """Typed refusal raised before an SDLC writer constructs a projection."""

    def __init__(
        self,
        reason_code: str,
        repair_action: str,
        detail: str | None = None,
        *,
        evidence_refs: tuple[str, ...] = (),
    ) -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
        self.evidence_refs = evidence_refs
        message = f"{reason_code}: {repair_action}"
        if detail:
            message += f" ({detail})"
        super().__init__(message)


@dataclass(frozen=True)
class TaskNoteSnapshot:
    task_id: str
    state: TaskState
    path: Path
    content: bytes
    mode: int
    frontmatter: dict[str, Any]
    body: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


@dataclass(frozen=True)
class ClaimDispatchBinding:
    task_id: str
    lane: str
    session_id: str
    claim_epoch: int
    dispatch_message_id: str
    platform: str
    mode: str
    profile: str
    authority_case: str
    binding_hash: str
    coord_dispatch_idempotency_key: str | None = None

    def body(self) -> dict[str, object]:
        return {
            "authority_case": self.authority_case,
            "binding_hash": self.binding_hash,
            "claim_epoch": self.claim_epoch,
            "coord_dispatch_idempotency_key": self.coord_dispatch_idempotency_key,
            "dispatch_message_id": self.dispatch_message_id,
            "lane": self.lane,
            "may_authorize": False,
            "mode": self.mode,
            "platform": self.platform,
            "profile": self.profile,
            "schema": CLAIM_DISPATCH_BINDING_SCHEMA,
            "session_id": self.session_id,
            "task_id": self.task_id,
        }

    @property
    def receipt_hash(self) -> str:
        return hashlib.sha256(_canonical_json_bytes(self.body())).hexdigest()

    def to_record(self) -> dict[str, object]:
        return {**self.body(), "receipt_hash": self.receipt_hash}

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        lane: str,
        session_id: str,
        claim_epoch: int,
        dispatch_message_id: str,
        platform: str,
        mode: str,
        profile: str,
        authority_case: str,
        binding_hash: str,
        coord_dispatch_idempotency_key: str | None = None,
    ) -> ClaimDispatchBinding:
        values = {
            "task_id": task_id,
            "lane": lane,
            "dispatch_message_id": dispatch_message_id,
            "platform": platform,
            "mode": mode,
            "profile": profile,
            "authority_case": authority_case,
        }
        if any(not value.strip() for value in values.values()):
            raise TaskStoreError(
                "claim_dispatch_binding_field_missing",
                "bind every claim dispatch identity field before exposing the claim",
            )
        if (
            _CLAIM_KEY_FRAGMENT_RE.fullmatch(session_id) is None
            or session_id.isdecimal()
            or "/" in session_id
        ):
            raise TaskStoreError(
                "claim_dispatch_binding_session_invalid",
                "bind one non-PID claim-keyable harness session identity",
                session_id,
            )
        if claim_epoch <= 0:
            raise TaskStoreError(
                "claim_dispatch_binding_epoch_invalid",
                "bind the positive epoch written beside this exact claim",
            )
        if re.fullmatch(r"[0-9a-f]{64}", binding_hash) is None:
            raise TaskStoreError(
                "claim_dispatch_binding_hash_invalid",
                "bind the exact 64-hex dispatch canon binding hash",
                binding_hash,
            )
        return cls(
            task_id=task_id,
            lane=lane,
            session_id=session_id,
            claim_epoch=claim_epoch,
            dispatch_message_id=dispatch_message_id,
            platform=platform,
            mode=mode,
            profile=profile,
            authority_case=authority_case,
            binding_hash=binding_hash,
            coord_dispatch_idempotency_key=coord_dispatch_idempotency_key or None,
        )


def claim_dispatch_binding_path(cache_dir: Path, claim_key: str) -> Path:
    if not claim_key or "/" in claim_key or claim_key in {".", ".."}:
        raise TaskStoreError(
            "claim_dispatch_binding_key_invalid",
            "use the exact role or role-session claim key",
            claim_key,
        )
    return cache_dir / f"cc-claim-dispatch-{claim_key}.json"


def write_claim_dispatch_binding(
    cache_dir: Path, claim_key: str, binding: ClaimDispatchBinding
) -> Path:
    path = claim_dispatch_binding_path(cache_dir, claim_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json_bytes(binding.to_record()) + b"\n"
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def load_claim_dispatch_binding(
    path: Path,
    *,
    content: bytes | None = None,
) -> ClaimDispatchBinding:
    def unique_pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in values:
            if key in output:
                raise TaskStoreError(
                    "claim_dispatch_binding_duplicate_key",
                    "remove duplicate JSON keys from the claim binding",
                    key,
                )
            output[key] = value
        return output

    try:
        payload = (
            content
            if content is not None
            else _regular_file_bytes(
                path,
                reason_code="claim_dispatch_binding_unreadable",
            )[0]
        )
        record = json.loads(payload.decode("ascii"), object_pairs_hook=unique_pairs)
    except TaskStoreError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TaskStoreError(
            "claim_dispatch_binding_unreadable",
            "restore the exact self-hashed claim binding sidecar",
            str(path),
        ) from exc
    exact_keys = {
        "authority_case",
        "binding_hash",
        "claim_epoch",
        "coord_dispatch_idempotency_key",
        "dispatch_message_id",
        "lane",
        "may_authorize",
        "mode",
        "platform",
        "profile",
        "receipt_hash",
        "schema",
        "session_id",
        "task_id",
    }
    if (
        not isinstance(record, dict)
        or set(record) != exact_keys
        or record.get("schema") != CLAIM_DISPATCH_BINDING_SCHEMA
        or record.get("may_authorize") is not False
        or type(record.get("claim_epoch")) is not int
        or any(
            not isinstance(record.get(key), str)
            for key in {
                "authority_case",
                "binding_hash",
                "dispatch_message_id",
                "lane",
                "mode",
                "platform",
                "profile",
                "receipt_hash",
                "session_id",
                "task_id",
            }
        )
        or (
            record.get("coord_dispatch_idempotency_key") is not None
            and not isinstance(record.get("coord_dispatch_idempotency_key"), str)
        )
        or payload != _canonical_json_bytes(record) + b"\n"
    ):
        raise TaskStoreError(
            "claim_dispatch_binding_malformed",
            "restore the exact non-authorizing claim binding schema",
            str(path),
        )
    binding = ClaimDispatchBinding.create(
        task_id=record["task_id"],
        lane=record["lane"],
        session_id=record["session_id"],
        claim_epoch=record["claim_epoch"],
        dispatch_message_id=record["dispatch_message_id"],
        platform=record["platform"],
        mode=record["mode"],
        profile=record["profile"],
        authority_case=record["authority_case"],
        binding_hash=record["binding_hash"],
        coord_dispatch_idempotency_key=record["coord_dispatch_idempotency_key"],
    )
    if record.get("receipt_hash") != binding.receipt_hash:
        raise TaskStoreError(
            "claim_dispatch_binding_receipt_hash_mismatch",
            "restore the exact self-hashed claim binding sidecar",
            str(path),
        )
    return binding


@dataclass(frozen=True)
class ClaimLeaseSnapshot:
    claim_key: str
    claim_path: Path
    claim_content: bytes
    claim_mode: int
    epoch_path: Path
    epoch_content: bytes
    epoch_mode: int
    binding_path: Path
    binding_content: bytes
    binding_mode: int
    binding: ClaimDispatchBinding


def _normalized_path(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _walk_directory_fd(
    starting_fd: int,
    components: tuple[str, ...],
    *,
    create: bool,
) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.dup(starting_fd)
    try:
        for component in components:
            if component in {"", ".", ".."} or "/" in component:
                raise OSError(f"unsafe directory component: {component}")
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def open_task_store_directory_fd(path: Path, *, create: bool = False) -> int:
    """Open a directory by descriptor-walking every non-symlink path component.

    The caller owns the returned descriptor. ``create`` is intentionally limited
    to real directories created beneath already opened real directories; it does
    not make publication atomic against another same-UID writer.
    """

    normalized = _normalized_path(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    root_fd = os.open("/", flags)
    try:
        return _walk_directory_fd(root_fd, normalized.parts[1:], create=create)
    finally:
        os.close(root_fd)


def rename_task_store_no_replace(
    source_directory_fd: int,
    source_name: str,
    destination_directory_fd: int,
    destination_name: str,
) -> None:
    """Publish one descriptor-anchored Linux directory entry without replacement."""

    if any(
        not name or name in {".", ".."} or "/" in name
        for name in (source_name, destination_name)
    ):
        raise TaskStoreError(
            "task_store_rename_name_unsafe",
            "rename only one named child between anchored task-store directories",
        )
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameat2", None)
    if function is None:
        raise TaskStoreError(
            "task_store_atomic_no_replace_unavailable",
            "run task-store publication on Linux with renameat2 support",
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
        source_directory_fd,
        os.fsencode(source_name),
        destination_directory_fd,
        os.fsencode(destination_name),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        value = ctypes.get_errno()
        raise OSError(value, os.strerror(value), f"{source_name}->{destination_name}")


@contextmanager
def _open_parent_dir(path: Path):
    normalized = _normalized_path(path)
    if normalized.name in {"", ".", ".."}:
        raise TaskStoreError(
            "task_store_path_unsafe",
            "use one named entry below real non-symlink directories",
            str(path),
        )
    try:
        fd = open_task_store_directory_fd(normalized.parent)
    except OSError as exc:
        raise TaskStoreError(
            "task_store_parent_unsafe",
            "restore every task-store parent as a real non-symlink directory",
            str(normalized.parent),
        ) from exc
    try:
        yield fd, normalized.name
    finally:
        os.close(fd)


def _regular_file_bytes(path: Path, *, reason_code: str) -> tuple[bytes, int]:
    try:
        with _open_parent_dir(path) as (directory_fd, name):
            fd = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode):
                    raise OSError("not a regular non-symlink file")
                chunks: list[bytes] = []
                while chunk := os.read(fd, 1024 * 1024):
                    chunks.append(chunk)
                return b"".join(chunks), metadata.st_mode & 0o777
            finally:
                os.close(fd)
    except (OSError, TaskStoreError) as exc:
        raise TaskStoreError(
            reason_code,
            "restore the exact regular claim, epoch, and dispatch-binding sidecars",
            str(path),
        ) from exc


def resolve_claim_leases(
    cache_dir: Path,
    *,
    role: str,
    session_id: str,
    task_id: str,
) -> tuple[ClaimLeaseSnapshot, ...]:
    if not role.strip() or role == "unknown":
        raise TaskStoreError(
            "claim_identity_missing",
            "bind one real lane identity before lifecycle mutation",
        )
    if (
        _CLAIM_KEY_FRAGMENT_RE.fullmatch(session_id) is None
        or session_id.isdecimal()
        or "/" in session_id
    ):
        raise TaskStoreError(
            "claim_session_identity_invalid",
            "bind one non-PID claim-keyable harness session before lifecycle mutation",
            session_id,
        )
    keys = [role, f"{role}-{session_id}"]
    leases: list[ClaimLeaseSnapshot] = []
    for key in keys:
        claim_path = cache_dir / f"cc-active-task-{key}"
        epoch_path = cache_dir / f"cc-claim-epoch-{key}"
        binding_path = claim_dispatch_binding_path(cache_dir, key)
        claim_content, claim_mode = _regular_file_bytes(
            claim_path, reason_code="claim_cache_missing"
        )
        epoch_content, epoch_mode = _regular_file_bytes(
            epoch_path, reason_code="claim_epoch_missing"
        )
        binding_content, binding_mode = _regular_file_bytes(
            binding_path, reason_code="claim_dispatch_binding_missing"
        )
        if claim_content.decode("utf-8").strip() != task_id:
            raise TaskStoreError(
                "claim_task_mismatch",
                "bind every current claim cache to the exact task",
                str(claim_path),
            )
        try:
            epoch_text, epoch_task = epoch_content.decode("utf-8").split()
            epoch = int(epoch_text)
        except (UnicodeError, ValueError) as exc:
            raise TaskStoreError(
                "claim_epoch_malformed",
                "restore the '<epoch> <task_id>' claim epoch sidecar",
                str(epoch_path),
            ) from exc
        binding = load_claim_dispatch_binding(binding_path, content=binding_content)
        if (
            epoch <= 0
            or epoch_task != task_id
            or binding.claim_epoch != epoch
            or binding.task_id != task_id
            or binding.lane != role
            or binding.session_id != session_id
        ):
            raise TaskStoreError(
                "claim_binding_vector_mismatch",
                "reclaim through the exact governed dispatch so all claim sidecars agree",
                key,
            )
        leases.append(
            ClaimLeaseSnapshot(
                claim_key=key,
                claim_path=claim_path,
                claim_content=claim_content,
                claim_mode=claim_mode,
                epoch_path=epoch_path,
                epoch_content=epoch_content,
                epoch_mode=epoch_mode,
                binding_path=binding_path,
                binding_content=binding_content,
                binding_mode=binding_mode,
                binding=binding,
            )
        )
    if any(item.binding != leases[0].binding for item in leases[1:]):
        raise TaskStoreError(
            "claim_binding_sidecars_conflict",
            "restore identical role and session claim dispatch bindings",
            role,
        )
    return tuple(leases)


def resolve_claim_leases_for_task(
    cache_dir: Path,
    *,
    role: str,
    task_id: str,
) -> tuple[ClaimLeaseSnapshot, ...]:
    """Resolve a role-rooted lease using its durable dispatch-bound session."""

    binding_path = claim_dispatch_binding_path(cache_dir, role)
    binding_content, binding_mode = _regular_file_bytes(
        binding_path,
        reason_code="claim_dispatch_binding_missing",
    )
    binding = load_claim_dispatch_binding(binding_path, content=binding_content)
    if binding.task_id != task_id or binding.lane != role or not binding.session_id.strip():
        raise TaskStoreError(
            "claim_role_binding_mismatch",
            "restore the role binding for this exact task, lane, and claim session",
            role,
        )
    leases = resolve_claim_leases(
        cache_dir,
        role=role,
        session_id=binding.session_id,
        task_id=task_id,
    )
    role_lease = leases[0]
    if (
        role_lease.binding_path != binding_path
        or role_lease.binding_content != binding_content
        or role_lease.binding_mode != binding_mode
        or role_lease.binding != binding
    ):
        raise TaskStoreError(
            "claim_role_binding_changed_during_resolution",
            "retry after the exact role binding stabilizes",
            role,
        )
    return leases


_StatVector = tuple[int, int, int, int, int, int, int, int, int]
_StateManifest = tuple[tuple[Path, _StatVector], ...]


@dataclass(frozen=True)
class TaskIdentityEntry:
    state: TaskState
    path: Path
    stat_vector: _StatVector
    task_id: str | None
    content_sha256: str | None
    mode: int | None
    error_reason_code: str | None = None
    error_repair_action: str | None = None
    error_detail: str | None = None
    legacy_classification: Literal["annotated_legacy", "legacy_cc_task"] | None = None
    legacy_status: str | None = None


@dataclass(frozen=True)
class TaskIdentityIndex:
    vault_root: Path
    manifest: Mapping[TaskState, _StateManifest]
    entries: tuple[TaskIdentityEntry, ...]
    by_task_id: Mapping[str, tuple[TaskIdentityEntry, ...]]
    unbound_entries: tuple[TaskIdentityEntry, ...]
    frontier_hash: str
    content_frontier_hash: str
    no_effect: Literal[True] = True
    may_authorize: Literal[False] = False


@dataclass(frozen=True)
class LegacyTaskSnapshot:
    legacy_locator: str
    relative_path: str
    content_sha256: str
    status: str
    classification: Literal["annotated_legacy", "legacy_cc_task"]
    identity_state: Literal["unresolved_candidate"] = "unresolved_candidate"
    authority_ceiling: Literal["support_non_authoritative"] = "support_non_authoritative"
    loss: Literal["canonical_task_identity_absent"] = "canonical_task_identity_absent"
    may_authorize: Literal[False] = False

    def to_record(self) -> dict[str, object]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "classification": self.classification,
            "content_sha256": self.content_sha256,
            "identity_state": self.identity_state,
            "legacy_locator": self.legacy_locator,
            "loss": self.loss,
            "may_authorize": self.may_authorize,
            "relative_path": self.relative_path,
            "state": "closed",
            "status": self.status,
        }


@dataclass(frozen=True)
class TaskStoreAssessment:
    frontier_hash: str
    content_frontier_hash: str
    canonical_identity_count: int
    duplicate_identity_count: int
    legacy_snapshots: tuple[LegacyTaskSnapshot, ...]
    legacy_canonical_collisions: tuple[str, ...]
    blocking_unbound_refs: tuple[str, ...]
    assessment_hash: str
    no_effect: Literal[True] = True
    may_authorize: Literal[False] = False

    @staticmethod
    def _body(
        *,
        legacy_canonical_collisions: tuple[str, ...],
        frontier_hash: str,
        content_frontier_hash: str,
        canonical_identity_count: int,
        duplicate_identity_count: int,
        legacy_snapshots: tuple[LegacyTaskSnapshot, ...],
        blocking_unbound_refs: tuple[str, ...],
    ) -> dict[str, object]:
        return {
            "legacy_canonical_collisions": list(legacy_canonical_collisions),
            "blocking_unbound_refs": list(blocking_unbound_refs),
            "canonical_identity_count": canonical_identity_count,
            "duplicate_identity_count": duplicate_identity_count,
            "content_frontier_hash": content_frontier_hash,
            "frontier_hash": frontier_hash,
            "legacy_snapshots": [item.to_record() for item in legacy_snapshots],
            "may_authorize": False,
            "no_effect": True,
            "schema": "hapax.task-store-assessment.v1",
        }

    def to_record(self) -> dict[str, object]:
        return {
            **self._body(
                legacy_canonical_collisions=self.legacy_canonical_collisions,
                frontier_hash=self.frontier_hash,
                content_frontier_hash=self.content_frontier_hash,
                canonical_identity_count=self.canonical_identity_count,
                duplicate_identity_count=self.duplicate_identity_count,
                legacy_snapshots=self.legacy_snapshots,
                blocking_unbound_refs=self.blocking_unbound_refs,
            ),
            "assessment_hash": self.assessment_hash,
        }


@dataclass(frozen=True)
class TaskIdentityWriteIntent:
    task_id: str
    state: TaskState
    relative_path: str
    content_sha256: str

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        state: TaskState,
        relative_path: str,
        content_sha256: str,
    ) -> TaskIdentityWriteIntent:
        normalized_task_id = task_id.strip()
        if not normalized_task_id or "/" in normalized_task_id or normalized_task_id in {".", ".."}:
            raise TaskStoreError(
                "task_identity_write_intent_task_id_invalid",
                "use one non-path task identifier",
                task_id,
            )
        if state not in _TASK_STATES:
            raise TaskStoreError(
                "task_identity_write_intent_state_invalid",
                "use one canonical task vault state",
                str(state),
            )
        relative = PurePosixPath(relative_path)
        if (
            relative.is_absolute()
            or len(relative.parts) != 2
            or relative.parts[0] != state
            or relative.parts[1] in {"", ".", ".."}
            or not relative.parts[1].endswith(".md")
            or relative.as_posix() != relative_path
        ):
            raise TaskStoreError(
                "task_identity_write_intent_path_invalid",
                "bind one normalized Markdown child below the intended canonical state",
                relative_path,
            )
        if re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None:
            raise TaskStoreError(
                "task_identity_write_intent_hash_invalid",
                "bind the exact staged task-note SHA-256",
                content_sha256,
            )
        return cls(
            task_id=normalized_task_id,
            state=state,
            relative_path=relative_path,
            content_sha256=content_sha256,
        )

    def to_record(self) -> dict[str, str]:
        return {
            "content_sha256": self.content_sha256,
            "relative_path": self.relative_path,
            "state": self.state,
            "task_id": self.task_id,
        }


@dataclass(frozen=True)
class TaskIdentityWriteGuard:
    vault_root: Path
    base_frontier_hash: str
    base_content_frontier_hash: str
    expected_content_frontier_hash: str
    intents: tuple[TaskIdentityWriteIntent, ...]
    guard_hash: str
    no_effect: Literal[True] = True
    may_authorize: Literal[False] = False

    @staticmethod
    def _body(
        base_frontier_hash: str,
        base_content_frontier_hash: str,
        expected_content_frontier_hash: str,
        intents: tuple[TaskIdentityWriteIntent, ...],
    ) -> dict[str, object]:
        return {
            "base_frontier_hash": base_frontier_hash,
            "base_content_frontier_hash": base_content_frontier_hash,
            "expected_content_frontier_hash": expected_content_frontier_hash,
            "intents": [intent.to_record() for intent in intents],
            "may_authorize": False,
            "no_effect": True,
            "schema": "hapax.task-identity-write-guard.v2",
        }

    @classmethod
    def create(
        cls,
        *,
        vault_root: Path,
        base_frontier_hash: str,
        base_content_frontier_hash: str,
        expected_content_frontier_hash: str,
        intents: tuple[TaskIdentityWriteIntent, ...],
    ) -> TaskIdentityWriteGuard:
        if re.fullmatch(r"[0-9a-f]{64}", base_frontier_hash) is None:
            raise TaskStoreError(
                "task_identity_write_guard_frontier_invalid",
                "bind one exact task identity frontier hash",
                base_frontier_hash,
            )
        for label, value in (
            ("base", base_content_frontier_hash),
            ("expected", expected_content_frontier_hash),
        ):
            if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise TaskStoreError(
                    "task_identity_write_guard_content_frontier_invalid",
                    "bind exact base and expected task identity content frontiers",
                    f"{label}={value}",
                )
        if not intents:
            raise TaskStoreError(
                "task_identity_write_guard_empty",
                "bind at least one exact task identity write intent",
            )
        task_ids = [intent.task_id for intent in intents]
        relative_paths = [intent.relative_path for intent in intents]
        if len(task_ids) != len(set(task_ids)) or len(relative_paths) != len(set(relative_paths)):
            raise TaskStoreError(
                "task_identity_write_guard_duplicate_intent",
                "bind each intended task identity and destination exactly once",
            )
        ordered = tuple(sorted(intents, key=lambda intent: (intent.state, intent.relative_path)))
        body = cls._body(
            base_frontier_hash,
            base_content_frontier_hash,
            expected_content_frontier_hash,
            ordered,
        )
        guard_hash = hashlib.sha256(
            b"hapax.task-identity-write-guard.v2\0" + _canonical_json_bytes(body)
        ).hexdigest()
        return cls(
            vault_root=_normalized_path(vault_root),
            base_frontier_hash=base_frontier_hash,
            base_content_frontier_hash=base_content_frontier_hash,
            expected_content_frontier_hash=expected_content_frontier_hash,
            intents=ordered,
            guard_hash=guard_hash,
        )

    def to_record(self) -> dict[str, object]:
        return {
            **self._body(
                self.base_frontier_hash,
                self.base_content_frontier_hash,
                self.expected_content_frontier_hash,
                self.intents,
            ),
            "guard_hash": self.guard_hash,
        }


@dataclass(frozen=True)
class TaskIdentityWriteReconciliation:
    guard_hash: str
    base_frontier_hash: str
    base_content_frontier_hash: str
    observed_content_frontier_hash: str
    observed_frontier_hash: str
    installed_task_ids: tuple[str, ...]
    absent_task_ids: tuple[str, ...]
    complete: bool
    no_effect: Literal[True] = True
    may_authorize: Literal[False] = False


def _stat_vector(metadata: os.stat_result) -> _StatVector:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _state_manifest(vault_root: Path, state: TaskState) -> _StateManifest:
    directory = _normalized_path(vault_root / state)
    try:
        directory_fd = open_task_store_directory_fd(directory)
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise TaskStoreError(
            "task_note_directory_unsafe",
            "restore the task vault state directory as a real non-symlink directory",
            str(directory),
        ) from exc
    try:
        names = sorted(name for name in os.listdir(directory_fd) if name.endswith(".md"))
        manifest: list[tuple[Path, _StatVector]] = []
        for name in names:
            try:
                metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise TaskStoreError(
                    "task_store_frontier_changed_during_resolution",
                    "retry only after the complete task-store frontier stabilizes",
                    str(directory / name),
                ) from exc
            manifest.append((directory / name, _stat_vector(metadata)))
    finally:
        os.close(directory_fd)
    return tuple(manifest)


def _complete_frontier(vault_root: Path) -> dict[TaskState, _StateManifest]:
    return {state: _state_manifest(vault_root, state) for state in _TASK_STATES}


def _frontier_map(
    frontier: Mapping[TaskState, _StateManifest],
) -> dict[Path, tuple[TaskState, _StatVector]]:
    return {
        path: (state, stat_vector)
        for state in _TASK_STATES
        for path, stat_vector in frontier[state]
    }


def _frontier_hash(vault_root: Path, frontier: Mapping[TaskState, _StateManifest]) -> str:
    body = {
        "schema": "hapax.task-identity-index-frontier.v1",
        "entries": [
            {
                "path": path.relative_to(vault_root).as_posix(),
                "state": state,
                "stat_vector": list(stat_vector),
            }
            for state in _TASK_STATES
            for path, stat_vector in frontier[state]
        ],
    }
    return hashlib.sha256(
        b"hapax.task-identity-index-frontier.v1\0" + _canonical_json_bytes(body)
    ).hexdigest()


def _stat_ref(stat_vector: _StatVector) -> str:
    return hashlib.sha256(_canonical_json_bytes(list(stat_vector))).hexdigest()


def _frontier_delta(
    vault_root: Path,
    before: Mapping[TaskState, _StateManifest],
    after: Mapping[TaskState, _StateManifest],
) -> tuple[str, tuple[str, ...]]:
    before_map = _frontier_map(before)
    after_map = _frontier_map(after)
    records: list[dict[str, object]] = []
    evidence_refs: list[str] = []
    for path in sorted(set(before_map) | set(after_map), key=str):
        relative = path.relative_to(vault_root).as_posix()
        old = before_map.get(path)
        new = after_map.get(path)
        if old == new:
            continue
        if old is None:
            assert new is not None
            state, vector = new
            records.append({"change": "added", "path": relative, "state": state, "new": vector})
            evidence_refs.append(f"added:{relative}@stat:{_stat_ref(vector)}")
        elif new is None:
            state, vector = old
            records.append({"change": "removed", "path": relative, "state": state, "old": vector})
            evidence_refs.append(f"removed:{relative}@stat:{_stat_ref(vector)}")
        else:
            old_state, old_vector = old
            new_state, new_vector = new
            records.append(
                {
                    "change": "changed",
                    "path": relative,
                    "old_state": old_state,
                    "new_state": new_state,
                    "old": old_vector,
                    "new": new_vector,
                }
            )
            evidence_refs.append(
                f"changed:{relative}@stat:{_stat_ref(old_vector)}->{_stat_ref(new_vector)}"
            )
    payload = {"schema": "hapax.task-store-frontier-delta.v1", "changes": records}
    digest = hashlib.sha256(
        b"hapax.task-store-frontier-delta.v1\0" + _canonical_json_bytes(payload)
    ).hexdigest()
    counts = {
        change: sum(record["change"] == change for record in records)
        for change in ("added", "removed", "changed")
    }
    detail = (
        f"delta_ref=task-store-delta@sha256:{digest};"
        f"added={counts['added']};removed={counts['removed']};changed={counts['changed']}"
    )
    return detail, tuple(evidence_refs)


def _raise_frontier_changed(
    *,
    reason_code: str,
    vault_root: Path,
    before: Mapping[TaskState, _StateManifest],
    after: Mapping[TaskState, _StateManifest],
) -> None:
    detail, evidence_refs = _frontier_delta(vault_root, before, after)
    raise TaskStoreError(
        reason_code,
        "retry only through a distinct resolution after the complete frontier stabilizes",
        detail,
        evidence_refs=evidence_refs,
    )


def _index_entry(
    path: Path,
    *,
    state: TaskState,
    stat_vector: _StatVector,
) -> TaskIdentityEntry:
    legacy_classification: Literal["annotated_legacy", "legacy_cc_task"] | None = None
    legacy_status: str | None = None
    try:
        content, mode = _regular_file_bytes(path, reason_code="task_note_path_unsafe")
        text = content.decode("utf-8")
    except TaskStoreError as exc:
        return TaskIdentityEntry(
            state=state,
            path=_normalized_path(path),
            stat_vector=stat_vector,
            task_id=None,
            content_sha256=None,
            mode=None,
            error_reason_code=exc.reason_code,
            error_repair_action=exc.repair_action,
            error_detail=exc.detail,
        )
    except UnicodeError:
        return TaskIdentityEntry(
            state=state,
            path=_normalized_path(path),
            stat_vector=stat_vector,
            task_id=None,
            content_sha256=hashlib.sha256(content).hexdigest(),
            mode=mode,
            error_reason_code="task_note_unreadable",
            error_repair_action="restore the exact UTF-8 task note and retry resolution",
            error_detail=str(path),
        )
    parsed = parse_frontmatter_with_diagnostics(text)
    if not parsed.ok or parsed.frontmatter is None:
        return TaskIdentityEntry(
            state=state,
            path=_normalized_path(path),
            stat_vector=stat_vector,
            task_id=None,
            content_sha256=hashlib.sha256(content).hexdigest(),
            mode=mode,
            error_reason_code="task_note_frontmatter_malformed",
            error_repair_action="restore one closed YAML frontmatter mapping",
            error_detail=f"{path}:{parsed.error_kind or 'unknown'}",
        )
    observed_task_id = str(parsed.frontmatter.get("task_id") or "").strip() or None
    observed_status = str(parsed.frontmatter.get("status") or "").strip().lower()
    observed_type = str(parsed.frontmatter.get("type") or "").strip()
    if (
        observed_task_id is None
        and state == "closed"
        and observed_status in {"done", "completed", "withdrawn"}
    ):
        if observed_type == "cc-task":
            legacy_classification = "legacy_cc_task"
        elif not observed_type:
            legacy_classification = "annotated_legacy"
        legacy_status = observed_status if legacy_classification is not None else None
    return TaskIdentityEntry(
        state=state,
        path=_normalized_path(path),
        stat_vector=stat_vector,
        task_id=observed_task_id,
        content_sha256=hashlib.sha256(content).hexdigest(),
        mode=mode,
        legacy_classification=legacy_classification,
        legacy_status=legacy_status,
    )


def _identity_content_record(
    vault_root: Path,
    entry: TaskIdentityEntry,
) -> dict[str, object]:
    return {
        "content_sha256": entry.content_sha256,
        "error_reason_code": entry.error_reason_code,
        "legacy_classification": entry.legacy_classification,
        "legacy_status": entry.legacy_status,
        "path": entry.path.relative_to(vault_root).as_posix(),
        "state": entry.state,
        "task_id": entry.task_id,
    }


def _intent_content_record(intent: TaskIdentityWriteIntent) -> dict[str, object]:
    return {
        "content_sha256": intent.content_sha256,
        "error_reason_code": None,
        "legacy_classification": None,
        "legacy_status": None,
        "path": intent.relative_path,
        "state": intent.state,
        "task_id": intent.task_id,
    }


def _identity_content_frontier_hash(
    vault_root: Path,
    entries: tuple[TaskIdentityEntry, ...],
    *,
    added_intents: tuple[TaskIdentityWriteIntent, ...] = (),
) -> str:
    records = [
        *(_identity_content_record(vault_root, entry) for entry in entries),
        *(_intent_content_record(intent) for intent in added_intents),
    ]
    records.sort(key=lambda record: (str(record["state"]), str(record["path"])))
    body = {
        "entries": records,
        "schema": "hapax.task-identity-content-frontier.v1",
    }
    return hashlib.sha256(
        b"hapax.task-identity-content-frontier.v1\0" + _canonical_json_bytes(body)
    ).hexdigest()


def _make_identity_index(
    vault_root: Path,
    frontier: Mapping[TaskState, _StateManifest],
    entries: tuple[TaskIdentityEntry, ...],
) -> TaskIdentityIndex:
    grouped: dict[str, list[TaskIdentityEntry]] = {}
    for entry in entries:
        if entry.task_id is not None and entry.error_reason_code is None:
            grouped.setdefault(entry.task_id, []).append(entry)
    by_task_id = MappingProxyType(
        {task_id: tuple(values) for task_id, values in sorted(grouped.items())}
    )
    immutable_frontier = MappingProxyType({state: tuple(frontier[state]) for state in _TASK_STATES})
    return TaskIdentityIndex(
        vault_root=vault_root,
        manifest=immutable_frontier,
        entries=entries,
        by_task_id=by_task_id,
        unbound_entries=tuple(
            entry
            for entry in entries
            if entry.task_id is None or entry.error_reason_code is not None
        ),
        frontier_hash=_frontier_hash(vault_root, frontier),
        content_frontier_hash=_identity_content_frontier_hash(vault_root, entries),
    )


def build_task_identity_index(vault_root: Path) -> TaskIdentityIndex:
    """Build one immutable, non-authorizing parsed-identity index."""

    root = _normalized_path(vault_root)
    frontier = _complete_frontier(root)
    entries = tuple(
        _index_entry(path, state=state, stat_vector=stat_vector)
        for state in _TASK_STATES
        for path, stat_vector in frontier[state]
    )
    post_frontier = _complete_frontier(root)
    if post_frontier != frontier:
        _raise_frontier_changed(
            reason_code="task_store_frontier_changed_during_index_build",
            vault_root=root,
            before=frontier,
            after=post_frontier,
        )
    return _make_identity_index(root, frontier, entries)


def validate_task_identity_index(index: TaskIdentityIndex) -> None:
    """Refuse drift without refreshing or replacing the supplied index."""

    current_frontier = _complete_frontier(index.vault_root)
    if current_frontier != index.manifest:
        _raise_frontier_changed(
            reason_code="task_store_frontier_changed_since_index",
            vault_root=index.vault_root,
            before=index.manifest,
            after=current_frontier,
        )


def _task_identity_entry_ref(index: TaskIdentityIndex, entry: TaskIdentityEntry) -> str:
    relative = entry.path.relative_to(index.vault_root).as_posix()
    content = entry.content_sha256 or "unreadable"
    return f"task-artifact:{relative}@content:{content}@stat:{_stat_ref(entry.stat_vector)}"


def resolve_task_identity_projection(
    vault_root: Path,
    task_ids: tuple[str, ...],
    *,
    identity_index: TaskIdentityIndex | None = None,
) -> tuple[TaskIdentityEntry, ...]:
    """Resolve each requested identity exactly once across every canonical state.

    This is a read-only live projection join. It deliberately does not require
    the task to remain at its original path or retain its genesis bytes after a
    governed lifecycle transition.
    """

    normalized_ids = tuple(task_id.strip() for task_id in task_ids)
    if not normalized_ids or any(
        not task_id or "/" in task_id or task_id in {".", ".."} for task_id in normalized_ids
    ):
        raise TaskStoreError(
            "task_identity_projection_request_invalid",
            "request at least one non-path canonical task identity",
        )
    if len(normalized_ids) != len(set(normalized_ids)):
        raise TaskStoreError(
            "task_identity_projection_request_duplicate",
            "request each live task identity exactly once",
            ",".join(normalized_ids),
        )

    root = _normalized_path(vault_root)
    index = identity_index or build_task_identity_index(root)
    if index.vault_root != root:
        raise TaskStoreError(
            "task_identity_projection_root_mismatch",
            "build the identity index from the exact requested task vault root",
            f"index={index.vault_root};requested={root}",
        )
    validate_task_identity_index(index)

    resolved: list[TaskIdentityEntry] = []
    for task_id in normalized_ids:
        matches = index.by_task_id.get(task_id, ())
        if not matches:
            locator_matches = tuple(
                entry
                for entry in index.entries
                if entry.path.name == f"{task_id}.md" or entry.path.stem.startswith(f"{task_id}-")
            )
            raise TaskStoreError(
                "task_identity_projection_missing",
                "restore exactly one live canonical projection of the committed task identity",
                task_id,
                evidence_refs=tuple(
                    _task_identity_entry_ref(index, entry) for entry in locator_matches
                ),
            )
        if len(matches) != 1:
            raise TaskStoreError(
                "task_identity_projection_ambiguous",
                "reconcile every duplicate projection of the committed task identity",
                task_id,
                evidence_refs=tuple(_task_identity_entry_ref(index, entry) for entry in matches),
            )
        entry = matches[0]
        if entry.error_reason_code is not None or entry.content_sha256 is None:
            raise TaskStoreError(
                "task_identity_projection_unreadable",
                "restore one readable canonical projection of the committed task identity",
                task_id,
                evidence_refs=(_task_identity_entry_ref(index, entry),),
            )
        resolved.append(entry)

    validate_task_identity_index(index)
    return tuple(resolved)


def assess_task_identity_index(index: TaskIdentityIndex) -> TaskStoreAssessment:
    legacy_snapshots = tuple(
        LegacyTaskSnapshot(
            legacy_locator=entry.path.stem,
            relative_path=entry.path.relative_to(index.vault_root).as_posix(),
            content_sha256=entry.content_sha256 or "",
            status=entry.legacy_status or "",
            classification=entry.legacy_classification,
        )
        for entry in index.unbound_entries
        if entry.legacy_classification is not None
        and entry.content_sha256 is not None
        and entry.legacy_status is not None
    )
    classified_paths = {snapshot.relative_path for snapshot in legacy_snapshots}
    blocking_refs = tuple(
        _task_identity_entry_ref(index, entry)
        for entry in index.unbound_entries
        if entry.path.relative_to(index.vault_root).as_posix() not in classified_paths
    )
    legacy_canonical_collisions = tuple(
        sorted({item.legacy_locator for item in legacy_snapshots} & set(index.by_task_id))
    )
    duplicate_count = sum(len(entries) > 1 for entries in index.by_task_id.values())
    ordered_snapshots = tuple(sorted(legacy_snapshots, key=lambda item: item.relative_path))
    body = TaskStoreAssessment._body(
        legacy_canonical_collisions=legacy_canonical_collisions,
        frontier_hash=index.frontier_hash,
        content_frontier_hash=index.content_frontier_hash,
        canonical_identity_count=len(index.by_task_id),
        duplicate_identity_count=duplicate_count,
        legacy_snapshots=ordered_snapshots,
        blocking_unbound_refs=blocking_refs,
    )
    assessment_hash = hashlib.sha256(
        b"hapax.task-store-assessment.v1\0" + _canonical_json_bytes(body)
    ).hexdigest()
    return TaskStoreAssessment(
        frontier_hash=index.frontier_hash,
        content_frontier_hash=index.content_frontier_hash,
        canonical_identity_count=len(index.by_task_id),
        duplicate_identity_count=duplicate_count,
        legacy_snapshots=ordered_snapshots,
        legacy_canonical_collisions=legacy_canonical_collisions,
        blocking_unbound_refs=blocking_refs,
        assessment_hash=assessment_hash,
    )


def _require_task_identity_write_store_integrity(
    index: TaskIdentityIndex,
    *,
    intended_task_ids: tuple[str, ...],
) -> TaskStoreAssessment:
    assessment = assess_task_identity_index(index)
    if assessment.blocking_unbound_refs:
        raise TaskStoreError(
            "task_identity_write_store_unclassified",
            "classify or repair every non-terminal unbound task artifact before creating identities",
            f"count={len(assessment.blocking_unbound_refs)}",
            evidence_refs=assessment.blocking_unbound_refs,
        )
    legacy_by_locator = {
        snapshot.legacy_locator: snapshot for snapshot in assessment.legacy_snapshots
    }
    collisions = tuple(
        legacy_by_locator[task_id]
        for task_id in sorted(set(intended_task_ids))
        if task_id in legacy_by_locator
    )
    if collisions:
        raise TaskStoreError(
            "task_identity_write_legacy_alias_collision",
            "admit an explicit identity migration before targeting an unresolved legacy locator",
            ",".join(snapshot.legacy_locator for snapshot in collisions),
            evidence_refs=tuple(
                f"legacy-task-snapshot:{snapshot.relative_path}@content:{snapshot.content_sha256}"
                for snapshot in collisions
            ),
        )
    duplicate_entries = tuple(
        entry for entries in index.by_task_id.values() if len(entries) > 1 for entry in entries
    )
    if duplicate_entries:
        raise TaskStoreError(
            "task_identity_write_store_ambiguous",
            "reconcile every duplicate identity before creating task identities",
            f"identity_count={sum(len(entries) > 1 for entries in index.by_task_id.values())}",
            evidence_refs=tuple(
                _task_identity_entry_ref(index, entry) for entry in duplicate_entries
            ),
        )
    return assessment


def _parse_staged_task_identity(relative_path: str, content: bytes) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeError as exc:
        raise TaskStoreError(
            "task_identity_write_staged_unreadable",
            "stage one exact UTF-8 task note",
            relative_path,
        ) from exc
    parsed = parse_frontmatter_with_diagnostics(text)
    if not parsed.ok or parsed.frontmatter is None:
        raise TaskStoreError(
            "task_identity_write_staged_frontmatter_malformed",
            "stage one closed YAML frontmatter mapping",
            f"{relative_path}:{parsed.error_kind or 'unknown'}",
        )
    task_id = str(parsed.frontmatter.get("task_id") or "").strip()
    if not task_id:
        raise TaskStoreError(
            "task_identity_write_staged_task_id_missing",
            "bind the exact intended task_id in staged frontmatter",
            relative_path,
        )
    return task_id


def prepare_task_identity_writes(
    index: TaskIdentityIndex,
    intents: tuple[TaskIdentityWriteIntent, ...],
    staged_bytes: Mapping[str, bytes],
) -> TaskIdentityWriteGuard:
    """Validate an exact no-effect identity-creation basis."""

    validate_task_identity_index(index)
    intended_paths = {intent.relative_path for intent in intents}
    if set(staged_bytes) != intended_paths:
        raise TaskStoreError(
            "task_identity_write_staged_set_mismatch",
            "stage exactly one byte image for every intended task identity",
            f"expected={sorted(intended_paths)};observed={sorted(staged_bytes)}",
        )
    entries_by_path = {
        entry.path.relative_to(index.vault_root).as_posix(): entry for entry in index.entries
    }
    for intent in intents:
        content = staged_bytes[intent.relative_path]
        content_sha256 = hashlib.sha256(content).hexdigest()
        if content_sha256 != intent.content_sha256:
            raise TaskStoreError(
                "task_identity_write_staged_hash_mismatch",
                "stage the exact content-bound task note",
                intent.relative_path,
            )
        observed_task_id = _parse_staged_task_identity(intent.relative_path, content)
        if observed_task_id != intent.task_id:
            raise TaskStoreError(
                "task_identity_write_staged_identity_mismatch",
                "make staged frontmatter name the exact intended task identity",
                f"{intent.relative_path}:{observed_task_id}",
            )
        existing_identity = index.by_task_id.get(intent.task_id, ())
        if existing_identity:
            raise TaskStoreError(
                "task_identity_write_identity_exists",
                "do not create an identity already present in any canonical state",
                intent.task_id,
                evidence_refs=tuple(
                    _task_identity_entry_ref(index, entry) for entry in existing_identity
                ),
            )
        existing_path = entries_by_path.get(intent.relative_path)
        if existing_path is not None:
            raise TaskStoreError(
                "task_identity_write_path_exists",
                "do not create through an occupied canonical task path",
                intent.relative_path,
                evidence_refs=(_task_identity_entry_ref(index, existing_path),),
            )
    guard = TaskIdentityWriteGuard.create(
        vault_root=index.vault_root,
        base_frontier_hash=index.frontier_hash,
        base_content_frontier_hash=index.content_frontier_hash,
        expected_content_frontier_hash=_identity_content_frontier_hash(
            index.vault_root,
            index.entries,
            added_intents=intents,
        ),
        intents=intents,
    )
    _require_task_identity_write_store_integrity(
        index, intended_task_ids=tuple(intent.task_id for intent in guard.intents)
    )
    return guard


def load_task_identity_write_guard(
    record: Mapping[str, object],
    *,
    vault_root: Path,
) -> TaskIdentityWriteGuard:
    if record.get("schema") != "hapax.task-identity-write-guard.v2":
        raise TaskStoreError(
            "task_identity_write_guard_schema_invalid",
            "restore one canonical task identity write guard record",
        )
    raw_intents = record.get("intents")
    if not isinstance(raw_intents, list):
        raise TaskStoreError(
            "task_identity_write_guard_intents_invalid",
            "restore the exact typed task identity write intents",
        )
    try:
        intents = tuple(
            TaskIdentityWriteIntent.create(
                task_id=str(item["task_id"]),
                state=str(item["state"]),  # type: ignore[arg-type]
                relative_path=str(item["relative_path"]),
                content_sha256=str(item["content_sha256"]),
            )
            for item in raw_intents
            if isinstance(item, dict)
        )
    except (KeyError, TypeError, TaskStoreError) as exc:
        raise TaskStoreError(
            "task_identity_write_guard_intents_invalid",
            "restore the exact typed task identity write intents",
        ) from exc
    if len(intents) != len(raw_intents):
        raise TaskStoreError(
            "task_identity_write_guard_intents_invalid",
            "restore the exact typed task identity write intents",
        )
    guard = TaskIdentityWriteGuard.create(
        vault_root=vault_root,
        base_frontier_hash=str(record.get("base_frontier_hash") or ""),
        base_content_frontier_hash=str(record.get("base_content_frontier_hash") or ""),
        expected_content_frontier_hash=str(record.get("expected_content_frontier_hash") or ""),
        intents=intents,
    )
    if record != guard.to_record():
        raise TaskStoreError(
            "task_identity_write_guard_hash_mismatch",
            "restore the exact self-hashed task identity write guard",
        )
    return guard


def reconcile_task_identity_writes(
    guard: TaskIdentityWriteGuard,
    current_index: TaskIdentityIndex,
) -> TaskIdentityWriteReconciliation:
    """Accept only exact intended additions over the guard's base frontier."""

    if current_index.vault_root != guard.vault_root:
        raise TaskStoreError(
            "task_identity_write_guard_root_mismatch",
            "reconcile against the exact guarded task vault root",
        )
    validate_task_identity_index(current_index)
    _require_task_identity_write_store_integrity(
        current_index, intended_task_ids=tuple(intent.task_id for intent in guard.intents)
    )
    current_by_path = {
        entry.path.relative_to(current_index.vault_root).as_posix(): entry
        for entry in current_index.entries
    }
    installed: list[TaskIdentityWriteIntent] = []
    absent: list[TaskIdentityWriteIntent] = []
    for intent in guard.intents:
        identity_entries = current_index.by_task_id.get(intent.task_id, ())
        path_entry = current_by_path.get(intent.relative_path)
        if not identity_entries:
            if path_entry is not None:
                raise TaskStoreError(
                    "task_identity_write_path_occupied_by_other_identity",
                    "restore the guarded destination to absence before recovery",
                    intent.relative_path,
                    evidence_refs=(_task_identity_entry_ref(current_index, path_entry),),
                )
            absent.append(intent)
            continue
        if len(identity_entries) != 1:
            raise TaskStoreError(
                "task_identity_write_installed_identity_ambiguous",
                "reconcile every copy of the intended identity before recovery",
                intent.task_id,
                evidence_refs=tuple(
                    _task_identity_entry_ref(current_index, entry) for entry in identity_entries
                ),
            )
        entry = identity_entries[0]
        if (
            entry.state != intent.state
            or entry.path.relative_to(current_index.vault_root).as_posix() != intent.relative_path
            or entry.content_sha256 != intent.content_sha256
        ):
            raise TaskStoreError(
                "task_identity_write_installed_postimage_mismatch",
                "restore the exact intended state path identity and content",
                intent.task_id,
                evidence_refs=(_task_identity_entry_ref(current_index, entry),),
            )
        installed.append(intent)

    installed_paths = {current_index.vault_root / intent.relative_path for intent in installed}
    residual_frontier = {
        state: tuple(
            (path, stat_vector)
            for path, stat_vector in current_index.manifest[state]
            if path not in installed_paths
        )
        for state in _TASK_STATES
    }
    residual_hash = _frontier_hash(current_index.vault_root, residual_frontier)
    residual_entries = tuple(
        entry for entry in current_index.entries if entry.path not in installed_paths
    )
    residual_content_hash = _identity_content_frontier_hash(
        current_index.vault_root, residual_entries
    )
    if residual_content_hash != guard.base_content_frontier_hash:
        raise TaskStoreError(
            "task_identity_write_residual_content_frontier_mismatch",
            "remove unrelated content drift or rebuild a separately admitted write guard",
            (
                f"expected={guard.base_content_frontier_hash};"
                f"observed={residual_content_hash};current={current_index.content_frontier_hash}"
            ),
        )
    if residual_hash != guard.base_frontier_hash:
        raise TaskStoreError(
            "task_identity_write_residual_frontier_mismatch",
            "remove unrelated drift or rebuild a separately admitted write guard",
            (
                f"expected={guard.base_frontier_hash};observed={residual_hash};"
                f"current={current_index.frontier_hash}"
            ),
        )
    complete = not absent
    if complete and current_index.content_frontier_hash != guard.expected_content_frontier_hash:
        raise TaskStoreError(
            "task_identity_write_expected_content_frontier_mismatch",
            "restore the exact guarded content post-frontier before receipt",
            (
                f"expected={guard.expected_content_frontier_hash};"
                f"observed={current_index.content_frontier_hash}"
            ),
        )
    return TaskIdentityWriteReconciliation(
        guard_hash=guard.guard_hash,
        base_frontier_hash=guard.base_frontier_hash,
        base_content_frontier_hash=guard.base_content_frontier_hash,
        observed_content_frontier_hash=current_index.content_frontier_hash,
        observed_frontier_hash=current_index.frontier_hash,
        installed_task_ids=tuple(intent.task_id for intent in installed),
        absent_task_ids=tuple(intent.task_id for intent in absent),
        complete=complete,
    )


def refresh_task_identity_index(index: TaskIdentityIndex) -> TaskIdentityIndex:
    """Explicitly refresh changed entries; never called implicitly by resolution."""

    frontier = _complete_frontier(index.vault_root)
    old_entries = {entry.path: entry for entry in index.entries}
    entries: list[TaskIdentityEntry] = []
    for state in _TASK_STATES:
        for path, stat_vector in frontier[state]:
            old = old_entries.get(path)
            if old is not None and old.state == state and old.stat_vector == stat_vector:
                entries.append(old)
            else:
                entries.append(_index_entry(path, state=state, stat_vector=stat_vector))
    post_frontier = _complete_frontier(index.vault_root)
    if post_frontier != frontier:
        _raise_frontier_changed(
            reason_code="task_store_frontier_changed_during_index_refresh",
            vault_root=index.vault_root,
            before=frontier,
            after=post_frontier,
        )
    return _make_identity_index(index.vault_root, frontier, tuple(entries))


def _raise_entry_error(entry: TaskIdentityEntry) -> None:
    assert entry.error_reason_code is not None
    raise TaskStoreError(
        entry.error_reason_code,
        entry.error_repair_action or "restore the exact task-store artifact",
        entry.error_detail,
        evidence_refs=(f"task-artifact:{entry.path}@stat:{_stat_ref(entry.stat_vector)}",),
    )


def _snapshot(path: Path, *, expected_task_id: str, state: TaskState) -> TaskNoteSnapshot:
    try:
        content, mode = _regular_file_bytes(path, reason_code="task_note_path_unsafe")
        text = content.decode("utf-8")
    except TaskStoreError:
        raise
    except UnicodeError as exc:
        raise TaskStoreError(
            "task_note_unreadable",
            "restore the exact UTF-8 task note and retry resolution",
            str(path),
        ) from exc
    parsed = parse_frontmatter_with_diagnostics(text)
    if not parsed.ok or parsed.frontmatter is None:
        raise TaskStoreError(
            "task_note_frontmatter_malformed",
            "restore one closed YAML frontmatter mapping",
            f"{path}:{parsed.error_kind or 'unknown'}",
        )
    observed_task_id = str(parsed.frontmatter.get("task_id") or "").strip()
    if observed_task_id != expected_task_id:
        raise TaskStoreError(
            "task_note_identity_mismatch",
            "make the filename candidate and frontmatter task_id name the same task",
            f"{path}:{observed_task_id or 'missing'}",
        )
    return TaskNoteSnapshot(
        task_id=expected_task_id,
        state=state,
        path=_normalized_path(path),
        content=content,
        mode=mode,
        frontmatter=dict(parsed.frontmatter),
        body=parsed.body,
    )


def resolve_task_note(
    vault_root: Path,
    task_id: str,
    *,
    state: TaskState = "active",
    require_no_other_state: bool = True,
    identity_index: TaskIdentityIndex | None = None,
) -> TaskNoteSnapshot:
    """Resolve one parsed identity across the complete task-state namespace."""

    normalized = task_id.strip()
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        raise TaskStoreError(
            "task_id_invalid",
            "use one non-path task identifier",
            task_id,
        )
    if state not in _TASK_STATES:
        raise TaskStoreError(
            "task_note_state_invalid",
            "use one canonical task vault state",
            str(state),
        )
    if not require_no_other_state:
        raise TaskStoreError(
            "task_note_partial_resolution_forbidden",
            "resolve the task identity across every canonical state before mutation",
            normalized,
        )

    root = _normalized_path(vault_root)
    index = identity_index or build_task_identity_index(root)
    if index.vault_root != root:
        raise TaskStoreError(
            "task_identity_index_root_mismatch",
            "build the identity index from the exact requested task vault root",
            f"index={index.vault_root};requested={root}",
        )
    validate_task_identity_index(index)

    exact_name = f"{normalized}.md"
    for entry in index.entries:
        if entry.path.name == exact_name and entry.task_id != normalized:
            if entry.error_reason_code is not None:
                _raise_entry_error(entry)
            raise TaskStoreError(
                "task_note_identity_mismatch",
                "make the exact filename locator and frontmatter task_id name the same task",
                f"{entry.path}:{entry.task_id or 'missing'}",
            )
    for entry in index.unbound_entries:
        if entry.path.name.startswith(normalized):
            if entry.error_reason_code is not None:
                _raise_entry_error(entry)
            raise TaskStoreError(
                "task_note_identity_mismatch",
                "bind the task_id in every matching task locator",
                f"{entry.path}:missing",
            )

    matches = index.by_task_id.get(normalized, ())
    by_state = {
        candidate_state: tuple(entry for entry in matches if entry.state == candidate_state)
        for candidate_state in _TASK_STATES
    }
    for state_matches in by_state.values():
        if len(state_matches) > 1:
            raise TaskStoreError(
                "task_note_identity_ambiguous",
                "retain exactly one task note for this parsed identity in each state",
                ",".join(str(entry.path) for entry in state_matches),
            )
    if len(matches) > 1:
        raise TaskStoreError(
            "task_note_cross_state_duplicate",
            "reconcile every state copy before lifecycle mutation",
            ",".join(str(entry.path) for entry in matches),
        )
    if not matches:
        raise TaskStoreError(
            "task_note_not_found",
            f"restore the {state} task note before lifecycle mutation",
            normalized,
        )
    selected = matches[0]
    if selected.state != state:
        raise TaskStoreError(
            "task_note_state_mismatch",
            f"move the canonical task note to {state} through the governed lifecycle",
            str(selected.path),
        )
    snapshot = _snapshot(selected.path, expected_task_id=normalized, state=state)
    if snapshot.sha256 != selected.content_sha256 or snapshot.mode != selected.mode:
        raise TaskStoreError(
            "task_note_changed_since_identity_index",
            "build a fresh identity index before lifecycle mutation",
            str(selected.path),
        )
    post_frontier = _complete_frontier(root)
    if post_frontier != index.manifest:
        _raise_frontier_changed(
            reason_code="task_store_frontier_changed_during_resolution",
            vault_root=root,
            before=index.manifest,
            after=post_frontier,
        )
    return snapshot
