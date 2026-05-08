"""Tests for RC-003 private observe-only dashboard substrate."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.resource_capability import (
    ActionClass,
    DecisionState,
    MeasurementActionContract,
    load_resource_capability_fixtures,
)
from shared.resource_capability_backfill import (
    REQUIRED_STALE_CONFLICT_IDS,
    load_resource_capability_backfill_fixtures,
)
from shared.resource_capability_dashboard import (
    REQUIRED_DASHBOARD_VIEW_KINDS,
    DashboardRecommendationState,
    DashboardRow,
    PlanningOnlyBudgetEnvelope,
    ResourceCapabilityDashboardFixtureSet,
    load_resource_capability_dashboard_fixtures,
)


def test_dashboard_fixture_loads_and_preserves_consumer_boundary() -> None:
    fixtures = load_resource_capability_dashboard_fixtures()

    assert fixtures.consumer_permission_after == "private_observe_only_dashboard_tests_only"
    assert fixtures.dashboard_snapshots
    assert fixtures.planning_only_budget_envelopes


def test_dashboard_snapshot_has_required_views_and_refs() -> None:
    snapshot = load_resource_capability_dashboard_fixtures().dashboard_snapshots[0]

    view_kinds = {row.view_kind.value for row in snapshot.dashboard_rows}
    assert REQUIRED_DASHBOARD_VIEW_KINDS.issubset(view_kinds)
    assert snapshot.authority_source == "isap:resource-capability-observe-only-dashboard-20260508"
    assert "config/resource-capability-fixtures.json" in snapshot.source_fixture_refs
    assert "config/resource-capability-backfill-fixtures.json" in snapshot.source_fixture_refs


def test_dashboard_output_cannot_authorize_action_or_public_projection() -> None:
    fixtures = load_resource_capability_dashboard_fixtures()
    snapshot = fixtures.dashboard_snapshots[0]

    assert snapshot.dashboard_action_authorized is False
    assert snapshot.output_action_authority is False
    assert snapshot.dispatch_authorized is False
    assert snapshot.public_projection_allowed is False

    for row in snapshot.dashboard_rows:
        assert row.dashboard_action_authorized is False
        assert row.output_action_authority is False
        assert row.dispatch_authorized is False
        assert row.provider_api_execution_authorized is False
        assert row.credential_lookup_authorized is False
        assert row.outbound_email_authorized is False
        assert row.live_calendar_write_authorized is False
        assert row.payment_movement_authorized is False
        assert row.public_offer_authorized is False
        assert row.public_claim_upgrade_authorized is False
        assert row.public_projection_allowed is False
        assert row.runtime_feeder_execution_authorized is False
        assert row.external_action_authorized is False

    payload = snapshot.dashboard_rows[0].model_dump(mode="json")
    payload["dashboard_action_authorized"] = True
    with pytest.raises(ValidationError, match="Input should be False"):
        DashboardRow.model_validate(payload)


def test_underlying_gate_metrics_do_not_make_dashboard_dispatch_active() -> None:
    resource_fixtures = load_resource_capability_fixtures()
    assert any(
        isinstance(contract, MeasurementActionContract)
        and contract.action_class is not ActionClass.OBSERVE
        for contract in resource_fixtures.measurement_action_contracts
    )

    snapshot = load_resource_capability_dashboard_fixtures().dashboard_snapshots[0]
    candidate_rows = [row for row in snapshot.dashboard_rows if row.action_candidate_refs]
    assert candidate_rows
    for row in candidate_rows:
        assert ActionClass.GATE in row.underlying_action_classes
        assert row.recommendation_state is DashboardRecommendationState.NO_ACTION
        assert row.dashboard_action_authorized is False
        assert row.output_action_authority is False
        assert row.dispatch_authorized is False


def test_stale_conflicts_stay_blocked_after_model_validation() -> None:
    backfill = load_resource_capability_backfill_fixtures()
    snapshot = load_resource_capability_dashboard_fixtures().dashboard_snapshots[0]

    assert REQUIRED_STALE_CONFLICT_IDS.issubset(set(snapshot.blocked_conflict_refs))
    blocked_row = next(
        row
        for row in snapshot.dashboard_rows
        if row.decision_state is DecisionState.BLOCKED_STALE_CONFLICT
    )
    assert REQUIRED_STALE_CONFLICT_IDS.issubset(set(blocked_row.stale_conflict_refs))

    for conflict_id in REQUIRED_STALE_CONFLICT_IDS:
        conflict = backfill.conflict_by_id(conflict_id)
        assert conflict.decision_state is DecisionState.BLOCKED_STALE_CONFLICT
        assert conflict.may_activate_capability is False
        assert conflict.normalization_allowed_without_later_isap is False


def test_planning_budget_envelope_cannot_record_live_amount_or_spend() -> None:
    budget = load_resource_capability_dashboard_fixtures().planning_only_budget_envelopes[0]

    assert budget.nominal_available_usd is None
    assert budget.operator_commitment_confirmed is False
    assert budget.planning_authority is True
    assert budget.spend_authorized is False
    assert budget.cash_movement_authorized is False
    assert budget.payment_movement_authorized is False

    payload = budget.model_dump(mode="json")
    payload["nominal_available_usd"] = 2000
    with pytest.raises(ValidationError, match="Input should be None"):
        PlanningOnlyBudgetEnvelope.model_validate(payload)


def test_dashboard_fixture_set_rejects_duplicate_rows_and_missing_views() -> None:
    fixtures = load_resource_capability_dashboard_fixtures()
    payload = fixtures.model_dump(mode="json")
    rows = payload["dashboard_snapshots"][0]["dashboard_rows"]
    rows[1]["row_id"] = rows[0]["row_id"]
    with pytest.raises(ValidationError, match="row_id values must be unique"):
        ResourceCapabilityDashboardFixtureSet.model_validate(payload)

    payload = fixtures.model_dump(mode="json")
    rows = payload["dashboard_snapshots"][0]["dashboard_rows"]
    prediction_row = next(row for row in rows if row["view_kind"] == "prediction_status")
    prediction_row["view_kind"] = "account_resource_growth"
    with pytest.raises(ValidationError, match="missing required view kinds"):
        ResourceCapabilityDashboardFixtureSet.model_validate(payload)


def test_dashboard_rows_reject_absolute_paths_and_raw_email_tokens() -> None:
    row = load_resource_capability_dashboard_fixtures().dashboard_snapshots[0].dashboard_rows[0]

    payload = row.model_dump(mode="json")
    payload["evidence_refs"] = ["/private/absolute"]
    with pytest.raises(ValidationError, match="repo-relative or symbolic"):
        DashboardRow.model_validate(payload)

    payload = row.model_dump(mode="json")
    payload["evidence_refs"] = ["sender@example.com"]
    with pytest.raises(ValidationError, match="raw email addresses"):
        DashboardRow.model_validate(payload)


def test_fixture_file_contains_no_private_payload_or_public_claim_material() -> None:
    text = Path("config/resource-capability-dashboard-fixtures.json").read_text(encoding="utf-8")

    forbidden_tokens = [
        "/private/operator-home",
        "raw_body",
        "receipt_email",
        "customer_email",
        "billing_details",
        "card_number",
        "government_id",
        "passport",
        "pass show",
        "STRIPE_PAYMENT_LINK_WEBHOOK_SECRET",
        "OMG_LOL_PAY_WEBHOOK_SECRET",
        "partnered with",
        "endorsed by",
        "approved by",
    ]
    for token in forbidden_tokens:
        assert token not in text


def test_dashboard_module_has_no_runtime_provider_or_dispatch_imports() -> None:
    source = Path("shared/resource_capability_dashboard.py").read_text(encoding="utf-8")

    forbidden_tokens = [
        "import stripe",
        "from stripe",
        "requests",
        "httpx",
        "googleapiclient",
        "smtplib",
        "subprocess",
        "os.environ",
        "pass_show",
        "agents.mail_monitor",
        "agents.gmail_sync",
        "agents.gcalendar_sync",
        "agents.payment_processors",
        "events.insert",
        "events.patch",
        "payment_rails",
        "dispatch_task",
        "cc-claim",
    ]
    for token in forbidden_tokens:
        assert token not in source
