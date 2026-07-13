"""logos/api/routes/payment_rails.py — FastAPI receiver for monetization rails.

Per cc-task ``github-sponsors-end-to-end-wiring``. First wired
monetization rail in the publication-bus family. Validates the
receive-only architecture pattern for the other 9 rails to copy.

Design:

- One route per rail (currently just ``/api/payment-rails/github-sponsors``).
- Captures the *raw* request body bytes (mandatory for HMAC
  verification — re-encoding the parsed payload would not reproduce
  the byte sequence the platform signed).
- Reads the canonical signature header for the rail (GitHub Sponsors
  uses ``X-Hub-Signature-256``; sibling rails will declare their own
  headers).
- Calls the rail's :class:`...RailReceiver.ingest_webhook()` to
  validate the payload + verify the signature + return a normalized
  event record.
- Dispatches the normalized event through the rail's V5 publisher
  (see :class:`agents.publication_bus.github_sponsors_publisher.GitHubSponsorsPublisher`).
- Returns 200 on success, 400 on receive-only-rail validation failure,
  500 on transient publisher error.

Receive-only invariants (carried through from the rail receivers):

- No outbound calls; the route is pure receive-only.
- No PII persisted beyond the aggregate manifest the publisher writes.
- Refusal-annex auto-link fires inside the publisher on cancellation;
  the route does not need to know about that path.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from agents.publication_bus.buy_me_a_coffee_publisher import (
    BuyMeACoffeePublisher,
)
from agents.publication_bus.github_sponsors_publisher import (
    GitHubSponsorsPublisher,
)
from agents.publication_bus.ko_fi_publisher import KoFiPublisher
from agents.publication_bus.liberapay_publisher import LiberapayPublisher
from agents.publication_bus.mercury_publisher import MercuryPublisher
from agents.publication_bus.modern_treasury_publisher import (
    ModernTreasuryPublisher,
)
from agents.publication_bus.open_collective_publisher import (
    OpenCollectivePublisher,
)
from agents.publication_bus.patreon_publisher import PatreonPublisher
from agents.publication_bus.stripe_payment_link_publisher import (
    StripePaymentLinkPublisher,
)
from agents.publication_bus.treasury_prime_publisher import (
    TreasuryPrimePublisher,
)
from logos.api.routes._payment_rails_helpers import (
    dispatch_publish_result,
    parse_webhook_request_body,
    render_null_event_response,
    require_ingress_resource_receipt,
    wrap_rail_error_to_400,
)
from shared._rail_idempotency import (
    get_idempotency_store as _get_idempotency_store,
)
from shared.buy_me_a_coffee_receive_only_rail import (
    BuyMeACoffeeRailReceiver,
)
from shared.buy_me_a_coffee_receive_only_rail import (
    ReceiveOnlyRailError as BuyMeACoffeeReceiveOnlyRailError,
)
from shared.durable_jsonl_sink import DurableJsonlSink
from shared.github_sponsors_receive_only_rail import (
    GitHubSponsorsRailReceiver,
)
from shared.github_sponsors_receive_only_rail import (
    ReceiveOnlyRailError as GitHubSponsorsReceiveOnlyRailError,
)
from shared.ko_fi_receive_only_rail import (
    KoFiRailReceiver,
)
from shared.ko_fi_receive_only_rail import (
    ReceiveOnlyRailError as KoFiReceiveOnlyRailError,
)
from shared.liberapay_receive_only_rail import (
    LiberapayRailReceiver,
)
from shared.liberapay_receive_only_rail import (
    ReceiveOnlyRailError as LiberapayReceiveOnlyRailError,
)
from shared.mercury_receive_only_rail import (
    MercuryRailReceiver,
)
from shared.mercury_receive_only_rail import (
    ReceiveOnlyRailError as MercuryReceiveOnlyRailError,
)
from shared.modern_treasury_receive_only_rail import (
    ModernTreasuryRailReceiver,
)
from shared.modern_treasury_receive_only_rail import (
    ReceiveOnlyRailError as ModernTreasuryReceiveOnlyRailError,
)
from shared.open_collective_receive_only_rail import (
    OpenCollectiveRailReceiver,
)
from shared.open_collective_receive_only_rail import (
    ReceiveOnlyRailError as OpenCollectiveReceiveOnlyRailError,
)
from shared.patreon_receive_only_rail import (
    PatreonRailReceiver,
)
from shared.patreon_receive_only_rail import (
    ReceiveOnlyRailError as PatreonReceiveOnlyRailError,
)
from shared.stripe_payment_link_receive_only_rail import (
    ReceiveOnlyRailError as StripePaymentLinkReceiveOnlyRailError,
)
from shared.stripe_payment_link_receive_only_rail import (
    StripePaymentLinkRailReceiver,
)
from shared.treasury_prime_receive_only_rail import (
    ReceiveOnlyRailError as TreasuryPrimeReceiveOnlyRailError,
)
from shared.treasury_prime_receive_only_rail import (
    TreasuryPrimeRailReceiver,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payment-rails", tags=["payment-rails"])
stripe_webhook_router = APIRouter(prefix="/api", tags=["payment-rails"])


# Per-rail webhook delivery-id headers + bridge-fallback chains.
# Idempotency stores themselves are managed by the shared registry in
# `shared._rail_idempotency.get_idempotency_store(rail_subdir)` — see
# the receive_*_webhook handlers below.
def _payment_event_payload(event: Any) -> dict[str, Any]:
    if hasattr(event, "model_dump_json"):
        return json.loads(event.model_dump_json())
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    return json.loads(event.json())


def _persist_payment_event_durable(event: Any, log_label: str) -> None:
    """Write normalized PaymentEvent metadata to the durable Stage-0 sink.

    Must fail-closed and propagate errors to FastAPI/client rather than
    silently dropping to volatile-only persistence.
    """
    sink = DurableJsonlSink()
    payload = _payment_event_payload(event)

    ts = event.occurred_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    timestamp_str = ts.isoformat().replace("+00:00", "Z")

    ref = f"receipt://payment/{log_label}/{event.raw_payload_sha256}/{event.event_kind.value}"

    # Idempotent on the deterministic source_receipt_ref: a provider retry or a
    # redelivery that mints a fresh delivery id for the same payload with an
    # identical stable identity reuses the single committed row instead of
    # appending a second Stage-0 row. This bounds only the Stage-0 write; it is
    # not a claim about end-to-end publication, downstream projection, or
    # process-death safety.
    sink.append_once(
        stream_id="payment-event",
        data_class="financial_receipt",
        source_receipt_ref=ref,
        payload=payload,
        timestamp=timestamp_str,
    )


GITHUB_SPONSORS_DELIVERY_ID_HEADER: str = "X-GitHub-Delivery"
"""GitHub webhook per-delivery identifier header (UUID per delivery)."""

OPEN_COLLECTIVE_DELIVERY_ID_HEADER: str = "X-Open-Collective-Activity-Id"
"""Open Collective per-delivery activity identifier header."""

_LIBERAPAY_DELIVERY_ID_HEADERS: tuple[str, ...] = (
    "X-Liberapay-Delivery-Id",
    "X-Cloudmailin-Message-Id",
    "Message-Id",
)


def _resolve_liberapay_delivery_id(headers) -> str | None:
    """Walk the bridge-header fallback chain for a per-delivery identifier.

    Returns the first non-empty value found across the documented
    bridge contracts (cloudmailin, mailgun, n8n, generic SMTP). Returns
    ``None`` if no bridge header is present — the route returns 400
    so the bridge layer fails-loud.
    """
    for header_name in _LIBERAPAY_DELIVERY_ID_HEADERS:
        value = headers.get(header_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _payload_event_hint(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "webhook_delivery"


class _ReceiptFirstIdempotencyStore:
    """Record private receipt evidence before idempotency mutates seen-state."""

    def __init__(
        self,
        store: Any,
        *,
        rail: str,
        route_path: str,
        raw_payload_sha256: str | None,
        event_kind: str,
    ) -> None:
        self._store = store
        self._rail = rail
        self._route_path = route_path
        self._raw_payload_sha256 = raw_payload_sha256
        self._event_kind = event_kind
        self.resource_receipt_ref: str | None = None
        # The exact seen-key this request newly recorded (None if this request
        # saw a duplicate or never reached record_or_skip). Captured here so the
        # shared finalize helper never re-derives ten rail-specific keys.
        self._recorded_event_id: str | None = None

    def record_or_skip(self, event_id: str, *, first_seen_at: Any = None) -> bool:
        self.resource_receipt_ref = require_ingress_resource_receipt(
            rail=self._rail,
            route_path=self._route_path,
            external_id=event_id,
            event_kind=self._event_kind,
            raw_payload_sha256=self._raw_payload_sha256,
            downstream_action="rail_idempotency.record_or_skip",
        )
        recorded = self._store.record_or_skip(event_id, first_seen_at=first_seen_at)
        if recorded:
            self._recorded_event_id = event_id
        return recorded

    def has_seen(self, event_id: str) -> bool:
        return self._store.has_seen(event_id)

    def reopen_after_retryable_failure(self) -> None:
        """Roll back the seen-key this request recorded so a provider retry
        re-enters instead of short-circuiting as a duplicate.

        One-shot and idempotent: it clears at most the id this request newly
        recorded, and only once. This prevents nested cleanup and ABA deletion
        of a key a concurrent retry may have re-inserted. A no-op when this
        request recorded nothing (duplicate/None) or was already reopened.
        """
        event_id = self._recorded_event_id
        if event_id is None:
            return
        self._recorded_event_id = None
        self._store.remove(event_id)


def _receipt_first_idempotency_store(
    request: Request,
    *,
    rail: str,
    store: Any,
    raw_body: bytes,
    event_kind: str,
) -> _ReceiptFirstIdempotencyStore:
    raw_payload_sha256 = hashlib.sha256(raw_body).hexdigest() if raw_body else None
    return _ReceiptFirstIdempotencyStore(
        store,
        rail=rail,
        route_path=request.url.path,
        raw_payload_sha256=raw_payload_sha256,
        event_kind=event_kind,
    )


def _finalize_payment_event(
    event: Any,
    *,
    log_label: str,
    idempotency_store: _ReceiptFirstIdempotencyStore,
    publisher: Any,
    extra_received_fields: dict[str, Any] | None = None,
) -> JSONResponse:
    """Durably persist Stage-0, publish, and render the rail's HTTP response.

    Rolls back the seen-key this request recorded on exactly three retryable
    surfaces so a provider retry re-enters instead of returning a false-negative
    duplicate: a durable-persist exception, a publisher exception, or a
    ``PublisherResult.error`` transport failure. It never reopens after a
    successful or refused publish (both terminal), nor after a post-success
    rendering failure — reopening a terminally handled publisher outcome would
    let it be re-published. Publisher success/refusal is a reported publisher
    outcome, not financial settlement.
    Combined with the idempotent Stage-0 append, a reopened retry reuses the
    single committed Stage-0 row for the same deterministic ref and identical
    stable semantics, so this tested caught-failure retry path does not append
    a second row. This is NOT an outbox or exactly-once publication guarantee:
    process death, an ambiguous or non-idempotent publisher effect, and an
    in-flight concurrent duplicate that gets a 200 before this request's later
    rollback all remain open windows tracked as a governed reconciliation
    follow-up.
    """
    try:
        _persist_payment_event_durable(event, log_label=log_label)
    except Exception:
        idempotency_store.reopen_after_retryable_failure()
        raise
    try:
        publish_result = publisher.publish_event(event)
    except Exception:
        idempotency_store.reopen_after_retryable_failure()
        raise
    if publish_result.error:
        idempotency_store.reopen_after_retryable_failure()
    return dispatch_publish_result(
        publish_result,
        event,
        log_label=log_label,
        extra_received_fields=extra_received_fields,
        resource_receipt_ref=idempotency_store.resource_receipt_ref,
    )


# Stripe Payment Link migrated to the shared idempotency registry —
# its `IdempotencyStore` class now wraps `shared._rail_idempotency.IdempotencyStore`,
# so the route uses `_get_idempotency_store("stripe-payment-link")` like
# every other rail.


GITHUB_SPONSORS_SIGNATURE_HEADER: str = "X-Hub-Signature-256"
"""GitHub Sponsors webhook signature header. Documented at
https://docs.github.com/en/webhooks/webhook-events-and-payloads — the
``sha256=<hex>`` form is GitHub's canonical wire shape."""

