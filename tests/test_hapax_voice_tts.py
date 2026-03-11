"""Tests for hapax_voice TTS tier abstraction and synthesis backends."""
from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agents.hapax_voice.tts import (
    TTSManager,
    _audio_to_pcm_int16,
    select_tier,
)


# ---------------------------------------------------------------------------
# select_tier
# ---------------------------------------------------------------------------


def test_select_tier_chime_is_piper() -> None:
    assert select_tier("chime") == "piper"


def test_select_tier_confirmation_is_piper() -> None:
    assert select_tier("confirmation") == "piper"


def test_select_tier_short_ack_is_piper() -> None:
    assert select_tier("short_ack") == "piper"


def test_select_tier_conversation_is_kokoro() -> None:
    assert select_tier("conversation") == "kokoro"


def test_select_tier_notification_is_kokoro() -> None:
    assert select_tier("notification") == "kokoro"


def test_select_tier_briefing_is_kokoro() -> None:
    assert select_tier("briefing") == "kokoro"


def test_select_tier_unknown_defaults_to_kokoro() -> None:
    assert select_tier("unknown_thing") == "kokoro"


# ---------------------------------------------------------------------------
# _audio_to_pcm_int16
# ---------------------------------------------------------------------------


def test_pcm_silence() -> None:
    silence = np.zeros(100, dtype=np.float32)
    pcm = _audio_to_pcm_int16(silence)
    assert len(pcm) == 200  # 100 samples * 2 bytes each
    assert pcm == b"\x00" * 200


def test_pcm_full_scale() -> None:
    full = np.ones(1, dtype=np.float32)
    pcm = _audio_to_pcm_int16(full)
    value = struct.unpack("<h", pcm)[0]
    assert value == 32767


def test_pcm_clipping() -> None:
    over = np.array([2.0], dtype=np.float32)
    pcm = _audio_to_pcm_int16(over)
    value = struct.unpack("<h", pcm)[0]
    assert value == 32767


def test_pcm_negative() -> None:
    neg = np.array([-1.0], dtype=np.float32)
    pcm = _audio_to_pcm_int16(neg)
    value = struct.unpack("<h", pcm)[0]
    assert value == -32767


# ---------------------------------------------------------------------------
# TTSManager — init and dispatch
# ---------------------------------------------------------------------------


def test_tts_manager_init_sets_voice() -> None:
    mgr = TTSManager(kokoro_voice="bf_emma")
    assert mgr.kokoro_voice == "bf_emma"


def test_tts_manager_lazy_init() -> None:
    mgr = TTSManager()
    assert mgr._piper_model is None
    assert mgr._kokoro_pipeline is None


def test_dispatch_chime_calls_piper() -> None:
    mgr = TTSManager()
    mgr._synthesize_piper = MagicMock(return_value=b"\x00\x00")
    mgr._synthesize_kokoro = MagicMock(return_value=b"\x00\x00")
    mgr.synthesize("ding", use_case="chime")
    mgr._synthesize_piper.assert_called_once_with("ding")
    mgr._synthesize_kokoro.assert_not_called()


def test_dispatch_conversation_calls_kokoro() -> None:
    mgr = TTSManager()
    mgr._synthesize_piper = MagicMock(return_value=b"\x00\x00")
    mgr._synthesize_kokoro = MagicMock(return_value=b"\x00\x00")
    mgr.synthesize("hello world", use_case="conversation")
    mgr._synthesize_kokoro.assert_called_once_with("hello world")
    mgr._synthesize_piper.assert_not_called()


# ---------------------------------------------------------------------------
# Piper synthesis (mocked)
# ---------------------------------------------------------------------------


def test_piper_missing_model_raises(tmp_path: object) -> None:
    mgr = TTSManager(piper_model_path=tmp_path / "nonexistent.onnx")  # type: ignore[operator]
    with pytest.raises(RuntimeError, match="not found"):
        mgr.synthesize("hello", use_case="chime")


