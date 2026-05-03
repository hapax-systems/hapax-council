"""Modern Treasury receive-only rail.

Phase 0 receiver for Modern Treasury webhook events. Normalizes
inbound ``incoming_payment_detail.created`` /
``incoming_payment_detail.completed`` deliveries into a typed,
payer-aggregate :class:`IncomingPaymentEvent` — *without* calls,
outbound writes, CRM, or per-supporter relationship surfaces.

**Receive-only invariant.** This module never originates an outbound
network call, never writes to an external system, and never persists
PII. Modern Treasury's ``incoming_payment_detail`` object carries
``originating_account_number``, ``originating_routing_number``,
``description`` (free-text memo), and ``vendor_id`` (operator-internal
banking-partner cross-correlation ID) — all of which constitute
material banking PII if extracted. The receiver intentionally *does
not* extract them. The only payer-side field surfaced on the
normalized event is ``originating_party_name`` — the public sender
display Modern Treasury already shows on the operator's dashboard
(equivalent in sensitivity to a GitHub login or a BMaC supporter
handle, *not* a banking-customer identifier).

**Direction filter promoted into the event-kind taxonomy.** Modern
Treasury's webhook taxonomy separates incoming and outgoing flows at
the event-name level: ``incoming_payment_detail.created`` and
``incoming_payment_detail.completed`` are the only event names the
receiver accepts. Outgoing flows ride on ``payment_order.*`` events
which are rejected as unaccepted-event-type. This is a cleaner shape
than Mercury (where the ``kind`` field on the transaction data must
be inspected) — the receiver's accept set IS the direction filter.
The :class:`IncomingPaymentEventKind` enum lists the two accepted
events; everything else fail-closes.

**Strict 5-second response budget.** Per Modern Treasury's documented
webhook contract (and the Jr currentness-scout packet's 2026-changes
note), the platform enforces a 2xx-within-5-seconds response budget
on every delivery. Synchronous payload processing in the upstream
FastAPI handler can cause timeout failures + retry storms. The
receiver itself is pure validation (microseconds); the upstream
handler is responsible for keeping its accept-and-defer pattern
below the budget. This docstring documents the constraint so the
caller is reminded.

**No Modern Treasury SDK.** This module deliberately does NOT import
any Modern Treasury Python SDK or REST client. SDKs pull in HTTP
client surfaces and support outbound API calls — neither belongs in
a receive-only rail. HMAC SHA-256 verification per Modern Treasury's
documented ``X-Signature`` header format is implemented inline using
only ``hmac`` + ``hashlib`` from the standard library.

**HMAC SHA-256 wire format (matches Mercury / GitHub Sponsors /
BuyMeACoffee).** Modern Treasury signs webhook deliveries with HMAC
SHA-256 using the per-webhook secret configured in the Modern
Treasury dashboard, with the hexadecimal digest delivered in the
case-insensitive ``X-Signature`` HTTP header. The signature is
computed over the *raw* request body bytes — the upstream FastAPI
handler is responsible for capturing the raw body before JSON
parsing and passing both the parsed payload dict and the captured
raw bytes into :meth:`ModernTreasuryRailReceiver.ingest_webhook`.
A bare hex digest *and* the ``sha256=<hex>`` prefixed form are both
accepted; mismatch raises :class:`ReceiveOnlyRailError`.

**Modern Treasury envelope shape.** Live deliveries ship a JSON
envelope of the form::

    {
        "event": "incoming_payment_detail.created"
            | "incoming_payment_detail.completed",
        "data": {
            "id": "<uuid>",
            "object": "incoming_payment_detail",
            "amount": 10000,
            "currency": "USD",
            "originating_party_name": "<public sender display>",
            "type": "ach" | "wire" | "check" | "book" | "rtp" | "sepa",
            "status": "pending" | "completed" | "returned",
            "as_of_date": "2026-05-02",
            "created_at": "2026-05-02T12:00:00Z",
            ...
        }
    }

The receiver reads the event name from the top-level ``event`` field
(Modern Treasury's documented key — distinct from Mercury's ``type``)
and the payment fields from the nested ``data`` object. Modern
Treasury historically used the legacy top-level key ``type`` on some
deliveries; both forms are accepted on ingest with ``event`` taking
precedence when both are present.

**Amount normalization.** Modern Treasury's REST API and webhooks
ship ``amount`` as integer minor-units in the source currency (cents
for USD, pence for GBP, etc.) — the API contract is integer, distinct
from Mercury / Stripe / BMaC which ship decimal strings. The
receiver accepts both shapes for forward compatibility:

- Integer or integer-coercible numeric → used as-is (already
  minor-units).
- Decimal string with a decimal point (``"100.00"``) → multiplied by
  100 via ``Decimal`` (matches the BMaC / Mercury normalization;
  guards against incorrect SDK rendering that re-stringifies the
  integer cents as a decimal).
- Decimal string without a decimal point (``"10000"``) → parsed as
  integer-shaped string and used as-is.

Negative amounts (e.g. credit-returned reversals) are converted to
absolute value so the rail expresses gross movement; net flow is
reconstructed by ``event_kind`` + ``payment_method`` downstream.

**Multi-currency.** Modern Treasury is primarily USD-denominated for
ACH receipts but supports the broader ISO 4217 set on wire / SEPA
rails. The receiver preserves the source currency on the normalized
event. ``currency`` is verified to be a non-empty 3-letter uppercase
ISO 4217 code; non-conforming values fail-closed.

**Governance constraint.** No PII (no account/routing numbers, no
counterparty email, no description/memo text, no vendor_id), no
outbound, multi-currency normalized to minor-units in source
currency, HMAC SHA-256 auth via
:data:`MODERN_TREASURY_WEBHOOK_SECRET_ENV` env var. Validation,
signature, unknown-event, or shape failures fail-closed via
:class:`ReceiveOnlyRailError`.

cc-task: ``modern-treasury-receive-only-rail`` (Phase 0). Sibling
rails:
``shared/github_sponsors_receive_only_rail.py`` (#2218),
``shared/liberapay_receive_only_rail.py`` (#2219),
``shared/open_collective_receive_only_rail.py`` (#2226),
``shared/stripe_payment_link_receive_only_rail.py`` (#2227),
``shared/ko_fi_receive_only_rail.py`` (#2230),
``shared/patreon_receive_only_rail.py`` (#2231),
``shared/buy_me_a_coffee_receive_only_rail.py`` (#2234), and
``shared/mercury_receive_only_rail.py`` (#2251). Ninth rail in the
family — second direct-bank rail.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from shared._rail_idempotency import (
    IdempotencyError as _SharedIdempotencyError,
)
from shared._rail_idempotency import (
    IdempotencyStore,
)

MODERN_TREASURY_WEBHOOK_SECRET_ENV = "MODERN_TREASURY_WEBHOOK_SECRET"

_ISO_4217_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected Modern Treasury webhook payload.

    Raised on malformed payloads, unaccepted event kinds, HMAC SHA-256
    signature failures, missing fields, malformed currency codes,
    outgoing-direction events (``payment_order.*``), or shape
    violations. The receiver never silently drops or
    partially-accepts an inbound event.
    """


class IncomingPaymentEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver.

    Modern Treasury's webhook taxonomy splits incoming and outgoing at
    the event-name level. The receiver accepts only the two
    ``incoming_payment_detail.*`` lifecycle events; outgoing flows
    (``payment_order.*``, ``ledger_transaction.*``) are rejected as
    unaccepted-event-type. This makes the accept set the direction
    filter — there is no separate ``kind`` field that needs
    inspection.

    ``CREATED`` fires when Modern Treasury first detects the inbound
    payment; ``COMPLETED`` fires when the payment has cleared and is
    available in the operator's ledger. Both flow through the same
    normalized event shape; downstream consumers can dedupe by
    ``payment_id`` if they need create-vs-completed semantics.
    """

    CREATED = "incoming_payment_detail.created"
    COMPLETED = "incoming_payment_detail.completed"


_ACCEPTED_KINDS: frozenset[str] = frozenset(k.value for k in IncomingPaymentEventKind)


class PaymentMethod(StrEnum):
    """Canonical payment-method values Modern Treasury surfaces on
    ``data.type``.

    The receiver preserves the payment method on the normalized event
    so downstream consumers can route by rail (e.g. wire receipts get
    one downstream policy, ACH receipts another). Unknown method
    strings fail-closed rather than coerce to a fallback.
    """

    ACH = "ach"
    WIRE = "wire"
    CHECK = "check"
    BOOK = "book"
    RTP = "rtp"
    SEPA = "sepa"
    SIGNET = "signet"
    INTERAC = "interac"


_ACCEPTED_PAYMENT_METHODS: frozenset[str] = frozenset(m.value for m in PaymentMethod)


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IncomingPaymentEvent(_RailModel):
    """Normalized, payer-aggregate Modern Treasury incoming payment.

    *No PII fields exist on this type.* ``originating_party_handle``
    is the Modern Treasury public ``originating_party_name`` (the
    display Modern Treasury already surfaces for the sender —
    equivalent in sensitivity to a GitHub login or a BMaC supporter
    handle; *not* an account number, *not* a routing number, *not* an
    address, *not* an email, *not* a description/memo, *not* a
    vendor_id). ``amount_currency_cents`` is integer minor-units
    (cents/pence/etc.) in the source currency named by ``currency``.
    ``currency`` is the ISO 4217 3-letter uppercase code.
    ``raw_payload_sha256`` correlates this normalized event to the
    original webhook delivery without re-storing the raw payload
    (which contains memo text, account numbers, and other fields we
    do not want to persist beyond the receiver boundary).
    """

    originating_party_handle: str = Field(min_length=1, max_length=255)
    amount_currency_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    event_kind: IncomingPaymentEventKind
    payment_method: PaymentMethod
    occurred_at: datetime
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("originating_party_handle")
    @classmethod
    def _handle_is_display_name_only(cls, value: str) -> str:
        """``originating_party_handle`` must be a display, not an email."""
        if "@" in value:
            raise ValueError(
                "originating_party_handle must be a display name, not an email address"
            )
        return value

    @field_validator("currency")
    @classmethod
    def _currency_is_iso_4217(cls, value: str) -> str:
        """``currency`` must be a 3-letter uppercase ISO 4217 code."""
        if not _ISO_4217_CURRENCY_RE.fullmatch(value):
            raise ValueError(f"currency must be a 3-letter uppercase ISO 4217 code, got {value!r}")
        return value


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _verify_signature(raw_body: bytes, signature: str, secret: str) -> None:
    """Fail-closed HMAC SHA-256 verification.

    Modern Treasury's signature header is ``X-Signature: <hexdigest>``.
    Some integrations / partner forwarders prefix the digest with
    ``sha256=`` (parity with the GitHub format); both that and a bare
    hex digest are accepted (the receiver strips the prefix if
    present). Comparison uses :func:`hmac.compare_digest` to avoid
    timing leaks. Mismatch raises :class:`ReceiveOnlyRailError`.

    The signature is computed over the *raw* HTTP body bytes — the
    upstream FastAPI handler MUST capture the raw body before JSON
    parsing and pass it here.
    """
    if not secret:
        raise ReceiveOnlyRailError(
            f"signature provided but {MODERN_TREASURY_WEBHOOK_SECRET_ENV} is not set"
        )
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    if not hmac.compare_digest(expected, candidate):
        raise ReceiveOnlyRailError("HMAC SHA-256 signature mismatch")


def _coerce_event_kind(payload: dict[str, Any]) -> IncomingPaymentEventKind:
    """Map Modern Treasury's ``event`` (or legacy ``type``) string to enum.

    Outgoing event names like ``payment_order.created`` are rejected
    with a direction-specific message so the rejection is auditable.
    """
    raw_event = payload.get("event")
    if raw_event is None:
        raw_event = payload.get("type")
    if not isinstance(raw_event, str):
        raise ReceiveOnlyRailError(
            f"webhook 'event' must be a string, got {type(raw_event).__name__}"
        )
    if raw_event in _ACCEPTED_KINDS:
        return IncomingPaymentEventKind(raw_event)
    if raw_event.startswith("payment_order.") or raw_event.startswith("expected_payment."):
        raise ReceiveOnlyRailError(f"refusing outgoing event {raw_event!r} on receive-only rail")
    raise ReceiveOnlyRailError(f"unaccepted webhook event type {raw_event!r}")


def _payment_object(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the nested ``data`` object carrying payment fields."""
    candidate = payload.get("data")
    if isinstance(candidate, dict) and candidate:
        return candidate
    raise ReceiveOnlyRailError("payload missing 'data' object")


