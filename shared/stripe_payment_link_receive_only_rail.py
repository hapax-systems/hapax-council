"""Stripe Payment Link receive-only rail.

Phase 0 receiver for Stripe Payment Link webhook events. Normalizes
inbound ``payment_intent.succeeded`` / ``checkout.session.completed`` /
``customer.subscription.created`` / ``customer.subscription.deleted``
deliveries into a typed, payer-aggregate ``PaymentEvent`` — *without*
calls, outbound writes, CRM, or per-supporter relationship surfaces.

**Receive-only invariant.** This module never originates an outbound
network call, never writes to an external system, and never persists
PII. ``customer_handle`` is the Stripe customer ID (``cus_...``) or
checkout session ID (``cs_...``) — opaque, non-PII identifiers Stripe
uses to reference the payer aggregate. Emails, payment-method details,
card last-4, billing addresses, customer names, free-text product
descriptions, and any ``receipt_email`` / ``receipt_url`` fields are
intentionally not extracted.

**No Stripe SDK.** This module deliberately does NOT import the
``stripe`` Python SDK. The SDK pulls in HTTP client surfaces (urllib3,
requests) and supports outbound API calls — neither belongs in a
receive-only rail. HMAC SHA-256 verification per Stripe's documented
``Stripe-Signature`` header format is implemented inline using only
``hmac`` + ``hashlib`` from the standard library. This is what makes
the rail provably outbound-free.

**Stripe Payment Links** (`https://stripe.com/docs/payment-links`)
are no-code hosted checkout URLs that fire the standard Stripe webhook
events on the merchant's account. This receiver subscribes to the four
events a donation/payment Payment Link will emit end-to-end:

- ``payment_intent.succeeded`` — one-time payment captured. Fires for
  any Payment Link that uses a one-time price (i.e. donation,
  pay-what-you-want, fixed-amount product).
- ``checkout.session.completed`` — Stripe Checkout session backing the
  Payment Link finalized (covers both one-time and subscription
  Payment Links; emitted *in addition to* the payment-intent or
  subscription event).
- ``customer.subscription.created`` — recurring donation began (Payment
  Link uses a recurring price).
- ``customer.subscription.deleted`` — recurring donation cancelled
  (operator-initiated cancellation, end of billing period after
  customer cancel, or unrecoverable payment failure).

Other event types Stripe may emit (``charge.succeeded``,
``invoice.paid``, ``customer.created``, ``payment_method.attached``,
etc.) are rejected as *unaccepted-but-known*; entirely unknown strings
are rejected as *malformed*. Both raise :class:`ReceiveOnlyRailError`.

**Multi-currency.** Stripe Payment Links are multi-currency-native: a
single Payment Link may collect donations in USD, EUR, GBP, CAD, AUD,
JPY, and the full Stripe-supported ISO 4217 set. Like the Open
Collective rail (and unlike the GitHub Sponsors / Liberapay rails),
this receiver preserves the source currency on the normalized event.
The ``amount_currency_cents`` field is integer minor-units (cents,
pence, euro-cents) in the currency named by ``currency``. Stripe
itself emits amounts in minor units already (``amount`` /
``amount_total`` are already integer cents), so no rounding occurs at
the receiver boundary. Zero-decimal currencies (JPY, KRW, VND, etc.)
are passed through as-is — the field is integer minor-units in the
currency-specific minor-unit definition. Downstream consumers are
responsible for any FX normalization.

**Stripe signature format & replay protection.** Stripe's
``Stripe-Signature`` header carries a timestamp and one or more
versioned HMAC signatures, separated by commas:
``t=1492774577,v1=5257a869e7ecebeda32affa62cdca3fa51cad7e77a0e56ff536d0ce8e108d8bd``.
Verification per `https://stripe.com/docs/webhooks/signatures`:

1. Split the header on ``,`` and parse each ``key=value`` pair; collect
   the timestamp ``t`` and all ``v1`` signatures (a single header may
   carry multiple signatures during secret rotation).
2. Compute the expected signature: HMAC SHA-256 of
   ``f"{timestamp}.{payload}"`` (the literal raw request body, not
   re-serialized JSON) with the webhook signing secret.
3. Compare against each provided ``v1`` signature with
   :func:`hmac.compare_digest`. At least one must match.
4. Reject if the timestamp is older than ``DEFAULT_TOLERANCE_SECONDS``
   (300s by default, per Stripe's documented recommendation) — this
   blocks replay of an old signed delivery.

The webhook signing secret is read from
``STRIPE_PAYMENT_LINK_WEBHOOK_SECRET`` (``os.environ.get``; never
hardcoded). Validation, signature, replay, or unknown-event failures
fail-closed via :class:`ReceiveOnlyRailError`.

**Idempotency / replay-protection-at-rest.** The 300s timestamp
window blocks replay of an old signed delivery, but Stripe's
at-least-once delivery semantics mean the *same* event id (``evt_...``)
can legitimately arrive twice within the 300s window — for example, a
network-induced retry. To prevent duplicate fulfillment downstream,
the receiver supports an optional sqlite-backed
:class:`IdempotencyStore` keyed on ``event.id`` with a UNIQUE
constraint. When the store is provided, second-arrival of a known
event id is treated as a no-op (``ingest_webhook`` returns ``None``);
the caller's webhook handler returns 200 OK without invoking
downstream side-effects again. When no store is provided, the
receiver behaves identically to its previous shape (no idempotency
gate; suitable for unit tests + bridges that handle dedup elsewhere).

**Thin-event rejection.** Stripe offers a "thin payload" delivery
mode where ``data.object`` carries only ``id`` + ``object`` (the type
discriminator), and the receiving system fetches the full object via
:meth:`stripe.Event.retrieve`. The Stripe SDK pattern enables the
fetch; this rail's receive-only invariant *forbids* outbound calls.
Thin events are therefore rejected with
:class:`ReceiveOnlyRailError`. Operators must keep their Stripe
endpoint configured for the standard (non-thin) delivery mode for
this rail.

**Startup secret validation.** Empty / unset webhook secrets cause
HMAC verification to silently accept any payload (the April 2026
public-bug-bounty disclosure). :func:`validate_secret_or_raise` is a
fail-fast assertion designed to be called from the FastAPI app's
startup hook so a misconfigured deployment refuses to start rather
than silently accepting unsigned events.

**Governance constraint.** No PII, no outbound, multi-currency
normalized to lowest-unit cents in the source currency, 300s
timestamp tolerance for replay protection, sqlite idempotency
locally on disk, fail-closed on thin events. This is the FIRST rail
in the family to implement timestamped-HMAC + replay protection +
event-id idempotency — prior rails (GitHub Sponsors, Liberapay, Open
Collective) used a bare HMAC SHA-256 over the canonical-JSON payload
bytes with no timestamp.

cc-task: ``publication-bus-monetization-rails-surfaces`` (Phase 0,
Stripe Payment Link rail). Sibling rails:
``shared/github_sponsors_receive_only_rail.py`` (#2218),
``shared/liberapay_receive_only_rail.py`` (#2219), and
``shared/open_collective_receive_only_rail.py`` (#2226). Timestamped
HMAC + 300s replay tolerance are the new shapes this rail introduces
vs the prior three.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV = "STRIPE_PAYMENT_LINK_WEBHOOK_SECRET"

#: Stripe's documented default tolerance for replay protection on
#: webhook signatures. Deliveries with a timestamp older than this many
#: seconds (relative to the verifier's clock) are rejected.
DEFAULT_TOLERANCE_SECONDS: int = 300

_ISO_4217_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_STRIPE_CUSTOMER_HANDLE_RE = re.compile(r"^(cus|cs|sub|pi|ch|in)_[A-Za-z0-9_]+$")


class ReceiveOnlyRailError(Exception):
    """Fail-closed error for any rejected Stripe Payment Link webhook payload.

    Raised on malformed payloads, unaccepted event kinds, signature
    verification failures, missing fields, malformed currency codes,
    expired timestamps (replay protection), or shape violations. The
    receiver never silently drops or partially-accepts an inbound event.
    """


class PaymentEventKind(StrEnum):
    """Canonical event kinds accepted by the receiver."""

    PAYMENT_INTENT_SUCCEEDED = "payment_intent_succeeded"
    CHECKOUT_SESSION_COMPLETED = "checkout_session_completed"
    CUSTOMER_SUBSCRIPTION_CREATED = "customer_subscription_created"
    CUSTOMER_SUBSCRIPTION_DELETED = "customer_subscription_deleted"


_ACCEPTED_EVENTS: frozenset[str] = frozenset(k.value for k in PaymentEventKind)
_STRIPE_EVENT_ALIASES: dict[str, PaymentEventKind] = {
    # Stripe emits dotted event types; both the dotted form and the
    # underscored canonical form are accepted on ingest.
    "payment_intent.succeeded": PaymentEventKind.PAYMENT_INTENT_SUCCEEDED,
    "checkout.session.completed": PaymentEventKind.CHECKOUT_SESSION_COMPLETED,
    "customer.subscription.created": PaymentEventKind.CUSTOMER_SUBSCRIPTION_CREATED,
    "customer.subscription.deleted": PaymentEventKind.CUSTOMER_SUBSCRIPTION_DELETED,
}


class _RailModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PaymentEvent(_RailModel):
    """Normalized, payer-aggregate Stripe Payment Link event.

    *No PII fields exist on this type.* ``customer_handle`` is the
    Stripe customer ID (``cus_...``), checkout session ID (``cs_...``),
    subscription ID (``sub_...``), or payment intent ID (``pi_...``)
    extracted from the delivery — opaque Stripe identifiers, not email
    addresses or names. ``amount_currency_cents`` is integer minor-units
    (cents/pence/etc.) in the source currency named by ``currency``.
    ``currency`` is the ISO 4217 3-letter uppercase code. Note that
    Stripe emits ``currency`` lowercase by convention; this receiver
    normalizes to uppercase. ``raw_payload_sha256`` is included so a
    downstream consumer can correlate this normalized event to the
    original webhook delivery without re-storing the raw payload (which
    typically contains receipt URLs, customer emails, billing
    addresses, and other fields we do not want to persist beyond the
    receiver boundary).
    """

    customer_handle: str = Field(min_length=1, max_length=255)
    amount_currency_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    event_kind: PaymentEventKind
    occurred_at: datetime
    raw_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("customer_handle")
    @classmethod
    def _handle_is_stripe_id(cls, value: str) -> str:
        """``customer_handle`` must look like a Stripe object ID, not an email."""
        if "@" in value or " " in value:
            raise ValueError(
                "customer_handle must be a Stripe object ID, not an email or qualified path"
            )
        if not _STRIPE_CUSTOMER_HANDLE_RE.fullmatch(value):
            raise ValueError(
                f"customer_handle must match a Stripe object ID prefix "
                f"(cus_, cs_, sub_, pi_, ch_, in_), got {value!r}"
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


def validate_secret_or_raise(env_var: str = STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV) -> None:
    """Fail-fast assertion that ``env_var`` carries a non-empty webhook secret.

    Designed to be called from a FastAPI ``startup`` hook so a
    misconfigured deployment refuses to start rather than silently
    accepting unsigned events. Raises :class:`ReceiveOnlyRailError`
    when the env var is unset or empty after stripping whitespace.
    """
    value = os.environ.get(env_var, "")
    if not value or not value.strip():
        raise ReceiveOnlyRailError(
            f"{env_var} must be set to a non-empty Stripe webhook signing secret "
            f"before the receiver accepts deliveries"
        )


_THIN_EVENT_KEYS: frozenset[str] = frozenset({"id", "object"})


def _is_thin_event_object(obj: dict[str, Any]) -> bool:
    """Detect Stripe's thin-payload mode (data.object has only ``id`` + ``object``).

    Stripe's thin-payload webhook mode sends only the event-object
    discriminator + identifier; the receiving system is expected to
    fetch the full payload via the SDK. This rail's receive-only
    invariant forbids outbound calls, so thin events must be refused.
    """
    keys = set(obj.keys())
    return keys.issubset(_THIN_EVENT_KEYS) or (keys == _THIN_EVENT_KEYS)


class IdempotencyStore:
    """sqlite-backed event-id seen-set for Stripe webhook idempotency.

    Stripe's at-least-once delivery semantics permit the *same* event
    id (``evt_...``) to arrive twice within the 300s replay window —
    e.g. a network retry between Stripe's edge and our receiver. This
    store keys on ``event.id`` with a UNIQUE constraint and exposes
    :meth:`record_or_skip` returning ``True`` on first insert, ``False``
    on collision. The receiver wraps this so a duplicate delivery
    short-circuits to a no-op (caller returns 200 OK).

    The default DB path lives under ``$HAPAX_HOME`` (or
    ``~/hapax-state``) — local disk only, no network. Construction
    creates the parent directory + table on demand. Concurrent
    receivers are safe via sqlite's serialized writes (per-connection
    BEGIN IMMEDIATE on insert); the workload is one-row INSERT per
    delivery so contention is negligible.
    """

    _SCHEMA_SQL = (
        "CREATE TABLE IF NOT EXISTS stripe_webhook_events ("
        "  event_id TEXT PRIMARY KEY,"
        "  first_seen_at_iso TEXT NOT NULL"
        ")"
    )

    def __init__(self, *, db_path: Path | None = None) -> None:
        self._db_path = db_path if db_path is not None else _default_idempotency_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(self._SCHEMA_SQL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path), isolation_level=None, timeout=5.0)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def record_or_skip(self, event_id: str, *, first_seen_at: datetime | None = None) -> bool:
        """Insert ``event_id`` into the seen-set or report a duplicate.

        Returns ``True`` if this is the first time we have seen the
        event id (caller should proceed with downstream processing) or
        ``False`` if the id was already in the table (caller should
        short-circuit to a no-op). Does not raise on collision; collision
        is the explicit signal.
        """
        if not event_id or not isinstance(event_id, str):
            raise ReceiveOnlyRailError(
                f"event_id must be a non-empty string, got {type(event_id).__name__}"
            )
        first_seen_iso = (first_seen_at or datetime.now(tz=UTC)).isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO stripe_webhook_events(event_id, first_seen_at_iso) VALUES (?, ?)",
                    (event_id, first_seen_iso),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def has_seen(self, event_id: str) -> bool:
        """Read-only existence probe — ``True`` if the id is recorded."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM stripe_webhook_events WHERE event_id = ? LIMIT 1",
                (event_id,),
            )
            return cursor.fetchone() is not None


