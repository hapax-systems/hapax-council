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

from agents.publication_bus.github_sponsors_publisher import (
    GitHubSponsorsPublisher,
)
from shared.github_sponsors_receive_only_rail import (
    GitHubSponsorsRailReceiver,
    ReceiveOnlyRailError,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payment-rails", tags=["payment-rails"])

GITHUB_SPONSORS_SIGNATURE_HEADER: str = "X-Hub-Signature-256"
"""GitHub Sponsors webhook signature header. Documented at
https://docs.github.com/en/webhooks/webhook-events-and-payloads — the
``sha256=<hex>`` form is GitHub's canonical wire shape."""


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
    except ReceiveOnlyRailError as exc:
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


__all__ = [
    "GITHUB_SPONSORS_SIGNATURE_HEADER",
    "router",
]
