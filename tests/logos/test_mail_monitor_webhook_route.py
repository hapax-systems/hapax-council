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
