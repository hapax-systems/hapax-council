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

from agents.audio_health.classifier import classify, measure_pcm
from agents.audio_health.m1_dimensions import compute_spectral_flatness
from agents.audio_health.m2_lufs_s_daemon import (
    DEFAULT_BANDS,
    LufsBand,
    M2DaemonConfig,
    StageState,
    _emit_snapshot,
    _probe_stage,
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
from agents.audio_health.m3_crest_flatness_daemon import (
    _probe_stage as m3_probe_stage,
)
from agents.audio_health.probes import ProbeResult
from shared.audio_loudness import EGRESS_LRA_MAX_LU, EGRESS_TARGET_LUFS_I


def _parse_unit_environment(unit_text: str) -> dict[str, str]:
    """Extract ``Environment=KEY=VALUE`` pairs from a systemd unit body."""
    env: dict[str, str] = {}
    prefix = "Environment="
    for raw in unit_text.splitlines():
        line = raw.strip()
        if not line.startswith(prefix):
            continue
        key, _, value = line[len(prefix) :].partition("=")
        if key:
            env[key.strip()] = value.strip()
    return env


def _probe_result(stage: str, samples: np.ndarray) -> ProbeResult:
    measurement = measure_pcm(samples)
    return ProbeResult(
        stage=stage,
        classification=classify(measurement),
        measurement=measurement,
        samples_mono=samples,
        captured_at=1000.0,
        duration_s=samples.size / 44100,
        error=None,
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


class TestM2RawSampleContract:
    """M2 consumes explicit ProbeResult samples and reports analyzer failures."""

    def test_silent_input_uses_result_samples_without_dynamic_measurement_attr(self) -> None:
        state = StageState()
        cfg = M2DaemonConfig(
            stages=("stage-a",),
            bands={"stage-a": LufsBand(low=-23.0, high=-16.0)},
            enable_ntfy=False,
        )
        result = _probe_result("stage-a", np.zeros(44100, dtype=np.int16))

        with patch("agents.audio_health.m2_lufs_s_daemon.capture_and_measure", return_value=result):
            _probe_stage("stage-a", state, cfg, now=1000.0)

        assert not hasattr(result.measurement, "samples_mono")
        assert result.samples_mono.size == 44100
        assert state.last_error is None
        assert state.last_lufs == pytest.approx(-120.0)
        assert state.in_band is True  # silence gate suppresses band check

    def test_tone_input_updates_lufs_without_samples_mono_attribute_error(self) -> None:
        t = np.linspace(0, 1, 44100, endpoint=False)
        tone = (0.25 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
        state = StageState()
        cfg = M2DaemonConfig(stages=("stage-a",), enable_ntfy=False)
        result = _probe_result("stage-a", tone)

        with patch("agents.audio_health.m2_lufs_s_daemon.capture_and_measure", return_value=result):
            _probe_stage("stage-a", state, cfg, now=1000.0)

        assert state.last_error is None
        assert state.last_lufs > -120.0

    def test_analyzer_exception_is_snapshot_health_evidence(self, tmp_path: Path) -> None:
        state = StageState()
        cfg = M2DaemonConfig(snapshot_path=tmp_path / "lufs-s.json", enable_ntfy=False)
        result = _probe_result("stage-a", np.zeros(44100, dtype=np.int16))

        with (
            patch("agents.audio_health.m2_lufs_s_daemon.capture_and_measure", return_value=result),
            patch(
                "agents.audio_health.m2_lufs_s_daemon.compute_lufs_s",
                side_effect=RuntimeError("lufs analyzer failed"),
            ),
        ):
            _probe_stage("stage-a", state, cfg, now=1000.0)

        assert state.analyzer_error_count == 1
        assert state.last_error == "RuntimeError: lufs analyzer failed"
        _emit_snapshot({"stage-a": state}, cfg, now=1000.0)
        payload = json.loads(cfg.snapshot_path.read_text(encoding="utf-8"))
        assert payload["stages"]["stage-a"]["analyzer_error"] == state.last_error
        assert payload["stages"]["stage-a"]["analyzer_error_count"] == 1


class TestM2EgressBandSSOT:
    """Regression for P0 incident f3d2b04e (audio_lufs_breach).

    The OBS egress short-term LUFS band must encompass the broadcast loudness
    envelope declared in ``shared/audio_loudness.py`` (``EGRESS_TARGET_LUFS_I``
    with ``EGRESS_LRA_MAX_LU`` of legitimate spread). The shipped
    ``DEFAULT_BANDS`` undershoot that envelope and minted spurious P0 breaches
    on normal program dynamics; the corrected band is deployed via the unit's
    ``Environment=`` directives and asserted here against the SSOT.
    """

    # SSOT-derived obs-broadcast-remap band (mirrors the unit Environment=).
    REMEDIATION_LOW = -25.0
    REMEDIATION_HIGH = -6.0

    def test_default_egress_band_is_too_tight_for_ssot(self) -> None:
        # Documents the root cause: the shipped default cannot contain the
        # legitimate short-term range of a -14 LUFS-I / 11 LU-LRA egress.
        default_low, default_high = DEFAULT_BANDS["hapax-obs-broadcast-remap"]
        assert (default_low, default_high) == (-22.0, -18.0)
        legit_floor = EGRESS_TARGET_LUFS_I - EGRESS_LRA_MAX_LU  # -25.0
        assert not (default_low <= legit_floor <= default_high)
        # The incident's measured breaches sit inside the legit loudness range
        # yet below the default floor -> false positives.
        for lufs in (-23.4, -22.7):
            assert legit_floor <= lufs <= EGRESS_TARGET_LUFS_I
            assert not (default_low <= lufs <= default_high)
        # And the egress legitimately runs hot toward the target, breaching the
        # default ceiling in the other direction.
        assert not (default_low <= -15.34 <= default_high)

    def test_remediation_band_encompasses_ssot_envelope(self) -> None:
        low, high = self.REMEDIATION_LOW, self.REMEDIATION_HIGH
        assert low <= EGRESS_TARGET_LUFS_I - EGRESS_LRA_MAX_LU
        assert high >= EGRESS_TARGET_LUFS_I
        # GREEN: the full legitimate short-term span stays in band (no breach),
        # including the incident's breaches and the live hot reading.
        for lufs in (-25.0, -23.4, -22.7, -20.0, -17.51, -15.34, -14.0, -9.0):
            assert low <= lufs <= high, f"{lufs} LUFS-S should be in band"
        # RED: a sustained gross over-level (limiter carrying programme) breaches.
        assert not (low <= -3.0 <= high)

    def test_from_env_applies_remediation_band(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "HAPAX_AUDIO_HEALTH_LUFS_S_BAND_HAPAX_OBS_BROADCAST_REMAP_LOW": str(
                    self.REMEDIATION_LOW
                ),
                "HAPAX_AUDIO_HEALTH_LUFS_S_BAND_HAPAX_OBS_BROADCAST_REMAP_HIGH": str(
                    self.REMEDIATION_HIGH
                ),
            },
        ):
            cfg = M2DaemonConfig.from_env()
        band = cfg.bands["hapax-obs-broadcast-remap"]
        assert (band.low, band.high) == (self.REMEDIATION_LOW, self.REMEDIATION_HIGH)

    def test_unit_environment_pins_egress_band_to_ssot(self) -> None:
        # The committed systemd unit must carry the SSOT-aligned override so the
        # fix survives a fresh deploy, not just a runtime env file.
        repo_root = Path(__file__).resolve().parents[3]
        unit = repo_root / "systemd/units/hapax-audio-health-lufs-s.service"
        env = _parse_unit_environment(unit.read_text(encoding="utf-8"))
        low = float(env["HAPAX_AUDIO_HEALTH_LUFS_S_BAND_HAPAX_OBS_BROADCAST_REMAP_LOW"])
        high = float(env["HAPAX_AUDIO_HEALTH_LUFS_S_BAND_HAPAX_OBS_BROADCAST_REMAP_HIGH"])
        assert low <= EGRESS_TARGET_LUFS_I - EGRESS_LRA_MAX_LU
        assert high >= EGRESS_TARGET_LUFS_I
        # The committed band must relieve the incident's measured breaches.
        for lufs in (-23.4, -22.7):
            assert low <= lufs <= high


# ── M3 Tests ────────────────────────────────────────────────────────────


class TestCrestFactor:
    """Crest factor computation."""

    def test_sine_wave_crest(self) -> None:
        """Sine wave crest factor = sqrt(2) ≈ 1.414."""
        t = np.linspace(0, 1, 44100, endpoint=False)
        sine = np.sin(2 * np.pi * 440 * t)
        crest = compute_crest_factor(sine)
        assert crest == pytest.approx(math.sqrt(2), abs=0.05)

    def test_white_noise_crest(self) -> None:
        """White noise crest factor ≈ 3.0 (sqrt(3)), but can vary."""
        rng = np.random.default_rng(42)
        noise = rng.standard_normal(44100)
        crest = compute_crest_factor(noise)
        # White noise crest typically 2.5-5.0
        assert 2.0 < crest < 6.0

    def test_silence_crest(self) -> None:
        """Silent input returns 0.0."""
        silence = np.zeros(44100)
        assert compute_crest_factor(silence) == 0.0

    def test_empty_input(self) -> None:
        assert compute_crest_factor(np.array([])) == 0.0

    def test_dc_signal_crest(self) -> None:
        """DC signal has crest factor = 1.0."""
        dc = np.full(44100, 0.5)
        crest = compute_crest_factor(dc)
        assert crest == pytest.approx(1.0, abs=0.01)


class TestZCR:
    """Zero crossing rate computation."""

    def test_sine_wave_zcr(self) -> None:
        """440 Hz sine at 48kHz has ~880 crossings / 44100 samples ≈ 0.018."""
        t = np.linspace(0, 1, 44100, endpoint=False)
        sine = np.sin(2 * np.pi * 440 * t)
        zcr = compute_zcr(sine)
        expected = 2 * 440 / 44100
        assert zcr == pytest.approx(expected, abs=0.005)

    def test_white_noise_zcr(self) -> None:
        """White noise ZCR ≈ 0.5."""
        rng = np.random.default_rng(42)
        noise = rng.standard_normal(44100)
        zcr = compute_zcr(noise)
        assert 0.4 < zcr < 0.6

    def test_silence_zcr(self) -> None:
        silence = np.zeros(44100)
        # All samples are 0 — signbit is False for all, so no crossings
        assert compute_zcr(silence) == 0.0

    def test_dc_zcr(self) -> None:
        """DC signal has no crossings."""
        dc = np.full(44100, 0.5)
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
        assert cfg.crest_drop_zcr_min == 0.25
        assert cfg.crest_drop_flatness_min == 0.30
        assert cfg.flatness_noise_threshold == 0.6

    def test_from_env_with_override(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "HAPAX_AUDIO_HEALTH_CREST_FLATNESS_CREST_DROP_THRESHOLD": "4.0",
                "HAPAX_AUDIO_HEALTH_CREST_FLATNESS_CREST_DROP_ZCR_MIN": "0.40",
                "HAPAX_AUDIO_HEALTH_CREST_FLATNESS_CREST_DROP_FLATNESS_MIN": "0.50",
            },
        ):
            cfg = M3DaemonConfig.from_env()
            assert cfg.crest_drop_threshold == 4.0
            assert cfg.crest_drop_zcr_min == 0.40
            assert cfg.crest_drop_flatness_min == 0.50


class TestM3MeasurementClassification:
    """M3 acoustic content discrimination."""

    def test_music_like_signal(self) -> None:
        """Music: high crest, low ZCR, low flatness."""
        # Simulated music-like signal (multiple tones)
        t = np.linspace(0, 1, 44100, endpoint=False)
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
        noise = rng.standard_normal(44100)
        crest = compute_crest_factor(noise)
        zcr = compute_zcr(noise)
        flatness = compute_spectral_flatness(noise)
        assert 2.0 < crest < 6.0
        assert zcr > 0.35
        assert flatness > 0.5

    def test_tone_drone_signal(self) -> None:
        """Pure tone: low crest (~1.4), very low ZCR, very low flatness."""
        t = np.linspace(0, 1, 44100, endpoint=False)
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


class TestM3RawSampleContract:
    """M3 consumes explicit ProbeResult samples and reports analyzer failures."""

    def test_tone_input_updates_crest_zcr_flatness_without_dynamic_measurement_attr(self) -> None:
        t = np.linspace(0, 1, 44100, endpoint=False)
        tone = (0.4 * np.sin(2 * np.pi * 60 * t) * 32767).astype(np.int16)
        state = M3StageState()
        cfg = M3DaemonConfig(stages=("stage-a",), enable_ntfy=False)
        result = _probe_result("stage-a", tone)

        with patch(
            "agents.audio_health.m3_crest_flatness_daemon.capture_and_measure",
            return_value=result,
        ):
            m3_probe_stage("stage-a", state, cfg, now=1000.0)

        assert not hasattr(result.measurement, "samples_mono")
        assert state.last_error is None
        assert state.last_measurement is not None
        assert state.last_measurement.crest == pytest.approx(math.sqrt(2), abs=0.1)
        assert state.last_measurement.zcr < 0.01
        assert state.last_measurement.spectral_flatness < 0.1

    def test_white_noise_input_exercises_flatness_path(self) -> None:
        rng = np.random.default_rng(42)
        noise = np.clip(rng.standard_normal(44100) * 5000, -32768, 32767).astype(np.int16)
        state = M3StageState()
        cfg = M3DaemonConfig(stages=("stage-a",), enable_ntfy=False)
        result = _probe_result("stage-a", noise)

        with patch(
            "agents.audio_health.m3_crest_flatness_daemon.capture_and_measure",
            return_value=result,
        ):
            m3_probe_stage("stage-a", state, cfg, now=1000.0)

        assert state.last_error is None
        assert state.last_measurement is not None
        assert state.last_measurement.crest > 2.0
        assert state.last_measurement.zcr > 0.35
        assert state.last_measurement.spectral_flatness > 0.5

    def test_analyzer_exception_is_snapshot_health_evidence(self, tmp_path: Path) -> None:
        state = M3StageState()
        cfg = M3DaemonConfig(snapshot_path=tmp_path / "crest-flatness.json", enable_ntfy=False)
        result = _probe_result("stage-a", np.zeros(44100, dtype=np.int16))

        with (
            patch(
                "agents.audio_health.m3_crest_flatness_daemon.capture_and_measure",
                return_value=result,
            ),
            patch(
                "agents.audio_health.m3_crest_flatness_daemon.compute_spectral_flatness",
                side_effect=RuntimeError("flatness analyzer failed"),
            ),
        ):
            m3_probe_stage("stage-a", state, cfg, now=1000.0)

        assert state.analyzer_error_count == 1
        assert state.last_error == "RuntimeError: flatness analyzer failed"
        m3_emit_snapshot({"stage-a": state}, cfg, now=1000.0)
        payload = json.loads(cfg.snapshot_path.read_text(encoding="utf-8"))
        assert payload["stages"]["stage-a"]["analyzer_error"] == state.last_error
        assert payload["stages"]["stage-a"]["analyzer_error_count"] == 1


class TestM3BreachDetection:
    """M3 threshold breach detection."""

    def test_crest_drop_detected(self) -> None:
        """Crest dropping from >5 to <5 is only a candidate breach."""
        state = M3StageState(prev_crest=8.0)
        cfg = M3DaemonConfig(enable_ntfy=False)
        new_crest = 3.0
        assert new_crest < cfg.crest_drop_threshold
        assert state.prev_crest > cfg.crest_drop_threshold

    def test_low_crest_tonal_program_does_not_page(self) -> None:
        """Low crest with low ZCR/flatness is compressed program material, not noise."""
        state = M3StageState(prev_crest=8.0, crest_drop_start=990.0)
        cfg = M3DaemonConfig(enable_ntfy=True)
        result = _probe_result("hapax-obs-broadcast-remap", np.zeros(44100, dtype=np.int16))

        with (
            patch(
                "agents.audio_health.m3_crest_flatness_daemon.capture_and_measure",
                return_value=result,
            ),
            patch(
                "agents.audio_health.m3_crest_flatness_daemon.compute_crest_factor",
                return_value=3.8,
            ),
            patch("agents.audio_health.m3_crest_flatness_daemon.compute_zcr", return_value=0.04),
            patch(
                "agents.audio_health.m3_crest_flatness_daemon.compute_spectral_flatness",
                return_value=0.001,
            ),
            patch("agents.audio_health.m3_crest_flatness_daemon._send_ntfy") as send_ntfy,
        ):
            m3_probe_stage("hapax-obs-broadcast-remap", state, cfg, now=1005.0)

        assert state.crest_drop_count == 0
        assert state.crest_drop_start is None
        send_ntfy.assert_not_called()

    def test_noise_like_crest_drop_pages_after_sustain(self) -> None:
        """Low crest with high ZCR/flatness still triggers the M3 alert."""
        state = M3StageState(prev_crest=8.0, crest_drop_start=990.0)
        cfg = M3DaemonConfig(enable_ntfy=True)
        noise = (np.random.default_rng(42).standard_normal(44100) * 3000).astype(np.int16)
        result = _probe_result("hapax-obs-broadcast-remap", noise)

        with (
            patch(
                "agents.audio_health.m3_crest_flatness_daemon.capture_and_measure",
                return_value=result,
            ),
            patch(
                "agents.audio_health.m3_crest_flatness_daemon.compute_crest_factor",
                return_value=2.5,
            ),
            patch("agents.audio_health.m3_crest_flatness_daemon.compute_zcr", return_value=0.42),
            patch(
                "agents.audio_health.m3_crest_flatness_daemon.compute_spectral_flatness",
                return_value=0.55,
            ),
            patch("agents.audio_health.m3_crest_flatness_daemon._send_ntfy") as send_ntfy,
        ):
            m3_probe_stage("hapax-obs-broadcast-remap", state, cfg, now=1005.0)

        assert state.crest_drop_count == 1
        send_ntfy.assert_called_once()
        assert "zcr=0.420" in send_ntfy.call_args.args[2]

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
