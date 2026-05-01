"""Tests for hooks/scripts/asset-provenance-gate.sh.

Pre-tool-use hook on Bash that gates ``git commit`` / ``git push``
when the staged/branch delta touches ``assets/aesthetic-library/``.
Delegates to ``scripts/verify-aesthetic-library.py`` for the actual
check; the hook's job is path-gating + error surfacing.

Tests cover the gating lattice:
- non-Bash tools / non-git-commit-or-push commands → exit 0
- outside a git repo → exit 0
- no verify script in repo → exit 0
- no assets dir in repo → exit 0
- staged delta does not touch aesthetic-library → exit 0
- staged delta DOES touch aesthetic-library + verify script absent
  → exit 0 (fail-open per docstring)
- uv not on PATH → exit 0 (dev-env sanity)

The actual subprocess.run of ``uv run python verify-aesthetic-library.py``
is the CI authority; tests don't invoke it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "asset-provenance-gate.sh"


def _run(
    payload: dict,
    cwd: Path,
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
        cwd=cwd,
        timeout=15,
    )


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _make_repo(
    tmp_path: Path,
    *,
    with_verify_script: bool = True,
    with_assets_dir: bool = True,
) -> Path:
    """Init a git repo with optional verify script + assets dir."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    if with_verify_script:
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "verify-aesthetic-library.py").write_text("#!/usr/bin/env python3\n")
    if with_assets_dir:
        assets = tmp_path / "assets" / "aesthetic-library"
        assets.mkdir(parents=True)
        (assets / "_manifest.yaml").write_text("# placeholder\n")
    # An initial commit so HEAD is valid.
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "root"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


# ── Tool gating ────────────────────────────────────────────────────


class TestToolGating:
    def test_edit_tool_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run({"tool_name": "Edit", "tool_input": {"file_path": "x"}}, cwd=repo)
        assert result.returncode == 0
        assert result.stderr == ""

    def test_write_tool_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run({"tool_name": "Write", "tool_input": {"file_path": "x"}}, cwd=repo)
        assert result.returncode == 0
        assert result.stderr == ""


# ── Command gating ─────────────────────────────────────────────────


class TestCommandGating:
    def test_ls_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run(_bash("ls -la"), cwd=repo)
        assert result.returncode == 0
        assert result.stderr == ""

    def test_git_status_silent(self, tmp_path: Path) -> None:
        """Other git subcommands don't trigger the gate."""
        repo = _make_repo(tmp_path)
        result = _run(_bash("git status"), cwd=repo)
        assert result.returncode == 0
        assert result.stderr == ""

    def test_git_add_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run(_bash("git add -A"), cwd=repo)
        assert result.returncode == 0
        assert result.stderr == ""


# ── Repo-level gating ──────────────────────────────────────────────


class TestRepoGating:
    def test_outside_git_repo_silent(self, tmp_path: Path) -> None:
        result = _run(_bash("git commit -m 'x'"), cwd=tmp_path)
        assert result.returncode == 0
        assert result.stderr == ""

    def test_no_verify_script_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, with_verify_script=False)
        result = _run(_bash("git commit -m 'x'"), cwd=repo)
        assert result.returncode == 0
        assert result.stderr == ""

    def test_no_assets_dir_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path, with_assets_dir=False)
        result = _run(_bash("git commit -m 'x'"), cwd=repo)
        assert result.returncode == 0
        assert result.stderr == ""


# ── Path-delta gating ──────────────────────────────────────────────


class TestPathDeltaGating:
    def test_commit_no_aesthetic_files_staged_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        # Stage a non-aesthetic file.
        (repo / "src.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "src.py"], cwd=repo, check=True)
        result = _run(_bash("git commit -m 'src only'"), cwd=repo)
        assert result.returncode == 0
        assert "BLOCKED" not in result.stderr

    def test_commit_with_aesthetic_files_staged_runs_verify(self, tmp_path: Path) -> None:
        """When the staged delta touches assets/aesthetic-library/, the
        hook progresses to the verify path. Without uv on PATH, it
        bails silently per the dev-env-sanity comment."""
        repo = _make_repo(tmp_path)
        new_asset = repo / "assets" / "aesthetic-library" / "newgroup" / "asset.txt"
        new_asset.parent.mkdir(parents=True)
        new_asset.write_text("placeholder\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        # Strip uv from PATH so the hook skips the actual verify subprocess.
        result = _run(
            _bash("git commit -m 'add asset'"),
            cwd=repo,
            extra_env={"PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0
        # The hook should have reached the path-delta gate but bailed
        # silently when uv was missing — no BLOCKED stderr.
        assert "BLOCKED" not in result.stderr
