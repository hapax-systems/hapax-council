"""Strict task-note identity and dispatch-bound claim sidecars."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.sdlc_lifecycle import TASK_MUTABLE_STATUSES
from shared.sdlc_owner_identity import owner_matches

TaskState = Literal["active", "closed"]
CLAIM_DISPATCH_BINDING_SCHEMA = "hapax.claim-dispatch-binding.v1"


class TaskStoreError(RuntimeError):
    """Typed refusal raised before an SDLC identity mutation."""

    def __init__(self, reason_code: str, repair_action: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
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


def _snapshot(path: Path, *, expected_task_id: str, state: TaskState) -> TaskNoteSnapshot:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise TaskStoreError(
            "task_note_unreadable",
            "restore the exact regular task note and retry resolution",
            str(path),
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise TaskStoreError(
            "task_note_path_unsafe",
            "use one regular non-symlink task note",
            str(path),
        )
    try:
        content = path.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise TaskStoreError(
            "task_note_unreadable",
            "restore the exact UTF-8 task note and retry resolution",
            str(path),
        ) from exc
    parsed = parse_frontmatter_with_diagnostics(text)
    if not parsed.ok or parsed.frontmatter is None:
        if parsed.error_kind == "missing_closing_marker":
            repair = "restore the task note; it has no closing frontmatter delimiter"
        elif (
            parsed.error_kind == "yaml_error"
            and "duplicate" in (parsed.error_message or "").lower()
        ):
            repair = "remove duplicate frontmatter keys"
        else:
            repair = "restore one closed YAML frontmatter mapping"
        raise TaskStoreError(
            "task_note_frontmatter_malformed",
            repair,
            f"{path}:{parsed.error_kind or 'unknown'}",
        )
    observed_task_id = parsed.frontmatter.get("task_id")
    if not isinstance(observed_task_id, str) or observed_task_id.strip() != expected_task_id:
        raise TaskStoreError(
            "task_note_identity_mismatch",
            "make the selected filename and frontmatter task_id name the same task",
            f"{path}:{str(observed_task_id or 'missing').strip()}",
        )
    return TaskNoteSnapshot(
        task_id=expected_task_id,
        state=state,
        path=path.resolve(strict=True),
        content=content,
        mode=metadata.st_mode & 0o777,
        frontmatter=dict(parsed.frontmatter),
        body=parsed.body,
    )


def resolve_task_note(
    vault_root: Path,
    task_id: str,
    *,
    state: TaskState = "active",
) -> TaskNoteSnapshot:
    """Resolve one note with exact-path precedence and strict declared identity."""

    normalized = task_id.strip()
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        raise TaskStoreError(
            "task_id_invalid",
            "use one non-path task identifier",
            task_id,
        )
    directory = vault_root / state
    exact = directory / f"{normalized}.md"
    if exact.exists() or exact.is_symlink():
        return _snapshot(exact, expected_task_id=normalized, state=state)

    try:
        candidates = sorted(directory.glob(f"{normalized}-*.md"))
    except OSError as exc:
        raise TaskStoreError(
            "task_note_unreadable",
            "restore the active task directory and retry resolution",
            str(directory),
        ) from exc
    matches: list[TaskNoteSnapshot] = []
    for candidate in candidates:
        try:
            matches.append(_snapshot(candidate, expected_task_id=normalized, state=state))
        except TaskStoreError as exc:
            if exc.reason_code == "task_note_identity_mismatch":
                continue
            raise
    if not matches:
        raise TaskStoreError(
            "task_note_not_found",
            f"restore the {state} task note before lifecycle mutation",
            normalized,
        )
    if len(matches) != 1:
        raise TaskStoreError(
            "task_note_identity_ambiguous",
            "retain exactly one task note for this identity",
            ",".join(str(item.path) for item in matches),
        )
    return matches[0]


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
        required = (
            task_id,
            lane,
            dispatch_message_id,
            platform,
            mode,
            profile,
            authority_case,
        )
        if any(not value.strip() for value in required):
            raise TaskStoreError(
                "claim_dispatch_binding_field_missing",
                "bind every claim dispatch identity field before exposing the claim",
            )
        if claim_epoch <= 0:
            raise TaskStoreError(
                "claim_dispatch_binding_epoch_invalid",
                "bind the positive epoch written beside this exact claim",
            )
        if re.fullmatch(r"[0-9a-f]{64}", binding_hash) is None:
            raise TaskStoreError(
                "claim_dispatch_binding_hash_invalid",
                "bind the exact 64-hex dispatch preparation hash",
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


def claim_dispatch_binding_bytes(binding: ClaimDispatchBinding) -> bytes:
    return _canonical_json_bytes(binding.to_record()) + b"\n"


def write_claim_dispatch_binding(
    cache_dir: Path,
    claim_key: str,
    binding: ClaimDispatchBinding,
) -> Path:
    path = claim_dispatch_binding_path(cache_dir, claim_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = claim_dispatch_binding_bytes(binding)
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


def load_claim_dispatch_binding(path: Path) -> ClaimDispatchBinding:
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
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError("not a regular non-symlink file")
        record = json.loads(path.read_text(encoding="ascii"), object_pairs_hook=unique_pairs)
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
        or not isinstance(record.get("claim_epoch"), int)
        or isinstance(record.get("claim_epoch"), bool)
    ):
        raise TaskStoreError(
            "claim_dispatch_binding_malformed",
            "restore the exact non-authorizing claim binding schema",
            str(path),
        )
    binding = ClaimDispatchBinding.create(
        task_id=str(record["task_id"]),
        lane=str(record["lane"]),
        session_id=str(record["session_id"]),
        claim_epoch=int(record["claim_epoch"]),
        dispatch_message_id=str(record["dispatch_message_id"]),
        platform=str(record["platform"]),
        mode=str(record["mode"]),
        profile=str(record["profile"]),
        authority_case=str(record["authority_case"]),
        binding_hash=str(record["binding_hash"]),
        coord_dispatch_idempotency_key=(
            str(record["coord_dispatch_idempotency_key"])
            if record["coord_dispatch_idempotency_key"] is not None
            else None
        ),
    )
    if record.get("receipt_hash") != binding.receipt_hash:
        raise TaskStoreError(
            "claim_dispatch_binding_receipt_hash_mismatch",
            "restore the exact self-hashed claim binding sidecar",
            str(path),
        )
    return binding


def _read_regular_text(path: Path, *, reason_code: str) -> str:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError("not a regular non-symlink file")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TaskStoreError(
            reason_code,
            "restore the exact claim projection and retry verification",
            str(path),
        ) from exc


def assert_claim_slot_available(
    *,
    cache_dir: Path,
    role: str,
    session_id: str,
    task_id: str,
) -> None:
    """Refuse any claim that would replace or inherit existing ownership.

    Claim age, task terminality, and a force flag are not authority to detach a
    slot. Existing dispatch bindings also require the explicit read-only verify
    path rather than a mutating claim refresh.
    """

    legacy_key = role
    session_key = f"{role}-{session_id}" if session_id else ""
    try:
        claim_paths = sorted(cache_dir.glob(f"cc-active-task-{role}*"))
    except OSError as exc:
        raise TaskStoreError(
            "claim_slot_projection_unreadable",
            "restore readable claim projections before claiming",
            str(cache_dir),
        ) from exc

    observed_keys: set[str] = set()
    for path in claim_paths:
        prefix = "cc-active-task-"
        if not path.name.startswith(prefix):
            continue
        key = path.name.removeprefix(prefix)
        if key != legacy_key and not key.startswith(f"{role}-"):
            continue
        existing_task = _read_regular_text(
            path,
            reason_code="claim_slot_projection_unreadable",
        ).strip()
        if not existing_task:
            raise TaskStoreError(
                "claim_slot_projection_malformed",
                "repair the empty claim projection before claiming",
                str(path),
            )
        if existing_task != task_id:
            raise TaskStoreError(
                "claim_slot_occupied",
                "close or explicitly recover the existing owner before claiming new work",
                f"{key}:{existing_task}",
            )
        if key != legacy_key and key != session_key:
            raise TaskStoreError(
                "claim_same_task_owned_by_other_session",
                "resume the owning session or perform governed owner-only recovery",
                key,
            )
        observed_keys.add(key)

    projection_keys = set(observed_keys)
    for pattern, prefix, suffix in (
        (f"cc-claim-epoch-{role}*", "cc-claim-epoch-", ""),
        (f"cc-claim-dispatch-{role}*.json", "cc-claim-dispatch-", ".json"),
    ):
        try:
            paths = sorted(cache_dir.glob(pattern))
        except OSError as exc:
            raise TaskStoreError(
                "claim_slot_projection_unreadable",
                "restore readable claim projections before claiming",
                str(cache_dir),
            ) from exc
        for path in paths:
            key = path.name.removeprefix(prefix)
            if suffix and key.endswith(suffix):
                key = key.removesuffix(suffix)
            if key == legacy_key or key.startswith(f"{role}-"):
                projection_keys.add(key)

    relevant_keys = {legacy_key}
    if session_key:
        relevant_keys.add(session_key)
    for key in relevant_keys | projection_keys:
        binding_path = claim_dispatch_binding_path(cache_dir, key)
        epoch_path = cache_dir / f"cc-claim-epoch-{key}"
        claim_path = cache_dir / f"cc-active-task-{key}"
        if key != legacy_key and key != session_key:
            raise TaskStoreError(
                "claim_slot_projection_incomplete",
                "repair the other-session projection before claiming",
                key,
            )
        try:
            binding_present = binding_path.lstat() is not None
        except FileNotFoundError:
            binding_present = False
        except OSError as exc:
            raise TaskStoreError(
                "claim_slot_projection_unreadable",
                "restore readable claim projections before claiming",
                str(binding_path),
            ) from exc
        if binding_present:
            binding = load_claim_dispatch_binding(binding_path)
            if binding.task_id != task_id or binding.lane != role:
                raise TaskStoreError(
                    "claim_slot_dispatch_binding_mismatch",
                    "repair the exact claim/binding projection before claiming",
                    key,
                )
            raise TaskStoreError(
                "claim_slot_already_dispatch_bound",
                "use cc-claim --verify-dispatch-binding instead of mutating a bound claim",
                key,
            )
        try:
            claim_present = claim_path.lstat() is not None
        except FileNotFoundError:
            claim_present = False
        try:
            epoch_present = epoch_path.lstat() is not None
        except FileNotFoundError:
            epoch_present = False
        if claim_present != epoch_present:
            raise TaskStoreError(
                "claim_slot_projection_incomplete",
                "repair the claim and epoch projection before claiming",
                key,
            )
    if observed_keys and (not session_key or session_key not in observed_keys):
        raise TaskStoreError(
            "claim_same_task_session_unproven",
            "use the session that owns the exact session-keyed claim or recover explicitly",
            role,
        )


def assert_close_slot_owned(
    *,
    cache_dir: Path,
    role: str,
    session_id: str,
    task_id: str,
) -> None:
    """Verify that any local ownership projection belongs to this closer.

    A task-note owner may close without cache projections, but the presence of
    any claim projection raises the evidence floor: the claim, epoch, optional
    dispatch binding, role, task, and session must form one complete identity.
    """

    legacy_key = role
    session_key = f"{role}-{session_id}" if session_id else ""
    allowed_keys = {legacy_key}
    if session_key:
        allowed_keys.add(session_key)

    projection_keys: set[str] = set()
    for pattern, prefix, suffix in (
        (f"cc-active-task-{role}*", "cc-active-task-", ""),
        (f"cc-claim-epoch-{role}*", "cc-claim-epoch-", ""),
        (f"cc-claim-dispatch-{role}*.json", "cc-claim-dispatch-", ".json"),
    ):
        try:
            paths = sorted(cache_dir.glob(pattern))
        except OSError as exc:
            raise TaskStoreError(
                "close_slot_projection_unreadable",
                "restore readable ownership projections before closing",
                str(cache_dir),
            ) from exc
        for path in paths:
            key = path.name.removeprefix(prefix)
            if suffix and key.endswith(suffix):
                key = key.removesuffix(suffix)
            if key == legacy_key or key.startswith(f"{role}-"):
                projection_keys.add(key)

    unexpected = projection_keys - allowed_keys
    if unexpected:
        raise TaskStoreError(
            "close_slot_owned_by_other_session",
            "resume the session that owns the claim or perform governed owner-only recovery",
            ",".join(sorted(unexpected)),
        )

    bindings: list[ClaimDispatchBinding] = []
    binding_keys: set[str] = set()
    for key in sorted(projection_keys):
        claim_path = cache_dir / f"cc-active-task-{key}"
        epoch_path = cache_dir / f"cc-claim-epoch-{key}"
        binding_path = claim_dispatch_binding_path(cache_dir, key)

        def present(path: Path) -> bool:
            try:
                path.lstat()
            except FileNotFoundError:
                return False
            except OSError as exc:
                raise TaskStoreError(
                    "close_slot_projection_unreadable",
                    "restore readable ownership projections before closing",
                    str(path),
                ) from exc
            return True

        claim_present = present(claim_path)
        epoch_present = present(epoch_path)
        binding_present = present(binding_path)
        if claim_present != epoch_present or (binding_present and not claim_present):
            raise TaskStoreError(
                "close_slot_projection_incomplete",
                "restore the claim, epoch, and dispatch sidecars before closing",
                key,
            )
        if claim_present:
            claim_task = _read_regular_text(
                claim_path,
                reason_code="close_slot_projection_unreadable",
            ).strip()
            epoch_parts = _read_regular_text(
                epoch_path,
                reason_code="close_slot_projection_unreadable",
            ).split()
            if (
                claim_task != task_id
                or len(epoch_parts) != 2
                or not epoch_parts[0].isdigit()
                or epoch_parts[1] != task_id
            ):
                raise TaskStoreError(
                    "close_slot_projection_identity_mismatch",
                    "close only the exact task named by the current ownership projection",
                    key,
                )
        if binding_present:
            binding = load_claim_dispatch_binding(binding_path)
            if (
                binding.task_id != task_id
                or binding.lane != role
                or binding.session_id != session_id
            ):
                raise TaskStoreError(
                    "close_dispatch_binding_identity_mismatch",
                    "only the exact dispatch-bound session may close this task",
                    key,
                )
            bindings.append(binding)
            binding_keys.add(key)

    if bindings:
        expected_binding_keys = {legacy_key}
        if session_id:
            expected_binding_keys.add(session_key)
        if binding_keys != expected_binding_keys or any(
            binding.receipt_hash != bindings[0].receipt_hash for binding in bindings
        ):
            raise TaskStoreError(
                "close_dispatch_binding_projection_incomplete",
                "restore one exact role/session dispatch-binding projection before closing",
                role,
            )


def verify_claim_dispatch_state(
    *,
    cache_dir: Path,
    vault_root: Path,
    task_id: str,
    role: str,
    session_id: str,
    dispatch_message_id: str,
    platform: str,
    mode: str,
    profile: str,
    authority_case: str,
    binding_hash: str,
    idempotency_key: str,
    parent_spec: str,
    parent_spec_sha256: str,
) -> ClaimDispatchBinding:
    """Verify one already-published claim against its exact dispatch environment."""

    keys = [role]
    if session_id:
        keys.append(f"{role}-{session_id}")
    bindings: list[ClaimDispatchBinding] = []
    for key in keys:
        binding = load_claim_dispatch_binding(claim_dispatch_binding_path(cache_dir, key))
        claim_task = _read_regular_text(
            cache_dir / f"cc-active-task-{key}",
            reason_code="claim_dispatch_claim_cache_unreadable",
        ).strip()
        epoch_parts = _read_regular_text(
            cache_dir / f"cc-claim-epoch-{key}",
            reason_code="claim_dispatch_epoch_unreadable",
        ).split()
        if (
            claim_task != task_id
            or len(epoch_parts) != 2
            or not epoch_parts[0].isdigit()
            or int(epoch_parts[0]) != binding.claim_epoch
            or epoch_parts[1] != task_id
        ):
            raise TaskStoreError(
                "claim_dispatch_projection_mismatch",
                "restore the claim, epoch, and dispatch sidecars as one projection",
                key,
            )
        bindings.append(binding)

    expected = (
        task_id,
        role,
        session_id,
        dispatch_message_id,
        platform,
        mode,
        profile,
        authority_case,
        binding_hash,
        idempotency_key,
    )
    for binding in bindings:
        observed = (
            binding.task_id,
            binding.lane,
            binding.session_id,
            binding.dispatch_message_id,
            binding.platform,
            binding.mode,
            binding.profile,
            binding.authority_case,
            binding.binding_hash,
            binding.coord_dispatch_idempotency_key or "",
        )
        if observed != expected or binding.receipt_hash != bindings[0].receipt_hash:
            raise TaskStoreError(
                "claim_dispatch_binding_identity_mismatch",
                "re-run the exact governed dispatch claim before launch",
                role,
            )

    snapshot = resolve_task_note(vault_root, task_id, state="active")
    status = str(snapshot.frontmatter.get("status") or "").strip().lower()
    owner = str(snapshot.frontmatter.get("assigned_to") or "").strip()
    observed_authority = str(snapshot.frontmatter.get("authority_case") or "").strip()
    observed_parent = str(snapshot.frontmatter.get("parent_spec") or "").strip()
    parent_path = Path(parent_spec).expanduser()
    if not parent_path.is_absolute():
        parent_path = Path.home() / "Documents" / "Personal" / parent_path
    try:
        if parent_path.is_symlink() or not parent_path.is_file():
            raise OSError("parent spec is not a regular non-symlink file")
        observed_parent_hash = hashlib.sha256(parent_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise TaskStoreError(
            "claim_dispatch_parent_spec_unreadable",
            "restore the exact parent-spec preimage before launch",
            str(parent_path),
        ) from exc
    if (
        status not in TASK_MUTABLE_STATUSES
        or not owner_matches(owner, role, platform)
        or observed_authority != authority_case
        or observed_parent != parent_spec
        or re.fullmatch(r"[0-9a-f]{64}", parent_spec_sha256) is None
        or observed_parent_hash != parent_spec_sha256
    ):
        raise TaskStoreError(
            "claim_dispatch_authoritative_state_mismatch",
            "re-run the governed claim against current task and parent-spec bytes",
            task_id,
        )
    return bindings[0]
