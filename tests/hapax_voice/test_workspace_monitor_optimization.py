"""Tests for WorkspaceMonitor deterministic hyprctl context optimization."""

from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_voice.workspace_monitor import WorkspaceMonitor


class TestDeterministicContext:
    @pytest.mark.asyncio
    async def test_builds_window_context_from_hyprctl(self):
        """Workspace monitor should query hyprctl for window list
        and include it in the analyzer prompt."""
        from shared.hyprland import WindowInfo

        mock_clients = [
            WindowInfo("0x1", "foot", "~/projects/ai-agents", 1, 10, 0, 0, 800, 600, False, False),
            WindowInfo(
                "0x2", "google-chrome", "cockpit-web", 3, 20, 0, 0, 1920, 1080, False, False
            ),
        ]

        with (
            patch("agents.hapax_voice.workspace_monitor.HyprlandIPC") as MockIPC,
            patch("agents.hapax_voice.workspace_monitor.HyprlandEventListener"),
            patch("agents.hapax_voice.workspace_monitor.ScreenCapturer"),
            patch("agents.hapax_voice.workspace_monitor.WorkspaceAnalyzer"),
        ):
            mock_ipc = MagicMock()
            mock_ipc.get_clients.return_value = mock_clients
            MockIPC.return_value = mock_ipc

            monitor = WorkspaceMonitor(enabled=True)
            context = monitor._build_deterministic_context()

        assert "foot" in context
        assert "google-chrome" in context
        assert "ai-agents" in context

    def test_returns_empty_when_disabled(self):
        """Disabled monitor returns empty string from deterministic context."""
        monitor = WorkspaceMonitor(enabled=False)
        assert monitor._build_deterministic_context() == ""

    def test_returns_empty_when_no_clients(self):
        """Returns empty string when hyprctl reports no open windows."""
        with (
            patch("agents.hapax_voice.workspace_monitor.HyprlandIPC") as MockIPC,
            patch("agents.hapax_voice.workspace_monitor.HyprlandEventListener"),
            patch("agents.hapax_voice.workspace_monitor.ScreenCapturer"),
            patch("agents.hapax_voice.workspace_monitor.WorkspaceAnalyzer"),
        ):
            mock_ipc = MagicMock()
            mock_ipc.get_clients.return_value = []
            MockIPC.return_value = mock_ipc

            monitor = WorkspaceMonitor(enabled=True)
            context = monitor._build_deterministic_context()

        assert context == ""

    def test_context_includes_workspace_id(self):
        """Context string includes workspace ID for each window."""
        from shared.hyprland import WindowInfo

        mock_clients = [
            WindowInfo("0x1", "foot", "bash", 5, 10, 0, 0, 800, 600, False, False),
        ]

        with (
            patch("agents.hapax_voice.workspace_monitor.HyprlandIPC") as MockIPC,
            patch("agents.hapax_voice.workspace_monitor.HyprlandEventListener"),
            patch("agents.hapax_voice.workspace_monitor.ScreenCapturer"),
            patch("agents.hapax_voice.workspace_monitor.WorkspaceAnalyzer"),
        ):
            mock_ipc = MagicMock()
            mock_ipc.get_clients.return_value = mock_clients
            MockIPC.return_value = mock_ipc

            monitor = WorkspaceMonitor(enabled=True)
            context = monitor._build_deterministic_context()

        assert "workspace 5" in context
