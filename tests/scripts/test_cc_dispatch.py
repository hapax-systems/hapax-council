"""Tests for the cc-dispatch CLI (the friendly one-command capability surface)."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest

_CC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cc-dispatch"

VALID = frozenset(
    {
        "antigrav.interactive.full",
        "codex.headless.full",
        "claude.headless.full",
        "claude.headless.opus",
        "vibe.headless.full",
        "glmcp.review.direct",
    }
)


def _load():
    loader = SourceFileLoader("cc_dispatch_cli", str(_CC_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _patch_valid(monkeypatch, mod):
    monkeypatch.setattr(mod, "load_valid_route_ids", lambda *a, **k: VALID)


def test_list(monkeypatch, capsys) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    assert mod.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "agy" in out and "antigrav.interactive.full" in out
    assert "glmcp-review" not in out  # non-spawnable excluded


def test_utilization(monkeypatch, capsys) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    monkeypatch.setattr(
        mod,
        "read_dispatch_ledger",
        lambda *a, **k: iter(
            [{"platform": "codex", "mode": "headless", "profile": "full", "launched": True}]
        ),
    )
    assert mod.main(["--utilization"]) == 0
    out = capsys.readouterr().out
    assert "ACTIVE" in out and "LATENT" in out
    assert "codex.headless.full" in out


def test_unrouted_fails_closed(monkeypatch, capsys) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    assert mod.main(["fugu", "cc-task-x"]) == 2
    err = capsys.readouterr().err
    assert "cannot dispatch 'fugu'" in err and "P2" in err


def test_unknown_fails_closed(monkeypatch, capsys) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    assert mod.main(["bogus", "cc-task-x"]) == 2
    assert "unknown capability" in capsys.readouterr().err


def test_dispatch_validate_builds_correct_cmd(monkeypatch) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    calls: list[list[str]] = []
    monkeypatch.setattr(mod, "dispatcher_cmd", lambda: ["DISPATCH"])
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda cmd, *a, **k: (calls.append(cmd), SimpleNamespace(returncode=0))[1],
    )
    assert mod.main(["agy", "cc-task-x", "--lane", "agy-1"]) == 0
    cmd = calls[0]
    assert cmd[:1] == ["DISPATCH"]
    assert "--task" in cmd and "cc-task-x" in cmd
    assert cmd[cmd.index("--lane") + 1] == "agy-1"  # dispatcher requires --task AND --lane
    assert cmd[cmd.index("--platform") + 1] == "antigrav"
    assert cmd[cmd.index("--mode") + 1] == "interactive"
    assert cmd[cmd.index("--profile") + 1] == "full"
    assert "--launch" not in cmd  # validate-only by default


def test_dispatch_launch_passes_launch_flag(monkeypatch) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    calls: list[list[str]] = []
    monkeypatch.setattr(mod, "dispatcher_cmd", lambda: ["DISPATCH"])
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda cmd, *a, **k: (calls.append(cmd), SimpleNamespace(returncode=0))[1],
    )
    assert mod.main(["agy", "cc-task-x", "--lane", "agy-1", "--launch"]) == 0
    assert "--launch" in calls[0]


def test_dispatch_passthrough_extra_flags(monkeypatch) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    calls: list[list[str]] = []
    monkeypatch.setattr(mod, "dispatcher_cmd", lambda: ["DISPATCH"])
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda cmd, *a, **k: (calls.append(cmd), SimpleNamespace(returncode=0))[1],
    )
    assert mod.main(["agy", "cc-task-x", "--lane", "agy-1", "--mq-message-id", "M1"]) == 0
    assert "--mq-message-id" in calls[0] and "M1" in calls[0]


def test_missing_args_errors(monkeypatch) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    with pytest.raises(SystemExit):
        mod.main([])


def test_missing_lane_errors(monkeypatch) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    with pytest.raises(SystemExit):
        mod.main(["agy", "cc-task-x"])  # no --lane -> the dispatcher would reject; we fail early


def test_dispatcher_cmd_env_override(monkeypatch) -> None:
    mod = _load()
    monkeypatch.setenv("HAPAX_METHODOLOGY_DISPATCH_BIN", "/opt/x/hapax-methodology-dispatch")
    assert mod.dispatcher_cmd() == ["/opt/x/hapax-methodology-dispatch"]


def test_dispatcher_cmd_path_found(monkeypatch) -> None:
    mod = _load()
    monkeypatch.delenv("HAPAX_METHODOLOGY_DISPATCH_BIN", raising=False)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: "/usr/bin/hapax-methodology-dispatch")
    assert mod.dispatcher_cmd() == ["/usr/bin/hapax-methodology-dispatch"]


def test_dispatcher_cmd_sibling_fallback(monkeypatch) -> None:
    mod = _load()
    monkeypatch.delenv("HAPAX_METHODOLOGY_DISPATCH_BIN", raising=False)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    cmd = mod.dispatcher_cmd()  # the real sibling scripts/hapax-methodology-dispatch exists
    assert cmd[0] == mod.sys.executable
    assert cmd[1].endswith("hapax-methodology-dispatch")


def test_dispatcher_cmd_not_found_exits(monkeypatch, tmp_path) -> None:
    mod = _load()
    monkeypatch.delenv("HAPAX_METHODOLOGY_DISPATCH_BIN", raising=False)
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    monkeypatch.setattr(mod, "_HERE", tmp_path)  # no sibling dispatcher here
    with pytest.raises(SystemExit) as exc:
        mod.dispatcher_cmd()
    assert exc.value.code == 3


def test_print_list_empty_registry_returns_1(monkeypatch, capsys) -> None:
    mod = _load()
    monkeypatch.setattr(mod, "load_valid_route_ids", lambda *a, **k: frozenset())
    assert mod.main(["--list"]) == 1
    assert "no launchable capabilities" in capsys.readouterr().err
