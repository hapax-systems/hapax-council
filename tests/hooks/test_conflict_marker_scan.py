"""Tests for hooks/scripts/conflict-marker-scan.sh.

The hook is a PostToolUse advisory: after a git operation that can
produce conflicts (`stash apply`, `rebase`, `merge`, `cherry-pick`,
`pull`), it scans the working tree for conflict markers (``<<<<<<<``,
``=======``, ``>>>>>>>``) and emits a warning if any are found.
Non-blocking. The hook was untested.

Conflict markers in source files break running services on this rig
(logos-api SyntaxError, vite build failure), so this hook is a load-
bearing safety net.

Tests cover the early-exit pass-through paths + the active scan path
under per-test temp git repos seeded with synthetic conflict markers.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "conflict-marker-scan.sh"

CONFLICT_BODY = "x = 1\n<<<<<<< HEAD\nfoo\n=======\nbar\n>>>>>>> branch\ny = 2\n"


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


def _make_git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Init a git repo at tmp_path; commit files. Returns repo root."""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(
        ["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    for path, body in files.items():
        full = tmp_path / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "test"], cwd=tmp_path, check=True, env=env)
    return tmp_path


# ── Pass-through: tool / command shape doesn't match ───────────────


class TestPassthrough:
    def test_passes_through_non_bash(self) -> None:
        result = _run({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_passes_through_empty_command(self) -> None:
        result = _run({"tool_name": "Bash", "tool_input": {}})
        assert result.returncode == 0
        assert result.stderr == ""

    def test_passes_through_non_git_command(self) -> None:
        result = _run(_bash("ls -la"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_passes_through_non_conflict_git_command(self) -> None:
        """Hook only fires on stash apply / rebase / merge / cherry-pick / pull."""
        result = _run(_bash("git status"))
        assert result.returncode == 0
        assert result.stderr == ""

    def test_passes_through_outside_git_repo(self, tmp_path: Path) -> None:
        result = _run(_bash("git rebase main"), cwd=tmp_path)
        assert result.returncode == 0
        assert "WARNING" not in result.stderr


# ── Active scan path: trigger commands fire the scan ───────────────


class TestActiveScan:
    """The hook fires on these git subcommands; verify each triggers the scan."""

    def test_stash_apply_triggers(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path, {"src.py": CONFLICT_BODY})
        result = _run(_bash("git stash apply"), cwd=repo)
        assert "WARNING" in result.stderr
        assert "conflict markers" in result.stderr.lower()

    def test_rebase_triggers(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path, {"src.py": CONFLICT_BODY})
        result = _run(_bash("git rebase origin/main"), cwd=repo)
        assert "WARNING" in result.stderr

    def test_merge_triggers(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path, {"src.py": CONFLICT_BODY})
        result = _run(_bash("git merge feature-branch"), cwd=repo)
        assert "WARNING" in result.stderr

    def test_cherry_pick_triggers(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path, {"src.py": CONFLICT_BODY})
        result = _run(_bash("git cherry-pick abc123"), cwd=repo)
        assert "WARNING" in result.stderr

    def test_pull_triggers(self, tmp_path: Path) -> None:
        repo = _make_git_repo(tmp_path, {"src.py": CONFLICT_BODY})
        result = _run(_bash("git pull origin main"), cwd=repo)
        assert "WARNING" in result.stderr


# ── Quiet path: repo clean → no warning ────────────────────────────


class TestQuietWhenClean:
    def test_no_warning_when_repo_is_clean(self, tmp_path: Path) -> None:
        """Trigger command + clean repo → exit 0 silently."""
        repo = _make_git_repo(tmp_path, {"src.py": "x = 1\ny = 2\n"})
        result = _run(_bash("git rebase main"), cwd=repo)
        assert result.returncode == 0
        assert "WARNING" not in result.stderr

    def test_no_warning_for_partial_marker_lines(self, tmp_path: Path) -> None:
        """The hook greps for `^<<<<<<<` / `^=======$` / `^>>>>>>>` (BoL).
        Strings containing those substrings mid-line do NOT count as
        conflict markers — those are quoted text, not real conflicts."""
        repo = _make_git_repo(
            tmp_path,
            {
                "doc.py": '"""Document the conflict marker shape: <<<<<<< (start)."""\n',
            },
        )
        result = _run(_bash("git rebase main"), cwd=repo)
        assert result.returncode == 0
        assert "WARNING" not in result.stderr


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
        """Conflict-marker-scan is PostToolUse — operation already happened.
        Hook must never block."""
        body = HOOK.read_text(encoding="utf-8")
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("exit "):
                assert stripped.endswith("0"), f"advisory hook must only `exit 0`: {line!r}"

    def test_hook_lists_recovery_steps(self) -> None:
        """The warning message must list recovery steps so a human can act
        without grepping for the hook source."""
        body = HOOK.read_text(encoding="utf-8")
        assert "git stash drop" in body
        assert "git rebase --continue" in body
