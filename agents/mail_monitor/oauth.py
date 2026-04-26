"""mail-monitor OAuth — first-consent CLI + refresh-token loader.

Implements cc-task ``mail-monitor-002-oauth-bootstrap``.

## Bootstrap (operator-physical, one-time)

1. Operator creates a Google Cloud project (or reuses an existing one)
   and enables Gmail API + Cloud Pub/Sub API.
2. Operator creates an OAuth 2.0 Client ID of type ``Desktop app`` and
   inserts the resulting client id + secret into ``pass``::

       pass insert mail-monitor/google-client-id
       pass insert mail-monitor/google-client-secret

3. Operator runs ``python -m agents.mail_monitor.oauth --first-consent``
   once. A browser window opens at the Google consent screen. The
   operator approves the ``gmail.modify`` scope. The refresh token that
   Google returns is persisted to ``pass mail-monitor/google-refresh-token``.

After bootstrap, every daemon process loads the refresh token from
``pass`` and exchanges it for a fresh access token on each call. Refresh
tokens are valid indefinitely until the operator revokes them via
Google Account → Security → Third-party access.

## Daemon use

::

    creds = load_credentials()
    if creds is None:
        emit_awareness_degraded()
        return
    service = build_gmail_service(creds=creds)
    profile = service.users().getProfile(userId="me").execute()

``load_credentials`` returns ``None`` on any of:

- missing ``mail-monitor/google-client-id``
- missing ``mail-monitor/google-client-secret``
- missing ``mail-monitor/google-refresh-token``
- refresh token rejected by Google (``invalid_grant`` → revoked)
- transport error reaching the Google token endpoint

Each outcome increments
``hapax_mail_monitor_oauth_refresh_total{result="..."}`` so the daemon
loop and Grafana dashboard can distinguish between "operator hasn't
bootstrapped yet" and "operator revoked".

## Scope discipline

The OAuth scope requested is *exactly*
``https://www.googleapis.com/auth/gmail.modify``. We deliberately do
not include ``gmail.readonly`` (insufficient — filters require
modify) or ``https://mail.google.com/`` (over-broad — full mail
access is not needed). See spec §1, §5 for the layered privacy
mechanism that compensates for ``gmail.modify`` being mailbox-wide.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from typing import TYPE_CHECKING, Any

from prometheus_client import Counter

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

log = logging.getLogger(__name__)

GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
SCOPES: list[str] = [GMAIL_MODIFY_SCOPE]

CLIENT_ID_PASS_KEY = "mail-monitor/google-client-id"
CLIENT_SECRET_PASS_KEY = "mail-monitor/google-client-secret"
REFRESH_TOKEN_PASS_KEY = "mail-monitor/google-refresh-token"

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"

OAUTH_REFRESH_COUNTER = Counter(
    "hapax_mail_monitor_oauth_refresh_total",
    "OAuth token refresh attempts by outcome.",
    labelnames=("result",),
)
# Pre-register every outcome label so Prometheus scrape returns 0
# series before any traffic, rather than nothing — Grafana stat panels
# render "no data" otherwise.
for _result in ("success", "revoked", "transport_error", "missing_credential"):
    OAUTH_REFRESH_COUNTER.labels(result=_result)


def _pass_show(key: str, *, timeout_s: float = 5.0) -> str | None:
    """Return ``pass show <key>`` first line stripped, or ``None`` on failure.

    Mirrors :func:`agents.payment_processors.secrets.pass_show` so the
    pattern is recognisable to readers across the council codebase.
    """
    try:
        result = subprocess.run(
            ["pass", "show", key],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        log.warning("pass show %s failed: %s", key, exc)
        return None
    if result.returncode != 0:
        log.debug(
            "pass show %s returned %d: %s",
            key,
            result.returncode,
            result.stderr.strip(),
        )
        return None
    value = result.stdout.strip().split("\n", 1)[0].strip()
    return value or None


def _pass_insert(key: str, value: str, *, timeout_s: float = 5.0) -> bool:
    """Write ``value`` to ``pass <key>`` (replacing any prior content).

    Uses ``pass insert -m`` to allow multi-line input via stdin. Returns
    ``True`` on success.
    """
    try:
        result = subprocess.run(
            ["pass", "insert", "-m", "-f", key],
            input=value,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        log.error("pass insert %s failed: %s", key, exc)
        return False
    if result.returncode != 0:
        log.error(
            "pass insert %s returned %d: %s",
            key,
            result.returncode,
            result.stderr.strip(),
        )
        return False
    return True


def _client_config() -> dict[str, dict[str, Any]] | None:
    """Build an InstalledAppFlow ``client_config`` dict from pass-store.

    Returns ``None`` when either the client id or client secret is
    missing — caller should print a hint to the operator pointing at
    the bootstrap docs.
    """
    client_id = _pass_show(CLIENT_ID_PASS_KEY)
    client_secret = _pass_show(CLIENT_SECRET_PASS_KEY)
    if not client_id or not client_secret:
        return None
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }
    }


def run_first_consent(*, port: int = 0) -> bool:
    """Run the InstalledAppFlow consent screen and persist the refresh token.

    Opens the operator's default browser at the Google consent URL.
    On approval, the access token + refresh token are returned by
    ``run_local_server``; the refresh token is the only durable
    artifact we persist. Access tokens are minted fresh per
    :func:`load_credentials` call.

    Returns ``True`` on success. Returns ``False`` (with a logged error
    pointing at the bootstrap runbook) when:

    - the OAuth client credentials are missing from ``pass``
    - the consent flow returned no refresh token (rare; happens when
      the user re-consents an already-authorized client without
      ``prompt=consent``)
    - the refresh token could not be written back to ``pass``
    """
    config = _client_config()
    if config is None:
        log.error(
            "Missing OAuth client credentials. Run:\n"
            "    pass insert %s\n"
            "    pass insert %s\n"
            "See docs/specs/2026-04-25-mail-monitor.md §Bootstrap.",
            CLIENT_ID_PASS_KEY,
            CLIENT_SECRET_PASS_KEY,
        )
        return False

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(config, SCOPES)
    # ``prompt="consent"`` forces a fresh consent screen so Google
    # always returns a refresh token, even when the operator has
    # consented to this client before.
    creds = flow.run_local_server(port=port, prompt="consent")

    refresh_token = getattr(creds, "refresh_token", None)
    if not refresh_token:
        log.error(
            "OAuth flow returned no refresh token. Re-run with a fresh "
            "consent screen (revoke the existing grant in Google "
            "Account → Security → Third-party access first if needed)."
        )
        return False

    if not _pass_insert(REFRESH_TOKEN_PASS_KEY, refresh_token):
        return False

    log.info(
        "OAuth bootstrap complete. Refresh token persisted to pass:%s.",
        REFRESH_TOKEN_PASS_KEY,
    )
    return True


def load_credentials() -> Credentials | None:
    """Load the persisted refresh token and mint a fresh access token.

    Uses the three pass-store entries written during bootstrap to
    construct a :class:`google.oauth2.credentials.Credentials`, then
    calls :meth:`Credentials.refresh` to exchange the refresh token
    for a short-lived access token at the Google token endpoint.

    Returns ``None`` on any failure path; callers should treat ``None``
    as "daemon should enter DEGRADED state and emit
    ``awareness.mail.degraded=true``" per spec §5.5.
    """
    client_id = _pass_show(CLIENT_ID_PASS_KEY)
    client_secret = _pass_show(CLIENT_SECRET_PASS_KEY)
    refresh_token = _pass_show(REFRESH_TOKEN_PASS_KEY)
    if not client_id or not client_secret or not refresh_token:
        OAUTH_REFRESH_COUNTER.labels(result="missing_credential").inc()
        log.warning(
            "OAuth credentials incomplete in pass: id=%s secret=%s refresh=%s. "
            "Run python -m agents.mail_monitor.oauth --first-consent.",
            bool(client_id),
            bool(client_secret),
            bool(refresh_token),
        )
        return None

    from google.auth.exceptions import RefreshError, TransportError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=GOOGLE_TOKEN_URI,
        scopes=SCOPES,
    )

    try:
        creds.refresh(Request())
    except RefreshError as exc:
        # ``invalid_grant`` is Google's signal for "refresh token has
        # been revoked or expired". Anything else (network blip,
        # 5xx) is a transient transport error.
        msg = str(exc).lower()
        if "invalid_grant" in msg or "revoked" in msg or "expired" in msg:
            OAUTH_REFRESH_COUNTER.labels(result="revoked").inc()
            log.warning("OAuth refresh token rejected (revoked): %s", exc)
        else:
            OAUTH_REFRESH_COUNTER.labels(result="transport_error").inc()
            log.warning("OAuth refresh failed: %s", exc)
        return None
    except TransportError as exc:
        OAUTH_REFRESH_COUNTER.labels(result="transport_error").inc()
        log.warning("OAuth refresh transport error: %s", exc)
        return None

    OAUTH_REFRESH_COUNTER.labels(result="success").inc()
    return creds


def build_gmail_service(*, creds: Credentials | None = None) -> Any | None:
    """Return an authenticated ``gmail v1`` service, or ``None`` on failure.

    Mints credentials via :func:`load_credentials` when ``creds`` is
    ``None``. Tests pass a pre-built ``Credentials`` to avoid the
    pass-store + token-refresh path.
    """
    if creds is None:
        creds = load_credentials()
    if creds is None:
        return None
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _verify(creds: Credentials) -> bool:
    """Call ``users.getProfile`` to confirm the access token works.

    Used by ``--verify`` to give the operator a one-shot smoke test
    after running ``--first-consent``. Prints the bound email address
    + total message count to stdout on success.
    """
    from googleapiclient.errors import HttpError

    service = build_gmail_service(creds=creds)
    if service is None:
        print("FAIL: build_gmail_service returned None", file=sys.stderr)
        return False
    try:
        profile = service.users().getProfile(userId="me").execute()
    except HttpError as exc:
        print(f"FAIL: users.getProfile raised HttpError: {exc}", file=sys.stderr)
        return False
    print(json.dumps(profile, indent=2))
    return True


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: ``python -m agents.mail_monitor.oauth [...]``.

    ``--first-consent`` runs the InstalledAppFlow once. ``--verify``
    loads cached credentials and calls ``users.getProfile`` so the
    operator can confirm the bootstrap worked.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agents.mail_monitor.oauth",
        description="mail-monitor OAuth bootstrap + verification.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--first-consent",
        action="store_true",
        help="Run InstalledAppFlow; persist refresh token to pass.",
    )
    group.add_argument(
        "--verify",
        action="store_true",
        help="Load cached credentials; call users.getProfile.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Local consent-callback port (0 = pick free).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.first_consent:
        return 0 if run_first_consent(port=args.port) else 1

    creds = load_credentials()
    if creds is None:
        print(
            "FAIL: load_credentials returned None. Have you run --first-consent yet?",
            file=sys.stderr,
        )
        return 1
    return 0 if _verify(creds) else 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
