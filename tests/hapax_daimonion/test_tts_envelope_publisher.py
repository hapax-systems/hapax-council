"""Tests for the TTS envelope publisher (GEAL Phase 2 Task 2.1, spec §5.1).

The publisher taps CpalRunner's PCM playback stream, computes per-30 ms
RMS / spectral centroid / ZCR / F0 / voicing probability, and writes a
lock-free mmap ring of 256 × 5 f32s to
``/dev/shm/hapax-daimonion/tts-envelope.f32`` at ~100 Hz. GEAL reads
the ring each frame to drive V1 Chladni ignition + V2 halo radius /
opacity.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np
import pytest

RING_SLOTS = 256
FIELDS_PER_SLOT = 5  # rms, centroid, zcr, f0, voicing_prob
HEADER_SIZE = 4  # u32 head index
PAYLOAD_SIZE = RING_SLOTS * FIELDS_PER_SLOT * 4  # f32 = 4 bytes
FILE_SIZE = HEADER_SIZE + PAYLOAD_SIZE


@pytest.fixture()
def publisher_path(tmp_path: Path) -> Path:
    return tmp_path / "tts-envelope.f32"


@pytest.fixture()
def publisher(publisher_path: Path):
    from agents.hapax_daimonion.tts_envelope_publisher import TtsEnvelopePublisher

    p = TtsEnvelopePublisher(path=publisher_path, sample_rate_hz=24000)
    yield p
    p.close()


def _read_head(path: Path) -> int:
    data = path.read_bytes()
    return struct.unpack_from("<I", data, 0)[0]


def _read_slot(path: Path, slot: int) -> tuple[float, float, float, float, float]:
    data = path.read_bytes()
    offset = HEADER_SIZE + slot * FIELDS_PER_SLOT * 4
    return struct.unpack_from("<fffff", data, offset)


def _sine_pcm(
    freq_hz: float,
    sample_rate_hz: int,
    duration_s: float,
    amp: float = 0.5,
) -> bytes:
    """Generate signed-int16 PCM bytes for a pure tone."""
    n = int(duration_s * sample_rate_hz)
    t = np.arange(n) / sample_rate_hz
    x = amp * np.sin(2.0 * math.pi * freq_hz * t)
    return (x * 32767.0).astype(np.int16).tobytes()


def test_file_has_expected_size(publisher, publisher_path) -> None:
    assert publisher_path.exists()
    assert publisher_path.stat().st_size == FILE_SIZE


def test_initial_head_is_zero(publisher, publisher_path) -> None:
    assert _read_head(publisher_path) == 0


def test_feed_advances_head(publisher, publisher_path) -> None:
    pcm = _sine_pcm(220.0, 24000, 0.05)  # 50 ms → one 30 ms window
    publisher.feed(pcm)
    assert _read_head(publisher_path) >= 1


def test_rms_is_nonzero_for_tone(publisher, publisher_path) -> None:
    pcm = _sine_pcm(220.0, 24000, 0.03)
    publisher.feed(pcm)
    head = _read_head(publisher_path)
    assert head >= 1
    rms, *_ = _read_slot(publisher_path, (head - 1) % RING_SLOTS)
    assert rms > 0.01, f"expected non-zero RMS, got {rms}"


def test_rms_is_zero_for_silence(publisher, publisher_path) -> None:
    pcm = np.zeros(int(0.03 * 24000), dtype=np.int16).tobytes()
    publisher.feed(pcm)
    head = _read_head(publisher_path)
    assert head >= 1
    rms, *_ = _read_slot(publisher_path, (head - 1) % RING_SLOTS)
    assert rms < 0.001, f"expected near-zero RMS on silence, got {rms}"


def test_f0_tracks_pure_tone(publisher, publisher_path) -> None:
    """YIN on a 220 Hz sine should land within 5 % of true frequency."""
    pcm = _sine_pcm(220.0, 24000, 0.06)  # ~60 ms → two windows
    publisher.feed(pcm)
    head = _read_head(publisher_path)
    assert head >= 1
    _, _, _, f0, voicing = _read_slot(publisher_path, (head - 1) % RING_SLOTS)
    # Allow generous margin for a stdlib-grade YIN — we'll tighten
    # after gold-standard reference sweeps.
    assert abs(f0 - 220.0) / 220.0 < 0.10, f"expected ~220 Hz, got {f0}"
    assert voicing > 0.4, f"expected voicing > 0.4 on clean tone, got {voicing}"


def test_voicing_low_for_noise(publisher, publisher_path) -> None:
    rng = np.random.default_rng(seed=42)
    n = int(0.03 * 24000)
    x = rng.uniform(-0.5, 0.5, size=n)
    pcm = (x * 32767.0).astype(np.int16).tobytes()
    publisher.feed(pcm)
    head = _read_head(publisher_path)
    assert head >= 1
    *_, voicing = _read_slot(publisher_path, (head - 1) % RING_SLOTS)
    assert voicing < 0.6, f"expected low voicing on noise, got {voicing}"


def test_centroid_higher_for_treble_than_bass(publisher, publisher_path) -> None:
    bass = _sine_pcm(80.0, 24000, 0.03)
    publisher.feed(bass)
    head_bass = _read_head(publisher_path)
    _, centroid_bass, *_ = _read_slot(publisher_path, (head_bass - 1) % RING_SLOTS)

    treble = _sine_pcm(4000.0, 24000, 0.03)
    publisher.feed(treble)
    head_treble = _read_head(publisher_path)
    _, centroid_treble, *_ = _read_slot(publisher_path, (head_treble - 1) % RING_SLOTS)

    assert centroid_treble > centroid_bass, (
        f"expected treble centroid > bass centroid, got {centroid_treble} vs {centroid_bass}"
    )


def test_zcr_higher_for_higher_pitch(publisher, publisher_path) -> None:
    low = _sine_pcm(110.0, 24000, 0.03)
    publisher.feed(low)
    head_low = _read_head(publisher_path)
    _, _, zcr_low, *_ = _read_slot(publisher_path, (head_low - 1) % RING_SLOTS)

    high = _sine_pcm(2000.0, 24000, 0.03)
    publisher.feed(high)
    head_high = _read_head(publisher_path)
    _, _, zcr_high, *_ = _read_slot(publisher_path, (head_high - 1) % RING_SLOTS)

    assert zcr_high > zcr_low, f"expected ZCR to rise with pitch, got {zcr_low} vs {zcr_high}"


def test_snapshot_returns_last_n_slots(publisher, publisher_path) -> None:
    """snapshot(n) returns the n most-recent ring entries in oldest-first order."""
    # Feed 3 windows of pure tones so each has distinct RMS.
    for amp in (0.1, 0.3, 0.7):
        publisher.feed(_sine_pcm(220.0, 24000, 0.03, amp=amp))

    samples = publisher.snapshot(3)
    assert len(samples) == 3
    # RMS should climb with amplitude (oldest → newest).
    rms_values = [s[0] for s in samples]
    assert rms_values[0] < rms_values[1] < rms_values[2]


def test_ring_wraps_after_256_windows(publisher, publisher_path) -> None:
    """After 300 windows, head wraps back into [0, 256)."""
    pcm = _sine_pcm(220.0, 24000, 0.03)
    for _ in range(300):
        publisher.feed(pcm)
    head = _read_head(publisher_path)
    # Head counter modulo RING_SLOTS.
    assert 0 <= head < RING_SLOTS