LIBERAPAY_SIGNATURE_HEADER: str = "X-Liberapay-Signature"
"""Liberapay does not natively ship webhooks; this is the canonical
header bridges (cloudmailin / mailgun / n8n) set when forwarding
HMAC-signed deliveries to the rail. The bridge layer chooses; the
header name is stable across the rail's documented bridge contracts."""

OPEN_COLLECTIVE_SIGNATURE_HEADER: str = "X-Open-Collective-Signature"
"""Open Collective webhook signature header (per the rail's
documented contract). Bare hex digest; ``sha256=<hex>`` prefix also
accepted by the receiver."""

STRIPE_PAYMENT_LINK_SIGNATURE_HEADER: str = "Stripe-Signature"
"""Stripe canonical signature header — timestamped HMAC SHA-256 with
the documented ``t=<unix_ts>,v1=<hex_digest>`` format. The rail
parses this internally and verifies replay-tolerance separately."""

PATREON_SIGNATURE_HEADER: str = "X-Patreon-Signature"
"""Patreon webhook signature header — hex-encoded HMAC MD5 digest
(NOT SHA-256, per Patreon's documented wire format)."""

PATREON_EVENT_HEADER: str = "X-Patreon-Event"
"""Patreon event-kind header — separate from the signature header.
Carries the colon-delimited event name (e.g. ``members:create``,
``members:pledge:delete``)."""

