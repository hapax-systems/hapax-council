import base64
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import textwrap
import time
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
    # Host-independence: a remotely-dispatched test runner (appendix lanes)
    # carries its OWN dispatch/identity env; scrub it so the launcher under
    # test sees only what each test sets explicitly.
    for var in (
        "HAPAX_DISPATCH_HOST",
        "HAPAX_DISPATCH_HOST_FALLBACK",
        "HAPAX_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "HAPAX_AGENT_ROLE",
        "HAPAX_AGENT_NAME",
        "CLAUDE_ROLE",
        "HAPAX_WORKTREE_ROLE",
        "HAPAX_METHODOLOGY_DISPATCH_TASK",
        "HAPAX_CLAUDE_BIN",
        "HAPAX_CLAUDE_BIN_PATH",
        "NPM_CONFIG_PREFIX",
    ):
        env.pop(var, None)
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


def test_headless_uses_npm_global_claude_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_args = tmp_path / "claude-args.txt"
    npm_bin = home / ".npm-global" / "bin"
    npm_bin.mkdir(parents=True)
    _stub_bin(
        npm_bin,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert claude_args.exists()


def test_headless_honors_explicit_claude_bin_override(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_args = tmp_path / "claude-args.txt"
    explicit_bin = tmp_path / "explicit" / "claude"
    explicit_bin.parent.mkdir()
    _stub_bin(
        explicit_bin.parent,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_BIN"] = str(explicit_bin)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert claude_args.exists()


def test_headless_rejects_invalid_explicit_claude_bin_override(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fallback_marker = tmp_path / "fallback-used"
    _stub_bin(bin_dir, "claude", f"touch {fallback_marker}\nexit 0\n")
    explicit_bin = tmp_path / "explicit" / "claude"
    explicit_bin.parent.mkdir()
    explicit_bin.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    explicit_bin.chmod(0o644)
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_CLAUDE_BIN"] = str(explicit_bin)

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 4
    assert "configured Claude binary is not executable" in result.stderr
    assert not fallback_marker.exists()


def test_appendix_hop_passes_remote_args_without_shell_interpolation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    execution_home = tmp_path / "execution-home"
    execution_home.mkdir()
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    _remote_contract_modules(workdir)
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
exec env HOME="{execution_home}" bash -c "$remote_cmd"
""".replace("{execution_home}", str(execution_home)),
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
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"
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
    assert not list((tmp_path / "pipe").glob("beta-*.pid")), "SSH PID is not a local writer binding"
    args = claude_args.read_text(encoding="utf-8").splitlines()
    assert args[:5] == [
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
    ]


def test_appendix_short_alias_is_local_on_appendix(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_called = tmp_path / "ssh-called"
    claude_args = tmp_path / "claude-args.txt"
    _stub_bin(
        bin_dir,
        "hostname",
        """
case "${1:-}" in
  -s|-f) printf '%s\n' hapax-appendix ;;
  *) printf '%s\n' hapax-appendix ;;
esac
""",
    )
    _stub_bin(
        bin_dir,
        "ssh",
        f": > {ssh_called}\necho 'ssh should not be called for local appendix alias' >&2\nexit 99\n",
    )
    _stub_bin(
        bin_dir,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "appendix"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert not ssh_called.exists()
    assert claude_args.exists()


def test_appendix_local_ip_skips_ssh_on_appendix(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh_called = tmp_path / "ssh-called"
    claude_args = tmp_path / "claude-args.txt"
    _stub_bin(
        bin_dir,
        "hostname",
        """
case "${1:-}" in
  -s|-f) printf '%s\n' hapax-appendix ;;
  -I) printf '%s\n' '192.168.68.50 10.0.0.50' ;;
  *) printf '%s\n' hapax-appendix ;;
esac
""",
    )
    _stub_bin(
        bin_dir,
        "ssh",
        f": > {ssh_called}\necho 'ssh should not be called for local appendix IP' >&2\nexit 99\n",
    )
    _stub_bin(
        bin_dir,
        "claude",
        f'printf "%s\\n" "$@" > {claude_args}\n: > {claim_file}\nexit 0\n',
    )
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "192.168.68.50"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert not ssh_called.exists()
    assert claude_args.exists()


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
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
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
    markers = list(cache.glob("session-role-*"))
    assert len(markers) == 1
    sid = markers[0].name.removeprefix("session-role-")
    child_pid = int((pipe_dir / f"beta-{sid}.pid").read_text())
    launcher_pid = int((pipe_dir / f"beta-{sid}.launcher.pid").read_text())
    assert not Path(f"/proc/{child_pid}").exists()
    assert not Path(f"/proc/{launcher_pid}").exists()
    assert not (pipe_dir / "beta.pid").exists()


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


# ---------------------------------------------------------------------------
# Session identity through the dispatch boundary (taxonomy-a3-session-identity):
# the launcher mints HAPAX_SESSION_ID per spawn, but before the fix the G2
# remote hop dropped every identity var at the SSH boundary — the appendix
# claude resolved a DIFFERENT session id (CLAUDE_CODE_SESSION_ID), the
# session-keyed claim file existed only podium-side, and the dispatch proof
# witnessed the exec by pid alone. The lane then hit cc-claim exit-4 walls
# (see relay receipts epsilon-claim-rejected.yaml, zeta-claim-rejected.yaml).
# The identity thread must survive the hop: payload env -> remote exec ->
# marker + claim materialization on the exec host -> session-stamped proof.
# ---------------------------------------------------------------------------


def test_headless_mint_fallback_is_never_pid_derived() -> None:
    """Claim-by-pid unrepresentable: the retired `<role>-$$` fallback minted
    pid-shaped session ids that cc-claim now refuses to key."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"$ROLE" "$$"' not in text, "launcher session-id fallback mints pid-shaped ids"


def test_headless_preamble_carries_session_identity() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Session identity: role=$ROLE session_id=$SESSION_UUID" in text


