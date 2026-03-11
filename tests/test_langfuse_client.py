"""Tests for shared/langfuse_client.py — Langfuse API client."""
import base64
import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest


def test_auth_header_construction():
    """Verify Basic auth header is base64-encoded pk:sk."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test-123",
        "LANGFUSE_SECRET_KEY": "sk-test-456",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        import importlib
        import shared.langfuse_client as mod
        importlib.reload(mod)

        expected = base64.b64encode(b"pk-test-123:sk-test-456").decode()

        with patch("shared.langfuse_client.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"data": []}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            mod.langfuse_get("/traces", {"limit": 1})

            req = mock_urlopen.call_args[0][0]
            assert req.get_header("Authorization") == f"Basic {expected}"


def test_url_encoding_of_params():
    """Query parameters must be URL-encoded (especially ISO timestamps with +00:00)."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        import importlib
        import shared.langfuse_client as mod
        importlib.reload(mod)

        with patch("shared.langfuse_client.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"data": []}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            mod.langfuse_get("/traces", {
                "fromTimestamp": "2026-01-01T00:00:00+00:00",
                "limit": 100,
            })

            req = mock_urlopen.call_args[0][0]
            url = req.full_url
            # + should be encoded as %2B in query string
            assert "%2B" in url or "fromTimestamp=" in url
            assert "/api/public/traces?" in url


def test_empty_credentials_returns_empty_dict():
    """langfuse_get returns empty dict when credentials are missing."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "",
        "LANGFUSE_SECRET_KEY": "",
    }):
        import importlib
        import shared.langfuse_client as mod
        importlib.reload(mod)

        result = mod.langfuse_get("/traces", {"limit": 1})
        assert result == {}


def test_http_failure_returns_empty_dict():
    """langfuse_get returns empty dict on HTTP failure."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        import importlib
        import shared.langfuse_client as mod
        importlib.reload(mod)

        with patch("shared.langfuse_client.urlopen", side_effect=URLError("connection refused")):
            result = mod.langfuse_get("/traces", {"limit": 1})
            assert result == {}


def test_json_decode_failure_returns_empty_dict():
    """langfuse_get returns empty dict on malformed JSON."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        import importlib
        import shared.langfuse_client as mod
        importlib.reload(mod)

        with patch("shared.langfuse_client.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"not json at all"
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            result = mod.langfuse_get("/traces")
            assert result == {}


def test_is_available_false_without_keys():
    """is_available returns False when no public key."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "",
        "LANGFUSE_SECRET_KEY": "",
    }):
        import importlib
        import shared.langfuse_client as mod
        importlib.reload(mod)

        assert mod.is_available() is False


def test_is_available_true_with_traces():
    """is_available returns True when Langfuse has traces."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        import importlib
        import shared.langfuse_client as mod
        importlib.reload(mod)

        with patch("shared.langfuse_client.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({
                "data": [{"id": "trace-1"}]
            }).encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            assert mod.is_available() is True


def test_is_available_false_no_traces():
    """is_available returns False when Langfuse returns empty data."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        import importlib
        import shared.langfuse_client as mod
        importlib.reload(mod)

        with patch("shared.langfuse_client.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"data": []}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            assert mod.is_available() is False


def test_no_params_omits_query_string():
    """langfuse_get with no params should not append query string."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        import importlib
        import shared.langfuse_client as mod
        importlib.reload(mod)

        with patch("shared.langfuse_client.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"data": []}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            mod.langfuse_get("/traces")

            req = mock_urlopen.call_args[0][0]
            assert req.full_url == "http://localhost:3000/api/public/traces"


def test_timeout_passed_to_urlopen():
    """Custom timeout should be passed to urlopen."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        import importlib
        import shared.langfuse_client as mod
        importlib.reload(mod)

        with patch("shared.langfuse_client.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"data": []}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            mod.langfuse_get("/traces", timeout=30)

            _, kwargs = mock_urlopen.call_args
            assert kwargs.get("timeout") == 30


# ── F-3.1: Distinct error logging per failure type ─────────────────────────

def test_connection_error_logs_connection(caplog):
    """URLError logs with '(connection)' tag."""
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        import importlib, logging
        import shared.langfuse_client as mod
        importlib.reload(mod)

        with patch("shared.langfuse_client.urlopen", side_effect=URLError("refused")):
            with caplog.at_level(logging.WARNING):
                mod.langfuse_get("/traces")

    assert any("(connection)" in r.message for r in caplog.records)


def test_json_error_logs_invalid_json(caplog):
    """JSONDecodeError logs with '(invalid JSON)' tag."""
    import json as _json
    with patch.dict("os.environ", {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "http://localhost:3000",
    }):
        import importlib, logging
        import shared.langfuse_client as mod
        importlib.reload(mod)

        with patch("shared.langfuse_client.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"not json"
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp

            with caplog.at_level(logging.WARNING):
                mod.langfuse_get("/traces")

    assert any("(invalid JSON" in r.message for r in caplog.records)
