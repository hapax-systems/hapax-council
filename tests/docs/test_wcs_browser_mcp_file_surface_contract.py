"""Schema contract tests for browser/MCP/file WCS read-surface fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest

from shared.wcs_browser_mcp_file_surface import (
    FAIL_CLOSED_POLICY,
    REQUIRED_AVAILABILITY_STATES,
    REQUIRED_SURFACE_KINDS,
    REQUIRED_WITNESS_KINDS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "wcs-browser-mcp-file-surface.schema.json"
FIXTURES = REPO_ROOT / "config" / "wcs-browser-mcp-file-surface-fixtures.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_wcs_browser_mcp_file_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "WCSBrowserMCPFileSurface"
    assert fixtures["schema_version"] == 1
    assert fixtures["$schema"] == "../schemas/wcs-browser-mcp-file-surface.schema.json"


def test_schema_pins_required_surface_states_and_witnesses() -> None:
    schema = _json(SCHEMA)

    assert set(schema["x-required_surface_kinds"]) == REQUIRED_SURFACE_KINDS
    assert set(schema["x-required_availability_states"]) == REQUIRED_AVAILABILITY_STATES
    assert set(schema["x-required_witness_kinds"]) == REQUIRED_WITNESS_KINDS

    defs = schema["$defs"]
    assert set(defs["SourceSurfaceKind"]["enum"]) >= REQUIRED_SURFACE_KINDS
    assert set(defs["SourceAvailabilityState"]["enum"]) >= REQUIRED_AVAILABILITY_STATES
    assert set(defs["SourceWitnessKind"]["enum"]) >= REQUIRED_WITNESS_KINDS


def test_fixture_catalog_covers_required_kinds_states_and_fail_closed_policy() -> None:
    fixtures = _json(FIXTURES)
    surfaces = cast("list[dict[str, Any]]", fixtures["surfaces"])
    probes = cast("list[dict[str, Any]]", fixtures["witness_probes"])

    assert {surface["surface_kind"] for surface in surfaces} >= REQUIRED_SURFACE_KINDS
    assert {surface["availability_state"] for surface in surfaces} >= REQUIRED_AVAILABILITY_STATES
    assert {probe["witness_kind"] for probe in probes} >= REQUIRED_WITNESS_KINDS
    assert fixtures["fail_closed_policy"] == FAIL_CLOSED_POLICY


def test_schema_requires_source_refs_and_witness_probe_ids() -> None:
    fixtures = _json(FIXTURES)
    bad = json.loads(json.dumps(fixtures))
    bad["surfaces"][0]["source_refs"] = []

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)

    bad = json.loads(json.dumps(fixtures))
    bad["surfaces"][0]["witness_probe_ids"] = []

    with pytest.raises(jsonschema.ValidationError):
        _validator().validate(bad)


def test_fixture_sources_avoid_local_absolute_paths() -> None:
    fixture_text = FIXTURES.read_text(encoding="utf-8")
    schema_text = SCHEMA.read_text(encoding="utf-8")

    assert "/home/hapax/" not in fixture_text
    assert "/home/hapax/" not in schema_text
