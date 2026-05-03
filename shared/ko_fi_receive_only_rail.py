"""Ko-fi receive-only rail.

Phase 0 receiver for Ko-fi webhook events. Normalizes inbound
``Donation`` / ``Subscription`` / ``Commission`` / ``Shop Order``
deliveries into a typed, payer-aggregate ``KoFiEvent`` — *without*
calls, outbound writes, CRM, or per-supporter relationship surfaces.

**Receive-only invariant.** This module never originates an outbound
network call, never writes to an external system, and never persists
PII. ``sender_handle`` is the Ko-fi public handle (``from_name`` field;
the public display the supporter chose to use on Ko-fi); emails,
shipping addresses, free-text messages, payment methods, and Ko-fi
user IDs (``kofi_transaction_id`` aside) are intentionally not
extracted. Per Ko-fi's webhook contract the donor display name is the
*public* attribution shown on the operator's Ko-fi page — equivalent in
sensitivity to a GitHub login or Open Collective slug.

**Ko-fi webhook product.** Ko-fi ships a single configured webhook URL
per Ko-fi page (`https://help.ko-fi.com/hc/en-us/articles/360004162298`).
Deliveries are POSTed as ``application/x-www-form-urlencoded`` with a
single ``data`` field whose value is a JSON string carrying the event
envelope. The upstream FastAPI handler is responsible for parsing the
form body and the inner JSON; this receiver's
:meth:`KoFiRailReceiver.ingest_webhook` accepts the already-parsed
``data`` JSON object as a Python ``dict``.

**Verification token (NOT HMAC).** Unlike the GitHub Sponsors,
Liberapay, Open Collective, and Stripe Payment Link rails — all of
which use HMAC SHA-256 signature headers (Stripe additionally a
timestamped header with replay tolerance) — Ko-fi does **not** sign
its webhook payloads. Instead, every delivery includes a
``verification_token`` field whose value the receiver compares against
a static token configured per-page in the Ko-fi dashboard. The token
is read from ``KO_FI_WEBHOOK_VERIFICATION_TOKEN`` (``os.environ.get``;
never hardcoded) and matched with :func:`hmac.compare_digest` to avoid
timing leaks. This shape is the NEW invariant this rail introduces vs
the prior four rails — token-based auth replaces signature
verification, with no replay protection (Ko-fi does not include a
timestamp in the auth-bearing field).

**Accepted event kinds.**

- ``donation`` — one-off tip / "Buy Me A Coffee" style support.
- ``subscription`` — monthly recurring supporter contribution
  ("Ko-fi Gold" / page subscription tier).
- ``commission`` — operator-fulfilled commission settled through
  Ko-fi's commission product.
- ``shop_order`` — purchase of a digital or physical product from the
  operator's Ko-fi Shop.

Other event types Ko-fi may emit (``Membership``, etc., or future
additions) are rejected as *unaccepted-but-known*; entirely unknown
strings are rejected as *malformed*. Both raise
:class:`ReceiveOnlyRailError`.

**Multi-currency.** Ko-fi is multi-currency-native: a single Ko-fi
page may receive support in USD, EUR, GBP, CAD, AUD, JPY, and the
broader set Ko-fi supports. Like the Open Collective and Stripe
Payment Link rails (and unlike the GitHub Sponsors USD-only / Liberapay
EUR-only rails), this receiver preserves the source currency on the
normalized event. The ``amount_currency_cents`` field is integer
minor-units (cents/pence/etc.) in the currency named by ``currency``.
Ko-fi sends amounts as decimal strings (e.g. ``"5.00"``,
``"12.50"``); the receiver normalizes to integer minor-units via
``Decimal`` × 100, rounded to integer. Zero-decimal currencies (JPY,
KRW, VND, etc.) are passed through as-is — the field is integer
minor-units in the currency-specific minor-unit definition. Downstream
consumers are responsible for any FX normalization. ``currency`` is
verified to be a non-empty 3-letter uppercase ISO 4217 code;
non-conforming values fail-closed.

**Governance constraint.** No PII, no outbound, multi-currency
normalized to lowest-unit cents in the source currency,
verification-token-based auth (NOT HMAC like the four prior rails).
Validation, token, or unknown-event failures fail-closed via
:class:`ReceiveOnlyRailError`.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0,
Ko-fi rail). Sibling rails:
``shared/github_sponsors_receive_only_rail.py`` (#2218),
``shared/liberapay_receive_only_rail.py`` (#2219),
``shared/open_collective_receive_only_rail.py`` (#2226), and
``shared/stripe_payment_link_receive_only_rail.py`` (#2227).
Verification-token auth (in lieu of HMAC) is the new shape this rail
introduces vs the prior four.
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

KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV = "KO_FI_WEBHOOK_VERIFICATION_TOKEN"

_ISO_4217_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected Ko-fi webhook payload.

    Raised on malformed payloads, unaccepted event kinds, verification
    token failures, missing fields, malformed currency codes, or shape
    violations. The receiver never silently drops or partially-accepts
    an inbound event.
    """


class KoFiEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver."""

    DONATION = "donation"
    SUBSCRIPTION = "subscription"
    COMMISSION = "commission"
    SHOP_ORDER = "shop_order"


_ACCEPTED_KINDS: frozenset[str] = frozenset(k.value for k in KoFiEventKind)
_KO_FI_KIND_ALIASES: dict[str, KoFiEventKind] = {
    # Ko-fi emits human-readable ``type`` strings ("Donation", "Subscription",
    # "Commission", "Shop Order") in production. Both the Ko-fi-shipped form
    # and the underscored canonical form are accepted on ingest.
    "Donation": KoFiEventKind.DONATION,
    "Subscription": KoFiEventKind.SUBSCRIPTION,
    "Commission": KoFiEventKind.COMMISSION,
    "Shop Order": KoFiEventKind.SHOP_ORDER,
}


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KoFiEvent(_RailModel):
    """Normalized, payer-aggregate Ko-fi event.

    *No PII fields exist on this type.* ``sender_handle`` is the Ko-fi
    public ``from_name`` (the display name the supporter chose for
    public attribution on the operator's Ko-fi page — equivalent in
    sensitivity to a GitHub login or Open Collective slug; *not* an
    email and *not* a Ko-fi internal user ID). ``amount_currency_cents``
    is integer minor-units (cents/pence/etc.) in the source currency
    named by ``currency``. ``currency`` is the ISO 4217 3-letter
    uppercase code. ``raw_payload_sha256`` is included so a downstream
    consumer can correlate this normalized event to the original
    webhook delivery without re-storing the raw payload (which contains
    free-text supporter messages, shipping addresses for shop orders,
    email if marketing-opt-in was provided, and other fields we do not
    want to persist beyond the receiver boundary).
    """

    sender_handle: str = Field(min_length=1, max_length=255)
    amount_currency_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    event_kind: KoFiEventKind
    occurred_at: datetime
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("sender_handle")
    @classmethod
    def _handle_is_display_name_only(cls, value: str) -> str:
        """``sender_handle`` must be a Ko-fi display name, not an email."""
        if "@" in value:
            raise ValueError("sender_handle must be a Ko-fi display name, not an email address")
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


def _verify_token(payload: dict[str, Any], expected_token: str) -> None:
    """Fail-closed verification-token check.

    Ko-fi does not sign its webhook payloads. Each delivery carries a
    ``verification_token`` field whose value must match the per-page
    static token configured in the Ko-fi dashboard. Comparison uses
    :func:`hmac.compare_digest` to avoid timing leaks even though the
    token is not a cryptographic signature.

    Raises :class:`ReceiveOnlyRailError` if the env-var token is unset,
    if the payload omits ``verification_token``, or if the values
    mismatch.
    """
    if not expected_token:
        raise ReceiveOnlyRailError(
            f"verification token requested but {KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV} is not set"
        )
    candidate = payload.get("verification_token")
    if not isinstance(candidate, str) or not candidate:
        raise ReceiveOnlyRailError("payload missing 'verification_token' field")
    if not hmac.compare_digest(expected_token, candidate):
        raise ReceiveOnlyRailError("Ko-fi verification_token mismatch")


def _coerce_kind(raw_kind: Any) -> KoFiEventKind:
    """Map Ko-fi's ``type`` string to our enum or raise."""
    if not isinstance(raw_kind, str):
        raise ReceiveOnlyRailError(
            f"webhook 'type' must be a string, got {type(raw_kind).__name__}"
        )
    if raw_kind in _ACCEPTED_KINDS:
        return KoFiEventKind(raw_kind)
    if raw_kind in _KO_FI_KIND_ALIASES:
        return _KO_FI_KIND_ALIASES[raw_kind]
    raise ReceiveOnlyRailError(f"unaccepted webhook event type {raw_kind!r}")


def _extract_sender_handle(payload: dict[str, Any]) -> str:
    """Extract Ko-fi's public ``from_name`` display.

    Ko-fi uses ``from_name`` as the primary public attribution field on
    every event type. Anonymous supporters appear with ``from_name``
    set to ``"Anonymous"`` by Ko-fi's webhook contract — that string
    passes through as the canonical aggregate handle for unattributed
    support (it is not an email and not personally identifying).
    """
    handle = payload.get("from_name")
    if not isinstance(handle, str) or not handle:
        raise ReceiveOnlyRailError("payload missing 'from_name'")
    return handle