def test_piper_synthesis_concatenates_chunks(tmp_path: object) -> None:
    model_path = tmp_path / "voice.onnx"  # type: ignore[operator]
    model_path.write_bytes(b"fake")

    mock_voice = MagicMock()
    mock_voice.synthesize_stream_raw.return_value = [b"\x01\x00", b"\x02\x00"]

    with patch("piper.PiperVoice") as MockPiper:
        MockPiper.load.return_value = mock_voice
        mgr = TTSManager(piper_model_path=model_path)
        result = mgr.synthesize("ok", use_case="confirmation")

    assert result == b"\x01\x00\x02\x00"
    mock_voice.synthesize_stream_raw.assert_called_once_with("ok")


def test_piper_import_error() -> None:
    mgr = TTSManager()
    with patch.dict("sys.modules", {"piper": None}):
        with pytest.raises(RuntimeError, match="piper-tts is not installed"):
            mgr._load_piper()


def test_piper_model_loaded_once(tmp_path: object) -> None:
    model_path = tmp_path / "voice.onnx"  # type: ignore[operator]
    model_path.write_bytes(b"fake")

    mock_voice = MagicMock()
    mock_voice.synthesize_stream_raw.return_value = [b"\x00\x00"]

    with patch("piper.PiperVoice") as MockPiper:
        MockPiper.load.return_value = mock_voice
        mgr = TTSManager(piper_model_path=model_path)
        mgr.synthesize("a", use_case="chime")
        mgr.synthesize("b", use_case="chime")

    MockPiper.load.assert_called_once()


# ---------------------------------------------------------------------------
# Kokoro synthesis (mocked)
# ---------------------------------------------------------------------------


def test_kokoro_synthesis_returns_pcm() -> None:
    import torch

    fake_audio = torch.zeros(480, dtype=torch.float32)
    mock_pipeline = MagicMock()
    mock_pipeline.return_value = [("hello", "hɛloʊ", fake_audio)]

    with patch("kokoro.KPipeline", return_value=mock_pipeline):
        mgr = TTSManager(kokoro_voice="af_heart")
        result = mgr.synthesize("hello", use_case="conversation")

    assert isinstance(result, bytes)
    assert len(result) == 480 * 2  # int16 = 2 bytes per sample
    mock_pipeline.assert_called_once_with("hello", voice="af_heart")


def test_kokoro_multi_chunk() -> None:
    import torch

    chunk1 = torch.ones(100, dtype=torch.float32) * 0.5
    chunk2 = torch.ones(200, dtype=torch.float32) * -0.5

    mock_pipeline = MagicMock()
    mock_pipeline.return_value = [
        ("hel", "hɛl", chunk1),
        ("lo", "loʊ", chunk2),
    ]

    with patch("kokoro.KPipeline", return_value=mock_pipeline):
        mgr = TTSManager()
        result = mgr.synthesize("hello", use_case="briefing")

    assert len(result) == (100 + 200) * 2


def test_kokoro_import_error() -> None:
    mgr = TTSManager()
    with patch.dict("sys.modules", {"kokoro": None}):
        with pytest.raises(RuntimeError, match="kokoro is not installed"):
            mgr._load_kokoro()


def test_kokoro_empty_output() -> None:
    mock_pipeline = MagicMock()
    mock_pipeline.return_value = []

    with patch("kokoro.KPipeline", return_value=mock_pipeline):
        mgr = TTSManager()
        result = mgr.synthesize("", use_case="conversation")

    assert result == b""


def test_kokoro_pipeline_loaded_once() -> None:
    import torch

    fake_audio = torch.zeros(10, dtype=torch.float32)
    mock_pipeline = MagicMock()
    mock_pipeline.return_value = [("x", "x", fake_audio)]

    with patch("kokoro.KPipeline", return_value=mock_pipeline) as MockK:
        mgr = TTSManager()
        mgr.synthesize("a", use_case="conversation")
        mgr.synthesize("b", use_case="conversation")

    MockK.assert_called_once()
