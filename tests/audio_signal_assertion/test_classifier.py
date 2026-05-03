"""Synthesized-signal tests for the H1 classifier.

We feed the classifier idealised waveforms whose RMS, crest, and ZCR
properties are known a priori, then assert the right
:class:`Classification` falls out. This pins the +20 dB clipping
detection and the absolute-silence detection failure modes that the
H1 source research §1 calls out as the load-bearing motivators.
"""

from __future__ import annotations

import numpy as np
import pytest

from agents.audio_signal_assertion.classifier import (
    BAD_STEADY_STATES,
    Classification,
    ClassifierConfig,
    classify,
    measure_pcm,
)

SAMPLE_RATE = 48_000
WINDOW_SECONDS = 2.0


def _times(seconds: float = WINDOW_SECONDS) -> np.ndarray:
    n = int(seconds * SAMPLE_RATE)
    return np.arange(n) / SAMPLE_RATE


def _sine(amp: float, freq: float = 440.0, seconds: float = WINDOW_SECONDS) -> np.ndarray:
    return (amp * np.sin(2 * np.pi * freq * _times(seconds))).astype(np.float64)


def _noise(amp: float, *, seed: int = 0, seconds: float = WINDOW_SECONDS) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amp * rng.standard_normal(int(seconds * SAMPLE_RATE))).astype(np.float64)


def _hard_clipped_noise(
    amp: float = 1.0,
    *,
    seed: int = 0,
    ceiling: float = 0.99,
    seconds: float = WINDOW_SECONDS,
) -> np.ndarray:
    raw = _noise(amp * 4.0, seed=seed, seconds=seconds)
    return np.clip(raw, -ceiling, ceiling)


