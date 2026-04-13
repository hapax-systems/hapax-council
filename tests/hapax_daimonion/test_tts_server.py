"""Tests for agents.hapax_daimonion.tts_server.

Exercises the UDS wire protocol end-to-end against a stubbed TTSManager
so the test is hermetic (no torch, no Kokoro). Pairs with
tests/studio_compositor/test_tts_client.py — when both pass the
compositor→daimonion delegation path is wired correctly.
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import pytest

from agents.hapax_daimonion.tts_server import TtsServer


class _StubTtsManager:
    """Record calls and return deterministic fake PCM for verification."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.raise_on_next: Exception | None = None

    def synthesize(self, text: str, use_case: str = "conversation") -> bytes:
        self.calls.append((text, use_case))
        if self.raise_on_next is not None:
            exc = self.raise_on_next
            self.raise_on_next = None
            raise exc
        return (text.encode("utf-8") + b":" + use_case.encode("utf-8")) * 2


@pytest.fixture
def stub_tts() -> _StubTtsManager:
    return _StubTtsManager()


@pytest.fixture
def socket_path(tmp_path: Path) -> Path:
    return tmp_path / "tts.sock"


async def _sync_client_request(path: Path, payload: dict[str, str]) -> tuple[dict, bytes]:
    """Sync client round-trip — mirrors DaimonionTtsClient's wire format."""

    def _do() -> tuple[dict, bytes]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(5.0)
            s.connect(str(path))
            s.sendall(json.dumps(payload).encode("utf-8") + b"\n")
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            buf = bytearray()
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
            idx = bytes(buf).find(b"\n")
            header_bytes = bytes(buf[:idx])
            tail = bytes(buf[idx + 1 :])
            header = json.loads(header_bytes.decode("utf-8"))
            pcm_len = int(header.get("pcm_len", 0))
            remaining = pcm_len - len(tail)
            chunks = [tail] if tail else []
            while remaining > 0:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return header, b"".join(chunks)

    return await asyncio.to_thread(_do)


@pytest.mark.asyncio
async def test_start_binds_and_reports_ok(stub_tts: _StubTtsManager, socket_path: Path) -> None:
    server = TtsServer(socket_path=socket_path, tts_manager=stub_tts)
    await server.start()
    try:
        assert socket_path.exists()
        header, pcm = await _sync_client_request(
            socket_path, {"text": "hello", "use_case": "conversation"}
        )
        assert header["status"] == "ok"
        assert header["sample_rate"] == 24000
        assert header["pcm_len"] == len(pcm)
        assert pcm == b"hello:conversation" * 2
        assert stub_tts.calls == [("hello", "conversation")]
    finally:
        await server.stop()
        assert not socket_path.exists()


@pytest.mark.asyncio
async def test_default_use_case(stub_tts: _StubTtsManager, socket_path: Path) -> None:
    server = TtsServer(socket_path=socket_path, tts_manager=stub_tts)
    await server.start()
    try:
        header, pcm = await _sync_client_request(socket_path, {"text": "hi"})
        assert header["status"] == "ok"
        assert stub_tts.calls == [("hi", "conversation")]
        assert pcm == b"hi:conversation" * 2
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_missing_text_returns_error(stub_tts: _StubTtsManager, socket_path: Path) -> None:
    server = TtsServer(socket_path=socket_path, tts_manager=stub_tts)
    await server.start()
    try:
        header, pcm = await _sync_client_request(socket_path, {"use_case": "conversation"})
        assert header["status"] == "error"
        assert "text" in header["error"].lower()
        assert pcm == b""
        assert stub_tts.calls == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_synthesis_failure_is_reported(stub_tts: _StubTtsManager, socket_path: Path) -> None:
    stub_tts.raise_on_next = RuntimeError("kokoro boom")
    server = TtsServer(socket_path=socket_path, tts_manager=stub_tts)
    await server.start()
    try:
        header, pcm = await _sync_client_request(socket_path, {"text": "please break"})
        assert header["status"] == "error"
        assert "kokoro boom" in header["error"]
        assert pcm == b""
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_stop_unlinks_stale_socket_and_is_idempotent(
    stub_tts: _StubTtsManager, socket_path: Path
) -> None:
    # Pre-create a stale socket file; start() should unlink it.
    socket_path.write_bytes(b"")
    server = TtsServer(socket_path=socket_path, tts_manager=stub_tts)
    await server.start()
    assert socket_path.exists()
    await server.stop()
    assert not socket_path.exists()
    # Second stop must not raise.
    await server.stop()


@pytest.mark.asyncio
async def test_concurrent_calls_are_serialized(
    stub_tts: _StubTtsManager, socket_path: Path
) -> None:
    """Two simultaneous clients must not interleave synthesize calls.

    The server holds an asyncio.Lock around synthesize because daimonion's
    TTSManager is also used by the CPAL voice loop — concurrent in-process
    inference on the same Kokoro pipeline is not safe.
    """

    class _ObservingStub(_StubTtsManager):
        def __init__(self) -> None:
            super().__init__()
            self.in_flight = 0
            self.max_in_flight = 0

        def synthesize(self, text: str, use_case: str = "conversation") -> bytes:  # noqa: D401
            import time as _time

            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            _time.sleep(0.05)  # force overlap window if lock is missing
            try:
                return super().synthesize(text, use_case)
            finally:
                self.in_flight -= 1

    stub = _ObservingStub()
    server = TtsServer(socket_path=socket_path, tts_manager=stub)
    await server.start()
    try:
        results = await asyncio.gather(
            _sync_client_request(socket_path, {"text": "a"}),
            _sync_client_request(socket_path, {"text": "b"}),
            _sync_client_request(socket_path, {"text": "c"}),
        )
        for header, pcm in results:
            assert header["status"] == "ok"
            assert pcm != b""
        assert stub.max_in_flight == 1, (
            "tts server must serialize synthesize calls via asyncio.Lock"
        )
    finally:
        await server.stop()
