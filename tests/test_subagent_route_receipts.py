"""Tests for parent route/resource receipts used by subagent fanout."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.subagent_route_receipts import (
    PARENT_ROUTE_ENVELOPE_ENV,
    REQUIRE_PARENT_ROUTE_ENVELOPE_ENV,
    ChildCapabilityRequest,
    ParentRouteResourceEnvelope,
    ResourceBudgetReceipt,
    SpawnCapabilityShape,
    SubagentRouteReceiptError,
    admit_and_record_child_spawn,
    admit_child_spawn,
    child_request_for_parent,
    load_parent_route_resource_envelope,
    record_child_receipt,
    require_parent_envelope_path_from_env,
    spawn_surface_inventory,
    write_parent_route_resource_envelope,
)

NOW = datetime(2026, 6, 30, 5, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[1]


def _parent(*, issued_at: datetime = NOW) -> ParentRouteResourceEnvelope:
    return ParentRouteResourceEnvelope(
        envelope_id="parent-route-test",
        issued_at=issued_at,
        stale_after="2h",
        task_id="cc-task-test",
        lane="cx-cap-subagent",
        platform="codex",
        mode="headless",
        profile="full",
        route_id="codex.headless.full",
        authority_case="CASE-CAPACITY-ROUTING-001",
        parent_spec="/vault/spec.md",
        route_decision_id="decision-test",
        route_decision_receipt_ref="route-decision-receipt:test",
        capability_profile="codex.headless.full",
        resource_budget=ResourceBudgetReceipt(
            quota_state="ok",
            quota_receipt_refs=("quota-receipt:test",),
            resource_receipt_refs=("resource-receipt:test",),
            quota_freshness_green=True,
            resource_freshness_green=True,
            stale_after="2h",
        ),
        stop_conditions=("parent_task_closed", "budget_or_resource_receipt_stale"),
        receipt_chain=(
            "route-decision-receipt:test",
            "route-decision:decision-test",
            "resource-receipt:test",
            "quota-receipt:test",
        ),
    )


def _child(shape: SpawnCapabilityShape = SpawnCapabilityShape.SUBAGENT) -> ChildCapabilityRequest:
    return ChildCapabilityRequest(
        child_id="child-1",
        task_id="cc-task-test",
        authority_case="CASE-CAPACITY-ROUTING-001",
        shape=shape,
        route_id="codex.headless.full",
        capability_role="implementer",
    )


def test_child_spawn_requires_parent_route_resource_receipt() -> None:
    with pytest.raises(SubagentRouteReceiptError, match="missing_parent_route_resource_receipt"):
        admit_child_spawn(None, _child(), now=NOW)


def test_stale_parent_budget_blocks_child_spawn() -> None:
    parent = _parent(issued_at=NOW - timedelta(hours=3))

    with pytest.raises(SubagentRouteReceiptError, match="stale_parent_budget"):
        admit_child_spawn(parent, _child(), now=NOW)


def test_parent_envelope_requires_resource_refs_in_receipt_chain() -> None:
    with pytest.raises(ValidationError, match="receipt_chain must include"):
        ParentRouteResourceEnvelope(
            envelope_id="bad-parent",
            issued_at=NOW,
            stale_after="2h",
            task_id="cc-task-test",
            lane="cx-cap-subagent",
            platform="codex",
            mode="headless",
            profile="full",
            route_id="codex.headless.full",
            authority_case="CASE-CAPACITY-ROUTING-001",
            route_decision_id="decision-test",
            route_decision_receipt_ref="route-decision-receipt:test",
            capability_profile="codex.headless.full",
            resource_budget=ResourceBudgetReceipt(
                resource_receipt_refs=("resource-receipt:test",),
            ),
            stop_conditions=("parent_task_closed",),
            receipt_chain=("route-decision-receipt:test",),
        )


def test_unsupported_child_shape_is_refused_by_schema() -> None:
    with pytest.raises(ValidationError, match="Input should be"):
        ChildCapabilityRequest(
            child_id="child-1",
            task_id="cc-task-test",
            authority_case="CASE-CAPACITY-ROUTING-001",
            shape="unmetered_side_worker",
            route_id="codex.headless.full",
        )


def test_nested_orchestrator_is_capability_aggregator_and_records_child_receipts() -> None:
    parent = _parent()
    with pytest.raises(ValidationError, match="proposed_child_capabilities"):
        _child(SpawnCapabilityShape.ORCHESTRATOR)

    child = ChildCapabilityRequest(
        child_id="orchestrator-1",
        task_id="cc-task-test",
        authority_case="CASE-CAPACITY-ROUTING-001",
        shape=SpawnCapabilityShape.ORCHESTRATOR,
        route_id="fugu.orchestrator.direct",
        capability_role="orchestrator",
        proposed_child_capabilities=("codex.headless.full", "glmcp.review.direct"),
    )
    spawn = admit_child_spawn(parent, child, now=NOW)

    assert spawn.capability_role == "capability_aggregator"
    with pytest.raises(SubagentRouteReceiptError, match="child_receipt_refs_required"):
        record_child_receipt(parent, spawn, receipt_refs=())

    updated = record_child_receipt(
        parent,
        spawn,
        receipt_refs=("child-route-receipt:1", "child-resource-receipt:1"),
        emitted_at=NOW,
    )

    receipt = updated.child_receipts[0]
    assert receipt.parent_envelope_id == parent.envelope_id
    assert receipt.capability_role == "capability_aggregator"
    assert receipt.receipt_refs == ("child-route-receipt:1", "child-resource-receipt:1")
    assert "child-resource-receipt:1" in receipt.receipt_chain


def test_admit_and_record_child_spawn_writes_child_envelope_and_parent_receipt(
    tmp_path: Path,
) -> None:
    parent = _parent()
    parent_path = write_parent_route_resource_envelope(parent, ledger_dir=tmp_path)
    child = child_request_for_parent(
        parent,
        child_id="codex-headless:cx-cap-subagent:test-session",
        capability_role="worker",
    )

    recorded = admit_and_record_child_spawn(
        parent_envelope_path=parent_path,
        child=child,
        ledger_dir=tmp_path,
        now=NOW,
    )

    child_path = Path(recorded.child_envelope_path)
    assert child_path.is_file()
    child_payload = json.loads(child_path.read_text(encoding="utf-8"))
    assert child_payload["parent_envelope_id"] == parent.envelope_id
    assert child_payload["child"]["child_id"] == "codex-headless:cx-cap-subagent:test-session"

    updated = load_parent_route_resource_envelope(parent_path)
    assert len(updated.child_receipts) == 1
    receipt = updated.child_receipts[0]
    assert receipt.receipt_id == recorded.child_receipt_id
    assert receipt.child_envelope_id == recorded.child_envelope_id
    assert recorded.child_receipt_ref in receipt.receipt_refs
    assert "child-runtime:codex-headless:cx-cap-subagent:test-session" in receipt.receipt_refs


def test_required_parent_route_envelope_env_fails_closed() -> None:
    assert require_parent_envelope_path_from_env({}) is None
    assert require_parent_envelope_path_from_env(
        {PARENT_ROUTE_ENVELOPE_ENV: "/tmp/parent.json"}
    ) == Path("/tmp/parent.json")
    with pytest.raises(SubagentRouteReceiptError, match="missing_parent_route_resource_receipt"):
        require_parent_envelope_path_from_env({REQUIRE_PARENT_ROUTE_ENVELOPE_ENV: "1"})


def test_spawn_surface_inventory_covers_auto_fire_and_fugu_style_orchestration() -> None:
    by_id = {surface.surface_id: surface for surface in spawn_surface_inventory()}

    assert by_id["claude_code_probabilistic_subagents"].shape is SpawnCapabilityShape.SUBAGENT
    assert "auto-fire" in by_id["claude_code_probabilistic_subagents"].receipt_requirement
    assert by_id["fugu_style_orchestration"].shape is SpawnCapabilityShape.ORCHESTRATOR
    assert (
        by_id["governed_worker_lane_dispatch"].shape is SpawnCapabilityShape.EXISTING_AGENT_HARNESS
    )


def test_claude_subagent_definitions_require_parent_route_receipt_gate() -> None:
    agent_dir = REPO_ROOT / "tooling" / "claude-agents"
    agent_paths = sorted(path for path in agent_dir.glob("*.md") if path.name != "INSTALL.md")

    assert agent_paths
    for path in agent_paths:
        text = path.read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        tools_line = next(
            (line for line in frontmatter.splitlines() if line.startswith("tools:")),
            "",
        )
        assert "Bash" in tools_line, path
        assert "hapax-child-spawn-receipt" in text, path
        assert "HAPAX_PARENT_ROUTE_ENVELOPE" in text, path
        assert "HAPAX_CHILD_RECEIPT_ID" in text, path


def test_worker_launchers_explain_missing_receipt_helper_next_action() -> None:
    launchers = (
        "hapax-antigrav",
        "hapax-claude",
        "hapax-claude-headless",
        "hapax-codex",
        "hapax-codex-headless",
        "hapax-vibe",
    )

    for name in launchers:
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "parent route envelope required but helper is missing" in text, name
        assert "next action: sync this worktree/branch" in text, name


def test_claude_install_docs_wire_agent_conductor_gate() -> None:
    text = (REPO_ROOT / "tooling" / "claude-agents" / "INSTALL.md").read_text(encoding="utf-8")

    assert '"matcher": "Agent"' in text
    assert "conductor-pre.sh" in text
    assert "Task-tool invocations are blocked" in text
