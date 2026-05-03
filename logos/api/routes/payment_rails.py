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

import json
import logging

from fastapi import APIRouter, HTTPException, Request
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
from shared._rail_idempotency import IdempotencyStore as _RailIdempotencyStore
from shared._rail_idempotency import default_idempotency_db_path
from shared.buy_me_a_coffee_receive_only_rail import (
    BuyMeACoffeeRailReceiver,
)
from shared.buy_me_a_coffee_receive_only_rail import (
    ReceiveOnlyRailError as BuyMeACoffeeReceiveOnlyRailError,
)
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
    IdempotencyStore as StripePaymentLinkIdempotencyStore,
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

_stripe_payment_link_idempotency_store: StripePaymentLinkIdempotencyStore | None = None
_patreon_idempotency_store: _RailIdempotencyStore | None = None
_ko_fi_idempotency_store: _RailIdempotencyStore | None = None
_buy_me_a_coffee_idempotency_store: _RailIdempotencyStore | None = None
_liberapay_idempotency_store: _RailIdempotencyStore | None = None


def _get_liberapay_idempotency_store() -> _RailIdempotencyStore:
    """Lazy singleton sqlite-backed idempotency store for Liberapay.

    Keyed on a bridge-supplied `delivery_id` (resolved from one of:
    ``X-Liberapay-Delivery-Id``, ``X-Cloudmailin-Message-Id``,
    ``X-Mailgun-Variables`` JSON's ``message-id``, ``Message-Id``).
    """
    global _liberapay_idempotency_store  # noqa: PLW0603 — module-level singleton
    if _liberapay_idempotency_store is None:
        _liberapay_idempotency_store = _RailIdempotencyStore(
            db_path=default_idempotency_db_path("liberapay"),
        )
    return _liberapay_idempotency_store


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


def _get_buy_me_a_coffee_idempotency_store() -> _RailIdempotencyStore:
    """Lazy singleton sqlite-backed idempotency store for Buy Me a Coffee.

    Keyed on top-level ``event_id`` (BMaC's per-delivery UUID).
    """
    global _buy_me_a_coffee_idempotency_store  # noqa: PLW0603 — module-level singleton
    if _buy_me_a_coffee_idempotency_store is None:
        _buy_me_a_coffee_idempotency_store = _RailIdempotencyStore(
            db_path=default_idempotency_db_path("buy-me-a-coffee"),
        )
    return _buy_me_a_coffee_idempotency_store


def _get_ko_fi_idempotency_store() -> _RailIdempotencyStore:
    """Lazy singleton sqlite-backed idempotency store for Ko-fi.

    Keyed on ``kofi_transaction_id`` (in-payload UUID per delivery).
    Tests can swap the singleton by assigning to
    ``_ko_fi_idempotency_store`` directly.
    """
    global _ko_fi_idempotency_store  # noqa: PLW0603 — module-level singleton
    if _ko_fi_idempotency_store is None:
        _ko_fi_idempotency_store = _RailIdempotencyStore(
            db_path=default_idempotency_db_path("ko-fi"),
        )
    return _ko_fi_idempotency_store


def _get_patreon_idempotency_store() -> _RailIdempotencyStore:
    """Lazy singleton sqlite-backed idempotency store for Patreon.

    First call materializes the store + parent dir. Tests can swap the
    singleton by assigning to ``_patreon_idempotency_store`` directly.
    """
    global _patreon_idempotency_store  # noqa: PLW0603 — module-level singleton
    if _patreon_idempotency_store is None:
        _patreon_idempotency_store = _RailIdempotencyStore(
            db_path=default_idempotency_db_path("patreon"),
        )
    return _patreon_idempotency_store


