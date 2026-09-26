"""Tests for the session spawn and reunion rule."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import yaml

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.spawn import SpawnRule, detect_spawn_intent
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig


def _make_state(session_id: str = "sess-alpha", parent: str | None = None) -> SessionState:
    state = SessionState(
        session_id=session_id,
        pid=12345,
        started_at=datetime.now(),
    )
    state.parent_session = parent
    return state


def _make_user_msg_event(message: str) -> HookEvent:
    return HookEvent(
        event_type="post_tool_use",
        tool_name="Agent",
        tool_input={},
        session_id="sess-alpha",
        user_message=message,
    )


def _make_edit_event(file_path: str, session_id: str = "sess-beta") -> HookEvent:
    return HookEvent(
        event_type="pre_tool_use",
        tool_name="Edit",
        tool_input={"file_path": file_path},
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# detect_spawn_intent tests
# ---------------------------------------------------------------------------


def test_detect_spawn_intent_break_out():
    assert detect_spawn_intent("let's break this out into another session") is True


def test_detect_spawn_intent_another_session_fix():
    assert detect_spawn_intent("another session fix this bug") is True


def test_detect_spawn_intent_spawn_child():
    assert detect_spawn_intent("spawn a child session for this") is True


def test_detect_spawn_intent_no_match():
    assert detect_spawn_intent("just keep going with what we have") is False


# ---------------------------------------------------------------------------
# SpawnRule tests
# ---------------------------------------------------------------------------


def test_tool_output_never_mints_a_manifest(tmp_path: Path):
    """M103: conductor-post.sh sends a tool's stdout as `user_message`. A grep of source
    code containing a spawn phrase minted a manifest that an unrelated lane adopted."""
    state = _make_state()
    rule = SpawnRule(TopologyConfig(), state, spawns_dir=tmp_path)

    rule.on_post_tool_use(_make_user_msg_event("27:    re.compile(r'spawn a (child|session)')"))
    rule.on_post_tool_use(_make_user_msg_event("let's break this out into a new session"))

    assert list(tmp_path.glob("*.yaml")) == []
    assert state.children == []


def test_operator_prompt_event_writes_manifest(tmp_path: Path):
    state = _make_state()
    rule = SpawnRule(TopologyConfig(), state, spawns_dir=tmp_path)
    event = HookEvent(
        event_type="user_prompt",
        tool_name="",
        tool_input={},
        session_id="sess-alpha",
        user_message="let's break this out into a new session for the relay work",
    )

    rule.on_post_tool_use(event)

    manifests = list(tmp_path.glob("*.yaml"))
    assert len(manifests) == 1
    data = yaml.safe_load(manifests[0].read_text())
    assert data["status"] == "pending"
    assert data["parent_session"] == "sess-alpha"
    assert len(state.children) == 1


def test_no_manifest_is_adopted_without_an_explicit_binding(tmp_path: Path):
    """M103: adoption was lineage-blind: any conductor starting within 10 minutes took any
    pending manifest (dev14 -> dev17 -> dev18, and the seat). Only a named one is taken."""
    parent_state = _make_state("sess-alpha")
    topology = TopologyConfig()
    manifest = SpawnRule(topology, parent_state, spawns_dir=tmp_path)._write_manifest(
        topic="fix relay bug"
    )
    before = manifest.read_bytes()

    stranger = _make_state("sess-unrelated")
    rule = SpawnRule(topology, stranger, spawns_dir=tmp_path)

    assert rule.claim_pending_manifest(stranger) is None
    assert rule.claim_pending_manifest(stranger, manifest_id="no-such-child") is None
    assert rule.claim_pending_manifest(stranger, manifest_id="../escape") is None
    assert stranger.parent_session is None
    assert manifest.read_bytes() == before


def test_child_claims_the_manifest_it_was_launched_for(tmp_path: Path):
    parent_state = _make_state("sess-alpha")
    parent_state.in_flight_files = {"/foo/bar.py"}
    topology = TopologyConfig()
    manifest = SpawnRule(topology, parent_state, spawns_dir=tmp_path)._write_manifest(
        topic="fix relay bug"
    )

    child_state = _make_state("sess-beta")
    child_rule = SpawnRule(topology, child_state, spawns_dir=tmp_path)
    claimed = child_rule.claim_pending_manifest(child_state, manifest_id=manifest.stem)

    assert claimed is not None
    assert claimed["status"] == "claimed"
    assert claimed["claimed_by"] == "sess-beta"
    assert child_state.parent_session == "sess-alpha"
    assert child_state.parent_blocked_patterns == {"/foo/bar.py"}
    assert child_state.in_flight_files == set()


def test_child_blocked_from_parent_files(tmp_path: Path):
    child_state = _make_state("sess-beta", parent="sess-alpha")
    child_state.parent_blocked_patterns = {"/foo/bar.py", "/baz/qux.py"}
    child_rule = SpawnRule(TopologyConfig(), child_state, spawns_dir=tmp_path)

    response = child_rule.on_pre_tool_use(_make_edit_event("/foo/bar.py", session_id="sess-beta"))

    assert response is not None
    assert response.action == "block"
    assert "sess-alpha" in (response.message or "")


def test_child_is_never_blocked_by_its_own_edits(tmp_path: Path):
    """M103: the block read the child's own in_flight_files, which grow on every edit, so
    a child could write each file exactly once."""
    child_state = _make_state("sess-beta", parent="sess-alpha")
    child_state.in_flight_files = {"/mine/row.md"}
    child_rule = SpawnRule(TopologyConfig(), child_state, spawns_dir=tmp_path)

    assert child_rule.on_pre_tool_use(_make_edit_event("/mine/row.md", "sess-beta")) is None


def test_stopping_a_parent_abandons_its_pending_children(tmp_path: Path):
    """M106 (2): a stopped session's pending manifests stayed adoptable after it was gone."""
    parent_state = _make_state("sess-alpha")
    rule = SpawnRule(TopologyConfig(), parent_state, spawns_dir=tmp_path)
    manifest = rule._write_manifest(topic="never launched")

    rule.retire_pending_children()

    assert yaml.safe_load(manifest.read_text())["status"] == "abandoned"


