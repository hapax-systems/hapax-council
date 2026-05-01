"""Tests for hooks/scripts/branch-switch-guard.sh.

The hook is a PreToolUse blocker for branch CREATION in PRIMARY
worktrees (`git checkout -b`, `git switch -c`). Switching to existing
branches is allowed; branch creation in linked worktrees is allowed.
The hook was untested.

Policy rationale: feature work happens in dedicated linked worktrees
(`hapax-council--<role>` lanes). Creating a new branch in the primary
worktree dilutes the lane discipline; the hook nudges the operator to
`git worktree add` instead.

Tests cover the decision matrix:
- block: `checkout -b`, `checkout -B`, `switch -c`, `switch --create`
- allow: `checkout <existing>`, `checkout -- <file>`, `checkout -B main`,
  `switch <existing>`, plain `git status` etc.
- worktree-aware: same `checkout -b` blocked in primary, allowed in linked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "branch-switch-guard.sh"


def _run(payload: dict, *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _make_primary_repo(tmp_path: Path) -> Path:
    """Init a primary git repo (single worktree). Returns repo root."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("repo\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_path, check=True, env=env)
    return tmp_path


def _make_linked_worktree(primary: Path, linked_path: Path) -> Path:
    """Create a linked worktree (detached HEAD) off the primary repo.
    The primary already has `main` checked out, so the linked worktree
    must use --detach to avoid the "branch already checked out" error."""
    subprocess.run(
        ["git", "worktree", "add", "-q", "--detach", str(linked_path)],
        cwd=primary,
        check=True,
        capture_output=True,
    )
    return linked_path


# ── Block path: branch creation in primary worktree ────────────────


class TestBlockInPrimary:
    def test_blocks_checkout_dash_b(self, tmp_path: Path) -> None:
        repo = _make_primary_repo(tmp_path)
        result = _run(_bash("git checkout -b feature/x"), cwd=repo)
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr
        assert "git worktree add" in result.stderr

    def test_blocks_checkout_dash_B_other_branch(self, tmp_path: Path) -> None:
        """`git checkout -B <new>` is also creation; only -B main is excepted."""
        repo = _make_primary_repo(tmp_path)
        result = _run(_bash("git checkout -B feature/y"), cwd=repo)
        assert result.returncode == 2

    def test_blocks_switch_dash_c(self, tmp_path: Path) -> None:
        repo = _make_primary_repo(tmp_path)
        result = _run(_bash("git switch -c feature/z"), cwd=repo)
        assert result.returncode == 2

    def test_blocks_switch_create_long_form(self, tmp_path: Path) -> None:
        repo = _make_primary_repo(tmp_path)
        result = _run(_bash("git switch --create feature/w"), cwd=repo)
        assert result.returncode == 2


# ── Allow path: checkout-B-main recovery + non-creation ────────────


class TestAllowInPrimary:
    def test_allows_plain_checkout(self, tmp_path: Path) -> None:
        """Switching to an existing branch is unblocked."""
        repo = _make_primary_repo(tmp_path)
        result = _run(_bash("git checkout main"), cwd=repo)
        assert result.returncode == 0

    def test_allows_checkout_dash_B_main(self, tmp_path: Path) -> None:
        """`git checkout -B main` is recovery, explicitly excepted."""
        repo = _make_primary_repo(tmp_path)
        result = _run(_bash("git checkout -B main"), cwd=repo)
        assert result.returncode == 0

    def test_allows_checkout_file_restore(self, tmp_path: Path) -> None:
        """`git checkout -- <file>` is file restore, not branch op."""
        repo = _make_primary_repo(tmp_path)
        result = _run(_bash("git checkout -- README.md"), cwd=repo)
        assert result.returncode == 0

    def test_allows_plain_switch(self, tmp_path: Path) -> None:
        repo = _make_primary_repo(tmp_path)
        result = _run(_bash("git switch main"), cwd=repo)
        assert result.returncode == 0

    def test_allows_unrelated_git_commands(self, tmp_path: Path) -> None:
        repo = _make_primary_repo(tmp_path)
        for cmd in ("git status", "git log", "git diff", "git restore README.md"):
            result = _run(_bash(cmd), cwd=repo)
            assert result.returncode == 0, f"unexpected block on {cmd!r}: {result.stderr}"


# ── Worktree-aware: linked worktrees allow creation ────────────────


class TestWorktreeAware:
    def test_allows_branch_creation_in_linked_worktree(self, tmp_path: Path) -> None:
        """Linked worktrees are excepted from the primary-worktree gate."""
        primary = _make_primary_repo(tmp_path / "primary")
        linked = _make_linked_worktree(primary, tmp_path / "linked")
        result = _run(_bash("git checkout -b feature/in-linked"), cwd=linked)
        assert result.returncode == 0, (
            f"linked worktrees should allow branch creation: {result.stderr}"
        )

    def test_blocks_branch_creation_in_primary(self, tmp_path: Path) -> None:
        """Sanity: same command blocked in primary, allowed in linked above."""
        primary = _make_primary_repo(tmp_path)
        result = _run(_bash("git checkout -b feature/in-primary"), cwd=primary)
        assert result.returncode == 2


# ── Pass-through: non-Bash, empty cmd, outside-git ─────────────────


class TestPassthrough:
    def test_passes_through_non_bash(self) -> None:
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}})
        assert result.returncode == 0

    def test_passes_through_empty_cmd(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {}})
        assert result.returncode == 0

    def test_passes_through_non_git_cmd(self) -> None:
        result = _run(_bash("ls -la"))
        assert result.returncode == 0

    def test_passes_through_outside_git_repo(self, tmp_path: Path) -> None:
        """Fails open: if we can't determine git-dir, allow the command."""
        result = _run(_bash("git checkout -b feature/x"), cwd=tmp_path)
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

    def test_hook_documents_worktree_alternative(self) -> None:
        """The block message must point at the safe alternative
        (`git worktree add`) so the operator knows what to do."""
        body = HOOK.read_text(encoding="utf-8")
        assert "git worktree add" in body
