"""Large events reach hook consumers intact, without an execve-sized argv entry."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "hooks" / "scripts"
# Each value alone exceeds Linux MAX_ARG_STRLEN (128 KiB), including before
# JSON escaping. Quotes, Unicode, NUL and trailing newlines expose lossy copies.
LARGE = ('line "quoted" \\ λ\t\x00\n' * 12000) + "END\n\n"


@contextmanager
def _conductor(response: dict) -> Iterator[tuple[str, list[bytes]]]:
    role = f"test-large-{uuid.uuid4().hex}"
    path = Path(f"/run/user/{os.getuid()}/conductor-{role}.sock")
    received: list[bytes] = []
    errors: list[Exception] = []
    stop = threading.Event()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))  # Never unlink or reuse another role's socket.
        server.listen(1)
        server.settimeout(0.1)

        def serve() -> None:
            try:
                while not stop.is_set():
                    try:
                        conn, _ = server.accept()
                    except TimeoutError:
                        continue
                    with conn, conn.makefile("rb") as stream:
                        conn.settimeout(5)
                        # One complete JSON line, with no receive-size ceiling.
                        received.append(stream.readline())
                        conn.sendall(json.dumps(response).encode() + b"\n")
                    return
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield role, received
        finally:
            stop.set()
            thread.join(timeout=6)
            path.unlink()
            assert not thread.is_alive(), "fake conductor did not stop"
            assert not errors, errors


def _run(script: Path, payload: dict, role: str, *args: str) -> subprocess.CompletedProcess:
    # A deterministic test environment, with no live lane identity or bypasses.
    return subprocess.run(
        ["bash", str(script), *args],
        input=json.dumps(payload).encode(),
        capture_output=True,
        env={"PATH": os.environ["PATH"], "HAPAX_AGENT_NAME": role, "LANG": "C.UTF-8"},
        timeout=10,
        check=False,
    )


@pytest.mark.parametrize(
    ("phase", "large_field", "action", "expected_exit"),
    [
        ("pre", "input", "allow", 0),
        ("pre", "input", "block", 2),
        ("post", "input", "block", 0),
        ("post", "output", "block", 0),
    ],
)
def test_large_conductor_event_is_delivered_intact(
    phase: str, large_field: str, action: str, expected_exit: int
) -> None:
    assert len(LARGE.encode()) > 128 * 1024
    tool_input = {
        "file_path": "fixture.txt",
        "content": LARGE if large_field == "input" else "small\n",
        "metadata": {"null": None, "flag": True, "items": [1, "λ"]},
    }
    tool_output = LARGE if large_field == "output" else "small result\n\n"
    payload = {
        "session_id": "large-fixture-session",
        "tool_name": "Write",
        "tool_input": tool_input,
        "tool_response": {"stdout": tool_output},
    }
    with _conductor({"action": action, "message": "fixture decision"}) as (role, received):
        result = _run(SCRIPTS / f"conductor-{phase}.sh", payload, role)
    assert result.returncode == expected_exit, (result.returncode, result.stderr)
    assert b"fixture decision" in result.stderr
    assert len(received) == 1, "conductor did not receive exactly one complete event"
    event = json.loads(received[0])
    assert event["tool_input"] == tool_input
    assert event["tool_input"]["content"].encode() == tool_input["content"].encode()
    expected = {
        "event_type": f"{phase}_tool_use",
        "session_id": payload["session_id"],
        "tool_name": payload["tool_name"],
        "tool_input": tool_input,
    }
    if phase == "post":
        expected["tool_output"] = tool_output
        assert event["tool_output"].encode() == tool_output.encode()
    assert event == expected  # Tool output must not become user_message.


@pytest.mark.parametrize(
    ("phase", "large_field"), [("PreToolUse", "command"), ("PostToolUse", "output")]
)
def test_large_shell_event_reaches_adapter_consumer(
    tmp_path: Path, phase: str, large_field: str
) -> None:
    # Isolate the normalizer's consumer boundary from unrelated chain hooks.
    # This fixture neither executes the shell command nor changes live hooks.
    script_dir = tmp_path / "hooks" / "scripts"
    script_dir.mkdir(parents=True)
    adapter = script_dir / "codex-hook-adapter.sh"
    shutil.copy2(SCRIPTS / adapter.name, adapter)
    capture = script_dir / "captured.json"
    consumer = script_dir / (
        "host-power-command-guard.sh" if phase == "PreToolUse" else "axiom-audit.sh"
    )
    consumer.write_text('#!/usr/bin/env bash\ncat > "${BASH_SOURCE[0]%/*}/captured.json"\n')
    consumer.chmod(0o755)
    command = LARGE if large_field == "command" else "printf fixture\n\n"
    output = LARGE if large_field == "output" else "small output\n\n"
    result = _run(
        adapter,
        {
            "hook_event_name": "overridden-by-explicit-event",
            "session_id": "large-shell-session",
            "cwd": str(tmp_path),
            "tool_name": "exec_command",
            "tool_input": {"cmd": command},
            "tool_response": {"stdout": output},
        },
        "test-large-shell",
        phase,
    )
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert json.loads(result.stdout) == {"continue": True}
    event = json.loads(capture.read_bytes())
    assert event == {
        "hook_event_name": phase,
        "session_id": "large-shell-session",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_output": output,
        "tool_response": {"output": output},
    }
