"""GitHub Sponsors receive-only rail.

Phase 0 receiver for GitHub Sponsors webhook events. Normalizes inbound
``sponsorship.created`` / ``sponsorship.cancelled`` /
``sponsorship.tier_changed`` / ``sponsorship.pending_cancellation``
events into a typed, payer-aggregate ``SponsorshipEvent`` — *without*
calls, outbound writes, CRM, or per-supporter relationship surfaces.

**Receive-only invariant.** This module never originates an outbound
network call, never writes to an external system, and never persists
PII. ``sponsor_login`` is the GitHub-public handle the sponsor already
chose to associate with the gift; emails, payment methods, addresses,
and tier names beyond their amount are intentionally not extracted.

**Accepted event kinds.**

- ``created`` — new sponsorship begins.
- ``cancelled`` — existing sponsorship terminated (after grace period).
- ``tier_changed`` — sponsor moved to a different tier; new tier USD.
- ``pending_cancellation`` — cancellation requested, takes effect at
  ``effective_date`` per GitHub's webhook contract.

Other action strings GitHub may emit (``edited``, ``pending_tier_change``)
are rejected as *unaccepted-but-known*; entirely unknown strings are
rejected as *malformed*. Both raise :class:`ReceiveOnlyRailError`.

**Money type.** ``amount_usd_cents: int`` is the canonical money
field — always integer minor units (USD cents), never floating point.
Float arithmetic on money is a class of bug (``$0.10 + $0.20 ==
0.30000000000000004``) we structurally exclude. The receiver prefers
GitHub's ``monthly_price_in_cents`` (already integer); the
``monthly_price_in_dollars`` fallback is multiplied by 100 only when
the result is an exact integer (no fractional cents — e.g. $1.234
fails closed, $1.23 → 123).

**Governance constraint.** No PII, no outbound. The HMAC SHA-256
signature header is verified against ``GITHUB_SPONSORS_WEBHOOK_SECRET``
(``os.environ.get``; never hardcoded). Validation, signature, or
unknown-event failures fail-closed via :class:`ReceiveOnlyRailError`.

**REST → GraphQL deprecation (2026-03-10).** GitHub deprecated the
REST sponsors endpoint in favor of GraphQL on 2026-03-10. The
*webhook delivery path* — which is the only path this rail uses — is
unaffected: GitHub continues to ship `sponsorship.*` events with
HMAC SHA-256 over the raw body, and the payload schema fields the
rail extracts (``sponsorship.sponsor.login``, ``sponsorship.tier.
monthly_price_in_dollars`` / ``monthly_price_in_cents``,
``sponsorship.created_at`` / ``effective_date``) are stable across
both API surfaces. The deprecation only affects code that *queries*
the Sponsors API — which our receive-only invariant forbids by
design. No code change required.

**Canonicalization.** Module-private :func:`_canonical_bytes` produces
the byte stream the receiver hashes for the SHA-256 echo (and would
hash for HMAC verification when no ``raw_body`` is supplied). This is
the only canonicalizer in the module; the inline ``json.dumps`` call
that previously appeared in :meth:`ingest_webhook` was a drift item
(jr-github-sponsors-rail-cents-normalization).

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0,
GitHub Sponsors rail). Sibling rails:
``shared/license_request_price_class_router.py`` and
``shared/payment_aggregator_v2_support_normalizer.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from shared._rail_idempotency import (
    IdempotencyError as _SharedIdempotencyError,
)
from shared._rail_idempotency import (
    IdempotencyStore,
)

GITHUB_SPONSORS_WEBHOOK_SECRET_ENV = "GITHUB_SPONSORS_WEBHOOK_SECRET"


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected GitHub Sponsors webhook payload.

    Raised on malformed payloads, unaccepted action kinds, signature
    verification failures, missing fields, or shape violations. The
    receiver never silently drops or partially-accepts an inbound event.
    """


class SponsorshipEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver."""

    CREATED = "created"
    CANCELLED = "cancelled"
    TIER_CHANGED = "tier_changed"
    PENDING_CANCELLATION = "pending_cancellation"


_ACCEPTED_ACTIONS: frozenset[str] = frozenset(k.value for k in SponsorshipEventKind)


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SponsorshipEvent(_RailModel):
    """Normalized, payer-aggregate sponsorship event.

    *No PII fields exist on this type.* ``sponsor_login`` is the
    GitHub-public handle the sponsor selected. ``raw_payload_sha256``
    is included so a downstream consumer can correlate this normalized
    event to the original webhook delivery without re-storing the raw
    payload (which contains tier names and other text we do not want
    to persist beyond the receiver boundary).
    """

    sponsor_login: str = Field(min_length=1, max_length=255)
    amount_usd_cents: int = Field(ge=0)
    event_kind: SponsorshipEventKind
    occurred_at: datetime
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("sponsor_login")
    @classmethod
    def _login_is_handle_only(cls, value: str) -> str:
        """``sponsor_login`` must look like a GitHub username, not an email."""
        if "@" in value or "/" in value or " " in value:
            raise ValueError(
                "sponsor_login must be a GitHub handle, not an email or qualified path"
            )
        return value


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Canonical JSON encoding for HMAC + SHA-256 echo.

    Sorted keys, no whitespace separators, UTF-8 — the only canonical
    form the receiver hashes. Pulled out of :meth:`ingest_webhook` so
    every consumer (signature verifier, sha256 echo, future test
    fixtures) shares one implementation.
    """
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _verify_signature(payload_bytes: bytes, signature: str, secret: str) -> None:
    """Fail-closed HMAC SHA-256 verification.

    GitHub's signature header is ``sha256=<hexdigest>``. Both that and
    a bare hex digest are accepted (the receiver strips the prefix if
    present). Mismatch raises :class:`ReceiveOnlyRailError`.
    """
    if not secret:
        raise ReceiveOnlyRailError(
            f"signature provided but {GITHUB_SPONSORS_WEBHOOK_SECRET_ENV} is not set"
        )
    expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    candidate = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    if not hmac.compare_digest(expected, candidate):
        raise ReceiveOnlyRailError("HMAC SHA-256 signature mismatch")


def _coerce_action(raw_action: Any) -> SponsorshipEventKind:
    """Map GitHub's ``action`` string to our enum or raise."""
    if not isinstance(raw_action, str):
        raise ReceiveOnlyRailError(
            f"webhook 'action' must be a string, got {type(raw_action).__name__}"
        )
    if raw_action not in _ACCEPTED_ACTIONS:
        raise ReceiveOnlyRailError(f"unaccepted webhook action {raw_action!r}")
    return SponsorshipEventKind(raw_action)


def _extract_sponsor_login(payload: dict[str, Any]) -> str:
    sponsorship = payload.get("sponsorship")
    if not isinstance(sponsorship, dict):
        raise ReceiveOnlyRailError("payload missing 'sponsorship' object")
    sponsor = sponsorship.get("sponsor")
    if not isinstance(sponsor, dict):
        raise ReceiveOnlyRailError("payload missing 'sponsorship.sponsor' object")
    login = sponsor.get("login")
    if not isinstance(login, str) or not login:
        raise ReceiveOnlyRailError("payload missing 'sponsorship.sponsor.login'")
    return login


def _extract_amount_usd_cents(payload: dict[str, Any]) -> int:
    """Return tier amount as integer USD cents.

    Prefers ``monthly_price_in_cents`` (GitHub already emits it as
    integer cents — the canonical wire shape). Falls back to
    ``monthly_price_in_dollars × 100`` only when the dollars value
    multiplies to an exact integer; fractional cents (e.g. $1.234)
    fail-closed because money is integer-cents by invariant.

    Bool-typed values are rejected (``True`` is an ``int`` in Python).
    """
    sponsorship = payload.get("sponsorship", {})
    tier = sponsorship.get("tier") if isinstance(sponsorship, dict) else None
    if not isinstance(tier, dict):
        raise ReceiveOnlyRailError("payload missing 'sponsorship.tier' object")

    cents_raw = tier.get("monthly_price_in_cents")
    if cents_raw is not None:
        if isinstance(cents_raw, bool) or not isinstance(cents_raw, int):
            raise ReceiveOnlyRailError(
                f"'sponsorship.tier.monthly_price_in_cents' must be int, "
                f"got {type(cents_raw).__name__}"
            )
        if cents_raw < 0:
            raise ReceiveOnlyRailError(f"tier amount must be non-negative, got {cents_raw}")
        return cents_raw

    dollars_raw = tier.get("monthly_price_in_dollars")
    if dollars_raw is None:
        raise ReceiveOnlyRailError(
            "payload missing 'sponsorship.tier.monthly_price_in_cents' "
            "or 'monthly_price_in_dollars'"
        )
    if isinstance(dollars_raw, bool) or not isinstance(dollars_raw, int | float):
        raise ReceiveOnlyRailError(
            f"'sponsorship.tier.monthly_price_in_dollars' must be int or float, "
            f"got {type(dollars_raw).__name__}"
        )
    if dollars_raw < 0:
        raise ReceiveOnlyRailError(f"tier amount must be non-negative, got {dollars_raw}")

    cents_float = float(dollars_raw) * 100.0
    cents_int = round(cents_float)
    if abs(cents_float - cents_int) > 1e-6:
        raise ReceiveOnlyRailError(
            f"'monthly_price_in_dollars'={dollars_raw} does not multiply to integer cents "
            f"(got {cents_float}); fractional-cent amounts are not accepted"
        )
    return cents_int


