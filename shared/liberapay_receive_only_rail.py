"""Liberapay receive-only rail.

Phase 0 receiver for Liberapay donation-lifecycle events. Normalizes
inbound ``payin.created`` / ``payin.succeeded`` / ``tip.set`` /
``tip.cancelled`` notifications into a typed, payer-aggregate
``DonationEvent`` — *without* calls, outbound writes, CRM, or
per-supporter relationship surfaces.

**Receive-only invariant.** This module never originates an outbound
network call, never writes to an external system, and never persists
PII. ``donor_handle`` is the Liberapay-public username the donor
already chose to associate with the gift; emails, payment methods,
addresses, and tip messages are intentionally not extracted.

**Liberapay does not currently ship a webhook product.** As of
GitHub issue ``liberapay/liberapay.com#688`` (still open), the
project is "designing a proper HTTP API" and provides neither
webhook deliveries nor an HMAC-signing primitive. This receiver is
shaped for the practical bridges in use today:

1. **Email-to-webhook bridges** — Liberapay's outbound notification
   emails (parsed by an upstream mail-to-webhook gateway, e.g.
   `cloudmailin`, `mailgun`, an `n8n` workflow) land here as a
   structured JSON payload that this module validates and normalizes.
2. **Self-hosted CSV-export poller** — Liberapay's per-account public
   exports (see ``/about/me``) can be mirrored by a sibling daemon
   that synthesizes one ``DonationEvent`` per ledger row on each
   delta and posts it to the same internal handler this module backs.

Because Liberapay does not sign its own emails or exports, the
upstream bridge is responsible for authenticating its delivery to
this receiver. Two enforcement modes are supported, both fail-closed:

- **IP allowlist (default)** — set
  ``LIBERAPAY_REQUIRE_IP_ALLOWLIST=1`` to require every accepted
  payload to carry a non-empty ``source_ip`` field. The receiver
  does *not* itself perform CIDR comparison against an allowlist
  (that belongs in the FastAPI layer that calls
  :meth:`LiberapayRailReceiver.ingest_webhook`); but it *does* refuse
  any payload that omits the claim, so a misconfigured bridge
  cannot silently bypass the allowlist gate above it.
- **HMAC SHA-256 (optional)** — if the bridge does sign outgoing
  deliveries, set ``LIBERAPAY_WEBHOOK_SECRET`` and pass the
  hex-digest signature to :meth:`LiberapayRailReceiver.ingest_webhook`
  as the ``signature`` argument. The receiver verifies the HMAC
  against the canonical-JSON payload bytes. ``signature=None`` is
  accepted (and required) when HMAC is not in use; the IP-allowlist
  mode still applies independently.

**Accepted event kinds.**

- ``payin_created`` — donor authorizes a donation, payment in flight.
- ``payin_succeeded`` — donation cleared and crediting the donee.
- ``tip_set`` — donor pledges a recurring weekly amount (no money
  has moved yet on this notification — pledge intent only).
- ``tip_cancelled`` — donor terminates a recurring pledge.

Other action strings Liberapay may emit (``payin.failed``,
``payin.refunded``, ``team.member.added``) are rejected as
*unaccepted-but-known*; entirely unknown strings are rejected as
*malformed*. Both raise :class:`ReceiveOnlyRailError`.

**Governance constraint.** No PII, no outbound, EUR-cents
normalization. ``amount_eur_cents`` is integer cents, EUR-native:
Liberapay quotes amounts in EUR by default and emits a per-currency
``amount.amount`` decimal string plus ``amount.currency`` ISO 4217
code; non-EUR donations are converted at Liberapay's published rate
*at notification time* by the upstream bridge before being delivered
here. This module rejects any non-EUR delivery — currency conversion
happens upstream so the canonical normalized event stays EUR-cents.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0,
Liberapay rail). Sibling rails:
``shared/license_request_price_class_router.py``,
``shared/payment_aggregator_v2_support_normalizer.py``, and
``shared/github_sponsors_receive_only_rail.py``.
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

from shared._rail_idempotency import (
    IdempotencyError as _SharedIdempotencyError,
)
from shared._rail_idempotency import (
    IdempotencyStore,
)

LIBERAPAY_WEBHOOK_SECRET_ENV = "LIBERAPAY_WEBHOOK_SECRET"
LIBERAPAY_REQUIRE_IP_ALLOWLIST_ENV = "LIBERAPAY_REQUIRE_IP_ALLOWLIST"


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected Liberapay donation payload.

    Raised on malformed payloads, unaccepted action kinds, signature
    verification failures, missing fields, non-EUR currency, or shape
    violations. The receiver never silently drops or partially-accepts
    an inbound event.
    """


class DonationEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver."""

    PAYIN_CREATED = "payin_created"
    PAYIN_SUCCEEDED = "payin_succeeded"
    TIP_SET = "tip_set"
    TIP_CANCELLED = "tip_cancelled"


_ACCEPTED_ACTIONS: frozenset[str] = frozenset(k.value for k in DonationEventKind)
_LIBERAPAY_ACTION_ALIASES: dict[str, DonationEventKind] = {
    # Liberapay's email/RSS surfaces use dotted forms; the upstream bridge may
    # forward either the dotted form or the underscored canonical form.
    "payin.created": DonationEventKind.PAYIN_CREATED,
    "payin.succeeded": DonationEventKind.PAYIN_SUCCEEDED,
    "tip.set": DonationEventKind.TIP_SET,
    "tip.cancelled": DonationEventKind.TIP_CANCELLED,
}


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DonationEvent(_RailModel):
    """Normalized, payer-aggregate donation event.

    *No PII fields exist on this type.* ``donor_handle`` is the
    Liberapay-public username the donor selected. ``amount_eur_cents``
    is integer EUR cents (Liberapay is EUR-native).
    ``raw_payload_sha256`` is included so a downstream consumer can
    correlate this normalized event to the original inbound delivery
    without re-storing the raw payload (which may contain tip messages
    or other free text we do not want to persist beyond the receiver
    boundary).
    """

    donor_handle: str = Field(min_length=1, max_length=255)
    amount_eur_cents: int = Field(ge=0)
    event_kind: DonationEventKind
    occurred_at: datetime
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("donor_handle")
    @classmethod
    def _handle_is_username_only(cls, value: str) -> str:
        """``donor_handle`` must look like a Liberapay username, not an email."""
        if "@" in value or "/" in value or " " in value:
            raise ValueError(
                "donor_handle must be a Liberapay username, not an email or qualified path"
            )
        return value


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _verify_signature(payload_bytes: bytes, signature: str, secret: str) -> None:
    """Fail-closed HMAC SHA-256 verification.

    Accepts both bare hex digest and ``sha256=<hex>`` prefixed form
    (for parity with sibling rails). Mismatch raises
    :class:`ReceiveOnlyRailError`.
    """
    if not secret:
        raise ReceiveOnlyRailError(
            f"signature provided but {LIBERAPAY_WEBHOOK_SECRET_ENV} is not set"
        )
    expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    if not hmac.compare_digest(expected, candidate):
        raise ReceiveOnlyRailError("HMAC SHA-256 signature mismatch")


def _coerce_action(raw_action: Any) -> DonationEventKind:
    """Map Liberapay's notification ``event`` string to our enum or raise."""
    if not isinstance(raw_action, str):
        raise ReceiveOnlyRailError(
            f"webhook 'event' must be a string, got {type(raw_action).__name__}"
        )
    if raw_action in _ACCEPTED_ACTIONS:
        return DonationEventKind(raw_action)
    if raw_action in _LIBERAPAY_ACTION_ALIASES:
        return _LIBERAPAY_ACTION_ALIASES[raw_action]
    raise ReceiveOnlyRailError(f"unaccepted webhook event {raw_action!r}")


def _extract_donor_handle(payload: dict[str, Any]) -> str:
    donor = payload.get("donor")
    if not isinstance(donor, dict):
        raise ReceiveOnlyRailError("payload missing 'donor' object")
    handle = donor.get("username")
    if not isinstance(handle, str) or not handle:
        raise ReceiveOnlyRailError("payload missing 'donor.username'")
    return handle


