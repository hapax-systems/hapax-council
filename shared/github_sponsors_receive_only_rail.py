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

**Governance constraint.** No PII, no outbound. The HMAC SHA-256
signature header is verified against ``GITHUB_SPONSORS_WEBHOOK_SECRET``
(``os.environ.get``; never hardcoded). Validation, signature, or
unknown-event failures fail-closed via :class:`ReceiveOnlyRailError`.

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
    tier_amount_usd: float = Field(ge=0)
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


def _extract_tier_amount_usd(payload: dict[str, Any]) -> float:
    sponsorship = payload.get("sponsorship", {})
    tier = sponsorship.get("tier") if isinstance(sponsorship, dict) else None
    if not isinstance(tier, dict):
        raise ReceiveOnlyRailError("payload missing 'sponsorship.tier' object")
    amount = tier.get("monthly_price_in_dollars")
    if amount is None:
        amount = tier.get("monthly_price_in_cents")
        if isinstance(amount, int | float):
            amount = float(amount) / 100.0
    if not isinstance(amount, int | float):
        raise ReceiveOnlyRailError(
            "payload missing 'sponsorship.tier.monthly_price_in_dollars' "
            "or 'monthly_price_in_cents'"
        )
    if amount < 0:
        raise ReceiveOnlyRailError(f"tier amount must be non-negative, got {amount}")
    return float(amount)


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

    def __init__(self, *, secret_env_var: str = GITHUB_SPONSORS_WEBHOOK_SECRET_ENV) -> None:
        self._secret_env_var = secret_env_var

    def _resolve_secret(self) -> str:
        return os.environ.get(self._secret_env_var, "")

    def ingest_webhook(
        self, payload: dict[str, Any], signature: str | None
    ) -> SponsorshipEvent | None:
        """Validate + normalize a single GitHub Sponsors webhook delivery.

        Returns the normalized :class:`SponsorshipEvent` for accepted
        deliveries. Raises :class:`ReceiveOnlyRailError` for malformed
        payloads, unaccepted actions, or signature failures. Returns
        ``None`` only when the caller passes ``payload={}`` *and*
        ``signature=None``, which is treated as a no-op heartbeat ping
        from a pre-flight ping delivery.
        """
        if not isinstance(payload, dict):
            raise ReceiveOnlyRailError(f"payload must be a dict, got {type(payload).__name__}")

        if not payload and signature is None:
            return None

        if signature is not None:
            secret = self._resolve_secret()
            payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
            _verify_signature(payload_bytes, signature, secret)
            payload_sha256 = _sha256_hex(payload_bytes)
        else:
            payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
            payload_sha256 = _sha256_hex(payload_bytes)

        action = _coerce_action(payload.get("action"))
        sponsor_login = _extract_sponsor_login(payload)
        tier_amount_usd = _extract_tier_amount_usd(payload)
        occurred_at = _extract_occurred_at(payload)

        try:
            return SponsorshipEvent(
                sponsor_login=sponsor_login,
                tier_amount_usd=tier_amount_usd,
                event_kind=action,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "GITHUB_SPONSORS_WEBHOOK_SECRET_ENV",
    "GitHubSponsorsRailReceiver",
    "ReceiveOnlyRailError",
    "SponsorshipEvent",
    "SponsorshipEventKind",
]
