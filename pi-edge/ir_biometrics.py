"""ir_biometrics.py — rPPG heart rate + PERCLOS drowsiness from NIR.

Biometric loop runs at 30fps on a face ROI. Requires on-axis IR LED ring
for pupil detection. Gracefully disables when bright pupil not detected.
"""

from __future__ import annotations

import collections
import logging
import time

import numpy as np  # noqa: TC002 — Pi-side code

log = logging.getLogger(__name__)

EAR_BLINK_THRESHOLD = 0.22
PERCLOS_WINDOW_S = 60.0
PERCLOS_DROWSY_THRESHOLD = 0.4

RPPG_BUFFER_S = 10.0
RPPG_BANDPASS_LOW = 0.7  # Hz (42 BPM)
RPPG_BANDPASS_HIGH = 4.0  # Hz (240 BPM)


class BiometricTracker:
    """Tracks drowsiness (PERCLOS) and heart rate (rPPG) from NIR frames."""

    def __init__(self, fps: float = 30.0) -> None:
        self._fps = fps
        self.face_detected: bool = False
        self._ear_history: collections.deque[tuple[float, float]] = collections.deque(
            maxlen=int(PERCLOS_WINDOW_S * fps)
        )
        self._rppg_buffer: collections.deque[float] = collections.deque(
            maxlen=int(RPPG_BUFFER_S * fps)
        )
        self._last_bpm: int = 0
        self._last_bpm_confidence: float = 0.0
        self._blink_timestamps: collections.deque[float] = collections.deque(maxlen=100)
        self._was_closed = False

    def update_ear(self, ear: float, timestamp: float) -> None:
        """Record an Eye Aspect Ratio measurement."""
        self._ear_history.append((timestamp, ear))
        is_closed = ear < EAR_BLINK_THRESHOLD
        if self._was_closed and not is_closed:
            self._blink_timestamps.append(timestamp)
        self._was_closed = is_closed

    def update_rppg_intensity(self, mean_intensity: float) -> None:
        """Record a forehead ROI mean intensity value for rPPG."""
        self._rppg_buffer.append(mean_intensity)

    @property
    def perclos(self) -> float:
        """Percentage of time eyes were closed in the window."""
        if len(self._ear_history) < 10:
            return 0.0
        closed = sum(1 for _, ear in self._ear_history if ear < EAR_BLINK_THRESHOLD)
        return closed / len(self._ear_history)

    @property
    def drowsiness_score(self) -> float:
        """Composite drowsiness score [0.0, 1.0]."""
        p = self.perclos
        br = self.blink_rate
        score = 0.0
        if p > PERCLOS_DROWSY_THRESHOLD:
            score += 0.6
        elif p > 0.2:
            score += p
        if br < 5.0 and len(self._ear_history) > 100:
            score += 0.2
        return min(1.0, score)

    @property
    def blink_rate(self) -> float:
        """Blinks per minute over the last 60 seconds."""
        now = time.monotonic()
        cutoff = now - 60.0
        recent = [t for t in self._blink_timestamps if t > cutoff]
        if not self._blink_timestamps:
            return 0.0
        elapsed = min(60.0, now - self._blink_timestamps[0])
        if elapsed < 5.0:
            return 0.0
        return len(recent) / (elapsed / 60.0)

    def compute_heart_rate(self) -> tuple[int, float]:
        """Compute heart rate from rPPG buffer using FFT.

        Returns (bpm, confidence).
        """
        if len(self._rppg_buffer) < self._fps * 5:
            return self._last_bpm, 0.0

        signal = np.array(self._rppg_buffer)
        signal = signal - np.mean(signal)
        signal = signal * np.hamming(len(signal))

        fft = np.abs(np.fft.rfft(signal))
        freqs = np.fft.rfftfreq(len(signal), d=1.0 / self._fps)

        mask = (freqs >= RPPG_BANDPASS_LOW) & (freqs <= RPPG_BANDPASS_HIGH)
        if not np.any(mask):
            return self._last_bpm, 0.0

        band_fft = fft[mask]
        band_freqs = freqs[mask]

        peak_idx = np.argmax(band_fft)
        peak_freq = band_freqs[peak_idx]
        bpm = int(round(peak_freq * 60))

        mean_power = np.mean(band_fft)
        confidence = float(band_fft[peak_idx] / mean_power) if mean_power > 0 else 0.0
        confidence = min(1.0, max(0.0, (confidence - 1.0) / 4.0))

        if confidence > 0.3:
            self._last_bpm = bpm
            self._last_bpm_confidence = confidence

        return self._last_bpm, self._last_bpm_confidence

    def snapshot(self) -> dict:
        """Return current biometric state."""
        bpm, conf = self.compute_heart_rate()
        return {
            "heart_rate_bpm": bpm,
            "heart_rate_confidence": round(conf, 3),
            "perclos": round(self.perclos, 3),
            "blink_rate": round(self.blink_rate, 1),
            "drowsiness_score": round(self.drowsiness_score, 3),
            "pupil_detected": False,
            "face_detected": self.face_detected,
        }
