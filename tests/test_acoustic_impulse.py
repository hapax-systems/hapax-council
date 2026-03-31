"""Tests for acoustic impulse writer — Daimonion → Reverie cross-modal signal."""

import json
import struct
import tempfile
from pathlib import Path

from agents.hapax_daimonion.acoustic_impulse import (
    _compute_rms_energy,
    _estimate_pitch_zcr,
    write_acoustic_impulse,
)


def _make_pcm16(samples: list[int]) -> bytes:
    """Pack a list of int16 samples into PCM16 bytes."""
    return struct.pack(f"<{len(samples)}h", *samples)


def test_rms_energy_silence():
    pcm = _make_pcm16([0] * 100)
    assert _compute_rms_energy(pcm) == 0.0


def test_rms_energy_loud():
    pcm = _make_pcm16([20000] * 100)
    energy = _compute_rms_energy(pcm)
    assert energy > 0.5


def test_rms_energy_normalized():
    pcm = _make_pcm16([32767] * 100)
    energy = _compute_rms_energy(pcm)
    assert energy <= 1.0


def test_pitch_zcr_silence():
    pcm = _make_pcm16([0] * 100)
    pitch = _estimate_pitch_zcr(pcm, 24000, 1)
    assert pitch == 0.0


def test_pitch_zcr_tone():
    """A 1kHz tone at 24kHz sample rate → ~24 crossings per 24 samples."""
    import math

    samples = [int(10000 * math.sin(2 * math.pi * 1000 * i / 24000)) for i in range(2400)]
    pcm = _make_pcm16(samples)
    pitch = _estimate_pitch_zcr(pcm, 24000, 1)
    assert 800 < pitch < 1200  # rough estimate, 20% tolerance


def test_write_acoustic_impulse():
    pcm = _make_pcm16([15000] * 500)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "acoustic-impulse.json"
        write_acoustic_impulse(pcm, path=path)
        data = json.loads(path.read_text())
        assert data["source"] == "daimonion"
        assert data["signals"]["energy"] > 0.0
        assert "onset" in data["signals"]
        assert "pitch_hz" in data["signals"]


def test_write_acoustic_impulse_silence_skipped():
    pcm = _make_pcm16([0] * 500)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "acoustic-impulse.json"
        write_acoustic_impulse(pcm, path=path)
        assert not path.exists()  # below noise floor, not written
