"""Regression tests for hapax-lane-reaper stuck-lane handling."""

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
        cmd="$1"
        shift || true
        case "$cmd" in
          list-sessions)
            printf '%s\n' "${TMUX_SESSION:?}"
            ;;
          list-panes)
            printf '%s\n' "${TMUX_PANE_PID:?}"
            ;;
          capture-pane)
            printf '%s\n' "${TMUX_PANE_TEXT:?}"
            ;;
          display-message)
            printf '%s\n' "${TMUX_ACTIVITY:?}"
            ;;
          *)
            exit 0
            ;;
        esac
        """,
    )


def _base_env(tmp_path: Path, *, pane_pid: int, pane_text: str) -> dict[str, str]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    attempts = tmp_path / "reap-attempts"
    cache = tmp_path / "dispatch-service-time.json"
    for directory in (home, bin_dir, attempts):
        directory.mkdir(parents=True, exist_ok=True)
    cache.write_text("{}\n", encoding="utf-8")
    _write_fake_tmux(bin_dir)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TMUX_SESSION": "hapax-codex-cx-red",
            "TMUX_PANE_PID": str(pane_pid),
            "TMUX_PANE_TEXT": pane_text,
            "TMUX_ACTIVITY": "1",
            "HAPAX_COUNCIL_DIR": str(tmp_path / "council"),
            "HAPAX_DISPATCH_SERVICE_TIME_CACHE": str(cache),
            "HAPAX_REAP_ATTEMPTS_DIR": str(attempts),
            "HAPAX_RECOVERY_GOVERNOR_OFF": "1",
            "HAPAX_DISPATCH_SCHEDULER_LEGACY": "1",
        }
    )
    return env


def _write_claim(env: dict[str, str], *, status: str = "in_progress") -> tuple[Path, Path]:
    home = Path(env["HOME"])
    claim_dir = home / ".cache" / "hapax"
    claim_dir.mkdir(parents=True, exist_ok=True)
    claim_file = claim_dir / "cc-active-task-cx-red"
    claim_file.write_text("quota-task\n", encoding="utf-8")

    task_dir = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    task_dir.mkdir(parents=True, exist_ok=True)
    task_file = task_dir / "quota-task.md"
    task_file.write_text(
        f"---\nstatus: {status}\nassigned_to: cx-red\n---\n# Quota task\n",
        encoding="utf-8",
    )
    return claim_file, task_file


def _spawn_pane_shell() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "bash",
            "-c",
            'trap \'kill "$child" 2>/dev/null; exit 0\' TERM INT; sleep 600 & child=$!; wait "$child"',
        ]
    )


def _spawn_dead_pane() -> subprocess.Popen[bytes]:
    return subprocess.Popen(["sleep", "600"])


def _cleanup(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REAPER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_lane_reaper_help_exits_without_tmux_or_mutation() -> None:
    result = subprocess.run([str(REAPER), "--help"], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0
    assert "Usage: hapax-lane-reaper" in result.stdout


def test_lane_reaper_rejects_unknown_argument_without_tmux() -> None:
    result = subprocess.run(
        [str(REAPER), "--bogus"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 64
    assert "unknown argument: --bogus" in result.stderr
    assert "Usage: hapax-lane-reaper" in result.stderr


def test_lane_reaper_requires_threshold_value_without_tmux() -> None:
    result = subprocess.run(
        [str(REAPER), "--threshold"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 64
    assert "--threshold requires a MINUTES argument" in result.stderr
    assert "Usage: hapax-lane-reaper" in result.stderr


def test_lane_reaper_dry_run_does_not_release_quota_stuck_lane(tmp_path: Path) -> None:
    pane = _spawn_pane_shell()
    try:
        env = _base_env(
            tmp_path,
            pane_pid=pane.pid,
            pane_text="Usage limit reached\nretry after reset\nblocked",
        )
        claim_file, task_file = _write_claim(env)

        result = _run(env, "--dry-run")

        assert result.returncode == 0, result.stderr
        assert "DRY RUN: would release task: quota-task" in result.stderr
        assert claim_file.exists()
        task_text = task_file.read_text(encoding="utf-8")
        assert "status: in_progress" in task_text
        assert "assigned_to: cx-red" in task_text
    finally:
        _cleanup(pane)


def test_lane_reaper_ignores_quota_receipt_footer_without_real_wall(tmp_path: Path) -> None:
    pane = _spawn_pane_shell()
    try:
        env = _base_env(
            tmp_path,
            pane_pid=pane.pid,
            pane_text="Map quota-receipt pattern surface\nstatus: monitoring receipts\nready",
        )
        claim_file, task_file = _write_claim(env)

        result = _run(env)

        assert result.returncode == 0, result.stderr
        assert "Released task: quota-task" not in result.stderr
        assert "DRY RUN: would release task: quota-task" not in result.stderr
        assert claim_file.exists()
        task_text = task_file.read_text(encoding="utf-8")
        assert "status: in_progress" in task_text
        assert "assigned_to: cx-red" in task_text
    finally:
        _cleanup(pane)


def test_lane_reaper_releases_real_quota_wall_in_live_mode(tmp_path: Path) -> None:
    pane = _spawn_pane_shell()
    try:
        env = _base_env(
            tmp_path,
            pane_pid=pane.pid,
            pane_text="HTTP 429 Too Many Requests\nprovider quota wall\nblocked",
        )
        claim_file, task_file = _write_claim(env)

        result = _run(env)

        assert result.returncode == 0, result.stderr
        assert "Released task: quota-task" in result.stderr
        assert not claim_file.exists()
        task_text = task_file.read_text(encoding="utf-8")
        assert "status: offered" in task_text
        assert "assigned_to: unassigned" in task_text
    finally:
        _cleanup(pane)


def test_lane_reaper_dry_run_does_not_release_dead_lane_stale_claim(tmp_path: Path) -> None:
    pane = _spawn_dead_pane()
    try:
        env = _base_env(
            tmp_path,
            pane_pid=pane.pid,
            pane_text="ready",
        )
        claim_file, task_file = _write_claim(env)

        result = _run(env, "--dry-run", "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "DRY RUN: would release stale task: quota-task" in result.stderr
        assert "DRY RUN: would remove stale claim file:" in result.stderr
        assert claim_file.exists()
        task_text = task_file.read_text(encoding="utf-8")
        assert "status: in_progress" in task_text
        assert "assigned_to: cx-red" in task_text
    finally:
        _cleanup(pane)


def test_lane_reaper_classifier_keeps_quota_receipts_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="Map quota-receipt pattern surface\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "active"


def test_lane_reaper_classifier_keeps_quota_receipt_footer_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="background-agent: quota-receipt writer idle\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "active"


def test_lane_reaper_classifier_accepts_blocked_quota_exhausted_wall() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="BLOCKED: quota exhausted\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "stuck"