BUY_ME_A_COFFEE_SIGNATURE_HEADER: str = "X-Signature-Sha256"
"""Buy Me a Coffee webhook signature header — hex-encoded HMAC SHA-256
digest of the raw body. Both bare hex digest and ``sha256=<hex>``
prefixed forms are accepted by the receiver."""

MERCURY_SIGNATURE_HEADER: str = "X-Mercury-Signature"
"""Mercury canonical webhook signature header — HMAC SHA-256 over
raw body."""

MERCURY_LEGACY_SIGNATURE_HEADER: str = "X-Hook-Signature"
"""Mercury legacy webhook signature header — some older Mercury
integrations may still emit this name; the route accepts either
header (canonical X-Mercury-Signature takes precedence)."""

MODERN_TREASURY_SIGNATURE_HEADER: str = "X-Signature"
"""Modern Treasury webhook signature header — HMAC SHA-256 over raw
body. Bare hex digest; ``sha256=<hex>`` prefix also accepted."""

TREASURY_PRIME_SIGNATURE_HEADER: str = "X-Signature"
"""Treasury Prime webhook signature header — HMAC SHA-256 over raw
body. Same name as Modern Treasury; the URL path
(/api/payment-rails/treasury-prime vs /api/payment-rails/modern-treasury)
disambiguates the two rails."""


