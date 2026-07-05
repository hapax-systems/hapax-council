"""Tests for the cc-dispatch CLI (the friendly one-command capability surface)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import SimpleNamespace

import pytest

_CC_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cc-dispatch"

# Full registry set (matches the shared test fixture) so --list output is not
# silently narrower than the real registry exposes.
VALID = frozenset(
    {
        "codex.headless.full",
        "codex.headless.spark",
        "claude.headless.full",
        "claude.headless.opus",
        "claude.headless.sonnet",
        "claude.headless.haiku",
        "claude.interactive.full",
        "api.headless.provider_gateway",
        "api.headless.api_frontier",
        "vibe.headless.full",
        "glmcp.review.direct",
        "local_tool.local.worker",
    }
)
ACTIVE = VALID


def _load():
    loader = SourceFileLoader("cc_dispatch_cli", str(_CC_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _patch_valid(monkeypatch, mod):
    monkeypatch.setattr(mod, "load_valid_route_ids", lambda *a, **k: VALID)
    monkeypatch.setattr(mod, "load_active_route_ids", lambda *a, **k: ACTIVE)


def test_list(monkeypatch, capsys) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    assert mod.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "codex" in out and "codex.headless.full" in out
    assert "agy" not in out and "antigrav.interactive.full" not in out
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


def test_deprecated_antigrav_alias_fails_closed(monkeypatch, capsys) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    assert mod.main(["agy", "cc-task-x"]) == 2
    err = capsys.readouterr().err
    assert "cannot dispatch 'agy'" in err and "deprecated" in err.lower()
    assert "measured agy supply leaves" in err


def test_literal_antigrav_capability_fails_with_retired_next_action(monkeypatch, capsys) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    assert mod.main(["antigrav", "cc-task-x"]) == 2
    err = capsys.readouterr().err
    assert "cannot dispatch 'antigrav'" in err
    assert "deprecated/excised" in err
    assert "measured agy supply leaves" in err

    assert mod.main(["antigravity", "cc-task-x"]) == 2
    err = capsys.readouterr().err
    assert "cannot dispatch 'antigravity'" in err
    assert "deprecated/excised" in err
    assert "measured agy supply leaves" in err

    assert mod.main(["antigrav.interactive.full", "cc-task-x"]) == 2
    err = capsys.readouterr().err
    assert "cannot dispatch 'antigrav.interactive.full'" in err
    assert "deprecated/excised" in err


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
    assert mod.main(["codex", "cc-task-x", "--lane", "cx-red"]) == 0
    cmd = calls[0]
    assert cmd[:1] == ["DISPATCH"]
    assert "--task" in cmd and "cc-task-x" in cmd
    assert cmd[cmd.index("--lane") + 1] == "cx-red"  # dispatcher requires --task AND --lane
    assert cmd[cmd.index("--platform") + 1] == "codex"
    assert cmd[cmd.index("--mode") + 1] == "headless"
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
    assert mod.main(["codex", "cc-task-x", "--lane", "cx-red", "--launch"]) == 0
    assert "--launch" in calls[0]


def test_safe_flags_forwarded(monkeypatch) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    calls: list[list[str]] = []
    monkeypatch.setattr(mod, "dispatcher_cmd", lambda: ["DISPATCH"])
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda cmd, *a, **k: (calls.append(cmd), SimpleNamespace(returncode=0))[1],
    )
    argv = [
        "codex",
        "cc-task-x",
        "--lane",
        "cx-red",
        "--mq-message-id",
        "M1",
        "--idempotency-key",
        "K1",
    ]
    assert mod.main(argv) == 0
    cmd = calls[0]
    assert cmd[cmd.index("--mq-message-id") + 1] == "M1"
    assert cmd[cmd.index("--idempotency-key") + 1] == "K1"


def test_reserved_flags_rejected(monkeypatch) -> None:
    # CRITICAL: route-defining / receipt flags must NOT be operator-overridable.
    # parse_args rejects them (unknown to cc-dispatch) -> SystemExit, never forwarded.
    mod = _load()
    _patch_valid(monkeypatch, mod)
    for bad in (
        ["--platform", "claude"],
        ["--no-receipt"],
        ["--task", "other"],
        ["--skip-worktree-check"],
    ):
        with pytest.raises(SystemExit):
            mod.main(["codex", "cc-task-x", "--lane", "cx-red", *bad])


def test_missing_args_errors(monkeypatch) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    with pytest.raises(SystemExit):
        mod.main([])


def test_missing_lane_errors(monkeypatch) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    with pytest.raises(SystemExit):
        mod.main(["codex", "cc-task-x"])  # no --lane -> the dispatcher would reject; we fail early


def test_unrouted_fails_closed(monkeypatch, capsys) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    assert mod.main(["fugu", "cc-task-x"]) == 2
    err = capsys.readouterr().err
    assert "cannot dispatch 'fugu'" in err and "P2" in err


def test_dispatcher_cmd_uses_repo_sibling() -> None:
    # Trust ONLY the in-repo sibling — never env/PATH (those are bypass vectors).
    mod = _load()
    cmd = mod.dispatcher_cmd()
    assert cmd[0] == mod.sys.executable
    assert cmd[1] == str(mod._HERE / "hapax-methodology-dispatch")


def test_dispatcher_cmd_ignores_hostile_env(monkeypatch) -> None:
    # CRITICAL fix: a hostile env override must NOT redirect the governed dispatcher.
    mod = _load()
    monkeypatch.setenv("HAPAX_METHODOLOGY_DISPATCH_BIN", "/bin/true")
    cmd = mod.dispatcher_cmd()
    assert cmd != ["/bin/true"]
    assert cmd[1] == str(mod._HERE / "hapax-methodology-dispatch")


def test_dispatcher_cmd_missing_sibling_exits(monkeypatch, tmp_path) -> None:
    mod = _load()
    monkeypatch.setattr(mod, "_HERE", tmp_path)  # no sibling dispatcher here
    with pytest.raises(SystemExit) as exc:
        mod.dispatcher_cmd()
    assert exc.value.code == 3


def test_dispatch_composes_with_real_dispatcher(tmp_path) -> None:
    # Real-composition evidence (not a mock): cc-dispatch's resolved flags reach the
    # governed dispatcher's validation (no argparse rejection) and a bogus task fails
    # closed — rebuts "launch predicate only tested as mocked command construction".
    mod = _load()
    valid = mod.load_valid_route_ids()
    if not valid:  # pragma: no cover - env guard
        pytest.skip("registry unreadable")
    res = mod.resolve_capability("claude", valid_route_ids=valid)
    assert res.ok
    cmd = mod.dispatcher_cmd() + [
        "--task",
        "cc-task-DOES-NOT-EXIST-ccdispatch-selftest",
        "--lane",
        "ccdispatch-selftest",
        "--platform",
        res.platform,
        "--mode",
        res.mode,
        "--profile",
        res.profile,
    ]
    env = {**os.environ, "HAPAX_ORCHESTRATION_LEDGER_DIR": str(tmp_path)}
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - env guard
        pytest.skip(f"dispatcher not runnable: {exc}")
    combined = proc.stdout + proc.stderr
    assert "unrecognized arguments" not in combined  # flags accepted by the real dispatcher
    assert "are required" not in combined  # --task/--lane satisfied
    assert proc.returncode != 0  # a bogus task must NOT falsely succeed


def test_print_list_empty_registry_returns_1(monkeypatch, capsys) -> None:
    mod = _load()
    monkeypatch.setattr(mod, "load_active_route_ids", lambda *a, **k: frozenset())
    assert mod.main(["--list"]) == 1
    assert "no launchable capabilities" in capsys.readouterr().err


def test_utilization_warns_on_missing_ledger(monkeypatch, capsys) -> None:
    # MAJOR: a LATENT scorecard must not silently hide that the evidence source is absent.
    mod = _load()
    _patch_valid(monkeypatch, mod)
    monkeypatch.setattr(mod, "ledger_health", lambda *a, **k: (False, 0))
    monkeypatch.setattr(mod, "read_dispatch_ledger", lambda *a, **k: iter([]))
    assert mod.main(["--utilization"]) == 0
    err = capsys.readouterr().err
    assert "no dispatch ledger" in err and "not verified non-use" in err


def test_utilization_warns_on_corrupt_ledger(monkeypatch, capsys) -> None:
    mod = _load()
    _patch_valid(monkeypatch, mod)
    monkeypatch.setattr(mod, "ledger_health", lambda *a, **k: (True, 3))
    monkeypatch.setattr(mod, "read_dispatch_ledger", lambda *a, **k: iter([]))
    assert mod.main(["--utilization"]) == 0
    assert "corrupt ledger row" in capsys.readouterr().err


def test_utilization_unreadable_registry_returns_1(monkeypatch, capsys) -> None:
    # MAJOR: utilization must NOT report 0/0 against an unread SSOT.
    mod = _load()
    monkeypatch.setattr(mod, "load_valid_route_ids", lambda *a, **k: frozenset())
    monkeypatch.setattr(mod, "registry_error", lambda *a, **k: "registry unreadable: boom")
    assert mod.main(["--utilization"]) == 1
    err = capsys.readouterr().err
    assert "cannot read the route registry" in err and "boom" in err


def test_dispatch_unreadable_registry_returns_1(monkeypatch, capsys) -> None:
    mod = _load()
    monkeypatch.setattr(mod, "load_valid_route_ids", lambda *a, **k: frozenset())
    monkeypatch.setattr(mod, "registry_error", lambda *a, **k: "registry malformed JSON: x")
    assert mod.main(["codex", "cc-task-x", "--lane", "cx-red"]) == 1
    assert "cannot read the route registry" in capsys.readouterr().err
