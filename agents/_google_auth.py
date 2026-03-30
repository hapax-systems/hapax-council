"""Shared Google OAuth2 credential management.

All Google service sync agents use this module for authentication.
Credentials stored in pass(1): google/client-secret, google/token.
"""

from __future__ import annotations

import json
import logging
import subprocess

from googleapiclient.discovery import build as discovery_build

log = logging.getLogger(__name__)

TOKEN_PASS_KEY = "google/token"
CLIENT_SECRET_PASS_KEY = "google/client-secret"

# All Google scopes to request in a single OAuth consent flow.
# Individual agents pass their own scopes, but the consent flow
# requests all so the token works for every service.
ALL_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def _load_token_from_pass(scopes: list[str]):
    """Load OAuth2 credentials from pass store. Returns Credentials or None."""
    from google.oauth2.credentials import Credentials

    try:
        token_json = subprocess.check_output(
            ["pass", "show", TOKEN_PASS_KEY],
            stderr=subprocess.DEVNULL,
        ).decode()
        return Credentials.from_authorized_user_info(json.loads(token_json), scopes)
    except subprocess.CalledProcessError:
        log.debug("No existing token in pass store")
        return None
    except Exception as exc:
        log.debug("Could not load token: %s", exc)
        return None


def _save_token_to_pass(creds) -> None:
    """Save OAuth token to pass store."""
    token_data = json.dumps(
        {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or []),
        }
    )
    proc = subprocess.run(
        ["pass", "insert", "-m", TOKEN_PASS_KEY],
        input=token_data.encode(),
        capture_output=True,
    )
    if proc.returncode != 0:
        log.warning("Failed to save token to pass: %s", proc.stderr.decode())


def get_google_credentials(scopes: list[str]):
    """Load, refresh, or create OAuth2 credentials.

    Tries cached token first, refreshes if expired, falls back to
    interactive OAuth consent flow (opens browser).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = _load_token_from_pass(scopes)
    if creds:
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            try:
                creds.refresh(Request())
                _save_token_to_pass(creds)
                return creds
            except Exception as exc:
                log.info("Token refresh failed (scope change?): %s", exc)

    # No valid token — run OAuth flow with all known scopes
    # so a single consent covers Drive, Calendar, Gmail, etc.
    all_scopes = list(set(scopes) | set(ALL_SCOPES))
    client_json = subprocess.check_output(
        ["pass", "show", CLIENT_SECRET_PASS_KEY],
        stderr=subprocess.DEVNULL,
    ).decode()
    flow = InstalledAppFlow.from_client_config(json.loads(client_json), all_scopes)
    creds = flow.run_local_server(port=0)
    _save_token_to_pass(creds)
    return creds


def build_service(api: str, version: str, scopes: list[str]):
    """Build an authenticated Google API service client."""
    creds = get_google_credentials(scopes)
    return discovery_build(api, version, credentials=creds)
