"""Tests for audio_perception models — loading and graceful fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from agents.audio_perception.models import (
    _resample,
    load_clap,
    load_essentia,
    load_pyannote,
)


class TestResample:
    def test_same_rate_returns_identity(self) -> None:
        audio = np.array([1.0, 2.0, 3.0, 4.0])
        result = _resample(audio, 44100, 44100)
        np.testing.assert_array_equal(result, audio)

    def test_upsample_increases_length(self) -> None:
        audio = np.ones(44100, dtype=np.float32)
        result = _resample(audio, 44100, 48000)
        assert len(result) == 48000

    def test_downsample_decreases_length(self) -> None:
        audio = np.ones(44100, dtype=np.float32)
        result = _resample(audio, 44100, 16000)
        assert len(result) == 16000


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
