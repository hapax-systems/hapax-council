"""Smoke tests for ``scripts/bootstrap_cred_tokens.py``.

Imports + CLI plumbing only — actual browser flow requires an operator-
interactive Playwright session and lives outside CI scope. The token
values flow through subprocess pipe, so by-design the script can't be
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
    # 6 pass-store entries across 5 services (IA + Bluesky have 2 each)
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


def test_pass_has_returns_false_for_unknown(mod):
    # Sentinel key the operator's pass-store will NEVER contain
    import shutil

    if shutil.which("pass") is None:
        pytest.skip("pass CLI not available in this environment")
    assert mod.pass_has("hapax-test/sentinel-never-set") is False


def test_main_help_runs(mod, capsys):
    # argparse exits with SystemExit(0) on --help; surface that gracefully
    with pytest.raises(SystemExit) as excinfo:
        mod.main(["--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--only" in out
    assert "--dry-run" in out
    assert "--force" in out


def test_pass_insert_no_token_in_stdout(mod, monkeypatch, capsys):
    # The contract: when pass insert succeeds (or fails), the token
    # bytes must not echo to our stdout/stderr.
    sentinel = b"super-secret-token-do-not-print"

    class FakeProc:
        returncode = 0

    def fake_run(*args, **kwargs):
        # Verify the token reaches subprocess.run via stdin, not via
        # any logged path
        assert kwargs.get("input") == sentinel
        assert kwargs.get("capture_output") is True
        return FakeProc()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    mod.pass_insert("hapax-test/sentinel", sentinel)
    captured = capsys.readouterr()
    assert sentinel.decode() not in captured.out
    assert sentinel.decode() not in captured.err
