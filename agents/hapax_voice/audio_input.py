"""Continuous audio input from PipeWire/ALSA via PyAudio callback stream."""
from __future__ import annotations

import asyncio
import logging
import queue
import subprocess

import pyaudio

log = logging.getLogger(__name__)


class AudioInputStream:
    """Wraps a PyAudio input stream with async frame retrieval.

    Opens a callback-mode stream on a named PipeWire/ALSA source.
    Frames are buffered in a thread-safe queue and retrieved via
    the async get_frame() method.
    """

    def __init__(
        self,
        source_name: str = "echo_cancel_capture",
        sample_rate: int = 16000,
        frame_ms: int = 30,
        queue_maxsize: int = 100,
    ) -> None:
        self._source_name = source_name
        self._sample_rate = sample_rate
        self._frame_ms = frame_ms
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=queue_maxsize)
        self._stream: pyaudio.Stream | None = None
        self._active = False

        self._drop_count: int = 0
        self._pa: pyaudio.PyAudio | None = None
        self._pa_terminated = True
        self._init_pyaudio()
        self._device_index = self._find_device()

    @property
    def frame_samples(self) -> int:
        return self._sample_rate * self._frame_ms // 1000

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * 2

    @property
    def is_active(self) -> bool:
        return self._active

    def _init_pyaudio(self) -> None:
        """Create a fresh PyAudio instance."""
        self._pa = pyaudio.PyAudio()
        self._pa_terminated = False

    def _set_pipewire_default_source(self) -> bool:
        """Set the requested source as PipeWire default via pactl.

        PyAudio's ALSA backend cannot directly open PipeWire virtual sources
        (they produce silence). Setting the PipeWire default source routes
        PyAudio's default device through the requested source.

        Returns True if the source was set, False on failure.
        """
        try:
            result = subprocess.run(
                ["pactl", "set-default-source", self._source_name],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                log.info(
                    "Set PipeWire default source to '%s'", self._source_name,
                )
                return True
            log.warning(
                "pactl set-default-source failed (rc=%d): %s",
                result.returncode,
                result.stderr.decode(errors="replace").strip(),
            )
        except FileNotFoundError:
            log.warning("pactl not found, cannot set default source")
        except Exception as exc:
            log.warning("Failed to set PipeWire default source: %s", exc)
        return False

    def _find_device(self) -> int | None:
        """Configure audio routing for the requested source.

        Sets the PipeWire default source to the requested name (e.g.
        echo_cancel_capture), then returns None to use PyAudio's default
        device — which PipeWire routes through the selected source.
        """
        if self._set_pipewire_default_source():
            return None
        log.warning(
            "Could not set '%s' as default source, using system default",
            self._source_name,
        )
        return None

    def start(self) -> None:
        if self._active:
            return
        if self._pa_terminated:
            self._init_pyaudio()
            self._device_index = self._find_device()
        try:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self._sample_rate,
                input=True,
                input_device_index=self._device_index,
                frames_per_buffer=self.frame_samples,
                stream_callback=self._pyaudio_callback,
            )
            self._active = True
            log.info(
                "Audio input stream started (rate=%d, frame=%dms)",
                self._sample_rate,
                self._frame_ms,
            )
        except Exception as exc:
            log.warning("Failed to open audio input stream: %s", exc)
            self._active = False

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._active = False
        if not self._pa_terminated:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa_terminated = True

    def _pyaudio_callback(
        self, in_data: bytes, frame_count: int, time_info: dict, status: int
    ) -> tuple[None, int]:
        try:
            self._queue.put_nowait(in_data)
            self._drop_count = 0
        except queue.Full:
            self._drop_count += 1
            if self._drop_count == 1:
                log.warning("Audio frame queue full — dropping frames")
        return (None, pyaudio.paContinue)

    async def get_frame(self, timeout: float = 1.0) -> bytes | None:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: self._queue.get(timeout=timeout)
            )
        except queue.Empty:
            return None
