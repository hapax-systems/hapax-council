"""Credential loader for payment receivers.

All credentials are read from the ``pass`` store via ``pass show <key>``.
Returns ``None`` on any failure (missing key, gpg-agent unavailable,
pass not installed) so the calling receiver can disable itself
gracefully and emit a refusal-brief annex rather than crash.

The functions are NOT cached: each rail reads at startup and stores
the value in its own runner. Rotating a credential via
``pass insert`` followed by a ``systemctl restart`` is the supported
update path; in-process caches would defeat that.
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

LIGHTNING_ALBY_KEY = "lightning/alby-access-token"
NOSTR_NSEC_KEY = "nostr/nsec-hex"
NOSTR_NPUB_KEY = "nostr/npub-hex"
LIBERAPAY_USERNAME_KEY = "liberapay/username"
LIBERAPAY_PASSWORD_KEY = "liberapay/password"


def pass_show(key: str, *, timeout_s: float = 5.0) -> str | None:
    """Read ``pass show <key>`` and return the stripped first line.

    Returns ``None`` on any failure. The shape mirrors
    ``shared.orcid.operator_orcid`` / ``shared.omg_lol_client`` so the
    pattern is recognizable to readers across the council codebase.
    """
    try:
        result = subprocess.run(
            ["pass", "show", key],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log.warning("pass show %s failed: %s", key, e)
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


def load_alby_token() -> str | None:
    """Return Alby access token or ``None`` if unavailable."""
    return pass_show(LIGHTNING_ALBY_KEY)


def load_nostr_npub() -> str | None:
    """Return operator's Nostr public key (hex) or ``None``."""
    return pass_show(NOSTR_NPUB_KEY)


def load_nostr_nsec() -> str | None:
    """Return operator's Nostr private key (hex) or ``None``.

    NOTE: receivers do NOT sign zaps; this is only used if a future
    receiver needs to publish kind-0 (metadata) for a public profile.
    Receive-only contract is preserved either way.
    """
    return pass_show(NOSTR_NSEC_KEY)


def load_liberapay_credentials() -> tuple[str, str] | None:
    """Return ``(username, password)`` or ``None`` if either missing.

    Liberapay's API uses HTTP Basic auth (no API token product). The
    same credentials are used for the web UI; rotation requires
    ``pass insert liberapay/password`` plus a service restart.
    """
    username = pass_show(LIBERAPAY_USERNAME_KEY)
    password = pass_show(LIBERAPAY_PASSWORD_KEY)
    if not username or not password:
        return None
    return (username, password)


__all__ = [
    "LIBERAPAY_PASSWORD_KEY",
    "LIBERAPAY_USERNAME_KEY",
    "LIGHTNING_ALBY_KEY",
    "NOSTR_NPUB_KEY",
    "NOSTR_NSEC_KEY",
    "load_alby_token",
    "load_liberapay_credentials",
    "load_nostr_npub",
    "load_nostr_nsec",
    "pass_show",
]
