"""Schema contract tests for Director World Surface snapshot fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.director_world_surface_snapshot import (
    DIRECTOR_MOVE_ROW_REQUIRED_FIELDS,
    DIRECTOR_SNAPSHOT_REQUIRED_FIELDS,
    REQUIRED_MOVE_STATUSES,
    REQUIRED_SURFACE_FAMILIES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "director-world-surface-snapshot.schema.json"
FIXTURES = REPO_ROOT / "config" / "director-world-surface-snapshot-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = cast("dict[str, Any]", payload["snapshots"][0])
    rows: list[dict[str, Any]] = []
    for bucket in (
        "available_moves",
        "blocked_moves",
        "dry_run_moves",
        "private_only_moves",
        "fallback_moves",
    ):
        rows.extend(cast("list[dict[str, Any]]", snapshot[bucket]))
    return rows


def test_director_world_surface_snapshot_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "DirectorWorldSurfaceSnapshotFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/director-world-surface-snapshot.schema.json"


def test_schema_pins_snapshot_move_row_and_required_field_contracts() -> None:
    schema = _json(SCHEMA)
    defs = cast("dict[str, Any]", schema["$defs"])
    move_row = cast("dict[str, Any]", defs["move_row"])
    snapshot = cast("dict[str, Any]", defs["director_snapshot"])

    assert set(schema["x-required_move_statuses"]) == REQUIRED_MOVE_STATUSES
    assert set(schema["x-required_surface_families"]) == REQUIRED_SURFACE_FAMILIES
    assert set(schema["x-director_move_row_required_fields"]) == set(
        DIRECTOR_MOVE_ROW_REQUIRED_FIELDS
    )
    assert set(schema["x-director_snapshot_required_fields"]) == set(
        DIRECTOR_SNAPSHOT_REQUIRED_FIELDS
    )
    assert set(move_row["required"]) == set(DIRECTOR_MOVE_ROW_REQUIRED_FIELDS)
    assert set(snapshot["required"]) == set(DIRECTOR_SNAPSHOT_REQUIRED_FIELDS)
    assert cast("dict[str, Any]", move_row["properties"])["status"]["$ref"] == (
        "#/$defs/move_status"
    )
    assert cast("dict[str, Any]", move_row["properties"])["surface_family"]["$ref"] == (
        "#/$defs/surface_family"
    )


def test_fixture_catalog_covers_statuses_families_and_static_prompt_hint() -> None:
    fixtures = _json(FIXTURES)
    rows = _rows(fixtures)
    static_hint = next(row for row in rows if row["generated_from"] == ["static_prompt_hint"])

    assert set(fixtures["move_statuses"]) == REQUIRED_MOVE_STATUSES
    assert set(fixtures["surface_families"]) >= REQUIRED_SURFACE_FAMILIES
    assert {row["status"] for row in rows} == REQUIRED_MOVE_STATUSES
    assert {row["surface_family"] for row in rows} >= REQUIRED_SURFACE_FAMILIES
    assert all(value is False for value in static_hint["availability"].values())
    assert static_hint["public_claim_allowed"] is False
    assert static_hint["claim_posture"]["public_live_claim_allowed"] is False


def test_schema_rejects_static_prompt_hint_availability() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(row for row in _rows(bad) if row["generated_from"] == ["static_prompt_hint"])
    row["availability"]["available_to_attempt"] = True

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


@pytest.mark.parametrize("status", ["stale", "blocked", "unavailable", "blocked_hardware_no_op"])
def test_schema_rejects_public_claimability_on_non_public_statuses(status: str) -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(row for row in _rows(bad) if row["status"] == status)
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


def test_director_snapshot_fixture_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
