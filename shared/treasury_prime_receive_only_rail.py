"""Treasury Prime receive-only rail (Phase 0, ledger accounts).

Phase 0 receiver for Treasury Prime webhook events on ledger
accounts. Normalizes inbound ``incoming_ach.create`` deliveries into
a typed, payer-aggregate :class:`IncomingAchEvent` — *without* calls,
outbound writes, CRM, or per-supporter relationship surfaces.

**Phase 0 + Phase 1 scope: ledger-account ACH + core direct accounts.**
Treasury Prime emits webhooks for two account types: ledger accounts
(event ``incoming_ach.create``, Phase 0) and core direct accounts
(event ``transaction.create``, Phase 1). Phase 0 ships
``incoming_ach.create`` — incoming-by-name at the event-kind level
(Modern Treasury shape). Phase 1 (this iteration) adds
``transaction.create`` with the data-level direction filter (Mercury
shape): ``data.direction`` must be ``"credit"`` or ``"incoming"``;
``"debit"`` and ``"outgoing"`` are refused; missing or unknown values
fail-closed.

**Receive-only invariant.** This module never originates an outbound
network call, never writes to an external system, and never persists
PII. Treasury Prime's ``incoming_ach`` object carries the originator
account number, the routing number, the originator address, and any
trace number / company-entry-description fields that constitute
material banking PII or low-utility metadata. The receiver
intentionally does *not* extract any of those. The only payer-side
field surfaced on the normalized event is
``originating_party_handle`` — the public sender display Treasury
Prime already shows on the operator's dashboard (equivalent in
sensitivity to a GitHub login or a BMaC supporter handle, *not* a
banking-customer identifier).

**Direction filter at event-kind level (cleaner than Mercury).** The
receiver's accept set is the single event ``incoming_ach.create`` —
incoming by event-name, no separate ``data.kind`` inspection needed.
Outgoing flows ride on ``transaction.create`` (core direct accounts;
Phase 1) and ``ach_origination.*`` events (rejected as
unaccepted-event-type with a direction-specific message).

**No Treasury Prime SDK.** This module deliberately does NOT import
any Treasury Prime Python SDK or REST client. SDKs pull in HTTP
client surfaces and support outbound API calls — neither belongs in
a receive-only rail. HMAC SHA-256 verification per Treasury Prime's
documented ``X-Signature`` header format is implemented inline using
only ``hmac`` + ``hashlib`` from the standard library.

**HMAC SHA-256 wire format (matches Modern Treasury / Mercury /
GitHub Sponsors / BuyMeACoffee).** Treasury Prime signs webhook
deliveries with HMAC SHA-256 using the per-webhook secret configured
in the Treasury Prime dashboard. The signature is delivered in the
case-insensitive ``X-Signature`` HTTP header (same header name as
Modern Treasury — the FastAPI handler at the dispatch boundary
disambiguates by URL path, not by header). The signature is
computed over the *raw* request body bytes — the upstream FastAPI
handler is responsible for capturing the raw body before JSON
parsing and passing both the parsed payload dict and the captured
raw bytes into :meth:`TreasuryPrimeRailReceiver.ingest_webhook`.
A bare hex digest *and* the ``sha256=<hex>`` prefixed form are both
accepted; mismatch raises :class:`ReceiveOnlyRailError`.

**Treasury Prime envelope shape.** Live ledger-account deliveries
ship a JSON envelope of the form::

    {
        "event": "incoming_ach.create",
        "data": {
            "id": "<uuid>",
            "amount": 10000,
            "currency": "USD",
            "originating_party_name": "<public sender display>",
            "ledger_account_id": "<uuid>",
            "settlement_date": "2026-05-04",
            "created_at": "2026-05-02T12:00:00Z",
            ...
        }
    }

The receiver reads the event name from the top-level ``event`` field
and the payment fields from the nested ``data`` object.

**Amount normalization.** Treasury Prime's REST API and webhooks
ship ``amount`` as integer minor-units in the source currency
(matching Modern Treasury). The receiver also accepts decimal-string
forms for forward compatibility — strings with a decimal point are
treated as major units (× 100); strings without are treated as
already-minor-units. Negative amounts (e.g. credit-returned
reversals) are converted to absolute value (gross movement).

**Multi-currency.** Treasury Prime is USD-only on ACH receipts in
Phase 0 scope. The receiver still preserves the source currency on
the normalized event and validates ISO 4217 — when Treasury Prime
adds wire support beyond USD, the receiver auto-supports it without
schema change. ``currency`` is verified to be a non-empty 3-letter
uppercase ISO 4217 code; non-conforming values fail-closed.

**Governance constraint.** No PII (no account/routing numbers, no
originator-address, no trace number, no company-entry-description),
no outbound, multi-currency normalized to minor-units in source
currency, HMAC SHA-256 auth via
:data:`TREASURY_PRIME_WEBHOOK_SECRET_ENV` env var. Validation,
signature, unknown-event, or shape failures fail-closed via
:class:`ReceiveOnlyRailError`.

cc-task: ``treasury-prime-receive-only-rail`` (Phase 0). Sibling
rails:
``shared/github_sponsors_receive_only_rail.py`` (#2218),
``shared/liberapay_receive_only_rail.py`` (#2219),
``shared/open_collective_receive_only_rail.py`` (#2226),
``shared/stripe_payment_link_receive_only_rail.py`` (#2227),
``shared/ko_fi_receive_only_rail.py`` (#2230),
``shared/patreon_receive_only_rail.py`` (#2231),
``shared/buy_me_a_coffee_receive_only_rail.py`` (#2234),
``shared/mercury_receive_only_rail.py`` (#2251), and
``shared/modern_treasury_receive_only_rail.py`` (#2255). Tenth rail
in the family — third direct-bank rail. Closes the Jr
currentness-scout packet's full Bank-as-API recommendation set.
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

TREASURY_PRIME_WEBHOOK_SECRET_ENV = "TREASURY_PRIME_WEBHOOK_SECRET"

_ISO_4217_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected Treasury Prime webhook payload.

    Raised on malformed payloads, unaccepted event kinds, HMAC SHA-256
    signature failures, missing fields, malformed currency codes,
    outgoing-direction events, or shape violations. The receiver
    never silently drops or partially-accepts an inbound event.
    """


class IncomingAchEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver.

    Phase 0 added ``incoming_ach.create`` — the ledger-account incoming
    ACH event (event-name-level direction filter; outgoing flows ride
    on a different event name).

    Phase 1 (this module) adds ``transaction.create`` — the core
    direct-account event that includes BOTH incoming and outgoing
    transactions. Direction filtering is applied at the data level via
    :func:`_extract_direction` (Mercury shape): only ``data.direction
    == "credit"`` is accepted; ``debit`` and unknown values fail-closed.
    """

    INCOMING_ACH_CREATED = "incoming_ach.create"
    TRANSACTION_CREATE = "transaction.create"


_ACCEPTED_KINDS: frozenset[str] = frozenset(k.value for k in IncomingAchEventKind)


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IncomingAchEvent(_RailModel):
    """Normalized, payer-aggregate Treasury Prime incoming ACH event.

    *No PII fields exist on this type.* ``originating_party_handle``
    is the Treasury Prime public ``originating_party_name`` (the
    display Treasury Prime already surfaces for the sender —
    equivalent in sensitivity to a GitHub login; *not* an account
    number, *not* a routing number, *not* an address, *not* a trace
    number, *not* a company-entry-description).
    ``amount_currency_cents`` is integer minor-units (cents) in the
    source currency named by ``currency``. ``currency`` is the ISO
    4217 3-letter uppercase code. ``raw_payload_sha256`` correlates
    this normalized event to the original webhook delivery without
    re-storing the raw payload.
    """

    originating_party_handle: str = Field(min_length=1, max_length=255)
    amount_currency_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    event_kind: IncomingAchEventKind
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

    Treasury Prime's signature header is ``X-Signature: <hexdigest>``.
    Some integrations / partner forwarders prefix the digest with
    ``sha256=`` (parity with the GitHub format); both that and a
    bare hex digest are accepted (the receiver strips the prefix if
    present). Comparison uses :func:`hmac.compare_digest` to avoid
    timing leaks. Mismatch raises :class:`ReceiveOnlyRailError`.
    """
    if not secret:
        raise ReceiveOnlyRailError(
            f"signature provided but {TREASURY_PRIME_WEBHOOK_SECRET_ENV} is not set"
        )
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    if not hmac.compare_digest(expected, candidate):
        raise ReceiveOnlyRailError("HMAC SHA-256 signature mismatch")


