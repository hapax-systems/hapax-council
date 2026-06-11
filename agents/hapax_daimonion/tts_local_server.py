"""Podium-local TTS engine server.

This process owns the TTS model and exposes a localhost-only Unix socket to
the daimonion runtime. It is the single synthesis queue for conversation,
bridge/presynth, and hosting speech so daemon restarts do not reload model
weights and concurrent callers do not collide inside Kokoro/Chatterbox.

Wire protocol v1:

* request: one newline-terminated JSON object
* success: one JSON header line, then repeated ``pcm`` frames, then ``done``
* error: one JSON header line with ``status=error``

PCM frames are ``{"type": "pcm", "len": N}\\n`` followed by exactly ``N``
bytes of raw int16 mono PCM. The final frame is ``{"type": "done",
"pcm_len": total}\\n``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from agents.hapax_daimonion.tts import (
    TTS_SAMPLE_RATE,
    TTS_STREAM_PROTOCOL,
    TTSManager,
    resolve_request_deadline_s,
    resolve_server_socket_path,
)

log = logging.getLogger(__name__)

_MAX_REQUEST_BYTES = 64 * 1024
_STREAM_CHUNK_BYTES = 64 * 1024
_REQUEST_READ_TIMEOUT_S = 5.0
_DEADLINE_EXIT_CODE = 124
_PRIORITY_VALUE = {
    "interactive": 0,
    "bridge": 1,
    "hosting": 2,
}


@dataclass(order=True)
class _QueuedRequest:
    priority: int
    sequence: int
    enqueued_at: float = field(compare=False)
    deadline_at: float = field(compare=False)
    request: dict[str, Any] = field(compare=False)
    writer: asyncio.StreamWriter = field(compare=False)
    done: asyncio.Future[None] = field(compare=False)


class TtsLocalServer:
    """UDS server that owns the TTS model and one prioritized synth queue."""

    def __init__(
        self,
        *,
        socket_path: Path,
        tts_manager: TTSManager,
        default_deadline_s: float = 30.0,
        sample_rate: int = TTS_SAMPLE_RATE,
        channels: int = 1,
        fatal_exit: Callable[[int], object] = os._exit,
    ) -> None:
        self.socket_path = socket_path
        self._tts = tts_manager
        self._default_deadline_s = default_deadline_s
        self._sample_rate = sample_rate
        self._channels = channels
        self._server: asyncio.AbstractServer | None = None
        self._queue: asyncio.PriorityQueue[_QueuedRequest] = asyncio.PriorityQueue()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts-engine")
        self._worker_task: asyncio.Task[None] | None = None
        self._sequence = 0
        self._fatal_exit = fatal_exit

    async def start(self) -> None:
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._worker_task = asyncio.create_task(self._worker_loop(), name="tts-engine-worker")
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path),
        )
        os.chmod(self.socket_path, 0o600)
        log.info("TTS engine server listening on %s", self.socket_path)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._worker_task is not None:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
            self._worker_task = None
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError:
                log.debug("TTS engine socket vanished during stop", exc_info=True)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\n"), _REQUEST_READ_TIMEOUT_S)
        except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            await _write_error(writer, "malformed request framing", error_type=type(exc).__name__)
            return

        if len(raw) > _MAX_REQUEST_BYTES:
            await _write_error(writer, "request too large")
            return

        try:
            request = json.loads(raw.decode("utf-8").rstrip("\n"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            await _write_error(writer, f"invalid json: {exc}", error_type=type(exc).__name__)
            return

        if request.get("op") == "ping":
            await self._write_ping(writer, request_id=_request_id(request))
            return

        text = request.get("text")
        use_case = request.get("use_case", "conversation")
        if not isinstance(text, str) or not text.strip():
            await _write_error(writer, "missing or empty text", request_id=_request_id(request))
            return
        if not isinstance(use_case, str):
            await _write_error(writer, "non-string use_case", request_id=_request_id(request))
            return

        deadline_s = _deadline_s(request, self._default_deadline_s)
        if deadline_s is None:
            await _write_error(
                writer,
                "deadline_s must be a positive number",
                request_id=_request_id(request),
            )
            return

        done = asyncio.get_running_loop().create_future()
        self._sequence += 1
        item = _QueuedRequest(
            priority=_priority_value(request.get("priority")),
            sequence=self._sequence,
            enqueued_at=time.monotonic(),
            deadline_at=time.monotonic() + deadline_s,
            request=request,
            writer=writer,
            done=done,
        )
        await self._queue.put(item)
        await done

    async def _write_ping(self, writer: asyncio.StreamWriter, *, request_id: str | None) -> None:
        header = {
            "status": "ok",
            "op": "pong",
            "protocol": TTS_STREAM_PROTOCOL,
            "request_id": request_id,
            "backend": self._tts.backend,
            "last_synthesis_backend": self._tts.last_synthesis_backend,
            "queue_depth": self._queue.qsize(),
            "sample_rate": self._sample_rate,
            "channels": self._channels,
        }
        await _write_json_line_and_close(writer, header)

    async def _worker_loop(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                await self._serve_request(item)
            finally:
                self._queue.task_done()

    async def _serve_request(self, item: _QueuedRequest) -> None:
        request_id = _request_id(item.request)
        queue_wait_ms = round((time.monotonic() - item.enqueued_at) * 1000)
        remaining_s = item.deadline_at - time.monotonic()
        if remaining_s <= 0:
            await _write_error(
                item.writer,
                "deadline expired before synthesis started",
                request_id=request_id,
                queue_wait_ms=queue_wait_ms,
                error_type="DeadlineExpired",
            )
            item.done.set_result(None)
            return

        text = str(item.request["text"])
        use_case = str(item.request.get("use_case") or "conversation")
        speed = _float_or_default(item.request.get("speed"), 1.0)
        interview_mode = bool(item.request.get("interview_mode", False))
        role = item.request.get("role")
        arc_position = item.request.get("arc_position")
        synth_started = time.monotonic()

        loop = asyncio.get_running_loop()
        synth_call = partial(
            self._tts.synthesize,
            text,
            use_case,
            speed=speed,
            interview_mode=interview_mode,
            role=role if isinstance(role, str) else None,
            arc_position=_optional_float(arc_position),
        )
        try:
            pcm = await asyncio.wait_for(
                loop.run_in_executor(self._executor, synth_call),
                timeout=remaining_s,
            )
        except TimeoutError:
            await _write_error(
                item.writer,
                "deadline exceeded during synthesis",
                request_id=request_id,
                queue_wait_ms=queue_wait_ms,
                error_type="DeadlineExceeded",
            )
            item.done.set_result(None)
            log.critical(
                "TTS engine synthesis deadline exceeded; exiting so systemd restarts "
                "the model owner instead of leaving the single worker wedged"
            )
            self._fatal_exit(_DEADLINE_EXIT_CODE)
            return
        except Exception as exc:
            log.exception("TTS engine synthesis failed for %r", text[:80])
            await _write_error(
                item.writer,
                f"synthesis failed: {exc}",
                request_id=request_id,
                queue_wait_ms=queue_wait_ms,
                error_type=type(exc).__name__,
            )
            item.done.set_result(None)
            return

        synthesis_ms = round((time.monotonic() - synth_started) * 1000)
        if not pcm:
            await _write_error(
                item.writer,
                "synthesis produced no audio",
                request_id=request_id,
                queue_wait_ms=queue_wait_ms,
                synthesis_ms=synthesis_ms,
                error_type="EmptyPcm",
            )
            item.done.set_result(None)
            return

        await _write_pcm_stream(
            item.writer,
            pcm=pcm,
            request_id=request_id,
            backend=self._tts.last_synthesis_backend,
            queue_wait_ms=queue_wait_ms,
            synthesis_ms=synthesis_ms,
            sample_rate=self._sample_rate,
            channels=self._channels,
        )
        item.done.set_result(None)


async def _write_pcm_stream(
    writer: asyncio.StreamWriter,
    *,
    pcm: bytes,
    request_id: str | None,
    backend: str | None,
    queue_wait_ms: int,
    synthesis_ms: int,
    sample_rate: int,
    channels: int,
) -> None:
    header = {
        "status": "ok",
        "protocol": TTS_STREAM_PROTOCOL,
        "request_id": request_id,
        "sample_rate": sample_rate,
        "channels": channels,
        "backend": backend,
        "queue_wait_ms": queue_wait_ms,
        "synthesis_ms": synthesis_ms,
        "stream": "pcm-chunks",
    }
    try:
        writer.write(json.dumps(header).encode("utf-8") + b"\n")
        for offset in range(0, len(pcm), _STREAM_CHUNK_BYTES):
            chunk = pcm[offset : offset + _STREAM_CHUNK_BYTES]
            frame = {"type": "pcm", "len": len(chunk)}
            writer.write(json.dumps(frame).encode("utf-8") + b"\n")
            writer.write(chunk)
            await writer.drain()
        done = {"type": "done", "pcm_len": len(pcm)}
        writer.write(json.dumps(done).encode("utf-8") + b"\n")
        await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        log.debug("TTS engine client disconnected before stream completed")
    finally:
        await _close_writer(writer)


async def _write_error(
    writer: asyncio.StreamWriter,
    message: str,
    *,
    request_id: str | None = None,
    queue_wait_ms: int | None = None,
    synthesis_ms: int | None = None,
    error_type: str = "Error",
) -> None:
    header = {
        "status": "error",
        "protocol": TTS_STREAM_PROTOCOL,
        "request_id": request_id,
        "error": message,
        "error_type": error_type,
        "sample_rate": TTS_SAMPLE_RATE,
        "channels": 1,
        "pcm_len": 0,
    }
    if queue_wait_ms is not None:
        header["queue_wait_ms"] = queue_wait_ms
    if synthesis_ms is not None:
        header["synthesis_ms"] = synthesis_ms
    await _write_json_line_and_close(writer, header)


async def _write_json_line_and_close(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    try:
        writer.write(json.dumps(payload).encode("utf-8") + b"\n")
        await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        await _close_writer(writer)


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except (ConnectionResetError, BrokenPipeError):
        pass


def _request_id(request: dict[str, Any]) -> str | None:
    value = request.get("request_id")
    return value if isinstance(value, str) else None


def _deadline_s(request: dict[str, Any], default: float) -> float | None:
    value = request.get("deadline_s", default)
    try:
        deadline = float(value)
    except (TypeError, ValueError):
        return None
    if deadline <= 0:
        return None
    return deadline


def _priority_value(value: Any) -> int:
    if isinstance(value, int):
        return max(0, min(value, 99))
    if isinstance(value, str):
        return _PRIORITY_VALUE.get(value, _PRIORITY_VALUE["hosting"])
    return _PRIORITY_VALUE["hosting"]


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def serve(
    *,
    socket_path: Path | None = None,
    voice_id: str = "af_heart",
    default_deadline_s: float | None = None,
) -> None:
    tts = TTSManager(voice_id=voice_id, transport="local")
    log.info("Preloading TTS model for local engine server...")
    tts.preload()
    server = TtsLocalServer(
        socket_path=socket_path or resolve_server_socket_path(),
        tts_manager=tts,
        default_deadline_s=default_deadline_s or resolve_request_deadline_s(),
    )
    await server.start()
    try:
        await asyncio.Event().wait()
    finally:
        await server.stop()


def main() -> None:
    from agents._log_setup import configure_logging

    configure_logging(agent="hapax-tts-local")
    asyncio.run(serve())


if __name__ == "__main__":
    main()
