"""Tests for TTS speed parameter passthrough (AMBIENT register density modulation)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_tts_synthesize_accepts_speed_param() -> None:
    """TTSManager.synthesize must accept speed kwarg without error."""
    from agents.hapax_daimonion.tts import TTSManager

    mgr = TTSManager.__new__(TTSManager)
    mgr._pipeline = None
    mgr._voice_id = "af_heart"
    with patch.object(mgr, "_get_pipeline", return_value=MagicMock(return_value=[])):
        with patch.object(mgr, "_synthesize_kokoro", return_value=b"") as mock_kokoro:
            mgr.synthesize("test", "proactive", speed=0.85)
            mock_kokoro.assert_called_once()
            # Verify speed was passed through
            _, kwargs = mock_kokoro.call_args
            assert kwargs["speed"] == 0.85


def test_tts_synthesize_default_speed_is_one() -> None:
    """TTSManager.synthesize defaults to speed=1.0 when not specified."""
    from agents.hapax_daimonion.tts import TTSManager

    mgr = TTSManager.__new__(TTSManager)
    mgr._pipeline = None
    mgr._voice_id = "af_heart"
    with patch.object(mgr, "_get_pipeline", return_value=MagicMock(return_value=[])):
        with patch.object(mgr, "_synthesize_kokoro", return_value=b"") as mock_kokoro:
            mgr.synthesize("test", "proactive")
            mock_kokoro.assert_called_once()
            _, kwargs = mock_kokoro.call_args
            assert kwargs["speed"] == 1.0


def test_synthesize_kokoro_passes_speed_to_pipeline() -> None:
    """_synthesize_kokoro passes speed kwarg to the Kokoro pipeline call."""
    from agents.hapax_daimonion.tts import TTSManager

    mgr = TTSManager.__new__(TTSManager)
    mgr._voice_id = "af_heart"
    mock_pipeline = MagicMock(return_value=[])
    mgr._pipeline = mock_pipeline
    mgr._synthesize_kokoro("hello world", speed=0.92)
    mock_pipeline.assert_called_once_with("hello world", voice="af_heart", speed=0.92)
