"""Tests for tool sequence phase detection."""

from __future__ import annotations

from agents.dev_story.phase_detector import detect_phase_sequence, detect_phases


def test_detect_phases_explore():
    tools = ["Read", "Grep", "Glob", "Read", "Grep", "Read"]
    phases = detect_phases(tools)
    assert phases == ["explore"]


def test_detect_phases_implement():
    tools = ["Read", "Edit", "Write", "Edit", "Edit", "Bash"]
    phases = detect_phases(tools)
    assert "implement" in phases


def test_detect_phases_test():
    tools = ["Bash:pytest tests/ -v", "Bash:uv run pytest", "Bash:pytest"]
    phases = detect_phases(tools)
    assert "test" in phases


def test_detect_phases_debug_cycle():
    tools = [
        "Read",
        "Edit",
        "Bash:pytest",
        "Read",
        "Edit",
        "Bash:pytest",
        "Read",
        "Edit",
        "Bash:pytest",
    ]
    phases = detect_phases(tools)
    assert "debug" in phases


def test_detect_phases_design():
    tools = ["Agent", "Agent", "Agent"]
    phases = detect_phases(tools)
    assert "design" in phases


def test_detect_phase_sequence():
    tools = [
        "Grep",
        "Read",
        "Glob",
        "Read",  # explore
        "Edit",
        "Write",
        "Edit",  # implement
        "Bash:pytest tests/ -v",  # test
    ]
    seq = detect_phase_sequence(tools)
    assert seq == "explore>implement>test"


def test_detect_phase_sequence_empty():
    assert detect_phase_sequence([]) == ""


def test_detect_phase_sequence_single():
    tools = ["Read", "Read", "Grep"]
    seq = detect_phase_sequence(tools)
    assert seq == "explore"
