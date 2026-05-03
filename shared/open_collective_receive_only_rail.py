"""Open Collective receive-only rail.

Phase 0 receiver for Open Collective webhook events. Normalizes inbound
``collective.transaction.created`` / ``order.processed`` /
``member.created`` / ``expense.paid`` deliveries into a typed,
payer-aggregate ``CollectiveEvent`` — *without* calls, outbound writes,
CRM, or per-supporter relationship surfaces.

**Receive-only invariant.** This module never originates an outbound
network call, never writes to an external system, and never persists
PII. ``member_handle`` is the Open Collective public slug the member
chose to associate with the gift; emails, payment methods, addresses,
member descriptions, and free-text expense notes are intentionally not
extracted.

**Open Collective webhook product.** Open Collective ships a first-class
webhook product (`https://docs.opencollective.com/help/integrations/webhooks`)
that fires HTTP POST deliveries to a per-collective registered URL on
the activity types this receiver subscribes to. Deliveries are signed
via HMAC SHA-256 with the per-webhook secret in the
``X-Open-Collective-Signature`` header (bare hex digest, no prefix
when emitted by Open Collective; the receiver also tolerates the
``sha256=<hex>`` prefix form for parity with sibling rails). The
secret is read from ``OPEN_COLLECTIVE_WEBHOOK_SECRET``
(``os.environ.get``; never hardcoded). Validation, signature, or
unknown-event failures fail-closed via :class:`ReceiveOnlyRailError`.

**Accepted event kinds.**

- ``collective_transaction_created`` — new transaction (debit/credit)
  recorded against the collective ledger (the most general signal,
  emitted on every donation/contribution settlement).
- ``order_processed`` — a one-off or recurring contribution order has
  been processed end-to-end (payment cleared, ledger entry written).
- ``member_created`` — a new sponsor/backer/follower joined the
  collective at a given tier.
- ``expense_paid`` — a previously-approved expense has been paid out
  (signals net outflow on the collective; included for completeness so
  monetization dashboards can compute net-receipts cleanly).

Other activity types Open Collective may emit (``expense.created``,
``expense.approved``, ``expense.rejected``, ``collective.created``,
``user.created``, etc.) are rejected as *unaccepted-but-known*;
entirely unknown strings are rejected as *malformed*. Both raise
:class:`ReceiveOnlyRailError`.

**Multi-currency.** Open Collective is multi-currency-native: a single
collective may receive donations in USD, EUR, GBP, CAD, AUD, and many
other ISO 4217 currencies. Unlike the GitHub Sponsors rail (USD-only)
and the Liberapay rail (EUR-only with upstream conversion), this
receiver preserves the source currency on the normalized event. The
``amount_currency_cents`` field is integer minor-units (e.g. cents,
pence, euro-cents) in the currency named by ``currency``. Downstream
consumers are responsible for any FX normalization. The receiver
verifies that ``currency`` is a non-empty 3-letter uppercase ISO 4217
code; non-conforming values fail-closed.

**Governance constraint.** No PII, no outbound, multi-currency
normalized to lowest unit cents in the source currency. The HMAC
SHA-256 signature header is verified against
``OPEN_COLLECTIVE_WEBHOOK_SECRET`` (``os.environ.get``; never
hardcoded). Validation, signature, or unknown-event failures
fail-closed via :class:`ReceiveOnlyRailError`.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0,
Open Collective rail). Sibling rails:
``shared/github_sponsors_receive_only_rail.py`` (#2218) and
``shared/liberapay_receive_only_rail.py`` (#2219). Multi-currency
preservation is the new shape this rail introduces vs the prior two.
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

OPEN_COLLECTIVE_WEBHOOK_SECRET_ENV = "OPEN_COLLECTIVE_WEBHOOK_SECRET"

_ISO_4217_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected Open Collective webhook payload.

    Raised on malformed payloads, unaccepted activity kinds, signature
    verification failures, missing fields, malformed currency codes,
    or shape violations. The receiver never silently drops or
    partially-accepts an inbound event.
    """


class CollectiveEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver."""

    COLLECTIVE_TRANSACTION_CREATED = "collective_transaction_created"
    ORDER_PROCESSED = "order_processed"
    MEMBER_CREATED = "member_created"
    EXPENSE_PAID = "expense_paid"


_ACCEPTED_ACTIVITIES: frozenset[str] = frozenset(k.value for k in CollectiveEventKind)
_OPEN_COLLECTIVE_ACTIVITY_ALIASES: dict[str, CollectiveEventKind] = {
    # Open Collective emits dotted activity types in the webhook envelope.
    # Both the dotted form and the underscored canonical form are accepted.
    "collective.transaction.created": CollectiveEventKind.COLLECTIVE_TRANSACTION_CREATED,
    "order.processed": CollectiveEventKind.ORDER_PROCESSED,
    "member.created": CollectiveEventKind.MEMBER_CREATED,
    "expense.paid": CollectiveEventKind.EXPENSE_PAID,
}


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CollectiveEvent(_RailModel):
    """Normalized, payer-aggregate Open Collective event.

    *No PII fields exist on this type.* ``member_handle`` is the
    Open Collective public slug the member selected (or the
    transaction collective slug for transaction events; either is
    public information already exposed on opencollective.com).
    ``amount_currency_cents`` is integer minor-units (cents/pence/etc.)
    in the source currency named by ``currency``. ``currency`` is the
    ISO 4217 3-letter uppercase code. ``raw_payload_sha256`` is
    included so a downstream consumer can correlate this normalized
    event to the original webhook delivery without re-storing the raw
    payload (which may contain free-text descriptions, expense notes,
    or other fields we do not want to persist beyond the receiver
    boundary).
    """

    member_handle: str = Field(min_length=1, max_length=255)
    amount_currency_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    event_kind: CollectiveEventKind
    occurred_at: datetime
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("member_handle")
    @classmethod
    def _handle_is_slug_only(cls, value: str) -> str:
        """``member_handle`` must look like an Open Collective slug, not an email."""
        if "@" in value or " " in value:
            raise ValueError(
                "member_handle must be an Open Collective slug, not an email or qualified path"
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


def _verify_signature(payload_bytes: bytes, signature: str, secret: str) -> None:
    """Fail-closed HMAC SHA-256 verification.

    Open Collective's ``X-Open-Collective-Signature`` header is a bare
    hex digest. For parity with sibling rails, the ``sha256=<hex>``
    prefix form is also accepted. Mismatch raises
    :class:`ReceiveOnlyRailError`.
    """
    if not secret:
        raise ReceiveOnlyRailError(
            f"signature provided but {OPEN_COLLECTIVE_WEBHOOK_SECRET_ENV} is not set"
        )
    expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    if not hmac.compare_digest(expected, candidate):
        raise ReceiveOnlyRailError("HMAC SHA-256 signature mismatch")


def _coerce_activity(raw_activity: Any) -> CollectiveEventKind:
    """Map Open Collective's ``type`` string to our enum or raise."""
    if not isinstance(raw_activity, str):
        raise ReceiveOnlyRailError(
            f"webhook 'type' must be a string, got {type(raw_activity).__name__}"
        )
    if raw_activity in _ACCEPTED_ACTIVITIES:
        return CollectiveEventKind(raw_activity)
    if raw_activity in _OPEN_COLLECTIVE_ACTIVITY_ALIASES:
        return _OPEN_COLLECTIVE_ACTIVITY_ALIASES[raw_activity]
    raise ReceiveOnlyRailError(f"unaccepted webhook activity {raw_activity!r}")


