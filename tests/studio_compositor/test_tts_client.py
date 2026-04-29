"""Tests for agents.studio_compositor.tts_client.

Exercises the sync client against an in-process stub UDS server. The
stub implements the same wire format as TtsServer without pulling in
torch, so these tests work in CI without GPU/Kokoro dependencies.
"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

from agents.studio_compositor.tts_client import DaimonionTtsClient, synthesis_timeout_s


class _StubServer:
    """Minimal blocking-socket UDS server for client tests.

    Accepts exactly one connection at a time. Each call to ``serve_once``
    reads one request + writes the canned response; the client must
    disconnect between calls.
    """

    def __init__(
        self,
        socket_path: Path,
        *,
        header_factory,
        body: bytes = b"",
        delay_between_header_and_body_s: float = 0.0,
        close_before_header: bool = False,
        malformed_header: bool = False,
    ) -> None:
        self.socket_path = socket_path
        self.header_factory = header_factory
        self.body = body
        self.delay = delay_between_header_and_body_s
        self.close_before_header = close_before_header
        self.malformed_header = malformed_header
        self.received: list[dict] = []
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self.socket_path))
        self._sock.listen(4)
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop:
            try:
                self._sock.settimeout(0.5)
                try:
                    conn, _ = self._sock.accept()
                except TimeoutError:
                    continue
            except OSError:
                return
            with conn:
                self._handle(conn)

    def _handle(self, conn: socket.socket) -> None:
        buf = bytearray()
        while b"\n" not in buf:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf.extend(chunk)
        idx = bytes(buf).find(b"\n")
        try:
            req = json.loads(bytes(buf[:idx]).decode("utf-8"))
            self.received.append(req)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        if self.close_before_header:
            return

        if self.malformed_header:
            conn.sendall(b"{not json\n")
            return

        header = self.header_factory(req)
        header_bytes = json.dumps(header).encode("utf-8") + b"\n"
        try:
            conn.sendall(header_bytes)
            if self.delay > 0:
                import time as _time

                _time.sleep(self.delay)
            conn.sendall(self.body)
        except OSError:
            return

    def close(self) -> None:
        self._stop = True
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)
        if self.socket_path.exists():
            self.socket_path.unlink()


@pytest.fixture
def socket_path(tmp_path: Path) -> Path:
    return tmp_path / "tts.sock"


def test_happy_path_returns_pcm(socket_path: Path) -> None:
    body = b"\x01\x02\x03\x04" * 8
    server = _StubServer(
        socket_path,
        header_factory=lambda req: {
            "status": "ok",
            "sample_rate": 24000,
            "pcm_len": len(body),
        },
        body=body,
    )
    try:
        client = DaimonionTtsClient(socket_path=socket_path, timeout_s=2.0)
        pcm = client.synthesize("hello world")
        assert pcm == body
        assert server.received == [{"text": "hello world", "use_case": "conversation"}]
    finally:
        server.close()


def test_use_case_is_passed_through(socket_path: Path) -> None:
    server = _StubServer(
        socket_path,
        header_factory=lambda req: {"status": "ok", "sample_rate": 24000, "pcm_len": 0},
        body=b"",
    )
    try:
        client = DaimonionTtsClient(socket_path=socket_path, timeout_s=2.0)
        client.synthesize("hi", use_case="briefing")
        assert server.received[0]["use_case"] == "briefing"
    finally:
        server.close()


def test_empty_text_short_circuits_without_connecting(tmp_path: Path) -> None:
    # Socket does not exist — an empty-text call should NOT touch it.
    missing = tmp_path / "nope.sock"
    client = DaimonionTtsClient(socket_path=missing, timeout_s=1.0)
    assert client.synthesize("") == b""
    assert client.synthesize("   ") == b""
    assert not missing.exists()


def test_missing_socket_returns_empty_bytes(tmp_path: Path) -> None:
    client = DaimonionTtsClient(socket_path=tmp_path / "missing.sock", timeout_s=1.0)
    assert client.synthesize("hello") == b""


def test_server_error_status_returns_empty(socket_path: Path) -> None:
    server = _StubServer(
        socket_path,
        header_factory=lambda req: {
            "status": "error",
            "error": "kokoro boom",
            "sample_rate": 24000,
            "pcm_len": 0,
        },
    )
    try:
        client = DaimonionTtsClient(socket_path=socket_path, timeout_s=2.0)
        assert client.synthesize("hello") == b""
    finally:
        server.close()


def test_malformed_header_returns_empty(socket_path: Path) -> None:
    server = _StubServer(
        socket_path,
        header_factory=lambda req: {"status": "ok", "sample_rate": 24000, "pcm_len": 0},
        malformed_header=True,
    )
    try:
        client = DaimonionTtsClient(socket_path=socket_path, timeout_s=2.0)
        assert client.synthesize("hello") == b""
    finally:
        server.close()


def test_server_closes_before_header_returns_empty(socket_path: Path) -> None:
    server = _StubServer(
        socket_path,
        header_factory=lambda req: {"status": "ok", "sample_rate": 24000, "pcm_len": 0},
        close_before_header=True,
    )
    try:
        client = DaimonionTtsClient(socket_path=socket_path, timeout_s=2.0)
        assert client.synthesize("hello") == b""
    finally:
        server.close()


def test_body_split_across_multiple_recvs_is_reassembled(socket_path: Path) -> None:
    body = b"\xaa" * 100_000
    server = _StubServer(
        socket_path,
        header_factory=lambda req: {
            "status": "ok",
            "sample_rate": 24000,
            "pcm_len": len(body),
        },
        body=body,
    )
    try:
        client = DaimonionTtsClient(socket_path=socket_path, timeout_s=5.0)
        pcm = client.synthesize("big")
        assert pcm == body
    finally:
        server.close()


def test_synthesis_timeout_scales_with_long_text() -> None:
    short = "brief director beat"
    long = "word " * 260

    assert synthesis_timeout_s(short, minimum_s=90.0) == 90.0
    assert synthesis_timeout_s(long, minimum_s=90.0) > 260.0


def test_client_uses_duration_aware_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed_timeouts: list[float] = []
    text = "word " * 260

    class _FakeSocket:
        def __enter__(self) -> _FakeSocket:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def settimeout(self, value: float) -> None:
            observed_timeouts.append(value)

        def connect(self, _path: str) -> None:
            raise FileNotFoundError

    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: _FakeSocket())

    client = DaimonionTtsClient(socket_path=tmp_path / "tts.sock", timeout_s=90.0)
    assert client.synthesize(text) == b""
    assert observed_timeouts == [synthesis_timeout_s(text, minimum_s=90.0)]
