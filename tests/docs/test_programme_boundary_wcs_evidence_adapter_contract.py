"""Schema contract tests for programme boundary WCS/evidence adapter fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "programme-boundary-wcs-evidence-adapter.schema.json"
FIXTURES = REPO_ROOT / "config" / "programme-boundary-wcs-evidence-adapter.json"


def _json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _validator() -> jsonschema.Draft202012Validator:
    schema = _json(SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_schema_validates_fixture_payload() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)

    _validator().validate(fixtures)

    assert schema["title"] == "ProgrammeBoundaryWcsEvidenceAdapterFixtures"
    assert fixtures["schema_version"] == 1
    assert fixtures["schema_ref"] == "schemas/programme-boundary-wcs-evidence-adapter.schema.json"


def test_schema_pins_adapter_output_ref_fields_and_consumers() -> None:
    schema = _json(SCHEMA)

    assert set(schema["x-adapter_output_required_ref_fields"]) >= {
        "wcs_snapshot_refs",
        "wcs_surface_refs",
        "evidence_refs",
        "evidence_envelope_refs",
        "grounding_gate_refs",
        "outcome_refs",
        "refusal_or_correction_refs",
    }
    assert schema["x-downstream_consumers"] == [
        "format_public_event_adapter",
        "content_programme_feedback_ledger",
    ]


def test_fixture_catalog_covers_required_boundary_cases() -> None:
    fixtures = _json(FIXTURES)
    fixture_cases = {fixture["run_fixture_case"] for fixture in fixtures["fixtures"]}
    boundary_types = {fixture["boundary"]["boundary_type"] for fixture in fixtures["fixtures"]}

    assert set(fixtures["required_fixture_cases"]) == {
        "public_safe_evidence_audit",
        "conversion_held_run",
        "world_surface_blocked_run",
        "refusal_run",
        "correction_run",
    }
    assert fixture_cases >= set(fixtures["required_fixture_cases"])
    assert {"refusal.issued", "correction.made"} <= boundary_types


def test_public_fail_closed_policy_constants_are_non_permissive() -> None:
    schema = _json(SCHEMA)
    fixtures = _json(FIXTURES)
    policy_schema = schema["properties"]["fail_closed_policy"]["properties"]

    for key, value in fixtures["fail_closed_policy"].items():
        assert value is False
        assert policy_schema[key]["const"] is False

    assert "research_vehicle_public_event_missing" in schema["x-public_fail_closed_reasons"]
    assert "wcs_snapshot_ref_missing" in schema["x-public_fail_closed_reasons"]
    assert "capability_outcome_ref_missing" in schema["x-public_fail_closed_reasons"]


def test_boundary_fixture_keeps_gate_and_public_mapping_explicit() -> None:
    fixtures = _json(FIXTURES)

    for fixture in fixtures["fixtures"]:
        boundary = fixture["boundary"]
        gate = boundary["no_expert_system_gate"]
        mapping = boundary["public_event_mapping"]

        assert "gate_ref" in gate
        assert "gate_state" in gate
        assert "claim_allowed" in gate
        assert "public_claim_allowed" in gate
        assert "unavailable_reasons" in mapping
        assert "fallback_action" in mapping


def test_schema_and_fixtures_avoid_local_absolute_paths() -> None:
    assert "/home/hapax/" not in SCHEMA.read_text(encoding="utf-8")
    assert "/home/hapax/" not in FIXTURES.read_text(encoding="utf-8")
