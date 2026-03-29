"""Tests for tool registration on the Pipecat LLM service."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.config import DaimonionConfig


def test_register_tool_handlers_calls_register_function():
    from agents.hapax_daimonion.tools import register_tool_handlers

    mock_llm = MagicMock()
    cfg = DaimonionConfig(tools_enabled=True)

    register_tool_handlers(mock_llm, cfg)

    assert mock_llm.register_function.call_count == 26

    registered_names = [call.args[0] for call in mock_llm.register_function.call_args_list]
    expected = [
        "search_documents",
        "get_calendar_today",
        "search_emails",
        "search_drive",
        "send_sms",
        "confirm_send_sms",
        "analyze_scene",
        "get_system_status",
        "generate_image",
        "get_current_time",
        "get_weather",
        "get_briefing",
        "focus_window",
        "switch_workspace",
        "open_app",
        "confirm_open_app",
        "get_desktop_state",
        "check_consent_status",
        "describe_consent_flow",
        "check_governance_health",
        "query_scene_inventory",
        "highlight_detection",
        "set_detection_layers",
        "query_person_details",
        "query_object_motion",
        "query_scene_state",
    ]
    for name in expected:
        assert name in registered_names, f"Missing tool: {name}"


def test_register_skipped_when_tools_disabled():
    from agents.hapax_daimonion.tools import register_tool_handlers

    mock_llm = MagicMock()
    cfg = DaimonionConfig(tools_enabled=False)

    register_tool_handlers(mock_llm, cfg)

    mock_llm.register_function.assert_not_called()
