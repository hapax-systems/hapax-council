"""Tests for ChimePlayer wiring into VoiceDaemon."""
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from agents.hapax_voice.config import VoiceConfig


class TestVoiceConfigChime:
    def test_chime_enabled_default(self):
        cfg = VoiceConfig()
        assert cfg.chime_enabled is False

    def test_chime_volume_default(self):
        cfg = VoiceConfig()
        assert cfg.chime_volume == 0.7

    def test_chime_dir_default(self):
        cfg = VoiceConfig()
        assert "chimes" in cfg.chime_dir


class TestDaemonChimeWiring:
    @patch("agents.hapax_voice.__main__.AudioInputStream")
    @patch("agents.hapax_voice.__main__.TTSManager")
    @patch("agents.hapax_voice.__main__.WakeWordDetector")
    @patch("agents.hapax_voice.__main__.HotkeyServer")
    @patch("agents.hapax_voice.__main__.ChimePlayer")
    def test_daemon_creates_chime_player(self, MockChime, *_):
        from agents.hapax_voice.__main__ import VoiceDaemon

        cfg = VoiceConfig()
        daemon = VoiceDaemon(cfg=cfg)
        MockChime.assert_called_once()

    @patch("agents.hapax_voice.__main__._screen_flash")
    @patch("agents.hapax_voice.__main__.AudioInputStream")
    @patch("agents.hapax_voice.__main__.TTSManager")
    @patch("agents.hapax_voice.__main__.WakeWordDetector")
    @patch("agents.hapax_voice.__main__.HotkeyServer")
    @patch("agents.hapax_voice.__main__.ChimePlayer")
    def test_on_wake_word_plays_activation_chime(self, MockChime, *_, **__):
        from agents.hapax_voice.__main__ import VoiceDaemon

        cfg = VoiceConfig(chime_enabled=True)
        daemon = VoiceDaemon(cfg=cfg)
        mock_player = MockChime.return_value

        # Mock pipeline start to avoid actual pipeline creation
        daemon._start_pipeline = AsyncMock()

        daemon._on_wake_word()
        mock_player.play.assert_called_once_with("activation")

    @patch("agents.hapax_voice.__main__._screen_flash")
    @patch("agents.hapax_voice.__main__.AudioInputStream")
    @patch("agents.hapax_voice.__main__.TTSManager")
    @patch("agents.hapax_voice.__main__.WakeWordDetector")
    @patch("agents.hapax_voice.__main__.HotkeyServer")
    @patch("agents.hapax_voice.__main__.ChimePlayer")
    def test_chime_disabled_uses_screen_flash(self, MockChime, _hotkey, _ww, _tts, _audio, mock_flash):
        from agents.hapax_voice.__main__ import VoiceDaemon

        cfg = VoiceConfig(chime_enabled=False)
        daemon = VoiceDaemon(cfg=cfg)
        mock_player = MockChime.return_value

        daemon._start_pipeline = AsyncMock()
        daemon._on_wake_word()
        mock_player.play.assert_not_called()
        mock_flash.assert_called_with("activation")
