"""Surface 5: Desktop tools — Hyprland IPC integration.

Tests that desktop tool handlers dispatch to Hyprland correctly
and that the open_app confirmation flow works end-to-end.

Key implementation details (verified against source):
- Module-level _ipc singleton: patch agents.hapax_voice.desktop_tools._ipc
- result_callback receives a dict, not a string
- focus_window uses "target" arg (class name), not "window_title"
- switch_workspace uses "workspace" arg (int), not "workspace_id"
- open_app uses "command" arg, not "app_name"
- confirm_open_app calls _ipc.dispatch, not subprocess directly
- get_desktop_state uses get_clients() (list) + get_active_window() + get_workspaces()
- WindowInfo: app_class (not class_name), no workspace_name field
- WorkspaceInfo: no active field
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.desktop_tools import (
    DESKTOP_TOOL_SCHEMAS,
    handle_confirm_open_app,
    handle_focus_window,
    handle_get_desktop_state,
    handle_open_app,
    handle_switch_workspace,
)
import agents.hapax_voice.desktop_tools as desktop_mod


def _make_params(arguments: dict):
    """Create a mock FunctionCallParams-like object."""
    params = MagicMock()
    params.arguments = arguments
    params.result_callback = AsyncMock()
    return params


# ---------------------------------------------------------------------------
# Schema surface
# ---------------------------------------------------------------------------


class TestDesktopToolSchemas:
    """Desktop tool schemas are correctly defined."""

    def test_five_desktop_tools(self):
        assert len(DESKTOP_TOOL_SCHEMAS) == 5

    def test_schema_names(self):
        names = [s.name for s in DESKTOP_TOOL_SCHEMAS]
        assert "focus_window" in names
        assert "switch_workspace" in names
        assert "open_app" in names
        assert "confirm_open_app" in names
        assert "get_desktop_state" in names

    def test_focus_window_requires_target(self):
        schema = next(s for s in DESKTOP_TOOL_SCHEMAS if s.name == "focus_window")
        assert "target" in schema.required

    def test_switch_workspace_requires_workspace(self):
        schema = next(s for s in DESKTOP_TOOL_SCHEMAS if s.name == "switch_workspace")
        assert "workspace" in schema.required

    def test_open_app_requires_command(self):
        schema = next(s for s in DESKTOP_TOOL_SCHEMAS if s.name == "open_app")
        assert "command" in schema.required

    def test_confirm_open_app_no_required_fields(self):
        schema = next(s for s in DESKTOP_TOOL_SCHEMAS if s.name == "confirm_open_app")
        assert schema.required == []

    def test_get_desktop_state_no_required_fields(self):
        schema = next(s for s in DESKTOP_TOOL_SCHEMAS if s.name == "get_desktop_state")
        assert schema.required == []


# ---------------------------------------------------------------------------
# focus_window handler
# ---------------------------------------------------------------------------


class TestFocusWindow:
    @pytest.mark.asyncio
    async def test_dispatches_focuswindow_on_success(self):
        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = True
        params = _make_params({"target": "foot"})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_focus_window(params)

        mock_ipc.dispatch.assert_called_once_with("focuswindow", "class:foot")
        params.result_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_result_contains_focused_status_on_success(self):
        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = True
        params = _make_params({"target": "google-chrome"})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_focus_window(params)

        result = params.result_callback.call_args.args[0]
        assert result["status"] == "focused"
        assert result["target"] == "google-chrome"

    @pytest.mark.asyncio
    async def test_result_contains_failed_status_on_failure(self):
        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = False
        params = _make_params({"target": "nonexistent-app"})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_focus_window(params)

        result = params.result_callback.call_args.args[0]
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_always_calls_result_callback(self):
        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = False
        params = _make_params({"target": "nonexistent"})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_focus_window(params)

        params.result_callback.assert_called_once()


# ---------------------------------------------------------------------------
# switch_workspace handler
# ---------------------------------------------------------------------------


class TestSwitchWorkspace:
    @pytest.mark.asyncio
    async def test_dispatches_workspace_command(self):
        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = True
        params = _make_params({"workspace": 3})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_switch_workspace(params)

        mock_ipc.dispatch.assert_called_once_with("workspace", "3")

    @pytest.mark.asyncio
    async def test_result_contains_switched_status(self):
        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = True
        params = _make_params({"workspace": 3})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_switch_workspace(params)

        result = params.result_callback.call_args.args[0]
        assert result["status"] == "switched"
        assert result["workspace"] == 3

    @pytest.mark.asyncio
    async def test_result_contains_failed_status_on_failure(self):
        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = False
        params = _make_params({"workspace": 99})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_switch_workspace(params)

        result = params.result_callback.call_args.args[0]
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# open_app and confirm_open_app confirmation flow
# ---------------------------------------------------------------------------


class TestOpenAppConfirmation:
    def setup_method(self):
        # Reset global pending state before each test
        desktop_mod._pending_open = None

    @pytest.mark.asyncio
    async def test_open_app_stores_pending_and_returns_pending_confirmation(self):
        params = _make_params({"command": "foot"})

        await handle_open_app(params)

        result = params.result_callback.call_args.args[0]
        assert result["status"] == "pending_confirmation"
        assert desktop_mod._pending_open is not None
        assert desktop_mod._pending_open["command"] == "foot"

    @pytest.mark.asyncio
    async def test_open_app_message_mentions_confirm(self):
        params = _make_params({"command": "google-chrome-stable"})

        await handle_open_app(params)

        result = params.result_callback.call_args.args[0]
        assert "confirm" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_open_app_stores_workspace_when_provided(self):
        params = _make_params({"command": "foot", "workspace": 2})

        await handle_open_app(params)

        assert desktop_mod._pending_open["workspace"] == 2

    @pytest.mark.asyncio
    async def test_open_app_stores_none_workspace_when_absent(self):
        params = _make_params({"command": "foot"})

        await handle_open_app(params)

        assert desktop_mod._pending_open["workspace"] is None

    @pytest.mark.asyncio
    async def test_confirm_launches_app_via_ipc_dispatch(self):
        # Stage the pending state first
        setup_params = _make_params({"command": "foot"})
        await handle_open_app(setup_params)

        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = True
        confirm_params = _make_params({})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_confirm_open_app(confirm_params)

        mock_ipc.dispatch.assert_called_once_with("exec", "foot")
        confirm_params.result_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_uses_workspace_exec_when_workspace_set(self):
        setup_params = _make_params({"command": "foot", "workspace": 4})
        await handle_open_app(setup_params)

        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = True
        confirm_params = _make_params({})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_confirm_open_app(confirm_params)

        mock_ipc.dispatch.assert_called_once_with("exec", "[workspace 4 silent] foot")

    @pytest.mark.asyncio
    async def test_confirm_returns_launched_status_on_success(self):
        setup_params = _make_params({"command": "obsidian"})
        await handle_open_app(setup_params)

        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = True
        confirm_params = _make_params({})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_confirm_open_app(confirm_params)

        result = confirm_params.result_callback.call_args.args[0]
        assert result["status"] == "launched"
        assert result["command"] == "obsidian"

    @pytest.mark.asyncio
    async def test_confirm_returns_failed_status_on_ipc_failure(self):
        setup_params = _make_params({"command": "bad-app"})
        await handle_open_app(setup_params)

        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = False
        confirm_params = _make_params({})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_confirm_open_app(confirm_params)

        result = confirm_params.result_callback.call_args.args[0]
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_confirm_clears_pending_state(self):
        setup_params = _make_params({"command": "foot"})
        await handle_open_app(setup_params)
        assert desktop_mod._pending_open is not None

        mock_ipc = MagicMock()
        mock_ipc.dispatch.return_value = True
        confirm_params = _make_params({})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_confirm_open_app(confirm_params)

        assert desktop_mod._pending_open is None

    @pytest.mark.asyncio
    async def test_confirm_with_no_pending_returns_error(self):
        assert desktop_mod._pending_open is None  # setup_method ensures this
        confirm_params = _make_params({})

        await handle_confirm_open_app(confirm_params)

        result = confirm_params.result_callback.call_args.args[0]
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# get_desktop_state handler
# ---------------------------------------------------------------------------


class TestGetDesktopState:
    @pytest.mark.asyncio
    async def test_calls_result_callback(self):
        from shared.hyprland import WindowInfo, WorkspaceInfo

        mock_ipc = MagicMock()
        mock_ipc.get_active_window.return_value = None
        mock_ipc.get_clients.return_value = []
        mock_ipc.get_workspaces.return_value = []
        params = _make_params({})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_get_desktop_state(params)

        params.result_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_result_contains_active_window_info(self):
        from shared.hyprland import WindowInfo, WorkspaceInfo

        active_win = WindowInfo(
            address="0xdeadbeef",
            app_class="foot",
            title="foot terminal",
            workspace_id=1,
            pid=1234,
            x=0, y=0, width=800, height=600,
            floating=False,
            fullscreen=False,
        )
        mock_ipc = MagicMock()
        mock_ipc.get_active_window.return_value = active_win
        mock_ipc.get_clients.return_value = [active_win]
        mock_ipc.get_workspaces.return_value = []
        params = _make_params({})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_get_desktop_state(params)

        result = params.result_callback.call_args.args[0]
        assert result["active_window"] is not None
        assert result["active_window"]["class"] == "foot"
        assert result["active_window"]["title"] == "foot terminal"
        assert result["active_window"]["workspace"] == 1

    @pytest.mark.asyncio
    async def test_result_contains_windows_list(self):
        from shared.hyprland import WindowInfo

        win1 = WindowInfo(
            address="0x1", app_class="foot", title="terminal",
            workspace_id=1, pid=100,
            x=0, y=0, width=800, height=600,
            floating=False, fullscreen=False,
        )
        win2 = WindowInfo(
            address="0x2", app_class="google-chrome", title="Chrome",
            workspace_id=2, pid=200,
            x=0, y=0, width=1920, height=1080,
            floating=False, fullscreen=False,
        )
        mock_ipc = MagicMock()
        mock_ipc.get_active_window.return_value = None
        mock_ipc.get_clients.return_value = [win1, win2]
        mock_ipc.get_workspaces.return_value = []
        params = _make_params({})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_get_desktop_state(params)

        result = params.result_callback.call_args.args[0]
        assert len(result["windows"]) == 2
        classes = {w["class"] for w in result["windows"]}
        assert "foot" in classes
        assert "google-chrome" in classes

    @pytest.mark.asyncio
    async def test_result_contains_workspaces_list(self):
        from shared.hyprland import WorkspaceInfo

        ws1 = WorkspaceInfo(
            id=1, name="1", window_count=3,
            last_window_title="foot", monitor="DP-1",
        )
        ws2 = WorkspaceInfo(
            id=2, name="2", window_count=1,
            last_window_title="Chrome", monitor="DP-1",
        )
        mock_ipc = MagicMock()
        mock_ipc.get_active_window.return_value = None
        mock_ipc.get_clients.return_value = []
        mock_ipc.get_workspaces.return_value = [ws1, ws2]
        params = _make_params({})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_get_desktop_state(params)

        result = params.result_callback.call_args.args[0]
        assert len(result["workspaces"]) == 2
        ws_ids = {w["id"] for w in result["workspaces"]}
        assert 1 in ws_ids
        assert 2 in ws_ids

    @pytest.mark.asyncio
    async def test_result_active_window_none_when_no_focused_window(self):
        mock_ipc = MagicMock()
        mock_ipc.get_active_window.return_value = None
        mock_ipc.get_clients.return_value = []
        mock_ipc.get_workspaces.return_value = []
        params = _make_params({})

        with patch.object(desktop_mod, "_ipc", mock_ipc):
            await handle_get_desktop_state(params)

        result = params.result_callback.call_args.args[0]
        assert result["active_window"] is None