@router.post("/github-sponsors")
async def receive_github_sponsors_webhook(request: Request) -> JSONResponse:
    """Receive a GitHub Sponsors webhook delivery and dispatch through V5 publisher.

    Workflow:
      1. Capture raw body bytes (mandatory for HMAC verification).
      2. Parse JSON envelope; reject malformed JSON with 400.
      3. Read ``X-Hub-Signature-256`` header (None if missing —
         ingest_webhook skips verification when None, but the rail
         is configured to fail closed if the env-var secret is set
         and the signature is missing).
      4. Call :meth:`GitHubSponsorsRailReceiver.ingest_webhook` to
         validate + normalize.
      5. On accepted event: dispatch through the V5 publisher.
      6. On heartbeat ping (empty payload + None signature):
         return 200 with ``{"status": "ping_ok"}``.

    Returns 200 with the publisher's outcome on success, 400 on
    validation/signature failure, 500 on transient transport error.
    """
    raw_body, payload = await parse_webhook_request_body(request, log_label="github_sponsors")

    if payload is None:
        # Empty-body GitHub heartbeat ping.
        return JSONResponse({"status": "ping_ok"})

    signature = request.headers.get(GITHUB_SPONSORS_SIGNATURE_HEADER)
    delivery_id = request.headers.get(GITHUB_SPONSORS_DELIVERY_ID_HEADER)

    idempotency_store = _receipt_first_idempotency_store(
        request,
        rail="github-sponsors",
        store=_get_idempotency_store("github-sponsors"),
        raw_body=raw_body,
        event_kind=_payload_event_hint(payload, "action"),
    )
    receiver = GitHubSponsorsRailReceiver(
        idempotency_store=idempotency_store,
    )
    with wrap_rail_error_to_400(GitHubSponsorsReceiveOnlyRailError, log_label="github_sponsors"):
        event = receiver.ingest_webhook(
            payload,
            signature,
            raw_body=raw_body,
            delivery_id=delivery_id,
        )

    if event is None:
        return render_null_event_response(
            payload,
            duplicate_id_key="delivery_id",
            duplicate_id_value=delivery_id,
            log_label="github_sponsors",
            resource_receipt_ref=idempotency_store.resource_receipt_ref,
        )

    return _finalize_payment_event(
        event,
        log_label="github_sponsors",
        idempotency_store=idempotency_store,
        publisher=GitHubSponsorsPublisher(),
    )


