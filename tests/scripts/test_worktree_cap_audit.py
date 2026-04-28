"""Tests for worktree cap classification."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "worktree-cap-audit.sh"


def test_claude_worktrees_are_infrastructure_not_session_slots(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_git = bin_dir / "git"
    fake_git.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "rev-parse" ]; then
  exit 0
fi
if [ "$1" = "worktree" ] && [ "$2" = "list" ]; then
  cat <<'EOF'
/home/hapax/projects/hapax-council  abc123 [main]
/home/hapax/projects/hapax-council--beta  abc123 [beta]
/home/hapax/projects/hapax-council--delta-feature  abc123 [delta]
/home/hapax/projects/hapax-council--epsilon-feature  abc123 [epsilon]
/home/hapax/projects/hapax-council/.claude/worktrees/task-a  abc123 [task-a]
EOF
  exit 0
fi
exit 1
"""
    )
    fake_git.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert '"infra": 1' in result.stdout
    assert '"session_total": 4' in result.stdout
    assert '"status": "ok"' in result.stdout


def test_codex_visible_worktrees_are_counted_as_first_class_sessions(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_git = bin_dir / "git"
    fake_git.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "rev-parse" ]; then
  exit 0
fi
if [ "$1" = "worktree" ] && [ "$2" = "list" ]; then
  cat <<'EOF'
/home/hapax/projects/hapax-council  abc123 [main]
/home/hapax/projects/hapax-council--cx-green  abc123 [codex/cx-green]
/home/hapax/projects/hapax-council--cx-amber  abc123 [codex/cx-amber]
/home/hapax/projects/.codex/worktrees/scratch  abc123 [scratch]
EOF
  exit 0
fi
exit 1
"""
    )
    fake_git.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert '"codex": 2' in result.stdout
    assert '"infra": 1' in result.stdout
    assert '"session_total": 3' in result.stdout
    assert '"status": "ok"' in result.stdout
