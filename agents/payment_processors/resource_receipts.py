"""Governed resource receipts for receive-only money rails.

These receipts are private routing/resource evidence. They prove that a money
rail ingress, external API poll, payment-event append, or awareness-state write
was admitted into the governed resource calculus. They never grant spend
authority, public projection authority, perks, or customer-service obligations.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import sqlite3
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

log = logging.getLogger(__name__)

# Pure canonical fallback. The live ledger path is resolved at call time by
# ``default_receipt_log_path()`` from ``MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV``;
# this constant is only the /dev/shm fallback used when the env var is unset. It
# must NOT capture the environment at import, or a later env change would be
# ignored and patching this constant would appear to work while the resolver
# still read a stale import-time value. Bind isolation through the env contract.
DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH = Path(
    "/dev/shm/hapax-monetization/resource-receipts.jsonl"
)
MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV = "HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH"
MONEY_RAIL_RESOURCE_RECEIPT_SCHEMA_VERSION = 1
MONEY_RAIL_RESOURCE_RECEIPT_INDEX_SCHEMA_VERSION = 1
TASK_ID = "cc-task-money-rails-resource-receipt-ledger-20260630"
AUTHORITY_CASE = "CASE-CAPACITY-ROUTING-001"
RECEIPT_REF_PREFIX = "money-rail-resource-receipt:"
_SHA256_RE = r"^[a-f0-9]{64}$"
_EMPTY_FINAL_ROW_OFFSET = -1
_EMPTY_FINAL_ROW_LENGTH = 0
_EMPTY_FINAL_ROW_SHA256 = ""
_SQLITE_INDEX_ARTIFACT_SUFFIXES = ("-journal", "-wal", "-shm")
_LEDGER_PRIVATE_MODE = 0o600
_SQLITE_PRIVATE_MODE = 0o600
_RECEIPTS_TABLE_SQL = """
CREATE TABLE receipts (
    receipt_id TEXT NOT NULL PRIMARY KEY,
    row_offset INTEGER NOT NULL CHECK (typeof(row_offset) = 'integer' AND row_offset >= 0),
    row_length INTEGER NOT NULL CHECK (typeof(row_length) = 'integer' AND row_length > 0),
    rail TEXT NOT NULL CHECK (typeof(rail) = 'text' AND length(rail) > 0),
    raw_line_sha256 TEXT NOT NULL CHECK (
        typeof(raw_line_sha256) = 'text' AND length(raw_line_sha256) = 64
    ),
    stable_semantics_sha256 TEXT NOT NULL CHECK (
        typeof(stable_semantics_sha256) = 'text'
        AND length(stable_semantics_sha256) = 64
    )
)
""".strip()
_METADATA_TABLE_SQL = """
CREATE TABLE metadata (
    key TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL CHECK (typeof(value) = 'text')
)
""".strip()
_EXPECTED_RECEIPTS_TABLE_INFO = (
    (0, "receipt_id", "TEXT", 1, None, 1),
    (1, "row_offset", "INTEGER", 1, None, 0),
    (2, "row_length", "INTEGER", 1, None, 0),
    (3, "rail", "TEXT", 1, None, 0),
    (4, "raw_line_sha256", "TEXT", 1, None, 0),
    (5, "stable_semantics_sha256", "TEXT", 1, None, 0),
)
_EXPECTED_METADATA_TABLE_INFO = (
    (0, "key", "TEXT", 1, None, 1),
    (1, "value", "TEXT", 1, None, 0),
)
_EXPECTED_SQLITE_MASTER_OBJECTS = (
    ("table", "metadata", "metadata"),
    ("table", "receipts", "receipts"),
)

_lock = threading.Lock()


class MoneyRailResourceReceiptError(ValueError):
    """Raised when money-rail resource receipts are missing or malformed."""


class MoneyRailReceiptOperation(StrEnum):
    INGRESS = "ingress"
    EXTERNAL_API_POLL = "external_api_poll"
    PAYMENT_EVENT_APPEND = "payment_event_append"
    AWARENESS_STATE_WRITE = "awareness_state_write"


class MoneyRailResourceReceipt(BaseModel):
    """Private evidence receipt for one receive-only money-rail resource action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_schema: Literal[1] = MONEY_RAIL_RESOURCE_RECEIPT_SCHEMA_VERSION
    receipt_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    created_at: datetime
    task_id: Literal["cc-task-money-rails-resource-receipt-ledger-20260630"] = TASK_ID
    authority_case: Literal["CASE-CAPACITY-ROUTING-001"] = AUTHORITY_CASE
    rail: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    operation: MoneyRailReceiptOperation
    route_path: str | None = None
    external_id_sha256: str | None = Field(default=None, pattern=_SHA256_RE)
    event_kind: str | None = None
    raw_payload_sha256: str | None = Field(default=None, pattern=_SHA256_RE)
    downstream_action: str = Field(min_length=1)
    route_provenance: tuple[str, ...] = Field(default=())
    resource_provenance: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())
    receive_only: Literal[True] = True
    spend_authority_granted: Literal[False] = False
    provider_spend_authorized: Literal[False] = False
    public_projection_allowed: Literal[False] = False
    no_perk_or_relationship_granted: Literal[True] = True
    operator_visible_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def _evidence_matches_operation(self) -> Self:
        if self.operation is MoneyRailReceiptOperation.INGRESS:
            if not self.route_path:
                raise ValueError("ingress receipts require route_path")
            if not (self.external_id_sha256 or self.raw_payload_sha256):
                raise ValueError(
                    "ingress receipts require external_id_sha256 or raw_payload_sha256"
                )
        if self.operation is MoneyRailReceiptOperation.EXTERNAL_API_POLL:
            if not self.resource_provenance:
                raise ValueError("external API poll receipts require resource_provenance")
        if self.operation is MoneyRailReceiptOperation.AWARENESS_STATE_WRITE:
            if not self.resource_provenance:
                raise ValueError("awareness write receipts require resource_provenance")
        if self.spend_authority_granted or self.provider_spend_authorized:
            raise ValueError("money-rail resource receipts cannot grant spend authority")
        if self.public_projection_allowed:
            raise ValueError("money-rail resource receipts are private evidence, not public state")
        return self


