"""Tests for tool capability model."""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.tool_capability import (
    ToolCapability,
    ToolCategory,
    ToolRegistry,
)
from shared.capability import ResourceTier, SystemContext


def _make_ctx(**overrides) -> SystemContext:
    defaults = {
        "stimmung_stance": "nominal",
        "consent_state": {},
        "guest_present": False,
        "active_backends": {"vision", "hyprland", "phone"},
        "working_mode": "rnd",
        "experiment_flags": {},
    }
    defaults.update(overrides)
    return SystemContext(**defaults)


async def _noop_handler(args: dict) -> str:
    return "ok"


def _make_tool(name: str = "test_tool", **overrides) -> ToolCapability:
    defaults = {
        "name": name,
        "description": "Test tool",
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": "test",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        "handler": _noop_handler,
        "tool_category": ToolCategory.INFORMATION,
        "resource_tier": ResourceTier.INSTANT,
        "requires_consent": [],
        "requires_backends": [],
        "requires_confirmation": False,
        "timeout_s": 3.0,
    }
    defaults.update(overrides)
    return ToolCapability(**defaults)


class TestToolCapabilityAvailability(unittest.TestCase):
    def test_available_nominal(self):
        tool = _make_tool()
        assert tool.available(_make_ctx()) is True

    def test_heavy_tool_suppressed_when_degraded(self):
        tool = _make_tool(resource_tier=ResourceTier.HEAVY)
        assert tool.available(_make_ctx(stimmung_stance="degraded")) is False

    def test_heavy_tool_ok_when_nominal(self):
        tool = _make_tool(resource_tier=ResourceTier.HEAVY)
        assert tool.available(_make_ctx(stimmung_stance="nominal")) is True

    def test_consent_tool_suppressed_with_guest(self):
        tool = _make_tool(requires_consent=["interpersonal_transparency"])
        assert tool.available(_make_ctx(guest_present=True)) is False

    def test_consent_tool_ok_without_guest(self):
        tool = _make_tool(requires_consent=["interpersonal_transparency"])
        assert tool.available(_make_ctx(guest_present=False)) is True

    def test_backend_requirement_missing(self):
        tool = _make_tool(requires_backends=["vision"])
        assert tool.available(_make_ctx(active_backends={"hyprland"})) is False

    def test_backend_requirement_met(self):
        tool = _make_tool(requires_backends=["vision"])
        assert tool.available(_make_ctx(active_backends={"vision", "hyprland"})) is True

    def test_research_mode_suppresses_without_flag(self):
        tool = _make_tool()
        assert (
            tool.available(
                _make_ctx(working_mode="research", experiment_flags={"tools_enabled": False})
            )
            is False
        )

    def test_research_mode_allows_with_flag(self):
        tool = _make_tool()
        assert (
            tool.available(
                _make_ctx(working_mode="research", experiment_flags={"tools_enabled": True})
            )
            is True
        )


class TestToolRegistry(unittest.TestCase):
    def test_register_and_list(self):
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        reg.register(_make_tool("b"))
        assert len(reg.available_tools(_make_ctx())) == 2

    def test_filtering_removes_unavailable(self):
        reg = ToolRegistry()
        reg.register(_make_tool("light", resource_tier=ResourceTier.LIGHT))
        reg.register(_make_tool("heavy", resource_tier=ResourceTier.HEAVY))
        available = reg.available_tools(_make_ctx(stimmung_stance="critical"))
        names = [t.name for t in available]
        assert "light" in names
        assert "heavy" not in names

    def test_schemas_for_llm(self):
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        schemas = reg.schemas_for_llm(_make_ctx())
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "a"

    def test_handler_map(self):
        reg = ToolRegistry()
        reg.register(_make_tool("a"))
        handlers = reg.handler_map(_make_ctx())
        assert "a" in handlers

    def test_degrade_message(self):
        tool = _make_tool("analyze_scene")
        msg = tool.degrade()
        assert "analyze_scene" in msg
