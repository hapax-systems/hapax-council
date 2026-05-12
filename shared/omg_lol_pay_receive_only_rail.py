"""Dormant omg.lol Pay receive-only parser.

omg.lol Pay is not a shipped omg.lol product. This parser remains as a
receive-only historical scaffold for capability research, but it is not
registered in the publication bus and has no publisher activation path.

Receive-only invariant. Same posture as
:mod:`shared.liberapay_receive_only_rail`: this module never
originates an outbound network call, never writes to an external
system, and never persists PII. ``donor_handle`` is the omg.lol
address (the public ``<name>.omg.lol`` username) the donor already
selected; emails, billing addresses, and free-text payment notes
are intentionally not extracted.

This module accepts the historical hypothetical webhook payload
shape and validates HMAC-SHA-256 signatures via the ``X-OMG-Signature``
header (``OMG_LOL_PAY_WEBHOOK_SECRET`` env). USD-cents normalization is
kept for fixture compatibility; non-USD deliveries are rejected.

Accepted event kinds:

* ``payment_succeeded`` — donor's one-time payment cleared.
* ``payment_refunded`` — payment refunded (auto-link to refusal log
  per the cancellation-as-refusal pattern shared with Liberapay).
* ``subscription_set`` — donor authorized a recurring subscription.
* ``subscription_cancelled`` — donor cancelled the subscription.

Other action strings emit ``ReceiveOnlyRailError`` (fail-closed) so
a misconfigured bridge cannot silently bypass the gate.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

OMG_LOL_PAY_WEBHOOK_SECRET_ENV = "OMG_LOL_PAY_WEBHOOK_SECRET"
OMG_LOL_PAY_REQUIRE_IP_ALLOWLIST_ENV = "OMG_LOL_PAY_REQUIRE_IP_ALLOWLIST"

__all__ = [
    "OMG_LOL_PAY_REQUIRE_IP_ALLOWLIST_ENV",
    "OMG_LOL_PAY_WEBHOOK_SECRET_ENV",
    "OmgLolPayRailReceiver",
    "PaymentEvent",
    "PaymentEventKind",
    "ReceiveOnlyRailError",
]


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected omg.lol Pay payload.

    Raised on malformed payloads, unaccepted action kinds, signature
    verification failures, missing fields, non-USD currency, or shape
    violations. The receiver never silently drops or partially-accepts
    an inbound event.
    """


class PaymentEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver."""

    PAYMENT_SUCCEEDED = "payment_succeeded"
    PAYMENT_REFUNDED = "payment_refunded"
    SUBSCRIPTION_SET = "subscription_set"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"


_ACCEPTED_ACTIONS: frozenset[str] = frozenset(k.value for k in PaymentEventKind)
# Bridge-style aliases from the historical hypothetical payload shape.
_OMG_LOL_PAY_ACTION_ALIASES: dict[str, PaymentEventKind] = {
    "payment.succeeded": PaymentEventKind.PAYMENT_SUCCEEDED,
    "payment.refunded": PaymentEventKind.PAYMENT_REFUNDED,
    "subscription.set": PaymentEventKind.SUBSCRIPTION_SET,
    "subscription.cancelled": PaymentEventKind.SUBSCRIPTION_CANCELLED,
}


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PaymentEvent(_RailModel):
    """Normalized, payer-aggregate omg.lol Pay event.

    No PII fields exist on this type. ``donor_handle`` is the
    omg.lol address (public ``<name>.omg.lol`` username) the donor
    selected. ``amount_usd_cents`` is integer USD cents from the
    historical fixture shape. ``raw_payload_sha256`` is included so a
    downstream consumer can correlate to the original delivery
    without re-storing the raw payload.
    """

    donor_handle: str = Field(min_length=1, max_length=255)
    amount_usd_cents: int = Field(ge=0)
    event_kind: PaymentEventKind
    occurred_at: datetime
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("donor_handle")
    @classmethod
    def _handle_is_address_only(cls, value: str) -> str:
        """``donor_handle`` must look like an omg.lol address, not an email."""
        if "@" in value or "/" in value or " " in value:
            raise ValueError(
                "donor_handle must be an omg.lol address, not an email or qualified path"
            )
        return value


# ── HMAC + canonical bytes helpers ────────────────────────────────────


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Stable canonical JSON for HMAC verification.

    Sorted keys + comma-separated to match the bridge's signing
    convention. Diverging from this would silently break HMAC.
    """

    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _verify_signature(payload_bytes: bytes, signature: str, secret: str) -> None:
    """Fail-closed HMAC SHA-256 verification.

    Accepts both bare hex digest and ``sha256=<hex>`` prefixed form
    (parity with sibling rails). Mismatch raises
    :class:`ReceiveOnlyRailError`.
    """

    if not secret:
        raise ReceiveOnlyRailError(
            f"signature provided but {OMG_LOL_PAY_WEBHOOK_SECRET_ENV} is not set"
        )
    expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    if not hmac.compare_digest(expected, candidate):
        raise ReceiveOnlyRailError("HMAC SHA-256 signature mismatch")


def _coerce_action(raw_action: Any) -> PaymentEventKind:
    """Map omg.lol Pay's ``event`` string to our enum or raise."""

    if not isinstance(raw_action, str):
        raise ReceiveOnlyRailError(
            f"webhook 'event' must be a string, got {type(raw_action).__name__}"
        )
    if raw_action in _ACCEPTED_ACTIONS:
        return PaymentEventKind(raw_action)
    if raw_action in _OMG_LOL_PAY_ACTION_ALIASES:
        return _OMG_LOL_PAY_ACTION_ALIASES[raw_action]
    raise ReceiveOnlyRailError(f"unaccepted webhook event {raw_action!r}")