@pytest.mark.parametrize("existing_remote_claim", [False, True])
def test_appendix_hop_threads_session_identity_end_to_end(
    tmp_path: Path, existing_remote_claim: bool
) -> None:
    """E2E canary: fake ssh executes locally with a separate execution HOME,
    so the assertions cover the full chain — launcher mint -> payload env ->
    remote exec env -> exec-host marker/claim materialization -> proof."""
    home = tmp_path / "home"
    workdir = home / "projects" / "hapax-council--beta"
    workdir.mkdir(parents=True)
    _remote_contract_modules(workdir)
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_file = cache / "cc-active-task-beta"
    claim_file.write_text("task-x\n")
    execution_home = tmp_path / "execution-home"
    execution_cache = execution_home / ".cache/hapax"
    execution_cache.mkdir(parents=True)
    if existing_remote_claim:
        (execution_cache / "cc-active-task-beta").write_text("task-x\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude_env = tmp_path / "claude-env.txt"
    # Simulate the real SSH env boundary: the remote shell never inherits the
    # launcher's exports, so identity can ONLY arrive via the exec payload.
    _stub_bin(
        bin_dir,
        "ssh",
        'remote_cmd="${@: -1}"\n'
        "exec env -u HAPAX_SESSION_ID -u HAPAX_AGENT_INTERFACE -u HAPAX_AGENT_NAME"
        " -u HAPAX_AGENT_ROLE -u CLAUDE_ROLE -u HAPAX_WORKTREE_ROLE"
        f' -u HAPAX_METHODOLOGY_DISPATCH_TASK HOME="{execution_home}" bash -c "$remote_cmd"\n',
    )
    _stub_bin(
        bin_dir,
        "gh",
        'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then exit 0; fi\nexit 1\n',
    )
    # The "remote" claude dumps its env, then clears the legacy claim so the
    # respawn loop tears down after one pass.
    _stub_bin(bin_dir, "claude", f"env > {claude_env}\n: > {claim_file}\nexit 0\n")
    env = _headless_env(home, bin_dir, tmp_path / "pipe")
    env["HAPAX_DISPATCH_HOST"] = "appendix-remote"

    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr

    proofs = sorted((cache / "orchestration" / "dispatch-host-proofs").glob("*.json"))
    assert proofs, "remote exec must write a dispatch proof"
    proof = json.loads(proofs[-1].read_text(encoding="utf-8"))
    if existing_remote_claim:
        assert not claude_env.exists()
        assert {path.name: path.read_bytes() for path in execution_cache.iterdir()} == {
            "cc-active-task-beta": b"task-x\n"
        }
        assert proof["claim_materialized"] is False and proof["claim_epoch"] is None
        assert proof["dispatch_state"] == "hold"
        assert proof["claim_materialization_reason"] == "remote_claim_binding_unresolved"
        return

    # One session id, minted by the launcher, recorded in the role marker.
    markers = sorted(cache.glob("session-role-*"))
    assert len(markers) == 1, f"expected exactly one session marker, got {markers}"
    sid = markers[0].name.removeprefix("session-role-")
    assert markers[0].read_text().strip() == "beta"
    assert (execution_cache / markers[0].name).read_text() == "beta\n"

    # The exec-side claude carries the SAME identity the launcher minted.
    claude_vars = dict(
        line.split("=", 1) for line in claude_env.read_text().splitlines() if "=" in line
    )
    assert claude_vars.get("HAPAX_SESSION_ID") == sid
    assert claude_vars.get("HAPAX_AGENT_ROLE") == "beta"
    assert claude_vars.get("CLAUDE_ROLE") == "beta"
    assert claude_vars.get("HAPAX_METHODOLOGY_DISPATCH_TASK") == "task-x"

    # Only remote materialization can populate the initially empty exec cache.
    keyed = execution_cache / f"cc-active-task-beta-{sid}"
    assert keyed.read_text(encoding="utf-8") == "task-x\n"
    epoch_sidecar = execution_cache / f"cc-claim-epoch-beta-{sid}"
    epoch, _, sidecar_task = epoch_sidecar.read_text(encoding="utf-8").strip().partition(" ")
    assert epoch.isdigit()
    assert sidecar_task == "task-x"

    # The dispatch proof witnesses the session, not just the pid.
    assert proof["session_id"] == sid
    assert proof["role"] == "beta"
    assert proof["task_id"] == "task-x"
    assert proof["claim_materialized"] is True


# ---------------------------------------------------------------------------
# task_is_terminal: claim-stamp drift must not reap a fresh live lane.
# 2026-07-01 eta/ndcvb-phase1 incident: cc-claim's note stamp landed partially
# (claimed_at key absent in the authored note), cc-hygiene H1 reverted the
# note to offered/unassigned 13s later, and the assigned-mismatch branch
# returned terminal — SIGTERMing a healthy freshly-launched worker.
# ---------------------------------------------------------------------------


def _run_task_is_terminal_result(
    tmp_path: Path,
    *,
    cache_task: str | None,
    note_status: str,
    note_assigned: str,
    cache_age_s: int = 0,
    note_pr: int | None = None,
    gh_state: str = "",
    legacy_cache: bool = False,
    sidecar_task: str | None = None,
    session_keyed_cache: bool = False,
    legacy_cache_task: str | None = None,
    older_matching_session_cache: bool = False,
    epoch_check_bypass: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Extract task_is_terminal() from the launcher and drive it with fixtures.

    Returns the bash exit code: 0 = terminal (lane reaped), 1 = live.

    ``cache_age_s`` ages the claim EPOCH recorded in the task-bound
    ``cc-claim-epoch-*`` sidecar while the claim file's mtime stays fresh —
    deliberately simulating the cc-task-gate lease-keep-alive ``touch`` that
    makes mtime useless as a claim-age witness. ``legacy_cache`` writes no
    sidecar (non-conforming-writer shape). ``sidecar_task`` overrides the
    task id recorded in the sidecar (stale-sidecar shape).
    """
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True, exist_ok=True)
    note = tmp_path / "note.md"
    pr_line = f"pr: {note_pr}\n" if note_pr is not None else ""
    note.write_text(
        f"---\nstatus: {note_status}\nassigned_to: {note_assigned}\n{pr_line}---\n",
        encoding="utf-8",
    )
    sid = "9b6ba5ca-513c-41aa-9900-d3026b42aad1"
    old_sid = "00000000-0000-4000-8000-000000000001"
    claim_file = cache / "cc-active-task-eta"
    session_claim_file = cache / f"cc-active-task-eta-{sid}"
    active_claim_file = session_claim_file if session_keyed_cache else claim_file
    sidecar = (
        cache / f"cc-claim-epoch-eta-{sid}" if session_keyed_cache else cache / "cc-claim-epoch-eta"
    )
    sidecar.unlink(missing_ok=True)
    if older_matching_session_cache:
        older_claim = cache / f"cc-active-task-eta-{old_sid}"
        older_sidecar = cache / f"cc-claim-epoch-eta-{old_sid}"
        older_claim.write_text("task-under-test\n", encoding="utf-8")
        older_sidecar.write_text(f"{int(time.time()) - 3600} task-under-test\n", encoding="utf-8")
    if legacy_cache_task is not None:
        claim_file.write_text(legacy_cache_task + "\n", encoding="utf-8")
    if cache_task is not None:
        active_claim_file.write_text(cache_task + "\n", encoding="utf-8")
        if legacy_cache:
            if cache_age_s:
                aged = time.time() - cache_age_s
                os.utime(active_claim_file, (aged, aged))
        else:
            epoch = int(time.time()) - cache_age_s
            bound_task = sidecar_task if sidecar_task is not None else cache_task
            sidecar.write_text(f"{epoch} {bound_task}\n", encoding="utf-8")
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("task_is_terminal()")
    end = text.index("\n}\n", start) + 3
    func = text[start:end]
    gh_stub = f'gh() {{ echo "{gh_state}"; }}' if gh_state else "gh() { return 1; }"
    harness = "\n".join(
        [
            "set -u",
            f'HOME="{home}"',
            'ROLE="eta"',
            f'CLAIM_FILE="{claim_file}"',
            f'SESSION_CLAIM_FILE="{session_claim_file}"',
            f'HAPAX_CLAIM_EPOCH_CHECK_BYPASS="{1 if epoch_check_bypass else 0}"',
            f'find_active_note() {{ echo "{note}"; }}',
            gh_stub,
            func,
            'task_is_terminal "task-under-test"',
        ]
    )
    result = subprocess.run(["bash", "-c", harness], text=True, capture_output=True, check=False)
    assert result.returncode in (0, 1), result.stderr
    return result


def _run_task_is_terminal(
    tmp_path: Path,
    *,
    cache_task: str | None,
    note_status: str,
    note_assigned: str,
    cache_age_s: int = 0,
    note_pr: int | None = None,
    gh_state: str = "",
    legacy_cache: bool = False,
    sidecar_task: str | None = None,
    session_keyed_cache: bool = False,
    legacy_cache_task: str | None = None,
    older_matching_session_cache: bool = False,
    epoch_check_bypass: bool = False,
) -> int:
    """Return the bash exit code: 0 = terminal (lane reaped), 1 = live."""
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task=cache_task,
        note_status=note_status,
        note_assigned=note_assigned,
        cache_age_s=cache_age_s,
        note_pr=note_pr,
        gh_state=gh_state,
        legacy_cache=legacy_cache,
        sidecar_task=sidecar_task,
        session_keyed_cache=session_keyed_cache,
        legacy_cache_task=legacy_cache_task,
        older_matching_session_cache=older_matching_session_cache,
        epoch_check_bypass=epoch_check_bypass,
    )
    return result.returncode


def test_terminal_check_survives_claim_stamp_drift(tmp_path: Path) -> None:
    """Matching claim cache + ghost-reverted note (offered/unassigned) = LIVE."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
    )
    assert rc == 1


def test_terminal_check_reaps_reassignment_even_with_fresh_cache(
    tmp_path: Path,
) -> None:
    """assigned_to naming ANOTHER ROLE is definitive terminal even while our
    cache is fresh — the gate touches the cache before any check (lease
    keep-alive), so a reassigned old lane attempting gated writes keeps its
    own cache fresh; an mtime bound alone could never reap it."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="claimed",
        note_assigned="some-other-role",
        cache_age_s=0,
    )
    assert rc == 0


def test_terminal_check_reaps_long_unassigned_despite_gate_heartbeat(
    tmp_path: Path,
) -> None:
    """The H1-revert indeterminate shape is bounded by the claim EPOCH in the
    cache content — the harness keeps mtime fresh (the gate's lease
    keep-alive touch), so this proves the bound is heartbeat-immune: a lane
    sitting on a long-unassigned task reaps even while it keeps writing."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        cache_age_s=3600,
    )
    assert rc == 0


