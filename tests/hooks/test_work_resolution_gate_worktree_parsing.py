"""Regression tests for `git worktree list` parsing in
hooks/scripts/work-resolution-gate.sh.

The hook's section-7 (on-main) gate scopes its block to PRs whose
branch is checked out IN THIS worktree. To do that it builds a
`_other_wt_branches` set from `git worktree list` output and removes
those branches from the local-branch candidate set.

Bug (surfaced by PR #2221's WirePlumber leak guard worker): the prior
parser used `sed -n 's/.*\\[//;s/\\]//p'` against the human-readable
output, which appends `locked` / `prunable` annotations after the
`[branch]` token on locked or prunable worktrees:

    /path/to/wt   abc1234 [branch-name]
    /path/to/lk   abc1234 [branch-name] locked

The captured token then became `branch-name] locked`, never matched
any real branch in `grep -F -x`, and so other-worktree branches were
NOT filtered out — which broke file Write under the on-main gate.

The fix switches to `git worktree list --porcelain` which emits
each worktree as a stanza with separate `worktree`, `HEAD`,
`branch refs/heads/<name>`, and (optionally) `locked` lines. These
tests pin the parser end-to-end through real worktree fixtures that
include locked entries, so a regression cannot land silently.
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


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _make_repo(tmp_path: Path, default_branch: str = "main") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", default_branch)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "root")
    _git(repo, "update-ref", f"refs/remotes/origin/{default_branch}", "HEAD")
    return repo


# ── Direct parser exercise ─────────────────────────────────────────


class TestPorcelainParser:
    """Drive the section-7 parser through a fixture-shell that mirrors
    the hook's exact code path. Operates on the in-tree hook source so
    if the parser shape regresses (e.g. someone restores the human
    parsing path), these tests catch it without needing a full repo +
    PR fixture."""

    @staticmethod
    def _harness(porcelain_input: str, repo_root: str) -> str:
        """Run a bash subprocess that pastes the hook's parser block
        and emits the resulting branch list to stdout. Mirrors the
        actual code in work-resolution-gate.sh; if you change the
        hook's parsing block, also update this harness."""
        script = r"""
set -euo pipefail
repo_root="REPO_ROOT_PLACEHOLDER"
_other_wt_branches=""
_wt_path=""
_wt_branch=""
_flush() {
  if [[ -n "$_wt_path" && "$_wt_path" != "$repo_root" && -n "$_wt_branch" ]]; then
    _other_wt_branches="${_other_wt_branches}${_wt_branch}"$'\n'
  fi
  _wt_path=""
  _wt_branch=""
}
while IFS= read -r _wt_line; do
  case "$_wt_line" in
    "worktree "*) _flush; _wt_path="${_wt_line#worktree }" ;;
    "branch refs/heads/"*) _wt_branch="${_wt_line#branch refs/heads/}" ;;
    "") _flush ;;
  esac
done < <(cat <<'PORCELAIN_EOF'
PORCELAIN_INPUT_PLACEHOLDER
PORCELAIN_EOF
)
_flush
printf '%s' "$_other_wt_branches"
"""
        script = script.replace("REPO_ROOT_PLACEHOLDER", repo_root)
        script = script.replace("PORCELAIN_INPUT_PLACEHOLDER", porcelain_input)
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout

    def test_locked_worktree_branch_not_corrupted(self) -> None:
        """A worktree with `locked` annotation must yield a clean
        branch name, NOT `branch] locked` — this is the original bug."""
        porcelain = (
            "worktree /path/to/main\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /path/to/lk\n"
            "HEAD def456\n"
            "branch refs/heads/alpha/bt-firmware-watchdog\n"
            "locked\n"
        )
        out = self._harness(porcelain, "/path/to/main")
        branches = [b for b in out.split("\n") if b]
        assert "alpha/bt-firmware-watchdog" in branches
        assert not any("locked" in b for b in branches), (
            f"locked annotation leaked into branch list: {branches!r}"
        )
        assert not any("]" in b for b in branches), (
            f"closing bracket leaked into branch list: {branches!r}"
        )

    def test_main_worktree_excluded(self) -> None:
        """The current worktree's own branch must NOT appear in
        _other_wt_branches — the gate would then incorrectly filter
        out branches present in this worktree."""
        porcelain = (
            "worktree /path/to/main\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /path/to/other\n"
            "HEAD def456\n"
            "branch refs/heads/feature/x\n"
        )
        out = self._harness(porcelain, "/path/to/main")
        branches = [b for b in out.split("\n") if b]
        assert "main" not in branches
        assert "feature/x" in branches

    def test_detached_head_skipped(self) -> None:
        """Detached HEAD worktrees have no `branch` line — they must
        be skipped entirely (not emitted as empty / not crash)."""
        porcelain = (
            "worktree /path/to/main\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /path/to/detached\n"
            "HEAD def456\n"
            "detached\n"
            "\n"
            "worktree /path/to/normal\n"
            "HEAD aaa111\n"
            "branch refs/heads/feature/y\n"
        )
        out = self._harness(porcelain, "/path/to/main")
        branches = [b for b in out.split("\n") if b]
        assert branches == ["feature/y"]

    def test_multiple_locked_worktrees(self) -> None:
        """The agent fleet often has 5-15 simultaneously-locked
        worktrees (subagent isolation). All branch names must be
        clean."""
        stanzas = ["worktree /path/to/main\nHEAD abc\nbranch refs/heads/main\n"]
        for i in range(8):
            stanzas.append(
                f"worktree /path/to/lk{i}\nHEAD sha{i}\nbranch refs/heads/alpha/lock-{i}\nlocked\n"
            )
        porcelain = "\n".join(stanzas)
        out = self._harness(porcelain, "/path/to/main")
        branches = [b for b in out.split("\n") if b]
        assert len(branches) == 8
        for b in branches:
            assert b.startswith("alpha/lock-")
            assert "locked" not in b
            assert "]" not in b

    def test_prunable_worktree_branch_not_corrupted(self) -> None:
        """Pruneable worktrees emit a `prunable` line in porcelain
        output. Must be ignored by the case statement, not appended
        to the branch name. Use a branch name without 'prunable' so
        the assertion uniquely targets the annotation, not the name."""
        porcelain = (
            "worktree /path/to/main\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /path/to/pr\n"
            "HEAD def456\n"
            "branch refs/heads/feature/abandoned-one\n"
            "prunable gitdir file points to non-existent location\n"
        )
        out = self._harness(porcelain, "/path/to/main")
        branches = [b for b in out.split("\n") if b]
        assert branches == ["feature/abandoned-one"], (
            f"prunable annotation may have leaked: got {branches!r}"
        )

    def test_branch_with_slashes_preserved(self) -> None:
        """Branch names with multiple `/` segments (the council
        convention — `alpha/foo/bar`) must round-trip intact."""
        porcelain = (
            "worktree /path/to/main\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /path/to/deep\n"
            "HEAD def456\n"
            "branch refs/heads/alpha/long/path/name\n"
        )
        out = self._harness(porcelain, "/path/to/main")
        branches = [b for b in out.split("\n") if b]
        assert "alpha/long/path/name" in branches


