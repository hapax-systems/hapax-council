"""The prose half of the pass sweep: what the estate SAYS about where secrets live.

`tests/test_no_pass_invocations.py` pins invocations and deliberately reads code, not prose.
That left a class it cannot see: a string the operator reads at runtime that still names the
pass store. PR #4680 merged with ~15 of them, two of which reported a token write to a store
that never received it (`agents/gdrive_sync.py`, `agents/youtube_sync.py`).

This gate reads the same walk with the same prose-stripping, so comments and docstrings stay
free to quote the ruling ("never from pass") — what it pins is string literals, unit
`Description=` lines and yaml values: the text a process can emit or a status line can show.

It also pins the claims the sweep made while replacing those strings, because a next action
that names a secret the code never reads is the same defect with a newer noun.
"""

from __future__ import annotations

import re

import pytest

from tests.test_no_pass_invocations import _code, _runtime_files, _violations

#: Files whose literals name pass AS the thing they refuse, scrub, or deny — never as custody.
CONTROLS: dict[str, str] = {
    "config/ci/self-hosted-runner-experiment.yaml": "an isolation boundary: the runner is given NO pass store",
}

#: The last arm is lowercase-only and same-line: shell gates print "... in\nPASS" and test
#: verdicts read "result in PASS", neither of which is about the store.
PROSE = re.compile(
    r"""(?xi)
      (?<![\w-])pass[\s-]store\b
    | (?<![\w-])pass[\s-]entr(?:y|ies)\b
    | (?<![\w-])pass[\s-](?:backed|based)\b
    | \b(?:in|from|via)[ \t]+(?-i:pass)\b(?![ \t-]*\d)
    """,
)


def test_no_operator_facing_string_still_names_the_pass_store() -> None:
    files = _runtime_files()
    assert len(files) > 500, "the walk found too few files to be the runtime tree"
    violations = _violations(files, PROSE, CONTROLS)
    assert violations == [], "operator-facing text still names pass at:\n  " + "\n  ".join(
        violations
    )


def test_every_declared_control_still_exists_and_still_names_pass() -> None:
    for relative in CONTROLS:
        code = _code(relative)
        assert code is not None, relative
        assert PROSE.search(code), f"{relative} no longer names pass; drop it from CONTROLS"


@pytest.mark.parametrize(
    "sample",
    [
        'print("Token saved to pass store (gdrive/token).")',
        'log.error("omg.lol client disabled (no API key in pass store)")',
        'reason="Liberapay 401; password rotated? Re-insert via pass and restart."',
        '"store live credentials in pass entries"',
        '"could not build Gmail service from pass-backed credentials"',
        "Description=Hapax credential watch — snapshot pass entry names",
        '"belong only in the operator\'s private vault/pass store."',
        '"or store in pass as langfuse/public-key"',
        '"(hapax-secrets.service from pass `zenodo/api-token`)"',
    ],
)
def test_the_gate_sees_each_prose_shape(sample: str) -> None:
    assert PROSE.search(sample), sample


@pytest.mark.parametrize(
    "sample",
    [
        '"Single-pass entry for the daemon"',
        '"no bypass paths"',
        '"flagged in pass-1 audit"',
        '"rendered in pass 2 of the compositor"',
        'check "deny hook installed" "PASS"\necho "result in\nPASS"',
        '"all gates result in PASS"',
        'GateState = Literal["pass", "fail"]',
        '"--pass-key google/token"',
        "pass_entries: list[str]",
        '"callers pass their own scopes"',
        '"Token present in the FileStore (google/token)."',
    ],
)
def test_the_gate_ignores_each_known_false_positive(sample: str) -> None:
    assert not PROSE.search(sample), sample


# ── The claims the sweep made in place of the old strings ────────────────────


@pytest.mark.parametrize("present", [True, False])
def test_token_custody_line_claims_only_what_it_checked(
    monkeypatch: pytest.MonkeyPatch, present: bool
) -> None:
    import agents._google_auth as google_auth

    asked: list[str] = []

    def fake_has_secret(name: str) -> bool:
        asked.append(name)
        return present

    monkeypatch.setattr(google_auth, "has_secret", fake_has_secret)

    line = google_auth.token_custody_line()

    assert asked == [google_auth.TOKEN_PASS_KEY]
    assert google_auth.TOKEN_PASS_KEY in line
    assert "saved" not in line.lower().replace("save failed", "")
    assert not PROSE.search(line)
    if present:
        assert line.startswith("Token present in the FileStore")
    else:
        assert "NOT in the FileStore" in line
        assert "Next action:" in line


class _Call:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def execute(self) -> dict:
        return self._payload


class _DriveService:
    def about(self) -> _DriveService:
        return self

    def get(self, **_: object) -> _Call:
        return _Call({"user": {"emailAddress": "operator@example.invalid"}})


class _YouTubeService:
    def channels(self) -> _YouTubeService:
        return self

    def list(self, **_: object) -> _Call:
        return _Call({"items": []})


@pytest.mark.parametrize("present", [True, False])
def test_gdrive_run_auth_prints_the_checked_custody_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], present: bool
) -> None:
    import agents._google_auth as google_auth
    import agents.gdrive_sync as gdrive_sync

    monkeypatch.setattr(google_auth, "has_secret", lambda _name: present)
    monkeypatch.setattr(gdrive_sync, "_get_drive_service", _DriveService)

    gdrive_sync.run_auth()

    out = capsys.readouterr().out
    assert google_auth.token_custody_line() in out
    assert ("NOT in the FileStore" in out) is (not present)
    assert not PROSE.search(out)


@pytest.mark.parametrize("present", [True, False])
def test_youtube_run_auth_prints_the_checked_custody_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], present: bool
) -> None:
    import agents._google_auth as google_auth
    import agents.youtube_sync as youtube_sync

    monkeypatch.setattr(google_auth, "has_secret", lambda _name: present)
    monkeypatch.setattr(youtube_sync, "_get_youtube_service", _YouTubeService)

    youtube_sync.run_auth()

    out = capsys.readouterr().out
    assert google_auth.token_custody_line() in out
    assert ("NOT in the FileStore" in out) is (not present)
    assert not PROSE.search(out)


def test_langfuse_next_action_names_the_secrets_the_code_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agents.langfuse_sync as langfuse_sync

    requested: list[str] = []

    def fake_get_credential(_env_var: str, secret_name: str) -> str:
        requested.append(secret_name)
        return ""

    monkeypatch.setattr(langfuse_sync, "_get_credential", fake_get_credential)

    with pytest.raises(RuntimeError) as excinfo:
        langfuse_sync._langfuse_auth_header()

    assert len(requested) == 2
    for name in requested:
        assert name in str(excinfo.value), f"the next action never names {name}"
    assert not PROSE.search(str(excinfo.value))


def test_tavily_next_action_names_a_secret_the_loader_reads() -> None:
    import shared.tavily_client as tavily_client

    assert tavily_client.SECRET_NAMES[0] in tavily_client.NO_API_KEY_MESSAGE
    assert "Next action:" in tavily_client.NO_API_KEY_MESSAGE
    assert not PROSE.search(tavily_client.NO_API_KEY_MESSAGE)
