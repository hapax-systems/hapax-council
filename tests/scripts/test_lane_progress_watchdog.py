"""Output age is diagnostic, never authority to relaunch, nudge, or reoffer.

These supersede the historical watchdog recovery assertions under the
2026-09-24 repair spec. Dead unclaimed lanes still recover through guard;
quiet claimed writers and uncertain owners hold for inspection.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = Path(
    os.environ.get("HAPAX_TEST_SUPERVISOR", REPO_ROOT / "scripts/hapax-lane-supervisor")
)


# ─── harness (mirrors test_lane_supervisor.py, extended for the progress leg) ──


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _write_recorder(path: Path, log: Path) -> None:
    """A fake binary that records its argv to ``log`` and exits 0."""
    _write_executable(
        path,
        f"""
        #!/usr/bin/env bash
        printf '%s\\n' "$*" >> "{log}"
        """,
    )


def _write_fake_tmux(bin_dir: Path) -> None:
    """Fake tmux: ``has-session`` succeeds only for sessions in $TMUX_LIVE."""
    _write_executable(
        bin_dir / "tmux",
        """
        #!/usr/bin/env bash
        cmd="$1"; shift || true
        case "$cmd" in
          has-session)
            target=""
            while [ $# -gt 0 ]; do
              case "$1" in
                -t) target="$2"; shift 2 ;;
                *) shift ;;
              esac
            done
            # `=name` is tmux's exact-match anchor (a bare name also prefix-matches);
            # the supervisor anchors every session target, so honour the syntax.
            target="${target#=}"
            for live in ${TMUX_LIVE:-}; do
              [ "$live" = "$target" ] && exit 0
            done
            exit 1
            ;;
          *) exit 0 ;;
        esac
        """,
    )


def _base(tmp_path: Path, **overrides: str) -> tuple[dict[str, str], Path]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "state"
    runtime_dir = tmp_path / "runtime"
    log_dir = tmp_path / "headless-logs"
    metrics = tmp_path / "metrics.prom"
    calls = tmp_path / "calls"
    for d in (home, bin_dir, state_dir, runtime_dir, log_dir, calls):
        d.mkdir(parents=True, exist_ok=True)
    (home / "projects").mkdir(parents=True, exist_ok=True)

    _write_fake_tmux(bin_dir)
    _write_recorder(bin_dir / "hapax-claude-headless", calls / "claude-headless.txt")
    _write_recorder(bin_dir / "hapax-claude", calls / "claude.txt")
    _write_recorder(bin_dir / "hapax-codex", calls / "codex.txt")
    _write_recorder(bin_dir / "hapax-antigrav", calls / "antigrav.txt")
    _write_recorder(bin_dir / "curl", calls / "curl.txt")
    runner = tmp_path / "supervisor/scripts/hapax-lane-supervisor"
    _write_executable(runner, SUPERVISOR.read_text())
    (runner.parent.parent / "shared").symlink_to(REPO_ROOT / "shared", target_is_directory=True)
    _write_recorder(runner.parent / "hapax-alert", calls / "alert.txt")

    env = os.environ.copy()
    for leaky in ("CLAUDE_ROLE", "HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE", "TMUX_LIVE"):
        env.pop(leaky, None)
    env.update(
        {
            "HOME": str(home),
            "TEST_SUPERVISOR_BIN": str(runner),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "HAPAX_SUPERVISOR_STATE_DIR": str(state_dir),
            "HAPAX_SUPERVISOR_RUNTIME_DIR": str(runtime_dir),
            "HAPAX_SUPERVISOR_WORKTREE_ROOT": str(home / "projects"),
            "HAPAX_SUPERVISOR_VAULT_ROOT": str(home / "vault"),
            "HAPAX_SUPERVISOR_CLAUDE_LANES": "",
            "HAPAX_SUPERVISOR_CODEX_LANES": "",
            "HAPAX_SUPERVISOR_ANTIGRAV_LANES": "",
            "HAPAX_SUPERVISOR_RESTART_COOLDOWN_S": "0",
            "HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS": "0",
            "HAPAX_SUPERVISOR_REAP_OFF": "1",
            "HAPAX_SUPERVISOR_PROGRESS_OFF": "0",
            "HAPAX_SUPERVISOR_P0_IDLE_RESPAWN": "0",
            "HAPAX_LOCAL_DEV_MAINTENANCE_MODE": "local",
            "HAPAX_CLAUDE_HEADLESS_BIN": str(bin_dir / "hapax-claude-headless"),
            "HAPAX_CLAUDE_BIN": str(bin_dir / "hapax-claude"),
            "HAPAX_CODEX_BIN": str(bin_dir / "hapax-codex"),
            "HAPAX_ANTIGRAV_BIN": str(bin_dir / "hapax-antigrav"),
            # progress-watchdog knobs
            "HAPAX_SUPERVISOR_CLAUDE_LOG_DIR": str(log_dir),
            "HAPAX_SUPERVISOR_STALL_T": "900",
            "HAPAX_SUPERVISOR_RESUME_MAX_ATTEMPTS": "3",
            "HAPAX_SUPERVISOR_RESUME_WINDOW_S": "3600",
            "HAPAX_SUPERVISOR_RESUME_COOLDOWN_S": "0",
            "HAPAX_SUPERVISOR_METRICS_FILE": str(metrics),
            # admission DI seam: default-open so the progress leg runs in tests.
            "HAPAX_SUPERVISOR_ADMISSION_CMD": "printf open",
            "HAPAX_NTFY_URL": "http://ntfy.invalid",
            "HAPAX_NTFY_TOPIC": "hapax-test",
        }
    )
    env.update(overrides)
    return env, calls


def _make_worktree(env: dict[str, str], lane: str) -> Path:
    wt = Path(env["HAPAX_SUPERVISOR_WORKTREE_ROOT"]) / f"hapax-council--{lane}"
    wt.mkdir(parents=True, exist_ok=True)
    return wt


def _write_claim(
    env: dict[str, str], lane: str, task_id: str, *, status: str = "in_progress"
) -> Path:
    claim_dir = Path(env["HOME"]) / ".cache" / "hapax"
    claim_dir.mkdir(parents=True, exist_ok=True)
    (claim_dir / f"cc-active-task-{lane}").write_text(f"{task_id}\n", encoding="utf-8")
    active = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"]) / "active"
    active.mkdir(parents=True, exist_ok=True)
    note = active / f"{task_id}.md"
    note.write_text(
        f"---\ntask_id: {task_id}\nstatus: {status}\nassigned_to: {lane}\n"
        f'title: "Build the thing {task_id}"\n---\n# task\n',
        encoding="utf-8",
    )
    return note


def _move_claim_to_session(env: dict[str, str], lane: str, task_id: str) -> Path:
    claim_dir = Path(env["HOME"]) / ".cache" / "hapax"
    legacy = claim_dir / f"cc-active-task-{lane}"
    legacy.unlink()
    session = claim_dir / f"cc-active-task-{lane}-9b6ba5ca-513c-41aa-9900-d3026b42aad1"
    session.write_text(f"{task_id}\n", encoding="utf-8")
    return session


def _alive_pid() -> int:
    """A pid guaranteed live for the duration of the test (the test process)."""
    return os.getpid()


def _dead_pid() -> int:
    """A pid guaranteed not to exist."""
    return 2147483646


def _set_claude_alive(env: dict[str, str], lane: str, *, pid: int | None = None) -> None:
    runtime = Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"])
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / f"{lane}.pid").write_text(f"{pid or _alive_pid()}\n", encoding="utf-8")


def _set_launcher(env: dict[str, str], lane: str, *, alive: bool) -> None:
    runtime = Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"])
    runtime.mkdir(parents=True, exist_ok=True)
    pid = _alive_pid() if alive else _dead_pid()
    (runtime / f"{lane}.launcher.pid").write_text(f"{pid}\n", encoding="utf-8")


def _set_output(env: dict[str, str], lane: str, *, age_s: float) -> Path:
    log_dir = Path(env["HAPAX_SUPERVISOR_CLAUDE_LOG_DIR"]) / lane
    log_dir.mkdir(parents=True, exist_ok=True)
    oj = log_dir / "output.jsonl"
    oj.write_text('{"type":"assistant"}\n', encoding="utf-8")
    mtime = time.time() - age_s
    os.utime(oj, (mtime, mtime))
    return oj


def _stalled_lane(
    env: dict[str, str],
    lane: str,
    task_id: str = "reform-clog-x-20260601",
    *,
    launcher_alive: bool,
    age_s: float = 3600.0,
    status: str = "in_progress",
) -> Path:
    """Set up a live writer with quiet output, which cannot prove a stall."""
    _make_worktree(env, lane)
    note = _write_claim(env, lane, task_id, status=status)
    _set_claude_alive(env, lane)  # claude_alive TRUE -> supervisor would skip
    _set_launcher(env, lane, alive=launcher_alive)
    _set_output(env, lane, age_s=age_s)
    return note


def _spawn_headless_launcher(env: dict[str, str], lane: str, task_id: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            "bash",
            "-c",
            ('exec -a "$3" python3 -c \'import time; time.sleep(60)\' --task "$1" "$2"'),
            "_",
            task_id,
            lane,
            "hapax-claude-headless",
        ],
        env=env,
        text=True,
    )


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [env["TEST_SUPERVISOR_BIN"]], env=env, capture_output=True, text=True, timeout=30
    )


def _reads(calls: Path, name: str) -> str:
    p = calls / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _ownership_snapshot(env: dict[str, str]) -> dict[str, bytes]:
    roots = (Path(env["HOME"]) / ".cache/hapax", Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"]))
    return {str(p): p.read_bytes() for root in roots for p in root.rglob("*") if p.is_file()}


def _assert_progress_hold(env, calls, before, result):
    assert result.returncode == 0, result.stderr
    assert "progress_hold:output_silence" in result.stdout
    assert _ownership_snapshot(env) == before
    assert not list(calls.iterdir()), result.stdout
    assert not (Path(env["HAPAX_SUPERVISOR_STATE_DIR"]) / "lanes_resumed_total").exists()


# ─── Output silence preserves both writer and ownership ──────────────────────


def test_dead_launcher_with_live_writer_holds_same_task(tmp_path: Path) -> None:
    """A missing wrapper and stale output cannot authorize a second writer."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    _stalled_lane(env, "delta", "reform-clog-i-20260601", launcher_alive=False)

    before = _ownership_snapshot(env)
    _assert_progress_hold(env, calls, before, _run(env))