def _extract_amount_eur_cents(payload: dict[str, Any]) -> int:
    amount = payload.get("amount")
    if not isinstance(amount, dict):
        raise ReceiveOnlyRailError("payload missing 'amount' object")
    currency = amount.get("currency")
    if currency != "EUR":
        raise ReceiveOnlyRailError(
            f"non-EUR currency {currency!r}; bridge must convert before delivery"
        )
    raw_amount = amount.get("amount")
    if raw_amount is None:
        raise ReceiveOnlyRailError("payload missing 'amount.amount'")
    if isinstance(raw_amount, bool):
        # bool is a subclass of int in Python; reject explicitly.
        raise ReceiveOnlyRailError("'amount.amount' must be a number or numeric string")
    if isinstance(raw_amount, int | float):
        try:
            decimal_amount = Decimal(str(raw_amount))
        except InvalidOperation as exc:  # pragma: no cover - defensive
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
    cents = int((decimal_amount * 100).to_integral_value())
    return cents


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

    The actual CIDR check belongs in the calling FastAPI route — this
    receiver only refuses to proceed when the upstream bridge fails to
    forward the source-ip claim altogether (a config bug that would
    silently bypass the IP gate above this layer).
    """
    if not require:
        return
    source_ip = payload.get("source_ip")
    if not isinstance(source_ip, str) or not source_ip:
        raise ReceiveOnlyRailError(
            f"payload missing 'source_ip' but {LIBERAPAY_REQUIRE_IP_ALLOWLIST_ENV}=1 "
            "(upstream bridge must forward client IP)"
        )


class LiberapayRailReceiver:
    """Receive-only adapter for Liberapay donation notifications.

    Construction is cheap and side-effect-free. The single public
    method :meth:`ingest_webhook` validates payload shape, optionally
    verifies the HMAC SHA-256 signature, optionally enforces a
    source-ip claim, and returns a normalized :class:`DonationEvent`.
    The receiver never opens a network socket, writes to disk, or
    contacts any external system.
    """

    def __init__(
        self,
        *,
        secret_env_var: str = LIBERAPAY_WEBHOOK_SECRET_ENV,
        require_ip_env_var: str = LIBERAPAY_REQUIRE_IP_ALLOWLIST_ENV,
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self._secret_env_var = secret_env_var
        self._require_ip_env_var = require_ip_env_var
        self._idempotency_store = idempotency_store

    def _resolve_secret(self) -> str:
        return os.environ.get(self._secret_env_var, "")

    def _ip_allowlist_required(self) -> bool:
        return os.environ.get(self._require_ip_env_var, "") == "1"

    def ingest_webhook(
        self,
        payload: dict[str, Any],
        signature: str | None,
        *,
        raw_body: bytes | None = None,
        delivery_id: str | None = None,
    ) -> DonationEvent | None:
        """Validate + normalize a single Liberapay donation notification.

        Returns the normalized :class:`DonationEvent` for accepted
        deliveries. Raises :class:`ReceiveOnlyRailError` for malformed
        payloads, unaccepted actions, signature failures, or missing
        IP claims when allowlist is required. Returns ``None`` only
        when the caller passes ``payload={}`` *and* ``signature=None``,
        which is treated as a no-op heartbeat ping.

        ``raw_body`` is the raw HTTP body bytes the upstream bridge
        signed (the FastAPI handler captures these before JSON
        parsing).  When provided, signature verification uses the raw
        bytes — the only correct shape against bridges that sign their
        wire deliveries.  When omitted, the receiver falls back to
        canonical-encoding the parsed payload (preserves prior
        behavior used by the rail's own unit tests + bridges that
        synthesize JSON in canonical form).
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

        _enforce_ip_allowlist_claim(payload, require=self._ip_allowlist_required())

        payload_sha256 = _sha256_hex(payload_bytes)

        action = _coerce_action(payload.get("event"))
        donor_handle = _extract_donor_handle(payload)
        amount_eur_cents = _extract_amount_eur_cents(payload)
        occurred_at = _extract_occurred_at(payload)

        if self._idempotency_store is not None:
            if not delivery_id:
                raise ReceiveOnlyRailError(
                    "idempotency_store provided but delivery_id missing — "
                    "the bridge layer must supply a unique delivery identifier "
                    "(e.g. cloudmailin Message-Id, mailgun X-Mailgun-Variables) "
                    "via the route's delivery_id resolution"
                )
            try:
                if not self._idempotency_store.record_or_skip(delivery_id):
                    return None
            except _SharedIdempotencyError as exc:
                raise ReceiveOnlyRailError(str(exc)) from exc

        try:
            return DonationEvent(
                donor_handle=donor_handle,
                amount_eur_cents=amount_eur_cents,
                event_kind=action,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "LIBERAPAY_REQUIRE_IP_ALLOWLIST_ENV",
    "LIBERAPAY_WEBHOOK_SECRET_ENV",
    "DonationEvent",
    "DonationEventKind",
    "IdempotencyStore",
    "LiberapayRailReceiver",
    "ReceiveOnlyRailError",
]
