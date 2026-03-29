from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_daimonion.hyprland_listener import (
    FocusEvent,
    HyprlandEventListener,
)


def test_focus_event_creation():
    ev = FocusEvent(app_class="foot", title="~/projects", workspace_id=1, address="0x1")
    assert ev.app_class == "foot"


class TestEventParsing:
    def test_parse_activewindowv2(self):
        listener = HyprlandEventListener()
        ev = listener._parse_line("activewindowv2>>0x55a1c2e3f0a0")
        assert ev is not None
        assert ev[0] == "activewindowv2"
        assert ev[1] == "0x55a1c2e3f0a0"

    def test_parse_openwindow(self):
        listener = HyprlandEventListener()
        ev = listener._parse_line("openwindow>>0x1234,1,foot,~/projects")
        assert ev is not None
        assert ev[0] == "openwindow"

    def test_parse_workspace(self):
        listener = HyprlandEventListener()
        ev = listener._parse_line("workspacev2>>3,3")
        assert ev is not None
        assert ev[0] == "workspacev2"

    def test_parse_ignores_unknown(self):
        listener = HyprlandEventListener()
        ev = listener._parse_line("configreloaded>>")
        # Parsed but not an error
        assert ev is not None

    def test_parse_handles_malformed(self):
        listener = HyprlandEventListener()
        ev = listener._parse_line("garbage")
        assert ev is None


class TestDebounce:
    def test_same_focus_suppressed(self):
        listener = HyprlandEventListener(debounce_s=1.0)
        callback = MagicMock()
        listener.on_focus_changed = callback

        # Simulate two identical focus events
        listener._handle_focus_event("foot", "term", 1, "0x1")
        listener._handle_focus_event("foot", "term", 1, "0x1")
        assert callback.call_count == 1

    def test_different_focus_fires(self):
        listener = HyprlandEventListener(debounce_s=0.0)
        callback = MagicMock()
        listener.on_focus_changed = callback

        listener._handle_focus_event("foot", "term", 1, "0x1")
        listener._handle_focus_event("chrome", "tab", 3, "0x2")
        assert callback.call_count == 2

    def test_debounced_event_fires_via_pending_confirmation(self):
        """Events within debounce window are stored as pending and
        fire after debounce elapses (via _confirm_pending)."""
        listener = HyprlandEventListener(debounce_s=1.0)
        callback = MagicMock()
        listener.on_focus_changed = callback

        # First event fires immediately
        listener._handle_focus_event("foot", "term", 1, "0x1")
        assert callback.call_count == 1

        # Second event within debounce — stored as pending
        listener._handle_focus_event("chrome", "tab", 3, "0x2")
        # In sync mode (no event loop), _confirm_pending fires immediately
        # because _schedule_pending_confirmation falls through to sync path
        assert callback.call_count == 2
        last_event = callback.call_args[0][0]
        assert last_event.app_class == "chrome"


class TestProcessEvent:
    @pytest.mark.asyncio
    async def test_activewindowv2_queries_ipc(self):
        from shared.hyprland import WindowInfo

        listener = HyprlandEventListener(debounce_s=0.0)
        callback = MagicMock()
        listener.on_focus_changed = callback

        mock_win = WindowInfo(
            "0x1234",
            "foot",
            "term",
            1,
            42,
            0,
            0,
            800,
            600,
            False,
            False,
        )
        with patch.object(listener._ipc, "get_active_window", return_value=mock_win):
            await listener._process_event("activewindowv2", "0x1234")

        assert callback.call_count == 1
        assert callback.call_args[0][0].app_class == "foot"

    @pytest.mark.asyncio
    async def test_openwindow_calls_handler(self):
        listener = HyprlandEventListener()
        handler = MagicMock()
        listener.on_window_opened = handler

        await listener._process_event("openwindow", "0x1234,1,foot,~/projects")
        handler.assert_called_once_with("foot", "~/projects", "0x1234")

    @pytest.mark.asyncio
    async def test_closewindow_calls_handler(self):
        listener = HyprlandEventListener()
        handler = MagicMock()
        listener.on_window_closed = handler

        await listener._process_event("closewindow", "0x1234")
        handler.assert_called_once_with("0x1234")


class TestFallback:
    def test_available_false_when_no_socket(self):
        with patch.dict("os.environ", {"HYPRLAND_INSTANCE_SIGNATURE": "", "XDG_RUNTIME_DIR": ""}):
            listener = HyprlandEventListener()
            assert listener.available is False
