"""Gmail Pub/Sub webhook verification and payload decoding.

Spec: ``docs/specs/2026-04-25-mail-monitor.md`` §5.2 / §5.4.

The Pub/Sub subscription is configured with Google OIDC push auth in
``agents.mail_monitor.pubsub_bootstrap``. This receiver verifies that
JWT before any Gmail client is constructed, then decodes only the small
Pub/Sub notification envelope (emailAddress + historyId). Message body
content is fetched later through the label-scoped history loop.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from agents.mail_monitor.oauth import _pass_show
from agents.mail_monitor.pubsub_bootstrap import (
    PUBSUB_SA_EMAIL_PASS_KEY,
    WEBHOOK_URL_PASS_KEY,
)

log = logging.getLogger(__name__)

WEBHOOK_AUDIENCE_ENV = "HAPAX_MAIL_MONITOR_WEBHOOK_AUDIENCE"
PUBSUB_SA_EMAIL_ENV = "HAPAX_MAIL_MONITOR_PUBSUB_SA_EMAIL"


class WebhookAuthError(RuntimeError):
    """Raised when Pub/Sub push auth is missing or invalid."""


class WebhookPayloadError(ValueError):
    """Raised when a Pub/Sub envelope does not contain a Gmail history id."""


@dataclass(frozen=True)
class GmailNotification:
    """Minimal Gmail Pub/Sub notification payload."""

    history_id: str
    email_address: str | None = None
    message_id: str | None = None


def _env_or_pass(env_name: str, pass_key: str) -> str | None:
    value = os.environ.get(env_name)
    if value:
        return value
    return _pass_show(pass_key)


def expected_audience() -> str | None:
    """Return the OIDC audience expected on Pub/Sub push JWTs."""

    return _env_or_pass(WEBHOOK_AUDIENCE_ENV, WEBHOOK_URL_PASS_KEY)


def expected_service_account_email() -> str | None:
    """Return the service account email Pub/Sub signs as."""

    return _env_or_pass(PUBSUB_SA_EMAIL_ENV, PUBSUB_SA_EMAIL_PASS_KEY)


def bearer_token(authorization: str | None) -> str:
    """Extract a bearer token from an Authorization header."""

    if not authorization:
        raise WebhookAuthError("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise WebhookAuthError("Authorization must be Bearer <token>")
    return token.strip()


def verify_authorization(
    authorization: str | None,
    *,
    audience: str | None = None,
    expected_email: str | None = None,
) -> dict[str, Any]:
    """Verify Pub/Sub OIDC push authorization and return JWT claims."""

    token = bearer_token(authorization)
    audience = audience or expected_audience()
    expected_email = expected_email or expected_service_account_email()
    if not audience or not expected_email:
        raise WebhookAuthError(
            "mail-monitor webhook auth is not configured; expected audience and "
            "service account email are required"
        )
    return verify_pubsub_jwt(token, audience=audience, expected_email=expected_email)


def verify_pubsub_jwt(
    token: str,
    *,
    audience: str,
    expected_email: str,
) -> dict[str, Any]:
    """Verify a Google-signed Pub/Sub OIDC JWT."""

    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_oauth2_token(token, Request(), audience)
    except ValueError as exc:
        raise WebhookAuthError(f"invalid Pub/Sub JWT: {exc}") from exc

    signer_email = claims.get("email")
    if signer_email != expected_email:
        raise WebhookAuthError("Pub/Sub JWT signer email mismatch")
    if claims.get("email_verified") is False:
        raise WebhookAuthError("Pub/Sub JWT email is not verified")
    return claims


def _decode_json_b64(data: str) -> dict[str, Any]:
    try:
        padded = data + "=" * (-len(data) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        decoded = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookPayloadError("Pub/Sub message.data is not base64 JSON") from exc
    if not isinstance(decoded, dict):
        raise WebhookPayloadError("Pub/Sub message.data JSON must be an object")
    return decoded


def decode_pubsub_envelope(payload: dict[str, Any]) -> GmailNotification:
    """Decode the Pub/Sub push envelope into a Gmail notification."""

    message = payload.get("message")
    if not isinstance(message, dict):
        raise WebhookPayloadError("Pub/Sub envelope missing message object")
    data = message.get("data")
    if not isinstance(data, str) or not data:
        raise WebhookPayloadError("Pub/Sub envelope missing message.data")

    notification = _decode_json_b64(data)
    history_id = notification.get("historyId")
    if not history_id:
        raise WebhookPayloadError("Gmail notification missing historyId")

    email_address = notification.get("emailAddress")
    pubsub_message_id = message.get("messageId") or message.get("message_id")
    return GmailNotification(
        history_id=str(history_id),
        email_address=str(email_address) if email_address else None,
        message_id=str(pubsub_message_id) if pubsub_message_id else None,
    )