def _get_stripe_payment_link_idempotency_store() -> StripePaymentLinkIdempotencyStore:
    """Lazy singleton sqlite-backed idempotency store for Stripe Payment Link.

    First-call creates the store + parent directory. Subsequent calls
    reuse the same instance (sqlite connections are short-lived per
    `record_or_skip` call). Tests can swap the singleton by assigning
    to ``_stripe_payment_link_idempotency_store`` directly.
    """
    global _stripe_payment_link_idempotency_store  # noqa: PLW0603 — module-level singleton
    if _stripe_payment_link_idempotency_store is None:
        _stripe_payment_link_idempotency_store = StripePaymentLinkIdempotencyStore()
    return _stripe_payment_link_idempotency_store


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
    raw_body = await request.body()

    if not raw_body:
        # Empty body + no signature is a valid GitHub heartbeat.
        receiver = GitHubSponsorsRailReceiver()
        result = receiver.ingest_webhook({}, None)
        if result is None:
            return JSONResponse({"status": "ping_ok"})
        # Defensive — the heartbeat path returns None, anything else
        # would be unexpected.
        raise HTTPException(status_code=500, detail="unexpected non-None result from heartbeat")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("github_sponsors webhook: malformed JSON")
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    signature = request.headers.get(GITHUB_SPONSORS_SIGNATURE_HEADER)

    receiver = GitHubSponsorsRailReceiver()
    try:
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)
    except GitHubSponsorsReceiveOnlyRailError as exc:
        log.warning("github_sponsors webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        return JSONResponse({"status": "ping_ok"})

    publisher = GitHubSponsorsPublisher()
    publish_result = publisher.publish_event(event)

    if publish_result.refused:
        log.info(
            "github_sponsors publish refused: %s",
            publish_result.detail,
        )
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("github_sponsors publish error: %s", publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )

    return JSONResponse(
        {
            "status": "received",
            "event_kind": event.event_kind.value,
            "publish_detail": publish_result.detail,
            "raw_payload_sha256": event.raw_payload_sha256,
        }
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
    raw_body = await request.body()

    if not raw_body:
        receiver = LiberapayRailReceiver()
        result = receiver.ingest_webhook({}, None)
        if result is None:
            return JSONResponse({"status": "ping_ok"})
        raise HTTPException(status_code=500, detail="unexpected non-None result from heartbeat")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("liberapay webhook: malformed JSON")
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    signature = request.headers.get(LIBERAPAY_SIGNATURE_HEADER)
    delivery_id = _resolve_liberapay_delivery_id(request.headers)

    receiver = LiberapayRailReceiver(
        idempotency_store=_get_liberapay_idempotency_store(),
    )
    try:
        event = receiver.ingest_webhook(
            payload,
            signature,
            raw_body=raw_body,
            delivery_id=delivery_id,
        )
    except LiberapayReceiveOnlyRailError as exc:
        log.warning("liberapay webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        # Either heartbeat ping or duplicate delivery_id — both 200 OK.
        if payload and isinstance(delivery_id, str) and delivery_id:
            log.info("liberapay webhook duplicate: %s", delivery_id)
            return JSONResponse({"status": "duplicate", "delivery_id": delivery_id})
        return JSONResponse({"status": "ping_ok"})

    publisher = LiberapayPublisher()
    publish_result = publisher.publish_event(event)

    if publish_result.refused:
        log.info("liberapay publish refused: %s", publish_result.detail)
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("liberapay publish error: %s", publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )

    return JSONResponse(
        {
            "status": "received",
            "event_kind": event.event_kind.value,
            "publish_detail": publish_result.detail,
            "raw_payload_sha256": event.raw_payload_sha256,
        }
    )


@router.post("/open-collective")
async def receive_open_collective_webhook(request: Request) -> JSONResponse:
    """Receive an Open Collective webhook delivery and dispatch.

    Open Collective signs deliveries with HMAC SHA-256 in the
    ``X-Open-Collective-Signature`` header. Multi-currency native;
    no cancellation event in the canonical 4 (so no auto-link path).
    """
    raw_body = await request.body()

    if not raw_body:
        receiver = OpenCollectiveRailReceiver()
        result = receiver.ingest_webhook({}, None)
        if result is None:
            return JSONResponse({"status": "ping_ok"})
        raise HTTPException(status_code=500, detail="unexpected non-None result from heartbeat")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("open_collective webhook: malformed JSON")
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    signature = request.headers.get(OPEN_COLLECTIVE_SIGNATURE_HEADER)

    receiver = OpenCollectiveRailReceiver()
    try:
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)
    except OpenCollectiveReceiveOnlyRailError as exc:
        log.warning("open_collective webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        return JSONResponse({"status": "ping_ok"})

    publisher = OpenCollectivePublisher()
    publish_result = publisher.publish_event(event)

    if publish_result.refused:
        log.info("open_collective publish refused: %s", publish_result.detail)
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("open_collective publish error: %s", publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )

    return JSONResponse(
        {
            "status": "received",
            "event_kind": event.event_kind.value,
            "publish_detail": publish_result.detail,
            "raw_payload_sha256": event.raw_payload_sha256,
        }
    )


@router.post("/stripe-payment-link")
async def receive_stripe_payment_link_webhook(request: Request) -> JSONResponse:
    """Receive a Stripe Payment Link webhook delivery and dispatch.

    Stripe signs deliveries with a timestamped HMAC SHA-256 in the
    ``Stripe-Signature`` header (``t=<unix>,v1=<hex>`` format). The
    rail's ``ingest_webhook`` parses + verifies internally with
    replay-tolerance.
    """
    raw_body = await request.body()

    if not raw_body:
        receiver = StripePaymentLinkRailReceiver()
        result = receiver.ingest_webhook({}, None)
        if result is None:
            return JSONResponse({"status": "ping_ok"})
        raise HTTPException(status_code=500, detail="unexpected non-None result from heartbeat")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("stripe_payment_link webhook: malformed JSON")
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    signature = request.headers.get(STRIPE_PAYMENT_LINK_SIGNATURE_HEADER)

    receiver = StripePaymentLinkRailReceiver(
        idempotency_store=_get_stripe_payment_link_idempotency_store(),
    )
    try:
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)
    except StripePaymentLinkReceiveOnlyRailError as exc:
        log.warning("stripe_payment_link webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        # Either heartbeat ping (empty payload) or duplicate event id —
        # both shapes return 200 OK so Stripe stops retrying.
        if payload:
            event_id = payload.get("id", "<missing>")
            log.info("stripe_payment_link webhook duplicate: %s", event_id)
            return JSONResponse({"status": "duplicate", "event_id": event_id})
        return JSONResponse({"status": "ping_ok"})

    publisher = StripePaymentLinkPublisher()
    publish_result = publisher.publish_event(event)

    if publish_result.refused:
        log.info("stripe_payment_link publish refused: %s", publish_result.detail)
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("stripe_payment_link publish error: %s", publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )

    return JSONResponse(
        {
            "status": "received",
            "event_kind": event.event_kind.value,
            "publish_detail": publish_result.detail,
            "raw_payload_sha256": event.raw_payload_sha256,
        }
    )


@router.post("/ko-fi")
async def receive_ko_fi_webhook(request: Request) -> JSONResponse:
    """Receive a Ko-fi webhook delivery and dispatch.

    Ko-fi uses **token-in-payload verification** (not HMAC). The
    sender includes a ``verification_token`` field in the JSON body
    matching the per-page secret configured in the Ko-fi dashboard.
    The rail's ``ingest_webhook`` reads the token field inline and
    fails closed on mismatch.
    """
    raw_body = await request.body()

    if not raw_body:
        receiver = KoFiRailReceiver()
        result = receiver.ingest_webhook({}, verify_token=False)
        if result is None:
            return JSONResponse({"status": "ping_ok"})
        raise HTTPException(status_code=500, detail="unexpected non-None result from heartbeat")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("ko_fi webhook: malformed JSON")
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    receiver = KoFiRailReceiver(idempotency_store=_get_ko_fi_idempotency_store())
    try:
        event = receiver.ingest_webhook(payload, verify_token=True)
    except KoFiReceiveOnlyRailError as exc:
        log.warning("ko_fi webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        # Either heartbeat ping or duplicate kofi_transaction_id — both 200 OK.
        transaction_id = payload.get("kofi_transaction_id") if payload else None
        if payload and isinstance(transaction_id, str) and transaction_id:
            log.info("ko_fi webhook duplicate: %s", transaction_id)
            return JSONResponse({"status": "duplicate", "kofi_transaction_id": transaction_id})
        return JSONResponse({"status": "ping_ok"})

    publisher = KoFiPublisher()
    publish_result = publisher.publish_event(event)

    if publish_result.refused:
        log.info("ko_fi publish refused: %s", publish_result.detail)
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("ko_fi publish error: %s", publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )

    return JSONResponse(
        {
            "status": "received",
            "event_kind": event.event_kind.value,
            "publish_detail": publish_result.detail,
            "raw_payload_sha256": event.raw_payload_sha256,
        }
    )


@router.post("/patreon")
async def receive_patreon_webhook(request: Request) -> JSONResponse:
    """Receive a Patreon webhook delivery and dispatch.

    Patreon's signature shape is HMAC MD5 (not SHA-256, per their
    documented wire format) in the ``X-Patreon-Signature`` header.
    The event-kind ships separately in ``X-Patreon-Event`` (colon-
    delimited form like ``members:pledge:create``).
    """
    raw_body = await request.body()

    if not raw_body:
        receiver = PatreonRailReceiver()
        result = receiver.ingest_webhook({}, None, None)
        if result is None:
            return JSONResponse({"status": "ping_ok"})
        raise HTTPException(status_code=500, detail="unexpected non-None result from heartbeat")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("patreon webhook: malformed JSON")
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    signature = request.headers.get(PATREON_SIGNATURE_HEADER)
    event_header = request.headers.get(PATREON_EVENT_HEADER)
    webhook_id = request.headers.get("X-Patreon-Webhook-Id")

    receiver = PatreonRailReceiver(idempotency_store=_get_patreon_idempotency_store())
    try:
        event = receiver.ingest_webhook(
            payload,
            signature,
            event_header,
            raw_body=raw_body,
            webhook_id=webhook_id,
        )
    except PatreonReceiveOnlyRailError as exc:
        log.warning("patreon webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        # Either heartbeat ping or duplicate webhook id — both 200 OK.
        if payload and webhook_id:
            log.info("patreon webhook duplicate: %s", webhook_id)
            return JSONResponse({"status": "duplicate", "webhook_id": webhook_id})
        return JSONResponse({"status": "ping_ok"})

    publisher = PatreonPublisher()
    publish_result = publisher.publish_event(event)

    if publish_result.refused:
        log.info("patreon publish refused: %s", publish_result.detail)
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("patreon publish error: %s", publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )

    return JSONResponse(
        {
            "status": "received",
            "event_kind": event.event_kind.value,
            "publish_detail": publish_result.detail,
            "raw_payload_sha256": event.raw_payload_sha256,
        }
    )


@router.post("/buy-me-a-coffee")
async def receive_buy_me_a_coffee_webhook(request: Request) -> JSONResponse:
    """Receive a Buy Me a Coffee webhook delivery and dispatch.

    BMaC signs deliveries with HMAC SHA-256 over the raw body in the
    ``X-Signature-Sha256`` header. Both bare hex digest and
    ``sha256=<hex>`` prefixed forms are accepted.
    """
    raw_body = await request.body()

    if not raw_body:
        receiver = BuyMeACoffeeRailReceiver()
        result = receiver.ingest_webhook({}, None)
        if result is None:
            return JSONResponse({"status": "ping_ok"})
        raise HTTPException(status_code=500, detail="unexpected non-None result from heartbeat")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("buy_me_a_coffee webhook: malformed JSON")
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    signature = request.headers.get(BUY_ME_A_COFFEE_SIGNATURE_HEADER)

    receiver = BuyMeACoffeeRailReceiver(
        idempotency_store=_get_buy_me_a_coffee_idempotency_store(),
    )
    try:
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)
    except BuyMeACoffeeReceiveOnlyRailError as exc:
        log.warning("buy_me_a_coffee webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        # Either heartbeat ping or duplicate event_id — both 200 OK.
        event_id = payload.get("event_id") if payload else None
        if payload and isinstance(event_id, str) and event_id:
            log.info("buy_me_a_coffee webhook duplicate: %s", event_id)
            return JSONResponse({"status": "duplicate", "event_id": event_id})
        return JSONResponse({"status": "ping_ok"})

    publisher = BuyMeACoffeePublisher()
    publish_result = publisher.publish_event(event)

    if publish_result.refused:
        log.info("buy_me_a_coffee publish refused: %s", publish_result.detail)
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("buy_me_a_coffee publish error: %s", publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )

    return JSONResponse(
        {
            "status": "received",
            "event_kind": event.event_kind.value,
            "publish_detail": publish_result.detail,
            "raw_payload_sha256": event.raw_payload_sha256,
        }
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
    raw_body = await request.body()

    if not raw_body:
        receiver = MercuryRailReceiver()
        result = receiver.ingest_webhook({}, None)
        if result is None:
            return JSONResponse({"status": "ping_ok"})
        raise HTTPException(status_code=500, detail="unexpected non-None result from heartbeat")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("mercury webhook: malformed JSON")
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    # Canonical header takes precedence; fall back to legacy.
    signature = request.headers.get(MERCURY_SIGNATURE_HEADER) or request.headers.get(
        MERCURY_LEGACY_SIGNATURE_HEADER
    )

    receiver = MercuryRailReceiver()
    try:
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)
    except MercuryReceiveOnlyRailError as exc:
        log.warning("mercury webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        return JSONResponse({"status": "ping_ok"})

    publisher = MercuryPublisher()
    publish_result = publisher.publish_event(event)

    if publish_result.refused:
        log.info("mercury publish refused: %s", publish_result.detail)
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("mercury publish error: %s", publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )

    return JSONResponse(
        {
            "status": "received",
            "event_kind": event.event_kind.value,
            "direction": event.direction.value,
            "publish_detail": publish_result.detail,
            "raw_payload_sha256": event.raw_payload_sha256,
        }
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
    raw_body = await request.body()

    if not raw_body:
        receiver = ModernTreasuryRailReceiver()
        result = receiver.ingest_webhook({}, None)
        if result is None:
            return JSONResponse({"status": "ping_ok"})
        raise HTTPException(status_code=500, detail="unexpected non-None result from heartbeat")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("modern_treasury webhook: malformed JSON")
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    signature = request.headers.get(MODERN_TREASURY_SIGNATURE_HEADER)

    receiver = ModernTreasuryRailReceiver()
    try:
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)
    except ModernTreasuryReceiveOnlyRailError as exc:
        log.warning("modern_treasury webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        return JSONResponse({"status": "ping_ok"})

    publisher = ModernTreasuryPublisher()
    publish_result = publisher.publish_event(event)

    if publish_result.refused:
        log.info("modern_treasury publish refused: %s", publish_result.detail)
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("modern_treasury publish error: %s", publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )

    return JSONResponse(
        {
            "status": "received",
            "event_kind": event.event_kind.value,
            "payment_method": event.payment_method.value,
            "publish_detail": publish_result.detail,
            "raw_payload_sha256": event.raw_payload_sha256,
        }
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
    raw_body = await request.body()

    if not raw_body:
        receiver = TreasuryPrimeRailReceiver()
        result = receiver.ingest_webhook({}, None)
        if result is None:
            return JSONResponse({"status": "ping_ok"})
        raise HTTPException(status_code=500, detail="unexpected non-None result from heartbeat")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("treasury_prime webhook: malformed JSON")
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    signature = request.headers.get(TREASURY_PRIME_SIGNATURE_HEADER)

    receiver = TreasuryPrimeRailReceiver()
    try:
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)
    except TreasuryPrimeReceiveOnlyRailError as exc:
        log.warning("treasury_prime webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
        return JSONResponse({"status": "ping_ok"})

    publisher = TreasuryPrimePublisher()
    publish_result = publisher.publish_event(event)

    if publish_result.refused:
        log.info("treasury_prime publish refused: %s", publish_result.detail)
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("treasury_prime publish error: %s", publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )

    return JSONResponse(
        {
            "status": "received",
            "event_kind": event.event_kind.value,
            "publish_detail": publish_result.detail,
            "raw_payload_sha256": event.raw_payload_sha256,
        }
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
