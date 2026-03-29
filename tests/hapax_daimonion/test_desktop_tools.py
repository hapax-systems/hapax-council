from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.desktop_tools import (
    DESKTOP_TOOL_SCHEMAS,
    handle_confirm_open_app,
    handle_focus_window,
    handle_get_desktop_state,
    handle_open_app,
    handle_switch_workspace,
)


class TestToolSchemas:
    def test_eight_desktop_tools_defined(self):
        assert len(DESKTOP_TOOL_SCHEMAS) == 8

    def test_schema_names(self):
        names = {s.name for s in DESKTOP_TOOL_SCHEMAS}
        assert names == {
            "focus_window",
            "switch_workspace",
            "open_app",
            "confirm_open_app",
            "get_desktop_state",
            "move_window",
            "resize_window",
            "close_window",
        }


class TestFocusWindow:
    @pytest.mark.asyncio
    async def test_focus_by_class(self):
        params = MagicMock()
        params.arguments = {"target": "google-chrome"}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_daimonion.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = True
            await handle_focus_window(params)

        mock_ipc.dispatch.assert_called_once_with("focuswindow", "class:google-chrome")
        params.result_callback.assert_awaited_once()
        result = params.result_callback.call_args[0][0]
        assert result["status"] == "focused"


class TestSwitchWorkspace:
    @pytest.mark.asyncio
    async def test_switch_to_number(self):
        params = MagicMock()
        params.arguments = {"workspace": 3}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_daimonion.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = True
            await handle_switch_workspace(params)

        mock_ipc.dispatch.assert_called_once_with("workspace", "3")


class TestOpenApp:
    @pytest.mark.asyncio
    async def test_open_returns_pending_confirmation(self):
        import agents.hapax_daimonion.desktop_tools as dt

        dt._pending_open = None  # Reset state

        params = MagicMock()
        params.arguments = {"command": "foot", "workspace": 2}
        params.result_callback = AsyncMock()

        await handle_open_app(params)

        result = params.result_callback.call_args[0][0]
        assert result["status"] == "pending_confirmation"
        assert dt._pending_open is not None

    @pytest.mark.asyncio
    async def test_confirm_launches_pending(self):
        import time

        import agents.hapax_daimonion.desktop_tools as dt

        dt._pending_open = {"command": "foot", "workspace": 2, "created_at": time.monotonic()}

        params = MagicMock()
        params.arguments = {}
        params.result_callback = AsyncMock()

        with patch("agents.hapax_daimonion.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = True
            await handle_confirm_open_app(params)

        mock_ipc.dispatch.assert_called_once_with("exec", "[workspace 2 silent] foot")
        assert dt._pending_open is None


class TestGetDesktopState:
    @pytest.mark.asyncio
    async def test_returns_window_list(self):
        from shared.hyprland import WindowInfo, WorkspaceInfo

        params = MagicMock()
        params.arguments = {}
        params.result_callback = AsyncMock()

        mock_clients = [
            WindowInfo("0x1", "foot", "term", 1, 10, 0, 0, 800, 600, False, False),
            WindowInfo("0x2", "chrome", "tab", 3, 20, 0, 0, 1920, 1080, False, False),
        ]
        mock_workspaces = [
            WorkspaceInfo(1, "1", 1, "foot", "DP-1"),
            WorkspaceInfo(3, "3", 1, "chrome", "DP-1"),
        ]

        with patch("agents.hapax_daimonion.desktop_tools._ipc") as mock_ipc:
            mock_ipc.get_clients.return_value = mock_clients
            mock_ipc.get_workspaces.return_value = mock_workspaces
            mock_ipc.get_active_window.return_value = mock_clients[0]
            await handle_get_desktop_state(params)

        result = params.result_callback.call_args[0][0]
        assert result["active_window"]["class"] == "foot"
        assert len(result["windows"]) == 2
        assert len(result["workspaces"]) == 2
