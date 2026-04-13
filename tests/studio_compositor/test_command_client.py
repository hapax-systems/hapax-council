"""Tests for agents.studio_compositor.command_client.

Exercises ``CompositorCommandClient`` against an in-process stub UDS
server that speaks the same line-framed JSON protocol as the real
``CommandServer``. Hermetic (no compositor process required).
"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

from agents.studio_compositor.command_client import (
    CommandClientError,
    CompositorCommandClient,
)


class _StubCommandServer:
    """Accept one request per connection, reply with canned payload."""

    def __init__(
        self,
        socket_path: Path,
        *,
        response_factory=None,
        close_before_reply: bool = False,
        malformed_reply: bool = False,
    ) -> None:
        self.socket_path = socket_path
        self.response_factory = response_factory or (lambda req: {"status": "ok"})
        self.close_before_reply = close_before_reply
        self.malformed_reply = malformed_reply
        self.received: list[dict] = []
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self.socket_path))
        self._sock.listen(4)
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop:
            try:
                self._sock.settimeout(0.5)
                try:
                    conn, _ = self._sock.accept()
                except TimeoutError:
                    continue
            except OSError:
                return
            with conn:
                self._handle(conn)

    def _handle(self, conn: socket.socket) -> None:
        buf = bytearray()
        while b"\n" not in buf:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf.extend(chunk)
        idx = bytes(buf).find(b"\n")
        try:
            req = json.loads(bytes(buf[:idx]).decode())
            self.received.append(req)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        if self.close_before_reply:
            return
        if self.malformed_reply:
            try:
                conn.sendall(b"{not json\n")
            except OSError:
                pass
            return
        try:
            resp = self.response_factory(req)
            conn.sendall((json.dumps(resp) + "\n").encode())
        except OSError:
            pass

    def close(self) -> None:
        self._stop = True
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)
        if self.socket_path.exists():
            self.socket_path.unlink()


@pytest.fixture
def socket_path(tmp_path: Path) -> Path:
    return tmp_path / "cmd.sock"


def test_happy_path_round_trip(socket_path: Path) -> None:
    server = _StubCommandServer(
        socket_path,
        response_factory=lambda req: {
            "status": "ok",
            "surface_id": req["args"]["surface_id"],
            "applied": True,
        },
    )
    try:
        client = CompositorCommandClient(socket_path=socket_path, timeout_s=2.0)
        result = client.execute(
            "compositor.surface.set_geometry",
            {"surface_id": "pip-lr", "x": 0, "y": 0, "w": 480, "h": 180},
        )
        assert result == {"status": "ok", "surface_id": "pip-lr", "applied": True}
        assert server.received[0]["command"] == "compositor.surface.set_geometry"
        assert server.received[0]["args"]["surface_id"] == "pip-lr"
    finally:
        server.close()


def test_missing_socket_raises_structured(tmp_path: Path) -> None:
    client = CompositorCommandClient(socket_path=tmp_path / "does-not-exist.sock", timeout_s=1.0)
    with pytest.raises(CommandClientError) as exc:
        client.execute("compositor.layout.save")
    assert exc.value.payload["error"] == "socket_missing"
    assert str(tmp_path / "does-not-exist.sock") in exc.value.payload["socket_path"]


def test_server_error_raises_with_full_payload(socket_path: Path) -> None:
    def _error_factory(req):
        return {
            "status": "error",
            "error": "unknown_surface",
            "surface_id": req["args"].get("surface_id"),
            "hint": "pip-ul, pip-ur",
        }

    server = _StubCommandServer(socket_path, response_factory=_error_factory)
    try:
        client = CompositorCommandClient(socket_path=socket_path, timeout_s=2.0)
        with pytest.raises(CommandClientError) as exc:
            client.execute(
                "compositor.surface.set_geometry",
                {"surface_id": "pip-bogus", "x": 0, "y": 0, "w": 1, "h": 1},
            )
        payload = exc.value.payload
        assert payload["status"] == "error"
        assert payload["error"] == "unknown_surface"
        assert payload["hint"] == "pip-ul, pip-ur"
    finally:
        server.close()


def test_server_closes_before_reply_raises_read_failed(socket_path: Path) -> None:
    server = _StubCommandServer(socket_path, close_before_reply=True)
    try:
        client = CompositorCommandClient(socket_path=socket_path, timeout_s=2.0)
        with pytest.raises(CommandClientError) as exc:
            client.execute("compositor.layout.save")
        assert exc.value.payload["error"] == "read_failed"
    finally:
        server.close()


def test_malformed_reply_raises_invalid_response(socket_path: Path) -> None:
    server = _StubCommandServer(socket_path, malformed_reply=True)
    try:
        client = CompositorCommandClient(socket_path=socket_path, timeout_s=2.0)
        with pytest.raises(CommandClientError) as exc:
            client.execute("compositor.layout.save")
        assert exc.value.payload["error"] == "invalid_response"
    finally:
        server.close()


def test_args_default_to_empty_dict(socket_path: Path) -> None:
    """Commands that take no args (save/reload) should work without passing args."""
    server = _StubCommandServer(socket_path)
    try:
        client = CompositorCommandClient(socket_path=socket_path, timeout_s=2.0)
        result = client.execute("compositor.layout.save")
        assert result == {"status": "ok"}
        assert server.received[0] == {"command": "compositor.layout.save", "args": {}}
    finally:
        server.close()
