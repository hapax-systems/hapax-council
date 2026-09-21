"""Credential loader for payment receivers.

All credentials are read through :mod:`shared.secrets` — environment, then the reins
FileStore, then ``hapax-secret`` — never pass. A missing credential returns ``None`` so the
calling receiver can disable itself gracefully and emit a refusal-brief annex rather than
crash. A credential that is PRESENT but fails its integrity check is a different fact: that
raises :class:`shared.secrets.SecretIntegrityFailed` out of the loader, because a tampered
credential must not be reported as "operator has not bootstrapped this rail yet".

The functions are NOT cached: each rail reads at startup and stores the value in its own
runner. Rotating a credential is a put through ``hapax-secret`` (the TTY dialogue) followed by
a ``systemctl restart``; in-process caches would defeat that.
"""

from __future__ import annotations

import logging

from shared.secrets import SecretIntegrityFailed, SecretUnavailable, get_secret

log = logging.getLogger(__name__)

LIGHTNING_ALBY_KEY = "lightning/alby-access-token"
NOSTR_NSEC_KEY = "nostr/nsec-hex"
NOSTR_NPUB_KEY = "nostr/npub-hex"
LIBERAPAY_USERNAME_KEY = "liberapay/username"
LIBERAPAY_PASSWORD_KEY = "liberapay/password"  # pragma: allowlist secret


def _credential_ref(key: str) -> str:
    refs = {
        LIGHTNING_ALBY_KEY: "secret-ref:lightning-alby-credential",
        NOSTR_NSEC_KEY: "secret-ref:nostr-private-credential",
        NOSTR_NPUB_KEY: "secret-ref:nostr-public-key",
        LIBERAPAY_USERNAME_KEY: "secret-ref:liberapay-username",
        LIBERAPAY_PASSWORD_KEY: "secret-ref:liberapay-credential",  # pragma: allowlist secret
    }
    return refs.get(key, "secret-ref:redacted")


def read_secret(key: str) -> str | None:
    """The stored value's first line, stripped, or ``None`` when the secret is absent.

    Mirrors ``agents.mail_monitor.oauth._read_secret`` so the pattern is recognizable to
    readers across the council codebase. Only the redacted reference is ever logged — never
    the name as stored, never the value, never the resolver's reason text.
    """
    try:
        value = get_secret(key, required=False)
    except SecretIntegrityFailed:
        raise
    except SecretUnavailable as exc:
        log.warning("secret unavailable for %s (%s)", _credential_ref(key), type(exc).__name__)
        return None
    if value is None:
        return None
    first = value.strip().split("\n", 1)[0].strip()
    return first or None


def load_alby_token() -> str | None:
    """Return Alby access token or ``None`` if unavailable."""
    return read_secret(LIGHTNING_ALBY_KEY)


def load_nostr_npub() -> str | None:
    """Return operator's Nostr public key (hex) or ``None``."""
    return read_secret(NOSTR_NPUB_KEY)


def load_nostr_nsec() -> str | None:
    """Return operator's Nostr private key (hex) or ``None``.

    NOTE: receivers do NOT sign zaps; this is only used if a future
    receiver needs to publish kind-0 (metadata) for a public profile.
    Receive-only contract is preserved either way.
    """
    return read_secret(NOSTR_NSEC_KEY)


def load_liberapay_credentials() -> tuple[str, str] | None:
    """Return ``(username, password)`` or ``None`` if either missing.

    Liberapay's API uses HTTP Basic auth (no API token product). The
    same credentials are used for the web UI; rotation is a put of
    ``liberapay/password`` through ``hapax-secret`` plus a service restart.
    """
    username = read_secret(LIBERAPAY_USERNAME_KEY)
    password = read_secret(LIBERAPAY_PASSWORD_KEY)
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
    "read_secret",
]
