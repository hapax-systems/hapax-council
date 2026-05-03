"""Schema contract tests for World Capability Surface health envelopes."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.world_surface_health import (
    HEALTH_ENVELOPE_REQUIRED_FIELDS,
    HEALTH_RECORD_REQUIRED_FIELDS,
    REQUIRED_CLAIM_BLOCKER_CASES,
    REQUIRED_HEALTH_STATUSES,
    REQUIRED_SURFACE_FAMILIES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "world-surface-health-envelope.schema.json"
FIXTURES = REPO_ROOT / "config" / "world-surface-health-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", payload["envelopes"][0]["records"])


def test_world_surface_health_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "WorldSurfaceHealthEnvelopeFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/world-surface-health-envelope.schema.json"


def test_schema_pins_status_family_and_required_field_contracts() -> None:
    schema = _json(SCHEMA)
    defs = schema["$defs"]
    record = defs["health_record"]
    envelope = defs["health_envelope"]

    assert set(schema["x-required_health_statuses"]) == REQUIRED_HEALTH_STATUSES
    assert set(schema["x-required_surface_families"]) == REQUIRED_SURFACE_FAMILIES
    assert set(schema["x-claim_blocker_cases"]) == REQUIRED_CLAIM_BLOCKER_CASES
    assert set(schema["x-health_record_required_fields"]) == set(HEALTH_RECORD_REQUIRED_FIELDS)
    assert set(schema["x-health_envelope_required_fields"]) == set(HEALTH_ENVELOPE_REQUIRED_FIELDS)
    assert set(record["required"]) == set(HEALTH_RECORD_REQUIRED_FIELDS)
    assert set(envelope["required"]) == set(HEALTH_ENVELOPE_REQUIRED_FIELDS)
    assert record["properties"]["status"]["$ref"] == "#/$defs/health_status"
    assert record["properties"]["surface_family"]["$ref"] == "#/$defs/surface_family"
    assert record["properties"]["fixture_case"]["$ref"] == "#/$defs/fixture_case"


def test_fixture_catalog_covers_required_statuses_families_and_blockers() -> None:
    fixtures = _json(FIXTURES)
    records = _records(fixtures)

    assert set(fixtures["health_statuses"]) == REQUIRED_HEALTH_STATUSES
    assert set(fixtures["surface_families"]) >= REQUIRED_SURFACE_FAMILIES
    assert {record["status"] for record in records} == REQUIRED_HEALTH_STATUSES
    assert {record["surface_family"] for record in records} >= REQUIRED_SURFACE_FAMILIES
    assert set(fixtures["claim_blocker_cases"]) == REQUIRED_CLAIM_BLOCKER_CASES
    assert {record["fixture_case"] for record in records} >= REQUIRED_CLAIM_BLOCKER_CASES


@pytest.mark.parametrize(
    "fixture_case",
    [
        "candidate",
        "unknown",
        "stale",
        "missing",
        "inferred",
        "selected_only",
        "commanded_only",
        "wrong_route",
        "leak",
        "unsupported_claim",
        "false_monetization",
    ],
)
def test_schema_rejects_claimability_on_false_grounding_cases(fixture_case: str) -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(record for record in _records(bad) if record["fixture_case"] == fixture_case)
    row["claimable_health"] = True
    row["public_claim_allowed"] = True
    row["monetization_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_public_claimability_on_non_healthy_status() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(record for record in _records(bad) if record["status"] == "degraded")
    row["claimable_health"] = True
    row["public_claim_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_fail_closed_policy_constants_are_non_permissive() -> None:
    schema = _json(SCHEMA)
    policy = schema["properties"]["fail_closed_policy"]["properties"]
    fixtures = _json(FIXTURES)

    for key, value in fixtures["fail_closed_policy"].items():
        assert value is False
        assert policy[key]["const"] is False


def test_world_surface_health_fixture_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
