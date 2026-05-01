"""Tests for hooks/scripts/conductor-pre.sh.

The hook is a PreToolUse forwarder: it pipes the tool invocation
event to the per-role conductor sidecar over a UNIX domain socket
at /run/user/$UID/conductor-<role>.sock and acts on the response
(allow/block + optional stderr message).

Test surface covered here is the early-exit lattice — empty stdin,
missing session_id, no socket present. The full request/response
path requires a live UDS server fixture; this test class spins one
up via Python `socket` + threading so the JSON protocol is exercised
end-to-end without depending on the real conductor sidecar.

Conductor agent role is sourced via `hapax_agent_role_or_default
alpha` which reads HAPAX_AGENT_ROLE; tests override that env var to
target a private per-test socket name.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "conductor-pre.sh"


def _run(
    payload: dict,
    role: str = "test-alpha",
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HAPAX_AGENT_ROLE"] = role
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _socket_path(role: str) -> Path:
    return Path(f"/run/user/{os.getuid()}/conductor-{role}.sock")


@contextmanager
def _uds_server(role: str, response: dict) -> Iterator[Path]:
    """Spin a single-shot UDS listener that returns ``response`` on connect.

    The hook uses `socat ... UNIX-CONNECT`, sends the event JSON, and
    reads the response. We accept one connection, drain the request,
    write the JSON response + newline, close. Cleanup unlinks the
    socket file.
    """
    path = _socket_path(role)
    if path.exists():
        path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)

    def _serve() -> None:
        try:
            conn, _ = server.accept()
            with conn:
                # drain request
                conn.recv(8192)
                conn.sendall(json.dumps(response).encode() + b"\n")
        except OSError:
            pass

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    try:
        yield path
    finally:
        thread.join(timeout=5)
        server.close()
        if path.exists():
            path.unlink()


# ── Early-exit paths (no socket required) ──────────────────────────


class TestEarlyExits:
    def test_empty_stdin_exits_zero(self) -> None:
        result = subprocess.run(
            ["bash", str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0

    def test_missing_session_id_exits_zero(self) -> None:
        """Hook short-circuits if session_id is empty/missing."""
        result = _run({"tool_name": "Bash"})
        assert result.returncode == 0

    def test_session_id_no_socket_allows(self) -> None:
        """No socket file = conductor offline = allow (exit 0)."""
        role = "test-no-socket-12345"
        path = _socket_path(role)
        if path.exists():
            path.unlink()
        result = _run(
            {"session_id": "s1", "tool_name": "Bash", "tool_input": {}},
            role=role,
        )
        assert result.returncode == 0


# ── End-to-end with a live UDS server ──────────────────────────────


class TestSocketProtocol:
    def test_action_allow_exits_zero(self) -> None:
        role = "test-allow-001"
        with _uds_server(role, {"action": "allow"}):
            result = _run(
                {
                    "session_id": "sX",
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                },
                role=role,
            )
        assert result.returncode == 0

    def test_action_block_exits_two_with_message(self) -> None:
        role = "test-block-002"
        msg = "BLOCKED: conductor says no"
        with _uds_server(role, {"action": "block", "message": msg}):
            result = _run(
                {
                    "session_id": "sX",
                    "tool_name": "Bash",
                    "tool_input": {"command": "rm -rf /"},
                },
                role=role,
            )
        assert result.returncode == 2
        assert msg in result.stderr

    def test_allow_with_message_prints_warning(self) -> None:
        """action=allow with a message → stderr advisory, exit 0."""
        role = "test-allow-msg-003"
        msg = "advisory: rate-limit nearing"
        with _uds_server(role, {"action": "allow", "message": msg}):
            result = _run(
                {
                    "session_id": "sX",
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                },
                role=role,
            )
        assert result.returncode == 0
        assert msg in result.stderr

    def test_unknown_action_defaults_to_allow(self) -> None:
        """Any action other than 'block' falls through to exit 0."""
        role = "test-unknown-004"
        with _uds_server(role, {"action": "wat"}):
            result = _run(
                {
                    "session_id": "sX",
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                },
                role=role,
            )
        assert result.returncode == 0

    def test_no_action_field_defaults_to_allow(self) -> None:
        """Empty/no-action response → fail-open allow."""
        role = "test-noaction-005"
        with _uds_server(role, {}):
            result = _run(
                {
                    "session_id": "sX",
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                },
                role=role,
            )
        assert result.returncode == 0
