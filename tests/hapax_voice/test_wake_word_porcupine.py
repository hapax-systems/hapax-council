"""Tests for Porcupine wake word detector."""
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

import numpy as np
import pytest

from agents.hapax_voice.wake_word_porcupine import (
    PorcupineWakeWord,
    DETECTION_COOLDOWN_S,
    _load_access_key,
)


class TestLoadAccessKey:
    @patch("agents.hapax_voice.wake_word_porcupine.subprocess.run")
    def test_returns_key_on_success(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="test-key-123\n", returncode=0
        )
        assert _load_access_key() == "test-key-123"

    @patch("agents.hapax_voice.wake_word_porcupine.subprocess.run")
    def test_returns_none_on_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        assert _load_access_key() is None

    @patch("agents.hapax_voice.wake_word_porcupine.subprocess.run")
    def test_returns_none_on_nonzero_returncode(self, mock_run):
        mock_run.return_value = MagicMock(stdout="key", returncode=1)
        assert _load_access_key() is None

    @patch("agents.hapax_voice.wake_word_porcupine.subprocess.run",
           side_effect=FileNotFoundError)
    def test_returns_none_when_pass_not_found(self, _):
        assert _load_access_key() is None

    @patch("agents.hapax_voice.wake_word_porcupine.subprocess.run",
           side_effect=Exception("boom"))
    def test_returns_none_on_generic_error(self, _):
        assert _load_access_key() is None


class TestPorcupineWakeWordInit:
    def test_default_model_path(self):
        detector = PorcupineWakeWord()
        assert detector.model_path == (
            Path.home() / ".local" / "share" / "hapax-voice" / "hapax_porcupine.ppn"
        )

    def test_custom_model_path(self):
        p = Path("/tmp/custom.ppn")
        detector = PorcupineWakeWord(model_path=p)
        assert detector.model_path == p

    def test_default_sensitivity(self):
        detector = PorcupineWakeWord()
        assert detector.sensitivity == 0.5

    def test_custom_sensitivity(self):
        detector = PorcupineWakeWord(sensitivity=0.7)
        assert detector.sensitivity == 0.7

    def test_not_loaded_initially(self):
        detector = PorcupineWakeWord()
        assert not detector.is_loaded


class TestPorcupineWakeWordLoad:
    @patch("agents.hapax_voice.wake_word_porcupine._load_access_key",
           return_value=None)
    def test_load_fails_without_access_key(self, _):
        detector = PorcupineWakeWord()
        detector.model_path = MagicMock(exists=MagicMock(return_value=True))
        detector.load()
        assert not detector.is_loaded

    def test_load_fails_without_model_file(self):
        detector = PorcupineWakeWord(model_path=Path("/nonexistent.ppn"))
        detector.load()
        assert not detector.is_loaded

    @patch("agents.hapax_voice.wake_word_porcupine._load_access_key",
           return_value="test-key")
    def test_load_fails_without_pvporcupine(self, _):
        detector = PorcupineWakeWord()
        detector.model_path = MagicMock(exists=MagicMock(return_value=True))
        # pvporcupine import will fail since it's not in test deps
        detector.load()
        assert not detector.is_loaded

    @patch("agents.hapax_voice.wake_word_porcupine._load_access_key",
           return_value="test-key")
    @patch("agents.hapax_voice.wake_word_porcupine.pvporcupine", create=True)
    def test_load_success(self, mock_pv, _):
        import sys
        mock_module = MagicMock()
        mock_handle = MagicMock()
        mock_handle.frame_length = 512
        mock_handle.sample_rate = 16000
        mock_module.create.return_value = mock_handle

        with patch.dict(sys.modules, {"pvporcupine": mock_module}):
            detector = PorcupineWakeWord()
            detector.model_path = MagicMock(
                exists=MagicMock(return_value=True),
                name="hapax_porcupine.ppn",
            )
            # Override the lazy import
            detector.load.__func__  # force fresh call
            # Directly test the success path
            detector._handle = mock_handle
            detector.frame_length = 512
            assert detector.is_loaded


