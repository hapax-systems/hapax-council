"""Energy-ratio echo classification for continuous perception.

Layer 2 of the three-layer echo discrimination stack:
  Layer 1: PipeWire webrtc AEC (hardware-level)
  Layer 2: Energy-ratio classifier (this module)
  Layer 3: Adaptive VAD thresholds (conversation_buffer.py)

Replaces feed_reference() — instead of feeding raw PCM to an echo
canceller, we record the energy envelope for frame classification.
"""

from __future__ import annotations

import math
import struct
import time
from collections import deque


def _rms_int16(pcm: bytes) -> float:
    """Compute RMS energy of int16 PCM."""
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm)
    return math.sqrt(sum(s * s for s in samples) / n)


class TtsEnergyTracker:
    """Ring buffer of TTS output RMS energy for echo classification.

    Fed at each TTS write point (replaces feed_reference). The energy
    envelope is compared against mic input to distinguish residual echo
    from real operator speech.
    """

    def __init__(self, buffer_size: int = 100, decay_s: float = 1.5) -> None:
        self._energy_ring: deque[tuple[float, float]] = deque(maxlen=buffer_size)
        self._decay_s = decay_s
        self._last_record_at: float = 0.0

    def record(self, pcm: bytes) -> None:
        """Record RMS energy of a TTS PCM chunk."""
        rms = _rms_int16(pcm)
        now = time.monotonic()
        self._energy_ring.append((now, rms))
        self._last_record_at = now

    def is_active(self) -> bool:
        """True when system has spoken recently (within decay window)."""
        if self._last_record_at == 0.0:
            return False
        return (time.monotonic() - self._last_record_at) < self._decay_s

    def expected_energy(self) -> float:
        """Current expected echo energy level (RMS of recent TTS)."""
        if not self.is_active():
            return 0.0
        now = time.monotonic()
        recent = [e for t, e in self._energy_ring if now - t < self._decay_s]
        if not recent:
            return 0.0
        return sum(recent) / len(recent)


# Silence threshold: below this RMS, frame is silent regardless
_SILENCE_THRESHOLD = 300.0

# Echo ratio: if mic_rms / expected_tts_rms < this, it's likely echo
# (mic energy is "explained by" the known playback signal)
_ECHO_RATIO_CEILING = 1.5

# Speech floor: mic must exceed this RMS to be considered speech during TTS
_SPEECH_FLOOR_DURING_TTS = 1000.0


class EnergyClassifier:
    """Per-frame classification: speech vs residual echo vs silence.

    During system speech, compares mic frame energy against the known
    TTS energy envelope. High correlation = residual echo. Low
    correlation with high energy = real operator speech.
    """

    def __init__(self, tracker: TtsEnergyTracker) -> None:
        self._tracker = tracker

    def classify(self, mic_frame: bytes, *, system_speaking: bool) -> str:
        """Classify a single mic frame.

        Returns:
            "speech" — real operator speech (pass to VAD/buffer)
            "echo"   — residual echo of system output (suppress)
            "silent"  — below energy threshold (pass through, VAD handles)
        """
        mic_rms = _rms_int16(mic_frame)

        if mic_rms < _SILENCE_THRESHOLD:
            return "silent"

        if not system_speaking:
            return "speech"

        expected = self._tracker.expected_energy()
        if expected < _SILENCE_THRESHOLD:
            # Tracker has no recent TTS energy — can't be echo
            return "speech"

        # During system speech: compare mic energy against expected echo level.
        # AEC already attenuated ~30dB, so residual echo is much lower than
        # the original TTS. If mic energy is close to or below expected
        # residual level, it's echo. If much higher, it's real speech.
        ratio = mic_rms / expected
        if ratio < _ECHO_RATIO_CEILING and mic_rms < _SPEECH_FLOOR_DURING_TTS:
            return "echo"

        return "speech"
