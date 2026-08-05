"""Schema contract tests for dispatcher policy route decision receipts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from shared.dispatcher_policy import DispatchAction, RouteDecision

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "dispatcher-policy-route-decision.schema.json"


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_dispatcher_policy_route_decision_schema_validates_model_dump() -> None:
    schema = _schema()
    decision = RouteDecision(
        decision_id="rd-20260509T223000Z-policy-test-aaaaaaaaaaaa",
        created_at=datetime(2026, 5, 9, 22, 30, tzinfo=UTC),
        task_id="policy-test",
        lane="cx-green",
        route_id="codex.headless.full",
        platform="codex",
        mode="headless",
        profile="full",
        action=DispatchAction.LAUNCH,
        policy_outcome="launch",
        launch_allowed=True,
        prompt_allowed=True,
        quality_floor_satisfied=True,
        authority_allowed=True,
        reason_codes=("policy_launch",),
        message="policy_launch",
        resource_state_refs=("capability.resource_source:local_probe",),
    )

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(decision.model_dump(mode="json"))

    assert schema["title"] == "DispatcherPolicyRouteDecision"

    reserved_leaf = decision.model_dump(mode="json")
    reserved_leaf["selected_descriptor_leaf"] = (
        "codex.headless.full#local_compute.agentic_trust_evaluator_surface"
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(reserved_leaf)
    with pytest.raises(ValueError, match="cannot be a selected descriptor leaf"):
        RouteDecision.model_validate(reserved_leaf)

    mismatched_leaf = decision.model_dump(mode="python")
    mismatched_leaf["selected_descriptor_leaf"] = "claude.headless.full#effort_low"
    with pytest.raises(ValueError, match="must be bound to route_id"):
        RouteDecision.model_validate(mismatched_leaf)


def test_dispatcher_policy_schema_pins_fail_closed_actions() -> None:
    schema = _schema()

    assert schema["properties"]["action"]["enum"] == [
        "launch",
        "hold",
        "support_only",
        "refuse",
    ]
    assert schema["properties"]["policy_outcome"]["enum"] == [
        "launch",
        "hold",
        "support_only",
        "refuse",
    ]
