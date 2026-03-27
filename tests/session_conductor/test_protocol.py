"""Tests for the UDS protocol server."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from agents.session_conductor.protocol import ConductorServer
from agents.session_conductor.rules import HookEvent, HookResponse, RuleBase, RuleRegistry
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig


def _make_state() -> SessionState:
    return SessionState(
        session_id="sess-alpha",
        pid=12345,
        started_at=datetime.now(),
    )


def _make_registry_with_block() -> RuleRegistry:
    """Registry whose first rule always blocks pre_tool_use."""

    class BlockRule(RuleBase):
        def on_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
            return HookResponse.block("test block")

        def on_post_tool_use(self, event: HookEvent) -> HookResponse | None:
            return None

    registry = RuleRegistry()
    registry.register(BlockRule(TopologyConfig()))
    return registry


def _make_registry_with_allow() -> RuleRegistry:
    """Registry that allows everything."""

    class AllowRule(RuleBase):
        def on_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
            return None

        def on_post_tool_use(self, event: HookEvent) -> HookResponse | None:
            return None

    registry = RuleRegistry()
    registry.register(AllowRule(TopologyConfig()))
    return registry


def _make_registry_with_post_response() -> RuleRegistry:
    """Registry whose rule returns a response on post_tool_use."""

    class PostRule(RuleBase):
        def on_pre_tool_use(self, event: HookEvent) -> HookResponse | None:
            return None

        def on_post_tool_use(self, event: HookEvent) -> HookResponse | None:
            return HookResponse.allow()

    registry = RuleRegistry()
    registry.register(PostRule(TopologyConfig()))
    return registry


def _make_server(
    tmp_path: Path,
    registry: RuleRegistry | None = None,
) -> ConductorServer:
    state = _make_state()
    state_path = tmp_path / "state.json"
    sock_path = tmp_path / "conductor.sock"
    reg = registry or _make_registry_with_allow()
    return ConductorServer(state=state, registry=reg, state_path=state_path, sock_path=sock_path)


# ---------------------------------------------------------------------------
# Synchronous process_event tests
# ---------------------------------------------------------------------------


def test_process_event_allow(tmp_path: Path):
    server = _make_server(tmp_path, _make_registry_with_allow())
    event_data = {
        "event_type": "pre_tool_use",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "session_id": "sess-alpha",
    }
    result = server.process_event(event_data)
    assert result["action"] == "allow"


def test_process_event_block(tmp_path: Path):
    server = _make_server(tmp_path, _make_registry_with_block())
    event_data = {
        "event_type": "pre_tool_use",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/foo.py"},
        "session_id": "sess-alpha",
    }
    result = server.process_event(event_data)
    assert result["action"] == "block"
    assert "test block" in result.get("message", "")


def test_process_event_post_tool(tmp_path: Path):
    server = _make_server(tmp_path, _make_registry_with_post_response())
    event_data = {
        "event_type": "post_tool_use",
        "tool_name": "Agent",
        "tool_input": {"prompt": "do something"},
        "session_id": "sess-alpha",
    }
    result = server.process_event(event_data)
    assert result["action"] == "allow"


def test_process_event_saves_state(tmp_path: Path):
    server = _make_server(tmp_path, _make_registry_with_allow())
    state_path = server.state_path

    event_data = {
        "event_type": "pre_tool_use",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "session_id": "sess-alpha",
    }
    server.process_event(event_data)
    assert state_path.exists()


def test_process_event_invalid_json_handled(tmp_path: Path):
    """process_event itself doesn't handle JSON — that's _handle_client's job."""
    server = _make_server(tmp_path)
    # process_event expects a dict; passing valid dict should work
    result = server.process_event(
        {"event_type": "pre_tool_use", "tool_name": "Bash", "tool_input": {}, "session_id": "x"}
    )
    assert result["action"] == "allow"


# ---------------------------------------------------------------------------
# Async UDS roundtrip test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_uds_roundtrip(tmp_path: Path):
    """Full async roundtrip: send event over UDS, receive response."""
    server = _make_server(tmp_path, _make_registry_with_allow())

    # Start server in background
    server_task = asyncio.create_task(server.start())
    # Give it a moment to bind
    await asyncio.sleep(0.05)

    try:
        reader, writer = await asyncio.open_unix_connection(path=str(server.sock_path))

        event_data = {
            "event_type": "pre_tool_use",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "session_id": "sess-alpha",
        }
        writer.write((json.dumps(event_data) + "\n").encode())
        await writer.drain()

        raw = await reader.readline()
        result = json.loads(raw.decode())
        assert result["action"] == "allow"

        writer.close()
        await writer.wait_closed()
    finally:
        server.shutdown()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (TimeoutError, asyncio.CancelledError):
            server_task.cancel()


@pytest.mark.asyncio
async def test_handle_client_invalid_json(tmp_path: Path):
    """Client sending invalid JSON receives error response, not crash."""
    server = _make_server(tmp_path, _make_registry_with_allow())

    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(0.05)

    try:
        reader, writer = await asyncio.open_unix_connection(path=str(server.sock_path))

        writer.write(b"not valid json\n")
        await writer.drain()

        raw = await reader.readline()
        result = json.loads(raw.decode())
        assert "error" in result

        writer.close()
        await writer.wait_closed()
    finally:
        server.shutdown()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (TimeoutError, asyncio.CancelledError):
            server_task.cancel()
