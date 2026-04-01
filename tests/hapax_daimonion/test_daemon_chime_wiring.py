"""Tests for ChimePlayer wiring into VoiceDaemon."""

from unittest.mock import MagicMock, patch

from agents.hapax_daimonion.config import DaimonionConfig


class TestDaimonionConfigChime:
    def test_chime_enabled_default(self):
        cfg = DaimonionConfig()
        assert cfg.chime_enabled is False

    def test_chime_volume_default(self):
        cfg = DaimonionConfig()
        assert cfg.chime_volume == 0.7

    def test_chime_dir_default(self):
        cfg = DaimonionConfig()
        assert "chimes" in cfg.chime_dir


class TestDaemonChimeWiring:
    @patch("agents.hapax_daimonion.daemon.AudioInputStream")
    @patch("agents.hapax_daimonion.daemon.TTSManager")
    @patch("agents.hapax_daimonion.daemon.HotkeyServer")
    @patch("agents.hapax_daimonion.daemon.ChimePlayer")
    def test_daemon_creates_chime_player(self, MockChime, *_):
        from agents.hapax_daimonion.__main__ import VoiceDaemon

        cfg = DaimonionConfig()
        VoiceDaemon(cfg=cfg)
        MockChime.assert_called_once()

    def test_acknowledge_plays_chime_when_enabled(self):
        """_acknowledge('activation') plays chime when chime_enabled=True."""
        from tests.hapax_daimonion.conftest import make_stub_daemon

        daemon = make_stub_daemon()
        daemon.cfg.chime_enabled = True
        mock_player = MagicMock()
        daemon.chime_player = mock_player

        daemon._acknowledge("activation")
        mock_player.play.assert_called_once_with("activation")

    @patch("agents.hapax_daimonion.session_events.screen_flash")
    def test_acknowledge_uses_screen_flash_when_disabled(self, mock_flash):
        """_acknowledge('activation') uses screen flash when chime_enabled=False."""
        from tests.hapax_daimonion.conftest import make_stub_daemon

        daemon = make_stub_daemon()
        daemon.cfg.chime_enabled = False
        mock_player = MagicMock()
        daemon.chime_player = mock_player

        daemon._acknowledge("activation")
        mock_player.play.assert_not_called()
        mock_flash.assert_called_with("activation")
