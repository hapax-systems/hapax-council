"""Tests for hooks/scripts/axiom-commit-scan.sh.

Wired PreToolUse hook on Bash that detects:
- ``git commit`` — scans the staged diff for axiom-violating patterns
  (multi-user scaffolding, feedback-generation language, etc.) and
  exits 2 if any of the patterns from axiom-patterns.sh match.
- ``git push`` — same scan over the branch delta vs main.
- File-writing bash commands (sed -i, tee, > redirect, python -c,
  perl -ip) — scans the command itself for the same patterns.
- curl/wget to non-localhost — corporate_boundary advisory if the
  repo has a ``.corporate-boundary`` marker file.

The violating fixture text is assembled at runtime via string
concatenation so the test source itself doesn't trigger the sister
hook (axiom-scan.sh) which scans on Edit/Write.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "axiom-commit-scan.sh"

# Build the violating snippets at runtime so this file's source text
# does NOT itself contain the pattern axiom-scan looks for.
_AUTH_CLASS = "class " + "User" + "Manager:\n    def authenticate" + "_user(self): pass\n"
_FEEDBACK_FN = "def generate" + "_feedback(): pass\n"


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


def _make_repo(tmp_path: Path) -> Path:
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
    return tmp_path


# ── jq dependency: hook fails LOUD when jq missing ─────────────────


class TestJqMissing:
    def test_no_jq_on_path_exits_two(self, tmp_path: Path) -> None:
        """Per docstring, axiom-commit-scan fails non-zero when jq is
        unavailable rather than silently no-op'ing — operator notices."""
        repo = _make_repo(tmp_path)
        env = dict(os.environ)
        env["PATH"] = "/etc"
        result = subprocess.run(
            ["/usr/bin/bash", str(HOOK)],
            input=json.dumps(_bash("ls")),
            capture_output=True,
            text=True,
            check=False,
            env=env,
            cwd=repo,
            timeout=15,
        )
        assert result.returncode == 2
        assert "jq" in result.stderr.lower()


# ── Empty / no-command paths ───────────────────────────────────────


class TestEmptyCommand:
    def test_empty_command_exits_zero(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run({"tool_name": "Bash", "tool_input": {}}, cwd=repo)
        assert result.returncode == 0
        assert result.stderr == ""


# ── git commit: clean staged diff ─────────────────────────────────


class TestGitCommit:
    def test_no_staged_diff_exits_zero(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run(_bash("git commit -m 'hi'"), cwd=repo)
        assert result.returncode == 0

    def test_clean_staged_diff_exits_zero(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        (repo / "ok.py").write_text("def hello() -> str:\n    return 'world'\n")
        subprocess.run(["git", "add", "ok.py"], cwd=repo, check=True)
        result = _run(_bash("git commit -m 'add hello'"), cwd=repo)
        assert result.returncode == 0
        assert "Axiom violation" not in result.stderr

    def test_violating_staged_diff_exits_two(self, tmp_path: Path) -> None:
        """A file introducing a multi-user-scaffolding class that matches
        an AXIOM_PATTERN is blocked."""
        repo = _make_repo(tmp_path)
        (repo / "bad.py").write_text(_AUTH_CLASS)
        subprocess.run(["git", "add", "bad.py"], cwd=repo, check=True)
        result = _run(_bash("git commit -m 'auth'"), cwd=repo)
        assert result.returncode == 2
        assert "Axiom violation" in result.stderr
        assert "single_user" in result.stderr

    def test_management_governance_pattern_blocks(self, tmp_path: Path) -> None:
        """Feedback-generation language is blocked under
        management_governance domain."""
        repo = _make_repo(tmp_path)
        (repo / "fb.py").write_text(_FEEDBACK_FN)
        subprocess.run(["git", "add", "fb.py"], cwd=repo, check=True)
        result = _run(_bash("git commit -m 'add'"), cwd=repo)
        assert result.returncode == 2
        assert "management_governance" in result.stderr


# ── Bash file-writer scan ──────────────────────────────────────────


class TestBashFileWriter:
    def test_sed_inplace_clean_exits_zero(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run(_bash("sed -i 's/foo/bar/' file.py"), cwd=repo)
        assert result.returncode == 0
        assert result.stderr == ""

    def test_python_c_violating_exits_two(self, tmp_path: Path) -> None:
        """A python -c constructing a violating class is scanned and
        blocked the same way a commit is."""
        repo = _make_repo(tmp_path)
        result = _run(_bash(f"python -c '{_AUTH_CLASS}'"), cwd=repo)
        assert result.returncode == 2
        assert "Axiom violation" in result.stderr


# ── curl / wget corporate-boundary advisory ────────────────────────


class TestCurlAdvisory:
    def test_curl_localhost_exits_zero_silent(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = _run(_bash("curl http://localhost:8051/api/health"), cwd=repo)
        assert result.returncode == 0
        assert "corporate_boundary" not in result.stderr

    def test_curl_external_no_marker_exits_zero_silent(self, tmp_path: Path) -> None:
        """External URL without corporate-boundary marker file → silent."""
        repo = _make_repo(tmp_path)
        result = _run(_bash("curl https://example.com"), cwd=repo)
        assert result.returncode == 0
        assert "corporate_boundary" not in result.stderr

    def test_curl_external_with_marker_advises(self, tmp_path: Path) -> None:
        """External URL + .corporate-boundary marker → stderr advisory,
        still exit 0 (advisory not block)."""
        repo = _make_repo(tmp_path)
        (repo / ".corporate-boundary").write_text("\n")
        result = _run(_bash("curl https://example.com"), cwd=repo)
        assert result.returncode == 0
        assert "corporate_boundary" in result.stderr