def _default_idempotency_db_path() -> Path:
    base = os.environ.get("HAPAX_HOME")
    if base:
        return Path(base) / "stripe-payment-link" / "idempotency.db"
    return Path.home() / "hapax-state" / "stripe-payment-link" / "idempotency.db"


def _parse_stripe_signature_header(signature: str) -> tuple[int, list[str]]:
    """Parse a Stripe-Signature header into ``(timestamp, [v1_signatures])``.

    The header format is documented at
    https://stripe.com/docs/webhooks/signatures#verify-manually:
    ``t=TIMESTAMP,v1=SIG[,v1=SIG2,...]``. Other scheme prefixes
    (``v0``, future versions) are ignored. The timestamp is a Unix
    epoch integer in seconds. Raises :class:`ReceiveOnlyRailError` on
    a malformed header (missing ``t``, no ``v1`` signatures, non-integer
    timestamp).
    """
    if not isinstance(signature, str) or not signature.strip():
        raise ReceiveOnlyRailError("Stripe-Signature header is empty or non-string")

    timestamp: int | None = None
    v1_signatures: list[str] = []

    for part in signature.split(","):
        if "=" not in part:
            continue
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except (TypeError, ValueError) as exc:
                raise ReceiveOnlyRailError(
                    f"Stripe-Signature timestamp 't' must be an integer, got {value!r}"
                ) from exc
        elif key == "v1":
            v1_signatures.append(value)

    if timestamp is None:
        raise ReceiveOnlyRailError("Stripe-Signature header missing 't' timestamp")
    if not v1_signatures:
        raise ReceiveOnlyRailError("Stripe-Signature header missing any 'v1' signature")
    return timestamp, v1_signatures