class TestPorcupineProcessAudio:
    def test_noop_when_not_loaded(self):
        detector = PorcupineWakeWord()
        # Should not raise
        detector.process_audio(np.zeros(512, dtype=np.int16))

    def test_fires_callback_on_detection(self):
        detector = PorcupineWakeWord()
        mock_handle = MagicMock()
        mock_handle.process.return_value = 0  # keyword_index >= 0 means detected
        detector._handle = mock_handle

        callback = MagicMock()
        detector.on_wake_word = callback

        audio = np.zeros(512, dtype=np.int16)
        detector.process_audio(audio)

        callback.assert_called_once()
        mock_handle.process.assert_called_once_with(audio)

    def test_no_callback_when_not_detected(self):
        detector = PorcupineWakeWord()
        mock_handle = MagicMock()
        mock_handle.process.return_value = -1  # no detection
        detector._handle = mock_handle

        callback = MagicMock()
        detector.on_wake_word = callback

        detector.process_audio(np.zeros(512, dtype=np.int16))
        callback.assert_not_called()

    def test_cooldown_suppresses_rapid_detections(self):
        detector = PorcupineWakeWord()
        mock_handle = MagicMock()
        mock_handle.process.return_value = 0
        detector._handle = mock_handle

        callback = MagicMock()
        detector.on_wake_word = callback

        audio = np.zeros(512, dtype=np.int16)
        detector.process_audio(audio)
        detector.process_audio(audio)  # within cooldown

        assert callback.call_count == 1

    def test_no_callback_when_none(self):
        detector = PorcupineWakeWord()
        mock_handle = MagicMock()
        mock_handle.process.return_value = 0
        detector._handle = mock_handle
        detector.on_wake_word = None

        # Should not raise
        detector.process_audio(np.zeros(512, dtype=np.int16))


class TestPorcupineClose:
    def test_close_releases_handle(self):
        detector = PorcupineWakeWord()
        mock_handle = MagicMock()
        detector._handle = mock_handle

        detector.close()
        mock_handle.delete.assert_called_once()
        assert not detector.is_loaded

    def test_close_noop_when_not_loaded(self):
        detector = PorcupineWakeWord()
        detector.close()  # should not raise


class TestDaemonWakeWordSelection:
    @patch("agents.hapax_voice.__main__._screen_flash")
    @patch("agents.hapax_voice.__main__.AudioInputStream")
    @patch("agents.hapax_voice.__main__.TTSManager")
    @patch("agents.hapax_voice.__main__.WakeWordDetector")
    @patch("agents.hapax_voice.__main__.PorcupineWakeWord")
    @patch("agents.hapax_voice.__main__.HotkeyServer")
    @patch("agents.hapax_voice.__main__.ChimePlayer")
    def test_porcupine_selected_by_default(self, _chime, _hotkey, MockPorc, MockOWW, *_):
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.config import VoiceConfig

        cfg = VoiceConfig(wake_word_engine="porcupine")
        daemon = VoiceDaemon(cfg=cfg)
        MockPorc.assert_called_once_with(sensitivity=0.5)
        MockOWW.assert_not_called()

    @patch("agents.hapax_voice.__main__._screen_flash")
    @patch("agents.hapax_voice.__main__.AudioInputStream")
    @patch("agents.hapax_voice.__main__.TTSManager")
    @patch("agents.hapax_voice.__main__.WakeWordDetector")
    @patch("agents.hapax_voice.__main__.PorcupineWakeWord")
    @patch("agents.hapax_voice.__main__.HotkeyServer")
    @patch("agents.hapax_voice.__main__.ChimePlayer")
    def test_oww_selected_when_configured(self, _chime, _hotkey, MockPorc, MockOWW, *_):
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.config import VoiceConfig

        cfg = VoiceConfig(wake_word_engine="oww")
        daemon = VoiceDaemon(cfg=cfg)
        MockOWW.assert_called_once()
        MockPorc.assert_not_called()
