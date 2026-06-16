"""Tests for the lane PROGRESS watchdog leg of hapax-lane-supervisor.

The FM-11 supervisor guarantees lane *process* liveness (dead -> respawn). But a
lane can be process-alive yet make no PROGRESS: it did a bounded chunk, the turn
ended, and nothing drives a continuation, so ``output.jsonl`` freezes while the
slot stays occupied ``in_progress`` and no PR opens (observed 2026-06-01: theta
output-stale 100min with a live launcher; delta orphaned). The supervisor's
``claude_alive`` check (claude pidfile / tmux) says "fine" and skips it.

This is the missing leg: detect an ``in_progress`` lane whose ``output.jsonl`` is
stale > STALL_T and RESUME it on the SAME task, bounded by per-(lane,task)
attempts + ntfy escalation + pressure-gating. Recovery adapts to launcher state
(the empirically-correct split, not the note's assumed "launcher always dead"):

  * launcher DEAD  -> re-launch via hapax-claude-headless (fresh, flock-free).
  * launcher ALIVE -> nudge the live launcher's stdin FIFO with a resume message
    (its own injection mechanism; a re-launch would flock-fail). Both resume the
    same task from the same worktree.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"


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

    env = os.environ.copy()
    for leaky in ("CLAUDE_ROLE", "HAPAX_AGENT_NAME", "HAPAX_AGENT_ROLE", "TMUX_LIVE"):
        env.pop(leaky, None)
    env.update(
        {
            "HOME": str(home),
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
    """Set up a process-alive but output-stalled lane: the missing-leg scenario."""
    _make_worktree(env, lane)
    note = _write_claim(env, lane, task_id, status=status)
    _set_claude_alive(env, lane)  # claude_alive TRUE -> supervisor would skip
    _set_launcher(env, lane, alive=launcher_alive)
    _set_output(env, lane, age_s=age_s)
    return note


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SUPERVISOR)], env=env, capture_output=True, text=True)


def _reads(calls: Path, name: str) -> str:
    p = calls / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _wait_reads(calls: Path, name: str, *, timeout: float = 8.0) -> str:
    deadline = time.monotonic() + timeout
    text = ""
    while time.monotonic() < deadline:
        text = _reads(calls, name)
        if text.strip():
            return text
        time.sleep(0.05)
    return text


# ─── AC1: a stalled lane is auto-resumed on its SAME task ──────────────────────


def test_dead_launcher_stall_relaunches_same_task(tmp_path: Path) -> None:
    """Orphaned (launcher-dead) + output-stale in_progress -> re-launch headless
    on the SAME task with a resume prompt (flock-free; resumes from worktree)."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    _stalled_lane(env, "delta", "reform-clog-i-20260601", launcher_alive=False)

    result = _run(env)
    assert result.returncode == 0, result.stderr

    headless = _wait_reads(calls, "claude-headless.txt")
    assert "--task reform-clog-i-20260601" in headless
    assert "delta" in headless
    assert "stall" in headless.lower() or "resume" in headless.lower()


def test_live_launcher_stall_nudges_fifo_same_task(tmp_path: Path) -> None:
    """Live launcher + output-stale (the observed theta case) -> nudge the live
    launcher's stdin FIFO with a resume message; do NOT re-launch (flock)."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="theta")
    _stalled_lane(env, "theta", "reform-native-merge-queue-20260601", launcher_alive=True)

    # A real FIFO with a background reader (claude would be the reader in prod).
    fifo = Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"]) / "theta.stdin"
    os.mkfifo(fifo)
    capture = tmp_path / "fifo-capture.txt"
    reader = subprocess.Popen(["bash", "-c", f'cat "{fifo}" > "{capture}"'])
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        deadline = time.monotonic() + 8.0
        text = ""
        while time.monotonic() < deadline:
            text = capture.read_text(encoding="utf-8") if capture.exists() else ""
            if text.strip():
                break
            time.sleep(0.05)
    finally:
        reader.terminate()
        reader.wait(timeout=5)

    # No re-launch when a live launcher holds the lane.
    assert _reads(calls, "claude-headless.txt").strip() == ""
    # The FIFO got a stream-json user message naming the task.
    assert "reform-native-merge-queue-20260601" in text
    assert '"type":"user"' in text


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


def test_pr_open_not_resumed(tmp_path: Path) -> None:
    """A pr_open lane is finishing, not stalled mid-build -> never resumed."""
    env, calls = _base(tmp_path, HAPAX_SUPERVISOR_CLAUDE_LANES="delta")
    _stalled_lane(env, "delta", launcher_alive=False, status="pr_open")

    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude-headless.txt").strip() == ""


# ─── AC3: bounded attempts -> reoffer + ntfy (no infinite relaunch) ────────────


def test_attempts_exhausted_reoffers_and_ntfys(tmp_path: Path) -> None:
    """After MAX failed resumes in the window the task reverts to offered +
    assigned_to:unassigned, the claim slot is cleared, and an ntfy fires."""
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_RESUME_MAX_ATTEMPTS="2",
    )
    note = _stalled_lane(env, "delta", "reform-clog-i-20260601", launcher_alive=False)
    claim = Path(env["HOME"]) / ".cache" / "hapax" / "cc-active-task-delta"

    # Two ticks resume (attempts 1, 2); the third sees the cap reached -> reoffer.
    _run(env)
    _run(env)
    result = _run(env)
    assert result.returncode == 0, result.stderr

    text = note.read_text(encoding="utf-8")
    assert "status: offered" in text
    assert "assigned_to: unassigned" in text
    assert claim.read_text(encoding="utf-8").strip() == ""
    curl = _reads(calls, "curl.txt")
    assert "delta" in curl and "reform-clog-i-20260601" in curl


# ─── AC4: pressure gating (queue, never drop) ──────────────────────────────────


def test_pressure_closed_defers_resume(tmp_path: Path) -> None:
    """admission_state closed -> defer the resume this tick (queued, not dropped)
    and do NOT re-launch."""
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_ADMISSION_CMD="printf closed",
    )
    _stalled_lane(env, "delta", launcher_alive=False)

    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert _reads(calls, "claude-headless.txt").strip() == ""
    assert "pressure" in result.stdout.lower() or "closed" in result.stdout.lower()


def test_pressure_clears_resumes_after_defer(tmp_path: Path) -> None:
    """The deferred resume is queued, not dropped: once admission re-opens the
    next tick resumes it (no attempt was burned while pressure was closed)."""
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_ADMISSION_CMD="printf closed",
    )
    _stalled_lane(env, "delta", launcher_alive=False)
    _run(env)  # closed -> defer
    assert _reads(calls, "claude-headless.txt").strip() == ""

    env_open = dict(env, HAPAX_SUPERVISOR_ADMISSION_CMD="printf open")
    _run(env_open)
    assert _wait_reads(calls, "claude-headless.txt").strip() != ""


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
    _wait_reads(tmp_path / "calls", "claude-headless.txt")

    text = metrics.read_text(encoding="utf-8") if metrics.exists() else ""
    assert "hapax_lane_supervisor_lanes_resumed_total" in text
    assert "hapax_lane_supervisor_lanes_stalled" in text


def test_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(SUPERVISOR)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
