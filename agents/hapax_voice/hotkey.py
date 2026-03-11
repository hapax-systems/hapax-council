"""Hotkey activation via Unix domain socket."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Coroutine
from pathlib import Path

log = logging.getLogger(__name__)

_VALID_COMMANDS = {"toggle", "open", "close", "status", "scan"}


class HotkeyServer:
    """Unix socket server that receives hotkey commands."""

    def __init__(
        self,
        socket_path: Path,
        on_command: Callable[[str], Coroutine],
    ) -> None:
        self.socket_path = socket_path
        self.on_command = on_command
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        """Start listening on the Unix socket."""
        # Remove stale socket file if present
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path),
        )
        os.chmod(self.socket_path, 0o600)
        log.info("Hotkey server listening on %s", self.socket_path)

    async def stop(self) -> None:
        """Stop the server and clean up the socket file."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path.exists():
            self.socket_path.unlink()
        log.info("Hotkey server stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Read one command line, validate, and dispatch."""
        try:
            data = await reader.readline()
            command = data.decode().strip()
            if command in _VALID_COMMANDS:
                log.debug("Received valid command: %s", command)
                await self.on_command(command)
            else:
                log.warning("Ignored invalid command: %r", command)
        except Exception:
            log.exception("Error handling hotkey client")
        finally:
            writer.close()
            await writer.wait_closed()
