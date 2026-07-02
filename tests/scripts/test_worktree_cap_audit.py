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


def test_agy_visible_worktrees_are_counted_as_first_class_not_spontaneous(tmp_path: Path) -> None:
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
/home/hapax/projects/hapax-council--agy  abc123 [agy]
/home/hapax/projects/hapax-council--agy-2  abc123 [agy-2]
/home/hapax/projects/hapax-council--task-demo  abc123 [task-demo]
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
    assert '"agy": 2' in result.stdout
    assert '"spontaneous": 1' in result.stdout
    assert '"session_total": 4' in result.stdout
    assert '"status": "ok"' in result.stdout


def test_malformed_agy_prefixed_worktree_is_spontaneous_not_agy(tmp_path: Path) -> None:
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
/home/hapax/projects/hapax-council--agyity  abc123 [agyity]
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
    assert '"agy": 0' in result.stdout
    assert '"spontaneous": 1' in result.stdout
    assert '"session_total": 2' in result.stdout


def test_relocated_infra_on_data_mount_is_not_counted(tmp_path: Path) -> None:
    """Infra that moved off ~/.cache to /data2/data/cache + /store + source-activation
    must NOT count as session worktrees (2026-06-27 false over-cap regression)."""
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
/data2/data/cache/hapax/rebuild/worktree  abc123 (detached HEAD)
/data2/data/cache/hapax/scratch/eval-batch  abc123 [cc/eval-batch]
/data2/data/cache/hapax/source-activation/releases/deadbeef  abc123 (detached HEAD)
/var/lib/hapax/source-activation/releases/feedf00d  abc123 (detached HEAD)
/store/llm-data/runtime/health-monitor-source  abc123 (detached HEAD)
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
    # 5 infra: rebuild, scratch, release-under-cache/hapax, AND a standalone
    # source-activation path NOT under cache/hapax (exercises the source-activation
    # arm independently), plus the runtime source. 2 sessions (primary + cx-green).
    assert '"infra": 5' in result.stdout
    assert '"session_total": 2' in result.stdout
    assert '"unknown": 0' in result.stdout
    assert '"status": "ok"' in result.stdout