@router.post("/liberapay")
async def receive_liberapay_webhook(request: Request) -> JSONResponse:
    """Receive a Liberapay donation notification (via bridge) and dispatch.

    Liberapay does not natively ship webhooks (per
    https://github.com/liberapay/liberapay.com/issues/688). Bridges
    (cloudmailin / mailgun / n8n) parse Liberapay's outbound
    notification emails or per-account CSV exports and POST a
    structured JSON envelope to this endpoint. The bridge is
    responsible for authenticating its delivery upstream of the rail
    (IP allowlist set via LIBERAPAY_REQUIRE_IP_ALLOWLIST=1, or HMAC
    SHA-256 signing with LIBERAPAY_WEBHOOK_SECRET).

    Same workflow as the github-sponsors handler: capture raw body,
    parse, validate via :class:`LiberapayRailReceiver.ingest_webhook`,
    dispatch through :class:`LiberapayPublisher`. Returns 200 on
    success, 400 on validation failure, 500 on transient publisher
    error.
    """
    raw_body, payload = await parse_webhook_request_body(request, log_label="liberapay")

    if payload is None:
        return JSONResponse({"status": "ping_ok"})

    signature = request.headers.get(LIBERAPAY_SIGNATURE_HEADER)
    delivery_id = _resolve_liberapay_delivery_id(request.headers)

    idempotency_store = _receipt_first_idempotency_store(
        request,
        rail="liberapay",
        store=_get_idempotency_store("liberapay"),
        raw_body=raw_body,
        event_kind=_payload_event_hint(payload, "event"),
    )
    receiver = LiberapayRailReceiver(
        idempotency_store=idempotency_store,
    )
    with wrap_rail_error_to_400(LiberapayReceiveOnlyRailError, log_label="liberapay"):
        event = receiver.ingest_webhook(
            payload,
            signature,
            raw_body=raw_body,
            delivery_id=delivery_id,
        )

    if event is None:
        return render_null_event_response(
            payload,
            duplicate_id_key="delivery_id",
            duplicate_id_value=delivery_id,
            log_label="liberapay",
            resource_receipt_ref=idempotency_store.resource_receipt_ref,
        )

    return _finalize_payment_event(
        event,
        log_label="liberapay",
        idempotency_store=idempotency_store,
        publisher=LiberapayPublisher(),
    )


@router.post("/open-collective")
async def receive_open_collective_webhook(request: Request) -> JSONResponse:
    """Receive an Open Collective webhook delivery and dispatch.

    Open Collective signs deliveries with HMAC SHA-256 in the
    ``X-Open-Collective-Signature`` header. Multi-currency native;
    no cancellation event in the canonical 4 (so no auto-link path).
    """
    raw_body, payload = await parse_webhook_request_body(request, log_label="open_collective")

    if payload is None:
        return JSONResponse({"status": "ping_ok"})

    signature = request.headers.get(OPEN_COLLECTIVE_SIGNATURE_HEADER)
    delivery_id = request.headers.get(OPEN_COLLECTIVE_DELIVERY_ID_HEADER)

    idempotency_store = _receipt_first_idempotency_store(
        request,
        rail="open-collective",
        store=_get_idempotency_store("open-collective"),
        raw_body=raw_body,
        event_kind=_payload_event_hint(payload, "type"),
    )
    receiver = OpenCollectiveRailReceiver(
        idempotency_store=idempotency_store,
    )
    with wrap_rail_error_to_400(OpenCollectiveReceiveOnlyRailError, log_label="open_collective"):
        event = receiver.ingest_webhook(
            payload,
            signature,
            raw_body=raw_body,
            delivery_id=delivery_id,
        )

    if event is None:
        return render_null_event_response(
            payload,
            duplicate_id_key="delivery_id",
            duplicate_id_value=delivery_id,
            log_label="open_collective",
            resource_receipt_ref=idempotency_store.resource_receipt_ref,
        )

    return _finalize_payment_event(
        event,
        log_label="open_collective",
        idempotency_store=idempotency_store,
        publisher=OpenCollectivePublisher(),
    )


