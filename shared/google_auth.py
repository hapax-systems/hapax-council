"""Shared Google OAuth2 credential management.

All Google service sync agents use this module for authentication.
Credentials live in the FileStore, read through ``shared.secrets``:
``google/client-secret`` + one or more token entries. ``google/token`` is the default (main Google account —
Gmail / Calendar / Drive / Obsidian).

**Brand-channel / sub-channel tokens**: OAuth tokens are scoped to the
YouTube channel the user picks at consent time, not just the Google
account. When a brand-account sub-channel needs its own scoped token
(e.g., ``liveBroadcasts.list(mine=true)`` must see the sub-channel,
not the primary), the operator mints a second token under a different
secret name (canonical: ``google/token-youtube-streaming``). Callers pass
``pass_key=`` to :func:`get_google_credentials` to opt into the scoped
token; the default path remains the main-account token so gmail sync,
calendar sync, obsidian, etc. are untouched.

Minting a new scoped token: run
``scripts/mint-google-token.py --pass-key google/token-youtube-streaming``
which opens a browser with ``prompt=consent`` forcing the Google
channel picker — the operator selects the sub-channel on the second
screen, and the resulting token gets written to the specified secret name.
"""

from __future__ import annotations

import json
import logging

from googleapiclient.discovery import build as discovery_build

from shared.secrets import SecretIntegrityFailed, SecretUnavailable, get_secret, put_secret

log = logging.getLogger(__name__)

TOKEN_PASS_KEY = "google/token"
CLIENT_SECRET_PASS_KEY = "google/client-secret"

# Secret name for the YouTube streaming sub-channel token. Minted by the
# operator running ``scripts/mint-google-token.py`` after selecting the
# sub-channel in the Google OAuth channel picker. Consumed by
# ``scripts/youtube-video-id-publisher.py`` and
# ``scripts/youtube-viewer-count-producer.py`` (when shipped). Falls
# back to TOKEN_PASS_KEY when missing so the caller degrades to the
# main-account token rather than hard-failing — the API then returns
# ``liveStreamingNotEnabled`` on the sub-channel, which is the
# observable that tells the operator to mint the scoped token.
YOUTUBE_STREAMING_TOKEN_PASS_KEY = "google/token-youtube-streaming"

# All Google scopes to request in a single OAuth consent flow.
# Individual agents pass their own scopes, but the consent flow
# requests all so the token works for every service.
ALL_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def _load_token(scopes: list[str], pass_key: str = TOKEN_PASS_KEY):
    """Load OAuth2 credentials from the secret named ``pass_key`` (the FileStore; never pass).

    Returns Credentials or None. ``pass_key`` defaults to :data:`TOKEN_PASS_KEY` (main Google
    account); callers that need a scoped token (e.g., YouTube brand sub-channel) pass a
    different name. An integrity failure on the stored blob propagates: a token that is
    present but will not verify is not "no token yet".
    """
    from google.oauth2.credentials import Credentials

    try:
        token_json = get_secret(pass_key, required=False)
    except SecretIntegrityFailed:
        raise
    except SecretUnavailable as exc:
        log.debug("Could not load token %s: %s", pass_key, type(exc).__name__)
        return None
    if not token_json:
        log.debug("No existing token at secret %s", pass_key)
        return None
    try:
        return Credentials.from_authorized_user_info(json.loads(token_json), scopes)
    except Exception as exc:
        log.debug("Could not load token from %s: %s", pass_key, type(exc).__name__)
        return None


def _save_token(creds, pass_key: str = TOKEN_PASS_KEY) -> None:
    """Save the OAuth token JSON under the secret named ``pass_key`` (the FileStore)."""
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
        put_secret(pass_key, token_data.encode("utf-8"))
    except SecretUnavailable as exc:
        log.warning("Failed to save token %s: %s", pass_key, type(exc).__name__)


def get_google_credentials(
    scopes: list[str],
    *,
    pass_key: str = TOKEN_PASS_KEY,
    interactive: bool = True,
):
    """Load, refresh, or create OAuth2 credentials.

    ``pass_key`` selects which secret name to read/write. The default
    (:data:`TOKEN_PASS_KEY`) is the main-account token shared by gmail,
    calendar, drive, and obsidian services. To get a channel-scoped
    token for a brand sub-channel, pass
    :data:`YOUTUBE_STREAMING_TOKEN_PASS_KEY` (or a custom key).

    ``interactive`` — when False, skip the browser consent fallback
    and return None if no cached token exists. Long-running systemd
    daemons should pass ``interactive=False`` so a missing token logs
    a warning rather than hanging on browser-flow blocking IO.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = _load_token(scopes, pass_key=pass_key)
    if creds:
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            try:
                creds.refresh(Request())
                _save_token(creds, pass_key=pass_key)
                return creds
            except Exception as exc:
                log.info("Token refresh failed for %s (scope change?): %s", pass_key, exc)

    if not interactive:
        log.warning(
            "No valid credentials at secret %s and interactive flow disabled",
            pass_key,
        )
        return None

    # No valid token — run OAuth flow with all known scopes
    # so a single consent covers Drive, Calendar, Gmail, etc.
    all_scopes = list(set(scopes) | set(ALL_SCOPES))
    client_json = get_secret(CLIENT_SECRET_PASS_KEY)
    flow = InstalledAppFlow.from_client_config(json.loads(client_json), all_scopes)
    creds = flow.run_local_server(port=0)
    _save_token(creds, pass_key=pass_key)
    return creds


def build_service(
    api: str,
    version: str,
    scopes: list[str],
    *,
    pass_key: str = TOKEN_PASS_KEY,
):
    """Build an authenticated Google API service client."""
    creds = get_google_credentials(scopes, pass_key=pass_key)
    return discovery_build(api, version, credentials=creds)
