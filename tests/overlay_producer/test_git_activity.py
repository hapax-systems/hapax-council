"""Tests for ``agents.overlay_producer.git_activity``.

Coverage:

- ``_git_log`` parsing: well-formed lines emit GitCommit records, malformed
  lines are skipped, empty stdout yields empty list.
- Subprocess error paths: timeout / non-zero exit / OSError → empty list
  (degraded empty-state).
- Missing-git PATH → empty list without invoking subprocess.
- Missing ``.git`` directory → empty list.
- ``_format_body`` truncates long subjects with ``…`` and stays under
  the repo-wide body cap.
- ``GitActivitySource.collect`` emits ``TextEntry`` objects with
  ``[GIT] <hash7> <subject>`` body, ``context_keys=["main"]``, and id
  derived from the commit sha.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from agents.overlay_producer.git_activity import (
    DEFAULT_MAX_SUBJECT_LEN,
    GitActivitySource,
    GitCommit,
    _format_body,
    _git_log,
)


def _stub_runner(
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
    raises: Exception | None = None,
):
    """Build a fake subprocess.run replacement."""

    def runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        if raises is not None:
            raise raises
        del args, kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return runner


def _make_git_dir(tmp_path: Path) -> Path:
    """Create a fake ``.git`` directory so the path-existence check passes."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    return repo


# ── _git_log ─────────────────────────────────────────────────────────────


class TestGitLogParsing:
    def test_wellformed_lines_parse(self, tmp_path: Path) -> None:
        repo = _make_git_dir(tmp_path)
        stdout = (
            "abcd1234abcd1234abcd1234abcd1234abcd1234\t1700000000\tFirst commit\n"
            "fedc4321fedc4321fedc4321fedc4321fedc4321\t1700001000\tSecond"
        )
        commits = _git_log(
            repo,
            since_seconds=3600,
            max_commits=8,
            runner=_stub_runner(stdout=stdout),
        )
        assert len(commits) == 2
        assert commits[0].sha.startswith("abcd1234")
        assert commits[0].subject == "First commit"
        assert commits[0].timestamp == pytest.approx(1700000000)
        assert commits[1].subject == "Second"

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        repo = _make_git_dir(tmp_path)
        stdout = (
            "abcd1234\t1700000000\tValid\n"
            "no-tabs-here\n"  # missing tab separator → 1 part
            "fedc4321\tnot-a-number\tBadTimestamp\n"  # ts parse fails
            "\t\tEmpty\n"  # empty sha and subject (subject "Empty" but sha "")
            "wxyz9999\t1700002000\tValid2"
        )
        commits = _git_log(
            repo,
            since_seconds=3600,
            max_commits=8,
            runner=_stub_runner(stdout=stdout),
        )
        subjects = [c.subject for c in commits]
        assert subjects == ["Valid", "Valid2"]

    def test_empty_stdout_yields_empty_list(self, tmp_path: Path) -> None:
        repo = _make_git_dir(tmp_path)
        commits = _git_log(
            repo,
            since_seconds=3600,
            max_commits=8,
            runner=_stub_runner(stdout=""),
        )
        assert commits == []

    def test_nonzero_exit_yields_empty(self, tmp_path: Path) -> None:
        repo = _make_git_dir(tmp_path)
        commits = _git_log(
            repo,
            since_seconds=3600,
            max_commits=8,
            runner=_stub_runner(stdout="ignored", returncode=128, stderr="bad ref"),
        )
        assert commits == []

    def test_subprocess_oserror_yields_empty(self, tmp_path: Path) -> None:
        repo = _make_git_dir(tmp_path)
        commits = _git_log(
            repo,
            since_seconds=3600,
            max_commits=8,
            runner=_stub_runner(raises=OSError("boom")),
        )
        assert commits == []

    def test_subprocess_timeout_yields_empty(self, tmp_path: Path) -> None:
        repo = _make_git_dir(tmp_path)
        commits = _git_log(
            repo,
            since_seconds=3600,
            max_commits=8,
            runner=_stub_runner(raises=subprocess.TimeoutExpired(cmd="git", timeout=10.0)),
        )
        assert commits == []

    def test_no_git_directory_yields_empty(self, tmp_path: Path) -> None:
        """If the path has no ``.git`` AND no ``HEAD`` (bare-repo proxy),
        ``_git_log`` short-circuits without invoking subprocess."""
        invoked = {"n": 0}

        def runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
            invoked["n"] += 1
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="")

        commits = _git_log(
            tmp_path / "no-such-repo",
            since_seconds=3600,
            max_commits=8,
            runner=runner,
        )
        assert commits == []
        assert invoked["n"] == 0


# ── _format_body ─────────────────────────────────────────────────────────


class TestFormatBody:
    def test_short_subject_passes_through(self) -> None:
        commit = GitCommit(
            sha="abcd1234abcd1234abcd1234abcd1234abcd1234",
            subject="Short subject",
            timestamp=1700000000.0,
        )
        body = _format_body(commit, max_subject_len=DEFAULT_MAX_SUBJECT_LEN)
        assert body == "[GIT] abcd123 Short subject"

    def test_long_subject_truncated_with_ellipsis(self) -> None:
        long_subject = "x" * 200
        commit = GitCommit(
            sha="abcd1234abcd1234abcd1234abcd1234abcd1234",
            subject=long_subject,
            timestamp=1700000000.0,
        )
        body = _format_body(commit, max_subject_len=DEFAULT_MAX_SUBJECT_LEN)
        # Hash prefix + space = 13 chars, then up to max_subject_len with "…".
        assert body.startswith("[GIT] abcd123 ")
        assert body.endswith("…")
        # Total subject portion ≤ max_subject_len.
        assert len(body) - len("[GIT] abcd123 ") <= DEFAULT_MAX_SUBJECT_LEN


# ── GitActivitySource.collect ────────────────────────────────────────────


class TestGitActivitySource:
    def test_emits_textentry_per_commit(self, tmp_path: Path) -> None:
        repo = _make_git_dir(tmp_path)
        stdout = (
            "11112222333344445555666677778888aaaabbbb\t1700000000\tAdd thing\n"
            "ccccdddd1111222233334444aaaabbbbccccdddd\t1700001000\tFix bug"
        )
        source = GitActivitySource(repo_path=repo, runner=_stub_runner(stdout=stdout))
        entries = source.collect(now=1700002000.0)
        assert len(entries) == 2
        assert entries[0].id.startswith("11112222")
        assert entries[0].body == "[GIT] 1111222 Add thing"
        assert entries[0].context_keys == ["main"]
        assert entries[0].tags == ["git"]
        assert entries[1].body == "[GIT] ccccddd Fix bug"

    def test_empty_when_no_repo(self, tmp_path: Path) -> None:
        source = GitActivitySource(
            repo_path=tmp_path / "absent",
            runner=_stub_runner(stdout="ignored"),
        )
        assert source.collect(now=1700000000.0) == []

    def test_empty_when_subprocess_errors(self, tmp_path: Path) -> None:
        repo = _make_git_dir(tmp_path)
        source = GitActivitySource(
            repo_path=repo,
            runner=_stub_runner(returncode=128, stderr="not a repo"),
        )
        assert source.collect(now=1700000000.0) == []
