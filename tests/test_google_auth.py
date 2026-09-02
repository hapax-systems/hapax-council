"""Tests for shared Google auth utilities."""

from __future__ import annotations

import re
from pathlib import Path
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


_DRIVE_RO = "https://www.googleapis.com/auth/drive.readonly"


def test_build_service_passes_interactive_through_to_the_credential_loader():
    """An unattended caller's ``interactive=False`` must reach the loader unchanged."""
    from shared.google_auth import build_service

    with (
        patch("shared.google_auth.get_google_credentials") as mock_creds,
        patch("shared.google_auth.discovery_build") as mock_build,
    ):
        mock_build.return_value = MagicMock()
        build_service("drive", "v3", [_DRIVE_RO], interactive=False)
    mock_creds.assert_called_once_with([_DRIVE_RO], pass_key="google/token", interactive=False)


def test_non_interactive_build_service_refuses_instead_of_building_an_unauthenticated_client():
    """No token + no consent flow = a refusal naming the pass key and the remedy, never a client."""
    from shared.google_auth import GoogleCredentialsUnavailable, build_service

    with (
        patch("shared.google_auth._load_token_from_pass", return_value=None),
        patch("shared.google_auth.discovery_build") as mock_build,
    ):
        with pytest.raises(GoogleCredentialsUnavailable) as excinfo:
            build_service("drive", "v3", [_DRIVE_RO], interactive=False)
    mock_build.assert_not_called()
    message = str(excinfo.value)
    assert "'google/token'" in message
    assert "Next action" in message
    assert "scripts/mint-google-token.py --pass-key google/token" in message


def test_unattended_google_callers_use_the_shared_client_non_interactively():
    """The retired ``agents._google_auth`` parked daemons on a browser consent flow.

    Every unattended caller now goes through the shared client with the flow
    disabled, and no module under ``agents/`` may import the legacy path again.
    """
    repo = Path(__file__).resolve().parents[1]
    assert not (repo / "agents" / "_google_auth.py").exists()
    offenders = sorted(
        str(path.relative_to(repo))
        for path in (repo / "agents").rglob("*.py")
        if "_google_auth" in path.read_text(encoding="utf-8")
    )
    assert offenders == []
    unattended = [
        "agents/gmail_sync.py",
        "agents/gcalendar_sync.py",
        "agents/gdrive_sync.py",
        "agents/youtube_sync.py",
        "agents/hapax_daimonion/tools.py",
    ]
    for rel in unattended:
        text = (repo / rel).read_text(encoding="utf-8")
        assert "from shared.google_auth import build_service" in text, rel
        calls = re.findall(r"build_service\([^)]*\)", text)
        assert calls, rel
        for call in calls:
            assert "interactive=False" in call, (rel, call)
