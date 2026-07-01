"""Durable append-only JSONL sink with per-stream SHA-256 chain anchors.

This is the Stage-0 primitive for receipt and evidence rows that must survive
reboot. It is deliberately stricter than advisory coordination ledgers: the
configured root must already exist on non-volatile storage, append failures
raise, and a partially written line is rolled back under the stream lock.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final = 1
GENESIS_HASH: Final = "0" * 64
VOLATILE_FS_TYPES: Final[frozenset[str]] = frozenset({"tmpfs", "ramfs"})
DEFAULT_ROOT_ENV: Final = "HAPAX_DURABLE_SINK_ROOT"
_STREAM_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")


class DurableSinkPathError(ValueError):
    """The configured durable sink path is absent or unsafe."""


class DurableSinkValueError(ValueError):
    """A row value cannot be safely encoded into the durable sink schema."""


class DurableSinkAppendError(RuntimeError):
    """A durable append did not complete successfully."""


class DurableSinkChainError(RuntimeError):
    """A stream file failed SHA-256 chain validation."""

    def __init__(self, result: ChainValidationResult) -> None:
        self.result = result
        detail = "; ".join(issue.message for issue in result.issues)
        super().__init__(detail or "durable sink chain validation failed")


@dataclass(frozen=True)
class DurableSinkRow:
    """One append-only sink row.

    ``row_hash`` is the SHA-256 digest of the canonical JSON row with
    ``row_hash`` omitted. ``prior_hash`` links to the previous row in the same
    stream, or :data:`GENESIS_HASH` for the first row.
    """

    schema_version: int
    timestamp: str
    stream_id: str
    data_class: str
    source_receipt_ref: str
    prior_hash: str
    row_hash: str
    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "stream_id": self.stream_id,
            "data_class": self.data_class,
            "source_receipt_ref": self.source_receipt_ref,
            "prior_hash": self.prior_hash,
            "row_hash": self.row_hash,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class ChainIssue:
    line_number: int | None
    code: str
    message: str


@dataclass(frozen=True)
class ChainValidationResult:
    valid: bool
    row_count: int
    tail_hash: str
    issues: tuple[ChainIssue, ...] = ()

    def raise_for_issues(self) -> None:
        if not self.valid:
            raise DurableSinkChainError(self)


def configured_durable_sink_root() -> Path:
    """Return the configured durable sink root without creating it."""

    return Path(
        os.environ.get(
            DEFAULT_ROOT_ENV,
            str(Path.home() / ".cache" / "hapax" / "stage0-durable-sink"),
        )
    )


def assert_durable_root(root: Path | str) -> Path:
    """Resolve and validate the configured durable sink root.

    The root must already exist, be a directory, and live on a filesystem that
    is not reported as tmpfs/ramfs. We fail closed when the mount type cannot be
    determined because a reboot-survival sink cannot assume persistence.
    """

    candidate = Path(root).expanduser()
    if not candidate.is_absolute():
        raise DurableSinkPathError(f"durable sink root must be absolute: {candidate}")
    if not candidate.exists():
        raise DurableSinkPathError(f"durable sink root is absent: {candidate}")
    if not candidate.is_dir():
        raise DurableSinkPathError(f"durable sink root is not a directory: {candidate}")

    resolved = candidate.resolve()
    fstype = _mount_fstype_for_path(resolved)
    if fstype is None:
        raise DurableSinkPathError(f"could not determine filesystem type for {resolved}")
    if fstype in VOLATILE_FS_TYPES:
        raise DurableSinkPathError(
            f"durable sink root is on volatile filesystem {fstype}: {resolved}"
        )
    if resolved.stat().st_mode & 0o002:
        raise DurableSinkPathError(f"durable sink root is world-writable: {resolved}")
    return resolved


@dataclass(frozen=True)
class DurableJsonlSink:
    """Append-only per-stream JSONL sink rooted in a durable directory."""

    root: Path

    def __init__(self, root: Path | str | None = None) -> None:
        object.__setattr__(
            self, "root", assert_durable_root(root or configured_durable_sink_root())
        )

    def path_for_stream(self, stream_id: str) -> Path:
        return self.root / _stream_filename(stream_id)

    def append(
        self,
        *,
        stream_id: str,
        data_class: str,
        source_receipt_ref: str,
        payload: Mapping[str, Any],
        timestamp: str | None = None,
    ) -> DurableSinkRow:
        """Append one chained row and return the committed envelope."""

        root = assert_durable_root(self.root)
        target = root / _stream_filename(stream_id)
        lock_fd = os.open(_lock_path(target), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            validation = validate_chain(target, stream_id=stream_id)
            validation.raise_for_issues()
            row = make_row(
                stream_id=stream_id,
                data_class=data_class,
                source_receipt_ref=source_receipt_ref,
                payload=payload,
                prior_hash=validation.tail_hash,
                timestamp=timestamp,
            )
            _append_row_locked(target, row)
            return row
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


def make_row(
    *,
    stream_id: str,
    data_class: str,
    source_receipt_ref: str,
    payload: Mapping[str, Any],
    prior_hash: str,
    timestamp: str | None = None,
) -> DurableSinkRow:
    """Build a canonical sink row and compute its ``row_hash``."""

    stream_id = _required_text(stream_id, "stream_id")
    _stream_filename(stream_id)
    data_class = _required_text(data_class, "data_class")
    source_receipt_ref = _required_text(source_receipt_ref, "source_receipt_ref")
    if not _is_sha256(prior_hash):
        raise DurableSinkValueError(f"prior_hash must be 64 lowercase hex chars: {prior_hash!r}")
    if not isinstance(payload, Mapping):
        raise DurableSinkValueError("payload must be a mapping")

    timestamp = _required_text(timestamp or _utc_now_iso(), "timestamp")
    payload_copy = _json_safe_copy(dict(payload), field_name="payload")
    material = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": timestamp,
        "stream_id": stream_id,
        "data_class": data_class,
        "source_receipt_ref": source_receipt_ref,
        "prior_hash": prior_hash,
        "payload": payload_copy,
    }
    row_hash = _hash_material(material)
    return DurableSinkRow(
        schema_version=SCHEMA_VERSION,
        timestamp=timestamp,
        stream_id=stream_id,
        data_class=data_class,
        source_receipt_ref=source_receipt_ref,
        prior_hash=prior_hash,
        row_hash=row_hash,
        payload=payload_copy,
    )


def validate_chain(
    path: Path | str,
    *,
    stream_id: str | None = None,
    expected_tail_hash: str | None = None,
    expected_count: int | None = None,
) -> ChainValidationResult:
    """Validate a durable stream file.

    ``expected_tail_hash`` is the external anchor for detecting tail deletion.
    Without an external tail anchor, any hash chain can detect missing middle
    rows, reordering, and row modification, but not silent truncation of the
    newest row.
    """

    target = Path(path)
    issues: list[ChainIssue] = []
    expected_prior = GENESIS_HASH
    row_count = 0

    if stream_id is not None:
        stream_id = _required_text(stream_id, "stream_id")
        _stream_filename(stream_id)

    if not target.exists():
        result = _result_with_expectation_checks(
            issues=issues,
            row_count=0,
            tail_hash=GENESIS_HASH,
            expected_tail_hash=expected_tail_hash,
            expected_count=expected_count,
        )
        return result
    if not target.is_file():
        issues.append(ChainIssue(None, "not_file", f"durable sink path is not a file: {target}"))
        return ChainValidationResult(False, 0, GENESIS_HASH, tuple(issues))

    with target.open("r", encoding="utf-8") as fh:
        for line_number, raw in enumerate(fh, 1):
            line = raw.rstrip("\n")
            if not line:
                issues.append(
                    ChainIssue(line_number, "blank_line", f"line {line_number}: blank row")
                )
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                issues.append(
                    ChainIssue(
                        line_number,
                        "invalid_json",
                        f"line {line_number}: invalid JSON: {exc.msg}",
                    )
                )
                continue
            if not isinstance(row, dict):
                issues.append(
                    ChainIssue(
                        line_number,
                        "not_object",
                        f"line {line_number}: row must be a JSON object",
                    )
                )
                continue

            row_count += 1
            claimed_hash = _validate_row(
                row=row,
                line_number=line_number,
                expected_prior=expected_prior,
                expected_stream_id=stream_id,
                issues=issues,
            )
            if claimed_hash is not None:
                expected_prior = claimed_hash

    return _result_with_expectation_checks(
        issues=issues,
        row_count=row_count,
        tail_hash=expected_prior,
        expected_tail_hash=expected_tail_hash,
        expected_count=expected_count,
    )


def _append_row_locked(target: Path, row: DurableSinkRow) -> None:
    blob = (_canonical_json(row.as_dict()) + "\n").encode("utf-8")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    start_offset = os.lseek(fd, 0, os.SEEK_END)
    try:
        try:
            _write_all(fd, blob)
            os.fsync(fd)
        except Exception as exc:
            _rollback_partial_append(fd, start_offset)
            raise DurableSinkAppendError(f"failed to append durable sink row to {target}") from exc
    finally:
        os.close(fd)
    _fsync_directory(target.parent)


def _write_all(fd: int, blob: bytes) -> None:
    view = memoryview(blob)
    written_total = 0
    while written_total < len(blob):
        written = os.write(fd, view[written_total:])
        if written <= 0:
            raise DurableSinkAppendError("os.write returned no progress")
        written_total += written


def _rollback_partial_append(fd: int, start_offset: int) -> None:
    try:
        os.ftruncate(fd, start_offset)
        os.fsync(fd)
    except OSError:
        pass


def _fsync_directory(path: Path) -> None:
    dir_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    except OSError as exc:
        raise DurableSinkAppendError(f"failed to fsync durable sink directory {path}") from exc
    finally:
        os.close(dir_fd)


def _validate_row(
    *,
    row: dict[str, Any],
    line_number: int,
    expected_prior: str,
    expected_stream_id: str | None,
    issues: list[ChainIssue],
) -> str | None:
    required = (
        "schema_version",
        "timestamp",
        "stream_id",
        "data_class",
        "source_receipt_ref",
        "prior_hash",
        "row_hash",
        "payload",
    )
    missing = [field for field in required if field not in row]
    if missing:
        issues.append(
            ChainIssue(
                line_number,
                "missing_field",
                f"line {line_number}: missing required field(s): {', '.join(missing)}",
            )
        )
        return None

    claimed_hash = row.get("row_hash")
    if not isinstance(claimed_hash, str) or not _is_sha256(claimed_hash):
        issues.append(
            ChainIssue(
                line_number,
                "invalid_row_hash",
                f"line {line_number}: row_hash must be 64 lowercase hex chars",
            )
        )
        claimed_hash = None

    prior_hash = row.get("prior_hash")
    if prior_hash != expected_prior:
        issues.append(
            ChainIssue(
                line_number,
                "prior_hash_mismatch",
                f"line {line_number}: prior_hash {prior_hash!r} != expected {expected_prior!r}",
            )
        )

    if expected_stream_id is not None and row.get("stream_id") != expected_stream_id:
        issues.append(
            ChainIssue(
                line_number,
                "stream_id_mismatch",
                f"line {line_number}: stream_id {row.get('stream_id')!r} "
                f"!= expected {expected_stream_id!r}",
            )
        )

    _validate_required_text(row, line_number, issues)
    if row.get("schema_version") != SCHEMA_VERSION:
        issues.append(
            ChainIssue(
                line_number,
                "schema_version_mismatch",
                f"line {line_number}: schema_version {row.get('schema_version')!r} "
                f"!= {SCHEMA_VERSION}",
            )
        )
    if not isinstance(row.get("payload"), dict):
        issues.append(
            ChainIssue(
                line_number, "invalid_payload", f"line {line_number}: payload must be an object"
            )
        )

    try:
        recomputed_hash = _hash_row_dict(row)
    except (TypeError, ValueError) as exc:
        issues.append(
            ChainIssue(
                line_number,
                "uncanonicalizable_row",
                f"line {line_number}: row cannot be canonicalized: {exc}",
            )
        )
        return claimed_hash

    if claimed_hash is not None and claimed_hash != recomputed_hash:
        issues.append(
            ChainIssue(
                line_number,
                "row_hash_mismatch",
                f"line {line_number}: row_hash {claimed_hash!r} != recomputed {recomputed_hash!r}",
            )
        )
    return claimed_hash


def _validate_required_text(
    row: dict[str, Any], line_number: int, issues: list[ChainIssue]
) -> None:
    for field in ("timestamp", "stream_id", "data_class", "source_receipt_ref"):
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                ChainIssue(
                    line_number,
                    "invalid_text_field",
                    f"line {line_number}: {field} must be a non-empty string",
                )
            )
    stream_id = row.get("stream_id")
    if isinstance(stream_id, str) and not _STREAM_ID_RE.fullmatch(stream_id):
        issues.append(
            ChainIssue(
                line_number,
                "invalid_stream_id",
                f"line {line_number}: stream_id has unsafe filename characters",
            )
        )


def _result_with_expectation_checks(
    *,
    issues: list[ChainIssue],
    row_count: int,
    tail_hash: str,
    expected_tail_hash: str | None,
    expected_count: int | None,
) -> ChainValidationResult:
    if expected_tail_hash is not None and tail_hash != expected_tail_hash:
        issues.append(
            ChainIssue(
                None,
                "tail_hash_mismatch",
                f"tail_hash {tail_hash!r} != expected {expected_tail_hash!r}",
            )
        )
    if expected_count is not None and row_count != expected_count:
        issues.append(
            ChainIssue(
                None,
                "row_count_mismatch",
                f"row_count {row_count} != expected {expected_count}",
            )
        )
    return ChainValidationResult(not issues, row_count, tail_hash, tuple(issues))


def _required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DurableSinkValueError(f"{field} must be a non-empty string")
    return value


def _stream_filename(stream_id: str) -> str:
    if not isinstance(stream_id, str) or not _STREAM_ID_RE.fullmatch(stream_id):
        raise DurableSinkValueError(
            "stream_id must start with an alphanumeric and contain only "
            "alphanumerics, '.', '_', ':', or '-'"
        )
    return f"{stream_id}.jsonl"


def _lock_path(target: Path) -> Path:
    return target.with_name(target.name + ".lock")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_safe_copy(value: Mapping[str, Any], *, field_name: str) -> dict[str, Any]:
    try:
        loaded = json.loads(_canonical_json(value))
    except (TypeError, ValueError) as exc:
        raise DurableSinkValueError(f"{field_name} must be canonical JSON encodable") from exc
    if not isinstance(loaded, dict):
        raise DurableSinkValueError(f"{field_name} must encode to a JSON object")
    return loaded


def _hash_material(material: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(material).encode("utf-8")).hexdigest()


def _hash_row_dict(row: Mapping[str, Any]) -> str:
    material = dict(row)
    material.pop("row_hash", None)
    return _hash_material(material)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _mount_fstype_for_path(path: Path) -> str | None:
    resolved = path.resolve()
    best_match: tuple[int, str] | None = None
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mount_point = Path(_decode_mount_field(parts[1]))
        try:
            mount_resolved = mount_point.resolve()
        except OSError:
            mount_resolved = mount_point
        if resolved == mount_resolved or resolved.is_relative_to(mount_resolved):
            match_len = len(str(mount_resolved))
            if best_match is None or match_len > best_match[0]:
                best_match = (match_len, parts[2])
    return None if best_match is None else best_match[1]


def _decode_mount_field(value: str) -> str:
    return (
        value.replace(r"\040", " ")
        .replace(r"\011", "\t")
        .replace(r"\012", "\n")
        .replace(r"\134", "\\")
    )
