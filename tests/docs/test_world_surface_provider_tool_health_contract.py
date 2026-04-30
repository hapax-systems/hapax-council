"""Schema contract tests for provider/tool WCS health fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

from shared.world_surface_provider_tool_health import REQUIRED_PROVIDER_TOOL_FAMILIES

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "world-surface-provider-tool-health.schema.json"
FIXTURES = REPO_ROOT / "config" / "world-surface-provider-tool-health-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_provider_tool_health_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "WorldSurfaceProviderToolHealthFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/world-surface-provider-tool-health.schema.json"


def test_schema_pins_provider_tool_route_fields() -> None:
    schema = _json(SCHEMA)
    route = schema["$defs"]["route_health"]
    required = set(route["required"])

    for field in (
        "route_id",
        "classification_row_id",
        "route_family",
        "provider_registry_id",
        "model_id",
        "tool_id",
        "route_ref",
        "availability_state",
        "source_acquisition_capability",
        "source_acquisition_evidence_refs",
        "supplied_evidence_mode",
        "redaction_privacy_posture",
        "freshness",
        "authority_ceiling",
        "public_claim_policy",
        "blocking_reasons",
        "fallback",
        "kill_switch_state",
    ):
        assert field in required


def test_fixture_routes_cover_required_provider_tool_families() -> None:
    fixtures = _json(FIXTURES)
    route_families = {route["route_family"] for route in fixtures["routes"]}

    assert set(fixtures["required_route_families"]) == REQUIRED_PROVIDER_TOOL_FAMILIES
    assert route_families >= REQUIRED_PROVIDER_TOOL_FAMILIES


def test_fail_closed_policy_constants_are_non_permissive() -> None:
    schema = _json(SCHEMA)
    policy_schema = schema["properties"]["fail_closed_policy"]["properties"]
    fixtures = _json(FIXTURES)

    for key, value in fixtures["fail_closed_policy"].items():
        assert value is False
        assert policy_schema[key]["const"] is False


def test_provider_tool_health_contract_avoids_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
