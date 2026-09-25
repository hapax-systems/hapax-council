"""Tests for shared Google auth utilities."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

google_missing = pytest.importorskip(
    "googleapiclient", reason="google-api-python-client not installed"
)


def test_get_credentials_returns_valid_cached(tmp_path):
    """Valid cached token is returned without refresh."""
    from shared.google_auth import get_google_credentials

    mock_creds = MagicMock()
    mock_creds.valid = True
    with patch("shared.google_auth._load_token", return_value=mock_creds):
        result = get_google_credentials(["https://www.googleapis.com/auth/drive.readonly"])
    assert result is mock_creds


def test_get_credentials_refreshes_expired(tmp_path):
    """Expired token with refresh_token gets refreshed."""
    from shared.google_auth import get_google_credentials

    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "refresh_tok"
    with (
        patch("shared.google_auth._load_token", return_value=mock_creds),
        patch("shared.google_auth._save_token") as mock_save,
    ):
        get_google_credentials(["https://www.googleapis.com/auth/drive.readonly"])
    mock_creds.refresh.assert_called_once()
    mock_save.assert_called_once()


def test_build_service():
    """build_service returns a googleapiclient Resource."""
    from shared.google_auth import build_service

    with (
        patch("shared.google_auth.get_google_credentials") as mock_creds,
        patch("shared.google_auth.discovery_build") as mock_build,
    ):
        mock_build.return_value = MagicMock()
        build_service("drive", "v3", ["https://www.googleapis.com/auth/drive.readonly"])
    mock_build.assert_called_once_with("drive", "v3", credentials=mock_creds.return_value)


def test_pass_key_names():
    """Token pass key uses google/token."""
    from shared.google_auth import CLIENT_SECRET_PASS_KEY, TOKEN_PASS_KEY

    assert TOKEN_PASS_KEY == "google/token"
    assert CLIENT_SECRET_PASS_KEY == "google/client-secret"


_DRIVE_RO = "https://www.googleapis.com/auth/drive.readonly"


def test_build_service_passes_interactive_through_to_the_credential_loader():
    """An unattended caller's ``interactive=False`` must reach the loader unchanged."""
    from shared.google_auth import build_service

    with (
        patch("shared.google_auth.get_google_credentials") as mock_creds,
        patch("shared.google_auth.discovery_build") as mock_build,
    ):
        mock_build.return_value = MagicMock()
        build_service("drive", "v3", [_DRIVE_RO], interactive=False)
    mock_creds.assert_called_once_with([_DRIVE_RO], pass_key="google/token", interactive=False)


def test_non_interactive_build_service_refuses_instead_of_building_an_unauthenticated_client():
    """No token + no consent flow = a refusal naming the pass key and the remedy, never a client."""
    from shared.google_auth import GoogleCredentialsUnavailable, build_service

    with (
        patch("shared.google_auth._load_token", return_value=None),
        patch("shared.google_auth.discovery_build") as mock_build,
    ):
        with pytest.raises(GoogleCredentialsUnavailable) as excinfo:
            build_service("drive", "v3", [_DRIVE_RO], interactive=False)
    mock_build.assert_not_called()
    message = str(excinfo.value)
    assert "'google/token'" in message
    assert "Next action" in message
    assert "get_google_credentials" in message
    assert "mint-google-token.py" not in message


def test_unrefreshable_token_refuses_without_opening_a_consent_flow():
    """Review finding at a9c30e854 (major): only an ABSENT token was tested. An expired token
    whose refresh fails must also refuse under ``interactive=False``, without saving anything and
    without reaching the browser consent flow."""
    import sys
    from types import ModuleType

    from shared.google_auth import GoogleCredentialsUnavailable, build_service

    creds = MagicMock()
    creds.valid = False
    creds.expired = True
    creds.refresh_token = "stale"
    creds.refresh.side_effect = RuntimeError("invalid_grant")
    flow_module = ModuleType("google_auth_oauthlib.flow")
    flow_module.InstalledAppFlow = MagicMock(name="InstalledAppFlow")
    with (
        patch("shared.google_auth._load_token", return_value=creds),
        patch("shared.google_auth._save_token") as save,
        patch("shared.google_auth.discovery_build") as build,
        patch.dict(sys.modules, {"google_auth_oauthlib.flow": flow_module}),
    ):
        with pytest.raises(GoogleCredentialsUnavailable):
            build_service("drive", "v3", [_DRIVE_RO], interactive=False)
    creds.refresh.assert_called_once()
    save.assert_not_called()
    build.assert_not_called()
    flow_module.InstalledAppFlow.from_client_config.assert_not_called()


