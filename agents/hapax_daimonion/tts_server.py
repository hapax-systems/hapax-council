"""Unix-domain-socket server exposing the in-process TTSManager.

Lets out-of-process callers (the studio compositor director loop, primarily)
delegate synthesis to the daimonion's already-loaded TTS backend (Kokoro or
Chatterbox) instead of loading torch themselves. Mirrors the existing
``HotkeyServer`` pattern (asyncio.start_unix_server, 0o600 socket perms,
idempotent start/stop).

Wire format: request is a single ``\\n``-terminated JSON object with
``text`` and optional ``use_case``. Response is a ``\\n``-terminated JSON
header followed by ``pcm_len`` bytes of raw PCM (int16 mono):

    {"status": "ok", "sample_rate": 24000, "pcm_len": N, "channels": 1}\\n<N bytes>

The sample_rate field reflects the active backend (24000 for both Kokoro
and Chatterbox Turbo). Clients MUST read sample_rate from the response
header rather than hardcoding it.

On error, the header is ``{"status": "error", "error": "..."}`` with
``pcm_len == 0``. Each client connection is handled in a single
call — the client is expected to close after reading the response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.tts import TTSManager

log = logging.getLogger(__name__)

# Header read cap: a request text of a few kB is plenty; reject anything
# larger so a malformed client can't exhaust memory before the JSON parse.
_MAX_REQUEST_BYTES = 64 * 1024


class TtsServer:
    """UDS server that delegates synthesize calls to an owned TTSManager."""

    def __init__(
        self,
        socket_path: Path,
        tts_manager: TTSManager,
        *,
        sample_rate: int = 24000,
        channels: int = 1,
    ) -> None:
        self.socket_path = socket_path
        self._tts_manager = tts_manager
        self._sample_rate = sample_rate
        self._channels = channels
        self._server: asyncio.AbstractServer | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Bind the UDS and begin accepting synthesize requests."""
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path),
        )
        os.chmod(self.socket_path, 0o600)
        log.info("TTS server listening on %s", self.socket_path)

    async def stop(self) -> None:
        """Close the listener and unlink the socket file."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError:
                log.debug("tts server socket already gone at stop", exc_info=True)
        log.info("TTS server stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await reader.readuntil(b"\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            log.warning("tts client sent malformed request framing: %s", exc)
            await _write_error(writer, "malformed request framing")
            return
        except Exception:
            log.exception("tts client read failed")
            return

        if len(raw) > _MAX_REQUEST_BYTES:
            await _write_error(writer, "request too large")
            return

        try:
            req = json.loads(raw.decode("utf-8").rstrip("\n"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            await _write_error(writer, f"invalid json: {exc}")
            return

        text = req.get("text")
        use_case = req.get("use_case", "conversation")
        if not isinstance(text, str):
            await _write_error(writer, "missing or non-string 'text'")
            return
        if not isinstance(use_case, str):
            await _write_error(writer, "non-string 'use_case'")
            return

        try:
            async with self._lock:
                pcm = await asyncio.to_thread(self._tts_manager.synthesize, text, use_case)
        except Exception as exc:
            log.exception("tts synthesis failed for %r", text[:80])
            await _write_error(writer, f"synthesis failed: {exc}")
            return

        header = json.dumps(
            {
                "status": "ok",
                "sample_rate": self._sample_rate,
                "channels": self._channels,
                "pcm_len": len(pcm),
            }
        ).encode("utf-8")
        try:
            writer.write(header + b"\n" + pcm)
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            log.debug("tts client disconnected before response write")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionResetError, BrokenPipeError):
                pass


async def _write_error(writer: asyncio.StreamWriter, message: str) -> None:
    header = json.dumps(
        {"status": "error", "error": message, "sample_rate": 24000, "channels": 1, "pcm_len": 0}
    ).encode("utf-8")
    try:
        writer.write(header + b"\n")
        await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionResetError, BrokenPipeError):
            pass
