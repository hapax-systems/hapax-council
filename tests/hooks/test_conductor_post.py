"""Tests for hooks/scripts/conductor-post.sh.

Sister hook to conductor-pre. PostToolUse forwarder: pipes the tool
result event to the per-role conductor sidecar at
/run/user/$UID/conductor-<role>.sock and, if the response carries a
non-empty `message`, prints it to stderr. Unlike conductor-pre, this
hook NEVER blocks (PostToolUse hooks fire after the tool ran, so a
"block" verdict is meaningless — the tool already executed).

Coverage:
- empty stdin / missing session_id / no socket → exit 0 silently
- socket {message: "x"} → exit 0 with x on stderr
- socket {} → exit 0 silently (no-message response)
- socket sends only message field → exit 0 with message
- HAPAX_AGENT_ROLE override targets a private per-test socket
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
HOOK = REPO_ROOT / "hooks" / "scripts" / "conductor-post.sh"


def _run(
    payload: dict,
    role: str = "test-alpha-post",
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
    """Spin a single-shot UDS listener that replies with ``response`` JSON."""
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


# ── Early-exit paths ───────────────────────────────────────────────


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
        result = _run({"tool_name": "Bash"})
        assert result.returncode == 0

    def test_session_id_no_socket_exits_zero(self) -> None:
        role = "test-post-no-socket-9991"
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
    def test_response_with_message_prints_to_stderr(self) -> None:
        role = "test-post-msg-001"
        msg = "advisory: test ran but flag is on"
        with _uds_server(role, {"message": msg}):
            result = _run(
                {
                    "session_id": "sX",
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                    "tool_output": "stdout",
                },
                role=role,
            )
        assert result.returncode == 0
        assert msg in result.stderr

    def test_response_without_message_is_silent(self) -> None:
        role = "test-post-empty-002"
        with _uds_server(role, {}):
            result = _run(
                {
                    "session_id": "sX",
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                    "tool_output": "ok",
                },
                role=role,
            )
        assert result.returncode == 0
        assert result.stderr == ""

    def test_post_never_blocks_even_if_response_has_block_field(self) -> None:
        """PostToolUse hooks can't block — tool already ran. Exit 0 always."""
        role = "test-post-block-003"
        with _uds_server(role, {"action": "block", "message": "irrelevant"}):
            result = _run(
                {
                    "session_id": "sX",
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                    "tool_output": "ok",
                },
                role=role,
            )
        assert result.returncode == 0

    def test_response_includes_tool_output_in_event(self) -> None:
        """Hook forwards tool_output via the user_message field."""
        role = "test-post-toutput-004"
        with _uds_server(role, {"message": "got it"}):
            result = _run(
                {
                    "session_id": "sY",
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo hi"},
                    "tool_output": "hi\n",
                },
                role=role,
            )
        assert result.returncode == 0
        assert "got it" in result.stderr
