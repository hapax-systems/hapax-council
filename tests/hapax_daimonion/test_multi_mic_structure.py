"""Tests for structure-borne noise reference extension to NoiseReference."""

from __future__ import annotations

import numpy as np

from agents.hapax_daimonion.multi_mic import NoiseReference


def _make_pcm(freq_hz: float = 200.0, amplitude: float = 0.3, n_samples: int = 512) -> bytes:
    t = np.arange(n_samples) / 16000.0
    samples = (amplitude * 32767 * np.sin(2 * np.pi * freq_hz * t)).astype(np.int16)
    return samples.tobytes()


def _make_silence(n_samples: int = 512) -> bytes:
    return b"\x00" * (n_samples * 2)


class TestStructureSources:
    def test_accepts_structure_sources_param(self):
        ref = NoiseReference(structure_sources=["Test Device"])
        assert ref._structure_sources == ["Test Device"]

    def test_default_structure_sources_empty(self):
        ref = NoiseReference()
        assert ref._structure_sources == []

    def test_subtract_passthrough_without_estimates(self):
        ref = NoiseReference(structure_sources=["Test Device"])
        frame = _make_pcm()
        result = ref.subtract(frame)
        assert result == frame

    def test_structure_subtraction_reduces_energy(self):
        ref = NoiseReference(structure_sources=["Test Device"])
        window = np.hanning(512)
        noise_frame = np.frombuffer(_make_pcm(200.0, 0.3), dtype=np.int16).astype(np.float32)
        spec = np.fft.rfft(noise_frame * window)
        ref._structure_noise_estimate = np.abs(spec)

        input_frame = _make_pcm(200.0, 0.5)
        result = ref.subtract(input_frame)

        input_energy = np.sqrt(
            np.mean(np.frombuffer(input_frame, dtype=np.int16).astype(np.float32) ** 2)
        )
        result_energy = np.sqrt(
            np.mean(np.frombuffer(result, dtype=np.int16).astype(np.float32) ** 2)
        )
        assert result_energy < input_energy
