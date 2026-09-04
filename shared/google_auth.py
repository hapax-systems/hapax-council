"""Shared Google OAuth2 credential management.

All Google service sync agents use this module for authentication.
Credentials stored in pass(1): ``google/client-secret`` + one or more
token entries. ``google/token`` is the default (main Google account —
Gmail / Calendar / Drive / Obsidian).

**Brand-channel / sub-channel tokens**: OAuth tokens are scoped to the
YouTube channel the user picks at consent time, not just the Google
account. When a brand-account sub-channel needs its own scoped token
(e.g., ``liveBroadcasts.list(mine=true)`` must see the sub-channel,
not the primary), the operator mints a second token at a different
pass key (canonical: ``google/token-youtube-streaming``). Callers pass
``pass_key=`` to :func:`get_google_credentials` to opt into the scoped
token; the default path remains the main-account token so gmail sync,
calendar sync, obsidian, etc. are untouched.

Minting a new scoped token: run
``scripts/mint-google-token.py --pass-key google/token-youtube-streaming``
which opens a browser with ``prompt=consent`` forcing the Google
channel picker — the operator selects the sub-channel on the second
screen, and the resulting token gets written to the specified pass key.
"""

from __future__ import annotations

import json
import logging
import shlex
import subprocess

from googleapiclient.discovery import build as discovery_build

log = logging.getLogger(__name__)


class GoogleCredentialsUnavailable(RuntimeError):
    """No usable Google credential exists and the interactive consent flow is disabled.

    Raised by :func:`build_service` for unattended callers so a missing or
    unrefreshable token surfaces as a failed unit naming its remedy, never as a
    process parked forever on a browser consent flow nobody will answer.
    """


TOKEN_PASS_KEY = "google/token"
CLIENT_SECRET_PASS_KEY = "google/client-secret"

# Pass key for the YouTube streaming sub-channel token. Minted by the
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


def _consent_scopes(scopes: list[str]) -> list[str]:
    """Return every requested and shared scope once, in deterministic order."""
    return list(dict.fromkeys([*scopes, *ALL_SCOPES]))


def _load_token_from_pass(scopes: list[str], pass_key: str = TOKEN_PASS_KEY):
    """Load OAuth2 credentials from the specified pass store entry.

    Returns Credentials or None. ``pass_key`` defaults to
    :data:`TOKEN_PASS_KEY` (main Google account); callers that need a
    scoped token (e.g., YouTube brand sub-channel) pass a different key.
    """
    from google.oauth2.credentials import Credentials

    try:
        token_json = subprocess.check_output(
            ["pass", "show", pass_key],
            stderr=subprocess.DEVNULL,
        ).decode()
        return Credentials.from_authorized_user_info(json.loads(token_json), scopes)
    except subprocess.CalledProcessError:
        log.debug("No existing token at pass key %s", pass_key)
        return None
    except Exception as exc:
        log.debug("Could not load token from %s: %s", pass_key, exc)
        return None


def _save_token_to_pass(creds, pass_key: str = TOKEN_PASS_KEY) -> None:
    """Save OAuth token to the specified pass store entry."""
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
        ["pass", "insert", "-m", pass_key],
        input=token_data.encode(),
        capture_output=True,
    )
    if proc.returncode != 0:
        log.warning("Failed to save token to pass %s: %s", pass_key, proc.stderr.decode())


def get_google_credentials(
    scopes: list[str],
    *,
    pass_key: str = TOKEN_PASS_KEY,
    interactive: bool = True,
):
    """Load, refresh, or create OAuth2 credentials.

    ``pass_key`` selects which pass entry to read/write. The default
    (:data:`TOKEN_PASS_KEY`) is the main-account token shared by gmail,
    calendar, drive, and obsidian services. To get a channel-scoped
    token for a brand sub-channel, pass
    :data:`YOUTUBE_STREAMING_TOKEN_PASS_KEY` (or a custom key).

    ``interactive`` — when False, skip the browser consent fallback
    and return None if no cached token exists. Long-running systemd
    daemons should pass ``interactive=False`` so a missing token logs
    a warning rather than hanging on browser-flow blocking IO.
    """
    creds = _load_token_from_pass(scopes, pass_key=pass_key)
    if creds:
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            try:
                creds.refresh(Request())
                _save_token_to_pass(creds, pass_key=pass_key)
                return creds
            except Exception as exc:
                log.info("Token refresh failed for %s (scope change?): %s", pass_key, exc)

    if not interactive:
        log.warning(
            "No valid credentials at pass key %s and interactive flow disabled",
            pass_key,
        )
        return None

    # No valid token — run OAuth flow with all known scopes
    # so a single consent covers Drive, Calendar, Gmail, etc.
    # Imported here, not at the top of the function: unattended callers never
    # reach the consent flow and must not need google_auth_oauthlib installed.
    from google_auth_oauthlib.flow import InstalledAppFlow

    all_scopes = _consent_scopes(scopes)
    client_json = subprocess.check_output(
        ["pass", "show", CLIENT_SECRET_PASS_KEY],
        stderr=subprocess.DEVNULL,
    ).decode()
    flow = InstalledAppFlow.from_client_config(json.loads(client_json), all_scopes)
    creds = flow.run_local_server(port=0)
    _save_token_to_pass(creds, pass_key=pass_key)
    return creds


def build_service(
    api: str,
    version: str,
    scopes: list[str],
    *,
    pass_key: str = TOKEN_PASS_KEY,
    interactive: bool = True,
):
    """Build an authenticated Google API service client.

    ``interactive=False`` is for unattended callers (systemd daemons, the
    daimonion tools). When no usable token exists the call refuses with
    :class:`GoogleCredentialsUnavailable`, naming the pass key and the consent
    command, instead of blocking on a browser flow or building an
    unauthenticated client.
    """
    creds = get_google_credentials(scopes, pass_key=pass_key, interactive=interactive)
    if creds is None:
        mint_command = shlex.join(
            [
                "uv",
                "run",
                "python",
                "scripts/mint-google-token.py",
                "--pass-key",
                pass_key,
                "--scopes",
                *_consent_scopes(scopes),
            ]
        )
        raise GoogleCredentialsUnavailable(
            f"No usable Google credential for {api} {version} at pass key "
            f"{pass_key!r} and the interactive consent flow is disabled. "
            "Next action: mint the token once, interactively, on this host: "
            f"{mint_command}"
        )
    return discovery_build(api, version, credentials=creds)
