"""TTSExecutor — beat-aligned TTS playback via pre-synthesized PCM.

Implements the Executor protocol. Expects command.params["pcm_data"]
(pre-synthesized) and command.params["sample_rate"]. Synthesis happens
BEFORE enqueue into ScheduleQueue — execute() is pure playback.

This keeps synthesis latency out of the critical path.
The governance layer synthesizes first, packs PCM into Command.params,
creates Schedule targeting next bar boundary, enqueues. TTSExecutor just plays.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from agents.hapax_voice.commands import Command

if TYPE_CHECKING:
    import pyaudio

log = logging.getLogger(__name__)


class TTSExecutor:
    """Executor for beat-aligned TTS playback.

    handles = {"tts_announce"}
    """

    def __init__(self, pa: pyaudio.PyAudio | Any) -> None:
        self._pa = pa

    @property
    def name(self) -> str:
        return "tts"

    @property
    def handles(self) -> frozenset[str]:
        return frozenset({"tts_announce"})

    def execute(self, command: Command) -> None:
        """Play pre-synthesized PCM from command params. Non-blocking."""
        pcm_data = command.params.get("pcm_data")
        if pcm_data is None:
            log.warning("TTSExecutor: missing pcm_data in command params")
            return
        if not isinstance(pcm_data, bytes):
            log.warning("TTSExecutor: pcm_data is not bytes")
            return

        sample_rate = command.params.get("sample_rate", 24000)
        channels = command.params.get("channels", 1)

        thread = threading.Thread(
            target=self._play_pcm,
            args=(pcm_data, sample_rate, channels),
            daemon=True,
        )
        thread.start()

    def _play_pcm(self, pcm_data: bytes, rate: int, channels: int) -> None:
        """Play PCM buffer through PyAudio. Runs in a background thread."""
        try:
            stream = self._pa.open(
                format=8,  # pyaudio.paInt16 = 8
                channels=channels,
                rate=rate,
                output=True,
            )
            stream.write(pcm_data)
            stream.stop_stream()
            stream.close()
        except Exception as exc:
            log.warning("TTSExecutor playback failed: %s", exc)

    def available(self) -> bool:
        return self._pa is not None

    def close(self) -> None:
        pass  # PyAudio instance owned by daemon
