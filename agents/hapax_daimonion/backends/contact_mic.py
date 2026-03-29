"""Contact microphone perception backend.

Captures structure-borne vibration from a Cortado MKIII contact mic via
PipeWire (through a named 'contact_mic' virtual source). Computes desk
activity metrics and tap gesture detection — all CPU DSP, no ML.

The capture loop runs in a daemon thread. contribute() reads from a
thread-safe cache in <1ms (FAST tier).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

import numpy as np

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

try:
    import pyaudio
except ImportError:
    pyaudio = None  # type: ignore[assignment]

# ── DSP constants ─────────────────────────────────────────────────────────────

_FFT_SIZE = 512
_SAMPLE_RATE = 16000  # Perception DSP rate. Recorder service uses 48kHz for archival quality.
_FRAME_SAMPLES = _FFT_SIZE
_FRAME_BYTES = _FRAME_SAMPLES * 2  # int16

_RMS_SMOOTHING = 0.3  # exponential smoothing alpha
_ONSET_THRESHOLD = 0.157  # calibrated 2026-03-25 (midpoint silence p95 / typing mean)
_ONSET_MIN_INTERVAL_S = 0.08  # 80ms minimum between onsets
_GESTURE_WINDOW_S = 0.5  # max time window for gesture classification
_GESTURE_TIMEOUT_S = 0.3  # wait after last onset before classifying
_DOUBLE_TAP_MIN_IOI = 0.08  # min inter-onset interval for double tap
_DOUBLE_TAP_MAX_IOI = 0.25  # max inter-onset interval for double tap

_IDLE_THRESHOLD = 0.116  # calibrated 2026-03-25 (2x silence p95)
_TYPING_MIN_ONSET_RATE = 1.0  # calibrated (60% of observed 1.6/sec)
_TAPPING_MIN_ONSET_RATE = 1.6  # calibrated (60% of observed 2.7/sec)
_DRUMMING_MIN_ENERGY = 0.4  # calibrated (between tapping mean 0.33 and drumming mean 0.54)
_DRUMMING_MAX_CENTROID = 219.0  # calibrated (1.5x drumming centroid mean 146 Hz)

# Scratch detection via autocorrelation disabled — camera is primary detector.
# See vision.py cross-modal fusion: turntable zone + non-idle energy = scratching.
_SCRATCH_AUTOCORR_THRESHOLD = 0.9  # effectively disabled
_SCRATCH_MIN_ENERGY = 0.03  # calibrated (50% of scratch RMS mean 0.058)
_SCRATCH_MIN_LAG = 2  # ~64ms at 32ms frames (~16 Hz)
_SCRATCH_MAX_LAG = 16  # ~512ms at 32ms frames (~2 Hz)
_ENERGY_BUFFER_SIZE = 60  # ~1.9s of history at 32ms frames


# ── Pure DSP functions ────────────────────────────────────────────────────────


def _compute_rms(frame: bytes) -> float:
    """RMS energy of a PCM int16 frame, normalized to 0.0-1.0."""
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples**2)))


def _compute_spectral_centroid(frame: bytes) -> float:
    """Spectral centroid in Hz from a PCM int16 frame."""
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) < _FFT_SIZE:
        return 0.0
    window = np.hanning(_FFT_SIZE)
    spec = np.abs(np.fft.rfft(samples[:_FFT_SIZE] * window))
    total = spec.sum()
    if total < 1e-10:
        return 0.0
    freqs = np.fft.rfftfreq(_FFT_SIZE, d=1.0 / _SAMPLE_RATE)
    return float(np.sum(freqs * spec) / total)


def _detect_onsets(
    frames: list[bytes],
    threshold: float = _ONSET_THRESHOLD,
    min_interval_frames: int = 3,
) -> list[int]:
    """Detect onset frame indices from a list of PCM frames."""
    onsets: list[int] = []
    prev_energy = 0.0
    last_onset = -min_interval_frames - 1

    for i, frame in enumerate(frames):
        energy = _compute_rms(frame)
        if (
            energy > threshold
            and prev_energy <= threshold
            and (i - last_onset) >= min_interval_frames
        ):
            onsets.append(i)
            last_onset = i
        prev_energy = energy

    return onsets


def _compute_envelope_autocorrelation(energy_buffer: deque[float]) -> float:
    """Compute peak normalized autocorrelation of energy envelope in scratch lag range.

    Returns the maximum normalized autocorrelation value for lags corresponding
    to 2-16 Hz oscillation (the vinyl scratch gesture rate range).
    """
    if len(energy_buffer) < _SCRATCH_MAX_LAG + 1:
        return 0.0

    arr = np.array(energy_buffer, dtype=np.float32)
    arr = arr - arr.mean()
    norm = np.dot(arr, arr)
    if norm < 1e-10:
        return 0.0

    peak = 0.0
    for lag in range(_SCRATCH_MIN_LAG, _SCRATCH_MAX_LAG + 1):
        corr = np.dot(arr[:-lag], arr[lag:]) / norm
        if corr > peak:
            peak = corr
    return float(peak)


def _classify_activity(
    energy: float, onset_rate: float, centroid: float, autocorr_peak: float = 0.0
) -> str:
    """Classify desk activity from DSP metrics.

    Scratching is NOT classified here — its audio signature overlaps with
    typing (autocorr 0.289 vs 0.471). Scratching detection uses cross-modal
    fusion in vision.py (turntable zone + non-idle energy).
    """
    if energy < _IDLE_THRESHOLD:
        return "idle"
    if energy >= _DRUMMING_MIN_ENERGY and centroid < _DRUMMING_MAX_CENTROID:
        return "drumming"
    if onset_rate >= _TAPPING_MIN_ONSET_RATE:
        return "tapping"
    if onset_rate >= _TYPING_MIN_ONSET_RATE:
        return "typing"
    return "active"


def _classify_gesture(onset_times: list[float]) -> str:
    """Classify a burst of onset timestamps into a gesture.

    Args:
        onset_times: Monotonic timestamps of onsets within gesture window.

    Returns:
        "none", "double_tap", or "triple_tap"
    """
    n = len(onset_times)
    if n < 2:
        return "none"

    if n == 2:
        ioi = onset_times[1] - onset_times[0]
        if _DOUBLE_TAP_MIN_IOI <= ioi <= _DOUBLE_TAP_MAX_IOI:
            return "double_tap"
        return "none"

    if n >= 3:
        first_three = onset_times[:3]
        span = first_three[-1] - first_three[0]
        ioi_01 = first_three[1] - first_three[0]
        ioi_12 = first_three[2] - first_three[1]
        if (
            span <= _GESTURE_WINDOW_S
            and ioi_01 >= _DOUBLE_TAP_MIN_IOI
            and ioi_12 >= _DOUBLE_TAP_MIN_IOI
        ):
            return "triple_tap"

    return "none"


# ── Thread-safe cache ─────────────────────────────────────────────────────────


class _ContactMicCache:
    """Thread-safe cache for contact mic DSP results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._desk_activity: str = "idle"
        self._desk_energy: float = 0.0
        self._desk_onset_rate: float = 0.0
        self._desk_tap_gesture: str = "none"
        self._desk_spectral_centroid: float = 0.0
        self._desk_autocorr_peak: float = 0.0
        self._updated_at: float = 0.0

    def update(
        self,
        *,
        desk_activity: str,
        desk_energy: float,
        desk_onset_rate: float,
        desk_tap_gesture: str,
        desk_spectral_centroid: float = 0.0,
        desk_autocorr_peak: float = 0.0,
    ) -> None:
        with self._lock:
            self._desk_activity = desk_activity
            self._desk_energy = desk_energy
            self._desk_onset_rate = desk_onset_rate
            self._desk_tap_gesture = desk_tap_gesture
            self._desk_spectral_centroid = desk_spectral_centroid
            self._desk_autocorr_peak = desk_autocorr_peak
            self._updated_at = time.monotonic()

    def read(self) -> dict[str, str | float]:
        with self._lock:
            return {
                "desk_activity": self._desk_activity,
                "desk_energy": self._desk_energy,
                "desk_onset_rate": self._desk_onset_rate,
                "desk_tap_gesture": self._desk_tap_gesture,
                "desk_spectral_centroid": self._desk_spectral_centroid,
                "desk_autocorr_peak": self._desk_autocorr_peak,
                "updated_at": self._updated_at,
            }


