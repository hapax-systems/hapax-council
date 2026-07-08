"""R0-pin: launch_claude_headless must pin --model per profile (CEI drift guard).

Regression for the fable->opus silent-drop: the `full` profile previously inherited the
Claude Code CLI default model (fable) instead of its registry-declared model (opus).
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
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
    # The registry declares claude.headless.full -> claude-opus-4-8; the launch must pin
    # "opus" so it never inherits the CLI default (fable, which drops fable->opus).
    assert env["HAPAX_CLAUDE_MODEL"] == "opus"


@pytest.mark.parametrize(
    ("profile", "expected"),
    [("opus", "opus"), ("sonnet", "sonnet"), ("haiku", "haiku")],
)
def test_known_profiles_pin_their_declared_model(profile: str, expected: str):
    route = mod.PLATFORM_PATHS[("claude", "headless", profile)]
    rc, env = _run_launch(route)
    assert rc == 0
    assert env["HAPAX_CLAUDE_MODEL"] == expected


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
    missing = claude_profiles - set(mod.CLAUDE_PROFILE_MODEL_PIN)
    assert not missing, f"claude headless profiles missing a model pin: {missing}"
