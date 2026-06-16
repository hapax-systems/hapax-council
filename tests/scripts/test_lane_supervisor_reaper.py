"""Tests for the zombie-launcher reaper leg of the FM-11 lane supervisor.

A headless launcher (``hapax-claude-headless``) can outlive its task: the claude
child reads its stdin from a FIFO whose write-end the launcher itself holds open
(``exec 3<>``), so the child never sees EOF, the launcher's ``wait`` never
returns, and its own post-turn ``task_is_terminal`` teardown is unreachable. The
launcher then pins the lane (lifetime flock) and blocks re-dispatch. This was the
dispatch-blocking class: ``pgrep -fc hapax-claude-headless`` ~= 60 while only ~5
lanes were genuinely live.

The supervisor's reaper leg is the PID-targeted backstop. For a lane with a live
launcher it reaps (SIGTERM, single pid — NEVER a process group) when:
  1. the claimed task is terminal (note left active/, terminal status, or PR
     merged), gated on admission_state so a pressure-closed window defers; or
  2. the launcher exceeds a hard lifetime ceiling (escalate + reap), regardless
     of task state.

Regression pin (exit-144 cascade): the reaper must SIGTERM the EXACT launcher
pid, never ``kill -- -PGID`` / a negative pid / killpg.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _write_recorder(path: Path, log: Path) -> None:
    _write_executable(path, f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "{log}"\n')


def _write_fake_tmux(bin_dir: Path) -> None:
    """Fake tmux: ``has-session`` always fails (no live tmux lanes in these tests)."""
    _write_executable(
        bin_dir / "tmux",
        """
        #!/usr/bin/env bash
        case "$1" in
          has-session) exit 1 ;;
          *) exit 0 ;;
        esac
        """,
    )


def _base(tmp_path: Path, **overrides: str) -> tuple[dict[str, str], Path, Path]:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    state_dir = tmp_path / "state"
    runtime_dir = tmp_path / "runtime"
    calls = tmp_path / "calls"
    for d in (home, bin_dir, state_dir, runtime_dir, calls):
        d.mkdir(parents=True, exist_ok=True)
    (home / "projects").mkdir(parents=True, exist_ok=True)

    _write_fake_tmux(bin_dir)
    _write_recorder(bin_dir / "hapax-claude-headless", calls / "claude-headless.txt")
    _write_recorder(bin_dir / "hapax-claude", calls / "claude.txt")

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
            "HAPAX_SUPERVISOR_CLAUDE_LANES": "delta",
            "HAPAX_SUPERVISOR_CODEX_LANES": "",
            "HAPAX_SUPERVISOR_ANTIGRAV_LANES": "",
            "HAPAX_SUPERVISOR_RESTART_COOLDOWN_S": "0",
            "HAPAX_CLAUDE_HEADLESS_BIN": str(bin_dir / "hapax-claude-headless"),
            "HAPAX_CLAUDE_BIN": str(bin_dir / "hapax-claude"),
            "HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS": "0",
            # Deterministic admission gate (default open; the defer test sets closed).
            "HAPAX_SUPERVISOR_ADMISSION_CMD": "echo open",
        }
    )
    env.update(overrides)
    return env, calls, runtime_dir


def _make_worktree(env: dict[str, str], lane: str) -> None:
    (Path(env["HAPAX_SUPERVISOR_WORKTREE_ROOT"]) / f"hapax-council--{lane}").mkdir(
        parents=True, exist_ok=True
    )


def _mark_claude_alive(runtime_dir: Path, lane: str) -> None:
    """Point the lane's claude pidfile at a live process so the supervisor's
    claude_alive() short-circuits the respawn path — isolating reaper behavior."""
    (runtime_dir / f"{lane}.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")


def _write_claim(
    env: dict[str, str], lane: str, task_id: str, *, status: str | None, pr: str | None = None
) -> None:
    """Write the lane's claim file. ``status=None`` leaves NO active note (the
    note was moved to closed/) → terminal. A status writes an active/ note."""
    claim_dir = Path(env["HOME"]) / ".cache" / "hapax"
    claim_dir.mkdir(parents=True, exist_ok=True)
    (claim_dir / f"cc-active-task-{lane}").write_text(f"{task_id}\n", encoding="utf-8")
    if status is not None:
        active = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"]) / "active"
        active.mkdir(parents=True, exist_ok=True)
        pr_line = f"pr: {pr}\n" if pr else ""
        (active / f"{task_id}.md").write_text(
            f"---\ntask_id: {task_id}\nstatus: {status}\nassigned_to: {lane}\n{pr_line}"
            f'title: "task {task_id}"\n---\n# task\n',
            encoding="utf-8",
        )


def _spawn_launcher(runtime_dir: Path, lane: str) -> subprocess.Popen[bytes]:
    """A real, long-lived process standing in for a live headless launcher, in
    its OWN session (setsid) so a hypothetical process-group kill would be
    observable and would NOT reach the test runner."""
    proc = subprocess.Popen(["sleep", "600"], start_new_session=True)
    (runtime_dir / f"{lane}.launcher.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    return proc


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SUPERVISOR)], env=env, capture_output=True, text=True, timeout=30)


def _reads(calls: Path, name: str) -> str:
    p = calls / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _wait_dead(proc: subprocess.Popen[bytes], *, timeout: float = 6.0) -> bool:
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def _alive(proc: subprocess.Popen[bytes]) -> bool:
    return proc.poll() is None


def _cleanup(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass


# ─── core: reap a terminal-task launcher (AC2) ────────────────────────────────


def test_supervisor_reaps_launcher_when_task_terminal(tmp_path: Path) -> None:
    """A live launcher whose claimed task is terminal (note left active/) is
    SIGTERM'd within one sweep."""
    env, calls, runtime_dir = _base(tmp_path)
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status=None)  # no active note → terminal
    proc = _spawn_launcher(runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _wait_dead(proc), "terminal-task launcher was not reaped"
        assert "reaping launcher" in result.stdout
    finally:
        _cleanup(proc)


def test_supervisor_keeps_launcher_when_task_live(tmp_path: Path) -> None:
    """A live launcher whose task is still in_progress is NOT reaped."""
    env, calls, runtime_dir = _base(tmp_path)
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "live-task", status="in_progress")
    proc = _spawn_launcher(runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), "a live-task launcher must not be reaped"
        assert "reaping launcher" not in result.stdout
    finally:
        _cleanup(proc)


