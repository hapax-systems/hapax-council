"""Tests for the podium-local TTS engine server protocol."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from agents.hapax_daimonion.tts import TTSManager
from agents.hapax_daimonion.tts_local_server import TtsLocalServer


class _StubTtsManager:
    def __init__(self, pcm: bytes = b"\x00\x01" * 100, *, delay_s: float = 0.0) -> None:
        self.backend = "kokoro"
        self.last_synthesis_backend: str | None = None
        self.pcm = pcm
        self.delay_s = delay_s
        self.calls: list[tuple[str, str]] = []

    def synthesize(
        self,
        text: str,
        use_case: str = "conversation",
        *,
        speed: float = 1.0,
        interview_mode: bool = False,
        role: str | None = None,
        arc_position: float | None = None,
    ) -> bytes:
        del speed, interview_mode, role, arc_position
        self.calls.append((text, use_case))
        if self.delay_s:
            time.sleep(self.delay_s)
        self.last_synthesis_backend = "kokoro"
        return self.pcm


@pytest.fixture
def socket_path(tmp_path: Path) -> Path:
    return tmp_path / "tts-local.sock"


@pytest.mark.asyncio
async def test_client_reads_chunked_pcm_stream(socket_path: Path) -> None:
    pcm = b"\x01\x02" * 40_000
    stub = _StubTtsManager(pcm=pcm)
    server = TtsLocalServer(socket_path=socket_path, tts_manager=stub)
    await server.start()
    try:
        client = TTSManager(
            transport="server",
            server_socket_path=socket_path,
            request_deadline_s=5.0,
        )
        result = await asyncio.to_thread(client.synthesize, "hello", "conversation")
    finally:
        await server.stop()

    assert result == pcm
    assert stub.calls == [("hello", "conversation")]
    assert client.last_synthesis_backend == "kokoro"
    assert client.last_server_liveness is not None
    assert client.last_server_liveness["status"] == "ok"
    assert client.last_server_liveness["pcm_bytes"] == len(pcm)
    assert client.last_server_liveness["backend"] == "kokoro"


@pytest.mark.asyncio
async def test_preload_pings_server_without_synthesis(socket_path: Path) -> None:
    stub = _StubTtsManager()
    server = TtsLocalServer(socket_path=socket_path, tts_manager=stub)
    await server.start()
    try:
        client = TTSManager(
            transport="server",
            server_socket_path=socket_path,
            request_deadline_s=5.0,
        )
        await asyncio.to_thread(client.preload)
    finally:
        await server.stop()

    assert stub.calls == []
    assert client.last_server_liveness is not None
    assert client.last_server_liveness["status"] == "ok"
    assert client.last_server_liveness["backend"] == "kokoro"


@pytest.mark.asyncio
async def test_three_daemon_client_restarts_reuse_one_engine_server(socket_path: Path) -> None:
    stub = _StubTtsManager()
    server = TtsLocalServer(socket_path=socket_path, tts_manager=stub)
    await server.start()
    try:
        for idx in range(3):
            client = TTSManager(
                transport="server",
                server_socket_path=socket_path,
                request_deadline_s=5.0,
            )
            await asyncio.to_thread(client.preload)
            result = await asyncio.to_thread(
                client.synthesize,
                f"restart {idx}",
                "conversation",
            )
            assert result == stub.pcm
            assert client.last_server_liveness is not None
            assert client.last_server_liveness["status"] == "ok"
    finally:
        await server.stop()

    assert stub.calls == [
        ("restart 0", "conversation"),
        ("restart 1", "conversation"),
        ("restart 2", "conversation"),
    ]


@pytest.mark.asyncio
async def test_deadline_error_returns_empty_pcm(socket_path: Path) -> None:
    stub = _StubTtsManager(delay_s=0.05)
    server = TtsLocalServer(socket_path=socket_path, tts_manager=stub)
    await server.start()
    try:
        client = TTSManager(
            transport="server",
            server_socket_path=socket_path,
            request_deadline_s=0.01,
        )
        result = await asyncio.to_thread(client.synthesize, "too slow", "conversation")
    finally:
        await server.stop()

    assert result == b""
    assert stub.calls == [("too slow", "conversation")]
    assert client.last_server_liveness is not None
    assert client.last_server_liveness["status"] == "error"
    assert "deadline" in client.last_server_liveness["error"]
