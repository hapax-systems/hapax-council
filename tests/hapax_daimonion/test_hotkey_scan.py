"""Tests for document scanner hotkey."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_scan_command_captures_and_extracts():
    from agents.hapax_daimonion.__main__ import VoiceDaemon
    from agents.hapax_daimonion.config import DaimonionConfig

    cfg = DaimonionConfig(webcam_enabled=False, screen_monitor_enabled=False)
    daemon = VoiceDaemon(cfg=cfg)

    # Mock the workspace monitor's webcam capturer
    daemon.workspace_monitor._webcam_capturer = MagicMock()
    daemon.workspace_monitor._webcam_capturer.capture.return_value = "fake-base64"
    daemon.workspace_monitor._webcam_capturer.has_camera.return_value = True
    daemon.workspace_monitor._webcam_capturer.reset_cooldown = MagicMock()

    with patch("agents.hapax_daimonion.session_events.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        await daemon._handle_hotkey("scan")
        # Should not crash, even if Gemini call fails
