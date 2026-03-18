"""Audio preprocessing pipeline — applied to every mic frame before VAD/STT.

Lightweight DSP operations that clean the audio signal:
1. High-pass filter at 80Hz (removes room rumble, desk vibration, HVAC)
2. RMS normalization (consistent level regardless of mic distance)
3. Noise gate (kills sub-threshold ambient before VAD sees it)

Total latency: <0.5ms per frame on CPU. No GPU needed.
"""

from __future__ import annotations

import numpy as np

# High-pass filter coefficients (1st order Butterworth at 80Hz, 16kHz sample rate)
# Pre-computed: cutoff=80Hz, fs=16000Hz
_HP_ALPHA = 0.9845  # 1 / (1 + 2*pi*80/16000)

# Noise gate threshold (RMS below this = silence)
_GATE_THRESHOLD_RMS = 50  # int16 scale (32768 max). ~0.15% of full scale.
_GATE_ATTACK_FRAMES = 2  # frames to open gate (prevent clicks)
_GATE_RELEASE_FRAMES = 5  # frames to close gate (prevent chop)

# RMS normalization target
_TARGET_RMS = 3000  # int16 scale. Comfortable level for VAD/STT.
_MAX_GAIN = 10.0  # prevent extreme amplification of silence
_SMOOTHING = 0.95  # gain smoothing (prevent pumping)


class AudioPreprocessor:
    """Stateful audio preprocessor for the voice pipeline.

    Call process() on every 30ms frame (480 samples, int16 mono, 16kHz).
    Returns cleaned frame of the same format.
    """

    def __init__(
        self,
        highpass: bool = True,
        normalize: bool = True,
        gate: bool = True,
    ) -> None:
        self._highpass = highpass
        self._normalize = normalize
        self._gate = gate

        # High-pass filter state
        self._hp_prev_in: float = 0.0
        self._hp_prev_out: float = 0.0

        # Noise gate state
        self._gate_open = False
        self._gate_counter = 0

        # Normalization state
        self._current_gain: float = 1.0

    def process(self, frame: bytes) -> bytes:
        """Process a single audio frame.

        Args:
            frame: Raw PCM int16 mono, 480 samples (30ms at 16kHz).

        Returns:
            Processed frame, same format.
        """
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float64)

        if self._highpass:
            samples = self._apply_highpass(samples)

        if self._gate:
            samples = self._apply_gate(samples)

        if self._normalize:
            samples = self._apply_normalize(samples)

        return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()

    def _apply_highpass(self, samples: np.ndarray) -> np.ndarray:
        """1st order high-pass filter at 80Hz."""
        out = np.empty_like(samples)
        prev_in = self._hp_prev_in
        prev_out = self._hp_prev_out

        for i in range(len(samples)):
            out[i] = _HP_ALPHA * (prev_out + samples[i] - prev_in)
            prev_in = samples[i]
            prev_out = out[i]

        self._hp_prev_in = prev_in
        self._hp_prev_out = prev_out
        return out

    def _apply_gate(self, samples: np.ndarray) -> np.ndarray:
        """Noise gate — silence frames below threshold."""
        rms = np.sqrt(np.mean(samples**2))

        if rms > _GATE_THRESHOLD_RMS:
            self._gate_counter = min(self._gate_counter + 1, _GATE_ATTACK_FRAMES)
        else:
            self._gate_counter = max(self._gate_counter - 1, -_GATE_RELEASE_FRAMES)

        if self._gate_counter >= _GATE_ATTACK_FRAMES:
            self._gate_open = True
        elif self._gate_counter <= -_GATE_RELEASE_FRAMES:
            self._gate_open = False

        if not self._gate_open:
            return np.zeros_like(samples)
        return samples

    def _apply_normalize(self, samples: np.ndarray) -> np.ndarray:
        """RMS normalization with smoothed gain."""
        rms = np.sqrt(np.mean(samples**2))
        if rms < 1.0:
            return samples  # silence — don't amplify

        target_gain = min(_TARGET_RMS / rms, _MAX_GAIN)
        # Smooth gain changes to prevent pumping
        self._current_gain = _SMOOTHING * self._current_gain + (1 - _SMOOTHING) * target_gain

        return samples * self._current_gain
