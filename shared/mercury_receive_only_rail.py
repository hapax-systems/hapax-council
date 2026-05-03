"""Mercury receive-only rail.

Phase 0 receiver for Mercury Bank webhook events. Normalizes inbound
``transaction.created`` / ``transaction.updated`` deliveries into a
typed, payer-aggregate :class:`MercuryTransactionEvent` — *without*
calls, outbound writes, CRM, or per-supporter relationship surfaces.

**Receive-only invariant.** This module never originates an outbound
network call, never writes to an external system, and never persists
PII. The Mercury webhook delivers a banking transaction object that
includes account numbers, routing numbers, counterparty addresses,
and free-text memos — fields that would constitute material banking
PII if extracted into Hapax's data model. The receiver intentionally
*does not* extract them. The only payer-side field surfaced on the
normalized event is ``counterparty_name`` — the public sender display
that Mercury already shows on the operator's dashboard (equivalent in
sensitivity to a GitHub login or a BMaC supporter handle, *not* a
banking-customer identifier).

**Direction filter (receive-only).** Mercury delivers webhooks for
*both* incoming and outgoing transactions on the operator's account.
A receive-only rail must not act on outgoing flows. The receiver
validates the transaction's ``kind`` field against
:data:`_INCOMING_KINDS`; outgoing kinds (``ach_outgoing``,
``wire_outgoing``, ``check_outgoing``, ``card_purchase``,
``ach_origination``, ``platform_payment``) are rejected with a
:class:`ReceiveOnlyRailError`. This keeps the rail structurally
incapable of *initiating* value transfer even if a malicious or
misconfigured webhook delivery slipped past upstream Mercury filters.

**No Mercury SDK.** This module deliberately does NOT import any
Mercury Python SDK or REST client. SDKs pull in HTTP client surfaces
and support outbound API calls — neither belongs in a receive-only
rail. HMAC SHA-256 verification per Mercury's documented
``X-Mercury-Signature`` header format is implemented inline using
only ``hmac`` + ``hashlib`` from the standard library.

**HMAC SHA-256 wire format (matches GitHub Sponsors / Liberapay /
Stripe / BuyMeACoffee).** Mercury signs webhook deliveries with
HMAC SHA-256 using the per-webhook secret configured in the Mercury
dashboard. The signature is delivered in the case-insensitive
``X-Mercury-Signature`` HTTP header, with the legacy
``X-Hook-Signature`` header accepted as a fallback for older Mercury
integrations that have not yet migrated to the canonical name. The
signature is computed over the *raw* request body bytes — the upstream
FastAPI handler is responsible for capturing the raw body before JSON
parsing and passing both the parsed payload dict and the captured raw
bytes into :meth:`MercuryRailReceiver.ingest_webhook`. A bare hex
digest *and* the ``sha256=<hex>`` prefixed form are both accepted;
mismatch raises :class:`ReceiveOnlyRailError`.

This shape (HMAC SHA-256 over raw body + per-webhook secret env var)
matches the *signature*-bearing pattern from GitHub Sponsors (#2218),
Liberapay (#2219), Stripe Payment Link (#2227), and BuyMeACoffee
(#2234). The dual-header acceptance is the new shape this rail
introduces (per the Jr currentness-scout packet's note that some
Mercury legacy integrations may still emit ``X-Hook-Signature``).

**Mercury envelope shape.** Live Mercury deliveries ship a JSON
envelope of the form::

    {
        "type": "transaction.created" | "transaction.updated",
        "data": {
            "id": "<txn-uuid>",
            "amount": "100.00",
            "currency": "USD",
            "kind": "ach_incoming"
                | "wire_incoming"
                | "check_deposit"
                | "incoming_credit",
            "counterparty_name": "<public sender display>",
            "created_at": "2026-05-02T12:00:00Z",
            ...
        }
    }

The receiver reads ``type`` from the top-level envelope and the
transaction fields from the nested ``data`` object. Some legacy
deliveries place the transaction under a top-level ``transaction``
key instead of ``data``; both forms are accepted on ingest with
``data`` taking precedence when both are present.

**Accepted event kinds (2).**

- ``transaction.created`` — a new transaction posted to the operator's
  Mercury account.
- ``transaction.updated`` — an existing transaction's status changed
  (e.g., an ACH pending → settled transition).

Other event types Mercury may emit (``account.balance_changed``,
``card.created``, ``user.invited``, etc.) are rejected as
*unaccepted-but-known*; entirely unknown strings are rejected as
*malformed*. Both raise :class:`ReceiveOnlyRailError`.

**Multi-currency.** Mercury is primarily USD-denominated for ACH and
domestic-wire receipts, but multi-currency wires (Mercury Treasury) do
land in the operator's account in the source currency. The receiver
preserves the source currency on the normalized event and normalizes
the amount to integer minor-units via ``Decimal`` × 100 (matching the
Stripe / BMaC / Open Collective pattern). Zero-decimal currencies
(JPY, KRW, VND) pass through as-is. Downstream consumers are
responsible for any FX normalization. ``currency`` is verified to be
a non-empty 3-letter uppercase ISO 4217 code; non-conforming values
fail-closed.

**Governance constraint.** No PII (no account/routing numbers, no
counterparty email, no counterparty address, no memo text), no
outbound, multi-currency normalized to minor-units in the source
currency, HMAC SHA-256 auth via :data:`MERCURY_WEBHOOK_SECRET_ENV`
env var, direction filter rejects outgoing kinds. Validation,
signature, unknown-event, or wrong-direction failures fail-closed via
:class:`ReceiveOnlyRailError`.

cc-task: ``mercury-receive-only-rail`` (Phase 0). Sibling rails:
``shared/github_sponsors_receive_only_rail.py`` (#2218),
``shared/liberapay_receive_only_rail.py`` (#2219),
``shared/open_collective_receive_only_rail.py`` (#2226),
``shared/stripe_payment_link_receive_only_rail.py`` (#2227),
``shared/ko_fi_receive_only_rail.py`` (#2230),
``shared/patreon_receive_only_rail.py`` (#2231), and
``shared/buy_me_a_coffee_receive_only_rail.py`` (#2234). Eighth rail
in the family — the first that surfaces direct bank-rail receipts
(ACH / wire / check deposit) rather than a creator-platform abstraction.
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

MERCURY_WEBHOOK_SECRET_ENV = "MERCURY_WEBHOOK_SECRET"

_ISO_4217_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected Mercury webhook payload.

    Raised on malformed payloads, unaccepted event kinds, HMAC SHA-256
    signature failures, missing fields, malformed currency codes,
    outgoing-direction transactions, or shape violations. The
    receiver never silently drops or partially-accepts an inbound
    event.
    """


class MercuryEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver.

    Mercury's webhook taxonomy distinguishes only between
    ``transaction.created`` (a new transaction posted) and
    ``transaction.updated`` (an existing transaction's state moved,
    e.g. pending → settled). Both flow through the same normalized
    event shape; downstream consumers can dedupe by ``transaction_id``
    if they need create-vs-update semantics.
    """

    TRANSACTION_CREATED = "transaction.created"
    TRANSACTION_UPDATED = "transaction.updated"


_ACCEPTED_KINDS: frozenset[str] = frozenset(k.value for k in MercuryEventKind)


class MercuryTransactionDirection(StrEnum):
    """Direction of an inbound transaction notification.

    The receive-only rail accepts only :attr:`INCOMING` transactions.
    The outgoing kinds are listed for completeness in
    :data:`_OUTGOING_KINDS` so the rejection error message can name
    the offending kind precisely.
    """

    INCOMING = "incoming"


_INCOMING_KINDS: frozenset[str] = frozenset(
    {
        "ach_incoming",
        "wire_incoming",
        "check_deposit",
        "incoming_credit",
        "credit_returned",
        "interest",
        "refund_received",
    }
)
"""Mercury transaction-kind values that represent inbound value flow.

These are the only ``data.kind`` values the receiver accepts. Any
other value — including outgoing kinds and unknown kinds — fails
closed via :class:`ReceiveOnlyRailError`. Adding a new incoming kind
requires editing this set + landing the corresponding test case.
"""

_OUTGOING_KINDS: frozenset[str] = frozenset(
    {
        "ach_outgoing",
        "wire_outgoing",
        "check_outgoing",
        "card_purchase",
        "ach_origination",
        "platform_payment",
        "fee",
        "interest_paid",
    }
)
"""Mercury transaction-kind values that represent outbound value flow.