def _extract_member_handle(payload: dict[str, Any]) -> str:
    """Extract a public slug from the most-likely fields.

    Open Collective's webhook envelope places the active party under
    several keys depending on activity type: ``data.member.memberAccount.slug``
    (member.created), ``data.fromCollective.slug`` (transaction credits),
    ``data.order.fromAccount.slug`` (order events), or ``data.collective.slug``
    (expense.paid). We probe each in turn and raise if no slug can be
    located on this delivery.
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ReceiveOnlyRailError("payload missing 'data' object")

    candidates: list[Any] = []
    member = data.get("member")
    if isinstance(member, dict):
        member_account = member.get("memberAccount")
        if isinstance(member_account, dict):
            candidates.append(member_account.get("slug"))
    from_collective = data.get("fromCollective")
    if isinstance(from_collective, dict):
        candidates.append(from_collective.get("slug"))
    order = data.get("order")
    if isinstance(order, dict):
        from_account = order.get("fromAccount")
        if isinstance(from_account, dict):
            candidates.append(from_account.get("slug"))
    collective = data.get("collective")
    if isinstance(collective, dict):
        candidates.append(collective.get("slug"))

    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    raise ReceiveOnlyRailError(
        "payload missing a slug under 'data.member.memberAccount', "
        "'data.fromCollective', 'data.order.fromAccount', or 'data.collective'"
    )


def _extract_amount_and_currency(payload: dict[str, Any]) -> tuple[int, str]:
    """Extract minor-unit amount + ISO 4217 currency from the delivery.

    Open Collective's amount payloads come in two shapes:

    1. Modern GraphQL-shaped envelopes (recent webhooks):
       ``data.transaction.amount = {value: 5.0, currency: "USD"}`` —
       ``value`` is a decimal in the major unit.
    2. Legacy REST-shaped envelopes:
       ``data.transaction.amount = 500`` (integer cents) and
       ``data.transaction.currency = "USD"``.

    Both are accepted. The receiver normalizes to integer minor-units
    in the named currency. Negative amounts (debits) are converted to
    their absolute value so the rail expresses gross movement, not
    sign — net flow is reconstructed by event_kind downstream.
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ReceiveOnlyRailError("payload missing 'data' object")

    amount_obj: Any = None
    currency_str: str | None = None

    transaction = data.get("transaction")
    if isinstance(transaction, dict):
        amount_obj = transaction.get("amount")
        if isinstance(transaction.get("currency"), str):
            currency_str = transaction["currency"]
    if amount_obj is None:
        order = data.get("order")
        if isinstance(order, dict):
            amount_obj = order.get("totalAmount") or order.get("amount")
            if isinstance(order.get("currency"), str):
                currency_str = currency_str or order["currency"]
    if amount_obj is None:
        member = data.get("member")
        if isinstance(member, dict):
            tier = member.get("tier")
            if isinstance(tier, dict):
                amount_obj = tier.get("amount")
                if isinstance(tier.get("currency"), str):
                    currency_str = currency_str or tier["currency"]
    if amount_obj is None:
        expense = data.get("expense")
        if isinstance(expense, dict):
            amount_obj = expense.get("amount")
            if isinstance(expense.get("currency"), str):
                currency_str = currency_str or expense["currency"]

    if amount_obj is None:
        raise ReceiveOnlyRailError(
            "payload missing amount under 'data.transaction', 'data.order', "
            "'data.member.tier', or 'data.expense'"
        )

    raw_value: Any
    if isinstance(amount_obj, dict):
        raw_value = amount_obj.get("value")
        if raw_value is None:
            raw_value = amount_obj.get("valueInCents")
            if raw_value is not None and not isinstance(raw_value, bool):
                # GraphQL `valueInCents` shape — already integer minor-units.
                if not isinstance(raw_value, int):
                    raise ReceiveOnlyRailError(
                        f"'valueInCents' must be an int, got {type(raw_value).__name__}"
                    )
                inner_currency = amount_obj.get("currency")
                if isinstance(inner_currency, str):
                    currency_str = inner_currency
                if currency_str is None:
                    raise ReceiveOnlyRailError("payload missing currency for amount")
                cents = abs(raw_value)
                return cents, currency_str.upper()
        inner_currency = amount_obj.get("currency")
        if isinstance(inner_currency, str):
            currency_str = inner_currency
        if raw_value is None:
            raise ReceiveOnlyRailError("amount object missing 'value' or 'valueInCents'")
        if isinstance(raw_value, bool):
            raise ReceiveOnlyRailError("amount value must be a number or numeric string")
        try:
            decimal_amount = Decimal(str(raw_value))
        except InvalidOperation as exc:
            raise ReceiveOnlyRailError(f"invalid amount value {raw_value!r}: {exc}") from exc
        if currency_str is None:
            raise ReceiveOnlyRailError("payload missing currency for amount")
        cents = int((decimal_amount.copy_abs() * 100).to_integral_value())
        return cents, currency_str.upper()

    # Legacy REST shape: integer cents.
    if isinstance(amount_obj, bool):
        raise ReceiveOnlyRailError("amount value must be a number or numeric string")
    if not isinstance(amount_obj, int | float):
        raise ReceiveOnlyRailError(
            f"amount must be a number or amount-object, got {type(amount_obj).__name__}"
        )
    if currency_str is None:
        raise ReceiveOnlyRailError("payload missing 'currency' alongside legacy amount")
    cents = int(abs(int(round(float(amount_obj)))))
    return cents, currency_str.upper()


