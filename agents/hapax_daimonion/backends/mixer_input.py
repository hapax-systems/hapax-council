"""Mixer master perception backend.

Captures audio from the mixer_master PipeWire virtual source via pw-record
subprocess pipe. Computes per-frame DSP (energy, beat, 3-band spectral split)
and writes to a thread-safe cache. contribute() reads cache in <1ms (FAST tier).

Uses pw-record --target to avoid the pactl default-source race condition
that affects PyAudio-based backends.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time

import numpy as np

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

# ── DSP constants ─────────────────────────────────────────────────────────────

_SAMPLE_RATE = 48000
_FRAME_SAMPLES = 1024  # 21.3ms per frame, ~47 fps
_FRAME_BYTES = _FRAME_SAMPLES * 2  # int16 = 2 bytes per sample
_FFT_SIZE = _FRAME_SAMPLES

_RMS_SMOOTHING = 0.3  # exponential smoothing alpha
_BEAT_BASELINE_ALPHA = 0.02  # slow baseline tracking for beat detection
_BEAT_SPIKE_RATIO = 2.0  # RMS must exceed baseline × this to trigger beat
_BEAT_DECAY = 0.85  # per-frame decay for beat pulse (~200ms release)
_ACTIVITY_THRESHOLD = 0.005  # smoothed RMS above this = mixer_active
_BAND_PEAK_DECAY = 0.999  # slow decay for band normalization peaks

# Frequency band edges (Hz)
_BASS_UPPER = 250.0
_MID_UPPER = 2000.0
_HIGH_UPPER = 8000.0


# ── Pure DSP functions ────────────────────────────────────────────────────────


def _compute_rms(frame: bytes) -> float:
    """RMS energy of a PCM int16 frame, normalized to 0.0-1.0."""
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples**2)))


def _compute_three_band_split(frame: bytes) -> tuple[float, float, float]:
    """Compute bass/mid/high band energies from a PCM int16 frame.

    Returns raw (unnormalized) band magnitudes. Normalization is done
    in the capture loop using peak tracking.
    """
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) < _FFT_SIZE:
        return 0.0, 0.0, 0.0

    window = np.hanning(_FFT_SIZE)
    spec = np.abs(np.fft.rfft(samples[:_FFT_SIZE] * window))
    freqs = np.fft.rfftfreq(_FFT_SIZE, d=1.0 / _SAMPLE_RATE)

    bass_mask = freqs < _BASS_UPPER
    mid_mask = (freqs >= _BASS_UPPER) & (freqs < _MID_UPPER)
    high_mask = (freqs >= _MID_UPPER) & (freqs < _HIGH_UPPER)

    bass = float(np.sum(spec[bass_mask]))
    mid = float(np.sum(spec[mid_mask]))
    high = float(np.sum(spec[high_mask]))

    return bass, mid, high


def _detect_beat(rms: float, baseline: float, beat_val: float) -> tuple[float, float]:
    """Update beat detection state.

    Args:
        rms: Current frame RMS energy.
        baseline: Slow-tracking baseline energy.
        beat_val: Current beat pulse value.

    Returns:
        (updated_baseline, updated_beat_val)
    """
    # Update baseline with slow exponential smoothing
    baseline = _BEAT_BASELINE_ALPHA * rms + (1 - _BEAT_BASELINE_ALPHA) * baseline

    # Check for spike
    if rms > baseline * _BEAT_SPIKE_RATIO and baseline > 1e-6:
        beat_val = 1.0
    else:
        beat_val *= _BEAT_DECAY

    return baseline, beat_val


# ── Thread-safe cache ─────────────────────────────────────────────────────────


class _MixerCache:
    """Thread-safe cache for mixer DSP results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mixer_energy: float = 0.0
        self._mixer_beat: float = 0.0
        self._mixer_bass: float = 0.0
        self._mixer_mid: float = 0.0
        self._mixer_high: float = 0.0
        self._mixer_active: bool = False
        self._updated_at: float = 0.0

    def update(
        self,
        *,
        mixer_energy: float,
        mixer_beat: float,
        mixer_bass: float,
        mixer_mid: float,
        mixer_high: float,
        mixer_active: bool,
    ) -> None:
        with self._lock:
            self._mixer_energy = mixer_energy
            self._mixer_beat = mixer_beat
            self._mixer_bass = mixer_bass
            self._mixer_mid = mixer_mid
            self._mixer_high = mixer_high
            self._mixer_active = mixer_active
            self._updated_at = time.monotonic()

    def read(self) -> dict[str, float | bool]:
        with self._lock:
            return {
                "mixer_energy": self._mixer_energy,
                "mixer_beat": self._mixer_beat,
                "mixer_bass": self._mixer_bass,
                "mixer_mid": self._mixer_mid,
                "mixer_high": self._mixer_high,
                "mixer_active": self._mixer_active,
                "updated_at": self._updated_at,
            }


# ── Backend ───────────────────────────────────────────────────────────────────


