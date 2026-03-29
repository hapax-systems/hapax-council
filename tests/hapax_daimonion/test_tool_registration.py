"""Tests for tool registration on the Pipecat LLM service."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.config import DaimonionConfig


def test_register_tool_handlers_calls_register_function():
    from agents.hapax_daimonion.tools import register_tool_handlers

    mock_llm = MagicMock()
    cfg = DaimonionConfig(tools_enabled=True)

    register_tool_handlers(mock_llm, cfg)

    assert mock_llm.register_function.call_count == 14

    registered_names = [call.args[0] for call in mock_llm.register_function.call_args_list]
    assert "search_documents" in registered_names
    assert "get_calendar_today" in registered_names
    assert "search_emails" in registered_names
    assert "search_drive" in registered_names
    assert "send_sms" in registered_names
    assert "confirm_send_sms" in registered_names
    assert "analyze_scene" in registered_names
    assert "get_system_status" in registered_names
    assert "generate_image" in registered_names
    assert "focus_window" in registered_names
    assert "switch_workspace" in registered_names
    assert "open_app" in registered_names
    assert "confirm_open_app" in registered_names
    assert "get_desktop_state" in registered_names


def test_register_skipped_when_tools_disabled():
    from agents.hapax_daimonion.tools import register_tool_handlers

    mock_llm = MagicMock()
    cfg = DaimonionConfig(tools_enabled=False)

    register_tool_handlers(mock_llm, cfg)

    mock_llm.register_function.assert_not_called()
