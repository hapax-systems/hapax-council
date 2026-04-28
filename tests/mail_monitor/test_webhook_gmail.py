"""Tests for Gmail Pub/Sub webhook auth/payload helpers."""

from __future__ import annotations

import base64
import json
from unittest import mock

import pytest

from agents.mail_monitor import webhook_gmail


def _encoded_notification(payload: dict[str, str]) -> str:
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_decode_pubsub_envelope_extracts_gmail_history_id() -> None:
    envelope = {
        "message": {
            "messageId": "pubsub-1",
            "data": _encoded_notification(
                {"emailAddress": "operator@example.com", "historyId": "12345"}
            ),
        }
    }

    notification = webhook_gmail.decode_pubsub_envelope(envelope)

    assert notification.history_id == "12345"
    assert notification.email_address == "operator@example.com"
    assert notification.message_id == "pubsub-1"


def test_decode_pubsub_envelope_rejects_missing_history_id() -> None:
    envelope = {"message": {"data": _encoded_notification({"emailAddress": "x@example.com"})}}

    with pytest.raises(webhook_gmail.WebhookPayloadError, match="historyId"):
        webhook_gmail.decode_pubsub_envelope(envelope)


def test_decode_pubsub_envelope_rejects_non_json_data() -> None:
    envelope = {"message": {"data": "not-base64"}}

    with pytest.raises(webhook_gmail.WebhookPayloadError):
        webhook_gmail.decode_pubsub_envelope(envelope)


def test_bearer_token_requires_bearer_scheme() -> None:
    assert webhook_gmail.bearer_token("Bearer token-1") == "token-1"
    with pytest.raises(webhook_gmail.WebhookAuthError):
        webhook_gmail.bearer_token("Basic token-1")


def test_verify_authorization_uses_env_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        webhook_gmail.WEBHOOK_AUDIENCE_ENV,
        "https://logos.example.ts.net:8051/webhook/gmail",
    )
    monkeypatch.setenv(
        webhook_gmail.PUBSUB_SA_EMAIL_ENV,
        "hapax-pubsub@example.iam.gserviceaccount.com",
    )

    with mock.patch(
        "agents.mail_monitor.webhook_gmail.verify_pubsub_jwt",
        return_value={"email": "hapax-pubsub@example.iam.gserviceaccount.com"},
    ) as verify:
        claims = webhook_gmail.verify_authorization("Bearer signed.jwt")

    assert claims["email"] == "hapax-pubsub@example.iam.gserviceaccount.com"
    verify.assert_called_once_with(
        "signed.jwt",
        audience="https://logos.example.ts.net:8051/webhook/gmail",
        expected_email="hapax-pubsub@example.iam.gserviceaccount.com",
    )


def test_verify_authorization_fails_closed_without_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(webhook_gmail.WEBHOOK_AUDIENCE_ENV, raising=False)
    monkeypatch.delenv(webhook_gmail.PUBSUB_SA_EMAIL_ENV, raising=False)
    monkeypatch.setattr(webhook_gmail, "_pass_show", lambda _key: None)

    with pytest.raises(webhook_gmail.WebhookAuthError, match="not configured"):
        webhook_gmail.verify_authorization("Bearer signed.jwt")
