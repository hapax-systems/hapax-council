"""Tests for hapax_voice hotkey activation via Unix socket."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from agents.hapax_voice.hotkey import HotkeyServer


@pytest.mark.asyncio
async def test_socket_receives_toggle() -> None:
    """Send 'toggle' command and verify callback fires."""
    received: list[str] = []

    async def on_command(cmd: str) -> None:
        received.append(cmd)

    sock_path = Path(tempfile.mktemp(suffix=".sock"))
    server = HotkeyServer(socket_path=sock_path, on_command=on_command)
    try:
        await server.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(b"toggle\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

        # Give the server a moment to process
        await asyncio.sleep(0.05)

        assert received == ["toggle"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_socket_ignores_invalid() -> None:
    """Send invalid command and verify callback does NOT fire."""
    received: list[str] = []

    async def on_command(cmd: str) -> None:
        received.append(cmd)

    sock_path = Path(tempfile.mktemp(suffix=".sock"))
    server = HotkeyServer(socket_path=sock_path, on_command=on_command)
    try:
        await server.start()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(b"invalid_command\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

        await asyncio.sleep(0.05)

        assert received == []
    finally:
        await server.stop()
