"""Tests for RC-002 private resource-capability backfill projections."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.resource_capability import (
    DecisionState,
    PublicClaimCeiling,
    ResourceOpportunity,
    ResourceValuation,
)
from shared.resource_capability_backfill import (
    REQUIRED_RESOURCE_CLASS_PROJECTIONS,
    REQUIRED_STALE_CONFLICT_IDS,
    BackfillProjectionRow,
    ProjectionStatus,
    ReceiveOnlyRailProjection,
    ResourceCapabilityBackfillFixtureSet,
    StaleConflictProjection,
    SupportSurfaceDecision,
    SupportSurfaceProjection,
    load_resource_capability_backfill_fixtures,
)


def _support_surface_registry_by_id() -> dict[str, dict[str, object]]:
    registry = json.loads(Path("config/support-surface-registry.json").read_text(encoding="utf-8"))
    return {surface["surface_id"]: surface for surface in registry["surfaces"]}


def _accepted_event_strings_from_source(path: Path, alias_name: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    canonical: list[str] = []
    aliases: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "PaymentEventKind":
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
                    if isinstance(stmt.value.value, str):
                        canonical.append(stmt.value.value)
        alias_dict: ast.Dict | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == alias_name for target in node.targets
        ):
            alias_dict = node.value if isinstance(node.value, ast.Dict) else None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == alias_name and isinstance(node.value, ast.Dict):
                alias_dict = node.value
        if alias_dict is not None:
            aliases.extend(
                key.value
                for key in alias_dict.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )

    return canonical + aliases


def test_backfill_fixture_loads_and_preserves_consumer_boundary() -> None:
    fixtures = load_resource_capability_backfill_fixtures()

    assert fixtures.consumer_permission_after == "private_projection_tests_only"
    assert fixtures.authority_source == "isap:resource-capability-read-only-backfill-20260508"
    assert fixtures.all_projection_rows()


def test_required_resource_classes_are_separate_projection_rows() -> None:
    fixtures = load_resource_capability_backfill_fixtures()
    classes = {row.resource_class for row in fixtures.resource_class_projection_rows}

    assert REQUIRED_RESOURCE_CLASS_PROJECTIONS.issubset(classes)

    rows_by_class = {row.resource_class: row for row in fixtures.resource_class_projection_rows}
    assert rows_by_class["cash"].valuation.cash_equivalent_value == 0
    assert rows_by_class["credit"].valuation.cash_equivalent_value is None
    assert rows_by_class["compute"].valuation.nominal_unit == "COMPUTE_UNIT"
    assert rows_by_class["access"].valuation.cash_equivalent_value is None
    assert rows_by_class["institutional_support"].valuation.nominal_unit == (
        "INSTITUTIONAL_SUPPORT"
    )
    assert rows_by_class["trust_cost"].valuation.trust_cost == 1


def test_values_remain_separate_and_cannot_drive_public_claims() -> None:
    fixtures = load_resource_capability_backfill_fixtures()

    for row in fixtures.all_projection_rows():
        assert isinstance(row.valuation, ResourceValuation)
        assert row.public_claim_ceiling is PublicClaimCeiling.NONE
        assert row.value_may_drive_public_claim_or_action is False
        assert row.public_offer_authorized is False
        assert row.public_claim_upgrade_authorized is False

    payload = fixtures.resource_class_projection_rows[0].model_dump(mode="json")
    payload["public_claim_ceiling"] = "private_summary"
    with pytest.raises(ValidationError, match="public claim ceiling"):
        BackfillProjectionRow.model_validate(payload)


def test_support_surface_registry_rows_project_without_offer_authority() -> None:
    fixtures = load_resource_capability_backfill_fixtures()
    by_surface = {surface.surface_id: surface for surface in fixtures.support_surface_projections}

    assert by_surface["liberapay_recurring"].aggregate_only_receipts is True
    assert by_surface["kofi_tips_guarded"].registry_decision == SupportSurfaceDecision.GUARDED
    stripe = by_surface["stripe_payment_links"]
    assert stripe.registry_decision == SupportSurfaceDecision.REFUSAL_CONVERSION
    assert stripe.automation_class == "REFUSAL_ARTIFACT"
    assert stripe.refusal_brief_refs == ["docs/refusal-briefs/leverage-stripe-kyc.md"]
    assert stripe.registry_public_copy_text_projected is False
    assert stripe.public_offer_authorized is False

    payload = stripe.model_dump(mode="json")
    payload["registry_allowed_public_copy_entry_count"] = 1
    with pytest.raises(ValidationError, match="cannot project public copy"):
        SupportSurfaceProjection.model_validate(payload)


def test_projected_support_surface_fields_match_registry_source() -> None:
    fixtures = load_resource_capability_backfill_fixtures()
    registry = _support_surface_registry_by_id()

    for projection in fixtures.support_surface_projections:
        source = registry[projection.surface_id]
        assert projection.stable_source_id == source["surface_id"]
        assert projection.display_name == source["display_name"]
        assert projection.surface_family == source["surface_family"]
        assert projection.money_form == source["money_form"]
        assert projection.registry_decision == source["decision"]
        assert projection.automation_class == source["automation_class"]
        assert projection.no_perk_required == source["no_perk_required"]
        assert projection.aggregate_only_receipts == source["aggregate_only_receipts"]
        assert projection.readiness_gates == source["readiness_gates"]
        assert projection.refusal_brief_refs == source["refusal_brief_refs"]
        assert projection.buildable_conversion == source["buildable_conversion"]
        assert projection.registry_allowed_public_copy_entry_count == len(
            source["allowed_public_copy"]
        )


def test_receive_only_rail_facts_stay_read_receive_evidence_only() -> None:
    fixtures = load_resource_capability_backfill_fixtures()
    by_rail = {rail.rail_id: rail for rail in fixtures.receive_only_rail_projections}

    stripe = by_rail["stripe_payment_link"]
    assert stripe.projection_status is ProjectionStatus.READ_RECEIVE_EVIDENCE
    assert stripe.receive_only is True
    assert stripe.provider_api_execution_authorized is False
    assert stripe.credential_lookup_authorized is False
    assert stripe.outbound_fetch_authorized is False
    assert stripe.payment_movement_authorized is False
    assert stripe.raw_payload_persisted is False
    assert stripe.pii_retained is False
    assert "checkout.session.completed" in stripe.accepted_event_kinds

    payload = stripe.model_dump(mode="json")
    payload["projection_status"] = "projected_private"
    with pytest.raises(ValidationError, match="read_receive_evidence"):
        ReceiveOnlyRailProjection.model_validate(payload)


def test_projected_receive_only_event_kinds_match_local_sources() -> None:
    fixtures = load_resource_capability_backfill_fixtures()
    by_rail = {rail.rail_id: rail for rail in fixtures.receive_only_rail_projections}

    stripe_events = _accepted_event_strings_from_source(
        Path("shared/stripe_payment_link_receive_only_rail.py"),
        "_STRIPE_EVENT_ALIASES",
    )
    omg_lol_pay_events = _accepted_event_strings_from_source(
        Path("shared/omg_lol_pay_receive_only_rail.py"),
        "_OMG_LOL_PAY_ACTION_ALIASES",
    )

    assert by_rail["stripe_payment_link"].accepted_event_kinds == stripe_events
    assert by_rail["omg_lol_pay"].accepted_event_kinds == omg_lol_pay_events


def test_required_stale_conflicts_are_present_and_fail_closed() -> None:
    fixtures = load_resource_capability_backfill_fixtures()
    conflict_ids = {conflict.conflict_id for conflict in fixtures.stale_conflict_projections}

    assert REQUIRED_STALE_CONFLICT_IDS.issubset(conflict_ids)
    for conflict_id in REQUIRED_STALE_CONFLICT_IDS:
        conflict = fixtures.conflict_by_id(conflict_id)
        assert conflict.decision_state is DecisionState.BLOCKED_STALE_CONFLICT
        assert conflict.projection_status is ProjectionStatus.BLOCKED_STALE_CONFLICT
        assert conflict.normalization_allowed_without_later_isap is False
        assert conflict.may_activate_capability is False
        assert conflict.public_offer_authorized is False
        assert len(conflict.contradictory_refs) >= 2

    payload = fixtures.conflict_by_id(
        "stale-conflict:stripe-refusal-vs-payment-link-wiring"
    ).model_dump(mode="json")
    payload["decision_state"] = "observe_only"
    with pytest.raises(ValidationError, match="Input should be"):
        StaleConflictProjection.model_validate(payload)


def test_resource_capability_schema_rows_validate_with_existing_models() -> None:
    fixtures = load_resource_capability_backfill_fixtures()

    for opportunity in fixtures.projected_resource_opportunities:
        assert isinstance(opportunity, ResourceOpportunity)

    stale = next(
        opportunity
        for opportunity in fixtures.projected_resource_opportunities
        if opportunity.decision_state is DecisionState.BLOCKED_STALE_CONFLICT
    )
    payload = stale.model_dump(mode="json")
    payload["stale_conflict_refs"] = []
    with pytest.raises(ValidationError, match="requires stale_conflict_refs"):
        ResourceOpportunity.model_validate(payload)


def test_private_semantic_trace_and_pressure_ledger_have_no_external_effects() -> None:
    fixtures = load_resource_capability_backfill_fixtures()
    trace = fixtures.semantic_transaction_traces[0]
    ledger = fixtures.transaction_pressure_ledgers[0]

    assert trace.privacy_scope == "private"
    assert trace.public_projection_allowed is False
    assert trace.runtime_tracing_authorized is False
    assert trace.provider_api_execution_authorized is False
    assert ledger.public_projection_allowed is False
    assert ledger.provider_poll_authorized is False
    assert ledger.external_effect_authorized is False


def test_fixture_set_rejects_missing_conflicts_and_duplicate_rows() -> None:
    fixtures = load_resource_capability_backfill_fixtures()

    payload = fixtures.model_dump(mode="json")
    payload["stale_conflict_projections"][-1]["row_id"] = "stale-conflict:unknown"
    payload["stale_conflict_projections"][-1]["stable_source_id"] = "stale-conflict:unknown"
    payload["stale_conflict_projections"][-1]["conflict_id"] = "stale-conflict:unknown"
    payload["stale_conflict_projections"][-1]["stale_conflict_refs"] = ["stale-conflict:unknown"]
    with pytest.raises(ValidationError, match="missing required stale conflict"):
        ResourceCapabilityBackfillFixtureSet.model_validate(payload)

    payload = fixtures.model_dump(mode="json")
    payload["resource_class_projection_rows"][1]["row_id"] = payload[
        "resource_class_projection_rows"
    ][0]["row_id"]
    with pytest.raises(ValidationError, match="row_id values must be unique"):
        ResourceCapabilityBackfillFixtureSet.model_validate(payload)


def test_backfill_rows_reject_absolute_paths_and_raw_email_tokens() -> None:
    fixtures = load_resource_capability_backfill_fixtures()
    payload = fixtures.resource_class_projection_rows[0].model_dump(mode="json")
    payload["evidence_refs"] = ["/private/absolute"]
    with pytest.raises(ValidationError, match="repo-relative or symbolic"):
        BackfillProjectionRow.model_validate(payload)

    payload = fixtures.resource_class_projection_rows[0].model_dump(mode="json")
    payload["evidence_refs"] = ["sender@example.com"]
    with pytest.raises(ValidationError, match="raw email addresses"):
        BackfillProjectionRow.model_validate(payload)


def test_fixture_file_contains_no_private_payload_material() -> None:
    text = Path("config/resource-capability-backfill-fixtures.json").read_text(encoding="utf-8")

    forbidden_tokens = [
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
    ]
    for token in forbidden_tokens:
        assert token not in text


def test_backfill_module_has_no_provider_runtime_or_service_imports() -> None:
    source = Path("shared/resource_capability_backfill.py").read_text(encoding="utf-8")

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
        "shared.stripe_payment_link_receive_only_rail",
        "shared.omg_lol_pay_receive_only_rail",
        "events.insert",
        "events.patch",
        "payment_rails",
    ]
    for token in forbidden_tokens:
        assert token not in source