def _extract_amount_and_currency(payload: dict[str, Any]) -> tuple[int, str]:
    """Extract minor-unit amount + ISO 4217 currency from the delivery.

    Ko-fi sends amounts as decimal strings in the major unit (e.g.
    ``"5.00"`` for five dollars/euros/etc., ``"12.50"`` for twelve and
    a half). The receiver normalizes via ``Decimal`` × 100 (rounded to
    integer) so floating-point error never enters the cents field.
    Currency is sent as the ISO 4217 3-letter code (Ko-fi typically
    emits uppercase already, but the receiver normalizes upward
    defensively).

    Negative amounts are converted to absolute value so the rail
    expresses gross movement; net flow is reconstructed by event_kind
    downstream (consistent with the Stripe / Open Collective rails).
    """
    raw_amount = payload.get("amount")
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

    raw_currency = payload.get("currency")
    if not isinstance(raw_currency, str) or not raw_currency:
        raise ReceiveOnlyRailError("payload missing 'currency'")

    cents = int((decimal_amount.copy_abs() * 100).to_integral_value())
    return cents, raw_currency.upper()


def _extract_occurred_at(payload: dict[str, Any]) -> datetime:
    """Extract the delivery timestamp from Ko-fi's ``timestamp`` field.

    Ko-fi emits ``timestamp`` as an ISO 8601 string (typically with
    millisecond precision and trailing ``Z`` for UTC). The receiver
    accepts either ``timestamp`` or the alternate ``occurred_at`` /
    ``created_at`` keys for parity with the sibling rails.
    """
    raw = payload.get("timestamp") or payload.get("occurred_at") or payload.get("created_at")
    if not isinstance(raw, str) or not raw:
        raise ReceiveOnlyRailError("payload missing 'timestamp' / 'occurred_at' / 'created_at'")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiveOnlyRailError(f"invalid ISO 8601 timestamp {raw!r}: {exc}") from exc


class KoFiRailReceiver:
    """Receive-only adapter for Ko-fi webhooks.

    Construction is cheap and side-effect-free. The single public
    method :meth:`ingest_webhook` validates payload shape, verifies the
    static verification token (if provided / required), and returns a
    normalized :class:`KoFiEvent`. The receiver never opens a network
    socket, writes to disk, or contacts any external system.
    """

    def __init__(
        self,
        *,
        token_env_var: str = KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV,
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self._token_env_var = token_env_var
        self._idempotency_store = idempotency_store

    def _resolve_token(self) -> str:
        return os.environ.get(self._token_env_var, "")

    def ingest_webhook(
        self,
        payload: dict[str, Any],
        *,
        verify_token: bool = True,
    ) -> KoFiEvent | None:
        """Validate + normalize a single Ko-fi webhook delivery.

        Returns the normalized :class:`KoFiEvent` for accepted
        deliveries. Raises :class:`ReceiveOnlyRailError` for malformed
        payloads, unaccepted event types, or verification-token
        failures. Returns ``None`` only when the caller passes
        ``payload={}`` *and* ``verify_token=False``, which is treated
        as a no-op heartbeat ping (parity with the Stripe / Open
        Collective rails' empty-test-delivery handling).

        ``verify_token`` defaults to ``True`` for production safety;
        callers exercising the ingest path in tests where token
        verification is off-path may pass ``False`` to skip the check.
        Token verification reads
        ``KO_FI_WEBHOOK_VERIFICATION_TOKEN`` from the environment;
        unset env var with ``verify_token=True`` fails closed.
        """
        if not isinstance(payload, dict):
            raise ReceiveOnlyRailError(f"payload must be a dict, got {type(payload).__name__}")

        if not payload and not verify_token:
            return None

        if verify_token:
            expected_token = self._resolve_token()
            _verify_token(payload, expected_token)

        payload_bytes = _canonical_bytes(payload)
        payload_sha256 = _sha256_hex(payload_bytes)

        event_kind = _coerce_kind(payload.get("type"))
        sender_handle = _extract_sender_handle(payload)
        amount_cents, currency = _extract_amount_and_currency(payload)
        occurred_at = _extract_occurred_at(payload)

        if self._idempotency_store is not None:
            transaction_id = payload.get("kofi_transaction_id")
            if not isinstance(transaction_id, str) or not transaction_id:
                raise ReceiveOnlyRailError(
                    "idempotency_store provided but payload missing 'kofi_transaction_id' "
                    "(required for dedup keying)"
                )
            try:
                if not self._idempotency_store.record_or_skip(transaction_id):
                    return None
            except _SharedIdempotencyError as exc:
                raise ReceiveOnlyRailError(str(exc)) from exc

        try:
            return KoFiEvent(
                sender_handle=sender_handle,
                amount_currency_cents=amount_cents,
                currency=currency,
                event_kind=event_kind,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "KO_FI_WEBHOOK_VERIFICATION_TOKEN_ENV",
    "IdempotencyStore",
    "KoFiEvent",
    "KoFiEventKind",
    "KoFiRailReceiver",
    "ReceiveOnlyRailError",
]
