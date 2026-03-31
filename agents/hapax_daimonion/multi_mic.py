"""Multi-microphone noise reference subtraction.

Uses C920 webcam mics as ambient noise reference channels. The Yeti
captures operator voice + room noise. The C920s capture mostly room
noise (they're farther from the operator). Subtracting the C920 signal
from the Yeti reduces echo, ambient, and speaker bleed-through.

Optionally uses a contact microphone (e.g. Cortado MkII) for
structure-borne noise reference — desk vibrations, keyboard impacts,
mechanical rumble. Structure-borne subtraction runs first (alpha=1.0,
conservative) then airborne subtraction (alpha=1.5, aggressive).

This is spectral subtraction, not beamforming — no array geometry
needed. Works with arbitrary mic placement.

Capture uses pw-record (PipeWire) instead of PyAudio. Each reference
source gets its own pw-record subprocess. Multiple room sources are
averaged for a more robust noise estimate.

Usage:
    sources = discover_pipewire_sources(["C920"])
    ref = NoiseReference(
        room_sources=sources,
        structure_sources=["Contact Microphone"],
    )
    ref.start()
    # ... in audio loop:
    cleaned = ref.subtract(yeti_frame)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

# Spectral subtraction parameters
_FFT_SIZE = 512
_HOP_SIZE = 256
_SMOOTHING = 0.7  # noise estimate smoothing (0=no smoothing, 1=never update)

# Airborne subtraction (room mics — aggressive, removes ambient + echo)
_AIRBORNE_ALPHA = 1.5  # oversubtraction factor
_AIRBORNE_BETA = 0.01  # spectral floor

# Structure-borne subtraction (contact mic — conservative, removes desk/keyboard rumble)
_STRUCTURE_ALPHA = 1.0  # less aggressive (contact mic signal is already clean)
_STRUCTURE_BETA = 0.02  # slightly higher floor (preserve transient detail)


def discover_pipewire_sources(
    patterns: list[str],
    *,
    _pactl_output: str | None = None,
) -> list[str]:
    """Discover PipeWire sources matching name patterns.

    Runs ``pactl list sources short`` and returns full source names whose
    name column contains any of the given substrings.

    Args:
        patterns: Substrings to match against source names.
        _pactl_output: Override pactl output for testing.

    Returns:
        List of full PipeWire source names.
    """
    if _pactl_output is None:
        try:
            result = subprocess.run(
                ["pactl", "list", "sources", "short"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            _pactl_output = result.stdout
        except Exception:
            log.warning("Failed to list PipeWire sources via pactl")
            return []

    matched: list[str] = []
    for line in _pactl_output.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        source_name = parts[1]
        for pattern in patterns:
            if pattern in source_name:
                matched.append(source_name)
                break
    return matched


class NoiseReference:
    """Captures room noise from reference mics and subtracts from primary mic.

    The reference signal estimates what the room sounds like WITHOUT the
    operator's voice. Spectral subtraction removes this estimate from the
    Yeti signal, leaving mostly the operator's voice.

    Multiple room sources are averaged for a more robust noise estimate.
    """

    def __init__(
        self,
        room_sources: list[str] | None = None,
        structure_sources: list[str] | None = None,
        sample_rate: int = 16000,
    ) -> None:
        self._room_sources = room_sources or []
        self._structure_sources = structure_sources or []
        self._sample_rate = sample_rate
        self._running = False
        self._threads: list[threading.Thread] = []
        self._processes: list[subprocess.Popen] = []  # type: ignore[type-arg]

        # Per-source room noise estimates (averaged for subtraction)
        self._room_estimates: dict[str, np.ndarray] = {}
        self._room_lock = threading.Lock()

        # Structure-borne noise estimate (contact mic)
        self._structure_noise_estimate: np.ndarray | None = None
        self._structure_lock = threading.Lock()

    def _averaged_room_estimate(self) -> np.ndarray | None:
        """Average all room noise estimates into a single spectrum.

        Returns None if no estimates are available.
        """
        with self._room_lock:
            estimates = list(self._room_estimates.values())
        if not estimates:
            return None
        return np.mean(estimates, axis=0)

    def start(self) -> None:
        """Start capturing from reference microphones via pw-record."""
        if not self._room_sources and not self._structure_sources:
            log.info("No reference sources configured — noise subtraction disabled")
            return

        if shutil.which("pw-record") is None:
            log.warning("pw-record not found — noise subtraction disabled")
            return

        self._running = True
        for source in self._room_sources:
            t = threading.Thread(
                target=self._capture_loop,
                args=(source,),
                kwargs={"is_structure": False},
                daemon=True,
                name=f"noise-ref-{source[:20]}",
            )
            t.start()
            self._threads.append(t)
        for source in self._structure_sources:
            t = threading.Thread(
                target=self._capture_loop,
                args=(source,),
                kwargs={"is_structure": True},
                daemon=True,
                name=f"struct-ref-{source[:20]}",
            )
            t.start()
            self._threads.append(t)
        log.info(
            "Noise reference started with %d room + %d structure source(s)",
            len(self._room_sources),
            len(self._structure_sources),
        )

    def stop(self) -> None:
        """Stop all capture threads and terminate pw-record processes."""
        self._running = False
        for proc in self._processes:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._processes.clear()
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()

    @staticmethod
    def _apply_subtraction(
        mag: np.ndarray,
        noise_mag: np.ndarray | None,
        alpha: float,
        beta: float,
    ) -> np.ndarray:
        """Spectral subtraction: mag - alpha*noise, floored at beta*mag."""
        if noise_mag is not None and len(noise_mag) == len(mag):
            return np.maximum(mag - alpha * noise_mag, beta * mag)
        return mag

    def subtract(self, frame: bytes) -> bytes:
        """Apply spectral subtraction to a primary mic frame.

        Structure-borne subtraction runs first (conservative), then airborne
        subtraction (aggressive). This order prevents structure rumble from
        being misattributed to airborne noise.

        Args:
            frame: Raw PCM int16 mono audio frame from the Yeti.

        Returns:
            Cleaned PCM int16 mono audio frame.
        """
        room_est = self._averaged_room_estimate()
        if room_est is None and self._structure_noise_estimate is None:
            return frame  # no reference data yet — pass through

        # Convert to float
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        if len(samples) < _FFT_SIZE:
            return frame

        # STFT of input
        window = np.hanning(_FFT_SIZE)
        spec = np.fft.rfft(samples[:_FFT_SIZE] * window)
        mag = np.abs(spec)
        phase = np.angle(spec)

        # 1. Structure-borne subtraction (contact mic — conservative)
        with self._structure_lock:
            structure_mag = self._structure_noise_estimate
        mag = self._apply_subtraction(mag, structure_mag, _STRUCTURE_ALPHA, _STRUCTURE_BETA)

        # 2. Airborne subtraction (room mics — aggressive, using averaged estimate)
        mag = self._apply_subtraction(mag, room_est, _AIRBORNE_ALPHA, _AIRBORNE_BETA)

        # Reconstruct
        clean_spec = mag * np.exp(1j * phase)
        clean_samples = np.fft.irfft(clean_spec)[: len(samples)]

        # Convert back to int16
        clean_int16 = np.clip(clean_samples, -32768, 32767).astype(np.int16)
        return clean_int16.tobytes()

    def _capture_loop(self, source: str, *, is_structure: bool = False) -> None:
        """Continuously capture from a reference mic via pw-record.

        Spawns ``pw-record --target <source> --format s16 --rate 16000
        --channels 1 -`` and reads raw PCM from stdout. On process death,
        logs a warning, sleeps 2s, and restarts.

        Args:
            source: PipeWire source name to capture from.
            is_structure: If True, updates structure-borne estimate instead of airborne.
        """
        kind = "structure" if is_structure else "room"
        chunk_bytes = _FFT_SIZE * 2  # int16 = 2 bytes per sample
        retry_count = 0

        while self._running:
            proc: subprocess.Popen | None = None  # type: ignore[type-arg]
            try:
                proc = subprocess.Popen(
                    [
                        "pw-record",
                        "--target",
                        source,
                        "--format",
                        "s16",
                        "--rate",
                        str(self._sample_rate),
                        "--channels",
                        "1",
                        "-",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._processes.append(proc)
                retry_count = 0
                log.info("Noise reference capturing from %s source: %s", kind, source)

                while self._running and proc.poll() is None:
                    assert proc.stdout is not None
                    data = proc.stdout.read(chunk_bytes)
                    if len(data) < chunk_bytes:
                        break

                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    window = np.hanning(_FFT_SIZE)
                    spec = np.fft.rfft(samples * window)
                    mag = np.abs(spec)

                    if is_structure:
                        with self._structure_lock:
                            if self._structure_noise_estimate is None:
                                self._structure_noise_estimate = mag
                            else:
                                self._structure_noise_estimate = (
                                    _SMOOTHING * self._structure_noise_estimate
                                    + (1 - _SMOOTHING) * mag
                                )
                    else:
                        with self._room_lock:
                            if source not in self._room_estimates:
                                self._room_estimates[source] = mag
                            else:
                                self._room_estimates[source] = (
                                    _SMOOTHING * self._room_estimates[source]
                                    + (1 - _SMOOTHING) * mag
                                )

            except Exception:
                log.debug("Noise reference capture failed for %s (%s)", source, kind, exc_info=True)
            finally:
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        pass
                    if proc in self._processes:
                        self._processes.remove(proc)

            if self._running:
                backoff = min(30, 2 ** min(retry_count, 4))
                retry_count += 1
                log.warning(
                    "pw-record died for %s source %s — restarting in %ds (attempt %d)",
                    kind,
                    source,
                    backoff,
                    retry_count,
                )
                time.sleep(backoff)
