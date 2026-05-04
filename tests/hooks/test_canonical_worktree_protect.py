"""Tests for hooks/scripts/canonical-worktree-protect.sh.

The hook is a PreToolUse blocker that refuses git commands which would
leave the canonical worktree (/home/hapax/projects/hapax-council) on a
non-main ref. The canonical worktree is the operator surface and local
main-ref source for post-merge deploy convergence; agents must use their
own worktrees for feature branches.

Tests use HAPAX_CANONICAL_PATH_OVERRIDE to point the hook at a sandbox
path so we don't need to run inside the actual canonical worktree.

Tests cover:
- Refuses `git checkout <other-ref>` from canonical
- Refuses `git switch -c <branch>` from canonical
- Refuses `git checkout -b <branch>` from canonical
- Refuses `git reset --hard <other-ref>` from canonical
- Allows `git checkout main` / `git switch main` from canonical
- Allows `git pull` / `git fetch` from canonical
- Allows file-restore (`git checkout -- <file>`) from canonical
- Allows `git reset --hard origin/main` / `main` from canonical
- Allows the same blocked commands from a non-canonical worktree
- Allows `git worktree add` from canonical (does not modify canonical HEAD)
- Honors HAPAX_CANONICAL_PROTECT_BYPASS=1 escape hatch
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "canonical-worktree-protect.sh"


def _run(
    payload: dict,
    *,
    cwd: Path | None = None,
    canonical_override: Path | None = None,
    bypass: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if canonical_override is not None:
        env["HAPAX_CANONICAL_PATH_OVERRIDE"] = str(canonical_override)
    if bypass:
        env["HAPAX_CANONICAL_PROTECT_BYPASS"] = "1"
    else:
        env.pop("HAPAX_CANONICAL_PROTECT_BYPASS", None)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=env,
    )


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _make_repo_on_main(tmp_path: Path) -> Path:
    """Init a primary git repo on main with one commit. Returns repo root."""
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
    # Create an extra branch + tag so we have non-main refs to test against.
    subprocess.run(["git", "branch", "alpha/foo"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def _make_linked_worktree(canonical: Path, linked_path: Path) -> Path:
    """Create a linked (non-canonical) worktree on a feature branch.

    The canonical already has main checked out; the linked worktree
    is attached to alpha/foo so it's a different HEAD.
    """
    subprocess.run(
        ["git", "worktree", "add", "-q", str(linked_path), "alpha/foo"],
        cwd=canonical,
        check=True,
        capture_output=True,
    )
    return linked_path


# ── Block: state-changing git in canonical ─────────────────────────


class TestBlockInCanonical:
    def test_refuses_checkout_to_feature_branch(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git checkout alpha/foo"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 2, result.stderr
        assert "BLOCKED" in result.stderr
        assert "main" in result.stderr
        assert "git worktree add" in result.stderr

    def test_refuses_switch_to_feature_branch(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git switch alpha/foo"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 2, result.stderr
        assert "BLOCKED" in result.stderr

    def test_refuses_switch_dash_c(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git switch -c alpha/new"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 2, result.stderr

    def test_refuses_switch_create_long_form(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git switch --create alpha/new"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 2, result.stderr

    def test_refuses_checkout_dash_b(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git checkout -b alpha/new"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 2, result.stderr

    def test_refuses_checkout_dash_B_other(self, tmp_path: Path) -> None:
        """`-B main` is allowed (recovery), but `-B feature` is blocked."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git checkout -B alpha/new"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 2, result.stderr

    def test_refuses_reset_hard_to_other_ref(self, tmp_path: Path) -> None:
        """`reset --hard <other-ref>` would move HEAD off main."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git reset --hard alpha/foo"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 2, result.stderr

    def test_refuses_using_payload_cwd(self, tmp_path: Path) -> None:
        """Codex passes cwd in the hook payload; the hook must honor it."""
        canonical = _make_repo_on_main(tmp_path / "canonical")
        result = _run(
            {
                "tool_name": "Bash",
                "cwd": str(canonical),
                "tool_input": {"command": "git switch alpha/foo"},
            },
            cwd=tmp_path,
            canonical_override=canonical,
        )
        assert result.returncode == 2, result.stderr

    def test_refuses_leading_cd_then_switch(self, tmp_path: Path) -> None:
        """Common shell form: `cd canonical && git switch feature`."""
        canonical = _make_repo_on_main(tmp_path / "canonical")
        result = _run(
            _bash(f"cd {canonical} && git switch alpha/foo"),
            cwd=tmp_path,
            canonical_override=canonical,
        )
        assert result.returncode == 2, result.stderr

    def test_refuses_git_dash_c_checkout(self, tmp_path: Path) -> None:
        """Common shell form: `git -C canonical checkout feature`."""
        canonical = _make_repo_on_main(tmp_path / "canonical")
        result = _run(
            _bash(f"git -C {canonical} checkout alpha/foo"),
            cwd=tmp_path,
            canonical_override=canonical,
        )
        assert result.returncode == 2, result.stderr


# ── Allow: read-only / on-main / recovery commands in canonical ────


class TestAllowInCanonical:
    def test_allows_checkout_main(self, tmp_path: Path) -> None:
        """Idempotent re-checkout of main is fine."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git checkout main"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_switch_main(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git switch main"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_checkout_dash_B_main(self, tmp_path: Path) -> None:
        """`-B main` is recovery, explicitly allowed."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git checkout -B main"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_file_restore(self, tmp_path: Path) -> None:
        """`git checkout -- <file>` is file-level, not HEAD-mutating."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git checkout -- README.md"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_pull(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git pull --ff-only"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_fetch(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git fetch origin"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_status_log_diff(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path)
        for cmd in ("git status", "git log --oneline", "git diff", "git branch"):
            result = _run(
                _bash(cmd),
                cwd=canonical,
                canonical_override=canonical,
            )
            assert result.returncode == 0, f"{cmd}: {result.stderr}"

    def test_allows_reset_hard_to_main(self, tmp_path: Path) -> None:
        """Recovery: `git reset --hard main` is allowed."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git reset --hard main"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_reset_hard_to_origin_main(self, tmp_path: Path) -> None:
        """Operator-explicit recovery: `git reset --hard origin/main`."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git reset --hard origin/main"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_reset_soft_anywhere(self, tmp_path: Path) -> None:
        """Soft/mixed reset (no --hard) does not move HEAD's branch attachment."""
        canonical = _make_repo_on_main(tmp_path)
        for cmd in (
            "git reset HEAD~1",
            "git reset --soft HEAD~1",
            "git reset --mixed alpha/foo",
        ):
            result = _run(
                _bash(cmd),
                cwd=canonical,
                canonical_override=canonical,
            )
            assert result.returncode == 0, f"{cmd}: {result.stderr}"

    def test_allows_reset_hard_no_arg(self, tmp_path: Path) -> None:
        """`git reset --hard` (no ref) resets to HEAD; HEAD stays on main."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git reset --hard"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_worktree_add(self, tmp_path: Path) -> None:
        """git worktree add does not modify canonical HEAD — explicitly allowed."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash(f"git worktree add {tmp_path}/wt-new -b alpha/new"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr


# ── Worktree-aware: same commands ALLOWED outside canonical ────────


class TestNonCanonicalWorktree:
    def test_allows_checkout_in_linked_worktree(self, tmp_path: Path) -> None:
        """`git checkout alpha/foo` is fine in a non-canonical worktree."""
        canonical = _make_repo_on_main(tmp_path / "canonical")
        # Make a separate sibling repo to act as our "linked worktree" for the
        # test — the hook only blocks based on path equality, so any other
        # path is non-canonical from its perspective.
        other = _make_repo_on_main(tmp_path / "other")
        result = _run(
            _bash("git checkout alpha/foo"),
            cwd=other,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_switch_dash_c_in_linked(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path / "canonical")
        other = _make_repo_on_main(tmp_path / "other")
        result = _run(
            _bash("git switch -c alpha/new"),
            cwd=other,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr

    def test_allows_reset_hard_in_linked(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path / "canonical")
        other = _make_repo_on_main(tmp_path / "other")
        result = _run(
            _bash("git reset --hard alpha/foo"),
            cwd=other,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr


# ── Operator escape hatch ──────────────────────────────────────────


class TestBypassEnvVar:
    def test_bypass_allows_blocked_command(self, tmp_path: Path) -> None:
        """HAPAX_CANONICAL_PROTECT_BYPASS=1 overrides the gate (operator-only)."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("git checkout alpha/foo"),
            cwd=canonical,
            canonical_override=canonical,
            bypass=True,
        )
        assert result.returncode == 0, result.stderr
        assert "warning" in result.stderr.lower()


# ── Pass-through: non-Bash, non-git, empty, outside-git ─────────────


class TestPassthrough:
    def test_passes_through_non_bash(self, tmp_path: Path) -> None:
        result = _run(
            {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}},
            canonical_override=tmp_path,
        )
        assert result.returncode == 0

    def test_passes_through_empty_cmd(self, tmp_path: Path) -> None:
        result = _run(
            {"tool_name": "Bash", "tool_input": {}},
            canonical_override=tmp_path,
        )
        assert result.returncode == 0

    def test_passes_through_non_git_cmd(self, tmp_path: Path) -> None:
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash("ls -la"),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0

    def test_passes_through_outside_git_repo(self, tmp_path: Path) -> None:
        """Fails open: if we're not in a git repo, allow the command."""
        # tmp_path is a non-repo dir; the hook should bail at rev-parse.
        result = _run(
            _bash("git checkout alpha/foo"),
            cwd=tmp_path,
            canonical_override=tmp_path,
        )
        assert result.returncode == 0

    def test_passes_through_quoted_git_command_in_string(self, tmp_path: Path) -> None:
        """Commit messages mentioning 'git checkout alpha/x' must not trip the gate."""
        canonical = _make_repo_on_main(tmp_path)
        result = _run(
            _bash('echo "we used to git checkout alpha/foo here"'),
            cwd=canonical,
            canonical_override=canonical,
        )
        assert result.returncode == 0, result.stderr


# ── Hook integrity ─────────────────────────────────────────────────


class TestHookIntegrity:
    def test_hook_is_executable(self) -> None:
        assert os.access(HOOK, os.X_OK)

    def test_hook_uses_strict_bash(self) -> None:
        body = HOOK.read_text(encoding="utf-8")
        assert body.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in body

    def test_hook_documents_canonical_alternative(self) -> None:
        """Block message points at the safe alternative (`git worktree add`)."""
        body = HOOK.read_text(encoding="utf-8")
        assert "git worktree add" in body

    def test_hook_documents_bypass_env_var(self) -> None:
        """Bypass mechanism is documented for the operator."""
        body = HOOK.read_text(encoding="utf-8")
        assert "HAPAX_CANONICAL_PROTECT_BYPASS" in body
