"""Tests for voice tool schema definitions."""
import pytest

from agents.hapax_voice.tools import get_tool_schemas, TOOL_SCHEMAS


EXPECTED_TOOL_NAMES = [
    "search_documents",
    "search_drive",
    "get_calendar_today",
    "search_emails",
    "send_sms",
    "confirm_send_sms",
    "analyze_scene",
    "get_system_status",
    "generate_image",
]


def test_tool_schemas_returns_tools_schema():
    tools = get_tool_schemas(guest_mode=False)
    assert tools is not None


def test_tool_schemas_guest_mode_empty():
    tools = get_tool_schemas(guest_mode=True)
    assert tools is None


def test_all_expected_tools_present():
    names = [s.name for s in TOOL_SCHEMAS]
    for expected in EXPECTED_TOOL_NAMES:
        assert expected in names, f"Missing tool schema: {expected}"


def test_total_tool_count():
    assert len(TOOL_SCHEMAS) == 9


def test_search_documents_has_required_query():
    schema = next(s for s in TOOL_SCHEMAS if s.name == "search_documents")
    assert "query" in schema.required


def test_send_sms_requires_recipient_and_message():
    schema = next(s for s in TOOL_SCHEMAS if s.name == "send_sms")
    assert "recipient" in schema.required
    assert "message" in schema.required


def test_confirm_send_sms_requires_confirmation_id():
    schema = next(s for s in TOOL_SCHEMAS if s.name == "confirm_send_sms")
    assert "confirmation_id" in schema.required


def test_all_schemas_have_description():
    for schema in TOOL_SCHEMAS:
        assert schema.description, f"{schema.name} missing description"
