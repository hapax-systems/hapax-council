"""Mail-monitor OAuth revocation drill (cc-task 012).

DESTRUCTIVE TEST. Reads the operator's persisted mail-monitor refresh
token, calls Google's OAuth revoke endpoint, then asserts that
``load_credentials()`` returns ``None`` and the
``hapax_mail_monitor_oauth_refresh_total{result="revoked"}`` counter
increments.

Running this test PERMANENTLY revokes the operator's
``mail-monitor/google-refresh-token`` — the mail-monitor daemon will
enter DEGRADED state, and the operator must re-run::

    uv run python -m agents.mail_monitor.oauth --first-consent

to mint a fresh token and resume normal operation.

## When to run

Manually, on explicit operator intent. The test is marked
``@pytest.mark.revocation_drill`` and is **default-deselected** in
``pyproject.toml`` ``addopts``. To run::

    HAPAX_MAIL_MONITOR_REVOCATION_DRILL_OK=1 \\
        uv run pytest -m revocation_drill -v

The env-var gate is belt-and-suspenders so a stray ``-m
revocation_drill`` invocation without the env doesn't accidentally
torch the operator's setup.

## What it asserts (spec §5.5)

1. Before revoke: ``load_credentials()`` returns valid credentials.
2. Revoke via ``POST https://oauth2.googleapis.com/revoke``.
3. After revoke: ``load_credentials()`` returns ``None`` AND the
   ``revoked`` outcome counter increments by exactly 1.

The "daemon emits ``awareness.mail.degraded=true``" deliverable from
the cc-task is verified at the daemon level, not in this test —
``load_credentials()`` returning ``None`` is the daemon's signal to
flip the awareness flag, and the daemon's own startup test covers
that bit.

## Test-account contract

Live target: ``rylklee@gmail.com`` — the operator's primary Google
account, which is also the only account ``mail-monitor-002`` was ever
bootstrapped against. There's no separate test-account because the
operator runs on a single-user system (``single_user`` axiom).
"""

from __future__ import annotations

import os
import time

import pytest
import requests
from prometheus_client import REGISTRY

from agents.mail_monitor import oauth

# Skip the entire module if the env-var gate is missing — running
# without it means the operator did NOT intend to torch the token.
pytestmark = [
    pytest.mark.revocation_drill,
    pytest.mark.skipif(
        os.environ.get("HAPAX_MAIL_MONITOR_REVOCATION_DRILL_OK") != "1",
        reason=(
            "set HAPAX_MAIL_MONITOR_REVOCATION_DRILL_OK=1 to consent to "
            "revoking the operator's live mail-monitor refresh token."
        ),
    ),
]


GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"


def _revoked_counter() -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_oauth_refresh_total",
        {"result": "revoked"},
    )
    return val or 0.0


def test_revocation_drill_renders_credentials_invalid() -> None:
    """End-to-end revocation drill against the live mail-monitor token.

    Pre-condition: ``mail-monitor/google-refresh-token`` is present in
    ``pass`` and currently valid. The test fails fast with a clear
    message if the token is already missing/invalid (operator forgot to
    bootstrap, or already ran the drill).

    Post-condition: the refresh token is revoked at Google. Operator
    must re-bootstrap.
    """
    pre_creds = oauth.load_credentials()
    if pre_creds is None:
        pytest.fail(
            "Pre-condition failed: load_credentials() returned None before "
            "the drill ran. Bootstrap or re-bootstrap the token via "
            "`python -m agents.mail_monitor.oauth --first-consent` first."
        )

    refresh_token = oauth._pass_show(oauth.REFRESH_TOKEN_PASS_KEY)
    assert refresh_token, "refresh token disappeared between load and read"

    response = requests.post(
        GOOGLE_REVOKE_ENDPOINT,
        data={"token": refresh_token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    # Google returns 200 on successful revoke. 400 with
    # ``invalid_token`` means the token was already revoked — also a
    # success path for our purposes.
    assert response.status_code in (200, 400), (
        f"unexpected revoke response {response.status_code}: {response.text}"
    )

    # Brief sleep so Google's token-state propagation completes before
    # we attempt the post-condition refresh.
    time.sleep(3.0)

    before = _revoked_counter()
    post_creds = oauth.load_credentials()

    assert post_creds is None, (
        "Revocation drill failed: load_credentials returned credentials "
        "AFTER revoking the token. Either the revoke didn't take effect "
        "or load_credentials is masking the failure."
    )
    assert _revoked_counter() - before == 1.0, (
        "Revocation drill failed: load_credentials returned None but the "
        "'revoked' outcome counter did not increment. Inspect "
        "load_credentials' RefreshError classification."
    )
