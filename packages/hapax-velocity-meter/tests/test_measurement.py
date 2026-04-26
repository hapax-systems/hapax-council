"""Tests for measurement primitives."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from hapax_velocity_meter.measurement import VelocityReport, measure_repo

if TYPE_CHECKING:
    from pathlib import Path


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.org"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "a.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=repo, check=True)
    (repo / "a.txt").write_text("hello\nworld\n")
    subprocess.run(["git", "commit", "-q", "-am", "second"], cwd=repo, check=True)
    return repo


def test_measure_repo_counts_commits(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    report = measure_repo(repo=repo, window_days=7)
    assert isinstance(report, VelocityReport)
    assert report.commits == 2
    assert report.distinct_authors == 1
    assert report.commits_per_day == pytest.approx(2 / 7, rel=1e-3)


def test_measure_repo_rejects_non_git(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        measure_repo(repo=tmp_path, window_days=7)


def test_measure_repo_rejects_zero_window(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    with pytest.raises(ValueError):
        measure_repo(repo=repo, window_days=0)


def test_measure_repo_churn_nonnegative(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    report = measure_repo(repo=repo, window_days=7)
    assert report.additions >= 0
    assert report.deletions >= 0
    assert report.loc_churn_per_day >= 0
