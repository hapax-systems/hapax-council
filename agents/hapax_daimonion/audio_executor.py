"""AudioExecutor — plays samples via PyAudio in a daemon thread.

Implements the Executor protocol. Receives a shared PyAudio instance
from the daemon (same one ChimePlayer uses). Sub-50ms latency from
execute() call to first audio sample hitting PipeWire.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from agents.hapax_daimonion.commands import Command
from agents.hapax_daimonion.sample_bank import SampleBank

if TYPE_CHECKING:
    import pyaudio

log = logging.getLogger(__name__)


class AudioExecutor:
    """Executor playing MC samples via PyAudio.

    handles = {"vocal_throw", "ad_lib"}
    """

    def __init__(self, pa: pyaudio.PyAudio | Any, sample_bank: SampleBank) -> None:
        self._pa = pa
        self._sample_bank = sample_bank

    @property
    def name(self) -> str:
        return "audio"

    @property
    def handles(self) -> frozenset[str]:
        return frozenset({"vocal_throw", "ad_lib"})

    def execute(self, command: Command) -> None:
        """Play a sample matching the command action. Non-blocking."""
        energy_rms = command.params.get("energy_rms", 0.5)
        entry = self._sample_bank.select(command.action, energy_rms)
        if entry is None:
            log.debug("No sample for action=%s energy=%.2f", command.action, energy_rms)
            return
        thread = threading.Thread(
            target=self._play_pcm,
            args=(entry.pcm_data, entry.sample_rate, entry.channels, command.action),
            daemon=True,
        )
        thread.start()

    def _play_pcm(self, pcm_data: bytes, rate: int, channels: int, action: str) -> None:
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
            log.warning("AudioExecutor playback failed for %s: %s", action, exc)

    def available(self) -> bool:
        return self._pa is not None and self._sample_bank.sample_count > 0

    def close(self) -> None:
        pass  # PyAudio instance owned by daemon, not us
