import fcntl
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-headless"
VISIBLE = REPO_ROOT / "scripts" / "hapax-claude"


def _stub_bin(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


def _headless_env(home: Path, bin_dir: Path, pipe_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
    # Don't re-exec into a real systemd scope from the test sandbox.
    env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
    env["HAPAX_CLAUDE_HEADLESS_PIPE_DIR"] = str(pipe_dir)
    # Fast loop so a respawn regression spins (and is caught by the timeout)
    # rather than waiting 30s between iterations.
    env["HAPAX_CLAUDE_HEADLESS_RESTART_BACKOFF_SECONDS"] = "0"
    return env


def test_headless_defaults_to_disabled_without_governed_enable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = "/usr/bin:/bin"
    env.pop("HAPAX_CLAUDE_HEADLESS_ALLOW", None)
    env.pop("HAPAX_CLAUDE_HEADLESS_ENABLE_FILE", None)

    result = subprocess.run(
        [str(SCRIPT), "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 77
    assert "disabled until governed enable exists" in result.stderr


def test_headless_source_prepends_workdir_scripts_to_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'PATH="$WORKDIR/scripts:$PATH"' in text, (
        "headless wrapper must prepend $WORKDIR/scripts to PATH"
    )


def test_headless_source_contains_no_generic_work_pool_prompt() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "claim the next" not in text
    assert "highest-WSJF" not in text
    assert "Never stop" not in text
    assert "governed initial message required" in text
    assert "refusing mutating launch without --task" in text
    assert "Do not create, select, or claim other work from the task pool." in text
    assert "--task TASK_ID" in text
    assert "HAPAX_METHODOLOGY_DISPATCH_TASK" in text


def test_headless_source_supports_governed_model_profile_env() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'MODEL="${HAPAX_CLAUDE_MODEL:-}"' in text
    assert 'CLAUDE_ARGS+=(--model "$MODEL")' in text


def test_appendix_hop_passes_remote_args_without_shell_interpolation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exploit = tmp_path / "logos-url-shell-injection"
    claude_args = tmp_path / "claude-args.txt"
    _stub_bin(
        bin_dir,
        "ssh",
        """remote_cmd="${@: -1}"
case "$remote_cmd" in
  HAPAX_REMOTE_PAYLOAD=*)
    echo 'fish: Expected a variable name after this $' >&2
    exit 127
    ;;
esac
if [[ "$remote_cmd" == *"\\$'"* ]]; then
  echo 'fish: Expected a variable name after this $' >&2
  exit 127
fi
exec bash -c "$remote_cmd"
""",
    )
    _stub_bin(
        bin_dir,
        "gh",
        'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi\nexit 1\n',
    )
    _stub_bin(
        bin_dir,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "appendix"
    env["HAPAX_DISPATCH_LOGOS_URL"] = f"http://podium.invalid/api; touch {exploit}"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert not exploit.exists()
    args = claude_args.read_text(encoding="utf-8").splitlines()
    assert args[:5] == [
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
    ]


def test_visible_claude_launcher_requires_task_or_readonly() -> None:
    text = VISIBLE.read_text(encoding="utf-8")

    assert "--task TASK_ID|--readonly" in text
    assert "refusing mutating visible lane without governed task binding" in text
    assert "hapax-methodology-dispatch" in text
    assert "HAPAX_METHODOLOGY_DISPATCH_TASK" in text
    assert 'CLAUDE_TASK="$CLAIMED_TASK"' in text


def test_headless_refuses_without_task_or_existing_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    claude.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"
    env["HAPAX_SDLC_SLICE_ATTACH"] = "0"
    # Sandbox the launcher lock/pipe dir so a live beta lane on the host doesn't
    # trip the duplicate-launcher guard (exit 16) before the no-task guard (15).
    env["HAPAX_CLAUDE_HEADLESS_PIPE_DIR"] = str(tmp_path / "pipe")

    result = subprocess.run(
        [str(SCRIPT), "beta", "Task: fake\nAuthorityCase: fake\nParent spec: fake"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 15
    assert "without --task" in result.stderr


# ---------------------------------------------------------------------------
# Dispatch idempotency (bug #3): refuse a second live launcher for a lane.
# The reboot storm + naive re-dispatch + the supervisor firing during a
# restart-backoff window otherwise stack zombie wrappers that fight over the
# lane-keyed $ROLE.stdin / $ROLE.pid and re-inject restart prompts forever.
# ---------------------------------------------------------------------------


def test_headless_source_has_launcher_idempotency_guard() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "flock -n" in text
    assert "refusing duplicate launcher" in text


def test_headless_refuses_duplicate_launcher_for_live_lane(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exit 0\n")
    env = _headless_env(home, bin_dir, pipe_dir)

    # Simulate a live incumbent wrapper by holding the lane launcher lock.
    lock_path = pipe_dir / "beta.launcher.lock"
    lock_fd = open(lock_path, "w")  # noqa: SIM115 — held for the subprocess lifetime
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = subprocess.run(
            [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    assert result.returncode == 16, result.stderr
    assert "refusing duplicate launcher" in result.stderr


def test_headless_acquires_launcher_lock_when_lane_free(tmp_path: Path) -> None:
    """When no incumbent holds the lock, the wrapper proceeds (and self-heals)."""
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # claude exits immediately and clears the claim (simulating a closed task),
    # so the lane is free and the loop tears down cleanly on the first pass.
    _stub_bin(
        bin_dir,
        "claude",
        f"echo x >> {counter}\n: > {cache / 'cc-active-task-beta'}\nexit 0\n",
    )
    env = _headless_env(home, bin_dir, pipe_dir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert counter.read_text().count("x") == 1


# ---------------------------------------------------------------------------
# Merge-aware teardown (bug #2): the respawn loop must stop once its task is
# closed (claim cleared / note left active/ / terminal status) or its PR merged
# — not re-inject a generic restart prompt forever.
# ---------------------------------------------------------------------------


def test_headless_source_has_merge_aware_teardown() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "task_is_terminal" in text
    assert "stopping respawn loop" in text


def test_headless_stops_respawning_when_claim_cleared(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Simulate cc-close: the lane finishes, clearing its claim file, then exits.
    _stub_bin(bin_dir, "claude", f"echo x >> {counter}\n: > {claim_file}\nexit 0\n")
    env = _headless_env(home, bin_dir, pipe_dir)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "stopping respawn loop" in result.stdout
    assert counter.read_text().count("x") == 1  # exactly one claude run, no zombie


def test_headless_stops_respawning_when_note_status_terminal(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")  # claim stays
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "active" / "task-x-test.md").write_text("---\ntask_id: task-x\nstatus: done\n---\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", f"echo x >> {counter}\nexit 0\n")  # leaves claim
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "stopping respawn loop" in result.stdout
    assert counter.read_text().count("x") == 1


def test_headless_stops_respawning_when_pr_merged(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "active" / "task-x-test.md").write_text(
        "---\ntask_id: task-x\nstatus: pr_open\npr: 555\n---\n"
    )
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    counter = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", f"echo x >> {counter}\nexit 0\n")
    # gh stub reports the linked PR as merged.
    _stub_bin(bin_dir, "gh", "echo MERGED\n")
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "stopping respawn loop" in result.stdout
    assert counter.read_text().count("x") == 1


# ---------------------------------------------------------------------------
# Out-of-band self-reap (the zombie-launcher bug): the launcher holds the FIFO
# write-end open (exec 3<>), so a persistent stream-json claude NEVER sees EOF,
# `wait` never returns, and the post-turn task_is_terminal teardown is dead code.
# The fix is an out-of-band watchdog that polls task terminality WHILE claude is
# alive and SIGTERMs the child when the task closes/merges — independent of EOF.
# ---------------------------------------------------------------------------


def test_headless_source_has_out_of_band_self_reap() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "self-reaping" in text
    assert "TERMINAL_POLL" in text or "HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS" in text


def test_headless_self_reaps_terminal_task_while_claude_persists(tmp_path: Path) -> None:
    """The core fix: with a PERSISTENT claude (never exits → `wait` would block
    forever), the launcher must still tear down when the task goes terminal,
    driven by the out-of-band poll rather than the (unreachable) EOF path.

    If the watchdog were absent the launcher would hang on `wait` for the full
    `sleep 600` and the 20s subprocess timeout would fail the test.
    """
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")  # claim stays
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    # Terminal status from the start: the first out-of-band poll detects it.
    (vault / "active" / "task-x-test.md").write_text("---\ntask_id: task-x\nstatus: done\n---\n")
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # claude that NEVER exits on its own (the production behavior the bug needs):
    # it must be SIGTERM'd by the out-of-band watchdog.
    _stub_bin(bin_dir, "claude", "exec sleep 600\n")
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)
    env["HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS"] = "0.3"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert "self-reaping" in result.stdout
    assert "stopping respawn loop" in result.stdout


def test_headless_self_reap_keeps_persistent_claude_alive_while_task_live(tmp_path: Path) -> None:
    """The watchdog must NOT reap a persistent claude while the task is still
    live — it only acts once the task is terminal. With a live task the launcher
    blocks (claude never exits), so we assert it TIMES OUT (no premature reap)."""
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    (vault / "active" / "task-x-test.md").write_text(
        "---\ntask_id: task-x\nstatus: in_progress\n---\n"
    )
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exec sleep 600\n")
    env = _headless_env(home, bin_dir, pipe_dir)
    env["HAPAX_CC_TASK_ROOT"] = str(vault)
    env["HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS"] = "0.3"

    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=4,
        )
    # Reap the still-running launcher + its sleep child (own session) so the
    # sandbox doesn't leak processes.
    subprocess.run(["pkill", "-TERM", "-f", "sleep 600"], check=False)


# ---------------------------------------------------------------------------
# Stale-lock handling on startup: a SIGKILL'd launcher skips its EXIT trap,
# stranding the pidfile. The OFD flock still releases on death, so a free lock
# is reacquired normally; but a genuinely-held lock must never be stolen just
# because the recorded pid looks stale.
# ---------------------------------------------------------------------------


def test_headless_source_has_stale_lock_handling() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "stale" in text.lower()
    # On flock failure the incumbent's liveness is verified before refusing.
    assert "kill -0" in text


def test_headless_refuses_when_lock_held_even_with_stale_pidfile(tmp_path: Path) -> None:
    """A live holder of the lock must still be refused (no false steal) even when
    the recorded launcher pid is dead/stale."""
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    pipe_dir = tmp_path / "pipe"
    pipe_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_bin(bin_dir, "claude", "exit 0\n")
    env = _headless_env(home, bin_dir, pipe_dir)

    # A dead/stale pid in the pidfile (pid 2^31-1 is never live).
    (pipe_dir / "beta.launcher.pid").write_text("2147483647\n")
    # A LIVE incumbent holds the lock (Python fd held for the subprocess lifetime).
    lock_path = pipe_dir / "beta.launcher.lock"
    lock_fd = open(lock_path, "w")  # noqa: SIM115
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = subprocess.run(
            [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    assert result.returncode == 16, result.stderr
    assert "refusing duplicate launcher" in result.stderr


# ---------------------------------------------------------------------------
# Drift check (AC3): the committed launcher is the authoritative source — the
# incident was the committed launcher REGRESSING below the deployed runtime (a
# 190-line strip that dropped flock + teardown while the deployed copy had the
# 292-line fix). source-activation only ever deploys FROM git, so pinning the
# committed launcher's fix markers (+ a line-count floor) in CI keeps committed
# and deployed from diverging in the dangerous direction. A byte-equality test
# vs the deployed symlink is intentionally NOT used: it false-fails for the whole
# merged-not-yet-deployed window (the pinned release copy lags main).
# ---------------------------------------------------------------------------


def test_committed_launcher_pins_zombie_reap_fix_markers() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    # flock idempotency + named launcher pidfile
    assert "flock -n" in text
    assert "LAUNCHER_PIDFILE" in text
    # merge-aware terminal detection + out-of-band self-reap
    assert "task_is_terminal" in text
    assert "self-reaping" in text
    assert "stopping respawn loop" in text
    # Line-count floor: the regression stripped the launcher to ~190 lines. The
    # full launcher (flock + teardown + out-of-band self-reap) is well over 250.
    assert len(text.splitlines()) >= 250, "launcher appears stripped — regression risk"