def _music_like(amp: float = 0.2, seed: int = 0, seconds: float = WINDOW_SECONDS) -> np.ndarray:
    """Sparse-onset signal with high crest factor and low ZCR."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SAMPLE_RATE)
    out = np.zeros(n, dtype=np.float64)
    # Place ~6 brief bursts of low-frequency content per second.
    for i in range(int(seconds * 6)):
        start = i * (SAMPLE_RATE // 6) + rng.integers(-100, 100)
        if start < 0 or start + 200 >= n:
            continue
        envelope = np.exp(-np.linspace(0, 5, 200))
        burst = envelope * np.sin(np.linspace(0, np.pi * 4, 200))
        out[start : start + 200] += burst * amp
    return out


# ---------------------------------------------------------------------------
# measure_pcm: pure-numerics tests
# ---------------------------------------------------------------------------


def test_measure_pcm_silence_returns_floor():
    samples = np.zeros(SAMPLE_RATE * 2, dtype=np.int16)
    m = measure_pcm(samples)
    assert m.rms_dbfs <= -100.0
    assert m.peak_dbfs <= -100.0
    assert m.zero_crossing_rate == 0.0
    # Zero-amplitude has crest factor 0 by our convention (rather than
    # NaN), so noise/clipping precedence is well-defined.
    assert m.crest_factor == 0.0


def test_measure_pcm_sine_crest_factor_close_to_sqrt_2():
    samples = _sine(0.5)
    m = measure_pcm(samples)
    assert m.rms_dbfs == pytest.approx(20 * np.log10(0.5 / np.sqrt(2)), abs=0.5)
    assert m.crest_factor == pytest.approx(np.sqrt(2), rel=0.05)
    # Sine wave: ZCR ≈ 2 * freq / sample_rate
    assert m.zero_crossing_rate == pytest.approx(2 * 440 / SAMPLE_RATE, rel=0.05)


def test_measure_pcm_white_noise_crest_factor_in_3_to_5():
    samples = _noise(0.1, seed=42)
    m = measure_pcm(samples)
    # Gaussian white noise crest factor is ~3.5–5 for a 2s window.
    assert 3.0 <= m.crest_factor <= 6.0
    # ZCR ~0.5 for white Gaussian noise at this rate.
    assert m.zero_crossing_rate > 0.30


def test_measure_pcm_int16_round_trip():
    floats = _sine(0.5)
    int16_samples = (floats * 32768).clip(-32768, 32767).astype(np.int16)
    m_int = measure_pcm(int16_samples)
    m_float = measure_pcm(floats)
    assert m_int.rms_dbfs == pytest.approx(m_float.rms_dbfs, abs=0.5)
    assert m_int.crest_factor == pytest.approx(m_float.crest_factor, rel=0.05)


def test_measure_pcm_rejects_non_mono():
    samples = np.zeros((SAMPLE_RATE, 2), dtype=np.int16)
    with pytest.raises(ValueError, match="mono"):
        measure_pcm(samples)


def test_measure_pcm_handles_empty():
    samples = np.zeros(0, dtype=np.int16)
    m = measure_pcm(samples)
    assert m.sample_count == 0
    assert m.crest_factor == 0.0


# ---------------------------------------------------------------------------
# classify: synthesized-signal precedence tests
# ---------------------------------------------------------------------------


def test_classify_silence_below_floor():
    samples = np.zeros(SAMPLE_RATE, dtype=np.int16)
    label = classify(measure_pcm(samples))
    assert label == Classification.SILENT


def test_classify_low_rms_drone_is_silent():
    # -65 dBFS sine — below -55 dBFS silence floor.
    samples = _sine(amp=10 ** (-65 / 20.0))
    label = classify(measure_pcm(samples))
    assert label == Classification.SILENT


def test_classify_strong_sine_is_tone():
    samples = _sine(amp=0.4)
    label = classify(measure_pcm(samples))
    # crest ~ sqrt(2) < tone_crest_max=2.0, RMS ~ -8 dBFS so silence
    # check passes; we expect tone.
    assert label == Classification.TONE


def test_classify_white_noise_band_is_noise():
    samples = _noise(0.05, seed=11)
    label = classify(measure_pcm(samples))
    assert label == Classification.NOISE


def test_classify_clipping_when_peak_at_zero_dbfs():
    # Hard-clipped noise at near-full-scale: peak_dbfs ~ 0.
    samples = _hard_clipped_noise(amp=1.0, ceiling=0.99)
    label = classify(measure_pcm(samples))
    assert label == Classification.CLIPPING


def test_classify_clipping_via_crest_rms_route():
    # Loud square-ish wave: crest < 5, RMS > -10 dBFS.
    n = SAMPLE_RATE * 2
    rng = np.random.default_rng(7)
    raw = 0.7 * np.sign(np.sin(2 * np.pi * 220 * _times())) + 0.05 * rng.standard_normal(n)
    samples = np.clip(raw, -0.9, 0.9)
    m = measure_pcm(samples)
    assert m.rms_dbfs > -10.0
    assert m.crest_factor < 5.0
    assert classify(m) == Classification.CLIPPING


def test_classify_music_like_sparse_bursts():
    samples = _music_like(amp=0.4, seed=3)
    m = measure_pcm(samples)
    label = classify(m)
    # Music-like signals have high crest + low ZCR; pin the contract.
    assert label == Classification.MUSIC_VOICE


def test_clipping_precedence_over_noise():
    # Hard-clipped noise: noise-like crest after clipping (~3-4) but
    # peak is at the clipping ceiling, so clipping must win.
    samples = _hard_clipped_noise(amp=1.0, ceiling=0.99, seed=5)
    m = measure_pcm(samples)
    assert m.peak_dbfs >= -1.0
    assert classify(m) == Classification.CLIPPING


def test_silence_precedence_above_tone_when_below_floor():
    # Crest factor would otherwise place this in TONE, but RMS is below
    # the silence floor so SILENT must win.
    samples = _sine(amp=10 ** (-80 / 20.0))
    m = measure_pcm(samples)
    assert m.crest_factor < 2.0
    assert m.rms_dbfs < -55.0
    assert classify(m) == Classification.SILENT


# ---------------------------------------------------------------------------
# ClassifierConfig env override
# ---------------------------------------------------------------------------


def test_classifier_config_env_overrides(monkeypatch):
    monkeypatch.setenv("HAPAX_AUDIO_SIGNAL_SILENCE_FLOOR_DBFS", "-30.0")
    monkeypatch.setenv("HAPAX_AUDIO_SIGNAL_CLIPPING_PEAK_DBFS", "-3.0")
    cfg = ClassifierConfig.from_env()
    assert cfg.silence_floor_dbfs == -30.0
    assert cfg.clipping_peak_dbfs == -3.0


def test_classifier_config_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("HAPAX_AUDIO_SIGNAL_TONE_CREST_MAX", "not-a-number")
    cfg = ClassifierConfig.from_env()
    # Default preserved, invalid env doesn't crash.
    assert cfg.tone_crest_max == ClassifierConfig().tone_crest_max


# ---------------------------------------------------------------------------
# Bad-state set audit
# ---------------------------------------------------------------------------


def test_bad_steady_states_pin():
    # Pin the bad-state set so future classifier additions don't
    # silently shift the alerter's surface area.
    assert (
        frozenset({Classification.SILENT, Classification.NOISE, Classification.CLIPPING})
        == BAD_STEADY_STATES
    )