def _coerce_event_kind(payload: dict[str, Any]) -> IncomingAchEventKind:
    """Map Treasury Prime's ``event`` string to the rail's enum.

    Phase 0 accepts ``incoming_ach.create`` (ledger-account incoming);
    Phase 1 adds ``transaction.create`` (core direct accounts) — the
    latter requires the data-level direction filter applied below in
    :meth:`TreasuryPrimeRailReceiver.ingest_webhook` via
    :func:`_extract_direction`.

    Outgoing event names (``ach_origination.*`` / ``payment_order.*``)
    are rejected with a direction-specific message so the rejection
    is auditable.
    """
    raw_event = payload.get("event")
    if not isinstance(raw_event, str):
        raise ReceiveOnlyRailError(
            f"webhook 'event' must be a string, got {type(raw_event).__name__}"
        )
    if raw_event in _ACCEPTED_KINDS:
        return IncomingAchEventKind(raw_event)
    if raw_event.startswith("ach_origination.") or raw_event.startswith("payment_order."):
        raise ReceiveOnlyRailError(f"refusing outgoing event {raw_event!r} on receive-only rail")
    raise ReceiveOnlyRailError(f"unaccepted webhook event type {raw_event!r}")


_INCOMING_DIRECTIONS: frozenset[str] = frozenset({"credit", "incoming"})
_OUTGOING_DIRECTIONS: frozenset[str] = frozenset({"debit", "outgoing"})


def _extract_direction(txn: dict[str, Any], event_kind: IncomingAchEventKind) -> None:
    """Apply data-level direction filter for ``transaction.create`` events.

    For Phase 0 ``incoming_ach.create`` the event-name itself is the
    direction filter — this helper short-circuits and returns. For
    Phase 1 ``transaction.create`` (core direct accounts), Treasury
    Prime ships ``data.direction`` as ``"credit"`` (incoming to
    operator) or ``"debit"`` (outgoing). Mirrors Mercury's data-level
    direction filter.

    Outgoing directions raise with a direction-specific message;
    unknown values also fail closed (we do not silently accept
    un-categorized flows).
    """
    if event_kind is IncomingAchEventKind.INCOMING_ACH_CREATED:
        return  # event-name-level filter; no data-level check needed.
    raw_direction = txn.get("direction")
    if not isinstance(raw_direction, str) or not raw_direction:
        raise ReceiveOnlyRailError(
            "payload missing 'data.direction' on transaction.create "
            "(required for Phase 1 direction filter)"
        )
    direction = raw_direction.strip().lower()
    if direction in _INCOMING_DIRECTIONS:
        return
    if direction in _OUTGOING_DIRECTIONS:
        raise ReceiveOnlyRailError(
            f"refusing outgoing transaction direction {raw_direction!r} on receive-only rail"
        )
    raise ReceiveOnlyRailError(f"unknown transaction direction {raw_direction!r}")


