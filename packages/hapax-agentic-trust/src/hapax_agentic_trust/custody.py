# Read-only dependency-closure derivation from conservatory/evidence_store.py.
# upstream_sha256=8a553df116e4ea7c86aecd94b027d138477437116dbaa05f9dcf807fbdfe1643
# Only the dependency closure of the caller-pinned verification API is retained.

"""Read-only verification of content-addressed terminal-evidence custody.

This module parses an already-produced inventory and verifies every named local
object through a caller-held directory descriptor. Every walk is relative to
that descriptor, refuses symlinks, and checks exact content, size, mode,
link-count, and path binding. It contains no copy, write, seal, or publication
operation and cannot authorize a controller, model, tool, external action, or
local run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Final

from .errors import VerificationCustodyFailure, VerificationResourceLimitExceeded
from .limits import (
    DEFAULT_VERIFICATION_LIMITS,
    VerificationLimits,
    validate_json_resource_envelope,
    validate_relative_path_resource,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

EVIDENCE_INVENTORY_SCHEMA_VERSION: Final = 1

HASH_ALGORITHM: Final = "sha256"

OBJECT_LAYOUT: Final = "objects/sha256/{first_two_hex}/{sha256}"

AUTHORITY_STATUS: Final = "evidence_only_not_authorized"

READ_SIZE: Final = 1024 * 1024

SHA_RE: Final = re.compile(r"^[0-9a-f]{64}$")


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _canonical_compact_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _canonical_compact_sha256(document: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_compact_bytes(document)).hexdigest()


def _validate_sha256(name: str, value: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _validate_size(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _validate_relative_path(name: str, value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty canonical POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise ValueError(f"{name} must be canonical and relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{name} cannot contain empty, dot, or parent components")
    return path


def _object_relative_path(digest: str) -> str:
    _validate_sha256("object digest", digest)
    return f"objects/sha256/{digest[:2]}/{digest}"


def _inventory_relative_path(digest: str) -> str:
    _validate_sha256("inventory digest", digest)
    return f"inventories/sha256/{digest[:2]}/{digest}"


@dataclass(frozen=True, slots=True)
class EvidenceInventoryEntry:
    """One verified logical-path to content-addressed object mapping."""

    logical_path: str
    object_relative_path: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        _validate_relative_path("logical evidence path", self.logical_path)
        _validate_relative_path("object path", self.object_relative_path)
        _validate_sha256("object sha256", self.sha256)
        _validate_size("object size", self.size)
        if self.object_relative_path != _object_relative_path(self.sha256):
            raise ValueError("object path is not derived from its SHA-256 digest")

    def document(self) -> dict[str, Any]:
        return {
            "logical_path": self.logical_path,
            "object_relative_path": self.object_relative_path,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True, slots=True)
class EvidenceInventoryExpectation:
    """The terminal bundle's expected logical evidence projection."""

    logical_path: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        _validate_relative_path("expected logical evidence path", self.logical_path)
        _validate_sha256("expected evidence sha256", self.sha256)
        _validate_size("expected evidence size", self.size)