def test_live_launcher_silence_never_nudges_fifo(tmp_path: Path) -> None:
    """A quiet live writer can think without receiving an injected turn."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="theta")
    task_id = "reform-native-merge-queue-20260601"
    _stalled_lane(env, "theta", task_id, launcher_alive=False)
    launcher = _spawn_headless_launcher(env, "theta", task_id)
    (Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"]) / "theta.launcher.pid").write_text(
        f"{launcher.pid}\n", encoding="utf-8"
    )

    # Nonblocking read witnesses no bytes without a timing-only sleep.
    fifo = Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"]) / "theta.stdin"
    os.mkfifo(fifo)
    reader = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    before = _ownership_snapshot(env)
    try:
        result = _run(env)
        _assert_progress_hold(env, calls, before, result)
        with pytest.raises(BlockingIOError):
            os.read(reader, 4096)
        assert launcher.poll() is None
    finally:
        os.close(reader)
        launcher.terminate()
        launcher.wait(timeout=5)


# ─── AC2: a genuinely-working lane is NOT disrupted ────────────────────────────


def test_recent_output_not_disrupted(tmp_path: Path) -> None:
    """Fresh output.jsonl (within STALL_T) -> working; no resume, no nudge."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="epsilon")
    _stalled_lane(env, "epsilon", launcher_alive=True, age_s=60.0)  # 1min < 900

    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude-headless.txt").strip() == ""


