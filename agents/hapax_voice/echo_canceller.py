"""Application-level acoustic echo cancellation via speexdsp (ctypes).

Replaces PipeWire's broken AEC module (ENOTSUP on 1.6.x) with a
per-frame canceller that runs inline in _audio_loop().

Usage:
    ec = EchoCanceller(frame_size=480, tail_ms=200)
    # When TTS plays audio (24kHz int16 PCM):
    ec.feed_reference(tts_pcm_bytes)
    # For each mic frame (16kHz int16 PCM, 480 samples):
    clean = ec.process(mic_frame_bytes)
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import struct
from collections import deque
from threading import Lock

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
TTS_SAMPLE_RATE = 24000


def _load_speexdsp() -> ctypes.CDLL:
    """Load libspeexdsp, raising RuntimeError if unavailable."""
    path = ctypes.util.find_library("speexdsp")
    if path is None:
        raise RuntimeError("libspeexdsp not found. Install with: pacman -S speexdsp")
    lib = ctypes.CDLL(path)

    # SpeexEchoState* speex_echo_state_init(int frame_size, int filter_length)
    lib.speex_echo_state_init.restype = ctypes.c_void_p
    lib.speex_echo_state_init.argtypes = [ctypes.c_int, ctypes.c_int]

    # void speex_echo_state_destroy(SpeexEchoState*)
    lib.speex_echo_state_destroy.restype = None
    lib.speex_echo_state_destroy.argtypes = [ctypes.c_void_p]

    # void speex_echo_cancellation(SpeexEchoState*, const int16*, const int16*, int16*)
    lib.speex_echo_cancellation.restype = None
    lib.speex_echo_cancellation.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int16),
        ctypes.POINTER(ctypes.c_int16),
        ctypes.POINTER(ctypes.c_int16),
    ]

    # int speex_echo_ctl(SpeexEchoState*, int request, void* ptr)
    lib.speex_echo_ctl.restype = ctypes.c_int
    lib.speex_echo_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]

    return lib


class EchoCanceller:
    """Wraps speexdsp echo cancellation for real-time mic processing.

    Thread-safe: feed_reference() is called from the TTS executor thread,
    process() is called from the async audio loop.
    """

    def __init__(self, frame_size: int = 480, tail_ms: int = 200) -> None:
        self._frame_size = frame_size
        self._tail_samples = int(SAMPLE_RATE * tail_ms / 1000)
        self._frame_bytes = frame_size * 2  # int16

        self._lib = _load_speexdsp()
        self._state = self._lib.speex_echo_state_init(frame_size, self._tail_samples)
        if not self._state:
            raise RuntimeError("speex_echo_state_init returned NULL")

        # Set sample rate
        rate = ctypes.c_int(SAMPLE_RATE)
        SPEEX_ECHO_SET_SAMPLING_RATE = 24  # from speex_echo.h
        self._lib.speex_echo_ctl(self._state, SPEEX_ECHO_SET_SAMPLING_RATE, ctypes.byref(rate))

        # Reference buffer: TTS frames resampled to 16kHz, consumed by process()
        self._ref_lock = Lock()
        self._ref_buf: deque[bytes] = deque(maxlen=500)  # ~15s at 30ms frames

        # Latency compensation: delay reference by N frames to account for
        # acoustic propagation from speaker to mic (~10-20ms = ~1 frame at 30ms).
        # Without this, the reference arrives at the AEC before the echo
        # arrives at the mic, causing mis-alignment.
        self._latency_frames = max(1, int(15 / 30))  # ~15ms = 1 frame at 30ms
        self._latency_buf: deque[bytes] = deque(maxlen=self._latency_frames)

        # Pre-allocate output buffer
        self._out_buf = (ctypes.c_int16 * frame_size)()

        # Diagnostics: count frames processed vs passthrough
        self._frames_processed = 0
        self._frames_passthrough = 0
        self._refs_fed = 0
        self._diag_last_log = 0.0

        log.info(
            "EchoCanceller initialized: frame=%d samples, tail=%dms (%d samples)",
            frame_size,
            tail_ms,
            self._tail_samples,
        )

    def feed_reference(self, tts_pcm: bytes) -> None:
        """Feed TTS playback audio as the reference signal.

        Called from TTS thread after audio_output.write(). Input is 24kHz int16
        PCM — resampled to 16kHz before buffering.
        """
        if not tts_pcm:
            return

        # Resample 24kHz → 16kHz via simple decimation (2:3 ratio)
        resampled = _resample_24k_to_16k(tts_pcm)

        # Split into frame-sized chunks
        with self._ref_lock:
            offset = 0
            count = 0
            while offset + self._frame_bytes <= len(resampled):
                self._ref_buf.append(resampled[offset : offset + self._frame_bytes])
                offset += self._frame_bytes
                count += 1
            self._refs_fed += count

    def process(self, mic_frame: bytes) -> bytes:
        """Process a mic frame through echo cancellation.

        Returns echo-cancelled frame (same size). If no reference is
        available, returns the mic frame unchanged (passthrough).
        """
        if len(mic_frame) != self._frame_bytes:
            return mic_frame

        # Get reference frame (or silence if none available)
        with self._ref_lock:
            raw_ref = self._ref_buf.popleft() if self._ref_buf else None

        # Latency compensation: delay reference by 1 frame (~30ms) so it
        # aligns with when the acoustic echo actually reaches the mic.
        ref = None
        if raw_ref is not None:
            self._latency_buf.append(raw_ref)
            if len(self._latency_buf) >= self._latency_frames:
                ref = self._latency_buf.popleft()

        if ref is None:
            # No echo to cancel — passthrough
            self._frames_passthrough += 1
            self._log_diag()
            return mic_frame

        # Set up ctypes pointers — guard against invalid state (SEGV risk)
        if not self._state or len(ref) != self._frame_bytes:
            self._frames_passthrough += 1
            return mic_frame

        try:
            mic_arr = (ctypes.c_int16 * self._frame_size).from_buffer_copy(mic_frame)
            ref_arr = (ctypes.c_int16 * self._frame_size).from_buffer_copy(ref)
            self._lib.speex_echo_cancellation(self._state, mic_arr, ref_arr, self._out_buf)
        except Exception:
            self._frames_passthrough += 1
            self._log_diag()
            return mic_frame

        self._frames_processed += 1
        self._log_diag()
        return bytes(self._out_buf)

    def _log_diag(self) -> None:
        """Log AEC diagnostics every 5 seconds."""
        import time

        now = time.monotonic()
        if now - self._diag_last_log >= 5.0:
            self._diag_last_log = now
            total = self._frames_processed + self._frames_passthrough
            pct = (self._frames_processed / total * 100) if total > 0 else 0
            log.info(
                "AEC diag: processed=%d passthrough=%d (%.0f%% active), refs_fed=%d, ref_buf=%d",
                self._frames_processed,
                self._frames_passthrough,
                pct,
                self._refs_fed,
                len(self._ref_buf),
            )

    def destroy(self) -> None:
        """Release the speexdsp state."""
        if self._state:
            self._lib.speex_echo_state_destroy(self._state)
            self._state = None


def _resample_24k_to_16k(pcm_24k: bytes) -> bytes:
    """Resample 24kHz int16 PCM to 16kHz via linear interpolation.

    Ratio 24000:16000 = 3:2 — for every 3 input samples, produce 2 output.
    Uses simple linear interpolation for quality without numpy dependency.
    """
    n_samples = len(pcm_24k) // 2
    if n_samples < 3:
        return b""

    samples = struct.unpack(f"<{n_samples}h", pcm_24k)
    ratio = 24000 / 16000  # 1.5
    out_len = int(n_samples / ratio)
    out = []

    for i in range(out_len):
        src_pos = i * ratio
        idx = int(src_pos)
        frac = src_pos - idx
        if idx + 1 < n_samples:
            val = samples[idx] * (1.0 - frac) + samples[idx + 1] * frac
        else:
            val = samples[min(idx, n_samples - 1)]
        out.append(max(-32768, min(32767, int(val))))

    return struct.pack(f"<{len(out)}h", *out)
