"""Tests for tool capability definitions."""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.tool_capability import ToolCategory
from agents.hapax_daimonion.tool_definitions import build_registry
from shared.capability import SystemContext


class TestToolDefinitions(unittest.TestCase):
    def test_registry_has_all_tools(self):
        reg = build_registry()
        tools = reg.all_tools()
        names = {t.name for t in tools}
        assert "get_current_time" in names
        assert "search_documents" in names
        assert "get_weather" in names
        assert "get_briefing" in names
        assert "get_system_status" in names
        assert "analyze_scene" in names
        assert "send_sms" in names
        assert "focus_window" in names
        assert "open_app" in names
        assert "get_desktop_state" in names
        assert len(tools) >= 20

    def test_all_schemas_valid(self):
        reg = build_registry()
        for tool in reg.all_tools():
            assert tool.schema["type"] == "function"
            assert "name" in tool.schema["function"]
            assert "parameters" in tool.schema["function"]

    def test_categories_assigned(self):
        reg = build_registry()
        cats = {t.tool_category for t in reg.all_tools()}
        assert ToolCategory.INFORMATION in cats
        assert ToolCategory.CONTROL in cats

    def test_heavy_tools_identified(self):
        reg = build_registry()
        from agents.hapax_daimonion.tool_capability import ResourceTier

        heavy = [t for t in reg.all_tools() if t.resource_tier == ResourceTier.HEAVY]
        heavy_names = {t.name for t in heavy}
        assert "analyze_scene" in heavy_names
        assert "generate_image" in heavy_names

    def test_confirmation_tools_identified(self):
        reg = build_registry()
        confirm = [t for t in reg.all_tools() if t.requires_confirmation]
        confirm_names = {t.name for t in confirm}
        assert "send_sms" in confirm_names
        assert "open_app" in confirm_names

    def test_consent_tools_identified(self):
        reg = build_registry()
        consent = [t for t in reg.all_tools() if t.requires_consent]
        consent_names = {t.name for t in consent}
        assert "analyze_scene" in consent_names
        assert "search_drive" in consent_names

    def test_filtering_suppresses_vision_without_backend(self):
        reg = build_registry()
        ctx = SystemContext(active_backends=frozenset({"hyprland", "phone"}))
        available = {t.name for t in reg.available_tools(ctx)}
        assert "analyze_scene" not in available
        assert "get_current_time" in available
