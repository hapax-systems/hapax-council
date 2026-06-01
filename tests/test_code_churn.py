"""Objective code-churn computation (Velocity:Quality Observatory phase 1).

The parser is tested deterministically against synthetic ``git log --numstat``
output; one integration test exercises the real ``git`` plumbing on a throwaway repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shared.code_churn import ChurnResult, compute_churn, parse_numstat


def test_parse_numstat_sums_additions_and_deletions() -> None:
    out = "abc123def0\n10\t2\tfile.py\n5\t0\tother.py\nfed321cba9\n0\t3\tfile.py\n"
    r = parse_numstat(out)
    assert r.commits == 2
    assert r.lines_added == 15
    assert r.lines_deleted == 5
    assert r.churn_ratio == 5 / 15


def test_parse_numstat_skips_binary_rows() -> None:
    out = "a1b2c3d4e5\n-\t-\timage.png\n4\t1\tcode.py\n"
    r = parse_numstat(out)
    assert r.commits == 1
    assert r.lines_added == 4
    assert r.lines_deleted == 1


def test_churn_ratio_zero_when_no_additions() -> None:
    assert ChurnResult(commits=1, lines_added=0, lines_deleted=9).churn_ratio == 0.0


def test_parse_empty_output() -> None:
    assert parse_numstat("") == ChurnResult(0, 0, 0)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def test_compute_churn_on_synthetic_repo(tmp_path: Path) -> None:
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git unavailable")
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    f = repo / "f.txt"
    f.write_text("a\nb\nc\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    f.write_text("a\nB\nc\nd\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "edit")

    r = compute_churn(repo, since="1970-01-01")
    assert r.commits == 2
    assert r.lines_added > 0
    assert r.lines_deleted > 0


def test_compute_churn_bad_repo_returns_zero(tmp_path: Path) -> None:
    # Not a git repo — git fails, parser sees empty output.
    assert compute_churn(tmp_path, since="1970-01-01") == ChurnResult(0, 0, 0)
