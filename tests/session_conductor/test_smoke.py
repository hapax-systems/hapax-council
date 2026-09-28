"""Tests for the smoke test rule."""

from __future__ import annotations

from datetime import datetime

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.smoke import SmokeRule, is_smoke_test_trigger
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig


def _make_state() -> SessionState:
    return SessionState(
        session_id="sess-alpha",
        pid=12345,
        started_at=datetime.now(),
        smoke_test_active=False,
    )


def _make_user_msg_event(message: str) -> HookEvent:
    # An operator turn: the operator's own words, on the operator-turn event (M103).
    return HookEvent(
        event_type="user_prompt",
        tool_name="",
        tool_input={},
        session_id="sess-alpha",
        user_message=message,
    )


def _make_browser_event(tool_name: str = "browser_navigate") -> HookEvent:
    return HookEvent(
        event_type="pre_tool_use",
        tool_name=tool_name,
        tool_input={"url": "http://localhost:5173"},
        session_id="sess-alpha",
    )


def _make_bash_pr_event(pr_url: str) -> HookEvent:
    return HookEvent(
        event_type="post_tool_use",
        tool_name="Bash",
        tool_input={"command": "gh pr create"},
        session_id="sess-alpha",
        tool_output=pr_url,
    )


# ---------------------------------------------------------------------------
# is_smoke_test_trigger tests
# ---------------------------------------------------------------------------


def test_is_smoke_test_trigger_matches():
    assert is_smoke_test_trigger("please run a smoke test now") is True
    assert is_smoke_test_trigger("Smoke Test the UI") is True


def test_is_smoke_test_trigger_no_match():
    assert is_smoke_test_trigger("run the full test suite") is False
    assert is_smoke_test_trigger("just deploy it") is False


# ---------------------------------------------------------------------------
# SmokeRule tests
# ---------------------------------------------------------------------------


def test_activates_on_user_message():
    state = _make_state()
    topology = TopologyConfig()
    rule = SmokeRule(topology, state)

    event = _make_user_msg_event("let's do a smoke test of the new feature")
    rule.on_user_prompt(event)

    assert state.smoke_test_active is True


def test_activates_on_pr_create():
    state = _make_state()
    topology = TopologyConfig()
    rule = SmokeRule(topology, state)

    event = _make_bash_pr_event("https://github.com/foo/bar/pull/42")
    rule.on_post_tool_use(event)

    assert state.smoke_test_active is True


def test_rewrites_playwright_when_active():
    state = _make_state()
    state.smoke_test_active = True
    topology = TopologyConfig()
    rule = SmokeRule(topology, state)

    event = _make_browser_event("browser_navigate")
    response = rule.on_pre_tool_use(event)

    assert response is not None
    assert response.action == "rewrite"
    assert response.rewrite is not None
    assert response.rewrite["workspace"] == topology.smoke_test.workspace
    assert response.rewrite["fullscreen"] == topology.smoke_test.fullscreen


def test_no_rewrite_when_inactive():
    state = _make_state()
    assert state.smoke_test_active is False
    topology = TopologyConfig()
    rule = SmokeRule(topology, state)

    event = _make_browser_event("browser_navigate")
    response = rule.on_pre_tool_use(event)

    assert response is None
