"""Direct PipeWire audio capture for low-latency shader reactivity.

Improvements over the original:
- Hann windowed FFT (reduces spectral leakage for better onset detection)
- Rolling AGC: per-signal percentile normalization (reacts to dynamics, not absolute level)
- Onset classification: kick/snare/hat based on spectral shape at onset time
- Asymmetric beat pulse decay (fast attack, slow decay)
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections import deque

import numpy as np

log = logging.getLogger(__name__)

RATE = 48000
CHANNELS = 2
CHUNK = 512  # 10.7ms chunks for tighter transient response
BYTES_PER_FRAME = CHANNELS * 2  # int16
CHUNK_BYTES = CHUNK * BYTES_PER_FRAME

# Rolling AGC: ~4 seconds of history at ~93 chunks/sec (48000/512)
AGC_HISTORY_LEN = 372
AGC_FLOOR = 1e-6  # prevent division by zero

# 8 perceptually-spaced mel bands
MEL_BAND_EDGES_HZ = [20, 60, 250, 500, 1000, 2000, 4000, 8000, 16000]
MEL_BAND_NAMES = [
    "sub_bass",
    "bass",
    "low_mid",
    "mid",
    "upper_mid",
    "presence",
    "brilliance",
    "air",
]


def _hz_to_mel(hz: float) -> float:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _build_mel_filterbank(n_fft: int, sample_rate: int) -> np.ndarray:
    """Build an 8-band mel filterbank matrix (n_fft_bins x 8)."""
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
    n_bins = len(freqs)
    n_bands = len(MEL_BAND_EDGES_HZ) - 1
    fb = np.zeros((n_bins, n_bands), dtype=np.float32)
    for i in range(n_bands):
        lo = MEL_BAND_EDGES_HZ[i]
        hi = MEL_BAND_EDGES_HZ[i + 1]
        mask = (freqs >= lo) & (freqs < hi)
        if mask.any():
            fb[mask, i] = 1.0 / max(1, mask.sum())  # normalize per band
    return fb


class SignalNormalizer:
    """Per-signal rolling percentile normalization (AGC).

    Tracks recent values and normalizes against the p10-p90 range so
    the output reflects musical dynamics, not absolute level.
    """

    def __init__(self, history_len: int = AGC_HISTORY_LEN) -> None:
        self._bufs: dict[str, deque[float]] = {}
        self._history_len = history_len

    def normalize(self, name: str, raw: float) -> float:
        buf = self._bufs.get(name)
        if buf is None:
            buf = deque(maxlen=self._history_len)
            self._bufs[name] = buf
        buf.append(raw)
        if len(buf) < 10:
            return min(1.0, max(0.0, raw))
        arr = np.array(buf)
        p10 = float(np.percentile(arr, 10))
        p90 = float(np.percentile(arr, 90))
        spread = p90 - p10
        if spread < AGC_FLOOR:
            return 0.0
        return float(np.clip((raw - p10) / spread, 0.0, 1.0))


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
            "onset_kick": 0.0,
            "onset_snare": 0.0,
            "onset_hat": 0.0,
            "sidechain_kick": 0.0,  # slow-decay kick for sidechain pump (0.92x)
            "spectral_centroid": 0.0,
            "spectral_flatness": 0.0,
            "spectral_rolloff": 0.0,
            "zero_crossing_rate": 0.0,
        }
        # Add mel band signals
        for name in MEL_BAND_NAMES:
            self._signals[f"mel_{name}"] = 0.0
        # DSP state
        self._beat_pulse: float = 0.0
        self._onset_kick: float = 0.0
        self._onset_snare: float = 0.0
        self._onset_hat: float = 0.0
        self._sidechain_kick: float = 0.0
        self._prev_fft: np.ndarray | None = None
        self._flux_history: deque[float] = deque(maxlen=30)
        self._agc = SignalNormalizer()
        # Precompute Hann window and mel filterbank
        self._window = np.hanning(CHUNK)
        self._mel_fb = _build_mel_filterbank(CHUNK, RATE)

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
        """Read signals and decay transient pulses (called once per tick at 30fps)."""
        with self._lock:
            result = dict(self._signals)
            # Decay all pulse signals — fast attack already happened in _process_chunk
            self._beat_pulse *= 0.7
            self._onset_kick *= 0.75
            self._onset_snare *= 0.65
            self._onset_hat *= 0.55
            self._sidechain_kick *= 0.92  # slow pump decay (~500ms to 30%)
            self._signals["beat_pulse"] = self._beat_pulse
            self._signals["mixer_beat"] = self._beat_pulse
            self._signals["onset_kick"] = self._onset_kick
            self._signals["onset_snare"] = self._onset_snare
            self._signals["onset_hat"] = self._onset_hat
            self._signals["sidechain_kick"] = self._sidechain_kick
            return result

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
                        "512",
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

        # RMS energy — fixed multiplier, strong 0-1 swing
        rms = float(np.sqrt(np.mean(samples**2)))
        energy = min(1.0, rms * 4.0)

        # Hann-windowed FFT (reduces spectral leakage for better onset detection)
        windowed = samples * self._window
        fft = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(windowed), 1.0 / RATE)

        # --- Spectral flux onset detection (median baseline, adaptive threshold) ---
        if self._prev_fft is None:
            self._prev_fft = fft
            flux = 0.0
        else:
            diff = fft - self._prev_fft
            flux = float(np.sum(np.maximum(diff, 0.0)))
            self._prev_fft = fft

        self._flux_history.append(flux)
        if len(self._flux_history) >= 5:
            flux_arr = np.array(self._flux_history)
            flux_median = float(np.median(flux_arr))
            flux_std = float(np.std(flux_arr))
            threshold = flux_median + 2.0 * flux_std
        else:
            threshold = flux * 3.0

        is_onset = flux > threshold and flux > 0.5

        if is_onset:
            self._beat_pulse = 1.0
            self._classify_onset(fft, freqs)

        # --- 3-band split with fixed normalization ---
        # Use fixed multipliers (calibrated for typical music levels) instead of
        # AGC for modulator signals. AGC compressed dynamics too much — the
        # modulator needs strong 0-1 swings to drive visible effects.
        # Pipeline clamping prevents overflow.
        bass_mask = freqs < 250
        mid_mask = (freqs >= 250) & (freqs < 2000)
        high_mask = (freqs >= 2000) & (freqs < 8000)

        bass = min(1.0, float(np.mean(fft[bass_mask])) * 0.3) if bass_mask.any() else 0.0
        mid = min(1.0, float(np.mean(fft[mid_mask])) * 0.5) if mid_mask.any() else 0.0
        high = min(1.0, float(np.mean(fft[high_mask])) * 1.0) if high_mask.any() else 0.0

        # --- 8-band mel decomposition ---
        mel_energies = self._mel_fb.T @ fft  # (8,)
        mel_signals: dict[str, float] = {}
        # Fixed multipliers per band (lower bands louder, higher bands need more boost)
        mel_scales = [0.2, 0.3, 0.5, 0.6, 0.8, 1.0, 1.5, 2.0]
        for i, name in enumerate(MEL_BAND_NAMES):
            mel_signals[f"mel_{name}"] = min(1.0, float(mel_energies[i]) * mel_scales[i])

        # --- Timbral features ---
        fft_sum = float(np.sum(fft)) + AGC_FLOOR
        centroid = float(np.sum(freqs * fft) / fft_sum)
        centroid_norm = min(1.0, centroid / 8000.0)

        fft_positive = fft[fft > AGC_FLOOR]
        if len(fft_positive) > 0:
            log_mean = float(np.exp(np.mean(np.log(fft_positive))))
            arith_mean = float(np.mean(fft_positive))
            flatness = log_mean / (arith_mean + AGC_FLOOR)
        else:
            flatness = 0.0

        # Spectral rolloff: frequency below which 85% of energy is concentrated
        cumsum = np.cumsum(fft)
        rolloff_idx = np.searchsorted(cumsum, 0.85 * cumsum[-1]) if cumsum[-1] > 0 else 0
        rolloff = float(freqs[min(rolloff_idx, len(freqs) - 1)])
        rolloff_norm = min(1.0, rolloff / 8000.0)

        # Zero-crossing rate (time domain)
        zcr = float(np.sum(np.abs(np.diff(np.sign(samples))) > 0)) / len(samples)

        with self._lock:
            self._signals["mixer_energy"] = energy
            self._signals["mixer_bass"] = bass
            self._signals["mixer_mid"] = mid
            self._signals["mixer_high"] = high
            self._signals["spectral_centroid"] = centroid_norm
            self._signals["spectral_flatness"] = flatness
            self._signals["spectral_rolloff"] = rolloff_norm
            self._signals["zero_crossing_rate"] = zcr
            self._signals.update(mel_signals)
            if is_onset:
                self._signals["mixer_beat"] = 1.0
                self._signals["beat_pulse"] = 1.0

    def _classify_onset(self, fft: np.ndarray, freqs: np.ndarray) -> None:
        """Classify onset as kick/snare/hat based on spectral shape."""
        fft_sum = float(np.sum(fft)) + AGC_FLOOR
        centroid = float(np.sum(freqs * fft) / fft_sum)

        bass_mask = freqs < 250
        high_mask = freqs > 3000
        bass_ratio = float(np.sum(fft[bass_mask]) / fft_sum) if bass_mask.any() else 0.0
        high_ratio = float(np.sum(fft[high_mask]) / fft_sum) if high_mask.any() else 0.0

        # Spectral flatness for noise detection (snare/hat)
        fft_positive = fft[fft > AGC_FLOOR]
        if len(fft_positive) > 0:
            flatness = float(np.exp(np.mean(np.log(fft_positive)))) / (
                float(np.mean(fft_positive)) + AGC_FLOOR
            )
        else:
            flatness = 0.0

        # Classification thresholds tuned for hip-hop (tighter = less false positives)
        # 808 kicks: centroid ~60-80Hz, bass_ratio >0.7
        # Snares: centroid 200-1500Hz, broadband AND noisy (flatness >0.4)
        # Hats: centroid >3kHz, high_ratio >0.5
        if centroid < 200 and bass_ratio > 0.65:
            self._onset_kick = 1.0
            self._sidechain_kick = 1.0
        elif centroid > 3500 and high_ratio > 0.5:
            self._onset_hat = 1.0
        elif flatness > 0.4 and 200 < centroid < 1500:
            self._onset_snare = 1.0
        # Ambiguous onsets: don't attribute — let beat_pulse handle them.
        # This prevents chromatic aberration from firing on every sound.