@dataclass(frozen=True, slots=True)
class SealedEvidenceInventory:
    """Canonical logical evidence inventory with an inner Merkle-style root."""

    encoded: bytes
    inventory_root_sha256: str
    sha256: str
    entries: tuple[EvidenceInventoryEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.encoded, bytes):
            raise TypeError("inventory encoding must be bytes")
        _validate_sha256("inventory root sha256", self.inventory_root_sha256)
        _validate_sha256("inventory encoded sha256", self.sha256)
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ValueError("inventory must contain at least one evidence entry")
        if any(not isinstance(entry, EvidenceInventoryEntry) for entry in self.entries):
            raise TypeError("inventory entries must be EvidenceInventoryEntry values")
        validated = _validate_inventory_bytes(self.encoded, limits=None)
        if validated.inventory_root_sha256 != self.inventory_root_sha256:
            raise ValueError("inventory root field mismatch")
        if validated.sha256 != self.sha256:
            raise ValueError("inventory encoded hash mismatch")
        if validated.entries != self.entries:
            raise ValueError("inventory entry field mismatch")

    @property
    def document(self) -> dict[str, Any]:
        document = json.loads(self.encoded)
        if not isinstance(document, dict):
            raise TypeError("validated inventory decoded to a non-object")
        return document

    @classmethod
    def build(
        cls,
        entries: Iterable[EvidenceInventoryEntry],
    ) -> SealedEvidenceInventory:
        values = tuple(entries)
        _validate_inventory_entries(values)
        core = {
            "authority_status": AUTHORITY_STATUS,
            "entries": [entry.document() for entry in values],
            "hash_algorithm": HASH_ALGORITHM,
            "may_authorize_external_action": False,
            "object_layout": OBJECT_LAYOUT,
            "schema_version": EVIDENCE_INVENTORY_SCHEMA_VERSION,
        }
        inventory_root_sha256 = _canonical_compact_sha256(core)
        encoded = _canonical_bytes({**core, "inventory_root_sha256": inventory_root_sha256})
        return cls(
            encoded=encoded,
            inventory_root_sha256=inventory_root_sha256,
            sha256=hashlib.sha256(encoded).hexdigest(),
            entries=values,
        )

    @classmethod
    def from_bytes(
        cls,
        raw: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> SealedEvidenceInventory:
        validated = _validate_inventory_bytes(raw, limits=limits)
        return cls(
            encoded=raw,
            inventory_root_sha256=validated.inventory_root_sha256,
            sha256=validated.sha256,
            entries=validated.entries,
        )


@dataclass(frozen=True, slots=True)
class _ValidatedInventory:
    inventory_root_sha256: str
    sha256: str
    entries: tuple[EvidenceInventoryEntry, ...]


def _validate_inventory_entries(
    entries: tuple[EvidenceInventoryEntry, ...],
) -> None:
    if not entries:
        raise ValueError("inventory must contain at least one evidence entry")
    if any(not isinstance(entry, EvidenceInventoryEntry) for entry in entries):
        raise TypeError("inventory entries must be EvidenceInventoryEntry values")
    logical_paths = [entry.logical_path for entry in entries]
    if logical_paths != sorted(logical_paths):
        raise ValueError("inventory entries must be canonically ordered by logical path")
    if len(logical_paths) != len(set(logical_paths)):
        raise ValueError("inventory logical paths must be unique")


def _validate_inventory_bytes(
    raw: bytes,
    *,
    limits: VerificationLimits | None,
) -> _ValidatedInventory:
    if not isinstance(raw, bytes):
        raise TypeError("inventory encoding must be bytes")
    if limits is not None and not isinstance(limits, VerificationLimits):
        raise TypeError("limits must be a VerificationLimits value or None")
    if limits is not None and len(raw) > limits.inventory_bytes:
        raise VerificationResourceLimitExceeded(
            f"inventory exceeds inventory_bytes={limits.inventory_bytes}; "
            "next action: split the evidence into independently verified inventories"
        )
    if limits is not None:
        validate_json_resource_envelope(
            raw,
            label="evidence inventory",
            limits=limits,
        )
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("inventory is not valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise TypeError("inventory must be a JSON object")
    expected_fields = {
        "authority_status",
        "entries",
        "hash_algorithm",
        "inventory_root_sha256",
        "may_authorize_external_action",
        "object_layout",
        "schema_version",
    }
    if set(document) != expected_fields:
        raise ValueError("inventory has unknown or missing top-level fields")
    if (
        isinstance(document["schema_version"], bool)
        or not isinstance(document["schema_version"], int)
        or document["schema_version"] != EVIDENCE_INVENTORY_SCHEMA_VERSION
    ):
        raise ValueError("inventory schema_version mismatch")
    if document["hash_algorithm"] != HASH_ALGORITHM:
        raise ValueError("inventory hash algorithm mismatch")
    if document["object_layout"] != OBJECT_LAYOUT:
        raise ValueError("inventory object layout mismatch")
    if document["authority_status"] != AUTHORITY_STATUS:
        raise ValueError("inventory cannot grant execution authority")
    if document["may_authorize_external_action"] is not False:
        raise ValueError("inventory cannot authorize external action")
    rows = document["entries"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("inventory entries must be a non-empty array")
    if limits is not None and len(rows) > limits.inventory_entries:
        raise VerificationResourceLimitExceeded(
            f"inventory exceeds inventory_entries={limits.inventory_entries}; "
            "next action: split the evidence into independently verified inventories"
        )
    entries: list[EvidenceInventoryEntry] = []
    expected_entry_fields = {
        "logical_path",
        "object_relative_path",
        "sha256",
        "size",
    }
    declared_total = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_entry_fields:
            raise ValueError("inventory entry has unknown or missing fields")
        if limits is not None:
            validate_relative_path_resource(
                row["logical_path"],
                label="logical evidence path",
                limits=limits,
            )
            validate_relative_path_resource(
                row["object_relative_path"],
                label="object path",
                limits=limits,
            )
            size = _validate_size("object size", row["size"])
            if size > limits.evidence_object_bytes:
                raise VerificationResourceLimitExceeded(
                    f"object size exceeds evidence_object_bytes={limits.evidence_object_bytes}; "
                    "next action: split the evidence object and inventory each part"
                )
            declared_total += size
            if declared_total > limits.total_evidence_bytes:
                raise VerificationResourceLimitExceeded(
                    f"inventory exceeds total_evidence_bytes={limits.total_evidence_bytes}; "
                    "next action: split the evidence into independently verified inventories"
                )
        entries.append(
            EvidenceInventoryEntry(
                logical_path=row["logical_path"],
                object_relative_path=row["object_relative_path"],
                sha256=row["sha256"],
                size=row["size"],
            )
        )
    values = tuple(entries)
    _validate_inventory_entries(values)
    root = _validate_sha256(
        "inventory_root_sha256",
        document["inventory_root_sha256"],
    )
    core = {key: value for key, value in document.items() if key != "inventory_root_sha256"}
    if _canonical_compact_sha256(core) != root:
        raise ValueError("inventory root digest mismatch")
    if _canonical_bytes(document) != raw:
        raise ValueError("inventory is not canonical JSON")
    return _ValidatedInventory(root, hashlib.sha256(raw).hexdigest(), values)


def _open_parent_directory(root_fd: int, relative_path: str) -> tuple[int, str]:
    relative = _validate_relative_path("evidence path", relative_path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    directory_fd = os.dup(root_fd)
    try:
        for part in relative.parts[:-1]:
            try:
                child_fd = os.open(part, flags, dir_fd=directory_fd)
            except OSError as exc:
                raise VerificationCustodyFailure(
                    f"evidence path parent is absent, non-directory, or a symlink: {relative_path}"
                ) from exc
            os.close(directory_fd)
            directory_fd = child_fd
        return directory_fd, relative.parts[-1]
    except Exception:
        os.close(directory_fd)
        raise


def _stable_stat_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _observe_named_regular_file(
    parent_fd: int,
    name: str,
    *,
    display_name: str,
    retain_bytes: bool,
    max_bytes: int,
) -> tuple[str, int, int, int, bytes | None]:
    try:
        path_before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise VerificationCustodyFailure(f"stored object is absent: {display_name}") from exc
    if stat.S_ISLNK(path_before.st_mode) or not stat.S_ISREG(path_before.st_mode):
        raise VerificationCustodyFailure(f"stored object is not a regular file: {display_name}")
    if path_before.st_size > max_bytes:
        raise VerificationResourceLimitExceeded(
            f"stored object exceeds max_bytes={max_bytes}: {display_name}; "
            "next action: split the evidence object before verification"
        )
    try:
        fd = os.open(
            name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise VerificationCustodyFailure(
            f"stored object is absent or a forbidden symlink: {display_name}"
        ) from exc
    try:
        opened = os.fstat(fd)
        if (path_before.st_dev, path_before.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise VerificationCustodyFailure(f"stored object changed while opening: {display_name}")
        if opened.st_size > max_bytes:
            raise VerificationResourceLimitExceeded(
                f"stored object exceeds max_bytes={max_bytes}: {display_name}; "
                "next action: split the evidence object before verification"
            )
        digest = hashlib.sha256()
        retained: list[bytes] | None = [] if retain_bytes else None
        observed_size = 0
        while True:
            chunk = os.read(fd, READ_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            observed_size += len(chunk)
            if observed_size > max_bytes:
                raise VerificationResourceLimitExceeded(
                    f"stored object grew beyond max_bytes={max_bytes}: {display_name}; "
                    "next action: quarantine the mutable object and retry from immutable custody"
                )
            if retained is not None:
                retained.append(chunk)
        after = os.fstat(fd)
        if _stable_stat_identity(opened) != _stable_stat_identity(after):
            raise VerificationCustodyFailure(f"stored object changed while hashing: {display_name}")
        if observed_size != opened.st_size:
            raise VerificationCustodyFailure(
                f"stored object size changed while hashing: {display_name}"
            )
        path_after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(path_after.st_mode) or _stable_stat_identity(
            path_after
        ) != _stable_stat_identity(after):
            raise VerificationCustodyFailure(f"stored object path was replaced: {display_name}")
        raw = b"".join(retained) if retained is not None else None
        return (
            digest.hexdigest(),
            observed_size,
            stat.S_IMODE(opened.st_mode),
            opened.st_nlink,
            raw,
        )
    finally:
        os.close(fd)


def _verify_exact_stored_object(
    parent_fd: int,
    final_name: str,
    *,
    relative_path: str,
    expected_sha256: str,
    expected_size: int,
    max_bytes: int,
) -> bytes | None:
    digest, size, mode, link_count, raw = _observe_named_regular_file(
        parent_fd,
        final_name,
        display_name=relative_path,
        retain_bytes=False,
        max_bytes=max_bytes,
    )
    if digest != expected_sha256 or size != expected_size or mode != 0o400 or link_count != 1:
        detail = (
            f"expected digest={expected_sha256} size={expected_size} mode=0400 "
            f"links=1, observed digest={digest} size={size} mode={mode:04o} "
            f"links={link_count}"
        )
        raise VerificationCustodyFailure(f"custodied object failed verification: {detail}")
    return raw


def _validate_expected_projection(
    expected_entries: Iterable[EvidenceInventoryExpectation],
    *,
    expected_entry_count: int,
    limits: VerificationLimits,
) -> tuple[EvidenceInventoryExpectation, ...]:
    _validate_size("expected inventory entry count", expected_entry_count)
    if expected_entry_count < 1:
        raise ValueError("expected inventory entry count must be positive")
    if expected_entry_count > limits.inventory_entries:
        raise VerificationResourceLimitExceeded(
            "expected inventory entry count exceeds inventory_entries="
            f"{limits.inventory_entries}; "
            "next action: split the evidence into independently verified inventories"
        )
    values_list: list[EvidenceInventoryExpectation] = []
    for entry in expected_entries:
        if len(values_list) >= expected_entry_count:
            raise ValueError("expected_entries contains more rows than expected_entry_count")
        if not isinstance(entry, EvidenceInventoryExpectation):
            raise TypeError("expected_entries must contain EvidenceInventoryExpectation values")
        values_list.append(entry)
    if len(values_list) != expected_entry_count:
        raise ValueError("expected inventory entry count does not match expected_entries")
    values = tuple(values_list)
    values = tuple(sorted(values, key=lambda entry: entry.logical_path))
    logical_paths = [entry.logical_path for entry in values]
    if len(logical_paths) != len(set(logical_paths)):
        raise ValueError("expected logical evidence paths must be unique")
    for entry in values:
        validate_relative_path_resource(
            entry.logical_path,
            label="expected logical evidence path",
            limits=limits,
        )
        if entry.size > limits.evidence_object_bytes:
            raise VerificationResourceLimitExceeded(
                "expected evidence size exceeds evidence_object_bytes="
                f"{limits.evidence_object_bytes}; "
                "next action: split the evidence object and inventory each part"
            )
    if sum(entry.size for entry in values) > limits.total_evidence_bytes:
        raise VerificationResourceLimitExceeded(
            "expected projection exceeds total_evidence_bytes="
            f"{limits.total_evidence_bytes}; "
            "next action: split the evidence into independently verified inventories"
        )
    return values


def _verify_evidence_inventory_from_root_fd(
    root_fd: int,
    inventory_relative_path: str,
    *,
    expected_sha256: str | None = None,
    expected_root_sha256: str | None = None,
    expected_size: int | None = None,
    expected_entry_count: int | None = None,
    expected_entries: tuple[EvidenceInventoryExpectation, ...] | None = None,
    limits: VerificationLimits,
) -> SealedEvidenceInventory:
    validate_relative_path_resource(
        inventory_relative_path,
        label="inventory path",
        limits=limits,
    )
    relative = _validate_relative_path("inventory path", inventory_relative_path)
    if len(relative.parts) != 4 or relative.parts[:2] != ("inventories", "sha256"):
        raise ValueError("inventory path does not use the trusted inventory layout")
    digest = _validate_sha256("inventory path digest", relative.parts[-1])
    if relative.parts[-2] != digest[:2] or inventory_relative_path != (
        _inventory_relative_path(digest)
    ):
        raise ValueError("inventory path is not derived from its SHA-256 digest")
    if expected_sha256 is not None:
        _validate_sha256("expected inventory sha256", expected_sha256)
        if expected_sha256 != digest:
            raise ValueError("inventory path digest does not match the expected digest")
    if expected_root_sha256 is not None:
        _validate_sha256("expected inventory root sha256", expected_root_sha256)
    if expected_size is not None:
        _validate_size("expected inventory size", expected_size)
        if expected_size > limits.inventory_bytes:
            raise VerificationResourceLimitExceeded(
                "expected inventory size exceeds inventory_bytes="
                f"{limits.inventory_bytes}; "
                "next action: split the evidence into independently verified inventories"
            )
    if expected_entry_count is not None:
        _validate_size("expected inventory entry count", expected_entry_count)
        if expected_entry_count > limits.inventory_entries:
            raise VerificationResourceLimitExceeded(
                "expected inventory entry count exceeds inventory_entries="
                f"{limits.inventory_entries}; "
                "next action: split the evidence into independently verified inventories"
            )
    root_before = os.fstat(root_fd)
    if not stat.S_ISDIR(root_before.st_mode):
        raise VerificationCustodyFailure("evidence-store root fd must refer to a directory")

    inventory_parent_fd, inventory_name = _open_parent_directory(
        root_fd,
        inventory_relative_path,
    )
    try:
        observed_digest, size, mode, links, raw = _observe_named_regular_file(
            inventory_parent_fd,
            inventory_name,
            display_name=inventory_relative_path,
            retain_bytes=True,
            max_bytes=limits.inventory_bytes,
        )
    finally:
        os.close(inventory_parent_fd)
    if observed_digest != digest or mode != 0o400 or links != 1 or raw is None or size != len(raw):
        raise VerificationCustodyFailure("custodied inventory object failed verification")
    if expected_size is not None and size != expected_size:
        raise VerificationCustodyFailure("inventory size does not match the expected size")
    inventory = SealedEvidenceInventory.from_bytes(raw, limits=limits)
    if expected_root_sha256 is not None and (
        inventory.inventory_root_sha256 != expected_root_sha256
    ):
        raise VerificationCustodyFailure("inventory root does not match the expected root")
    if expected_entry_count is not None and (len(inventory.entries) != expected_entry_count):
        raise VerificationCustodyFailure("inventory entry count does not match the expected count")
    if expected_entries is not None:
        observed_projection = tuple(
            (entry.logical_path, entry.sha256, entry.size) for entry in inventory.entries
        )
        expected_projection = tuple(
            (entry.logical_path, entry.sha256, entry.size) for entry in expected_entries
        )
        if observed_projection != expected_projection:
            raise VerificationCustodyFailure("inventory expected-entry projection mismatch")
    for entry in inventory.entries:
        object_parent_fd, object_name = _open_parent_directory(
            root_fd,
            entry.object_relative_path,
        )
        try:
            _verify_exact_stored_object(
                object_parent_fd,
                object_name,
                relative_path=entry.object_relative_path,
                expected_sha256=entry.sha256,
                expected_size=entry.size,
                max_bytes=limits.evidence_object_bytes,
            )
        finally:
            os.close(object_parent_fd)
    # Rewalk every named path from the held root after the first complete pass.
    # A descriptor to a detached parent is not proof that the current path still
    # names that parent; the second pass closes that replacement window before
    # returning custody as verified.
    rebound_parent_fd, rebound_name = _open_parent_directory(
        root_fd,
        inventory_relative_path,
    )
    try:
        rebound_digest, rebound_size, rebound_mode, rebound_links, _ = _observe_named_regular_file(
            rebound_parent_fd,
            rebound_name,
            display_name=inventory_relative_path,
            retain_bytes=False,
            max_bytes=limits.inventory_bytes,
        )
    finally:
        os.close(rebound_parent_fd)
    if (
        rebound_digest != digest
        or rebound_size != size
        or rebound_mode != 0o400
        or rebound_links != 1
    ):
        raise VerificationCustodyFailure("inventory path was rebound during verification")
    for entry in inventory.entries:
        rebound_parent_fd, rebound_name = _open_parent_directory(
            root_fd,
            entry.object_relative_path,
        )
        try:
            _verify_exact_stored_object(
                rebound_parent_fd,
                rebound_name,
                relative_path=entry.object_relative_path,
                expected_sha256=entry.sha256,
                expected_size=entry.size,
                max_bytes=limits.evidence_object_bytes,
            )
        finally:
            os.close(rebound_parent_fd)
    root_after = os.fstat(root_fd)
    if not stat.S_ISDIR(root_after.st_mode) or (
        root_before.st_dev,
        root_before.st_ino,
    ) != (root_after.st_dev, root_after.st_ino):
        raise VerificationCustodyFailure("evidence-store root fd changed during verification")
    return inventory


def verify_evidence_inventory_with_root_fd(
    root_fd: int,
    inventory_relative_path: str,
    *,
    expected_sha256: str,
    expected_root_sha256: str,
    expected_size: int,
    expected_entry_count: int,
    expected_entries: Iterable[EvidenceInventoryExpectation],
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> SealedEvidenceInventory:
    """Verify inventory and objects through a borrowed, already-held root fd.

    The descriptor is never closed or path-reopened.  A private duplicate is
    held for the complete verification.  ``expected_entries`` is the exact
    terminal artifact projection excluding the inventory artifact itself.
    """

    if isinstance(root_fd, bool) or not isinstance(root_fd, int):
        raise TypeError("evidence-store root fd must be an integer")
    if root_fd < 0:
        raise VerificationCustodyFailure("evidence-store root fd cannot be negative")
    if not isinstance(limits, VerificationLimits):
        raise TypeError("limits must be a VerificationLimits value")
    _validate_sha256("expected inventory sha256", expected_sha256)
    _validate_sha256("expected inventory root sha256", expected_root_sha256)
    _validate_size("expected inventory size", expected_size)
    if expected_size > limits.inventory_bytes:
        raise VerificationResourceLimitExceeded(
            "expected inventory size exceeds inventory_bytes="
            f"{limits.inventory_bytes}; "
            "next action: split the evidence into independently verified inventories"
        )
    projection = _validate_expected_projection(
        expected_entries,
        expected_entry_count=expected_entry_count,
        limits=limits,
    )
    try:
        owned_fd = os.dup(root_fd)
    except OSError as exc:
        raise VerificationCustodyFailure("evidence-store root fd is not open") from exc
    try:
        return _verify_evidence_inventory_from_root_fd(
            owned_fd,
            inventory_relative_path,
            expected_sha256=expected_sha256,
            expected_root_sha256=expected_root_sha256,
            expected_size=expected_size,
            expected_entry_count=expected_entry_count,
            expected_entries=projection,
            limits=limits,
        )
    finally:
        os.close(owned_fd)


def load_evidence_inventory_with_root_fd(
    root_fd: int,
    inventory_relative_path: str,
    *,
    expected_sha256: str,
    expected_root_sha256: str,
    expected_size: int,
    expected_entry_count: int,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> SealedEvidenceInventory:
    """Load a fully verified inventory from an already-held store root.

    This is the bootstrap half of terminal closure.  It validates the encoded
    inventory, every object it names, and all externally supplied inventory
    pins before a caller has an exact logical projection to compare.  Callers
    must subsequently reconcile the returned entries to their independent
    receipt or terminal projection; this function deliberately does not treat
    the inventory as self-authorizing evidence of completeness.
    """

    if isinstance(root_fd, bool) or not isinstance(root_fd, int):
        raise TypeError("evidence-store root fd must be an integer")
    if root_fd < 0:
        raise VerificationCustodyFailure("evidence-store root fd cannot be negative")
    if not isinstance(limits, VerificationLimits):
        raise TypeError("limits must be a VerificationLimits value")
    _validate_sha256("expected inventory sha256", expected_sha256)
    _validate_sha256("expected inventory root sha256", expected_root_sha256)
    _validate_size("expected inventory size", expected_size)
    _validate_size("expected inventory entry count", expected_entry_count)
    if expected_size > limits.inventory_bytes:
        raise VerificationResourceLimitExceeded(
            "expected inventory size exceeds inventory_bytes="
            f"{limits.inventory_bytes}; "
            "next action: split the evidence into independently verified inventories"
        )
    if expected_entry_count > limits.inventory_entries:
        raise VerificationResourceLimitExceeded(
            "expected inventory entry count exceeds inventory_entries="
            f"{limits.inventory_entries}; "
            "next action: split the evidence into independently verified inventories"
        )
    if expected_entry_count < 1:
        raise ValueError("expected inventory entry count must be positive")
    try:
        owned_fd = os.dup(root_fd)
    except OSError as exc:
        raise VerificationCustodyFailure("evidence-store root fd is not open") from exc
    try:
        return _verify_evidence_inventory_from_root_fd(
            owned_fd,
            inventory_relative_path,
            expected_sha256=expected_sha256,
            expected_root_sha256=expected_root_sha256,
            expected_size=expected_size,
            expected_entry_count=expected_entry_count,
            limits=limits,
        )
    finally:
        os.close(owned_fd)


def read_verified_evidence_object_with_root_fd(
    root_fd: int,
    entry: EvidenceInventoryEntry,
    *,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> bytes:
    """Read one content-addressed object through a borrowed evidence-store root fd.

    Terminal validators use this after exact inventory reconciliation so that
    semantic parsing reads the custodied object, not a mutable logical source
    path.  The object is nevertheless verified again during this read; a prior
    successful inventory check is not treated as a timeless capability.
    """

    if isinstance(root_fd, bool) or not isinstance(root_fd, int):
        raise TypeError("evidence-store root fd must be an integer")
    if root_fd < 0:
        raise VerificationCustodyFailure("evidence-store root fd cannot be negative")
    if not isinstance(entry, EvidenceInventoryEntry):
        raise TypeError("entry must be an EvidenceInventoryEntry")
    if not isinstance(limits, VerificationLimits):
        raise TypeError("limits must be a VerificationLimits value")
    validate_relative_path_resource(
        entry.object_relative_path,
        label="object path",
        limits=limits,
    )
    if entry.size > limits.evidence_object_bytes:
        raise VerificationResourceLimitExceeded(
            f"evidence object exceeds evidence_object_bytes={limits.evidence_object_bytes}; "
            "next action: split the evidence object before verification"
        )
    try:
        owned_fd = os.dup(root_fd)
    except OSError as exc:
        raise VerificationCustodyFailure("evidence-store root fd is not open") from exc
    try:
        root_before = os.fstat(owned_fd)
        if not stat.S_ISDIR(root_before.st_mode):
            raise VerificationCustodyFailure("evidence-store root fd must refer to a directory")
        parent_fd, final_name = _open_parent_directory(
            owned_fd,
            entry.object_relative_path,
        )
        try:
            digest, size, mode, links, raw = _observe_named_regular_file(
                parent_fd,
                final_name,
                display_name=entry.object_relative_path,
                retain_bytes=True,
                max_bytes=limits.evidence_object_bytes,
            )
        finally:
            os.close(parent_fd)
        if (
            digest != entry.sha256
            or size != entry.size
            or mode != 0o400
            or links != 1
            or raw is None
            or len(raw) != entry.size
        ):
            raise VerificationCustodyFailure(
                "custodied evidence object no longer matches its inventory entry"
            )
        rebound_parent_fd, rebound_name = _open_parent_directory(
            owned_fd,
            entry.object_relative_path,
        )
        try:
            _verify_exact_stored_object(
                rebound_parent_fd,
                rebound_name,
                relative_path=entry.object_relative_path,
                expected_sha256=entry.sha256,
                expected_size=entry.size,
                max_bytes=limits.evidence_object_bytes,
            )
        finally:
            os.close(rebound_parent_fd)
        root_after = os.fstat(owned_fd)
        if not stat.S_ISDIR(root_after.st_mode) or (
            root_before.st_dev,
            root_before.st_ino,
        ) != (root_after.st_dev, root_after.st_ino):
            raise VerificationCustodyFailure("evidence-store root fd changed during object read")
        return raw
    finally:
        os.close(owned_fd)
