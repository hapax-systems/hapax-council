"""Tests for the zombie-launcher reaper leg of the FM-11 lane supervisor.

A headless launcher (``hapax-claude-headless``) can outlive its task: the claude
child reads its stdin from a FIFO whose write-end the launcher itself holds open
(``exec 3<>``), so the child never sees EOF, the launcher's ``wait`` never
returns, and its own post-turn ``task_is_terminal`` teardown is unreachable. The
launcher then pins the lane (lifetime flock) and blocks re-dispatch. This was the
dispatch-blocking class: ``pgrep -fc hapax-claude-headless`` ~= 60 while only ~5
lanes were genuinely live.

The supervisor's reaper leg is the PID-targeted backstop. Verified terminal
tasks permit cleanup (SIGTERM, single pid — NEVER a process group), gated on
admission_state below the lifetime ceiling. Age never authorizes terminating
an active or unresolved claim. Claims and launcher identity are rechecked at
the signal boundary, including for lifetime cleanup.

The ceiling reap is routine and silent — every launcher parks there once its
lane idles after a completed turn, and the reap self-heals. Only a ceiling reap
that does NOT take (same pid still over it after the grace window) escalates.

Regression pin (exit-144 cascade): the reaper must SIGTERM the EXACT launcher
pid, never ``kill -- -PGID`` / a negative pid / killpg.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import textwrap
import time
import uuid
from pathlib import Path

import pytest

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
            "HAPAX_LOCAL_DEV_MAINTENANCE_MODE": "local",
            "HAPAX_SUPERVISOR_P0_IDLE_RESPAWN": "0",
            "HAPAX_SUPERVISOR_REAP_OFF": "0",
            "HAPAX_SUPERVISOR_LANEBUS_DIR": str(tmp_path / "lanebus"),
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
    """Write a legacy claim; ``status=None`` leaves the task note unresolved."""
    claim_dir = Path(env["HOME"]) / ".cache" / "hapax"
    claim_dir.mkdir(parents=True, exist_ok=True)
    (claim_dir / f"cc-active-task-{lane}").write_text(f"{task_id}\n", encoding="utf-8")
    (claim_dir / f"cc-claim-epoch-{lane}").write_text(f"17 {task_id}\n")
    if status is not None:
        active = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"]) / "active"
        active.mkdir(parents=True, exist_ok=True)
        pr_line = f"pr: {pr}\n" if pr else ""
        (active / f"{task_id}.md").write_text(
            f"---\ntask_id: {task_id}\nstatus: {status}\nassigned_to: {lane}\n{pr_line}"
            f'title: "task {task_id}"\n---\n# task\n',
            encoding="utf-8",
        )


def _bind_launcher(env, runtime_dir, lane, proc, task):
    """Publish the existing launcher's session PID, role and current-task bindings."""
    sid = str(uuid.uuid4())
    cache = Path(env["HOME"]) / ".cache/hapax"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"session-role-{sid}").write_text(f"{lane}\n")
    claim = cache / f"cc-active-task-{lane}-{sid}"
    claim.write_text(f"{task}\n")
    (cache / f"cc-claim-epoch-{lane}-{sid}").write_text(f"17 {task}\n")
    (runtime_dir / f"{lane}-{sid}.launcher.pid").write_text(f"{proc.pid}\n")
    (runtime_dir / f"{lane}.current-task").write_text(f"{task}\n")
    return claim


def _spawn_launcher(env: dict[str, str], runtime_dir: Path, lane: str) -> subprocess.Popen[bytes]:
    """A real, long-lived process standing in for a live headless launcher, in
    its OWN session (setsid) so a hypothetical process-group kill would be
    observable and would NOT reach the test runner."""
    proc = subprocess.Popen(
        [
            "bash",
            "-c",
            ('exec -a "$2" python3 -c \'import time; time.sleep(600)\' "$1"'),
            "_",
            lane,
            "hapax-claude-headless",
        ],
        env=env,
        start_new_session=True,
    )
    (runtime_dir / f"{lane}.launcher.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    claim = Path(env["HOME"]) / f".cache/hapax/cc-active-task-{lane}"
    if claim.exists():
        _bind_launcher(env, runtime_dir, lane, proc, claim.read_text().strip())
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


@pytest.mark.parametrize("location", ["active", "closed"])
@pytest.mark.parametrize("status", ["done", "completed", "closed", "withdrawn"])
def test_supervisor_reaps_launcher_when_task_terminal(
    tmp_path: Path, location: str, status: str
) -> None:
    """A verified terminal task permits cleanup within one sweep."""
    env, calls, runtime_dir = _base(tmp_path)
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status=status)
    if location == "closed":
        vault = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"])
        (vault / "closed").mkdir()
        (vault / "active/done-task.md").rename(vault / "closed/done-task.md")
    proc = _spawn_launcher(env, runtime_dir, "delta")
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
    proc = _spawn_launcher(env, runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), "a live-task launcher must not be reaped"
        assert "reaping launcher" not in result.stdout
    finally:
        _cleanup(proc)


