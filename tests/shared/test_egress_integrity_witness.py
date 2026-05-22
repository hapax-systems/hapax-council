"""Tests for egress integrity witness."""

from __future__ import annotations

import numpy as np

from shared.egress_integrity_witness import (
    EgressQuality,
    classify_egress,
)


def _tone_int16(
    freq_hz: float = 440.0,
    duration_s: float = 1.0,
    sample_rate: int = 48000,
    amplitude: float = 0.5,
) -> np.ndarray:
    """Generate a clean sine tone as int16."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    return (amplitude * 32767 * np.sin(2 * np.pi * freq_hz * t)).astype(np.int16)


def _silence_int16(duration_s: float = 1.0, sample_rate: int = 48000) -> np.ndarray:
    """Generate silence as int16."""
    return np.zeros(int(sample_rate * duration_s), dtype=np.int16)


def _garbled_int16(
    duration_s: float = 1.0,
    sample_rate: int = 48000,
) -> np.ndarray:
    """Generate garbled/clipped audio — hard-clipped square-ish wave with jitter.

    This simulates corrupt USB capture: high ZCR + near-clipping + low crest factor.
    """
    n = int(sample_rate * duration_s)
    # Start with a high-frequency signal
    t = np.linspace(0, duration_s, n, endpoint=False)
    raw = np.sin(2 * np.pi * 5000 * t)
    # Hard-clip to create near-square-wave with crushed dynamics
    clipped = np.clip(raw * 3.0, -1.0, 1.0)
    # Add some high-frequency noise to push ZCR up
    noise = np.random.default_rng(42).uniform(-0.05, 0.05, n)
    return ((clipped + noise) * 32000).astype(np.int16)


class TestClassifyEgress:
    def test_normal_tone(self) -> None:
        pcm = _tone_int16(freq_hz=440, duration_s=1.0, amplitude=0.3)
        report = classify_egress(pcm, sample_rate=48000)
        assert report.quality == EgressQuality.NORMAL
        assert report.rms_dbfs > -60.0
        assert report.sample_count == 48000

    def test_silence(self) -> None:
        pcm = _silence_int16(duration_s=1.0)
        report = classify_egress(pcm, sample_rate=48000)
        assert report.quality == EgressQuality.SILENCE

    def test_near_silence_noise_floor(self) -> None:
        """Very quiet noise below threshold = silence."""
        rng = np.random.default_rng(99)
        pcm = (rng.uniform(-0.0001, 0.0001, 48000) * 32767).astype(np.int16)
        report = classify_egress(pcm, sample_rate=48000)
        assert report.quality == EgressQuality.SILENCE

    def test_garbled_audio(self) -> None:
        pcm = _garbled_int16(duration_s=1.0)
        report = classify_egress(pcm, sample_rate=48000)
        assert report.quality == EgressQuality.GARBLED
        assert report.zero_crossing_rate > 5000
        assert report.crest_factor_db < 6.0

    def test_empty_buffer(self) -> None:
        report = classify_egress(b"", sample_rate=48000)
        assert report.quality == EgressQuality.UNKNOWN
        assert report.sample_count == 0

    def test_insufficient_samples(self) -> None:
        pcm = _tone_int16(freq_hz=440, duration_s=0.1)  # 4800 samples < 24000
        report = classify_egress(pcm, sample_rate=48000)
        assert report.quality == EgressQuality.UNKNOWN

    def test_bytes_input(self) -> None:
        pcm = _tone_int16(freq_hz=440, duration_s=1.0, amplitude=0.3)
        report = classify_egress(pcm.tobytes(), sample_rate=48000)
        assert report.quality == EgressQuality.NORMAL

    def test_multichannel_extraction(self) -> None:
        """Interleaved stereo: extract channel 0."""
        mono = _tone_int16(freq_hz=440, duration_s=1.0, amplitude=0.3)
        silence = _silence_int16(duration_s=1.0)
        # Interleave: ch0=tone, ch1=silence
        stereo = np.empty(len(mono) * 2, dtype=np.int16)
        stereo[0::2] = mono
        stereo[1::2] = silence
        report = classify_egress(stereo, sample_rate=48000, channels=2, channel_index=0)
        assert report.quality == EgressQuality.NORMAL

    def test_multichannel_silence_channel(self) -> None:
        """Extract the silent channel from stereo."""
        mono = _tone_int16(freq_hz=440, duration_s=1.0, amplitude=0.3)
        silence = _silence_int16(duration_s=1.0)
        stereo = np.empty(len(mono) * 2, dtype=np.int16)
        stereo[0::2] = mono
        stereo[1::2] = silence
        report = classify_egress(stereo, sample_rate=48000, channels=2, channel_index=1)
        assert report.quality == EgressQuality.SILENCE

    def test_report_serializes(self) -> None:
        pcm = _tone_int16(freq_hz=440, duration_s=1.0, amplitude=0.3)
        report = classify_egress(pcm, sample_rate=48000)
        d = report.to_dict()
        assert d["quality"] == "normal"
        assert isinstance(d["rms_dbfs"], float)
        assert isinstance(d["zero_crossing_rate"], float)

    def test_inf_values_serialize_as_none(self) -> None:
        report = classify_egress(b"", sample_rate=48000)
        d = report.to_dict()
        assert d["rms_dbfs"] is None
        assert d["peak_dbfs"] is None
