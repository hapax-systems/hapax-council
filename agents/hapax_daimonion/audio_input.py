"""Continuous audio input from PipeWire via pw-cat subprocess.

Replaces PyAudio callback stream which delivers silence on PipeWire
(PyAudio's ALSA backend cannot read from PipeWire virtual sources).
pw-cat reads natively from PipeWire and pipes raw PCM to stdout.
"""

from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger(__name__)

# Preferred source when echo-cancellation is known to be active.
# See docs/runbooks/audio-topology.md and spec 2026-04-18-audio-pathways-audit-design.md.
_AEC_SOURCE_NAME = "echo_cancel_capture"
# Fallback when HAPAX_AEC_ACTIVE is not set — the raw Yeti source.
# Users keep this until the PipeWire drop-in is installed and verified.
_RAW_YETI_PATTERN = "alsa_input.usb-Blue_Microphones_Yeti"


def _resolve_default_source() -> str:
    """Pick the default pw-cat target based on the AEC env flag.

    Operator flips ``HAPAX_AEC_ACTIVE=1`` after installing
    ``config/pipewire/hapax-echo-cancel.conf`` and verifying with
    ``scripts/audio-topology-check.sh``. Off by default so daimonion
    does not chase a virtual source that is not yet in the graph.
    """
    if os.environ.get("HAPAX_AEC_ACTIVE", "").strip() == "1":
        return _AEC_SOURCE_NAME
    return _RAW_YETI_PATTERN


class AudioInputStream:
    """Reads audio from PipeWire via pw-cat subprocess.

    Spawns pw-cat --record targeting the configured source. Reads
    raw PCM int16 mono from stdout in frame-sized chunks. Frames
    are placed in an asyncio.Queue for async retrieval.
    """

    def __init__(
        self,
        source_name: str | None = None,
        sample_rate: int = 16000,
        frame_ms: int = 30,
        queue_maxsize: int = 300,
    ) -> None:
        self._source_name = source_name if source_name is not None else _resolve_default_source()
        self._sample_rate = sample_rate
        self._frame_ms = frame_ms
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=queue_maxsize)
        self._process: asyncio.subprocess.Process | None = None
        self._active = False
        self._reader_task: asyncio.Task | None = None
        self._drop_count: int = 0

    @property
    def frame_samples(self) -> int:
        return self._sample_rate * self._frame_ms // 1000

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * 2  # int16 = 2 bytes per sample

    @property
    def is_active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._active:
            return
        try:
            loop = asyncio.get_running_loop()
            self._reader_task = loop.create_task(self._run_reader())
            self._active = True
            log.info(
                "Audio input stream started (rate=%d, frame=%dms, source=%s)",
                self._sample_rate,
                self._frame_ms,
                self._source_name,
            )
        except Exception as exc:
            log.warning("Failed to start audio input: %s", exc)
            self._active = False

    def stop(self) -> None:
        self._active = False
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self._process is not None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass
            self._process = None

    async def _run_reader(self) -> None:
        """Spawn pw-cat and read frames from stdout into the queue."""
        cmd = [
            "pw-cat",
            "--record",
            "--target",
            self._source_name,
            "--format",
            "s16",
            "--rate",
            str(self._sample_rate),
            "--channels",
            "1",
            "-",
        ]
        retry_delay = 2.0
        while self._active:
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                log.info("pw-cat started (pid=%d, target=%s)", self._process.pid, self._source_name)
                retry_delay = 2.0

                while self._active and self._process.returncode is None:
                    data = await self._process.stdout.readexactly(self.frame_bytes)
                    try:
                        self._queue.put_nowait(data)
                        self._drop_count = 0
                    except asyncio.QueueFull:
                        self._drop_count += 1
                        if self._drop_count == 1:
                            log.warning("Audio frame queue full — dropping frames")

            except asyncio.IncompleteReadError:
                log.warning("pw-cat stream ended unexpectedly")
            except asyncio.CancelledError:
                break
            except FileNotFoundError:
                log.error("pw-cat not found — install pipewire")
                self._active = False
                break
            except Exception as exc:
                log.warning("pw-cat error: %s — retrying in %.0fs", exc, retry_delay)

            if self._active:
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)

        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except (TimeoutError, ProcessLookupError):
                pass

    async def get_frame(self, timeout: float = 1.0) -> bytes | None:
        """Await the next audio frame from the queue."""
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None
