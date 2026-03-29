"""Surface 8: Hotkey commands — socket → validation → dispatch.

Tests hotkey server lifecycle, command validation, and real
Unix domain socket communication.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from agents.hapax_daimonion.hotkey import HotkeyServer


class TestHotkeyServerLifecycle:
    """Server starts, listens, and stops cleanly."""

    @pytest.mark.asyncio
    async def test_start_creates_socket(self, tmp_path):
        sock = tmp_path / "test.sock"
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()
        assert sock.exists()

        await server.stop()
        assert not sock.exists()

    @pytest.mark.asyncio
    async def test_removes_stale_socket(self, tmp_path):
        sock = tmp_path / "test.sock"
        sock.touch()  # stale socket
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()
        assert sock.exists()

        await server.stop()


class TestHotkeyCommandDispatch:
    """Commands are validated and dispatched correctly."""

    @pytest.mark.asyncio
    async def test_valid_command_dispatched(self, tmp_path):
        sock = tmp_path / "test.sock"
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()

        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write(b"toggle\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

        await asyncio.sleep(0.1)
        callback.assert_called_once_with("toggle")

        await server.stop()

    @pytest.mark.asyncio
    async def test_invalid_command_ignored(self, tmp_path):
        sock = tmp_path / "test.sock"
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()

        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write(b"invalid_command\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

        await asyncio.sleep(0.1)
        callback.assert_not_called()

        await server.stop()

    @pytest.mark.asyncio
    async def test_all_valid_commands_accepted(self, tmp_path):
        sock = tmp_path / "test.sock"
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()

        for cmd in ["toggle", "open", "close", "status", "scan"]:
            callback.reset_mock()
            reader, writer = await asyncio.open_unix_connection(str(sock))
            writer.write(f"{cmd}\n".encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.05)
            callback.assert_called_once_with(cmd)

        await server.stop()

    @pytest.mark.asyncio
    async def test_multiple_clients_sequential(self, tmp_path):
        sock = tmp_path / "test.sock"
        callback = AsyncMock()
        server = HotkeyServer(socket_path=sock, on_command=callback)

        await server.start()

        for _i in range(3):
            reader, writer = await asyncio.open_unix_connection(str(sock))
            writer.write(b"status\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        await asyncio.sleep(0.15)
        assert callback.call_count == 3

        await server.stop()