@pytest.mark.parametrize(
    ("module", "builder"),
    [
        ("agents.gmail_sync", "_get_gmail_service"),
        ("agents.gcalendar_sync", "_get_calendar_service"),
        ("agents.gdrive_sync", "_get_drive_service"),
        ("agents.youtube_sync", "_get_youtube_service"),
    ],
)
def test_each_sync_daemon_refuses_instead_of_parking_on_consent(module: str, builder: str):
    """Review finding at a9c30e854 (major): caller behaviour was checked as source text. This
    EXECUTES each daemon's service builder with no token; it must refuse with the named remedy
    and never reach the browser consent flow that would park a systemd unit forever."""
    import importlib
    import sys
    from types import ModuleType

    from shared.google_auth import GoogleCredentialsUnavailable

    flow_module = ModuleType("google_auth_oauthlib.flow")
    flow_module.InstalledAppFlow = MagicMock(name="InstalledAppFlow")
    target = importlib.import_module(module)
    with (
        patch("shared.google_auth._load_token", return_value=None),
        patch("shared.google_auth.discovery_build") as build,
        patch.dict(sys.modules, {"google_auth_oauthlib.flow": flow_module}),
    ):
        with pytest.raises(GoogleCredentialsUnavailable, match="Next action"):
            getattr(target, builder)()
    build.assert_not_called()
    flow_module.InstalledAppFlow.from_client_config.assert_not_called()


def _recovery_command_argv(message: str) -> list[str]:
    """Extract the shell-safe recovery command from an auth refusal."""
    marker = "Next action: mint the token once, interactively, on this host: "
    return shlex.split(message.split(marker, maxsplit=1)[1])


def _refusal(pass_key: str, scopes: list[str]) -> str:
    from shared.google_auth import GoogleCredentialsUnavailable, build_service

    with patch("shared.google_auth._load_token", return_value=None):
        with pytest.raises(GoogleCredentialsUnavailable) as excinfo:
            build_service("drive", "v3", scopes, pass_key=pass_key, interactive=False)
    return str(excinfo.value)


def _main_account_consent_scopes(command: list[str]) -> list[str]:
    """The scope list passed to the shared client's interactive consent in a `python -c` remedy."""
    import ast

    assert command[:4] == ["uv", "run", "python", "-c"], command
    tree = ast.parse(command[4])
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "get_google_credentials"
    ]
    assert len(calls) == 1, command[4]
    call = calls[0]
    # The default pass key is google/token and the default is interactive: the remedy must not
    # override either, or it would not be the main-account consent it claims to be.
    assert not call.keywords, command[4]
    return ast.literal_eval(call.args[0])


def test_main_token_recovery_never_routes_through_the_sub_channel_mint_script():
    """Review finding at a9c30e854 (major): the refusal for ``google/token`` named
    ``mint-google-token.py``, whose prompt says to pick the YouTube SUB-CHANNEL and whose
    docstring promises it never touches ``google/token``. Following the instruction would
    replace the main-account credential shared by gmail, calendar and drive."""
    command = _recovery_command_argv(_refusal("google/token", [_DRIVE_RO]))
    assert "scripts/mint-google-token.py" not in command
    assert "--pass-key" not in command


