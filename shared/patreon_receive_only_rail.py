"""Patreon receive-only rail.

Phase 0 receiver for Patreon webhook events. Normalizes inbound
``members:create`` / ``members:update`` / ``members:pledge:create`` /
``members:pledge:delete`` deliveries into a typed, payer-aggregate
``PledgeEvent`` — *without* calls, outbound writes, CRM, or
per-supporter relationship surfaces.

**Receive-only invariant.** This module never originates an outbound
network call, never writes to an external system, and never persists
PII. ``patron_handle`` is the patron's public Patreon vanity URL
slug (the public handle that appears in their Patreon profile URL,
e.g. ``patreon.com/<vanity>``). ``email``, ``full_name``, billing
address, ``note``, ``last_charge_date`` of any individual cycle, and
any other personally-identifying or transactional-history fields the
JSON:API ``included`` array surfaces are intentionally not extracted.

**No Patreon SDK.** This module deliberately does NOT import any
Patreon Python SDK or REST client (``patreon``, ``patreon-python``).
SDKs pull in HTTP client surfaces and support outbound API calls —
neither belongs in a receive-only rail. HMAC MD5 verification per
Patreon's documented ``X-Patreon-Signature`` header format is
implemented inline using only ``hmac`` + ``hashlib`` from the
standard library.

**MD5 vs SHA-256 — Patreon's wire format.** Patreon signs webhook
deliveries with HMAC **MD5**, not SHA-256 (Patreon API documentation,
https://docs.patreon.com/?javascript#webhooks). This is a divergence
from every sibling rail in the family: GitHub Sponsors, Liberapay,
Open Collective, and Stripe Payment Link all use HMAC SHA-256 (the
last two with additional shape — JSON:API + JWT for Open Collective,
timestamped + replay window for Stripe). MD5 is cryptographically
broken for collision-resistance but remains *practically* unforgeable
for HMAC use because HMAC's keyed construction does not depend on
collision-resistance for its security proof — see RFC 2104 §6 and
NIST SP 800-107r1 §5.3.4. We implement MD5 here to match Patreon's
wire format; this is **not** a security improvement we should make,
and we do not silently upgrade to SHA-256 because doing so would
break verification against legitimate deliveries. Document, do not
fix, the upstream choice.

**JSON:API payload structure — new shape vs prior rails.** Patreon
webhooks ship JSON:API-compliant payloads (https://jsonapi.org/), a
substantially different envelope from the flat dicts shipped by
GitHub Sponsors, Liberapay, Open Collective, or Stripe. The payload
shape is::

    {
        "data": {
            "type": "member",
            "id": "<member-id>",
            "attributes": {
                "patron_status": "active_patron" | "declined_patron" | "former_patron" | None,
                "currently_entitled_amount_cents": <int>,
                "will_pay_amount_cents": <int>,
                "pledge_relationship_start": "<ISO 8601>",
                "last_charge_status": "Paid" | "Declined" | ...,
                "last_charge_date": "<ISO 8601>",
                "lifetime_support_cents": <int>,
                "campaign_lifetime_support_cents": <int>,
                # PII fields we do NOT extract:
                "email": ..., "full_name": ..., "note": ...
            },
            "relationships": {
                "user": {"data": {"type": "user", "id": "<user-id>"}},
                "campaign": {"data": {"type": "campaign", "id": "<campaign-id>"}},
                "currently_entitled_tiers": {"data": [...]}
            }
        },
        "included": [
            {"type": "user", "id": "<user-id>",
             "attributes": {"vanity": "<patron-handle>", "url": "..."}},
            {"type": "campaign", "id": "<campaign-id>",
             "attributes": {"currency": "USD", "vanity": "<creator-vanity>"}}
        ]
    }

The receiver:

1. Reads the event kind from the ``X-Patreon-Event`` header (passed
   in alongside the payload).
2. Extracts ``data.attributes.currently_entitled_amount_cents`` (or
   ``will_pay_amount_cents`` for the ``members:pledge:create`` shape
   when entitlement is not yet computed).
3. Walks ``included[]`` for the related ``user`` resource and reads
   its ``attributes.vanity`` to get the patron's public handle. This
   is the only patron field extracted; ``email`` / ``full_name`` /
   ``url`` are intentionally skipped.
4. Walks ``included[]`` for the related ``campaign`` resource and
   reads its ``attributes.currency`` (ISO 4217 3-letter code) to
   determine the donation currency. Patreon allows campaigns to be
   denominated in non-USD (EUR, GBP, CAD, AUD, etc.) and the patron's
   currency follows the campaign.

Other event kinds Patreon may emit (``members:delete``,
``members:pledge:update``, ``posts:publish``, ``posts:update``,
``posts:delete``) are rejected as *unaccepted-but-known*; entirely
unknown strings are rejected as *malformed*. Both raise
:class:`ReceiveOnlyRailError`.

**Multi-currency.** Patreon campaigns are denominated in the creator's
chosen currency (USD by default, but EUR/GBP/CAD/AUD and other ISO
4217 currencies are supported). Patreon emits ``amount_cents`` in the
campaign currency's minor units (cents/pence/euro-cents). Like the
Stripe Payment Link rail (and unlike the GitHub Sponsors / Liberapay
rails), this receiver preserves the source currency on the normalized
event. The ``amount_currency_cents`` field is integer minor-units in
the currency named by ``currency``. Downstream consumers are
responsible for any FX normalization.

**Governance constraint.** No PII (no ``email``, ``full_name``,
billing address, ``note``, ``last_charge_date``), no outbound,
multi-currency normalized to lowest-unit cents in the source
currency. This is the FIRST rail in the family to implement HMAC MD5
(per Patreon's documented wire format) and the FIRST rail to handle
JSON:API envelope shape with ``included[]`` resource walking. The
webhook secret is read from ``PATREON_WEBHOOK_SECRET``
(``os.environ.get``; never hardcoded). Validation, signature, or
unknown-event failures fail-closed via :class:`ReceiveOnlyRailError`.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0,
Patreon rail). Sibling rails:
``shared/github_sponsors_receive_only_rail.py`` (#2218),
``shared/liberapay_receive_only_rail.py`` (#2219),
``shared/open_collective_receive_only_rail.py`` (#2226), and
``shared/stripe_payment_link_receive_only_rail.py`` (#2227). HMAC MD5
+ JSON:API ``included[]`` walking are the new shapes this rail
introduces vs the prior four.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

PATREON_WEBHOOK_SECRET_ENV = "PATREON_WEBHOOK_SECRET"

_ISO_4217_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
#: Patreon vanity slugs are URL path segments — alphanumerics, dashes,
#: dots, underscores. Whitespace and ``@`` are explicit rejection
#: signals (would mean the upstream leaked an email or display name
#: into the field).
_PATREON_VANITY_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected Patreon webhook payload.

    Raised on malformed payloads, unaccepted event kinds, signature
    verification failures, missing fields, malformed currency codes,
    or shape violations. The receiver never silently drops or
    partially-accepts an inbound event.
    """


class PledgeEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver.

    Patreon's documented webhook triggers are in
    ``namespace:resource[:action]`` form (e.g. ``members:create``,
    ``members:pledge:create``). The enum stores the underscored
    canonical form; the receiver also accepts the colon-delimited
    form on ingest via :data:`_PATREON_EVENT_ALIASES`.
    """

    MEMBERS_CREATE = "members_create"
    MEMBERS_UPDATE = "members_update"
    MEMBERS_PLEDGE_CREATE = "members_pledge_create"
    MEMBERS_PLEDGE_DELETE = "members_pledge_delete"


_ACCEPTED_EVENTS: frozenset[str] = frozenset(k.value for k in PledgeEventKind)
_PATREON_EVENT_ALIASES: dict[str, PledgeEventKind] = {
    # Patreon emits colon-delimited event kinds; both the colon form
    # and the underscored canonical form are accepted on ingest.
    "members:create": PledgeEventKind.MEMBERS_CREATE,
    "members:update": PledgeEventKind.MEMBERS_UPDATE,
    "members:pledge:create": PledgeEventKind.MEMBERS_PLEDGE_CREATE,
    "members:pledge:delete": PledgeEventKind.MEMBERS_PLEDGE_DELETE,
}


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PledgeEvent(_RailModel):
    """Normalized, payer-aggregate Patreon pledge event.

    *No PII fields exist on this type.* ``patron_handle`` is the
    patron's public Patreon vanity slug (the path segment from
    ``patreon.com/<vanity>``) — already public-by-the-patron's-choice
    when they registered it on their profile. ``email``, ``full_name``,
    billing address, ``note``, and any cycle-by-cycle charge history
    are intentionally not extracted.

    ``amount_currency_cents`` is integer minor-units (cents, pence,
    euro-cents) in the source currency named by ``currency``. Patreon
    emits ``amount_cents`` already in minor units, so no rounding
    occurs at the receiver boundary. ``currency`` is the ISO 4217
    3-letter uppercase code of the campaign currency.

    ``raw_payload_sha256`` is included so a downstream consumer can
    correlate this normalized event to the original webhook delivery
    without re-storing the raw payload (which contains email,
    full_name, billing addresses, and other fields we do not want to
    persist beyond the receiver boundary).
    """

    patron_handle: str = Field(min_length=1, max_length=255)
    amount_currency_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    event_kind: PledgeEventKind
    occurred_at: datetime
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("patron_handle")
    @classmethod
    def _handle_is_vanity_only(cls, value: str) -> str:
        """``patron_handle`` must look like a Patreon vanity slug, not an email."""
        if "@" in value or "/" in value or " " in value:
            raise ValueError(
                "patron_handle must be a Patreon vanity slug, not an email or qualified path"
            )
        if not _PATREON_VANITY_RE.fullmatch(value):
            raise ValueError(
                "patron_handle must match Patreon vanity slug character set "
                f"([A-Za-z0-9._-]+), got {value!r}"
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
    """Fail-closed Patreon HMAC MD5 verification.

    Per Patreon's documented spec
    (https://docs.patreon.com/?javascript#webhooks), the
    ``X-Patreon-Signature`` header carries a hex-encoded HMAC MD5
    digest of the raw request body computed with the webhook secret.
    We use ``hmac.compare_digest`` for constant-time comparison even
    though MD5's collision properties are weak — the keyed-HMAC
    construction does not require collision-resistance for its
    security proof (RFC 2104 §6). Mismatch raises
    :class:`ReceiveOnlyRailError`.

    NOTE: MD5 is Patreon's wire format choice (not ours). We do not
    silently upgrade to SHA-256 because doing so would break
    verification against every legitimate Patreon delivery. The MD5
    selection is documented in this module's header.
    """
    if not secret:
        raise ReceiveOnlyRailError(
            f"signature provided but {PATREON_WEBHOOK_SECRET_ENV} is not set"
        )
    expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.md5).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ReceiveOnlyRailError("Patreon HMAC MD5 signature mismatch")


def _coerce_event_kind(raw_event: Any) -> PledgeEventKind:
    """Map Patreon's ``X-Patreon-Event`` header value to our enum or raise."""
    if not isinstance(raw_event, str):
        raise ReceiveOnlyRailError(
            f"webhook event header must be a string, got {type(raw_event).__name__}"
        )
    if raw_event in _ACCEPTED_EVENTS:
        return PledgeEventKind(raw_event)
    if raw_event in _PATREON_EVENT_ALIASES:
        return _PATREON_EVENT_ALIASES[raw_event]
    raise ReceiveOnlyRailError(f"unaccepted webhook event kind {raw_event!r}")


def _extract_data_object(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the JSON:API ``data`` envelope or raise.

    Patreon webhooks always carry a top-level ``data`` object (the
    primary resource of the delivery), with ``type``, ``id``,
    ``attributes``, and ``relationships`` per JSON:API.
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ReceiveOnlyRailError("payload missing 'data' object")
    return data


def _extract_attributes(data: dict[str, Any]) -> dict[str, Any]:
    attributes = data.get("attributes")
    if not isinstance(attributes, dict):
        raise ReceiveOnlyRailError("payload missing 'data.attributes' dict")
    return attributes


def _walk_included(payload: dict[str, Any], resource_type: str) -> dict[str, Any] | None:
    """Return the first ``included[]`` entry matching ``resource_type``.

    JSON:API responses may inline related resources in a top-level
    ``included`` array. Each entry has its own ``type``, ``id``, and
    ``attributes``. This helper walks the array and returns the first
    entry whose ``type`` matches; returns ``None`` if no entry matches
    (the caller decides whether absence is a hard failure or a
    soft fallback).
    """
    included = payload.get("included")
    if not isinstance(included, list):
        return None
    for entry in included:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == resource_type:
            return entry
    return None


def _extract_patron_handle(payload: dict[str, Any]) -> str:
    """Walk ``included[]`` for the related ``user`` resource and read its vanity.

    The ``user`` resource carries ``attributes.vanity`` (the public
    Patreon profile slug). If no ``user`` is included or the vanity is
    missing, fall back to the ``user`` ID from
    ``data.relationships.user.data.id`` (an opaque numeric Patreon
    user ID — not PII, just an internal handle). Raises if neither is
    present.
    """
    user = _walk_included(payload, "user")
    if isinstance(user, dict):
        attributes = user.get("attributes")
        if isinstance(attributes, dict):
            vanity = attributes.get("vanity")
            if isinstance(vanity, str) and vanity.strip():
                return vanity.strip()
    # Fallback: the relationship reference contains the user ID.
    data = payload.get("data", {})
    relationships = data.get("relationships") if isinstance(data, dict) else None
    if isinstance(relationships, dict):
        user_rel = relationships.get("user")
        if isinstance(user_rel, dict):
            user_data = user_rel.get("data")
            if isinstance(user_data, dict):
                user_id = user_data.get("id")
                if isinstance(user_id, str) and user_id.strip():
                    return user_id.strip()
    raise ReceiveOnlyRailError(
        "payload missing both included[type=user].attributes.vanity and "
        "data.relationships.user.data.id"
    )


def _extract_amount_cents(attributes: dict[str, Any], event_kind: PledgeEventKind) -> int:
    """Extract integer minor-unit amount from member/pledge attributes.

    Patreon emits amounts as integer cents already; no decimal
    conversion is needed at this boundary. Field selection by event:

    - ``members:create`` / ``members:update`` /
      ``members:pledge:create`` → ``currently_entitled_amount_cents``
      preferred (current entitled tier amount), falls back to
      ``will_pay_amount_cents`` (next-cycle pledge amount, useful when
      entitlement is not yet computed e.g. mid-trial).
    - ``members:pledge:delete`` → fall back to ``will_pay_amount_cents``
      then ``currently_entitled_amount_cents`` (delete events may carry
      either depending on cycle position); default to 0 if neither
      shipped (delete may carry only IDs).

    Negative amounts (refunds/chargebacks) are converted to absolute
    value so the rail expresses gross movement; net flow is
    reconstructed by event_kind downstream.
    """
    if event_kind in (
        PledgeEventKind.MEMBERS_CREATE,
        PledgeEventKind.MEMBERS_UPDATE,
    ):
        candidates = (
            attributes.get("currently_entitled_amount_cents"),
            attributes.get("will_pay_amount_cents"),
        )
    else:
        # MEMBERS_PLEDGE_CREATE / MEMBERS_PLEDGE_DELETE — the pledge-shape
        # events carry ``will_pay_amount_cents`` as the canonical "what the
        # patron is committing to next cycle" field; ``currently_entitled``
        # is often 0 here (entitlement not yet computed mid-trial / mid-cycle).
        candidates = (
            attributes.get("will_pay_amount_cents"),
            attributes.get("currently_entitled_amount_cents"),
        )
    for amount in candidates:
        if isinstance(amount, bool):
            continue
        if isinstance(amount, int):
            return abs(amount)
    if event_kind is PledgeEventKind.MEMBERS_PLEDGE_DELETE:
        return 0
    raise ReceiveOnlyRailError(
        "payload missing 'currently_entitled_amount_cents' or "
        "'will_pay_amount_cents' on data.attributes"
    )


def _extract_currency(payload: dict[str, Any]) -> str:
    """Walk ``included[]`` for the related ``campaign`` resource and read currency.

    Patreon campaigns declare ``attributes.currency`` (ISO 4217
    3-letter code, may be lowercase per Patreon's emit convention).
    Defaults to ``"USD"`` if no campaign is included (Patreon's
    default campaign currency when not otherwise specified).
    """
    campaign = _walk_included(payload, "campaign")
    if isinstance(campaign, dict):
        attributes = campaign.get("attributes")
        if isinstance(attributes, dict):
            currency = attributes.get("currency")
            if isinstance(currency, str) and currency.strip():
                return currency.strip().upper()
    return "USD"


def _extract_occurred_at(attributes: dict[str, Any], event_kind: PledgeEventKind) -> datetime:
    """Extract the event timestamp from member attributes.

    Patreon does not ship a top-level ``created`` timestamp on the
    webhook envelope (unlike Stripe). The most relevant per-event
    timestamps live on ``data.attributes``:

    - ``members:create`` / ``members:pledge:create`` →
      ``pledge_relationship_start`` (when the patron-creator
      relationship began).
    - ``members:update`` / ``members:pledge:delete`` →
      ``last_charge_date`` if present, else
      ``pledge_relationship_start``.

    Both are ISO 8601 strings. We deliberately do NOT extract the
    full per-cycle charge history (which lives in ``included[]`` as a
    ``pledge-event`` resource); only the single anchor timestamp
    relevant to this delivery enters the normalized event.
    """
    if event_kind in (
        PledgeEventKind.MEMBERS_CREATE,
        PledgeEventKind.MEMBERS_PLEDGE_CREATE,
    ):
        candidates = (
            attributes.get("pledge_relationship_start"),
            attributes.get("last_charge_date"),
        )
    else:
        candidates = (
            attributes.get("last_charge_date"),
            attributes.get("pledge_relationship_start"),
        )
    for raw in candidates:
        if isinstance(raw, str) and raw:
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ReceiveOnlyRailError(f"invalid ISO 8601 timestamp {raw!r}: {exc}") from exc
    raise ReceiveOnlyRailError(
        "payload missing 'pledge_relationship_start' / 'last_charge_date' on data.attributes"
    )


class PatreonRailReceiver:
    """Receive-only adapter for Patreon webhooks.

    Construction is cheap and side-effect-free. The single public
    method :meth:`ingest_webhook` validates payload shape, optionally
    verifies the HMAC MD5 signature, and returns a normalized
    :class:`PledgeEvent`. The receiver never opens a network socket,
    writes to disk, or contacts any external system.

    Patreon ships event kind in the ``X-Patreon-Event`` HTTP header
    (not in the body), so callers must pass it as the ``event_header``
    argument alongside the payload. Patreon ships signature in the
    ``X-Patreon-Signature`` HTTP header.
    """

    def __init__(self, *, secret_env_var: str = PATREON_WEBHOOK_SECRET_ENV) -> None:
        self._secret_env_var = secret_env_var

    def _resolve_secret(self) -> str:
        return os.environ.get(self._secret_env_var, "")

    def ingest_webhook(
        self,
        payload: dict[str, Any],
        signature: str | None,
        event_header: str | None,
        *,
        raw_body: bytes | None = None,
    ) -> PledgeEvent | None:
        """Validate + normalize a single Patreon webhook delivery.

        Returns the normalized :class:`PledgeEvent` for accepted
        deliveries. Raises :class:`ReceiveOnlyRailError` for malformed
        payloads, unaccepted event kinds, or signature failures.
        Returns ``None`` only when the caller passes ``payload={}``,
        ``signature=None``, *and* ``event_header=None``, which is
        treated as a no-op heartbeat (Patreon does not ship a formal
        ping but operators may invoke the receiver with empty input
        for liveness checks).

        ``raw_body`` is the raw HTTP body bytes Patreon signed
        (Patreon signs ``raw_body`` with HMAC MD5 in the
        ``X-Patreon-Signature`` header).  When provided, signature
        verification uses the raw bytes — the only correct shape
        against live Patreon deliveries.  When omitted, the receiver
        falls back to canonical-encoding the parsed payload (preserves
        prior behavior the rail's own unit tests rely on).
        """
        if not isinstance(payload, dict):
            raise ReceiveOnlyRailError(f"payload must be a dict, got {type(payload).__name__}")

        if not payload and signature is None and event_header is None:
            return None

        if event_header is None:
            raise ReceiveOnlyRailError(
                "missing 'X-Patreon-Event' header (event kind is header-borne, not body-borne)"
            )

        canonical = _canonical_bytes(payload)
        payload_bytes = raw_body if raw_body is not None else canonical

        if signature is not None:
            secret = self._resolve_secret()
            _verify_signature(payload_bytes, signature, secret)

        payload_sha256 = _sha256_hex(payload_bytes)

        event_kind = _coerce_event_kind(event_header)
        data = _extract_data_object(payload)
        attributes = _extract_attributes(data)
        patron_handle = _extract_patron_handle(payload)
        amount_cents = _extract_amount_cents(attributes, event_kind)
        currency = _extract_currency(payload)
        occurred_at = _extract_occurred_at(attributes, event_kind)

        try:
            return PledgeEvent(
                patron_handle=patron_handle,
                amount_currency_cents=amount_cents,
                currency=currency,
                event_kind=event_kind,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "PATREON_WEBHOOK_SECRET_ENV",
    "PatreonRailReceiver",
    "PledgeEvent",
    "PledgeEventKind",
    "ReceiveOnlyRailError",
]
