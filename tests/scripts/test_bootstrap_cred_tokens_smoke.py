"""Smoke tests for ``scripts/bootstrap_cred_tokens.py``.

Imports + CLI plumbing only — actual browser flow requires an operator-
interactive Playwright session and lives outside CI scope. The token
values flow straight into the FileStore, so by design the script can't be
end-to-end tested without compromising the security model.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/bootstrap_cred_tokens.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("bootstrap_cred_tokens", _SCRIPT)
    assert spec is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules["bootstrap_cred_tokens"] = m
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def test_keys_registry_covers_six_keys(mod):
    # entries across 5 services (IA + Bluesky have 2 each)
    flat = [k for ks in mod.KEYS.values() for k in ks]
    assert sorted(flat) == [
        "bluesky/operator-app-password",
        "bluesky/operator-did",
        "ia/access-key",
        "ia/secret-key",
        "osf/api-token",
        "philarchive/session-cookie",
        "zenodo/api-token",
    ]


def test_service_bootstrappers_match_keys_registry(mod):
    assert set(mod.SERVICE_BOOTSTRAPPERS) == set(mod.KEYS)


def test_philarchive_cookie_domain_uses_hostname_boundary(mod):
    assert mod._is_philarchive_cookie_domain("philarchive.org")
    assert mod._is_philarchive_cookie_domain(".philarchive.org")
    assert not mod._is_philarchive_cookie_domain("evilphilarchive.org")
    assert not mod._is_philarchive_cookie_domain("philarchive.org.evil.test")


def test_secret_present_is_false_for_an_unknown_name(mod, tmp_path, monkeypatch):
    # A throwaway FileStore root: presence is probed there, never in the operator's store.
    monkeypatch.setenv("REINS_SECRET_STORE", str(tmp_path / "secrets"))
    assert mod.secret_present("hapax-test/sentinel-never-set") is False


def test_main_help_runs(mod, capsys):
    # argparse exits with SystemExit(0) on --help; surface that gracefully
    with pytest.raises(SystemExit) as excinfo:
        mod.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--only" in out
    assert "--dry-run" in out
    assert "--force" in out


def test_store_secret_never_echoes_the_token(mod, monkeypatch, capsys):
    # The contract: the token bytes reach the FileStore writer as bytes and
    # never echo to our stdout/stderr.
    sentinel = b"super-secret-token-do-not-print"
    seen: dict[str, bytes] = {}

    monkeypatch.setattr(mod, "put_secret", lambda key, value: seen.__setitem__(key, value))
    mod.store_secret("hapax-test/sentinel", sentinel)
    assert seen == {"hapax-test/sentinel": sentinel}
    captured = capsys.readouterr()
    assert sentinel.decode() not in captured.out
    assert sentinel.decode() not in captured.err
