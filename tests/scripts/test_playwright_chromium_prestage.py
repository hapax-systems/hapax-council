"""Tests for the governed Playwright Chromium pre-stage helper."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hapax-playwright-chromium-prestage"


def _load():
    loader = importlib.machinery.SourceFileLoader("playwright_chromium_prestage_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


def test_main_stages_chromium_under_governed_browser_root(tmp_path, monkeypatch, capsys):
    mod = _load()
    activation = tmp_path / "activation"
    activation.mkdir()
    browser_root = tmp_path / "source-activation" / "playwright-browsers"
    calls = []
    monkeypatch.setenv("HAPAX_RECHECK_ACTIVATION", str(activation))
    monkeypatch.setenv("HAPAX_RECHECK_PLAYWRIGHT_BROWSERS", str(browser_root))

    def fake_run(cmd, *, cwd, env, check):
        calls.append((cmd, cwd, env["PLAYWRIGHT_BROWSERS_PATH"], check))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mod,
        "_staged_chromium_executable",
        lambda root: root / "chromium-1/chrome-linux64/chrome",
    )

    assert mod.main() == 0

    assert calls == [
        (
            ["uv", "run", "python", "-m", "playwright", "install", "chromium"],
            activation,
            str(browser_root),
            True,
        )
    ]
    assert "OK staged Chromium:" in capsys.readouterr().out


def test_main_reports_next_action_on_playwright_install_failure(tmp_path, monkeypatch, capsys):
    mod = _load()
    activation = tmp_path / "activation"
    activation.mkdir()
    browser_root = tmp_path / "browsers"
    monkeypatch.setenv("HAPAX_RECHECK_ACTIVATION", str(activation))
    monkeypatch.setenv("HAPAX_RECHECK_PLAYWRIGHT_BROWSERS", str(browser_root))

    def fake_run(cmd, **_kwargs):
        raise subprocess.CalledProcessError(7, cmd)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.main() == 7

    err = capsys.readouterr().err
    assert "FAIL playwright chromium install failed rc=7" in err
    assert "next:" in err
    assert str(browser_root) in err
    assert str(activation) in err


def test_main_reports_next_action_when_activation_dir_is_missing(tmp_path, monkeypatch, capsys):
    mod = _load()
    activation = tmp_path / "missing-activation"
    browser_root = tmp_path / "browsers"
    monkeypatch.setenv("HAPAX_RECHECK_ACTIVATION", str(activation))
    monkeypatch.setenv("HAPAX_RECHECK_PLAYWRIGHT_BROWSERS", str(browser_root))

    assert mod.main() == 1

    err = capsys.readouterr().err
    assert "FAIL playwright chromium install could not start:" in err
    assert "next:" in err
    assert str(browser_root) in err
    assert str(activation) in err


def test_main_reports_next_action_when_uv_executable_is_missing(tmp_path, monkeypatch, capsys):
    mod = _load()
    activation = tmp_path / "activation"
    activation.mkdir()
    browser_root = tmp_path / "browsers"
    monkeypatch.setenv("HAPAX_RECHECK_ACTIVATION", str(activation))
    monkeypatch.setenv("HAPAX_RECHECK_PLAYWRIGHT_BROWSERS", str(browser_root))

    def fake_run(_cmd, **_kwargs):
        raise FileNotFoundError("uv")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.main() == 1

    err = capsys.readouterr().err
    assert "FAIL playwright chromium install could not start:" in err
    assert "next:" in err
    assert str(browser_root) in err
    assert str(activation) in err


def test_main_reports_next_action_when_browser_root_cannot_be_created(
    tmp_path, monkeypatch, capsys
):
    mod = _load()
    activation = tmp_path / "activation"
    activation.mkdir()
    browser_root = tmp_path / "browsers"
    browser_root.write_text("not a directory\n")
    monkeypatch.setenv("HAPAX_RECHECK_ACTIVATION", str(activation))
    monkeypatch.setenv("HAPAX_RECHECK_PLAYWRIGHT_BROWSERS", str(browser_root))

    assert mod.main() == 1

    err = capsys.readouterr().err
    assert "FAIL playwright chromium install could not start:" in err
    assert "next:" in err
    assert str(browser_root) in err
    assert str(activation) in err


def test_main_fails_with_next_action_when_install_leaves_no_executable(
    tmp_path, monkeypatch, capsys
):
    mod = _load()
    activation = tmp_path / "activation"
    activation.mkdir()
    browser_root = tmp_path / "browsers"
    monkeypatch.setenv("HAPAX_RECHECK_ACTIVATION", str(activation))
    monkeypatch.setenv("HAPAX_RECHECK_PLAYWRIGHT_BROWSERS", str(browser_root))
    monkeypatch.setattr(mod.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mod, "_staged_chromium_executable", lambda _root: None)

    assert mod.main() == 1

    err = capsys.readouterr().err
    assert "FAIL no executable Chromium" in err
    assert "next:" in err