@router.post("/stripe-payment-link")
async def receive_stripe_payment_link_webhook(request: Request) -> JSONResponse:
    """Receive a Stripe Payment Link webhook delivery and dispatch.

    Stripe signs deliveries with a timestamped HMAC SHA-256 in the
    ``Stripe-Signature`` header (``t=<unix>,v1=<hex>`` format). The
    rail's ``ingest_webhook`` parses + verifies internally with
    replay-tolerance.
    """
    raw_body, payload = await parse_webhook_request_body(request, log_label="stripe_payment_link")

    if payload is None:
        return JSONResponse({"status": "ping_ok"})

    signature = request.headers.get(STRIPE_PAYMENT_LINK_SIGNATURE_HEADER)

    idempotency_store = _receipt_first_idempotency_store(
        request,
        rail="stripe-payment-link",
        store=_get_idempotency_store("stripe-payment-link"),
        raw_body=raw_body,
        event_kind=_payload_event_hint(payload, "type"),
    )
    receiver = StripePaymentLinkRailReceiver(
        idempotency_store=idempotency_store,
    )
    with wrap_rail_error_to_400(
        StripePaymentLinkReceiveOnlyRailError, log_label="stripe_payment_link"
    ):
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)

    if event is None:
        event_id = payload.get("id")
        return render_null_event_response(
            payload,
            duplicate_id_key="event_id",
            duplicate_id_value=event_id if isinstance(event_id, str) else None,
            log_label="stripe_payment_link",
            resource_receipt_ref=idempotency_store.resource_receipt_ref,
        )

    return _finalize_payment_event(
        event,
        log_label="stripe_payment_link",
        idempotency_store=idempotency_store,
        publisher=StripePaymentLinkPublisher(),
    )


@stripe_webhook_router.post("/stripe-webhook")
async def receive_stripe_webhook(request: Request) -> JSONResponse:
    """Compatibility endpoint for Stripe dashboard/webhook setup.

    The canonical implementation stays the receive-only Payment Link rail;
    this path exists because the bootstrap contract names
    ``/api/stripe-webhook`` as the operator-facing Stripe endpoint.
    """
    return await receive_stripe_payment_link_webhook(request)


@router.post("/ko-fi")
async def receive_ko_fi_webhook(request: Request) -> JSONResponse:
    """Receive a Ko-fi webhook delivery and dispatch.

    Ko-fi uses **token-in-payload verification** (not HMAC). The
    sender includes a ``verification_token`` field in the JSON body
    matching the per-page secret configured in the Ko-fi dashboard.
    The rail's ``ingest_webhook`` reads the token field inline and
    fails closed on mismatch.
    """
    raw_body, payload = await parse_webhook_request_body(request, log_label="ko_fi")

    if payload is None:
        return JSONResponse({"status": "ping_ok"})

    idempotency_store = _receipt_first_idempotency_store(
        request,
        rail="ko-fi",
        store=_get_idempotency_store("ko-fi"),
        raw_body=raw_body,
        event_kind=_payload_event_hint(payload, "type", "message_type"),
    )
    receiver = KoFiRailReceiver(idempotency_store=idempotency_store)
    with wrap_rail_error_to_400(KoFiReceiveOnlyRailError, log_label="ko_fi"):
        event = receiver.ingest_webhook(payload, verify_token=True)

    if event is None:
        transaction_id = payload.get("kofi_transaction_id")
        return render_null_event_response(
            payload,
            duplicate_id_key="kofi_transaction_id",
            duplicate_id_value=transaction_id if isinstance(transaction_id, str) else None,
            log_label="ko_fi",
            resource_receipt_ref=idempotency_store.resource_receipt_ref,
        )

    return _finalize_payment_event(
        event,
        log_label="ko_fi",
        idempotency_store=idempotency_store,
        publisher=KoFiPublisher(),
    )


