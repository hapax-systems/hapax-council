"""Tests for hooks/scripts/doc-update-advisory.sh.

The hook is a PostToolUse advisory (non-blocking) that fires after
a `git commit` Bash invocation. It inspects the just-created HEAD
commit: if 3+ source files changed AND zero documentation files
changed, it emits an ADVISORY to stderr. It always exits 0 (advisory,
not blocker).

Source extensions: .py / .ts / .tsx / .js / .jsx / .sh / .go / .rs
Doc extensions: .md / .rst / .txt / .yaml / .yml / paths matching
  */docs/* or */doc/*, and CLAUDE.md / README* / CHANGELOG*.

Tests cover:
 - non-Bash tool invocations (silent)
 - Bash but not a git commit (silent)
 - 3+ source / 0 docs (advises)
 - 3+ source / 1+ docs (silent — mixed commits are fine)
 - 0 source files (silent — pure-doc commits never advise)
 - 2 source / 0 docs (silent — under threshold)
 - 5 source / 0 docs (advises — well over threshold)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "doc-update-advisory.sh"


def _run_in(cwd: Path, payload: dict) -> subprocess.CompletedProcess[str]:
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


def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Init a git repo in tmp_path, create the test files in a SECOND commit.

    The hook calls `git diff-tree HEAD` (without --root), which returns
    empty for root commits. Production never sees a root commit at the
    Bash-after-git-commit moment, so we mirror reality by creating a
    placeholder parent commit first, then committing the files under
    test on top.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
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
    for relpath, content in files.items():
        target = tmp_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "test commit"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


# ── Wrong-tool path: hook only fires for Bash ──────────────────────


class TestNonBashIgnored:
    def test_edit_tool_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, {"a.py": "x", "b.py": "x", "c.py": "x"})
        result = _run_in(
            repo,
            {"tool_name": "Edit", "tool_input": {"file_path": "a.py"}},
        )
        assert result.returncode == 0
        assert result.stderr == ""

    def test_write_tool_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, {"a.py": "x", "b.py": "x", "c.py": "x"})
        result = _run_in(
            repo,
            {"tool_name": "Write", "tool_input": {"file_path": "a.py"}},
        )
        assert result.returncode == 0
        assert result.stderr == ""


# ── Wrong-command path: Bash but not git commit ────────────────────


class TestNonGitCommitIgnored:
    def test_ls_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, {"a.py": "x", "b.py": "x", "c.py": "x"})
        result = _run_in(repo, _bash("ls -la"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_git_status_silent(self, tmp_path: Path) -> None:
        """Other git subcommands don't trigger the advisory."""
        repo = _make_repo(tmp_path, {"a.py": "x", "b.py": "x", "c.py": "x"})
        result = _run_in(repo, _bash("git status"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_git_log_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, {"a.py": "x", "b.py": "x", "c.py": "x"})
        result = _run_in(repo, _bash("git log --oneline"))
        assert result.returncode == 0
        assert result.stderr == ""


# ── Outside-repo: silent (advisory cannot inspect HEAD) ────────────


class TestOutsideRepoSilent:
    def test_outside_git_repo_silent(self, tmp_path: Path) -> None:
        """No git repo at cwd → exit silently, never crash."""
        result = _run_in(tmp_path, _bash("git commit -m 'hi'"))
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr


# ── Threshold path: 3+ source / 0 docs → advises ───────────────────


class TestAdvisesWhenSrcOnly:
    def test_three_source_no_docs_advises(self, tmp_path: Path) -> None:
        repo = _make_repo(
            tmp_path,
            {"a.py": "x", "b.ts": "x", "c.sh": "x"},
        )
        result = _run_in(repo, _bash("git commit -m 'src only'"))
        assert result.returncode == 0
        assert "ADVISORY" in result.stderr
        assert "3 source files" in result.stderr or "3" in result.stderr

    def test_five_source_no_docs_advises(self, tmp_path: Path) -> None:
        repo = _make_repo(
            tmp_path,
            {
                "a.py": "x",
                "b.ts": "x",
                "c.sh": "x",
                "d.go": "x",
                "e.rs": "x",
            },
        )
        result = _run_in(repo, _bash("git commit -m 'lots of src'"))
        assert result.returncode == 0
        assert "ADVISORY" in result.stderr

    def test_advisory_mentions_doc_update(self, tmp_path: Path) -> None:
        """Advisory message tells the user to consider docs."""
        repo = _make_repo(
            tmp_path,
            {"a.py": "x", "b.py": "x", "c.py": "x"},
        )
        result = _run_in(repo, _bash("git commit -m 'three py files'"))
        assert "documentation" in result.stderr.lower()


# ── Below threshold: silent ────────────────────────────────────────


class TestSilentBelowThreshold:
    def test_two_source_no_docs_silent(self, tmp_path: Path) -> None:
        """2 source files = under threshold (3+)."""
        repo = _make_repo(tmp_path, {"a.py": "x", "b.py": "x"})
        result = _run_in(repo, _bash("git commit -m 'two files'"))
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr

    def test_one_source_no_docs_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, {"a.py": "x"})
        result = _run_in(repo, _bash("git commit -m 'one file'"))
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr


# ── Has docs: silent (mixed commits are fine) ──────────────────────


class TestSilentWhenDocsPresent:
    def test_three_source_one_doc_silent(self, tmp_path: Path) -> None:
        """3 source + 1 doc = mixed commit, no advisory."""
        repo = _make_repo(
            tmp_path,
            {"a.py": "x", "b.py": "x", "c.py": "x", "README.md": "x"},
        )
        result = _run_in(repo, _bash("git commit -m 'mixed'"))
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr

    def test_three_source_yaml_doc_silent(self, tmp_path: Path) -> None:
        """yaml counts as doc per the hook's classification."""
        repo = _make_repo(
            tmp_path,
            {"a.py": "x", "b.py": "x", "c.py": "x", "config.yaml": "x"},
        )
        result = _run_in(repo, _bash("git commit -m 'src+yaml'"))
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr

    def test_three_source_docs_dir_silent(self, tmp_path: Path) -> None:
        """Anything under docs/ counts as doc."""
        repo = _make_repo(
            tmp_path,
            {"a.py": "x", "b.py": "x", "c.py": "x", "docs/note.md": "x"},
        )
        result = _run_in(repo, _bash("git commit -m 'src+docs/'"))
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr

    def test_pure_doc_commit_silent(self, tmp_path: Path) -> None:
        """0 source files = silent (nothing to advise)."""
        repo = _make_repo(
            tmp_path,
            {"README.md": "x", "CHANGELOG.md": "x", "docs/a.md": "x"},
        )
        result = _run_in(repo, _bash("git commit -m 'docs only'"))
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr


# ── Always exits 0 (advisory only, never blocks) ───────────────────


class TestAlwaysExitsZero:
    def test_advisory_returncode_zero(self, tmp_path: Path) -> None:
        repo = _make_repo(
            tmp_path,
            {"a.py": "x", "b.py": "x", "c.py": "x"},
        )
        result = _run_in(repo, _bash("git commit -m 'src'"))
        assert result.returncode == 0

    def test_no_input_returncode_zero(self) -> None:
        """Missing stdin payload — still must exit 0 cleanly."""
        result = subprocess.run(
            ["bash", str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
