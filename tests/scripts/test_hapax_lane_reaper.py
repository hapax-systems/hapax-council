"""Regression tests for read-only hapax-lane-reaper projections."""

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
            printf '%s\n' "${TMUX_PANE_PIDS:-${TMUX_PANE_PID:?}}"
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
    for directory in (home, bin_dir):
        directory.mkdir(parents=True, exist_ok=True)
    cache.write_text("{}\n", encoding="utf-8")
    _write_fake_tmux(bin_dir)
    (home / "Documents/Personal/20-projects/hapax-cc-tasks/active").mkdir(parents=True)

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
        f"---\ntask_id: quota-task\nstatus: {status}\nassigned_to: cx-red\n---\n# Quota task\n",
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
    return subprocess.Popen(
        ["bash", "--noprofile", "--norc"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _spawn_nested_pane_shell() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            "bash",
            "-c",
            "trap 'kill \"$child\" 2>/dev/null; exit 0' TERM INT; "
            'bash -c \'sleep 600 & nested=$!; wait "$nested"\' & child=$!; wait "$child"',
        ]
    )


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


def test_lane_reaper_dry_run_holds_quota_stuck_lane(tmp_path: Path) -> None:
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
        assert "claim detach HOLD task=quota-task" in result.stderr
        assert "would release" not in result.stderr
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


def test_lane_reaper_holds_real_quota_wall_in_live_mode(tmp_path: Path) -> None:
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
        assert "claim detach HOLD task=quota-task" in result.stderr
        assert claim_file.exists()
        task_text = task_file.read_text(encoding="utf-8")
        assert "status: in_progress" in task_text
        assert "assigned_to: cx-red" in task_text
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
        assert "claim detach HOLD: task=quota-task" in result.stderr
        assert "would release" not in result.stderr
        assert "would remove" not in result.stderr
        assert "DRY RUN: would os.kill" not in result.stderr
        assert claim_file.exists()
        assert pane.poll() is None
        assert not (Path(env["HAPAX_REAP_ATTEMPTS_DIR"]) / "cx-red").exists()
        task_text = task_file.read_text(encoding="utf-8")
        assert "status: in_progress" in task_text
        assert "assigned_to: cx-red" in task_text
    finally:
        _cleanup(pane)


