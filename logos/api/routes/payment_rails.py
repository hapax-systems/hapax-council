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
    ReceiveOnlyRailError as StripePaymentLinkReceiveOnlyRailError,
)
from shared.stripe_payment_link_receive_only_rail import (
    StripePaymentLinkRailReceiver,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payment-rails", tags=["payment-rails"])

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

    receiver = LiberapayRailReceiver()
    try:
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)
    except LiberapayReceiveOnlyRailError as exc:
        log.warning("liberapay webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
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

    receiver = StripePaymentLinkRailReceiver()
    try:
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)
    except StripePaymentLinkReceiveOnlyRailError as exc:
        log.warning("stripe_payment_link webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
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

    receiver = KoFiRailReceiver()
    try:
        event = receiver.ingest_webhook(payload, verify_token=True)
    except KoFiReceiveOnlyRailError as exc:
        log.warning("ko_fi webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
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

    receiver = PatreonRailReceiver()
    try:
        event = receiver.ingest_webhook(payload, signature, event_header, raw_body=raw_body)
    except PatreonReceiveOnlyRailError as exc:
        log.warning("patreon webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
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

    receiver = BuyMeACoffeeRailReceiver()
    try:
        event = receiver.ingest_webhook(payload, signature, raw_body=raw_body)
    except BuyMeACoffeeReceiveOnlyRailError as exc:
        log.warning("buy_me_a_coffee webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if event is None:
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
    "router",
]
