"""Tests for observe-only capacity routing dashboard state."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from shared.capacity_routing_dashboard import (
    build_capacity_routing_dashboard,
    route_metadata_items_from_planning_queue,
)
from shared.quota_spend_ledger import QUOTA_SPEND_LEDGER_FIXTURES

NOW = datetime(2026, 5, 17, 8, 0, 0, tzinfo=UTC)


def _ledger_payload() -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8")),
    )


def test_dashboard_aggregates_required_non_green_routing_state() -> None:
    dashboard = build_capacity_routing_dashboard(
        route_metadata_summary={"explicit": 1, "hold": 1, "malformed": 1},
        route_metadata_items=[
            {
                "task_id": "held-task",
                "status": "hold",
                "evidence_refs": ["cc-task:held-task:route_metadata"],
            },
            {
                "task_id": "bad-task",
                "status": "malformed",
                "evidence_refs": ["cc-task:bad-task:route_metadata"],
            },
        ],
        route_metadata_generated_at=NOW,
        now=NOW,
    )

    states = {state.state for state in dashboard.non_green_states}

    assert dashboard.observe_only is True
    assert dashboard.dispatch_authority is False
    assert dashboard.spend_authority is False
    assert dashboard.repair_authority is False
    assert dashboard.route_metadata_summary.hold == 1
    assert dashboard.route_metadata_summary.malformed == 1
    assert dashboard.registry_freshness_ok is False
    assert dashboard.registry_non_green_route_count > 0
    assert dashboard.subscription_quota_state == "fresh"
    assert dashboard.paid_api_budget_state == "active"
    assert dashboard.bootstrap_dependency_state == "none"
    assert dashboard.local_resource_state == "green"
    assert dashboard.provider_dependency_count == 0
    assert dashboard.support_artifacts_waiting_for_review == 0
    assert dashboard.budget_ledger_stale is False
    assert dashboard.next_budget_review_at == datetime(2026, 6, 9, 0, 0, tzinfo=UTC)
    assert "route_metadata_hold" in states
    assert "route_metadata_malformed" in states
    assert "paid_api_budget_state:unknown" not in states
    assert "support_artifacts_waiting_for_review" not in states
    assert dashboard.support_artifact_refs == ()
    assert dashboard.closed_support_artifact_refs == ("artifacts/support/bootstrap-draft.md",)


def test_missing_route_metadata_summary_renders_unknown_non_green() -> None:
    dashboard = build_capacity_routing_dashboard(now=NOW)

    assert any(
        state.state == "route_metadata_summary_unavailable" and state.source == "route_metadata"
        for state in dashboard.non_green_states
    )


def test_stale_route_metadata_summary_renders_non_green() -> None:
    dashboard = build_capacity_routing_dashboard(
        route_metadata_summary={"explicit": 1},
        route_metadata_generated_at=NOW - timedelta(seconds=901),
        now=NOW,
    )

    assert any(
        state.state == "route_metadata_summary_stale" for state in dashboard.non_green_states
    )


def test_missing_registry_renders_non_green_without_exception(tmp_path: Path) -> None:
    dashboard = build_capacity_routing_dashboard(
        route_metadata_summary={"explicit": 1},
        route_metadata_generated_at=NOW,
        registry_path=tmp_path / "missing-registry.json",
        now=NOW,
    )

    assert dashboard.registry_freshness_ok is False
    assert any(
        state.state == "platform_registry_unavailable"
        and str(tmp_path / "missing-registry.json") in state.evidence_refs
        for state in dashboard.non_green_states
    )


def test_contradictory_ledger_renders_non_green_without_authorizing_artifact(
    tmp_path: Path,
) -> None:
    payload = deepcopy(_ledger_payload())
    payload["artifact_provenance"][0]["support_artifact_authority"] = "accepted_authoritative"
    ledger_path = tmp_path / "contradictory-ledger.json"
    ledger_path.write_text(json.dumps(payload), encoding="utf-8")

    dashboard = build_capacity_routing_dashboard(
        route_metadata_summary={"explicit": 1},
        route_metadata_generated_at=NOW,
        quota_spend_ledger_path=ledger_path,
        now=NOW,
    )

    assert dashboard.spend_authority is False
    assert dashboard.support_artifacts_waiting_for_review == 0
    assert any(
        state.state == "quota_spend_ledger_unavailable" and str(ledger_path) in state.evidence_refs
        for state in dashboard.non_green_states
    )


def test_planning_queue_route_metadata_items_are_cited() -> None:
    items = route_metadata_items_from_planning_queue(
        [
            {
                "item_type": "task",
                "task_id": "T-1",
                "route_metadata": {"status": "hold", "hold_reasons": ["missing_quality_floor"]},
            }
        ]
    )

    assert items == (
        {
            "task_id": "T-1",
            "status": "hold",
            "evidence_refs": ("cc-task:T-1:route_metadata",),
            "reasons": ("missing_quality_floor",),
        },
    )