def test_missing_output_jsonl_not_resumed(tmp_path: Path) -> None:
    """No output.jsonl at all (never produced) -> not a progress-stall."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="gamma")
    _make_worktree(env, "gamma")
    _write_claim(env, "gamma", "reform-clog-x-20260601", status="in_progress")
    _set_claude_alive(env, "gamma")
    _set_launcher(env, "gamma", alive=False)
    # deliberately no output.jsonl

    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude-headless.txt").strip() == ""


def test_claimed_but_not_in_progress_not_resumed(tmp_path: Path) -> None:
    """status=claimed (not yet in_progress) is out of scope per the note."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    _stalled_lane(env, "delta", launcher_alive=False, status="claimed")

    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude-headless.txt").strip() == ""


def test_session_keyed_quiet_claim_is_preserved(tmp_path: Path) -> None:
    """A session claim remains owned work when its writer is quiet."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="gamma")
    task_id = "p0-incident-session-keyed-progress"
    _stalled_lane(env, "gamma", task_id, launcher_alive=False)
    _move_claim_to_session(env, "gamma", task_id)

    before = _ownership_snapshot(env)
    _assert_progress_hold(env, calls, before, _run(env))


def test_pr_open_not_resumed(tmp_path: Path) -> None:
    """A pr_open lane is finishing, not stalled mid-build -> never resumed."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    _stalled_lane(env, "delta", launcher_alive=False, status="pr_open")

    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude-headless.txt").strip() == ""


