from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-compositor-runtime-source-check"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "runtime-source@example.test")
    _git(repo, "config", "user.name", "Runtime Source")
    (repo / "required.txt").write_text("ok\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    return repo


def test_runtime_source_check_passes_for_expected_cwd_and_required_file(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    env = os.environ.copy()
    env["HAPAX_SOURCE_ACTIVATION_RECEIPT"] = str(tmp_path / "missing-current.json")

    result = subprocess.run(
        [str(SCRIPT), "--source-root", str(repo), "--require-file", "required.txt"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "OK: compositor runtime source root" in result.stdout


def test_runtime_source_check_fails_when_service_cwd_is_wrong(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    env = os.environ.copy()
    env["HAPAX_SOURCE_ACTIVATION_RECEIPT"] = str(tmp_path / "missing-current.json")

    result = subprocess.run(
        [str(SCRIPT), "--source-root", str(repo), "--require-file", "required.txt"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "service working directory" in result.stderr


def test_runtime_source_check_fails_when_required_file_missing(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    env = os.environ.copy()
    env["HAPAX_SOURCE_ACTIVATION_RECEIPT"] = str(tmp_path / "missing-current.json")

    result = subprocess.run(
        [str(SCRIPT), "--source-root", str(repo), "--require-file", "missing.txt"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    assert "required runtime source file missing" in result.stderr
