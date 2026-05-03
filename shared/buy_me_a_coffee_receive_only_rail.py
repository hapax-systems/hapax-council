"""Buy Me a Coffee receive-only rail.

Phase 0 receiver for Buy Me a Coffee (BMaC) webhook events. Normalizes
inbound ``donation`` / ``membership.started`` / ``membership.cancelled``
/ ``extras_purchase`` deliveries into a typed, payer-aggregate
``CoffeeEvent`` — *without* calls, outbound writes, CRM, or
per-supporter relationship surfaces.

**Receive-only invariant.** This module never originates an outbound
network call, never writes to an external system, and never persists
PII. ``supporter_handle`` is the BMaC public ``supporter_name`` field
(the public display the supporter chose for attribution on the
operator's BMaC page; equivalent in sensitivity to a Ko-fi display name
or a GitHub login). Emails (``supporter_email``), free-text supporter
messages, the supporter's BMaC user ID, payment-method strings, and any
shipping/billing fields BMaC may surface for extras orders are
intentionally not extracted.

**No BMaC SDK.** This module deliberately does NOT import any Buy Me a
Coffee Python SDK or REST client. SDKs pull in HTTP client surfaces and
support outbound API calls — neither belongs in a receive-only rail.
HMAC SHA-256 verification per BMaC's documented ``X-Signature-Sha256``
header format is implemented inline using only ``hmac`` + ``hashlib``
from the standard library.

**HMAC SHA-256 wire format (matches GitHub Sponsors / Liberapay /
Stripe).** BMaC signs webhook deliveries with HMAC SHA-256 using the
per-webhook secret configured in the BMaC dashboard, with the
hexadecimal digest delivered in the case-insensitive
``X-Signature-Sha256`` HTTP header. The signature is computed over the
*raw* request body bytes — the upstream FastAPI handler is responsible
for capturing the raw body before JSON parsing and passing both the
parsed payload dict and the captured raw bytes into
:meth:`BuyMeACoffeeRailReceiver.ingest_webhook`. A bare hex digest
*and* the ``sha256=<hex>`` prefixed form are both accepted; mismatch
raises :class:`ReceiveOnlyRailError`.

This shape (HMAC SHA-256 over raw body + per-webhook secret env var)
restores the *signature*-bearing pattern from GitHub Sponsors /
Liberapay / Stripe Payment Link, distinguishing it from the
verification-token shape Ko-fi introduced (#2230) and the HMAC MD5
divergence Patreon required (#2231). It is the most common shape
across the family.

**BMaC envelope shape.** Live BMaC deliveries ship a JSON envelope of
the form::

    {
        "type": "donation"
            | "membership.started"
            | "membership.cancelled"
            | "extras_purchase",
        "live_mode": true,
        "attempt": 1,
        "created": "2026-05-02T12:00:00Z",
        "event_id": "<bmc-event-uuid>",
        "data": {
            "id": "<resource-id>",
            "supporter_name": "<public display name>",
            "amount": "5.00",
            "currency": "USD",
            "created_at": "2026-05-02T12:00:00Z",
            ...
        }
    }

The receiver reads ``type`` from the top-level envelope and the payer
fields (``supporter_name`` / ``amount`` / ``currency`` / ``created_at``)
from the nested ``data`` object. Some legacy / partner deliveries place
the payer fields under a ``response`` key instead of ``data`` (per
the publicly-documented Laravel webhook example); both keys are
accepted on ingest with ``data`` taking precedence when both are
present.

**Accepted event kinds (4).**

- ``donation`` — one-time tip / "Buy Me a Coffee" purchase.
- ``membership.started`` — new recurring membership begun.
- ``membership.cancelled`` — recurring membership terminated.
- ``extras_purchase`` — one-time purchase of an "Extra" (digital
  product or operator-fulfilled offering attached to the BMaC page).

Other event types BMaC may emit (``commission.created``,
``contribution.refund``, ``membership.level_updated``, etc.) are
rejected as *unaccepted-but-known*; entirely unknown strings are
rejected as *malformed*. Both raise :class:`ReceiveOnlyRailError`.

**Multi-currency.** BMaC is multi-currency-native: a single BMaC page
may receive support in USD, EUR, GBP, CAD, AUD, JPY, and the broader
ISO 4217 set BMaC supports. Like the Ko-fi / Open Collective / Stripe
Payment Link rails (and unlike the GitHub Sponsors USD-only / Liberapay
EUR-only rails), this receiver preserves the source currency on the
normalized event. The ``amount_currency_cents`` field is integer
minor-units (cents/pence/etc.) in the currency named by ``currency``.
BMaC sends amounts as decimal strings (e.g. ``"5.00"``, ``"12.50"``);
the receiver normalizes to integer minor-units via ``Decimal`` × 100,
rounded to integer. Zero-decimal currencies (JPY, KRW, VND, etc.) are
passed through as-is — the field is integer minor-units in the
currency-specific minor-unit definition. Downstream consumers are
responsible for any FX normalization. ``currency`` is verified to be a
non-empty 3-letter uppercase ISO 4217 code; non-conforming values
fail-closed.

**Governance constraint.** No PII, no outbound, multi-currency
normalized to lowest-unit cents in the source currency, HMAC SHA-256
auth via :data:`BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV` env var.
Validation, signature, or unknown-event failures fail-closed via
:class:`ReceiveOnlyRailError`.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0,
Buy Me a Coffee rail). Sibling rails:
``shared/github_sponsors_receive_only_rail.py`` (#2218),
``shared/liberapay_receive_only_rail.py`` (#2219),
``shared/open_collective_receive_only_rail.py`` (#2226),
``shared/stripe_payment_link_receive_only_rail.py`` (#2227),
``shared/ko_fi_receive_only_rail.py`` (#2230), and
``shared/patreon_receive_only_rail.py`` (#2231). Eighth rail in the
family. Restores the HMAC-SHA256-over-raw-body pattern (vs Ko-fi's
verification-token and Patreon's HMAC-MD5 divergences).
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

BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV = "BUY_ME_A_COFFEE_WEBHOOK_SECRET"

_ISO_4217_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected BMaC webhook payload.

    Raised on malformed payloads, unaccepted event kinds, HMAC SHA-256
    signature failures, missing fields, malformed currency codes, or
    shape violations. The receiver never silently drops or
    partially-accepts an inbound event.
    """


class CoffeeEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver.

    Values are the dotted-or-underscored forms BMaC ships on the wire
    in the top-level ``type`` field. Membership lifecycle events use
    BMaC's documented dotted form (``membership.started`` /
    ``membership.cancelled``); the one-time and extras events use
    underscored snake_case. Both forms are accepted as-is on ingest.
    """

    DONATION = "donation"
    MEMBERSHIP_STARTED = "membership.started"
    MEMBERSHIP_CANCELLED = "membership.cancelled"
    EXTRAS_PURCHASE = "extras_purchase"


_ACCEPTED_KINDS: frozenset[str] = frozenset(k.value for k in CoffeeEventKind)
_BMAC_KIND_ALIASES: dict[str, CoffeeEventKind] = {
    # BMaC has shipped historical aliases for the same logical events
    # (e.g. older deliveries sometimes use ``coffee_purchase`` for the
    # one-time donation event, ``membership_started`` underscored, and
    # ``extras.purchase`` dotted). Accept the documented aliases on
    # ingest; emit the canonical enum value on the normalized event.
    "coffee_purchase": CoffeeEventKind.DONATION,
    "Donation": CoffeeEventKind.DONATION,
    "membership_started": CoffeeEventKind.MEMBERSHIP_STARTED,
    "membership.created": CoffeeEventKind.MEMBERSHIP_STARTED,
    "membership_cancelled": CoffeeEventKind.MEMBERSHIP_CANCELLED,
    "membership.canceled": CoffeeEventKind.MEMBERSHIP_CANCELLED,
    "extras.purchase": CoffeeEventKind.EXTRAS_PURCHASE,
    "extras_purchased": CoffeeEventKind.EXTRAS_PURCHASE,
}


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CoffeeEvent(_RailModel):
    """Normalized, payer-aggregate BMaC event.

    *No PII fields exist on this type.* ``supporter_handle`` is the
    BMaC public ``supporter_name`` (the display name the supporter
    chose for public attribution on the operator's BMaC page —
    equivalent in sensitivity to a Ko-fi display name or a GitHub
    login; *not* an email and *not* a BMaC internal user ID).
    ``amount_currency_cents`` is integer minor-units (cents/pence/etc.)
    in the source currency named by ``currency``. ``currency`` is the
    ISO 4217 3-letter uppercase code. ``raw_payload_sha256`` is
    included so a downstream consumer can correlate this normalized
    event to the original webhook delivery without re-storing the raw
    payload (which contains free-text supporter messages, supporter
    emails, and other fields we do not want to persist beyond the
    receiver boundary).
    """

    supporter_handle: str = Field(min_length=1, max_length=255)
    amount_currency_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    event_kind: CoffeeEventKind
    occurred_at: datetime
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("supporter_handle")
    @classmethod
    def _handle_is_display_name_only(cls, value: str) -> str:
        """``supporter_handle`` must be a BMaC display name, not an email."""
        if "@" in value:
            raise ValueError("supporter_handle must be a BMaC display name, not an email address")
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

    BMaC's signature header is ``X-Signature-Sha256: <hexdigest>``.
    Some integrations / partner forwarders prefix the digest with
    ``sha256=`` (parity with the GitHub format); both that and a bare
    hex digest are accepted (the receiver strips the prefix if
    present). Comparison uses :func:`hmac.compare_digest` to avoid
    timing leaks. Mismatch raises :class:`ReceiveOnlyRailError`.

    The signature is computed over the *raw* HTTP body bytes — the
    upstream FastAPI handler MUST capture the raw body before JSON
    parsing and pass it here. Re-encoding the parsed dict would not
    necessarily reproduce the byte sequence BMaC signed (key ordering,
    whitespace) and the verification would spuriously fail.
    """
    if not secret:
        raise ReceiveOnlyRailError(
            f"signature provided but {BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV} is not set"
        )
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    if not hmac.compare_digest(expected, candidate):
        raise ReceiveOnlyRailError("HMAC SHA-256 signature mismatch")


