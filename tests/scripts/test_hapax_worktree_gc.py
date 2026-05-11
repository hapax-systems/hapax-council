"""Tests for stale Hapax worktree garbage collection."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-worktree-gc.sh"
SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-worktree-gc.service"
TIMER = REPO_ROOT / "systemd" / "units" / "hapax-worktree-gc.timer"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, path: str, body: str, message: str) -> None:
    file_path = repo / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(body, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-m", message)


def _age_path(path: Path, *, now: int, seconds_old: int) -> None:
    timestamp = now - seconds_old
    os.utime(path, (timestamp, timestamp))


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "hapax-council"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True)
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    _commit(repo, "README.md", "# test\n", "seed")
    return repo


def test_removes_old_clean_merged_worktrees_and_alerts_unmerged(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    now = int(time.time())

    merged = tmp_path / "hapax-council--merged-clean"
    dirty = tmp_path / "hapax-council--merged-dirty"
    unmerged = tmp_path / "hapax-council--unmerged"

    _git(repo, "branch", "merged-clean", "main")
    _git(repo, "worktree", "add", str(merged), "merged-clean")

    _git(repo, "branch", "merged-dirty", "main")
    _git(repo, "worktree", "add", str(dirty), "merged-dirty")
    (dirty / "local.txt").write_text("not committed\n", encoding="utf-8")

    _git(repo, "branch", "unmerged", "main")
    _git(repo, "worktree", "add", str(unmerged), "unmerged")
    _commit(unmerged, "feature.txt", "not merged\n", "unmerged change")

    _age_path(merged, now=now, seconds_old=49 * 3600)
    _age_path(dirty, now=now, seconds_old=49 * 3600)
    _age_path(unmerged, now=now, seconds_old=8 * 24 * 3600)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl.log"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        f"""#!/usr/bin/env bash
for arg in "$@"; do
  printf '%s\\n' "$arg" >> {curl_log}
done
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--repo",
            str(repo),
            "--base-ref",
            "main",
            "--no-fetch",
            "--now",
            str(now),
            "--ntfy-url",
            "http://ntfy.test/hapax-worktree-gc",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert not merged.exists()
    assert dirty.exists()
    assert unmerged.exists()
    assert "removable" in result.stdout
    assert "merged-clean" in result.stdout
    assert "removed" in result.stdout
    assert "stale_unmerged=1" in result.stdout

    alert = curl_log.read_text(encoding="utf-8")
    assert "Hapax stale unmerged worktrees" in alert
    assert "hapax-council--unmerged" in alert
    assert "not merged into main" in alert


def test_worktree_gc_systemd_timer_is_installable_and_six_hourly() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    timer = TIMER.read_text(encoding="utf-8")
    preset = PRESET.read_text(encoding="utf-8")

    assert "Type=oneshot" in service
    assert "scripts/hapax-worktree-gc.sh --repo %h/projects/hapax-council" in service
    assert "WorkingDirectory=%h/projects/hapax-council" in service
    assert "OnUnitActiveSec=6h" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer
    assert "enable hapax-worktree-gc.timer" in preset
