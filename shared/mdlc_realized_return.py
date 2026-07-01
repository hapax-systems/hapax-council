"""MonDLC rail reader for witnessed realized inbound returns.

Payment rail receivers accept a wider set of lifecycle events than the
M-instrument may score. This module is the narrow boundary: it turns only
settled, witnessed, positive inbound receipt events into
``MonDLCMeasurement`` values, and returns explicit refusal records for
membership lifecycle events, refunds, reversals, fees, outbound movement,
projected values, unsupported kinds, and malformed evidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from shared.durable_jsonl_sink import DurableSinkRow, validate_chain
from shared.mdlc_measure import MonDLCMeasurement

PAYMENT_EVENT_STREAM_ID: Final = "payment-event"
PAYMENT_EVENT_DATA_CLASS: Final = "financial_receipt"

REALIZED_INBOUND_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        # Stripe / generic payment rails.
        "payment_intent_succeeded",
        "checkout_session_completed",
        "payment_succeeded",
        # Donation/support rails.
        "payin_succeeded",
        "collective_transaction_created",
        "order_processed",
        "donation",
        "commission",
        "shop_order",
        "extras_purchase",
        # Bank rails.
        "incoming_payment_detail.completed",
        "incoming_ach.create",
        "transaction.create",
        "transaction.created",
        "transaction.updated",
        # Legacy awareness receive rails.
        "lightning",
        "nostr_zap",
        "liberapay",
        "x402_usdc_base",
    }
)
MEMBERSHIP_LIFECYCLE_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "created",
        "tier_changed",
        "member_created",
        "customer_subscription_created",
        "subscription",
        "subscription_set",
        "membership.started",
        "members_create",
        "members_update",
        "members_pledge_create",
        "tip_set",
    }
)
NON_SETTLED_INBOUND_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "payin_created",
        "incoming_payment_detail.created",
    }
)
REFUND_REVERSAL_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "cancelled",
        "pending_cancellation",
        "customer_subscription_deleted",
        "payment_refunded",
        "subscription_cancelled",
        "tip_cancelled",
        "membership.cancelled",
        "members_pledge_delete",
    }
)
OUTBOUND_EVENT_KINDS: Final[frozenset[str]] = frozenset({"expense_paid"})
DIRECTION_FILTERED_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "transaction.create",
        "transaction.created",
        "transaction.updated",
    }
)
PROJECTED_PROVENANCE_VALUES: Final[frozenset[str]] = frozenset(
    {"projected", "projection", "forecast", "estimated", "synthetic"}
)
INBOUND_DIRECTION_VALUES: Final[frozenset[str]] = frozenset({"credit", "incoming", "inbound"})
OUTBOUND_DIRECTION_VALUES: Final[frozenset[str]] = frozenset({"debit", "outgoing", "outbound"})


class RealizedReturnStatus(StrEnum):
    """Rail-reader status with truthiness deliberately guarded."""

    ACCEPTED = "accepted"
    REFUSED = "refused"


class RealizedReturnRefusalReason(StrEnum):
    """Machine-readable refusal reasons for ratchet-ledger and CCTV consumers."""

    PROJECTED_VALUE = "projected_value"
    OUTBOUND_EVENT = "outbound_event"
    REFUND_OR_REVERSAL_EVENT = "refund_or_reversal_event"
    FEE_EVENT = "fee_event"
    MEMBERSHIP_LIFECYCLE_EVENT = "membership_lifecycle_event"
    NON_SETTLED_INBOUND_EVENT = "non_settled_inbound_event"
    UNSUPPORTED_EVENT_KIND = "unsupported_event_kind"
    MISSING_EVENT_KIND = "missing_event_kind"
    MISSING_AMOUNT = "missing_amount"
    NON_POSITIVE_AMOUNT = "non_positive_amount"
    MISSING_OBSERVED_AT = "missing_observed_at"
    MISSING_RAIL_EVIDENCE = "missing_rail_evidence"
    INVALID_EVENT_SHAPE = "invalid_event_shape"
    NOT_STAGE0_PAYMENT_EVENT = "not_stage0_payment_event"


@dataclass(frozen=True)
class RealizedReturnRailResult:
    """Result of reading one payment rail event at the MonDLC boundary."""

    status: RealizedReturnStatus
    measurement: MonDLCMeasurement | None
    refusal_reason: RealizedReturnRefusalReason | None
    event_kind: str | None
    amount_minor_units: int | None
    currency: str | None
    observed_at: datetime | None
    evidence_refs: tuple[str, ...]
    source_class: str = "payment_event"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status is RealizedReturnStatus.ACCEPTED

    def __bool__(self) -> bool:
        raise TypeError("RealizedReturnRailResult truthiness is undefined; inspect status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "refusal_reason": None if self.refusal_reason is None else self.refusal_reason.value,
            "event_kind": self.event_kind,
            "amount_minor_units": self.amount_minor_units,
            "currency": self.currency,
            "observed_at": None if self.observed_at is None else _iso_utc(self.observed_at),
            "evidence_refs": list(self.evidence_refs),
            "source_class": self.source_class,
            "detail": self.detail,
            "measurement": None
            if self.measurement is None
            else {
                "value": self.measurement.value,
                "provenance": self.measurement.provenance,
                "observed_at": None
                if self.measurement.observed_at is None
                else _iso_utc(self.measurement.observed_at),
                "evidence_refs": list(self.measurement.evidence_refs),
                "corroborated_by": list(self.measurement.corroborated_by),
            },
        }


def realized_return_from_rail(
    event: Any,
    *,
    source_receipt_ref: str | None = None,
    durable_row_hash: str | None = None,
) -> RealizedReturnRailResult:
    """Read one rail event as a MonDLC realized-return candidate.

    Only explicitly enumerated, positive, witnessed inbound receipt kinds become
    measurements. Every other path returns a refusal object instead of handing a
    synthetic or lifecycle value to ``score()``.
    """

    if _is_projected(event):
        return _refused(
            RealizedReturnRefusalReason.PROJECTED_VALUE,
            event=event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
            detail="projected or forecast provenance is not realized return evidence",
        )

    event_kind = _event_kind(event)
    if event_kind is None:
        return _refused(
            RealizedReturnRefusalReason.MISSING_EVENT_KIND,
            event=event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
            detail="event_kind or legacy rail field is required",
        )
    event_kind_key = event_kind.casefold()

    direction = _direction(event)
    if direction in OUTBOUND_DIRECTION_VALUES:
        return _refused(
            RealizedReturnRefusalReason.OUTBOUND_EVENT,
            event=event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
            event_kind=event_kind,
            detail=f"direction {direction!r} is outbound",
        )
    if event_kind_key in DIRECTION_FILTERED_EVENT_KINDS and direction not in (
        INBOUND_DIRECTION_VALUES | {None}
    ):
        return _refused(
            RealizedReturnRefusalReason.OUTBOUND_EVENT,
            event=event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
            event_kind=event_kind,
            detail="bank transaction event lacks an inbound direction witness",
        )

    refusal_reason = _refusal_reason_for_event_kind(event_kind_key)
    if refusal_reason is not None:
        return _refused(
            refusal_reason,
            event=event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
            event_kind=event_kind,
            detail=f"event kind {event_kind!r} is not a realized inbound return",
        )
    if event_kind_key not in REALIZED_INBOUND_EVENT_KINDS:
        return _refused(
            RealizedReturnRefusalReason.UNSUPPORTED_EVENT_KIND,
            event=event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
            event_kind=event_kind,
            detail=f"event kind {event_kind!r} is not in the realized inbound allowlist",
        )

    amount_result = _amount_minor_units(event)
    if isinstance(amount_result, RealizedReturnRefusalReason):
        return _refused(
            amount_result,
            event=event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
            event_kind=event_kind,
            detail="event amount is absent or malformed",
        )
    amount_minor_units, currency = amount_result
    if amount_minor_units <= 0:
        return _refused(
            RealizedReturnRefusalReason.NON_POSITIVE_AMOUNT,
            event=event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
            event_kind=event_kind,
            amount_minor_units=amount_minor_units,
            currency=currency,
            detail="realized return must be positive before score folding",
        )

    observed_at = _observed_at(event)
    if observed_at is None:
        return _refused(
            RealizedReturnRefusalReason.MISSING_OBSERVED_AT,
            event=event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
            event_kind=event_kind,
            amount_minor_units=amount_minor_units,
            currency=currency,
            detail="occurred_at, timestamp, or observed_at is required",
        )

    refs = _evidence_refs(
        event,
        source_receipt_ref=source_receipt_ref,
        durable_row_hash=durable_row_hash,
    )
    if not refs:
        return _refused(
            RealizedReturnRefusalReason.MISSING_RAIL_EVIDENCE,
            event=event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
            event_kind=event_kind,
            amount_minor_units=amount_minor_units,
            currency=currency,
            detail="rail evidence requires a durable receipt, payload hash, or external id",
        )

    measurement = MonDLCMeasurement(
        value=float(amount_minor_units),
        provenance="inbound_rail",
        observed_at=observed_at,
        evidence_refs=refs,
    )
    return RealizedReturnRailResult(
        status=RealizedReturnStatus.ACCEPTED,
        measurement=measurement,
        refusal_reason=None,
        event_kind=event_kind,
        amount_minor_units=amount_minor_units,
        currency=currency,
        observed_at=observed_at,
        evidence_refs=refs,
        detail="accepted witnessed realized inbound return",
    )


def realized_return_from_durable_payment_event(
    row: DurableSinkRow | Mapping[str, Any],
) -> RealizedReturnRailResult:
    """Read one Stage0 durable ``payment-event`` row."""

    stream_id = _row_field(row, "stream_id")
    data_class = _row_field(row, "data_class")
    payload = _row_field(row, "payload")
    source_receipt_ref = _row_field(row, "source_receipt_ref")
    row_hash = _row_field(row, "row_hash")

    if stream_id != PAYMENT_EVENT_STREAM_ID or data_class != PAYMENT_EVENT_DATA_CLASS:
        return RealizedReturnRailResult(
            status=RealizedReturnStatus.REFUSED,
            measurement=None,
            refusal_reason=RealizedReturnRefusalReason.NOT_STAGE0_PAYMENT_EVENT,
            event_kind=None,
            amount_minor_units=None,
            currency=None,
            observed_at=None,
            evidence_refs=_string_tuple((source_receipt_ref,)),
            detail="durable row must be payment-event/financial_receipt",
        )
    if not isinstance(payload, Mapping):
        return RealizedReturnRailResult(
            status=RealizedReturnStatus.REFUSED,
            measurement=None,
            refusal_reason=RealizedReturnRefusalReason.INVALID_EVENT_SHAPE,
            event_kind=None,
            amount_minor_units=None,
            currency=None,
            observed_at=None,
            evidence_refs=_string_tuple((source_receipt_ref, row_hash)),
            detail="durable payment row payload must be a mapping",
        )
    return realized_return_from_rail(
        payload,
        source_receipt_ref=str(source_receipt_ref or ""),
        durable_row_hash=str(row_hash or ""),
    )


def realized_returns_from_durable_payment_events(
    path: Path | str,
) -> tuple[RealizedReturnRailResult, ...]:
    """Read all current rows from a durable Stage0 payment-event stream file."""

    target = Path(path)
    validation = validate_chain(target, stream_id=PAYMENT_EVENT_STREAM_ID)
    validation.raise_for_issues()
    if not target.exists():
        return ()

    results: list[RealizedReturnRailResult] = []
    with target.open("r", encoding="utf-8") as fh:
        for raw in fh:
            text = raw.strip()
            if not text:
                continue
            row = json.loads(text)
            if not isinstance(row, Mapping):
                results.append(
                    RealizedReturnRailResult(
                        status=RealizedReturnStatus.REFUSED,
                        measurement=None,
                        refusal_reason=RealizedReturnRefusalReason.INVALID_EVENT_SHAPE,
                        event_kind=None,
                        amount_minor_units=None,
                        currency=None,
                        observed_at=None,
                        evidence_refs=(),
                        detail="durable JSONL row is not an object",
                    )
                )
                continue
            results.append(realized_return_from_durable_payment_event(row))
    return tuple(results)


def _refusal_reason_for_event_kind(
    event_kind: str,
) -> RealizedReturnRefusalReason | None:
    if "fee" in event_kind:
        return RealizedReturnRefusalReason.FEE_EVENT
    if event_kind in REFUND_REVERSAL_EVENT_KINDS or any(
        marker in event_kind
        for marker in ("refund", "reversal", "chargeback", "clawback", "dispute")
    ):
        return RealizedReturnRefusalReason.REFUND_OR_REVERSAL_EVENT
    if event_kind in OUTBOUND_EVENT_KINDS or "payment_order" in event_kind:
        return RealizedReturnRefusalReason.OUTBOUND_EVENT
    if event_kind in MEMBERSHIP_LIFECYCLE_EVENT_KINDS:
        return RealizedReturnRefusalReason.MEMBERSHIP_LIFECYCLE_EVENT
    if event_kind in NON_SETTLED_INBOUND_EVENT_KINDS:
        return RealizedReturnRefusalReason.NON_SETTLED_INBOUND_EVENT
    return None


def _refused(
    refusal_reason: RealizedReturnRefusalReason,
    *,
    event: Any,
    source_receipt_ref: str | None,
    durable_row_hash: str | None,
    event_kind: str | None = None,
    amount_minor_units: int | None = None,
    currency: str | None = None,
    detail: str = "",
) -> RealizedReturnRailResult:
    return RealizedReturnRailResult(
        status=RealizedReturnStatus.REFUSED,
        measurement=None,
        refusal_reason=refusal_reason,
        event_kind=event_kind or _event_kind(event),
        amount_minor_units=amount_minor_units,
        currency=currency,
        observed_at=_observed_at(event),
        evidence_refs=_evidence_refs(
            event,
            source_receipt_ref=source_receipt_ref,
            durable_row_hash=durable_row_hash,
        ),
        detail=detail,
    )


def _is_projected(event: Any) -> bool:
    if _truthy_field(event, "projected", "is_projected", "forecast", "estimated"):
        return True
    provenance = _text_field(event, "provenance")
    return provenance is not None and provenance.casefold() in PROJECTED_PROVENANCE_VALUES


def _event_kind(event: Any) -> str | None:
    raw = _field(event, "event_kind")
    if raw is None:
        raw = _field(event, "rail")
    text = _normalize_text(raw)
    return text or None


def _direction(event: Any) -> str | None:
    direction = _normalize_text(_field(event, "direction"))
    return None if direction is None else direction.casefold()


def _observed_at(event: Any) -> datetime | None:
    for name in ("occurred_at", "timestamp", "observed_at", "realized_at"):
        value = _field(event, name)
        if value is not None:
            return _optional_datetime(value)
    return None


def _amount_minor_units(
    event: Any,
) -> tuple[int, str | None] | RealizedReturnRefusalReason:
    for field_name, default_currency in (
        ("amount_currency_cents", None),
        ("amount_usd_cents", "USD"),
        ("amount_eur_cents", "EUR"),
        ("amount_sats", "SATS"),
    ):
        raw = _field(event, field_name)
        if raw is not None:
            amount = _integer_amount(raw)
            if amount is None:
                return RealizedReturnRefusalReason.INVALID_EVENT_SHAPE
            currency = _text_field(event, "currency") or default_currency
            return amount, currency

    for field_name, default_currency in (("amount_usd", "USD"), ("amount_eur", "EUR")):
        raw = _field(event, field_name)
        if raw is not None:
            amount = _major_units_to_minor(raw)
            if amount is None:
                return RealizedReturnRefusalReason.INVALID_EVENT_SHAPE
            return amount, default_currency
    return RealizedReturnRefusalReason.MISSING_AMOUNT


def _integer_amount(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value)


def _major_units_to_minor(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        minor = Decimal(str(value)) * Decimal("100")
    except (InvalidOperation, ValueError):
        return None
    integral = minor.to_integral_value()
    if minor != integral:
        return None
    return int(integral)


def _evidence_refs(
    event: Any,
    *,
    source_receipt_ref: str | None,
    durable_row_hash: str | None,
) -> tuple[str, ...]:
    refs: list[str] = []
    for ref in _coerce_refs(_field(event, "evidence_refs")):
        refs.append(ref)
    if source_receipt_ref and source_receipt_ref.strip():
        refs.append(source_receipt_ref.strip())
    if durable_row_hash and durable_row_hash.strip():
        refs.append(f"durable:{PAYMENT_EVENT_STREAM_ID}:{durable_row_hash.strip()}")
    payload_hash = _text_field(event, "raw_payload_sha256")
    if payload_hash:
        refs.append(f"payload_sha256:{payload_hash}")
    external_id = _text_field(
        event, "external_id", "event_id", "payment_id", "transaction_id", "id"
    )
    if external_id:
        refs.append(f"rail_external_id:{external_id}")
    return tuple(dict.fromkeys(refs))


def _row_field(row: DurableSinkRow | Mapping[str, Any], name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name)


def _field(event: Any, *names: str) -> Any:
    for name in names:
        if isinstance(event, Mapping):
            if name in event:
                return event[name]
            continue
        if hasattr(event, name):
            return getattr(event, name)
    return None


def _truthy_field(event: Any, *names: str) -> bool:
    return any(bool(_field(event, name)) for name in names)


def _text_field(event: Any, *names: str) -> str | None:
    for name in names:
        text = _normalize_text(_field(event, name))
        if text:
            return text
    return None


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    text = str(value).strip()
    return text or None


def _optional_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        return _ensure_utc(datetime.fromisoformat(text))
    return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return _ensure_utc(value).isoformat().replace("+00:00", "Z")


def _coerce_refs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, Sequence):
        return _string_tuple(value)
    return ()


def _string_tuple(value: Sequence[Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        ref = item.strip()
        if ref:
            refs.append(ref)
    return tuple(refs)


__all__ = [
    "DIRECTION_FILTERED_EVENT_KINDS",
    "MEMBERSHIP_LIFECYCLE_EVENT_KINDS",
    "NON_SETTLED_INBOUND_EVENT_KINDS",
    "OUTBOUND_EVENT_KINDS",
    "PAYMENT_EVENT_DATA_CLASS",
    "PAYMENT_EVENT_STREAM_ID",
    "REALIZED_INBOUND_EVENT_KINDS",
    "REFUND_REVERSAL_EVENT_KINDS",
    "RealizedReturnRailResult",
    "RealizedReturnRefusalReason",
    "RealizedReturnStatus",
    "realized_return_from_durable_payment_event",
    "realized_return_from_rail",
    "realized_returns_from_durable_payment_events",
]
