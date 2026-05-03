"""Internal helpers for payment-rails route handlers.

Extracted in cc-task ``rails-extract-helpers-phase-2`` to consolidate
the repeated boilerplate across 10 webhook receive routes (parse + null
+ refused/error/received dispatch). Each rail-specific route handler
calls these to bracket its rail-unique receiver invocation.

Receive-only invariant preserved: this module only translates between
HTTP and rail-receiver shapes; it never originates an outbound call,
never persists PII, and never bypasses any rail's signature/replay/
idempotency check.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Iterator
from typing import Any, Protocol

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class _PublisherResultLike(Protocol):
    """Duck-typed protocol for `agents.publication_bus.publisher_kit.PublisherResult`.

    Avoids importing the publisher-kit module here so this helper
    stays a pure HTTP-translation surface.
    """

    refused: bool
    error: bool
    detail: str


class _NormalizedEventLike(Protocol):
    """Duck-typed protocol for the rail's normalized event Pydantic model.

    Every rail's normalized event carries `event_kind.value` and
    `raw_payload_sha256`; that's the contract this helper depends on.
    """

    raw_payload_sha256: str

    @property
    def event_kind(self) -> Any: ...


async def parse_webhook_request_body(
    request: Request, *, log_label: str
) -> tuple[bytes, dict[str, Any] | None]:
    """Read the raw body, parse JSON, validate dict shape.

    Returns ``(raw_body, payload)`` where ``payload`` is ``None`` only
    for an empty-body heartbeat (the caller routes empty heartbeats to
    the rail's receiver with empty inputs and returns ``ping_ok``).

    Raises ``HTTPException(400)`` for malformed JSON or non-dict
    payloads, after warning-log.
    """
    raw_body = await request.body()
    if not raw_body:
        return raw_body, None

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        log.warning("%s webhook: malformed JSON", log_label)
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    return raw_body, payload


def render_null_event_response(
    payload: dict[str, Any],
    *,
    duplicate_id_key: str,
    duplicate_id_value: str | None,
    log_label: str,
) -> JSONResponse:
    """Render the receiver's ``None`` return as a 200 OK JSONResponse.

    The receiver returns ``None`` for two cases:
      1. Empty-body heartbeat ping (``payload`` is empty dict)
      2. Idempotency-store short-circuit on duplicate delivery id

    This helper distinguishes via ``duplicate_id_value``: when present
    and non-empty, it's a duplicate; otherwise it's a heartbeat.
    """
    if payload and isinstance(duplicate_id_value, str) and duplicate_id_value:
        log.info("%s webhook duplicate: %s", log_label, duplicate_id_value)
        return JSONResponse({"status": "duplicate", duplicate_id_key: duplicate_id_value})
    return JSONResponse({"status": "ping_ok"})


def dispatch_publish_result(
    publish_result: _PublisherResultLike,
    event: _NormalizedEventLike,
    *,
    log_label: str,
    extra_received_fields: dict[str, Any] | None = None,
) -> JSONResponse:
    """Translate a PublisherResult into the rail's HTTP response.

    Three outcomes:
      - ``refused`` → 200 ``{"status": "refused", "detail": ...}``
      - ``error`` → 500 with the publisher's transport-error message
      - ok → 200 ``{"status": "received", "event_kind": ..., "publish_detail": ..., "raw_payload_sha256": ...}``

    ``extra_received_fields`` allows a rail to add its own fields to
    the received-response payload (e.g. ``payment_method`` for Modern
    Treasury).
    """
    if publish_result.refused:
        log.info("%s publish refused: %s", log_label, publish_result.detail)
        return JSONResponse(
            {"status": "refused", "detail": publish_result.detail},
            status_code=200,
        )
    if publish_result.error:
        log.error("%s publish error: %s", log_label, publish_result.detail)
        raise HTTPException(
            status_code=500,
            detail=f"publisher transport error: {publish_result.detail}",
        )
    body: dict[str, Any] = {
        "status": "received",
        "event_kind": event.event_kind.value,
        "publish_detail": publish_result.detail,
        "raw_payload_sha256": event.raw_payload_sha256,
    }
    if extra_received_fields:
        body.update(extra_received_fields)
    return JSONResponse(body)


@contextlib.contextmanager
def wrap_rail_error_to_400(error_class: type[Exception], *, log_label: str) -> Iterator[None]:
    """Translate a rail's ``ReceiveOnlyRailError`` into HTTP 400.

    Each rail's ``ingest_webhook`` raises its own per-rail subclass of
    ``ReceiveOnlyRailError``. The route's responsibility is uniform:
    log a warning, raise HTTPException(400, detail=str(exc)). This
    context manager DRYs the try/except pattern across 10 rails.

    Usage::

        with wrap_rail_error_to_400(MyRailError, log_label="my_rail"):
            event = receiver.ingest_webhook(...)
    """
    try:
        yield
    except error_class as exc:
        log.warning("%s webhook rejected: %s", log_label, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


__all__ = [
    "dispatch_publish_result",
    "parse_webhook_request_body",
    "render_null_event_response",
    "wrap_rail_error_to_400",
]
