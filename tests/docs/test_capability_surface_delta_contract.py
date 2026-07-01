from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "capability-surface-delta.schema.json"
FIXTURES = REPO_ROOT / "config" / "capability-surface-delta-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_capability_surface_delta_schema_validates_fixtures() -> None:
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/capability-surface-delta.schema.json"


def test_schema_pins_delta_kind_freshness_and_action_vocabularies() -> None:
    defs = _json(SCHEMA)["$defs"]

    assert "new_capability" in defs["delta_kind"]["enum"]
    assert "stale_determination" in defs["delta_kind"]["enum"]
    assert "delta_pending" in defs["freshness_state"]["enum"]
    assert "refresh_receipt" in defs["required_intake_action"]["enum"]
    assert "money_rail" in defs["surface_kind"]["enum"]


def test_schema_rejects_new_capability_without_delta_pending_state() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(delta for delta in bad["deltas"] if delta["delta_kind"] == "new_capability")
    row["freshness_state"] = "fresh"

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_stale_determination_without_refresh_action() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(delta for delta in bad["deltas"] if delta["delta_kind"] == "stale_determination")
    row["required_intake_action"] = "mint_intake_item"

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_schema_rejects_actionable_delta_without_remediation_ref() -> None:
    fixtures = _json(FIXTURES)
    bad = deepcopy(fixtures)
    row = next(delta for delta in bad["deltas"] if delta["delta_kind"] == "new_capability")
    row["remediation_ref"] = None

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)
