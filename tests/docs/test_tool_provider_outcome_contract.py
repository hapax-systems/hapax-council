"""Schema contract tests for tool/provider outcome fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.tool_provider_outcome import (
    REQUIRED_TOOL_PROVIDER_FIXTURE_CASES,
    TOOL_PROVIDER_OUTCOME_REQUIRED_FIELDS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "tool-provider-outcome-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "tool-provider-outcome-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _outcomes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", payload["outcomes"])


def test_tool_provider_outcome_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "ToolProviderOutcomeEnvelopeFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/tool-provider-outcome-envelope.schema.json"


def test_schema_pins_required_fields_and_fixture_cases() -> None:
    schema = _json(SCHEMA)
    envelope = schema["$defs"]["tool_provider_outcome_envelope"]

    assert set(schema["x-required_fixture_cases"]) == REQUIRED_TOOL_PROVIDER_FIXTURE_CASES
    assert set(schema["x-outcome_envelope_required_fields"]) == set(
        TOOL_PROVIDER_OUTCOME_REQUIRED_FIELDS
    )
    assert set(envelope["required"]) == set(TOOL_PROVIDER_OUTCOME_REQUIRED_FIELDS)
    assert envelope["properties"]["result_status"]["$ref"] == "#/$defs/result_status"
    assert envelope["properties"]["acquisition_mode"]["$ref"] == "#/$defs/acquisition_mode"
    assert envelope["properties"]["authority_ceiling"]["$ref"] == "#/$defs/authority_ceiling"
    assert envelope["properties"]["witnessed_world_truth"]["const"] is False


def test_fixture_payload_covers_required_cases() -> None:
    fixtures = _json(FIXTURES)
    outcomes = _outcomes(fixtures)

    assert set(fixtures["fixture_cases"]) == REQUIRED_TOOL_PROVIDER_FIXTURE_CASES
    assert {outcome["fixture_case"] for outcome in outcomes} == (
        REQUIRED_TOOL_PROVIDER_FIXTURE_CASES
    )


def test_schema_rejects_source_claim_without_acquisition_evidence() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(
        outcome for outcome in _outcomes(bad) if outcome["fixture_case"] == "source_acquired"
    )
    row["source_acquisition_evidence_refs"] = []

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_supplied_evidence_claiming_source_acquisition() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(
        outcome for outcome in _outcomes(bad) if outcome["fixture_case"] == "supplied_evidence"
    )
    row["source_acquired"] = True
    row["acquired_source_refs"] = ["source:forged"]

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_redacted_public_claim_support() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(outcome for outcome in _outcomes(bad) if outcome["fixture_case"] == "redacted")
    row["public_claim_supported"] = True

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_error_without_error_object() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(outcome for outcome in _outcomes(bad) if outcome["fixture_case"] == "error")
    row["error"] = None

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_success_without_authority() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(
        outcome for outcome in _outcomes(bad) if outcome["fixture_case"] == "source_acquired"
    )
    row["authority_ceiling"] = "no_claim"

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_fail_closed_policy_constants_are_non_permissive() -> None:
    schema = _json(SCHEMA)
    policy_schema = schema["properties"]["fail_closed_policy"]["properties"]
    fixtures = _json(FIXTURES)

    for key, value in fixtures["fail_closed_policy"].items():
        assert value is False
        assert policy_schema[key]["const"] is False


def test_tool_provider_outcome_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