@router.post("/patreon")
async def receive_patreon_webhook(request: Request) -> JSONResponse:
    """Receive a Patreon webhook delivery and dispatch.

    Patreon's signature shape is HMAC MD5 (not SHA-256, per their
    documented wire format) in the ``X-Patreon-Signature`` header.
    The event-kind ships separately in ``X-Patreon-Event`` (colon-
    delimited form like ``members:pledge:create``).
    """
    raw_body, payload = await parse_webhook_request_body(request, log_label="patreon")

    if payload is None:
        return JSONResponse({"status": "ping_ok"})

    signature = request.headers.get(PATREON_SIGNATURE_HEADER)
    event_header = request.headers.get(PATREON_EVENT_HEADER)
    webhook_id = request.headers.get("X-Patreon-Webhook-Id")

    idempotency_store = _receipt_first_idempotency_store(
        request,
        rail="patreon",
        store=_get_idempotency_store("patreon"),
        raw_body=raw_body,
        event_kind=event_header or _payload_event_hint(payload, "type"),
    )
    receiver = PatreonRailReceiver(idempotency_store=idempotency_store)
    with wrap_rail_error_to_400(PatreonReceiveOnlyRailError, log_label="patreon"):
        event = receiver.ingest_webhook(
            payload,
            signature,
            event_header,
            raw_body=raw_body,
            webhook_id=webhook_id,
        )

    if event is None:
        return render_null_event_response(
            payload,
            duplicate_id_key="webhook_id",
            duplicate_id_value=webhook_id,
            log_label="patreon",
            resource_receipt_ref=idempotency_store.resource_receipt_ref,
        )

    return _finalize_payment_event(
        event,
        log_label="patreon",
        idempotency_store=idempotency_store,
        publisher=PatreonPublisher(),
    )


@router.post("/buy-me-a-coffee")
async def receive_buy_me_a_coffee_webhook(request: Request) -> JSONResponse:
    """Receive a Buy Me a Coffee webhook delivery and dispatch.

    BMaC signs deliveries with HMAC SHA-256 over the raw body in the
    ``X-Signature-Sha256`` header. Both bare hex digest and
    ``sha256=<hex>`` prefixed forms are accepted.
    """
    raw_body, payload = await parse_webhook_request_body(request, log_label="buy_me_a_coffee")

    if payload is None:
        return JSONResponse({"status": "ping_ok"})

    signature = request.headers.get(BUY_ME_A_COFFEE_SIGNATURE_HEADER)

    idempotency_store = _receipt_first_idempotency_store(
        request,
        rail="buy-me-a-coffee",
        store=_get_idempotency_store("buy-me-a-coffee"),
        raw_body=raw_body,
        event_kind=_payload_event_hint(payload, "type", "event"),
    )
    receiver = BuyMeACoffeeRailReceiver(
        idempotency_store=idempotency_store,
    )
    with wrap_rail_error_to_400(BuyMeACoffeeReceiveOnlyRailError, log_label="buy_me_a_coffee"):
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)

    if event is None:
        event_id = payload.get("event_id")
        return render_null_event_response(
            payload,
            duplicate_id_key="event_id",
            duplicate_id_value=event_id if isinstance(event_id, str) else None,
            log_label="buy_me_a_coffee",
            resource_receipt_ref=idempotency_store.resource_receipt_ref,
        )

    return _finalize_payment_event(
        event,
        log_label="buy_me_a_coffee",
        idempotency_store=idempotency_store,
        publisher=BuyMeACoffeePublisher(),
    )


@router.post("/mercury")
async def receive_mercury_webhook(request: Request) -> JSONResponse:
    """Receive a Mercury webhook delivery and dispatch.

    Mercury signs deliveries with HMAC SHA-256 over raw body in the
    ``X-Mercury-Signature`` header. Some legacy integrations may
    still emit the older ``X-Hook-Signature`` header; the route
    accepts either (canonical takes precedence). The rail's
    direction filter rejects outgoing transaction kinds at the
    receiver boundary.
    """
    raw_body, payload = await parse_webhook_request_body(request, log_label="mercury")

    if payload is None:
        return JSONResponse({"status": "ping_ok"})

    # Canonical header takes precedence; fall back to legacy.
    signature = request.headers.get(MERCURY_SIGNATURE_HEADER) or request.headers.get(
        MERCURY_LEGACY_SIGNATURE_HEADER
    )

    idempotency_store = _receipt_first_idempotency_store(
        request,
        rail="mercury",
        store=_get_idempotency_store("mercury"),
        raw_body=raw_body,
        event_kind=_payload_event_hint(payload, "type", "event"),
    )
    receiver = MercuryRailReceiver(idempotency_store=idempotency_store)
    with wrap_rail_error_to_400(MercuryReceiveOnlyRailError, log_label="mercury"):
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)

    if event is None:
        txn_id = (payload.get("data") or {}).get("id")
        return render_null_event_response(
            payload,
            duplicate_id_key="transaction_id",
            duplicate_id_value=txn_id if isinstance(txn_id, str) else None,
            log_label="mercury",
            resource_receipt_ref=idempotency_store.resource_receipt_ref,
        )

    return _finalize_payment_event(
        event,
        log_label="mercury",
        idempotency_store=idempotency_store,
        publisher=MercuryPublisher(),
        extra_received_fields={"direction": event.direction.value},
    )


