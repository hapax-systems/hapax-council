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


def write_claim_dispatch_binding(
    cache_dir: Path,
    claim_key: str,
    binding: ClaimDispatchBinding,
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
