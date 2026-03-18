"""Multi-microphone noise reference subtraction.

Uses C920 webcam mics as ambient noise reference channels. The Yeti
captures operator voice + room noise. The C920s capture mostly room
noise (they're farther from the operator). Subtracting the C920 signal
from the Yeti reduces echo, ambient, and speaker bleed-through.

This is spectral subtraction, not beamforming — no array geometry
needed. Works with arbitrary mic placement.

Usage:
    ref = NoiseReference(room_sources=["alsa_input.usb-046d_HD_Pro_Webcam_C920_86B6B75F-02.analog-stereo"])
    ref.start()
    # ... in audio loop:
    cleaned = ref.subtract(yeti_frame)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

import numpy as np

log = logging.getLogger(__name__)

# Spectral subtraction parameters
_FFT_SIZE = 512
_HOP_SIZE = 256
_ALPHA = 1.5  # oversubtraction factor (>1 = more aggressive noise removal)
_BETA = 0.01  # spectral floor (prevents musical noise artifacts)
_SMOOTHING = 0.7  # noise estimate smoothing (0=no smoothing, 1=never update)


class NoiseReference:
    """Captures room noise from reference mics and subtracts from primary mic.

    The reference signal estimates what the room sounds like WITHOUT the
    operator's voice. Spectral subtraction removes this estimate from the
    Yeti signal, leaving mostly the operator's voice.
    """

    def __init__(
        self,
        room_sources: list[str] | None = None,
        sample_rate: int = 16000,
    ) -> None:
        self._room_sources = room_sources or []
        self._sample_rate = sample_rate
        self._running = False
        self._threads: list[threading.Thread] = []

        # Noise estimate (magnitude spectrum, updated continuously from reference mics)
        self._noise_estimate: np.ndarray | None = None
        self._lock = threading.Lock()

        # Ring buffer of recent reference frames for averaging
        self._ref_frames: deque[np.ndarray] = deque(maxlen=20)  # ~600ms at 30ms/frame

    def start(self) -> None:
        """Start capturing from reference microphones."""
        if not self._room_sources:
            log.info("No room reference sources configured — noise subtraction disabled")
            return

        self._running = True
        for source in self._room_sources:
            t = threading.Thread(
                target=self._capture_loop,
                args=(source,),
                daemon=True,
                name=f"noise-ref-{source[:20]}",
            )
            t.start()
            self._threads.append(t)
        log.info("Noise reference started with %d room source(s)", len(self._room_sources))

    def stop(self) -> None:
        self._running = False
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()

    def subtract(self, frame: bytes) -> bytes:
        """Apply spectral subtraction to a primary mic frame.

        Args:
            frame: Raw PCM int16 mono audio frame from the Yeti.

        Returns:
            Cleaned PCM int16 mono audio frame.
        """
        if self._noise_estimate is None:
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

        # Subtract noise estimate
        with self._lock:
            noise_mag = self._noise_estimate

        # Ensure same size
        if noise_mag is not None and len(noise_mag) == len(mag):
            clean_mag = np.maximum(mag - _ALPHA * noise_mag, _BETA * mag)
        else:
            clean_mag = mag

        # Reconstruct
        clean_spec = clean_mag * np.exp(1j * phase)
        clean_samples = np.fft.irfft(clean_spec)[: len(samples)]

        # Convert back to int16
        clean_int16 = np.clip(clean_samples, -32768, 32767).astype(np.int16)
        return clean_int16.tobytes()

    def _capture_loop(self, source: str) -> None:
        """Continuously capture from a reference mic and update noise estimate."""
        try:
            import pyaudio

            pa = pyaudio.PyAudio()

            # Find the device index for this source
            device_idx = None
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if source in str(info.get("name", "")):
                    device_idx = i
                    break

            if device_idx is None:
                log.warning("Noise reference source not found: %s", source)
                pa.terminate()
                return

            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self._sample_rate,
                input=True,
                input_device_index=device_idx,
                frames_per_buffer=_FFT_SIZE,
            )

            log.info("Noise reference capturing from: %s (device %d)", source, device_idx)

            while self._running:
                try:
                    data = stream.read(_FFT_SIZE, exception_on_overflow=False)
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)

                    # Compute magnitude spectrum
                    window = np.hanning(_FFT_SIZE)
                    spec = np.fft.rfft(samples * window)
                    mag = np.abs(spec)

                    # Update noise estimate with exponential smoothing
                    with self._lock:
                        if self._noise_estimate is None:
                            self._noise_estimate = mag
                        else:
                            self._noise_estimate = (
                                _SMOOTHING * self._noise_estimate + (1 - _SMOOTHING) * mag
                            )

                except Exception:
                    time.sleep(0.1)

            stream.stop_stream()
            stream.close()
            pa.terminate()

        except Exception:
            log.debug("Noise reference capture failed for %s", source, exc_info=True)
