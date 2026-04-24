"""TTS envelope publisher — 100 Hz RMS/centroid/ZCR/F0/voicing SHM ring.

Taps CpalRunner's PCM playback stream, computes per-30 ms analysis
features, and writes a lock-free mmap ring of ``256 × 5`` f32s to
``/dev/shm/hapax-daimonion/tts-envelope.f32``. GEAL reads the ring
each frame to drive V1 Chladni ignition, V2 halo radius/opacity, and
future voicing-gated primitives.

Layout
------

::

    offset 0         u32 little-endian  head index (wraps at RING_SLOTS)
    offset 4         f32 × 5 × RING_SLOTS  rms / centroid / zcr / f0 / voicing

Write order
-----------

1. Fill the target slot's 5 × f32 payload with :func:`struct.pack_into`.
2. Bump the head index last with an atomic u32 write.

Consumers that observe ``head = N`` are guaranteed the slot ``N-1``
is fully written. GIL-serialised Python means the intervening payload
write is visible before the head bump is observable.

Spec: ``docs/superpowers/specs/2026-04-23-geal-spec.md`` §5.1, §10.
Plan: ``docs/superpowers/plans/2026-04-23-geal-plan.md`` Task 2.1.
"""

from __future__ import annotations

import logging
import math
import mmap
import os
import struct
from pathlib import Path

import numpy as np

__all__ = [
    "DEFAULT_ENVELOPE_PATH",
    "FIELDS_PER_SLOT",
    "RING_SLOTS",
    "TtsEnvelopePublisher",
]

log = logging.getLogger(__name__)

DEFAULT_ENVELOPE_PATH = Path("/dev/shm/hapax-daimonion/tts-envelope.f32")

RING_SLOTS = 256
FIELDS_PER_SLOT = 5  # rms, centroid, zcr, f0, voicing_prob
_HEADER_SIZE = 4  # u32 head index
_F32_BYTES = 4
_SLOT_SIZE = FIELDS_PER_SLOT * _F32_BYTES
_PAYLOAD_SIZE = RING_SLOTS * _SLOT_SIZE
_FILE_SIZE = _HEADER_SIZE + _PAYLOAD_SIZE

# Analysis window in milliseconds. Spec §5.1 prescribes 30 ms @ ~100 Hz;
# at 24 kHz sample rate that's 720 samples per window. Rounded to the
# nearest power-of-two-adjacent size keeps the windowing code simple.
_WINDOW_MS = 30.0

# F0 search bounds. Human voice spans ~80–400 Hz; GEAL's consumers
# primarily need voicing probability and a rough pitch region, so a
# narrow band is fine.
_F0_MIN_HZ = 70.0
_F0_MAX_HZ = 500.0

# YIN voicing threshold. Lower values = more confident voicing;
# 0.15 is the canonical YIN cut-off, which we use as the "voiced/not"
# boundary when converting to a [0, 1] probability.
_YIN_THRESHOLD = 0.15


