"""Shared Google OAuth2 credential management (legacy entry point).

All Google service sync agents use this module for authentication. Credentials live in the
FileStore, read and written through ``shared.secrets``: ``google/client-secret`` and
``google/token``. Never pass.
"""

from __future__ import annotations

import json
import logging

from googleapiclient.discovery import build as discovery_build

from shared.secrets import SecretIntegrityFailed, SecretUnavailable, get_secret, put_secret

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


def _load_token(scopes: list[str]):
    """Load OAuth2 credentials from the ``google/token`` secret. Returns Credentials or None.

    An integrity failure on the stored blob propagates: a token that is present but will not
    verify is not "no token yet".
    """
    from google.oauth2.credentials import Credentials

    try:
        token_json = get_secret(TOKEN_PASS_KEY, required=False)
    except SecretIntegrityFailed:
        raise
    except SecretUnavailable as exc:
        log.debug("Could not load token: %s", type(exc).__name__)
        return None
    if not token_json:
        log.debug("No existing token in the FileStore")
        return None
    try:
        return Credentials.from_authorized_user_info(json.loads(token_json), scopes)
    except Exception as exc:
        log.debug("Could not load token: %s", type(exc).__name__)
        return None


def _save_token(creds) -> None:
    """Save the OAuth token JSON under the ``google/token`` secret (the FileStore)."""
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
    try:
        put_secret(TOKEN_PASS_KEY, token_data.encode("utf-8"))
    except SecretUnavailable as exc:
        log.warning("Failed to save token: %s", type(exc).__name__)


def get_google_credentials(scopes: list[str]):
    """Load, refresh, or create OAuth2 credentials.

    Tries cached token first, refreshes if expired, falls back to
    interactive OAuth consent flow (opens browser).
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = _load_token(scopes)
    if creds:
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            try:
                creds.refresh(Request())
                _save_token(creds)
                return creds
            except Exception as exc:
                log.info("Token refresh failed (scope change?): %s", exc)

    # No valid token — run OAuth flow with all known scopes
    # so a single consent covers Drive, Calendar, Gmail, etc.
    all_scopes = list(set(scopes) | set(ALL_SCOPES))
    client_json = get_secret(CLIENT_SECRET_PASS_KEY)
    flow = InstalledAppFlow.from_client_config(json.loads(client_json), all_scopes)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    return creds


def build_service(api: str, version: str, scopes: list[str]):
    """Build an authenticated Google API service client."""
    creds = get_google_credentials(scopes)
    return discovery_build(api, version, credentials=creds)
