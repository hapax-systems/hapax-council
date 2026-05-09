"""Tests for RC-004 private dispatch-active metric contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.resource_capability import ActionClass, DecisionState
from shared.resource_capability_dispatch import (
    DispatchRecommendationKind,
    MetricActionEvaluation,
    MetricContractEvaluationState,
    ResourceCapabilityDispatchError,
    ResourceCapabilityDispatchFixtureSet,
    load_resource_capability_dispatch_fixtures,
)

FIXTURE_PATH = Path("config/resource-capability-dispatch-fixtures.json")


def _fixture_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _write_fixture(tmp_path: Path, payload: dict) -> Path:
    fixture_path = tmp_path / "resource-capability-dispatch-fixtures.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    return fixture_path


def test_dispatch_fixture_loads_and_preserves_consumer_boundary() -> None:
    fixtures = load_resource_capability_dispatch_fixtures()

    assert fixtures.consumer_permission_after == "private_internal_recommendation_tests_only"
    assert fixtures.dispatch_packets
    packet = fixtures.dispatch_packets[0]
    assert packet.authority_source == "isap:resource-capability-dispatch-active-metrics-20260509"
    assert packet.internal_followup_task_drafts
    assert packet.hold_block_recommendations


def test_dispatch_models_are_strict_and_reject_extra_fields() -> None:
    evaluation = (
        load_resource_capability_dispatch_fixtures().dispatch_packets[0].metric_evaluations[0]
    )
    payload = evaluation.model_dump(mode="json")
    payload["surprise_authority"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MetricActionEvaluation.model_validate(payload)


def test_private_recommendations_cannot_authorize_external_or_live_internal_effects() -> None:
    packet = load_resource_capability_dispatch_fixtures().dispatch_packets[0]

    authority_fields = [
        "task_file_write_authorized",
        "coordinator_send_authorized",
        "provider_api_execution_authorized",
        "credential_lookup_authorized",
        "outbound_email_authorized",
        "live_calendar_write_authorized",
        "payment_movement_authorized",
        "public_offer_authorized",
        "public_claim_upgrade_authorized",
        "public_projection_allowed",
        "runtime_feeder_execution_authorized",
        "service_execution_authorized",
        "external_action_authorized",
        "stale_surface_activation_authorized",
    ]
    rows = [
        packet,
        *packet.metric_evaluations,
        *packet.internal_followup_task_drafts,
        *packet.hold_block_recommendations,
    ]
    for row in rows:
        for field in authority_fields:
            assert getattr(row, field) is False

    payload = packet.model_dump(mode="json")
    payload["task_file_write_authorized"] = True
    with pytest.raises(ValidationError, match="Input should be False"):
        ResourceCapabilityDispatchFixtureSet.model_validate(
            {
                "schema_version": 1,
                "fixture_set_id": "bad",
                "consumer_permission_after": "private_internal_recommendation_tests_only",
                "dispatch_packets": [payload],
            }
        )


def test_internal_followup_drafts_require_passed_measurement_contracts() -> None:
    packet = load_resource_capability_dispatch_fixtures().dispatch_packets[0]
    passed = {
        evaluation.evaluation_id
        for evaluation in packet.metric_evaluations
        if evaluation.state is MetricContractEvaluationState.PASSED
    }

    assert packet.internal_followup_task_drafts
    for draft in packet.internal_followup_task_drafts:
        assert draft.from_evaluation_id in passed
        assert draft.internal_followup_task_draft_authorized is True
        assert draft.creates_vault_task is False
        assert draft.sends_to_coordinator is False

    payload = _fixture_payload()
    payload["dispatch_packets"][0]["internal_followup_task_drafts"][0]["from_evaluation_id"] = (
        "metric-eval:blocked-stale-conflicts"
    )
    with pytest.raises(ValidationError, match="internal followup drafts require passed"):
        ResourceCapabilityDispatchFixtureSet.model_validate(payload)


def test_failed_missing_and_stale_evaluations_produce_hold_or_block_rows() -> None:
    packet = load_resource_capability_dispatch_fixtures().dispatch_packets[0]

    failed_or_blocked = {
        evaluation.evaluation_id
        for evaluation in packet.metric_evaluations
        if evaluation.state is not MetricContractEvaluationState.PASSED
    }
    hold_block_eval_ids = {
        recommendation.from_evaluation_id for recommendation in packet.hold_block_recommendations
    }

    assert failed_or_blocked
    assert failed_or_blocked.issubset(hold_block_eval_ids)
    assert all(
        recommendation.recommendation_kind
        in {
            DispatchRecommendationKind.HOLD_RECOMMENDATION,
            DispatchRecommendationKind.BLOCK_RECOMMENDATION,
        }
        for recommendation in packet.hold_block_recommendations
    )

    payload = _fixture_payload()
    payload["dispatch_packets"][0]["hold_block_recommendations"] = [
        payload["dispatch_packets"][0]["hold_block_recommendations"][0]
    ]
    with pytest.raises(ValidationError, match="failed evaluations require hold/block"):
        ResourceCapabilityDispatchFixtureSet.model_validate(payload)


def test_stale_conflict_evaluations_stay_blocked_and_cannot_draft_work(tmp_path: Path) -> None:
    packet = load_resource_capability_dispatch_fixtures().dispatch_packets[0]
    blocked = next(
        evaluation
        for evaluation in packet.metric_evaluations
        if evaluation.state is MetricContractEvaluationState.BLOCKED_STALE_CONFLICT
    )
    recommendation = next(
        row
        for row in packet.hold_block_recommendations
        if row.from_evaluation_id == blocked.evaluation_id
    )

    assert blocked.eligible_for_internal_followup is False
    assert blocked.hold_or_block_required is True
    assert recommendation.decision_state is DecisionState.BLOCKED_STALE_CONFLICT
    assert recommendation.stale_conflict_refs

    payload = _fixture_payload()
    payload["dispatch_packets"][0]["metric_evaluations"][1]["state"] = "passed"
    payload["dispatch_packets"][0]["metric_evaluations"][1]["eligible_for_internal_followup"] = True
    payload["dispatch_packets"][0]["metric_evaluations"][1]["hold_or_block_required"] = False
    payload["dispatch_packets"][0]["metric_evaluations"][1]["fail_closed_reason"] = None
    with pytest.raises(ResourceCapabilityDispatchError, match="stale conflict row cannot pass"):
        load_resource_capability_dispatch_fixtures(_write_fixture(tmp_path, payload))


def test_cross_source_validation_requires_measurement_contract_match(tmp_path: Path) -> None:
    payload = _fixture_payload()
    payload["dispatch_packets"][0]["metric_evaluations"][0]["action_class"] = ActionClass.DISPATCH

    with pytest.raises(ResourceCapabilityDispatchError, match="action_class does not match"):
        load_resource_capability_dispatch_fixtures(_write_fixture(tmp_path, payload))


def test_missing_contracts_fail_closed_instead_of_drafting(tmp_path: Path) -> None:
    payload = _fixture_payload()
    missing = payload["dispatch_packets"][0]["metric_evaluations"][2]
    missing["action_class"] = "gate"
    missing["state"] = "passed"
    missing["eligible_for_internal_followup"] = True
    missing["hold_or_block_required"] = False
    missing["fail_closed_reason"] = None

    with pytest.raises(ResourceCapabilityDispatchError, match="missing contract must fail closed"):
        load_resource_capability_dispatch_fixtures(_write_fixture(tmp_path, payload))


def test_dispatch_fixture_file_contains_no_private_payload_or_public_claim_material() -> None:
    text = FIXTURE_PATH.read_text(encoding="utf-8")

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


def test_dispatch_module_has_no_runtime_provider_or_task_writer_imports() -> None:
    source = Path("shared/resource_capability_dispatch.py").read_text(encoding="utf-8")

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
        ".write_text(",
    ]
    for token in forbidden_tokens:
        assert token not in source
