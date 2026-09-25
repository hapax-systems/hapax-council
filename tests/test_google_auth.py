"""Tests for shared Google auth utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

google_missing = pytest.importorskip(
    "googleapiclient", reason="google-api-python-client not installed"
)


def test_get_credentials_returns_valid_cached(tmp_path):
    """Valid cached token is returned without refresh."""
    from shared.google_auth import get_google_credentials

    mock_creds = MagicMock()
    mock_creds.valid = True
    with patch("shared.google_auth._load_token", return_value=mock_creds):
        result = get_google_credentials(["https://www.googleapis.com/auth/drive.readonly"])
    assert result is mock_creds


def test_get_credentials_refreshes_expired(tmp_path):
    """Expired token with refresh_token gets refreshed."""
    from shared.google_auth import get_google_credentials

    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "refresh_tok"
    with (
        patch("shared.google_auth._load_token", return_value=mock_creds),
        patch("shared.google_auth._save_token") as mock_save,
    ):
        get_google_credentials(["https://www.googleapis.com/auth/drive.readonly"])
    mock_creds.refresh.assert_called_once()
    mock_save.assert_called_once()


def test_build_service():
    """build_service returns a googleapiclient Resource."""
    from shared.google_auth import build_service

    with (
        patch("shared.google_auth.get_google_credentials") as mock_creds,
        patch("shared.google_auth.discovery_build") as mock_build,
    ):
        mock_build.return_value = MagicMock()
        build_service("drive", "v3", ["https://www.googleapis.com/auth/drive.readonly"])
    mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds.return_value)


def test_pass_key_names():
    """Token pass key uses google/token."""
    from shared.google_auth import CLIENT_SECRET_PASS_KEY, TOKEN_PASS_KEY

    assert TOKEN_PASS_KEY == "google/token"
    assert CLIENT_SECRET_PASS_KEY == "google/client-secret"


def test_load_token_reads_the_secret_and_absent_is_none(monkeypatch):
    import json

    import shared.google_auth as ga

    payload = {
        "token": "t",
        "refresh_token": "r",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "c",
        "client_secret": "s",
        "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
    }
    monkeypatch.setattr(
        ga, "get_secret", lambda name, *, env=None, required=True: json.dumps(payload)
    )
    creds = ga._load_token(payload["scopes"], pass_key="google/token")
    assert creds is not None
    assert creds.refresh_token == "r"

    monkeypatch.setattr(ga, "get_secret", lambda name, *, env=None, required=True: None)
    assert ga._load_token(payload["scopes"], pass_key="google/token") is None


def test_save_token_puts_the_six_fields_as_utf8_json(monkeypatch):
    import json
    from types import SimpleNamespace

    import shared.google_auth as ga

    saved: dict[str, bytes] = {}
    monkeypatch.setattr(ga, "put_secret", lambda name, value: saved.__setitem__(name, value))
    creds = SimpleNamespace(
        token="t", refresh_token="r", token_uri="u", client_id="c", client_secret="s", scopes=["a"]
    )
    ga._save_token(creds, pass_key="google/token-youtube-streaming")
    assert list(saved) == ["google/token-youtube-streaming"]
    assert json.loads(saved["google/token-youtube-streaming"].decode("utf-8")) == {
        "token": "t",
        "refresh_token": "r",
        "token_uri": "u",
        "client_id": "c",
        "client_secret": "s",
        "scopes": ["a"],
    }
