"""Governed resource receipts for receive-only money rails.

These receipts are private routing/resource evidence. They prove that a money
rail ingress, external API poll, payment-event append, or awareness-state write
was admitted into the governed resource calculus. They never grant spend
authority, public projection authority, perks, or customer-service obligations.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections import deque
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

log = logging.getLogger(__name__)

DEFAULT_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH = Path(
    os.environ.get(
        "HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH",
        "/dev/shm/hapax-monetization/resource-receipts.jsonl",
    )
)
MONEY_RAIL_RESOURCE_RECEIPT_LOG_ENV = "HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH"
MONEY_RAIL_RESOURCE_RECEIPT_SCHEMA_VERSION = 1
TASK_ID = "cc-task-money-rails-resource-receipt-ledger-20260630"
AUTHORITY_CASE = "CASE-CAPACITY-ROUTING-001"
RECEIPT_REF_PREFIX = "money-rail-resource-receipt:"
_SHA256_RE = r"^[a-f0-9]{64}$"

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
    """Append one receipt idempotently; return True iff present afterward."""

    target = log_path if log_path is not None else default_receipt_log_path()
    line = receipt.model_dump_json() + "\n"
    with _lock:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if receipt.receipt_id in _existing_receipt_ids(target):
                return True
            with target.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
        except OSError:
            log.warning("money-rail resource receipt append failed at %s", target, exc_info=True)
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
        with target.open("r", encoding="utf-8") as fh:
            for raw in fh:
                text = raw.strip()
                if not text:
                    continue
                try:
                    tail.append(MoneyRailResourceReceipt.model_validate_json(text))
                except (ValidationError, ValueError, TypeError):
                    log.debug("malformed money-rail resource receipt skipped")
    except OSError:
        log.warning("money-rail resource receipt read failed at %s", target, exc_info=True)
        return []
    return list(tail)


def resource_receipt_exists(ref: str, *, log_path: Path | None = None) -> bool:
    try:
        _prefix, rail, receipt_id = ref.split(":", 2)
    except ValueError:
        return False
    if _prefix != RECEIPT_REF_PREFIX.rstrip(":"):
        return False
    target = log_path if log_path is not None else default_receipt_log_path()
    if not target.exists():
        return False
    try:
        with target.open("r", encoding="utf-8") as fh:
            for raw in fh:
                text = raw.strip()
                if not text:
                    continue
                try:
                    receipt = MoneyRailResourceReceipt.model_validate_json(text)
                except (ValidationError, ValueError, TypeError):
                    log.debug("malformed money-rail resource receipt skipped")
                    continue
                if receipt.rail == rail and receipt.receipt_id == receipt_id:
                    return True
    except OSError:
        log.warning("money-rail resource receipt read failed at %s", target, exc_info=True)
    return False


def require_resource_receipt(ref: str, *, log_path: Path | None = None) -> None:
    if not resource_receipt_exists(ref, log_path=log_path):
        raise MoneyRailResourceReceiptError(
            f"missing money-rail resource receipt: {ref}; "
            "check HAPAX_MONEY_RAIL_RESOURCE_RECEIPT_LOG_PATH, /dev/shm availability, "
            "and receipt log permissions"
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
    return _append_and_ref(receipt, log_path=log_path)


def record_awareness_write_resource_receipt(
    *,
    state_path: Path,
    source_log_path: Path,
    receipt_count: int,
    log_path: Path | None = None,
) -> str | None:
    receipt = build_resource_receipt(
        rail="awareness",
        operation=MoneyRailReceiptOperation.AWARENESS_STATE_WRITE,
        external_id=f"{state_path}:{datetime.now(UTC).isoformat()}",
        downstream_action="operator_awareness.write_state_atomic",
        route_provenance=(
            "route:agents.payment_processors.monetization_aggregator",
            f"authority_case:{AUTHORITY_CASE}",
        ),
        resource_provenance=(
            f"awareness_state_path:{state_path}",
            f"payment_event_log:{source_log_path}",
            f"receipt_count:{receipt_count}",
        ),
    )
    return _append_and_ref(receipt, log_path=log_path)


def _append_and_ref(
    receipt: MoneyRailResourceReceipt,
    *,
    log_path: Path | None = None,
) -> str | None:
    if not append_resource_receipt(receipt, log_path=log_path):
        return None
    ref = receipt_reference(receipt)
    try:
        require_resource_receipt(ref, log_path=log_path)
    except MoneyRailResourceReceiptError:
        return None
    return ref


def _existing_receipt_ids(target: Path) -> set[str]:
    if not target.exists():
        return set()
    ids: set[str] = set()
    with target.open("r", encoding="utf-8") as fh:
        for raw in fh:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("receipt_id"), str):
                ids.add(payload["receipt_id"])
    return ids


def _receipt_id(
    *,
    rail: str,
    operation: MoneyRailReceiptOperation,
    route_path: str | None,
    external_id_sha256: str | None,
    raw_payload_sha256: str | None,
    created_at: datetime,
) -> str:
    if operation is MoneyRailReceiptOperation.INGRESS:
        basis = f"ingress:{rail}:{external_id_sha256 or raw_payload_sha256}:{route_path}"
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
    "receipt_ref_from_id",
    "receipt_reference",
    "record_awareness_write_resource_receipt",
    "record_external_api_poll_receipt",
    "record_ingress_resource_receipt",
    "record_payment_event_resource_receipt",
    "require_resource_receipt",
    "resource_receipt_exists",
    "resource_receipt_ref_present",
    "resource_receipt_refs",
    "tail_resource_receipts",
]
