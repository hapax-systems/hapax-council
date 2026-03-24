"""Unix domain socket server for inbound control commands.

Protocol: JSON-line (one JSON object per newline) over Unix socket.
Path: $XDG_RUNTIME_DIR/hapax-bar.sock

Commands:
  {"cmd": "theme", "mode": "research|rnd"}
  {"cmd": "refresh", "modules": ["health", "gpu"]}
  {"cmd": "flash", "module": "health", "duration_ms": 3000}
"""

from __future__ import annotations

import json
import os
from typing import Any

from gi.repository import Gio, GLib


def _socket_path() -> str:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    return os.path.join(runtime_dir, "hapax-bar.sock")


class SocketServer:
    """Listens on a Unix socket for JSON commands."""

    def __init__(self) -> None:
        self._handlers: dict[str, Any] = {}
        self._service: Gio.SocketService | None = None

    def register(self, cmd: str, handler: Any) -> None:
        """Register a handler for a command name."""
        self._handlers[cmd] = handler

    def start(self) -> None:
        """Start listening on the Unix socket."""
        sock_path = _socket_path()

        # Remove stale socket
        try:
            os.unlink(sock_path)
        except FileNotFoundError:
            pass

        self._service = Gio.SocketService()
        address = Gio.UnixSocketAddress.new(sock_path)
        self._service.add_address(
            address,
            Gio.SocketType.STREAM,
            Gio.SocketProtocol.DEFAULT,
        )
        self._service.connect("incoming", self._on_incoming)
        self._service.start()

    def stop(self) -> None:
        if self._service:
            self._service.stop()
        try:
            os.unlink(_socket_path())
        except FileNotFoundError:
            pass

    def _on_incoming(
        self,
        _service: Gio.SocketService,
        connection: Gio.SocketConnection,
        _source: Any,
    ) -> bool:
        try:
            istream = connection.get_input_stream()
            data = istream.read_bytes(4096, None)
            if data is None:
                return True

            text = data.get_data().decode("utf-8", errors="replace").strip()
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    cmd = msg.get("cmd", "")
                    handler = self._handlers.get(cmd)
                    if handler:
                        # Run on main thread via idle_add
                        GLib.idle_add(handler, msg)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        return True
