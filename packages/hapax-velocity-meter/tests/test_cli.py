"""Tests for CLI surface."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from hapax_velocity_meter.cli import main

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
    return repo


def test_cli_run_human_readable(tmp_path: Path, capsys) -> None:
    repo = _make_repo(tmp_path)
    rc = main(["run", "--repo", str(repo), "--days", "7"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "commits" in out
    assert "Methodology" in out


def test_cli_run_json(tmp_path: Path, capsys) -> None:
    repo = _make_repo(tmp_path)
    rc = main(["run", "--repo", str(repo), "--days", "7", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["commits"] == 1
    assert payload["window_days"] == 7


def test_cli_cite(capsys) -> None:
    rc = main(["cite"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "@misc{hapax_velocity_2026" in out


def test_cli_run_rejects_zero_window(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    rc = main(["run", "--repo", str(repo), "--days", "0"])
    assert rc == 2
