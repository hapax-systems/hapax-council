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

# Beta PR #756 queue-024 Phase 1 measured Kokoro CPU synth at
# ~6.6 chars/sec (361-char text → 54.6 s synth). Compositor react
# texts run 200–425 chars, which would time out 82% of long calls
# under the original 30 s cap. Raise to 90 s, which covers up to
# ~600 chars at the measured throughput. The complementary fix is
# a character cap enforced by ``director_loop._synthesize`` so the
# voice path never waits that long on a single speak-react call.
_DEFAULT_TIMEOUT_S = 90.0


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
                # BETA-FINDING-G: the initial version of this client
                # called ``s.shutdown(SHUT_WR)`` here. That caused a
                # 100% failure rate in production because the server
                # runs on uvloop, and uvloop's
                # ``asyncio.StreamReader.readuntil(b"\n")`` does not
                # surface the already-buffered newline before the EOF
                # notification: it waits for more data that will never
                # arrive, and the connection hangs until the client's
                # read timeout fires. Keeping the write side open past
                # ``sendall`` lets the server's readuntil return the
                # framed request immediately. The request is already
                # newline-terminated so there is no ambiguity about
                # message boundaries.
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