def test_supervisor_reap_deferred_when_admission_closed(tmp_path: Path) -> None:
    """Terminal-task reap is gated on admission_state: a pressure-closed window
    defers (queue, never drop) — the launcher survives this tick."""
    env, calls, runtime_dir = _base(tmp_path, HAPAX_SUPERVISOR_ADMISSION_CMD="echo closed")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status=None)
    proc = _spawn_launcher(runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), "reap must defer while admission is closed"
        assert "deferring reap" in result.stdout
    finally:
        _cleanup(proc)


def test_supervisor_reaps_launcher_over_lifetime_ceiling(tmp_path: Path) -> None:
    """A launcher past the hard lifetime ceiling is reaped + escalated even when
    its task is still live."""
    notify_log = tmp_path / "notify.txt"
    _write_executable(
        tmp_path / "bin" / "notify-recorder",
        f'#!/usr/bin/env bash\nprintf \'%s|%s\\n\' "$1" "$2" >> "{notify_log}"\n',
    )
    env, calls, runtime_dir = _base(
        tmp_path,
        HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0",  # any age exceeds → reap
        HAPAX_SUPERVISOR_NOTIFY_CMD=str(tmp_path / "bin" / "notify-recorder"),
    )
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "live-task", status="in_progress")  # task LIVE
    proc = _spawn_launcher(runtime_dir, "delta")
    time.sleep(1.2)  # ensure etimes >= 1 so the ceiling=0 trigger is unambiguous
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _wait_dead(proc), "launcher past lifetime ceiling was not reaped"
        assert "lifetime" in result.stdout
        assert notify_log.exists() and "lifetime ceiling" in notify_log.read_text()
    finally:
        _cleanup(proc)


