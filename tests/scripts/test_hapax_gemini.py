"""Tests for the Hapax Gemini CLI Interactive launcher (scripts/hapax-gemini)."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "hapax-gemini"


def _base_env(tmp_path: Path) -> dict[str, str]:
    """Build a clean env that pins HOME, cache, and worktree root to tmp_path."""
    env = os.environ.copy()
    env["HAPAX_COUNCIL_DIR"] = str(REPO_ROOT)
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["HAPAX_GEMINI_WORKTREE_ROOT"] = str(tmp_path / "projects")
    env["HAPAX_GEMINI_VAULT_DIR"] = str(tmp_path / "vault")
    env["HAPAX_GEMINI_RELAY_DIR"] = str(tmp_path / "relay")
    env["HAPAX_GEMINI_POLICY"] = str(tmp_path / "policy.toml")
    # Don't inherit operator role hints
    env.pop("HAPAX_AGENT_NAME", None)
    env.pop("HAPAX_AGENT_ROLE", None)
    env.pop("GEMINI_ROLE", None)
    env.pop("HAPAX_AGENT_INTERFACE", None)
    return env


def _make_iota_worktree(env: dict[str, str]) -> Path:
    root = Path(env["HAPAX_GEMINI_WORKTREE_ROOT"]) / "hapax-council--iota"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_dry_run_emits_expected_argv(tmp_path: Path) -> None:
    """--dry-run prints the gemini argv that would be exec'd, without spawning anything."""
    env = _base_env(tmp_path)
    _make_iota_worktree(env)
    result = subprocess.run(
        [str(LAUNCHER), "--role", "iota", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    out = result.stdout.strip()
    # Tokenize the dry-run output
    tokens = shlex.split(out)
    # First token is the gemini binary path (default $HOME/.npm-global/bin/gemini
    # since command -v gemini may resolve to it; we don't assert the exact path)
    assert tokens[0].endswith("gemini")
    # Argv must include --approval-mode plan
    assert "--approval-mode" in tokens
    plan_idx = tokens.index("--approval-mode")
    assert tokens[plan_idx + 1] == "plan"
    # --resume latest by default
    assert "--resume" in tokens
    resume_idx = tokens.index("--resume")
    assert tokens[resume_idx + 1] == "latest"
    # --include-directories should carry both vault and relay
    assert "--include-directories" in tokens
    inc_idx = tokens.index("--include-directories")
    inc_arg = tokens[inc_idx + 1]
    assert env["HAPAX_GEMINI_VAULT_DIR"] in inc_arg
    assert env["HAPAX_GEMINI_RELAY_DIR"] in inc_arg
    # --policy should be included (the policy file string was written into env)
    assert "--policy" in tokens


def test_dry_run_omits_resume_when_disabled(tmp_path: Path) -> None:
    """Setting HAPAX_GEMINI_RESUME='' disables --resume (e.g. for fresh sessions)."""
    env = _base_env(tmp_path)
    env["HAPAX_GEMINI_RESUME"] = ""
    _make_iota_worktree(env)
    result = subprocess.run(
        [str(LAUNCHER), "--role", "iota", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    tokens = shlex.split(result.stdout)
    assert "--resume" not in tokens


def test_dry_run_overrides_approval_mode(tmp_path: Path) -> None:
    """HAPAX_GEMINI_APPROVAL_MODE swaps the default plan mode (e.g. for future widening)."""
    env = _base_env(tmp_path)
    env["HAPAX_GEMINI_APPROVAL_MODE"] = "edit"
    _make_iota_worktree(env)
    result = subprocess.run(
        [str(LAUNCHER), "--role", "iota", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, f"stderr={result.stderr}"
    tokens = shlex.split(result.stdout)
    plan_idx = tokens.index("--approval-mode")
    assert tokens[plan_idx + 1] == "edit"


def test_invalid_role_rejected(tmp_path: Path) -> None:
    """Roles outside iota|kappa|lambda|mu are refused; lane name is load-bearing for hooks."""
    env = _base_env(tmp_path)
    result = subprocess.run(
        [str(LAUNCHER), "--role", "alpha", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 2
    assert "invalid role" in result.stderr


def test_invalid_terminal_rejected(tmp_path: Path) -> None:
    """Terminal must be one of none|tmux|foot."""
    env = _base_env(tmp_path)
    _make_iota_worktree(env)
    result = subprocess.run(
        [str(LAUNCHER), "--role", "iota", "--terminal", "kitty", "--dry-run"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 2
    assert "invalid terminal" in result.stderr


def test_missing_worktree_rejected(tmp_path: Path) -> None:
    """If the worktree path doesn't exist and --dry-run isn't set, the launcher fails fast."""
    env = _base_env(tmp_path)
    # Do NOT create the iota worktree
    result = subprocess.run(
        [str(LAUNCHER), "--role", "iota", "--terminal", "tmux"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 3
    assert "worktree not found" in result.stderr


def test_extra_args_pass_through(tmp_path: Path) -> None:
    """Args after `--` are appended to the gemini invocation verbatim."""
    env = _base_env(tmp_path)
    _make_iota_worktree(env)
    result = subprocess.run(
        [str(LAUNCHER), "--role", "iota", "--dry-run", "--", "--debug", "--verbose"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 0
    tokens = shlex.split(result.stdout)
    assert "--debug" in tokens
    assert "--verbose" in tokens
