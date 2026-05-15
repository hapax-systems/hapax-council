"""Sync client for the compositor CommandServer UDS.

Used by ``logos-api`` to proxy HTTP requests from the frontend /
MCP / voice surfaces into the compositor's in-memory ``LayoutState``.
Mirrors the wire format from
:class:`agents.studio_compositor.command_server.CommandServer`:
newline-terminated JSON request followed by newline-terminated JSON
response. One request per connection.

Protocol (matches command_server.py line-by-line):

    request  :  {"command": "compositor.surface.set_geometry",
                 "args": {"surface_id": "pip-lr", "x": 0, "y": 0,
                          "w": 480, "h": 180}} + b"\\n"
    response :  {"status": "ok", ...} + b"\\n"
             or {"status": "error", "error": "...", ...} + b"\\n"

On any socket-layer failure the client returns a structured error
dict with ``status="error"`` and ``error="<category>"`` so callers
can surface a consistent error envelope to the HTTP layer without
needing to know about ``OSError`` / ``TimeoutError`` at the
framework level.
"""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 2.0


class CommandClientError(Exception):
    """Carries a structured ``{status: error, error: <code>, ...}`` payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("error", "command_failed"))
        self.payload = payload


class CompositorCommandClient:
    """Sync client that sends one JSON command over the compositor UDS.

    Call ``execute`` with a command string and args dict. Returns the
    parsed response dict on success, or raises ``CommandClientError``
    with a structured payload on any protocol / connection / server-
    side error.

    The client opens a fresh socket per call — matches the server's
    one-request-per-connection protocol. No connection pooling.
    """

    def __init__(
        self,
        socket_path: Path,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self.socket_path = socket_path
        self.timeout_s = timeout_s

    def execute(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Send one command and return the parsed ``status=ok`` payload.

        Raises ``CommandClientError`` on any failure mode:

        - ``socket_missing`` — the server isn't running (socket file absent)
        - ``connection_refused`` — the socket exists but nothing is listening
        - ``timeout`` — the connection or round-trip took longer than
          ``timeout_s`` seconds
        - ``read_failed`` — the server closed before sending a response line
        - ``invalid_response`` — the server response wasn't valid JSON
        - ``server_error`` — the server returned ``status=error``. The
          raised ``CommandClientError`` payload includes the full server
          error dict (``error``, ``hint``, ``surface_id``, etc.).
        """
        request = {"command": command, "args": args or {}}
        if request_id:
            request["request_id"] = request_id
        line = (json.dumps(request) + "\n").encode("utf-8")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout_s)
                s.connect(str(self.socket_path))
                s.sendall(line)
                # BETA-FINDING-G: do NOT shutdown(SHUT_WR) — the compositor
                # command server is a plain blocking ``socket.recv`` loop
                # (not uvloop), so the race that broke the daimonion TTS
                # server doesn't apply here, but leaving the write side
                # open keeps this client consistent with
                # ``DaimonionTtsClient`` and avoids any future regression.
                buf = bytearray()
                while b"\n" not in buf:
                    try:
                        chunk = s.recv(4096)
                    except TimeoutError as exc:
                        raise CommandClientError(
                            {"status": "error", "error": "timeout", "detail": str(exc)}
                        ) from exc
                    if not chunk:
                        raise CommandClientError({"status": "error", "error": "read_failed"})
                    buf.extend(chunk)
                    if len(buf) > 64 * 1024:
                        raise CommandClientError({"status": "error", "error": "response_too_large"})
                idx = bytes(buf).find(b"\n")
                header_bytes = bytes(buf[:idx])
        except FileNotFoundError as exc:
            raise CommandClientError(
                {
                    "status": "error",
                    "error": "socket_missing",
                    "socket_path": str(self.socket_path),
                }
            ) from exc
        except ConnectionRefusedError as exc:
            raise CommandClientError({"status": "error", "error": "connection_refused"}) from exc
        except TimeoutError as exc:
            raise CommandClientError(
                {"status": "error", "error": "timeout", "detail": str(exc)}
            ) from exc
        except OSError as exc:
            raise CommandClientError(
                {"status": "error", "error": "socket_error", "detail": str(exc)}
            ) from exc

        try:
            response = json.loads(header_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandClientError(
                {"status": "error", "error": "invalid_response", "detail": str(exc)}
            ) from exc

        if not isinstance(response, dict):
            raise CommandClientError(
                {"status": "error", "error": "invalid_response", "detail": "not a dict"}
            )

        if response.get("status") != "ok":
            raise CommandClientError(response)

        return response