def test_main_token_recovery_requests_the_interactive_consent_union():
    """The remedy for ``google/token`` is the shared client's own consent flow, with requested
    scopes beyond ``ALL_SCOPES`` retained, in the flow's deterministic order."""
    from shared.google_auth import ALL_SCOPES

    requested_scopes = [_DRIVE_RO, "https://www.googleapis.com/auth/example.extra"]
    command = _recovery_command_argv(_refusal("google/token", requested_scopes))
    assert _main_account_consent_scopes(command) == list(
        dict.fromkeys([*requested_scopes, *ALL_SCOPES])
    )


def test_scoped_token_recovery_keeps_the_sub_channel_mint_script():
    """A sub-channel key is what ``mint-google-token.py`` exists for, so its remedy is unchanged."""
    from shared.google_auth import ALL_SCOPES, YOUTUBE_STREAMING_TOKEN_PASS_KEY

    command = _recovery_command_argv(_refusal(YOUTUBE_STREAMING_TOKEN_PASS_KEY, [_DRIVE_RO]))
    assert command[:4] == ["uv", "run", "python", "scripts/mint-google-token.py"]
    assert command[command.index("--pass-key") + 1] == YOUTUBE_STREAMING_TOKEN_PASS_KEY
    scopes_index = command.index("--scopes")
    assert command[scopes_index + 1 :] == list(dict.fromkeys([_DRIVE_RO, *ALL_SCOPES]))


def test_unattended_google_callers_use_the_shared_client_non_interactively():
    """The retired ``agents._google_auth`` parked daemons on a browser consent flow.

    Every unattended caller now goes through the shared client with the flow
    disabled, and no module under ``agents/`` may import the legacy path again.
    """
    repo = Path(__file__).resolve().parents[1]
    assert not (repo / "agents" / "_google_auth.py").exists()
    offenders = sorted(
        str(path.relative_to(repo))
        for path in (repo / "agents").rglob("*.py")
        if "_google_auth" in path.read_text(encoding="utf-8")
    )
    assert offenders == []
    unattended = [
        "agents/gmail_sync.py",
        "agents/gcalendar_sync.py",
        "agents/gdrive_sync.py",
        "agents/youtube_sync.py",
        "agents/hapax_daimonion/tools.py",
    ]
    for rel in unattended:
        text = (repo / rel).read_text(encoding="utf-8")
        assert "from shared.google_auth import build_service" in text, rel
        calls = re.findall(r"build_service\([^)]*\)", text)
        assert calls, rel
        for call in calls:
            assert "interactive=False" in call, (rel, call)


def test_load_token_reads_the_secret_and_absent_is_none(monkeypatch):
    import json

    import shared.google_auth as ga

    payload = {
        "token": "t",
        "refresh_token": "r",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "c",
        "client_secret": "s",
        "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
    }
    monkeypatch.setattr(
        ga, "get_secret", lambda name, *, env=None, required=True: json.dumps(payload)
    )
    creds = ga._load_token(payload["scopes"], pass_key="google/token")
    assert creds is not None
    assert creds.refresh_token == "r"

    monkeypatch.setattr(ga, "get_secret", lambda name, *, env=None, required=True: None)
    assert ga._load_token(payload["scopes"], pass_key="google/token") is None


def test_save_token_puts_the_six_fields_as_utf8_json(monkeypatch):
    import json
    from types import SimpleNamespace

    import shared.google_auth as ga

    saved: dict[str, bytes] = {}
    monkeypatch.setattr(ga, "put_secret", lambda name, value: saved.__setitem__(name, value))
    creds = SimpleNamespace(
        token="t", refresh_token="r", token_uri="u", client_id="c", client_secret="s", scopes=["a"]
    )
    ga._save_token(creds, pass_key="google/token-youtube-streaming")
    assert list(saved) == ["google/token-youtube-streaming"]
    assert json.loads(saved["google/token-youtube-streaming"].decode("utf-8")) == {
        "token": "t",
        "refresh_token": "r",
        "token_uri": "u",
        "client_id": "c",
        "client_secret": "s",
        "scopes": ["a"],
    }
