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
    with patch("shared.google_auth._load_token_from_pass", return_value=mock_creds):
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
        patch("shared.google_auth._load_token_from_pass", return_value=mock_creds),
        patch("shared.google_auth._save_token_to_pass") as mock_save,
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