@pytest.mark.parametrize("ceiling", ["0", "21600"])
@pytest.mark.parametrize("status", ["in_progress", "claimed", "pr_open", "blocked", None])
def test_reaper_preserves_active_or_unresolved_claim(
    tmp_path: Path, ceiling: str, status: str | None
) -> None:
    env, calls, runtime_dir = _base(tmp_path, HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S=ceiling)
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "held-task", status=status)
    cache = Path(env["HOME"]) / ".cache/hapax"
    vault = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"])
    proc = _spawn_launcher(env, runtime_dir, "delta")
    before = {p: p.read_bytes() for root in (cache, vault) for p in root.rglob("*") if p.is_file()}
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "reap_hold:" in result.stdout
        assert not list(calls.iterdir())
        assert {
            p: p.read_bytes() for root in (cache, vault) for p in root.rglob("*") if p.is_file()
        } == before
        state = Path(env["HAPAX_SUPERVISOR_STATE_DIR"])
        assert not (state / "delta.launcher-lifetime-reaped").exists()
        assert not (state / "launchers_reaped_total").exists()
        assert not (state / "launcher_lifetime_reaps_total").exists()
    finally:
        _cleanup(proc)


def test_lifetime_reaper_requires_observed_terminal_task(tmp_path: Path) -> None:
    """No claim is not proof that a launcher has finished its work."""
    env, calls, runtime_dir = _base(tmp_path, HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    proc = _spawn_launcher(env, runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "reap_hold:terminal_state_unverified" in result.stdout
        assert not list(calls.iterdir())
    finally:
        _cleanup(proc)


@pytest.mark.parametrize("owner", ["", "other-lane"])
def test_reaper_requires_terminal_task_owner(tmp_path: Path, owner: str) -> None:
    env, calls, runtime_dir = _base(tmp_path, HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    note = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"]) / "active/done-task.md"
    note.write_text(note.read_text().replace("assigned_to: delta", f"assigned_to: {owner}"))
    proc = _spawn_launcher(env, runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "reap_hold:terminal_state_unverified" in result.stdout
    finally:
        _cleanup(proc)


def test_active_claim_after_prior_lifetime_reap_never_escalates(tmp_path: Path) -> None:
    notify_log = _write_notify_recorder(tmp_path)
    env, calls, runtime_dir = _base(
        tmp_path,
        HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0",
        HAPAX_SUPERVISOR_LIFETIME_REAP_GRACE_S="0",
        HAPAX_SUPERVISOR_NOTIFY_CMD=str(tmp_path / "bin/notify-recorder"),
    )
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "held-task", status="in_progress")
    proc = _spawn_launcher(env, runtime_dir, "delta")
    marker = Path(env["HAPAX_SUPERVISOR_STATE_DIR"]) / "delta.launcher-lifetime-reaped"
    prior = f"{proc.pid} {int(time.time()) - 600}\n"
    marker.write_text(prior)
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "reap_hold:active_or_unresolved_claim" in result.stdout
        assert not notify_log.exists(), "an active-claim hold must not recommend termination"
        assert marker.read_text() == prior
    finally:
        _cleanup(proc)


def test_terminal_legacy_claim_cannot_mask_active_session_claim(tmp_path: Path) -> None:
    env, calls, runtime_dir = _base(tmp_path, HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "held-task", status="in_progress")
    cache = Path(env["HOME"]) / ".cache/hapax"
    session = "a81c4e9a-1111-4444-8888-123456abcdef"
    claim = cache / f"cc-active-task-delta-{session}"
    epoch = cache / f"cc-claim-epoch-delta-{session}"
    claim.write_text("held-task\n")
    epoch.write_text("17 held-task\n")
    _write_claim(env, "delta", "done-task", status="done")
    proc = _spawn_launcher(env, runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "reap_hold:active_or_unresolved_claim" in result.stdout
        assert claim.read_text() == "held-task\n"
        assert epoch.read_text() == "17 held-task\n"
        assert not list(calls.iterdir())
    finally:
        _cleanup(proc)


def test_reaper_rechecks_claim_after_admission(tmp_path: Path) -> None:
    """A task reopened during admission must hold the final signal."""
    env, calls, runtime_dir = _base(tmp_path)
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    note = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"]) / "active/done-task.md"
    env["HAPAX_SUPERVISOR_ADMISSION_CMD"] = (
        f"sed -i 's/status: done/status: in_progress/' {shlex.quote(str(note))}; echo open"
    )
    proc = _spawn_launcher(env, runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert "status: in_progress" in note.read_text()
        assert _alive(proc), result.stdout
        assert "reap_hold:active_or_unresolved_claim" in result.stdout
    finally:
        _cleanup(proc)


@pytest.mark.parametrize("publication", ["empty", "in_progress", "missing"])
@pytest.mark.parametrize("ceiling", ["0", "21600"])
def test_old_terminal_claim_cannot_authorize_current_launcher(
    tmp_path: Path, publication: str, ceiling: str
) -> None:
    env, calls, runtime = _base(tmp_path, HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S=ceiling)
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime, "delta")
    _write_claim(env, "delta", "old-task", status="done")
    cache = Path(env["HOME"]) / ".cache/hapax"
    old = cache / "cc-active-task-delta-a81c4e9a-1111-4444-8888-123456abcdef"
    old.write_text("old-task\n")
    _write_claim(env, "delta", "current-task", status="in_progress")
    proc = _spawn_launcher(env, runtime, "delta")
    current = next(p for p in cache.glob("cc-active-task-delta-*") if p != old)
    # The role marker still points at the old terminal task during publication.
    (cache / "cc-active-task-delta").write_text("old-task\n")
    if publication == "empty":
        current.write_text("")
    elif publication == "missing":
        current.unlink()
    before = {p: p.read_bytes() for p in cache.iterdir()}
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "reap_hold:" in result.stdout
        if publication == "empty":
            assert "empty_claim" in result.stdout
        assert {p: p.read_bytes() for p in cache.iterdir()} == before
        assert not list(calls.iterdir())
        state = Path(env["HAPAX_SUPERVISOR_STATE_DIR"])
        assert not (state / "launchers_reaped_total").exists()
        assert not (state / "delta.launcher-lifetime-reaped").exists()
    finally:
        _cleanup(proc)


@pytest.mark.parametrize(
    "damage", ["missing", "wrong_pid", "stale_pid", "ambiguous", "wrong_role", "wrong_task"]
)
def test_terminal_cleanup_requires_current_launcher_binding(tmp_path: Path, damage: str) -> None:
    env, calls, runtime = _base(tmp_path, HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    proc = _spawn_launcher(env, runtime, "delta")
    binding = next(runtime.glob("delta-*.launcher.pid"))
    sid = binding.name.removeprefix("delta-").removesuffix(".launcher.pid")
    if damage == "missing":
        binding.unlink()
    elif damage == "wrong_pid":
        binding.write_text(f"{os.getpid()}\n")
    elif damage == "stale_pid":
        os.utime(binding, (1, 1))
    elif damage == "ambiguous":
        _bind_launcher(env, runtime, "delta", proc, "done-task")
    elif damage == "wrong_role":
        (Path(env["HOME"]) / f".cache/hapax/session-role-{sid}").write_text("gamma\n")
    else:
        (runtime / "delta.current-task").write_text("other-task\n")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "reap_hold:launcher_binding_unresolved" in result.stdout
        assert not list(calls.iterdir())
    finally:
        _cleanup(proc)


def test_empty_claim_published_after_admission_holds_reap(tmp_path: Path) -> None:
    env, calls, runtime = _base(tmp_path)
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    proc = _spawn_launcher(env, runtime, "delta")
    claim = next((Path(env["HOME"]) / ".cache/hapax").glob("cc-active-task-delta-*"))
    env["HAPAX_SUPERVISOR_ADMISSION_CMD"] = f": > {shlex.quote(str(claim))}; echo open"
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert claim.read_text() == ""
        assert _alive(proc), result.stdout
        assert "empty_claim" in result.stdout
        assert not list(calls.iterdir())
    finally:
        _cleanup(proc)


@pytest.mark.parametrize("key", ["legacy", "session"])
def test_empty_parallel_claim_holds_bound_terminal_launcher(tmp_path: Path, key: str) -> None:
    env, calls, runtime = _base(tmp_path, HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    proc = _spawn_launcher(env, runtime, "delta")
    suffix = "" if key == "legacy" else "-a81c4e9a-1111-4444-8888-123456abcdef"
    claim = Path(env["HOME"]) / f".cache/hapax/cc-active-task-delta{suffix}"
    claim.write_text("")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "empty_claim" in result.stdout
        assert claim.read_text() == ""
        assert not list(calls.iterdir())
    finally:
        _cleanup(proc)


def test_reaper_rechecks_launcher_after_admission(tmp_path: Path) -> None:
    env, calls, runtime_dir = _base(tmp_path)
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    other = _spawn_launcher(env, runtime_dir, "delta")
    proc = _spawn_launcher(env, runtime_dir, "delta")
    pidfile = shlex.quote(str(runtime_dir / "delta.launcher.pid"))
    env["HAPAX_SUPERVISOR_ADMISSION_CMD"] = f"echo {other.pid} > {pidfile}; echo open"
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc) and _alive(other), result.stdout
        assert "reap_hold:launcher_changed" in result.stdout
    finally:
        _cleanup(proc)
        _cleanup(other)


def test_supervisor_reap_deferred_when_admission_closed(tmp_path: Path) -> None:
    """Terminal-task reap is gated on admission_state: a pressure-closed window
    defers (queue, never drop) — the launcher survives this tick."""
    env, calls, runtime_dir = _base(tmp_path, HAPAX_SUPERVISOR_ADMISSION_CMD="echo closed")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    proc = _spawn_launcher(env, runtime_dir, "delta")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), "reap must defer while admission is closed"
        assert "deferring reap" in result.stdout
    finally:
        _cleanup(proc)


def _write_notify_recorder(tmp_path: Path) -> Path:
    """A stand-in for the escalation channel. Its log is the P0-mint evidence:
    notify() is what feeds shared.p0_incident_intake."""
    log = tmp_path / "notify.txt"
    _write_executable(
        tmp_path / "bin" / "notify-recorder",
        f'#!/usr/bin/env bash\nprintf \'%s|%s\\n\' "$1" "$2" >> "{log}"\n',
    )
    return log


def test_supervisor_reaps_launcher_over_lifetime_ceiling_without_escalating(
    tmp_path: Path,
) -> None:
    """Verified terminal cleanup over the ceiling stays quiet on first reap."""
    notify_log = _write_notify_recorder(tmp_path)
    env, calls, runtime_dir = _base(
        tmp_path,
        HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0",  # any age exceeds → reap
        HAPAX_SUPERVISOR_NOTIFY_CMD=str(tmp_path / "bin" / "notify-recorder"),
    )
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    proc = _spawn_launcher(env, runtime_dir, "delta")
    time.sleep(1.2)  # ensure etimes >= 1 so the ceiling=0 trigger is unambiguous
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _wait_dead(proc), "launcher past lifetime ceiling was not reaped"
        assert "lifetime" in result.stdout
        assert not notify_log.exists(), (
            f"routine ceiling reap must not escalate: {notify_log.read_text()}"
        )
    finally:
        _cleanup(proc)


def test_supervisor_escalates_when_lifetime_reap_does_not_take(tmp_path: Path) -> None:
    """A launcher that SURVIVES its ceiling reap is the pathological case, and
    that one does escalate.

    Discriminator: a reap that worked ends the launcher, so the next crossing is
    always a fresh pid. Seeing the SAME pid still over the ceiling after the
    grace window means the SIGTERM did not take.
    """
    notify_log = _write_notify_recorder(tmp_path)
    env, calls, runtime_dir = _base(
        tmp_path,
        HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0",
        HAPAX_SUPERVISOR_LIFETIME_REAP_GRACE_S="0",  # no wait between sweeps in test
        HAPAX_SUPERVISOR_NOTIFY_CMD=str(tmp_path / "bin" / "notify-recorder"),
    )
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    # A launcher that ignores SIGTERM — the reap cannot take.
    proc = subprocess.Popen(
        [
            "bash",
            "-c",
            (
                'exec -a "$2" python3 -c '
                "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                'time.sleep(600)\' "$1"'
            ),
            "_",
            "delta",
            "hapax-claude-headless",
        ],
        env=env,
        start_new_session=True,
    )
    (runtime_dir / "delta.launcher.pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    _bind_launcher(env, runtime_dir, "delta", proc, "done-task")
    time.sleep(1.2)
    try:
        first = _run(env)
        assert first.returncode == 0, first.stderr
        assert _alive(proc), "SIGTERM-immune launcher should still be alive"
        assert not notify_log.exists(), "first crossing must stay quiet"

        second = _run(env)
        assert second.returncode == 0, second.stderr
        assert notify_log.exists(), "a ceiling reap that did not take must escalate"
        assert "lifetime ceiling" in notify_log.read_text()
    finally:
        _cleanup(proc)


def test_supervisor_reaps_pidfile_free_launcher_over_lifetime_ceiling(tmp_path: Path) -> None:
    """A lock-holding launcher without launcher.pid is still found through /proc
    and reaped once it exceeds the lifetime ceiling (still quiet on first
    crossing)."""
    notify_log = _write_notify_recorder(tmp_path)
    env, calls, runtime_dir = _base(
        tmp_path,
        HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0",
        HAPAX_SUPERVISOR_NOTIFY_CMD=str(tmp_path / "bin" / "notify-recorder"),
        HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS="1",
    )
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status="done")
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
        [str(launcher), "--task", "done-task", "delta", "prompt"],
        env=env,
        start_new_session=True,
    )
    _bind_launcher(env, runtime_dir, "delta", proc, "done-task")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _wait_dead(proc), "pidfile-free launcher past lifetime ceiling was not reaped"
        assert "lifetime" in result.stdout
        assert not notify_log.exists(), (
            f"routine ceiling reap must not escalate: {notify_log.read_text()}"
        )
    finally:
        _cleanup(proc)


def test_supervisor_reaper_dry_run_does_not_kill(tmp_path: Path) -> None:
    """Dry-run reports the reap it WOULD do but sends no signal."""
    env, calls, runtime_dir = _base(tmp_path, HAPAX_SUPERVISOR_DRY_RUN="1")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime_dir, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    proc = _spawn_launcher(env, runtime_dir, "delta")
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
    proc = _spawn_launcher(env, runtime_dir, "delta")
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


@pytest.mark.parametrize("epoch_state", ["new_task", "empty", "missing", "malformed", "zero"])
@pytest.mark.parametrize("ceiling", ["0", "21600"])
def test_reaper_holds_claim_publication_window(tmp_path, epoch_state, ceiling):
    """New epoch precedes the session claim overwrite; old terminal bytes cannot reap."""
    env, calls, runtime = _base(tmp_path, HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S=ceiling)
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime, "delta")
    _write_claim(env, "delta", "old-task", status="done")
    proc = _spawn_launcher(env, runtime, "delta")
    cache = Path(env["HOME"]) / ".cache/hapax"
    epoch = next(cache.glob("cc-claim-epoch-delta-*"))
    note = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"]) / "active/new-task.md"
    if epoch_state == "new_task":
        note.write_text("---\ntask_id: new-task\nstatus: in_progress\nassigned_to: delta\n---\n")
    values = {
        "new_task": "18 new-task\n",
        "empty": "",
        "malformed": "invalid",
        "zero": "0 old-task\n",
    }
    if epoch_state == "missing":
        epoch.unlink()
    else:
        epoch.write_text(values[epoch_state])
    before = {p: p.read_bytes() for p in cache.iterdir()}
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "reap_hold:" in result.stdout
        assert {p: p.read_bytes() for p in cache.iterdir()} == before
        assert not list(calls.iterdir())
        assert not (Path(env["HAPAX_SUPERVISOR_STATE_DIR"]) / "launchers_reaped_total").exists()
    finally:
        _cleanup(proc)


def test_reaper_status_vocabulary():
    import ast
    import re

    from shared.sdlc_lifecycle import TASK_TERMINAL_STATUSES

    matched = re.search(r"^terminal = (.+)$", SUPERVISOR.read_text(), re.MULTILINE)
    statuses = ast.literal_eval(matched.group(1))
    legacy = {"cancelled", "canceled", "abandoned"}
    assert statuses - legacy <= TASK_TERMINAL_STATUSES
    assert {"done", "completed", "closed", "withdrawn", "superseded"} <= statuses
    assert "deferred" not in statuses


@pytest.mark.parametrize("epoch_key", ["session", "role"])
def test_new_epoch_for_old_terminal_claim_holds(tmp_path, epoch_key):
    env, calls, runtime = _base(tmp_path, HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    proc = _spawn_launcher(env, runtime, "delta")
    cache = Path(env["HOME"]) / ".cache/hapax"
    epoch = (
        cache / "cc-claim-epoch-delta"
        if epoch_key == "role"
        else next(cache.glob("cc-claim-epoch-delta-*"))
    )
    epoch.write_text("18 new-task\n")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "reap_hold:" in result.stdout
        assert not list(calls.iterdir())
    finally:
        _cleanup(proc)


@pytest.mark.parametrize("changed", ["epoch", "note", "new_claim", "new_note"])
def test_reaper_rejects_input_changed_during_observation(tmp_path, changed):
    """Run the actual embedded observer; publish new bytes during its final read."""
    import sys

    env, _, runtime = _base(tmp_path)
    _write_claim(env, "delta", "done-task", status="done")
    proc = _spawn_launcher(env, runtime, "delta")
    cache = Path(env["HOME"]) / ".cache/hapax"
    note = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"]) / "active/done-task.md"
    target = next(cache.glob("cc-claim-epoch-delta-*")) if changed == "epoch" else note
    new_bytes = (
        b"18 done-task\n"
        if changed == "epoch"
        else note.read_bytes().replace(b"status: done", b"status: in_progress")
    )
    trigger = target
    trigger_read = 3 if changed == "note" else 2
    reason = "reap_input_changed"
    if changed in {"new_claim", "new_note"}:
        trigger = runtime / "delta.current-task"
        trigger_read = 1
        if changed == "new_claim":
            target = cache / f"cc-active-task-delta-{uuid.uuid4()}"
            new_bytes = b"new-task\n"
            reason = "claim_inventory_changed"
        else:
            target = note.with_name("new-task.md")
            new_bytes = b"---\ntask_id: new-task\nstatus: in_progress\nassigned_to: delta\n---\n"
            reason = "task_note_inventory_changed"
    observer = SUPERVISOR.read_text().split("<<'PYCLAIM'\n", 1)[1].split("\nPYCLAIM", 1)[0]
    # Publish during final validation, or insert a new key after the initial
    # inventory was read, before the observer can authorize any signal.
    instrument = f"""from pathlib import Path
original = Path.read_bytes
reads = 0
def publish(self):
    global reads
    if str(self) == {str(trigger)!r}:
        reads += 1
        if reads == {trigger_read}:
            Path({str(target)!r}).write_bytes({new_bytes!r})
    return original(self)
Path.read_bytes = publish
"""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-",
                str(REPO_ROOT),
                env["HAPAX_SUPERVISOR_VAULT_ROOT"],
                "delta",
                str(runtime),
                env["HAPAX_SUPERVISOR_STATE_DIR"],
                env["HAPAX_SUPERVISOR_LANEBUS_DIR"],
                "reap",
                str(proc.pid),
            ],
            input=instrument + observer,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert target.read_bytes() == new_bytes
        assert result.returncode == 1, result.stdout + result.stderr
        assert reason in result.stdout
    finally:
        _cleanup(proc)


@pytest.mark.parametrize("location", ["active", "closed"])
def test_runbook_displays_launcher_note_and_epoch(tmp_path, location):
    import sys

    env, _, runtime = _base(tmp_path)
    _write_claim(env, "delta", "done-task", status="completed")
    vault = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"])
    if location == "closed":
        (vault / "closed").mkdir()
        (vault / "active/done-task.md").rename(vault / "closed/done-task.md")
    proc = _spawn_launcher(env, runtime, "delta")
    command = (REPO_ROOT / "docs/runbooks/lane-death-forensics.md").read_text()
    command = command.split("python3 - \"$lane\" <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    try:
        result = subprocess.run(
            [sys.executable, "-", "delta"],
            input=command,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert "status completed" in result.stdout
        assert "assigned_to delta" in result.stdout
        assert "task_id done-task" in result.stdout
        assert str(vault / location / "done-task.md") in result.stdout
        assert "cc-claim-epoch-delta-" in result.stdout
        assert "17 done-task" in result.stdout
    finally:
        _cleanup(proc)


def test_new_owned_note_before_epoch_publication_holds_reap(tmp_path):
    env, calls, runtime = _base(tmp_path, HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S="0")
    _make_worktree(env, "delta")
    _mark_claude_alive(runtime, "delta")
    _write_claim(env, "delta", "done-task", status="done")
    proc = _spawn_launcher(env, runtime, "delta")
    note = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"]) / "active/new-task.md"
    note.write_text("---\ntask_id: new-task\nstatus: in_progress\nassigned_to: delta\n---\n")
    try:
        result = _run(env)
        assert result.returncode == 0, result.stderr
        assert _alive(proc), result.stdout
        assert "reap_hold:nonterminal_owned_note" in result.stdout
        assert not list(calls.iterdir())
    finally:
        _cleanup(proc)