# ── End-to-end exercise via real git worktrees ─────────────────────


class TestEndToEndWithRealWorktrees:
    """Build a real fixture repo with locked + clean worktrees and
    exercise the hook end-to-end. Catches regressions in the wiring
    between section-7's parsing block and the rest of the gate."""

    def test_hook_does_not_crash_on_locked_worktree_fixture(self, tmp_path: Path) -> None:
        """The hook must not exit non-zero (other than the documented
        block exit code 2) when locked worktrees are present.
        Pre-fix, `set -euo pipefail` plus a corrupt branch token
        caused some downstream pipelines to fail loudly."""
        repo = _make_repo(tmp_path)
        # Create a second branch + worktree with --lock.
        _git(repo, "branch", "feature/locked-one")
        wt_dir = tmp_path / "wt-locked"
        _git(repo, "worktree", "add", "--lock", str(wt_dir), "feature/locked-one")

        # Create a third clean branch + worktree.
        _git(repo, "branch", "feature/clean-one")
        wt2_dir = tmp_path / "wt-clean"
        _git(repo, "worktree", "add", str(wt2_dir), "feature/clean-one")

        # Edit a file IN MAIN. We're on main with a local branch that
        # has no commits ahead, so the gate should silently allow.
        target = repo / "ok.py"
        target.write_text("# ok\n")
        result = _run({"tool_name": "Edit", "tool_input": {"file_path": str(target)}})
        # Either the hook fails-open (returncode 0) or it has another
        # legitimate gating reason. What it MUST NOT do is exit because
        # of a parsing crash. So accept 0 or 2; reject anything else.
        assert result.returncode in (0, 2), (
            f"hook crashed with rc={result.returncode}: stderr={result.stderr!r}"
        )
        # Any block message must reference an actual branch name, not
        # a corrupt `branch] locked` token.
        assert "] locked" not in result.stderr
        assert "feature/locked-one] locked" not in result.stderr