def _payment_object(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the nested ``data`` object carrying payment fields."""
    candidate = payload.get("data")
    if isinstance(candidate, dict) and candidate:
        return candidate
    raise ReceiveOnlyRailError("payload missing 'data' object")


def _extract_originating_party_handle(payment: dict[str, Any]) -> str:
    """Extract Treasury Prime's public ``originating_party_name``."""
    handle = payment.get("originating_party_name")
    if not isinstance(handle, str) or not handle:
        raise ReceiveOnlyRailError("payload missing 'originating_party_name'")
    return handle


def _amount_to_cents(raw_amount: Any) -> int:
    """Normalize Treasury Prime amount shapes to integer cents.

    Treasury Prime's REST API ships amounts as integer minor-units;
    the receiver also accepts decimal-string forms for forward
    compatibility.
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

    Treasury Prime ships ``created_at`` on the payment object plus an
    optional top-level envelope ``created`` field. The receiver
    checks ``created_at`` first (most precise), then falls back to
    the envelope ``created``. ISO 8601 strings are accepted with
    optional ``Z`` UTC suffix.
    """
    raw = (
        payment.get("created_at")
        or payment.get("posted_at")
        or payload.get("occurred_at")
        or payload.get("created")
    )
    if not isinstance(raw, str) or not raw:
        raise ReceiveOnlyRailError("payload missing 'created_at' / 'posted_at' / 'created'")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiveOnlyRailError(f"invalid ISO 8601 timestamp {raw!r}: {exc}") from exc


class TreasuryPrimeRailReceiver:
    """Receive-only adapter for Treasury Prime ledger-account webhooks.

    Construction is cheap and side-effect-free. The single public
    method :meth:`ingest_webhook` validates payload shape, optionally
    verifies the HMAC SHA-256 signature against the *raw* request
    body bytes, filters direction via the event-kind allowlist, and
    returns a normalized :class:`IncomingAchEvent`. The receiver
    never opens a network socket, writes to disk, or contacts any
    external system.
    """

    def __init__(
        self,
        *,
        secret_env_var: str = TREASURY_PRIME_WEBHOOK_SECRET_ENV,
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
    ) -> IncomingAchEvent | None:
        """Validate + normalize a single Treasury Prime delivery.

        Returns the normalized :class:`IncomingAchEvent` for accepted
        ``incoming_ach.create`` deliveries. Raises
        :class:`ReceiveOnlyRailError` for malformed payloads,
        unaccepted event types (including outgoing
        ``ach_origination.*`` and the out-of-Phase-0
        ``transaction.create``), signature failures, or shape
        violations. Returns ``None`` only when the caller passes
        ``payload={}`` *and* ``signature=None``, which is treated as
        a no-op heartbeat ping (parity with sibling rails'
        empty-test-delivery handling).

        ``signature`` is the value of the ``X-Signature`` HTTP header
        (``None`` skips verification — only acceptable for tests /
        pre-flight pings; production callers must always pass it).
        ``raw_body`` is the raw HTTP body bytes Treasury Prime
        signed; if not provided, the receiver falls back to
        canonical-encoding the parsed payload for verification.
        Signature verification reads
        :data:`TREASURY_PRIME_WEBHOOK_SECRET_ENV` from the
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
        _extract_direction(payment, event_kind)
        originating_party_handle = _extract_originating_party_handle(payment)
        amount_cents, currency = _extract_amount_and_currency(payment)
        occurred_at = _extract_occurred_at(payload, payment)

        if self._idempotency_store is not None:
            ach_id = payment.get("id")
            if not isinstance(ach_id, str) or not ach_id:
                raise ReceiveOnlyRailError(
                    "idempotency_store provided but data.id missing — "
                    "Treasury Prime incoming_ach payloads carry the "
                    "per-delivery identifier in data.id"
                )
            try:
                if not self._idempotency_store.record_or_skip(ach_id):
                    return None
            except _SharedIdempotencyError as exc:
                raise ReceiveOnlyRailError(str(exc)) from exc

        try:
            return IncomingAchEvent(
                originating_party_handle=originating_party_handle,
                amount_currency_cents=amount_cents,
                currency=currency,
                event_kind=event_kind,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "TREASURY_PRIME_WEBHOOK_SECRET_ENV",
    "IdempotencyStore",
    "IncomingAchEvent",
    "IncomingAchEventKind",
    "ReceiveOnlyRailError",
    "TreasuryPrimeRailReceiver",
]
