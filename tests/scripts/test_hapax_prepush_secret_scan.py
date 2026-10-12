"""The scan-before-push hook refuses secret-shaped strings and home paths, passes clean pushes,
and honours only an explicit local exemption. Runs detect-secrets for real (via PATH or uvx)."""

from __future__ import annotations

import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "prepush_secret_scan.py"
ZERO = "0" * 40


pytestmark = pytest.mark.skipif(
    not (shutil.which("detect-secrets") or shutil.which("uvx")),
    reason="needs detect-secrets or uvx on PATH",
)


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """Never inherit the operator's hooks, signing, Git directory, or config."""
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    template = tmp_path / "empty-template"
    template.mkdir()
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(template))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("clean\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


def _run(repo: Path, remote: str, refs: str) -> subprocess.CompletedProcess:
    try:
        destination = _git(repo, "remote", "get-url", "--push", remote)
    except subprocess.CalledProcessError:
        destination = (
            ""  # Direct protocol tests with no configured destination scan conservatively.
        )
    return subprocess.run(
        [sys.executable, str(SCRIPT), remote, destination],
        cwd=repo,
        input=refs,
        capture_output=True,
        text=True,
        timeout=900,
    )


def test_deletion_pushes_nothing_and_passes(tmp_path):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    r = _run(repo, "origin", f"(delete) {ZERO} refs/heads/old {base}\n")
    assert r.returncode == 0, r.stderr


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def clean_detector(tmp_path, monkeypatch):
    bin_dir = tmp_path / "clean-detector"
    bin_dir.mkdir()
    _executable(
        bin_dir / "detect-secrets",
        '#!/bin/sh\nprintf \'%s\\n\' \'{"version": "1.5.0", "results": {}}\'\n',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return bin_dir


def _publish_base(repo: Path, tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-q", "-b", "main", str(remote))
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    assert _git(repo, "rev-parse", "refs/remotes/origin/main") == _git(remote, "rev-parse", "main")
    return remote


def _published_feature(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = _repo(tmp_path)
    remote = _publish_base(repo, tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature")
    base = _commit(repo, "feature.txt", "published feature\n")
    _git(repo, "push", "-q", "origin", "feature")
    return repo, remote, base


def _feature_scan(repo: Path, base: str) -> subprocess.CompletedProcess:
    tip = _git(repo, "rev-parse", "HEAD")
    return _run(repo, "origin", f"refs/heads/feature {tip} refs/heads/feature {base}\n")


SEPARATORS = ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\r"]
SEPARATOR_IDS = ["vt", "ff", "fs", "gs", "rs", "nel", "ls", "ps", "cr"]


@pytest.mark.parametrize("content", ["ordinary content", "sensitive-looking content"])
def test_preparation_content_cannot_pass_without_detector(tmp_path, content):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    tip = _commit(repo, "probe.txt", content + "\n")
    result = _run(repo, "origin", f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert result.returncode == 3
    assert "REFUSED [detector-not-composed]" in result.stderr
    assert "Remedy:" in result.stderr
    assert content not in result.stdout + result.stderr


def test_preparation_history_keeps_intermediate_exposure(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    middle = _commit(repo, "probe.txt", "introduced content\n")
    tip = _commit(repo, "probe.txt", "replaced content\n")
    scanner = runpy.run_path(str(SCRIPT))
    monkeypatch.chdir(repo)
    assert scanner["pushed_commits"]([base], tip) == [middle, tip]
    assert scanner["commit_additions"](middle) == (
        ["probe.txt"],
        set(),
        {"probe.txt": [(1, "introduced content")]},
    )
    assert scanner["pushed_commits"]([tip], tip) == []


def test_preparation_unavailable_destination_does_not_use_cached_refs(
    tmp_path, monkeypatch, capsys
):
    repo = _repo(tmp_path)
    tip = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", tip)
    scanner = runpy.run_path(str(SCRIPT))
    monkeypatch.chdir(repo)
    assert scanner["remote_commits"](str(tmp_path / "missing.git")) == []
    assert scanner["pushed_commits"]([], tip) == [tip]
    assert "without cached exclusions" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["has space.txt", ":(glob)*.txt", "line\nname.txt"])
def test_preparation_literal_transport_preserves_paths(tmp_path, monkeypatch, name):
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "other.txt").write_text("unrelated addition\n")
    tip = _commit(repo, name, "new line\n")
    scanner = runpy.run_path(str(SCRIPT))
    monkeypatch.chdir(repo)
    assert sorted(scanner["changed_files"](base, tip)) == sorted([name, "other.txt"])
    assert scanner["added_lines"](base, tip, [name]) == {name: [(1, "new line")]}