@pytest.mark.parametrize("note_assigned", ["", "null", "none", "~", "[]", '"null"'])
def test_terminal_check_treats_nullish_assignee_as_unassigned(
    tmp_path: Path, note_assigned: str
) -> None:
    """Nullish YAML spellings are the unassigned drift shape, not a named role."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned=note_assigned,
        cache_age_s=3600,
    )
    assert rc == 0


def test_terminal_check_reaps_sidecarless_cache(tmp_path: Path) -> None:
    """No mtime fallback: mtime is heartbeat-refreshed by the gate, so a
    matching cache with NO sidecar (non-conforming writer) reaps in the
    unassigned-drift shape rather than living unbounded."""
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        legacy_cache=True,
    )
    assert result.returncode == 0
    assert "no valid task-bound epoch sidecar" in result.stderr
    assert "non-conforming writer" in result.stderr


def test_terminal_check_ignores_stale_sidecar_bound_to_other_task(tmp_path: Path) -> None:
    """A sidecar naming a DIFFERENT task (stale leftover from an earlier
    claim) must not vouch for this claim — the lane reaps."""
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        sidecar_task="an-earlier-task",
    )
    assert result.returncode == 0
    assert "sidecar names task=an-earlier-task" in result.stderr
    assert "stale sidecar" in result.stderr


def test_terminal_check_logs_expired_unassigned_claim(tmp_path: Path) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        cache_age_s=3600,
    )
    assert result.returncode == 0
    assert "exceeds grace=600s" in result.stderr
    assert "stale unassigned claim" in result.stderr


def test_terminal_check_uses_session_keyed_epoch_sidecar(tmp_path: Path) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        session_keyed_cache=True,
    )
    assert result.returncode == 1
    assert "session-keyed:cc-active-task-eta-" in result.stderr
    assert "treating as indeterminate" in result.stderr


def test_terminal_check_prefers_matching_session_cache_over_repointed_legacy(
    tmp_path: Path,
) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        session_keyed_cache=True,
        legacy_cache_task="newer-task-on-shared-role",
    )
    assert result.returncode == 1
    assert "session-keyed:cc-active-task-eta-" in result.stderr
    assert "treating as indeterminate" in result.stderr


def test_terminal_check_prefers_exact_session_over_older_same_task_lease(
    tmp_path: Path,
) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        session_keyed_cache=True,
        older_matching_session_cache=True,
    )
    assert result.returncode == 1
    assert "session-keyed:cc-active-task-eta-9b6ba5ca-" in result.stderr
    assert "treating as indeterminate" in result.stderr


def test_terminal_check_epoch_bypass_keeps_matching_cache_live(tmp_path: Path) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        legacy_cache=True,
        epoch_check_bypass=True,
    )
    assert result.returncode == 1
    assert "HAPAX_CLAIM_EPOCH_CHECK_BYPASS=1" in result.stderr
    assert "repair the writer" in result.stderr


def test_terminal_check_epoch_bypass_still_reaps_merged_pr(tmp_path: Path) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        note_pr=4242,
        gh_state="MERGED",
        legacy_cache=True,
        epoch_check_bypass=True,
    )
    assert result.returncode == 0
    assert "HAPAX_CLAIM_EPOCH_CHECK_BYPASS=1" in result.stderr


def test_terminal_check_reaps_when_cache_repointed(tmp_path: Path) -> None:
    """A cache naming a DIFFERENT task is claim_moved, never terminal by
    itself (2026-09-16 claim-hop fix): the launcher re-binds and evaluates the
    NEW task's own row. Here the hop target is claimed by another role —
    definitive terminal (two lanes never own one task)."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="a-different-task",
        note_status="claimed",
        note_assigned="some-other-role",
    )
    assert rc == 0


