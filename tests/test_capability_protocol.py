"""Tests for shared capability protocol and registry."""

from __future__ import annotations

import unittest

from shared.capability import (
    Capability,
    CapabilityCategory,
    CapabilityRegistry,
    ResourceTier,
    SystemContext,
)


def _make_ctx(**overrides) -> SystemContext:
    defaults = {
        "stimmung_stance": "nominal",
        "consent_state": {},
        "guest_present": False,
        "active_backends": frozenset({"vision", "hyprland", "phone"}),
        "working_mode": "rnd",
        "experiment_flags": {},
        "tpn_active": False,
    }
    defaults.update(overrides)
    return SystemContext(**defaults)


class StubCapability:
    def __init__(
        self,
        name: str = "stub",
        category: CapabilityCategory = CapabilityCategory.TOOL,
        resource_tier: ResourceTier = ResourceTier.INSTANT,
        is_available: bool = True,
    ):
        self._name = name
        self._category = category
        self._resource_tier = resource_tier
        self._is_available = is_available

    @property
    def name(self) -> str:
        return self._name

    @property
    def category(self) -> CapabilityCategory:
        return self._category

    @property
    def resource_tier(self) -> ResourceTier:
        return self._resource_tier

    def available(self, ctx: SystemContext) -> bool:
        return self._is_available

    def degrade(self) -> str:
        return f"{self._name} is unavailable"


class TestSystemContext(unittest.TestCase):
    def test_frozen(self):
        ctx = _make_ctx()
        with self.assertRaises(AttributeError):
            ctx.stimmung_stance = "degraded"

    def test_defaults(self):
        ctx = SystemContext()
        assert ctx.stimmung_stance == "nominal"
        assert ctx.working_mode == "rnd"
        assert ctx.tpn_active is False


class TestCapabilityProtocol(unittest.TestCase):
    def test_stub_is_capability(self):
        cap = StubCapability()
        assert isinstance(cap, Capability)

    def test_stub_properties(self):
        cap = StubCapability("test", CapabilityCategory.EXPRESSION, ResourceTier.HEAVY)
        assert cap.name == "test"
        assert cap.category == CapabilityCategory.EXPRESSION
        assert cap.resource_tier == ResourceTier.HEAVY

    def test_available_delegates(self):
        cap = StubCapability(is_available=False)
        assert cap.available(_make_ctx()) is False

    def test_degrade_returns_string(self):
        cap = StubCapability("my_tool")
        assert "my_tool" in cap.degrade()


class TestCapabilityRegistry(unittest.TestCase):
    def test_register_and_get(self):
        reg = CapabilityRegistry()
        cap = StubCapability("a")
        reg.register(cap)
        assert reg.get("a") is cap

    def test_register_duplicate_raises(self):
        reg = CapabilityRegistry()
        reg.register(StubCapability("a"))
        with self.assertRaises(ValueError):
            reg.register(StubCapability("a"))

    def test_all_returns_registered(self):
        reg = CapabilityRegistry()
        reg.register(StubCapability("a"))
        reg.register(StubCapability("b"))
        assert len(reg.all()) == 2

    def test_available_filters(self):
        reg = CapabilityRegistry()
        reg.register(StubCapability("on", is_available=True))
        reg.register(StubCapability("off", is_available=False))
        available = reg.available(_make_ctx())
        assert len(available) == 1
        assert available[0].name == "on"

    def test_available_filters_by_category(self):
        reg = CapabilityRegistry()
        reg.register(StubCapability("t", category=CapabilityCategory.TOOL))
        reg.register(StubCapability("e", category=CapabilityCategory.EXPRESSION))
        tools = reg.available(_make_ctx(), category=CapabilityCategory.TOOL)
        assert len(tools) == 1
        assert tools[0].name == "t"

    def test_get_missing_returns_none(self):
        reg = CapabilityRegistry()
        assert reg.get("nonexistent") is None


class TestToolCapabilityConformance(unittest.TestCase):
    def test_tool_capability_is_capability(self):
        from agents.hapax_daimonion.tool_capability import ToolCapability, ToolCategory

        async def noop(args):
            return "ok"

        tool = ToolCapability(
            name="test",
            description="test",
            schema={
                "type": "function",
                "function": {
                    "name": "test",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            handler=noop,
            tool_category=ToolCategory.INFORMATION,
            resource_tier=ResourceTier.INSTANT,
        )
        assert isinstance(tool, Capability)
        assert tool.category == CapabilityCategory.TOOL


class TestSpeechCapabilityConformance(unittest.TestCase):
    def test_speech_capability_is_capability(self):
        from agents.hapax_daimonion.capability import SpeechProductionCapability

        cap = SpeechProductionCapability()
        assert isinstance(cap, Capability)
        assert cap.category == CapabilityCategory.EXPRESSION
        assert cap.resource_tier == ResourceTier.HEAVY
        assert cap.name == "speech_production"

    def test_speech_degrade(self):
        from agents.hapax_daimonion.capability import SpeechProductionCapability

        cap = SpeechProductionCapability()
        assert "speech" in cap.degrade().lower()


class TestShaderGraphConformance(unittest.TestCase):
    def test_shader_graph_is_capability(self):
        from agents.effect_graph.capability import ShaderGraphCapability

        cap = ShaderGraphCapability()
        assert isinstance(cap, Capability)
        assert cap.category == CapabilityCategory.EXPRESSION
        assert cap.resource_tier == ResourceTier.HEAVY
        assert cap.name == "shader_graph"

    def test_shader_graph_degrade(self):
        from agents.effect_graph.capability import ShaderGraphCapability

        cap = ShaderGraphCapability()
        assert "visual" in cap.degrade().lower() or "unavailable" in cap.degrade().lower()
