"""Session conductor rule base classes and registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agents.session_conductor.topology import TopologyConfig

log = logging.getLogger(__name__)


@dataclass
class HookEvent:
    """Represents a Claude Code hook event (pre/post tool use)."""

    event_type: str
    tool_name: str
    tool_input: dict[str, object]
    session_id: str
    # The operator's own words. Sent only by the operator-turn path
    # (event_type "user_prompt"). A tool's stdout is `tool_output` (M103).
    user_message: str | None = None
    # A tool's stdout/stderr. Never an operator turn.
    tool_output: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> HookEvent:
        return cls(
            event_type=d.get("event_type", ""),
            tool_name=d.get("tool_name", ""),
            tool_input=d.get("tool_input", {}),
            session_id=d.get("session_id", ""),
            user_message=d.get("user_message"),
            tool_output=d.get("tool_output"),
        )


@dataclass
class HookResponse:
    """Response from a rule indicating how to handle the event."""

    action: str  # "allow" | "block" | "rewrite"
    message: str | None = None
    rewrite: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"action": self.action}
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

    def on_user_prompt(self, event: HookEvent) -> HookResponse | None:
        """Called on the operator's own turn (UserPromptSubmit). Default: no opinion.

        Deliberately not abstract: this hook is newer than the rules, and a rule
        that has nothing to say about an operator turn should not have to say so.
        """
        return None


class RuleRegistry:
    """Registry of rules; dispatches events to registered rules."""

    def __init__(self) -> None:
        self._rules: list[RuleBase] = []

    def register(self, rule: RuleBase) -> None:
        self._rules.append(rule)

    def process_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
        """Block wins over rewrite; rewrites merge. Fail-open on rule exceptions."""
        merged_rewrite: dict[str, object] | None = None
        merged_message: str | None = None
        for rule in self._rules:
            try:
                resp = rule.on_pre_tool_use(event)
            except Exception:
                log.exception(
                    "Rule %s.on_pre_tool_use crashed — skipping (fail-open)", type(rule).__name__
                )
                continue
            if resp is not None and resp.action == "block":
                return resp
            if resp is not None and resp.action == "rewrite" and resp.rewrite:
                if merged_rewrite is None:
                    merged_rewrite = dict(resp.rewrite)
                else:
                    merged_rewrite.update(resp.rewrite)
                if resp.message:
                    merged_message = (
                        resp.message
                        if merged_message is None
                        else f"{merged_message}; {resp.message}"
                    )
        if merged_rewrite is not None:
            return HookResponse(action="rewrite", message=merged_message, rewrite=merged_rewrite)
        return None

    def process_post_tool_use(self, event: HookEvent) -> list[HookResponse]:
        """Collect all non-None responses from post-tool-use handlers. Fail-open on exceptions."""
        results = []
        for rule in self._rules:
            try:
                resp = rule.on_post_tool_use(event)
            except Exception:
                log.exception(
                    "Rule %s.on_post_tool_use crashed — skipping (fail-open)", type(rule).__name__
                )
                continue
            if resp is not None:
                results.append(resp)
        return results

    def process_user_prompt(self, event: HookEvent) -> list[HookResponse]:
        """Collect all non-None responses from operator-turn handlers. Fail-open on exceptions."""
        results = []
        for rule in self._rules:
            try:
                resp = rule.on_user_prompt(event)
            except Exception:
                log.exception(
                    "Rule %s.on_user_prompt crashed — skipping (fail-open)", type(rule).__name__
                )
                continue
            if resp is not None:
                results.append(resp)
        return results
