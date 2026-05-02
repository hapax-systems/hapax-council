"""Schema contract tests for temporal/perceptual WCS health fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

from shared.world_surface_temporal_perceptual_health import (
    FAIL_CLOSED_POLICY,
    REQUIRED_OBSERVATION_CATEGORIES,
    TEMPORAL_FALSE_GROUNDING_METRIC,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "world-surface-temporal-perceptual-health.schema.json"
FIXTURES = REPO_ROOT / "config" / "world-surface-temporal-perceptual-health-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_temporal_perceptual_health_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "WorldSurfaceTemporalPerceptualHealthFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == (
        "schemas/world-surface-temporal-perceptual-health.schema.json"
    )


def test_schema_pins_temporal_perceptual_fields_and_categories() -> None:
    schema = _json(SCHEMA)
    row = schema["$defs"]["health_row"]
    required = set(row["required"])

    for field in (
        "category",
        "temporal_band",
        "freshness",
        "authority_ceiling",
        "evidence_envelope_refs",
        "witness_refs",
        "span_refs",
        "grounding_key_paths",
        "false_grounding_risk_causes",
        "blocker_reason",
    ):
        assert field in required
    assert set(schema["$defs"]["observation_category"]["enum"]) == (REQUIRED_OBSERVATION_CATEGORIES)


def test_fixture_rows_cover_temporal_bands_and_observation_categories() -> None:
    fixtures = _json(FIXTURES)
    rows = fixtures["rows"]

    assert set(fixtures["required_observation_categories"]) == REQUIRED_OBSERVATION_CATEGORIES
    assert {row["category"] for row in rows} >= REQUIRED_OBSERVATION_CATEGORIES
    assert {row["temporal_band"] for row in rows if row["category"] == "temporal_band"} >= {
        "retention",
        "impression",
        "protention",
        "surprise",
    }


def test_fail_closed_policy_and_metric_ref_are_non_permissive() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)
    policy_schema = schema["properties"]["fail_closed_policy"]["properties"]

    assert fixtures["fail_closed_policy"] == FAIL_CLOSED_POLICY
    for key, value in fixtures["fail_closed_policy"].items():
        assert value is False
        assert policy_schema[key]["const"] is False
    assert f"metrics:{TEMPORAL_FALSE_GROUNDING_METRIC}" in fixtures["metrics_refs"]


def test_temporal_perceptual_health_contract_avoids_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
