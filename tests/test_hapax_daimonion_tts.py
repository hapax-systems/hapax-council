"""Tests for hapax_daimonion TTS tier abstraction and Kokoro synthesis backend."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from agents.hapax_daimonion.tts import (
    TTSManager,
    select_tier,
)

# ---------------------------------------------------------------------------
# select_tier
# ---------------------------------------------------------------------------


def test_select_tier_conversation_is_kokoro() -> None:
    assert select_tier("conversation") == "kokoro"


def test_select_tier_notification_is_kokoro() -> None:
    assert select_tier("notification") == "kokoro"


def test_select_tier_briefing_is_kokoro() -> None:
    assert select_tier("briefing") == "kokoro"


def test_select_tier_unknown_defaults_to_kokoro() -> None:
    assert select_tier("unknown_thing") == "kokoro"


# ---------------------------------------------------------------------------
# TTSManager — init
# ---------------------------------------------------------------------------


def test_tts_manager_init_sets_voice() -> None:
    mgr = TTSManager(voice_id="bf_emma")
    assert mgr._voice_id == "bf_emma"


def test_tts_manager_default_voice() -> None:
    """Default voice is af_heart."""
    mgr = TTSManager()
    assert mgr._voice_id == "af_heart"


# ---------------------------------------------------------------------------
# Kokoro synthesis (mocked pipeline)
# ---------------------------------------------------------------------------


def _make_mock_pipeline(audio_samples: np.ndarray | None = None) -> MagicMock:
    """Create a mock Kokoro pipeline that yields one chunk."""
    pipeline = MagicMock()
    if audio_samples is not None:
        pipeline.return_value = iter([("hello", "hɛˈloʊ", audio_samples)])
    else:
        # No audio produced
        pipeline.return_value = iter([("hello", "hɛˈloʊ", None)])
    return pipeline


def test_kokoro_synthesis_returns_pcm() -> None:
    """Mock Kokoro pipeline, verify PCM output."""
    samples = np.array([0.0, 0.5, -0.5, 1.0], dtype=np.float32)
    mock_pipeline = _make_mock_pipeline(samples)

    mgr = TTSManager()
    mgr._pipeline = mock_pipeline
    result = mgr.synthesize("hello")

    assert isinstance(result, bytes)
    assert len(result) == len(samples) * 2  # int16 = 2 bytes per sample


def test_kokoro_empty_text_returns_empty() -> None:
    """Empty text returns b'' without calling pipeline."""
    mgr = TTSManager()
    assert mgr.synthesize("") == b""
    assert mgr.synthesize("   ") == b""


def test_kokoro_no_audio_output() -> None:
    """Pipeline yields None audio, returns b''."""
    mock_pipeline = _make_mock_pipeline(None)

    mgr = TTSManager()
    mgr._pipeline = mock_pipeline
    result = mgr.synthesize("hello")

    assert result == b""


def test_kokoro_pipeline_loaded_once() -> None:
    """Lazy-init singleton pattern — pipeline created once, reused."""
    samples = np.array([0.0], dtype=np.float32)

    mock_pipeline = MagicMock()
    mock_pipeline.side_effect = [
        iter([("a", "a", samples)]),
        iter([("b", "b", samples)]),
    ]

    mgr = TTSManager()
    mgr._pipeline = mock_pipeline
    mgr.synthesize("a")
    mgr.synthesize("b")

    # Pipeline was pre-injected; verify it wasn't replaced
    assert mgr._pipeline is mock_pipeline
    assert mock_pipeline.call_count == 2


def test_kokoro_torch_tensor_converted() -> None:
    """If audio has .numpy() method (torch tensor), it gets converted."""
    raw = np.array([0.5, -0.5], dtype=np.float32)
    tensor = MagicMock()
    tensor.numpy.return_value = raw

    mock_pipeline = MagicMock()
    mock_pipeline.return_value = iter([("hi", "haɪ", tensor)])

    mgr = TTSManager()
    mgr._pipeline = mock_pipeline
    result = mgr.synthesize("hi")

    tensor.numpy.assert_called_once()
    assert len(result) == 4  # 2 samples * 2 bytes


def test_kokoro_preload() -> None:
    """preload() triggers lazy init."""
    with patch("agents.hapax_daimonion.tts.TTSManager._get_pipeline") as mock_get:
        mgr = TTSManager()
        mgr.preload()
        mock_get.assert_called_once()
