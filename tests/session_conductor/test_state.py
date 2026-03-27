"""Tests for session conductor state model."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agents.session_conductor.state import (
    ChildSession,
    EpicPhase,
    SessionState,
    TopicState,
)


def test_session_state_creation():
    state = SessionState(
        session_id="abc-123",
        pid=12345,
        started_at=datetime(2026, 3, 27, 12, 0, 0),
    )
    assert state.session_id == "abc-123"
    assert state.pid == 12345
    assert state.parent_session is None
    assert state.children == []
    assert state.active_topics == {}
    assert state.in_flight_files == set()
    assert state.epic_phase is None


def test_topic_state_is_converging_true():
    topic = TopicState(
        slug="compositor-effects",
        rounds=3,
        findings_per_round=[12, 3, 1],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.is_converging() is True


def test_topic_state_is_converging_false_too_few_rounds():
    topic = TopicState(
        slug="compositor-effects",
        rounds=1,
        findings_per_round=[12],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.is_converging() is False


def test_topic_state_is_converging_false_not_decreasing():
    topic = TopicState(
        slug="compositor-effects",
        rounds=3,
        findings_per_round=[5, 8, 7],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.is_converging() is False


def test_topic_state_is_capped():
    topic = TopicState(
        slug="test",
        rounds=5,
        findings_per_round=[10, 8, 6, 4, 2],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.is_capped() is True


def test_topic_state_not_capped():
    topic = TopicState(
        slug="test",
        rounds=3,
        findings_per_round=[10, 8, 6],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.is_capped() is False


def test_epic_phase_ordering():
    assert EpicPhase.RESEARCH.value == "research"
    assert EpicPhase.IMPLEMENTATION.value == "implementation"
    phases = list(EpicPhase)
    assert phases[0] == EpicPhase.RESEARCH
    assert phases[-1] == EpicPhase.IMPLEMENTATION


def test_session_state_serialize_roundtrip(tmp_path: Path):
    state = SessionState(
        session_id="abc-123",
        pid=12345,
        started_at=datetime(2026, 3, 27, 12, 0, 0),
    )
    state.active_topics["test"] = TopicState(
        slug="test",
        rounds=2,
        findings_per_round=[5, 3],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=tmp_path / "test.md",
    )
    state.in_flight_files.add("foo.py")

    path = tmp_path / "state.json"
    state.save(path)
    loaded = SessionState.load(path)

    assert loaded.session_id == "abc-123"
    assert loaded.pid == 12345
    assert "test" in loaded.active_topics
    assert loaded.active_topics["test"].rounds == 2
    assert "foo.py" in loaded.in_flight_files


def test_topic_slug_matching():
    topic = TopicState(
        slug="compositor-effects",
        rounds=1,
        findings_per_round=[5],
        first_seen=datetime(2026, 3, 27, 12, 0, 0),
        prior_file=Path("/tmp/test.md"),
    )
    assert topic.matches_prompt("research all compositor effects touch points") is True
    assert topic.matches_prompt("fix the login screen") is False


def test_child_session_creation():
    child = ChildSession(
        session_id="child-1",
        topic="logos-api-bug",
        spawn_manifest=Path("/tmp/spawn.yaml"),
        status="pending",
    )
    assert child.session_id == "child-1"
    assert child.status == "pending"