def test_terminal_check_reaps_done_note(tmp_path: Path) -> None:
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="done",
        note_assigned="eta",
    )
    assert rc == 0


def test_terminal_check_reaps_foreign_assignee_when_cache_stale(tmp_path: Path) -> None:
    """Reassignment to a named role reaps regardless of cache age."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="claimed",
        note_assigned="some-other-role",
        cache_age_s=3600,
    )
    assert rc == 0


def test_terminal_check_reaps_foreign_assignee_with_no_cache(tmp_path: Path) -> None:
    """Missing cache + foreign assignee is the genuinely-reassigned shape."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task=None,
        note_status="claimed",
        note_assigned="some-other-role",
    )
    assert rc == 0


def test_terminal_check_reaps_unassigned_note_with_no_cache(tmp_path: Path) -> None:
    result = _run_task_is_terminal_result(
        tmp_path,
        cache_task=None,
        note_status="offered",
        note_assigned="unassigned",
    )
    assert result.returncode == 0
    assert "no matching claim cache" in result.stderr
    assert "rerun cc-claim" in result.stderr


def test_terminal_check_indeterminate_still_reaps_merged_pr(tmp_path: Path) -> None:
    """The drift-survival fall-through still honors the merged-PR terminal."""
    rc = _run_task_is_terminal(
        tmp_path,
        cache_task="task-under-test",
        note_status="offered",
        note_assigned="unassigned",
        note_pr=4242,
        gh_state="MERGED",
    )
    assert rc == 0


