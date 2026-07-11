"""Tests for local shell tool route/resource receipt gating."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.dispatcher_policy import build_route_authority_receipt, write_route_authority_receipt
from shared.local_tool_policy import (
    classify_local_tool_command,
    evaluate_local_tool_receipt_gate,
)

TASK_ID = "cc-task-local-tool-invocation-route-resource-receipts-20260630"
ROLE = "cx-red"
ROUTE_ID = "codex.headless.full"
NOW = datetime(2026, 7, 6, 2, 30, tzinfo=UTC)


def _write_route_decision(path: Path, *, task_id: str = TASK_ID, route_id: str = ROUTE_ID) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "decision_schema": 1,
        "decision_id": "decision-local-tool",
        "created_at": NOW.isoformat(),
        "task_id": task_id,
        "lane": ROLE,
        "route_id": route_id,
        "action": "launch",
        "launch_allowed": True,
        "route_policy_green": True,
        "authority_allowed": True,
        "quota_freshness_green": True,
        "quota_evidence_refs": ["quota:codex"],
        "resource_freshness_green": True,
        "resource_state_refs": ["resource:appendix"],
    }
    path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")


def _write_local_tool_receipt(
    receipt_root: Path, surfaces: tuple[str, ...], *, stale: bool = False
) -> None:
    receipt = build_route_authority_receipt(
        receipt_type="local_tool_invocation",
        route_id=ROUTE_ID,
        evidence_refs=["operator-signed:local-tool-systemctl"],
        task_ids=[TASK_ID],
        mutation_surfaces=surfaces,
        stale_after="1h",
        issued_at=NOW - timedelta(hours=2) if stale else NOW,
    )
    write_route_authority_receipt(receipt, receipt_dir=receipt_root)


def test_read_only_shell_evidence_is_allowed_without_task() -> None:
    result = evaluate_local_tool_receipt_gate(
        "rg -n local_tool shared tests",
        task_id=None,
        role=None,
        now=NOW,
    )

    assert result.allowed is True
    assert result.reason_code == "read_only_or_bounded_evidence"
    assert result.classification is not None
    assert result.classification.side_effecting is False


def test_local_git_filesystem_mutation_is_classified_but_left_to_task_gate() -> None:
    classification = classify_local_tool_command("git add shared/local_tool_policy.py")

    assert classification.side_effecting is False
    assert classification.effect_classes == ("filesystem_mutation",)
    assert classification.required_mutation_surfaces == (
        "local_tool",
        "filesystem",
    )


def test_systemctl_mutation_classifies_process_control_surfaces() -> None:
    classification = classify_local_tool_command("systemctl --user restart hapax-dmn.service")

    assert classification.side_effecting is True
    assert classification.tool_id == "local_tool.systemctl"
    assert classification.required_mutation_surfaces == (
        "local_tool",
        "process_control",
        "local",
    )


def test_side_effecting_local_tool_requires_route_decision(tmp_path: Path) -> None:
    result = evaluate_local_tool_receipt_gate(
        "tmux new-session -d -s hapax-codex-cx-red",
        task_id=TASK_ID,
        role=ROLE,
        ledger_path=tmp_path / "missing-route-decisions.jsonl",
        receipt_root=tmp_path / "receipts",
        now=NOW,
    )

    assert result.allowed is False
    assert result.reason_code == "route_decision_absent"


def test_side_effecting_local_tool_requires_local_tool_invocation_receipt(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    _write_route_decision(ledger)

    result = evaluate_local_tool_receipt_gate(
        "systemctl --user restart hapax-dmn.service",
        task_id=TASK_ID,
        role=ROLE,
        ledger_path=ledger,
        receipt_root=tmp_path / "receipts",
        now=NOW,
    )

    assert result.allowed is False
    assert result.reason_code == "local_tool_invocation_receipt_absent"
    assert result.route_id == ROUTE_ID


def test_fresh_local_tool_invocation_receipt_allows_process_control(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    receipt_root = tmp_path / "receipts"
    _write_route_decision(ledger)
    classification = classify_local_tool_command("systemctl --user restart hapax-dmn.service")
    _write_local_tool_receipt(receipt_root, classification.required_mutation_surfaces)

    result = evaluate_local_tool_receipt_gate(
        "systemctl --user restart hapax-dmn.service",
        task_id=TASK_ID,
        role=ROLE,
        ledger_path=ledger,
        receipt_root=receipt_root,
        now=NOW,
    )

    assert result.allowed is True
    assert result.reason_code == "local_tool_receipts_ok"
    assert result.receipt_ref is not None
    assert result.evidence_refs == ("quota:codex", "resource:appendix")


def test_stale_local_tool_invocation_receipt_blocks(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    receipt_root = tmp_path / "receipts"
    _write_route_decision(ledger)
    classification = classify_local_tool_command("systemctl --user restart hapax-dmn.service")
    _write_local_tool_receipt(receipt_root, classification.required_mutation_surfaces, stale=True)

    result = evaluate_local_tool_receipt_gate(
        "systemctl --user restart hapax-dmn.service",
        task_id=TASK_ID,
        role=ROLE,
        ledger_path=ledger,
        receipt_root=receipt_root,
        now=NOW,
    )

    assert result.allowed is False
    assert result.reason_code == "local_tool_invocation_receipt_stale"
