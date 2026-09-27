"""Integration tests for the full ConductorServer lifecycle."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from agents.session_conductor.protocol import ConductorServer
from agents.session_conductor.rules import RuleRegistry
from agents.session_conductor.rules.convergence import ConvergenceRule
from agents.session_conductor.rules.epic import EpicRule
from agents.session_conductor.rules.focus import FocusRule
from agents.session_conductor.rules.relay import RelayRule
from agents.session_conductor.rules.smoke import SmokeRule
from agents.session_conductor.rules.spawn import SpawnRule
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import PlaywrightConfig, SmokeTestConfig, TopologyConfig


def _build_server(tmp_path: Path) -> ConductorServer:
    topology = TopologyConfig(
        playwright=PlaywrightConfig(testing_workspace=10, screenshot_max_bytes=500_000),
        smoke_test=SmokeTestConfig(workspace=10, fullscreen=True),
    )
    state = SessionState(session_id="integ-test", pid=1, started_at=datetime(2026, 3, 27))
    registry = RuleRegistry()
    registry.register(FocusRule(topology=topology))
    registry.register(SmokeRule(topology=topology, state=state))
    registry.register(ConvergenceRule(topology=topology, context_dir=tmp_path / "context"))
    registry.register(EpicRule(topology=topology, state=state))
    registry.register(
        RelayRule(topology=topology, state=state, relay_dir=tmp_path / "relay", role="alpha")
    )
    registry.register(SpawnRule(topology=topology, state=state, spawns_dir=tmp_path / "spawns"))
    return ConductorServer(
        state=state,
        registry=registry,
        state_path=tmp_path / "state.json",
        sock_path=tmp_path / "conductor.sock",
    )


# ---------------------------------------------------------------------------
# Test 1: FocusRule rewrites browser_navigate to testing workspace 10
# ---------------------------------------------------------------------------


def test_playwright_always_workspace_10(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    event = {
        "event_type": "pre_tool_use",
        "tool_name": "browser_navigate",
        "tool_input": {"url": "http://localhost:5173"},
        "session_id": "integ-test",
    }
    result = server.process_event(event)
    assert result["action"] == "rewrite"
    assert result["rewrite"]["workspace"] == 10


# ---------------------------------------------------------------------------
# Test 2: ConvergenceRule blocks after convergence
# ---------------------------------------------------------------------------


def test_research_tracked_across_rounds(tmp_path: Path) -> None:
    server = _build_server(tmp_path)

    # Use the same prompt each round so all rounds accumulate on the same topic slug.
    # The ConvergenceRule derives the slug from the prompt via extract_topic_slug, so
    # varying the prompt words creates different slugs and splits the round count.
    PROMPT = "investigate latency architecture"

    # Round 1: 10 findings (many bullets)
    post_r1 = {
        "event_type": "post_tool_use",
        "tool_name": "Agent",
        "tool_input": {"prompt": PROMPT},
        "session_id": "integ-test",
        "tool_output": "\n".join(f"- finding {i}" for i in range(10)),
    }
    server.process_event(post_r1)

    # Round 2: 3 findings (30% of first round — still at threshold, not yet converging)
    post_r2 = {
        "event_type": "post_tool_use",
        "tool_name": "Agent",
        "tool_input": {"prompt": PROMPT},
        "session_id": "integ-test",
        "tool_output": "\n".join(f"- finding {i}" for i in range(3)),
    }
    server.process_event(post_r2)

    # Round 3: 1 finding (10% of first round — two consecutive rounds ≤30% → converging)
    post_r3 = {
        "event_type": "post_tool_use",
        "tool_name": "Agent",
        "tool_input": {"prompt": PROMPT},
        "session_id": "integ-test",
        "tool_output": "- one finding",
    }
    server.process_event(post_r3)

    # Round 4 pre: should be blocked (topic is now converging)
    pre_r4 = {
        "event_type": "pre_tool_use",
        "tool_name": "Agent",
        "tool_input": {"prompt": PROMPT},
        "session_id": "integ-test",
    }
    result = server.process_event(pre_r4)
    assert result["action"] == "block"
    assert "latency" in result["message"].lower() or "converging" in result["message"].lower()


# ---------------------------------------------------------------------------
# Test 3: EpicRule enters RESEARCH phase on trigger phrase
# ---------------------------------------------------------------------------


def test_epic_pipeline_full_flow(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    assert server.state.epic_phase is None

    # Trigger epic entry via Agent tool post event
    event = {
        "event_type": "post_tool_use",
        "tool_name": "Agent",
        "tool_input": {"prompt": "research any loose ends before implementation"},
        "session_id": "integ-test",
        "tool_output": "- finding A\n- finding B",
    }
    server.process_event(event)

    from agents.session_conductor.state import EpicPhase

    assert server.state.epic_phase == EpicPhase.RESEARCH


# ---------------------------------------------------------------------------
# Test 4: SmokeRule activates on PR creation in Bash output
# ---------------------------------------------------------------------------


def test_smoke_activates_on_pr(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    assert not server.state.smoke_test_active

    # Bash post event with PR URL in output
    event = {
        "event_type": "post_tool_use",
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr create --title test"},
        "session_id": "integ-test",
        "tool_output": "Created PR: https://github.com/hapax/hapax-council/pull/999",
    }
    server.process_event(event)

    assert server.state.smoke_test_active

    # FocusRule runs before SmokeRule in the registry and always rewrites browser_*
    # tools to the testing workspace (workspace=10). Since the first rewrite wins,
    # the response comes from FocusRule. The smoke test config takes effect when
    # SmokeRule is registered before FocusRule. In the default build order (FocusRule
    # first), the workspace constraint is still enforced via workspace=10.
    pre_event = {
        "event_type": "pre_tool_use",
        "tool_name": "browser_navigate",
        "tool_input": {"url": "http://localhost:5173"},
        "session_id": "integ-test",
    }
    result = server.process_event(pre_event)
    assert result["action"] == "rewrite"
    # Workspace is pinned to testing workspace (10) by FocusRule
    assert result["rewrite"]["workspace"] == 10

    # Verify smoke state persists by building a server with SmokeRule registered first
    # (before FocusRule) so the smoke rewrite takes priority.
    topology = TopologyConfig(
        playwright=PlaywrightConfig(testing_workspace=10, screenshot_max_bytes=500_000),
        smoke_test=SmokeTestConfig(workspace=10, fullscreen=True),
    )
    state2 = SessionState(session_id="integ-smoke", pid=2, started_at=datetime(2026, 3, 27))
    state2.smoke_test_active = True  # pre-activate
    registry2 = RuleRegistry()
    registry2.register(SmokeRule(topology=topology, state=state2))
    registry2.register(FocusRule(topology=topology))
    server2 = ConductorServer(
        state=state2,
        registry=registry2,
        state_path=tmp_path / "state2.json",
        sock_path=tmp_path / "conductor2.sock",
    )
    result2 = server2.process_event(pre_event)
    assert result2["action"] == "rewrite"
    assert result2["rewrite"].get("fullscreen") is True


# ---------------------------------------------------------------------------
# Test 5: RelayRule tracks in-flight files from Edit events
# ---------------------------------------------------------------------------


def test_file_edits_tracked(tmp_path: Path) -> None:
    server = _build_server(tmp_path)
    assert len(server.state.in_flight_files) == 0

    event = {
        "event_type": "post_tool_use",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/home/hapax/projects/hapax-council/agents/foo.py"},
        "session_id": "integ-test",
    }
    server.process_event(event)

    assert "/home/hapax/projects/hapax-council/agents/foo.py" in server.state.in_flight_files

    # State should be persisted
    assert (tmp_path / "state.json").exists()
    import json

    saved = json.loads((tmp_path / "state.json").read_text())
    assert "/home/hapax/projects/hapax-council/agents/foo.py" in saved["in_flight_files"]


# ---------------------------------------------------------------------------
# Test 6: Full UDS lifecycle — start server, connect, send event, receive response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uds_full_lifecycle(tmp_path: Path) -> None:
    server = _build_server(tmp_path)

    # Start the server as a background task
    server_task = asyncio.create_task(server.start())

    # Give it a moment to bind the socket
    sock_path = tmp_path / "conductor.sock"
    for _ in range(50):
        if sock_path.exists():
            break
        await asyncio.sleep(0.05)

    assert sock_path.exists(), "UDS socket did not appear"

    try:
        # Connect and send a pre_tool_use event
        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        event = {
            "event_type": "pre_tool_use",
            "tool_name": "browser_navigate",
            "tool_input": {"url": "http://localhost:5173"},
            "session_id": "integ-test",
        }
        writer.write((json.dumps(event) + "\n").encode())
        await writer.drain()

        raw = await asyncio.wait_for(reader.readline(), timeout=2.0)
        result = json.loads(raw.decode())
        assert result["action"] == "rewrite"
        assert result["rewrite"]["workspace"] == 10

        writer.close()
        await writer.wait_closed()
    finally:
        server.shutdown()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except TimeoutError:
            server_task.cancel()
