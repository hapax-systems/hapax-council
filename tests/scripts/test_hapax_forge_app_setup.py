"""O2 setup script: the manifest form and the one-hour code conversion.

The conversion response carries the App's private key. The unsafe case: the key goes
anywhere except the stdin of ``systemd-creds encrypt`` into the root credstore. It must
never reach argv, the FileStore, stdout or stderr, or a file. It must not be written at
all when the App is not owned by the org, when the state does not match, or when a
credential already exists and no rotation was asked for.
"""

from __future__ import annotations

import html
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-forge-app-setup"
MANIFEST = REPO_ROOT / "docs" / "runbooks" / "forge-machine-identity-app-manifest.json"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nSENTINEL-KEY-MATERIAL\n-----END RSA PRIVATE KEY-----\n"  # pragma: allowlist secret
STATE = "s" * 32


def _load() -> ModuleType:
    from importlib.machinery import SourceFileLoader

    loader = SourceFileLoader("hapax_forge_app_setup", str(SCRIPT))
    spec = importlib.util.spec_from_loader("hapax_forge_app_setup", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _conversion(owner: str = "hapax-systems", owner_type: str = "Organization") -> dict[str, Any]:
    return {
        "id": 424242,
        "slug": "hapax-forge",
        "client_id": "Iv23client",
        "owner": {"login": owner, "type": owner_type},
        "pem": PEM,
        "webhook_secret": None,
        "client_secret": "cs-SENTINEL",  # pragma: allowlist secret
    }


class _Fakes:
    def __init__(self, conversion: dict[str, Any], *, exists: bool = False, encrypt_rc: int = 0):
        self.conversion = conversion
        self.exists = exists
        self.encrypt_rc = encrypt_rc
        self.posts: list[str] = []
        self.gets: list[str] = []
        self.runs: list[tuple[list[str], str | None]] = []
        self.metadata: list[dict[str, Any]] = []

    def post(self, url: str) -> dict[str, Any]:
        self.posts.append(url)
        return self.conversion

    def get(self, url: str) -> dict[str, Any]:
        self.gets.append(url)
        return {"id": 987654321, "login": "hapax-forge[bot]"}

    def run(self, argv: list[str], stdin: str | None = None) -> int:
        self.runs.append((list(argv), stdin))
        if argv[:2] == ["sudo", "test"]:
            return 0 if self.exists else 1
        return self.encrypt_rc

    def put(self, metadata: dict[str, Any]) -> None:
        self.metadata.append(metadata)

    def encrypt_calls(self) -> list[tuple[list[str], str | None]]:
        return [call for call in self.runs if "systemd-creds" in call[0]]


def _convert(module: ModuleType, fakes: _Fakes, **kwargs: Any) -> dict[str, Any]:
    return module.convert(
        "code123",
        kwargs.pop("state", STATE),
        expected_state=STATE,
        http_post=fakes.post,
        http_get=fakes.get,
        run=fakes.run,
        put_metadata=fakes.put,
        **kwargs,
    )


class TestConvert:
    def test_pem_reaches_only_the_encrypt_stdin(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        module = _load()
        fakes = _Fakes(_conversion())

        metadata = _convert(module, fakes)

        encrypts = fakes.encrypt_calls()
        assert len(encrypts) == 1
        argv, stdin = encrypts[0]
        assert stdin == PEM
        assert argv[-2:] == ["-", module.CREDSTORE_TARGET]
        assert "--name=forge-app-key" in argv
        for other_argv, other_stdin in fakes.runs:
            assert "SENTINEL" not in " ".join(other_argv)
            if other_argv is not argv:
                assert other_stdin is None or "SENTINEL" not in other_stdin
        assert "SENTINEL" not in json.dumps(fakes.metadata)
        assert "SENTINEL" not in json.dumps(metadata)
        out = capsys.readouterr()
        assert "SENTINEL" not in out.out + out.err
        assert not any(
            "SENTINEL" in p.read_text(errors="ignore") for p in tmp_path.rglob("*") if p.is_file()
        )

    def test_stores_only_non_secret_identity(self) -> None:
        module = _load()
        fakes = _Fakes(_conversion())

        _convert(module, fakes)

        assert fakes.metadata == [
            {
                "app_id": 424242,
                "client_id": "Iv23client",
                "slug": "hapax-forge",
                "owner": "hapax-systems",
                "bot_user_id": 987654321,
            }
        ]

    def test_refuses_an_app_owned_by_a_personal_account(self) -> None:
        module = _load()
        fakes = _Fakes(_conversion(owner="ryanklee", owner_type="User"))

        with pytest.raises(module.SetupRefused, match="app_not_org_owned:ryanklee"):
            _convert(module, fakes)

        assert fakes.encrypt_calls() == []
        assert fakes.metadata == []

    def test_refuses_a_state_mismatch_before_any_network_call(self) -> None:
        module = _load()
        fakes = _Fakes(_conversion())

        with pytest.raises(module.SetupRefused, match="state_mismatch"):
            _convert(module, fakes, state="t" * 32)

        assert fakes.posts == []
        assert fakes.runs == []

    def test_refuses_to_overwrite_an_existing_credential(self) -> None:
        module = _load()
        fakes = _Fakes(_conversion(), exists=True)

        with pytest.raises(module.SetupRefused, match="credential_exists"):
            _convert(module, fakes)

        assert fakes.encrypt_calls() == []
        assert fakes.metadata == []

    def test_rotation_overwrites_only_when_asked(self) -> None:
        module = _load()
        fakes = _Fakes(_conversion(), exists=True)

        _convert(module, fakes, replace=True)

        assert len(fakes.encrypt_calls()) == 1

    def test_failed_encrypt_stores_nothing(self) -> None:
        module = _load()
        fakes = _Fakes(_conversion(), encrypt_rc=1)

        with pytest.raises(module.SetupRefused, match="credential_encrypt_failed"):
            _convert(module, fakes)

        assert fakes.metadata == []

    def test_refuses_a_response_without_a_key(self) -> None:
        module = _load()
        conversion = _conversion()
        conversion.pop("pem")
        fakes = _Fakes(conversion)

        with pytest.raises(module.SetupRefused, match="conversion_malformed"):
            _convert(module, fakes)

        assert fakes.encrypt_calls() == []

    def test_refuses_to_run_as_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = _load()
        monkeypatch.setattr(module.os, "geteuid", lambda: 0)

        assert module.main(["convert", "code123", STATE, "--state-file", "/nonexistent"]) == 2


class TestForm:
    def test_form_posts_the_committed_manifest_to_the_org(self) -> None:
        module = _load()
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

        page = module.render_form(manifest, STATE)

        action = re.search(r'action="([^"]+)"', page)
        assert action is not None
        assert html.unescape(action.group(1)) == (
            f"https://github.com/organizations/hapax-systems/settings/apps/new?state={STATE}"
        )
        value = re.search(r'name="manifest" value="([^"]*)"', page)
        assert value is not None
        assert json.loads(html.unescape(value.group(1))) == manifest

    def test_form_command_writes_the_state_beside_the_page(self, tmp_path: Path) -> None:
        module = _load()
        out = tmp_path / "form.html"

        assert module.main(["form", str(out)]) == 0

        state = (tmp_path / "form.html.state").read_text(encoding="utf-8").strip()
        assert len(state) >= 32
        assert state in out.read_text(encoding="utf-8")
