"""Session ownership and quiet-writer regressions; all effects stay in tmp_path."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.scripts.test_lane_supervisor import (
    _base,
    _make_worktree,
    _write_claim,
    _write_executable,
)
from tests.scripts.test_lane_supervisor_reaper import _spawn_launcher

ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = Path(os.environ.get("HAPAX_TEST_SUPERVISOR", ROOT / "scripts/hapax-lane-supervisor"))
SID = "a81c4e9a-1111-4444-8888-123456abcdef"


def setup_lane(tmp_path, *, pane=False, claim=True):
    env, calls = _base(
        tmp_path,
        HAPAX_SUPERVISOR_CLAUDE_LANES="delta",
        HAPAX_SUPERVISOR_REAP_OFF="1",
        HAPAX_SUPERVISOR_PROGRESS_OFF="0",
        HAPAX_SUPERVISOR_ADMISSION_CMD="echo open",
        HAPAX_SUPERVISOR_P0_IDLE_RESPAWN="0",
        HAPAX_LOCAL_DEV_MAINTENANCE_MODE="local",
        HAPAX_SUPERVISOR_STALL_T="1",
        HAPAX_SUPERVISOR_LANEBUS_DIR=str(tmp_path / "lanebus"),
    )
    _make_worktree(env, "delta")
    # A native executable fixture, distinct from the helper's /usr/bin/sleep
    # inode. This exercises executable identity without launching a model.
    shutil.copy2(shutil.which("sleep"), tmp_path / "bin/claude")
    _write_executable(
        tmp_path / "bin/tmux",
        '#!/bin/bash\ncase "$1" in\n'
        ' has-session) [ "${TEST_PANE:-0}" = 1 ];;\n'
        ' list-panes) [ "${TEST_PANE:-0}" = 1 ] && printf "hapax-claude-delta\\t0\\t%s\\n" "$TEST_PANE_PID"; exit 0;;\n'
        " *) exit 0;;\nesac\n",
    )
    env["TEST_PANE"] = "1" if pane else "0"
    env["TEST_PANE_PID"] = str(os.getpid())
    # Run exact source bytes with isolated siblings: the installed exhaustion
    # path resolves hapax-alert relative to itself, bypassing a PATH fake.
    runner = tmp_path / "supervisor/scripts/hapax-lane-supervisor"
    _write_executable(runner, SUPERVISOR.read_text())
    (runner.parent.parent / "shared").symlink_to(ROOT / "shared", target_is_directory=True)
    _write_executable(runner.parent / "hapax-alert", "#!/bin/bash\nexit 0\n")
    env["TEST_SUPERVISOR_BIN"] = str(runner)
    env["HAPAX_SUPERVISOR_METRICS_FILE"] = str(tmp_path / "metrics.prom")
    # No test can send a real alert, including the installed unsafe exhaustion leg.
    _write_executable(tmp_path / "bin/curl", "#!/bin/bash\nexit 0\n")
    if claim:
        _write_claim(env, "delta", "session-task", status="in_progress")
    output = Path(env["HOME"]) / ".cache/hapax/claude-headless/delta/output.jsonl"
    output.parent.mkdir(parents=True)
    output.write_text('{"type":"assistant"}\n')
    os.utime(output, (time.time() - 3600,) * 2)
    return env, calls


def run(env):
    return subprocess.run(
        [env["TEST_SUPERVISOR_BIN"]], env=env, capture_output=True, text=True, timeout=20
    )


def claims_snapshot(env):
    cache = Path(env["HOME"]) / ".cache/hapax"
    vault = Path(env["HAPAX_SUPERVISOR_VAULT_ROOT"])
    return {str(p): p.read_bytes() for d in (cache, vault) for p in d.rglob("*") if p.is_file()}


def assert_no_recovery(env, calls, before, result):
    assert result.returncode == 0, result.stderr
    assert not list(calls.iterdir()), result.stdout
    assert claims_snapshot(env) == before
    state = Path(env["HAPAX_SUPERVISOR_STATE_DIR"])
    assert not list(state.glob("*.resume-log"))
    assert not (state / "lanes_resumed_total").exists()


@pytest.mark.parametrize("exhausted", [False, True])
def test_live_pane_stale_headless_output_never_recovers(tmp_path, exhausted):
    env, calls = setup_lane(tmp_path, pane=True)
    if exhausted:
        (Path(env["HAPAX_SUPERVISOR_STATE_DIR"]) / "delta.session-task.resume-log").write_text(
            (f"{int(time.time())}\n") * 3
        )
    before = claims_snapshot(env)
    result = run(env)
    assert result.returncode == 0, result.stderr
    assert not list(calls.iterdir()), result.stdout
    assert claims_snapshot(env) == before
    assert "progress_hold:" in result.stdout


@pytest.mark.parametrize("reaper_enabled", [False, True])
def test_live_headless_silence_never_nudges_or_reoffers(tmp_path, reaper_enabled):
    env, calls = setup_lane(tmp_path)
    env["HAPAX_SUPERVISOR_REAP_OFF"] = "0" if reaper_enabled else "1"
    env["HAPAX_SUPERVISOR_LAUNCHER_MAX_LIFETIME_S"] = "0"
    runtime = Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"])
    proc = _spawn_launcher(env, runtime, "delta")
    fifo = runtime / "delta.stdin"
    os.mkfifo(fifo)
    reader = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    (runtime / "delta.pid").write_text(str(proc.pid))
    before = claims_snapshot(env)
    try:
        result = run(env)
        assert_no_recovery(env, calls, before, result)
        with pytest.raises(BlockingIOError):
            os.read(reader, 4096)
        assert proc.poll() is None
        assert "progress_hold:" in result.stdout
    finally:
        os.close(reader)
        proc.terminate()
        proc.wait(timeout=5)


def session_claim(env, pid=None):
    cache = Path(env["HOME"]) / ".cache/hapax"
    (cache / f"cc-active-task-delta-{SID}").write_text("session-task\n")
    (cache / f"cc-claim-epoch-delta-{SID}").write_text("17|preserve-epoch\n")
    (cache / f"session-role-{SID}").write_text("delta\n")
    if pid is not None:
        (Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"]) / f"delta-{SID}.pid").write_text(str(pid))


def dead_pid():
    proc = subprocess.Popen(["true"])
    proc.wait(timeout=5)
    return proc.pid


def test_dead_holder_detected_beneath_live_pane_claim_untouched(tmp_path):
    env, calls = setup_lane(tmp_path, pane=True)
    pid = dead_pid()
    session_claim(env, pid)
    (Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"]) / "delta.pid").write_text(str(pid))
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert f"claim_orphaned:session-task:{SID}" in result.stdout
    assert "claim_orphan_unresolved:governed_rebind_required" in result.stdout
    receipts = list((tmp_path / "lanebus/delta").glob("*claim-holder*.json"))
    assert receipts
    receipt = json.loads(receipts[-1].read_text())
    assert receipt["session_id"] == SID
    assert receipt["state"] == "dead"
    assert receipt["claim_sha256"] and receipt["epoch_sha256"]


@pytest.mark.parametrize("binding", [None, "not-a-pid", "0", "-1"])
def test_unresolved_holder_is_typed_hold(tmp_path, binding):
    env, calls = setup_lane(tmp_path, pane=True)
    session_claim(env, binding)
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "claim_orphan_unresolved:" in result.stdout
    assert "claim_orphaned:" not in result.stdout


def test_live_claim_holder_and_pane_no_orphan(tmp_path):
    env, calls = setup_lane(tmp_path, pane=True)
    proc = subprocess.Popen(
        [str(tmp_path / "bin/claude"), "60"], env={**env, "HAPAX_SESSION_ID": SID}
    )
    try:
        session_claim(env, proc.pid)
        before = claims_snapshot(env)
        result = run(env)
        assert_no_recovery(env, calls, before, result)
        assert "claim_holder_live:session-task:" in result.stdout
        assert "claim_orphaned:" not in result.stdout
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_live_pane_without_claim_has_no_orphan_or_respawn(tmp_path):
    env, calls = setup_lane(tmp_path, pane=True, claim=False)
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "claim_orphan" not in result.stdout


@pytest.mark.parametrize("contents", ["", "corrupt", "0", "-1"])
def test_invalid_role_pidfile_holds_unclaimed_lane(tmp_path, contents):
    env, calls = setup_lane(tmp_path, claim=False)
    pidfile = Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"]) / "delta.pid"
    pidfile.write_text(contents)
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "writer_unresolved:invalid_pid" in result.stdout
    assert pidfile.read_text() == contents


def test_dead_holder_without_other_writer_waits_for_governed_rebind(tmp_path):
    env, calls = setup_lane(tmp_path)
    session_claim(env, dead_pid())
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "claim_orphaned:" in result.stdout
    assert "governed_rebind_required" in result.stdout


@pytest.mark.parametrize("mismatch", ["session", "home"])
def test_reused_session_pid_is_unknown_not_dead(tmp_path, mismatch):
    env, calls = setup_lane(tmp_path, pane=True)
    child_env = dict(env)
    if mismatch == "home":
        child_env.update(HAPAX_SESSION_ID=SID, HOME=str(tmp_path / "other-home"))
    proc = subprocess.Popen([str(tmp_path / "bin/claude"), "60"], env=child_env)
    try:
        session_claim(env, proc.pid)
        before = claims_snapshot(env)
        result = run(env)
        assert_no_recovery(env, calls, before, result)
        assert "pid_identity_mismatch" in result.stdout
        assert "claim_orphaned:" not in result.stdout
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_receipt_failure_holds_claim(tmp_path):
    env, calls = setup_lane(tmp_path)
    session_claim(env, dead_pid())
    (tmp_path / "lanebus").write_text("not a directory")
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "claim_orphan_unresolved:observation_failed:" in result.stdout


@pytest.mark.parametrize("writer", ["live", "dead", "unbound", "binding_unresolved", "upgraded"])
def test_real_pane_distinguishes_writer_from_surviving_helper(tmp_path, writer):
    from tests.scripts.test_lane_supervisor_pane_death_forensics import (
        ProbeServer,
        _require_real_tmux,
        _wait_for,
    )

    _require_real_tmux()
    env, calls = setup_lane(tmp_path)
    session_claim(env, dead_pid() if writer == "upgraded" else None)
    binary = tmp_path / "bin/claude"
    if writer == "dead":
        child = subprocess.Popen([str(binary), "60"], env={**env, "HAPAX_SESSION_ID": SID})
        try:
            session_claim(env, child.pid)
        finally:
            child.terminate()
            child.wait(timeout=5)
        # The claim's actual writer exited; the pane below keeps a helper with
        # the same inherited identity alive. It must not certify that writer.
    command = shlex.join([str(binary) if writer in {"live", "upgraded"} else "sleep", "60"])
    if writer == "binding_unresolved":
        binary.unlink()
        _write_executable(binary, "#!/bin/sh\nexec sleep 60\n")
    probe = ProbeServer(tmp_path)
    try:
        probe(
            "new-session",
            "-d",
            "-s",
            "hapax-claude-delta",
            "-e",
            f"HOME={env['HOME']}",
            "-e",
            f"HAPAX_SESSION_ID={SID}",
            command,
            check=True,
        )

        # new-session returns before the shell necessarily execs the command.
        # Wait for the process witness under test, not for elapsed wall time.
        def identity_ready():
            pid = probe(
                "display-message", "-p", "-t", "=hapax-claude-delta:", "#{pane_pid}"
            ).stdout.strip()
            try:
                raw = (Path("/proc") / pid / "environ").read_bytes().split(b"\0")
                return (
                    f"HAPAX_SESSION_ID={SID}".encode() in raw
                    and f"HOME={env['HOME']}".encode() in raw
                    and (Path("/proc") / pid / "exe").samefile(
                        binary if writer in {"live", "upgraded"} else shutil.which("sleep")
                    )
                )
            except OSError:
                return False

        assert _wait_for(identity_ready)
        if writer == "upgraded":
            replacement = binary.with_suffix(".new")
            shutil.copy2(shutil.which("sleep"), replacement)
            replacement.replace(binary)
        env["PATH"] = f"{probe.bin_dir}:{env['PATH']}"
        before = claims_snapshot(env)
        result = run(env)
        assert_no_recovery(env, calls, before, result)
        if writer == "live":
            assert f"claim_holder_live:session-task:{SID}:pane_session_process" in result.stdout
        else:
            assert f"claim_holder_live:session-task:{SID}" not in result.stdout
            receipt = json.loads(
                (
                    Path(env["HAPAX_SUPERVISOR_STATE_DIR"]) / f"delta-{SID}.claim-holder.json"
                ).read_text()
            )
            assert receipt["state"] == "unknown"
            assert "claim_orphan_unresolved:" in result.stdout
            assert f"claim_orphaned:session-task:{SID}" not in result.stdout
    finally:
        probe.kill()


@pytest.mark.parametrize("binding", ["writer", "launcher"])
def test_bound_helper_is_not_a_live_claim_writer(tmp_path, binding):
    env, calls = setup_lane(tmp_path)
    helper = subprocess.Popen(["sleep", "60"], env={**env, "HAPAX_SESSION_ID": SID})
    try:
        session_claim(env, helper.pid if binding == "writer" else dead_pid())
        if binding == "launcher":
            (Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"]) / f"delta-{SID}.launcher.pid").write_text(
                str(helper.pid)
            )
        before = claims_snapshot(env)
        result = run(env)
        assert_no_recovery(env, calls, before, result)
        assert f"claim_holder_live:session-task:{SID}" not in result.stdout
        assert f"claim_orphaned:session-task:{SID}" not in result.stdout
        assert f"claim_orphan_unresolved:session-task:{SID}" in result.stdout
    finally:
        helper.terminate()
        helper.wait(timeout=5)


def test_claim_arriving_at_respawn_boundary_holds(tmp_path):
    env, calls = setup_lane(tmp_path, claim=False)
    # The first liveness observation discovers no pane but delivers a claim
    # before respawn. The use-boundary observation must see it.
    cache = Path(env["HOME"]) / ".cache/hapax"
    _write_executable(
        tmp_path / "bin/tmux",
        f'#!/bin/bash\nif [ "$1" = has-session ]; then\n'
        f'printf "session-task\\n" > "{cache}/cc-active-task-delta"\nfi\nexit 1\n',
    )
    result = run(env)
    assert result.returncode == 0, result.stderr
    assert not list(calls.iterdir()), result.stdout
    assert "respawn_hold:occupancy_changed" in result.stdout
    assert (cache / "cc-active-task-delta").read_text() == "session-task\n"


def test_malformed_pane_liveness_holds_unclaimed_lane(tmp_path):
    env, calls = setup_lane(tmp_path, claim=False)
    _write_executable(
        tmp_path / "bin/tmux",
        '#!/bin/bash\ncase "$1" in\n'
        " has-session) exit 0;;\n"
        ' list-panes) printf "hapax-claude-delta\\tunknown\\n";;\n'
        " *) exit 0;;\nesac\n",
    )
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)


def test_invalid_session_claim_key_holds_instead_of_disappearing(tmp_path):
    env, calls = setup_lane(tmp_path)
    cache = Path(env["HOME"]) / ".cache/hapax"
    (cache / "cc-active-task-delta").rename(cache / "cc-active-task-delta-12345")
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "claim_orphan_unresolved:" in result.stdout


def test_failed_pane_inspection_is_unknown_even_with_dead_pid(tmp_path):
    env, calls = setup_lane(tmp_path, pane=True)
    session_claim(env, dead_pid())
    _write_executable(
        tmp_path / "bin/tmux",
        '#!/bin/bash\ncase "$1" in\n'
        'has-session) exit 0;;\nlist-panes) echo "inspection failed" >&2; exit 1;;\nesac\n',
    )
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "pane_inspection_unresolved" in result.stdout
    assert "claim_orphaned:" not in result.stdout


@pytest.mark.parametrize("pid", ["", "broken", "0", "-1"])
def test_invalid_role_pid_holds_with_repair_action(tmp_path, pid):
    env, calls = setup_lane(tmp_path, claim=False)
    (Path(env["HAPAX_SUPERVISOR_RUNTIME_DIR"]) / "delta.pid").write_text(pid)
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "writer_unresolved:invalid_pid" in result.stdout
    assert "inspect" in result.stdout


def test_invalid_task_claim_has_receipt_and_repair_action(tmp_path):
    env, calls = setup_lane(tmp_path, claim=False)
    cache = Path(env["HOME"]) / ".cache/hapax"
    marker = cache / "cc-active-task-delta"
    marker.write_text("../invalid-task\n")
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "claim_orphan_unresolved:invalid_task_id" in result.stdout
    assert str(marker) in result.stdout and "inspect" in result.stdout
    receipts = list((tmp_path / "lanebus/delta").glob("*claim-holder*.json"))
    assert receipts
    assert json.loads(receipts[-1].read_text())["reason"] == "invalid_task_id"


def test_conflicting_session_role_is_unknown_not_absent(tmp_path):
    env, calls = setup_lane(tmp_path)
    session_claim(env, dead_pid())
    cache = Path(env["HOME"]) / ".cache/hapax"
    (cache / "cc-active-task-delta").unlink()
    (cache / f"session-role-{SID}").write_text("delta-other\n")
    before = claims_snapshot(env)
    result = run(env)
    assert_no_recovery(env, calls, before, result)
    assert "claim_orphan_unresolved:" in result.stdout
    assert "claim_orphaned:" not in result.stdout


def test_known_prefix_sibling_claim_does_not_hold_unclaimed_lane(tmp_path):
    env, calls = setup_lane(tmp_path, claim=False)
    _write_claim(env, "delta-other", "sibling-task")
    cache = Path(env["HOME"]) / ".cache/hapax"
    (cache / f"cc-active-task-delta-other-{SID}").write_text("sibling-task\n")
    (cache / f"session-role-{SID}").write_text("delta-other\n")
    before = claims_snapshot(env)
    result = run(env)
    assert result.returncode == 0, result.stderr
    assert (calls / "claude.txt").is_file(), result.stdout
    assert "claim_orphan" not in result.stdout
    assert claims_snapshot(env) == before
