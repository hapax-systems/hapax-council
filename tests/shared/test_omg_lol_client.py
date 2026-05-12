"""Tests for shared/omg_lol_client.py — ytb-OMG1.

Verifies the omg.lol API client wrapper: credential loading, request
shape (method + path + Authorization header), 200 success parsing,
401/403 silent-skip with metric, 429/5xx exponential-backoff retry,
and per-endpoint method dispatch. All HTTP calls mocked via
``requests.Session``; no real network contacted.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared.omg_lol_client import (
    ApiCallOutcome,
    OmgLolClient,
    OmgLolHttpError,
)


def _fake_response(status: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = json_body or {}
    resp.text = text or str(json_body or "")
    resp.headers = {}
    return resp


@pytest.fixture(autouse=True)
def _fake_pass_subprocess(monkeypatch: pytest.MonkeyPatch):
    """Stub out `pass show` so the client gets a deterministic API key
    without touching the real operator password store."""

    def _fake_run(argv, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "fake-omg-lol-api-key\n"
        result.stderr = ""
        return result

    monkeypatch.setattr("shared.omg_lol_client.subprocess.run", _fake_run)


class TestCredentialLoad:
    def test_client_loads_api_key_from_pass(self) -> None:
        client = OmgLolClient()
        assert client.enabled is True
        assert client._api_key == "fake-omg-lol-api-key"

    def test_missing_key_disables_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fail_run(argv, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = "pass: key not found"
            return result

        monkeypatch.setattr("shared.omg_lol_client.subprocess.run", _fail_run)
        client = OmgLolClient()
        assert client.enabled is False


class TestRequestShape:
    def test_get_now_builds_correct_url_and_headers(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {"response": {"content": "hello"}})
        client._session = mock_session

        client.get_now("hapax")

        mock_session.request.assert_called_once()
        call = mock_session.request.call_args
        assert call.kwargs.get("method") == "GET" or call.args[0] == "GET"
        url = call.kwargs.get("url") or call.args[1]
        assert url.endswith("/address/hapax/now")
        headers = call.kwargs["headers"]
        assert headers["Authorization"] == "Bearer fake-omg-lol-api-key"

    def test_post_status_builds_json_body(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {"response": {"id": "abc123"}})
        client._session = mock_session

        client.post_status("hapax", content="test status", emoji="📻")

        call = mock_session.request.call_args
        assert (call.kwargs.get("method") or call.args[0]) == "POST"
        url = call.kwargs.get("url") or call.args[1]
        assert url.endswith("/address/hapax/statuses")
        body = call.kwargs["json"]
        assert body["content"] == "test status"
        assert body["emoji"] == "📻"


class TestExecute200:
    def test_returns_parsed_json(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(
            200, {"request": {"statusCode": 200}, "response": {"message": "ok"}}
        )
        client._session = mock_session

        resp = client._execute("GET", "/address/hapax/now", endpoint="address.now.get")
        assert resp == {"request": {"statusCode": 200}, "response": {"message": "ok"}}


class TestExecute401:
    def test_persistent_401_silent_skips(self) -> None:
        client = OmgLolClient(max_retries=1)
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(401, {"error": "unauthorized"})
        client._session = mock_session

        resp = client._execute("GET", "/address/hapax/now", endpoint="address.now.get")

        assert resp is None
        # Verify not called more than max_retries+1 = 2 times
        assert mock_session.request.call_count <= 2

    def test_persistent_403_silent_skips(self) -> None:
        client = OmgLolClient(max_retries=1)
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(403, {"error": "forbidden"})
        client._session = mock_session

        resp = client._execute("GET", "/address/hapax/now", endpoint="address.now.get")

        assert resp is None


class TestExecute5xx:
    def test_5xx_retries_then_succeeds(self) -> None:
        client = OmgLolClient(max_retries=2, backoff_base_s=0.0)
        mock_session = MagicMock()
        mock_session.request.side_effect = [
            _fake_response(500, {"error": "internal"}),
            _fake_response(503, {"error": "unavailable"}),
            _fake_response(200, {"response": "ok"}),
        ]
        client._session = mock_session

        resp = client._execute("GET", "/x", endpoint="e")

        assert resp == {"response": "ok"}
        assert mock_session.request.call_count == 3

    def test_5xx_gives_up_after_max_retries(self) -> None:
        client = OmgLolClient(max_retries=1, backoff_base_s=0.0)
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(500, {"error": "internal"})
        client._session = mock_session

        resp = client._execute("GET", "/x", endpoint="e")

        assert resp is None
        assert mock_session.request.call_count == 2  # initial + 1 retry


class TestExecute429:
    def test_429_retries_respects_retry_after(self) -> None:
        client = OmgLolClient(max_retries=1, backoff_base_s=0.0)
        mock_session = MagicMock()
        rate_limited = _fake_response(429, {"error": "rate limited"})
        rate_limited.headers = {"Retry-After": "0"}
        mock_session.request.side_effect = [
            rate_limited,
            _fake_response(200, {"response": "ok"}),
        ]
        client._session = mock_session

        resp = client._execute("GET", "/x", endpoint="e")

        assert resp == {"response": "ok"}
        assert mock_session.request.call_count == 2


class TestApiCallOutcome:
    def test_outcome_dataclass_shape(self) -> None:
        outcome = ApiCallOutcome(
            endpoint="test", result="ok", http_status=200, retries=0, latency_s=0.1
        )
        assert outcome.endpoint == "test"
        assert outcome.result == "ok"


class TestDisabledClient:
    def test_disabled_client_silent_skips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fail_run(argv, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = "no key"
            return result

        monkeypatch.setattr("shared.omg_lol_client.subprocess.run", _fail_run)
        client = OmgLolClient()
        assert client.enabled is False
        # Calling through an endpoint method returns None, does not raise.
        resp = client.get_now("hapax")
        assert resp is None


class TestEndpointMethods:
    """Smoke that every documented endpoint method exists and routes to
    the underlying execute with the correct (method, path) shape."""

    def test_get_now_shape(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {})
        client._session = mock_session
        client.get_now("hapax")
        call = mock_session.request.call_args
        assert (call.kwargs.get("method") or call.args[0]) == "GET"
        url = call.kwargs.get("url") or call.args[1]
        assert "/address/hapax/now" in url

    def test_set_now_shape(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {})
        client._session = mock_session
        client.set_now("hapax", content="new content")
        call = mock_session.request.call_args
        assert (call.kwargs.get("method") or call.args[0]) == "POST"
        body = call.kwargs["json"]
        assert body["content"] == "new content"

    def test_get_web_shape(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {})
        client._session = mock_session
        client.get_web("hapax")
        call = mock_session.request.call_args
        url = call.kwargs.get("url") or call.args[1]
        assert "/address/hapax/web" in url

    def test_set_web_shape(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {})
        client._session = mock_session
        client.set_web("hapax", content="<html>...</html>", publish=True)
        call = mock_session.request.call_args
        assert (call.kwargs.get("method") or call.args[0]) == "POST"
        body = call.kwargs["json"]
        assert body["content"] == "<html>...</html>"
        assert body["publish"] is True

    def test_get_statuses_shape(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {"response": {"statuses": []}})
        client._session = mock_session
        client.get_statuses("hapax")
        call = mock_session.request.call_args
        url = call.kwargs.get("url") or call.args[1]
        assert "/address/hapax/statuses" in url

    def test_list_purls_shape(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {"response": {"purls": []}})
        client._session = mock_session
        client.list_purls("hapax")
        call = mock_session.request.call_args
        url = call.kwargs.get("url") or call.args[1]
        assert "/address/hapax/purls" in url

    def test_create_purl_shape(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {})
        client._session = mock_session
        client.create_purl("hapax", name="foo", url="https://example.com")
        call = mock_session.request.call_args
        assert (call.kwargs.get("method") or call.args[0]) == "POST"
        url = call.kwargs.get("url") or call.args[1]
        assert "/address/hapax/purl" in url
        body = call.kwargs["json"]
        assert body["name"] == "foo"
        assert body["url"] == "https://example.com"

    def test_set_paste_shape(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {})
        client._session = mock_session
        client.set_paste("hapax", content="note body", title="my note")
        call = mock_session.request.call_args
        assert (call.kwargs.get("method") or call.args[0]) == "POST"
        url = call.kwargs.get("url") or call.args[1]
        assert "/address/hapax/pastebin" in url
        body = call.kwargs["json"]
        assert body["content"] == "note body"
        assert body["title"] == "my note"

    def test_set_bio_shape(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {})
        client._session = mock_session
        client.set_bio("hapax", content="new bio")
        call = mock_session.request.call_args
        assert (call.kwargs.get("method") or call.args[0]) == "POST"
        url = call.kwargs.get("url") or call.args[1]
        assert "/address/hapax/statuses/bio" in url
        body = call.kwargs["json"]
        assert body["content"] == "new bio"

    def test_delete_weblog_entry_shape(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {})
        client._session = mock_session

        client.delete_entry("hapax", "deploy-verify-weblog-producer")

        call = mock_session.request.call_args
        assert (call.kwargs.get("method") or call.args[0]) == "DELETE"
        url = call.kwargs.get("url") or call.args[1]
        assert url.endswith("/address/hapax/weblog/delete/deploy-verify-weblog-producer")
        assert "/weblog/entry/" not in url

    def test_set_weblog_config_uses_raw_text_body(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {})
        client._session = mock_session

        client.set_weblog_config("hapax", configuration="Weblog title: Hapax Weblog")

        call = mock_session.request.call_args
        assert (call.kwargs.get("method") or call.args[0]) == "POST"
        url = call.kwargs.get("url") or call.args[1]
        assert url.endswith("/address/hapax/weblog/configuration")
        assert call.kwargs["data"] == b"Weblog title: Hapax Weblog"
        assert "json" not in call.kwargs
        assert call.kwargs["headers"]["Content-Type"] == "text/plain; charset=utf-8"

    def test_set_weblog_template_uses_raw_text_body(self) -> None:
        client = OmgLolClient()
        mock_session = MagicMock()
        mock_session.request.return_value = _fake_response(200, {})
        client._session = mock_session

        client.set_template("hapax", template="{body}")

        call = mock_session.request.call_args
        assert (call.kwargs.get("method") or call.args[0]) == "POST"
        url = call.kwargs.get("url") or call.args[1]
        assert url.endswith("/address/hapax/weblog/template")
        assert call.kwargs["data"] == b"{body}"
        assert "json" not in call.kwargs
        assert call.kwargs["headers"]["Content-Type"] == "text/plain; charset=utf-8"


class TestOmgLolHttpError:
    def test_error_carries_status_and_message(self) -> None:
        err = OmgLolHttpError(status=500, endpoint="e.f.g", message="boom")
        assert err.status == 500
        assert err.endpoint == "e.f.g"
        assert "boom" in str(err)