def _extract_donor_handle(payload: dict[str, Any]) -> str:
    donor = payload.get("donor")
    if not isinstance(donor, dict):
        raise ReceiveOnlyRailError("payload missing 'donor' object")
    handle = donor.get("address") or donor.get("username")
    if not isinstance(handle, str) or not handle:
        raise ReceiveOnlyRailError("payload missing 'donor.address' or 'donor.username'")
    return handle


def _extract_amount_usd_cents(payload: dict[str, Any]) -> int:
    amount = payload.get("amount")
    if not isinstance(amount, dict):
        raise ReceiveOnlyRailError("payload missing 'amount' object")
    currency = amount.get("currency")
    if currency != "USD":
        raise ReceiveOnlyRailError(
            f"non-USD currency {currency!r}; bridge must convert before delivery"
        )
    raw_amount = amount.get("amount")
    if raw_amount is None:
        raise ReceiveOnlyRailError("payload missing 'amount.amount'")
    if isinstance(raw_amount, bool):
        raise ReceiveOnlyRailError("'amount.amount' must be a number or numeric string")
    if isinstance(raw_amount, int | float):
        try:
            decimal_amount = Decimal(str(raw_amount))
        except InvalidOperation as exc:  # pragma: no cover — defensive
            raise ReceiveOnlyRailError(f"invalid 'amount.amount' value {raw_amount!r}") from exc
    elif isinstance(raw_amount, str):
        try:
            decimal_amount = Decimal(raw_amount)
        except InvalidOperation as exc:
            raise ReceiveOnlyRailError(
                f"invalid 'amount.amount' decimal {raw_amount!r}: {exc}"
            ) from exc
    else:
        raise ReceiveOnlyRailError(
            f"'amount.amount' must be a number or numeric string, got {type(raw_amount).__name__}"
        )
    if decimal_amount < 0:
        raise ReceiveOnlyRailError(f"amount must be non-negative, got {decimal_amount}")
    return int((decimal_amount * 100).to_integral_value())


def _extract_occurred_at(payload: dict[str, Any]) -> datetime:
    raw = payload.get("occurred_at") or payload.get("timestamp")
    if not isinstance(raw, str) or not raw:
        raise ReceiveOnlyRailError("payload missing 'occurred_at' / 'timestamp'")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiveOnlyRailError(f"invalid ISO 8601 timestamp {raw!r}: {exc}") from exc


def _enforce_ip_allowlist_claim(payload: dict[str, Any], require: bool) -> None:
    """Raise if the bridge omitted ``source_ip`` while allowlist is required.

    The CIDR check belongs in the calling FastAPI route. This
    receiver only refuses to proceed when the bridge fails to
    forward the source-ip claim altogether (a config bug that would
    silently bypass the IP gate above this layer).
    """

    if not require:
        return
    source_ip = payload.get("source_ip")
    if not isinstance(source_ip, str) or not source_ip:
        raise ReceiveOnlyRailError(
            f"payload missing 'source_ip' but {OMG_LOL_PAY_REQUIRE_IP_ALLOWLIST_ENV}=1 "
            "(upstream bridge must forward client IP)"
        )


# ── Receiver class ────────────────────────────────────────────────────


class OmgLolPayRailReceiver:
    """Validate and normalize omg.lol Pay webhook deliveries.

    Stateless across calls; one instance per FastAPI process is
    sufficient. Tests inject the secret directly; production reads
    via ``OMG_LOL_PAY_WEBHOOK_SECRET`` env.
    """

    def __init__(
        self,
        *,
        webhook_secret: str | None = None,
        require_ip_allowlist: bool | None = None,
    ) -> None:
        self._webhook_secret = (
            webhook_secret
            if webhook_secret is not None
            else os.environ.get(OMG_LOL_PAY_WEBHOOK_SECRET_ENV, "")
        )
        if require_ip_allowlist is None:
            self._require_ip_allowlist = (
                os.environ.get(OMG_LOL_PAY_REQUIRE_IP_ALLOWLIST_ENV, "0") == "1"
            )
        else:
            self._require_ip_allowlist = require_ip_allowlist

    def ingest_webhook(
        self,
        payload: dict[str, Any],
        *,
        signature: str | None = None,
    ) -> PaymentEvent:
        """Validate and normalize one inbound omg.lol Pay delivery.

        Raises :class:`ReceiveOnlyRailError` on any shape, signature,
        currency, or action violation. Returns the normalized
        :class:`PaymentEvent` on success.
        """

        if not isinstance(payload, dict):
            raise ReceiveOnlyRailError(
                f"payload must be a JSON object, got {type(payload).__name__}"
            )

        _enforce_ip_allowlist_claim(payload, self._require_ip_allowlist)

        if signature is not None:
            _verify_signature(_canonical_bytes(payload), signature, self._webhook_secret)
        elif self._webhook_secret:
            raise ReceiveOnlyRailError(
                f"{OMG_LOL_PAY_WEBHOOK_SECRET_ENV} is set but no signature was provided"
            )

        event_str = payload.get("event")
        kind = _coerce_action(event_str)
        donor_handle = _extract_donor_handle(payload)
        amount_cents = _extract_amount_usd_cents(payload)
        occurred_at = _extract_occurred_at(payload)
        raw_sha = _sha256_hex(_canonical_bytes(payload))

        try:
            return PaymentEvent(
                donor_handle=donor_handle,
                amount_usd_cents=amount_cents,
                event_kind=kind,
                occurred_at=occurred_at,
                raw_payload_sha256=raw_sha,
            )
        except ValidationError as exc:
            # Surface the underlying constraint violation as the
            # canonical fail-closed error so callers don't need to
            # handle two exception types. Donor-handle validators
            # raise ValueError("...omg.lol address...") which arrives
            # here wrapped in pydantic's ValidationError.
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc
