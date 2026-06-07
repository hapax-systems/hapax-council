"""Tests for audio_perception models — loading and graceful fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from agents.audio_perception.models import (
    CLAP_SAMPLE_RATE,
    ESSENTIA_SAMPLE_RATE,
    PYANNOTE_SAMPLE_RATE,
    SAMPLE_RATE,
    _resample,
    load_clap,
    load_essentia,
    load_pyannote,
)


class TestResample:
    def test_same_rate_returns_identity(self) -> None:
        audio = np.array([1.0, 2.0, 3.0, 4.0])
        result = _resample(audio, SAMPLE_RATE, SAMPLE_RATE)
        np.testing.assert_array_equal(result, audio)

    def test_clap_rate_is_native_capture_rate(self) -> None:
        audio = np.ones(SAMPLE_RATE, dtype=np.float32)
        result = _resample(audio, SAMPLE_RATE, CLAP_SAMPLE_RATE)
        assert len(result) == CLAP_SAMPLE_RATE

    def test_essentia_rate_downsamples_to_algorithm_requirement(self) -> None:
        audio = np.ones(SAMPLE_RATE, dtype=np.float32)
        result = _resample(audio, SAMPLE_RATE, ESSENTIA_SAMPLE_RATE)
        assert len(result) == ESSENTIA_SAMPLE_RATE

    def test_pyannote_rate_downsamples_to_model_requirement(self) -> None:
        audio = np.ones(SAMPLE_RATE, dtype=np.float32)
        result = _resample(audio, SAMPLE_RATE, PYANNOTE_SAMPLE_RATE)
        assert len(result) == PYANNOTE_SAMPLE_RATE


class TestLoadClap:
    def test_returns_none_on_import_error(self) -> None:
        with patch.dict("sys.modules", {"laion_clap": None}):
            result = load_clap()
        assert result is None

    def test_returns_none_on_exception(self) -> None:
        mock_module = MagicMock()
        mock_module.CLAP_Module.side_effect = RuntimeError("model load failed")
        with patch.dict("sys.modules", {"laion_clap": mock_module}):
            result = load_clap()
        assert result is None


class TestLoadEssentia:
    def test_returns_none_on_import_error(self) -> None:
        with patch.dict("sys.modules", {"essentia": None, "essentia.standard": None}):
            result = load_essentia()
        assert result is None


class TestLoadPyannote:
    def test_returns_none_on_import_error(self) -> None:
        with patch.dict(
            "sys.modules",
            {
                "pyannote": None,
                "pyannote.audio": None,
                "pyannote.audio.pipelines": None,
            },
        ):
            result = load_pyannote()
        assert result is None
