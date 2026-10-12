"""Process ownership fixtures: missing observation never falls back to a wrapper."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import yaml

from agents.session_conductor.lifecycle import (
    ProcessIdentity,
    find_codex_owner,
    process_identity,
    watch_owner,
)


def proc(root, pid, parent, ticks, *, state="S", executable="/bin/bash"):
    directory = root / str(pid)
    directory.mkdir(exist_ok=True)
    # stat comm may itself contain ')' and whitespace.
    fields = [state, str(parent)] + ["0"] * 17 + [str(ticks)]
    (directory / "stat").write_text(f"{pid} (name ) spaces) " + " ".join(fields))
    exe = directory / "exe"
    exe.unlink(missing_ok=True)
    exe.symlink_to(executable)


def test_native_ancestor_is_selected_past_transient_shells(tmp_path):
    proc(tmp_path, 40, 30, 400)
    proc(tmp_path, 30, 20, 300)
    proc(tmp_path, 20, 10, 200, executable="/opt/native/bin/codex")
    proc(tmp_path, 10, 1, 100)
    assert find_codex_owner(40, proc_root=tmp_path) == ProcessIdentity(20, 200)


def test_no_observed_native_ancestor_has_no_parent_fallback(tmp_path):
    proc(tmp_path, 40, 30, 400)
    proc(tmp_path, 30, 1, 300)
    assert find_codex_owner(40, proc_root=tmp_path) is None


@pytest.mark.parametrize("change", ["gone", "reused", "zombie", "malformed"])
async def test_watchdog_ends_when_original_owner_is_not_live(tmp_path, change):
    proc(tmp_path, 20, 10, 200, executable="/bin/codex")
    ended = asyncio.Event()
    task = asyncio.create_task(
        watch_owner(ProcessIdentity(20, 200), ended.set, interval=0.001, proc_root=tmp_path)
    )
    try:
        await asyncio.sleep(0.01)
        assert not ended.is_set()
        if change == "gone":
            (tmp_path / "20/stat").unlink()
        elif change == "reused":
            proc(tmp_path, 20, 10, 201)
        elif change == "zombie":
            proc(tmp_path, 20, 10, 200, state="Z")
        else:
            (tmp_path / "20/stat").write_text("bad")
        await asyncio.wait_for(ended.wait(), timeout=1)
        await task
    finally:
        task.cancel()


def test_unreadable_process_identity_is_unobserved(tmp_path: Path):
    assert process_identity(20, proc_root=tmp_path) is None


def test_codex_daemon_refuses_missing_owner(monkeypatch, tmp_path):
    from agents.session_conductor import __main__ as cli

    monkeypatch.setattr(cli, "PID_DIR", tmp_path)
    monkeypatch.setenv("HAPAX_AGENT_INTERFACE", "codex")
    with pytest.raises(ValueError, match="observed native"):
        cli.cmd_start(cli.build_parser().parse_args(["--role", "fixture", "start"]))
    assert not list(tmp_path.glob("*.pid"))


@pytest.mark.parametrize("exit_kind", ["owner", "signal"])
def test_real_fixture_daemon_owner_exit_and_single_writer(exit_kind):
    # A short isolated socket path and HOME; no live conductor, hook, manager,
    # relay, topology or spawn manifest can be reached by these subprocesses.
    with tempfile.TemporaryDirectory(prefix="conductor-") as directory:
        root = Path(directory)
        env = {
            "HOME": directory,
            "PATH": os.environ["PATH"],
            "HAPAX_AGENT_INTERFACE": "codex",
            "OTEL_SDK_DISABLED": "true",
        }
        owner = subprocess.Popen(["sleep", "60"], env=env)
        daemon = None
        try:
            identity = process_identity(owner.pid)
            assert identity is not None
            runner = """
from pathlib import Path
import agents._log_setup as logging_setup
from agents.session_conductor import __main__ as cli
logging_setup.configure_logging = lambda **kwargs: None
cli.PID_DIR = cli.STATE_DIR = cli.SOCK_DIR = Path.home()
cli.PARENT_WATCHDOG_INTERVAL = 0.01
cli.main()
"""
            command = [
                sys.executable,
                "-c",
                runner,
                "--role",
                "fixture",
                "start",
                "--session-id",
                "lane-uuid",
                "--session-id-kind",
                "lane",
                "--native-session-id",
                "native-uuid",
                "--owner-pid",
                str(owner.pid),
                "--owner-start-ticks",
                str(identity.start_ticks),
            ]
            if exit_kind == "signal":
                # Direct CLI usage has no lane/native ID to assert.
                command = command[: command.index("--session-id")] + [
                    "--owner-pid",
                    str(owner.pid),
                    "--owner-start-ticks",
                    str(identity.start_ticks),
                ]
            with (root / "daemon.log").open("w+") as output:
                daemon = subprocess.Popen(command, env=env, stdout=output, stderr=output)
                sock = root / "conductor-fixture.sock"
                deadline = time.monotonic() + 5
                while not sock.exists() and daemon.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert sock.exists(), (root / "daemon.log").read_text()
                for _ in range(2):
                    with socket.socket(socket.AF_UNIX) as client:
                        client.connect(str(sock))
                        client.sendall(
                            json.dumps(
                                {
                                    "event_type": "post_tool_use",
                                    "tool_name": "Bash",
                                    "tool_input": {"command": "true"},
                                    "session_id": "native-uuid",
                                }
                            ).encode()
                            + b"\n"
                        )
                        assert json.loads(client.recv(4096))["action"] == "allow"
                state_path = root / "conductor-fixture-state.json"
                before = state_path.read_bytes()
                duplicate = subprocess.run(command, env=env, capture_output=True, timeout=3)
                assert duplicate.returncode == 0, duplicate.stderr
                assert daemon.poll() is None
                assert state_path.read_bytes() == before
                assert (root / "conductor-fixture.pid").read_text() == str(daemon.pid)
                if exit_kind == "owner":
                    owner.terminate()
                    owner.wait(timeout=3)
                else:
                    daemon.terminate()
                assert daemon.wait(timeout=3) == 0, (root / "daemon.log").read_text()
                assert not sock.exists()
                assert not (root / "conductor-fixture.pid").exists()
                state = json.loads(state_path.read_text())
                session_id = (
                    "lane-uuid" if exit_kind == "owner" else f"conductor-fixture-{daemon.pid}"
                )
                session_kind = "lane" if exit_kind == "owner" else "conductor"
                native_id = "native-uuid" if exit_kind == "owner" else None
                assert state["session_id"] == session_id
                assert state["session_id_kind"] == session_kind
                assert state["native_session_id"] == native_id
                assert state["owner_pid"] == owner.pid
                assert state["owner_start_ticks"] == identity.start_ticks
                assert state["started_at"].endswith("+00:00")
                projection = root / ".cache/hapax/relay/conductor/fixture.yaml"
                data = yaml.safe_load(projection.read_text())
                assert data["event_type"] == "shutdown"
                assert data["session_id"] == session_id
                assert data["session_id_kind"] == session_kind
                assert data["native_session_id"] == native_id
                assert data["conductor_pid"] == daemon.pid
                assert data["owner_pid"] == owner.pid
                assert data["timestamp"].endswith("+00:00")
        finally:
            for process in (daemon, owner):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        # Deliberate regressions can break graceful cleanup too.
                        # Kill only the Popen fixture this test created.
                        process.kill()
                        process.wait(timeout=2)