def _extract_originating_party_handle(payment: dict[str, Any]) -> str:
    """Extract Modern Treasury's public ``originating_party_name``."""
    handle = payment.get("originating_party_name")
    if not isinstance(handle, str) or not handle:
        raise ReceiveOnlyRailError("payload missing 'originating_party_name'")
    return handle


def _extract_payment_method(payment: dict[str, Any]) -> PaymentMethod:
    """Extract + validate the payment-method type.

    Modern Treasury's ``data.type`` field is one of:
    ``ach`` / ``wire`` / ``check`` / ``book`` / ``rtp`` / ``sepa``
    / ``signet`` / ``interac``. Any other value fails closed.
    """
    raw = payment.get("type")
    if not isinstance(raw, str) or not raw:
        raise ReceiveOnlyRailError("payload missing 'type' (payment method)")
    if raw not in _ACCEPTED_PAYMENT_METHODS:
        raise ReceiveOnlyRailError(f"unknown payment method {raw!r}")
    return PaymentMethod(raw)


def _amount_to_cents(raw_amount: Any) -> int:
    """Normalize the various Modern Treasury amount shapes to integer cents.

    Modern Treasury's REST API ships amounts as integer minor-units;
    the receiver also accepts decimal-string forms for forward
    compatibility with SDK changes that may re-stringify the value.
    """
    if isinstance(raw_amount, bool):
        raise ReceiveOnlyRailError("'amount' must be a numeric string or number")
    if isinstance(raw_amount, int):
        return abs(raw_amount)
    if isinstance(raw_amount, float):
        try:
            decimal_amount = Decimal(str(raw_amount))
        except InvalidOperation as exc:  # pragma: no cover - defensive
            raise ReceiveOnlyRailError(f"invalid 'amount' value {raw_amount!r}") from exc
        if decimal_amount % 1 == 0:
            return int(decimal_amount.copy_abs())
        return int((decimal_amount.copy_abs() * 100).to_integral_value())
    if isinstance(raw_amount, str):
        try:
            decimal_amount = Decimal(raw_amount)
        except InvalidOperation as exc:
            raise ReceiveOnlyRailError(
                f"invalid 'amount' decimal string {raw_amount!r}: {exc}"
            ) from exc
        # Decimal-string with a fractional part → treat as major units (× 100).
        # Decimal-string without fractional part → already minor units.
        if "." in raw_amount:
            return int((decimal_amount.copy_abs() * 100).to_integral_value())
        return int(decimal_amount.copy_abs())
    raise ReceiveOnlyRailError(
        f"'amount' must be a numeric string or number, got {type(raw_amount).__name__}"
    )