def _extract_occurred_at(payload: dict[str, Any]) -> datetime:
    raw = payload.get("createdAt") or payload.get("created_at") or payload.get("occurred_at")
    if not isinstance(raw, str) or not raw:
        raise ReceiveOnlyRailError("payload missing 'createdAt' / 'created_at' / 'occurred_at'")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiveOnlyRailError(f"invalid ISO 8601 timestamp {raw!r}: {exc}") from exc


class OpenCollectiveRailReceiver:
    """Receive-only adapter for Open Collective webhooks.

    Construction is cheap and side-effect-free. The single public
    method :meth:`ingest_webhook` validates payload shape, optionally
    verifies the HMAC SHA-256 signature, and returns a normalized
    :class:`CollectiveEvent`. The receiver never opens a network
    socket, writes to disk, or contacts any external system.
    """

    def __init__(
        self,
        *,
        secret_env_var: str = OPEN_COLLECTIVE_WEBHOOK_SECRET_ENV,
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
        delivery_id: str | None = None,
    ) -> CollectiveEvent | None:
        """Validate + normalize a single Open Collective webhook delivery.

        Returns the normalized :class:`CollectiveEvent` for accepted
        deliveries. Raises :class:`ReceiveOnlyRailError` for malformed
        payloads, unaccepted activities, or signature failures.
        Returns ``None`` only when the caller passes ``payload={}``
        *and* ``signature=None``, which is treated as a no-op heartbeat
        ping from a pre-flight ping delivery.

        ``raw_body`` is the raw HTTP body bytes Open Collective signed
        (the FastAPI handler captures these before JSON parsing).
        When provided, signature verification uses the raw bytes —
        the only correct shape against live deliveries.  When omitted,
        the receiver falls back to canonical-encoding the parsed
        payload (preserves prior behavior used by the rail's own unit
        tests).
        """
        if not isinstance(payload, dict):
            raise ReceiveOnlyRailError(f"payload must be a dict, got {type(payload).__name__}")

        if not payload and signature is None:
            return None

        canonical = _canonical_bytes(payload)
        payload_bytes = raw_body if raw_body is not None else canonical

        if signature is not None:
            secret = self._resolve_secret()
            _verify_signature(payload_bytes, signature, secret)

        payload_sha256 = _sha256_hex(payload_bytes)

        activity = _coerce_activity(payload.get("type"))
        member_handle = _extract_member_handle(payload)
        amount_cents, currency = _extract_amount_and_currency(payload)
        occurred_at = _extract_occurred_at(payload)

        if self._idempotency_store is not None:
            if not delivery_id:
                raise ReceiveOnlyRailError(
                    "idempotency_store provided but delivery_id missing — "
                    "Open Collective webhooks ship a per-delivery identifier "
                    "in the X-Open-Collective-Activity-Id header"
                )
            try:
                if not self._idempotency_store.record_or_skip(delivery_id):
                    return None
            except _SharedIdempotencyError as exc:
                raise ReceiveOnlyRailError(str(exc)) from exc

        try:
            return CollectiveEvent(
                member_handle=member_handle,
                amount_currency_cents=amount_cents,
                currency=currency,
                event_kind=activity,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "OPEN_COLLECTIVE_WEBHOOK_SECRET_ENV",
    "CollectiveEvent",
    "CollectiveEventKind",
    "IdempotencyStore",
    "OpenCollectiveRailReceiver",
    "ReceiveOnlyRailError",
]
