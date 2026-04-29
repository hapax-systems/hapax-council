"""Schema contract tests for CapabilityOutcomeEnvelope fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.capability_outcome import (
    OUTCOME_ENVELOPE_REQUIRED_FIELDS,
    REQUIRED_NO_UPDATE_CASES,
    REQUIRED_OUTCOME_STATUSES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "capability-outcome-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "capability-outcome-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _outcomes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", payload["outcomes"])


def test_capability_outcome_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "CapabilityOutcomeEnvelopeFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/capability-outcome-envelope.schema.json"


def test_schema_pins_status_no_update_and_required_field_contracts() -> None:
    schema = _json(SCHEMA)
    defs = schema["$defs"]
    envelope = defs["capability_outcome_envelope"]

    assert set(schema["x-required_outcome_statuses"]) == REQUIRED_OUTCOME_STATUSES
    assert set(schema["x-no_update_fixture_cases"]) == REQUIRED_NO_UPDATE_CASES
    assert set(schema["x-outcome_envelope_required_fields"]) == set(
        OUTCOME_ENVELOPE_REQUIRED_FIELDS
    )
    assert set(envelope["required"]) == set(OUTCOME_ENVELOPE_REQUIRED_FIELDS)
    assert envelope["properties"]["outcome_status"]["$ref"] == "#/$defs/outcome_status"
    assert envelope["properties"]["selection_state"]["$ref"] == "#/$defs/selection_state"
    assert envelope["properties"]["witness_policy"]["$ref"] == "#/$defs/witness_policy"
    assert envelope["properties"]["fixture_case"]["$ref"] == "#/$defs/fixture_case"


def test_fixture_catalog_covers_required_statuses_and_no_update_cases() -> None:
    fixtures = _json(FIXTURES)
    outcomes = _outcomes(fixtures)

    assert set(fixtures["outcome_statuses"]) == REQUIRED_OUTCOME_STATUSES
    assert set(fixtures["no_update_fixture_cases"]) == REQUIRED_NO_UPDATE_CASES
    assert {outcome["outcome_status"] for outcome in outcomes} == REQUIRED_OUTCOME_STATUSES
    assert {outcome["fixture_case"] for outcome in outcomes} >= REQUIRED_NO_UPDATE_CASES


@pytest.mark.parametrize(
    "fixture_case",
    ["selected_only", "commanded_only", "inferred", "stale", "missing"],
)
def test_schema_rejects_success_update_on_no_update_cases(fixture_case: str) -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(outcome for outcome in _outcomes(bad) if outcome["fixture_case"] == fixture_case)
    row["learning_update"]["allowed"] = True
    row["learning_update"]["policy"] = "success"
    row["learning_update"]["target"] = "affordance_activation"
    row["learning_update"]["required_witness_refs"] = ["witness:fake"]
    row["verified_success"]["capability"] = True
    row["verified_success"]["action"] = True

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_claim_posterior_update_without_public_claim_evidence() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(
        outcome
        for outcome in _outcomes(bad)
        if outcome["outcome_id"] == "coe:audio.public-tts:witnessed-success"
    )
    row["claim_posterior_update"]["allowed"] = True
    row["claim_posterior_update"]["claim_ids"] = ["claim:unsupported"]
    row["claim_posterior_update"]["evidence_envelope_refs"] = ["evidence-envelope:fake"]
    row["claim_posterior_update"]["gate_refs"] = ["gate:fake"]

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_public_success_without_public_event_gate_evidence() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(
        outcome
        for outcome in _outcomes(bad)
        if outcome["outcome_id"] == "coe:public-event.rvpe:accepted"
    )
    row["public_claim_evidence"]["present"] = False
    row["public_claim_evidence"]["required"] = False
    row["public_claim_evidence"]["evidence_envelope_refs"] = []
    row["public_claim_evidence"]["public_event_refs"] = []
    row["public_claim_evidence"]["gate_refs"] = []

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_fail_closed_policy_constants_are_non_permissive() -> None:
    schema = _json(SCHEMA)
    policy = schema["properties"]["fail_closed_policy"]["properties"]
    fixtures = _json(FIXTURES)

    for key, value in fixtures["fail_closed_policy"].items():
        assert value is False
        assert policy[key]["const"] is False


def test_capability_outcome_fixture_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
