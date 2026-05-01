"""Tests for hooks/scripts/docs-only-pr-warn.sh.

The hook is a PreToolUse advisory: when `git commit` on a feature
branch is about to commit only docs-sentinel-matching files (docs/**,
root *.md, lab-journal/**, research/**, axioms/**.md), it emits a
stderr advisory confirming the docs-only CI sentinels will fire. Never
blocks. The hook was untested.

Pattern matches `tests/hooks/test_doc_update_advisory.py` — per-test
temp git repos seeded with staged-but-not-committed files, hook fired
against the simulated `git commit` invocation.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "docs-only-pr-warn.sh"


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


def _make_repo(tmp_path: Path, *, branch: str = "feature/x") -> Path:
    """Init a git repo at tmp_path, create the branch, return repo root."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    # Initial commit on main so HEAD exists.
    (tmp_path / ".gitignore").write_text("\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_path, check=True, env=env)
    if branch != "main":
        subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=tmp_path, check=True)
    return tmp_path


def _stage(repo: Path, files: dict[str, str]) -> None:
    for path, body in files.items():
        full = repo / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)


# ── Pass-through: tool / cmd / branch / non-staged shape ───────────


class TestPassthrough:
    def test_passes_through_non_bash(self) -> None:
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_passes_through_empty_cmd(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {}})
        assert result.returncode == 0

    def test_passes_through_non_commit_cmd(self) -> None:
        result = _run(_bash("git status"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_passes_through_outside_git_repo(self, tmp_path: Path) -> None:
        result = _run(_bash("git commit -m 'x'"), cwd=tmp_path)
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr

    def test_passes_through_on_main_branch(self, tmp_path: Path) -> None:
        """Hook fires only on feature branches; main commits are out-of-scope."""
        repo = _make_repo(tmp_path, branch="main")
        _stage(repo, {"docs/foo.md": "# x"})
        result = _run(_bash("git commit -m 'docs'"), cwd=repo)
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr

    def test_passes_through_with_no_staged_files(self, tmp_path: Path) -> None:
        """Empty stage → no advisory (the commit will fail anyway)."""
        repo = _make_repo(tmp_path)
        result = _run(_bash("git commit -m 'empty'"), cwd=repo)
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr


# ── Active path: all-docs-sentinel staged set fires advisory ───────


class TestAdvisoryActive:
    def test_advises_on_docs_only_path(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _stage(repo, {"docs/foo.md": "# x", "docs/bar.md": "# y"})
        result = _run(_bash("git commit -m 'docs only'"), cwd=repo)
        assert result.returncode == 0
        assert "ADVISORY" in result.stderr
        assert "Docs-only commit" in result.stderr

    def test_advises_on_root_md_only(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _stage(repo, {"README.md": "# r", "CHANGELOG.md": "# c"})
        result = _run(_bash("git commit -m 'root md'"), cwd=repo)
        assert "ADVISORY" in result.stderr

    def test_advises_on_research_only(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _stage(repo, {"research/2026-05-01-note.md": "# r"})
        result = _run(_bash("git commit -m 'research'"), cwd=repo)
        assert "ADVISORY" in result.stderr

    def test_advises_on_axioms_md_only(self, tmp_path: Path) -> None:
        """`axioms/**/*.md` is a docs sentinel; axioms/*.py is not."""
        repo = _make_repo(tmp_path)
        _stage(repo, {"axioms/x.md": "# x"})
        result = _run(_bash("git commit -m 'axioms md'"), cwd=repo)
        assert "ADVISORY" in result.stderr

    def test_advises_on_lab_journal_only(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        _stage(repo, {"lab-journal/note.md": "# x"})
        result = _run(_bash("git commit -m 'lab'"), cwd=repo)
        assert "ADVISORY" in result.stderr


# ── Quiet path: mixed staged set ───────────────────────────────────


class TestQuietWhenMixed:
    def test_no_advisory_when_python_alongside_docs(self, tmp_path: Path) -> None:
        """1 .py + 1 .md → not all-docs → no advisory; CI runs full."""
        repo = _make_repo(tmp_path)
        _stage(repo, {"agent.py": "x = 1\n", "docs/note.md": "# x"})
        result = _run(_bash("git commit -m 'mixed'"), cwd=repo)
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr

    def test_no_advisory_for_nested_md_outside_sentinel(self, tmp_path: Path) -> None:
        """`agents/foo/README.md` is NOT a sentinel path (not docs/, not root,
        not lab-journal/, not research/, not axioms/)."""
        repo = _make_repo(tmp_path)
        _stage(repo, {"agents/foo/README.md": "# x"})
        result = _run(_bash("git commit -m 'agent doc'"), cwd=repo)
        assert result.returncode == 0
        assert "ADVISORY" not in result.stderr


# ── Quoted-string false-positive avoidance ─────────────────────────


class TestQuotedStringFalsePositives:
    def test_quoted_git_commit_in_message_does_not_trigger(self, tmp_path: Path) -> None:
        """A `git commit -m '... git commit ...'` should fire because the
        outer command IS a commit; but the inner reference shouldn't
        cause double-fire or weird behavior. This pins the no-double-fire
        semantic."""
        repo = _make_repo(tmp_path)
        _stage(repo, {"docs/x.md": "# x"})
        result = _run(_bash("git commit -m 'feat: explain git commit semantics'"), cwd=repo)
        assert result.returncode == 0
        assert result.stderr.count("ADVISORY") == 1


# ── Hook integrity ─────────────────────────────────────────────────


class TestHookIntegrity:
    def test_hook_is_executable(self) -> None:
        import os

        assert os.access(HOOK, os.X_OK)

    def test_hook_uses_strict_bash(self) -> None:
        body = HOOK.read_text(encoding="utf-8")
        assert body.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in body

    def test_hook_is_advisory_only(self) -> None:
        """Pin: hook never returns non-zero. Advisory hooks must not block
        legitimate docs-only commits."""
        body = HOOK.read_text(encoding="utf-8")
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("exit "):
                assert stripped.endswith("0"), f"advisory hook must only `exit 0`: {line!r}"