class TtsEnvelopePublisher:
    """Computes per-window audio features and mmap-publishes them.

    Feed PCM (int16 bytes) via :meth:`feed` from any point in the TTS
    pipeline. The publisher accumulates an internal buffer and emits
    one ring entry per 30 ms window, dropping any partial tail (it
    will land in the next :meth:`feed` call).

    Construction allocates a ``mmap`` at the declared path, truncating
    the file to the correct size and zeroing the header + payload.
    Tests point the path at a ``tmp_path`` so production SHM is never
    touched.
    """

    def __init__(
        self,
        *,
        path: Path | str = DEFAULT_ENVELOPE_PATH,
        sample_rate_hz: int = 24000,
    ) -> None:
        self._path = Path(path)
        self._sample_rate_hz = int(sample_rate_hz)
        self._window_samples = max(1, int(sample_rate_hz * _WINDOW_MS / 1000.0))
        self._buffer = np.zeros(0, dtype=np.int16)
        self._head = 0

        # Allocate + zero the file, then mmap it for low-overhead writes.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "wb") as fh:
            fh.truncate(_FILE_SIZE)
        self._file = open(self._path, "r+b")
        self._mmap = mmap.mmap(self._file.fileno(), _FILE_SIZE, access=mmap.ACCESS_WRITE)

        # Seed the header to 0 explicitly (truncate already zeroed, but
        # this makes intent obvious and tolerates any reallocation).
        struct.pack_into("<I", self._mmap, 0, 0)

    # -- Public API ---------------------------------------------------------

    def feed(self, pcm: bytes | bytearray | memoryview | np.ndarray) -> None:
        """Ingest PCM samples (int16 LE, mono) and emit ring entries.

        Multiple :meth:`feed` calls accumulate — any tail shorter than
        one window waits for the next call rather than being flushed
        as a partial window (partial windows would give misleading RMS
        + skew F0).
        """
        if isinstance(pcm, np.ndarray):
            samples = np.asarray(pcm, dtype=np.int16)
        else:
            samples = np.frombuffer(pcm, dtype=np.int16)
        if samples.size == 0:
            return

        self._buffer = np.concatenate([self._buffer, samples]) if self._buffer.size else samples

        # Emit one ring entry per full window, drop the consumed tail.
        while self._buffer.size >= self._window_samples:
            window = self._buffer[: self._window_samples].astype(np.float32) / 32768.0
            self._buffer = self._buffer[self._window_samples :]
            self._emit(window)

    def snapshot(self, n: int) -> list[tuple[float, float, float, float, float]]:
        """Return the ``n`` most-recent ring entries in oldest-first order.

        Used by tests + the GEAL render loop (which asks for the last
        8–16 samples to smooth the voice envelope). Tolerates ``n`` >
        ``head`` by returning only what exists.
        """
        if n <= 0:
            return []
        head = struct.unpack_from("<I", self._mmap, 0)[0]
        available = min(n, head, RING_SLOTS)
        out: list[tuple[float, float, float, float, float]] = []
        for i in range(available, 0, -1):
            slot_logical = head - i  # logical index — positive step toward "most recent"
            slot = slot_logical % RING_SLOTS
            offset = _HEADER_SIZE + slot * _SLOT_SIZE
            out.append(struct.unpack_from("<fffff", self._mmap, offset))
        return out

    def close(self) -> None:
        """Flush and release the mmap + file handle."""
        try:
            self._mmap.flush()
        except (ValueError, OSError):
            pass
        try:
            self._mmap.close()
        except (ValueError, OSError):
            pass
        try:
            self._file.close()
        except OSError:
            pass

    # -- Internals ----------------------------------------------------------

    def _emit(self, window: np.ndarray) -> None:
        """Analyse one window and write a slot + bump the head index."""
        rms = _compute_rms(window)
        centroid = _compute_spectral_centroid(window, self._sample_rate_hz)
        zcr = _compute_zcr(window, self._sample_rate_hz)
        f0, voicing = _compute_f0_yin(
            window,
            self._sample_rate_hz,
            f_min=_F0_MIN_HZ,
            f_max=_F0_MAX_HZ,
        )
        slot = self._head % RING_SLOTS
        offset = _HEADER_SIZE + slot * _SLOT_SIZE
        struct.pack_into("<fffff", self._mmap, offset, rms, centroid, zcr, f0, voicing)
        # Head bump last so consumers observing head=N get a fully-
        # written slot N-1. Wrap the visible head so 0 <= head < RING_SLOTS.
        self._head = (self._head + 1) % RING_SLOTS
        struct.pack_into("<I", self._mmap, 0, self._head)


# -- Feature extractors ----------------------------------------------------


def _compute_rms(window: np.ndarray) -> float:
    if window.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(window.astype(np.float64) ** 2)))


