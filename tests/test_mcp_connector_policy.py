from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.dispatcher_policy import build_route_authority_receipt, write_route_authority_receipt
from shared.mcp_connector_policy import (
    canonicalize_tool_name,
    classify_connector_tool,
    evaluate_connector_receipt_gate,
    is_side_effecting_connector_tool,
)


def _write_route_decision(
    path: Path,
    *,
    task_id: str = "task-1",
    lane: str = "cx-red",
    route_id: str = "codex.headless.full",
    created_at: datetime | None = None,
    quota_refs: list[str] | None = None,
    resource_refs: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "decision_schema": 1,
        "decision_id": "decision-1",
        "created_at": (created_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
        "task_id": task_id,
        "lane": lane,
        "route_id": route_id,
        "platform": "codex",
        "mode": "headless",
        "profile": "full",
        "action": "launch",
        "policy_outcome": "launch",
        "launch_allowed": True,
        "route_policy_green": True,
        "authority_allowed": True,
        "quota_freshness_green": True,
        "resource_freshness_green": True,
        "quota_evidence_refs": quota_refs if quota_refs is not None else ["quota:test"],
        "resource_state_refs": resource_refs if resource_refs is not None else ["resource:test"],
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def _write_connector_receipt(
    root: Path,
    *,
    task_id: str = "task-1",
    route_id: str = "codex.headless.full",
    surfaces: list[str] | None = None,
    stale_after: str = "24h",
    issued_at: datetime | None = None,
) -> None:
    receipt = build_route_authority_receipt(
        receipt_type="connector_mutation",
        route_id=route_id,
        receipt_id="connector-test",
        evidence_refs=["operator-signed:connector-test"],
        stale_after=stale_after,
        task_ids=[task_id],
        mutation_surfaces=surfaces or ["connector", "external", "public", "governance"],
        issued_at=issued_at,
    )
    write_route_authority_receipt(receipt, receipt_dir=root)


def test_canonicalizes_codex_app_connector_names() -> None:
    assert canonicalize_tool_name("mcp__codex_apps__gmail___send_draft") == "gmail.send_draft"
    assert canonicalize_tool_name("mcp__github__merge_pull_request") == (
        "github.merge_pull_request"
    )


def test_manifest_classifies_mutators_and_read_only_evidence() -> None:
    gmail = classify_connector_tool("mcp__codex_apps__gmail___send_draft")
    assert gmail is not None
    assert gmail.side_effecting
    assert gmail.required_mutation_surfaces == ("connector", "external", "public")

    docs = classify_connector_tool("mcp__context7__query-docs")
    assert docs is not None
    assert docs.effect_classes == ("read_only_evidence",)
    assert not is_side_effecting_connector_tool("mcp__context7__query-docs")

    hapax = classify_connector_tool("mcp__hapax_mcp__working_mode_set")
    assert hapax is not None
    assert hapax.side_effecting
    assert set(hapax.effect_classes) == {"local_mutation", "governance_mutation"}

    for tool_name in (
        "mcp__codex_apps__google_drive___import_document",
        "mcp__codex_apps__google_drive___bulk_update_file_comments",
        "mcp__codex_apps__google_drive___batch_update_document",
        "mcp__codex_apps__github___reply_to_review_comment",
        "mcp__codex_apps__github___enable_auto_merge",
        "mcp__codex_apps__github___update_ref",
        "mcp__codex_apps__github___remove_reaction_from_issue_comment",
        "mcp__codex_apps__gmail___forward_emails",
        "mcp__codex_apps__gmail___apply_labels_to_emails",
    ):
        classification = classify_connector_tool(tool_name)
        assert classification is not None
        assert classification.side_effecting


def test_heuristic_catches_new_mutating_connector_names() -> None:
    for tool_name in (
        "mcp__codex_apps__google_drive___delete_file",
        "mcp__codex_apps__google_drive___import_unregistered_file",
        "mcp__codex_apps__github___reply_to_unregistered_review_comment",
        "mcp__codex_apps__github___enable_unregistered_auto_merge",
        "mcp__codex_apps__github___remove_unregistered_reaction",
        "mcp__codex_apps__slack___send_message",
        "mcp__codex_apps__gmail___forward_unregistered_email",
        "mcp__codex_apps__gmail___apply_unregistered_label",
    ):
        classification = classify_connector_tool(tool_name)
        assert classification is not None
        assert classification.side_effecting
        assert classification.matched_by in {
            "heuristic_mutating_verb",
            "heuristic_unknown_mutating_verb",
        }


def test_resource_prefixed_known_service_mutators_fail_closed() -> None:
    for tool_name in (
        "mcp__codex_apps__gmail___messages_modify",
        "mcp__codex_apps__google_drive___files_update",
        "mcp__codex_apps__github___pulls_merge",
        "mcp__codex_apps__google_calendar___events_delete",
    ):
        classification = classify_connector_tool(tool_name)
        assert classification is not None
        assert classification.side_effecting
        assert classification.matched_by in {
            "heuristic_mutating_verb",
            "heuristic_unclassified_connector_tool",
        }


def test_unknown_connector_service_fails_closed_when_not_explicitly_read_only() -> None:
    classification = classify_connector_tool("mcp__codex_apps__linear___transition_issue")

    assert classification is not None
    assert classification.side_effecting
    assert classification.matched_by == "heuristic_unknown_connector_service"


def test_read_only_prefix_does_not_hide_embedded_mutating_verbs() -> None:
    classification = classify_connector_tool("mcp__codex_apps__gmail___get_or_create_label")

    assert classification is not None
    assert classification.side_effecting
    assert classification.matched_by in {
        "heuristic_mutating_verb",
        "heuristic_unclassified_connector_tool",
    }


def test_unparseable_mcp_tool_fails_closed() -> None:
    classification = classify_connector_tool("mcp__broken")

    assert classification is not None
    assert classification.side_effecting
    assert classification.matched_by == "heuristic_unparseable_mcp_tool"


def test_read_only_connector_does_not_require_receipts(tmp_path: Path) -> None:
    result = evaluate_connector_receipt_gate(
        "mcp__context7__query-docs",
        task_id=None,
        role=None,
        ledger_path=tmp_path / "missing-route-decisions.jsonl",
        receipt_root=tmp_path / "receipts",
    )

    assert result.allowed
    assert result.reason_code == "read_only_or_unclassified"


def test_side_effecting_connector_blocks_without_route_decision(tmp_path: Path) -> None:
    for tool_name in (
        "mcp__codex_apps__gmail___send_draft",
        "mcp__codex_apps__google_drive___import_document",
        "mcp__codex_apps__google_drive___bulk_update_file_comments",
        "mcp__codex_apps__github___reply_to_review_comment",
        "mcp__codex_apps__gmail___messages_modify",
        "mcp__codex_apps__google_drive___files_update",
        "mcp__codex_apps__github___pulls_merge",
        "mcp__codex_apps__google_calendar___events_delete",
        "mcp__codex_apps__gmail___get_or_create_label",
        "mcp__broken",
        "mcp__codex_apps__gmail___forward_emails",
        "mcp__codex_apps__gmail___apply_labels_to_emails",
    ):
        result = evaluate_connector_receipt_gate(
            tool_name,
            task_id="task-1",
            role="cx-red",
            ledger_path=tmp_path / "missing-route-decisions.jsonl",
            receipt_root=tmp_path / "receipts",
        )

        assert not result.allowed
        assert result.reason_code == "route_decision_absent"


def test_side_effecting_connector_requires_quota_and_resource_refs(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    _write_route_decision(ledger, quota_refs=[], resource_refs=["resource:test"])

    result = evaluate_connector_receipt_gate(
        "mcp__codex_apps__gmail___send_draft",
        task_id="task-1",
        role="cx-red",
        ledger_path=ledger,
        receipt_root=tmp_path / "receipts",
    )

    assert not result.allowed
    assert result.reason_code == "quota_evidence_refs_absent"


def test_side_effecting_connector_requires_connector_mutation_receipt(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    _write_route_decision(ledger)

    result = evaluate_connector_receipt_gate(
        "mcp__codex_apps__gmail___send_draft",
        task_id="task-1",
        role="cx-red",
        ledger_path=ledger,
        receipt_root=tmp_path / "receipts",
    )

    assert not result.allowed
    assert result.reason_code == "connector_mutation_receipt_absent"


def test_side_effecting_connector_allows_with_route_and_receipt(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    receipts = tmp_path / "receipts"
    _write_route_decision(ledger)
    _write_connector_receipt(receipts)

    result = evaluate_connector_receipt_gate(
        "mcp__codex_apps__gmail___send_draft",
        task_id="task-1",
        role="cx-red",
        ledger_path=ledger,
        receipt_root=receipts,
    )

    assert result.allowed
    assert result.reason_code == "connector_receipts_ok"
    assert result.receipt_ref is not None


def test_connector_receipt_must_cover_required_surfaces(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    receipts = tmp_path / "receipts"
    _write_route_decision(ledger)
    _write_connector_receipt(receipts, surfaces=["connector", "external"])

    result = evaluate_connector_receipt_gate(
        "mcp__codex_apps__gmail___send_draft",
        task_id="task-1",
        role="cx-red",
        ledger_path=ledger,
        receipt_root=receipts,
    )

    assert not result.allowed
    assert result.reason_code == "connector_mutation_surface_mismatch"


def test_connector_receipt_route_and_task_must_match(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    receipts = tmp_path / "receipts"
    _write_route_decision(ledger)
    _write_connector_receipt(receipts, route_id="codex.other.full")

    result = evaluate_connector_receipt_gate(
        "mcp__codex_apps__gmail___send_draft",
        task_id="task-1",
        role="cx-red",
        ledger_path=ledger,
        receipt_root=receipts,
    )

    assert not result.allowed
    assert result.reason_code == "connector_mutation_route_mismatch"

    _write_connector_receipt(receipts, task_id="other-task")
    result = evaluate_connector_receipt_gate(
        "mcp__codex_apps__gmail___send_draft",
        task_id="task-1",
        role="cx-red",
        ledger_path=ledger,
        receipt_root=receipts,
    )

    assert not result.allowed
    assert result.reason_code == "connector_mutation_task_mismatch"


def test_connector_receipt_and_route_decision_must_be_fresh(tmp_path: Path) -> None:
    ledger = tmp_path / "route-decisions.jsonl"
    receipts = tmp_path / "receipts"
    old = datetime.now(UTC) - timedelta(days=2)
    _write_route_decision(ledger, created_at=old)
    _write_connector_receipt(receipts)

    result = evaluate_connector_receipt_gate(
        "mcp__codex_apps__gmail___send_draft",
        task_id="task-1",
        role="cx-red",
        ledger_path=ledger,
        receipt_root=receipts,
    )

    assert not result.allowed
    assert result.reason_code == "route_decision_stale"

    _write_route_decision(ledger)
    _write_connector_receipt(receipts, stale_after="1s", issued_at=old)
    result = evaluate_connector_receipt_gate(
        "mcp__codex_apps__gmail___send_draft",
        task_id="task-1",
        role="cx-red",
        ledger_path=ledger,
        receipt_root=receipts,
    )

    assert not result.allowed
    assert result.reason_code == "connector_mutation_receipt_stale"