def _coerce_kind(raw_kind: Any) -> CoffeeEventKind:
    """Map BMaC's ``type`` string to our enum or raise."""
    if not isinstance(raw_kind, str):
        raise ReceiveOnlyRailError(
            f"webhook 'type' must be a string, got {type(raw_kind).__name__}"
        )
    if raw_kind in _ACCEPTED_KINDS:
        return CoffeeEventKind(raw_kind)
    if raw_kind in _BMAC_KIND_ALIASES:
        return _BMAC_KIND_ALIASES[raw_kind]
    raise ReceiveOnlyRailError(f"unaccepted webhook event type {raw_kind!r}")


def _payer_object(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the nested object carrying payer fields.

    BMaC's documented production envelope nests payer fields under
    ``data``; some legacy / partner-forwarded deliveries use
    ``response`` (per the publicly-documented Laravel example).
    Accept both with ``data`` taking precedence.
    """
    for key in ("data", "response"):
        candidate = payload.get(key)
        if isinstance(candidate, dict) and candidate:
            return candidate
    raise ReceiveOnlyRailError("payload missing 'data' / 'response' object")


def _extract_supporter_handle(payer: dict[str, Any]) -> str:
    """Extract BMaC's public ``supporter_name`` display.

    Anonymous supporters appear with ``supporter_name`` set to
    ``"Anonymous"`` by BMaC's webhook contract — that string passes
    through as the canonical aggregate handle for unattributed support
    (it is not an email and not personally identifying).
    """
    handle = payer.get("supporter_name")
    if not isinstance(handle, str) or not handle:
        raise ReceiveOnlyRailError("payload missing 'supporter_name'")
    return handle


def _extract_amount_and_currency(payer: dict[str, Any]) -> tuple[int, str]:
    """Extract minor-unit amount + ISO 4217 currency from the delivery.

    BMaC sends amounts as decimal strings in the major unit (e.g.
    ``"5.00"``, ``"12.50"``). The receiver normalizes via ``Decimal``
    × 100 (rounded to integer) so floating-point error never enters
    the cents field. Currency is sent as the ISO 4217 3-letter code
    (BMaC typically emits uppercase already, but the receiver
    normalizes upward defensively).

    Negative amounts are converted to absolute value so the rail
    expresses gross movement; net flow is reconstructed by event_kind
    downstream (consistent with the Ko-fi / Stripe / Open Collective
    rails).
    """
    raw_amount = payer.get("amount")
    if raw_amount is None:
        raise ReceiveOnlyRailError("payload missing 'amount'")
    if isinstance(raw_amount, bool):
        # bool is a subclass of int in Python; reject explicitly.
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

    raw_currency = payer.get("currency")
    if not isinstance(raw_currency, str) or not raw_currency:
        raise ReceiveOnlyRailError("payload missing 'currency'")

    cents = int((decimal_amount.copy_abs() * 100).to_integral_value())
    return cents, raw_currency.upper()


def _extract_occurred_at(payload: dict[str, Any], payer: dict[str, Any]) -> datetime:
    """Extract the delivery timestamp.

    BMaC ships a top-level ``created`` field on the envelope and a
    nested ``created_at`` on the payer object; some deliveries also
    carry ``support_created_on`` (legacy field per the publicly
    documented Laravel example). The receiver checks the nested
    payer keys first (most precise), then falls back to the envelope
    ``created``. ISO 8601 strings are accepted with optional ``Z``
    UTC suffix.
    """
    raw = (
        payer.get("created_at")
        or payer.get("support_created_on")
        or payload.get("created")
        or payload.get("occurred_at")
    )
    if not isinstance(raw, str) or not raw:
        raise ReceiveOnlyRailError(
            "payload missing 'created_at' / 'support_created_on' / 'created'"
        )
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiveOnlyRailError(f"invalid ISO 8601 timestamp {raw!r}: {exc}") from exc


class BuyMeACoffeeRailReceiver:
    """Receive-only adapter for Buy Me a Coffee webhooks.

    Construction is cheap and side-effect-free. The single public
    method :meth:`ingest_webhook` validates payload shape, optionally
    verifies the HMAC SHA-256 signature against the *raw* request body
    bytes, and returns a normalized :class:`CoffeeEvent`. The receiver
    never opens a network socket, writes to disk, or contacts any
    external system.
    """

    def __init__(
        self,
        *,
        secret_env_var: str = BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV,
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
    ) -> CoffeeEvent | None:
        """Validate + normalize a single BMaC webhook delivery.

        Returns the normalized :class:`CoffeeEvent` for accepted
        deliveries. Raises :class:`ReceiveOnlyRailError` for malformed
        payloads, unaccepted event types, or signature failures.
        Returns ``None`` only when the caller passes ``payload={}``
        *and* ``signature=None``, which is treated as a no-op heartbeat
        ping (parity with sibling rails' empty-test-delivery handling).

        ``signature`` is the value of the ``X-Signature-Sha256`` HTTP
        header (None to skip verification — only acceptable for tests
        / pre-flight pings; production callers must always pass it).
        ``raw_body`` is the raw HTTP body bytes BMaC signed; if not
        provided, the receiver falls back to canonical-encoding the
        parsed payload for verification, which works for round-trip
        test fixtures but may spuriously fail against live BMaC
        deliveries — pass the raw bytes whenever they're available.
        Signature verification reads
        :data:`BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV` from the
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

        event_kind = _coerce_kind(payload.get("type"))
        payer = _payer_object(payload)
        supporter_handle = _extract_supporter_handle(payer)
        amount_cents, currency = _extract_amount_and_currency(payer)
        occurred_at = _extract_occurred_at(payload, payer)

        if self._idempotency_store is not None:
            event_id = payload.get("event_id")
            if not isinstance(event_id, str) or not event_id:
                raise ReceiveOnlyRailError(
                    "idempotency_store provided but payload missing top-level 'event_id' "
                    "(BMaC's per-delivery UUID; required for dedup keying)"
                )
            try:
                if not self._idempotency_store.record_or_skip(event_id):
                    return None
            except _SharedIdempotencyError as exc:
                raise ReceiveOnlyRailError(str(exc)) from exc

        try:
            return CoffeeEvent(
                supporter_handle=supporter_handle,
                amount_currency_cents=amount_cents,
                currency=currency,
                event_kind=event_kind,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "BUY_ME_A_COFFEE_WEBHOOK_SECRET_ENV",
    "BuyMeACoffeeRailReceiver",
    "CoffeeEvent",
    "CoffeeEventKind",
    "IdempotencyStore",
    "ReceiveOnlyRailError",
]