def test_supervisor_reaps_pidfile_free_launcher_over_lifetime_ceiling(tmp_path: Path) -> None:
    """A lock-holding launcher without launcher.pid is still found through /proc
    and reaped once it exceeds the lifetime ceiling."""
    notify_log = tmp_path / "notify.txt"
    _write_executable(
        tmp_path / "bin" / "notify-recorder",
        f'#!/usr/bin/env bash\nprintf \'%s|%s\\n\' "$1" "$2" >> "{notify_log}"\n',
    )
    env, calls, runtime_dir = _base(
        tmp_path,
        HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0",
        HAPAX_SUPERVISOR_NOTIFY_CMD=str(tmp_path / "bin" / "notify-recorder"),
        HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS="1",
    )
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "live-task", status="in_progress")
    launcher = Path(env["HAPAX_CLAUDE_HEADLESS_BIN"])
    _write_executable(
        launcher,
        """
        #!/usr/bin/env python3
        import signal
        import sys
        import time

        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        time.sleep(600)
        """,
    )
    proc = subprocess.Popen(
        [str(launcher), "--task", "live-task", "delta", "prompt"],
        env=env,
        start_new_session=True,
    )
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _wait_dead(proc), "pidfile-free launcher past lifetime ceiling was not reaped"
        assert "lifetime" in result.stdout
        assert notify_log.exists() and "lifetime ceiling" in notify_log.read_text()
    finally:
        _cleanup(proc)


def test_supervisor_reaper_dry_run_does_not_kill(tmp_path: Path) -> None:
    """Dry-run reports the reap it WOULD do but sends no signal."""
    env, calls, runtime_dir = _base(tmp_path, HAPAX_SUPERVISOR_DRY_RUN="1")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status=None)
    proc = _spawn_launcher(runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), "dry-run must not actually reap"
        assert "WOULD reap launcher" in result.stdout
    finally:
        _cleanup(proc)


def test_supervisor_reaper_noop_without_live_launcher(tmp_path: Path) -> None:
    """No launcher pidfile → reaper is a no-op (nothing to reap)."""
    env, calls, runtime_dir = _base(tmp_path)
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status=None)
    # No launcher.pid written.
    result = _run(env)
    assert result.returncode == 0, result.stderr
    assert "reaping launcher" not in result.stdout


def test_supervisor_reaper_can_be_disabled(tmp_path: Path) -> None:
    """HAPAX_SUPERVISOR_REAP_OFF=1 disables the reaper entirely."""
    env, calls, runtime_dir = _base(tmp_path, HAPAX_SUPERVISOR_REAP_OFF="1")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status=None)
    proc = _spawn_launcher(runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), "reaper disabled — launcher must survive"
    finally:
        _cleanup(proc)


# ─── regression pin: single pid, NEVER a process group (exit-144 cascade) ──────


def test_supervisor_reaper_never_uses_process_group_kill() -> None:
    """The reaper must SIGTERM the EXACT launcher pid. A negative pid / process
    group kill (``kill -- -PGID``, ``kill -TERM -<pid>``, killpg) is the pinned
    exit-144 regression that cascaded into sibling lanes."""
    import re

    raw = SUPERVISOR.read_text(encoding="utf-8")
    # Scan CODE only — strip full-line and inline `#` comments so explanatory
    # prose that names the forbidden idiom (`kill -- -PGID`) doesn't trip it.
    code_lines = []
    for line in raw.splitlines():
        if line.lstrip().startswith("#"):
            continue
        code_lines.append(re.sub(r"\s#.*$", "", line))
    code = "\n".join(code_lines)

    assert "killpg" not in code
    # A process-group kill targets a NEGATIVE pid: either an explicit
    # `kill -- -<pgid>` or a dash-prefixed target AFTER the signal flag
    # (`kill -TERM -<pgid>`). Signal flags themselves (`kill -0`, `kill -TERM`,
    # `kill -9`) are legitimate and must NOT match.
    assert not re.search(r"kill\s+--\s+-", code), "kill -- -<pgid> (process group)"
    assert not re.search(r"kill\s+-\w+\s+-", code), "kill -<sig> -<pgid> (process group)"
    # And the reaper positively SIGTERMs a single positive pid variable.
    assert 'kill -TERM "$pid"' in code


def test_supervisor_shell_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(SUPERVISOR)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
