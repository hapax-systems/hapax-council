"""Tests for the mail-monitor FastAPI webhook route."""

from __future__ import annotations

import base64
import json
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from logos.api.routes import mail_monitor


def _payload(history_id: str = "123") -> dict:
    data = base64.urlsafe_b64encode(
        json.dumps({"emailAddress": "operator@example.com", "historyId": history_id}).encode(
            "utf-8"
        )
    ).decode("ascii")
    return {"message": {"messageId": "pubsub-1", "data": data}}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(mail_monitor.router)
    return TestClient(app)


def test_gmail_webhook_verifies_and_processes_notification() -> None:
    client = _client()

    with (
        mock.patch("logos.api.routes.mail_monitor.verify_authorization") as verify,
        mock.patch(
            "logos.api.routes.mail_monitor._process_notification", return_value=2
        ) as process,
    ):
        response = client.post(
            "/webhook/gmail",
            json=_payload("555"),
            headers={"Authorization": "Bearer signed.jwt"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "processed": 2}
    verify.assert_called_once_with("Bearer signed.jwt")
    process.assert_called_once_with("555")


def test_gmail_webhook_rejects_bad_auth() -> None:
    client = _client()

    with mock.patch(
        "logos.api.routes.mail_monitor.verify_authorization",
        side_effect=mail_monitor.WebhookAuthError("bad"),
    ):
        response = client.post("/webhook/gmail", json=_payload())

    assert response.status_code == 401


def test_gmail_webhook_unauthorized_response_is_empty() -> None:
    """Rejected auth must reveal nothing in the body. Attackers learn nothing."""

    client = _client()

    with mock.patch(
        "logos.api.routes.mail_monitor.verify_authorization",
        side_effect=mail_monitor.WebhookAuthError("missing token"),
    ):
        response = client.post("/webhook/gmail", json=_payload())

    assert response.status_code == 401
    assert response.content == b""
    assert "invalid" not in response.text.lower()
    assert "authorization" not in response.text.lower()


def test_gmail_webhook_unauthorized_response_has_no_store_header() -> None:
    """Rejected auth must not be cached by any intermediary."""

    client = _client()

    with mock.patch(
        "logos.api.routes.mail_monitor.verify_authorization",
        side_effect=mail_monitor.WebhookAuthError("bad token"),
    ):
        response = client.post("/webhook/gmail", json=_payload())

    cache_control = response.headers.get("cache-control", "")
    assert "no-store" in cache_control.lower(), (
        f"401 response missing Cache-Control: no-store; got {cache_control!r}"
    )


def test_gmail_webhook_unauthorized_does_not_invoke_processor() -> None:
    """Auth failure short-circuits before any Gmail-side work happens."""

    client = _client()

    with (
        mock.patch(
            "logos.api.routes.mail_monitor.verify_authorization",
            side_effect=mail_monitor.WebhookAuthError("bad"),
        ),
        mock.patch("logos.api.routes.mail_monitor.decode_pubsub_envelope") as decode,
        mock.patch("logos.api.routes.mail_monitor._process_notification") as process,
    ):
        response = client.post("/webhook/gmail", json=_payload())

    assert response.status_code == 401
    decode.assert_not_called()
    process.assert_not_called()


def test_gmail_webhook_rejects_bad_payload() -> None:
    client = _client()

    with mock.patch("logos.api.routes.mail_monitor.verify_authorization"):
        response = client.post(
            "/webhook/gmail",
            json={"message": {"data": "bad"}},
            headers={"Authorization": "Bearer signed.jwt"},
        )

    assert response.status_code == 400


def test_gmail_webhook_503s_when_processor_unavailable() -> None:
    client = _client()

    with (
        mock.patch("logos.api.routes.mail_monitor.verify_authorization"),
        mock.patch(
            "logos.api.routes.mail_monitor._process_notification",
            side_effect=RuntimeError("credentials unavailable"),
        ),
    ):
        response = client.post(
            "/webhook/gmail",
            json=_payload(),
            headers={"Authorization": "Bearer signed.jwt"},
        )

    assert response.status_code == 503
