"""Tests for shared Hapax coding-agent role detection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HELPER = REPO_ROOT / "hooks" / "scripts" / "agent-role.sh"


def _bash(expr: str, *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    merged_env = os.environ.copy()
    merged_env.pop("HAPAX_AGENT_ROLE", None)
    merged_env.pop("HAPAX_AGENT_NAME", None)
    merged_env.pop("HAPAX_WORKTREE_ROLE", None)
    merged_env.pop("CODEX_THREAD_NAME", None)
    merged_env.pop("CODEX_ROLE", None)
    merged_env.pop("CLAUDE_ROLE", None)
    merged_env.pop("HAPAX_AGENT_INTERFACE", None)
    if env:
        merged_env.update(env)
    result = subprocess.run(
        ["bash", "-c", f'. "{HELPER}"; {expr}'],
        cwd=str(cwd or REPO_ROOT),
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_role_env_precedence() -> None:
    out = _bash(
        "hapax_agent_identity",
        env={
            "HAPAX_AGENT_NAME": "cx-red",
            "HAPAX_AGENT_ROLE": "epsilon",
            "CODEX_ROLE": "delta",
            "CLAUDE_ROLE": "alpha",
        },
    )
    assert out == "cx-red"


def test_codex_role_falls_back_before_claude_role() -> None:
    out = _bash("hapax_agent_identity", env={"CODEX_ROLE": "cx-blue", "CLAUDE_ROLE": "alpha"})
    assert out == "cx-blue"


def test_codex_thread_name_precedes_codex_role() -> None:
    out = _bash(
        "hapax_agent_identity",
        env={"CODEX_THREAD_NAME": "cx-green", "CODEX_ROLE": "cx-blue"},
    )
    assert out == "cx-green"


def test_claude_role_supported_for_compatibility() -> None:
    out = _bash("hapax_agent_identity", env={"CLAUDE_ROLE": "beta"})
    assert out == "beta"


def test_role_from_delta_worktree_path(tmp_path: Path) -> None:
    worktree = tmp_path / "hapax-council--delta-omg"
    worktree.mkdir()
    out = _bash("hapax_agent_worktree_role", cwd=worktree)
    assert out == "delta"


def test_codex_interface_detection() -> None:
    out = _bash("hapax_agent_interface", env={"CODEX_THREAD_NAME": "cx-red"})
    assert out == "codex"


def test_worktree_role_separate_from_codex_thread() -> None:
    out = _bash(
        "hapax_agent_identity; hapax_agent_worktree_role",
        env={"CODEX_THREAD_NAME": "cx-red", "HAPAX_WORKTREE_ROLE": "beta"},
    )
    assert out.splitlines() == ["cx-red", "beta"]