def default_receipt_log_path() -> Path:
    """Resolve the receipt log path at call time for tests and services."""

    raw = os.environ.get(MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV)
    return Path(raw) if raw else DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH


def receipt_reference(receipt: MoneyRailResourceReceipt) -> str:
    return f"{RECEIPT_REF_PREFIX}{receipt.rail}:{receipt.receipt_id}"


def receipt_ref_from_id(rail: str, receipt_id: str) -> str:
    return f"{RECEIPT_REF_PREFIX}{rail}:{receipt_id}"


def resource_receipt_ref_present(refs: Iterable[str]) -> bool:
    return any(ref.startswith(RECEIPT_REF_PREFIX) for ref in refs)


def resource_receipt_refs(refs: Iterable[str]) -> tuple[str, ...]:
    return tuple(ref for ref in refs if ref.startswith(RECEIPT_REF_PREFIX))


def resource_receipt_recovery_guidance(*, log_path: Path | None = None) -> str:
    """Operator next action for missing, corrupt, or conflicting receipt evidence."""

    target = log_path if log_path is not None else default_receipt_log_path()
    index_path = _receipt_index_path(target)
    sqlite_artifacts = ", ".join(str(path) for path in _sqlite_artifact_paths(index_path))
    return (
        f"check {MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV}, receipt log {target}, "
        f"derived index {index_path}, SQLite artifacts {sqlite_artifacts}, sidecar lock "
        f"{_receipt_log_lock_path(target)}, /dev/shm availability, and receipt log permissions; "
        "if a full JSONL ledger stream validates, preserve or copy the JSONL unchanged, "
        "quarantine or rebuild only the derived index and SQLite artifacts, then retry; "
        "reserve ledger-row repair for independently proven ledger corruption such as a torn "
        "final line, malformed row, or conflicting receipt_id; when ledger corruption is proven, "
        "stop money-rail daemons, copy the log and lock sidecar for audit, repair or quarantine "
        "only the corrupt rows, preserve valid committed receipts, then retry"
    )


def build_resource_receipt(
    *,
    rail: str,
    operation: MoneyRailReceiptOperation,
    downstream_action: str,
    route_path: str | None = None,
    external_id: str | None = None,
    event_kind: str | None = None,
    raw_payload_sha256: str | None = None,
    route_provenance: Iterable[str] = (),
    resource_provenance: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    created_at: datetime | None = None,
) -> MoneyRailResourceReceipt:
    """Build a deterministic private receipt for a money-rail resource action."""

    when = _ensure_utc(created_at or datetime.now(UTC))
    external_id_sha256 = _sha256_text(external_id) if external_id else None
    receipt_id = _receipt_id(
        rail=rail,
        operation=operation,
        route_path=route_path,
        external_id_sha256=external_id_sha256,
        raw_payload_sha256=raw_payload_sha256,
        created_at=when,
    )
    evidence = list(evidence_refs)
    if raw_payload_sha256:
        evidence.append(f"raw-payload-sha256:{raw_payload_sha256}")
    if external_id_sha256:
        evidence.append(f"external-id-sha256:{external_id_sha256}")
    return MoneyRailResourceReceipt(
        receipt_id=receipt_id,
        created_at=when,
        rail=rail,
        operation=operation,
        route_path=route_path,
        external_id_sha256=external_id_sha256,
        event_kind=event_kind,
        raw_payload_sha256=raw_payload_sha256,
        downstream_action=downstream_action,
        route_provenance=tuple(dict.fromkeys(route_provenance)),
        resource_provenance=tuple(dict.fromkeys(resource_provenance)),
        evidence_refs=tuple(dict.fromkeys(evidence)),
        operator_visible_summary=(
            f"{operation.value} receipt for {rail}; downstream={downstream_action}; "
            "spend_authority=false"
        ),
    )


def append_resource_receipt(
    receipt: MoneyRailResourceReceipt,
    *,
    log_path: Path | None = None,
) -> bool:
    """Append one receipt idempotently; return True iff present afterward.

    The ledger is append-only admission evidence. The same stable receipt may be
    observed by multiple same-host processes and reuses the first row. A receipt
    id collision with different stable semantics fails closed instead of
    overwriting, retracting, or appending ambiguous evidence.
    """

    target = log_path if log_path is not None else default_receipt_log_path()
    line = (receipt.model_dump_json() + "\n").encode("utf-8")
    with _lock:
        try:
            operation_budget = _ReceiptIndexOperationBudget()
            with _locked_receipt_log(target):
                prior = _load_reconciled_indexed_receipt(
                    target,
                    create_ledger=True,
                    receipt_id=receipt.receipt_id,
                    operation_budget=operation_budget,
                )
                if prior is not None:
                    if _stable_receipt_semantics(prior) == _stable_receipt_semantics(receipt):
                        return True
                    log.warning(
                        "money-rail resource receipt append refused at %s: "
                        "conflicting stable semantics for receipt_id=%s; %s",
                        target,
                        receipt.receipt_id,
                        resource_receipt_recovery_guidance(log_path=target),
                    )
                    return False
                _append_line_durable(target, line)
                _ensure_reconciled_receipt_index(
                    target,
                    create_ledger=True,
                    operation_budget=operation_budget,
                )
        except (MoneyRailResourceReceiptError, OSError):
            log.warning(
                "money-rail resource receipt append failed at %s; %s",
                target,
                resource_receipt_recovery_guidance(log_path=target),
                exc_info=True,
            )
            return False
    return True


