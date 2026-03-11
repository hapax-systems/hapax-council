"""Tests for document scanner hotkey."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_scan_command_captures_and_extracts():
    from agents.hapax_voice.__main__ import VoiceDaemon
    from agents.hapax_voice.config import VoiceConfig

    cfg = VoiceConfig(webcam_enabled=False, screen_monitor_enabled=False)
    daemon = VoiceDaemon(cfg=cfg)

    # Mock the workspace monitor's webcam capturer
    daemon.workspace_monitor._webcam_capturer = MagicMock()
    daemon.workspace_monitor._webcam_capturer.capture.return_value = "fake-base64"
    daemon.workspace_monitor._webcam_capturer.has_camera.return_value = True
    daemon.workspace_monitor._webcam_capturer.reset_cooldown = MagicMock()

    with patch("agents.hapax_voice.__main__.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        await daemon._handle_hotkey("scan")
        # Should not crash, even if Gemini call fails