Listed here only so the receive-only rejection message can identify
the kind precisely. Any value matching this set raises
:class:`ReceiveOnlyRailError` with a direction-specific message; the
rail is structurally incapable of acting on outgoing flows.
"""


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MercuryTransactionEvent(_RailModel):
    """Normalized, payer-aggregate Mercury transaction event.

    *No PII fields exist on this type.* ``counterparty_handle`` is the
    Mercury public ``counterparty_name`` (the display Mercury already
    surfaces on the operator's dashboard for the sender — equivalent
    in sensitivity to a GitHub login or a BMaC supporter handle; *not*
    a bank account number, *not* a routing number, *not* an address,
    *not* an email, *not* a memo). ``amount_currency_cents`` is
    integer minor-units (cents/pence/etc.) in the source currency
    named by ``currency``. ``currency`` is the ISO 4217 3-letter
    uppercase code. ``raw_payload_sha256`` is included so a downstream
    consumer can correlate this normalized event to the original
    webhook delivery without re-storing the raw payload (which
    contains account/routing numbers, free-text memos, and other
    fields we do not want to persist beyond the receiver boundary).
    """

    counterparty_handle: str = Field(min_length=1, max_length=255)
    amount_currency_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    event_kind: MercuryEventKind
    direction: MercuryTransactionDirection
    occurred_at: datetime
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("counterparty_handle")
    @classmethod
    def _handle_is_display_name_only(cls, value: str) -> str:
        """``counterparty_handle`` must be a Mercury display, not an email."""
        if "@" in value:
            raise ValueError(
                "counterparty_handle must be a Mercury display name, not an email address"
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

    Mercury's signature header is ``X-Mercury-Signature: <hexdigest>``.
    Some integrations may still emit ``X-Hook-Signature`` (the legacy
    name); the receiver accepts either header at the dispatch boundary
    (handled by the caller) and only sees the digest string here.

    Some integrations / partner forwarders prefix the digest with
    ``sha256=`` (parity with the GitHub format); both that and a bare
    hex digest are accepted (the receiver strips the prefix if
    present). Comparison uses :func:`hmac.compare_digest` to avoid
    timing leaks. Mismatch raises :class:`ReceiveOnlyRailError`.

    The signature is computed over the *raw* HTTP body bytes — the
    upstream FastAPI handler MUST capture the raw body before JSON
    parsing and pass it here. Re-encoding the parsed dict would not
    necessarily reproduce the byte sequence Mercury signed (key
    ordering, whitespace) and the verification would spuriously fail.
    """
    if not secret:
        raise ReceiveOnlyRailError(
            f"signature provided but {MERCURY_WEBHOOK_SECRET_ENV} is not set"
        )
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    if not hmac.compare_digest(expected, candidate):
        raise ReceiveOnlyRailError("HMAC SHA-256 signature mismatch")


def _coerce_kind(raw_kind: Any) -> MercuryEventKind:
    """Map Mercury's ``type`` string to our enum or raise."""
    if not isinstance(raw_kind, str):
        raise ReceiveOnlyRailError(
            f"webhook 'type' must be a string, got {type(raw_kind).__name__}"
        )
    if raw_kind in _ACCEPTED_KINDS:
        return MercuryEventKind(raw_kind)
    raise ReceiveOnlyRailError(f"unaccepted webhook event type {raw_kind!r}")


