"""Session conductor rule base classes and registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agents.session_conductor.topology import TopologyConfig

log = logging.getLogger(__name__)


@dataclass
class HookEvent:
    """Represents a Claude Code hook event (pre/post tool use)."""

    event_type: str
    tool_name: str
    tool_input: dict[str, Any]
    session_id: str
    user_message: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HookEvent:
        return cls(
            event_type=d.get("event_type", ""),
            tool_name=d.get("tool_name", ""),
            tool_input=d.get("tool_input", {}),
            session_id=d.get("session_id", ""),
            user_message=d.get("user_message"),
        )


@dataclass
class HookResponse:
    """Response from a rule indicating how to handle the event."""

    action: str  # "allow" | "block" | "rewrite"
    message: str | None = None
    rewrite: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"action": self.action}
        if self.message is not None:
            result["message"] = self.message
        if self.rewrite is not None:
            result["rewrite"] = self.rewrite
        return result

    @classmethod
    def allow(cls) -> HookResponse:
        return cls(action="allow")

    @classmethod
    def block(cls, message: str) -> HookResponse:
        return cls(action="block", message=message)


class RuleBase(ABC):
    """Abstract base class for session conductor rules."""

    def __init__(self, topology: TopologyConfig) -> None:
        self.topology = topology

    @abstractmethod
    def on_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
        """Called before a tool is used. Return None to pass through."""
        ...

    @abstractmethod
    def on_post_tool_use(self, event: HookEvent) -> HookResponse | None:
        """Called after a tool is used. Return None to pass through."""
        ...


class RuleRegistry:
    """Registry of rules; dispatches events to registered rules."""

    def __init__(self) -> None:
        self._rules: list[RuleBase] = []

    def register(self, rule: RuleBase) -> None:
        self._rules.append(rule)

    def process_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
        """First block wins; None means allow."""
        for rule in self._rules:
            resp = rule.on_pre_tool_use(event)
            if resp is not None and resp.action == "block":
                return resp
            if resp is not None and resp.action == "rewrite":
                return resp
        return None

    def process_post_tool_use(self, event: HookEvent) -> list[HookResponse]:
        """Collect all non-None responses from post-tool-use handlers."""
        results = []
        for rule in self._rules:
            resp = rule.on_post_tool_use(event)
            if resp is not None:
                results.append(resp)
        return results