@router.post("/modern-treasury")
async def receive_modern_treasury_webhook(request: Request) -> JSONResponse:
    """Receive a Modern Treasury webhook delivery and dispatch.

    Modern Treasury signs deliveries with HMAC SHA-256 over raw body
    in ``X-Signature``. Direction is filtered at the event-name level
    (only ``incoming_payment_detail.*`` events accepted; outgoing
    ``payment_order.*`` rejected). Same X-Signature header name as
    Treasury Prime — disambiguated by URL path.
    """
    raw_body, payload = await parse_webhook_request_body(request, log_label="modern_treasury")

    if payload is None:
        return JSONResponse({"status": "ping_ok"})

    signature = request.headers.get(MODERN_TREASURY_SIGNATURE_HEADER)

    idempotency_store = _receipt_first_idempotency_store(
        request,
        rail="modern-treasury",
        store=_get_idempotency_store("modern-treasury"),
        raw_body=raw_body,
        event_kind=_payload_event_hint(payload, "event", "type"),
    )
    receiver = ModernTreasuryRailReceiver(
        idempotency_store=idempotency_store,
    )
    with wrap_rail_error_to_400(ModernTreasuryReceiveOnlyRailError, log_label="modern_treasury"):
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)

    if event is None:
        payment_id = (payload.get("data") or {}).get("id")
        return render_null_event_response(
            payload,
            duplicate_id_key="payment_id",
            duplicate_id_value=payment_id if isinstance(payment_id, str) else None,
            log_label="modern_treasury",
            resource_receipt_ref=idempotency_store.resource_receipt_ref,
        )

    return _finalize_payment_event(
        event,
        log_label="modern_treasury",
        idempotency_store=idempotency_store,
        publisher=ModernTreasuryPublisher(),
        extra_received_fields={"payment_method": event.payment_method.value},
    )


@router.post("/treasury-prime")
async def receive_treasury_prime_webhook(request: Request) -> JSONResponse:
    """Receive a Treasury Prime webhook delivery and dispatch.

    Treasury Prime signs deliveries with HMAC SHA-256 over raw body
    in ``X-Signature``. Phase 0 accepts only ``incoming_ach.create``
    (ledger-account events); Phase 1 will extend to ``transaction.create``
    (core direct accounts) with the data-level direction filter from
    Mercury.
    """
    raw_body, payload = await parse_webhook_request_body(request, log_label="treasury_prime")

    if payload is None:
        return JSONResponse({"status": "ping_ok"})

    signature = request.headers.get(TREASURY_PRIME_SIGNATURE_HEADER)

    idempotency_store = _receipt_first_idempotency_store(
        request,
        rail="treasury-prime",
        store=_get_idempotency_store("treasury-prime"),
        raw_body=raw_body,
        event_kind=_payload_event_hint(payload, "event", "type"),
    )
    receiver = TreasuryPrimeRailReceiver(
        idempotency_store=idempotency_store,
    )
    with wrap_rail_error_to_400(TreasuryPrimeReceiveOnlyRailError, log_label="treasury_prime"):
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)

    if event is None:
        ach_id = (payload.get("data") or {}).get("id")
        return render_null_event_response(
            payload,
            duplicate_id_key="ach_id",
            duplicate_id_value=ach_id if isinstance(ach_id, str) else None,
            log_label="treasury_prime",
            resource_receipt_ref=idempotency_store.resource_receipt_ref,
        )

    return _finalize_payment_event(
        event,
        log_label="treasury_prime",
        idempotency_store=idempotency_store,
        publisher=TreasuryPrimePublisher(),
    )


__all__ = [
    "BUY_ME_A_COFFEE_SIGNATURE_HEADER",
    "GITHUB_SPONSORS_SIGNATURE_HEADER",
    "LIBERAPAY_SIGNATURE_HEADER",
    "MERCURY_LEGACY_SIGNATURE_HEADER",
    "MERCURY_SIGNATURE_HEADER",
    "MODERN_TREASURY_SIGNATURE_HEADER",
    "OPEN_COLLECTIVE_SIGNATURE_HEADER",
    "PATREON_EVENT_HEADER",
    "PATREON_SIGNATURE_HEADER",
    "STRIPE_PAYMENT_LINK_SIGNATURE_HEADER",
    "TREASURY_PRIME_SIGNATURE_HEADER",
    "router",
]
