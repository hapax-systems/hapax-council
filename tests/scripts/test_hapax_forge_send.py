"""hapax-forge-send smoke: the O2 runtime leg's instrument.

Run inside the forge-send credential sandbox after the operator's click, it opens one
PR on a test branch as the App's bot. The unsafe cases: it must make no network call
without the unit's credential; it must refuse a token that is expired or near expiry
before touching the repository; and it must refuse (and say so) if GitHub attributes
the commit or the PR to anyone but the bot.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-forge-send"
NOW = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
BOT = "hapax-forge[bot]"


def _load() -> ModuleType:
    loader = SourceFileLoader("hapax_forge_send", str(SCRIPT))
    spec = importlib.util.spec_from_loader("hapax_forge_send", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class _GitHub:
    """A fake GitHub that records every call, in order."""

    def __init__(
        self,
        *,
        token_expires_in: timedelta = timedelta(minutes=59),
        commit_author: str = BOT,
        pr_author: str = BOT,
    ) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.token_expires_in = token_expires_in
        self.commit_author = commit_author
        self.pr_author = pr_author

    def __call__(self, method: str, url: str, auth: str, body: Any = None) -> dict[str, Any]:
        self.calls.append((method, url.replace("https://api.github.com", ""), auth.split()[0]))
        path = url.replace("https://api.github.com", "")
        if path.endswith("/installation"):
            return {"id": 555}
        if path.endswith("/access_tokens"):
            expires = (NOW + self.token_expires_in).isoformat().replace("+00:00", "Z")
            return {"token": "ghs_test", "expires_at": expires}  # pragma: allowlist secret
        if "/git/ref/heads/" in path:
            return {"object": {"sha": "a" * 40}}
        if path.endswith("/git/refs"):
            return {"ref": body["ref"]}
        if path == "/graphql":
            return {
                "data": {
                    "createCommitOnBranch": {
                        "commit": {
                            "oid": "b" * 40,
                            "url": "https://github.com/x",
                            "author": {"user": {"login": self.commit_author}},
                        }
                    }
                }
            }
        if path.endswith("/pulls"):
            return {
                "number": 9001,
                "html_url": "https://github.com/hapax-systems/hapax-council/pull/9001",
                "user": {"login": self.pr_author},
            }
        raise AssertionError(f"unexpected call {method} {path}")


def _creds(tmp_path: Path) -> dict[str, str]:
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / "forge-app-key").write_text("unused-by-fake-signer\n", encoding="utf-8")
    return {"CREDENTIALS_DIRECTORY": str(creds)}


def _smoke(module: ModuleType, github: _GitHub, env: dict[str, str]) -> dict[str, Any]:
    return module.smoke(
        repository="hapax-systems/hapax-council",
        client_id="Iv23client",
        bot_login=BOT,
        branch="forge/o2-runtime-leg",
        env=env,
        now=NOW,
        http=github,
        sign=lambda client_id, key, now: "jwt-test",
    )


class TestSmoke:
    def test_opens_one_bot_authored_pr_with_a_narrowed_token(self, tmp_path: Path) -> None:
        module = _load()
        github = _GitHub()

        result = _smoke(module, github, _creds(tmp_path))

        assert result["pr"] == 9001
        assert result["commit_author"] == BOT
        assert result["pr_author"] == BOT
        # The JWT is used only to find the installation and mint the token; every
        # repository write uses the installation token.
        assert [c[2] for c in github.calls[:2]] == ["Bearer", "Bearer"]
        assert github.calls[0][1] == "/repos/hapax-systems/hapax-council/installation"
        assert github.calls[1][1] == "/app/installations/555/access_tokens"
        assert all(c[2] == "token" for c in github.calls[2:])

    def test_makes_no_call_without_the_units_credential(self) -> None:
        module = _load()
        github = _GitHub()

        with pytest.raises(module.ForgeIdentityRefused, match="credentials_directory_unset"):
            _smoke(module, github, {})

        assert github.calls == []

    def test_refuses_a_near_expiry_token_before_touching_the_repository(
        self, tmp_path: Path
    ) -> None:
        module = _load()
        github = _GitHub(token_expires_in=timedelta(minutes=2))

        with pytest.raises(module.ForgeIdentityRefused, match="installation_token_near_expiry"):
            _smoke(module, github, _creds(tmp_path))

        assert [c[1] for c in github.calls] == [
            "/repos/hapax-systems/hapax-council/installation",
            "/app/installations/555/access_tokens",
        ]

    def test_refuses_a_commit_not_attributed_to_the_bot(self, tmp_path: Path) -> None:
        module = _load()
        github = _GitHub(commit_author="ryanklee")

        with pytest.raises(module.ForgeIdentityRefused, match="commit_not_bot_authored:ryanklee"):
            _smoke(module, github, _creds(tmp_path))

        assert not any(c[1].endswith("/pulls") for c in github.calls)

    def test_refuses_a_pr_not_attributed_to_the_bot(self, tmp_path: Path) -> None:
        module = _load()
        github = _GitHub(pr_author="ryanklee")

        with pytest.raises(module.ForgeIdentityRefused, match="pr_not_bot_authored:ryanklee"):
            _smoke(module, github, _creds(tmp_path))

    def test_refuses_a_repository_outside_the_org(self, tmp_path: Path) -> None:
        module = _load()
        github = _GitHub()

        with pytest.raises(module.ForgeIdentityRefused, match="repository_outside_org"):
            module.smoke(
                repository="ryanklee/hapax-coord",
                client_id="Iv23client",
                bot_login=BOT,
                branch="forge/o2-runtime-leg",
                env=_creds(tmp_path),
                now=NOW,
                http=github,
                sign=lambda client_id, key, now: "jwt-test",
            )

        assert github.calls == []
