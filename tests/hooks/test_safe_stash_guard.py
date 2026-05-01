"""Tests for hooks/scripts/safe-stash-guard.sh.

The guard is a PreToolUse hook that blocks ``git stash pop`` because the
3-way merge can leave conflict markers in files with no ``--abort`` to
undo, and the stash is not auto-dropped on conflict. This has broken
running services on this rig before (logos-api SyntaxError, vite build
failure). Tests pin the decision matrix the hook implements.

Invokes the shell hook via subprocess so the test doesn't need to
re-implement bash semantics — exit codes and stderr lines are the real
contract.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "safe-stash-guard.sh"


def _run(payload: dict) -> subprocess.CompletedProcess[str]:
    """Send the given hook payload over stdin and return the completed process."""
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def _bash_payload(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# ── Block path: real git stash pop invocations ─────────────────────


class TestBlocks:
    def test_blocks_bare_stash_pop(self) -> None:
        result = _run(_bash_payload("git stash pop"))
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr
        assert "git stash apply" in result.stderr  # safe-alternative hint

    def test_blocks_stash_pop_with_index(self) -> None:
        result = _run(_bash_payload("git stash pop stash@{0}"))
        assert result.returncode == 2

    def test_blocks_stash_pop_with_leading_whitespace(self) -> None:
        result = _run(_bash_payload("   git stash pop"))
        assert result.returncode == 2

    def test_blocks_stash_pop_after_double_amp(self) -> None:
        """Catches `cd foo && git stash pop` chained-command escapes."""
        result = _run(_bash_payload("cd /tmp && git stash pop"))
        assert result.returncode == 2

    def test_blocks_stash_pop_after_semicolon(self) -> None:
        result = _run(_bash_payload("ls; git stash pop"))
        assert result.returncode == 2


# ── Allow path: safe stash idioms ──────────────────────────────────


class TestAllows:
    def test_allows_stash_apply(self) -> None:
        result = _run(_bash_payload("git stash apply"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_allows_stash_drop(self) -> None:
        result = _run(_bash_payload("git stash drop"))
        assert result.returncode == 0

    def test_allows_stash_branch(self) -> None:
        result = _run(_bash_payload("git stash branch wip-recovery"))
        assert result.returncode == 0

    def test_allows_stash_list(self) -> None:
        result = _run(_bash_payload("git stash list"))
        assert result.returncode == 0

    def test_allows_stash_push(self) -> None:
        result = _run(_bash_payload("git stash push -m 'wip'"))
        assert result.returncode == 0

    def test_allows_apply_then_drop_chain(self) -> None:
        """The recommended replacement idiom must not be blocked."""
        result = _run(_bash_payload("git stash apply && git stash drop"))
        assert result.returncode == 0


# ── Quoted-string false-positive avoidance ─────────────────────────


class TestQuotedStringFalsePositives:
    """The hook strips quoted strings + heredoc bodies before pattern
    matching so PR titles, commit messages, and echo'd text mentioning
    `git stash pop` don't trigger the block."""

    def test_allows_stash_pop_inside_single_quotes(self) -> None:
        result = _run(
            _bash_payload("git commit -m 'fix(docs): note that git stash pop is prohibited'")
        )
        assert result.returncode == 0

    def test_allows_stash_pop_inside_double_quotes(self) -> None:
        result = _run(_bash_payload('echo "git stash pop is unsafe — use apply"'))
        assert result.returncode == 0

    def test_allows_stash_pop_in_pr_body_heredoc(self) -> None:
        """Hook uses sed -z so multi-line heredoc bodies are stripped too."""
        cmd = (
            "gh pr create --title 'docs' --body \"$(cat <<'EOF'\n"
            "Don't run `git stash pop`. Use git stash apply instead.\n"
            'EOF\n)"'
        )
        result = _run(_bash_payload(cmd))
        assert result.returncode == 0


# ── Pass-through for non-relevant tool calls ───────────────────────


class TestPassthrough:
    def test_passes_through_non_bash_tools(self) -> None:
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_passes_through_bash_with_no_command_field(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {}})
        assert result.returncode == 0

    def test_passes_through_empty_input(self) -> None:
        result = subprocess.run(
            ["bash", str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0

    def test_passes_through_malformed_json(self) -> None:
        """Hook fails open on parse errors — better to allow than to wedge."""
        result = subprocess.run(
            ["bash", str(HOOK)],
            input="not-json{{{",
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0


# ── Hook integrity ─────────────────────────────────────────────────


class TestHookIntegrity:
    def test_hook_is_executable(self) -> None:
        import os

        assert os.access(HOOK, os.X_OK), f"{HOOK} not executable"

    def test_hook_uses_strict_bash(self) -> None:
        body = HOOK.read_text(encoding="utf-8")
        assert body.startswith("#!/usr/bin/env bash"), "hook must shebang bash"
        assert "set -euo pipefail" in body, "hook must enable strict mode"
