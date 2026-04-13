"""Sync TTS client — delegates synthesis to the hapax-daimonion TTS UDS server.

Removes the need to import ``agents.hapax_daimonion.tts`` (and therefore
torch + the full CUDA driver stack) in the compositor process. See
``docs/superpowers/audits/2026-04-13-alpha-finding-1-root-cause.md`` for
the root cause that motivated this split.

Wire format mirrors ``agents.hapax_daimonion.tts_server``:
request is a single ``\\n``-terminated JSON object, response is a
``\\n``-terminated JSON header followed by ``pcm_len`` bytes of raw PCM.
"""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 30.0  # Kokoro synthesis rarely exceeds a few seconds


class DaimonionTtsClient:
    """Sync client that synthesizes text over the daimonion TTS UDS.

    The compositor's director loop runs this from a background thread
    (``speak-react``), so a blocking ``socket.socket`` is the natural fit:
    no asyncio loop to juggle, and the thread is already dedicated to the
    one synthesize call at a time.
    """

    def __init__(
        self,
        socket_path: Path,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self.socket_path = socket_path
        self.timeout_s = timeout_s

    def synthesize(self, text: str, use_case: str = "conversation") -> bytes:
        """Send ``text`` to the daimonion and return raw PCM int16 bytes.

        Returns empty bytes on any failure (socket missing, connection
        refused, protocol error, server-side synthesis error). The caller
        is a speech-producing thread whose only recourse on failure is to
        fall through silently — matching the previous behavior of the
        in-process TTSManager path when it raised.
        """
        if not text or not text.strip():
            return b""

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout_s)
                s.connect(str(self.socket_path))
                request = json.dumps({"text": text, "use_case": use_case})
                s.sendall(request.encode("utf-8") + b"\n")
                # shutdown the write side so the server can detect EOF on
                # its single-request read, not that it strictly needs it
                # — readuntil('\n') already frames the request — but it
                # makes broken-pipe semantics cleaner if the server closes.
                try:
                    s.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
                header_bytes, body_head = _read_until_newline(s)
                if header_bytes is None:
                    log.warning("tts client: server closed before header")
                    return b""
                try:
                    header = json.loads(header_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    log.warning("tts client: malformed header: %r", header_bytes[:80])
                    return b""
                if header.get("status") != "ok":
                    log.warning(
                        "tts client: server error %r",
                        header.get("error", "unknown"),
                    )
                    return b""
                pcm_len = int(header.get("pcm_len", 0))
                if pcm_len <= 0:
                    return b""
                remaining = pcm_len - len(body_head)
                chunks: list[bytes] = [body_head] if body_head else []
                while remaining > 0:
                    chunk = s.recv(min(remaining, 65536))
                    if not chunk:
                        log.warning(
                            "tts client: server closed mid-body, got %d of %d",
                            pcm_len - remaining,
                            pcm_len,
                        )
                        return b""
                    chunks.append(chunk)
                    remaining -= len(chunk)
                return b"".join(chunks)
        except FileNotFoundError:
            log.warning("tts client: daimonion socket missing at %s", self.socket_path)
            return b""
        except ConnectionRefusedError:
            log.warning("tts client: daimonion refused connection at %s", self.socket_path)
            return b""
        except TimeoutError:
            log.warning("tts client: synthesize timed out after %.1fs", self.timeout_s)
            return b""
        except OSError as exc:
            log.warning("tts client: socket error: %s", exc)
            return b""


def _read_until_newline(sock: socket.socket) -> tuple[bytes | None, bytes]:
    """Read bytes up to (and dropping) the first ``\\n``.

    Returns (header_bytes, tail) where ``tail`` is any bytes that were
    already in the same recv chunk after the newline — those belong to
    the PCM body. Returns (None, b"") on premature EOF.
    """
    buf = bytearray()
    tail = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            return None, b""
        idx = chunk.find(b"\n")
        if idx >= 0:
            buf.extend(chunk[:idx])
            tail = chunk[idx + 1 :]
            return bytes(buf), tail
        buf.extend(chunk)
        if len(buf) > 64 * 1024:
            log.warning("tts client: header exceeded 64 KB without newline")
            return None, b""
