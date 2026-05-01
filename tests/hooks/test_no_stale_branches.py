"""Tests for hooks/scripts/no-stale-branches.sh.

246-LOC wired PreToolUse hook on Bash; the operator's primary
branch-discipline gate. Two protection categories:

1. **Branch-creation gate** — blocks ``git checkout -b`` /
   ``git switch -c`` / ``git branch <name>`` / ``git worktree add -b``
   when ANY local-or-remote feature branch has commits ahead of main.
2. **Destructive-command gate** — blocks ``git reset --hard`` /
   ``git checkout .`` / ``git branch -f`` / ``git worktree remove``
   on a feature branch that has commits ahead of main, with carve-
   outs for ``git reset --hard {main,origin/main}`` (recovery, not
   destruction) and operations on branches whose remote tracking is
   already gone (squash-merge cleanup).

Coverage focuses on the lattice of branches the hook fires on:
- non-creating non-destructive commands → exit 0
- branch-creation in clean / stale-bearing repos
- destructive commands on main / feature branches / recovery resets
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "no-stale-branches.sh"


def _run(
    payload: dict,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=dict(os.environ),
        cwd=cwd,
        timeout=20,
    )


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _make_repo(tmp_path: Path) -> Path:
    """Init a git repo on `main` with one root commit."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "root"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def _add_stale_branch(repo: Path, name: str = "feat/abandoned") -> None:
    """Create a branch with one commit ahead of main, then return to main."""
    subprocess.run(["git", "checkout", "-q", "-b", name], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "stale work"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)


def _checkout_feature(repo: Path, name: str = "feat/active") -> None:
    """Create + check out a feature branch with one commit ahead of main."""
    subprocess.run(["git", "checkout", "-q", "-b", name], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "active work"],
        cwd=repo,
        check=True,
    )


# ── Tool gating ────────────────────────────────────────────────────


class TestToolGating:
    def test_edit_tool_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run({"tool_name": "Edit", "tool_input": {"file_path": "x"}}, cwd=repo)
        assert result.returncode == 0
        assert result.stderr == ""


# ── Non-creating commands ──────────────────────────────────────────


class TestNonCreatingCommands:
    def test_ls_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run(_bash("ls -la"), cwd=repo)
        assert result.returncode == 0

    def test_git_status_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run(_bash("git status"), cwd=repo)
        assert result.returncode == 0

    def test_git_branch_show_current_silent(self, tmp_path: Path) -> None:
        """git branch --show-current is not branch creation."""
        repo = _make_repo(tmp_path)
        result = _run(_bash("git branch --show-current"), cwd=repo)
        assert result.returncode == 0


# ── Branch-creation gate ───────────────────────────────────────────


class TestBranchCreation:
    def test_checkout_b_in_clean_repo_allowed(self, tmp_path: Path) -> None:
        """No stale branches → exit 0 (creation allowed)."""
        repo = _make_repo(tmp_path)
        result = _run(_bash("git checkout -b feat/new"), cwd=repo)
        assert result.returncode == 0

    def test_switch_c_in_clean_repo_allowed(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run(_bash("git switch -c feat/new"), cwd=repo)
        assert result.returncode == 0

    def test_checkout_b_with_stale_branch_blocked(self, tmp_path: Path) -> None:
        """Existing local branch ahead of main → BLOCKED."""
        repo = _make_repo(tmp_path)
        _add_stale_branch(repo, name="feat/abandoned")
        result = _run(_bash("git checkout -b feat/new"), cwd=repo)
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr
        assert "feat/abandoned" in result.stderr

    def test_branch_with_name_blocked_when_stale_exists(self, tmp_path: Path) -> None:
        """`git branch <name>` (creating form) gated by the same rule."""
        repo = _make_repo(tmp_path)
        _add_stale_branch(repo)
        result = _run(_bash("git branch feat/new"), cwd=repo)
        assert result.returncode == 2

    def test_outside_git_repo_silent(self, tmp_path: Path) -> None:
        """`git checkout -b new` outside a repo → exit 0 (gated by repo
        check; no main to compare against)."""
        # Don't init a repo. Run from tmp_path which is empty.
        result = _run(_bash("git checkout -b feat/new"), cwd=tmp_path)
        assert result.returncode == 0


# ── Destructive command gate ───────────────────────────────────────


class TestDestructiveCommands:
    def test_reset_hard_on_main_allowed(self, tmp_path: Path) -> None:
        """git reset --hard while on main is allowed (no commits to lose)."""
        repo = _make_repo(tmp_path)
        result = _run(_bash("git reset --hard"), cwd=repo)
        assert result.returncode == 0

    def test_reset_hard_to_main_recovery_allowed(self, tmp_path: Path) -> None:
        """git reset --hard main while on a feature branch is recovery,
        not destruction; carve-out per docstring."""
        repo = _make_repo(tmp_path)
        _checkout_feature(repo, name="feat/recover")
        result = _run(_bash("git reset --hard main"), cwd=repo)
        assert result.returncode == 0

    def test_reset_hard_on_feature_with_commits_blocked(self, tmp_path: Path) -> None:
        """git reset --hard on a feature branch with commits ahead → BLOCKED."""
        repo = _make_repo(tmp_path)
        _checkout_feature(repo, name="feat/has-work")
        result = _run(_bash("git reset --hard HEAD~1"), cwd=repo)
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr
        assert "Destructive" in result.stderr or "destructive" in result.stderr.lower()

    def test_quoted_destructive_in_commit_message_allowed(self, tmp_path: Path) -> None:
        """Mentioning `git reset --hard` inside a quoted commit message
        must NOT trigger the gate (string-stripping behaviour)."""
        repo = _make_repo(tmp_path)
        _checkout_feature(repo, name="feat/quoted")
        result = _run(
            _bash("git commit -m 'note: removed git reset --hard from script'"),
            cwd=repo,
        )
        assert result.returncode == 0