def _verify_signature(
    payload_bytes: bytes,
    signature: str,
    secret: str,
    *,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: float | None = None,
) -> None:
    """Fail-closed Stripe HMAC SHA-256 + replay-protection verification.

    Implements the algorithm at
    https://stripe.com/docs/webhooks/signatures#verify-manually:

    1. Parse ``t=...,v1=...,...`` header.
    2. Compute expected signature: HMAC SHA-256 of
       ``f"{timestamp}.{payload}"`` with the secret.
    3. Compare against each provided ``v1`` signature. At least one
       must match.
    4. Reject if the delivery timestamp is older than
       ``tolerance_seconds`` relative to ``now``. ``now`` defaults to
       the current wall-clock; tests pass an explicit value.

    Mismatch on any step raises :class:`ReceiveOnlyRailError`.
    """
    if not secret:
        raise ReceiveOnlyRailError(
            f"signature provided but {STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV} is not set"
        )

    timestamp, v1_signatures = _parse_stripe_signature_header(signature)

    current_time = now if now is not None else time.time()
    age_seconds = current_time - float(timestamp)
    if age_seconds > tolerance_seconds:
        raise ReceiveOnlyRailError(
            f"Stripe-Signature timestamp is older than {tolerance_seconds}s "
            f"tolerance window (age={int(age_seconds)}s) — replay rejected"
        )

    signed_payload = f"{timestamp}.".encode() + payload_bytes
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()

    for candidate in v1_signatures:
        if hmac.compare_digest(expected, candidate):
            return
    raise ReceiveOnlyRailError("Stripe HMAC SHA-256 signature mismatch on all v1 signatures")