def _compute_zcr(window: np.ndarray, sample_rate_hz: int) -> float:
    """Zero-crossing rate normalised as crossings per second.

    Normalised so GEAL can compare ZCR across window sizes without
    rescaling — 2 × fundamental for a pure sine, substantially higher
    for unvoiced / noise.
    """
    if window.size < 2:
        return 0.0
    signs = np.sign(window)
    crossings = int(np.sum(np.abs(np.diff(signs)) > 0))
    duration_s = window.size / float(sample_rate_hz)
    if duration_s <= 0.0:
        return 0.0
    return float(crossings) / duration_s


def _compute_spectral_centroid(window: np.ndarray, sample_rate_hz: int) -> float:
    """Power-weighted mean frequency of the window."""
    if window.size < 4:
        return 0.0
    # Hann-window to reduce spectral leakage.
    n = window.size
    w = 0.5 * (1.0 - np.cos(2.0 * math.pi * np.arange(n) / max(1, n - 1)))
    spectrum = np.fft.rfft(window * w)
    magnitudes = np.abs(spectrum)
    total = magnitudes.sum()
    if total <= 1e-12:
        return 0.0
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)
    return float(np.sum(freqs * magnitudes) / total)


def _compute_f0_yin(
    window: np.ndarray,
    sample_rate_hz: int,
    *,
    f_min: float,
    f_max: float,
) -> tuple[float, float]:
    """YIN F0 estimator with a voicing-probability side-channel.

    Returns ``(f0_hz, voicing_prob)``. On silence / noise / the search
    range containing no clear peak, ``f0_hz`` is 0.0 and voicing is
    low. On a clean tone, ``f0_hz`` lands within a few percent of the
    true frequency and voicing approaches 1.

    Simplified stdlib-grade YIN — adequate for GEAL's use case where
    we need a voicing gate + a rough pitch region, not forensic
    pitch tracking.
    """
    if window.size < 16:
        return 0.0, 0.0
    tau_min = max(1, int(sample_rate_hz / f_max))
    tau_max = min(window.size - 2, int(sample_rate_hz / f_min))
    if tau_max <= tau_min:
        return 0.0, 0.0

    # Squared difference function (YIN step 1 — equation 6).
    diff = np.zeros(tau_max + 1, dtype=np.float64)
    for tau in range(1, tau_max + 1):
        delta = window[: window.size - tau] - window[tau : window.size]
        diff[tau] = float(np.sum(delta * delta))

    # Cumulative mean normalised difference (YIN step 2).
    cmnd = np.ones_like(diff)
    running = 0.0
    for tau in range(1, tau_max + 1):
        running += diff[tau]
        cmnd[tau] = diff[tau] * tau / max(1e-12, running)

    # Absolute threshold (YIN step 3).
    # Walk the search range, pick the first tau below threshold.
    tau = 0
    for i in range(tau_min, tau_max + 1):
        if cmnd[i] < _YIN_THRESHOLD:
            # Advance to the local minimum (parabolic refinement would
            # improve accuracy; omit for v1 to keep cost bounded).
            while i + 1 <= tau_max and cmnd[i + 1] < cmnd[i]:
                i += 1
            tau = i
            break

    if tau == 0:
        # No voiced period found; return the global minimum of the
        # search range for voicing scoring, but flag f0 = 0.
        if tau_max >= tau_min:
            local = cmnd[tau_min : tau_max + 1]
            min_cmnd = float(local.min()) if local.size else 1.0
        else:
            min_cmnd = 1.0
        voicing = max(0.0, 1.0 - min_cmnd)
        return 0.0, voicing

    f0 = float(sample_rate_hz) / float(tau)
    voicing = max(0.0, min(1.0, 1.0 - float(cmnd[tau])))
    return f0, voicing


# -- Env-gate helper for CpalRunner integration (Phase 2 Task 2.1 step 3) --


def envelope_publish_enabled() -> bool:
    """Default ON; set ``HAPAX_TTS_ENVELOPE_PUBLISH=0`` to disable."""
    return os.environ.get("HAPAX_TTS_ENVELOPE_PUBLISH", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
        "",
    )
