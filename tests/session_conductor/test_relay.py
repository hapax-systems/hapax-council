"""Tests for the relay sync rule."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.relay import (
    RelayRule,
    detect_pr_event,
)
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig


def _make_state(session_id: str = "sess-alpha") -> SessionState:
    return SessionState(
        session_id=session_id,
        pid=12345,
        started_at=datetime.now(),
    )


def _make_bash_event(output: str, session_id: str = "sess-alpha") -> HookEvent:
    return HookEvent(
        event_type="post_tool_use",
        tool_name="Bash",
        tool_input={"command": "gh pr create ..."},
        session_id=session_id,
        user_message=output,
    )


def _make_edit_event(file_path: str, session_id: str = "sess-alpha") -> HookEvent:
    return HookEvent(
        event_type="post_tool_use",
        tool_name="Edit",
        tool_input={"file_path": file_path},
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# detect_pr_event tests
# ---------------------------------------------------------------------------


def test_detect_pr_create():
    output = "Created PR: https://github.com/foo/bar/pull/42"
    result = detect_pr_event(output)
    assert result is not None
    assert result["type"] == "create"
    assert result["pr_number"] == 42


def test_detect_pr_merge():
    output = "Pull request #17 merged into main"
    result = detect_pr_event(output)
    assert result is not None
    assert result["type"] == "merge"
    assert result["pr_number"] == 17


def test_detect_no_pr():
    output = "Nothing interesting here, just some random output"
    result = detect_pr_event(output)
    assert result is None


# ---------------------------------------------------------------------------
# RelayRule tests
# ---------------------------------------------------------------------------


def test_writes_status_on_pr_event(tmp_path: Path):
    state = _make_state()
    topology = TopologyConfig()
    rule = RelayRule(topology, state, relay_dir=tmp_path, role="alpha")

    event = _make_bash_event("Created PR: https://github.com/foo/bar/pull/99")
    rule.on_post_tool_use(event)

    status_file = tmp_path / "alpha-status.yaml"
    assert status_file.exists()
    data = yaml.safe_load(status_file.read_text())
    assert data["event_type"] == "pr_create"
    assert data["pr_event"]["pr_number"] == 99


def test_periodic_sync_when_never_synced(tmp_path: Path):
    state = _make_state()
    assert state.last_relay_sync is None
    topology = TopologyConfig()
    rule = RelayRule(topology, state, relay_dir=tmp_path, role="alpha")

    event = HookEvent(
        event_type="post_tool_use",
        tool_name="Agent",
        tool_input={"prompt": "do something"},
        session_id="sess-alpha",
    )
    rule.on_post_tool_use(event)

    status_file = tmp_path / "alpha-status.yaml"
    assert status_file.exists()
    data = yaml.safe_load(status_file.read_text())
    assert data["event_type"] == "periodic"


def test_tracks_in_flight_files(tmp_path: Path):
    state = _make_state()
    topology = TopologyConfig()
    rule = RelayRule(topology, state, relay_dir=tmp_path, role="alpha")

    rule.on_post_tool_use(_make_edit_event("/foo/bar.py"))
    rule.on_post_tool_use(_make_edit_event("/baz/qux.py"))

    assert "/foo/bar.py" in state.in_flight_files
    assert "/baz/qux.py" in state.in_flight_files


def test_detects_peer_conflicts(tmp_path: Path):
    # Write a beta peer status file with overlapping file
    peer_status = {
        "session_id": "sess-beta",
        "role": "beta",
        "in_flight_files": ["/foo/bar.py", "/other/file.py"],
    }
    (tmp_path / "beta-status.yaml").write_text(yaml.dump(peer_status))

    state = _make_state()
    state.in_flight_files = {"/foo/bar.py", "/alpha-only.py"}
    topology = TopologyConfig()
    rule = RelayRule(topology, state, relay_dir=tmp_path, role="alpha")

    conflicts = rule.check_peer_conflicts()
    assert "/foo/bar.py" in conflicts
    assert "/alpha-only.py" not in conflicts


def test_no_conflicts_when_no_in_flight(tmp_path: Path):
    peer_status = {
        "session_id": "sess-beta",
        "role": "beta",
        "in_flight_files": ["/foo/bar.py"],
    }
    (tmp_path / "beta-status.yaml").write_text(yaml.dump(peer_status))

    state = _make_state()
    # in_flight_files is empty
    topology = TopologyConfig()
    rule = RelayRule(topology, state, relay_dir=tmp_path, role="alpha")

    conflicts = rule.check_peer_conflicts()
    assert conflicts == []
