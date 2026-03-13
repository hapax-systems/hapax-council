"""Non-blocking chime playback via PyAudio.

Pre-loads WAV files into memory at startup and plays them through
a dedicated PyAudio stream. Designed for sub-50ms latency from
play() call to first audio sample hitting PipeWire.

Playback runs in a daemon thread so play() returns immediately
without blocking the caller's event loop.
"""

from __future__ import annotations

import logging
import threading
import wave
from pathlib import Path

import pyaudio

log = logging.getLogger(__name__)

CHIME_SAMPLE_RATE = 48000
CHIME_CHANNELS = 1
CHIME_SAMPLE_WIDTH = 2  # 16-bit


class ChimePlayer:
    """Loads and plays pre-rendered chime WAV files with minimal latency.

    Args:
        chime_dir: Directory containing WAV files (activation.wav, etc.).
        auto_generate: If True, generates missing chimes on load.
        volume: Playback volume multiplier (0.0-1.0).
    """

    def __init__(
        self,
        chime_dir: Path,
        auto_generate: bool = False,
        volume: float = 0.7,
        pa: pyaudio.PyAudio | None = None,
    ) -> None:
        self._chime_dir = Path(chime_dir)
        self._auto_generate = auto_generate
        self._volume = max(0.0, min(1.0, volume))
        self._buffers: dict[str, bytes] = {}
        self._pa: pyaudio.PyAudio | None = pa
        self._owns_pa = pa is None  # only terminate if we created it

    def load(self) -> None:
        """Pre-load all chime WAVs into memory. Call once at daemon startup."""
        if self._auto_generate:
            self._ensure_chimes_exist()

        if not self._chime_dir.is_dir():
            log.warning("Chime directory does not exist: %s", self._chime_dir)
            return

        wav_files = list(self._chime_dir.glob("*.wav"))
        if not wav_files:
            log.warning("No WAV files found in %s", self._chime_dir)
            return

        for wav_path in wav_files:
            try:
                with wave.open(str(wav_path), "rb") as f:
                    raw = f.readframes(f.getnframes())
                # Pre-apply volume scaling so play() has zero overhead
                if self._volume < 1.0:
                    import numpy as np

                    samples = np.frombuffer(raw, dtype=np.int16)
                    raw = (samples * self._volume).astype(np.int16).tobytes()
                self._buffers[wav_path.stem] = raw
                log.debug("Loaded chime: %s (%d bytes)", wav_path.stem, len(raw))
            except Exception as exc:
                log.warning("Failed to load chime %s: %s", wav_path.name, exc)

        if self._pa is None:
            self._pa = pyaudio.PyAudio()
            self._owns_pa = True
        log.info("ChimePlayer loaded %d chimes from %s", len(self._buffers), self._chime_dir)

    def play(self, name: str) -> None:
        """Play a chime by name. Returns immediately — playback runs in a daemon thread.

        Args:
            name: Chime name (e.g. 'activation', 'deactivation', 'error', 'completion').
        """
        buf = self._buffers.get(name)
        if buf is None:
            log.warning("Unknown chime: %s", name)
            return

        if self._pa is None:
            log.warning("ChimePlayer not loaded, cannot play %s", name)
            return

        thread = threading.Thread(target=self._play_buf, args=(buf, name), daemon=True)
        thread.start()

    def _play_buf(self, buf: bytes, name: str) -> None:
        """Play a PCM buffer through PyAudio. Runs in a background thread."""
        try:
            stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=CHIME_CHANNELS,
                rate=CHIME_SAMPLE_RATE,
                output=True,
            )
            stream.write(buf)
            stream.stop_stream()
            stream.close()
        except Exception as exc:
            log.warning("Failed to play chime %s: %s", name, exc)

    def close(self) -> None:
        """Release PyAudio resources (only if self-owned)."""
        if self._pa is not None and self._owns_pa:
            self._pa.terminate()
            self._pa = None

    def _ensure_chimes_exist(self) -> None:
        """Generate chime WAVs if they don't exist."""
        expected = {"activation.wav", "deactivation.wav", "error.wav", "completion.wav"}
        if self._chime_dir.is_dir():
            existing = {f.name for f in self._chime_dir.glob("*.wav")}
            if expected <= existing:
                return  # All chimes present

        log.info("Generating chime WAVs in %s", self._chime_dir)
        try:
            from agents.hapax_voice.chime_synthesis import generate_all_chimes

            generate_all_chimes(self._chime_dir)
        except Exception as exc:
            log.warning("Failed to generate chimes: %s", exc)