def tail_resource_receipts(
    *,
    limit: int = 200,
    log_path: Path | None = None,
) -> list[MoneyRailResourceReceipt]:
    target = log_path if log_path is not None else default_receipt_log_path()
    if not target.exists():
        return []
    tail: deque[MoneyRailResourceReceipt] = deque(maxlen=limit)
    try:
        for row in _iter_ledger_receipt_rows(target, start_offset=0, fail_closed=False):
            tail.append(row.receipt)
    except OSError:
        log.warning(
            "money-rail resource receipt read failed at %s; %s",
            target,
            resource_receipt_recovery_guidance(log_path=target),
            exc_info=True,
        )
        return []
    return list(tail)


def resource_receipt_exists(ref: str, *, log_path: Path | None = None) -> bool:
    return load_resource_receipt(ref, log_path=log_path) is not None


def load_resource_receipt(
    ref: str, *, log_path: Path | None = None
) -> MoneyRailResourceReceipt | None:
    try:
        _prefix, rail, receipt_id = ref.split(":", 2)
    except ValueError:
        return None
    if _prefix != RECEIPT_REF_PREFIX.rstrip(":"):
        return None
    target = log_path if log_path is not None else default_receipt_log_path()
    try:
        with _lock:
            operation_budget = _ReceiptIndexOperationBudget()
            with _locked_receipt_log(target):
                receipt = _load_reconciled_indexed_receipt(
                    target,
                    create_ledger=False,
                    receipt_id=receipt_id,
                    expected_rail=rail,
                    operation_budget=operation_budget,
                )
    except (MoneyRailResourceReceiptError, OSError):
        log.warning(
            "money-rail resource receipt admission lookup failed at %s; %s",
            target,
            resource_receipt_recovery_guidance(log_path=target),
            exc_info=True,
        )
        return None
    if receipt is not None and receipt.rail == rail:
        return receipt
    return None


def resource_receipt_matches(
    ref: str,
    *,
    rail: str,
    operation: MoneyRailReceiptOperation,
    external_id: str | None = None,
    log_path: Path | None = None,
) -> bool:
    """Return True only when ``ref`` points at the expected receipt provenance."""

    receipt = load_resource_receipt(ref, log_path=log_path)
    if receipt is None:
        return False
    if receipt.rail != rail or receipt.operation is not operation:
        return False
    if external_id is None:
        return True
    return receipt.external_id_sha256 == _sha256_text(external_id)


def require_resource_receipt(ref: str, *, log_path: Path | None = None) -> None:
    if not resource_receipt_exists(ref, log_path=log_path):
        raise MoneyRailResourceReceiptError(
            f"missing money-rail resource receipt: {ref}; "
            f"{resource_receipt_recovery_guidance(log_path=log_path)}"
        )


def record_ingress_resource_receipt(
    *,
    rail: str,
    route_path: str,
    external_id: str | None,
    event_kind: str | None,
    raw_payload_sha256: str | None,
    downstream_action: str,
    log_path: Path | None = None,
) -> str | None:
    receipt = build_resource_receipt(
        rail=rail,
        operation=MoneyRailReceiptOperation.INGRESS,
        route_path=route_path,
        external_id=external_id,
        event_kind=event_kind,
        raw_payload_sha256=raw_payload_sha256,
        downstream_action=downstream_action,
        route_provenance=(
            "route:logos.api.routes.payment_rails",
            f"route_path:{route_path}",
            f"authority_case:{AUTHORITY_CASE}",
        ),
        resource_provenance=("resource:receive_only_money_rail",),
    )
    return _append_and_ref(receipt, log_path=log_path)


def record_external_api_poll_receipt(
    *,
    rail: str,
    endpoint: str,
    downstream_action: str,
    log_path: Path | None = None,
) -> str | None:
    receipt = build_resource_receipt(
        rail=rail,
        operation=MoneyRailReceiptOperation.EXTERNAL_API_POLL,
        external_id=f"{endpoint}:{datetime.now(UTC).isoformat()}",
        downstream_action=downstream_action,
        route_provenance=(
            "route:agents.payment_processors",
            f"authority_case:{AUTHORITY_CASE}",
        ),
        resource_provenance=(f"external_api:{endpoint}", "resource:polling_daemon"),
    )
    return _append_and_ref(receipt, log_path=log_path)


def record_payment_event_resource_receipt(
    *,
    rail: str,
    external_id: str | None,
    event_kind: str,
    downstream_action: str,
    log_path: Path | None = None,
) -> str | None:
    _ref, receipt = prepare_payment_event_resource_receipt(
        rail=rail,
        external_id=external_id,
        event_kind=event_kind,
        downstream_action=downstream_action,
    )
    return _append_and_ref(receipt, log_path=log_path)


def prepare_payment_event_resource_receipt(
    *,
    rail: str,
    external_id: str | None,
    event_kind: str,
    downstream_action: str,
) -> tuple[str, MoneyRailResourceReceipt]:
    """Build a payment-event receipt ref before committing the receipt.

    Receive rails use this to commit a durable receipt before writing the event
    with that ref. Once committed, receipts are append-only: failed downstream
    writes leave the deterministic receipt in place so duplicate workers cannot
    delete evidence that another successful worker already referenced.
    """

    receipt = build_resource_receipt(
        rail=rail,
        operation=MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
        external_id=external_id,
        event_kind=event_kind,
        downstream_action=downstream_action,
        route_provenance=(
            "route:agents.payment_processors.event_log",
            f"authority_case:{AUTHORITY_CASE}",
        ),
        resource_provenance=("resource:payment_event_log",),
    )
    return receipt_reference(receipt), receipt


def commit_prepared_resource_receipt(
    receipt: MoneyRailResourceReceipt,
    *,
    log_path: Path | None = None,
) -> str | None:
    return _append_and_ref(receipt, log_path=log_path)


def retract_prepared_resource_receipt(
    receipt: MoneyRailResourceReceipt,
    *,
    log_path: Path | None = None,
) -> bool:
    """Compatibility hook; committed money-rail receipts are never removed."""

    _ = receipt, log_path
    return True


