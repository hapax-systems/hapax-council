"""Formal capability model for voice daemon tools.

Tools conform to the Hapax recruitment protocol: each declares what it
provides, what it requires, when it's available, and how it degrades.
This pass (queue #016) establishes registration + gating. A future pass
(queue #015) will replace LLM-menu selection with affordance-based recruitment.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from shared.capability import (
    CapabilityCategory,
    ResourceTier,
    SystemContext,
)

log = logging.getLogger(__name__)


class ToolCategory(enum.Enum):
    INFORMATION = "information"
    ACTION = "action"
    CONTROL = "control"


# Backward-compat alias — other code importing ToolContext still works.
ToolContext = SystemContext


@dataclass
class ToolCapability:
    """A tool modeled as a formal Hapax capability."""

    name: str
    description: str
    schema: dict
    handler: Callable

    tool_category: ToolCategory
    resource_tier: ResourceTier
    requires_consent: list[str] = field(default_factory=list)
    requires_backends: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    timeout_s: float = 3.0

    @property
    def category(self) -> CapabilityCategory:
        """Protocol-required property: all tools are CapabilityCategory.TOOL."""
        return CapabilityCategory.TOOL

    def available(self, ctx: SystemContext) -> bool:
        """Check all preconditions for this tool."""
        if ctx.working_mode == "research" and not ctx.experiment_flags.get("tools_enabled", False):
            return False
        if self.resource_tier == ResourceTier.HEAVY and ctx.stimmung_stance in (
            "degraded",
            "critical",
        ):
            return False
        if self.requires_consent and ctx.guest_present:
            return False
        if self.requires_backends:
            backends = (
                ctx.active_backends
                if isinstance(ctx.active_backends, (set, frozenset))
                else set(ctx.active_backends)
            )
            if not all(b in backends for b in self.requires_backends):
                return False
        return True

    def degrade(self) -> str:
        """Fallback message when this tool is unavailable."""
        return f"The {self.name} capability is not available right now."


class ToolRegistry:
    """Manages tool capabilities with dynamic availability filtering."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolCapability] = {}

    def register(self, tool: ToolCapability) -> None:
        if tool.name in self._tools:
            log.warning("Tool %s already registered, replacing", tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolCapability | None:
        return self._tools.get(name)

    def available_tools(self, ctx: ToolContext) -> list[ToolCapability]:
        return [t for t in self._tools.values() if t.available(ctx)]

    def schemas_for_llm(self, ctx: ToolContext) -> list[dict]:
        return [t.schema for t in self.available_tools(ctx)]

    def handler_map(self, ctx: ToolContext) -> dict[str, Callable]:
        return {t.name: t.handler for t in self.available_tools(ctx)}

    def all_tools(self) -> list[ToolCapability]:
        return list(self._tools.values())