# ── Backend ───────────────────────────────────────────────────────────────────


class ContactMicBackend:
    """FAST-tier perception backend for contact microphone desk sensing.

    A daemon thread captures audio from the contact mic PipeWire source
    and computes RMS energy, onset rate, activity classification, and
    tap gesture detection. contribute() reads the cache in <1ms.

    Device matching uses PyAudio device name substring matching against
    PipeWire's node.description (not node.name).
    """

    def __init__(self, source_name: str = "Contact Microphone") -> None:
        self._source_name = source_name
        self._cache = _ContactMicCache()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream: object | None = None  # pyaudio.Stream (optional dep)

        # Behaviors (created once, updated in contribute)
        self._b_activity: Behavior[str] = Behavior("idle")
        self._b_energy: Behavior[float] = Behavior(0.0)
        self._b_onset_rate: Behavior[float] = Behavior(0.0)
        self._b_gesture: Behavior[str] = Behavior("none")
        self._b_spectral_centroid: Behavior[float] = Behavior(0.0)
        self._b_autocorr_peak: Behavior[float] = Behavior(0.0)

    @property
    def name(self) -> str:
        return "contact_mic"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset(
            {
                "desk_activity",
                "desk_energy",
                "desk_onset_rate",
                "desk_tap_gesture",
                "desk_spectral_centroid",
                "desk_autocorr_peak",
            }
        )

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        """Check if the contact mic PipeWire source exists."""
        if pyaudio is None:
            return False
        try:
            import subprocess

            result = subprocess.run(
                ["pw-cli", "ls", "Node"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return self._source_name in result.stdout
        except Exception:
            return False

    def start(self) -> None:
        if pyaudio is None:
            log.info("ContactMicBackend: pyaudio not available")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="contact-mic-capture",
        )
        self._thread.start()
        log.info("ContactMicBackend started (source=%s)", self._source_name)

    def stop(self) -> None:
        self._stop_event.set()
        # Close stream directly to unblock any pending read()
        stream = self._stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        log.info("ContactMicBackend stopped")

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        data = self._cache.read()

        self._b_activity.update(data["desk_activity"], now)
        self._b_energy.update(float(data["desk_energy"]), now)
        self._b_onset_rate.update(float(data["desk_onset_rate"]), now)
        self._b_gesture.update(data["desk_tap_gesture"], now)
        self._b_spectral_centroid.update(float(data["desk_spectral_centroid"]), now)
        self._b_autocorr_peak.update(float(data["desk_autocorr_peak"]), now)

        behaviors["desk_activity"] = self._b_activity
        behaviors["desk_energy"] = self._b_energy
        behaviors["desk_onset_rate"] = self._b_onset_rate
        behaviors["desk_tap_gesture"] = self._b_gesture
        behaviors["desk_spectral_centroid"] = self._b_spectral_centroid
        behaviors["desk_autocorr_peak"] = self._b_autocorr_peak

    def _capture_loop(self) -> None:
        """Background thread: capture audio, compute DSP, update cache.

        Uses pactl to set the PipeWire default source to the contact mic
        node, then opens the default PyAudio device. PyAudio cannot see
        PipeWire virtual sources by name — only the default source works.
        """
        try:
            import subprocess

            # Set contact_mic as the default PipeWire source for this capture
            try:
                subprocess.run(
                    ["pactl", "set-default-source", "contact_mic"],
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                log.warning("Failed to set contact_mic as default source")

            pa = pyaudio.PyAudio()

            # Use default device (now routed to contact_mic via PipeWire)
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=_SAMPLE_RATE,
                input=True,
                frames_per_buffer=_FRAME_SAMPLES,
            )
            self._stream = stream

            log.info("Contact mic capturing from device %d", device_idx)

            # State for onset detection and gesture classification
            smoothed_energy = 0.0
            prev_energy = 0.0
            onset_times: deque[float] = deque(maxlen=20)
            gesture_onset_burst: list[float] = []
            last_onset_time = 0.0
            last_gesture_check = time.monotonic()
            frame_count = 0
            centroid = 0.0
            current_gesture = "none"
            energy_buffer: deque[float] = deque(maxlen=_ENERGY_BUFFER_SIZE)
            autocorr_peak = 0.0

            while not self._stop_event.is_set():
                try:
                    data = stream.read(_FRAME_SAMPLES, exception_on_overflow=False)
                    now = time.monotonic()
                    frame_count += 1

                    # RMS energy with exponential smoothing
                    raw_energy = _compute_rms(data)
                    smoothed_energy = (
                        _RMS_SMOOTHING * raw_energy + (1 - _RMS_SMOOTHING) * smoothed_energy
                    )

                    energy_buffer.append(smoothed_energy)

                    # Onset detection
                    if (
                        raw_energy > _ONSET_THRESHOLD
                        and prev_energy <= _ONSET_THRESHOLD
                        and (now - last_onset_time) >= _ONSET_MIN_INTERVAL_S
                    ):
                        # New onset arriving after a classified gesture resets it
                        if current_gesture != "none":
                            current_gesture = "none"
                        onset_times.append(now)
                        gesture_onset_burst.append(now)
                        last_onset_time = now
                        last_gesture_check = now

                    prev_energy = raw_energy

                    # Onset rate: count onsets in last 1 second
                    cutoff = now - 1.0
                    recent_onsets = [t for t in onset_times if t > cutoff]
                    onset_rate = float(len(recent_onsets))

                    # Spectral centroid (every 4th frame to save CPU)
                    # centroid persists from last computation on non-FFT frames
                    if frame_count % 4 == 0:
                        centroid = _compute_spectral_centroid(data)
                        autocorr_peak = _compute_envelope_autocorrelation(energy_buffer)

                    # Activity classification
                    activity = _classify_activity(
                        smoothed_energy, onset_rate, centroid, autocorr_peak
                    )

                    # Gesture classification (after timeout)
                    if gesture_onset_burst and (now - last_gesture_check) >= _GESTURE_TIMEOUT_S:
                        current_gesture = _classify_gesture(gesture_onset_burst)
                        gesture_onset_burst.clear()
                        last_gesture_check = time.monotonic()

                    # Auto-expire gesture if no new onset within 3× timeout
                    if (
                        current_gesture != "none"
                        and (now - last_gesture_check) >= _GESTURE_TIMEOUT_S * 3
                    ):
                        current_gesture = "none"

                    self._cache.update(
                        desk_activity=activity,
                        desk_energy=smoothed_energy,
                        desk_onset_rate=onset_rate,
                        desk_tap_gesture=current_gesture,
                        desk_spectral_centroid=centroid,
                        desk_autocorr_peak=autocorr_peak,
                    )

                except Exception:
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.1)

            self._stream = None
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            pa.terminate()

        except Exception:
            log.debug("Contact mic capture failed", exc_info=True)
