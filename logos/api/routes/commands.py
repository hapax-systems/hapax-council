"""WebSocket command relay endpoint.

Relays command messages between external clients (MCP, voice) and the
frontend browser. The frontend connects with ?role=frontend; external
clients connect without that param.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

_log = logging.getLogger(__name__)

router = APIRouter(tags=["commands"])

# Forward-declared commands that go to the frontend
_FORWARDABLE_TYPES = {"execute", "query", "list"}


class _RelayState:
    """Mutable singleton holding the relay's runtime state."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.frontend: WebSocket | None = None
        # Maps message id → external WebSocket that is awaiting a result
        self.pending: dict[str, WebSocket] = {}
        # Maps subscription id → (pattern_regex, external WebSocket)
        self.subscriptions: dict[str, tuple[re.Pattern[str], WebSocket]] = {}

    def subscribe(self, sub_id: str, pattern: str, ws: WebSocket) -> None:
        # Convert glob pattern: escape dots, convert * to .*
        regex_str = re.escape(pattern).replace(r"\*", ".*")
        self.subscriptions[sub_id] = (re.compile(f"^{regex_str}$"), ws)

    def unsubscribe(self, sub_id: str) -> None:
        self.subscriptions.pop(sub_id, None)

    def remove_external(self, ws: WebSocket) -> None:
        """Remove all pending + subscriptions belonging to ws."""
        self.pending = {k: v for k, v in self.pending.items() if v is not ws}
        self.subscriptions = {k: v for k, v in self.subscriptions.items() if v[1] is not ws}


_state = _RelayState()


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await ws.send_json(payload)
    except Exception:
        pass


async def _handle_frontend(ws: WebSocket) -> None:
    """Handle messages coming from the frontend."""
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            msg_id = msg.get("id")

            if msg_type == "result" and msg_id:
                # Route result back to the waiting external client
                target = _state.pending.pop(msg_id, None)
                if target is not None:
                    await _send_json(target, msg)

            elif msg_type == "event":
                # Forward to matching subscribers
                path = msg.get("path", "")
                for sub_id, (pattern, ext_ws) in list(_state.subscriptions.items()):
                    if pattern.match(path):
                        await _send_json(ext_ws, {**msg, "subscription": sub_id})

    except WebSocketDisconnect:
        pass
    finally:
        if _state.frontend is ws:
            _state.frontend = None


async def _handle_external(ws: WebSocket) -> None:
    """Handle messages coming from an external client (MCP, voice, etc.)."""
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            msg_id = msg.get("id", "")

            if msg_type == "subscribe":
                pattern = msg.get("pattern", "*")
                _state.subscribe(msg_id, pattern, ws)

            elif msg_type == "unsubscribe":
                _state.unsubscribe(msg_id)

            elif msg_type in _FORWARDABLE_TYPES:
                if _state.frontend is None:
                    await _send_json(
                        ws,
                        {
                            "type": "result",
                            "id": msg_id,
                            "data": {"ok": False, "error": "frontend not connected"},
                        },
                    )
                else:
                    _state.pending[msg_id] = ws
                    await _send_json(_state.frontend, msg)

    except WebSocketDisconnect:
        pass
    finally:
        _state.remove_external(ws)


@router.websocket("/ws/commands")
async def commands_ws(websocket: WebSocket, role: str | None = None) -> None:
    """WebSocket relay between external command senders and the frontend."""
    await websocket.accept()

    if role == "frontend":
        _state.frontend = websocket
        await _handle_frontend(websocket)
    else:
        await _handle_external(websocket)
