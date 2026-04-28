"""Mail-monitor webhook routes."""

from __future__ import annotations

import logging
from typing import Any

import anyio
from fastapi import APIRouter, Header, HTTPException, status

from agents.mail_monitor.label_bootstrap import LabelBootstrapError, bootstrap_labels
from agents.mail_monitor.oauth import build_gmail_service, load_credentials
from agents.mail_monitor.runner import process_history
from agents.mail_monitor.webhook_gmail import (
    WebhookAuthError,
    WebhookPayloadError,
    decode_pubsub_envelope,
    verify_authorization,
)

log = logging.getLogger(__name__)

router = APIRouter()


def _process_notification(history_id: str) -> int:
    creds = load_credentials()
    if creds is None:
        raise RuntimeError("mail-monitor Gmail credentials unavailable")
    service = build_gmail_service(creds=creds)
    if service is None:
        raise RuntimeError("mail-monitor Gmail service unavailable")
    label_ids = bootstrap_labels(service)
    return process_history(service, history_id, label_ids_by_name=label_ids)


@router.post("/webhook/gmail")
async def gmail_webhook(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Receive Google Pub/Sub Gmail notifications.

    Non-2xx responses intentionally ask Pub/Sub to retry. The route
    never returns sender, subject, or body content.
    """

    try:
        verify_authorization(authorization)
        notification = decode_pubsub_envelope(payload)
    except WebhookAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid Pub/Sub authorization",
        ) from exc
    except WebhookPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid Pub/Sub Gmail envelope",
        ) from exc

    try:
        processed = await anyio.to_thread.run_sync(
            _process_notification,
            notification.history_id,
        )
    except LabelBootstrapError as exc:
        log.warning("mail-monitor label bootstrap failed during webhook processing: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="mail-monitor label bootstrap unavailable",
        ) from exc
    except RuntimeError as exc:
        log.warning("mail-monitor webhook processing unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="mail-monitor processing unavailable",
        ) from exc

    return {"status": "ok", "processed": processed}
