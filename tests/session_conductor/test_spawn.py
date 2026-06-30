"""Tests for the session spawn and reunion rule."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from agents.session_conductor.rules import HookEvent
from agents.session_conductor.rules.spawn import SpawnRule, detect_spawn_intent
from agents.session_conductor.state import SessionState
from agents.session_conductor.topology import TopologyConfig


@pytest.fixture(autouse=True)
def _clear_parent_route_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HAPAX_PARENT_ROUTE_ENVELOPE",
        "HAPAX_REQUIRE_PARENT_ROUTE_ENVELOPE",
        "HAPAX_CHILD_SPAWN_ENVELOPE",
        "HAPAX_CHILD_RECEIPT_REF",
        "HAPAX_CHILD_RECEIPT_ID",
    ):
        monkeypatch.delenv(name, raising=False)


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


def _make_agent_pre_event(agent_name: str = "shader-bridge-auditor") -> HookEvent:
    return HookEvent(
        event_type="pre_tool_use",
        tool_name="Agent",
        tool_input={"subagent_type": agent_name, "prompt": "audit the bridge"},
        session_id="sess-alpha",
    )


def _write_parent_envelope(path: Path) -> Path:
    payload = {
        "parent_route_resource_envelope_schema": 1,
        "envelope_id": "parent-route-session-conductor-test",
        "issued_at": "2026-06-30T05:00:00+00:00",
        "stale_after": "999999h",
        "task_id": "cc-task-session-conductor-test",
        "lane": "cx-cap-subagent",
        "platform": "codex",
        "mode": "headless",
        "profile": "full",
        "route_id": "codex.headless.full",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "parent_spec": "/vault/spec.md",
        "route_decision_id": "decision-session-conductor-test",
        "route_decision_receipt_ref": "route-decision-receipt:test",
        "capability_profile": "codex.headless.full",
        "resource_budget": {
            "quota_state": "ok",
            "quota_receipt_refs": ["quota-receipt:test"],
            "resource_receipt_refs": ["resource-receipt:test"],
            "quota_freshness_green": True,
            "resource_freshness_green": True,
            "stale_after": "999999h",
        },
        "stop_conditions": ["parent_task_closed", "budget_or_resource_receipt_stale"],
        "receipt_chain": [
            "route-decision-receipt:test",
            "route-decision:decision-session-conductor-test",
            "resource-receipt:test",
            "quota-receipt:test",
        ],
        "child_receipts": [],
    }
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


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


def test_writes_manifest_on_spawn_intent(tmp_path: Path):
    state = _make_state()
    topology = TopologyConfig()
    rule = SpawnRule(topology, state, spawns_dir=tmp_path)

    event = _make_user_msg_event("let's break this out into a new session for the relay work")
    rule.on_post_tool_use(event)

    manifests = list(tmp_path.glob("*.yaml"))
    assert len(manifests) == 1
    data = yaml.safe_load(manifests[0].read_text())
    assert data["status"] == "pending"
    assert data["parent_session"] == "sess-alpha"
    assert len(state.children) == 1


def test_spawn_manifest_records_parent_child_route_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    parent_path = _write_parent_envelope(tmp_path / "parent.json")
    monkeypatch.setenv("HAPAX_PARENT_ROUTE_ENVELOPE", str(parent_path))
    monkeypatch.setattr(
        "agents.session_conductor.rules.spawn.DEFAULT_ORCHESTRATION_LEDGER_DIR",
        tmp_path / "ledger",
    )
    state = _make_state()
    rule = SpawnRule(TopologyConfig(), state, spawns_dir=tmp_path / "spawns")

    manifest_path = rule._write_manifest(topic="fix relay bug", context="spawn a child session")

    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert data["parent_route_envelope"] == str(parent_path)
    assert data["child_spawn_envelope"].endswith(".json")
    assert data["child_receipt_id"].startswith("child-receipt-")
    assert data["child_receipt_ref"].startswith("child-spawn-envelope:")

    parent_payload = json.loads(parent_path.read_text(encoding="utf-8"))
    receipt = parent_payload["child_receipts"][0]
    assert receipt["child_id"] == f"session-conductor:{data['child_id']}"
    assert receipt["capability_role"] == "capability_aggregator"
    assert receipt["receipt_refs"][0] == data["child_receipt_ref"]


def test_spawn_intent_blocks_when_required_parent_route_receipt_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("HAPAX_REQUIRE_PARENT_ROUTE_ENVELOPE", "1")
    state = _make_state()
    rule = SpawnRule(TopologyConfig(), state, spawns_dir=tmp_path)

    response = rule.on_post_tool_use(_make_user_msg_event("spawn a child session for relay work"))

    assert response is not None
    assert response.action == "block"
    assert "missing_parent_route_resource_receipt" in (response.message or "")
    assert "next action:" in (response.message or "")
    assert list(tmp_path.glob("*.yaml")) == []


def test_agent_tool_spawn_blocks_without_parent_route_receipt(tmp_path: Path):
    state = _make_state()
    rule = SpawnRule(TopologyConfig(), state, spawns_dir=tmp_path)

    response = rule.on_pre_tool_use(_make_agent_pre_event())

    assert response is not None
    assert response.action == "block"
    assert "missing_parent_route_resource_receipt" in (response.message or "")
    assert "before invoking Agent/Task" in (response.message or "")


def test_agent_tool_spawn_records_child_receipt_before_subagent_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    parent_path = _write_parent_envelope(tmp_path / "parent.json")
    monkeypatch.setenv("HAPAX_PARENT_ROUTE_ENVELOPE", str(parent_path))
    monkeypatch.setattr(
        "agents.session_conductor.rules.spawn.DEFAULT_ORCHESTRATION_LEDGER_DIR",
        tmp_path / "ledger",
    )
    state = _make_state()
    rule = SpawnRule(TopologyConfig(), state, spawns_dir=tmp_path / "spawns")

    response = rule.on_pre_tool_use(_make_agent_pre_event())

    assert response is None
    parent_payload = json.loads(parent_path.read_text(encoding="utf-8"))
    receipt = parent_payload["child_receipts"][0]
    assert receipt["shape"] == "subagent"
    assert receipt["child_id"].startswith("claude-subagent:shader-bridge-auditor:sess-alpha:")
    assert receipt["capability_id"] == "claude-subagent:shader-bridge-auditor"
    assert receipt["receipt_refs"][0].startswith("child-spawn-envelope:")


def test_child_claims_manifest(tmp_path: Path):
    # Parent writes manifest
    parent_state = _make_state("sess-alpha")
    topology = TopologyConfig()
    parent_rule = SpawnRule(topology, parent_state, spawns_dir=tmp_path)
    parent_rule._write_manifest(topic="fix relay bug")

    # Child claims it
    child_state = _make_state("sess-beta")
    child_rule = SpawnRule(topology, child_state, spawns_dir=tmp_path)
    claimed = child_rule.claim_pending_manifest(child_state)

    assert claimed is not None
    assert claimed["status"] == "claimed"
    assert claimed["claimed_by"] == "sess-beta"
    assert child_state.parent_session == "sess-alpha"


def test_child_blocked_from_parent_files(tmp_path: Path):
    # Parent session has in-flight files
    parent_state = _make_state("sess-alpha")
    parent_state.in_flight_files = {"/foo/bar.py", "/baz/qux.py"}

    # Child session knows it has a parent
    child_state = _make_state("sess-beta", parent="sess-alpha")
    child_state.in_flight_files = {"/foo/bar.py", "/baz/qux.py"}  # same files as parent

    topology = TopologyConfig()
    # Child's rule knows about the parent's blocked files via state
    child_rule = SpawnRule(topology, child_state, spawns_dir=tmp_path)

    # Block child from editing a parent-owned file
    event = _make_edit_event("/foo/bar.py", session_id="sess-beta")
    response = child_rule.on_pre_tool_use(event)

    assert response is not None
    assert response.action == "block"
    assert "sess-alpha" in (response.message or "")


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