def _extract_amount_and_currency(payment: dict[str, Any]) -> tuple[int, str]:
    """Extract minor-unit amount + ISO 4217 currency from the delivery."""
    raw_amount = payment.get("amount")
    if raw_amount is None:
        raise ReceiveOnlyRailError("payload missing 'amount'")
    cents = _amount_to_cents(raw_amount)

    raw_currency = payment.get("currency")
    if not isinstance(raw_currency, str) or not raw_currency:
        raise ReceiveOnlyRailError("payload missing 'currency'")
    return cents, raw_currency.upper()


def _extract_occurred_at(payload: dict[str, Any], payment: dict[str, Any]) -> datetime:
    """Extract the delivery timestamp.

    Modern Treasury ships ``created_at`` and ``updated_at`` on the
    payment object, plus an ``as_of_date`` for the settlement date.
    The receiver checks ``updated_at`` first (most recent), then
    ``created_at``, then top-level envelope fallbacks. ISO 8601
    strings are accepted with optional ``Z`` UTC suffix.
    """
    raw = (
        payment.get("updated_at")
        or payment.get("created_at")
        or payload.get("occurred_at")
        or payload.get("created")
    )
    if not isinstance(raw, str) or not raw:
        raise ReceiveOnlyRailError("payload missing 'updated_at' / 'created_at' / 'occurred_at'")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiveOnlyRailError(f"invalid ISO 8601 timestamp {raw!r}: {exc}") from exc


