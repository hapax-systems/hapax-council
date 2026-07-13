"""Regression tests for hapax-lane-reaper stuck-lane task release.

The P0 incident was a proxy-signal failure: a live pane mentioned
``quota-receipt`` in task/background-agent text, and the reaper treated that as
a terminal quota wall. The same branch also mutated claim/task state in
``--dry-run``.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REAPER = REPO_ROOT / "scripts" / "hapax-lane-reaper"


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _write_fake_tmux(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "tmux",
        """
        #!/usr/bin/env bash
        cmd="$1"; shift || true
        case "$cmd" in
          list-sessions)
            printf '%s\\n' "hapax-claude-eta"
            ;;
          list-panes)
            printf '%s\\n' "4242"
            ;;
          capture-pane)
            cat "$HAPAX_FAKE_TMUX_CAPTURE"
            ;;
          display-message)
            printf '%s\\n' "0"
            ;;
          *)
            exit 0
            ;;
        esac
        """,
    )


def _write_fake_ps(bin_dir: Path) -> None:
    _write_executable(
        bin_dir / "ps",
        """
        #!/usr/bin/env bash
        if [[ "$1" == "--ppid" ]]; then
          printf '%s\\n' "claude"
          exit 0
        fi
        exit 1
        """,
    )


def _base(tmp_path: Path, pane_text: str) -> tuple[dict[str, str], Path]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    cache_dir = home / ".cache" / "hapax"
    capture = tmp_path / "pane.txt"
    cache = cache_dir / "dispatch-service-time.json"

    cache_dir.mkdir(parents=True, exist_ok=True)
    (home / "projects").mkdir(parents=True, exist_ok=True)
    capture.write_text(pane_text, encoding="utf-8")
    cache.write_text("{}\n", encoding="utf-8")

    _write_fake_tmux(bin_dir)
    _write_fake_ps(bin_dir)
    _write_executable(bin_dir / "systemctl", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_COUNCIL_DIR": str(home / "projects" / "hapax-council"),
            "HAPAX_DISPATCH_SERVICE_TIME_CACHE": str(cache),
            "HAPAX_FAKE_TMUX_CAPTURE": str(capture),
            "HAPAX_REAP_ATTEMPTS_DIR": str(cache_dir / "lane-reap-attempts"),
            "HAPAX_RECOVERY_GOVERNOR_OFF": "1",
        }
    )
    return env, home


def _write_claim(home: Path, *, status: str = "claimed") -> tuple[Path, Path]:
    task_id = "cc-task-claude-subscription-quota-receipts-20260708"
    claim = home / ".cache" / "hapax" / "cc-active-task-eta"
    task = (
        home
        / "Documents"
        / "Personal"
        / "20-projects"
        / "hapax-cc-tasks"
        / "active"
        / f"{task_id}.md"
    )
    claim.parent.mkdir(parents=True, exist_ok=True)
    task.parent.mkdir(parents=True, exist_ok=True)
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    task.write_text(
        (
            "---\n"
            f"task_id: {task_id}\n"
            f"status: {status}\n"
            "assigned_to: eta\n"
            "title: fixture\n"
            "---\n"
            "# fixture\n"
        ),
        encoding="utf-8",
    )
    return claim, task


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REAPER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_quota_receipt_pane_text_does_not_release_active_task(tmp_path: Path) -> None:
    env, home = _base(
        tmp_path,
        "\n".join(
            [
                "Map quota-receipt pattern surface",
                "background-agent: quota-receipt watcher",
                "working normally",
            ]
        ),
    )
    claim, task = _write_claim(home, status="in_progress")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert claim.exists()
    text = task.read_text(encoding="utf-8")
    assert "status: in_progress" in text
    assert "assigned_to: eta" in text
    assert "STUCK" not in result.stderr


def test_dry_run_real_quota_wall_does_not_release_task(tmp_path: Path) -> None:
    env, home = _base(tmp_path, "429 Too Many Requests\n")
    claim, task = _write_claim(home)

    result = _run(env, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert claim.exists()
    text = task.read_text(encoding="utf-8")
    assert "status: claimed" in text
    assert "assigned_to: eta" in text
    assert "DRY RUN: would release task" in result.stderr


def test_live_real_quota_wall_releases_task_without_killing_session(tmp_path: Path) -> None:
    env, home = _base(tmp_path, "BLOCKED: quota wall\n")
    claim, task = _write_claim(home, status="in_progress")

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert not claim.exists()
    text = task.read_text(encoding="utf-8")
    assert "status: offered" in text
    assert "assigned_to: unassigned" in text
    assert "Released task" in result.stderr
