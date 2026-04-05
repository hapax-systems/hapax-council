"""Direct PipeWire audio capture for low-latency shader reactivity."""

from __future__ import annotations

import logging
import subprocess
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

RATE = 48000
CHANNELS = 2
CHUNK = 1024
BYTES_PER_FRAME = CHANNELS * 2  # int16
CHUNK_BYTES = CHUNK * BYTES_PER_FRAME


class CompositorAudioCapture:
    """Captures mixer audio via pw-cat for low-latency reactivity signals."""

    def __init__(self, target: str = "mixer_master") -> None:
        self._target = target
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._running = False
        self._lock = threading.Lock()
        self._signals: dict[str, float] = {
            "mixer_energy": 0.0,
            "mixer_bass": 0.0,
            "mixer_mid": 0.0,
            "mixer_high": 0.0,
            "mixer_beat": 0.0,
            "beat_pulse": 0.0,
        }
        # DSP state
        self._smoothed_rms: float = 0.0
        self._beat_baseline: float = 0.01
        self._beat_pulse: float = 0.0
        self._bass_peak: float = 0.01
        self._mid_peak: float = 0.01
        self._high_peak: float = 0.01

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="audio-capture"
        )
        self._thread.start()
        log.info("Audio capture started (target=%s)", self._target)

    def stop(self) -> None:
        self._running = False
        if self._proc:
            try:
                self._proc.kill()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)
        log.info("Audio capture stopped")

    def get_signals(self) -> dict[str, float]:
        with self._lock:
            return dict(self._signals)

    def _capture_loop(self) -> None:
        while self._running:
            try:
                self._proc = subprocess.Popen(
                    [
                        "pw-cat",
                        "--record",
                        "--target",
                        self._target,
                        "--rate",
                        str(RATE),
                        "--channels",
                        str(CHANNELS),
                        "--format",
                        "s16",
                        "--latency",
                        "1024",
                        "-",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                log.info("pw-cat connected to %s", self._target)

                while self._running and self._proc.poll() is None:
                    data = self._proc.stdout.read(CHUNK_BYTES)  # type: ignore[union-attr]
                    if not data or len(data) < CHUNK_BYTES:
                        break
                    self._process_chunk(data)

            except Exception:
                log.debug("Audio capture error, reconnecting in 2s", exc_info=True)
            finally:
                if self._proc:
                    try:
                        self._proc.kill()
                    except OSError:
                        pass
                    self._proc = None

            if self._running:
                time.sleep(2.0)

    def _process_chunk(self, data: bytes) -> None:
        # Decode int16 stereo to mono float
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if CHANNELS == 2:
            samples = (samples[0::2] + samples[1::2]) * 0.5

        # RMS energy — fast attack, moderate decay, no multiplier saturation
        rms = float(np.sqrt(np.mean(samples**2)))
        alpha = 0.5 if rms > self._smoothed_rms else 0.2  # fast attack, moderate decay
        self._smoothed_rms = alpha * rms + (1 - alpha) * self._smoothed_rms
        energy = min(1.0, self._smoothed_rms * 3.0)

        # Beat detection: spike above baseline
        self._beat_baseline = 0.995 * self._beat_baseline + 0.005 * rms  # faster baseline adapt
        is_beat = rms > self._beat_baseline * 2.5 and rms > 0.02  # higher threshold
        if is_beat:
            self._beat_pulse = 1.0
        self._beat_pulse *= 0.85
        beat = min(1.0, self._beat_pulse)

        # 3-band FFT split
        fft = np.abs(np.fft.rfft(samples))
        freqs = np.fft.rfftfreq(len(samples), 1.0 / RATE)

        bass_mask = freqs < 250
        mid_mask = (freqs >= 250) & (freqs < 2000)
        high_mask = (freqs >= 2000) & (freqs < 8000)

        bass_raw = float(np.mean(fft[bass_mask])) if bass_mask.any() else 0.0
        mid_raw = float(np.mean(fft[mid_mask])) if mid_mask.any() else 0.0
        high_raw = float(np.mean(fft[high_mask])) if high_mask.any() else 0.0

        # Peak normalization — faster decay so peaks track real dynamics
        self._bass_peak = max(self._bass_peak * 0.99, bass_raw, 0.01)
        self._mid_peak = max(self._mid_peak * 0.99, mid_raw, 0.01)
        self._high_peak = max(self._high_peak * 0.99, high_raw, 0.01)

        bass = min(1.0, bass_raw / self._bass_peak)
        mid = min(1.0, mid_raw / self._mid_peak)
        high = min(1.0, high_raw / self._high_peak)

        with self._lock:
            self._signals["mixer_energy"] = energy
            self._signals["mixer_bass"] = bass
            self._signals["mixer_mid"] = mid
            self._signals["mixer_high"] = high
            self._signals["mixer_beat"] = beat
            self._signals["beat_pulse"] = beat