@pytest.mark.parametrize(
    ("current", "exit_code", "kill_reason", "expected"),
    [
        ('{"type":"assistant"}\n', "0", "", "own_exit:code_0"),
        ('{"type":"result"}\n', "0", "", "clean exit (headless)"),
        ('{"type": "result"}\n', "0", "", "clean exit (headless)"),
        ('{"type":"result"}\n', "143", "task_terminal", "self_reap:task_terminal"),
        ('{"type":"result"}\n', "1", "", "own_exit:code_1"),
    ],
)
def test_retire_reason_uses_only_last_child_output(
    tmp_path, current, exit_code, kill_reason, expected
):
    """A previous child's result must not certify the last child's quiet exit."""
    history = '{"type":"result","result":"previous attempt"}\n'
    log = tmp_path / "output.jsonl"
    log.write_text(history + current)
    source = SCRIPT.read_text()
    functions = source[source.index("last_log_line() {") : source.index("cleanup() {")]
    env = {
        **os.environ,
        "LOG_FILE": str(log),
        "LAST_CHILD_EXIT_CODE": exit_code,
        "LAST_KILL_REASON": kill_reason,
        "LAST_CHILD_LOG_OFFSET": str(len(history.encode())),
        "DISABLE_FILE": str(tmp_path / "no-latch"),
    }
    result = subprocess.run(
        ["bash", "-c", functions + "\ncompute_retire_reason 0\n"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.startswith(expected), result.stdout
    assert log.read_text() == history + current


def test_launcher_attempt_wiring_and_supervisor_pid_binding(tmp_path: Path) -> None:
    """Exercise both sides of the binding with actual launcher-produced PID files."""
    home = tmp_path / "home"
    (home / "projects/hapax-council--beta").mkdir(parents=True)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    claim = cache / "cc-active-task-beta"
    claim.write_text("task-x\n")
    vault = tmp_path / "vault"
    (vault / "active").mkdir(parents=True)
    note = vault / "active/task-x.md"
    note.write_text("---\ntask_id: task-x\nstatus: in_progress\nassigned_to: beta\n---\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pipe = tmp_path / "pipe"
    _stub_bin(
        bin_dir,
        "claude",
        """if [ ! -f "$ATTEMPT_FILE" ]; then
  printf 'first\n' > "$ATTEMPT_FILE"
  printf '{"type":"result"}\n'
  exit 0
fi
printf 'second\n' >> "$ATTEMPT_FILE"
printf -- '---\ntask_id: task-x\nstatus: done\nassigned_to: beta\n---\n' > "$TEST_TASK_NOTE"
: > "$HOME/.cache/hapax/cc-active-task-beta"
exit 0
""",
    )
    _stub_bin(bin_dir, "detect-quota-wall", "exit 0\n")
    _stub_bin(bin_dir, "tmux", 'case "$1" in has-session) exit 1;; *) exit 0;; esac\n')
    retire_scripts = tmp_path / "retire/scripts"
    retire_scripts.mkdir(parents=True)
    _stub_bin(retire_scripts, "hapax-relay-retire", 'printf "%s\\n" "$*" > "$RETIRE_LOG"\n')
    env = _headless_env(home, bin_dir, pipe)
    env.update(
        HAPAX_CC_TASK_ROOT=str(vault),
        HAPAX_COUNCIL_DIR=str(tmp_path / "retire"),
        HAPAX_CLAUDE_HEADLESS_TERMINAL_POLL_SECONDS="60",
        ATTEMPT_FILE=str(tmp_path / "attempts"),
        TEST_TASK_NOTE=str(note),
        RETIRE_LOG=str(tmp_path / "retire.log"),
    )
    result = subprocess.run(
        [str(SCRIPT), "--task", "task-x", "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "attempts").read_text().splitlines() == ["first", "second"]
    assert "own_exit:code_0" in (tmp_path / "retire.log").read_text()
    assert "clean exit" not in (tmp_path / "retire.log").read_text()
    sid = next(cache.glob("session-role-*")).name.removeprefix("session-role-")
    # Set up the lease left after a dead session, without synthesizing its PID
    # observation: those bytes MUST come from the launcher above.
    note.write_text("---\ntask_id: task-x\nstatus: in_progress\nassigned_to: beta\n---\n")
    (cache / f"cc-active-task-beta-{sid}").write_text("task-x\n")
    (cache / f"cc-claim-epoch-beta-{sid}").write_text("17|test-epoch\n")
    before = {p.name: p.read_bytes() for p in cache.glob("cc-*")}
    env.update(
        HAPAX_SUPERVISOR_STATE_DIR=str(tmp_path / "state"),
        HAPAX_SUPERVISOR_RUNTIME_DIR=env["HAPAX_CLAUDE_HEADLESS_PIPE_DIR"],
        HAPAX_SUPERVISOR_VAULT_ROOT=str(vault),
        HAPAX_SUPERVISOR_WORKTREE_ROOT=str(home / "projects"),
        HAPAX_SUPERVISOR_CLAUDE_LANES="beta",
        HAPAX_SUPERVISOR_CODEX_LANES="",
        HAPAX_SUPERVISOR_REAP_OFF="1",
        HAPAX_SUPERVISOR_PROGRESS_OFF="1",
        HAPAX_SUPERVISOR_PROC_SCAN_LAUNCHERS="0",
        HAPAX_SUPERVISOR_P0_IDLE_RESPAWN="0",
        HAPAX_LOCAL_DEV_MAINTENANCE_MODE="local",
        HAPAX_SUPERVISOR_LANEBUS_DIR=str(tmp_path / "lanebus"),
    )
    result = subprocess.run(
        [str(REPO_ROOT / "scripts/hapax-lane-supervisor")],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert f"claim_orphaned:task-x:{sid}" in result.stdout
    assert "governed_rebind_required" in result.stdout
    assert {p.name: p.read_bytes() for p in cache.glob("cc-*")} == before


def test_launcher_and_supervisor_default_pid_directory_match():
    """Production defaults must agree as well as explicitly bound test paths."""
    supervisor = (REPO_ROOT / "scripts/hapax-lane-supervisor").read_text()
    launcher = SCRIPT.read_text()
    assignments = [
        next(line for line in supervisor.splitlines() if line.startswith("RUNTIME_DIR=")),
        next(line for line in launcher.splitlines() if line.startswith("PIPE_DIR=")),
    ]
    env = os.environ.copy()
    env.pop("HAPAX_SUPERVISOR_RUNTIME_DIR", None)
    env.pop("HAPAX_CLAUDE_HEADLESS_PIPE_DIR", None)
    result = subprocess.run(
        ["bash", "-c", "\n".join(assignments) + '\n[ "$RUNTIME_DIR" = "$PIPE_DIR" ]'],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# Consumer tests substitute the dependency interface. The actual PR4726 interface
# is independently qualified before deployment; these tests do not confer that.
def _remote_contract_modules(workdir: Path) -> None:
    shared = workdir / "shared"
    shared.mkdir(exist_ok=True)
    (shared / "__init__.py").touch()
    (shared / "session_identity.py").write_bytes(
        (REPO_ROOT / "shared/session_identity.py").read_bytes()
    )
    (shared / "gate0b_claim_publication_install.py").write_text(
        "from types import SimpleNamespace\n"
        "def default_claim_publication_roots(*, home):\n"
        "    return SimpleNamespace(\n"
        '        claim_lock_root=str(home / ".local/state/hapax/task-locks/gate0b-claim-publish-v1"),\n'
        '        claim_cache_dir=str(home / ".cache/hapax"))\n'
    )
    (shared / "sdlc_claim.py").write_text(
        textwrap.dedent("""
        import builtins
        import fcntl
        import json
        import time
        from contextlib import contextmanager
        from pathlib import Path

        class Busy(Exception):
            reason_code = "claim_publication_lock_unavailable"

        @contextmanager
        def claim_role_exclusion(role, *, lock_root):
            lock_root.mkdir(parents=True, exist_ok=True)
            path = lock_root / (role + ".test-lock")
            trace = Path.home() / "lock-observation.json"
            observation = {"role": role, "root": str(lock_root), "writes": []}
            trace.write_text(json.dumps(observation))
            with path.open("a") as held:
                try:
                    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise Busy() from exc
                original_open = builtins.open

                def checked_open(target, mode="r", *args, **kwargs):
                    name = Path(target).name
                    race = Path.home() / "sidecar-race.json"
                    if any(flag in mode for flag in "wx") and race.exists():
                        injection = json.loads(race.read_text())
                        if name == injection["name"]:
                            race.unlink()
                            Path(target).symlink_to(injection["target"])
                    if name.startswith("session-role-") and any(flag in mode for flag in "wx"):
                        barrier = Path.home() / "marker-race"
                        if barrier.exists():
                            (barrier / role).touch()
                            deadline = time.monotonic() + 5
                            while len(list(barrier.iterdir())) != 2:
                                if time.monotonic() >= deadline:
                                    raise AssertionError("second role never reached marker publication")
                                time.sleep(0.01)
                    if any(flag in mode for flag in "wx") and (Path.home() / "fail-write").exists() and name == "cc-active-task-beta":
                        raise OSError("injected write failure")
                    if any(flag in mode for flag in "wx") and name.startswith(("cc-", "session-role-")):
                        with path.open("a") as rival:
                            try:
                                fcntl.flock(rival, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            except BlockingIOError:
                                observation["writes"].append(name)
                            else:
                                raise AssertionError("materialization outside role exclusion")
                        trace.write_text(json.dumps(observation))
                    return original_open(target, mode, *args, **kwargs)

                builtins.open = checked_open
                try:
                    yield
                finally:
                    builtins.open = original_open
                    fcntl.flock(held, fcntl.LOCK_UN)
    """)
    )


def _remote_materialization(tmp_path: Path, *, identity=None):
    home = tmp_path / "execution-home"
    workdir = tmp_path / "execution-source"
    home.mkdir()
    workdir.mkdir()
    _remote_contract_modules(workdir)
    sid = "9381e195-f8e6-43ce-83bf-ea7e5b846723"
    identity = identity or {
        "HAPAX_SESSION_ID": sid,
        "HAPAX_AGENT_ROLE": "beta",
        "HAPAX_METHODOLOGY_DISPATCH_TASK": "task-x",
    }
    proof = home / "proof/dispatch.json"
    executed = home / "executed"
    payload = {
        "workdir": str(workdir),
        "env": identity,
        "proof_file": str(proof),
        "requested_host": "synthetic-execution-host",
        "argv": [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(executed)!r}).touch()",
        ],
    }
    env = os.environ.copy()
    env.update(
        HOME=str(home), HAPAX_REMOTE_PAYLOAD=base64.b64encode(json.dumps(payload).encode()).decode()
    )
    # This is the complete remote program, through proof and native-exec boundary.
    program = SCRIPT.read_text().split("REMOTE_EXEC_PY='", 1)[1].split("'\n", 1)[0]
    return home, workdir, proof, executed, [sys.executable, "-I", "-c", program], env


def test_remote_materialization_busy_role_never_writes_or_executes(tmp_path: Path) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    lock_root = home / ".local/state/hapax/task-locks/gate0b-claim-publish-v1"
    lock_root.mkdir(parents=True)
    with (lock_root / "beta.test-lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert not list((home / ".cache/hapax").glob("*"))
    data = json.loads(proof.read_text())
    assert data["claim_materialized"] is False
    assert data["claim_materialization_reason"] == "claim_publication_lock_unavailable"
    assert data["dispatch_state"] == "hold"
    observation = json.loads((home / "lock-observation.json").read_text())
    assert observation == {"role": "beta", "root": str(lock_root), "writes": []}


def test_remote_materialization_all_writes_share_execution_host_lock(tmp_path: Path) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert executed.exists()
    data = json.loads(proof.read_text())
    sid = data["session_id"]
    assert data["role"] == "beta" and data["task_id"] == "task-x"
    assert data["claim_materialized"] is True
    assert data["dispatch_state"] == "ready"
    cache = home / ".cache/hapax"
    assert (cache / f"session-role-{sid}").read_text() == "beta\n"
    for key in ("beta", f"beta-{sid}"):
        assert (cache / f"cc-active-task-{key}").read_text() == "task-x\n"
        assert (cache / f"cc-claim-epoch-{key}").read_text().split() == [
            str(data["claim_epoch"]),
            "task-x",
        ]
    observation = json.loads((home / "lock-observation.json").read_text())
    assert observation["role"] == "beta"
    assert observation["root"] == str(
        home / ".local/state/hapax/task-locks/gate0b-claim-publish-v1"
    )
    assert observation["writes"] == [
        f"session-role-{sid}",
        "cc-claim-epoch-beta",
        f"cc-claim-epoch-beta-{sid}",
        "cc-active-task-beta",
        f"cc-active-task-beta-{sid}",
    ]


def test_remote_materialization_missing_contract_holds(tmp_path: Path) -> None:
    home, workdir, proof, executed, command, env = _remote_materialization(tmp_path)
    (workdir / "shared/sdlc_claim.py").write_text("# Interface not installed yet.\n")
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert not list((home / ".cache/hapax").glob("*"))
    data = json.loads(proof.read_text())
    assert data["dispatch_state"] == "hold"
    assert data["claim_materialization_reason"] == "remote_claim_contract_unavailable"


@pytest.mark.parametrize(
    "field,value",
    [
        ("HAPAX_SESSION_ID", "beta-1234"),
        ("HAPAX_SESSION_ID", " valid-session-uuid "),
        ("HAPAX_AGENT_ROLE", "../elsewhere"),
        ("HAPAX_METHODOLOGY_DISPATCH_TASK", "task\nother"),
        ("HAPAX_METHODOLOGY_DISPATCH_TASK", ""),
    ],
)
def test_remote_materialization_invalid_identity_holds(
    tmp_path: Path, field: str, value: str
) -> None:
    identity = {
        "HAPAX_SESSION_ID": "9381e195-f8e6-43ce-83bf-ea7e5b846723",
        "HAPAX_AGENT_ROLE": "beta",
        "HAPAX_METHODOLOGY_DISPATCH_TASK": "task-x",
    }
    identity[field] = value
    home, _, proof, executed, command, env = _remote_materialization(tmp_path, identity=identity)
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert not list((home / ".cache/hapax").glob("*"))
    assert (
        json.loads(proof.read_text())["claim_materialization_reason"]
        == "remote_claim_identity_invalid"
    )


def test_remote_materialization_io_failure_cannot_launch(tmp_path: Path) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    # Fail after marker and epochs; preserve partial evidence, but never exec.
    (home / "fail-write").touch()
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    data = json.loads(proof.read_text())
    assert data["claim_materialized"] is False
    assert data["claim_materialization_reason"] == "remote_claim_materialization_failed"
    assert data["dispatch_state"] == "hold"
    assert (cache / "cc-claim-epoch-beta").exists()
    assert not (cache / "cc-active-task-beta").exists()


@pytest.mark.parametrize(
    "existing",
    [
        {"cc-active-task-beta": "other-task\n"},
        {"cc-active-task-beta-old-session-uuid": "task-x\n"},
        {"cc-active-task-beta": ""},
        {"cc-claim-epoch-beta": "123 other-task\n"},
    ],
)
def test_remote_materialization_conflicting_claim_holds(tmp_path: Path, existing) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    for name, content in existing.items():
        (cache / name).write_text(content)
    before = {p.name: p.read_bytes() for p in cache.iterdir()}
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert {p.name: p.read_bytes() for p in cache.iterdir()} == before
    assert (
        json.loads(proof.read_text())["claim_materialization_reason"]
        == "remote_claim_binding_unresolved"
    )


def test_remote_materialization_preserves_matching_epoch(tmp_path: Path) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    sid = "9381e195-f8e6-43ce-83bf-ea7e5b846723"
    for key in ("beta", f"beta-{sid}"):
        (cache / f"cc-claim-epoch-{key}").write_text("123 task-x\n")
        (cache / f"cc-active-task-{key}").write_text("task-x\n")
    before = {path.name: path.stat() for path in cache.iterdir()}
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert executed.exists()
    assert json.loads(proof.read_text())["claim_epoch"] == 123
    for key in ("beta", f"beta-{sid}"):
        assert (cache / f"cc-claim-epoch-{key}").read_text() == "123 task-x\n"
    for name, previous in before.items():
        current = (cache / name).stat()
        assert (current.st_ino, current.st_mtime_ns) == (previous.st_ino, previous.st_mtime_ns)


_REMOTE_SIDECARS = [
    prefix + key
    for prefix in ("cc-active-task-", "cc-claim-epoch-")
    for key in ("beta", "beta-9381e195-f8e6-43ce-83bf-ea7e5b846723")
]


@pytest.mark.parametrize("present_mask", range(1, 15))
@pytest.mark.parametrize("matching_marker", [False, True])
def test_remote_materialization_partial_matching_binding_holds(
    tmp_path: Path, present_mask: int, matching_marker: bool
) -> None:
    """Matching fragments never prove ownership, even with a session marker."""
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    for index, name in enumerate(_REMOTE_SIDECARS):
        if present_mask & (1 << index):
            (cache / name).write_text("123 task-x\n" if "epoch" in name else "task-x\n")
    if matching_marker:
        (cache / "session-role-9381e195-f8e6-43ce-83bf-ea7e5b846723").write_text("beta\n")
    before = {
        path.name: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
        for path in cache.iterdir()
    }
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert {
        path.name: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
        for path in cache.iterdir()
    } == before
    assert json.loads((home / "lock-observation.json").read_text())["writes"] == []
    data = json.loads(proof.read_text())
    assert data["dispatch_state"] == "hold" and data["claim_materialized"] is False
    assert data["claim_epoch"] is None
    assert data["claim_materialization_reason"] == "remote_claim_binding_unresolved"


@pytest.mark.parametrize("legacy_epoch", [False, True])
def test_remote_materialization_live_legacy_holder_cannot_be_adopted(
    tmp_path: Path, legacy_epoch: bool
) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    (cache / "cc-active-task-beta").write_text("task-x\n")
    if legacy_epoch:
        (cache / "cc-claim-epoch-beta").write_text("123 task-x\n")
    before = {path.name: path.read_bytes() for path in cache.iterdir()}
    # A real isolated process represents the legacy owner; no native model runs.
    holder_env = env | {"HAPAX_AGENT_ROLE": "beta"}
    for key in ("HAPAX_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID"):
        holder_env.pop(key, None)
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], env=holder_env)
    try:
        assert holder.poll() is None
        result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
        assert holder.poll() is None
        assert result.returncode == 75, result.stderr
        assert not executed.exists()
        assert {path.name: path.read_bytes() for path in cache.iterdir()} == before
        assert json.loads((home / "lock-observation.json").read_text())["writes"] == []
        data = json.loads(proof.read_text())
        assert data["dispatch_state"] == "hold" and data["claim_materialized"] is False
        assert data["claim_epoch"] is None
        assert data["claim_materialization_reason"] == "remote_claim_binding_unresolved"
    finally:
        holder.terminate()
        holder.wait(timeout=5)


@pytest.mark.parametrize("name", _REMOTE_SIDECARS)
@pytest.mark.parametrize("kind", ["symlink", "dangling", "directory", "fifo", "hardlink"])
def test_remote_materialization_nonregular_sidecar_holds(
    tmp_path: Path, name: str, kind: str
) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    sidecar, target = cache / name, home / "unrelated-target"
    content = "123 task-x\n" if "epoch" in name else "task-x\n"
    if kind != "dangling":
        target.write_text(content)
    if kind in ("symlink", "dangling"):
        sidecar.symlink_to(target)
    elif kind == "directory":
        sidecar.mkdir()
    elif kind == "fifo":
        os.mkfifo(sidecar)
    else:
        os.link(target, sidecar)
    before = target.stat() if target.exists() else None
    observed = sidecar.lstat()
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=3)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert list(cache.iterdir()) == [sidecar]
    assert sidecar.lstat() == observed
    if before is None:
        assert not target.exists()
    else:
        assert target.read_text() == content
        after = target.stat()
        assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    data = json.loads(proof.read_text())
    assert data["dispatch_state"] == "hold"
    assert data["claim_materialized"] is False and data["claim_epoch"] is None
    assert data["claim_materialization_reason"] == "remote_claim_binding_unresolved"


@pytest.mark.parametrize("name", _REMOTE_SIDECARS)
def test_remote_materialization_sidecar_changed_at_publication_holds(
    tmp_path: Path, name: str
) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    target = home / "unrelated-target"
    content = "123 task-x\n" if "epoch" in name else "task-x\n"
    target.write_text(content)
    before = target.stat()
    # Inject at the write itself, after every initial sidecar read has finished.
    (home / "sidecar-race.json").write_text(json.dumps({"name": name, "target": str(target)}))
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=3)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert (home / ".cache/hapax" / name).is_symlink()
    assert target.read_text() == content
    after = target.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    data = json.loads(proof.read_text())
    assert data["dispatch_state"] == "hold" and data["claim_materialized"] is False
    assert data["claim_materialization_reason"] == "remote_claim_binding_unresolved"


@pytest.mark.parametrize("content", ["", "123 task-x", "123  task-x\n", "0123 task-x\n"])
def test_remote_materialization_incomplete_epoch_holds(tmp_path: Path, content: str) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    epoch = cache / "cc-claim-epoch-beta"
    epoch.write_text(content)
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=3)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert list(cache.iterdir()) == [epoch] and epoch.read_text() == content
    assert (
        json.loads(proof.read_text())["claim_materialization_reason"]
        == "remote_claim_binding_unresolved"
    )


@pytest.mark.parametrize(
    "name", _REMOTE_SIDECARS + ["session-role-9381e195-f8e6-43ce-83bf-ea7e5b846723"]
)
def test_remote_materialization_carriage_return_holds(tmp_path: Path, name: str) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    sidecar = cache / name
    value = "beta" if name.startswith("session-role-") else "task-x"
    if "epoch" in name:
        value = "123 " + value
    content = (value + "\r\n").encode()
    sidecar.write_bytes(content)
    previous = sidecar.stat()
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=3)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert list(cache.iterdir()) == [sidecar] and sidecar.read_bytes() == content
    assert sidecar.stat().st_mtime_ns == previous.st_mtime_ns
    reason = (
        "remote_session_role_unresolved"
        if name.startswith("session-role-")
        else "remote_claim_binding_unresolved"
    )
    assert json.loads(proof.read_text())["claim_materialization_reason"] == reason


