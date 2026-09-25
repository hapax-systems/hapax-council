"""Unit tests for ``agents.mail_monitor.oauth``.

Covers the OAuth bootstrap + refresh-token loader for cc-task
``mail-monitor-002-oauth-bootstrap``. Each test patches the
``shared.secrets`` resolver calls (FileStore, never pass) and the
``Credentials.refresh`` call that hits Google's token endpoint, so
the test suite stays hermetic.
"""

from __future__ import annotations

import json
import types
from typing import Any
from unittest import mock

import pytest
from prometheus_client import REGISTRY

from agents.mail_monitor import oauth
from shared.secrets import SecretIntegrityFailed, SecretUnavailable


def _counter(result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_oauth_refresh_total",
        {"result": result},
    )
    return val or 0.0


# ── _read_secret ──────────────────────────────────────────────────────


def test_read_secret_returns_first_line_stripped() -> None:
    with mock.patch.object(oauth, "get_secret", return_value="my-secret-value\nsecond-line\n"):
        assert oauth._read_secret("any/key") == "my-secret-value"


def test_read_secret_returns_none_when_absent() -> None:
    with mock.patch.object(oauth, "get_secret", return_value=None):
        assert oauth._read_secret("missing/key") is None


def test_read_secret_logs_redacted_key_and_no_reason_text(caplog: pytest.LogCaptureFixture) -> None:
    raw_key = oauth.REFRESH_TOKEN_PASS_KEY
    reason = "refresh-token-material"
    with (
        mock.patch.object(oauth, "get_secret", side_effect=SecretUnavailable(raw_key, reason)),
        caplog.at_level("WARNING", logger=oauth.__name__),
    ):
        assert oauth._read_secret(raw_key) is None

    assert raw_key not in caplog.text
    assert reason not in caplog.text
    assert oauth._credential_ref(raw_key) in caplog.text


def test_read_secret_strips_blank_values() -> None:
    with mock.patch.object(oauth, "get_secret", return_value="   \n\n"):
        assert oauth._read_secret("any/key") is None


def test_read_secret_propagates_an_integrity_failure() -> None:
    """A blob that is present but will not verify is tampering or corruption, not absence —
    it must not read as 'the operator has not bootstrapped yet'."""
    with (
        mock.patch.object(oauth, "get_secret", side_effect=SecretIntegrityFailed("any/key")),
        pytest.raises(SecretIntegrityFailed),
    ):
        oauth._read_secret("any/key")


# ── _write_secret ─────────────────────────────────────────────────────


def test_write_secret_puts_utf8_bytes_through_the_resolver() -> None:
    with mock.patch.object(oauth, "put_secret") as put_mock:
        ok = oauth._write_secret("mail-monitor/google-refresh-token", "abc123")
    assert ok is True
    put_mock.assert_called_once_with("mail-monitor/google-refresh-token", b"abc123")


def test_write_secret_returns_false_when_the_store_is_unavailable() -> None:
    with mock.patch.object(
        oauth, "put_secret", side_effect=SecretUnavailable("mail-monitor/google-refresh-token", "x")
    ):
        assert oauth._write_secret("mail-monitor/google-refresh-token", "abc") is False


def test_write_secret_logs_redacted_key_and_neither_value_nor_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_key = oauth.REFRESH_TOKEN_PASS_KEY
    reason = "store-reason-text"
    with (
        mock.patch.object(oauth, "put_secret", side_effect=SecretUnavailable(raw_key, reason)),
        caplog.at_level("ERROR", logger=oauth.__name__),
    ):
        assert oauth._write_secret(raw_key, "refresh-token-value") is False

    assert raw_key not in caplog.text
    assert reason not in caplog.text
    assert "refresh-token-value" not in caplog.text
    assert oauth._credential_ref(raw_key) in caplog.text


# ── _client_config ────────────────────────────────────────────────────


def test_client_config_returns_installed_dict_when_creds_present() -> None:
    with mock.patch.object(oauth, "_read_secret", side_effect=["my-id", "my-secret"]):
        config = oauth._client_config()
    assert config is not None
    assert config["installed"]["client_id"] == "my-id"
    assert config["installed"]["client_secret"] == "my-secret"
    assert config["installed"]["token_uri"] == oauth.GOOGLE_TOKEN_URI
    assert config["installed"]["auth_uri"] == oauth.GOOGLE_AUTH_URI


def test_client_config_returns_none_when_id_missing() -> None:
    with mock.patch.object(oauth, "_read_secret", side_effect=[None, "secret"]):
        assert oauth._client_config() is None


def test_client_config_returns_none_when_secret_missing() -> None:
    with mock.patch.object(oauth, "_read_secret", side_effect=["id", None]):
        assert oauth._client_config() is None


# ── run_first_consent ─────────────────────────────────────────────────


def _flow_double(refresh_token: str | None = "rt-abc") -> Any:
    """Build a stand-in InstalledAppFlow whose run_local_server returns creds."""
    creds_double = mock.Mock()
    creds_double.refresh_token = refresh_token
    flow = mock.Mock()
    flow.run_local_server = mock.Mock(return_value=creds_double)
    return flow