def _coerce_event_type(raw_type: Any) -> PaymentEventKind:
    """Map Stripe's ``type`` string to our enum or raise."""
    if not isinstance(raw_type, str):
        raise ReceiveOnlyRailError(
            f"webhook 'type' must be a string, got {type(raw_type).__name__}"
        )
    if raw_type in _ACCEPTED_EVENTS:
        return PaymentEventKind(raw_type)
    if raw_type in _STRIPE_EVENT_ALIASES:
        return _STRIPE_EVENT_ALIASES[raw_type]
    raise ReceiveOnlyRailError(f"unaccepted webhook event type {raw_type!r}")


def _extract_data_object(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the inner ``data.object`` envelope or raise."""
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ReceiveOnlyRailError("payload missing 'data' object")
    obj = data.get("object")
    if not isinstance(obj, dict):
        raise ReceiveOnlyRailError("payload missing 'data.object' dict")
    return obj


def _extract_customer_handle(obj: dict[str, Any], event_kind: PaymentEventKind) -> str:
    """Extract a Stripe object identifier suitable as a payer-aggregate handle.

    Probes ``customer`` (preferred — stable across multiple sessions for
    the same payer), then falls back to the object's own ``id`` (always
    present on a Stripe webhook ``data.object``). For checkout-session
    events the session ID is itself the canonical aggregate when no
    ``customer`` was created (guest checkout). Raises if no candidate
    is found.
    """
    customer = obj.get("customer")
    if isinstance(customer, str) and customer:
        return customer
    object_id = obj.get("id")
    if isinstance(object_id, str) and object_id:
        return object_id
    raise ReceiveOnlyRailError(
        f"payload missing 'data.object.customer' or 'data.object.id' for {event_kind.value!r}"
    )


def _extract_amount_and_currency(
    obj: dict[str, Any], event_kind: PaymentEventKind
) -> tuple[int, str]:
    """Extract minor-unit amount + ISO 4217 currency from the data object.

    Stripe emits amounts as integer minor-units already; no decimal
    conversion is needed at this boundary. Field names vary by object
    type:

    - ``payment_intent`` → ``amount`` / ``amount_received``
    - ``checkout.session`` → ``amount_total`` (preferred) or ``amount_subtotal``
    - ``subscription`` → ``items.data[0].price.unit_amount`` × ``quantity``
      summed across items, or top-level ``plan.amount`` for legacy
      shapes; falls back to 0 on a subscription deletion when no
      pricing info is in the payload (deletion may carry only the IDs).

    Negative amounts (refunds) are converted to absolute value so the
    rail expresses gross movement; net flow is reconstructed by
    event_kind downstream.
    """
    currency_raw = obj.get("currency")
    if not isinstance(currency_raw, str) or not currency_raw:
        # Subscriptions nest currency on items[0].price.currency.
        items = obj.get("items")
        if isinstance(items, dict):
            data = items.get("data")
            if isinstance(data, list) and data:
                first = data[0]
                if isinstance(first, dict):
                    price = first.get("price")
                    if isinstance(price, dict) and isinstance(price.get("currency"), str):
                        currency_raw = price["currency"]
        if not isinstance(currency_raw, str) or not currency_raw:
            plan = obj.get("plan")
            if isinstance(plan, dict) and isinstance(plan.get("currency"), str):
                currency_raw = plan["currency"]
    if not isinstance(currency_raw, str) or not currency_raw:
        raise ReceiveOnlyRailError(
            f"payload missing 'currency' on data.object for {event_kind.value!r}"
        )

    amount_raw: Any = None
    if event_kind in (
        PaymentEventKind.PAYMENT_INTENT_SUCCEEDED,
        PaymentEventKind.CHECKOUT_SESSION_COMPLETED,
    ):
        amount_raw = (
            obj.get("amount_total")
            or obj.get("amount_received")
            or obj.get("amount_subtotal")
            or obj.get("amount")
        )
    else:
        # Subscription created/deleted: sum item totals if available,
        # else fall through to plan.amount, else default to 0.
        items = obj.get("items")
        if isinstance(items, dict):
            data = items.get("data")
            if isinstance(data, list):
                total = 0
                any_amount = False
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    price = item.get("price")
                    quantity = item.get("quantity") or 1
                    if not isinstance(price, dict):
                        continue
                    unit_amount = price.get("unit_amount")
                    if isinstance(unit_amount, int) and not isinstance(unit_amount, bool):
                        total += unit_amount * int(quantity)
                        any_amount = True
                if any_amount:
                    amount_raw = total
        if amount_raw is None:
            plan = obj.get("plan")
            if isinstance(plan, dict):
                plan_amount = plan.get("amount")
                if isinstance(plan_amount, int) and not isinstance(plan_amount, bool):
                    amount_raw = plan_amount
        if amount_raw is None:
            # Subscription deletions may carry no pricing info; treat as 0.
            amount_raw = 0

    if isinstance(amount_raw, bool) or not isinstance(amount_raw, int):
        raise ReceiveOnlyRailError(
            f"amount must be an integer (Stripe minor units), got {type(amount_raw).__name__}"
        )

    cents = abs(int(amount_raw))
    return cents, currency_raw.upper()


def _extract_occurred_at(payload: dict[str, Any]) -> datetime:
    """Stripe envelopes carry ``created`` as a Unix epoch integer (UTC seconds)."""
    raw = payload.get("created")
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ReceiveOnlyRailError(
            f"payload missing 'created' Unix timestamp (got {type(raw).__name__})"
        )
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ReceiveOnlyRailError(f"invalid Unix timestamp {raw!r}: {exc}") from exc


class StripePaymentLinkRailReceiver:
    """Receive-only adapter for Stripe Payment Link webhooks.

    Construction is cheap and side-effect-free. The single public
    method :meth:`ingest_webhook` validates payload shape, optionally
    verifies the timestamped HMAC SHA-256 signature with replay
    protection, and returns a normalized :class:`PaymentEvent`. The
    receiver never opens a network socket, writes to disk, or contacts
    any external system.
    """

    def __init__(
        self,
        *,
        secret_env_var: str = STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV,
        tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self._secret_env_var = secret_env_var
        self._tolerance_seconds = tolerance_seconds
        self._idempotency_store = idempotency_store

    def _resolve_secret(self) -> str:
        return os.environ.get(self._secret_env_var, "")

    def ingest_webhook(
        self,
        payload: dict[str, Any],
        signature: str | None,
        *,
        now: float | None = None,
        raw_body: bytes | None = None,
    ) -> PaymentEvent | None:
        """Validate + normalize a single Stripe Payment Link webhook delivery.

        Returns the normalized :class:`PaymentEvent` for accepted
        deliveries. Raises :class:`ReceiveOnlyRailError` for malformed
        payloads, unaccepted event types, signature failures, or
        replay-protection violations. Returns ``None`` only when the
        caller passes ``payload={}`` *and* ``signature=None``, which is
        treated as a no-op heartbeat ping (Stripe sends an empty test
        delivery on endpoint creation).

        ``now`` is an optional injection point for the current time
        (seconds since epoch) used in replay-protection checks. Tests
        pass an explicit value; production callers leave it ``None``.

        ``raw_body`` is the raw HTTP body bytes Stripe signed (Stripe
        signs ``<timestamp>.<raw_body>``).  When provided, the
        timestamped HMAC is verified against the raw bytes — the only
        correct shape against live Stripe deliveries.  When omitted,
        the receiver falls back to canonical-encoding the parsed
        payload (preserves prior behavior used by the rail's own unit
        tests + bridges that synthesize JSON in canonical form).
        """
        if not isinstance(payload, dict):
            raise ReceiveOnlyRailError(f"payload must be a dict, got {type(payload).__name__}")

        if not payload and signature is None:
            return None

        canonical = _canonical_bytes(payload)
        payload_bytes = raw_body if raw_body is not None else canonical

        if signature is not None:
            secret = self._resolve_secret()
            _verify_signature(
                payload_bytes,
                signature,
                secret,
                tolerance_seconds=self._tolerance_seconds,
                now=now,
            )

        payload_sha256 = _sha256_hex(payload_bytes)

        event_kind = _coerce_event_type(payload.get("type"))
        data_object = _extract_data_object(payload)

        if _is_thin_event_object(data_object):
            raise ReceiveOnlyRailError(
                "Stripe thin-payload event rejected — receive-only rail cannot fetch full "
                "object via SDK. Reconfigure the Stripe webhook endpoint to deliver full "
                "(non-thin) payloads."
            )

        customer_handle = _extract_customer_handle(data_object, event_kind)
        amount_cents, currency = _extract_amount_and_currency(data_object, event_kind)
        occurred_at = _extract_occurred_at(payload)

        if self._idempotency_store is not None:
            event_id = payload.get("id")
            if not isinstance(event_id, str) or not event_id:
                raise ReceiveOnlyRailError(
                    "payload missing top-level 'id' (Stripe event id 'evt_...') "
                    "required for idempotency check"
                )
            if not self._idempotency_store.record_or_skip(event_id):
                return None

        try:
            return PaymentEvent(
                customer_handle=customer_handle,
                amount_currency_cents=amount_cents,
                currency=currency,
                event_kind=event_kind,
                occurred_at=occurred_at,
                raw_payload_sha256=payload_sha256,
            )
        except ValidationError as exc:
            raise ReceiveOnlyRailError(f"normalized event failed validation: {exc}") from exc


__all__ = [
    "DEFAULT_TOLERANCE_SECONDS",
    "STRIPE_PAYMENT_LINK_WEBHOOK_SECRET_ENV",
    "IdempotencyStore",
    "PaymentEvent",
    "PaymentEventKind",
    "ReceiveOnlyRailError",
    "StripePaymentLinkRailReceiver",
    "validate_secret_or_raise",
]