def _extract_occurred_at(payload: dict[str, Any]) -> datetime:
    sponsorship = payload.get("sponsorship", {})
    if not isinstance(sponsorship, dict):
        raise ReceiveOnlyRailError("payload missing 'sponsorship' object")
    raw = sponsorship.get("created_at") or payload.get("effective_date")
    if not isinstance(raw, str) or not raw:
        raise ReceiveOnlyRailError("payload missing 'sponsorship.created_at' / 'effective_date'")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiveOnlyRailError(f"invalid ISO 8601 timestamp {raw!r}: {exc}") from exc


class GitHubSponsorsRailReceiver:
    """Receive-only adapter for GitHub Sponsors webhooks.

    Construction is cheap and side-effect-free. The single public
    method :meth:`ingest_webhook` validates payload shape, optionally
    verifies the HMAC SHA-256 signature, and returns a normalized
    :class:`SponsorshipEvent`. The receiver never opens a network
    socket, writes to disk, or contacts any external system.
    """

    def __init__(
        self,
        *,
        secret_env_var: str = GITHUB_SPONSORS_WEBHOOK_SECRET_ENV,
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
    ) -> SponsorshipEvent | None:
        """Validate + normalize a single GitHub Sponsors webhook delivery.

        Returns the normalized :class:`SponsorshipEvent` for accepted
        deliveries. Raises :class:`ReceiveOnlyRailError` for malformed
        payloads, unaccepted actions, or signature failures. Returns
        ``None`` only when the caller passes ``payload={}`` *and*
        ``signature=None``, which is treated as a no-op heartbeat ping
        from a pre-flight ping delivery.

        ``raw_body`` is the raw HTTP body bytes GitHub signed (the
        FastAPI handler captures these before JSON parsing).  When
        provided, signature verification uses the raw bytes — this is
        the only correct shape against live GitHub deliveries.  When
        omitted, the receiver falls back to canonical-encoding the
        parsed payload, which works for round-trip test fixtures but
        will spuriously fail against real wire deliveries.
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

        action = _coerce_action(payload.get("action"))
        sponsor_login = _extract_sponsor_login(payload)
        amount_usd_cents = _extract_amount_usd_cents(payload)
        occurred_at = _extract_occurred_at(payload)

        if self._idempotency_store is not None:
            if not delivery_id:
                raise ReceiveOnlyRailError(
                    "idempotency_store provided but delivery_id missing — "
                    "GitHub webhook deliveries carry the per-delivery "
                    "identifier in the X-GitHub-Delivery header"
                )
            try:
                if not self._idempotency_store.record_or_skip(delivery_id):
                    return None
            except _SharedIdempotencyError as exc:
                raise ReceiveOnlyRailError(str(exc)) from exc

        try:
            return SponsorshipEvent(
                sponsor_login=sponsor_login,
                amount_usd_cents=amount_usd_cents,
                event_kind=action,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "GITHUB_SPONSORS_WEBHOOK_SECRET_ENV",
    "GitHubSponsorsRailReceiver",
    "IdempotencyStore",
    "ReceiveOnlyRailError",
    "SponsorshipEvent",
    "SponsorshipEventKind",
]
