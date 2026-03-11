"""Surface 4: Tool calling — handler execution and result delivery.

Tests that tool handlers execute correctly when invoked by the LLM
and that results flow back through the result_callback.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.hapax_voice.tools as tools_mod
from agents.hapax_voice.config import VoiceConfig


def _setup_tools(config: VoiceConfig | None = None):
    """Register tools on a mock LLM and return the handler map."""
    from agents.hapax_voice.tools import register_tool_handlers

    mock_llm = MagicMock()
    cfg = config or VoiceConfig(tools_enabled=True)
    register_tool_handlers(mock_llm, cfg)

    handlers = {}
    for call in mock_llm.register_function.call_args_list:
        name = call.args[0]
        handler = call.args[1]
        handlers[name] = handler

    return handlers


def _make_params(arguments: dict):
    """Create a mock FunctionCallParams-like object."""
    params = MagicMock()
    params.arguments = arguments
    params.result_callback = AsyncMock()
    return params


# ---------------------------------------------------------------------------
# Registration surface (deduplication guard — existing test covers this deeper)
# ---------------------------------------------------------------------------


class TestToolHandlerRegistration:
    """All 14 expected tools are registered with callable handlers."""

    def test_all_14_tools_registered(self):
        handlers = _setup_tools()
        assert len(handlers) == 14

    def test_core_tools_present(self):
        handlers = _setup_tools()
        expected = [
            "search_documents",
            "search_drive",
            "get_calendar_today",
            "search_emails",
            "send_sms",
            "confirm_send_sms",
            "analyze_scene",
            "get_system_status",
            "generate_image",
            "focus_window",
            "switch_workspace",
            "open_app",
            "confirm_open_app",
            "get_desktop_state",
        ]
        for name in expected:
            assert name in handlers, f"Missing tool handler: {name}"

    def test_handlers_are_callable(self):
        handlers = _setup_tools()
        for name, handler in handlers.items():
            assert callable(handler), f"Handler for '{name}' is not callable"


# ---------------------------------------------------------------------------
# search_documents
# ---------------------------------------------------------------------------


class TestSearchDocumentsTool:
    """search_documents queries Qdrant and returns formatted text."""

    @pytest.mark.asyncio
    async def test_returns_results_when_found(self):
        handlers = _setup_tools()
        handler = handlers["search_documents"]
        params = _make_params({"query": "test query", "max_results": 3})

        mock_point = MagicMock()
        mock_point.payload = {
            "filename": "doc1.md",
            "text": "result content",
            "source_service": "obsidian",
        }
        mock_point.score = 0.85

        mock_results = MagicMock()
        mock_results.points = [mock_point]

        with (
            patch("agents.hapax_voice.tools.embed", return_value=[0.1] * 768),
            patch("agents.hapax_voice.tools.get_qdrant") as mock_get_qdrant,
        ):
            mock_client = MagicMock()
            mock_client.query_points.return_value = mock_results
            mock_get_qdrant.return_value = mock_client
            await handler(params)

        params.result_callback.assert_called_once()
        result_text = params.result_callback.call_args.args[0]
        assert "result content" in result_text
        assert "doc1.md" in result_text

    @pytest.mark.asyncio
    async def test_handles_empty_results(self):
        handlers = _setup_tools()
        handler = handlers["search_documents"]
        params = _make_params({"query": "nonexistent topic"})

        mock_results = MagicMock()
        mock_results.points = []

        with (
            patch("agents.hapax_voice.tools.embed", return_value=[0.1] * 768),
            patch("agents.hapax_voice.tools.get_qdrant") as mock_get_qdrant,
        ):
            mock_client = MagicMock()
            mock_client.query_points.return_value = mock_results
            mock_get_qdrant.return_value = mock_client
            await handler(params)

        params.result_callback.assert_called_once()
        result_text = params.result_callback.call_args.args[0]
        assert "no relevant documents found" in result_text.lower()

    @pytest.mark.asyncio
    async def test_search_exception_returns_error_message(self):
        handlers = _setup_tools()
        handler = handlers["search_documents"]
        params = _make_params({"query": "test"})

        with patch("agents.hapax_voice.tools.embed", side_effect=RuntimeError("embed failed")):
            await handler(params)

        params.result_callback.assert_called_once()
        result_text = params.result_callback.call_args.args[0]
        assert "failed" in result_text.lower()

    @pytest.mark.asyncio
    async def test_source_filter_forwarded(self):
        """source_filter is passed through to Qdrant query."""
        handlers = _setup_tools()
        handler = handlers["search_documents"]
        params = _make_params({"query": "email about project", "source_filter": "gmail"})

        mock_results = MagicMock()
        mock_results.points = []

        with (
            patch("agents.hapax_voice.tools.embed", return_value=[0.1] * 768),
            patch("agents.hapax_voice.tools.get_qdrant") as mock_get_qdrant,
        ):
            mock_client = MagicMock()
            mock_client.query_points.return_value = mock_results
            mock_get_qdrant.return_value = mock_client
            await handler(params)

        # Verify query_points was called with a filter (not None)
        call_kwargs = mock_client.query_points.call_args
        assert call_kwargs is not None
        # Filter should be present when source_filter is set
        query_filter = call_kwargs.kwargs.get("query_filter") or (
            call_kwargs.args[2] if len(call_kwargs.args) > 2 else None
        )
        # Confirm a filter object was passed (not None)
        assert query_filter is not None


# ---------------------------------------------------------------------------
# search_drive
# ---------------------------------------------------------------------------


class TestSearchDriveTool:
    """search_drive delegates to search_documents with source_filter=gdrive."""

    @pytest.mark.asyncio
    async def test_search_drive_sets_source_filter(self):
        handlers = _setup_tools()
        handler = handlers["search_drive"]
        params = _make_params({"query": "quarterly report"})

        mock_results = MagicMock()
        mock_results.points = []

        with (
            patch("agents.hapax_voice.tools.embed", return_value=[0.1] * 768),
            patch("agents.hapax_voice.tools.get_qdrant") as mock_get_qdrant,
        ):
            mock_client = MagicMock()
            mock_client.query_points.return_value = mock_results
            mock_get_qdrant.return_value = mock_client
            await handler(params)

        # After delegation, source_filter should have been injected
        assert params.arguments.get("source_filter") == "gdrive"
        params.result_callback.assert_called_once()


# ---------------------------------------------------------------------------
# get_system_status
# ---------------------------------------------------------------------------


class TestGetSystemStatusTool:
    """get_system_status returns health check lines."""

    @pytest.mark.asyncio
    async def test_returns_formatted_status_lines(self):
        handlers = _setup_tools()
        handler = handlers["get_system_status"]
        params = _make_params({})

        mock_results = [
            {"name": "docker-qdrant", "group": "docker", "status": "ok", "message": "running"},
            {"name": "gpu-vram", "group": "gpu", "status": "ok", "message": "12GB free"},
        ]

        with patch("agents.hapax_voice.tools._run_health_checks", return_value=mock_results):
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert "docker-qdrant" in result
        assert "gpu-vram" in result

    @pytest.mark.asyncio
    async def test_no_results_returns_none_available_message(self):
        handlers = _setup_tools()
        handler = handlers["get_system_status"]
        params = _make_params({})

        with patch("agents.hapax_voice.tools._run_health_checks", return_value=[]):
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert "no health check results" in result.lower()

    @pytest.mark.asyncio
    async def test_category_filter_forwarded(self):
        handlers = _setup_tools()
        handler = handlers["get_system_status"]
        params = _make_params({"category": "gpu"})

        mock_results = [{"name": "gpu-vram", "group": "gpu", "status": "ok", "message": "ok"}]

        with patch(
            "agents.hapax_voice.tools._run_health_checks", return_value=mock_results
        ) as mock_checks:
            await handler(params)

        mock_checks.assert_called_once_with("gpu")


# ---------------------------------------------------------------------------
# send_sms / confirm_send_sms — two-step confirmation flow
# ---------------------------------------------------------------------------


class TestSendSmsTool:
    """send_sms stores a pending entry and returns a confirmation dict."""

    def setup_method(self):
        """Clear module-level SMS state before each test."""
        tools_mod._pending_sms.clear()
        tools_mod._voice_config = None

    @pytest.mark.asyncio
    async def test_send_sms_no_config_returns_error(self):
        handlers = _setup_tools(VoiceConfig(tools_enabled=True, sms_contacts={}))
        handler = handlers["send_sms"]

        # Explicitly unset config to simulate unconfigured state
        tools_mod._voice_config = None

        params = _make_params({"recipient": "+1234567890", "message": "Hello"})
        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_send_sms_unknown_contact_returns_error(self):
        cfg = VoiceConfig(tools_enabled=True, sms_contacts={"Wife": "+15550001234"})
        handlers = _setup_tools(cfg)
        handler = handlers["send_sms"]

        params = _make_params({"recipient": "Unknown Person", "message": "Hello"})
        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "error"
        assert "Unknown Person" in result["detail"]

    @pytest.mark.asyncio
    async def test_send_sms_known_contact_stores_pending(self):
        cfg = VoiceConfig(tools_enabled=True, sms_contacts={"Wife": "+15550001234"})
        handlers = _setup_tools(cfg)
        handler = handlers["send_sms"]

        params = _make_params({"recipient": "Wife", "message": "On my way"})
        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "pending_confirmation"
        assert "confirmation_id" in result
        assert result["phone"] == "+15550001234"
        assert result["message"] == "On my way"

        # Pending should be stored in module state
        conf_id = result["confirmation_id"]
        assert conf_id in tools_mod._pending_sms

    @pytest.mark.asyncio
    async def test_send_sms_direct_phone_number_accepted(self):
        cfg = VoiceConfig(tools_enabled=True, sms_contacts={})
        handlers = _setup_tools(cfg)
        handler = handlers["send_sms"]

        params = _make_params({"recipient": "+19995550100", "message": "Test"})
        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "pending_confirmation"
        assert result["phone"] == "+19995550100"

    @pytest.mark.asyncio
    async def test_send_sms_case_insensitive_lookup(self):
        cfg = VoiceConfig(tools_enabled=True, sms_contacts={"Wife": "+15550001234"})
        handlers = _setup_tools(cfg)
        handler = handlers["send_sms"]

        params = _make_params({"recipient": "wife", "message": "Hello"})
        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "pending_confirmation"
        assert result["phone"] == "+15550001234"


class TestConfirmSendSmsTool:
    """confirm_send_sms completes or errors based on pending state."""

    def setup_method(self):
        tools_mod._pending_sms.clear()
        tools_mod._voice_config = None

    @pytest.mark.asyncio
    async def test_confirm_with_no_pending_returns_error(self):
        cfg = VoiceConfig(tools_enabled=True)
        handlers = _setup_tools(cfg)
        handler = handlers["confirm_send_sms"]

        params = _make_params({"confirmation_id": "nonexistent"})
        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "error"
        assert "not found" in result["detail"].lower() or "expired" in result["detail"].lower()

    @pytest.mark.asyncio
    async def test_confirm_valid_id_but_no_gateway_config(self):
        cfg = VoiceConfig(tools_enabled=True, sms_gateway_host="")
        handlers = _setup_tools(cfg)
        handler = handlers["confirm_send_sms"]

        # Pre-seed the pending dict
        tools_mod._pending_sms["test-id"] = {
            "phone": "+15550001234",
            "message": "Hello",
            "recipient": "Wife",
        }

        params = _make_params({"confirmation_id": "test-id"})
        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "error"
        assert "gateway" in result["detail"].lower() or "configured" in result["detail"].lower()

    @pytest.mark.asyncio
    async def test_confirm_gateway_success(self):
        cfg = VoiceConfig(
            tools_enabled=True,
            sms_gateway_host="sms.local:8888",
            sms_gateway_user="user",
            sms_contacts={"Wife": "+15550001234"},
        )
        handlers = _setup_tools(cfg)
        handler = handlers["confirm_send_sms"]

        tools_mod._pending_sms["abc-123"] = {
            "phone": "+15550001234",
            "message": "Hello",
            "recipient": "Wife",
        }

        mock_response = MagicMock()
        mock_response.status_code = 200

        params = _make_params({"confirmation_id": "abc-123"})

        with (
            patch("agents.hapax_voice.tools._get_sms_password", return_value="secret"),
            patch("agents.hapax_voice.tools.httpx.post", return_value=mock_response),
        ):
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "sent"
        assert result["recipient"] == "Wife"
        # Pending entry should be consumed
        assert "abc-123" not in tools_mod._pending_sms

    @pytest.mark.asyncio
    async def test_confirm_gateway_http_error(self):
        cfg = VoiceConfig(
            tools_enabled=True,
            sms_gateway_host="sms.local:8888",
            sms_gateway_user="user",
        )
        handlers = _setup_tools(cfg)
        handler = handlers["confirm_send_sms"]

        tools_mod._pending_sms["fail-id"] = {
            "phone": "+15550001234",
            "message": "Test",
            "recipient": "+15550001234",
        }

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        params = _make_params({"confirmation_id": "fail-id"})

        with (
            patch("agents.hapax_voice.tools._get_sms_password", return_value="secret"),
            patch("agents.hapax_voice.tools.httpx.post", return_value=mock_response),
        ):
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "error"
        assert "503" in result["detail"]


# ---------------------------------------------------------------------------
# analyze_scene
# ---------------------------------------------------------------------------


class TestAnalyzeSceneTool:
    """analyze_scene captures images from capturer objects and calls vision model."""

    @pytest.mark.asyncio
    async def test_no_capturers_returns_no_images_message(self):
        """Without webcam/screen capturers, returns a 'no images' response."""
        from agents.hapax_voice.tools import register_tool_handlers

        mock_llm = MagicMock()
        cfg = VoiceConfig(tools_enabled=True)
        # Pass no capturers
        register_tool_handlers(mock_llm, cfg, webcam_capturer=None, screen_capturer=None)
        handlers = {
            call.args[0]: call.args[1] for call in mock_llm.register_function.call_args_list
        }

        params = _make_params({"cameras": ["operator", "screen"]})
        await handlers["analyze_scene"](params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert "no cameras" in result.lower() or "couldn't capture" in result.lower()

    @pytest.mark.asyncio
    async def test_with_screen_capturer_calls_vision(self):
        """When screen capturer returns a frame, vision model is called."""
        from agents.hapax_voice.tools import register_tool_handlers

        mock_llm = MagicMock()
        cfg = VoiceConfig(tools_enabled=True)

        mock_screen = MagicMock()
        mock_screen.capture.return_value = "base64encodedimage=="
        mock_screen.reset_cooldown = MagicMock()

        register_tool_handlers(mock_llm, cfg, webcam_capturer=None, screen_capturer=mock_screen)
        handlers = {
            call.args[0]: call.args[1] for call in mock_llm.register_function.call_args_list
        }

        params = _make_params({"cameras": ["screen"], "question": "What is on screen?"})

        with patch(
            "agents.hapax_voice.tools._vision_analyze", return_value="A terminal window is open"
        ):
            await handlers["analyze_scene"](params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert "terminal" in result.lower()


# ---------------------------------------------------------------------------
# Desktop tools — focus_window, switch_workspace, open_app, confirm_open_app
# ---------------------------------------------------------------------------


class TestFocusWindowTool:
    """focus_window dispatches to HyprlandIPC and returns status dict."""

    @pytest.mark.asyncio
    async def test_successful_focus(self):
        handlers = _setup_tools()
        handler = handlers["focus_window"]
        params = _make_params({"target": "foot"})

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = True
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "focused"
        assert result["target"] == "foot"

    @pytest.mark.asyncio
    async def test_failed_focus(self):
        handlers = _setup_tools()
        handler = handlers["focus_window"]
        params = _make_params({"target": "nonexistent-app"})

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = False
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "failed"


class TestSwitchWorkspaceTool:
    """switch_workspace dispatches workspace command and returns status dict."""

    @pytest.mark.asyncio
    async def test_successful_switch(self):
        handlers = _setup_tools()
        handler = handlers["switch_workspace"]
        params = _make_params({"workspace": 3})

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = True
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "switched"
        assert result["workspace"] == 3

    @pytest.mark.asyncio
    async def test_failed_switch(self):
        handlers = _setup_tools()
        handler = handlers["switch_workspace"]
        params = _make_params({"workspace": 99})

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = False
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "failed"


class TestOpenAppTool:
    """open_app sets pending state and returns pending_confirmation status."""

    def setup_method(self):
        import agents.hapax_voice.desktop_tools as dt

        dt._pending_open = None

    @pytest.mark.asyncio
    async def test_open_app_returns_pending_confirmation(self):
        handlers = _setup_tools()
        handler = handlers["open_app"]
        params = _make_params({"command": "foot"})

        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "pending_confirmation"
        assert "foot" in result["message"]

    @pytest.mark.asyncio
    async def test_open_app_stores_pending(self):
        import agents.hapax_voice.desktop_tools as dt

        handlers = _setup_tools()
        handler = handlers["open_app"]
        params = _make_params({"command": "google-chrome-stable", "workspace": 2})

        await handler(params)

        assert dt._pending_open is not None
        assert dt._pending_open["command"] == "google-chrome-stable"
        assert dt._pending_open["workspace"] == 2


class TestConfirmOpenAppTool:
    """confirm_open_app dispatches exec or errors when no pending state."""

    def setup_method(self):
        import agents.hapax_voice.desktop_tools as dt

        dt._pending_open = None

    @pytest.mark.asyncio
    async def test_confirm_with_no_pending_returns_error(self):
        handlers = _setup_tools()
        handler = handlers["confirm_open_app"]
        params = _make_params({})

        await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "error"
        assert "no pending" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_confirm_launches_app(self):
        import agents.hapax_voice.desktop_tools as dt

        dt._pending_open = {"command": "foot", "workspace": None}

        handlers = _setup_tools()
        handler = handlers["confirm_open_app"]
        params = _make_params({})

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = True
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["status"] == "launched"
        assert result["command"] == "foot"
        # Pending should be cleared
        assert dt._pending_open is None

    @pytest.mark.asyncio
    async def test_confirm_with_workspace_uses_workspace_dispatch(self):
        import agents.hapax_voice.desktop_tools as dt

        dt._pending_open = {"command": "obsidian", "workspace": 4}

        handlers = _setup_tools()
        handler = handlers["confirm_open_app"]
        params = _make_params({})

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.dispatch.return_value = True
            await handler(params)

        # The workspace variant should include workspace in the dispatch call
        call_args = mock_ipc.dispatch.call_args
        assert "4" in str(call_args) or 4 in str(call_args)


class TestGetDesktopStateTool:
    """get_desktop_state returns structured window/workspace state dict."""

    @pytest.mark.asyncio
    async def test_returns_state_structure(self):
        handlers = _setup_tools()
        handler = handlers["get_desktop_state"]
        params = _make_params({})

        mock_active = MagicMock()
        mock_active.app_class = "foot"
        mock_active.title = "Terminal"
        mock_active.workspace_id = 1

        mock_client = MagicMock()
        mock_client.app_class = "foot"
        mock_client.title = "Terminal"
        mock_client.workspace_id = 1

        mock_ws = MagicMock()
        mock_ws.id = 1
        mock_ws.name = "1"
        mock_ws.window_count = 1

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.get_active_window.return_value = mock_active
            mock_ipc.get_clients.return_value = [mock_client]
            mock_ipc.get_workspaces.return_value = [mock_ws]
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert "active_window" in result
        assert "windows" in result
        assert "workspaces" in result
        assert result["active_window"]["class"] == "foot"

    @pytest.mark.asyncio
    async def test_handles_no_active_window(self):
        handlers = _setup_tools()
        handler = handlers["get_desktop_state"]
        params = _make_params({})

        with patch("agents.hapax_voice.desktop_tools._ipc") as mock_ipc:
            mock_ipc.get_active_window.return_value = None
            mock_ipc.get_clients.return_value = []
            mock_ipc.get_workspaces.return_value = []
            await handler(params)

        params.result_callback.assert_called_once()
        result = params.result_callback.call_args.args[0]
        assert result["active_window"] is None
