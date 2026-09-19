"""The custody line the ``--auth`` CLIs print must be checked, and must never read the value.

`agents/_google_auth.token_custody_line()` exists because "Token saved to ..." was a claim
`run_auth` could not make: `_save_token` swallows a failed write (`except SecretUnavailable:
log.warning`) and a still-valid cached token is never rewritten at all. Presence is the claim
that CAN be checked, so these pin the two branches, the two CLIs that print them, and the
property that makes the check safe to run at all — it calls `has_secret`, never `get_secret`.

The last one is the invariant with teeth: a future edit that reaches for `get_secret` to say
something more specific would pull a decrypted OAuth token into a print path.
"""

from __future__ import annotations

import pytest

from agents import _google_auth


@pytest.fixture
def no_value_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any value read from inside the custody path an immediate failure."""

    def _forbidden(*args: object, **kwargs: object) -> str:
        raise AssertionError(
            "token_custody_line read a secret VALUE; presence is checked with has_secret"
        )

    monkeypatch.setattr(_google_auth, "get_secret", _forbidden)


def test_present_branch_names_the_secret_and_does_not_read_it(
    monkeypatch: pytest.MonkeyPatch, no_value_reads: None
) -> None:
    monkeypatch.setattr(_google_auth, "has_secret", lambda name: True)

    line = _google_auth.token_custody_line()

    assert "google/token" in line
    assert "FileStore" in line
    assert "NOT" not in line


def test_absent_branch_refuses_with_a_next_action(
    monkeypatch: pytest.MonkeyPatch, no_value_reads: None
) -> None:
    monkeypatch.setattr(_google_auth, "has_secret", lambda name: False)

    line = _google_auth.token_custody_line()

    assert "NOT in the FileStore" in line
    assert "Next action:" in line
    # The next action must act on the object it names (memory
    # `an-errors-next-action-must-act-on-what-it-names`): the recheck command
    # has to address the same secret the line just said was missing.
    assert f"hapax-secret --where {_google_auth.TOKEN_PASS_KEY}" in line


def test_the_branch_is_decided_by_presence_of_this_secret(
    monkeypatch: pytest.MonkeyPatch, no_value_reads: None
) -> None:
    """Not merely "has_secret was called" — called with the name the writer uses."""
    asked: list[str] = []
    monkeypatch.setattr(_google_auth, "has_secret", lambda name: (asked.append(name), True)[1])

    _google_auth.token_custody_line()

    assert asked == [_google_auth.TOKEN_PASS_KEY] == ["google/token"]


@pytest.mark.parametrize("module_name", ["agents.gdrive_sync", "agents.youtube_sync"])
def test_run_auth_prints_the_custody_line(
    module_name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both --auth CLIs end on the checked line, not on a claim of their own."""
    import importlib

    module = importlib.import_module(module_name)
    sentinel = "CUSTODY-LINE-SENTINEL"
    monkeypatch.setattr(_google_auth, "token_custody_line", lambda: sentinel)

    class _Execute:
        def execute(self) -> dict[str, object]:
            return {"user": {"emailAddress": "operator@example.invalid"}, "items": []}

    class _Resource:
        def __getattr__(self, _name: str) -> object:
            return lambda *a, **k: self

        def execute(self) -> dict[str, object]:
            return _Execute().execute()

    if module_name == "agents.gdrive_sync":
        monkeypatch.setattr(module, "_get_drive_service", lambda: _Resource())
    else:
        monkeypatch.setattr(module, "_get_youtube_service", lambda: _Resource())

    module.run_auth()

    assert sentinel in capsys.readouterr().out