def record_awareness_write_resource_receipt(
    *,
    state_path: Path,
    source_log_path: Path,
    receipt_count: int,
    source_window_sha256: str | None = None,
    route_source: str = "agents.payment_processors.monetization_aggregator",
    log_path: Path | None = None,
) -> str | None:
    _ref, receipt = prepare_awareness_write_resource_receipt(
        state_path=state_path,
        source_log_path=source_log_path,
        receipt_count=receipt_count,
        source_window_sha256=source_window_sha256,
        route_source=route_source,
    )
    return _append_and_ref(receipt, log_path=log_path)


def prepare_awareness_write_resource_receipt(
    *,
    state_path: Path,
    source_log_path: Path,
    receipt_count: int,
    source_window_sha256: str | None = None,
    route_source: str = "agents.payment_processors.monetization_aggregator",
) -> tuple[str, MoneyRailResourceReceipt]:
    provenance = [
        f"awareness_state_path:{state_path}",
        f"payment_event_log:{source_log_path}",
        f"receipt_count:{receipt_count}",
    ]
    if source_window_sha256:
        provenance.append(f"payment_event_window_sha256:{source_window_sha256}")
    receipt = build_resource_receipt(
        rail="awareness",
        operation=MoneyRailReceiptOperation.AWARENESS_STATE_WRITE,
        external_id=f"{state_path}:{datetime.now(UTC).isoformat()}",
        downstream_action="operator_awareness.write_state_atomic",
        route_provenance=(
            f"route:{route_source}",
            f"authority_case:{AUTHORITY_CASE}",
        ),
        resource_provenance=provenance,
    )
    return receipt_reference(receipt), receipt


def _append_and_ref(
    receipt: MoneyRailResourceReceipt,
    *,
    log_path: Path | None = None,
) -> str | None:
    if not append_resource_receipt(receipt, log_path=log_path):
        return None
    return receipt_reference(receipt)


@dataclass(frozen=True)
class _LedgerReceiptRow:
    receipt: MoneyRailResourceReceipt
    row_offset: int
    row_length: int
    raw_line_sha256: str
    stable_semantics_sha256: str


@dataclass(frozen=True)
class _ReceiptIndexMetadata:
    ledger_st_dev: int
    ledger_st_ino: int
    verified_size: int
    line_count: int
    final_row_offset: int
    final_row_length: int
    final_row_sha256: str


@dataclass
class _ReceiptIndexOperationBudget:
    full_stream_replacement_spent: bool = False


class _ReceiptIndexRebuildRequired(Exception):
    """Raised when the derived index is corrupt or schema-incompatible."""


def _receipt_index_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.index.sqlite3")


def _open_reconciled_receipt_index_once(
    target: Path,
    *,
    create_ledger: bool,
    operation_budget: _ReceiptIndexOperationBudget,
) -> sqlite3.Connection | None:
    index_path = _receipt_index_path(target)
    if not target.exists():
        if index_path.exists():
            raise MoneyRailResourceReceiptError(
                f"money-rail resource receipt index exists without ledger {target}; "
                f"{resource_receipt_recovery_guidance(log_path=target)}"
            )
        if not create_ledger:
            return None
        _create_empty_ledger(target)
    else:
        _ensure_private_authoritative_ledger_file(target)

    if not index_path.exists():
        _spend_receipt_index_replacement(
            target,
            operation_budget=operation_budget,
            reason="missing derived index",
        )

    conn: sqlite3.Connection | None = None
    try:
        conn = _connect_receipt_index(index_path)
        _reconcile_receipt_index(conn, target)
        return conn
    except Exception:
        if conn is not None:
            conn.close()
        raise


def _load_reconciled_indexed_receipt(
    target: Path,
    *,
    create_ledger: bool,
    receipt_id: str,
    expected_rail: str | None = None,
    operation_budget: _ReceiptIndexOperationBudget | None = None,
) -> MoneyRailResourceReceipt | None:
    budget = operation_budget or _ReceiptIndexOperationBudget()

    def _attempt() -> MoneyRailResourceReceipt | None:
        conn = _open_reconciled_receipt_index_once(
            target,
            create_ledger=create_ledger,
            operation_budget=budget,
        )
        if conn is None:
            return None
        try:
            return _load_indexed_receipt(
                conn,
                target,
                receipt_id=receipt_id,
                expected_rail=expected_rail,
            )
        finally:
            conn.close()

    return _run_receipt_index_operation_with_recovery(
        target,
        operation_budget=budget,
        operation_label="receipt lookup",
        attempt=_attempt,
    )


def _ensure_reconciled_receipt_index(
    target: Path,
    *,
    create_ledger: bool,
    operation_budget: _ReceiptIndexOperationBudget,
) -> None:
    def _attempt() -> None:
        conn = _open_reconciled_receipt_index_once(
            target,
            create_ledger=create_ledger,
            operation_budget=operation_budget,
        )
        if conn is not None:
            conn.close()

    _run_receipt_index_operation_with_recovery(
        target,
        operation_budget=operation_budget,
        operation_label="receipt index reconcile",
        attempt=_attempt,
    )


