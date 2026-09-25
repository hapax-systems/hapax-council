"""``agents.payment_processors.secrets`` reads through ``shared.secrets`` and redacts.

The loader's contract: a missing secret is ``None`` (the rail disables itself); the log carries
only the redacted reference — never the stored name, the value, or the resolver's reason text;
and an integrity failure is NOT a missing secret.
"""

from __future__ import annotations

from unittest import mock

import pytest

from agents.payment_processors import secrets
from shared.secrets import SecretIntegrityFailed, SecretUnavailable


def test_read_secret_returns_the_first_line_stripped() -> None:
    with mock.patch.object(secrets, "get_secret", return_value="  first-line \nsecond-line\n"):
        assert secrets.read_secret(secrets.LIBERAPAY_USERNAME_KEY) == "first-line"


def test_read_secret_is_none_when_absent_or_blank() -> None:
    with mock.patch.object(secrets, "get_secret", return_value=None):
        assert secrets.read_secret(secrets.LIBERAPAY_USERNAME_KEY) is None
    with mock.patch.object(secrets, "get_secret", return_value="   \n\n"):
        assert secrets.read_secret(secrets.LIBERAPAY_USERNAME_KEY) is None


def test_read_secret_logs_redacted_key_and_no_reason_text(caplog: pytest.LogCaptureFixture) -> None:
    raw_key = secrets.LIBERAPAY_PASSWORD_KEY
    reason = "literal-password-material"
    with (
        mock.patch.object(secrets, "get_secret", side_effect=SecretUnavailable(raw_key, reason)),
        caplog.at_level("DEBUG", logger=secrets.__name__),
    ):
        assert secrets.read_secret(raw_key) is None

    assert raw_key not in caplog.text
    assert reason not in caplog.text
    assert "SecretUnavailable" in caplog.text
    assert secrets._credential_ref(raw_key) in caplog.text


def test_read_secret_propagates_an_integrity_failure() -> None:
    """A blob that is present but will not verify is tampering or corruption, not absence.
    Returning ``None`` here would present a tampered rail credential as 'not bootstrapped yet'."""
    raw_key = secrets.LIGHTNING_ALBY_KEY
    with (
        mock.patch.object(secrets, "get_secret", side_effect=SecretIntegrityFailed(raw_key)),
        pytest.raises(SecretIntegrityFailed),
    ):
        secrets.read_secret(raw_key)


def test_loaders_resolve_their_declared_names() -> None:
    seen: list[str] = []

    def fake(name: str, *, env=None, required=True):
        seen.append(name)
        return "value"

    with mock.patch.object(secrets, "get_secret", side_effect=fake):
        assert secrets.load_alby_token() == "value"
        assert secrets.load_nostr_npub() == "value"
        assert secrets.load_nostr_nsec() == "value"
        assert secrets.load_liberapay_credentials() == ("value", "value")
    assert seen == [
        secrets.LIGHTNING_ALBY_KEY,
        secrets.NOSTR_NPUB_KEY,
        secrets.NOSTR_NSEC_KEY,
        secrets.LIBERAPAY_USERNAME_KEY,
        secrets.LIBERAPAY_PASSWORD_KEY,
    ]