# ─── Historical retry exhaustion cannot authorize a claim transfer ──────────


def test_attempts_exhausted_preserves_claim_and_task(tmp_path: Path) -> None:
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_RESUME_MAX_ATTEMPTS="2",
    )
    task_id = "reform-clog-i-20260601"
    _stalled_lane(env, "delta", task_id, launcher_alive=False)
    history = Path(env["HAPAX_SUPERVISOR_STATE_DIR"]) / f"delta.{task_id}.resume-log"
    history.write_text(f"{int(time.time())}\n" * 2)
    before = _ownership_snapshot(env)
    old_history = history.read_bytes()
    for _ in range(3):
        _assert_progress_hold(env, calls, before, _run(env))
    assert history.read_bytes() == old_history


def test_attempts_exhausted_preserves_session_claim_and_epoch(tmp_path: Path) -> None:
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="gamma",
        HAPAX_SUPERVISOR_RESUME_MAX_ATTEMPTS="1",
    )
    task_id = "p0-incident-session-exhausted"
    _stalled_lane(env, "gamma", task_id, launcher_alive=False)
    session = _move_claim_to_session(env, "gamma", task_id)
    legacy = Path(env["HOME"]) / ".cache" / "hapax" / "cc-active-task-gamma"
    session.with_name(session.name.replace("cc-active-task-", "cc-claim-epoch-")).write_text(
        "17|preserve-epoch\n"
    )
    history = Path(env["HAPAX_SUPERVISOR_STATE_DIR"]) / f"gamma.{task_id}.resume-log"
    history.write_text(f"{int(time.time())}\n")
    before = _ownership_snapshot(env)
    for _ in range(2):
        _assert_progress_hold(env, calls, before, _run(env))
    assert not legacy.exists()


# ─── Admission state does not authorize output-age recovery ─────────────────


def test_closed_admission_keeps_quiet_writer_held(tmp_path: Path) -> None:
    """Closed admission leaves the existing writer and claim intact."""
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_ADMISSION_CMD="printf closed",
    )
    _stalled_lane(env, "delta", launcher_alive=False)

    before = _ownership_snapshot(env)
    _assert_progress_hold(env, calls, before, _run(env))


def test_pressure_clearing_does_not_authorize_silent_writer_recovery(tmp_path: Path) -> None:
    """Restored capacity does not prove that a quiet writer needs recovery."""
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_ADMISSION_CMD="printf closed",
    )
    _stalled_lane(env, "delta", launcher_alive=False)
    before = _ownership_snapshot(env)
    _assert_progress_hold(env, calls, before, _run(env))

    env_open = dict(env, HAPAX_SUPERVISOR_ADMISSION_CMD="printf open")
    _assert_progress_hold(env_open, calls, before, _run(env_open))


# ─── guards: dry-run, kill-switch, alive-via-pidfile precondition ──────────────


def test_dry_run_reports_without_resuming(tmp_path: Path) -> None:
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_DRY_RUN="1",
    )
    _stalled_lane(env, "delta", "reform-clog-i-20260601", launcher_alive=False)

    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude-headless.txt").strip() == ""
    assert "delta" in result.stdout
    assert "reform-clog-i-20260601" in result.stdout


def test_progress_off_disables_leg(tmp_path: Path) -> None:
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_PROGRESS_OFF="1",
    )
    _stalled_lane(env, "delta", launcher_alive=False)

    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude-headless.txt").strip() == ""


def test_dead_lane_respawn_path_still_works(tmp_path: Path) -> None:
    """The progress leg must not regress the existing dead-lane respawn: a lane
    with NO live process still respawns read-only into idle-await."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    _make_worktree(env, "delta")
    # no pidfile, no launcher, no claim -> dead + task-less

    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "--role delta" in _reads(calls, "claude.txt")
    assert "--readonly" in _reads(calls, "claude.txt")


# ─── AC5: observability metric ─────────────────────────────────────────────────


def test_emits_resume_metrics(tmp_path: Path) -> None:
    env, _calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    metrics = Path(env["HAPAX_SUPERVISOR_METRICS_FILE"])
    _stalled_lane(env, "delta", launcher_alive=False)

    result = _run(env)
    assert result.returncode == 0, result.stderr
    text = metrics.read_text(encoding="utf-8") if metrics.exists() else ""
    assert "hapax_lane_supervisor_lanes_resumed_total 0\n" in text
    assert "hapax_lane_supervisor_lanes_stalled 1\n" in text


def test_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(SUPERVISOR)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
