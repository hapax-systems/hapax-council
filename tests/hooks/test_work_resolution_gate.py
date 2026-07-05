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
import shutil
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


def _install_rest_status_helper(repo: Path) -> None:
    scripts = repo / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy2(REPO_ROOT / "scripts" / "github_pr_status.py", scripts / "github_pr_status.py")


def _install_fake_rest_gh(tmp_path: Path, *, branch: str = "feat/ci") -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "gh-calls.log"
    fake = bin_dir / "gh"
    fake.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${{GH_CALL_LOG}}"
if [[ "${{1:-}}" == "pr" ]]; then
  echo "unexpected gh pr call" >&2
  exit 97
fi
if [[ "${{1:-}}" != "api" ]]; then
  echo "unexpected gh command" >&2
  exit 98
fi
path="${{6:-}}"
case "$path" in
  repos/owner/repo/pulls)
    echo '[{{"number":42,"title":"PR 42","body":"","head":{{"ref":"{branch}","sha":"sha-42"}},"draft":false,"state":"open","changed_files":1}}]'
    ;;
  repos/owner/repo/pulls/42)
    echo '{{"number":42,"title":"PR 42","body":"","head":{{"ref":"{branch}","sha":"sha-42"}},"draft":false,"state":"open","changed_files":1,"mergeable_state":"clean"}}'
    ;;
  repos/owner/repo/commits/sha-42/check-runs)
    echo '{{"check_runs":[{{"name":"test","status":"completed","conclusion":"failure"}}]}}'
    ;;
  repos/owner/repo/commits/sha-42/status)
    echo '{{"statuses":[]}}'
    ;;
  *)
    echo "unexpected gh api path: $path" >&2
    exit 99
    ;;
esac
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return bin_dir, log_path


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

    def test_feature_branch_pr_status_uses_rest_helper_not_gh_pr(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _install_rest_status_helper(repo)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "checkout", "-q", "-b", "feat/ci"], cwd=repo, check=True)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        subprocess.run(["git", "add", "ok.py"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "feature"], cwd=repo, check=True)
        bin_dir, log_path = _install_fake_rest_gh(tmp_path)

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GH_CALL_LOG": str(log_path),
                "HAPAX_GITHUB_PR_STATUS_CACHE_TTL_SECONDS": "0",
            },
        )

        assert result.returncode == 0
        assert "has 1 failing check(s)" in result.stderr
        calls = log_path.read_text(encoding="utf-8")
        assert "\npr " not in f"\n{calls}"
        assert "repos/owner/repo/pulls" in calls
        assert "check-runs" in calls

    def test_main_branch_local_pr_sweep_uses_rest_helper_not_gh_pr(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _install_rest_status_helper(repo)
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
            cwd=repo,
            check=True,
        )
        subprocess.run(["git", "branch", "feat/ci"], cwd=repo, check=True)
        target = repo / "ok.py"
        target.write_text("# ok\n")
        bin_dir, log_path = _install_fake_rest_gh(tmp_path)

        result = _run(
            _edit(target),
            extra_env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "GH_CALL_LOG": str(log_path),
                "HAPAX_GITHUB_PR_STATUS_CACHE_TTL_SECONDS": "0",
            },
        )

        assert result.returncode == 2
        assert "PR #42 (feat/ci) — failing" in result.stderr
        calls = log_path.read_text(encoding="utf-8")
        assert "\npr " not in f"\n{calls}"
        assert "repos/owner/repo/pulls" in calls
        assert "check-runs" in calls


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