def test_run_first_consent_writes_refresh_token_to_pass() -> None:
    flow = _flow_double(refresh_token="r-token-XYZ")
    fake_module = mock.Mock()
    fake_module.InstalledAppFlow.from_client_config = mock.Mock(return_value=flow)

    with (
        mock.patch.object(oauth, "_client_config", return_value={"installed": {}}),
        mock.patch.dict("sys.modules", {"google_auth_oauthlib.flow": fake_module}),
        mock.patch.object(oauth, "_write_secret", return_value=True) as insert_mock,
    ):
        ok = oauth.run_first_consent(port=0)

    assert ok is True
    insert_mock.assert_called_once_with(oauth.REFRESH_TOKEN_PASS_KEY, "r-token-XYZ")
    fake_module.InstalledAppFlow.from_client_config.assert_called_once()
    _, scopes_arg = fake_module.InstalledAppFlow.from_client_config.call_args[0]
    assert scopes_arg == [oauth.GMAIL_MODIFY_SCOPE, oauth.GMAIL_SETTINGS_BASIC_SCOPE]
    flow.run_local_server.assert_called_once_with(
        port=0,
        prompt="consent",
        open_browser=False,
    )


def test_run_first_consent_can_open_browser_when_requested() -> None:
    flow = _flow_double(refresh_token="r-token-XYZ")
    fake_module = mock.Mock()
    fake_module.InstalledAppFlow.from_client_config = mock.Mock(return_value=flow)

    with (
        mock.patch.object(oauth, "_client_config", return_value={"installed": {}}),
        mock.patch.dict("sys.modules", {"google_auth_oauthlib.flow": fake_module}),
        mock.patch.object(oauth, "_write_secret", return_value=True),
    ):
        assert oauth.run_first_consent(port=8765, open_browser=True) is True

    flow.run_local_server.assert_called_once_with(
        port=8765,
        prompt="consent",
        open_browser=True,
    )


def test_run_first_consent_aborts_when_client_creds_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        mock.patch.object(oauth, "_client_config", return_value=None),
        caplog.at_level("ERROR", logger=oauth.__name__),
    ):
        assert oauth.run_first_consent() is False
    assert oauth.CLIENT_ID_PASS_KEY not in caplog.text
    assert oauth.CLIENT_SECRET_PASS_KEY not in caplog.text
    assert oauth.CLIENT_ID_PASS_REF in caplog.text
    assert oauth.CLIENT_CREDENTIAL_PASS_REF in caplog.text


def test_run_first_consent_aborts_when_flow_returns_no_refresh_token() -> None:
    flow = _flow_double(refresh_token=None)
    fake_module = mock.Mock()
    fake_module.InstalledAppFlow.from_client_config = mock.Mock(return_value=flow)

    with (
        mock.patch.object(oauth, "_client_config", return_value={"installed": {}}),
        mock.patch.dict("sys.modules", {"google_auth_oauthlib.flow": fake_module}),
        mock.patch.object(oauth, "_write_secret") as insert_mock,
    ):
        ok = oauth.run_first_consent()

    assert ok is False
    insert_mock.assert_not_called()


def test_run_first_consent_returns_false_when_the_write_fails() -> None:
    flow = _flow_double()
    fake_module = mock.Mock()
    fake_module.InstalledAppFlow.from_client_config = mock.Mock(return_value=flow)

    with (
        mock.patch.object(oauth, "_client_config", return_value={"installed": {}}),
        mock.patch.dict("sys.modules", {"google_auth_oauthlib.flow": fake_module}),
        mock.patch.object(oauth, "_write_secret", return_value=False),
    ):
        assert oauth.run_first_consent() is False


# ── load_credentials ──────────────────────────────────────────────────


def test_load_credentials_success_increments_success_metric() -> None:
    before = _counter("success")

    fake_creds = mock.Mock()
    fake_creds.refresh = mock.Mock()  # no-op

    fake_credentials_cls = mock.Mock(return_value=fake_creds)

    with (
        mock.patch.object(oauth, "_read_secret", side_effect=["id", "secret", "refresh"]),
        mock.patch("google.oauth2.credentials.Credentials", fake_credentials_cls),
        mock.patch("google.auth.transport.requests.Request"),
    ):
        creds = oauth.load_credentials()

    assert creds is fake_creds
    fake_creds.refresh.assert_called_once()
    assert _counter("success") - before == 1.0


def test_load_credentials_missing_entries_increments_missing_metric() -> None:
    before = _counter("missing_credential")
    with mock.patch.object(oauth, "_read_secret", side_effect=["id", "secret", None]):
        assert oauth.load_credentials() is None
    assert _counter("missing_credential") - before == 1.0


