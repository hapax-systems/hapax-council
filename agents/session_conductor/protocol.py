"""UDS (Unix Domain Socket) protocol server for the session conductor."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from agents.session_conductor.rules import HookEvent, RuleRegistry
from agents.session_conductor.state import SessionState

log = logging.getLogger(__name__)


class ConductorServer:
    """Async UDS server that routes hook events through the rule registry."""

    def __init__(
        self,
        state: SessionState,
        registry: RuleRegistry,
        state_path: Path,
        sock_path: Path,
    ) -> None:
        self.state = state
        self.registry = registry
        self.state_path = state_path
        self.sock_path = sock_path
        self._stop_event: asyncio.Event | None = None
        self._server: asyncio.AbstractServer | None = None

    # ------------------------------------------------------------------
    # Event processing
    # ------------------------------------------------------------------

    def process_event(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Route a hook event through the registry and persist state.

        Returns a dict with 'action' and optional 'message'/'rewrite' keys.
        """
        event = HookEvent.from_dict(event_data)

        event_type = event_data.get("event_type", "")

        if event_type == "pre_tool_use":
            response = self.registry.process_pre_tool_use(event)
            if response is not None:
                result = response.to_dict()
            else:
                result = {"action": "allow"}
        elif event_type == "post_tool_use":
            responses = self.registry.process_post_tool_use(event)
            # Aggregate: block takes priority, then rewrite, then allow
            block = next((r for r in responses if r.action == "block"), None)
            if block:
                result = block.to_dict()
            else:
                rewrite = next((r for r in responses if r.action == "rewrite"), None)
                if rewrite:
                    result = rewrite.to_dict()
                else:
                    result = {"action": "allow"}
        else:
            result = {"action": "allow"}

        # Persist state after every event
        try:
            self.state.save(self.state_path)
        except OSError:
            log.exception("ConductorServer: failed to save state")

        return result

    # ------------------------------------------------------------------
    # Async server lifecycle
    # ------------------------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single UDS client connection."""
        try:
            raw = await reader.readline()
            if not raw:
                return
            try:
                event_data = json.loads(raw.decode())
            except json.JSONDecodeError:
                response = {"action": "allow", "error": "invalid JSON"}
                writer.write((json.dumps(response) + "\n").encode())
                await writer.drain()
                return

            result = self.process_event(event_data)
            writer.write((json.dumps(result) + "\n").encode())
            await writer.drain()
        except Exception:
            log.exception("ConductorServer: error handling client")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self) -> None:
        """Start the UDS server and run until shutdown() is called."""
        self._stop_event = asyncio.Event()

        # Remove stale socket file
        if self.sock_path.exists():
            self.sock_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.sock_path),
        )
        log.info("ConductorServer: listening on %s", self.sock_path)

        async with self._server:
            await self._stop_event.wait()

        log.info("ConductorServer: stopped")

    def shutdown(self) -> None:
        """Signal the server to stop."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._server is not None:
            self._server.close()
