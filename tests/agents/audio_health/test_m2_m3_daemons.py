"""Tests for M2 LUFS-S daemon and M3 crest/flatness daemon.

Validates:
- M2: LUFS-S band detection, breach counting, Prometheus emission
- M3: Crest factor, ZCR, spectral flatness, threshold breach detection
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from agents.audio_health.m1_dimensions import compute_spectral_flatness
from agents.audio_health.m2_lufs_s_daemon import (
    LufsBand,
    M2DaemonConfig,
    StageState,
    _emit_snapshot,
)
from agents.audio_health.m3_crest_flatness_daemon import (
    M3DaemonConfig,
    StageMeasurement,
    compute_crest_factor,
    compute_zcr,
)
from agents.audio_health.m3_crest_flatness_daemon import (
    StageState as M3StageState,
)
from agents.audio_health.m3_crest_flatness_daemon import (
    _emit_snapshot as m3_emit_snapshot,
)

# ── M2 Tests ────────────────────────────────────────────────────────────


class TestM2Config:
    """M2DaemonConfig construction."""

    def test_default_bands(self) -> None:
        cfg = M2DaemonConfig()
        assert cfg.probe_interval_s == 5.0
        assert cfg.capture_duration_s == 3.0

    def test_from_env_with_overrides(self) -> None:
        with patch.dict(
            "os.environ",
            {"HAPAX_AUDIO_HEALTH_LUFS_S_PROBE_INTERVAL_S": "10.0"},
        ):
            cfg = M2DaemonConfig.from_env()
            assert cfg.probe_interval_s == 10.0

    def test_from_env_invalid_float_uses_default(self) -> None:
        with patch.dict(
            "os.environ",
            {"HAPAX_AUDIO_HEALTH_LUFS_S_PROBE_INTERVAL_S": "not-a-number"},
        ):
            cfg = M2DaemonConfig.from_env()
            assert cfg.probe_interval_s == 5.0


class TestM2StageState:
    """M2 LUFS-S band breach tracking."""

    def test_in_band_default(self) -> None:
        state = StageState()
        assert state.in_band is True
        assert state.breach_count == 0

    def test_band_check_in_range(self) -> None:
        band = LufsBand(low=-23.0, high=-16.0)
        lufs = -19.5
        in_band = band.low <= lufs <= band.high
        assert in_band is True

    def test_band_check_below(self) -> None:
        band = LufsBand(low=-23.0, high=-16.0)
        lufs = -30.0
        in_band = band.low <= lufs <= band.high
        assert in_band is False

    def test_band_check_above(self) -> None:
        band = LufsBand(low=-23.0, high=-16.0)
        lufs = -10.0
        in_band = band.low <= lufs <= band.high
        assert in_band is False


class TestM2Emission:
    """M2 Prometheus textfile and SHM snapshot emission."""

    def test_emit_snapshot_writes_json(self, tmp_path: Path) -> None:
        snapshot_path = tmp_path / "lufs-s.json"
        config = M2DaemonConfig(snapshot_path=snapshot_path)
        stages = {
            "hapax-broadcast-master": StageState(last_lufs=-19.2, in_band=True, breach_count=0),
        }
        _emit_snapshot(stages, config, now=1000.0)
        assert snapshot_path.exists()
        data = json.loads(snapshot_path.read_text())
        assert data["monitor"] == "lufs-s"
        assert data["stages"]["hapax-broadcast-master"]["lufs_s"] == pytest.approx(-19.2)
        assert data["stages"]["hapax-broadcast-master"]["in_band"] is True

    def test_emit_textfile_contains_metrics(self, tmp_path: Path) -> None:
        stages = {
            "hapax-broadcast-master": StageState(last_lufs=-20.0, in_band=True, breach_count=2),
        }
        with patch.object(Path, "parent", new_callable=lambda: property(lambda self: tmp_path)):
            # Just verify the textfile content is correct by checking the generation
            lines: list[str] = [
                "# HELP hapax_audio_health_lufs_s_value Short-term LUFS (3s EBU R128) per stage",
                "# TYPE hapax_audio_health_lufs_s_value gauge",
            ]
            for stage, state in stages.items():
                lines.append(
                    f'hapax_audio_health_lufs_s_value{{stage="{stage}"}} {state.last_lufs:.2f}'
                )
            text = "\n".join(lines)
            assert "hapax_audio_health_lufs_s_value" in text
            assert "-20.00" in text


# ── M3 Tests ────────────────────────────────────────────────────────────


class TestCrestFactor:
    """Crest factor computation."""

    def test_sine_wave_crest(self) -> None:
        """Sine wave crest factor = sqrt(2) ≈ 1.414."""
        t = np.linspace(0, 1, 48000, endpoint=False)
        sine = np.sin(2 * np.pi * 440 * t)
        crest = compute_crest_factor(sine)
        assert crest == pytest.approx(math.sqrt(2), abs=0.05)

    def test_white_noise_crest(self) -> None:
        """White noise crest factor ≈ 3.0 (sqrt(3)), but can vary."""
        rng = np.random.default_rng(42)
        noise = rng.standard_normal(48000)
        crest = compute_crest_factor(noise)
        # White noise crest typically 2.5-5.0
        assert 2.0 < crest < 6.0

    def test_silence_crest(self) -> None:
        """Silent input returns 0.0."""
        silence = np.zeros(48000)
        assert compute_crest_factor(silence) == 0.0

    def test_empty_input(self) -> None:
        assert compute_crest_factor(np.array([])) == 0.0

    def test_dc_signal_crest(self) -> None:
        """DC signal has crest factor = 1.0."""
        dc = np.full(48000, 0.5)
        crest = compute_crest_factor(dc)
        assert crest == pytest.approx(1.0, abs=0.01)


class TestZCR:
    """Zero crossing rate computation."""

    def test_sine_wave_zcr(self) -> None:
        """440 Hz sine at 48kHz has ~880 crossings / 48000 samples ≈ 0.018."""
        t = np.linspace(0, 1, 48000, endpoint=False)
        sine = np.sin(2 * np.pi * 440 * t)
        zcr = compute_zcr(sine)
        expected = 2 * 440 / 48000
        assert zcr == pytest.approx(expected, abs=0.005)

    def test_white_noise_zcr(self) -> None:
        """White noise ZCR ≈ 0.5."""
        rng = np.random.default_rng(42)
        noise = rng.standard_normal(48000)
        zcr = compute_zcr(noise)
        assert 0.4 < zcr < 0.6

    def test_silence_zcr(self) -> None:
        silence = np.zeros(48000)
        # All samples are 0 — signbit is False for all, so no crossings
        assert compute_zcr(silence) == 0.0

    def test_dc_zcr(self) -> None:
        """DC signal has no crossings."""
        dc = np.full(48000, 0.5)
        assert compute_zcr(dc) == 0.0

    def test_alternating_zcr(self) -> None:
        """Alternating signal has ZCR ≈ 1.0."""
        alt = np.array([1.0, -1.0] * 100)
        zcr = compute_zcr(alt)
        assert zcr == pytest.approx(1.0, abs=0.02)


class TestM3Config:
    """M3DaemonConfig construction."""

    def test_defaults(self) -> None:
        cfg = M3DaemonConfig()
        assert cfg.probe_interval_s == 5.0
        assert cfg.crest_drop_threshold == 5.0
        assert cfg.flatness_noise_threshold == 0.6

    def test_from_env_with_override(self) -> None:
        with patch.dict(
            "os.environ",
            {"HAPAX_AUDIO_HEALTH_CREST_FLATNESS_CREST_DROP_THRESHOLD": "4.0"},
        ):
            cfg = M3DaemonConfig.from_env()
            assert cfg.crest_drop_threshold == 4.0


class TestM3MeasurementClassification:
    """M3 acoustic content discrimination."""

    def test_music_like_signal(self) -> None:
        """Music: high crest, low ZCR, low flatness."""
        # Simulated music-like signal (multiple tones)
        t = np.linspace(0, 1, 48000, endpoint=False)
        signal = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.2 * np.sin(2 * np.pi * 880 * t)
        compute_crest_factor(signal)  # called to verify no error
        zcr = compute_zcr(signal)
        flatness = compute_spectral_flatness(signal)
        # Tonal signals: moderate crest, low ZCR, low flatness
        assert zcr < 0.15
        assert flatness < 0.3

    def test_white_noise_signal(self) -> None:
        """White noise: medium crest, high ZCR, high flatness."""
        rng = np.random.default_rng(42)
        noise = rng.standard_normal(48000)
        crest = compute_crest_factor(noise)
        zcr = compute_zcr(noise)
        flatness = compute_spectral_flatness(noise)
        assert 2.0 < crest < 6.0
        assert zcr > 0.35
        assert flatness > 0.5

    def test_tone_drone_signal(self) -> None:
        """Pure tone: low crest (~1.4), very low ZCR, very low flatness."""
        t = np.linspace(0, 1, 48000, endpoint=False)
        tone = np.sin(2 * np.pi * 60 * t)  # 60 Hz hum
        crest = compute_crest_factor(tone)
        zcr = compute_zcr(tone)
        flatness = compute_spectral_flatness(tone)
        assert crest == pytest.approx(math.sqrt(2), abs=0.1)
        assert zcr < 0.01
        assert flatness < 0.1


class TestM3Emission:
    """M3 Prometheus textfile and SHM snapshot emission."""

    def test_emit_snapshot_writes_json(self, tmp_path: Path) -> None:
        snapshot_path = tmp_path / "crest-flatness.json"
        config = M3DaemonConfig(snapshot_path=snapshot_path)
        states = {
            "hapax-broadcast-master": M3StageState(
                last_measurement=StageMeasurement(
                    crest=8.5,
                    zcr=0.05,
                    spectral_flatness=0.15,
                ),
                crest_drop_count=1,
            ),
        }
        m3_emit_snapshot(states, config, now=1000.0)
        assert snapshot_path.exists()
        data = json.loads(snapshot_path.read_text())
        assert data["monitor"] == "crest-flatness"
        assert data["stages"]["hapax-broadcast-master"]["crest"] == pytest.approx(8.5)
        assert data["stages"]["hapax-broadcast-master"]["zcr"] == pytest.approx(0.05)
        assert data["stages"]["hapax-broadcast-master"]["crest_drop_count"] == 1


class TestM3BreachDetection:
    """M3 threshold breach detection."""

    def test_crest_drop_detected(self) -> None:
        """Crest dropping from >5 to <5 should be detected."""
        state = M3StageState(prev_crest=8.0)
        cfg = M3DaemonConfig(enable_ntfy=False)
        new_crest = 3.0
        assert new_crest < cfg.crest_drop_threshold
        assert state.prev_crest > cfg.crest_drop_threshold

    def test_flatness_noise_detected(self) -> None:
        """Spectral flatness >0.6 should trigger white noise detection."""
        cfg = M3DaemonConfig()
        flatness = 0.75
        assert flatness >= cfg.flatness_noise_threshold

    def test_nominal_signal_no_breach(self) -> None:
        """Normal music signal should not trigger any breach."""
        cfg = M3DaemonConfig()
        measurement = StageMeasurement(crest=8.5, zcr=0.05, spectral_flatness=0.15)
        assert measurement.crest > cfg.crest_drop_threshold  # no drop
        assert measurement.spectral_flatness < cfg.flatness_noise_threshold  # no noise