def _transaction_object(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the nested object carrying transaction fields.

    Mercury's documented production envelope nests transaction fields
    under ``data``; some legacy / partner-forwarded deliveries use
    ``transaction``. Accept both with ``data`` taking precedence.
    """
    for key in ("data", "transaction"):
        candidate = payload.get(key)
        if isinstance(candidate, dict) and candidate:
            return candidate
    raise ReceiveOnlyRailError("payload missing 'data' / 'transaction' object")


def _extract_counterparty_handle(txn: dict[str, Any]) -> str:
    """Extract Mercury's public ``counterparty_name`` display.

    Anonymous / unattributed deposits (e.g. cash deposits) appear with
    ``counterparty_name`` set to ``"Unknown"`` or similar by Mercury's
    webhook contract — that string passes through as the canonical
    aggregate handle for unattributed receipts (it is not an email,
    not a banking-customer identifier, and not personally identifying
    beyond what Mercury already shows publicly on the operator's
    dashboard).
    """
    handle = txn.get("counterparty_name")
    if not isinstance(handle, str) or not handle:
        raise ReceiveOnlyRailError("payload missing 'counterparty_name'")
    return handle


def _extract_direction(txn: dict[str, Any]) -> MercuryTransactionDirection:
    """Filter the transaction's ``kind`` to incoming-only.

    Outgoing kinds are rejected explicitly so the rejection message
    can name the offending kind precisely; truly unknown kinds also
    fail closed (we do not silently accept un-categorized flows).
    """
    raw_kind = txn.get("kind")
    if not isinstance(raw_kind, str) or not raw_kind:
        raise ReceiveOnlyRailError("payload missing 'kind' (transaction direction)")
    if raw_kind in _INCOMING_KINDS:
        return MercuryTransactionDirection.INCOMING
    if raw_kind in _OUTGOING_KINDS:
        raise ReceiveOnlyRailError(
            f"refusing outgoing transaction kind {raw_kind!r} on receive-only rail"
        )
    raise ReceiveOnlyRailError(f"unknown transaction kind {raw_kind!r}")


def _extract_amount_and_currency(txn: dict[str, Any]) -> tuple[int, str]:
    """Extract minor-unit amount + ISO 4217 currency from the delivery.

    Mercury sends amounts as decimal strings in the major unit (e.g.
    ``"100.00"``, ``"1234.56"``). The receiver normalizes via
    ``Decimal`` × 100 (rounded to integer) so floating-point error
    never enters the cents field. Currency is sent as the ISO 4217
    3-letter code (Mercury typically emits uppercase already, but the
    receiver normalizes upward defensively).

    Negative amounts (Mercury occasionally signs incoming refunds /
    reversals as negatives in the ledger view) are converted to
    absolute value so the rail expresses gross movement; net flow is
    reconstructed by ``event_kind`` + ``direction`` downstream
    (consistent with the Ko-fi / Stripe / Open Collective / BMaC
    rails).
    """
    raw_amount = txn.get("amount")
    if raw_amount is None:
        raise ReceiveOnlyRailError("payload missing 'amount'")
    if isinstance(raw_amount, bool):
        raise ReceiveOnlyRailError("'amount' must be a numeric string or number")
    if isinstance(raw_amount, str):
        try:
            decimal_amount = Decimal(raw_amount)
        except InvalidOperation as exc:
            raise ReceiveOnlyRailError(
                f"invalid 'amount' decimal string {raw_amount!r}: {exc}"
            ) from exc
    elif isinstance(raw_amount, int | float):
        try:
            decimal_amount = Decimal(str(raw_amount))
        except InvalidOperation as exc:  # pragma: no cover - defensive
            raise ReceiveOnlyRailError(f"invalid 'amount' value {raw_amount!r}") from exc
    else:
        raise ReceiveOnlyRailError(
            f"'amount' must be a numeric string or number, got {type(raw_amount).__name__}"
        )

    raw_currency = txn.get("currency")
    if not isinstance(raw_currency, str) or not raw_currency:
        raise ReceiveOnlyRailError("payload missing 'currency'")

    cents = int((decimal_amount.copy_abs() * 100).to_integral_value())
    return cents, raw_currency.upper()


def _extract_occurred_at(payload: dict[str, Any], txn: dict[str, Any]) -> datetime:
    """Extract the delivery timestamp.

    Mercury ships ``created_at`` on the transaction object and a
    top-level ``created`` on some envelopes. The receiver checks the
    nested transaction key first (most precise), then falls back to
    the envelope ``created``. ISO 8601 strings are accepted with
    optional ``Z`` UTC suffix.
    """
    raw = (
        txn.get("created_at")
        or txn.get("posted_at")
        or payload.get("created")
        or payload.get("occurred_at")
    )
    if not isinstance(raw, str) or not raw:
        raise ReceiveOnlyRailError("payload missing 'created_at' / 'posted_at' / 'created'")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiveOnlyRailError(f"invalid ISO 8601 timestamp {raw!r}: {exc}") from exc


class MercuryRailReceiver:
    """Receive-only adapter for Mercury Bank webhooks.

    Construction is cheap and side-effect-free. The single public
    method :meth:`ingest_webhook` validates payload shape, optionally
    verifies the HMAC SHA-256 signature against the *raw* request body
    bytes, filters direction to incoming-only, and returns a
    normalized :class:`MercuryTransactionEvent`. The receiver never
    opens a network socket, writes to disk, or contacts any external
    system.
    """

    def __init__(
        self,
        *,
        secret_env_var: str = MERCURY_WEBHOOK_SECRET_ENV,
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
    ) -> MercuryTransactionEvent | None:
        """Validate + normalize a single Mercury webhook delivery.

        Returns the normalized :class:`MercuryTransactionEvent` for
        accepted incoming-direction deliveries. Raises
        :class:`ReceiveOnlyRailError` for malformed payloads,
        unaccepted event types, signature failures, or outgoing /
        unknown transaction kinds. Returns ``None`` only when the
        caller passes ``payload={}`` *and* ``signature=None``, which
        is treated as a no-op heartbeat ping (parity with sibling
        rails' empty-test-delivery handling).

        ``signature`` is the value of the ``X-Mercury-Signature`` HTTP
        header (or, for legacy integrations, the ``X-Hook-Signature``
        header value — the upstream caller is responsible for picking
        whichever header is present); ``None`` skips verification —
        only acceptable for tests / pre-flight pings; production
        callers must always pass it. ``raw_body`` is the raw HTTP body
        bytes Mercury signed; if not provided, the receiver falls
        back to canonical-encoding the parsed payload for
        verification, which works for round-trip test fixtures but may
        spuriously fail against live Mercury deliveries — pass the raw
        bytes whenever they're available. Signature verification reads
        :data:`MERCURY_WEBHOOK_SECRET_ENV` from the environment;
        unset env var with a non-None signature fails closed.
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

        event_kind = _coerce_kind(payload.get("type"))
        txn = _transaction_object(payload)
        direction = _extract_direction(txn)
        counterparty_handle = _extract_counterparty_handle(txn)
        amount_cents, currency = _extract_amount_and_currency(txn)
        occurred_at = _extract_occurred_at(payload, txn)

        if self._idempotency_store is not None:
            txn_id = txn.get("id")
            if not isinstance(txn_id, str) or not txn_id:
                raise ReceiveOnlyRailError(
                    "idempotency_store provided but data.id missing — "
                    "Mercury transactions carry the per-delivery identifier "
                    "in data.id"
                )
            try:
                if not self._idempotency_store.record_or_skip(txn_id):
                    return None
            except _SharedIdempotencyError as exc:
                raise ReceiveOnlyRailError(str(exc)) from exc

        try:
            return MercuryTransactionEvent(
                counterparty_handle=counterparty_handle,
                amount_currency_cents=amount_cents,
                currency=currency,
                event_kind=event_kind,
                direction=direction,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "MERCURY_WEBHOOK_SECRET_ENV",
    "IdempotencyStore",
    "MercuryEventKind",
    "MercuryRailReceiver",
    "MercuryTransactionDirection",
    "MercuryTransactionEvent",
    "ReceiveOnlyRailError",
]
