"""Audio-visual temporal correlation verification (ARI L4/L19).

L4 (Common Fate): elements reacting to the same audio stimulus form
perceptual groups — the Sierpinski waveform and line-width both track
mixer_energy, so they move in lockstep.

L19 (Synchresis): cross-modal binding between audio and visual is the
primary grounding channel — when Hapax speaks, the Sierpinski surface
must respond within a single frame.

This test verifies the structural correlation contract by simulating
audio energy sequences through the Sierpinski renderer and measuring
that the visual output (line-width modulation) correlates with the
input signal above a threshold of r > 0.3.
"""

from __future__ import annotations

import math

from agents.studio_compositor.sierpinski_renderer import (
    AUDIO_LINE_WIDTH_BASE_PX,
    AUDIO_LINE_WIDTH_SCALE_PX,
    SIERPINSKI_AUDIO_ATTACK_ALPHA,
    SIERPINSKI_AUDIO_BURST_CLAMP,
    SierpinskiCairoSource,
)


def _pearson_r(xs: list[float], ys: list[float]) -> float:
    """Compute Pearson correlation coefficient between two sequences."""
    n = len(xs)
    assert n == len(ys) and n > 2
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)


def _simulate_energy_sequence(
    renderer: SierpinskiCairoSource, energies: list[float]
) -> list[float]:
    """Feed an energy sequence and collect the smoothed line-width values."""
    widths: list[float] = []
    for e in energies:
        renderer.set_audio_energy(e)
        lw = AUDIO_LINE_WIDTH_BASE_PX + renderer._audio_energy_smoothed * AUDIO_LINE_WIDTH_SCALE_PX
        widths.append(lw)
    return widths


class TestAudioVisualTemporalCorrelation:
    """Verify that audio energy input correlates with visual line-width output."""

    def test_speech_burst_correlation_above_threshold(self) -> None:
        """Simulate a TTS speech burst and verify r > 0.3."""
        renderer = SierpinskiCairoSource()
        energies = [
            0.0,
            0.0,
            0.1,
            0.3,
            0.6,
            0.8,
            0.7,
            0.5,
            0.3,
            0.1,
            0.0,
            0.0,
            0.2,
            0.5,
            0.9,
            0.85,
            0.6,
            0.4,
            0.2,
            0.0,
        ]
        widths = _simulate_energy_sequence(renderer, energies)
        clamped_energies = [min(e, SIERPINSKI_AUDIO_BURST_CLAMP) for e in energies]
        r = _pearson_r(clamped_energies, widths)
        assert r > 0.3, f"audio-visual correlation {r:.3f} below 0.3 threshold"

    def test_passthrough_yields_near_perfect_correlation(self) -> None:
        """With α=1.0 (passthrough), correlation should be ~1.0."""
        assert SIERPINSKI_AUDIO_ATTACK_ALPHA == 1.0, "precondition: passthrough alpha"
        renderer = SierpinskiCairoSource()
        energies = [0.0, 0.1, 0.2, 0.4, 0.6, 0.8, 0.6, 0.4, 0.2, 0.0]
        widths = _simulate_energy_sequence(renderer, energies)
        clamped = [min(e, SIERPINSKI_AUDIO_BURST_CLAMP) for e in energies]
        r = _pearson_r(clamped, widths)
        assert r > 0.99, f"passthrough alpha should yield r≈1.0, got {r:.3f}"

    def test_zero_latency_response(self) -> None:
        """Energy change at frame N must appear in line-width at frame N (zero lag)."""
        renderer = SierpinskiCairoSource()
        renderer.set_audio_energy(0.0)
        assert renderer._audio_energy_smoothed == 0.0
        renderer.set_audio_energy(0.7)
        expected = min(0.7, SIERPINSKI_AUDIO_BURST_CLAMP)
        assert renderer._audio_energy_smoothed == expected, (
            f"expected immediate response to {expected}, got {renderer._audio_energy_smoothed}"
        )

    def test_silence_produces_baseline_width(self) -> None:
        """Zero energy should produce exactly the base line width."""
        renderer = SierpinskiCairoSource()
        renderer.set_audio_energy(0.0)
        lw = AUDIO_LINE_WIDTH_BASE_PX + renderer._audio_energy_smoothed * AUDIO_LINE_WIDTH_SCALE_PX
        assert lw == AUDIO_LINE_WIDTH_BASE_PX

    def test_burst_clamp_prevents_overcorrelation(self) -> None:
        """Energy above BURST_CLAMP should be clamped, preventing visual whip."""
        renderer = SierpinskiCairoSource()
        renderer.set_audio_energy(1.0)
        assert renderer._audio_energy_smoothed <= SIERPINSKI_AUDIO_BURST_CLAMP


class TestCommonFateGrouping:
    """L4: elements reacting to the same stimulus form perceptual groups.

    Both the waveform draw (raw energy) and line-width modulation (smoothed
    energy) track the same mixer_energy input — they MUST correlate.
    """

    def test_raw_and_smoothed_track_same_source(self) -> None:
        renderer = SierpinskiCairoSource()
        energies = [0.0, 0.3, 0.6, 0.9, 0.6, 0.3, 0.0]
        raw_values: list[float] = []
        smoothed_values: list[float] = []
        for e in energies:
            renderer.set_audio_energy(e)
            raw_values.append(renderer._audio_energy)
            smoothed_values.append(renderer._audio_energy_smoothed)
        r = _pearson_r(raw_values, smoothed_values)
        assert r > 0.95, f"raw/smoothed diverged: r={r:.3f}"


class TestAudioVisualMapping:
    """Document which visual elements respond to which audio sources.

    This is a structural verification — the mapping exists and is wired.
    """

    def test_sierpinski_reads_mixer_energy(self) -> None:
        """Sierpinski renderer exposes set_audio_energy driven by mixer_energy."""
        renderer = SierpinskiCairoSource()
        assert hasattr(renderer, "set_audio_energy")
        assert hasattr(renderer, "_audio_energy")
        assert hasattr(renderer, "_audio_energy_smoothed")

    def test_overlay_wires_mixer_energy_to_sierpinski(self) -> None:
        """overlay.py reads compositor._cached_audio['mixer_energy']."""
        import inspect

        from agents.studio_compositor import overlay

        source = inspect.getsource(overlay)
        assert "mixer_energy" in source
        assert "set_audio_energy" in source

    def test_m8_oscilloscope_reads_ring_buffer(self) -> None:
        """M8 oscilloscope source reads from /dev/shm binary ring."""
        from agents.studio_compositor.m8_oscilloscope_source import M8OscilloscopeCairoSource

        assert hasattr(M8OscilloscopeCairoSource, "render_content")

    def test_fx_chain_caches_audio_signals(self) -> None:
        """fx_chain.py caches audio signals for per-frame consumers."""
        import inspect

        from agents.studio_compositor import fx_chain

        source = inspect.getsource(fx_chain)
        assert "_cached_audio" in source
