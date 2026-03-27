"""Tests for the rule base class and registry."""

from __future__ import annotations

from agents.session_conductor.rules import (
    HookEvent,
    HookResponse,
    RuleBase,
    RuleRegistry,
)
from agents.session_conductor.topology import TopologyConfig


class _AllowRule(RuleBase):
    def on_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
        return None

    def on_post_tool_use(self, event: HookEvent) -> HookResponse | None:
        return None


class _BlockRule(RuleBase):
    def on_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
        return HookResponse.block("blocked by test rule")

    def on_post_tool_use(self, event: HookEvent) -> HookResponse | None:
        return None


def test_hook_event_from_dict():
    d = {
        "event_type": "pre_tool_use",
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/foo.py"},
        "session_id": "sess-1",
        "user_message": "read the file",
    }
    event = HookEvent.from_dict(d)
    assert event.event_type == "pre_tool_use"
    assert event.tool_name == "Read"
    assert event.tool_input == {"file_path": "/tmp/foo.py"}
    assert event.session_id == "sess-1"
    assert event.user_message == "read the file"


def test_hook_response_to_dict():
    resp = HookResponse(action="block", message="not allowed", rewrite=None)
    d = resp.to_dict()
    assert d["action"] == "block"
    assert d["message"] == "not allowed"
    assert "rewrite" not in d or d["rewrite"] is None


def test_hook_response_allow():
    resp = HookResponse.allow()
    assert resp.action == "allow"
    assert resp.message is None


def test_registry_dispatches_block():
    topology = TopologyConfig()
    registry = RuleRegistry()
    registry.register(_AllowRule(topology))
    registry.register(_BlockRule(topology))

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Bash",
        tool_input={"command": "ls"},
        session_id="sess-1",
        user_message="list files",
    )
    result = registry.process_pre_tool_use(event)
    assert result is not None
    assert result.action == "block"


def test_registry_allows_when_no_block():
    topology = TopologyConfig()
    registry = RuleRegistry()
    registry.register(_AllowRule(topology))

    event = HookEvent(
        event_type="pre_tool_use",
        tool_name="Read",
        tool_input={"file_path": "/tmp/foo.py"},
        session_id="sess-1",
        user_message=None,
    )
    result = registry.process_pre_tool_use(event)
    assert result is None