def test_load_credentials_invalid_grant_marks_revoked() -> None:
    before_revoked = _counter("revoked")
    before_transport = _counter("transport_error")

    from google.auth.exceptions import RefreshError

    fake_creds = mock.Mock()
    fake_creds.refresh = mock.Mock(side_effect=RefreshError("invalid_grant: revoked"))

    with (
        mock.patch.object(oauth, "_read_secret", side_effect=["id", "secret", "refresh"]),
        mock.patch("google.oauth2.credentials.Credentials", mock.Mock(return_value=fake_creds)),
        mock.patch("google.auth.transport.requests.Request"),
    ):
        assert oauth.load_credentials() is None

    assert _counter("revoked") - before_revoked == 1.0
    assert _counter("transport_error") == before_transport


def test_load_credentials_other_refresh_error_marks_transport() -> None:
    before = _counter("transport_error")

    from google.auth.exceptions import RefreshError

    fake_creds = mock.Mock()
    fake_creds.refresh = mock.Mock(side_effect=RefreshError("server_error 500"))

    with (
        mock.patch.object(oauth, "_read_secret", side_effect=["id", "secret", "refresh"]),
        mock.patch("google.oauth2.credentials.Credentials", mock.Mock(return_value=fake_creds)),
        mock.patch("google.auth.transport.requests.Request"),
    ):
        assert oauth.load_credentials() is None

    assert _counter("transport_error") - before == 1.0


def test_load_credentials_transport_error_marks_transport() -> None:
    before = _counter("transport_error")

    from google.auth.exceptions import TransportError

    fake_creds = mock.Mock()
    fake_creds.refresh = mock.Mock(side_effect=TransportError("connection reset"))

    with (
        mock.patch.object(oauth, "_read_secret", side_effect=["id", "secret", "refresh"]),
        mock.patch("google.oauth2.credentials.Credentials", mock.Mock(return_value=fake_creds)),
        mock.patch("google.auth.transport.requests.Request"),
    ):
        assert oauth.load_credentials() is None

    assert _counter("transport_error") - before == 1.0


# ── scope discipline ─────────────────────────────────────────────────


def test_scope_is_minimal_gmail_pair() -> None:
    assert oauth.SCOPES == [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.settings.basic",
    ]


def test_secret_names_match_cc_task_spec() -> None:
    assert oauth.CLIENT_ID_PASS_KEY == "mail-monitor/google-client-id"
    assert oauth.CLIENT_SECRET_PASS_KEY == "mail-monitor/google-client-secret"
    assert oauth.REFRESH_TOKEN_PASS_KEY == "mail-monitor/google-refresh-token"


# ── main / CLI ───────────────────────────────────────────────────────


def test_main_first_consent_returns_zero_on_success() -> None:
    with mock.patch.object(oauth, "run_first_consent", return_value=True) as run_mock:
        rc = oauth.main(["--first-consent"])
    assert rc == 0
    run_mock.assert_called_once_with(port=0, open_browser=False)


def test_main_first_consent_can_request_browser_open() -> None:
    with mock.patch.object(oauth, "run_first_consent", return_value=True) as run_mock:
        rc = oauth.main(["--first-consent", "--open-browser", "--port", "8765"])
    assert rc == 0
    run_mock.assert_called_once_with(port=8765, open_browser=True)


def test_main_first_consent_returns_one_on_failure() -> None:
    with mock.patch.object(oauth, "run_first_consent", return_value=False):
        assert oauth.main(["--first-consent"]) == 1


def test_main_verify_returns_one_when_no_credentials() -> None:
    with mock.patch.object(oauth, "load_credentials", return_value=None):
        assert oauth.main(["--verify"]) == 1


def test_main_verify_calls_get_profile_and_succeeds(capsys: pytest.CaptureFixture) -> None:
    fake_creds = mock.Mock()
    fake_service = mock.Mock()
    fake_service.users().getProfile().execute.return_value = {
        "emailAddress": "ops@example.com",
        "messagesTotal": 42,
    }
    fake_googleapiclient = types.ModuleType("googleapiclient")
    fake_googleapiclient.__path__ = []
    fake_errors = types.ModuleType("googleapiclient.errors")
    fake_errors.HttpError = Exception

    with (
        mock.patch.object(oauth, "load_credentials", return_value=fake_creds),
        mock.patch.object(oauth, "build_gmail_service", return_value=fake_service),
        mock.patch.dict(
            "sys.modules",
            {
                "googleapiclient": fake_googleapiclient,
                "googleapiclient.errors": fake_errors,
            },
        ),
    ):
        rc = oauth.main(["--verify"])

    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["emailAddress"] == "ops@example.com"


def test_main_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        oauth.main([])


# ── prometheus counter zero-init ──────────────────────────────────────


def test_all_outcome_labels_are_pre_registered() -> None:
    """Grafana stat tiles render 'no data' if a label has never been
    inc()'d. Module load must pre-touch every result label."""
    for outcome in ("success", "revoked", "transport_error", "missing_credential"):
        # Pre-registered samples are >= 0, never None.
        val = REGISTRY.get_sample_value(
            "hapax_mail_monitor_oauth_refresh_total",
            {"result": outcome},
        )
        assert val is not None, f"counter label {outcome!r} not pre-registered"
