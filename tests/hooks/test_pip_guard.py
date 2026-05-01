"""Tests for hooks/scripts/pip-guard.sh.

The hook is a PreToolUse blocker for direct `pip` / `pip3` /
`python -m pip` install/uninstall — the operator's policy is that all
Python package management goes through `uv` (uv pip / uv add / uv sync).

`uv pip` itself is allowed (the wrapper goes through uv).
Read-only `pip freeze` / `pip list` are allowed.
The hook was untested.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "pip-guard.sh"


def _run(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# ── Block path: direct pip install / uninstall ─────────────────────


class TestBlocksDirectPip:
    def test_blocks_pip_install(self) -> None:
        result = _run(_bash("pip install requests"))
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr
        assert "uv pip install" in result.stderr

    def test_blocks_pip_uninstall(self) -> None:
        result = _run(_bash("pip uninstall requests"))
        assert result.returncode == 2

    def test_blocks_pip3_install(self) -> None:
        result = _run(_bash("pip3 install requests"))
        assert result.returncode == 2

    def test_blocks_python_m_pip(self) -> None:
        result = _run(_bash("python -m pip install requests"))
        assert result.returncode == 2

    def test_blocks_python3_m_pip(self) -> None:
        result = _run(_bash("python3 -m pip install requests"))
        assert result.returncode == 2

    def test_blocks_pip_install_with_flags(self) -> None:
        """Flags don't bypass — `pip install -U requests` still blocked."""
        result = _run(_bash("pip install -U --no-deps requests"))
        assert result.returncode == 2


# ── Allow path: uv pip and read-only ───────────────────────────────


class TestAllowsUv:
    def test_allows_uv_pip_install(self) -> None:
        """`uv pip install` IS the recommended replacement."""
        result = _run(_bash("uv pip install requests"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_allows_uv_pip_uninstall(self) -> None:
        result = _run(_bash("uv pip uninstall requests"))
        assert result.returncode == 0

    def test_allows_uv_add(self) -> None:
        result = _run(_bash("uv add requests"))
        assert result.returncode == 0

    def test_allows_uv_sync(self) -> None:
        result = _run(_bash("uv sync"))
        assert result.returncode == 0


class TestAllowsReadOnly:
    def test_allows_pip_freeze(self) -> None:
        """Read-only `pip freeze` is informational; not blocked."""
        result = _run(_bash("pip freeze"))
        assert result.returncode == 0

    def test_allows_pip_list(self) -> None:
        result = _run(_bash("pip list"))
        assert result.returncode == 0

    def test_allows_pip_show(self) -> None:
        result = _run(_bash("pip show requests"))
        assert result.returncode == 0


# ── Heredoc / quoted-string false-positive avoidance ──────────────


class TestNoFalsePositives:
    """The hook reads only the FIRST line of the command, so heredoc
    bodies / multi-line strings that mention `pip install` don't trigger."""

    def test_heredoc_body_mentioning_pip_install_passes(self) -> None:
        cmd = (
            "gh pr create --title 'docs' --body \"$(cat <<'EOF'\n"
            "Don't run pip install; use uv pip install instead.\n"
            'EOF\n)"'
        )
        result = _run(_bash(cmd))
        assert result.returncode == 0

    def test_first_line_is_what_matters(self) -> None:
        """`echo` first, then `pip install` later — only first line counts."""
        cmd = "echo 'hello'\npip install requests  # this won't be evaluated"
        result = _run(_bash(cmd))
        assert result.returncode == 0


# ── Pass-through for non-relevant tool calls ───────────────────────


class TestPassthrough:
    def test_passes_through_non_bash(self) -> None:
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}})
        assert result.returncode == 0

    def test_passes_through_empty_command(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {}})
        assert result.returncode == 0

    def test_passes_through_unrelated_command(self) -> None:
        result = _run(_bash("ls -la"))
        assert result.returncode == 0


# ── Hook integrity ─────────────────────────────────────────────────


class TestHookIntegrity:
    def test_hook_is_executable(self) -> None:
        import os

        assert os.access(HOOK, os.X_OK)

    def test_hook_uses_strict_bash(self) -> None:
        body = HOOK.read_text(encoding="utf-8")
        assert body.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in body

    def test_block_message_documents_uv_alternative(self) -> None:
        """Block message must point at the safe alternative (`uv pip install` /
        `uv add` / `uv sync`) so the operator knows what to do."""
        body = HOOK.read_text(encoding="utf-8")
        assert "uv pip install" in body
        assert "uv add" in body
        assert "uv sync" in body
