"""Unit tests for ``agents.mail_monitor.oauth``.

Covers the OAuth bootstrap + refresh-token loader for cc-task
``mail-monitor-002-oauth-bootstrap``. Each test patches the
``subprocess.run`` calls that hit ``pass(1)`` and the
``Credentials.refresh`` call that hits Google's token endpoint, so
the test suite stays hermetic.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest import mock

import pytest
from prometheus_client import REGISTRY

from agents.mail_monitor import oauth


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> Any:
    """Build a stand-in for ``subprocess.run`` return value."""
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _counter(result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_oauth_refresh_total",
        {"result": result},
    )
    return val or 0.0


# ── _pass_show ────────────────────────────────────────────────────────


def test_pass_show_returns_first_line_stripped() -> None:
    with mock.patch.object(subprocess, "run", return_value=_completed(stdout="my-secret-value\n")):
        assert oauth._pass_show("any/key") == "my-secret-value"


def test_pass_show_returns_none_on_nonzero_exit() -> None:
    with mock.patch.object(
        subprocess, "run", return_value=_completed(returncode=1, stderr="not in store")
    ):
        assert oauth._pass_show("missing/key") is None


def test_pass_show_returns_none_on_timeout() -> None:
    with mock.patch.object(
        subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd=["pass"], timeout=5.0)
    ):
        assert oauth._pass_show("any/key") is None


def test_pass_show_returns_none_when_pass_missing() -> None:
    with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError("no pass")):
        assert oauth._pass_show("any/key") is None


def test_pass_show_strips_blank_outputs() -> None:
    with mock.patch.object(subprocess, "run", return_value=_completed(stdout="   \n\n")):
        assert oauth._pass_show("any/key") is None


# ── _pass_insert ──────────────────────────────────────────────────────


def test_pass_insert_returns_true_on_success() -> None:
    with mock.patch.object(subprocess, "run", return_value=_completed()) as run_mock:
        ok = oauth._pass_insert("mail-monitor/google-refresh-token", "abc123")
    assert ok is True
    args, kwargs = run_mock.call_args
    assert args[0][:3] == ["pass", "insert", "-m"]
    assert "mail-monitor/google-refresh-token" in args[0]
    assert kwargs["input"] == "abc123"


def test_pass_insert_returns_false_on_nonzero_exit() -> None:
    with mock.patch.object(
        subprocess, "run", return_value=_completed(returncode=1, stderr="gpg failed")
    ):
        assert oauth._pass_insert("mail-monitor/google-refresh-token", "abc") is False


def test_pass_insert_returns_false_when_pass_missing() -> None:
    with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError):
        assert oauth._pass_insert("mail-monitor/google-refresh-token", "abc") is False


# ── _client_config ────────────────────────────────────────────────────


def test_client_config_returns_installed_dict_when_creds_present() -> None:
    with mock.patch.object(oauth, "_pass_show", side_effect=["my-id", "my-secret"]):
        config = oauth._client_config()
    assert config is not None
    assert config["installed"]["client_id"] == "my-id"
    assert config["installed"]["client_secret"] == "my-secret"
    assert config["installed"]["token_uri"] == oauth.GOOGLE_TOKEN_URI
    assert config["installed"]["auth_uri"] == oauth.GOOGLE_AUTH_URI


def test_client_config_returns_none_when_id_missing() -> None:
    with mock.patch.object(oauth, "_pass_show", side_effect=[None, "secret"]):
        assert oauth._client_config() is None


def test_client_config_returns_none_when_secret_missing() -> None:
    with mock.patch.object(oauth, "_pass_show", side_effect=["id", None]):
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
        mock.patch.object(oauth, "_pass_insert", return_value=True) as insert_mock,
    ):
        ok = oauth.run_first_consent(port=0)

    assert ok is True
    insert_mock.assert_called_once_with(oauth.REFRESH_TOKEN_PASS_KEY, "r-token-XYZ")
    fake_module.InstalledAppFlow.from_client_config.assert_called_once()
    _, scopes_arg = fake_module.InstalledAppFlow.from_client_config.call_args[0]
    assert scopes_arg == [oauth.GMAIL_MODIFY_SCOPE]


def test_run_first_consent_aborts_when_client_creds_missing() -> None:
    with mock.patch.object(oauth, "_client_config", return_value=None):
        assert oauth.run_first_consent() is False


def test_run_first_consent_aborts_when_flow_returns_no_refresh_token() -> None:
    flow = _flow_double(refresh_token=None)
    fake_module = mock.Mock()
    fake_module.InstalledAppFlow.from_client_config = mock.Mock(return_value=flow)

    with (
        mock.patch.object(oauth, "_client_config", return_value={"installed": {}}),
        mock.patch.dict("sys.modules", {"google_auth_oauthlib.flow": fake_module}),
        mock.patch.object(oauth, "_pass_insert") as insert_mock,
    ):
        ok = oauth.run_first_consent()

    assert ok is False
    insert_mock.assert_not_called()


def test_run_first_consent_returns_false_when_pass_insert_fails() -> None:
    flow = _flow_double()
    fake_module = mock.Mock()
    fake_module.InstalledAppFlow.from_client_config = mock.Mock(return_value=flow)

    with (
        mock.patch.object(oauth, "_client_config", return_value={"installed": {}}),
        mock.patch.dict("sys.modules", {"google_auth_oauthlib.flow": fake_module}),
        mock.patch.object(oauth, "_pass_insert", return_value=False),
    ):
        assert oauth.run_first_consent() is False


# ── load_credentials ──────────────────────────────────────────────────


def test_load_credentials_success_increments_success_metric() -> None:
    before = _counter("success")

    fake_creds = mock.Mock()
    fake_creds.refresh = mock.Mock()  # no-op

    fake_credentials_cls = mock.Mock(return_value=fake_creds)

    with (
        mock.patch.object(oauth, "_pass_show", side_effect=["id", "secret", "refresh"]),
        mock.patch("google.oauth2.credentials.Credentials", fake_credentials_cls),
        mock.patch("google.auth.transport.requests.Request"),
    ):
        creds = oauth.load_credentials()

    assert creds is fake_creds
    fake_creds.refresh.assert_called_once()
    assert _counter("success") - before == 1.0


def test_load_credentials_missing_pass_entries_increments_missing_metric() -> None:
    before = _counter("missing_credential")
    with mock.patch.object(oauth, "_pass_show", side_effect=["id", "secret", None]):
        assert oauth.load_credentials() is None
    assert _counter("missing_credential") - before == 1.0


def test_load_credentials_invalid_grant_marks_revoked() -> None:
    before_revoked = _counter("revoked")
    before_transport = _counter("transport_error")

    from google.auth.exceptions import RefreshError

    fake_creds = mock.Mock()
    fake_creds.refresh = mock.Mock(side_effect=RefreshError("invalid_grant: revoked"))

    with (
        mock.patch.object(oauth, "_pass_show", side_effect=["id", "secret", "refresh"]),
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
        mock.patch.object(oauth, "_pass_show", side_effect=["id", "secret", "refresh"]),
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
        mock.patch.object(oauth, "_pass_show", side_effect=["id", "secret", "refresh"]),
        mock.patch("google.oauth2.credentials.Credentials", mock.Mock(return_value=fake_creds)),
        mock.patch("google.auth.transport.requests.Request"),
    ):
        assert oauth.load_credentials() is None

    assert _counter("transport_error") - before == 1.0


# ── scope discipline ─────────────────────────────────────────────────


def test_scope_is_exactly_gmail_modify() -> None:
    assert oauth.SCOPES == ["https://www.googleapis.com/auth/gmail.modify"]


def test_pass_keys_match_cc_task_spec() -> None:
    assert oauth.CLIENT_ID_PASS_KEY == "mail-monitor/google-client-id"
    assert oauth.CLIENT_SECRET_PASS_KEY == "mail-monitor/google-client-secret"
    assert oauth.REFRESH_TOKEN_PASS_KEY == "mail-monitor/google-refresh-token"


# ── main / CLI ───────────────────────────────────────────────────────


def test_main_first_consent_returns_zero_on_success() -> None:
    with mock.patch.object(oauth, "run_first_consent", return_value=True) as run_mock:
        rc = oauth.main(["--first-consent"])
    assert rc == 0
    run_mock.assert_called_once_with(port=0)


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

    with (
        mock.patch.object(oauth, "load_credentials", return_value=fake_creds),
        mock.patch.object(oauth, "build_gmail_service", return_value=fake_service),
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