@pytest.mark.parametrize("existing", ["gamma\n", "", "beta", "beta\nextra\n"])
def test_remote_materialization_session_role_conflict_holds(tmp_path: Path, existing: str) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    marker = cache / "session-role-9381e195-f8e6-43ce-83bf-ea7e5b846723"
    marker.write_text(existing)
    before = marker.stat()
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert list(cache.iterdir()) == [marker]
    assert marker.read_text() == existing
    assert (marker.stat().st_ino, marker.stat().st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    data = json.loads(proof.read_text())
    assert data["dispatch_state"] == "hold"
    assert data["claim_materialization_reason"] == "remote_session_role_unresolved"
    assert data["claim_materialized"] is False
    assert data["claim_epoch"] is None
    assert data["session_id"] == marker.name.removeprefix("session-role-")
    assert data["role"] == "beta" and data["task_id"] == "task-x"


def test_remote_materialization_matching_session_role_is_not_rewritten(tmp_path: Path) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    marker = cache / "session-role-9381e195-f8e6-43ce-83bf-ea7e5b846723"
    marker.write_text("beta\n")
    os.utime(marker, ns=(1_000_000_000, 1_000_000_000))
    before = marker.stat()
    for _ in range(2):
        result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert executed.exists()
        assert marker.read_text() == "beta\n"
        assert (marker.stat().st_ino, marker.stat().st_mtime_ns) == (
            before.st_ino,
            before.st_mtime_ns,
        )
        data = json.loads(proof.read_text())
        assert data["dispatch_state"] == "ready"
        assert data["claim_materialized"] is True
        assert (cache / "cc-claim-epoch-beta").read_text() == f"{data['claim_epoch']} task-x\n"


def test_remote_materialization_symlink_session_role_holds(tmp_path: Path) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    cache = home / ".cache/hapax"
    cache.mkdir(parents=True)
    target = home / "unrelated-marker"
    target.write_text("beta\n")
    before = target.stat()
    marker = cache / "session-role-9381e195-f8e6-43ce-83bf-ea7e5b846723"
    marker.symlink_to(target)
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 75, result.stderr
    assert not executed.exists()
    assert marker.is_symlink()
    assert list(cache.iterdir()) == [marker]
    assert target.read_text() == "beta\n"
    assert target.stat().st_mtime_ns == before.st_mtime_ns
    assert (
        json.loads(proof.read_text())["claim_materialization_reason"]
        == "remote_session_role_unresolved"
    )


def test_remote_materialization_concurrent_roles_cannot_share_session(tmp_path: Path) -> None:
    home, _, proof, executed, command, env = _remote_materialization(tmp_path)
    # Both roles hold their independent role locks and reach marker publication
    # before either can create it. A read-then-truncate check cannot pass this.
    (home / "marker-race").mkdir()
    payload = json.loads(base64.b64decode(env["HAPAX_REMOTE_PAYLOAD"]))
    payload["env"]["HAPAX_AGENT_ROLE"] = "gamma"
    payload["env"]["HAPAX_METHODOLOGY_DISPATCH_TASK"] = "task-y"
    rival_proof, rival_executed = home / "proof/gamma.json", home / "executed-gamma"
    payload["proof_file"] = str(rival_proof)
    payload["argv"][-1] = f"from pathlib import Path; Path({str(rival_executed)!r}).touch()"
    rival_env = env | {
        "HAPAX_REMOTE_PAYLOAD": base64.b64encode(json.dumps(payload).encode()).decode()
    }
    processes = [
        subprocess.Popen(
            command, env=child_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        for child_env in (env, rival_env)
    ]
    try:
        outputs = [process.communicate(timeout=10) for process in processes]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert sorted(process.returncode for process in processes) == [0, 75], outputs
    proofs = [json.loads(path.read_text()) for path in (proof, rival_proof)]
    winner = next(data for data in proofs if data["dispatch_state"] == "ready")
    loser = next(data for data in proofs if data["dispatch_state"] == "hold")
    assert loser["claim_materialization_reason"] == "remote_session_role_unresolved"
    assert loser["claim_materialized"] is False and loser["claim_epoch"] is None
    assert winner["session_id"] == loser["session_id"]
    cache = home / ".cache/hapax"
    sid = winner["session_id"]
    assert (cache / f"session-role-{sid}").read_text() == winner["role"] + "\n"
    expected = {f"session-role-{sid}"}
    for key in (winner["role"], f"{winner['role']}-{sid}"):
        expected.update({f"cc-active-task-{key}", f"cc-claim-epoch-{key}"})
        assert (cache / f"cc-active-task-{key}").read_text() == winner["task_id"] + "\n"
        assert (
            cache / f"cc-claim-epoch-{key}"
        ).read_text() == f"{winner['claim_epoch']} {winner['task_id']}\n"
    assert {path.name for path in cache.iterdir()} == expected
    assert executed.exists() == (winner["role"] == "beta")
    assert rival_executed.exists() == (winner["role"] == "gamma")


@pytest.mark.parametrize("changed", [None, "marker", "epoch", "host", "identity", "hold"])
def test_remote_materialization_runbook_recheck(tmp_path: Path, changed: str | None) -> None:
    home, workdir, proof, _, command, env = _remote_materialization(tmp_path)
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    cache = home / ".cache/hapax"
    data = json.loads(proof.read_text())
    if changed == "marker":
        (cache / f"session-role-{data['session_id']}").write_text("gamma\n")
    elif changed == "epoch":
        (cache / "cc-claim-epoch-beta").write_text("123 other-task\n")
    elif changed == "host":
        data["actual_host"] = "another-execution-host"
    elif changed == "identity":
        del data["session_id"]
    elif changed == "hold":
        data.update(dispatch_state="hold", claim_materialized=False)
    proof.write_text(json.dumps(data))
    before = {path: path.read_bytes() for path in cache.iterdir()}
    doc = (REPO_ROOT / "docs/runbooks/lane-death-forensics.md").read_text()
    program = doc.split("python3 - '<execution-source-root>' '<dispatch-proof-path>' <<'PY'\n", 1)[
        1
    ].split("\nPY", 1)[0]
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, str(workdir), str(proof)],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == (75 if changed else 0), result.stdout + result.stderr
    assert hashlib.sha256(proof.read_bytes()).hexdigest() in result.stdout
    assert {path: path.read_bytes() for path in cache.iterdir()} == before
    if changed:
        assert "remote_claim_recheck_hold:" in result.stderr
    else:
        for content in before.values():
            assert hashlib.sha256(content).hexdigest() in result.stdout
        assert result.stdout.count("\nmatch ") == 5
