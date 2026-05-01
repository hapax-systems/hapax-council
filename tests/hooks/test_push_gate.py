"""Tests for hooks/scripts/push-gate.sh.

The hook is a PreToolUse blocker for high-impact git/gh/MCP operations
that should never run autonomously: git push (non-dry-run), gh pr create,
gh pr merge, and the GitHub-MCP equivalents (create_pull_request,
merge_pull_request, push_files). The hook was untested.

Tests pin the decision matrix via subprocess invocation against the real
bash script. Pattern mirrors `tests/hooks/test_safe_stash_guard.py`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "push-gate.sh"


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


# ── Block path: git push / gh pr create / gh pr merge ──────────────


class TestBlocksGitPush:
    def test_blocks_bare_git_push(self) -> None:
        result = _run(_bash("git push"))
        assert result.returncode == 2
        assert "git push" in result.stderr
        assert "explicit user approval" in result.stderr

    def test_blocks_git_push_with_remote(self) -> None:
        result = _run(_bash("git push origin main"))
        assert result.returncode == 2

    def test_blocks_git_push_with_force(self) -> None:
        result = _run(_bash("git push --force-with-lease origin HEAD"))
        assert result.returncode == 2

    def test_blocks_git_push_with_leading_whitespace(self) -> None:
        result = _run(_bash("   git push"))
        assert result.returncode == 2

    def test_allows_git_push_dry_run(self) -> None:
        """`git push --dry-run` is informational; explicitly allowed by the hook."""
        result = _run(_bash("git push --dry-run origin main"))
        assert result.returncode == 0


class TestBlocksGhPr:
    def test_blocks_gh_pr_create(self) -> None:
        result = _run(_bash("gh pr create --title 'x' --body 'y'"))
        assert result.returncode == 2
        assert "PR creation/merge" in result.stderr

    def test_blocks_gh_pr_merge(self) -> None:
        result = _run(_bash("gh pr merge 1234 --squash"))
        assert result.returncode == 2

    def test_blocks_gh_pr_create_with_leading_whitespace(self) -> None:
        result = _run(_bash("  gh pr create"))
        assert result.returncode == 2


# ── Block path: GitHub-MCP equivalents ─────────────────────────────


class TestBlocksGitHubMcp:
    def test_blocks_create_pull_request_mcp(self) -> None:
        result = _run({"tool_name": "mcp__github__create_pull_request", "tool_input": {}})
        assert result.returncode == 2
        assert "PR creation via MCP" in result.stderr

    def test_blocks_merge_pull_request_mcp(self) -> None:
        result = _run({"tool_name": "mcp__github__merge_pull_request", "tool_input": {}})
        assert result.returncode == 2
        assert "PR merge via MCP" in result.stderr

    def test_blocks_push_files_mcp(self) -> None:
        result = _run({"tool_name": "mcp__github__push_files", "tool_input": {}})
        assert result.returncode == 2
        assert "File push via MCP" in result.stderr


# ── Allow path: read-only / non-mutating ───────────────────────────


class TestAllows:
    def test_allows_git_status(self) -> None:
        result = _run(_bash("git status"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_allows_git_log(self) -> None:
        result = _run(_bash("git log --oneline"))
        assert result.returncode == 0

    def test_allows_git_fetch(self) -> None:
        """fetch is read-only — pulls remote refs without altering branches."""
        result = _run(_bash("git fetch origin main"))
        assert result.returncode == 0

    def test_allows_git_pull(self) -> None:
        """pull is non-blocked here; the broader concern is unintended-merge,
        not unauthorized push, and pull doesn't generate outbound traffic."""
        result = _run(_bash("git pull origin main"))
        assert result.returncode == 0

    def test_allows_gh_pr_view(self) -> None:
        result = _run(_bash("gh pr view 1234"))
        assert result.returncode == 0

    def test_allows_gh_pr_list(self) -> None:
        result = _run(_bash("gh pr list --state open"))
        assert result.returncode == 0

    def test_allows_gh_pr_checks(self) -> None:
        result = _run(_bash("gh pr checks 1234"))
        assert result.returncode == 0


# ── Pass-through for non-relevant tool calls ───────────────────────


class TestPassthrough:
    def test_passes_through_non_bash_non_mcp(self) -> None:
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}})
        assert result.returncode == 0

    def test_passes_through_bash_with_no_command_field(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {}})
        assert result.returncode == 0

    def test_passes_through_unrelated_mcp_tool(self) -> None:
        result = _run({"tool_name": "mcp__github__get_pull_request", "tool_input": {}})
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

    def test_hook_documents_dry_run_exception(self) -> None:
        """The git push --dry-run exception is load-bearing for read-only push
        verification (e.g. CI dry-run); pin it stays documented in the hook."""
        body = HOOK.read_text(encoding="utf-8")
        assert "--dry-run" in body, "dry-run exception must remain documented"