class ModernTreasuryRailReceiver:
    """Receive-only adapter for Modern Treasury webhooks.

    Construction is cheap and side-effect-free. The single public
    method :meth:`ingest_webhook` validates payload shape, optionally
    verifies the HMAC SHA-256 signature against the *raw* request
    body bytes, filters direction via the event-kind allowlist, and
    returns a normalized :class:`IncomingPaymentEvent`. The receiver
    never opens a network socket, writes to disk, or contacts any
    external system.

    The upstream FastAPI handler must keep its accept-and-defer
    pattern below the 5-second response-budget Modern Treasury
    enforces; the receiver itself is microsecond-fast pure
    validation, so the budget pressure lives at the handler boundary,
    not here.
    """

    def __init__(
        self,
        *,
        secret_env_var: str = MODERN_TREASURY_WEBHOOK_SECRET_ENV,
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self._secret_env_var = secret_env_var
        self._idempotency_store = idempotency_store

    def _resolve_secret(self) -> str:
        return os.environ.get(self._secret_env_var, "")

    def ingest_webhook(
        self,
        payload: dict[str, Any],
        signature: str | None,
        *,
        raw_body: bytes | None = None,
    ) -> IncomingPaymentEvent | None:
        """Validate + normalize a single Modern Treasury delivery.

        Returns the normalized :class:`IncomingPaymentEvent` for
        accepted ``incoming_payment_detail.*`` deliveries. Raises
        :class:`ReceiveOnlyRailError` for malformed payloads,
        unaccepted event types (including outgoing
        ``payment_order.*``), signature failures, or shape
        violations. Returns ``None`` only when the caller passes
        ``payload={}`` *and* ``signature=None``, which is treated as
        a no-op heartbeat ping (parity with sibling rails'
        empty-test-delivery handling).

        ``signature`` is the value of the ``X-Signature`` HTTP header
        (``None`` skips verification — only acceptable for tests /
        pre-flight pings; production callers must always pass it).
        ``raw_body`` is the raw HTTP body bytes Modern Treasury
        signed; if not provided, the receiver falls back to
        canonical-encoding the parsed payload for verification, which
        works for round-trip test fixtures but may spuriously fail
        against live deliveries — pass the raw bytes whenever they're
        available. Signature verification reads
        :data:`MODERN_TREASURY_WEBHOOK_SECRET_ENV` from the
        environment; unset env var with a non-None signature fails
        closed.
        """
        if not isinstance(payload, dict):
            raise ReceiveOnlyRailError(f"payload must be a dict, got {type(payload).__name__}")

        if not payload and signature is None:
            return None

        payload_bytes = raw_body if raw_body is not None else _canonical_bytes(payload)
        payload_sha256 = _sha256_hex(payload_bytes)

        if signature is not None:
            secret = self._resolve_secret()
            _verify_signature(payload_bytes, signature, secret)

        event_kind = _coerce_event_kind(payload)
        payment = _payment_object(payload)
        originating_party_handle = _extract_originating_party_handle(payment)
        payment_method = _extract_payment_method(payment)
        amount_cents, currency = _extract_amount_and_currency(payment)
        occurred_at = _extract_occurred_at(payload, payment)

        if self._idempotency_store is not None:
            payment_id = payment.get("id")
            if not isinstance(payment_id, str) or not payment_id:
                raise ReceiveOnlyRailError(
                    "idempotency_store provided but data.id missing — "
                    "Modern Treasury IPD payloads carry the per-delivery "
                    "identifier in data.id"
                )
            try:
                if not self._idempotency_store.record_or_skip(payment_id):
                    return None
            except _SharedIdempotencyError as exc:
                raise ReceiveOnlyRailError(str(exc)) from exc

        try:
            return IncomingPaymentEvent(
                originating_party_handle=originating_party_handle,
                amount_currency_cents=amount_cents,
                currency=currency,
                event_kind=event_kind,
                payment_method=payment_method,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "MODERN_TREASURY_WEBHOOK_SECRET_ENV",
    "IdempotencyStore",
    "IncomingPaymentEvent",
    "IncomingPaymentEventKind",
    "ModernTreasuryRailReceiver",
    "PaymentMethod",
    "ReceiveOnlyRailError",
]