def _run_receipt_index_operation_with_recovery[T](
    target: Path,
    *,
    operation_budget: _ReceiptIndexOperationBudget,
    operation_label: str,
    attempt: Callable[[], T],
) -> T:
    try:
        return attempt()
    except (sqlite3.DatabaseError, _ReceiptIndexRebuildRequired) as exc:
        if operation_budget.full_stream_replacement_spent:
            raise MoneyRailResourceReceiptError(
                f"money-rail resource receipt index {operation_label} failed after one "
                f"full-stream rebuild at {target}; "
                f"{resource_receipt_recovery_guidance(log_path=target)}"
            ) from exc
        _spend_receipt_index_replacement(
            target,
            operation_budget=operation_budget,
            reason=f"{operation_label} failure",
        )
    except sqlite3.Error as exc:
        raise MoneyRailResourceReceiptError(
            f"money-rail resource receipt index {operation_label} failed with sqlite "
            f"resource error at {target}; {resource_receipt_recovery_guidance(log_path=target)}"
        ) from exc
    try:
        return attempt()
    except (sqlite3.DatabaseError, _ReceiptIndexRebuildRequired) as exc:
        raise MoneyRailResourceReceiptError(
            f"money-rail resource receipt index {operation_label} failed after one "
            f"full-stream rebuild at {target}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        ) from exc
    except sqlite3.Error as exc:
        raise MoneyRailResourceReceiptError(
            f"money-rail resource receipt index {operation_label} failed with sqlite "
            f"resource error after one full-stream rebuild at {target}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        ) from exc


def _spend_receipt_index_replacement(
    target: Path,
    *,
    operation_budget: _ReceiptIndexOperationBudget,
    reason: str,
) -> None:
    if operation_budget.full_stream_replacement_spent:
        raise MoneyRailResourceReceiptError(
            f"money-rail resource receipt index replacement budget exhausted after {reason} "
            f"at {target}; {resource_receipt_recovery_guidance(log_path=target)}"
        )
    operation_budget.full_stream_replacement_spent = True
    try:
        _replace_receipt_index_from_ledger(target)
    except (sqlite3.Error, _ReceiptIndexRebuildRequired) as exc:
        raise MoneyRailResourceReceiptError(
            f"money-rail resource receipt index replacement failed after {reason} at {target}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        ) from exc


def _create_empty_ledger(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _LEDGER_PRIVATE_MODE)
    try:
        _ensure_private_authoritative_ledger_fd(fd)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(target.parent)


def _connect_receipt_index(index_path: Path) -> sqlite3.Connection:
    _ensure_private_sqlite_file(index_path)
    conn = sqlite3.connect(index_path)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        conn.close()
        raise
    return conn


def _replace_receipt_index_from_ledger(target: Path) -> None:
    index_path = _receipt_index_path(target)
    tmp_path = target.with_name(f".{target.name}.index.sqlite3.tmp-{os.getpid()}")
    _discard_sqlite_file_set(tmp_path)
    conn = _connect_receipt_index(tmp_path)
    try:
        _create_receipt_index_schema(conn)
        metadata = _empty_index_metadata(target.stat())
        with conn:
            for row in _iter_ledger_receipt_rows(target, start_offset=0, fail_closed=True):
                metadata = _insert_or_validate_indexed_row(conn, target, metadata, row)
            _write_index_metadata(conn, metadata)
        _validate_receipt_index_replacement(conn, target)
        conn.close()
        _force_private_mode(tmp_path)
        _discard_sqlite_artifacts(tmp_path)
        _install_receipt_index_replacement(tmp_path, index_path)
    except Exception:
        conn.close()
        _discard_sqlite_file_set(tmp_path)
        raise


def _create_receipt_index_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(f"{_RECEIPTS_TABLE_SQL};\n{_METADATA_TABLE_SQL};")


def _reconcile_receipt_index(conn: sqlite3.Connection, target: Path) -> None:
    _ensure_receipt_index_schema(conn)
    metadata = _read_index_metadata(conn)
    _validate_index_metadata_anchor(conn, target, metadata)
    stat = target.stat()
    if stat.st_size == metadata.verified_size:
        return
    with conn:
        for row in _iter_ledger_receipt_rows(
            target,
            start_offset=metadata.verified_size,
            fail_closed=True,
        ):
            metadata = _insert_or_validate_indexed_row(conn, target, metadata, row)
        _write_index_metadata(conn, metadata)


def _ensure_receipt_index_schema(conn: sqlite3.Connection) -> None:
    objects = tuple(
        sorted(
            (object_type, name, tbl_name)
            for object_type, name, tbl_name in conn.execute(
                "SELECT type, name, tbl_name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            )
        )
    )
    if objects != _EXPECTED_SQLITE_MASTER_OBJECTS:
        raise _ReceiptIndexRebuildRequired
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT GLOB 'sqlite_*'"
        )
    }
    if tables != {"receipts", "metadata"}:
        raise _ReceiptIndexRebuildRequired
    if tuple(conn.execute("PRAGMA table_info(receipts)")) != _EXPECTED_RECEIPTS_TABLE_INFO:
        raise _ReceiptIndexRebuildRequired
    if tuple(conn.execute("PRAGMA table_info(metadata)")) != _EXPECTED_METADATA_TABLE_INFO:
        raise _ReceiptIndexRebuildRequired
    for table, expected_sql in (
        ("receipts", _RECEIPTS_TABLE_SQL),
        ("metadata", _METADATA_TABLE_SQL),
    ):
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if row is None or _normalize_sql(row[0]) != _normalize_sql(expected_sql):
            raise _ReceiptIndexRebuildRequired
        index_rows = list(conn.execute(f"PRAGMA index_list({table})"))
        if len(index_rows) != 1 or index_rows[0][2:] != (1, "pk", 0):
            raise _ReceiptIndexRebuildRequired
        indexed_columns = tuple(
            info[2] for info in conn.execute(f"PRAGMA index_info({index_rows[0][1]})")
        )
        if indexed_columns != (("receipt_id",) if table == "receipts" else ("key",)):
            raise _ReceiptIndexRebuildRequired


def _read_index_metadata(conn: sqlite3.Connection) -> _ReceiptIndexMetadata:
    rows: dict[str, str] = {}
    for key, value in conn.execute("SELECT key, value FROM metadata"):
        if not isinstance(key, str) or not isinstance(value, str):
            raise _ReceiptIndexRebuildRequired
        rows[key] = value
    try:
        schema_version = int(rows["schema_version"])
        if schema_version != MONEY_RAIL_RESOURCE_RECEIPT_INDEX_SCHEMA_VERSION:
            raise _ReceiptIndexRebuildRequired
        metadata = _ReceiptIndexMetadata(
            ledger_st_dev=int(rows["ledger_st_dev"]),
            ledger_st_ino=int(rows["ledger_st_ino"]),
            verified_size=int(rows["verified_size"]),
            line_count=int(rows["line_count"]),
            final_row_offset=int(rows["final_row_offset"]),
            final_row_length=int(rows["final_row_length"]),
            final_row_sha256=rows["final_row_sha256"],
        )
    except KeyError as exc:
        raise _ReceiptIndexRebuildRequired from exc
    except ValueError as exc:
        raise _ReceiptIndexRebuildRequired from exc
    if metadata.verified_size < 0 or metadata.line_count < 0:
        raise _ReceiptIndexRebuildRequired
    if metadata.line_count == 0:
        if (
            metadata.verified_size != 0
            or metadata.final_row_offset != _EMPTY_FINAL_ROW_OFFSET
            or metadata.final_row_length != _EMPTY_FINAL_ROW_LENGTH
            or metadata.final_row_sha256 != _EMPTY_FINAL_ROW_SHA256
        ):
            raise _ReceiptIndexRebuildRequired
    elif (
        metadata.final_row_offset < 0
        or metadata.final_row_length <= 0
        or metadata.final_row_offset + metadata.final_row_length != metadata.verified_size
    ):
        raise _ReceiptIndexRebuildRequired
    return metadata


def _write_index_metadata(
    conn: sqlite3.Connection,
    metadata: _ReceiptIndexMetadata,
) -> None:
    rows = {
        "schema_version": str(MONEY_RAIL_RESOURCE_RECEIPT_INDEX_SCHEMA_VERSION),
        "ledger_st_dev": str(metadata.ledger_st_dev),
        "ledger_st_ino": str(metadata.ledger_st_ino),
        "verified_size": str(metadata.verified_size),
        "line_count": str(metadata.line_count),
        "final_row_offset": str(metadata.final_row_offset),
        "final_row_length": str(metadata.final_row_length),
        "final_row_sha256": metadata.final_row_sha256,
    }
    conn.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        rows.items(),
    )


def _empty_index_metadata(stat: os.stat_result) -> _ReceiptIndexMetadata:
    return _ReceiptIndexMetadata(
        ledger_st_dev=stat.st_dev,
        ledger_st_ino=stat.st_ino,
        verified_size=0,
        line_count=0,
        final_row_offset=_EMPTY_FINAL_ROW_OFFSET,
        final_row_length=_EMPTY_FINAL_ROW_LENGTH,
        final_row_sha256=_EMPTY_FINAL_ROW_SHA256,
    )


def _validate_index_metadata_anchor(
    conn: sqlite3.Connection,
    target: Path,
    metadata: _ReceiptIndexMetadata,
) -> None:
    stat = target.stat()
    if stat.st_dev != metadata.ledger_st_dev or stat.st_ino != metadata.ledger_st_ino:
        raise MoneyRailResourceReceiptError(
            f"money-rail resource receipt index identity changed for {target}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        )
    if stat.st_size < metadata.verified_size:
        raise MoneyRailResourceReceiptError(
            f"money-rail resource receipt ledger truncated before verified index size "
            f"{metadata.verified_size} at {target}; {resource_receipt_recovery_guidance(log_path=target)}"
        )
    if metadata.line_count == 0:
        indexed_count = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
        if indexed_count != 0:
            raise _ReceiptIndexRebuildRequired
        return
    raw = _read_exact_ledger_row(
        target,
        row_offset=metadata.final_row_offset,
        row_length=metadata.final_row_length,
    )
    if not raw.endswith(b"\n") or _sha256_bytes(raw) != metadata.final_row_sha256:
        raise MoneyRailResourceReceiptError(
            f"money-rail resource receipt prior-tail anchor mismatch at {target}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        )


def _insert_or_validate_indexed_row(
    conn: sqlite3.Connection,
    target: Path,
    metadata: _ReceiptIndexMetadata,
    row: _LedgerReceiptRow,
) -> _ReceiptIndexMetadata:
    if row.row_offset != metadata.verified_size:
        raise MoneyRailResourceReceiptError(
            f"non-contiguous money-rail resource receipt row at byte {row.row_offset} "
            f"after verified size {metadata.verified_size}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        )
    prior = conn.execute(
        "SELECT stable_semantics_sha256 FROM receipts WHERE receipt_id = ?",
        (row.receipt.receipt_id,),
    ).fetchone()
    if prior is None:
        conn.execute(
            "INSERT INTO receipts("
            "receipt_id, row_offset, row_length, rail, raw_line_sha256, stable_semantics_sha256"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                row.receipt.receipt_id,
                row.row_offset,
                row.row_length,
                row.receipt.rail,
                row.raw_line_sha256,
                row.stable_semantics_sha256,
            ),
        )
    elif prior[0] != row.stable_semantics_sha256:
        raise MoneyRailResourceReceiptError(
            f"conflicting money-rail resource receipt rows for {row.receipt.receipt_id}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        )
    return _ReceiptIndexMetadata(
        ledger_st_dev=metadata.ledger_st_dev,
        ledger_st_ino=metadata.ledger_st_ino,
        verified_size=row.row_offset + row.row_length,
        line_count=metadata.line_count + 1,
        final_row_offset=row.row_offset,
        final_row_length=row.row_length,
        final_row_sha256=row.raw_line_sha256,
    )


def _load_indexed_receipt(
    conn: sqlite3.Connection,
    target: Path,
    *,
    receipt_id: str,
    expected_rail: str | None = None,
) -> MoneyRailResourceReceipt | None:
    row = conn.execute(
        "SELECT row_offset, row_length, rail, raw_line_sha256, stable_semantics_sha256 "
        "FROM receipts WHERE receipt_id = ?",
        (receipt_id,),
    ).fetchone()
    if row is None:
        return None
    row_offset, row_length, rail, raw_line_sha256, stable_semantics_sha256 = row
    if (
        not isinstance(row_offset, int)
        or isinstance(row_offset, bool)
        or row_offset < 0
        or not isinstance(row_length, int)
        or isinstance(row_length, bool)
        or row_length <= 0
        or not isinstance(rail, str)
        or not isinstance(raw_line_sha256, str)
        or len(raw_line_sha256) != 64
        or not isinstance(stable_semantics_sha256, str)
        or len(stable_semantics_sha256) != 64
    ):
        raise MoneyRailResourceReceiptError(
            f"malformed money-rail resource receipt index row for {receipt_id} at {target}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        )
    if expected_rail is not None and rail != expected_rail:
        return None
    raw = _read_exact_ledger_row(target, row_offset=row_offset, row_length=row_length)
    if not raw.endswith(b"\n") or _sha256_bytes(raw) != raw_line_sha256:
        raise MoneyRailResourceReceiptError(
            f"stale money-rail resource receipt locator for {receipt_id} at {target}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        )
    receipt = _parse_ledger_receipt_row(target, raw, line_number=None)
    if (
        receipt.receipt_id != receipt_id
        or receipt.rail != rail
        or _stable_receipt_semantics_sha256(receipt) != stable_semantics_sha256
    ):
        raise MoneyRailResourceReceiptError(
            f"money-rail resource receipt index hash mismatch for {receipt_id} at {target}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        )
    if expected_rail is not None and receipt.rail != expected_rail:
        return None
    return receipt


def _iter_ledger_receipt_rows(
    target: Path,
    *,
    start_offset: int,
    fail_closed: bool,
) -> Iterator[_LedgerReceiptRow]:
    fd = os.open(target, os.O_RDONLY)
    try:
        _ensure_private_authoritative_ledger_fd(fd)
        with os.fdopen(fd, "rb") as fh:
            fd = -1
            fh.seek(start_offset)
            offset = start_offset
            line_number = 1 if start_offset == 0 else None
            while True:
                raw = fh.readline()
                if not raw:
                    return
                row_offset = offset
                offset += len(raw)
                if not raw.endswith(b"\n"):
                    message = (
                        f"torn final money-rail resource receipt line at {target}"
                        f"{f':{line_number}' if line_number is not None else ''}; "
                        f"{resource_receipt_recovery_guidance(log_path=target)}"
                    )
                    if fail_closed:
                        raise MoneyRailResourceReceiptError(message)
                    log.debug("%s skipped", message)
                    if line_number is not None:
                        line_number += 1
                    continue
                try:
                    receipt = _parse_ledger_receipt_row(target, raw, line_number=line_number)
                except MoneyRailResourceReceiptError:
                    if fail_closed:
                        raise
                    log.debug("malformed money-rail resource receipt skipped")
                    if line_number is not None:
                        line_number += 1
                    continue
                yield _LedgerReceiptRow(
                    receipt=receipt,
                    row_offset=row_offset,
                    row_length=len(raw),
                    raw_line_sha256=_sha256_bytes(raw),
                    stable_semantics_sha256=_stable_receipt_semantics_sha256(receipt),
                )
                if line_number is not None:
                    line_number += 1
    finally:
        if fd != -1:
            os.close(fd)


def _parse_ledger_receipt_row(
    target: Path,
    raw: bytes,
    *,
    line_number: int | None,
) -> MoneyRailResourceReceipt:
    location = f"{target}:{line_number}" if line_number is not None else str(target)
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise MoneyRailResourceReceiptError(
            f"non-UTF-8 money-rail resource receipt line at {location}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        ) from exc
    if not text:
        raise MoneyRailResourceReceiptError(
            f"empty money-rail resource receipt line at {location}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        )
    try:
        return MoneyRailResourceReceipt.model_validate_json(text)
    except (ValidationError, ValueError, TypeError) as exc:
        raise MoneyRailResourceReceiptError(
            f"malformed money-rail resource receipt line at {location}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        ) from exc


def _read_exact_ledger_row(target: Path, *, row_offset: int, row_length: int) -> bytes:
    fd = os.open(target, os.O_RDONLY)
    try:
        ledger_size = _ensure_private_authoritative_ledger_fd(fd).st_size
        if row_offset < 0 or row_offset > ledger_size or row_length <= 0:
            raise MoneyRailResourceReceiptError(
                f"out-of-bounds money-rail resource receipt locator at {target}:{row_offset} "
                f"length {row_length} for ledger size {ledger_size}; "
                f"{resource_receipt_recovery_guidance(log_path=target)}"
            )
        remaining_size = ledger_size - row_offset
        if row_length > remaining_size:
            raise MoneyRailResourceReceiptError(
                f"out-of-bounds money-rail resource receipt locator at {target}:{row_offset} "
                f"length {row_length} exceeds remaining ledger size {remaining_size}; "
                f"{resource_receipt_recovery_guidance(log_path=target)}"
            )
        raw = os.pread(fd, row_length, row_offset)
    finally:
        os.close(fd)
    if len(raw) != row_length:
        raise MoneyRailResourceReceiptError(
            f"stale money-rail resource receipt locator at {target}:{row_offset}; "
            f"{resource_receipt_recovery_guidance(log_path=target)}"
        )
    return raw


def _stable_receipt_semantics(receipt: MoneyRailResourceReceipt) -> dict[str, object]:
    payload = receipt.model_dump(mode="json")
    payload.pop("created_at", None)
    return payload


def _stable_receipt_semantics_sha256(receipt: MoneyRailResourceReceipt) -> str:
    return hashlib.sha256(
        json.dumps(
            _stable_receipt_semantics(receipt),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_receipt_index_replacement(conn: sqlite3.Connection, target: Path) -> None:
    integrity = conn.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or integrity[0] != "ok":
        raise _ReceiptIndexRebuildRequired
    _ensure_receipt_index_schema(conn)
    metadata = _read_index_metadata(conn)
    _validate_index_metadata_anchor(conn, target, metadata)
    if metadata.verified_size != target.stat().st_size:
        raise _ReceiptIndexRebuildRequired


def _sqlite_artifact_paths(index_path: Path) -> tuple[Path, ...]:
    return tuple(
        index_path.with_name(f"{index_path.name}{suffix}")
        for suffix in _SQLITE_INDEX_ARTIFACT_SUFFIXES
    )


def _ensure_private_sqlite_file(index_path: Path) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    existed = index_path.exists()
    fd = os.open(index_path, os.O_CREAT | os.O_RDWR, _SQLITE_PRIVATE_MODE)
    try:
        mode = os.fstat(fd).st_mode & 0o777
        if not existed or mode != _SQLITE_PRIVATE_MODE:
            os.fchmod(fd, _SQLITE_PRIVATE_MODE)
            os.fsync(fd)
    finally:
        os.close(fd)


def _force_private_mode(path: Path) -> None:
    os.chmod(path, _SQLITE_PRIVATE_MODE)


def _discard_sqlite_artifacts(index_path: Path) -> None:
    for artifact in _sqlite_artifact_paths(index_path):
        # Idempotent cleanup: a missing artifact is already the desired end state
        # (also covers a concurrent unlink). Any other OSError stays loud.
        with suppress(FileNotFoundError):
            artifact.unlink()


def _discard_sqlite_file_set(index_path: Path) -> None:
    # Idempotent cleanup: a missing index file is already the desired end state.
    with suppress(FileNotFoundError):
        index_path.unlink()
    _discard_sqlite_artifacts(index_path)


def _install_receipt_index_replacement(tmp_path: Path, index_path: Path) -> None:
    _discard_sqlite_artifacts(index_path)
    _fsync_directory(index_path.parent)
    os.replace(tmp_path, index_path)
    _force_private_mode(index_path)
    _fsync_directory(index_path.parent)


def _normalize_sql(value: str) -> str:
    return " ".join(value.split())


def _ensure_private_authoritative_ledger_file(target: Path) -> None:
    fd = os.open(target, os.O_RDONLY)
    try:
        _ensure_private_authoritative_ledger_fd(fd)
    finally:
        os.close(fd)


def _ensure_private_authoritative_ledger_fd(fd: int) -> os.stat_result:
    stat = os.fstat(fd)
    if stat.st_mode & 0o777 != _LEDGER_PRIVATE_MODE:
        os.fchmod(fd, _LEDGER_PRIVATE_MODE)
        os.fsync(fd)
    return stat


def _append_line_durable(target: Path, line: bytes) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_APPEND | os.O_CREAT | os.O_WRONLY, _LEDGER_PRIVATE_MODE)
    try:
        _ensure_private_authoritative_ledger_fd(fd)
        offset = os.lseek(fd, 0, os.SEEK_END)
        _write_all(fd, line)
        os.fsync(fd)
        if os.fstat(fd).st_size != offset + len(line):
            raise OSError(
                "money-rail resource receipt append size mismatch; "
                "next action: stop money-rail daemons and audit receipt log writers"
            )
    finally:
        os.close(fd)
    _fsync_directory(target.parent)
    return offset


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    written_total = 0
    while written_total < len(view):
        written = os.write(fd, view[written_total:])
        if written <= 0:
            raise OSError(
                "money-rail resource receipt append made no write progress; "
                "next action: check receipt log filesystem health"
            )
        written_total += written


def _fsync_directory(path: Path) -> None:
    dir_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _receipt_log_lock_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.lock")


@contextmanager
def _locked_receipt_log(target: Path) -> Iterator[None]:
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _receipt_log_lock_path(target)
    with lock_path.open("a", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def _receipt_id(
    *,
    rail: str,
    operation: MoneyRailReceiptOperation,
    route_path: str | None,
    external_id_sha256: str | None,
    raw_payload_sha256: str | None,
    created_at: datetime,
) -> str:
    if operation in {
        MoneyRailReceiptOperation.INGRESS,
        MoneyRailReceiptOperation.PAYMENT_EVENT_APPEND,
    }:
        basis = f"{operation.value}:{rail}:{external_id_sha256 or raw_payload_sha256}:{route_path}"
    else:
        basis = (
            f"{operation.value}:{rail}:{external_id_sha256 or raw_payload_sha256}:"
            f"{route_path}:{created_at.isoformat()}"
        )
    return f"mrr-{_slug(rail)}-{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:20]}"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    chars = [ch if ch.isalnum() else "-" for ch in value.lower()]
    return "".join(chars).strip("-") or "rail"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (MoneyRailResourceReceipt._evidence_matches_operation,)


__all__ = [
    "AUTHORITY_CASE",
    "DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH",
    "MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV",
    "MoneyRailReceiptOperation",
    "MoneyRailResourceReceipt",
    "MoneyRailResourceReceiptError",
    "RECEIPT_REF_PREFIX",
    "TASK_ID",
    "append_resource_receipt",
    "build_resource_receipt",
    "default_receipt_log_path",
    "load_resource_receipt",
    "receipt_ref_from_id",
    "receipt_reference",
    "record_awareness_write_resource_receipt",
    "record_external_api_poll_receipt",
    "record_ingress_resource_receipt",
    "record_payment_event_resource_receipt",
    "prepare_payment_event_resource_receipt",
    "prepare_awareness_write_resource_receipt",
    "commit_prepared_resource_receipt",
    "retract_prepared_resource_receipt",
    "require_resource_receipt",
    "resource_receipt_exists",
    "resource_receipt_matches",
    "resource_receipt_ref_present",
    "resource_receipt_refs",
    "resource_receipt_recovery_guidance",
    "tail_resource_receipts",
]
