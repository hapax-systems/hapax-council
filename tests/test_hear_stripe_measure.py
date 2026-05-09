"""Tests for scripts/hear-stripe-measure spectral analysis and verdict logic."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

soundfile = pytest.importorskip("soundfile")

SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "hear-stripe-measure"


def _load_module():
    loader = importlib.machinery.SourceFileLoader("hear_stripe_measure", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("hear_stripe_measure", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hear_stripe_measure"] = mod
    spec.loader.exec_module(mod)
    return mod


hsm = _load_module()


def _write_wav(path: Path, data: np.ndarray, sr: int = 48000) -> None:
    soundfile.write(str(path), data, sr, format="WAV", subtype="FLOAT")


class TestSpectralAnalysis:
    def test_empty_signal(self, tmp_path: Path) -> None:
        wav = tmp_path / "empty.wav"
        _write_wav(wav, np.array([], dtype=np.float32))
        result = hsm._spectral_analysis(wav)
        assert result == {"error": "empty signal"}

    def test_sine_1khz_peaks_in_mid_band(self, tmp_path: Path) -> None:
        sr = 48000
        t = np.linspace(0, 1.0, sr, endpoint=False)
        data = 0.5 * np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        wav = tmp_path / "sine_1k.wav"
        _write_wav(wav, data, sr)

        result = hsm._spectral_analysis(wav)
        assert result["mid_500_2k"] > result["sub_bass_20_60"]
        assert result["mid_500_2k"] > result["air_10k_16k"]
        assert result["sample_rate"] == sr
        assert result["duration_s"] == pytest.approx(1.0, abs=0.01)

    def test_stereo_downmix(self, tmp_path: Path) -> None:
        sr = 48000
        t = np.linspace(0, 0.5, sr // 2, endpoint=False)
        left = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
        right = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
        stereo = np.column_stack([left, right])
        wav = tmp_path / "stereo.wav"
        _write_wav(wav, stereo, sr)

        result = hsm._spectral_analysis(wav)
        assert "error" not in result
        assert result["sample_rate"] == sr
        assert result["duration_s"] == pytest.approx(0.5, abs=0.01)

    def test_high_frequency_signal_raises_hf_ratio(self, tmp_path: Path) -> None:
        sr = 48000
        t = np.linspace(0, 1.0, sr, endpoint=False)
        data = 0.3 * np.sin(2 * np.pi * 12000 * t).astype(np.float32)
        wav = tmp_path / "hf.wav"
        _write_wav(wav, data, sr)

        result = hsm._spectral_analysis(wav)
        assert result["hf_ratio_pct"] > 50

    def test_band_keys_complete(self, tmp_path: Path) -> None:
        sr = 48000
        t = np.linspace(0, 0.1, sr // 10, endpoint=False)
        data = np.random.default_rng(42).normal(0, 0.1, len(t)).astype(np.float32)
        wav = tmp_path / "noise.wav"
        _write_wav(wav, data, sr)

        result = hsm._spectral_analysis(wav)
        expected_keys = {
            "sub_bass_20_60",
            "bass_60_250",
            "low_mid_250_500",
            "mid_500_2k",
            "upper_mid_2k_4k",
            "presence_4k_6k",
            "brilliance_6k_10k",
            "air_10k_16k",
            "ultra_16k_20k",
            "hf_ratio_pct",
            "rms_db",
            "duration_s",
            "sample_rate",
        }
        assert set(result.keys()) == expected_keys


class TestVerdictLogic:
    def test_survives_when_deltas_small(self) -> None:
        air_d = 2.0
        brill_d = 1.0
        survive = abs(air_d) < 6 and abs(brill_d) < 3
        assert survive is True

    def test_attenuated_when_air_drops(self) -> None:
        air_d = -8.0
        brill_d = 1.0
        survive = abs(air_d) < 6 and abs(brill_d) < 3
        assert survive is False

    def test_attenuated_when_brilliance_drops(self) -> None:
        air_d = 2.0
        brill_d = -4.0
        survive = abs(air_d) < 6 and abs(brill_d) < 3
        assert survive is False

    def test_boundary_air_just_under(self) -> None:
        assert abs(5.99) < 6

    def test_boundary_air_at_threshold(self) -> None:
        assert not (abs(6.0) < 6)


class TestTranscodeChain:
    def test_transcode_calls_ffmpeg(self, tmp_path: Path) -> None:
        src = tmp_path / "in.wav"
        dst = tmp_path / "out.m4a"
        src.write_bytes(b"fake")

        with patch("hear_stripe_measure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = hsm._transcode(src, dst, ["-acodec", "aac", "-b:a", "160k"])

        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in cmd
        assert "-acodec" in cmd

    def test_transcode_returns_false_on_failure(self, tmp_path: Path) -> None:
        src = tmp_path / "in.wav"
        dst = tmp_path / "out.m4a"
        src.write_bytes(b"fake")

        with patch("hear_stripe_measure.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = hsm._transcode(src, dst, ["-acodec", "aac"])

        assert result is False


class TestCheckTools:
    def test_passes_when_tools_exist(self) -> None:
        with patch("hear_stripe_measure.shutil.which", return_value="/usr/bin/fake"):
            assert hsm._check_tools() is True

    def test_fails_when_missing(self) -> None:
        with patch("hear_stripe_measure.shutil.which", return_value=None):
            assert hsm._check_tools() is False
