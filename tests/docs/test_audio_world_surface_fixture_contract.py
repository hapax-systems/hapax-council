"""Schema contract tests for audio WCS fixture rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.audio_world_surface_fixtures import (
    REQUIRED_AUDIO_HEALTH_STATES,
    REQUIRED_AUDIO_SURFACE_IDS,
    ROUTE_RESULT_REQUIRED_FIELDS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "audio-world-surface-fixtures.schema.json"
FIXTURES = REPO_ROOT / "config" / "audio-world-surface-fixtures.json"

EXPECTED_WITNESSES = {
    "public_audio_witness": "public",
    "private_audio_witness": "private",
    "no_leak_audio_witness": "no_leak",
}


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_audio_fixture_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "AudioWorldSurfaceFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/audio-world-surface-fixtures.schema.json"


def test_schema_pins_audio_surface_health_and_route_contracts() -> None:
    schema = _json(SCHEMA)
    defs = schema["$defs"]
    row = defs["audio_surface_row"]
    route_result = defs["route_result"]

    assert set(schema["x-required_audio_surface_ids"]) == REQUIRED_AUDIO_SURFACE_IDS
    assert set(schema["x-required_health_states"]) == REQUIRED_AUDIO_HEALTH_STATES
    assert set(schema["x-route_result_required_fields"]) == set(ROUTE_RESULT_REQUIRED_FIELDS)

    assert set(route_result["required"]) == set(ROUTE_RESULT_REQUIRED_FIELDS)
    assert route_result["properties"]["witness_class"]["$ref"] == "#/$defs/witness_class_id"
    assert row["properties"]["public_claim_allowed"]["const"] is False
    assert set(row["properties"]["semantic_destination"]["enum"]) >= {
        "broadcast_public",
        "private_assistant",
        "private_notification",
        "programme_audio",
        "caption_source",
        "l12_capture",
        "mpc_private_monitor",
        "broadcast_egress",
        "broadcast_health",
        "no_private_leak",
    }


def test_schema_rejects_raw_high_level_target_implementation_truth() -> None:
    schema = _json(SCHEMA)
    binding = schema["$defs"]["concrete_target_binding"]["properties"]
    witness = schema["$defs"]["witness_class"]["properties"]
    policy = schema["properties"]["fail_closed_policy"]["properties"]

    assert binding["raw_high_level_target_assumption"]["const"] is False
    assert witness["raw_target_assumptions_allowed"]["const"] is False
    assert policy["raw_high_level_targets_are_implementation_truth"]["const"] is False
    assert policy["fixtures_are_runtime_truth"]["const"] is False
    assert policy["missing_witness_allows_public_claim"]["const"] is False
    assert policy["private_audio_may_fallback_to_public"]["const"] is False
    assert policy["no_leak_can_be_inferred_from_route_name"]["const"] is False

    fixtures = _json(FIXTURES)
    bad = json.loads(json.dumps(fixtures))
    bad["audio_surface_rows"][0]["route_result"]["concrete_target_binding"][
        "raw_high_level_target_assumption"
    ] = True

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_fixture_catalog_covers_required_audio_surfaces_and_health_states() -> None:
    fixtures = _json(FIXTURES)
    rows = cast("list[dict[str, Any]]", fixtures["audio_surface_rows"])
    health_fixtures = cast("list[dict[str, Any]]", fixtures["health_state_fixtures"])

    assert {row["surface_id"] for row in rows} == REQUIRED_AUDIO_SURFACE_IDS
    assert set(fixtures["health_states"]) == REQUIRED_AUDIO_HEALTH_STATES
    assert {health["state"] for health in health_fixtures} == REQUIRED_AUDIO_HEALTH_STATES

    for row in rows:
        route = row["route_result"]
        assert route["semantic_destination"] == row["semantic_destination"]
        assert route["concrete_target_binding"]["raw_high_level_target_assumption"] is False
        assert row["public_claim_allowed"] is False
        assert row["blocked_reasons"]


def test_fixture_witness_classes_keep_public_private_and_no_leak_distinct() -> None:
    fixtures = _json(FIXTURES)
    witnesses = {
        witness["witness_class"]: witness
        for witness in cast("list[dict[str, Any]]", fixtures["witness_classes"])
    }

    for witness_id, scope in EXPECTED_WITNESSES.items():
        assert witnesses[witness_id]["privacy_scope"] == scope
        assert witnesses[witness_id]["raw_target_assumptions_allowed"] is False

    assert witnesses["public_audio_witness"] != witnesses["private_audio_witness"]
    assert witnesses["public_audio_witness"] != witnesses["no_leak_audio_witness"]
    assert witnesses["private_audio_witness"] != witnesses["no_leak_audio_witness"]


def test_audio_fixture_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
