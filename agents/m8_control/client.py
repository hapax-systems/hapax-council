"""In-process Python client for the M8 control daemon.

Lightweight wrapper for callers (director loop, recruitment consumer,
operator-facing CLI) that don't want to wrangle async UDS connections.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

from agents.m8_control.daemon import DEFAULT_UDS_PATH


class M8ControlClient:
    """Synchronous UDS client. One request per connection."""

    def __init__(self, uds_path: Path = DEFAULT_UDS_PATH, *, timeout_s: float = 1.0) -> None:
        self._uds_path = uds_path
        self._timeout_s = timeout_s

    def _send(self, payload: dict) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self._timeout_s)
            sock.connect(str(self._uds_path))
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
        raw = b"".join(chunks).decode("utf-8").strip()
        if not raw:
            return {"ok": False, "error": "empty response"}
        return json.loads(raw)

    def button(self, *names: str, hold_ms: int = 16) -> dict:
        return self._send({"cmd": "button", "mask": list(names), "hold_ms": hold_ms})

    def keyjazz(self, note: int, velocity: int = 100) -> dict:
        return self._send({"cmd": "keyjazz", "note": note, "velocity": velocity})

    def reset(self) -> dict:
        return self._send({"cmd": "reset"})

    def theme(self, slot: int, r: int, g: int, b: int) -> dict:
        return self._send({"cmd": "theme", "slot": slot, "r": r, "g": g, "b": b})
