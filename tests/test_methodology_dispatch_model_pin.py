"""Registry binding: launch_claude_headless must pin --model per profile (CEI drift guard).

Regression for the fable->opus silent-drop: the `full` profile previously inherited the
Claude Code CLI default model (fable) instead of its registry-declared model (opus).
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"


def _load() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_methodology_dispatch_modelpin", str(SCRIPT)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load()


def _run_launch(route) -> tuple[int, dict[str, str]]:
    captured: dict[str, dict[str, str]] = {}

    def fake_sliced_call(argv, env):
        captured["env"] = env
        return 0

    with (
        patch.object(mod, "_sliced_call", side_effect=fake_sliced_call),
        patch.object(mod, "lane_worktree", return_value=Path("/tmp/lane")),
        patch.object(mod, "effective_dispatch_host", return_value="appendix"),
    ):
        rc = mod.launch_claude_headless("task-x", "lane-x", "prompt", route)
    return rc, captured.get("env", {})


def test_full_profile_pins_opus_not_cli_default():
    route = mod.PLATFORM_PATHS[("claude", "headless", "full")]
    rc, env = _run_launch(route)
    assert rc == 0
    # Pass the concrete declared identity; a moving CLI alias is not identity.
    descriptor = mod.resolve_execution_descriptor("claude.headless.full")
    assert env["HAPAX_CLAUDE_MODEL"] == descriptor.model_id
    assert env["HAPAX_CLAUDE_EFFORT"] == descriptor.effort


@pytest.mark.parametrize(
    ("profile", "expected"),
    [("opus", "opus"), ("sonnet", "sonnet"), ("haiku", "haiku")],
)
def test_known_profiles_pin_their_declared_model(profile: str, expected: str):
    route = mod.PLATFORM_PATHS[("claude", "headless", profile)]
    rc, env = _run_launch(route)
    assert rc == 0
    descriptor = mod.resolve_execution_descriptor(f"claude.headless.{profile}")
    assert env["HAPAX_CLAUDE_MODEL"] == descriptor.model_id
    assert env["HAPAX_CLAUDE_EFFORT"] == descriptor.effort


def test_unknown_profile_fails_closed_without_launch():
    route = mod.PlatformPath("claude", "headless", "mystery", "launcher", "summary", True, "notes")
    rc, env = _run_launch(route)
    # Fail closed: refuse to launch rather than inherit the CLI default model.
    assert rc == 9
    assert env == {}  # _sliced_call was never reached; no model was bound


def test_every_claude_profile_in_registry_has_a_model_pin():
    """No claude headless route may exist without a declared model pin (else it would
    fail closed at dispatch)."""
    claude_profiles = {
        profile
        for (platform, mode, profile) in mod.PLATFORM_PATHS
        if platform == "claude" and mode == "headless"
    }
    for profile in claude_profiles:
        assert mod.resolve_execution_descriptor(f"claude.headless.{profile}").model_id


@pytest.mark.parametrize("mode", ["headless", "interactive"])
def test_descriptor_reaches_native_child_through_real_claude_launcher(tmp_path, mode):
    from types import SimpleNamespace

    from tests.scripts.test_hapax_claude_headless import _headless_env, _stub_bin

    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim = cache / "cc-active-task-beta"
    claim.write_text("task-x\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_file = tmp_path / "native-argv.txt"
    _stub_bin(
        bin_dir,
        "claude",
        'printf "%s\\n" "$@" > "$HAPAX_TEST_NATIVE_ARGV"\n: > "$HAPAX_TEST_CLAIM"\nexit 0\n',
    )
    # Execute the launcher's actual generated runner; no real tmux session or
    # native account is involved. The launcher and its argv handling are real.
    _stub_bin(
        bin_dir,
        "tmux",
        'case "$1" in\n'
        "  has-session) exit 1 ;;\n"
        '  new-session) for runner; do :; done; exec "$runner" ;;\n'
        "  *) exit 0 ;;\nesac\n",
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipes")
    env.update(
        HAPAX_TEST_NATIVE_ARGV=str(argv_file),
        HAPAX_TEST_CLAIM=str(claim),
        HAPAX_METHODOLOGY_CLAUDE_HEADLESS=str(REPO_ROOT / "scripts/hapax-claude-headless"),
        HAPAX_METHODOLOGY_CLAUDE_LAUNCHER=str(REPO_ROOT / "scripts/hapax-claude"),
        HAPAX_CLAUDE_EFFORT="low",
        HAPAX_CLAUDE_MODEL="haiku",
        XDG_CACHE_HOME=str(home / ".cache"),
    )

    def launch(argv, env):
        result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.returncode

    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(mod, "_sliced_call", side_effect=launch),
        patch.object(mod, "lane_worktree", return_value=workdir),
        patch.object(mod, "effective_dispatch_host", return_value=""),
    ):
        if mode == "headless":
            route = mod.PLATFORM_PATHS[("claude", "headless", "full")]
            rc = mod.launch_claude_headless("task-x", "beta", "inspect source", route)
        else:
            with patch.object(mod.subprocess, "call", side_effect=launch):
                rc = mod.launch_claude_interactive("task-x", "beta", SimpleNamespace(task=None))
    assert rc == 0
    argv = argv_file.read_text().splitlines()
    descriptor = mod.resolve_execution_descriptor(f"claude.{mode}.full")
    # The native CLI resolves repeated flags by the final value; ambient effort
    # defaults may precede the descriptor-derived explicit arguments.
    models = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "--model"]
    efforts = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "--effort"]
    assert models and models[-1] == descriptor.model_id
    assert efforts and efforts[-1] == descriptor.effort