def test_stale_manifest_ignored(tmp_path: Path):
    topology = TopologyConfig()
    state = _make_state("sess-alpha")
    rule = SpawnRule(topology, state, spawns_dir=tmp_path)

    # Write a manifest with an old timestamp (>10 minutes ago)
    old_time = (datetime.now() - timedelta(minutes=15)).isoformat()
    manifest = {
        "child_id": "oldchild",
        "parent_session": "sess-parent",
        "topic": "old work",
        "created_at": old_time,
        "status": "pending",
        "blocked_patterns": [],
    }
    (tmp_path / "oldchild.yaml").write_text(yaml.dump(manifest))

    child_state = _make_state("sess-new")
    claimed = rule.claim_pending_manifest(child_state)
    assert claimed is None


def test_reunion_injects_results(tmp_path: Path):
    from agents.session_conductor.state import ChildSession

    parent_state = _make_state("sess-alpha")
    topology = TopologyConfig()
    rule = SpawnRule(topology, parent_state, spawns_dir=tmp_path)

    # Write a completed manifest
    manifest_path = tmp_path / "child01.yaml"
    manifest_data = {
        "child_id": "child01",
        "parent_session": "sess-alpha",
        "topic": "fix relay",
        "status": "completed",
        "result_summary": "Fixed the relay bug in 3 files",
    }
    manifest_path.write_text(yaml.dump(manifest_data))

    # Add the child to parent state
    child = ChildSession(
        session_id="child01",
        topic="fix relay",
        spawn_manifest=manifest_path,
        status="pending",
    )
    parent_state.children.append(child)

    completed = rule.check_completed_children(parent_state)
    assert len(completed) == 1
    assert completed[0]["result_summary"] == "Fixed the relay bug in 3 files"
    assert child.status == "completed"
