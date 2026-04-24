"""Tests for the TTS envelope SHM reader."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest


def _sine_pcm(freq: float, sr: int, duration: float, amp: float = 0.5) -> bytes:
    n = int(duration * sr)
    t = np.arange(n) / sr
    x = amp * np.sin(2.0 * math.pi * freq * t)
    return (x * 32767.0).astype(np.int16).tobytes()


@pytest.fixture()
def envelope_path(tmp_path: Path) -> Path:
    return tmp_path / "tts-envelope.f32"


def test_reader_returns_empty_when_file_missing(envelope_path) -> None:
    from shared.tts_envelope_reader import TtsEnvelopeReader

    reader = TtsEnvelopeReader(path=envelope_path)
    # No producer has written; file doesn't exist yet.
    assert reader.latest(8) == []
    reader.close()


def test_reader_reads_producer_output(envelope_path) -> None:
    from agents.hapax_daimonion.tts_envelope_publisher import TtsEnvelopePublisher
    from shared.tts_envelope_reader import TtsEnvelopeReader

    publisher = TtsEnvelopePublisher(path=envelope_path, sample_rate_hz=24000)
    reader = TtsEnvelopeReader(path=envelope_path)

    for _ in range(3):
        publisher.feed(_sine_pcm(220.0, 24000, 0.03))

    samples = reader.latest(3)
    assert len(samples) == 3
    # Oldest-first; all three slots have non-zero RMS.
    for rms, *_ in samples:
        assert rms > 0.0

    publisher.close()
    reader.close()


def test_reader_survives_producer_restart(envelope_path) -> None:
    """Re-open on inode change so a daimonion restart doesn't leave a stale mmap."""
    from agents.hapax_daimonion.tts_envelope_publisher import TtsEnvelopePublisher
    from shared.tts_envelope_reader import TtsEnvelopeReader

    p1 = TtsEnvelopePublisher(path=envelope_path, sample_rate_hz=24000)
    p1.feed(_sine_pcm(220.0, 24000, 0.03))
    reader = TtsEnvelopeReader(path=envelope_path)
    first = reader.latest(1)
    assert len(first) == 1
    p1.close()

    # Simulate a daemon restart: delete + recreate the file (new inode).
    envelope_path.unlink()
    p2 = TtsEnvelopePublisher(path=envelope_path, sample_rate_hz=24000)
    p2.feed(_sine_pcm(440.0, 24000, 0.03))
    second = reader.latest(1)
    assert len(second) == 1
    # New data is distinct from the old data (centroid moves with pitch).
    assert second[0] != first[0]
    p2.close()
    reader.close()


def test_reader_caps_n_at_ring_size(envelope_path) -> None:
    from shared.tts_envelope_reader import RING_SLOTS, TtsEnvelopeReader

    reader = TtsEnvelopeReader(path=envelope_path)
    # n > RING_SLOTS should not crash; returns [] when no file exists.
    assert reader.latest(RING_SLOTS * 10) == []
    reader.close()