class MixerInputBackend:
    """FAST-tier perception backend for mixer master audio analysis.

    Captures audio from the mixer_master PipeWire virtual source via
    pw-record subprocess pipe. Computes RMS energy, beat detection,
    3-band spectral split, and activity state. contribute() reads
    the cache in <1ms.
    """

    def __init__(self) -> None:
        self._cache = _MixerCache()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None

        # Behaviors (created once, updated in contribute)
        self._b_energy: Behavior[float] = Behavior(0.0)
        self._b_beat: Behavior[float] = Behavior(0.0)
        self._b_bass: Behavior[float] = Behavior(0.0)
        self._b_mid: Behavior[float] = Behavior(0.0)
        self._b_high: Behavior[float] = Behavior(0.0)
        self._b_active: Behavior[bool] = Behavior(False)

    @property
    def name(self) -> str:
        return "mixer_input"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset(
            {
                "mixer_energy",
                "mixer_beat",
                "mixer_bass",
                "mixer_mid",
                "mixer_high",
                "mixer_active",
            }
        )

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        """Check if pw-record exists and mixer_master node is present."""
        if shutil.which("pw-record") is None:
            return False
        try:
            result = subprocess.run(
                ["pw-cli", "ls", "Node"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "mixer_master" in result.stdout
        except Exception:
            return False

    def start(self) -> None:
        """Launch pw-record subprocess and capture daemon thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="mixer-input-capture",
        )
        self._thread.start()
        log.info("MixerInputBackend started")

    def stop(self) -> None:
        """Terminate subprocess and join thread."""
        self._stop_event.set()
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        log.info("MixerInputBackend stopped")

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Read cache and update Behavior objects."""
        now = time.monotonic()
        data = self._cache.read()

        prev_active = self._b_active.value
        self._b_energy.update(float(data["mixer_energy"]), now)
        self._b_beat.update(float(data["mixer_beat"]), now)
        self._b_bass.update(float(data["mixer_bass"]), now)
        self._b_mid.update(float(data["mixer_mid"]), now)
        self._b_high.update(float(data["mixer_high"]), now)
        self._b_active.update(bool(data["mixer_active"]), now)

        behaviors["mixer_energy"] = self._b_energy
        behaviors["mixer_beat"] = self._b_beat
        behaviors["mixer_bass"] = self._b_bass
        behaviors["mixer_mid"] = self._b_mid
        behaviors["mixer_high"] = self._b_high
        behaviors["mixer_active"] = self._b_active

        new_active = self._b_active.value
        if new_active != prev_active:
            try:
                from shared.bayesian_impingement_emitter import (
                    emit_state_transition_impingement,
                )

                emit_state_transition_impingement(
                    source="audio.mixer_input",
                    claim_name="mixer-active",
                    from_state="ACTIVE" if prev_active else "INACTIVE",
                    to_state="ACTIVE" if new_active else "INACTIVE",
                    posterior=float(data["mixer_energy"]),
                    prev_posterior=None,
                    active_signals={"energy": data["mixer_energy"]},
                )
            except Exception:
                pass

    def _capture_loop(self) -> None:
        """Background thread: capture audio via pw-record, compute DSP, update cache."""
        try:
            proc = subprocess.Popen(
                [
                    "pw-record",
                    "--target",
                    "mixer_master",
                    "--format",
                    "s16",
                    "--rate",
                    str(_SAMPLE_RATE),
                    "--channels",
                    "1",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._proc = proc
            log.info("pw-record subprocess started (pid=%d)", proc.pid)

            # DSP state
            smoothed_energy = 0.0
            beat_baseline = 0.01
            beat_val = 0.0
            bass_peak = 1e-6
            mid_peak = 1e-6
            high_peak = 1e-6

            while not self._stop_event.is_set():
                try:
                    data = proc.stdout.read(_FRAME_BYTES)  # type: ignore[union-attr]
                    if not data or len(data) < _FRAME_BYTES:
                        if self._stop_event.is_set():
                            break
                        time.sleep(0.01)
                        continue

                    # RMS with exponential smoothing
                    raw_rms = _compute_rms(data)
                    smoothed_energy = (
                        _RMS_SMOOTHING * raw_rms + (1 - _RMS_SMOOTHING) * smoothed_energy
                    )

                    # Beat detection
                    beat_baseline, beat_val = _detect_beat(raw_rms, beat_baseline, beat_val)

                    # 3-band spectral split
                    raw_bass, raw_mid, raw_high = _compute_three_band_split(data)

                    # Normalize bands by tracking peak with slow decay
                    bass_peak = max(raw_bass, bass_peak * _BAND_PEAK_DECAY)
                    mid_peak = max(raw_mid, mid_peak * _BAND_PEAK_DECAY)
                    high_peak = max(raw_high, high_peak * _BAND_PEAK_DECAY)

                    norm_bass = raw_bass / bass_peak if bass_peak > 1e-6 else 0.0
                    norm_mid = raw_mid / mid_peak if mid_peak > 1e-6 else 0.0
                    norm_high = raw_high / high_peak if high_peak > 1e-6 else 0.0

                    # Clamp to 0-1
                    norm_bass = min(1.0, max(0.0, norm_bass))
                    norm_mid = min(1.0, max(0.0, norm_mid))
                    norm_high = min(1.0, max(0.0, norm_high))

                    # Activity
                    active = smoothed_energy > _ACTIVITY_THRESHOLD

                    self._cache.update(
                        mixer_energy=smoothed_energy,
                        mixer_beat=beat_val,
                        mixer_bass=norm_bass,
                        mixer_mid=norm_mid,
                        mixer_high=norm_high,
                        mixer_active=active,
                    )

                except Exception:
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.1)

            self._proc = None
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                pass

        except Exception:
            log.debug("Mixer input capture failed", exc_info=True)
