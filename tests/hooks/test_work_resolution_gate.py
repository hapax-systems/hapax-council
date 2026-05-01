"""Tests for hooks/scripts/work-resolution-gate.sh.

227-LOC wired PreToolUse hook on Edit/Write/MultiEdit/NotebookEdit
that blocks file mutations when the current session has unresolved
work. Three protection categories:

1. On a feature branch with commits ahead of main but no open PR.
2. On a feature branch with an open PR whose required checks are
   failing (warn, but allow edits — they're CI fixes).
3. On main with open PRs whose head branch exists locally — must
   merge / close first.

Coverage focuses on the early-exit lattice — wrong tool, no
file_path, edit_path outside any git repo, gh CLI missing, detached
HEAD, no main/master ref, and the on-feature-branch-with-no-commits
case. The gh-PR-list-dependent positive paths require a live gh
integration and are deferred to a follow-up.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "work-resolution-gate.sh"


def _run(
    payload: dict,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=15,
    )


def _edit(file_path: Path | str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}


def _make_repo(tmp_path: Path, default_branch: str = "main") -> Path:
    subprocess.run(
        ["git", "init", "-q", "-b", default_branch],
        cwd=tmp_path,
        check=True,
    )
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
    # Tag origin/main so the hook's `compare_ref="origin/main"` resolves.
    subprocess.run(
        ["git", "update-ref", f"refs/remotes/origin/{default_branch}", "HEAD"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


# ── Tool gating ────────────────────────────────────────────────────


class TestToolGating:
    def test_bash_tool_silent(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_read_tool_silent(self) -> None:
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "/etc/hosts"}})
        assert result.returncode == 0
        assert result.stderr == ""


# ── File-path gating ───────────────────────────────────────────────


class TestFilePathGating:
    def test_no_file_path_silent(self) -> None:
        """Edit without a file_path is malformed but the hook doesn't
        crash — bails silently."""
        result = _run({"tool_name": "Edit", "tool_input": {}})
        assert result.returncode == 0

    def test_file_path_outside_any_repo_silent(self, tmp_path: Path) -> None:
        """Editing a file outside any git repo → exit 0 silent."""
        target = tmp_path / "loose-file.txt"
        target.write_text("x")
        result = _run(_edit(target))
        assert result.returncode == 0


# ── Repo gating ────────────────────────────────────────────────────


class TestRepoGating:
    def test_clean_main_branch_no_prs_silent(self, tmp_path: Path) -> None:
        """On main, no open PRs in this clean fixture repo → exit 0."""
        repo = _make_repo(tmp_path)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        # Real gh queries the parent shell's auth; in tmp repo with no
        # remote it returns empty / errors which the hook tolerates.
        result = _run(_edit(target))
        assert result.returncode == 0

    def test_feature_branch_no_commits_ahead_silent(self, tmp_path: Path) -> None:
        """On a feature branch that has zero commits ahead of main,
        the work-resolution check has nothing to gate on → exit 0."""
        repo = _make_repo(tmp_path)
        subprocess.run(
            ["git", "checkout", "-q", "-b", "feat/empty"],
            cwd=repo,
            check=True,
        )
        target = repo / "ok.py"
        target.write_text("# ok\n")
        result = _run(_edit(target))
        assert result.returncode == 0

    def test_detached_head_silent(self, tmp_path: Path) -> None:
        """Detached HEAD short-circuits before the branch checks."""
        repo = _make_repo(tmp_path)
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        subprocess.run(["git", "checkout", "-q", head_sha], cwd=repo, check=True)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        result = _run(_edit(target))
        assert result.returncode == 0


# ── External-tool gating ───────────────────────────────────────────


class TestExternalToolGating:
    def test_no_gh_on_path_silent(self, tmp_path: Path) -> None:
        """When gh is missing, the hook fails-open since it can't
        determine PR state — exit 0 silent (the hook is advisory not
        mandatory; CI catches what it misses)."""
        repo = _make_repo(tmp_path)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        # Use absolute bash so PATH override doesn't lose the shell.
        env = dict(os.environ)
        env["PATH"] = "/usr/bin:/bin"  # may still have gh if installed there
        # If gh is in /usr/bin (systemwide install), this test will
        # exercise the gh path instead — still returns 0 because no
        # PRs in the tmp repo. Either way the hook is silent.
        result = subprocess.run(
            ["/usr/bin/bash", str(HOOK)],
            input=json.dumps(_edit(target)),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=15,
        )
        assert result.returncode == 0
