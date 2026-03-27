"""Tests for the epic pipeline rule."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.epic import EpicRule, is_epic_trigger
from agents.session_conductor.state import (
    EpicPhase,
    SessionState,
    TopicState,
)
from agents.session_conductor.topology import TopologyConfig


def _make_state(phase: EpicPhase | None = None) -> SessionState:
    state = SessionState(
        session_id="sess-1",
        pid=12345,
        started_at=datetime(2026, 3, 27),
    )
    state.epic_phase = phase
    return state


def _make_agent_event(prompt: str, session_id: str = "sess-1") -> HookEvent:
    return HookEvent(
        event_type="post_tool_use",
        tool_name="Agent",
        tool_input={"prompt": prompt},
        session_id=session_id,
        user_message="completed",
    )


def _make_write_event(file_path: str, content: str = "") -> HookEvent:
    return HookEvent(
        event_type="post_tool_use",
        tool_name="Write",
        tool_input={"file_path": file_path, "content": content},
        session_id="sess-1",
        user_message=None,
    )


def test_is_epic_trigger_research_loose_ends():
    assert is_epic_trigger("research any loose ends in the system") is True
    assert is_epic_trigger("research all loose ends before we proceed") is True


def test_is_epic_trigger_formal_design_doc():
    assert is_epic_trigger("write a formal design doc for the voice grounding system") is True


def test_is_epic_trigger_batched_planning():
    assert is_epic_trigger("do batched planning for the next sprint") is True


def test_is_epic_trigger_no_match():
    assert is_epic_trigger("fix the login screen bug") is False
    assert is_epic_trigger("run the tests") is False


def test_activates_on_pattern():
    topology = TopologyConfig()
    state = _make_state(phase=None)
    rule = EpicRule(topology, state)
    event = _make_agent_event("research any loose ends before designing")
    resp = rule.on_post_tool_use(event)
    assert state.epic_phase == EpicPhase.RESEARCH
    assert resp is not None
    assert "EPIC PIPELINE ACTIVATED" in (resp.message or "")


def test_transitions_to_design_on_convergence():
    topology = TopologyConfig()
    state = _make_state(phase=EpicPhase.RESEARCH)
    # Populate a converging topic
    slug = "compositor-effects"
    topic = TopicState(
        slug=slug,
        rounds=3,
        findings_per_round=[10, 1, 1],
        first_seen=datetime(2026, 3, 27),
        prior_file=Path("/tmp/test.md"),
    )
    state.active_topics[slug] = topic
    rule = EpicRule(topology, state)
    resp = rule._check_phase_transition(state)
    assert state.epic_phase == EpicPhase.DESIGN
    assert resp is not None
    assert "RESEARCH → DESIGN" in (resp.message or "")


def test_transitions_to_design_gaps_on_write():
    topology = TopologyConfig()
    state = _make_state(phase=EpicPhase.DESIGN)
    rule = EpicRule(topology, state)
    event = _make_write_event("/tmp/DESIGN.md", "# Design Document\n## Overview\n...")
    resp = rule.on_post_tool_use(event)
    assert state.epic_phase == EpicPhase.DESIGN_GAPS
    assert resp is not None
    assert "DESIGN → DESIGN_GAPS" in (resp.message or "")
    assert state.design_doc_path == "/tmp/DESIGN.md"


def test_gap_phases_capped():
    topology = TopologyConfig()
    state = _make_state(phase=EpicPhase.DESIGN_GAPS)
    state.gap_rounds = 2
    rule = EpicRule(topology, state)
    # After cap, should advance past gap phase
    resp = rule._check_phase_transition(state)
    assert state.epic_phase == EpicPhase.PLANNING
    assert resp is not None
    assert "DESIGN_GAPS → PLANNING" in (resp.message or "")


def test_transitions_to_implementation():
    topology = TopologyConfig()
    state = _make_state(phase=EpicPhase.PLANNING)
    rule = EpicRule(topology, state)
    event = _make_write_event("/tmp/PLAN.md", "# Implementation Plan\n1. Step one\n2. Step two\n")
    rule.on_post_tool_use(event)
    assert (
        state.epic_phase == EpicPhase.PLANNING_GAPS or state.epic_phase == EpicPhase.IMPLEMENTATION
    )