def test_lane_reaper_live_mode_holds_dead_claimed_lane(tmp_path: Path) -> None:
    pane = _spawn_dead_pane()
    try:
        env = _base_env(tmp_path, pane_pid=pane.pid, pane_text="ready")
        claim_file, task_file = _write_claim(env)
        before = task_file.read_bytes()

        result = _run(env, "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "claim detach HOLD: task=quota-task" in result.stderr
        assert claim_file.exists()
        assert task_file.read_bytes() == before
        assert pane.poll() is None
    finally:
        _cleanup(pane)


def test_lane_reaper_matches_platform_qualified_codex_owner(tmp_path: Path) -> None:
    pane = _spawn_dead_pane()
    try:
        env = _base_env(tmp_path, pane_pid=pane.pid, pane_text="ready")
        claim_file, task_file = _write_claim(env)
        task_file.write_text(
            task_file.read_text(encoding="utf-8").replace(
                "assigned_to: cx-red",
                "assigned_to: codex/cx-red",
            ),
            encoding="utf-8",
        )
        before = task_file.read_bytes()

        result = _run(env, "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "claim detach HOLD: task=quota-task" in result.stderr
        assert claim_file.exists()
        assert task_file.read_bytes() == before
        assert pane.poll() is None
    finally:
        _cleanup(pane)


def test_lane_reaper_holds_session_keyed_claim_without_legacy_marker(tmp_path: Path) -> None:
    pane = _spawn_dead_pane()
    try:
        env = _base_env(tmp_path, pane_pid=pane.pid, pane_text="ready")
        legacy_claim, task_file = _write_claim(env)
        session_claim = legacy_claim.with_name(
            "cc-active-task-cx-red-019f465c-8137-7a52-9348-5602a988dc3d"
        )
        session_claim.write_bytes(legacy_claim.read_bytes())
        legacy_claim.unlink()

        result = _run(env, "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "claim detach HOLD: task=quota-task" in result.stderr
        assert session_claim.exists()
        assert "status: in_progress" in task_file.read_text(encoding="utf-8")
        assert pane.poll() is None
    finally:
        _cleanup(pane)


def test_lane_reaper_holds_task_ssot_claim_when_all_claim_markers_are_missing(
    tmp_path: Path,
) -> None:
    pane = _spawn_dead_pane()
    try:
        env = _base_env(tmp_path, pane_pid=pane.pid, pane_text="ready")
        claim_file, task_file = _write_claim(env)
        claim_file.unlink()

        result = _run(env, "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "claim detach HOLD: task=quota-task" in result.stderr
        assert "no kill, cleanup, task edit, or claim removal" in result.stderr
        assert "status: in_progress" in task_file.read_text(encoding="utf-8")
        assert pane.poll() is None
    finally:
        _cleanup(pane)


def test_lane_reaper_holds_when_task_ssot_contains_duplicate_ownership(
    tmp_path: Path,
) -> None:
    pane = _spawn_dead_pane()
    try:
        env = _base_env(tmp_path, pane_pid=pane.pid, pane_text="ready")
        claim_file, task_file = _write_claim(env)
        claim_file.unlink()
        task_file.write_text(
            "---\ntask_id: quota-task\nstatus: in_progress\nassigned_to: cx-red\n"
            "assigned_to: unassigned\n---\n",
            encoding="utf-8",
        )

        result = _run(env, "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "recovery HOLD: task SSOT unreadable" in result.stderr
        assert pane.poll() is None
    finally:
        _cleanup(pane)


def test_lane_reaper_treats_explicit_null_owner_as_canonical_unassigned(
    tmp_path: Path,
) -> None:
    pane = _spawn_dead_pane()
    try:
        env = _base_env(tmp_path, pane_pid=pane.pid, pane_text="ready")
        claim_file, task_file = _write_claim(env)
        claim_file.unlink()
        task_file.write_text(
            "---\ntask_id: quota-task\nstatus: offered\nassigned_to: null\n---\n",
            encoding="utf-8",
        )

        result = _run(env, "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "recovery HOLD: standing effect authority absent" in result.stderr
        assert "task SSOT unreadable" not in result.stderr
        assert pane.poll() is None
    finally:
        _cleanup(pane)


def test_lane_reaper_holds_when_assigned_to_field_is_missing(tmp_path: Path) -> None:
    pane = _spawn_dead_pane()
    try:
        env = _base_env(tmp_path, pane_pid=pane.pid, pane_text="ready")
        claim_file, task_file = _write_claim(env)
        claim_file.unlink()
        task_file.write_text(
            "---\ntask_id: quota-task\nstatus: offered\n---\n",
            encoding="utf-8",
        )

        result = _run(env, "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "recovery HOLD: task SSOT unreadable" in result.stderr
        assert pane.poll() is None
    finally:
        _cleanup(pane)


def test_lane_reaper_holds_unclaimed_dead_lane_for_governed_recovery(tmp_path: Path) -> None:
    pane = _spawn_dead_pane()
    try:
        env = _base_env(tmp_path, pane_pid=pane.pid, pane_text="ready")

        result = _run(env, "--dry-run", "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "recovery HOLD: standing effect authority absent" in result.stderr
        assert "claim detach HOLD" not in result.stderr
        assert pane.poll() is None
    finally:
        _cleanup(pane)


def test_lane_reaper_observes_every_pane_before_unclaimed_reap(tmp_path: Path) -> None:
    idle_pane = _spawn_dead_pane()
    active_pane = _spawn_pane_shell()
    try:
        env = _base_env(tmp_path, pane_pid=idle_pane.pid, pane_text="ready")
        env["TMUX_PANE_PIDS"] = f"{idle_pane.pid}\n{active_pane.pid}"

        result = _run(env, "--dry-run", "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "DEAD idle" not in result.stderr
        assert idle_pane.poll() is None
        assert active_pane.poll() is None
    finally:
        _cleanup(idle_pane)
        _cleanup(active_pane)


def test_lane_reaper_observes_nested_worker_before_dead_projection(tmp_path: Path) -> None:
    pane = _spawn_nested_pane_shell()
    try:
        env = _base_env(tmp_path, pane_pid=pane.pid, pane_text="ready")

        result = _run(env, "--threshold", "0")

        assert result.returncode == 0, result.stderr
        assert "DEAD idle" not in result.stderr
        assert pane.poll() is None
    finally:
        _cleanup(pane)


def test_lane_reaper_source_has_no_task_or_claim_detach_writer() -> None:
    source = REAPER.read_text(encoding="utf-8")

    assert "status: offered" not in source
    assert "assigned_to: unassigned" not in source
    assert 'rm -f "$claim_file"' not in source
    assert "os.kill" not in source
    assert "worktree remove" not in source
    assert "systemctl --user start hapax-cc-hygiene.service" not in source
    assert "hapax-alert" not in source
    assert "--recompute" not in source


def test_lane_reaper_dry_run_does_not_reset_attempt_state(tmp_path: Path) -> None:
    pane = _spawn_pane_shell()
    try:
        env = _base_env(
            tmp_path,
            pane_pid=pane.pid,
            pane_text="ready",
        )
        attempts_dir = Path(env["HAPAX_REAP_ATTEMPTS_DIR"])
        attempts_dir.mkdir(parents=True)
        attempt_file = attempts_dir / "cx-red"
        attempt_file.write_text("2\n", encoding="utf-8")

        result = _run(env, "--dry-run")

        assert result.returncode == 0, result.stderr
        assert attempt_file.read_text(encoding="utf-8") == "2\n"
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


def test_lane_reaper_classifier_keeps_line_number_429_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="review note at line 429: update parser\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "active"


def test_lane_reaper_classifier_keeps_http_429_receipt_label_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="Map HTTP 429 receipt pattern surface\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "active"


def test_lane_reaper_classifier_keeps_http_429_quota_receipt_label_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="Map HTTP 429 quota-receipt pattern surface\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "active"


def test_lane_reaper_classifier_keeps_http_429_error_taxonomy_label_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="HTTP 429 error taxonomy\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "active"


def test_lane_reaper_classifier_accepts_http_429_too_many_requests_wall() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="HTTP 429 Too Many Requests\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "stuck"


def test_lane_reaper_classifier_keeps_weekly_limit_receipt_label_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="Map weekly limit receipt pattern surface\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "active"


def test_lane_reaper_classifier_accepts_hit_weekly_limit_wall() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="You've hit your weekly limit\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "stuck"


def test_lane_reaper_classifier_keeps_hit_weekly_limit_taxonomy_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="hit a wall mapping weekly limit taxonomy\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "active"


def test_lane_reaper_classifier_keeps_quota_limit_receipt_label_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="quota limit receipt pattern surface\n",
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


def test_lane_reaper_classifier_keeps_rate_limit_taxonomy_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="rate limit error taxonomy\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "active"


def test_lane_reaper_classifier_keeps_rate_limited_receipt_label_active() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="rate-limited receipt writer idle\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "active"


def test_lane_reaper_classifier_accepts_rate_limit_exceeded_wall() -> None:
    result = subprocess.run(
        [str(REAPER)],
        input="rate limit exceeded\n",
        env={**os.environ, "HAPAX_LANE_REAPER_CLASSIFY_STDIN": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "stuck"
